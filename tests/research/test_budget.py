"""Unit tests for :class:`TokenBudget` (Task 13.9).

Exercises the contract documented on
:mod:`src.research.agents.budget`:

* Defaults match Req 12.3 (32 000 / 8 000).
* ``add`` records usage and returns an immutable
  :class:`BudgetTotals` snapshot.
* ``is_exhausted`` uses strict ``>`` semantics (the run that lands
  exactly on the limit is still inside budget) and accepts look-ahead
  estimates.
* Concurrent ``add`` calls from many ``asyncio`` tasks never lose a
  token.
* Invalid inputs — non-positive limits, negative tokens, negative
  estimates — raise :class:`ValueError`.
"""

from __future__ import annotations

import asyncio

import pytest

from src.research.agents.budget import (
    DEFAULT_INPUT_LIMIT,
    DEFAULT_OUTPUT_LIMIT,
    BudgetTotals,
    TokenBudget,
)

# --------------------------------------------------------------------------- #
# Construction                                                                #
# --------------------------------------------------------------------------- #


class TestConstruction:
    def test_defaults_match_req_12_3(self) -> None:
        budget = TokenBudget()
        assert budget.input_limit == DEFAULT_INPUT_LIMIT == 32_000
        assert budget.output_limit == DEFAULT_OUTPUT_LIMIT == 8_000
        assert budget.totals() == BudgetTotals(0, 0)

    def test_custom_limits(self) -> None:
        budget = TokenBudget(input_limit=100, output_limit=50)
        assert budget.input_limit == 100
        assert budget.output_limit == 50

    def test_zero_input_limit_rejected(self) -> None:
        with pytest.raises(ValueError, match="input_limit"):
            TokenBudget(input_limit=0)

    def test_negative_input_limit_rejected(self) -> None:
        with pytest.raises(ValueError, match="input_limit"):
            TokenBudget(input_limit=-1)

    def test_zero_output_limit_rejected(self) -> None:
        with pytest.raises(ValueError, match="output_limit"):
            TokenBudget(output_limit=0)

    def test_negative_output_limit_rejected(self) -> None:
        with pytest.raises(ValueError, match="output_limit"):
            TokenBudget(output_limit=-10)


# --------------------------------------------------------------------------- #
# add + totals                                                                #
# --------------------------------------------------------------------------- #


class TestAddAndTotals:
    @pytest.mark.asyncio
    async def test_single_add_updates_totals(self) -> None:
        budget = TokenBudget(input_limit=1_000, output_limit=500)
        totals = await budget.add(100, 50)
        assert totals == BudgetTotals(100, 50)
        assert budget.totals() == BudgetTotals(100, 50)

    @pytest.mark.asyncio
    async def test_repeated_adds_accumulate(self) -> None:
        budget = TokenBudget(input_limit=10_000, output_limit=5_000)
        await budget.add(100, 10)
        await budget.add(200, 20)
        totals = await budget.add(300, 30)
        assert totals == BudgetTotals(600, 60)

    @pytest.mark.asyncio
    async def test_add_returns_snapshot_not_alias(self) -> None:
        """Each call returns a fresh snapshot, so later adds can't mutate it."""
        budget = TokenBudget(input_limit=100, output_limit=100)
        snapshot_1 = await budget.add(10, 5)
        await budget.add(20, 10)
        # The first snapshot stays the values it had when it was returned.
        assert snapshot_1 == BudgetTotals(10, 5)

    @pytest.mark.asyncio
    async def test_zero_tokens_accepted(self) -> None:
        """Zero output tokens are legitimate (empty completion)."""
        budget = TokenBudget(input_limit=100, output_limit=100)
        totals = await budget.add(10, 0)
        assert totals == BudgetTotals(10, 0)

    @pytest.mark.asyncio
    async def test_negative_input_tokens_rejected(self) -> None:
        budget = TokenBudget()
        with pytest.raises(ValueError, match="input_tokens"):
            await budget.add(-1, 0)

    @pytest.mark.asyncio
    async def test_negative_output_tokens_rejected(self) -> None:
        budget = TokenBudget()
        with pytest.raises(ValueError, match="output_tokens"):
            await budget.add(0, -5)


# --------------------------------------------------------------------------- #
# is_exhausted                                                                #
# --------------------------------------------------------------------------- #


class TestIsExhausted:
    @pytest.mark.asyncio
    async def test_fresh_budget_not_exhausted(self) -> None:
        budget = TokenBudget(input_limit=100, output_limit=50)
        assert await budget.is_exhausted() is False

    @pytest.mark.asyncio
    async def test_exactly_at_limit_not_exhausted(self) -> None:
        """Strict ``>`` semantics: the limit itself is inside budget."""
        budget = TokenBudget(input_limit=100, output_limit=50)
        await budget.add(100, 50)
        assert await budget.is_exhausted() is False

    @pytest.mark.asyncio
    async def test_one_over_input_limit_is_exhausted(self) -> None:
        budget = TokenBudget(input_limit=100, output_limit=50)
        await budget.add(101, 0)
        assert await budget.is_exhausted() is True

    @pytest.mark.asyncio
    async def test_one_over_output_limit_is_exhausted(self) -> None:
        budget = TokenBudget(input_limit=100, output_limit=50)
        await budget.add(0, 51)
        assert await budget.is_exhausted() is True

    @pytest.mark.asyncio
    async def test_estimate_pushes_over_input(self) -> None:
        """Look-ahead: current + estimate > limit → exhausted."""
        budget = TokenBudget(input_limit=100, output_limit=50)
        await budget.add(90, 10)
        assert await budget.is_exhausted(next_input_estimate=11) is True
        # 10 would land exactly on the limit — still inside.
        assert await budget.is_exhausted(next_input_estimate=10) is False

    @pytest.mark.asyncio
    async def test_estimate_pushes_over_output(self) -> None:
        budget = TokenBudget(input_limit=100, output_limit=50)
        await budget.add(10, 40)
        assert await budget.is_exhausted(next_output_estimate=11) is True
        assert await budget.is_exhausted(next_output_estimate=10) is False

    @pytest.mark.asyncio
    async def test_either_limit_triggers(self) -> None:
        """Exhaustion is an OR over the two limits, not an AND."""
        budget = TokenBudget(input_limit=100, output_limit=50)
        await budget.add(101, 0)  # over input, under output
        assert await budget.is_exhausted() is True

    @pytest.mark.asyncio
    async def test_negative_input_estimate_rejected(self) -> None:
        budget = TokenBudget()
        with pytest.raises(ValueError, match="next_input_estimate"):
            await budget.is_exhausted(next_input_estimate=-1)

    @pytest.mark.asyncio
    async def test_negative_output_estimate_rejected(self) -> None:
        budget = TokenBudget()
        with pytest.raises(ValueError, match="next_output_estimate"):
            await budget.is_exhausted(next_output_estimate=-1)

    def test_sync_variant_matches_async(self) -> None:
        budget = TokenBudget(input_limit=100, output_limit=50)
        assert budget.is_exhausted_sync() is False
        # Drive it over via a synchronous add in a fresh event loop.
        # ``asyncio.run`` creates a loop, runs the coroutine, and
        # closes the loop — pytest-asyncio's own loop is untouched.
        asyncio.run(budget.add(110, 0))
        assert budget.is_exhausted_sync() is True

    def test_sync_negative_estimate_rejected(self) -> None:
        budget = TokenBudget()
        with pytest.raises(ValueError):
            budget.is_exhausted_sync(next_input_estimate=-1)
        with pytest.raises(ValueError):
            budget.is_exhausted_sync(next_output_estimate=-1)


# --------------------------------------------------------------------------- #
# Concurrency                                                                 #
# --------------------------------------------------------------------------- #


class TestConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_adds_preserve_total(self) -> None:
        """N concurrent ``add(1, 1)`` calls → totals exactly (N, N)."""
        # Keep N well below the default limits so we can count up.
        budget = TokenBudget(input_limit=100_000, output_limit=100_000)
        n = 500

        async def one_call() -> None:
            await budget.add(1, 1)

        await asyncio.gather(*(one_call() for _ in range(n)))
        assert budget.totals() == BudgetTotals(n, n)

    @pytest.mark.asyncio
    async def test_concurrent_adds_with_varied_sizes(self) -> None:
        """Totals == sum of inputs regardless of scheduling."""
        budget = TokenBudget(input_limit=10_000_000, output_limit=10_000_000)
        calls = [(i, i * 2) for i in range(1, 101)]
        expected_input = sum(i for i, _ in calls)
        expected_output = sum(o for _, o in calls)

        await asyncio.gather(*(budget.add(i, o) for i, o in calls))
        totals = budget.totals()
        assert totals.input_tokens == expected_input
        assert totals.output_tokens == expected_output

    @pytest.mark.asyncio
    async def test_concurrent_is_exhausted_never_observes_torn_state(
        self,
    ) -> None:
        """A reader between two field updates must see a consistent total.

        We run many ``add`` / ``is_exhausted`` pairs concurrently and
        check that the observed totals (via :meth:`totals`) always
        satisfy ``input * 2 == output``. The add path increments both
        fields under the same lock; a torn read would produce a
        totals snapshot with ``output != 2*input``.
        """
        budget = TokenBudget(input_limit=10_000_000, output_limit=20_000_000)

        async def do_add() -> None:
            # output is always exactly 2x input
            await budget.add(3, 6)

        async def do_read() -> BudgetTotals:
            return budget.totals()

        # Interleave adds and reads.
        tasks = []
        for _ in range(200):
            tasks.append(asyncio.create_task(do_add()))
            tasks.append(asyncio.create_task(do_read()))
        results = await asyncio.gather(*tasks)

        # Every returned ``BudgetTotals`` (from do_read) must satisfy
        # the 2x invariant — if we ever read a torn (input updated,
        # output not yet) snapshot, that ratio would break.
        for result in results:
            if isinstance(result, BudgetTotals):
                assert result.output_tokens == result.input_tokens * 2

        # And the final total matches the exact number of adds.
        final = budget.totals()
        assert final.input_tokens == 200 * 3
        assert final.output_tokens == 200 * 6


# --------------------------------------------------------------------------- #
# Representation                                                              #
# --------------------------------------------------------------------------- #


class TestRepr:
    @pytest.mark.asyncio
    async def test_repr_shows_running_total(self) -> None:
        budget = TokenBudget(input_limit=100, output_limit=50)
        await budget.add(10, 5)
        assert "10/100" in repr(budget)
        assert "5/50" in repr(budget)


# --------------------------------------------------------------------------- #
# BudgetTotals                                                                #
# --------------------------------------------------------------------------- #


class TestBudgetTotals:
    def test_frozen(self) -> None:
        totals = BudgetTotals(1, 2)
        with pytest.raises(Exception):  # FrozenInstanceError is a dataclass exc
            totals.input_tokens = 99  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        assert BudgetTotals(1, 2) == BudgetTotals(1, 2)
        assert BudgetTotals(1, 2) != BudgetTotals(1, 3)
