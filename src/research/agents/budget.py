"""Per-``Research_Run`` token-budget tracker (Req 12.3–12.4, design §3.5).

Role in the Orchestrator graph
------------------------------
Design §3.5 specifies that every ``Research_Run`` enforces a central
token budget — 32 000 input tokens and 8 000 output tokens by default,
both configurable via ``research.agents.budget.*`` (Req 12.3). When a
run exceeds either limit, the Orchestrator MUST halt further
Sub_Agent calls and mark the final ``ResearchBrief`` with
``budget_exhausted=true`` (Req 12.4). The partial brief is still
returned to the caller so the UI has something to render.

This module hosts the data structure that tracks the running totals
and answers the two questions the Orchestrator asks between fan-out
steps:

1. *Would dispatching the next Sub_Agent push the run over either
   limit?* — :meth:`TokenBudget.is_exhausted`.
2. *What are the running totals?* — :meth:`TokenBudget.totals` (also
   the return value of :meth:`TokenBudget.add`).

The tracker is deliberately small. Recording token usage is a
per-provider-call concern (written to ``llm_usage`` — see
:mod:`src.research.agents.usage_writer`); the budget tracker only
needs to know "how many tokens have been spent so far" and "would
the next call push me over". Keeping the contract narrow matches the
Orchestrator's "inject a lightweight collaborator" pattern
(:mod:`src.research.agents.orchestrator`).

Concurrency
-----------
Sub_Agents fan out concurrently (default cap 6, Req 5.4) and every
one of them may call :meth:`add` or :meth:`is_exhausted` from a
different ``asyncio.Task``. The class is therefore thread-safe for
asyncio concurrency via an ``asyncio.Lock`` (``AsyncIO`` is
single-threaded, but an ``await`` point inside ``add``/``is_exhausted``
would otherwise let a second coroutine read stale totals). The lock
scope is deliberately tiny — just the read-modify-write / read-check
pair — so contention is negligible.

The tracker is **not** shared across processes: each Orchestrator run
owns its own :class:`TokenBudget` instance, constructed once per
:meth:`ResearchOrchestrator.run` invocation (Task 13.1 hook). The
``llm_usage`` table captures cross-process totals for observability;
this tracker is the single-run mechanism only.

Design references
-----------------
* §3.5 — token-budget tracker in the Orchestrator graph.
* §4.1 — ``llm_usage`` table that receives per-call rows (see
  :mod:`src.research.agents.usage_writer`).
* Req 12.3 — default limits 32 000 input / 8 000 output, configurable.
* Req 12.4 — on overrun, halt further Sub_Agent calls and set
  ``budget_exhausted=true``.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Final

__all__ = [
    "DEFAULT_INPUT_LIMIT",
    "DEFAULT_OUTPUT_LIMIT",
    "BudgetTotals",
    "TokenBudget",
]


# ---------------------------------------------------------------------------
# Defaults (Req 12.3)
# ---------------------------------------------------------------------------

# Design §3.5 / Req 12.3 defaults. Operator overrides flow through
# ``research.agents.budget.input_limit`` / ``.output_limit`` and are
# applied by the Orchestrator at construction time — this module
# exposes the constants so tests, the Orchestrator, and any future
# config validator all reference the same two numbers.
DEFAULT_INPUT_LIMIT: Final[int] = 32_000
DEFAULT_OUTPUT_LIMIT: Final[int] = 8_000


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BudgetTotals:
    """Immutable snapshot of the two running totals.

    Returned by :meth:`TokenBudget.add` and :meth:`TokenBudget.totals`
    so callers get a point-in-time view they can log / inspect
    without racing a concurrent :meth:`TokenBudget.add`. The class is
    frozen so a snapshot returned to one Sub_Agent cannot be mutated
    by accident and confuse observability wiring.
    """

    input_tokens: int
    output_tokens: int


# ---------------------------------------------------------------------------
# Budget tracker
# ---------------------------------------------------------------------------


class TokenBudget:
    """Track per-run token usage against configurable limits.

    The tracker exposes three operations:

    * :meth:`add` — record that a provider call consumed N input /
      output tokens. Returns the updated totals.
    * :meth:`is_exhausted` — answer "would adding the given estimate
      push me over either limit?". When called with both estimates
      equal to 0 (the default), returns True iff the current totals
      already exceed either limit.
    * :meth:`totals` — current totals as a :class:`BudgetTotals`
      snapshot.

    Parameters
    ----------
    input_limit:
        Maximum total input tokens allowed for this run. Default
        :data:`DEFAULT_INPUT_LIMIT` (32 000, Req 12.3). Values of 0 or
        less are rejected — a zero budget is never useful and would
        make every ``is_exhausted()`` call return True on the first
        add, which is always a configuration bug.
    output_limit:
        Maximum total output tokens. Default
        :data:`DEFAULT_OUTPUT_LIMIT` (8 000, Req 12.3). Same
        positivity check as ``input_limit``.

    Thread / asyncio safety
    -----------------------
    Holds both an :class:`asyncio.Lock` and a :class:`threading.Lock`
    so the tracker is safe from both asyncio concurrency (the common
    case — Sub_Agents fan out via :func:`asyncio.gather`) and
    legitimate cross-thread use (background Judge via
    :mod:`src.research.judge.async_fallback`, which runs the Judge
    on an ``asyncio.create_task`` backed by the same loop, but also
    from synchronous test harnesses that call :meth:`add` without an
    active event loop). The asyncio lock is used by the async
    methods; the threading lock guards the two synchronous helpers
    (:meth:`totals`, :meth:`is_exhausted_sync`). Python's GIL makes
    individual ``int`` field updates atomic, but a read-then-compare
    pattern — which is exactly what ``is_exhausted`` does — requires
    a real lock to avoid observing a partial update.

    Examples
    --------
    >>> import asyncio
    >>> budget = TokenBudget()  # 32k / 8k defaults
    >>> async def demo() -> None:
    ...     await budget.add(1_000, 200)
    ...     assert not await budget.is_exhausted(next_input_estimate=5_000)
    ...     await budget.add(30_000, 200)
    ...     assert await budget.is_exhausted()  # over the input limit
    >>> asyncio.run(demo())

    """

    def __init__(
        self,
        *,
        input_limit: int = DEFAULT_INPUT_LIMIT,
        output_limit: int = DEFAULT_OUTPUT_LIMIT,
    ) -> None:
        if input_limit <= 0:
            raise ValueError(
                f"input_limit must be positive; got {input_limit}",
            )
        if output_limit <= 0:
            raise ValueError(
                f"output_limit must be positive; got {output_limit}",
            )

        self._input_limit = input_limit
        self._output_limit = output_limit
        self._input_tokens = 0
        self._output_tokens = 0

        # An ``asyncio.Lock`` for coroutine-safe read-modify-write;
        # a ``threading.Lock`` for the sync helpers that may be
        # called from non-async contexts (tests, background
        # threads). The two locks guard disjoint code paths — every
        # async method takes the asyncio lock *and* the threading
        # lock so sync callers never observe a partial update, and
        # sync helpers hold only the threading lock.
        self._async_lock = asyncio.Lock()
        self._sync_lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Limits                                                             #
    # ------------------------------------------------------------------ #

    @property
    def input_limit(self) -> int:
        """Configured maximum input tokens (Req 12.3)."""
        return self._input_limit

    @property
    def output_limit(self) -> int:
        """Configured maximum output tokens (Req 12.3)."""
        return self._output_limit

    # ------------------------------------------------------------------ #
    # Core API                                                           #
    # ------------------------------------------------------------------ #

    async def add(
        self,
        input_tokens: int,
        output_tokens: int,
    ) -> BudgetTotals:
        """Record one provider call's token usage.

        Negative values are rejected — a negative cost would allow a
        misbehaving caller to "refund" the budget and mask an
        overrun. Zero is accepted because some providers return
        ``output_tokens=0`` for empty completions and the caller
        should not have to special-case that.

        Returns the updated totals as a :class:`BudgetTotals`
        snapshot so callers can log or inspect without racing
        concurrent updates.

        Requirements: 12.3, 12.4.
        """
        if input_tokens < 0:
            raise ValueError(
                f"input_tokens must be non-negative; got {input_tokens}",
            )
        if output_tokens < 0:
            raise ValueError(
                f"output_tokens must be non-negative; got {output_tokens}",
            )

        async with self._async_lock:
            # Also hold the threading lock so a sync reader observing
            # ``totals()`` between the two field updates can't see a
            # torn state (input updated, output not yet).
            with self._sync_lock:
                self._input_tokens += input_tokens
                self._output_tokens += output_tokens
                return BudgetTotals(
                    input_tokens=self._input_tokens,
                    output_tokens=self._output_tokens,
                )

    async def is_exhausted(
        self,
        next_input_estimate: int = 0,
        next_output_estimate: int = 0,
    ) -> bool:
        """Check whether the next call would exceed either limit.

        Parameters
        ----------
        next_input_estimate:
            Projected input-token cost of the next provider call. A
            value of 0 (the default) answers "am I already over?".
            Sub_Agents that want a more accurate pre-flight check can
            pass their prompt-token estimate here.
        next_output_estimate:
            Projected output-token cost of the next provider call.

        Returns
        -------
        bool
            ``True`` when ``current + estimate`` strictly exceeds
            either limit, ``False`` otherwise. The Orchestrator
            interprets ``True`` as "halt further Sub_Agent calls and
            mark ``budget_exhausted=true``" (Req 12.4).

        ``> limit`` — not ``>= limit`` — is deliberate: a run that
        lands exactly on the limit has consumed its full budget but
        has *not* exceeded it. Flagging equality would make
        deterministic tests that dial ``add`` up to the limit report
        exhaustion, which is the opposite of what design §3.5
        describes ("On overrun, halt further Sub_Agent calls").

        Negative estimates are rejected for the same reason
        :meth:`add` rejects negative values — they can only mask a
        real overrun.

        Requirements: 12.4.

        """
        if next_input_estimate < 0:
            raise ValueError(
                "next_input_estimate must be non-negative; got " f"{next_input_estimate}",
            )
        if next_output_estimate < 0:
            raise ValueError(
                "next_output_estimate must be non-negative; got " f"{next_output_estimate}",
            )

        async with self._async_lock:
            return self._is_exhausted_locked(
                next_input_estimate,
                next_output_estimate,
            )

    def is_exhausted_sync(
        self,
        next_input_estimate: int = 0,
        next_output_estimate: int = 0,
    ) -> bool:
        """Synchronous variant of :meth:`is_exhausted`.

        Useful from non-async code paths — for example a
        ``try``/``except`` handler in a background thread, or a
        synchronous test helper. Holds only the threading lock so it
        never blocks the asyncio event loop.
        """
        if next_input_estimate < 0:
            raise ValueError(
                "next_input_estimate must be non-negative; got " f"{next_input_estimate}",
            )
        if next_output_estimate < 0:
            raise ValueError(
                "next_output_estimate must be non-negative; got " f"{next_output_estimate}",
            )
        with self._sync_lock:
            return self._is_exhausted_locked(
                next_input_estimate,
                next_output_estimate,
            )

    def totals(self) -> BudgetTotals:
        """Return a :class:`BudgetTotals` snapshot of the running totals.

        Sync-safe: holds only the threading lock so it never yields
        on an ``asyncio`` boundary. Returns an immutable snapshot so
        a caller iterating a value cannot race a concurrent
        :meth:`add`.
        """
        with self._sync_lock:
            return BudgetTotals(
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
            )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _is_exhausted_locked(
        self,
        next_input_estimate: int,
        next_output_estimate: int,
    ) -> bool:
        """Shared exhaustion predicate. Caller MUST hold a lock.

        Kept private so the two public check methods — async and
        sync — share a single source of truth for the comparison. A
        future change to "use >= instead of >" (or to add a grace
        factor) lives in one place.
        """
        projected_input = self._input_tokens + next_input_estimate
        projected_output = self._output_tokens + next_output_estimate
        return projected_input > self._input_limit or projected_output > self._output_limit

    # ------------------------------------------------------------------ #
    # Introspection                                                      #
    # ------------------------------------------------------------------ #

    def __repr__(self) -> str:
        # Best-effort representation — read without the async lock so
        # this is safe from ``repr()`` in log formatters. Worst case
        # a concurrent ``add`` returns a torn value, which is fine
        # for a debug string.
        return (
            f"TokenBudget("
            f"input={self._input_tokens}/{self._input_limit}, "
            f"output={self._output_tokens}/{self._output_limit})"
        )
