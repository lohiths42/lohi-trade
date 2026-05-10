"""Centralised per-model similarity-floor lookup (Req 16.24, design §3.3, §12).

Why this lives in one file
--------------------------
Similarity-score magnitudes depend heavily on the embedding model that
produced them: a cosine of ``0.30`` from ``text-embedding-3-small`` is
meaningful, while the same ``0.30`` from ``text-embedding-ada-002``
(whose scores cluster near the top of the ``[-1, 1]`` range) is noise.
Design §3.3 therefore pins a **per-model floor**, and Req 16.24 requires
the Orchestrator to short-circuit to a refusal —
``"Insufficient evidence in the provided sources to answer this
question."`` — whenever :meth:`HybridRetriever.retrieve` returns zero
hits at or above that floor.

Keeping the lookup in a single helper gives every caller (the retriever
itself, the Orchestrator, the run trace, the health endpoint) the same
answer for a given ``model_id`` and makes it trivial to audit: any floor
drift is a one-file diff rather than a scattered-constant hunt.

Config override pattern
-----------------------
Operators tune floors by editing
``research.retrieval.similarity_floor.<model_id>`` in
``config/settings.yaml``. That block is passed in as ``config`` here —
a flat ``{model_id: float}`` mapping. When present, config values win
over the built-in defaults; when absent, the defaults below apply. An
unknown model falls through to a descriptive :class:`KeyError` so
misconfigurations surface loudly rather than silently returning a
wrong-magnitude floor.

Defaults (design §3.3, Decision-Log #6)
---------------------------------------
* ``BAAI/bge-small-en-v1.5``       — 0.25  (default offline; Req 2.5)
* ``BAAI/bge-base-en-v1.5``        — 0.30  (larger bge variant)
* ``text-embedding-3-small``       — 0.35  (OpenAI current-gen)
* ``text-embedding-ada-002``       — 0.75  (legacy OpenAI; compressed score range)
* ``nomic-embed-text``             — 0.35  (Ollama default embeddings)
"""

from __future__ import annotations

__all__ = ["DEFAULT_FLOORS", "similarity_floor_for"]


# --------------------------------------------------------------------------- #
# Built-in defaults                                                           #
# --------------------------------------------------------------------------- #
#
# Module-private source of truth. Exposed read-only via ``DEFAULT_FLOORS``
# below so tests can introspect without reaching into a ``_`` name.
_DEFAULT_FLOORS: dict[str, float] = {
    "BAAI/bge-small-en-v1.5":   0.25,
    "BAAI/bge-base-en-v1.5":    0.30,
    "text-embedding-3-small":   0.35,
    "text-embedding-ada-002":   0.75,
    "nomic-embed-text":         0.35,
}


# Public read-only view. Callers that want to display the shipped
# defaults (e.g. the health endpoint or a CLI ``--show-floors`` flag)
# import this rather than the underscored original.
DEFAULT_FLOORS: dict[str, float] = dict(_DEFAULT_FLOORS)


# --------------------------------------------------------------------------- #
# Public lookup                                                               #
# --------------------------------------------------------------------------- #


def similarity_floor_for(
    model_id: str,
    config: dict[str, float] | None = None,
) -> float:
    """Return the similarity floor for ``model_id`` (Req 16.24, design §3.3).

    Resolution order:

    1. ``config[model_id]`` — operator override from
       ``research.retrieval.similarity_floor.<model_id>``; wins if set.
    2. :data:`_DEFAULT_FLOORS` — shipped defaults covering the models
       listed in design §3.3 and the Decision Log.
    3. :class:`KeyError` — raised with a message listing every known
       model id so the operator's typo (e.g. ``bge-small`` vs the full
       ``BAAI/bge-small-en-v1.5``) is self-diagnosing.

    ``config`` is intentionally a flat ``{model_id: float}`` mapping
    rather than the full settings block so callers can pass either a
    raw ``research.retrieval.similarity_floor`` sub-dict straight out
    of YAML or a hand-built test fixture. A missing sub-dict is treated
    as "no override", not an error.
    """
    if config is not None and model_id in config:
        return float(config[model_id])

    if model_id in _DEFAULT_FLOORS:
        return _DEFAULT_FLOORS[model_id]

    known = sorted(set(_DEFAULT_FLOORS) | set(config or {}))
    raise KeyError(
        f"No similarity floor configured for embedding model {model_id!r}. "
        f"Known models: {known}. "
        "Either add it to research.retrieval.similarity_floor.<model_id> in "
        "config/settings.yaml or extend DEFAULT_FLOORS in "
        "src/research/index/similarity_floor.py.",
    )
