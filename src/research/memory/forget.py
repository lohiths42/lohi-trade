"""``memory.forget(user_id, scope)`` — cross-layer deletion dispatch (design §3.4, §14).

This module implements the user-facing "forget" operation required by
Req 4.8 and Req 4.9: deleting a tenant's memory entries across all
three layers — Working_Memory (Redis), Semantic_Memory (Postgres +
optional vector), and Episodic_Memory (Postgres) — in one call,
optionally narrowed by a ``scope`` token.

The function is a thin dispatcher: it owns the scope vocabulary and
the aggregation of the three per-layer delete counts, but pushes the
actual DELETE / SCAN work into the layer-specific classes. That
boundary matters for Req 4.9 (≤5 s for up to 10k rows): the layer
classes already use efficient primitives — ``SCAN_ITER`` for Redis,
bulk RLS-scoped ``DELETE`` in Postgres — and this module adds no
extra round trips beyond the audit-log write.

Scope vocabulary
----------------
Exactly five shapes are accepted:

* ``"all"`` — every layer for the tenant (wipes the user's research
  memory entirely).
* ``"working"`` — Redis only (every conversation for the tenant).
* ``"semantic"`` — Postgres semantic rows only.
* ``"episodic"`` — Postgres episodic rows only.
* ``"symbol:<SYMBOL>"`` — per-symbol scope: episodic rows for that
  symbol plus semantic rows with ``kind == "symbol_fact:<SYMBOL>"``.
  Working memory is **not** touched by symbol-scoped forget because
  Working_Memory is keyed by ``conv_id`` rather than symbol; there is
  no correct way to prune a conversation "by symbol" without
  re-reading and re-writing every list, which is expressly out of
  scope for this task.

Any other scope string raises :class:`ValueError` with a message that
enumerates the valid shapes — a clean contract failure at the service
boundary is preferable to silently deleting nothing.

Audit logging
-------------
The audit-log row required by Req 4.9 (``actor=user``,
``action=memory_forget``) is produced by the caller-supplied
``audit_log_writer`` callback, not by this module's own SQL. Decoupling
the writer lets the gateway layer plug in the existing
``research_audit_log`` insertion path (which is append-only via the
``no_delete``/``no_update`` rules from migration 002) without this
module needing a direct Postgres dependency of its own. Passing
``audit_log_writer=None`` disables the audit write, which is what the
unit and property tests do — the RLS-level audit-log invariant lives
in its own suite.

Requirements: 4.8, 4.9
Design: §3.4, §14
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Awaitable, Callable, Final
from uuid import UUID

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.research.memory.episodic import EpisodicMemory
    from src.research.memory.semantic import SemanticMemory
    from src.research.memory.working import WorkingMemory


__all__ = ["forget_memory"]


logger = logging.getLogger(__name__)


# The fixed scope tokens. Symbol-scoped calls use the ``symbol:``
# prefix separately (see ``_parse_symbol_scope``). Keeping the set
# frozen makes the ``ValueError`` message stable and lets static
# analyzers catch typos in caller code.
_FIXED_SCOPES: Final[frozenset[str]] = frozenset(
    {"all", "working", "semantic", "episodic"}
)

_SYMBOL_PREFIX: Final[str] = "symbol:"

# The semantic-memory ``kind`` template used by symbol-scoped forget.
# ``SemanticMemory.add`` already documents ``symbol_fact:<SYMBOL>`` as
# a valid kind (see ``_KNOWN_KINDS`` and the ``symbol_fact:`` branch
# of the soft-validation log in ``semantic.py``). Keeping the template
# here — rather than importing a constant from ``semantic.py`` —
# avoids a circular-looking import and documents the coupling
# explicitly at the dispatch site.
_SYMBOL_FACT_KIND_TEMPLATE: Final[str] = "symbol_fact:{symbol}"


async def forget_memory(
    user_id: UUID,
    scope: str,
    *,
    working: "WorkingMemory",
    semantic: "SemanticMemory",
    episodic: "EpisodicMemory",
    audit_log_writer: Callable[[UUID, str, dict], Awaitable[None]] | None = None,
) -> dict:
    """Delete memory entries for ``user_id`` at the given ``scope``.

    Dispatches to the three layer classes per the scope vocabulary
    documented in the module docstring and returns a structured
    summary. The return shape is::

        {
            "scope": "<the input scope>",
            "working_deleted": int,
            "semantic_deleted": int,
            "episodic_deleted": int,
        }

    All three counts are always present, so callers never need to
    special-case by scope. Layers that a given scope does not touch
    report ``0``.

    Ordering
    --------
    The three deletions run sequentially in a fixed order — working,
    semantic, episodic — rather than concurrently. Two reasons:

    1. **Failure semantics.** If the semantic delete raises, the
       working delete has already succeeded. Running them
       concurrently would leave the caller unable to tell which
       succeeded from the exception alone; sequential order plus
       the partial counts would, but it would also complicate the
       tests. Sequential is simpler and the performance budget
       (Req 4.9: ≤5 s for 10k rows) has plenty of headroom.
    2. **Audit-log semantics.** The audit row is written with the
       final aggregate counts. If any layer raises, no audit row is
       written — the caller sees the exception and can retry.
       Writing a "partial" audit row would obscure the real state.

    Parameters
    ----------
    user_id:
        The tenant whose memory is being pruned.
    scope:
        One of ``"all"``, ``"working"``, ``"semantic"``,
        ``"episodic"``, or ``"symbol:<SYMBOL>"``. Any other string
        raises :class:`ValueError`.
    working, semantic, episodic:
        The three memory-layer instances. Injected rather than
        constructed here so the gateway keeps ownership of their
        lifecycle (Redis client, asyncpg pool) and tests can swap in
        fakes.
    audit_log_writer:
        Optional async callable invoked after a successful deletion
        with ``(user_id, "memory_forget", payload)``. ``payload``
        includes the scope and the three per-layer counts (Req 4.9).
        Set to ``None`` in tests that do not exercise the audit
        path.

    Returns
    -------
    dict
        Summary of what was deleted; see the module docstring above.

    Raises
    ------
    ValueError
        If ``scope`` is not one of the documented shapes.

    Requirements: 4.8, 4.9
    Design: §3.4, §14
    """
    working_deleted = 0
    semantic_deleted = 0
    episodic_deleted = 0

    if scope == "all":
        # No ``conv_id`` → wipe every conversation for the tenant.
        working_deleted = await working.forget(user_id)
        semantic_deleted = await semantic.delete(user_id)
        episodic_deleted = await episodic.delete(user_id)

    elif scope == "working":
        working_deleted = await working.forget(user_id)

    elif scope == "semantic":
        semantic_deleted = await semantic.delete(user_id)

    elif scope == "episodic":
        episodic_deleted = await episodic.delete(user_id)

    elif scope.startswith(_SYMBOL_PREFIX):
        symbol = _parse_symbol_scope(scope)
        # Episodic rows are keyed directly by ``symbol``. Semantic
        # rows use the ``symbol_fact:<SYMBOL>`` kind convention from
        # :mod:`semantic`, so the two deletes together cover every
        # row that a reasonable caller would think of as "memory
        # about SYMBOL".
        episodic_deleted = await episodic.delete(user_id, symbol=symbol)
        semantic_deleted = await semantic.delete(
            user_id,
            kind=_SYMBOL_FACT_KIND_TEMPLATE.format(symbol=symbol),
        )
        # Working memory is intentionally untouched here — see the
        # module docstring for why.

    else:
        raise ValueError(
            f"unknown memory.forget scope: {scope!r}; "
            f"valid scopes are: 'all', 'working', 'semantic', "
            f"'episodic', or 'symbol:<SYMBOL>'"
        )

    result = {
        "working_deleted": working_deleted,
        "semantic_deleted": semantic_deleted,
        "episodic_deleted": episodic_deleted,
        "scope": scope,
    }

    # Req 4.9: audit log row on every invocation. The writer is
    # responsible for the actual INSERT into ``research_audit_log``
    # — this module only supplies the structured payload.
    if audit_log_writer is not None:
        await audit_log_writer(
            user_id,
            "memory_forget",
            {
                "scope": scope,
                "working_deleted": working_deleted,
                "semantic_deleted": semantic_deleted,
                "episodic_deleted": episodic_deleted,
            },
        )

    logger.info(
        "memory.forget: user_id=%s scope=%s working=%d semantic=%d episodic=%d",
        user_id,
        scope,
        working_deleted,
        semantic_deleted,
        episodic_deleted,
    )
    return result


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _parse_symbol_scope(scope: str) -> str:
    """Extract ``SYMBOL`` from a ``symbol:SYMBOL`` scope string.

    Raises :class:`ValueError` when the prefix is present but the
    symbol is empty (``"symbol:"``). Callers should therefore pass
    the whole ``scope`` through the top-level ``ValueError`` path
    rather than invoking this helper directly; it is internal to
    :func:`forget_memory`.
    """
    symbol = scope[len(_SYMBOL_PREFIX):].strip()
    if not symbol:
        raise ValueError(
            "memory.forget scope 'symbol:' requires a non-empty symbol"
        )
    return symbol
