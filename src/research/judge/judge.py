"""Judge_LLM invocation + ``JudgeReport`` schema (design §3.7, §11.1).

Scores a ``Research_Brief`` for groundedness, citation coverage,
contradiction, and off-policy content. Consumed by the Orchestrator
immediately after the Report_Synthesizer produces a brief (design
§3.5). On failure the Orchestrator runs a single re-synthesis loop
(design §11.2, Req 16.18) — this module only owns the per-invocation
scoring; the loop control lives upstream.

Contract
--------
:func:`invoke` takes the synthesised brief, the cited chunks, and the
deterministic numeric-validator findings; it formats them into the
versioned ``prompts/v1/judge.md`` template, calls the role-specific
``LLMProvider`` resolved via ``research.providers.judge.*`` (Req
16.20–16.21), parses the JSON response, and returns a fully-populated
:class:`JudgeReport`. Parse failures and upstream errors are caught:
the function returns a :class:`JudgeReport` with
``safe_to_display=False`` so the Orchestrator can react uniformly
(design §11.2 fail path) rather than crashing the run.

Why not cover the re-synthesis loop here
----------------------------------------
Design §11.2 describes re-synthesis as an **Orchestrator** concern:
the judge is invoked, the Orchestrator inspects ``safe_to_display``
and ``groundedness_score.values()``, decides whether to feed
``unsupported_claims`` back into the Report_Synthesizer, and bumps
``retry_count``. Keeping that logic outside this module means the
same :func:`invoke` implementation serves both the first pass
(``retry_count=0``) and the re-synthesis pass (``retry_count=1``) —
the Orchestrator passes the running count in as a parameter.

Satisfies
---------
* Req 16.12 — Judge_LLM scores every ``Research_Brief`` after synthesis.
* Req 16.13 — groundedness assessed against cited chunks.
* Req 16.14 — citation coverage: every non-boilerplate sentence cited.
* Req 16.15 — contradictions between claims flagged.
* Req 16.16 — off-policy findings emitted.
* Req 16.17 — structured ``JudgeReport`` with per-section score,
  ``unsupported_claims``, ``safe_to_display``.
* Req 16.20 — Judge role sourced from ``research.providers.judge.*``.
* Req 16.21 — default provider is NVIDIA NIM (applied by the registry,
  not this module — this module just consumes the factory output).

Design references
-----------------
* §3.7 — ``JudgeReport`` schema definition.
* §11.1 — Judge prompt structure and scoring rules.
* §11.2 — single re-synthesis loop (Orchestrator-owned).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Iterable, Mapping, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.research.guardrails.refusal_policy import REFUSAL_POLICY_BLOCK
from src.research.prompts.loader import load_prompt, render
from src.research.providers.base import LLMParams, LLMProvider, Message
from src.research.providers.registry import get_llm
from src.research.validators.types import UnsupportedClaim

__all__ = ["JudgeReport", "UnsupportedClaim", "invoke"]


# --------------------------------------------------------------------------- #
# Defaults                                                                    #
# --------------------------------------------------------------------------- #

# Canonical brief section list (design §3.5 / Req 1.5). Kept in sync
# with ``numeric_validator._BRIEF_SECTION_NAMES`` — if the two lists
# ever drift, the numeric findings will cite section names that the
# judge cannot score. Duplicated (rather than imported) to avoid a
# validators → judge import cycle; the canonical owner lands in
# Task 13.8 (the ``ResearchBrief`` Pydantic model) and both modules
# will read from there at that point.
_BRIEF_SECTION_NAMES: tuple[str, ...] = (
    "summary",
    "thesis",
    "risks",
    "financial_highlights",
    "management_commentary",
    "technical_view",
    "peers",
    "macro_context",
)

# Default exact-string used by the ``{{REFUSAL_NO_CONTEXT}}`` slot in
# every Sub_Agent template (design §3.9). The Judge never issues this
# refusal itself — it is part of the shared prompt skeleton — but the
# template requires the placeholder, so we substitute the canonical
# string. Centralised here rather than imported from a refusal module
# because no such module exists yet (design §10.1 enumerates the
# wording in the ``REFUSAL_POLICY_BLOCK``; the no-context refusal is
# emitted by Sub_Agents, not by a shared helper).
_REFUSAL_NO_CONTEXT: str = "INSUFFICIENT_EVIDENCE: no context available."

# Temperature used when calling the Judge. A low temperature is
# appropriate because we want deterministic JSON output; callers can
# override via the ``llm_config`` passed to :func:`invoke` (see the
# ``LLMParams`` construction in :func:`_judge_params`).
_DEFAULT_TEMPERATURE: float = 0.0

# Bound on generated tokens. The Judge response is a small JSON
# object; 2048 tokens is ample for every section + claim list we
# expect and matches the default in ``research.providers.judge.*``
# config (design §7.1).
_DEFAULT_MAX_TOKENS: int = 2048


# --------------------------------------------------------------------------- #
# Duck-typed inputs                                                           #
# --------------------------------------------------------------------------- #


@runtime_checkable
class _ChunkLike(Protocol):
    """Minimal duck-typed chunk — ``.chunk_id`` and ``.text`` are read.

    In production the Orchestrator passes ``ChunkRecord`` instances
    (:mod:`src.research.providers.base`) or the ``.chunk`` field of
    each ``ChunkHit``. Tests pass ``SimpleNamespace`` or a small
    dataclass. Only the two attributes below are read; the protocol
    keeps the judge from taking a hard dependency on a specific
    Pydantic model and keeps unit tests mock-free.
    """

    chunk_id: str
    text: str


# --------------------------------------------------------------------------- #
# JudgeReport                                                                 #
# --------------------------------------------------------------------------- #


class JudgeReport(BaseModel):
    """Structured output of a single Judge_LLM invocation (design §3.7).

    The shape is exactly as specified in design §3.7 with one
    pragmatic addition — ``elapsed_ms`` and ``model_id`` — so the
    Orchestrator can write the provenance row without re-measuring.
    Those two fields are defaulted so every call site that only cares
    about the scoring payload (tests, the offline rule-based fallback
    in Task 12.3) can omit them.

    Attributes
    ----------
    run_id:
        Research_Run this judgement belongs to. The Orchestrator
        supplies it; this module passes it through verbatim so a
        judge output is never orphaned from its run.
    groundedness_score:
        Per-section score in ``[0, 1]``. Every section named in the
        brief (design §3.5) SHOULD have an entry; missing sections
        are treated by :meth:`min_score` as score ``0.0`` so the
        Orchestrator's re-synthesis trigger is conservative.
    unsupported_claims:
        Every claim the Judge (or the numeric validator feeding it)
        could not ground. Re-synthesis feeds this list back into the
        Report_Synthesizer (design §11.2, Req 16.18). Uses the shared
        :class:`UnsupportedClaim` type so numeric-validator findings
        and Judge findings are wire-compatible.
    safe_to_display:
        Orchestrator-visible flag: ``False`` means show the brief
        with redactions and the refusal banner (design workflow C);
        ``True`` means the brief is ready for the user. The Judge
        sets this ``False`` when any off-policy finding is non-empty
        or any groundedness score falls below the operator-configured
        minimum (``research.judge.min_score``, default 0.7; Req 16.18).
    contradiction_pairs:
        Pairs of claim texts the Judge flagged as internally
        contradictory (Req 16.15). Stored as two-string tuples so
        downstream code is not forced to resolve offsets.
    off_policy_findings:
        Short phrases the Judge identified as violating the
        ``Refusal_Policy`` (Req 16.16). An empty list is the healthy
        case; any entry implies ``safe_to_display=False``.
    retry_count:
        Number of re-synthesis passes that have run so far. The
        Orchestrator manages this counter (design §11.2); the Judge
        simply echoes it back so downstream consumers don't need a
        separate source of truth.
    elapsed_ms:
        Wall time for this judge call. Defaults to ``0`` when the
        caller does not care (rule-based fallback, property tests).
    model_id:
        ``provider/model`` string identifying the Judge's LLM for
        the provenance row. Defaults to ``""`` for the same reason
        as ``elapsed_ms``.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: UUID = Field(..., description="Research_Run this report belongs to.")
    groundedness_score: dict[str, float] = Field(
        default_factory=dict,
        description="Per-section score in [0, 1].",
    )
    unsupported_claims: list[UnsupportedClaim] = Field(
        default_factory=list,
        description="Claims the Judge could not ground against cited chunks.",
    )
    safe_to_display: bool = Field(
        ...,
        description="True iff the brief is safe to surface to the user.",
    )
    contradiction_pairs: list[tuple[str, str]] = Field(
        default_factory=list,
        description="Pairs of internally-contradictory claim texts (Req 16.15).",
    )
    off_policy_findings: list[str] = Field(
        default_factory=list,
        description="Short phrases flagged as violating the Refusal_Policy.",
    )
    retry_count: int = Field(
        default=0,
        ge=0,
        description="Re-synthesis pass counter (Orchestrator-managed).",
    )
    elapsed_ms: int = Field(
        default=0,
        ge=0,
        description="Wall time of this judge call in milliseconds.",
    )
    model_id: str = Field(
        default="",
        description="'provider/model' identifier for the provenance row.",
    )

    # ------------------------------------------------------------------ #
    # Convenience                                                        #
    # ------------------------------------------------------------------ #

    def min_score(self) -> float:
        """Return the minimum per-section score, or ``0.0`` if empty.

        The Orchestrator's re-synthesis trigger (design §11.2,
        Req 16.18) compares this value against
        ``research.judge.min_score``. Defaulting to ``0.0`` when no
        sections were scored means an empty ``groundedness_score``
        always triggers re-synthesis — which is the conservative
        behaviour we want when the Judge produced no scores.
        """
        if not self.groundedness_score:
            return 0.0
        return min(self.groundedness_score.values())


# --------------------------------------------------------------------------- #
# Public invoke                                                               #
# --------------------------------------------------------------------------- #


async def invoke(
    *,
    run_id: UUID,
    brief: "Mapping[str, str] | object",
    chunks: Iterable[_ChunkLike],
    numeric_findings: Iterable[UnsupportedClaim] = (),
    llm_config: Mapping[str, Any] | None = None,
    min_score: float = 0.7,
    retry_count: int = 0,
    llm: LLMProvider | None = None,
    user_prompt: str = "Evaluate the Research_Brief for groundedness, "
    "citation coverage, contradictions, and off-policy content.",
) -> JudgeReport:
    """Invoke the Judge_LLM and return a :class:`JudgeReport`.

    The function is fail-soft: any error — unreachable provider,
    malformed JSON, Pydantic validation failure — yields a
    :class:`JudgeReport` with ``safe_to_display=False`` so the
    Orchestrator's re-synthesis path can engage without a bespoke
    error handler. Every such "fallback" report also carries a
    single :class:`UnsupportedClaim` with ``reason="off_policy"``
    and ``claim_text`` set to a short diagnostic so operators
    inspecting ``research_judge_reports`` can see *why* the Judge
    short-circuited.

    Parameters
    ----------
    run_id:
        The Research_Run this judgement belongs to. Passed through
        to :attr:`JudgeReport.run_id`.
    brief:
        Either a ``dict[str, str]`` mapping section name to
        ``content_md`` or any object exposing the canonical
        ``ResearchBrief`` section attributes (``summary``, ``thesis``,
        …). Duck-typed so Task 13.8 can hand the full Pydantic
        ``ResearchBrief`` in unchanged.
    chunks:
        Iterable of chunk-like objects exposing ``.chunk_id`` and
        ``.text``. In production this is ``[hit.chunk for hit in
        retrieved_hits]``; in tests it may be a list of
        ``SimpleNamespace`` rows.
    numeric_findings:
        Findings from the deterministic numeric validator (Task 11.1).
        Rendered into the prompt verbatim so the Judge does not have
        to re-derive numeric drift (design §11.1 — the "numeric_validator_findings"
        block). Defaults to an empty tuple when the caller has no
        findings to forward.
    llm_config:
        Flat config block from ``research.providers.judge.*`` —
        forwarded to :func:`get_llm` when ``llm`` is ``None``. When
        both ``llm`` and ``llm_config`` are ``None``, a :class:`ValueError`
        is raised because there is no way to build a Judge.
    min_score:
        Operator-configured minimum score from
        ``research.judge.min_score``. Rendered into the prompt so the
        Judge knows where the ``safe_to_display`` cut-off sits. Also
        used to cross-check the model's ``safe_to_display`` — a model
        that claims ``safe_to_display=True`` but produced a section
        score below ``min_score`` has its flag overridden to ``False``
        (design §11.1: "safe_to_display MUST be false if any
        groundedness_score value is below the operator-configured
        minimum"). Defaults to the design §7.1 default of 0.7.
    retry_count:
        The Orchestrator's running re-synthesis counter; echoed back
        in :attr:`JudgeReport.retry_count`. Defaults to ``0`` for the
        first pass.
    llm:
        Optional pre-built ``LLMProvider``. When supplied it takes
        precedence over ``llm_config`` — this is the test seam the
        unit tests in ``tests/research/test_judge.py`` use to inject
        a ``FakeLLMProvider``. Production code passes ``llm_config``
        and lets the registry resolve the provider.
    user_prompt:
        User-visible prompt rendered into the ``{{USER_PROMPT}}``
        slot of the Judge template (design §3.9 skeleton). Defaults
        to a canned instruction that mirrors the Judge's role; the
        Orchestrator may pass the original user question to give
        the Judge more context.

    Returns
    -------
    JudgeReport
        A fully-populated report. ``safe_to_display`` is ``True``
        only when the LLM returned valid JSON, all section scores
        are at or above ``min_score``, and no off-policy findings
        were flagged.

    Raises
    ------
    ValueError
        When neither ``llm`` nor ``llm_config`` is supplied — there
        is no way to build the Judge from an empty contract.
    """
    if llm is None and llm_config is None:
        raise ValueError(
            "judge.invoke() requires either an LLMProvider instance "
            "(`llm=`) or an LLM config block (`llm_config=`); both "
            "were None."
        )

    # --------------------------------------------------------------- #
    # Offline dispatch (Req 16.22, design §11.4)                      #
    # --------------------------------------------------------------- #
    # When ``LOHI_RESEARCH_OFFLINE=true`` the deterministic rule-based
    # judge replaces the LLM-backed judge entirely — no cloud call is
    # made and no provider is even resolved. The rule-based judge
    # returns the same :class:`JudgeReport` shape, so the Orchestrator
    # re-synthesis loop (design §11.2) and the provenance row
    # (``research_judge_reports``) are indistinguishable between the
    # two paths.
    #
    # The import is function-local to dodge the module-load-time
    # circular dependency with :mod:`src.research.judge.rule_based`
    # (which imports :class:`JudgeReport` from this file).
    if os.environ.get("LOHI_RESEARCH_OFFLINE", "").strip().lower() in (
        "true",
        "1",
        "yes",
    ):
        from src.research.judge.rule_based import invoke_rule_based

        return await invoke_rule_based(
            run_id=run_id,
            brief=brief,
            chunks=chunks,
            numeric_findings=numeric_findings,
            min_score=min_score,
            retry_count=retry_count,
        )

    # Build the provider if the caller did not hand one in. The
    # registry applies Req 16.20–16.21 (role-scoped lookup and NVIDIA
    # NIM default), so this module stays free of provider-specific
    # knowledge.
    provider = llm if llm is not None else get_llm(dict(llm_config or {}))

    # Start the stopwatch *after* the provider is built so ``elapsed_ms``
    # reflects Judge latency and not registry-probe time — the probe
    # runs at most once per process (see registry.py's
    # ``_AUTO_RESOLVED_BACKEND``) and would otherwise double-count
    # into the first run's judge latency.
    start = time.perf_counter()

    # Render the prompt. A template-loading failure is a deployment
    # bug we want to surface loudly rather than mask with a safe
    # fallback — the Orchestrator boot path will catch it on the
    # first Research_Run and fail-fast per Req 7.6.
    system_prompt = _render_judge_prompt(
        brief=brief,
        chunks=chunks,
        numeric_findings=numeric_findings,
        min_score=min_score,
        user_prompt=user_prompt,
    )

    messages = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=user_prompt),
    ]

    try:
        completion = await provider.complete(messages, _judge_params(llm_config))
    except Exception as exc:  # pragma: no cover - defensive
        # Any upstream failure — auth, timeout, transport — reduces to
        # "we cannot judge this brief right now". Returning a
        # safe_to_display=False report lets the Orchestrator decide
        # whether to re-synthesise or degrade the quality label,
        # rather than forcing it to bolt on bespoke error handling.
        return _fallback_report(
            run_id=run_id,
            retry_count=retry_count,
            elapsed_ms=int((time.perf_counter() - start) * 1000),
            model_id=_model_id_from_config(llm_config),
            reason=f"provider_error: {type(exc).__name__}: {exc}",
            min_score=min_score,
        )

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    model_id = f"{completion.provider}/{completion.model}"

    # Parse the JSON response into a structured report. Parse
    # failures reduce to safe_to_display=False, same as upstream
    # errors — an LLM that returns invalid JSON cannot have produced
    # a trustworthy judgement, so re-synthesis is the right default.
    parsed = _parse_judge_json(completion.content)
    if parsed is None:
        return _fallback_report(
            run_id=run_id,
            retry_count=retry_count,
            elapsed_ms=elapsed_ms,
            model_id=model_id,
            reason="json_parse_error: Judge returned non-JSON or malformed JSON.",
            min_score=min_score,
        )

    # Build the structured report. Any Pydantic validation failure on
    # the well-formed-but-schema-mismatched JSON (e.g. a model that
    # returns groundedness as a list instead of a dict) also reduces
    # to safe_to_display=False.
    try:
        report = _report_from_parsed(
            parsed,
            run_id=run_id,
            numeric_findings=numeric_findings,
            retry_count=retry_count,
            elapsed_ms=elapsed_ms,
            model_id=model_id,
            min_score=min_score,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        return _fallback_report(
            run_id=run_id,
            retry_count=retry_count,
            elapsed_ms=elapsed_ms,
            model_id=model_id,
            reason=f"schema_error: {type(exc).__name__}: {exc}",
            min_score=min_score,
        )

    _safe_log_judge_call(report=report, min_score=min_score)
    return report


# --------------------------------------------------------------------------- #
# Prompt rendering                                                            #
# --------------------------------------------------------------------------- #


def _render_judge_prompt(
    *,
    brief: "Mapping[str, str] | object",
    chunks: Iterable[_ChunkLike],
    numeric_findings: Iterable[UnsupportedClaim],
    min_score: float,
    user_prompt: str,
) -> str:
    """Render the versioned judge template (``prompts/v1/judge.md``).

    The template exposes four placeholders (see design §3.9 shared
    skeleton): ``{{REFUSAL_NO_CONTEXT}}``, ``{{REFUSAL_POLICY_BLOCK}}``,
    ``{{RETRIEVED_CHUNKS_VERBATIM}}``, ``{{USER_PROMPT}}``. Design
    §11.1 additionally specifies three semantic blocks — ``brief``,
    ``chunks_with_ids``, ``numeric_validator_findings`` — that the
    Judge must see. The actual v1 template packs those blocks into
    the ``{{USER_PROMPT}}`` slot (the template has no dedicated
    placeholder for them) so this function assembles the packed
    payload here and hands it back verbatim in the
    ``{{RETRIEVED_CHUNKS_VERBATIM}}`` slot, keeping the cited chunks
    visible to the model in the canonical fenced-context location.
    """
    prompt = load_prompt("v1", "judge")

    # The ``<|CONTEXT|>`` block carries the cited chunks verbatim
    # (Req 16.23 — chunks passed to the LLM without paraphrase). Each
    # chunk is prefixed with its ``chunk_id`` so the Judge can cite
    # via ``[cite:<chunk_id>]`` (design §3.9 prompt skeleton).
    chunks_block = _format_chunks(chunks)

    # Pack the Judge-specific semantic blocks into the user-prompt
    # slot. The v1 template does not expose dedicated placeholders
    # for these, so we concatenate them in a machine-readable
    # order that the Judge prompt already documents (design §11.1).
    packed_user = _pack_user_prompt(
        brief=brief,
        numeric_findings=numeric_findings,
        min_score=min_score,
        user_prompt=user_prompt,
    )

    return render(
        prompt,
        substitutions={
            "REFUSAL_NO_CONTEXT": _REFUSAL_NO_CONTEXT,
            "REFUSAL_POLICY_BLOCK": REFUSAL_POLICY_BLOCK,
            "RETRIEVED_CHUNKS_VERBATIM": chunks_block,
            "USER_PROMPT": packed_user,
        },
    )


def _format_chunks(chunks: Iterable[_ChunkLike]) -> str:
    """Format chunks as ``# <chunk_id>\\n<text>`` blocks separated by blank lines.

    The ``chunk_id`` prefix lets the Judge cite ``[cite:<chunk_id>]``
    without inventing ids (design §3.9 prompt-injection hardening).
    The blank-line separator is robust to chunks that themselves
    contain newlines.
    """
    blocks: list[str] = []
    for chunk in chunks:
        chunk_id = getattr(chunk, "chunk_id", "") or "<unknown>"
        text = getattr(chunk, "text", "") or ""
        blocks.append(f"# {chunk_id}\n{text}")
    if not blocks:
        return "<no cited chunks>"
    return "\n\n".join(blocks)


def _pack_user_prompt(
    *,
    brief: "Mapping[str, str] | object",
    numeric_findings: Iterable[UnsupportedClaim],
    min_score: float,
    user_prompt: str,
) -> str:
    """Pack the semantic blocks from design §11.1 into the user-prompt slot.

    Produces a plain-text payload with three fenced sections so the
    Judge can address each block in turn. Section order is fixed
    (brief → numeric findings → min_score → the caller's prompt) so
    the template's downstream token positions are stable — an LLM
    that trained on one ordering should not be confused by another.
    """
    brief_sections = _coerce_brief_sections(brief)
    brief_block = _format_brief_sections(brief_sections)

    # Numeric findings are rendered as a compact JSON array. Even
    # when the list is empty we emit ``[]`` so the model sees a
    # valid JSON literal and can parse it verbatim if it wants to.
    findings_block = json.dumps(
        [claim.model_dump() for claim in numeric_findings],
        ensure_ascii=False,
        indent=2,
    )

    return (
        f"<brief>\n{brief_block}\n</brief>\n\n"
        f"<numeric_validator_findings>\n{findings_block}\n</numeric_validator_findings>\n\n"
        f"<min_score>{min_score}</min_score>\n\n"
        f"<caller_prompt>\n{user_prompt}\n</caller_prompt>"
    )


def _format_brief_sections(sections: Mapping[str, str]) -> str:
    """Render ``{section_name: content}`` as fenced blocks for the Judge."""
    if not sections:
        return "<empty brief>"
    parts: list[str] = []
    for name, content in sections.items():
        parts.append(f"## {name}\n{content}")
    return "\n\n".join(parts)


def _coerce_brief_sections(
    brief: "Mapping[str, str] | object",
) -> dict[str, str]:
    """Normalise accepted brief inputs into ``{section_name: content}``.

    Mirrors :func:`src.research.validators.numeric_validator._coerce_brief_sections`
    so the Judge sees the same section ordering the numeric validator
    inspected — any drift between the two would let numeric findings
    cite sections the Judge did not score.
    """
    if isinstance(brief, Mapping):
        return {
            str(name): str(content)
            for name, content in brief.items()
            if content is not None
        }
    coerced: dict[str, str] = {}
    for name in _BRIEF_SECTION_NAMES:
        value = getattr(brief, name, None)
        if isinstance(value, str) and value:
            coerced[name] = value
    return coerced


# --------------------------------------------------------------------------- #
# LLM parameter construction                                                  #
# --------------------------------------------------------------------------- #


def _judge_params(llm_config: Mapping[str, Any] | None) -> LLMParams:
    """Build the ``LLMParams`` for a Judge call, honouring operator overrides.

    Operator overrides come from ``research.providers.judge.*`` in
    ``config/settings.yaml``; we read ``temperature``, ``max_tokens``,
    and ``timeout_ms`` directly and fall back to the per-module
    defaults defined above. Any field the operator did not set stays
    ``None``, which tells the adapter to use the upstream provider
    default — the same convention the Sub_Agent adapters follow.
    """
    cfg = dict(llm_config or {})
    return LLMParams(
        temperature=float(cfg.get("temperature", _DEFAULT_TEMPERATURE)),
        max_tokens=int(cfg.get("max_tokens", _DEFAULT_MAX_TOKENS)),
        timeout_ms=cfg.get("timeout_ms"),
    )


def _model_id_from_config(llm_config: Mapping[str, Any] | None) -> str:
    """Derive a ``provider/model`` string from config for fallback reports.

    Used only when a Judge call fails before a ``Completion`` is
    available — we still want the ``JudgeReport.model_id`` field
    populated so operators can trace the failure to the configured
    provider even when the upstream call did not return a model name.
    """
    cfg = dict(llm_config or {})
    provider = cfg.get("provider") or "<unknown>"
    model = cfg.get("model") or "<unknown>"
    return f"{provider}/{model}"


# --------------------------------------------------------------------------- #
# JSON parsing                                                                #
# --------------------------------------------------------------------------- #


def _parse_judge_json(content: str) -> dict[str, Any] | None:
    """Extract a JSON object from the Judge's raw response.

    Real LLMs frequently wrap JSON in prose ("Here is the report:
    ```json ... ```"). We scan for the first ``{`` and the last
    matching ``}`` and parse the substring. Returns ``None`` when no
    such substring parses — the caller reduces that to
    ``safe_to_display=False``.
    """
    if not isinstance(content, str) or not content.strip():
        return None

    # Fast path: content is pure JSON.
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Slow path: find the first balanced ``{...}`` span. We walk the
    # string once tracking brace depth so we skip over any
    # ```json / ``` fences the model may have emitted.
    start = content.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(content)):
        ch = content[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = content[start : i + 1]
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    return None
                return None
    return None


# --------------------------------------------------------------------------- #
# JudgeReport construction                                                    #
# --------------------------------------------------------------------------- #


def _report_from_parsed(
    parsed: dict[str, Any],
    *,
    run_id: UUID,
    numeric_findings: Iterable[UnsupportedClaim],
    retry_count: int,
    elapsed_ms: int,
    model_id: str,
    min_score: float,
) -> JudgeReport:
    """Build a :class:`JudgeReport` from a parsed JSON object.

    Merges the Judge's own ``unsupported_claims`` list with the
    numeric validator's findings — a numeric drift caught by the
    deterministic validator is still a claim the Judge must surface,
    even if the model itself did not flag it (design §11.1 "the
    numeric validator findings are inputs to the Judge"). Duplicates
    (same ``section``, ``claim_text``, ``start_offset``,
    ``end_offset``, ``reason``) are dropped so the re-synthesis
    prompt does not double-count a single drift.
    """
    # Groundedness score — coerce to a ``{str: float}`` dict.
    raw_scores = parsed.get("groundedness_score") or {}
    if not isinstance(raw_scores, Mapping):
        raise TypeError(
            f"groundedness_score must be an object, got {type(raw_scores).__name__}"
        )
    scores: dict[str, float] = {
        str(section): float(value) for section, value in raw_scores.items()
    }

    # Unsupported claims from the Judge — each item must validate as
    # an :class:`UnsupportedClaim`. Validation failures propagate to
    # the caller, which reduces them to a fallback report.
    raw_claims = parsed.get("unsupported_claims") or []
    if not isinstance(raw_claims, list):
        raise TypeError(
            f"unsupported_claims must be a list, got {type(raw_claims).__name__}"
        )
    judge_claims = [UnsupportedClaim.model_validate(item) for item in raw_claims]

    # Merge numeric findings, de-duplicating by identity tuple.
    seen: set[tuple[str, str, int, int, str]] = set()
    merged_claims: list[UnsupportedClaim] = []
    for claim in list(numeric_findings) + judge_claims:
        key = (
            claim.section,
            claim.claim_text,
            claim.start_offset,
            claim.end_offset,
            claim.reason,
        )
        if key in seen:
            continue
        seen.add(key)
        merged_claims.append(claim)

    # Contradiction pairs — coerce each element to a 2-tuple of str.
    raw_pairs = parsed.get("contradiction_pairs") or []
    if not isinstance(raw_pairs, list):
        raise TypeError(
            f"contradiction_pairs must be a list, got {type(raw_pairs).__name__}"
        )
    contradiction_pairs: list[tuple[str, str]] = []
    for pair in raw_pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError(
                f"Each contradiction_pair must be a 2-element list/tuple; got {pair!r}"
            )
        contradiction_pairs.append((str(pair[0]), str(pair[1])))

    # Off-policy findings — coerce to list[str].
    raw_findings = parsed.get("off_policy_findings") or []
    if not isinstance(raw_findings, list):
        raise TypeError(
            f"off_policy_findings must be a list, got {type(raw_findings).__name__}"
        )
    off_policy = [str(f) for f in raw_findings]

    # Model-supplied safe_to_display, overridden by the design §11.1
    # rule: ``False`` if any off-policy finding is non-empty OR any
    # section score falls below ``min_score``. A numeric-drift
    # finding in the merged list also forces ``False`` because the
    # deterministic validator's verdict is authoritative (Req 16.27).
    model_says_safe = bool(parsed.get("safe_to_display", False))
    numeric_drift_present = any(
        claim.reason == "numeric_drift" for claim in merged_claims
    )
    all_scores_pass = all(score >= min_score for score in scores.values()) if scores else False
    safe_to_display = (
        model_says_safe
        and not off_policy
        and not numeric_drift_present
        and all_scores_pass
    )

    return JudgeReport(
        run_id=run_id,
        groundedness_score=scores,
        unsupported_claims=merged_claims,
        safe_to_display=safe_to_display,
        contradiction_pairs=contradiction_pairs,
        off_policy_findings=off_policy,
        retry_count=retry_count,
        elapsed_ms=elapsed_ms,
        model_id=model_id,
    )


# --------------------------------------------------------------------------- #
# Fallback report                                                             #
# --------------------------------------------------------------------------- #


def _fallback_report(
    *,
    run_id: UUID,
    retry_count: int,
    elapsed_ms: int,
    model_id: str,
    reason: str,
    min_score: float = 0.0,
) -> JudgeReport:
    """Build a ``safe_to_display=False`` report for failure paths.

    The report carries a single :class:`UnsupportedClaim` with
    ``reason="off_policy"`` and ``section="<judge_error>"`` so the
    re-synthesis prompt has a concrete hook to show the model
    ("the previous judge call failed; here is why"). We use
    ``off_policy`` rather than inventing a new reason so the
    existing :data:`~src.research.validators.types.UnsupportedReason`
    enum stays closed — all five reasons trigger re-synthesis in
    design §11.2, so the downstream behaviour is identical.

    ``min_score`` defaults to ``0.0`` so callers that don't have the
    operator-configured threshold handy (paths that bail before the
    threshold matters) don't need to thread it in. The structured
    log (Task 20.1, Req 13.5) still records the failure so operators
    can see the judge short-circuit in the aggregated JSON stream.
    """
    report = JudgeReport(
        run_id=run_id,
        groundedness_score={},
        unsupported_claims=[
            UnsupportedClaim(
                section="<judge_error>",
                claim_text=reason or "judge_invocation_failed",
                start_offset=0,
                end_offset=max(len(reason or "judge_invocation_failed"), 1),
                reason="off_policy",
            )
        ],
        safe_to_display=False,
        contradiction_pairs=[],
        off_policy_findings=[reason] if reason else [],
        retry_count=retry_count,
        elapsed_ms=elapsed_ms,
        model_id=model_id,
    )
    _safe_log_judge_call(report=report, min_score=min_score)
    _safe_increment_judge_failures()
    return report


# --------------------------------------------------------------------------- #
# Structured observability log (Task 20.1)                                    #
# --------------------------------------------------------------------------- #
#
# Emits one JSON line per Judge call via
# :func:`src.research.judge.logging.log_judge_call`. Wrapped in
# try/except so an observability failure cannot break the Judge —
# the Orchestrator has a real fail-soft path (:func:`_fallback_report`),
# and we don't want a logger glitch to co-opt it.


def _safe_log_judge_call(*, report: JudgeReport, min_score: float) -> None:
    """Best-effort wrapper around :func:`log_judge_call`."""
    try:
        # Imported here to avoid a module-load-time cycle with
        # :mod:`src.research.judge.logging` (which does not import
        # this file today but we keep the guard for symmetry with
        # the offline-dispatch import at the top of ``invoke``).
        from src.research.judge.logging import log_judge_call

        log_judge_call(
            run_id=report.run_id,
            user_id=None,  # scoped at the Orchestrator level; not
                          # available in this module (see design
                          # §3.7 — the Judge receives the brief +
                          # chunks, not the user id).
            model_id=report.model_id,
            elapsed_ms=report.elapsed_ms,
            safe_to_display=report.safe_to_display,
            min_score=min_score,
            unsupported_count=len(report.unsupported_claims),
            off_policy_count=len(report.off_policy_findings),
            retry_count=report.retry_count,
        )
    except Exception:  # noqa: BLE001 - best-effort observability
        # Any failure is already a degraded path; we deliberately do
        # not emit another log here to avoid a loop if the logger is
        # the source of the failure.
        pass


def _safe_increment_judge_failures() -> None:
    """Best-effort increment of :data:`research_judge_failures_total`.

    Called from :func:`_fallback_report` — every path into that helper
    is a Judge short-circuit (provider error, JSON parse error, or
    schema error) and therefore a judge failure from a user's
    perspective. Prometheus-client import is lazy so a trimmed test
    install without the dependency does not break the Judge's import
    graph (Req 13.2, design §15).
    """
    try:
        from src.research.observability.metrics import (
            research_judge_failures_total,
        )

        research_judge_failures_total.inc()
    except Exception:  # noqa: BLE001 - best-effort metrics
        pass
