"""Offline rule-based fallback Judge (design §11.4, Req 16.22).

Deterministic, LLM-free judge used when ``LOHI_RESEARCH_OFFLINE=true``
(design §15 offline workflow C, Req 15.5). Returns the same
:class:`~src.research.judge.judge.JudgeReport` shape as
:func:`src.research.judge.judge.invoke` so downstream code — the
Orchestrator's re-synthesis loop (design §11.2) and the
``research_judge_reports`` provenance row — does not care whether
the verdict came from an LLM or from this module.

Scope
-----
Per design §11.4 the fallback performs three checks and combines
them into a :class:`JudgeReport`:

1. **Citation coverage.** Every non-boilerplate sentence in each
   brief section must end with at least one ``[cite:<chunk_id>]``
   marker. Uncited sentences become
   :class:`~src.research.validators.types.UnsupportedClaim` rows
   with ``reason="no_citation"``.
2. **Numeric fidelity.** The module delegates to the deterministic
   numeric validator
   (:func:`~src.research.validators.numeric_validator.validate_numeric_fidelity`)
   and folds its ``numeric_drift`` findings straight into
   ``unsupported_claims``. Callers that have already run the
   validator upstream may pass their findings in via
   ``numeric_findings=`` to avoid a second pass.
3. **Refusal_Policy regex.** Each section body is run through
   :func:`~src.research.validators.refusal_classifier.classify_refusal`;
   a match becomes an ``off_policy_findings`` entry tagged with
   ``"<rule_id>: <reason>"`` (e.g. ``"RP-002: price_target"``).

Groundedness scoring
--------------------
Per-section score = fraction of sentences that carry at least one
citation marker, clamped to ``[0, 1]``. An empty section scores
``1.0`` (no sentences means no uncited sentences). This simple
heuristic is the one design §11.4 specifies: the fallback is not
trying to reason about semantic support the way an LLM judge does —
it is trying to catch the obvious failure modes (missing citations,
off-policy leakage, numeric drift) that a rule-based pass can find
cheaply.

safe_to_display rule
--------------------
``True`` iff every one of these holds:

* no ``off_policy_findings`` (the policy regex found nothing),
* no ``unsupported_claims`` (every sentence cited and every numeric
  claim reconciled),
* every per-section score is at or above ``min_score``.

Any single violation flips ``safe_to_display`` to ``False`` so the
Orchestrator's re-synthesis trigger (design §11.2, Req 16.18) fires
uniformly regardless of which check caught the problem.

Provenance
----------
Reports produced by this module carry ``model_id="rule_based/v1"``
so operators inspecting ``research_judge_reports`` can see at a
glance that the verdict came from the offline judge. ``elapsed_ms``
is measured via :func:`time.perf_counter` so the latency-budget
plumbing (design §13.4) treats rule-based calls consistently with
LLM calls.

Satisfies
---------
* Req 16.22 — offline rule-based fallback judge performing
  citation-coverage and regex policy checks.
* Req 15.5 — system remains functional in fully-offline mode.
* design §11.4 — exact scoring flow specified here.

Design references
-----------------
* §11.4 — offline rule-based fallback (canonical spec).
* §3.7 — ``JudgeReport`` shape.
* §3.8 — deterministic validators used as inputs.
* §11.2 — re-synthesis loop that consumes the returned report.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable, Mapping
from typing import Final, Protocol, runtime_checkable
from uuid import UUID

from src.research.judge.judge import JudgeReport
from src.research.validators.numeric_validator import validate_numeric_fidelity
from src.research.validators.refusal_classifier import classify_refusal
from src.research.validators.types import UnsupportedClaim

__all__ = ["invoke_rule_based"]


# --------------------------------------------------------------------------- #
# Constants                                                                   #
# --------------------------------------------------------------------------- #


# ``provider/model`` identifier stamped onto every report this module
# produces. Kept in the ``rule_based/`` namespace so operators can
# distinguish these rows from LLM-authored ones in
# ``research_judge_reports``. Bumped to ``v2`` only if the scoring
# heuristic changes (for now the heuristic is fraction-of-cited
# sentences, design §11.4).
_MODEL_ID: Final[str] = "rule_based/v1"

# Citation marker regex. Matches ``[cite:<chunk_id>]`` where
# ``<chunk_id>`` is any non-empty sequence of non-``]`` characters.
# The loose body pattern is intentional — chunk ids land as
# ``sha256(document_sha256 || chunker_version || position)`` (design
# §3.3) which is hexadecimal, but user uploads may supply anything;
# we only care *that* a marker exists, not what it points at
# (citation-to-chunk resolution is the citation validator's job,
# design §3.8).
_CITATION_PATTERN: Final[re.Pattern[str]] = re.compile(r"\[cite:[^\]]+\]")

# Sentence splitter. Per task notes: split on ``. ? !`` followed by
# whitespace or newline. Kept deliberately simple — the fallback is
# a regex pass, not a linguistic parser, and over-splitting
# abbreviations (``Rs. 1,234``) only costs us an extra empty piece
# which the filter below drops. Multi-line briefs are handled by the
# ``\s+`` side of the lookbehind-free split: ``re.split`` on the
# pattern keeps the boundary characters out of the pieces, which is
# what we want.
_SENTENCE_BOUNDARY: Final[re.Pattern[str]] = re.compile(r"(?<=[.!?])\s+")


# --------------------------------------------------------------------------- #
# Duck-typed inputs                                                           #
# --------------------------------------------------------------------------- #


@runtime_checkable
class _ChunkLike(Protocol):
    """Minimal duck-typed chunk — ``.chunk_id`` and ``.text`` are read.

    Mirrors the protocol used by
    :func:`src.research.judge.judge.invoke` so callers can hand the
    same chunk iterable to either judge implementation. The rule
    -based judge itself only reads ``.text`` (via the numeric
    validator); ``.chunk_id`` is on the protocol for parity with
    the LLM judge and to give future refinements a seat (e.g.
    checking citation markers against actual chunk ids).
    """

    chunk_id: str
    text: str


# Canonical brief section list — duplicated from
# :mod:`src.research.validators.numeric_validator` (same rationale:
# the canonical owner lands in Task 13.8 with the ``ResearchBrief``
# Pydantic model, and both modules will read from there at that
# point).
_BRIEF_SECTION_NAMES: Final[tuple[str, ...]] = (
    "summary",
    "thesis",
    "risks",
    "financial_highlights",
    "management_commentary",
    "technical_view",
    "peers",
    "macro_context",
)


# --------------------------------------------------------------------------- #
# Public entry point                                                          #
# --------------------------------------------------------------------------- #


async def invoke_rule_based(
    *,
    run_id: UUID,
    brief: Mapping[str, str] | object,
    chunks: Iterable[_ChunkLike],
    numeric_findings: Iterable[UnsupportedClaim] | None = None,
    min_score: float = 0.7,
    retry_count: int = 0,
) -> JudgeReport:
    """Deterministic offline judge — returns a :class:`JudgeReport`.

    Signature matches :func:`src.research.judge.judge.invoke` minus
    the ``llm`` / ``llm_config`` arguments (there is no LLM here).
    ``async`` so callers can ``await`` it uniformly alongside the
    LLM-backed judge; there is no actual concurrency inside this
    function and it never yields to the event loop.

    Parameters
    ----------
    run_id:
        The Research_Run this judgement belongs to. Passed through
        to :attr:`JudgeReport.run_id`.
    brief:
        Either a ``dict[str, str]`` mapping section name to
        ``content_md`` or any object exposing the canonical
        ``ResearchBrief`` section attributes. Duck-typed per the
        same contract :func:`judge.invoke` uses.
    chunks:
        Iterable of chunk-like objects exposing ``.chunk_id`` and
        ``.text``. Consumed once by the numeric validator (which
        only reads ``.text``); callers should pass the list of
        cited chunks for the run.
    numeric_findings:
        Optional pre-computed findings from the deterministic
        numeric validator. Supply this when the Orchestrator has
        already run the validator upstream to avoid a second pass.
        When ``None`` (the default), the numeric validator runs
        here against ``brief`` and ``chunks``.
    min_score:
        Operator-configured minimum per-section score from
        ``research.judge.min_score`` (default 0.7). A section score
        below this floor forces ``safe_to_display=False``.
    retry_count:
        The Orchestrator's running re-synthesis counter; echoed
        back in :attr:`JudgeReport.retry_count`.

    Returns
    -------
    JudgeReport
        A fully-populated report with ``model_id="rule_based/v1"``.
        ``safe_to_display`` is ``True`` only when every check
        passed: no uncited sentences, no numeric-drift findings,
        no off-policy findings, and every per-section score at or
        above ``min_score``.

    """
    start = time.perf_counter()

    sections = _coerce_brief_sections(brief)

    # Citation-coverage pass. Produces one ``UnsupportedClaim`` per
    # uncited sentence plus a per-section coverage fraction that
    # feeds ``groundedness_score`` and the ``safe_to_display`` rule.
    coverage_claims, groundedness_score = _score_citation_coverage(sections)

    # Numeric fidelity. When the caller has not pre-computed the
    # findings (the common case for the offline judge, where no
    # Orchestrator has run yet), we run the validator here so the
    # fallback can stand alone.
    if numeric_findings is None:
        numeric_claims = validate_numeric_fidelity(
            brief=sections, cited_chunks=list(chunks),
        )
    else:
        numeric_claims = list(numeric_findings)

    # Refusal-policy pass. Each section body is classified; a match
    # becomes an ``off_policy_findings`` entry. Kept as plain strings
    # (``"<rule_id>: <reason>"``) to mirror the LLM-judge shape,
    # which emits short user-visible phrases.
    off_policy = _scan_refusal_policy(sections)

    # Merge uncited-sentence claims with numeric findings.
    # Duplicates are de-duped by the identity tuple the LLM judge
    # uses (section, claim_text, start, end, reason) so the
    # re-synthesis prompt never double-counts.
    unsupported_claims = _merge_claims(coverage_claims, numeric_claims)

    # ``safe_to_display`` rule: all three checks must pass AND every
    # per-section score must meet the floor. Missing sections in
    # ``groundedness_score`` is possible when the brief is empty —
    # ``all()`` over an empty iterable returns ``True`` which is
    # what we want (an empty brief with no off-policy and no numeric
    # findings is trivially safe).
    all_scores_pass = all(
        score >= min_score for score in groundedness_score.values()
    )
    safe_to_display = (
        not off_policy
        and not unsupported_claims
        and all_scores_pass
    )

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    return JudgeReport(
        run_id=run_id,
        groundedness_score=groundedness_score,
        unsupported_claims=unsupported_claims,
        safe_to_display=safe_to_display,
        contradiction_pairs=[],
        off_policy_findings=off_policy,
        retry_count=retry_count,
        elapsed_ms=elapsed_ms,
        model_id=_MODEL_ID,
    )


# --------------------------------------------------------------------------- #
# Citation coverage                                                           #
# --------------------------------------------------------------------------- #


def _score_citation_coverage(
    sections: Mapping[str, str],
) -> tuple[list[UnsupportedClaim], dict[str, float]]:
    """Per-section citation coverage scoring (design §11.4 step 1).

    Returns a ``(claims, scores)`` pair:

    * ``claims`` — one :class:`UnsupportedClaim` with
      ``reason="no_citation"`` per sentence that carries no
      ``[cite:<chunk_id>]`` marker. ``claim_text`` is the sentence
      verbatim; offsets are relative to the section body so the
      re-synthesis prompt can slice the section with
      ``content[start:end]``.
    * ``scores`` — per-section fraction in ``[0, 1]`` of sentences
      that do carry at least one citation marker. Empty sections
      score ``1.0`` (see module docstring).
    """
    claims: list[UnsupportedClaim] = []
    scores: dict[str, float] = {}

    for section_name, content in sections.items():
        if not content:
            # Empty section — no sentences to cite, trivially
            # grounded. ``safe_to_display`` folds cleanly because
            # an empty body cannot leak off-policy content either.
            scores[section_name] = 1.0
            continue

        sentences = list(_iter_sentences(content))
        if not sentences:
            # Section body had no sentence-terminal punctuation —
            # treat the whole body as a single sentence for
            # coverage purposes. Matches the behaviour callers
            # expect for a short bullet-style section.
            sentences = [(content.strip(), 0, len(content))]

        cited_count = 0
        for sentence_text, start, end in sentences:
            if _has_citation(sentence_text):
                cited_count += 1
                continue
            claims.append(
                UnsupportedClaim(
                    section=section_name,
                    claim_text=sentence_text,
                    start_offset=start,
                    end_offset=end,
                    reason="no_citation",
                ),
            )

        scores[section_name] = cited_count / len(sentences)

    return claims, scores


def _iter_sentences(content: str) -> Iterable[tuple[str, int, int]]:
    """Yield ``(sentence_text, start_offset, end_offset)`` triples.

    Splits on :data:`_SENTENCE_BOUNDARY` while preserving the
    original character offsets so the emitted
    :class:`UnsupportedClaim` rows carry accurate slice bounds.
    Empty / whitespace-only pieces are dropped — they cannot be
    "uncited" in any meaningful sense.

    The splitter is deliberately simple: one pass over the string,
    tracking the current position. Matches design §11.4's "simple
    sentence-splitting (e.g., on ``. ? !`` followed by
    whitespace/newline)" exactly.
    """
    cursor = 0
    for match in _SENTENCE_BOUNDARY.finditer(content):
        end = match.start()
        piece = content[cursor:end]
        stripped = piece.strip()
        if stripped:
            # ``start_offset`` points at the first non-whitespace
            # char of the sentence so the UI can highlight it
            # without leading space. ``end_offset`` points at the
            # terminal punctuation (exclusive bound on the
            # punctuation's index + 1).
            leading_ws = len(piece) - len(piece.lstrip())
            start_offset = cursor + leading_ws
            end_offset = start_offset + len(stripped)
            yield stripped, start_offset, end_offset
        cursor = match.end()

    # Tail piece after the last split boundary — or the whole string
    # when no boundary matched at all.
    if cursor < len(content):
        piece = content[cursor:]
        stripped = piece.strip()
        if stripped:
            leading_ws = len(piece) - len(piece.lstrip())
            start_offset = cursor + leading_ws
            end_offset = start_offset + len(stripped)
            yield stripped, start_offset, end_offset


def _has_citation(sentence: str) -> bool:
    """Return ``True`` when the sentence contains at least one
    ``[cite:<chunk_id>]`` marker.

    Uses :func:`re.search` rather than :func:`re.match` so the
    marker can sit anywhere in the sentence — briefs commonly
    place citations at the end (``"Revenue rose 12% [cite:c1]."``)
    but mid-sentence citations are valid too.
    """
    return _CITATION_PATTERN.search(sentence) is not None


# --------------------------------------------------------------------------- #
# Refusal-policy scan                                                         #
# --------------------------------------------------------------------------- #


def _scan_refusal_policy(sections: Mapping[str, str]) -> list[str]:
    """Run the refusal classifier against each section body.

    A match produces a short human-readable finding string of the
    form ``"<rule_id>: <reason>"`` (e.g. ``"RP-002: price_target"``).
    The shape mirrors what the LLM judge emits in
    ``off_policy_findings`` — short phrases an operator can scan.

    The classifier is invoked once per section; multi-match
    sections produce a single finding (the classifier is
    first-match-wins by design, see
    :mod:`src.research.validators.refusal_classifier`). That is
    consistent with how the LLM judge reports off-policy content
    and keeps the re-synthesis prompt compact.
    """
    findings: list[str] = []
    for section_name, content in sections.items():
        if not content:
            continue
        signal = classify_refusal(content)
        if not signal.matched:
            continue
        # ``reason`` is a ``RefusalReason`` literal (string) and
        # ``matched_rule_id`` follows the ``RP-###`` namespace —
        # both guaranteed non-None when ``matched`` is True.
        rule_id = signal.matched_rule_id or "RP-???"
        reason = signal.reason or "unknown"
        findings.append(f"{section_name}: {rule_id}: {reason}")
    return findings


# --------------------------------------------------------------------------- #
# Claim merge                                                                 #
# --------------------------------------------------------------------------- #


def _merge_claims(
    coverage_claims: list[UnsupportedClaim],
    numeric_claims: list[UnsupportedClaim],
) -> list[UnsupportedClaim]:
    """De-duplicate claims by the five-field identity tuple.

    Two claims are considered the same when ``(section, claim_text,
    start_offset, end_offset, reason)`` matches. This mirrors the
    merge rule used by :func:`src.research.judge.judge.invoke` so
    the two judges produce interchangeable shapes even when both
    paths see overlapping findings.

    Coverage claims come first so the ordering in the merged list
    reflects the section walk; numeric findings are appended in the
    order the validator emitted them.
    """
    seen: set[tuple[str, str, int, int, str]] = set()
    merged: list[UnsupportedClaim] = []
    for claim in list(coverage_claims) + list(numeric_claims):
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
        merged.append(claim)
    return merged


# --------------------------------------------------------------------------- #
# Brief-section coercion                                                      #
# --------------------------------------------------------------------------- #


def _coerce_brief_sections(
    brief: Mapping[str, str] | object,
) -> dict[str, str]:
    """Normalise accepted brief inputs into ``{section_name: content}``.

    Mirrors :func:`src.research.validators.numeric_validator._coerce_brief_sections`
    and :func:`src.research.judge.judge._coerce_brief_sections` so
    the rule-based judge sees the same sections the LLM judge does.
    Any drift would let one path score sections the other cannot
    see.
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
