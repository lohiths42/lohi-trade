"""Single re-synthesis loop — Orchestrator-side Judge control flow (design §11.2).

The Judge_LLM (``src.research.judge.judge.invoke``) is stateless: it
scores one brief against its cited chunks and returns a
:class:`~src.research.judge.judge.JudgeReport`. The control flow that
turns that verdict into an action — "re-synthesise once on failure,
otherwise degrade quality to ``low`` and label unsupported sections
'insufficient evidence'" — lives here, one level above ``invoke``.

Separating the two keeps the judge call a pure function of its
inputs (Req 16.12–16.17) and concentrates the Req 16.18–16.19
state machine in one place the Orchestrator wires into its graph
(design §3.5, §11.2).

Satisfies
---------
* Req 16.18 — ``safe_to_display == False`` OR minimum per-section
  groundedness below ``research.judge.min_score`` triggers exactly one
  re-synthesis pass. The Judge's ``unsupported_claims`` list plus the
  numeric-validator findings are fed back into the Report_Synthesizer's
  context (design §11.2 "feedback = {unsupported_claims,
  numeric_validator_findings}").
* Req 16.19 — if the re-synthesised brief still fails, the final brief
  is marked ``quality="low"`` and every section that carries unsupported
  claims is replaced with the exact string
  ``"insufficient evidence"`` (design §11.2 "mark quality=low, redact
  'insufficient evidence' where sections have unsupported claims").

Design references
-----------------
* §3.5 — Orchestrator graph: ``synthesise → numeric validator → Judge
  → re-synthesis? (≤1x) → emit ResearchBrief``.
* §11.2 — pass/fail state machine implemented here.
* §11.1 — Judge prompt structure (consumed via the ``judge_fn`` callable).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any, Literal

from src.research.judge.judge import JudgeReport
from src.research.validators.types import UnsupportedClaim

__all__ = [
    "INSUFFICIENT_EVIDENCE",
    "Quality",
    "ResynthesisOutcome",
    "run_resynthesis_loop",
]


# --------------------------------------------------------------------------- #
# Public constants + types                                                    #
# --------------------------------------------------------------------------- #

#: Label written into every section the Orchestrator cannot trust after
#: the re-synthesis failed (Req 16.19, design §11.2). Stored as a module
#: constant so the dashboard renderer and the persistence layer can
#: compare against the exact same string — any drift between sites
#: silently downgrades the redaction.
INSUFFICIENT_EVIDENCE: str = "insufficient evidence"


#: Canonical quality label attached to the final :class:`ResearchBrief`.
#:
#: * ``"high"``  — Judge passed on the first pass (no re-synthesis ran).
#: * ``"medium"`` — first pass failed, re-synthesis passed (design
#:   §11.2 "else emit final after re-synth").
#: * ``"low"``   — both passes failed; unsupported sections were
#:   redacted (Req 16.19).
Quality = Literal["high", "medium", "low"]


class ResynthesisOutcome:
    """Return value of :func:`run_resynthesis_loop`.

    Carries the final (possibly re-synthesised, possibly redacted)
    brief, the :class:`JudgeReport` from the Judge call that produced
    the terminal decision, and the :data:`Quality` label to record on
    the ``ResearchBrief`` (Req 16.19, design §4.1
    ``research_brief_sections.quality``).

    A lightweight class rather than a :class:`NamedTuple` or
    :class:`pydantic.BaseModel` because (a) the brief is duck-typed
    — ``Mapping[str, str]`` or any object exposing section attributes
    — and Pydantic cannot validate that cheaply without a full brief
    schema (which lands in Task 13.8), and (b) keeping the container
    a plain class keeps this module free of Pydantic imports, which
    matters for the Orchestrator's import graph.

    Attributes
    ----------
    brief:
        The brief the Orchestrator should surface. When
        ``quality == "low"``, every section whose name appears in
        ``unsupported_sections`` has been replaced with
        :data:`INSUFFICIENT_EVIDENCE`. Shape mirrors the input brief
        (``dict`` for mapping inputs, best-effort copy for object inputs).
    judge_report:
        The :class:`JudgeReport` from the Judge pass that terminated
        the loop — the first pass if it succeeded, the second (and
        final) pass otherwise. Carries ``retry_count`` so downstream
        persistence (``research_judge_reports.retry_count``, design
        §4.1) can record how many passes ran.
    quality:
        The :data:`Quality` label the caller stamps onto every
        :class:`~backend-gateway.app.models.research.brief_section`
        row (design §4.1).
    unsupported_sections:
        Set of section names that carried unsupported claims in the
        terminal judge report. Empty when ``quality`` is ``"high"``
        or ``"medium"``. Populated (and used for redaction) when
        ``quality`` is ``"low"``. Exposed so the gateway can surface
        the list to the UI's "verifying…" / "insufficient evidence"
        banners (Req 16.19, design §3.12 endpoint surface).

    """

    __slots__ = ("brief", "judge_report", "quality", "unsupported_sections")

    def __init__(
        self,
        *,
        brief: Mapping[str, str] | object,
        judge_report: JudgeReport,
        quality: Quality,
        unsupported_sections: frozenset[str] = frozenset(),
    ) -> None:
        self.brief = brief
        self.judge_report = judge_report
        self.quality: Quality = quality
        self.unsupported_sections = unsupported_sections

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"ResynthesisOutcome(quality={self.quality!r}, "
            f"retry_count={self.judge_report.retry_count}, "
            f"unsupported_sections={sorted(self.unsupported_sections)!r})"
        )


# --------------------------------------------------------------------------- #
# Callable contracts (duck-typed)                                             #
# --------------------------------------------------------------------------- #
#
# The loop takes two async callables. They are duck-typed
# (``Callable[..., Awaitable[...]]``) rather than declared as formal
# ``Protocol``s because the Orchestrator will bind them via
# ``functools.partial`` — the partial can capture Report_Synthesizer /
# Judge state, the run_id, the chunk set, and the LLM config — and a
# ``Protocol`` with fixed positional arguments would be too rigid.
#
# SynthesizeFn contract
# ---------------------
# ``async def synthesize(
#     *, prior_brief, unsupported_claims, numeric_findings
# ) -> brief``
#
# The caller guarantees ``prior_brief`` is the brief produced by the
# previous synthesis step (first-pass: the Report_Synthesizer's output;
# second-pass: this function does not call ``synthesize_fn`` again). The
# callable MUST return a new brief with the same shape (same section
# keys / attributes) as ``prior_brief`` so downstream code can merge
# section-wise without guessing the schema.
#
# JudgeFn contract
# ----------------
# ``async def judge(
#     *, brief, retry_count
# ) -> JudgeReport``
#
# The caller binds the Judge's ``run_id``, ``chunks``, ``numeric_findings``,
# ``min_score``, and ``llm`` / ``llm_config`` via ``functools.partial``.
# The loop only supplies the brief being scored and the running
# ``retry_count`` (which the loop owns — see design §11.2).

SynthesizeFn = Callable[..., Awaitable[Any]]
JudgeFn = Callable[..., Awaitable[JudgeReport]]


# --------------------------------------------------------------------------- #
# Public entry point                                                          #
# --------------------------------------------------------------------------- #


async def run_resynthesis_loop(
    *,
    synthesize_fn: SynthesizeFn,
    judge_fn: JudgeFn,
    brief: Mapping[str, str] | object,
    numeric_findings: Iterable[UnsupportedClaim] = (),
    min_score: float = 0.7,
    max_retries: int = 1,
) -> ResynthesisOutcome:
    """Run the Judge / re-synthesise / Judge loop defined in design §11.2.

    Exactly one re-synthesis is allowed (``max_retries=1`` per Req 16.18);
    the parameter is exposed so the Orchestrator can force-disable
    re-synthesis in degraded modes (e.g. budget_exhausted) without a
    separate code path.

    Parameters
    ----------
    synthesize_fn:
        Orchestrator-supplied callable that re-invokes the
        Report_Synthesizer with the Judge's ``unsupported_claims`` list
        and the numeric validator's findings as additional context
        (design §11.2 "feedback = {unsupported_claims,
        numeric_validator_findings}"). Called at most once. See the
        module-level "SynthesizeFn contract" comment for its signature.
    judge_fn:
        Orchestrator-supplied callable that re-scores a brief. Called
        once on the original brief; called a second time on the
        re-synthesised brief iff the first call failed. See the
        module-level "JudgeFn contract" comment.
    brief:
        The brief to score. Accepts either a ``Mapping[str, str]``
        (section name → content_md) or any object exposing the
        canonical ``ResearchBrief`` section attributes. Matches the
        duck type already supported by :func:`judge.invoke`.
    numeric_findings:
        Findings from the deterministic numeric validator (Task 11.1).
        Forwarded to ``synthesize_fn`` verbatim so the re-synthesis
        prompt includes them (design §11.2 feedback block). An empty
        iterable is the healthy case.
    min_score:
        Operator-configured minimum per-section groundedness score.
        The Judge's own ``safe_to_display`` flag is cross-checked
        against this (design §11.1 override); the loop re-checks it
        here so a Judge that mis-classifies a sub-threshold score as
        safe still triggers re-synthesis (Req 16.18). Defaults to the
        design §7.1 value of 0.7.
    max_retries:
        Upper bound on re-synthesis passes. Per Req 16.18 the canonical
        value is 1; exposed so the caller can set it to 0 to disable
        re-synthesis entirely (e.g. when the run is already flagged
        ``budget_exhausted``). Values > 1 are accepted but violate
        Req 16.18 — the caller is trusted to enforce the spec.

    Returns
    -------
    ResynthesisOutcome
        Carries the final brief (possibly redacted), the terminal
        :class:`JudgeReport`, and the :data:`Quality` label to stamp
        on the ``ResearchBrief``.

    Raises
    ------
    ValueError
        When ``max_retries`` is negative — negative retry budgets are
        always a caller bug.

    """
    if max_retries < 0:
        raise ValueError(
            f"max_retries must be non-negative; got {max_retries}",
        )

    # -------------------------------------------------------------- #
    # First pass — score the original brief.                          #
    # -------------------------------------------------------------- #
    first_report = await judge_fn(brief=brief, retry_count=0)

    if _is_passing(first_report, min_score=min_score):
        # Design §11.2 happy path: "JudgeReport.safe_to_display &&
        # min(groundedness_score) >= min_score  └─► emit final".
        return ResynthesisOutcome(
            brief=brief,
            judge_report=first_report,
            quality="high",
        )

    # First pass failed. If the operator disabled re-synthesis (max_retries=0)
    # we short-circuit straight to quality=low so the rest of the function
    # does not need to special-case the "no retries allowed" branch.
    if max_retries < 1:
        redacted, unsupported_sections = _redact_unsupported_sections(
            brief, first_report,
        )
        return ResynthesisOutcome(
            brief=redacted,
            judge_report=first_report,
            quality="low",
            unsupported_sections=unsupported_sections,
        )

    # -------------------------------------------------------------- #
    # Re-synthesis pass — feed the Judge's unsupported claims +       #
    # numeric findings back into the Report_Synthesizer.              #
    # -------------------------------------------------------------- #
    #
    # ``numeric_findings`` is passed separately from
    # ``first_report.unsupported_claims`` because the deterministic
    # validator's verdict is authoritative (Req 16.27) and the
    # Report_Synthesizer's prompt template treats the two lists
    # differently — numeric drifts come with cited chunks to cross-
    # reference, Judge-flagged claims come with section offsets.
    # Pre-materialising ``numeric_findings`` into a tuple means callers
    # can pass a generator without it being exhausted on the first
    # iteration (the synthesize_fn is called at most once, so a
    # single-pass iterable would normally be fine; the tuple also
    # stabilises the prompt ordering across ``synthesize_fn`` implementations).
    numeric_findings_list = tuple(numeric_findings)

    resynthesised_brief = await synthesize_fn(
        prior_brief=brief,
        unsupported_claims=tuple(first_report.unsupported_claims),
        numeric_findings=numeric_findings_list,
    )

    # Second pass — score the re-synthesised brief. ``retry_count=1``
    # tells the Judge this is the terminal pass so downstream
    # persistence rows line up with design §4.1's
    # ``research_judge_reports.retry_count`` column.
    second_report = await judge_fn(brief=resynthesised_brief, retry_count=1)

    if _is_passing(second_report, min_score=min_score):
        # Design §11.2 "else if retry_count == 0: …rerun Judge"
        # followed by the happy path on the re-scored brief.
        return ResynthesisOutcome(
            brief=resynthesised_brief,
            judge_report=second_report,
            quality="medium",
        )

    # Second pass failed — Req 16.19. Redact the unsupported sections
    # on the *re-synthesised* brief (it is the most recent, best-effort
    # output) and return quality=low.
    redacted, unsupported_sections = _redact_unsupported_sections(
        resynthesised_brief, second_report,
    )
    return ResynthesisOutcome(
        brief=redacted,
        judge_report=second_report,
        quality="low",
        unsupported_sections=unsupported_sections,
    )


# --------------------------------------------------------------------------- #
# Pass/fail predicate                                                         #
# --------------------------------------------------------------------------- #


def _is_passing(report: JudgeReport, *, min_score: float) -> bool:
    """Design §11.2 pass predicate.

    A report passes iff ``safe_to_display`` is ``True`` **and** the
    minimum per-section groundedness score is at or above
    ``min_score``. The Judge's own ``safe_to_display`` already folds
    in the ``min_score`` cut-off (see ``_report_from_parsed`` in
    :mod:`judge`), but we re-check it here so a stricter operator
    ``min_score`` (passed through this loop) still trips the
    re-synthesis even when the Judge was invoked with a laxer default.
    An empty ``groundedness_score`` dict means
    ``JudgeReport.min_score()`` returns ``0.0`` and the predicate
    fails — which is the conservative behaviour when the Judge
    produced no per-section scores (design §3.7 ``JudgeReport.min_score``).
    """
    if not report.safe_to_display:
        return False
    if report.min_score() < min_score:
        return False
    return True


# --------------------------------------------------------------------------- #
# Redaction                                                                   #
# --------------------------------------------------------------------------- #


def _redact_unsupported_sections(
    brief: Mapping[str, str] | object,
    report: JudgeReport,
) -> tuple[Any, frozenset[str]]:
    """Replace every unsupported section's body with :data:`INSUFFICIENT_EVIDENCE`.

    Req 16.19 and design §11.2 require two things of the final
    brief: (a) ``quality="low"``, which the caller stamps, and (b)
    "redact or label the unsupported sections as 'insufficient
    evidence'". This helper owns (b).

    Handling
    --------
    * ``Mapping`` input → returned as a plain ``dict`` with the same
      keys. Sections identified as unsupported have their value
      replaced; every other section is passed through verbatim. We
      do not mutate the caller's mapping.
    * Object input → mutated in place via ``setattr``. A fresh copy
      is not returned because the brief may be a large Pydantic
      model and we do not want to take a ``copy.deepcopy`` on every
      failed run; the caller already treats the brief as write-once
      once the loop returns.

    The set of "unsupported section names" is the set of
    ``UnsupportedClaim.section`` values across
    ``report.unsupported_claims`` — the same section names the
    numeric validator and the Judge agreed on (design §3.7, §3.8).
    Section names the brief does not contain (e.g. the synthetic
    ``"<judge_error>"`` section emitted by
    :func:`src.research.judge.judge._fallback_report`) are filtered
    out so we never invent a section that was not in the original
    brief.
    """
    # Collect every section name the Judge or numeric validator
    # flagged. ``frozenset`` makes the returned object hashable and
    # signals to callers that order is not meaningful.
    flagged_sections = frozenset(
        claim.section
        for claim in report.unsupported_claims
        # Drop the synthetic fallback section so we never try to
        # redact a section the brief never had.
        if claim.section and not claim.section.startswith("<")
    )

    if isinstance(brief, Mapping):
        redacted: dict[str, str] = {}
        applied: set[str] = set()
        for key, value in brief.items():
            key_str = str(key)
            if key_str in flagged_sections:
                redacted[key_str] = INSUFFICIENT_EVIDENCE
                applied.add(key_str)
            else:
                # Coerce to str so the returned dict has a uniform
                # value type regardless of the caller's input.
                redacted[key_str] = "" if value is None else str(value)
        return redacted, frozenset(applied)

    # Object input — mutate in place. Only redact sections the object
    # actually exposes so we do not create spurious attributes.
    applied_obj: set[str] = set()
    for section in flagged_sections:
        if hasattr(brief, section):
            try:
                setattr(brief, section, INSUFFICIENT_EVIDENCE)
                applied_obj.add(section)
            except (AttributeError, TypeError):
                # Frozen dataclass / Pydantic model with
                # ``frozen=True``: the caller will surface the
                # failure via ``quality="low"`` anyway, so falling
                # through without raising keeps the loop total.
                continue
    return brief, frozenset(applied_obj)
