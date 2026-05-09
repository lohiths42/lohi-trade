"""Unit tests for the offline latency-budget helper (Task 19.2).

Exercises the mode-aware budget plumbing that lets both the
Orchestrator and the async-Judge fallback decision pick the
right ``research.latency_budgets.*`` value without duplicating the
``LOHI_RESEARCH_OFFLINE`` probe.

Covered surfaces:

* :func:`src.research.judge.async_fallback.budget_for_mode` — the
  pure helper that takes both budgets plus an explicit / env-sourced
  mode and returns the right millisecond value (Req 15.5, design §13.1).
* :attr:`ResearchOrchestrator.effective_full_brief_budget_ms` — the
  property that exposes the same decision to the worker layer so
  partials-stream timeouts and the async-Judge fallback (design §11.3)
  use the relaxed budget when offline.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from src.research.agents.orchestrator import ResearchOrchestrator
from src.research.judge.async_fallback import budget_for_mode


# --------------------------------------------------------------------------- #
# budget_for_mode — explicit mode                                             #
# --------------------------------------------------------------------------- #


def test_budget_for_mode_online_returns_full_brief() -> None:
    """``offline=False`` must return the reference-configuration budget."""
    assert budget_for_mode(15000, 60000, offline=False) == 15000


def test_budget_for_mode_offline_returns_offline_full_brief() -> None:
    """``offline=True`` must return the offline budget (design §13.1)."""
    assert budget_for_mode(15000, 60000, offline=True) == 60000


def test_budget_for_mode_equal_values_pass_through() -> None:
    """When both budgets are equal the helper returns that value either way.

    Pins the helper's purity — no hidden adjustment, no clipping.
    """
    assert budget_for_mode(30000, 30000, offline=False) == 30000
    assert budget_for_mode(30000, 30000, offline=True) == 30000


# --------------------------------------------------------------------------- #
# budget_for_mode — env-sourced mode                                          #
# --------------------------------------------------------------------------- #


def test_budget_for_mode_env_online(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset env + ``offline=None`` resolves to online behaviour."""
    monkeypatch.delenv("LOHI_RESEARCH_OFFLINE", raising=False)
    assert budget_for_mode(15000, 60000) == 15000


def test_budget_for_mode_env_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """``LOHI_RESEARCH_OFFLINE=true`` + ``offline=None`` picks the offline budget."""
    monkeypatch.setenv("LOHI_RESEARCH_OFFLINE", "true")
    assert budget_for_mode(15000, 60000) == 60000


@pytest.mark.parametrize("value", ["true", "True", "1", "yes", "YES"])
def test_budget_for_mode_env_truthy_variants(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """Any truthy env value activates the offline budget.

    Matches the env-var contract documented on
    :func:`src.research.providers.registry._is_offline` so both
    offline-mode helpers agree on which values are "offline".
    """
    monkeypatch.setenv("LOHI_RESEARCH_OFFLINE", value)
    assert budget_for_mode(15000, 60000) == 60000


@pytest.mark.parametrize("value", ["", "false", "0", "no", "maybe"])
def test_budget_for_mode_env_falsy_variants(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """Falsy / unknown env values leave the online budget in play."""
    monkeypatch.setenv("LOHI_RESEARCH_OFFLINE", value)
    assert budget_for_mode(15000, 60000) == 15000


def test_budget_for_mode_explicit_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit ``offline=`` argument wins over the env variable.

    This is the production invocation shape: the worker boot reads
    the env once, stores the mode, and passes it in so every
    subsequent call is pure.
    """
    monkeypatch.setenv("LOHI_RESEARCH_OFFLINE", "true")
    assert budget_for_mode(15000, 60000, offline=False) == 15000
    monkeypatch.delenv("LOHI_RESEARCH_OFFLINE", raising=False)
    assert budget_for_mode(15000, 60000, offline=True) == 60000


# --------------------------------------------------------------------------- #
# Orchestrator effective_full_brief_budget_ms                                 #
# --------------------------------------------------------------------------- #


def _build_orchestrator(
    *,
    full_brief_ms_budget: int | None = None,
    offline_full_brief_ms_budget: int | None = None,
) -> ResearchOrchestrator:
    """Construct a minimally-mocked Orchestrator for the budget tests.

    The budget accessor does not exercise any Sub_Agent / synthesiser
    / judge behaviour, so every collaborator is a plain mock. Using
    :class:`unittest.mock.Mock` / :class:`AsyncMock` here keeps the
    test framework-free and matches the pattern used elsewhere in
    this suite for Orchestrator unit tests.
    """
    return ResearchOrchestrator(
        sub_agents=[],
        synthesizer=AsyncMock(return_value={}),
        judge_fn=AsyncMock(),
        retriever=Mock(),
        partials_publisher=None,
        full_brief_ms_budget=full_brief_ms_budget,
        offline_full_brief_ms_budget=offline_full_brief_ms_budget,
    )


def test_orchestrator_effective_budget_online(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Online mode returns ``full_brief_ms_budget`` verbatim."""
    monkeypatch.delenv("LOHI_RESEARCH_OFFLINE", raising=False)
    orch = _build_orchestrator(
        full_brief_ms_budget=15000,
        offline_full_brief_ms_budget=60000,
    )
    assert orch.effective_full_brief_budget_ms == 15000


def test_orchestrator_effective_budget_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offline mode swaps in ``offline_full_brief_ms_budget`` (Req 15.5)."""
    monkeypatch.setenv("LOHI_RESEARCH_OFFLINE", "true")
    orch = _build_orchestrator(
        full_brief_ms_budget=15000,
        offline_full_brief_ms_budget=60000,
    )
    assert orch.effective_full_brief_budget_ms == 60000


def test_orchestrator_effective_budget_offline_without_offline_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offline + no offline budget falls back to the reference value.

    Pins the "``None`` means not wired" branch of the accessor: the
    offline budget is not *required*, only relaxed when present.
    """
    monkeypatch.setenv("LOHI_RESEARCH_OFFLINE", "true")
    orch = _build_orchestrator(
        full_brief_ms_budget=15000,
        offline_full_brief_ms_budget=None,
    )
    assert orch.effective_full_brief_budget_ms == 15000


def test_orchestrator_effective_budget_both_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When neither budget is wired the accessor returns ``None``.

    Callers treat ``None`` as "apply whatever default you like" — the
    Orchestrator itself never enforces a budget.
    """
    monkeypatch.delenv("LOHI_RESEARCH_OFFLINE", raising=False)
    orch = _build_orchestrator()
    assert orch.effective_full_brief_budget_ms is None


def test_orchestrator_effective_budget_reads_env_each_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The accessor re-reads the env on every access.

    Same contract the registry's ``_is_offline`` helper uses — makes
    tests that flip the env mid-run (e.g. to simulate a supervisor
    setting offline mode after boot) behave predictably.
    """
    orch = _build_orchestrator(
        full_brief_ms_budget=15000,
        offline_full_brief_ms_budget=60000,
    )
    monkeypatch.delenv("LOHI_RESEARCH_OFFLINE", raising=False)
    assert orch.effective_full_brief_budget_ms == 15000
    monkeypatch.setenv("LOHI_RESEARCH_OFFLINE", "1")
    assert orch.effective_full_brief_budget_ms == 60000
    monkeypatch.setenv("LOHI_RESEARCH_OFFLINE", "false")
    assert orch.effective_full_brief_budget_ms == 15000
