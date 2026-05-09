"""Sentence-Transformers embeddings adapter (Req 2.5, design §3.1).

This is the **default local embeddings provider** for Lohi-Research
(design §7.1 — ``research.providers.embeddings.provider:
sentence_transformers`` with ``model: BAAI/bge-small-en-v1.5``). It is
the embeddings backend used by the ``Persona_Self_Hosted`` deployment
profile described in design §1 so no external API call is needed to
build the vector index: the model weights are downloaded once by the
``sentence-transformers`` library and then served entirely in-process
(design §3.1, §17).

This module implements the ``EmbeddingsProvider`` protocol declared in
``src.research.providers.base`` against the local
``sentence-transformers`` runtime and nothing else. It is registered
lazily by ``registry.py`` via the
``"sentence_transformers": "src.research.providers.embeddings.sentence_transformers:build"``
entry, so **importing this file does not pull in
``sentence-transformers`` or ``torch``** — those heavyweight imports
only happen inside ``build()``. That keeps the registry importable on
a bare install (Task 1.6, Req 2.12) and lets every downstream test
file ``from src.research.providers.embeddings import sentence_transformers``
without needing the package installed.

Defaults
--------
* ``model`` — ``BAAI/bge-small-en-v1.5`` (384-dim). Chosen as the
  project default because it is the smallest BGE model that still
  clears the retrieval similarity floor configured at
  ``research.retrieval.similarity_floor."BAAI/bge-small-en-v1.5":
  0.25`` in ``config/settings.yaml`` (design §7.1).
* ``device`` — whatever ``sentence-transformers`` auto-picks when the
  constructor is called with ``device=None`` (usually ``cpu`` on
  laptops, ``cuda`` on servers). Operators can pin this via
  ``cfg["device"]``.
* ``normalize_embeddings`` — ``True``. BGE retrieval quality is
  materially better when vectors are L2-normalised before cosine
  similarity (upstream model card recommendation), and every shipped
  vector-store adapter in this codebase assumes cosine distance. An
  operator who genuinely wants un-normalised outputs can pass
  ``normalize_embeddings: false`` in the config block.

Async behaviour
---------------
``SentenceTransformers.encode`` is **synchronous** and CPU-bound
(GPU-bound on CUDA setups). Calling it directly from an ``async def``
blocks the event loop for the duration of the encode — which for a
batch of 32 chunks on CPU is easily hundreds of milliseconds. We
therefore offload every ``embed`` call to the default executor via
``loop.run_in_executor(None, ...)`` so the orchestrator's other
coroutines (snapshot invalidations, partial emissions on
``research:partials``) stay responsive (design §3.4, §3.11).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from ..base import EmbeddingsProvider

# Type-only import: lets ``mypy`` understand the ``SentenceTransformer``
# annotations without forcing the package to be installed at runtime.
if TYPE_CHECKING:  # pragma: no cover - typing only
    from sentence_transformers import SentenceTransformer

# Project default — see module docstring and design §7.1.
_DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


class SentenceTransformersEmbeddings:
    """Concrete ``EmbeddingsProvider`` wrapping ``sentence-transformers``.

    Instantiated via ``build(cfg)``; operators never construct this
    class directly. The constructor takes an already-loaded
    ``SentenceTransformer`` instance so the heavyweight model-load
    happens exactly once inside ``build()`` and this class stays
    cheap to unit-test with a fake model (see ``FakeEmbeddingsProvider``
    in Task 2.19).
    """

    def __init__(
        self,
        *,
        model: "SentenceTransformer",
        model_id: str,
        normalize_embeddings: bool = True,
    ) -> None:
        # Kept private so callers go through ``embed`` / the property
        # accessors below; the underlying ``SentenceTransformer`` is
        # not part of the ``EmbeddingsProvider`` protocol.
        self._model = model
        self._model_id = model_id
        self._normalize = normalize_embeddings

    # ------------------------------------------------------------------ #
    # EmbeddingsProvider API                                             #
    # ------------------------------------------------------------------ #

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts`` and return one float vector per input.

        ``SentenceTransformer.encode`` is synchronous and CPU-bound, so
        we push it onto the default executor to avoid blocking the
        event loop while the model runs (design §3.4). The numpy
        array returned by ``encode`` is converted to nested Python
        lists via ``.tolist()`` so the result matches the
        ``list[list[float]]`` shape every ``VectorStore`` adapter in
        the codebase expects.
        """
        loop = asyncio.get_event_loop()
        vectors = await loop.run_in_executor(None, self._encode, texts)
        return vectors

    def _encode(self, texts: list[str]) -> list[list[float]]:
        """Synchronous encode helper, run inside the executor.

        Kept as a named method rather than an inline lambda so the
        call stack in tracebacks points at this file. Uses
        ``convert_to_numpy=True`` because the subsequent ``.tolist()``
        is noticeably faster than converting from a Python list of
        tensors.
        """
        array = self._model.encode(
            texts,
            normalize_embeddings=self._normalize,
            convert_to_numpy=True,
        )
        return array.tolist()

    @property
    def model_id(self) -> str:
        """Stable identifier used in cache keys (design §3.11, Req 5.6)."""
        return self._model_id

    @property
    def dim(self) -> int:
        """Embedding dimensionality; wired into ``VECTOR(dim)`` (Req 2.14).

        For the default ``BAAI/bge-small-en-v1.5`` this returns
        ``384``. We delegate to the loaded model so a swap to e.g.
        ``BAAI/bge-base-en-v1.5`` (768-dim) just works without
        touching this file.
        """
        return int(self._model.get_sentence_embedding_dimension())


def build(cfg: dict[str, Any]) -> EmbeddingsProvider:
    """Factory entry point used by ``registry.py`` (Req 2.12).

    ``cfg`` is the block under ``research.providers.embeddings`` in
    ``config/settings.yaml``; it is forwarded verbatim by the
    registry. All keys are optional:

    * ``model``                — defaults to ``BAAI/bge-small-en-v1.5``
                                  (design §7.1).
    * ``device``               — forwarded to ``SentenceTransformer``;
                                  when missing the library auto-picks
                                  (usually ``cpu`` on laptops,
                                  ``cuda`` on GPU boxes).
    * ``normalize_embeddings`` — defaults to ``True``; BGE models are
                                  tuned for normalised cosine.

    The heavyweight imports live inside this function so the module
    can be imported (and registered lazily) on a bare install that
    does not have ``sentence-transformers`` or ``torch`` available
    (Task 1.6, Req 2.12).
    """
    # Local import: keeps the module importable even when
    # ``sentence-transformers`` is not installed. ``build()`` is the
    # only code path that actually needs the package, and the
    # registry only calls ``build()`` once the operator has wired
    # this provider into ``config/settings.yaml``.
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    model_id = cfg.get("model") or _DEFAULT_MODEL
    device = cfg.get("device")  # ``None`` lets the library pick.
    normalize = cfg.get("normalize_embeddings", True)

    model = SentenceTransformer(model_id, device=device)
    return SentenceTransformersEmbeddings(
        model=model,
        model_id=model_id,
        normalize_embeddings=bool(normalize),
    )


__all__ = ["SentenceTransformersEmbeddings", "build"]
