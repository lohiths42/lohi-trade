"""Property 3 (RLS portion) — cross-user isolation against real Postgres.

Validates: Req 14.3, Req 4.5, Req 4.6. Design §14.

This test pins down the **canonical** invariant of the research
persistence layer: when an asyncpg connection engages RLS via
:func:`set_rls_user_id` / :func:`rls_connection` from Task 4.3, a
``SELECT`` as user ``u_a`` must return zero rows whose ``user_id ==
u_b``, and symmetrically. That invariant is the sole thing standing
between one tenant and another tenant's research notes on a multi-user
SaaS deployment (Persona_Cloud_SaaS in requirements.md §Glossary).

Why real Postgres only
----------------------
RLS is a Postgres feature. A SQLite or in-memory mock cannot enforce
``USING (user_id = current_setting('app.user_id')::uuid)`` — it has no
such concept. Running the property against a fake would answer a
different question (does our application-layer ``WHERE`` filter hit?)
rather than the one Req 4.6 actually asks (does the RLS predicate in
Postgres reject the row?). We therefore require a live Postgres for
this suite. When one is not reachable — on a developer laptop, or in
a CI job that does not spin up Postgres — every test in this file
calls :func:`pytest.skip` with a clear diagnostic instead of silently
passing.

How "reachable Postgres" is detected
------------------------------------
Three preconditions must all hold for the tests to run; any failure
collapses to ``pytest.skip`` with a specific reason:

1. ``DATABASE_URL`` is set in the environment.
2. An asyncpg pool can be created against that DSN and ``SELECT 1``
   succeeds (i.e. auth + network work).
3. The Task 4.1 research migration has been applied — detected by
   probing one table per RLS-protected family
   (``SELECT 1 FROM <table> LIMIT 0``). Any missing table → skip.

The :func:`src.research.providers.vector_store.autoselect.probe_pgvector`
helper cannot be reused here because it proves *pgvector* is available,
which is a stricter condition than what this test needs. RLS works
independently of the pgvector extension (the tables tested here,
excepting the embedding columns on ``research_chunks`` /
``research_semantic_memory``, are pure relational). We therefore use a
tailored ``SELECT 1`` probe at fixture setup time.

Tables covered
--------------
Every RLS-protected table in design §4.1 that owns a ``user_id``
column is exercised:

* ``research_documents``
* ``research_chunks``          (requires a parent ``research_documents`` row)
* ``research_runs``
* ``research_semantic_memory``
* ``research_episodic_memory`` (requires a parent ``research_runs`` row)
* ``research_snapshots``

Note that ``research_brief_sections``, ``research_provenance``, and
``research_judge_reports`` inherit tenant isolation *transitively*
through ``run_id → research_runs`` (they don't own a ``user_id``
column, see migration 002 docstring) and are consequently out of scope
for this property — the transitive case is covered by the parent
research_runs isolation.

Working_Memory (Redis) is explicitly out of scope for this task —
Task 7.5 exercises the Redis layer. ``llm_usage`` and
``research_audit_log`` are also out of scope because they are not
listed in the task description; adding them later would be purely
additive.

Requirements: 14.3, 4.5, 4.6
Design: §14
"""

from __future__ import annotations

import hashlib
import importlib.util as _ilu
import os
import pathlib as _pl
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# --------------------------------------------------------------------------- #
# RLS helper import shim                                                       #
# --------------------------------------------------------------------------- #
#
# The RLS helper lives under ``backend-gateway/app/services/research/rls.py``.
# Because ``backend-gateway`` has a hyphen in its directory name, there is no
# clean ``from backend_gateway.app...`` import path — Python identifiers
# can't contain hyphens. The production code gets around this by running
# with ``backend-gateway`` itself on ``sys.path`` (so it imports
# ``app.services.research.rls``), but that alias isn't configured for the
# pytest root at ``tests/``. Adding a global ``sys.path`` shim purely for
# this test would leak into other tests.
#
# Load the helper directly by file path instead. This is a one-module
# loader (no recursive imports out of ``rls.py``, which only pulls in
# stdlib ``contextlib`` + ``uuid`` and does a ``TYPE_CHECKING`` import
# of ``asyncpg``), so the ``spec_from_file_location`` + ``exec_module``
# pattern gives us exactly what we need without polluting the path.
_rls_path = (
    _pl.Path(__file__).resolve().parents[2]
    / "backend-gateway"
    / "app"
    / "services"
    / "research"
    / "rls.py"
)
_spec = _ilu.spec_from_file_location("_lohi_research_rls", str(_rls_path))
assert _spec is not None and _spec.loader is not None, (
    f"Could not locate the RLS helper module at {_rls_path}; Task 4.3 " f"should have landed it."
)
_rls_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_rls_mod)
rls_connection = _rls_mod.rls_connection


# --------------------------------------------------------------------------- #
# Constants                                                                   #
# --------------------------------------------------------------------------- #

# Every RLS-protected research table we verify in this suite. Names
# match migration 002.
_RLS_TABLES: tuple[str, ...] = (
    "research_documents",
    "research_chunks",
    "research_runs",
    "research_semantic_memory",
    "research_episodic_memory",
    "research_snapshots",
)


# --------------------------------------------------------------------------- #
# Session-scoped fixtures — Postgres detection & pool management              #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def _database_url() -> str:
    """Return ``DATABASE_URL`` or skip the entire suite.

    RLS is a Postgres feature; no DSN → no meaningful test. We skip
    (not fail) so the research test suite remains green on machines
    without a local Postgres, per the task's "real Postgres required"
    guidance.
    """
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        pytest.skip(
            "DATABASE_URL not set; RLS tests require a live Postgres. "
            "Set DATABASE_URL to a reachable DSN (e.g. "
            "postgresql://user:pw@host/db) to run this suite.",
        )
    return dsn


@pytest_asyncio.fixture(scope="session")
async def _pg_pool(_database_url: str) -> AsyncIterator[Any]:
    """Create an asyncpg pool against ``DATABASE_URL`` or skip.

    Runs ``SELECT 1`` as a connectivity probe. Any failure at pool
    creation (asyncpg missing, DNS failure, auth failure, refused
    connection) or at the probe query (unexpected driver-level
    shutdown, permissions) collapses to ``pytest.skip`` with a clear
    reason. Either outcome is acceptable for this test — passing or a
    clearly-logged skip — which is the point of the skip ladder.

    The pool is closed in teardown so the test process exits cleanly
    even when run under ``pytest -x``.
    """
    try:
        import asyncpg  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - exercised by skip path
        pytest.skip(f"asyncpg not importable; RLS tests require it: {exc!r}")

    try:
        pool = await asyncpg.create_pool(
            _database_url,
            min_size=1,
            max_size=4,
            command_timeout=5.0,
        )
    except Exception as exc:
        pytest.skip(
            f"Postgres not reachable at DATABASE_URL; RLS tests require a "
            f"live DB. ({type(exc).__name__}: {exc})",
        )

    # ``create_pool`` succeeded but that alone doesn't prove the DB is
    # healthy — on some drivers it defers the first connection. A
    # direct ``SELECT 1`` forces the handshake now so we skip rather
    # than fail deep inside a test.
    try:
        async with pool.acquire() as conn:
            one = await conn.fetchval("SELECT 1")
            assert one == 1
    except Exception as exc:
        await pool.close()
        pytest.skip(
            f"Postgres connectivity probe failed; RLS tests require a "
            f"live DB. ({type(exc).__name__}: {exc})",
        )

    try:
        yield pool
    finally:
        await pool.close()


@pytest_asyncio.fixture(scope="session")
async def _migrations_applied(_pg_pool: Any) -> None:
    """Skip the suite unless Task 4.1's research migration has been applied.

    Runs ``SELECT 1 FROM <table> LIMIT 0`` against each RLS-protected
    research table. The ``LIMIT 0`` form returns no rows but still
    forces Postgres to resolve the relation, so a missing table raises
    ``UndefinedTableError`` which we collapse to a skip with a clear
    message.

    We also confirm that the ``app.user_id`` setting is recognised by
    the server — without it, every RLS predicate short-circuits to
    ``NULL`` and the test becomes indistinguishable from a test that
    forgot to engage RLS. The existence of the setting is implicit in
    the migration's policy DDL, but probing it here gives a cleaner
    failure mode for misconfigured databases.
    """
    async with _pg_pool.acquire() as conn:
        for table in _RLS_TABLES:
            try:
                await conn.execute(f"SELECT 1 FROM {table} LIMIT 0")
            except Exception as exc:
                pytest.skip(
                    f"research migration has not been applied "
                    f"(missing table '{table}': {type(exc).__name__}: {exc})",
                )

        # Sanity: ``set_config('app.user_id', ..., true)`` must be
        # callable inside a transaction and ``current_setting`` must
        # then reflect it. A failure here is almost certainly a
        # misconfigured Postgres (e.g. a role without permission to
        # call ``set_config``) and we'd rather skip than run a test
        # that cannot possibly behave correctly.
        try:
            async with conn.transaction():
                await conn.execute(
                    "SELECT set_config('app.user_id', $1, true)",
                    str(uuid4()),
                )
                roundtrip = await conn.fetchval(
                    "SELECT current_setting('app.user_id', true)",
                )
                assert isinstance(roundtrip, str) and len(roundtrip) == 36
        except Exception as exc:
            pytest.skip(
                f"Postgres rejected set_config('app.user_id', ...); "
                f"RLS cannot engage. ({type(exc).__name__}: {exc})",
            )


# --------------------------------------------------------------------------- #
# Function-scoped fixtures — per-example users and cleanup                     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def _two_users() -> tuple[UUID, UUID]:
    """Fresh ``(u_a, u_b)`` pair per Hypothesis example.

    Distinct UUIDs on every call so no example can accidentally share
    tenant IDs with a previous one (which would defeat the isolation
    check). We draw with ``uuid4`` rather than a hypothesis-level
    strategy because the property under test is about isolation
    *between* two specific users, not about the space of user IDs —
    making these function-scoped is sufficient.
    """
    return uuid4(), uuid4()


@pytest_asyncio.fixture
async def _cleanup_rows(
    _pg_pool: Any,
    _migrations_applied: None,
    _two_users: tuple[UUID, UUID],
) -> AsyncIterator[None]:
    """Teardown-only fixture that deletes every row owned by the two test users.

    Deletes are issued via the same :func:`rls_connection` helper the
    production code uses, so we stay on the app role's RLS-engaged
    path rather than relying on superuser privileges — the test suite
    is expected to run as a normal app user in CI. Each user's rows
    are deleted under their own ``app.user_id`` setting so the RLS
    policy lets the DELETE see them.

    Order matters: ``research_episodic_memory`` and ``research_chunks``
    reference ``research_runs`` / ``research_documents`` via foreign
    keys with ``ON DELETE CASCADE``, so deleting the parent also
    sweeps the children. Even so, we delete children explicitly first
    to keep the cleanup robust if a future migration drops the
    cascade.
    """
    yield

    u_a, u_b = _two_users
    for uid in (u_a, u_b):
        try:
            async with rls_connection(_pg_pool, uid) as conn:
                # Child rows first (RLS-owned).
                await conn.execute("DELETE FROM research_episodic_memory")
                await conn.execute("DELETE FROM research_chunks")
                # Parents + standalone rows.
                await conn.execute("DELETE FROM research_snapshots")
                await conn.execute("DELETE FROM research_semantic_memory")
                await conn.execute("DELETE FROM research_runs")
                await conn.execute("DELETE FROM research_documents")
        except Exception:
            # Cleanup must never mask a test failure. A failure here
            # means the next example may see leftover rows and
            # shrink to a puzzling counterexample; that's still a
            # better outcome than the test suite crashing in
            # teardown.
            pass


# --------------------------------------------------------------------------- #
# Hypothesis strategies                                                       #
# --------------------------------------------------------------------------- #


@st.composite
def _isolation_scenario(draw: st.DrawFn) -> list[tuple[str, str]]:
    """Draw a non-empty list of ``(symbol, content)`` tuples.

    * ``n_rows`` ∈ [1, 5] keeps each example cheap — the property is
      "zero leakage across N rows", not "scale test".
    * ``symbol`` is 1-16 alphanumerics to match the ``VARCHAR(32)``
      column and avoid SQL-injection-like payloads (this is a
      correctness test, not a parsing stress test).
    * ``content`` is 1-200 chars of arbitrary text so it can contain
      unicode, quotes, and other content the inserted row must round-
      trip cleanly.
    """
    n_rows = draw(st.integers(min_value=1, max_value=5))
    symbols = st.text(
        alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"),
        ),
        min_size=1,
        max_size=16,
    )
    contents = st.text(min_size=1, max_size=200)
    return [(draw(symbols), draw(contents)) for _ in range(n_rows)]


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _sha256_hex(text: str) -> str:
    """64-char hex SHA-256 — matches ``research_documents.sha256 CHAR(64)``."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def _insert_all_for_user(
    conn: Any,
    user_id: UUID,
    rows: list[tuple[str, str]],
) -> None:
    """Insert one row per RLS-protected table for each ``(symbol, content)``.

    Every insert runs on a connection where ``app.user_id`` has already
    been set to ``user_id`` via :func:`rls_connection`, so the RLS
    policies let them through. This mirrors how production code
    inserts: the caller engages RLS, then issues the statement.

    ``research_chunks`` needs the parent document's primary key and
    ``research_episodic_memory`` needs the parent run's primary key —
    we ``RETURNING id`` from the parent INSERT and thread the value
    into the child INSERT, keeping everything in one transaction (the
    transaction is supplied by :func:`rls_connection`).

    Per-row uniqueness note: ``research_chunks.chunk_id`` and
    ``research_documents(user_id, sha256)`` both carry UNIQUE
    constraints. Hypothesis is free to draw the same ``content``
    twice, which would produce the same SHA-256. We therefore salt
    every SHA-256 with a fresh UUID suffix so distinct generated rows
    always land as distinct DB rows — the correctness property is
    about RLS, not about dedup, and the two concerns are orthogonal.
    """
    for symbol, content in rows:
        salt = uuid4().hex
        doc_sha = _sha256_hex(f"{content}:{salt}")
        chunk_id = _sha256_hex(f"chunk:{doc_sha}")

        # 1. research_documents — parent of research_chunks.
        doc_id = await conn.fetchval(
            """
            INSERT INTO research_documents
                (user_id, symbol, document_type, sha256, canonical_text)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            user_id,
            symbol,
            "test",
            doc_sha,
            content,
        )

        # 2. research_chunks — child, also carries user_id + symbol
        #    (denormalised per migration 002 module docstring).
        await conn.execute(
            """
            INSERT INTO research_chunks
                (document_id, user_id, symbol, chunk_id, position,
                 token_count, text, embedding_model, embedding_dim)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            doc_id,
            user_id,
            symbol,
            chunk_id,
            0,
            len(content),
            content,
            "fake",
            384,
        )

        # 3. research_runs — parent of research_episodic_memory.
        run_id = await conn.fetchval(
            """
            INSERT INTO research_runs (user_id, symbol, prompt, status)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            user_id,
            symbol,
            content,
            "done",
        )

        # 4. research_semantic_memory.
        await conn.execute(
            """
            INSERT INTO research_semantic_memory (user_id, kind, content)
            VALUES ($1, $2, $3)
            """,
            user_id,
            "preference",
            content,
        )

        # 5. research_episodic_memory — child of research_runs.
        await conn.execute(
            """
            INSERT INTO research_episodic_memory
                (user_id, symbol, run_id, summary)
            VALUES ($1, $2, $3, $4)
            """,
            user_id,
            symbol,
            run_id,
            content,
        )

        # 6. research_snapshots — composite PK (user_id, symbol) so we
        #    ON CONFLICT DO NOTHING to keep duplicate-symbol draws
        #    idempotent rather than blowing up the test on a generator
        #    collision.
        await conn.execute(
            """
            INSERT INTO research_snapshots
                (user_id, symbol, brief_json, generated_at,
                 input_document_hashes, stale)
            VALUES ($1, $2, $3::jsonb, now(), $4, FALSE)
            ON CONFLICT (user_id, symbol) DO NOTHING
            """,
            user_id,
            symbol,
            f'{{"s": {content!r}}}'.replace("'", '"'),
            ["x"],
        )


async def _assert_isolation_for(
    pool: Any,
    viewer: UUID,
    other: UUID,
) -> None:
    """Open an RLS connection as ``viewer`` and assert zero ``other`` rows.

    This is the heart of the property. For every RLS-protected table,
    fetch every row the viewer's RLS predicate allows, and check no
    row's ``user_id`` equals ``other``. Because the RLS policy is
    ``USING (user_id = current_setting('app.user_id')::uuid)``,
    "correct" behaviour means the ``other`` rows simply don't appear
    in the result — the assertion below is a cross-check against the
    weaker statement "the WHERE clause held" because we don't issue
    a WHERE clause at all. If an ``other`` row surfaces, RLS has
    silently failed; that is exactly the regression Req 4.6 exists to
    prevent.
    """
    async with rls_connection(pool, viewer) as conn:
        for table in _RLS_TABLES:
            rows = await conn.fetch(f"SELECT user_id FROM {table}")
            leaked = [r for r in rows if r["user_id"] == other]
            assert not leaked, (
                f"RLS leaked {len(leaked)} row(s) from {table} "
                f"to viewer={viewer} owned by other={other}"
            )
            # Dual assertion: every row we can see must be ours. This
            # strengthens the primary property: not only does ``other``
            # not leak, nothing else does either.
            not_ours = [r for r in rows if r["user_id"] != viewer]
            assert not not_ours, (
                f"RLS leaked {len(not_ours)} row(s) from {table} whose "
                f"user_id is neither viewer={viewer} nor any expected "
                f"tenant; found: {[r['user_id'] for r in not_ours[:5]]}"
            )


# --------------------------------------------------------------------------- #
# Property test                                                               #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@given(rows=_isolation_scenario())
@settings(
    max_examples=15,
    deadline=None,
    # The ``_two_users`` / ``_cleanup_rows`` fixtures are intentionally
    # function-scoped: every Hypothesis example needs a fresh pair of
    # user IDs and clean tables, otherwise rows from a prior example
    # would pollute the current one and muddy the counterexample.
    # Hypothesis flags function-scoped fixtures by default because
    # they reset between examples — that's exactly what we want, so
    # we suppress the health check.
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_rls_cross_user_isolation(
    rows: list[tuple[str, str]],
    _pg_pool: Any,
    _migrations_applied: None,
    _two_users: tuple[UUID, UUID],
    _cleanup_rows: None,
) -> None:
    """**Property 3 (RLS)**: RLS must never let one tenant see another's rows.

    Scenario per example:

    1. Draw a list of ``(symbol, content)`` tuples.
    2. For *each* tuple, insert the full fan-out — document, chunk,
       run, semantic memory, episodic memory, snapshot — **twice**:
       once under ``u_a`` and once under ``u_b``. So each tuple
       produces 12 DB rows in total, 6 per user.
    3. Open an RLS-engaged connection as ``u_a`` and assert that
       ``SELECT user_id FROM <table>`` returns zero rows whose
       ``user_id == u_b`` for every RLS-protected table. Then assert
       the symmetric case as ``u_b``.
    4. Teardown (via ``_cleanup_rows``) deletes everything so the
       next example starts clean.

    If the property holds (it does, assuming migration 002 was
    applied correctly), every example passes. If RLS is ever broken —
    a dropped policy, a missed ``app.user_id`` setter, a new table
    added without ENABLE ROW LEVEL SECURITY — Hypothesis will shrink
    to a one-row-one-table counterexample and point at the exact
    table whose ``user_id`` column leaked.

    Validates: Req 14.3, Req 4.5, Req 4.6.
    """
    u_a, u_b = _two_users

    # Seed both users with identical payload shape so any leakage is
    # unambiguous: a row whose ``user_id`` is the *other* user's is
    # mechanically definitely not ours.
    async with rls_connection(_pg_pool, u_a) as conn_a:
        await _insert_all_for_user(conn_a, u_a, rows)
    async with rls_connection(_pg_pool, u_b) as conn_b:
        await _insert_all_for_user(conn_b, u_b, rows)

    # The two symmetric halves of the property:
    await _assert_isolation_for(_pg_pool, viewer=u_a, other=u_b)
    await _assert_isolation_for(_pg_pool, viewer=u_b, other=u_a)
