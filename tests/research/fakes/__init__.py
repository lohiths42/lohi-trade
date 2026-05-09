"""Fake provider registry for Phase 6–12 tests (design §17.2, Req 14.7).

This package exposes three dependency-free, deterministic fakes that
implement the ``LLMProvider``, ``EmbeddingsProvider``, and
``VectorStore`` Protocols from ``src/research/providers/base.py``:

* :class:`FakeLLMProvider`        — configurable latency + canned text.
* :class:`FakeEmbeddingsProvider` — SHA-256-seeded deterministic 384-dim.
* :class:`FakeVectorStore`        — in-memory list-backed store.

Tests select the fakes via config through two layers:

1. A **parallel** ``FAKE_FACTORIES`` dict-of-dicts that mirrors the
   shape of the production registry (``LLM_FACTORIES``,
   ``EMBEDDINGS_FACTORIES``, ``VECTOR_STORE_FACTORIES``). Consumers that
   already look up factories in a nested ``{"llm": {...}, ...}`` map
   (e.g. parameterised property tests over backends) can import this
   dict directly.
2. A :func:`install_fakes` helper that registers the fakes under the
   name ``"fake"`` in the **production** registry via the existing
   ``register_llm`` / ``register_embeddings`` / ``register_vector_store``
   test seams. After ``install_fakes()`` runs (typically from a pytest
   fixture), ``get_llm({"provider": "fake"})`` returns a
   ``FakeLLMProvider`` instance — which is exactly how the provider-swap
   property (Task 2.20, Req 14.2) drives its generated configurations
   through the real registry without touching network-bound adapters.

Factory input contract
----------------------
Each fake factory receives the same flat ``cfg`` dict the production
factories do. To keep construction flexible without over-coupling to
``settings.yaml``, the fake factories honour an optional
``cfg["fake_kwargs"]`` sub-dict: if present, its contents are forwarded
to the fake's ``__init__`` as keyword arguments. This lets tests tune
``latency_ms``, ``canned_completion``, ``dim``, and so on per run
without a bespoke factory per variation.

Example::

    from tests.research.fakes import install_fakes
    from src.research.providers.registry import get_llm

    install_fakes()
    llm = get_llm({"provider": "fake", "fake_kwargs": {"latency_ms": 50}})
"""

from __future__ import annotations

from typing import Any, Callable

from src.research.providers import registry as _registry

from .embeddings import FakeEmbeddingsProvider
from .llm import FakeLLMProvider
from .vector_store import FakeVectorStore

__all__ = [
    "FakeLLMProvider",
    "FakeEmbeddingsProvider",
    "FakeVectorStore",
    "FAKE_FACTORIES",
    "install_fakes",
]


# --------------------------------------------------------------------------- #
# Parallel FAKE_FACTORIES registry (mirrors production shape)                 #
# --------------------------------------------------------------------------- #
#
# The production registry (``src/research/providers/registry.py``) keeps
# three separate top-level dicts. Mirroring them as a single nested dict
# here serves two purposes:
#
# * Tests that parametrise across provider *kinds* (LLM / embeddings /
#   vector store) can enumerate a single container.
# * ``install_fakes`` uses this structure to drive the three
#   ``register_*`` calls in one place, keeping the fake-registration
#   story in sync with the real registry's "one line per backend"
#   contract (Req 2.12).


def _build_fake_llm(cfg: dict) -> FakeLLMProvider:
    """Build a :class:`FakeLLMProvider` from a flat config block.

    Honours ``cfg["fake_kwargs"]`` so tests can tune construction
    without a bespoke factory per variation.
    """
    return FakeLLMProvider(**cfg.get("fake_kwargs", {}))


def _build_fake_embeddings(cfg: dict) -> FakeEmbeddingsProvider:
    """Build a :class:`FakeEmbeddingsProvider` from a flat config block."""
    return FakeEmbeddingsProvider(**cfg.get("fake_kwargs", {}))


def _build_fake_vector_store(cfg: dict) -> FakeVectorStore:
    """Build a :class:`FakeVectorStore`. Config is ignored (no knobs)."""
    return FakeVectorStore()


FAKE_FACTORIES: dict[str, dict[str, Callable[[dict], Any]]] = {
    "llm":          {"fake": _build_fake_llm},
    "embeddings":   {"fake": _build_fake_embeddings},
    "vector_store": {"fake": _build_fake_vector_store},
}


# --------------------------------------------------------------------------- #
# Production-registry installer                                               #
# --------------------------------------------------------------------------- #


def install_fakes() -> None:
    """Register every :data:`FAKE_FACTORIES` entry under ``"fake"`` in the
    production registry.

    After this call:

    * ``get_llm({"provider": "fake", ...})`` returns a ``FakeLLMProvider``.
    * ``get_embeddings({"provider": "fake", ...})`` returns a
      ``FakeEmbeddingsProvider``.
    * ``get_vector_store({"backend": "fake", ...})`` returns a
      ``FakeVectorStore``.

    Safe to call more than once — ``register_*`` is an assignment into a
    dict, so repeat calls simply overwrite the previous entry with the
    identical factory.

    Typical usage from a pytest fixture::

        @pytest.fixture(autouse=True)
        def _fakes():
            install_fakes()
    """
    _registry.register_llm("fake", _build_fake_llm)
    _registry.register_embeddings("fake", _build_fake_embeddings)
    _registry.register_vector_store("fake", _build_fake_vector_store)
