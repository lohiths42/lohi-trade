"""Provider factory registry with one-line extension pattern (design §3.1, §9).

This module is the single seam through which the rest of ``src/research/``
acquires a concrete ``LLMProvider``, ``EmbeddingsProvider``, or
``VectorStore``. Adding a new backend is deliberately cheap (Req 2.12):

1. Drop a new file under ``src/research/providers/{llm,embeddings,vector_store}/``
   exposing ``build(cfg: dict) -> <Protocol>``.
2. Add **one line** to the corresponding ``*_FACTORIES`` dict below.

That is the entire contract. Operators flip providers by editing
``config/settings.yaml`` (design §7.1) — no code change, no restart hook,
no plumbing outside this file. The provider-swap property test in Task
2.20 / Req 14.2 asserts that the shape returned by the builders is
indistinguishable across swaps.

Lazy imports
------------
Factories are registered as ``"<module>:<attr>"`` strings rather than
imported callables. The module is imported the first time the factory is
resolved (see ``_resolve``). This keeps this file free of concrete-adapter
imports — which is required so that:

* The registry can be imported without pulling in optional third-party
  dependencies (``qdrant-client``, ``lancedb``, ``sentence-transformers``,
  ``chromadb``, …). Task 1.6 needs ``from .providers import registry`` to
  work on a bare install.
* Circular-import risk between adapter modules and ``base.py`` is
  eliminated.

Tests and advanced call sites MAY bypass the string convention and
register a callable directly (see ``register_llm`` / ``register_embeddings``
/ ``register_vector_store``).

Config shape
------------
Every builder consumes the flat config dict for a single provider — the
same shape that appears under ``research.providers.*`` and
``research.vector_store`` in ``config/settings.yaml``:

* LLM blocks (``research.providers.chat|summarisation|judge``)
    name the factory via ``cfg["provider"]``.
* Embeddings block (``research.providers.embeddings``)
    names the factory via ``cfg["provider"]``.
* Vector-store block (``research.vector_store``)
    names the factory via ``cfg["backend"]`` (matches design §8 /
    ``backend: auto``). Each backend's sub-dict (``cfg["chroma"]`` /
    ``cfg["pgvector"]`` / …) is forwarded to that backend's ``build``
    alongside the top-level block so adapters can read both.

Satisfies
---------
Req 2.12, design §3.1, §9.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable
from typing import Any

from src.utils.logger import get_logger

from .base import EmbeddingsProvider, LLMProvider, VectorStore
from .errors import CloudProviderForbiddenError, UnknownProviderError
from .vector_store.autoselect import probe_pgvector_sync

logger = get_logger("ProviderRegistry")

# --------------------------------------------------------------------------- #
# Factory type                                                                #
# --------------------------------------------------------------------------- #
#
# A factory is either:
#   * a string ``"<module>:<attr>"`` resolved lazily by ``_resolve``; or
#   * a ``Callable[[dict], <Protocol>]`` registered directly (tests).
#
# Using ``Any`` here keeps the dict annotations readable; the builders
# narrow the return type when they call the resolved callable.
Factory = str | Callable[[dict], Any]


# --------------------------------------------------------------------------- #
# LLM registry (Req 2.4, Req 2.7, design §3.1, §9)                            #
# --------------------------------------------------------------------------- #
#
# One line per adapter. Concrete adapter files land in Tasks 2.3–2.10.
# They self-register neither at import time nor via a decorator — the
# single point of registration is this dict, so the "new provider = new
# file + one line here" contract is visually obvious.
LLM_FACTORIES: dict[str, Factory] = {
    "nvidia_nim": "src.research.providers.llm.nvidia_nim:build",  # Task 2.3
    "openai": "src.research.providers.llm.openai:build",  # Task 2.4
    "anthropic": "src.research.providers.llm.anthropic:build",  # Task 2.5
    "gemini": "src.research.providers.llm.gemini:build",  # Task 2.6
    "groq": "src.research.providers.llm.groq:build",  # Task 2.7
    "together": "src.research.providers.llm.together:build",  # Task 2.8
    "openrouter": "src.research.providers.llm.openrouter:build",  # Task 2.9
    "ollama": "src.research.providers.llm.ollama:build",  # Task 2.10
    # Add a new LLM provider here:
    # "mistral":   "src.research.providers.llm.mistral:build",
}


# --------------------------------------------------------------------------- #
# Embeddings registry (Req 2.5, design §3.1, §9)                              #
# --------------------------------------------------------------------------- #
EMBEDDINGS_FACTORIES: dict[str, Factory] = {
    "sentence_transformers": "src.research.providers.embeddings.sentence_transformers:build",  # Task 2.11
    "nvidia_nim": "src.research.providers.embeddings.nvidia_nim:build",  # Task 2.12
    "openai": "src.research.providers.embeddings.openai:build",  # Task 2.13
    "ollama": "src.research.providers.embeddings.ollama:build",  # Task 2.14
    # Add a new embeddings provider here.
}


# --------------------------------------------------------------------------- #
# Vector-store registry (Req 2.6, Req 2.13–2.15, design §3.1, §8, §9)         #
# --------------------------------------------------------------------------- #
VECTOR_STORE_FACTORIES: dict[str, Factory] = {
    "chroma": "src.research.providers.vector_store.chroma:build",  # Task 2.15
    "pgvector": "src.research.providers.vector_store.pgvector:build",  # Task 2.16
    "qdrant": "src.research.providers.vector_store.qdrant:build",  # Task 2.17
    "lancedb": "src.research.providers.vector_store.lancedb:build",  # Task 2.18
    # Add a new vector-store backend here.
}


# --------------------------------------------------------------------------- #
# Lazy resolution                                                             #
# --------------------------------------------------------------------------- #


def _resolve(factory: Factory) -> Callable[[dict], Any]:
    """Return a callable factory, importing the target module on first use.

    Accepts either a ``"<module>:<attr>"`` string or an already-callable
    factory. Strings are imported via ``importlib.import_module`` so this
    module has zero top-level imports of concrete adapter packages.
    """
    if callable(factory):
        return factory
    if not isinstance(factory, str) or ":" not in factory:
        raise TypeError(
            "Factory must be a callable or a 'module:attr' string; " f"got {factory!r}.",
        )
    module_path, attr = factory.split(":", 1)
    module = importlib.import_module(module_path)
    resolved = getattr(module, attr)
    if not callable(resolved):
        raise TypeError(
            f"Resolved factory {factory!r} is not callable: {resolved!r}.",
        )
    return resolved


def _lookup(
    registry: dict[str, Factory],
    kind: str,
    name: str,
) -> Callable[[dict], Any]:
    """Fetch a factory by name or raise ``UnknownProviderError``.

    The error message lists every registered key so operator typos are
    self-diagnosing (Req 2.12).
    """
    try:
        factory = registry[name]
    except KeyError as exc:
        raise UnknownProviderError(
            kind=kind,
            name=name,
            registered=tuple(sorted(registry)),
        ) from exc
    return _resolve(factory)


# --------------------------------------------------------------------------- #
# Vector-store auto-selection (Req 2.13–2.15, design §8)                      #
# --------------------------------------------------------------------------- #
#
# When ``research.vector_store.backend == "auto"``, the registry resolves
# the concrete backend **once** at boot by probing Postgres for the
# ``vector`` extension (design §8 decision tree). The result is cached
# here so subsequent ``get_vector_store`` calls are free and the gateway's
# ``GET /api/v2/research/health`` endpoint can surface the resolved
# backend without triggering a second probe (Req 7.7).
#
# The single decision log line is emitted at INFO level via the
# structured ``src.utils.logger`` so it is captured alongside every
# other boot-time component decision (design §15).

# Resolved backend from the last (and only) auto probe. ``None`` means
# the probe has not yet fired — i.e. ``get_vector_store`` has not been
# called with ``backend == "auto"`` since process start. Uppercase
# module-level constant name signals "set once, read everywhere".
_AUTO_RESOLVED_BACKEND: str | None = None


def get_resolved_vector_store_backend() -> str | None:
    """Return the cached auto-resolved backend name, or ``None`` if unresolved.

    Read-only accessor intended for the gateway's health endpoint
    (``GET /api/v2/research/health``, Req 7.7). Does **not** trigger a
    probe — returning ``None`` simply means no caller has requested an
    ``auto`` resolution yet, and the health endpoint should report the
    ``vector_store`` component as ``"pending"`` without spawning I/O on
    the request path.
    """
    return _AUTO_RESOLVED_BACKEND


def reset_auto_backend_cache() -> None:
    """Clear the cached auto-resolved backend (test seam).

    Production code never calls this — the cache is deliberately set
    once per process so the probe runs at most once (design §8). Tests
    that want to exercise multiple branches of the §8 decision tree in
    the same process use this helper to reset state between cases.
    """
    global _AUTO_RESOLVED_BACKEND
    _AUTO_RESOLVED_BACKEND = None


def _resolve_auto_backend(cfg: dict) -> str:
    """Resolve ``backend='auto'`` → ``'pgvector'`` if the probe hits, else ``'chroma'``.

    Caches the decision on :data:`_AUTO_RESOLVED_BACKEND` so the probe
    fires at most once per process. Logs the decision exactly once at
    INFO level via the project logger.

    DSN resolution order (design §8):

    1. ``cfg["pgvector"]["dsn"]`` — explicit DSN in the vector-store
       config block wins. This is the path operators take when
       ``research.vector_store.pgvector.dsn`` is set in
       ``config/settings.yaml``.
    2. ``DATABASE_URL`` environment variable — the gateway's existing
       convention, used when the vector-store block inherits from the
       main Postgres connection.
    3. Neither set — the probe is skipped and the resolution falls
       through to Chroma (design §8: "DB unreachable → use chroma").

    Returns either ``"pgvector"`` or ``"chroma"``. Never raises —
    :func:`probe_pgvector_sync` collapses every failure mode to
    ``False``.
    """
    global _AUTO_RESOLVED_BACKEND

    if _AUTO_RESOLVED_BACKEND is not None:
        return _AUTO_RESOLVED_BACKEND

    # DSN from config block first, then environment. ``cfg.get`` with a
    # default protects against both missing ``pgvector`` sub-block and
    # a ``pgvector`` sub-block that does not set ``dsn``.
    pgvector_cfg = cfg.get("pgvector") or {}
    dsn = (pgvector_cfg.get("dsn") or os.environ.get("DATABASE_URL") or "").strip()

    if not dsn:
        _AUTO_RESOLVED_BACKEND = "chroma"
        logger.info(
            "Lohi-Research vector store auto-selected: chroma "
            "(pgvector probe: skipped — no DSN configured)",
            extra={"backend": "chroma", "probe_result": None, "reason": "no_dsn"},
        )
        return _AUTO_RESOLVED_BACKEND

    probe_result = probe_pgvector_sync(dsn)
    resolved = "pgvector" if probe_result else "chroma"
    _AUTO_RESOLVED_BACKEND = resolved
    logger.info(
        f"Lohi-Research vector store auto-selected: {resolved} "
        f"(pgvector probe: {probe_result})",
        extra={"backend": resolved, "probe_result": probe_result},
    )
    return resolved


# --------------------------------------------------------------------------- #
# Offline-mode enforcement (Req 9.4, design §14)                              #
# --------------------------------------------------------------------------- #
#
# When ``LOHI_RESEARCH_OFFLINE=true`` (design §15 workflow F, Req 7.5),
# the registry refuses to instantiate any cloud LLM or cloud embeddings
# adapter and raises :class:`CloudProviderForbiddenError` naming the
# offending provider and role (design §14 "offline enforcement").
#
# The enforcement is done at the **registry edge** (``get_llm`` /
# ``get_embeddings`` entry) rather than inside each adapter so no import
# or factory resolution happens for a forbidden provider — a cloud
# adapter that ships its own SDK (``nvidia_nim``, ``openai``, etc.)
# never gets the chance to perform its own network handshake.
#
# Vector stores are intentionally **not** subject to this guard — every
# supported backend (Chroma, pgvector, Qdrant, LanceDB) is local-capable
# (design §3.1, Req 2.6).
_CLOUD_LLM_PROVIDERS: frozenset[str] = frozenset(
    {
        "nvidia_nim",
        "openai",
        "anthropic",
        "gemini",
        "groq",
        "together",
        "openrouter",
    },
)

_CLOUD_EMBEDDINGS_PROVIDERS: frozenset[str] = frozenset(
    {
        "nvidia_nim",
        "openai",
    },
)


def _is_offline() -> bool:
    """Return ``True`` when ``LOHI_RESEARCH_OFFLINE`` is truthy (Req 9.4).

    Accepted truthy values are ``"true"``, ``"1"``, and ``"yes"`` in any
    case; any other value — including unset — resolves to ``False``.
    Matches the design §15 workflow F env-var convention and the
    ``research.offline_mode: ${LOHI_RESEARCH_OFFLINE:false}`` interpolation
    in ``config/settings.yaml``.
    """
    return os.environ.get("LOHI_RESEARCH_OFFLINE", "").strip().lower() in (
        "true",
        "1",
        "yes",
    )


# --------------------------------------------------------------------------- #
# Public builders                                                             #
# --------------------------------------------------------------------------- #


def get_llm(cfg: dict) -> LLMProvider:
    """Build the ``LLMProvider`` named by ``cfg['provider']`` (Req 2.4).

    ``cfg`` is the flat per-agent block from ``research.providers.<role>``
    in ``config/settings.yaml``; it is forwarded verbatim to the adapter's
    ``build`` so new fields can be added without touching this file.

    Offline-mode enforcement (Req 9.4, design §14)
    ----------------------------------------------
    When ``LOHI_RESEARCH_OFFLINE=true`` the caller is refused a cloud
    LLM adapter: the provider name is compared against
    :data:`_CLOUD_LLM_PROVIDERS` **before** the factory lookup, so no
    import or SDK initialisation happens for a cloud provider. The
    only LLM provider allowed offline is ``ollama`` (design §3.1).
    """
    name = cfg["provider"]
    if _is_offline() and name in _CLOUD_LLM_PROVIDERS:
        raise CloudProviderForbiddenError(provider=name, role="llm")
    factory = _lookup(LLM_FACTORIES, "llm", name)
    return factory(cfg)


def get_embeddings(cfg: dict) -> EmbeddingsProvider:
    """Build the ``EmbeddingsProvider`` named by ``cfg['provider']`` (Req 2.5).

    Offline-mode enforcement (Req 9.4, design §14)
    ----------------------------------------------
    Mirrors :func:`get_llm`: when ``LOHI_RESEARCH_OFFLINE=true`` the
    caller is refused a cloud embeddings adapter. Allowed offline
    embeddings providers are ``sentence_transformers`` (the project
    default, design §3.1) and ``ollama``.
    """
    name = cfg["provider"]
    if _is_offline() and name in _CLOUD_EMBEDDINGS_PROVIDERS:
        raise CloudProviderForbiddenError(provider=name, role="embeddings")
    factory = _lookup(EMBEDDINGS_FACTORIES, "embeddings", name)
    return factory(cfg)


def get_vector_store(cfg: dict) -> VectorStore:
    """Build the ``VectorStore`` named by ``cfg['backend']`` (Req 2.6, 2.13–2.15).

    ``cfg`` is the full ``research.vector_store`` block, i.e. it contains
    ``backend`` plus the per-backend sub-dicts (``chroma``, ``pgvector``,
    ``qdrant``, ``lancedb``) — the adapter's ``build`` picks its own
    sub-block by name.

    Backend resolution
    ------------------
    * ``backend == "auto"`` — resolves once at boot via
      :func:`_resolve_auto_backend`, which probes Postgres for the
      ``vector`` extension (design §8). On hit → ``pgvector``;
      otherwise → ``chroma``. The resolved backend is cached on the
      module so subsequent calls never re-probe; the gateway's health
      endpoint reads the cached value through
      :func:`get_resolved_vector_store_backend`. Task 3.2 / Req 2.14.
    * Any other ``backend`` value (``"chroma"``, ``"pgvector"``,
      ``"qdrant"``, ``"lancedb"``, …) is treated as an **operator
      override** — the probe is skipped entirely and the named factory
      is used directly. Unknown names raise ``UnknownProviderError``.
      Task 3.2 / Req 2.15.
    """
    backend = cfg["backend"]

    # --------------------------------------------------------------- #
    # ``backend: auto`` — resolve once, then dispatch (design §8).    #
    # --------------------------------------------------------------- #
    # The resolution is cached on the module (see
    # ``_AUTO_RESOLVED_BACKEND``) so a running gateway probes Postgres
    # at most once per process lifetime. Operator overrides
    # (``backend`` != ``"auto"``) skip this branch entirely and go
    # straight to the factory lookup below — Req 2.15 guarantees the
    # explicit setting always wins.
    if backend == "auto":
        resolved = _resolve_auto_backend(cfg)
        # Rebuild cfg with the resolved backend and recurse exactly
        # once. We don't mutate the caller's dict — the
        # ``research.vector_store`` block lives in settings and is
        # expected to stay ``"auto"`` so the health endpoint can
        # surface the original intent alongside the resolved value.
        effective_cfg = {**cfg, "backend": resolved}
        return get_vector_store(effective_cfg)

    factory = _lookup(VECTOR_STORE_FACTORIES, "vector_store", backend)
    return factory(cfg)


# --------------------------------------------------------------------------- #
# Test / runtime registration helpers                                         #
# --------------------------------------------------------------------------- #
#
# These are convenience wrappers for the rare caller that needs to inject
# a factory at runtime — primarily the ``FakeLLMProvider`` / ``FakeEmbeddingsProvider``
# / ``FakeVectorStore`` used in Phase 6–12 tests (Task 2.19). Production
# code should prefer editing the ``*_FACTORIES`` dicts above so the
# "new provider = one line" contract stays visible (design §9).


def register_llm(name: str, factory: Factory) -> None:
    """Register an ``LLMProvider`` factory under ``name`` (test seam)."""
    LLM_FACTORIES[name] = factory


def register_embeddings(name: str, factory: Factory) -> None:
    """Register an ``EmbeddingsProvider`` factory under ``name`` (test seam)."""
    EMBEDDINGS_FACTORIES[name] = factory


def register_vector_store(name: str, factory: Factory) -> None:
    """Register a ``VectorStore`` factory under ``name`` (test seam)."""
    VECTOR_STORE_FACTORIES[name] = factory


__all__ = [
    # Registries
    "LLM_FACTORIES",
    "EMBEDDINGS_FACTORIES",
    "VECTOR_STORE_FACTORIES",
    # Builders
    "get_llm",
    "get_embeddings",
    "get_vector_store",
    # Auto-selection
    "get_resolved_vector_store_backend",
    "reset_auto_backend_cache",
    # Test seams
    "register_llm",
    "register_embeddings",
    "register_vector_store",
    # Re-export for convenience
    "UnknownProviderError",
    "CloudProviderForbiddenError",
]
