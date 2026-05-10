"""Property 10 — Refusal policy.

**Validates: Requirements 14.11, 16.28**

The invariant under test has two complementary halves, each expressed
as its own Hypothesis test so a failing assertion points at the right
half of the property:

1. **Positive path** — :func:`test_refusal_policy_prompts_are_classified`:
   for every prompt composed from the ``verb + action + entity``
   templates in ``tests/research/fixtures/refusal/corpus.yaml``,
   :func:`classify_refusal` MUST return ``matched=True`` with the
   ``reason`` and ``matched_rule_id`` matching the category the
   template was drawn from, plus a non-empty ``matched_text`` so
   audit logs and the guardrail layer can show users exactly which
   phrase tripped the policy (Req 14.11 "a refusal with an
   explanation", Req 16.28 listing the six refusal categories).

2. **Negative path** — :func:`test_neutral_analytical_prompts_pass`:
   prompts composed from research-style templates (``summarise``,
   ``describe``, ``explain`` + neutral nouns + entities) MUST NOT
   trigger a refusal. This is the regression guard that the
   classifier does not over-refuse on legitimate research queries
   which happen to mention refusal-policy keywords such as
   ``"buyback"``, ``"share transfer"``, or ``"target market"``.

Scope of this test
------------------
Per design §3.8 / §11.4, :func:`classify_refusal` is the
**deterministic component** of the refusal behaviour consumed by the
Guardrail_Layer's input phase and the offline rule-based Judge. The
task description says *"the system returns a refusal with an
explanation and produces no recommendation"* — the
:class:`RefusalSignal` is precisely that explanation (the
``reason``/``matched_rule_id``/``matched_text`` triple), and
downstream wiring in the Guardrail + Judge consumes this signal to
short-circuit into the :data:`REFUSAL_POLICY_BLOCK` response before
any Sub_Agent is invoked (design §3.6, §10.1). A ``matched=True``
signal is therefore proof that no recommendation, price target, or
trade suggestion could be produced for that prompt.

The test fuzzes over the Cartesian product of verb/action/entity
fragments rather than raw strings so Hypothesis's shrinker can
minimise to the smallest failing ``(category, template, filler)``
triple when a regression surfaces.

Hypothesis configuration
------------------------
``max_examples=200`` gives the strategy room to cover all six
categories and their template variants without bloating CI wall-
time (each example is a pure-Python regex scan, sub-millisecond).
``deadline=None`` because Hypothesis's default deadline can flake on
the first few examples while YAML loading warms the module cache.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import yaml
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.research.validators.refusal_classifier import (
    RefusalSignal,
    classify_refusal,
)

# --------------------------------------------------------------------------- #
# Corpus                                                                      #
# --------------------------------------------------------------------------- #


_CORPUS_PATH: Final[Path] = (
    Path(__file__).resolve().parent / "fixtures" / "refusal" / "corpus.yaml"
)


def _load_corpus() -> Mapping[str, Any]:
    """Load the refusal corpus once at module import.

    The corpus drives both the template-composition strategies below
    and the negative-path generators. Loading eagerly (rather than
    inside the strategies) keeps Hypothesis's shrinker simple: the
    strategies become pure functions over immutable lists.
    """
    with _CORPUS_PATH.open("r", encoding="utf-8") as fp:
        data = yaml.safe_load(fp) or {}
    if not data.get("categories"):
        raise RuntimeError(
            f"Empty or missing 'categories' in {_CORPUS_PATH}; "
            "property test cannot run.",
        )
    if not data.get("entities"):
        raise RuntimeError(
            f"Missing 'entities' list in {_CORPUS_PATH}; "
            "property test cannot run.",
        )
    if not data.get("negative"):
        raise RuntimeError(
            f"Missing 'negative' section in {_CORPUS_PATH}; "
            "negative-path test cannot run.",
        )
    return data


_CORPUS: Final[Mapping[str, Any]] = _load_corpus()
_ENTITIES: Final[list[str]] = list(_CORPUS["entities"])
_CATEGORY_NAMES: Final[list[str]] = list(_CORPUS["categories"].keys())


# --------------------------------------------------------------------------- #
# Positive strategy — compose refusal-policy prompts                          #
# --------------------------------------------------------------------------- #


# Light prefixes/suffixes so the generated prompts read like real
# user input without changing the semantic content. Kept to a short,
# neutral list so they cannot accidentally introduce refusal-policy
# keywords of their own (e.g. no "buy" in any prefix).
_PREFIXES: Final[tuple[str, ...]] = (
    "",
    "Hi, ",
    "Hey, ",
    "Quick question: ",
    "Please, ",
    "Quickly ",
)
_SUFFIXES: Final[tuple[str, ...]] = (
    "",
    ".",
    "?",
    " today.",
    " now.",
    " please.",
)


def _render_template(template: str, slots: Mapping[str, str]) -> str:
    """Substitute ``{slot}`` placeholders in ``template`` from ``slots``.

    Simpler than :meth:`str.format` because the templates may
    contain non-slot braces (e.g. Python-ish code samples like
    ``os.system('ls')``) and we want those left intact. We replace
    each ``{key}`` occurrence literally; unknown placeholders are
    left untouched rather than raising.
    """
    result = template
    for key, value in slots.items():
        result = result.replace("{" + key + "}", value)
    return result


@st.composite
def _refusal_prompt(draw: st.DrawFn) -> tuple[str, str, str, str]:
    """Compose a refusal-policy prompt plus its expected category.

    Returns a 4-tuple ``(category, rule_id, reason, prompt)`` so the
    assertion can check both classifier match and that the match
    lands on the expected category (which proves the explanation
    surfaced to the user is the right shape — Req 14.11).

    Composition:

    1. Pick a category uniformly from the corpus.
    2. Pick a template from that category.
    3. For every ``{slot}`` in the template, draw a value from the
       category's same-named slot list (or the top-level
       ``entities`` list for the universal ``{entity}`` slot).
    4. Wrap with a prefix/suffix to shake out sensitivity to
       surrounding whitespace and punctuation.
    """
    category = draw(st.sampled_from(_CATEGORY_NAMES))
    cat_block = _CORPUS["categories"][category]

    rule_id: str = cat_block["rule_id"]
    reason: str = cat_block["reason"]
    templates: list[str] = list(cat_block["templates"])
    template = draw(st.sampled_from(templates))

    # Resolve every placeholder the template needs. The corpus uses
    # plural keys (``actions``, ``verbs``) that expand to their
    # singular slot names (``action``, ``verb``) inside the template
    # — this mapping keeps the template readable while letting the
    # YAML list carry the pool.
    slot_pools: dict[str, list[str]] = {
        "entity": _ENTITIES,
    }
    plural_to_singular = {
        "actions": "action",
        "actions_ing": "action_ing",
        "verbs": "verb",
        "timeframes": "timeframe",
        "order_types": "order_type",
        "venues": "venue",
        "quantities": "quantity",
        "assets": "asset",
    }
    for plural_key, singular_key in plural_to_singular.items():
        pool = cat_block.get(plural_key)
        if pool:
            slot_pools[singular_key] = list(pool)

    slots: dict[str, str] = {}
    # Only fill slots that appear in the chosen template — avoids
    # spurious draws that would confuse the shrinker.
    for slot_name, pool in slot_pools.items():
        if ("{" + slot_name + "}") in template:
            slots[slot_name] = draw(st.sampled_from(pool))

    body = _render_template(template, slots)
    prefix = draw(st.sampled_from(_PREFIXES))
    suffix = draw(st.sampled_from(_SUFFIXES))
    prompt = f"{prefix}{body}{suffix}"
    return category, rule_id, reason, prompt


# --------------------------------------------------------------------------- #
# Positive test                                                               #
# --------------------------------------------------------------------------- #


@given(case=_refusal_prompt())
@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_refusal_policy_prompts_are_classified(
    case: tuple[str, str, str, str],
) -> None:
    """Every composed refusal prompt is flagged with the right category.

    Validates: Requirements 14.11, 16.28.

    For every ``(category, template, slots)`` triple drawn from the
    corpus, :func:`classify_refusal` returns a :class:`RefusalSignal`
    with:

    * ``matched=True`` — the prompt is recognised as a refusal.
    * ``reason`` matching the expected category — the explanation
      surfaced to the user identifies the right policy bucket.
    * ``matched_rule_id`` matching the category's ``RP-xxx`` id —
      audit logs carry a stable pointer back to the pattern that
      fired.
    * ``matched_text`` is a non-empty string — the guardrail layer
      has a concrete snippet to show the user alongside the refusal.

    A failure here means the deterministic refusal component does
    not detect one of the canonical phrasings that the ``Refusal_Policy``
    (design §10.1) is documented to cover — i.e. the system could
    produce a recommendation, price target, or trade suggestion for
    that prompt instead of refusing.
    """
    expected_category, expected_rule_id, expected_reason, prompt = case
    signal = classify_refusal(prompt)

    assert signal.matched is True, (
        f"Refusal-policy prompt slipped through the classifier: "
        f"prompt={prompt!r} expected_category={expected_category!r}"
    )
    assert signal.reason == expected_reason, (
        f"Wrong refusal reason: prompt={prompt!r} "
        f"expected={expected_reason!r} got={signal.reason!r}"
    )
    assert signal.matched_rule_id == expected_rule_id, (
        f"Wrong rule id: prompt={prompt!r} "
        f"expected={expected_rule_id!r} got={signal.matched_rule_id!r}"
    )
    # The explanation (``matched_text``) is what surfaces alongside
    # the refusal. An empty match would still satisfy ``matched=True``
    # in a hypothetical buggy classifier, so assert it explicitly.
    assert signal.matched_text is not None, (
        f"matched_text is None for refusal prompt: {prompt!r}"
    )
    assert signal.matched_text.strip() != "", (
        f"matched_text is empty for refusal prompt: {prompt!r}"
    )


# --------------------------------------------------------------------------- #
# Negative strategy — neutral analytical prompts                              #
# --------------------------------------------------------------------------- #


_NEG_BLOCK: Final[Mapping[str, Any]] = _CORPUS["negative"]
_NEG_VERBS: Final[list[str]] = list(_NEG_BLOCK.get("verbs") or [])
_NEG_NOUNS: Final[list[str]] = list(_NEG_BLOCK.get("nouns") or [])
_NEG_STANDALONE: Final[list[str]] = list(_NEG_BLOCK.get("standalone") or [])


@st.composite
def _neutral_prompt(draw: st.DrawFn) -> str:
    """Compose a neutral analytical prompt.

    Two shapes are exercised so the negative path covers both the
    free-form sentences maintainers hand-curate (``standalone``) and
    the Cartesian product of ``verb + noun + entity`` that the
    strategy generates at scale:

    * **Composed** — ``"{verb} {noun} for {entity}"``, e.g.
      ``"Summarise the annual report for RELIANCE."``.
    * **Standalone** — a single string drawn verbatim from the
      corpus.

    The composed shape deliberately uses neutral research verbs
    (``summarise``, ``describe``, ``explain``) and nouns that mention
    refusal-policy keywords in legitimate research context
    (``buyback``, ``share transfer``, ``target market``) — any
    classifier over-refusal on these is a real regression.
    """
    shape = draw(st.sampled_from(("composed", "standalone")))

    if shape == "standalone" and _NEG_STANDALONE:
        return draw(st.sampled_from(_NEG_STANDALONE))

    verb = draw(st.sampled_from(_NEG_VERBS))
    noun = draw(st.sampled_from(_NEG_NOUNS))
    entity = draw(st.sampled_from(_ENTITIES))
    suffix = draw(st.sampled_from(_SUFFIXES))
    return f"{verb} {noun} for {entity}{suffix}"


# --------------------------------------------------------------------------- #
# Negative test                                                               #
# --------------------------------------------------------------------------- #


@given(prompt=_neutral_prompt())
@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_neutral_analytical_prompts_pass(prompt: str) -> None:
    """Neutral research prompts are NOT classified as refusals.

    Validates: Requirements 14.11, 16.28.

    Guards against over-refusal — the classifier is applied to user
    prompts, so phrases like ``"buyback history"``, ``"share transfer
    rules"``, or ``"target market"`` which appear in legitimate
    research queries must not flip the refusal bit. A failure here
    means the classifier would block a user from reading a research
    brief about a company, which is the opposite of the intended
    Refusal_Policy scope (design §10.1).

    The no-match contract also requires the sentinel
    :data:`RefusalSignal.NO_MATCH` to be returned (so callers using
    identity comparison in hot paths behave correctly).
    """
    signal = classify_refusal(prompt)
    assert signal.matched is False, (
        f"Neutral analytical prompt was classified as refusal: "
        f"prompt={prompt!r} reason={signal.reason!r} "
        f"rule_id={signal.matched_rule_id!r} "
        f"matched_text={signal.matched_text!r}"
    )
    # All three explanatory fields must be ``None`` on a no-match
    # so callers never see a partially-populated signal.
    assert signal.reason is None
    assert signal.matched_rule_id is None
    assert signal.matched_text is None
    # Identity check — the module promises a shared sentinel.
    assert signal is RefusalSignal.NO_MATCH
