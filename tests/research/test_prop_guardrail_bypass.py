"""Property 7 — Guardrail-bypass invariance.

**Validates: Requirements 14.8**

The invariant under test: for every known jailbreak seed in
``tests/research/fixtures/jailbreak/corpus.yaml``, character-level
mutations an attacker can plausibly apply MUST still be caught by
:class:`PydanticGuardrail`. A "bypass" is defined as a decision list
whose only actions are ``"allow"`` — meaning the guardrail returned
no refuse and no modify for the mutated prompt.

Scope of this test
------------------
The v1 ruleset (``src/research/guardrails/rules/v1.yaml``) is a pure
ASCII regex ruleset. It is deliberately robust against:

* ``case_swap`` — every pattern starts with ``(?i)``.
* ``extra_whitespace`` — every multi-word pattern uses ``\\s+`` between
  tokens, so *extra* whitespace between already-separated words is
  tolerated.

It is **not** robust against, and this test deliberately does **not**
exercise:

* Homoglyph / unicode-confusable substitution (Cyrillic о, Greek α,
  fullwidth letters). These bypasses are a known limitation of any
  pure-regex ASCII ruleset and are handled by the optional
  small-model classifier in Task 10.5*. Exercising them here would
  produce false-negatives against a correctly-behaved v1 ruleset.
* Whitespace injection **inside** a token (e.g. ``"ign ore"``), which
  breaks the token itself and is outside the ``\\s+`` tolerance the
  regexes are designed for. Attackers who split every keyword token
  are blocked further upstream by the classifier.

The two tests below encode exactly this contract:

1. :func:`test_raw_seeds_are_blocked` — deterministic, asserts every
   seed as-written trips at least one non-``allow`` decision. This
   is the baseline: if the ruleset cannot catch an un-mutated seed,
   the property test below is vacuously passing.
2. :func:`test_case_and_whitespace_mutations_are_blocked` — Hypothesis-
   generated. Applies ``case_swap`` anywhere, and ``extra_whitespace``
   only at positions that are already adjacent to whitespace (i.e.
   word boundaries), which is the class of mutation the ruleset's
   ``\\s+`` tolerance is designed to absorb. Asserts every generated
   mutation is still blocked.

Hypothesis configuration
------------------------
``max_examples=50`` matches the task spec — enough variety across
seeds and mutation combinations to shake out regressions without
bloating CI wall-time. ``deadline=None`` because each example runs
an ``asyncio.run`` loop over the guardrail, whose event-loop cold
start can trip the default deadline.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

import yaml
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.research.guardrails.pydantic_guard import (
    GuardrailDecision,
    PydanticGuardrail,
)

# --------------------------------------------------------------------------- #
# Seed corpus                                                                 #
# --------------------------------------------------------------------------- #


_CORPUS_PATH: Final[Path] = (
    Path(__file__).resolve().parent / "fixtures" / "jailbreak" / "corpus.yaml"
)


def _load_seeds() -> list[str]:
    """Load the jailbreak seed corpus once at module import."""
    with _CORPUS_PATH.open("r", encoding="utf-8") as fp:
        data = yaml.safe_load(fp) or {}
    seeds = data.get("seeds") or []
    if not seeds:
        raise RuntimeError(
            f"Empty jailbreak corpus at {_CORPUS_PATH}; property test cannot run.",
        )
    return [str(s) for s in seeds]


_SEEDS: Final[list[str]] = _load_seeds()


# --------------------------------------------------------------------------- #
# Mutation helpers                                                            #
# --------------------------------------------------------------------------- #


def _case_swap(text: str, flip_indices: list[int]) -> str:
    """Flip the case of every alphabetic character at ``flip_indices``.

    Non-alphabetic characters at those indices are left untouched.
    Indices outside the string bounds are ignored. This models the
    ``(?i)`` tolerance of every pattern in the v1 ruleset.
    """
    if not text:
        return text
    chars = list(text)
    for idx in flip_indices:
        if 0 <= idx < len(chars) and chars[idx].isalpha():
            ch = chars[idx]
            chars[idx] = ch.lower() if ch.isupper() else ch.upper()
    return "".join(chars)


def _inject_whitespace_at_boundaries(text: str, insert_count: int) -> str:
    """Insert extra spaces **only** at existing whitespace positions.

    Every ``\\s+`` pattern in the ruleset treats one-or-more whitespace
    characters as a single token separator, so adding extra spaces
    next to an existing space is a no-op for matching. This is the
    class of mutation the ``\\s+`` tolerance is explicitly designed
    for.

    ``insert_count`` is clamped to the number of existing whitespace
    positions in the string; if the string has no whitespace, the
    function returns ``text`` unchanged.
    """
    if insert_count <= 0 or not text:
        return text
    # Positions where the current char is whitespace. Inserting
    # before such a position only increases the run of whitespace at
    # that boundary, which ``\s+`` absorbs.
    ws_positions = [i for i, ch in enumerate(text) if ch.isspace()]
    if not ws_positions:
        return text

    out = list(text)
    # Walk positions in reverse so inserting at earlier positions
    # does not shift the indices we have yet to visit.
    n_inserts = min(insert_count, len(ws_positions))
    targets = sorted(ws_positions[-n_inserts:], reverse=True)
    for pos in targets:
        out.insert(pos, " ")
    return "".join(out)


def _is_blocked(decisions: list[GuardrailDecision]) -> bool:
    """Guardrail counts as 'blocked' when any decision is refuse|modify."""
    return any(d.action in ("refuse", "modify") for d in decisions)


async def _check_input(guard: PydanticGuardrail, text: str) -> list[GuardrailDecision]:
    """Run ``check_input`` with a fresh user id and return decisions only."""
    user_id: UUID = uuid4()
    _, decisions = await guard.check_input(user_id, text)
    return decisions


# --------------------------------------------------------------------------- #
# Hypothesis strategy                                                         #
# --------------------------------------------------------------------------- #


@st.composite
def _case_and_whitespace_mutation(draw: st.DrawFn) -> tuple[str, str]:
    """Return ``(seed, mutated)`` applying only boundary-safe mutations.

    * Case-swap a small number of random alphabetic positions.
    * Optionally inject extra whitespace at existing whitespace
      boundaries.

    Neither mutation can break the ``(?i)\\w+\\s+\\w+`` structure the
    v1 regexes rely on, so the ruleset is expected to catch 100% of
    the generated outputs — which is what the property asserts.
    """
    seed = draw(st.sampled_from(_SEEDS))

    # Budget of 0–6 case flips is plenty to exercise the ``(?i)`` path
    # without drifting the seed so far from ASCII that semantics blur.
    n_flips = draw(st.integers(min_value=0, max_value=6))
    flip_indices = draw(
        st.lists(
            st.integers(min_value=0, max_value=max(0, len(seed) - 1)),
            min_size=n_flips,
            max_size=n_flips,
        ),
    )

    # 0–3 extra whitespace insertions at existing boundaries.
    n_ws = draw(st.integers(min_value=0, max_value=3))

    mutated = _case_swap(seed, flip_indices)
    mutated = _inject_whitespace_at_boundaries(mutated, n_ws)
    return seed, mutated


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #


def test_raw_seeds_are_blocked() -> None:
    """Every unmutated seed MUST trip at least one non-``allow`` decision.

    This is the baseline invariant — if the ruleset cannot catch the
    canonical jailbreak phrasing, the property test on mutations is
    vacuously passing and tells us nothing.
    """
    guard = PydanticGuardrail(redis_client=None, requests_per_minute=10_000)

    async def _body() -> None:
        for seed in _SEEDS:
            decisions = await _check_input(guard, seed)
            assert _is_blocked(decisions), (
                f"Seed not blocked by v1 ruleset: {seed!r} "
                f"decisions={[d.model_dump() for d in decisions]}"
            )

    asyncio.run(_body())


@given(pair=_case_and_whitespace_mutation())
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_case_and_whitespace_mutations_are_blocked(
    pair: tuple[str, str],
) -> None:
    """Mutated seeds under the ruleset's tolerance class stay blocked.

    Applies only ``case_swap`` (anywhere) and ``extra_whitespace``
    (at boundaries only). Both are mutations the v1 regexes are
    explicitly designed to absorb via ``(?i)`` and ``\\s+``. Failing
    this test means a real regression in the ruleset, not a known
    limitation.
    """
    seed, mutated = pair
    guard = PydanticGuardrail(redis_client=None, requests_per_minute=10_000)
    decisions = asyncio.run(_check_input(guard, mutated))
    assert _is_blocked(decisions), (
        f"Bypass detected: seed={seed!r} mutated={mutated!r} "
        f"decisions={[d.model_dump() for d in decisions]}"
    )
