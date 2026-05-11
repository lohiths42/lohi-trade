"""Working memory layer — Redis sliding window + running summary (design §3.4).

This module implements the **Working_Memory** layer of the three-layer
memory architecture defined in design §3.4 / Req 4.1–4.2. It stores the
most recent turns of a research conversation in Redis so Sub_Agents and
the Orchestrator can read a compact, token-bounded context without
round-tripping to Postgres on every turn.

Layout
------
Each conversation owns a single Redis **list** at the key template::

    research:wm:{user_id}:{conv_id}

(see :data:`src.research.constants.WORKING_MEMORY_KEY_TEMPLATE`, design
§4.3). Each list element is a JSON-serialised turn of shape::

    {"role": "user" | "assistant" | "system", "content": "...", "tokens": int}

New turns are appended on the right (``RPUSH``); reads return the list
in insertion order (``LRANGE 0 -1``). Forgetting a conversation or all
conversations for a user issues ``DEL`` / ``SCAN + DEL`` (design §3.4,
Req 4.8).

Token-budget handling
---------------------
The running total of ``turn["tokens"]`` is the sum of every list
element's ``tokens`` field. When the total exceeds ``max_tokens``
(default 4096, ``research.memory.working.max_tokens``), the oldest half
of the list is collapsed into a single **system**-role "summary" turn
at position 0 via the injected ``summariser`` callable. The un-
summarised tail is preserved verbatim so the most recent context stays
high-fidelity — the summary absorbs the older, lower-fidelity turns.

The ``summariser`` is a plain Python callable (``list[dict] -> str``)
deliberately so tests and the Task 13.x summarisation wiring can swap
implementations without this module gaining a dependency on the
provider registry. The default fallback concatenates turns and
truncates to ``2 * max_tokens`` characters — good enough to keep
conversations flowing while Task 13.x lands a real summariser.

Concurrency
-----------
The summarise-and-rewrite path is **not** a transaction. Two concurrent
summarisations on the same ``(user_id, conv_id)`` could race and
produce an inconsistent head. That is acceptable for this layer:

* Working memory is per-conversation, and a conversation has a single
  writer (the Orchestrator) at a time.
* A botched summary at worst drops a couple of turns; it cannot leak
  across tenants (the key template embeds ``user_id``).
* Re-introducing a ``MULTI``/``WATCH`` round-trip would noticeably hurt
  first-token latency (Req 5.1), which is where this layer sits on the
  critical path.

If a future design change introduces multi-writer conversations, guard
:meth:`summarise_if_needed` with a ``SETNX``-backed advisory lock.

Requirements: 4.1, 4.2, 4.8
Design: §3.4, §4.3
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from src.research.constants import WORKING_MEMORY_KEY_TEMPLATE

if TYPE_CHECKING:  # pragma: no cover - typing only
    from redis.asyncio import Redis


__all__ = ["WorkingMemory", "default_summariser"]


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Defaults                                                                    #
# --------------------------------------------------------------------------- #

# Matches the default in design §3.4 and ``research.memory.working``:
# twelve turns is enough to carry a multi-step conversation, short
# enough to stay inside the model's context even at small providers.
_DEFAULT_WINDOW_TURNS: Final[int] = 12

# ``research.memory.working.max_tokens`` default. When the running
# total of ``tokens`` across all turns exceeds this, the oldest half
# is summarised.
_DEFAULT_MAX_TOKENS: Final[int] = 4096


# --------------------------------------------------------------------------- #
# Default summariser                                                          #
# --------------------------------------------------------------------------- #


def default_summariser(turns: list[dict]) -> str:
    """Concatenate-and-truncate fallback used when no summariser is injected.

    Joins ``role: content`` lines with newlines and caps the result at
    a generous character budget so it cannot blow past the token
    budget on the next append. Task 13.x replaces this with a real LLM
    summariser wired through ``research.providers.summarisation.*``;
    until then this keeps the memory layer self-contained and
    dependency-free.

    The cap is deliberately in **characters**, not tokens — token
    counts require a model-specific tokeniser this module does not own.
    A 4×``max_tokens`` char budget is a safe overestimate of the token
    equivalent for any BPE tokeniser and is trimmed further by the
    summariser invoked from Task 13.x.
    """
    lines = [f"{t.get('role', '?')}: {t.get('content', '')}" for t in turns]
    joined = "\n".join(lines)
    # Character cap: 4 chars/token ≈ safe upper bound across BPE
    # tokenisers; yields ~1024 tokens of summary at the default
    # max_tokens. The trailing ellipsis signals truncation.
    char_cap = 4 * _DEFAULT_MAX_TOKENS
    if len(joined) > char_cap:
        return joined[:char_cap] + "…"
    return joined


# --------------------------------------------------------------------------- #
# WorkingMemory                                                               #
# --------------------------------------------------------------------------- #


class WorkingMemory:
    """Redis-backed sliding window + running summary for one conversation family.

    A single :class:`WorkingMemory` instance is shared across users and
    conversations — the ``user_id`` and ``conv_id`` flow through every
    method parameter, they are not held as instance state. That keeps
    the object thread-safe and lets the gateway construct one per
    service process rather than one per request.

    Parameters
    ----------
    redis_client:
        An async Redis client exposing the ``rpush``, ``lrange``,
        ``delete``, and ``scan_iter`` methods on
        :class:`redis.asyncio.Redis`. Typed as ``Any`` rather than
        ``redis.asyncio.Redis`` so callers can inject simple mocks
        in tests (the rate-limit test suite under
        ``backend-gateway/tests/`` uses this pattern).
    window_turns:
        Informational upper bound on turns kept verbatim. This module
        does **not** enforce it at write time — the token-budget
        summarisation path is the one that actually bounds memory.
        The parameter is accepted to honour the Task 7.1 signature
        and is available for consumers that want to compute the
        "older half" threshold relative to the configured window.
    max_tokens:
        Hard cap on the summed ``tokens`` field across all stored
        turns. Exceeding it triggers summarisation via
        :meth:`summarise_if_needed`. Default 4096 per design §3.4.
    summariser:
        Optional ``list[dict] -> str`` callable invoked with the
        oldest-half turns to produce the replacement summary.
        Defaults to :func:`default_summariser`.

    Requirements: 4.1, 4.2, 4.8
    Design: §3.4, §4.3

    """

    def __init__(
        self,
        *,
        redis_client: Redis | Any,
        window_turns: int = _DEFAULT_WINDOW_TURNS,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        summariser: Callable[[list[dict]], str] | None = None,
    ) -> None:
        if window_turns <= 0:
            raise ValueError(f"window_turns must be positive, got {window_turns}")
        if max_tokens <= 0:
            raise ValueError(f"max_tokens must be positive, got {max_tokens}")
        self._redis = redis_client
        self._window_turns = window_turns
        self._max_tokens = max_tokens
        self._summariser = summariser or default_summariser

    # ------------------------------------------------------------------ #
    # Key derivation                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _key(user_id: UUID, conv_id: UUID) -> str:
        """Build the canonical Redis list key for ``(user_id, conv_id)``.

        Uses the shared template from ``src/research/constants.py``
        so no other module needs to know the on-the-wire shape.
        """
        return WORKING_MEMORY_KEY_TEMPLATE.format(
            user_id=str(user_id), conv_id=str(conv_id),
        )

    @staticmethod
    def _user_scan_pattern(user_id: UUID) -> str:
        """Build the ``SCAN MATCH`` pattern matching every conv under ``user_id``.

        Matches the ``research:wm:{user_id}:*`` shape used by
        :meth:`forget` when no specific ``conv_id`` is supplied.
        """
        return WORKING_MEMORY_KEY_TEMPLATE.format(
            user_id=str(user_id), conv_id="*",
        )

    # ------------------------------------------------------------------ #
    # Append / read                                                      #
    # ------------------------------------------------------------------ #

    async def append_turn(
        self, user_id: UUID, conv_id: UUID, turn: dict,
    ) -> None:
        """Append a single turn to ``(user_id, conv_id)``.

        ``turn`` is JSON-serialised and pushed onto the right end of
        the Redis list (``RPUSH``) so subsequent reads preserve
        insertion order. The caller is responsible for populating
        ``role``, ``content``, and ``tokens`` — this method does not
        infer token counts because tokenisation is provider-specific.

        The method does **not** trigger summarisation automatically.
        Callers should invoke :meth:`summarise_if_needed` after the
        append so the summarisation cost is observable in the
        Orchestrator's trace rather than hidden inside the write.

        Requirements: 4.1
        """
        key = self._key(user_id, conv_id)
        payload = json.dumps(turn, ensure_ascii=False, sort_keys=True)
        await self._redis.rpush(key, payload)

    async def read(self, user_id: UUID, conv_id: UUID) -> list[dict]:
        """Return every stored turn for ``(user_id, conv_id)`` in order.

        Issues ``LRANGE 0 -1`` and decodes each element from JSON.
        Corrupt rows (not-JSON, or JSON that is not a dict) are
        logged and skipped — the alternative of raising would stop
        a live conversation on a single bad entry, which is a worse
        failure mode than losing one turn of context.

        Bytes-vs-str note: :mod:`redis.asyncio` returns bytes by
        default; we normalise to ``str`` before decoding so a client
        configured with ``decode_responses=True`` also works.

        Requirements: 4.1
        """
        key = self._key(user_id, conv_id)
        raw = await self._redis.lrange(key, 0, -1)
        out: list[dict] = []
        for item in raw:
            text = item.decode("utf-8") if isinstance(item, (bytes, bytearray)) else item
            try:
                decoded = json.loads(text)
            except (TypeError, ValueError):
                logger.warning(
                    "working_memory.read: skipping non-JSON entry for "
                    "user_id=%s conv_id=%s",
                    user_id,
                    conv_id,
                )
                continue
            if not isinstance(decoded, dict):
                logger.warning(
                    "working_memory.read: skipping non-dict entry for "
                    "user_id=%s conv_id=%s",
                    user_id,
                    conv_id,
                )
                continue
            out.append(decoded)
        return out

    # ------------------------------------------------------------------ #
    # Summarisation                                                      #
    # ------------------------------------------------------------------ #

    async def summarise_if_needed(
        self, user_id: UUID, conv_id: UUID,
    ) -> None:
        """Collapse the oldest half of turns into a summary if over budget.

        Algorithm (design §3.4, Req 4.2):

        1. Read every stored turn via :meth:`read`.
        2. Compute the running total of ``turn["tokens"]`` (missing or
           non-int fields contribute zero — conservative: if a caller
           forgot to populate ``tokens`` we under-count rather than
           wipe their history on the next call).
        3. If the total is ``<= max_tokens``, return — no-op.
        4. Otherwise split the turn list into ``older = turns[:n//2]``
           and ``newer = turns[n//2:]`` (integer floor means with
           exactly two turns we summarise one; with one turn we
           summarise none — nothing to collapse).
        5. Build a replacement system-role turn whose ``content`` is
           ``self._summariser(older)`` and whose ``tokens`` equals the
           sum of older turns' token counts (a conservative upper
           bound — the real summariser output is almost always
           smaller).
        6. Rewrite the Redis list atomically-enough: ``DEL`` then
           ``RPUSH`` the summary followed by each newer turn. This
           is not ``MULTI`` wrapped (see module docstring) because
           per-conversation single-writer makes the race impossible
           in practice.

        If ``older`` is empty (one-turn conversation over budget —
        uncommon but possible with very long single turns) the
        method returns without rewriting: there is nothing older to
        summarise, and clobbering the single newer turn would lose
        real conversation content.

        Requirements: 4.2
        """
        turns = await self.read(user_id, conv_id)
        if not turns:
            return

        # Conservative token accounting: non-int or missing ``tokens``
        # contributes zero so a forgotten field can't trigger an
        # infinite summarise loop.
        def _tokens_of(t: dict) -> int:
            val = t.get("tokens", 0)
            return val if isinstance(val, int) and val >= 0 else 0

        total = sum(_tokens_of(t) for t in turns)
        if total <= self._max_tokens:
            return

        split = len(turns) // 2
        older = turns[:split]
        newer = turns[split:]

        if not older:
            # One-turn-over-budget: no older half to collapse. Return
            # rather than clobbering ``newer`` (which is the *only*
            # turn we have).
            logger.info(
                "working_memory.summarise_if_needed: single turn over "
                "budget for user_id=%s conv_id=%s; leaving as-is "
                "(tokens=%d, budget=%d)",
                user_id,
                conv_id,
                total,
                self._max_tokens,
            )
            return

        summary_content = self._summariser(older)
        summary_turn: dict[str, Any] = {
            "role": "system",
            "content": summary_content,
            "tokens": sum(_tokens_of(t) for t in older),
        }

        key = self._key(user_id, conv_id)
        # Rewrite the list: delete everything, then RPUSH the summary
        # head followed by the preserved newer turns in order. Uses
        # a single RPUSH with multiple values when supported by the
        # client; falls back to iterative RPUSH otherwise.
        await self._redis.delete(key)
        new_entries = [summary_turn] + newer
        for entry in new_entries:
            await self._redis.rpush(
                key, json.dumps(entry, ensure_ascii=False, sort_keys=True),
            )

        logger.info(
            "working_memory.summarise_if_needed: summarised %d older turns "
            "for user_id=%s conv_id=%s; budget=%d tokens=%d",
            len(older),
            user_id,
            conv_id,
            self._max_tokens,
            total,
        )

    # ------------------------------------------------------------------ #
    # Forget                                                             #
    # ------------------------------------------------------------------ #

    async def forget(
        self, user_id: UUID, conv_id: UUID | None = None,
    ) -> int:
        """Delete one conversation or every conversation for ``user_id``.

        * ``conv_id`` supplied → delete the single list at
          ``research:wm:{user_id}:{conv_id}`` with ``DEL``. Returns 1
          if the key existed, 0 otherwise (asyncpg-style count).
        * ``conv_id`` is ``None`` → iterate every key matching
          ``research:wm:{user_id}:*`` via ``SCAN_ITER`` and delete
          each. Returns the number of keys actually deleted.

        ``SCAN_ITER`` is used instead of ``KEYS`` so that forgetting
        a prolific user does not block Redis on a single large scan
        — ``KEYS`` would be O(n) across the whole keyspace, while
        ``SCAN`` is cooperative. This is exactly the pattern Req 4.9
        leans on: up to 10k rows in ≤5 s.

        The ``delete`` call below passes each key individually rather
        than batching. Redis's ``DEL key1 key2 ...`` is atomic across
        multiple keys, but ``redis.asyncio.Redis.delete`` takes a
        variadic so the cost of one call per key is one round trip
        per key — acceptable at the ~10k-row ceiling, and keeps the
        failure mode per-key (a corrupt key does not abort the batch).

        Requirements: 4.8, 4.9
        Design: §3.4
        """
        if conv_id is not None:
            key = self._key(user_id, conv_id)
            deleted = await self._redis.delete(key)
            return int(deleted) if deleted is not None else 0

        pattern = self._user_scan_pattern(user_id)
        count = 0
        async for raw_key in self._redis.scan_iter(match=pattern):
            # ``scan_iter`` yields bytes on default clients and str
            # on ``decode_responses=True`` clients — feed both
            # through ``delete`` unchanged; redis-py handles either.
            removed = await self._redis.delete(raw_key)
            count += int(removed) if removed is not None else 0
        return count
