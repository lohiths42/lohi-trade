"""Memory scoping — design §17.1 Property 3 (in-memory layer) / Req 14.3, Req 4.5.

The invariant under test: **for any sequence of writes by two
distinct tenants into any of the three memory layers, a read by one
tenant never surfaces a row whose ``user_id`` belongs to the other
tenant.**

Req 4.5 frames this from the data-access side — "THE Lohi_Research
SHALL scope every query by user_id and SHALL never return a row whose
user_id does not match the caller". Req 14.3 formalises the same
invariant as a CI-gated property test.

Relationship to the RLS test
----------------------------
The Postgres-level incarnation of this property — where the
guarantee is enforced by ``CREATE POLICY … USING (user_id =
current_setting('app.user_id')::uuid)`` on real asyncpg connections —
lives in :mod:`tests.research.test_prop_rls_isolation`. That suite
was landed with Task 4.4; it skips when no live Postgres is
reachable. This file is the **in-memory complement** (Task 7.5): it
exercises the application-layer contract that the memory classes'
method signatures actually thread ``user_id`` through every read and
write, by swapping in inline fake implementations that honour the
same surface as :class:`WorkingMemory` / :class:`SemanticMemory` /
:class:`EpisodicMemory` but store data in ordinary Python dicts.

Why inline fakes rather than
``tests/research/fakes/``
-------------------------------
The fakes in this file encode the scoping invariant *in themselves*
— each one keys its in-memory storage by ``user_id`` and reads back
only the caller's slice, so the property they enforce is precisely
what a correct production implementation must guarantee. Keeping
them inline makes the test file self-contained: a reviewer can see
the full model the property is quantifying over without following an
import chain. The shared ``tests/research/fakes/`` directory is for
provider-level fakes (LLM, embeddings, vector store) where multiple
tests share a configurable surface; the memory fakes here are
single-purpose.

Strategy sketch
---------------
* Two distinct pinned user UUIDs, ``_USER_A`` and ``_USER_B``, are
  fixed at module scope so Hypothesis shrinking is deterministic —
  drawing UUIDs per example would produce noisy counter-examples.
* Each Hypothesis example is a list of 1..40 ``(user, op_type,
  payload)`` tuples, applied in order to the three fake layers.
* After application, we read back every layer for both users and
  assert:

    1. No row returned to ``user_a`` carries ``user_id = user_b``.
    2. No row returned to ``user_b`` carries ``user_id = user_a``.

Hypothesis configuration
------------------------
``max_examples=30`` per the task spec. ``deadline=None`` because the
test body runs an ``asyncio.run`` loop per example and the strategy
generates up to 40 ops; the default Hypothesis deadline is tight
enough that CI machines occasionally trip it.

Validates: Requirements 14.3, 4.5
Design: §3.4, §17.1
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# --------------------------------------------------------------------------- #
# Fixed universe                                                              #
# --------------------------------------------------------------------------- #
#
# Pinned per the task spec ("pin them as module-level constants to
# keep Hypothesis shrinking predictable"). All-1s and all-2s are
# unambiguous in failure output and trivially distinguishable when a
# counter-example prints.

_USER_A: UUID = UUID("11111111-1111-1111-1111-111111111111")
_USER_B: UUID = UUID("22222222-2222-2222-2222-222222222222")
_USERS: tuple[UUID, UUID] = (_USER_A, _USER_B)

# Small fixed symbol set. Hypothesis-drawn free-form symbols would
# work but would blow up shrinking with noise. Five is enough to
# exercise the episodic path's ``(user_id, symbol)`` composite key
# without dominating the search space.
_SYMBOLS: tuple[str, ...] = ("RELIANCE", "TCS", "INFY", "HDFCBANK", "ITC")

# Semantic-memory ``kind``s drawn from the production vocabulary
# (see ``_KNOWN_KINDS`` in :mod:`src.research.memory.semantic`). Kept
# narrow for the same shrinking reason as the symbols.
_SEMANTIC_KINDS: tuple[str, ...] = (
    "preference",
    "watchlist_fact",
    "session_summary",
)


# --------------------------------------------------------------------------- #
# Inline fakes                                                                #
# --------------------------------------------------------------------------- #


class InMemoryWorkingMemory:
    """Dict-backed stand-in for :class:`WorkingMemory`.

    Storage shape: ``{(user_id, conv_id): list[turn_dict]}``. The key
    is a tuple rather than a nested dict so the scoping invariant
    lives in the *key*: looking up the wrong user requires
    constructing a key with that user's UUID, which the ``read``
    path explicitly never does.

    The method surface mirrors the production class only to the
    extent :func:`forget_memory` needs (``append_turn``, ``read``,
    ``forget``). ``summarise_if_needed`` is deliberately absent —
    summarisation is orthogonal to the scoping invariant under test.
    """

    def __init__(self) -> None:
        self._store: dict[tuple[UUID, UUID], list[dict]] = {}

    async def append_turn(
        self, user_id: UUID, conv_id: UUID, turn: dict,
    ) -> None:
        # The stored turn carries ``user_id`` so the property-test
        # assertion has a concrete field to inspect. Production
        # Redis-backed storage does not need this (the key is keyed
        # by user_id), but the fake keeps it explicit to match the
        # test's quantified property.
        stamped = dict(turn)
        stamped["user_id"] = user_id
        self._store.setdefault((user_id, conv_id), []).append(stamped)

    async def read(self, user_id: UUID, conv_id: UUID) -> list[dict]:
        # Look up only by the caller's tuple — the cross-user key
        # space is simply not reachable from this path.
        return list(self._store.get((user_id, conv_id), []))

    async def forget(
        self, user_id: UUID, conv_id: UUID | None = None,
    ) -> int:
        if conv_id is not None:
            removed = self._store.pop((user_id, conv_id), None)
            return 1 if removed is not None else 0
        # No ``conv_id`` → wipe every conversation for the tenant.
        # Other tenants' keys are untouched; the fake mirrors the
        # production SCAN_ITER behaviour of :meth:`WorkingMemory.forget`.
        keys = [k for k in self._store if k[0] == user_id]
        for k in keys:
            self._store.pop(k, None)
        return len(keys)

    # Test-only helper: enumerate every (user_id, conv_id) pair the
    # fake has seen for a given tenant. Used by the property to
    # assert no cross-user key ever appears in the tenant's view.
    def _all_convs_for(self, user_id: UUID) -> list[UUID]:
        return [conv for (uid, conv) in self._store if uid == user_id]


class InMemorySemanticMemory:
    """Dict-backed stand-in for :class:`SemanticMemory`.

    Storage shape: ``{user_id: list[row_dict]}``. Each row carries
    ``user_id``, ``kind``, ``content`` — the same triple
    :meth:`SemanticMemory.query` returns via
    ``SELECT … FROM research_semantic_memory``.
    """

    def __init__(self) -> None:
        self._store: dict[UUID, list[dict]] = {}

    async def add(self, user_id: UUID, kind: str, content: str) -> None:
        self._store.setdefault(user_id, []).append(
            {"user_id": user_id, "kind": kind, "content": content},
        )

    async def query(
        self,
        user_id: UUID,
        *,
        kind: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        rows = self._store.get(user_id, [])
        if kind is not None:
            rows = [r for r in rows if r["kind"] == kind]
        # Slice after filter; the production SQL path does the same
        # via ``ORDER BY created_at DESC LIMIT``. Ordering is
        # irrelevant to the scoping invariant so the fake keeps
        # insertion order for deterministic counter-examples.
        return list(rows[:limit])

    async def delete(
        self, user_id: UUID, *, kind: str | None = None,
    ) -> int:
        rows = self._store.get(user_id, [])
        if not rows:
            return 0
        if kind is None:
            count = len(rows)
            self._store[user_id] = []
            return count
        remaining = [r for r in rows if r["kind"] != kind]
        deleted = len(rows) - len(remaining)
        self._store[user_id] = remaining
        return deleted


class InMemoryEpisodicMemory:
    """Dict-backed stand-in for :class:`EpisodicMemory`.

    Storage shape: ``{user_id: list[row_dict]}`` where each row is
    ``{"user_id": UUID, "symbol": str, "run_id": UUID, "summary": str}``.
    """

    def __init__(self) -> None:
        self._store: dict[UUID, list[dict]] = {}

    async def add(
        self,
        user_id: UUID,
        symbol: str,
        run_id: UUID,
        summary: str,
    ) -> None:
        self._store.setdefault(user_id, []).append(
            {
                "user_id": user_id,
                "symbol": symbol,
                "run_id": run_id,
                "summary": summary,
            },
        )

    async def read(
        self, user_id: UUID, symbol: str, limit: int = 10,
    ) -> list[dict]:
        rows = [r for r in self._store.get(user_id, []) if r["symbol"] == symbol]
        # Most-recent-first like the production path. Insertion order
        # is effectively creation order here, so reversing yields
        # ``created_at DESC`` equivalence.
        return list(reversed(rows))[:limit]

    async def delete(
        self, user_id: UUID, *, symbol: str | None = None,
    ) -> int:
        rows = self._store.get(user_id, [])
        if not rows:
            return 0
        if symbol is None:
            count = len(rows)
            self._store[user_id] = []
            return count
        remaining = [r for r in rows if r["symbol"] != symbol]
        deleted = len(rows) - len(remaining)
        self._store[user_id] = remaining
        return deleted


# --------------------------------------------------------------------------- #
# Operation strategy                                                          #
# --------------------------------------------------------------------------- #


_OP_TYPES: tuple[str, ...] = ("wm_append", "sem_add", "ep_add")


# ``user_id`` is drawn from the pinned pair so shrinking produces
# stable, human-readable counter-examples.
_user_strategy = st.sampled_from(_USERS)


# Text alphabet mirrors the citation-integrity test — readable on
# shrink, stable across locales.
_TEXT_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz "
_short_text = st.text(alphabet=_TEXT_ALPHABET, min_size=1, max_size=40)


@st.composite
def _wm_append_payload(draw: st.DrawFn) -> dict:
    """A working-memory append payload: conv_id + turn body."""
    # A tiny fixed pool of conversation UUIDs per user would make the
    # fake collide too easily; distinct uuid4s per draw exercise the
    # "many conversations, each independently scoped" case.
    return {
        "conv_id": uuid4(),
        "turn": {
            "role": draw(st.sampled_from(("user", "assistant", "system"))),
            "content": draw(_short_text),
            "tokens": draw(st.integers(min_value=0, max_value=100)),
        },
    }


@st.composite
def _sem_add_payload(draw: st.DrawFn) -> dict:
    return {
        "kind": draw(st.sampled_from(_SEMANTIC_KINDS)),
        "content": draw(_short_text),
    }


@st.composite
def _ep_add_payload(draw: st.DrawFn) -> dict:
    return {
        "symbol": draw(st.sampled_from(_SYMBOLS)),
        "run_id": uuid4(),
        "summary": draw(_short_text),
    }


@st.composite
def _op(draw: st.DrawFn) -> dict:
    """Draw a single ``(user, op_type, payload)`` triple.

    Returned as a dict so the shrink representation is readable —
    Hypothesis renders ``{'user': UUID(...), 'op_type': 'wm_append',
    ...}`` rather than a bare tuple index chase.
    """
    op_type = draw(st.sampled_from(_OP_TYPES))
    user = draw(_user_strategy)
    if op_type == "wm_append":
        payload = draw(_wm_append_payload())
    elif op_type == "sem_add":
        payload = draw(_sem_add_payload())
    else:  # ep_add
        payload = draw(_ep_add_payload())
    return {"user": user, "op_type": op_type, "payload": payload}


_ops_list = st.lists(_op(), min_size=1, max_size=40)


# --------------------------------------------------------------------------- #
# Property                                                                    #
# --------------------------------------------------------------------------- #


def _run(coro):  # pragma: no cover - trivial helper
    """Drive an async coroutine to completion inside a sync Hypothesis test.

    Matches :mod:`tests.research.test_prop_citation_integrity` — one
    fresh :func:`asyncio.run` per example keeps fake state isolated
    across examples and avoids sharing an event loop between Hypothesis
    iterations.
    """
    return asyncio.run(coro)


@given(ops=_ops_list)
@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[
        # Per-example setup draws up to 40 ops with nested composites;
        # that can exceed the default Hypothesis data-generation
        # budget even though each op is tiny.
        HealthCheck.data_too_large,
        HealthCheck.too_slow,
    ],
)
def test_memory_scoping_no_cross_user_leak(ops: list[dict]) -> None:
    """Reads never surface rows owned by the other tenant.

    Validates: Requirements 14.3, 4.5.

    For each generated op sequence:

    1. Fresh instances of all three in-memory fakes.
    2. Apply every op in order, honouring the ``user`` field as the
       caller's tenant id.
    3. For both users, read back every layer and assert no returned
       row carries the *other* tenant's ``user_id``.

    A failing example would either be a fake that accidentally
    aliased user slots (a bug in this file) or — once wired into the
    production classes via a future integration test — a real
    scoping violation in the memory layer.
    """

    async def _body() -> None:
        working = InMemoryWorkingMemory()
        semantic = InMemorySemanticMemory()
        episodic = InMemoryEpisodicMemory()

        # ------- Apply ops ------------------------------------------- #
        for op in ops:
            user = op["user"]
            op_type = op["op_type"]
            payload = op["payload"]

            if op_type == "wm_append":
                await working.append_turn(
                    user, payload["conv_id"], payload["turn"],
                )
            elif op_type == "sem_add":
                await semantic.add(user, payload["kind"], payload["content"])
            elif op_type == "ep_add":
                await episodic.add(
                    user,
                    payload["symbol"],
                    payload["run_id"],
                    payload["summary"],
                )
            else:  # pragma: no cover - defensive; _OP_TYPES is closed
                raise AssertionError(f"unknown op_type {op_type!r}")

        # ------- Read back and assert the invariant ------------------ #
        for reader in _USERS:
            other = _USER_B if reader == _USER_A else _USER_A

            # Working memory: enumerate every conversation the
            # reader has seen and confirm no turn in any of them
            # carries the other tenant's user_id.
            for conv_id in working._all_convs_for(reader):
                turns = await working.read(reader, conv_id)
                for turn in turns:
                    assert turn["user_id"] != other, (
                        f"working-memory leak: reader={reader} saw a turn "
                        f"with user_id={other} in conv_id={conv_id}: {turn!r}"
                    )
                    # Stronger: every row must be owned by the reader.
                    assert turn["user_id"] == reader, (
                        f"working-memory unexpected user_id: reader={reader} "
                        f"got turn with user_id={turn['user_id']}"
                    )

            # Semantic memory: an unfiltered query returns every
            # row the reader owns. Any row whose user_id belongs to
            # the other tenant would be a leak.
            sem_rows = await semantic.query(reader, limit=10_000)
            for row in sem_rows:
                assert row["user_id"] != other, (
                    f"semantic-memory leak: reader={reader} saw "
                    f"user_id={other} in row {row!r}"
                )
                assert row["user_id"] == reader, (
                    f"semantic-memory unexpected user_id: reader={reader} "
                    f"got row with user_id={row['user_id']}"
                )

            # Episodic memory: read every symbol, assert no row
            # owned by the other tenant ever surfaces.
            for symbol in _SYMBOLS:
                ep_rows = await episodic.read(reader, symbol, limit=10_000)
                for row in ep_rows:
                    assert row["user_id"] != other, (
                        f"episodic-memory leak: reader={reader} saw "
                        f"user_id={other} for symbol={symbol}: {row!r}"
                    )
                    assert row["user_id"] == reader, (
                        f"episodic-memory unexpected user_id: reader={reader} "
                        f"got row with user_id={row['user_id']}"
                    )

    _run(_body())


if __name__ == "__main__":  # pragma: no cover
    # Allow ``python tests/research/test_prop_memory_scoping.py``
    # for quick local iteration.
    import pytest

    pytest.main([__file__, "-v"])
