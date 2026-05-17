"""Vector-store auto-selection decision-tree tests (Req 2.15, design §8).

This suite locks down the five branches of the ``research.vector_store``
backend decision tree from design §8 and the operator-override promise
in Req 2.15:

=====  ==========================================  =====================
Case   Input                                        Expected
=====  ==========================================  =====================
(a)    ``backend: auto`` + pgvector available      → pgvector
(b)    ``backend: auto`` + pgvector missing        → chroma
(b')   ``backend: auto`` + ``DATABASE_URL`` unset  → chroma (no probe)
(c)    explicit ``backend: chroma`` w/ pgvector    → chroma (no probe)
(d)    explicit ``backend: qdrant``                → qdrant (no probe)
(e)    unknown backend                              → ``UnknownProviderError``
=====  ==========================================  =====================

The registry does real adapter I/O at build time (chroma spins up an
embedded DuckDB, qdrant imports ``qdrant-client``, pgvector reaches
for the asyncpg pool). To keep this suite a pure unit test we
install in-memory **fake factories** via
:func:`registry.register_vector_store` for the duration of each test;
the ``_preserve_registries`` fixture snapshots and restores the
``*_FACTORIES`` dicts so overrides cannot leak between tests.

We also reset ``registry._AUTO_RESOLVED_BACKEND`` before and after
each test so the one-shot probe cache is never carried between cases
— otherwise a case-(a) cache hit would make case (b) silently assert
the wrong thing.
"""

from __future__ import annotations

import pytest

from src.research.providers import registry
from src.research.providers.errors import UnknownProviderError

# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _reset_auto_cache(monkeypatch):
    """Clear the module-level auto-backend cache around every test.

    :data:`registry._AUTO_RESOLVED_BACKEND` is set exactly once per
    process in production — first ``backend: auto`` resolution wins.
    For tests we need a clean slate on every case so that (for example)
    a prior ``pgvector`` resolution does not satisfy a later
    ``chroma``-expecting test without the probe ever running.

    ``monkeypatch.setattr`` restores the original value after the test,
    which pairs with the explicit pre-clear at the top so both halves
    of the fixture lifecycle see ``None``.
    """
    monkeypatch.setattr(registry, "_AUTO_RESOLVED_BACKEND", None)


@pytest.fixture(autouse=True)
def _preserve_registries():
    """Snapshot + restore the three ``*_FACTORIES`` dicts.

    Tests register fake factories via :func:`registry.register_vector_store`
    etc. Because the registry dicts are module-level singletons, a test
    that mutates them would otherwise leak state into every subsequent
    test in the process. We shallow-copy the dicts before the test and
    replace their contents from the snapshot afterwards so the dict
    **objects** survive (anything holding a reference to them stays
    valid) while their contents are reset.
    """
    llm_snapshot = dict(registry.LLM_FACTORIES)
    emb_snapshot = dict(registry.EMBEDDINGS_FACTORIES)
    vs_snapshot = dict(registry.VECTOR_STORE_FACTORIES)
    try:
        yield
    finally:
        registry.LLM_FACTORIES.clear()
        registry.LLM_FACTORIES.update(llm_snapshot)
        registry.EMBEDDINGS_FACTORIES.clear()
        registry.EMBEDDINGS_FACTORIES.update(emb_snapshot)
        registry.VECTOR_STORE_FACTORIES.clear()
        registry.VECTOR_STORE_FACTORIES.update(vs_snapshot)


# --------------------------------------------------------------------------- #
# Decision-tree cases                                                         #
# --------------------------------------------------------------------------- #


def test_auto_resolves_pgvector_when_extension_present(monkeypatch):
    """Case (a): ``backend: auto`` + pgvector available → pgvector.

    With ``DATABASE_URL`` set and the probe returning ``True``, the
    registry must dispatch to the ``pgvector`` factory and cache
    ``"pgvector"`` as the resolved backend for the health endpoint.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    monkeypatch.setattr(
        registry,
        "probe_pgvector_sync",
        lambda _dsn: True,
    )
    registry.register_vector_store(
        "pgvector",
        lambda cfg: "PGVECTOR_INSTANCE",
    )

    result = registry.get_vector_store({"backend": "auto"})

    assert result == "PGVECTOR_INSTANCE"
    assert registry.get_resolved_vector_store_backend() == "pgvector"


def test_auto_resolves_chroma_when_extension_missing(monkeypatch):
    """Case (b): ``backend: auto`` + pgvector missing → chroma.

    The probe returns ``False`` (extension absent, auth failure, or
    Postgres unreachable all collapse to this branch — see
    ``autoselect.probe_pgvector`` contract). The registry must fall
    through to the ``chroma`` factory and cache ``"chroma"``.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    monkeypatch.setattr(
        registry,
        "probe_pgvector_sync",
        lambda _dsn: False,
    )
    registry.register_vector_store(
        "chroma",
        lambda cfg: "CHROMA_INSTANCE",
    )

    result = registry.get_vector_store({"backend": "auto"})

    assert result == "CHROMA_INSTANCE"
    assert registry.get_resolved_vector_store_backend() == "chroma"


def test_auto_resolves_chroma_when_database_url_missing(monkeypatch):
    """Case (b'): ``backend: auto`` + ``DATABASE_URL`` unset → chroma.

    The registry short-circuits to Chroma without probing when no DSN
    is configured (design §8 "DB unreachable → use chroma"). We verify
    the short-circuit by making the probe raise if called — if the
    code path ever regresses to calling the probe with an empty DSN
    the test fails with a clear message.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)

    def _probe_must_not_run(_dsn):
        raise AssertionError(
            "probe_pgvector_sync should not be called when " "DATABASE_URL is unset",
        )

    monkeypatch.setattr(
        registry,
        "probe_pgvector_sync",
        _probe_must_not_run,
    )
    registry.register_vector_store(
        "chroma",
        lambda cfg: "CHROMA_INSTANCE",
    )

    result = registry.get_vector_store({"backend": "auto"})

    assert result == "CHROMA_INSTANCE"
    assert registry.get_resolved_vector_store_backend() == "chroma"


def test_explicit_chroma_bypasses_probe_even_when_pgvector_available(monkeypatch):
    """Case (c): operator override ``backend: chroma`` wins over auto-detect.

    Even when Postgres *would* satisfy the pgvector probe, an explicit
    ``backend: chroma`` in config must dispatch straight to the
    ``chroma`` factory without probing (Req 2.15). We enforce the
    "no probe" half by making the probe raise: if the override logic
    is broken and the probe runs, the ``AssertionError`` surfaces as
    a crystal-clear test failure.
    """

    def _probe_must_not_run(_dsn):
        raise AssertionError(
            "probe_pgvector_sync should not be called for an explicit " "backend override",
        )

    monkeypatch.setattr(
        registry,
        "probe_pgvector_sync",
        _probe_must_not_run,
    )
    registry.register_vector_store(
        "chroma",
        lambda cfg: "CHROMA_INSTANCE",
    )

    result = registry.get_vector_store({"backend": "chroma"})

    assert result == "CHROMA_INSTANCE"


def test_explicit_qdrant_bypasses_probe(monkeypatch):
    """Case (d): explicit ``backend: qdrant`` → qdrant (no probe).

    Symmetric to case (c): any explicit backend name wins, the probe
    must not run, and the named factory is dispatched directly.
    """

    def _probe_must_not_run(_dsn):
        raise AssertionError(
            "probe_pgvector_sync should not be called for an explicit " "backend override",
        )

    monkeypatch.setattr(
        registry,
        "probe_pgvector_sync",
        _probe_must_not_run,
    )
    registry.register_vector_store(
        "qdrant",
        lambda cfg: "QDRANT_INSTANCE",
    )

    result = registry.get_vector_store({"backend": "qdrant"})

    assert result == "QDRANT_INSTANCE"


def test_unknown_backend_raises_structured_error(monkeypatch):
    """Case (e): unknown backend → structured ``UnknownProviderError``.

    A typo or unsupported backend name must fail loudly with an error
    that names both the offending value and the registered
    alternatives so operators can fix the config without reading
    source (Req 2.12, design §9).
    """

    def _probe_must_not_run(_dsn):
        raise AssertionError(
            "probe_pgvector_sync should not be called for an explicit " "backend override",
        )

    monkeypatch.setattr(
        registry,
        "probe_pgvector_sync",
        _probe_must_not_run,
    )

    with pytest.raises(UnknownProviderError) as exc_info:
        registry.get_vector_store({"backend": "notarealbackend"})

    err = exc_info.value
    assert err.kind == "vector_store"
    assert err.name == "notarealbackend"
    # The registered tuple is the sorted snapshot of
    # ``VECTOR_STORE_FACTORIES`` keys at the moment the lookup fails.
    # It MUST include every backend we ship out of the box so operator
    # typos are self-diagnosing from the exception message alone.
    assert set(err.registered) >= {"chroma", "pgvector", "qdrant", "lancedb"}
    message = str(err)
    assert "notarealbackend" in message
    for name in ("chroma", "pgvector", "qdrant", "lancedb"):
        assert name in message
