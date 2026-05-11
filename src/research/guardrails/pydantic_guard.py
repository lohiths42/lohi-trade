"""Framework-light default ``Guardrail_Layer`` implementation.

:class:`PydanticGuardrail` loads the versioned regex ruleset at
``src/research/guardrails/rules/v1.yaml`` (Task 10.3), compiles every
pattern once, and applies them in order on both the input phase
(pre-Sub_Agent) and the output phase (post-Sub_Agent). The default
path is pure Python + ``re`` so the latency budget from design §3.6
(p95 ≤ 50 ms overhead) holds trivially.

Rule semantics
--------------
Each rule has a ``phase`` (``"input"`` | ``"output"``) and an
``action``:

* ``refuse`` — return the original content and a
  :class:`GuardrailDecision` with ``action="refuse"``. Callers are
  expected to short-circuit the pipeline on any refuse decision and
  surface the :data:`~src.research.guardrails.refusal_policy.REFUSAL_POLICY_BLOCK`
  to the user.
* ``modify`` — substitute every match with the rule's ``replacement``
  (defaults to an empty string if absent) and emit a decision with
  ``action="modify"`` recording the pre/post content. Used for PII
  redaction (PII-001) and tool-call stripping (TA-001).
* ``allow`` — currently unused; included for future rules that want
  to explicitly whitelist content without changing it.

Rate limiting
-------------
When a Redis client is injected, :meth:`check_input` increments a
per-user, per-minute counter at
``research:gr:rl:{user_id}:{window_epoch}`` (see
:data:`~src.research.constants.GUARDRAIL_RATE_LIMIT_KEY_TEMPLATE`). If
the counter exceeds the configured ``requests_per_minute`` threshold,
the input is refused with rule id ``RL-001`` even when no content rule
matched. When the client is ``None`` — the default in unit tests —
rate-limit checks are skipped entirely (Req 16.5).

Satisfies:
    - Req 16.1 — every user prompt routes through this layer.
    - Req 16.2 — versioned regex ruleset drives jailbreak detection.
    - Req 16.5 — per-user rate limit via Redis counters.
    - Req 16.7 — framework-light Pydantic-validated default.
    - Req 16.9 — output-side stripping of unauthorised tool/function
      call tokens.
    - Req 16.10 — output-side PII redaction.

Design references:
    - §3.6 (Guardrail_Layer contract, ruleset layout, latency budget)
    - §10.1 (Default framework-light design)
    - §10.3 (Jailbreak ruleset v1)
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

import yaml
from pydantic import BaseModel, Field

from src.research.constants import GUARDRAIL_RATE_LIMIT_KEY_TEMPLATE

__all__ = [
    "Guardrail",
    "GuardrailDecision",
    "PydanticGuardrail",
]


# Default location of the v1 ruleset. Absolute string path so operators
# can override via constructor arg without wrestling with relative-
# cwd behaviour on different deployment topologies.
_DEFAULT_RULESET_PATH = "src/research/guardrails/rules/v1.yaml"

# Rate-limit window size in seconds. One-minute windows match the
# ``requests_per_minute`` constructor arg naming and keep counter keys
# short-lived so missed-expire bugs cannot inflate counters across
# windows.
_RATE_LIMIT_WINDOW_SECONDS = 60

# Rule id used by the rate-limit refusal path. Does not appear in
# ``v1.yaml`` because it is a code-level rule, not a content rule —
# keeping it distinct makes log filtering + dashboard metrics easier.
_RATE_LIMIT_RULE_ID = "RL-001"


class GuardrailDecision(BaseModel):
    """One guardrail decision — matches design §3.6 contract exactly.

    Emitted per matched rule (or per refused request in the case of
    rate limiting). A single ``check_input`` / ``check_output`` call
    may return zero, one, or several decisions depending on how many
    rules fired on the input.
    """

    phase: Literal["input", "output"]
    rule_id: str
    action: Literal["allow", "modify", "refuse"]
    reason: str
    content_before: str
    content_after: str | None = Field(
        default=None,
        description="Populated when action == 'modify'; None otherwise.",
    )


@runtime_checkable
class Guardrail(Protocol):
    """Runtime-checkable ``Guardrail_Layer`` contract (design §3.6).

    Implementations return ``(possibly_modified_content, decisions)``.
    On a ``refuse`` decision, the caller MUST short-circuit — the
    returned content is the original input unchanged and surfacing it
    to a downstream Sub_Agent would defeat the guardrail.
    """

    async def check_input(
        self, user_id: UUID, prompt: str,
    ) -> tuple[str, list[GuardrailDecision]]: ...

    async def check_output(
        self, user_id: UUID, text: str,
    ) -> tuple[str, list[GuardrailDecision]]: ...


class _CompiledRule:
    """Internal compiled form of a YAML rule row.

    The compiled form holds pre-parsed :class:`re.Pattern` objects so
    the hot path in :meth:`PydanticGuardrail.check_input` /
    :meth:`check_output` is a plain iterator over compiled patterns,
    with no per-call string parsing.
    """

    __slots__ = ("action", "id", "name", "patterns", "phase", "replacement")

    def __init__(
        self,
        *,
        id: str,
        name: str,
        phase: Literal["input", "output"],
        action: Literal["allow", "modify", "refuse"],
        patterns: list[re.Pattern[str]],
        replacement: str,
    ) -> None:
        self.id = id
        self.name = name
        self.phase = phase
        self.action = action
        self.patterns = patterns
        self.replacement = replacement


class PydanticGuardrail:
    """Default Pydantic-validated guardrail implementation.

    Parameters
    ----------
    ruleset_path:
        Filesystem path to the YAML ruleset. Defaults to the v1
        ruleset shipped under ``src/research/guardrails/rules/``.
    redis_client:
        Optional ``redis.asyncio.Redis`` instance used for the per-
        user rate-limit counter (Req 16.5). When ``None`` the rate
        limit is disabled — the constructor does not import the
        redis package so tests without a Redis server can still
        exercise the content rules.
    requests_per_minute:
        Per-user-per-window threshold for the rate limit. One-minute
        windows are anchored to the current wall-clock minute so
        every user gets a full budget each minute regardless of when
        the guardrail is instantiated.

    """

    def __init__(
        self,
        *,
        ruleset_path: str = _DEFAULT_RULESET_PATH,
        redis_client: Any | None = None,
        requests_per_minute: int = 30,
    ) -> None:
        self._redis = redis_client
        self._requests_per_minute = int(requests_per_minute)
        self._rules = self._load_ruleset(ruleset_path)

    # ---------------------------------------------------------------- #
    # Public Guardrail contract                                        #
    # ---------------------------------------------------------------- #

    async def check_input(
        self, user_id: UUID, prompt: str,
    ) -> tuple[str, list[GuardrailDecision]]:
        """Run input-phase rules + rate limit against ``prompt``.

        Rate limit fires first: if the user is over budget, return a
        single refuse decision and skip content matching. Otherwise,
        walk input-phase rules; a ``refuse`` action short-circuits
        (leaving the prompt unchanged, per contract), and ``modify``
        actions accumulate with the substituted content carried
        forward.
        """
        decisions: list[GuardrailDecision] = []

        # Rate limit first — a user who has just been flooding the
        # system should not even incur the regex work.
        rate_decision = await self._check_rate_limit(user_id, prompt)
        if rate_decision is not None:
            decisions.append(rate_decision)
            return prompt, decisions

        current = prompt
        for rule in self._rules:
            if rule.phase != "input":
                continue
            if not self._any_pattern_matches(rule, current):
                continue
            if rule.action == "refuse":
                decisions.append(
                    GuardrailDecision(
                        phase="input",
                        rule_id=rule.id,
                        action="refuse",
                        reason=rule.name,
                        content_before=current,
                        content_after=None,
                    ),
                )
                # Short-circuit — caller must not forward to sub-agents.
                return prompt, decisions
            if rule.action == "modify":
                modified = self._apply_modify(rule, current)
                decisions.append(
                    GuardrailDecision(
                        phase="input",
                        rule_id=rule.id,
                        action="modify",
                        reason=rule.name,
                        content_before=current,
                        content_after=modified,
                    ),
                )
                current = modified
                continue
            # ``allow`` is explicit no-op — decision still recorded so
            # operators can see which rules were consulted.
            decisions.append(
                GuardrailDecision(
                    phase="input",
                    rule_id=rule.id,
                    action="allow",
                    reason=rule.name,
                    content_before=current,
                    content_after=None,
                ),
            )

        return current, decisions

    async def check_output(
        self, user_id: UUID, text: str,
    ) -> tuple[str, list[GuardrailDecision]]:
        """Run output-phase rules against Sub_Agent-generated ``text``.

        Output rules are primarily ``modify`` (PII redaction,
        tool-call stripping). A ``refuse`` on output is permitted by
        the contract — if it fires, the caller should replace the
        text with the Refusal_Policy block.
        """
        del user_id  # retained for interface symmetry; not used yet
        decisions: list[GuardrailDecision] = []
        current = text

        for rule in self._rules:
            if rule.phase != "output":
                continue
            if not self._any_pattern_matches(rule, current):
                continue
            if rule.action == "refuse":
                decisions.append(
                    GuardrailDecision(
                        phase="output",
                        rule_id=rule.id,
                        action="refuse",
                        reason=rule.name,
                        content_before=current,
                        content_after=None,
                    ),
                )
                return text, decisions
            if rule.action == "modify":
                modified = self._apply_modify(rule, current)
                decisions.append(
                    GuardrailDecision(
                        phase="output",
                        rule_id=rule.id,
                        action="modify",
                        reason=rule.name,
                        content_before=current,
                        content_after=modified,
                    ),
                )
                current = modified
                continue
            decisions.append(
                GuardrailDecision(
                    phase="output",
                    rule_id=rule.id,
                    action="allow",
                    reason=rule.name,
                    content_before=current,
                    content_after=None,
                ),
            )

        return current, decisions

    # ---------------------------------------------------------------- #
    # Internals                                                        #
    # ---------------------------------------------------------------- #

    @staticmethod
    def _load_ruleset(path: str) -> list[_CompiledRule]:
        """Parse YAML + compile every regex. Raises on malformed input."""
        ruleset_path = Path(path)
        if not ruleset_path.is_file():
            raise FileNotFoundError(f"Guardrail ruleset not found: {ruleset_path}")
        with ruleset_path.open("r", encoding="utf-8") as fp:
            data = yaml.safe_load(fp) or {}
        rules_raw = data.get("rules") or []
        compiled: list[_CompiledRule] = []
        for row in rules_raw:
            rule_id = str(row["id"])
            name = str(row["name"])
            phase = row["phase"]
            action = row["action"]
            if phase not in ("input", "output"):
                raise ValueError(f"Rule {rule_id}: invalid phase {phase!r}")
            if action not in ("allow", "modify", "refuse"):
                raise ValueError(f"Rule {rule_id}: invalid action {action!r}")
            patterns_raw = row.get("patterns") or []
            if not patterns_raw:
                raise ValueError(f"Rule {rule_id}: at least one pattern required")
            patterns = [re.compile(p) for p in patterns_raw]
            replacement = str(row.get("replacement", ""))
            compiled.append(
                _CompiledRule(
                    id=rule_id,
                    name=name,
                    phase=phase,
                    action=action,
                    patterns=patterns,
                    replacement=replacement,
                ),
            )
        return compiled

    @staticmethod
    def _any_pattern_matches(rule: _CompiledRule, text: str) -> bool:
        return any(p.search(text) is not None for p in rule.patterns)

    @staticmethod
    def _apply_modify(rule: _CompiledRule, text: str) -> str:
        modified = text
        for pattern in rule.patterns:
            modified = pattern.sub(rule.replacement, modified)
        return modified

    async def _check_rate_limit(
        self, user_id: UUID, prompt: str,
    ) -> GuardrailDecision | None:
        """Per-user per-minute counter. Returns a refuse decision on overrun."""
        if self._redis is None:
            return None

        window_epoch = int(time.time()) // _RATE_LIMIT_WINDOW_SECONDS
        key = GUARDRAIL_RATE_LIMIT_KEY_TEMPLATE.format(
            user_id=str(user_id), window_epoch=window_epoch,
        )

        # INCR returns the post-increment value. Expire is set on the
        # first call only (via EXPIRE, which is a no-op on subsequent
        # hits in the same window thanks to the Redis semantics).
        try:
            count = await self._redis.incr(key)
            # Best-effort TTL set — if EXPIRE fails we still have a
            # correct counter for the current window.
            try:
                await self._redis.expire(key, _RATE_LIMIT_WINDOW_SECONDS)
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001 - Redis outage is non-fatal
            # Fail-open on Redis errors: content rules still run, and
            # the outage is visible to operators through the Redis
            # client's own instrumentation.
            return None

        if count > self._requests_per_minute:
            return GuardrailDecision(
                phase="input",
                rule_id=_RATE_LIMIT_RULE_ID,
                action="refuse",
                reason="rate_limit_exceeded",
                content_before=prompt,
                content_after=None,
            )
        return None
