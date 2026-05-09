"""Report_Synthesizer (Task 13.8, design §3.5, Req 1.4, Req 1.5).

Consumes the outputs of the other six Sub_Agents (Filings, Fundamentals,
News_Sentiment, Technicals, Peer_Sector, Macro) and produces a single
cohesive ``ResearchBrief`` with every canonical section populated. The
spec is explicit that this agent does **NOT** issue its own retrieval
calls (Req 1.4) — it reads the ``section_name`` and ``section_md`` from
each :class:`AgentResult` and threads them into the right brief field,
letting the LLM stitch the per-agent content into a coherent whole.

Where this agent sits in the graph
----------------------------------
Design §3.5 places the Report_Synthesizer at the confluence of the
fan-out:

    Filings ─┐
    Fund.    ├─► Report_Synthesizer ─► numeric validator ─► Judge_LLM
    News     │       (this module)
    Tech     │
    Peers    │
    Macro   ─┘

The Orchestrator (:mod:`src.research.agents.orchestrator`) invokes the
synthesizer through the duck-typed ``Synthesizer`` alias:

* First pass::

      await synthesizer(
          agent_results=[...],
          symbol="RELIANCE",
          user_prompt="Brief RELIANCE for Q2.",
      )

* Re-synthesis pass (design §11.2, Req 16.18)::

      await synthesizer(
          agent_results=[...],
          symbol="RELIANCE",
          user_prompt="Brief RELIANCE for Q2.",
          prior_brief={...},
          unsupported_claims=(UnsupportedClaim(...), ...),
          numeric_findings=(UnsupportedClaim(...), ...),
      )

The :class:`Synthesizer` class exposes ``__call__`` so a single
callable instance satisfies both signatures and the presence of
``prior_brief`` distinguishes first-pass from re-synthesis.

Return shape
------------
Every call returns a ``Mapping[str, str]`` keyed by the canonical brief
sections plus ``"citations"``. Every canonical key is always present
(set to ``""`` when no Sub_Agent contributed content) so the
Orchestrator's ``_assemble_final_brief`` and the numeric validator
don't have to special-case missing fields.

LLM JSON contract
-----------------
The LLM is instructed (via ``prompts/v1/report_synthesizer.md``) to
return JSON. We accept two shapes to keep the system robust to prompt
drift across Task 10.1 / future prompt versions:

1. ``{"sections": [{"name": ..., "content_markdown": ..., "citations": [...]}, ...],
      "executive_summary": "..."}``
   — the shape emitted by the current v1 template.
2. ``{"summary": "...", "thesis": "...", ..., "citations": [...]}``
   — a flat shape easier for some models to produce; also what
   re-synthesis prompts tend to emit when given a ``prior_brief``
   template.

Either is normalised into the canonical flat ``Mapping[str, str]``
the Orchestrator expects. Unknown section names in the LLM response
are dropped silently rather than forwarded — the canonical set is
authoritative and fabricated section names downstream would confuse
the numeric validator and the Judge.

Error handling
--------------
Per the task brief ("LLM error propagates"), upstream LLM failures —
auth, timeout, transport — propagate to the Orchestrator so its
per-call isolation wrapper (see
:meth:`ResearchOrchestrator._invoke_agent`) can surface the failure
in the run trace. This module does not swallow provider exceptions
and does not produce a "safe default" brief; that contrasts with the
Judge's fail-soft behaviour because the synthesizer is on the main
content path (a silent empty brief would look like a successful run
to downstream validators).

JSON parse failures are treated differently from upstream errors:
the LLM returned *something*, just not valid JSON. We fall back to
stitching each Sub_Agent's ``section_md`` into its declared section
verbatim. The resulting brief may still fail the Judge — the
hallucination-control stack is designed to handle that — but the
run produces a structurally-valid brief instead of crashing.

Satisfies
---------
* Req 1.4 — synthesizer consumes only other Sub_Agents' outputs; no
  retrieval calls. Enforced by the class's lack of retriever / vector
  store dependencies.
* Req 1.5 — returned brief carries the canonical section set and
  citations. Guaranteed by :data:`_BRIEF_SECTIONS` and the
  always-include-every-key invariant in :meth:`_build_result`.
* design §3.5 — Sub_Agent graph placement and "no retrieval of its
  own" constraint.
* design §11.2 / Req 16.18 — re-synthesis signature accepts
  ``prior_brief``, ``unsupported_claims``, ``numeric_findings`` so the
  Orchestrator can close the re-synth loop without a separate
  callable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Final, Iterable, Mapping, Sequence

from src.research.agents.orchestrator import AgentResult
from src.research.guardrails.refusal_policy import REFUSAL_POLICY_BLOCK
from src.research.prompts.loader import load_prompt, render
from src.research.providers.base import LLMParams, LLMProvider, Message
from src.research.validators.types import UnsupportedClaim

__all__ = ["Synthesizer", "build"]


# --------------------------------------------------------------------------- #
# Canonical brief sections                                                    #
# --------------------------------------------------------------------------- #

# The canonical brief section list (design §3.5, Req 1.5). Kept in
# lockstep with :data:`src.research.agents.orchestrator._BRIEF_SECTIONS`,
# :data:`src.research.validators.numeric_validator._BRIEF_SECTION_NAMES`,
# :data:`src.research.judge.judge._BRIEF_SECTION_NAMES`, and
# :data:`src.research.judge.rule_based._BRIEF_SECTION_NAMES`. Every
# site owns its own copy because the authoritative ``ResearchBrief``
# Pydantic model (design §4.2) is not yet in this tree; when it lands
# every module reads from there instead.
_BRIEF_SECTIONS: Final[tuple[str, ...]] = (
    "summary",
    "thesis",
    "risks",
    "financial_highlights",
    "management_commentary",
    "technical_view",
    "peers",
    "macro_context",
)

# The ``citations`` key sits alongside the section keys in the returned
# mapping (Req 1.5 explicitly lists it as part of the brief). Kept as
# its own constant so the tests can reference it symbolically and so
# downstream consumers don't fork over stringly-typed keys.
_CITATIONS_KEY: Final[str] = "citations"

# Prompt file the synthesizer renders. Matches
# ``src/research/prompts/v1/report_synthesizer.md`` (Task 10.1 output).
_PROMPT_VERSION: Final[str] = "v1"
_PROMPT_NAME: Final[str] = "report_synthesizer"

# Canonical refusal-no-context string. Mirrors the value in
# :mod:`src.research.agents._base` and :mod:`src.research.judge.judge`;
# the synthesizer never produces this refusal itself (the LLM might,
# per the prompt skeleton), but the placeholder must still be
# substituted to satisfy :func:`render`'s fail-loud contract.
_REFUSAL_NO_CONTEXT: Final[str] = "INSUFFICIENT_EVIDENCE: no context available."

# Default LLM sampling parameters. Deterministic temperature keeps the
# JSON output parseable and lets the Judge / property tests reason
# about content stability. ``max_tokens=4096`` is wider than the
# per-Sub_Agent default (2048) because the synthesizer is producing
# every section in one response; the upper bound still fits within the
# default per-run output budget (8k tokens, Req 12.3).
_DEFAULT_TEMPERATURE: Final[float] = 0.0
_DEFAULT_MAX_TOKENS: Final[int] = 4096


# --------------------------------------------------------------------------- #
# Synthesizer                                                                 #
# --------------------------------------------------------------------------- #


@dataclass
class Synthesizer:
    """Report_Synthesizer — stitches Sub_Agent outputs into a brief.

    The class exposes a single ``__call__`` that accepts both the
    first-pass and re-synthesis kwargs. Presence of ``prior_brief`` in
    the call distinguishes re-synthesis from the first pass — it is
    the only kwarg the Orchestrator's re-synthesis path supplies that
    the first pass does not.

    Parameters
    ----------
    llm:
        :class:`LLMProvider` instance that produces the stitched
        brief. In production this is resolved from
        ``research.providers.chat.*`` (Req 12.1, design §7.1); tests
        inject :class:`tests.research.fakes.FakeLLMProvider` to stay
        mock-free.
    temperature, max_tokens:
        Per-call overrides for :class:`LLMParams`. Defaults mirror
        the module-level constants.
    prompt_version:
        Directory under ``src/research/prompts/`` to load the
        synthesizer template from. Defaults to ``"v1"``.
    """

    llm: LLMProvider | None = None
    temperature: float = _DEFAULT_TEMPERATURE
    max_tokens: int = _DEFAULT_MAX_TOKENS
    prompt_version: str = _PROMPT_VERSION

    # --- Public call surface -------------------------------------------- #

    async def __call__(
        self,
        *,
        agent_results: Sequence[AgentResult],
        symbol: str | None,
        user_prompt: str,
        prior_brief: "Mapping[str, str] | object | None" = None,
        unsupported_claims: Iterable[UnsupportedClaim] = (),
        numeric_findings: Iterable[UnsupportedClaim] = (),
    ) -> dict[str, str]:
        """Run the synthesizer.

        First-pass callers pass ``agent_results`` + ``symbol`` +
        ``user_prompt``. The Orchestrator's re-synthesis path
        additionally supplies ``prior_brief`` / ``unsupported_claims``
        / ``numeric_findings`` so the LLM can rewrite the unsupported
        sections without starting from scratch.

        Returns
        -------
        dict[str, str]
            The canonical brief shape: every key in
            :data:`_BRIEF_SECTIONS` plus ``"citations"``. Unset
            sections carry ``""`` so downstream consumers never see
            missing keys.
        """
        if self.llm is None:
            # Matches the guard in :class:`BaseRetrievalAgent` — a
            # construction-time check would be tidier, but the
            # dataclass default-to-``None`` keeps call-sites simple
            # and the error message here is clearer than an
            # AttributeError on ``llm.complete``.
            raise ValueError(
                "Synthesizer requires an LLMProvider; construct with "
                "``llm=...``."
            )

        # 1) Render the prompt. Every slot present in the v1 template
        #    is filled verbatim; re-synthesis-specific context is
        #    appended to ``{{USER_PROMPT}}`` because the v1 template
        #    does not have dedicated placeholders for it (the Judge
        #    module uses the same packing strategy).
        system_prompt = self._render_prompt(
            agent_results=agent_results,
            user_prompt=user_prompt,
            symbol=symbol,
            prior_brief=prior_brief,
            unsupported_claims=tuple(unsupported_claims),
            numeric_findings=tuple(numeric_findings),
        )

        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt),
        ]

        # 2) Call the LLM. Exceptions propagate to the Orchestrator
        #    per the task brief ("LLM error propagates").
        completion = await self.llm.complete(messages, self._llm_params())

        # 3) Parse the LLM response into a section mapping. Falls
        #    back to stitching each Sub_Agent's ``section_md``
        #    verbatim when the response is not valid JSON — see the
        #    module docstring for the rationale.
        sections = _parse_sections(completion.content)
        if sections is None:
            sections = _fallback_stitch(agent_results)

        # 4) Build the result. This step enforces the "every canonical
        #    key always present" invariant, computes the citations
        #    list from the Sub_Agents' chunks (authoritative source
        #    of truth — we do not trust the LLM to enumerate the
        #    correct chunk_ids), and drops unknown section names.
        return _build_result(sections=sections, agent_results=agent_results)

    # --- Prompt rendering ---------------------------------------------- #

    def _render_prompt(
        self,
        *,
        agent_results: Sequence[AgentResult],
        user_prompt: str,
        symbol: str | None,
        prior_brief: "Mapping[str, str] | object | None",
        unsupported_claims: tuple[UnsupportedClaim, ...],
        numeric_findings: tuple[UnsupportedClaim, ...],
    ) -> str:
        """Render the versioned synthesizer prompt (Req 16.6, design §3.9).

        The v1 template exposes four shared-skeleton placeholders:
        ``REFUSAL_NO_CONTEXT``, ``REFUSAL_POLICY_BLOCK``,
        ``RETRIEVED_CHUNKS_VERBATIM``, ``USER_PROMPT``. The first two
        are substituted verbatim; the last two are packed with the
        synthesizer's actual inputs — Sub_Agent section content goes
        into ``RETRIEVED_CHUNKS_VERBATIM`` (so the LLM sees it in the
        fenced ``<|CONTEXT|>`` block), and ``USER_PROMPT`` carries
        the re-synthesis feedback (if any) alongside the original
        question.
        """
        prompt = load_prompt(self.prompt_version, _PROMPT_NAME)

        context_block = _format_agent_results(agent_results)
        packed_user = _pack_user_prompt(
            user_prompt=user_prompt,
            symbol=symbol,
            prior_brief=prior_brief,
            unsupported_claims=unsupported_claims,
            numeric_findings=numeric_findings,
        )

        return render(
            prompt,
            substitutions={
                "REFUSAL_NO_CONTEXT": _REFUSAL_NO_CONTEXT,
                "REFUSAL_POLICY_BLOCK": REFUSAL_POLICY_BLOCK,
                "RETRIEVED_CHUNKS_VERBATIM": context_block,
                "USER_PROMPT": packed_user,
            },
        )

    # --- LLM params ---------------------------------------------------- #

    def _llm_params(self) -> LLMParams:
        """Build :class:`LLMParams` from the synthesizer's knobs."""
        return LLMParams(
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            stream=False,
        )


# --------------------------------------------------------------------------- #
# Prompt assembly helpers                                                     #
# --------------------------------------------------------------------------- #


def _format_agent_results(results: Sequence[AgentResult]) -> str:
    """Format the Sub_Agent outputs for the ``<|CONTEXT|>`` block.

    Each Sub_Agent becomes a fenced block that carries:

    * Its ``agent_name`` — so the LLM can cite the source agent if
      the prompt ever asks for attribution.
    * Its ``kind`` — so ``no_data`` / ``error`` agents are explicit
      in the context rather than silently omitted. This lets the
      LLM acknowledge missing coverage (e.g. "macro context not
      available") without the synthesizer having to special-case it.
    * Its ``section_name`` — so the LLM knows which canonical
      section the content belongs to.
    * Its ``section_md`` body verbatim, preserving any
      ``[cite:<chunk_id>]`` markers emitted by the Sub_Agent's LLM.

    Empty result sets render as ``"<no agent outputs>"`` — the same
    convention :func:`src.research.judge.judge._format_chunks` uses.
    """
    if not results:
        return "<no agent outputs>"

    blocks: list[str] = []
    for result in results:
        header = (
            f"# agent={result.agent_name} "
            f"kind={result.kind} "
            f"section={result.section_name or '<unset>'}"
        )
        body: str
        if result.kind == "ok" and result.section_md:
            body = result.section_md
        elif result.kind == "no_data":
            reason = result.reason or "no_data"
            body = f"<no_data: {reason}>"
        elif result.kind == "error":
            reason = result.reason or "error"
            body = f"<error: {reason}>"
        else:
            # Defensive — ``kind`` should be one of the three above
            # (see :class:`AgentResult`), but fall through gracefully
            # if a future task introduces a new variant.
            body = result.section_md or f"<kind={result.kind}>"
        blocks.append(f"{header}\n{body}")

    return "\n\n".join(blocks)


def _pack_user_prompt(
    *,
    user_prompt: str,
    symbol: str | None,
    prior_brief: "Mapping[str, str] | object | None",
    unsupported_claims: tuple[UnsupportedClaim, ...],
    numeric_findings: tuple[UnsupportedClaim, ...],
) -> str:
    """Pack the synthesizer's semantic blocks into the user-prompt slot.

    The v1 prompt template only exposes ``{{USER_PROMPT}}`` for the
    caller's free text — the Judge module uses the same packing
    trick. We add fenced sub-blocks for ``symbol``, the re-synthesis
    context (``prior_brief`` + feedback lists), and the original
    prompt so the LLM can address each in turn.

    Re-synthesis vs first pass: the first-pass call passes
    ``prior_brief=None`` and empty feedback lists, in which case
    only the ``symbol`` and ``caller_prompt`` blocks are emitted.
    The LLM sees a tight, familiar shape during the common path and
    additional instructions only when they are actionable.
    """
    parts: list[str] = []

    if symbol:
        parts.append(f"<symbol>{symbol}</symbol>")
    else:
        # Explicit marker so the LLM knows no symbol scope was
        # provided (Req 1.5 allows generic queries).
        parts.append("<symbol>none</symbol>")

    # Re-synthesis context — only rendered when the Orchestrator
    # supplies a ``prior_brief``. The LLM sees the failing brief plus
    # the authoritative findings and is asked (via the template body)
    # to rewrite the flagged sections.
    if prior_brief is not None:
        prior_sections = _coerce_brief_sections(prior_brief)
        prior_block = _format_brief_sections(prior_sections)
        parts.append(f"<prior_brief>\n{prior_block}\n</prior_brief>")

    if unsupported_claims:
        claims_json = json.dumps(
            [claim.model_dump() for claim in unsupported_claims],
            ensure_ascii=False,
            indent=2,
        )
        parts.append(
            f"<unsupported_claims>\n{claims_json}\n</unsupported_claims>"
        )

    if numeric_findings:
        findings_json = json.dumps(
            [claim.model_dump() for claim in numeric_findings],
            ensure_ascii=False,
            indent=2,
        )
        parts.append(
            f"<numeric_findings>\n{findings_json}\n</numeric_findings>"
        )

    parts.append(f"<caller_prompt>\n{user_prompt}\n</caller_prompt>")
    return "\n\n".join(parts)


def _format_brief_sections(sections: Mapping[str, str]) -> str:
    """Render ``{section: content}`` as fenced blocks for the LLM."""
    if not sections:
        return "<empty brief>"
    return "\n\n".join(
        f"## {name}\n{content}" for name, content in sections.items()
    )


def _coerce_brief_sections(
    brief: "Mapping[str, str] | object",
) -> dict[str, str]:
    """Normalise a brief into ``{section_name: content}``.

    Mirrors the coercion in the Orchestrator, the numeric validator,
    the Judge, and the rule-based judge. Keeping all four in lockstep
    means a re-synthesis prompt sees the same sections the Judge
    scored — any drift would let the LLM "fix" sections the downstream
    validators didn't flag.
    """
    if isinstance(brief, Mapping):
        return {
            str(name): "" if content is None else str(content)
            for name, content in brief.items()
        }
    coerced: dict[str, str] = {}
    for name in _BRIEF_SECTIONS:
        value = getattr(brief, name, None)
        if isinstance(value, str):
            coerced[name] = value
    return coerced


# --------------------------------------------------------------------------- #
# Response parsing                                                            #
# --------------------------------------------------------------------------- #


def _parse_sections(content: str) -> dict[str, str] | None:
    """Parse the LLM's JSON response into ``{section: content_md}``.

    Accepts either of the two shapes documented in the module
    docstring. Returns ``None`` when neither parses — the caller
    falls back to ``_fallback_stitch``.

    JSON extraction is deliberately lenient: LLMs often wrap JSON in
    prose or code fences. We mirror :func:`judge._parse_judge_json`'s
    balanced-brace scan so the synthesizer is robust to the same
    quirks the Judge is.
    """
    parsed = _extract_json_object(content)
    if parsed is None:
        return None

    # Shape 1 — ``{"sections": [{"name": ..., "content_markdown": ...}, ...]}``.
    raw_sections = parsed.get("sections")
    if isinstance(raw_sections, list):
        sections = _parse_sections_list(raw_sections)
        # If an executive_summary is present, route it into the
        # canonical ``summary`` section unless the LLM already
        # populated that field — the prompt surfaces both fields,
        # so we want either one to satisfy the Orchestrator.
        exec_summary = parsed.get("executive_summary")
        if isinstance(exec_summary, str) and exec_summary.strip():
            sections.setdefault("summary", exec_summary)
        return sections

    # Shape 2 — flat mapping keyed by section name. We accept it when
    # at least one canonical section key is present; otherwise the
    # response is unrelated JSON (e.g. an error envelope) and we
    # return ``None`` so the caller falls back.
    flat: dict[str, str] = {}
    for name in _BRIEF_SECTIONS:
        value = parsed.get(name)
        if isinstance(value, str):
            flat[name] = value
    if flat:
        return flat

    return None


def _parse_sections_list(raw: list[Any]) -> dict[str, str]:
    """Normalise a ``sections`` array into ``{name: content_md}``.

    Items without a ``name``, or with a ``name`` outside
    :data:`_BRIEF_SECTIONS`, are dropped silently — the canonical set
    is authoritative (Req 1.5) and forwarding a fabricated section
    would confuse the numeric validator and the Judge.

    ``content_markdown`` is preferred but ``content`` is accepted as
    a fallback since a few earlier prompt iterations used it.
    """
    out: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        if not isinstance(name, str) or name not in _BRIEF_SECTIONS:
            continue
        content = item.get("content_markdown")
        if not isinstance(content, str):
            content = item.get("content")
        if not isinstance(content, str):
            continue
        out[name] = content
    return out


def _extract_json_object(content: str) -> dict[str, Any] | None:
    """Pull the first balanced JSON object out of an LLM response.

    Mirrors :func:`src.research.judge.judge._parse_judge_json`. A
    single shared helper would be nicer; deferred until the
    ``ResearchBrief`` Pydantic model lands and both modules can
    import from a common location.
    """
    if not isinstance(content, str) or not content.strip():
        return None

    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

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
# Fallback + assembly                                                         #
# --------------------------------------------------------------------------- #


def _fallback_stitch(
    results: Sequence[AgentResult],
) -> dict[str, str]:
    """Fallback when the LLM response is not parseable JSON.

    Each ``ok`` Sub_Agent's ``section_md`` is threaded into its
    declared ``section_name``. Multiple agents contributing to the
    same section (e.g. Filings → ``management_commentary`` and a
    future agent that also writes there) have their content
    concatenated with a blank line between — the Judge can then flag
    any resulting inconsistencies, rather than this module picking a
    winner silently.

    ``no_data`` / ``error`` results contribute nothing. The empty
    string for their section still satisfies Req 1.5 because
    :func:`_build_result` fills every canonical key regardless.
    """
    sections: dict[str, list[str]] = {}
    for result in results:
        if result.kind != "ok" or not result.section_md.strip():
            continue
        section_name = result.section_name
        if section_name not in _BRIEF_SECTIONS:
            continue
        sections.setdefault(section_name, []).append(result.section_md)

    return {name: "\n\n".join(parts) for name, parts in sections.items()}


def _build_result(
    *,
    sections: Mapping[str, str],
    agent_results: Sequence[AgentResult],
) -> dict[str, str]:
    """Assemble the final ``Mapping[str, str]`` returned to the Orchestrator.

    Invariants:

    * Every canonical key in :data:`_BRIEF_SECTIONS` is present,
      defaulting to ``""`` — the Orchestrator's ``_assemble_final_brief``
      already does this as a belt, but we do it here as braces so
      callers bypassing the Orchestrator still get the invariant.
    * Unknown section names from the LLM are dropped. The canonical
      set is authoritative (Req 1.5) and downstream validators (numeric
      / Judge) key off it.
    * The ``citations`` field is derived from the Sub_Agents' actual
      chunks — the LLM's own citation list is ignored because the
      authoritative provenance lives on the ``AgentResult.chunks``
      attribute. This is the Req 3.11 invariant: every Citation in
      the brief must resolve to an existing chunk in the
      Vector_Store, which is only guaranteed when we take chunk_ids
      from the Sub_Agent output.
    """
    out: dict[str, str] = {}
    for name in _BRIEF_SECTIONS:
        value = sections.get(name, "")
        out[name] = "" if value is None else str(value)

    out[_CITATIONS_KEY] = _collect_citation_ids(agent_results)
    return out


def _collect_citation_ids(results: Sequence[AgentResult]) -> str:
    """Join every Sub_Agent's cited ``chunk_id`` into a JSON array string.

    The canonical brief shape (design §4.2) represents ``citations``
    as a list of :class:`Citation` objects; until the full Pydantic
    ``ResearchBrief`` lands in a follow-up, the synthesizer emits a
    compact JSON array of chunk_ids so the Mapping signature remains
    ``Mapping[str, str]`` (which is what the Orchestrator's
    ``Synthesizer`` alias expects). The Orchestrator's
    ``_assemble_final_brief`` further lifts ``citations`` into its
    own list on the returned brief payload — our string value is a
    stable, machine-parseable representation that survives that
    shape without loss.

    Deduplication preserves order so the Judge can trace a citation
    back to the Sub_Agent that produced it.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for result in results:
        for hit in result.chunks:
            chunk_id = hit.chunk.chunk_id
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            ordered.append(chunk_id)
    return json.dumps(ordered, ensure_ascii=False, separators=(",", ":"))


# --------------------------------------------------------------------------- #
# Factory                                                                     #
# --------------------------------------------------------------------------- #


def build(llm: LLMProvider, **kwargs: Any) -> Synthesizer:
    """Convenience factory mirroring the provider-adapter pattern.

    ``src/research/providers/registry.py`` registers adapters as
    ``build(cfg)`` callables; keeping a parallel factory here means
    a future synthesizer registry can construct the Report_Synthesizer
    the same way.
    """
    return Synthesizer(llm=llm, **kwargs)
