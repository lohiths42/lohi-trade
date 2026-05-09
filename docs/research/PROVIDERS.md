# Lohi-Research Provider Data-Locality Reference

Every LLM, embeddings, and vector-store adapter shipped under
`src/research/providers/` is pluggable through
[`config/settings.yaml`](../../config/settings.yaml). Because each adapter
reaches a different endpoint — some local, some cloud — operators need to
know exactly **what data leaves the host** when a given provider is
selected. This doc satisfies that requirement (Req 9.5, design §14) and is
the canonical place to look when choosing a backend or deciding whether a
deployment is truly offline.

The authoritative list of registered adapters lives in
[`src/research/providers/registry.py`](../../src/research/providers/registry.py).
Offline-mode enforcement is implemented at the registry edge via
`CloudProviderForbiddenError` (design §14): when
`LOHI_RESEARCH_OFFLINE=true`, any attempt to instantiate a cloud LLM or
cloud embeddings adapter fails fast at boot, naming the offending provider
and role. The `_CLOUD_LLM_PROVIDERS` / `_CLOUD_EMBEDDINGS_PROVIDERS`
constants in `registry.py` define the exact refusal set.

---

## Summary

| Provider | Role | Locality | Offline-compatible |
|---|---|---|---|
| `nvidia_nim` | llm | cloud | no |
| `openai` | llm | cloud | no |
| `anthropic` | llm | cloud | no |
| `gemini` | llm | cloud | no |
| `groq` | llm | cloud | no |
| `together` | llm | cloud | no |
| `openrouter` | llm | cloud (router) | no |
| `ollama` | llm | **local** | **yes** |
| `sentence_transformers` | embeddings | **local** | **yes** |
| `nvidia_nim` | embeddings | cloud | no |
| `openai` | embeddings | cloud | no |
| `ollama` | embeddings | **local** | **yes** |
| `chroma` | vector_store | **local** | **yes** |
| `pgvector` | vector_store | **local** (reuses gateway Postgres) | **yes** |
| `qdrant` | vector_store | local OR cloud (operator-chosen URL) | **yes** (local URL only) |
| `lancedb` | vector_store | **local** | **yes** |

> Data-locality note: every row marked "cloud" sends the outgoing prompt
> plus the retrieved context chunks (and, for embeddings, the raw text
> being embedded) to that provider's API. No Research data is sent to any
> endpoint not named here.

---

## LLM providers

All LLM adapters implement the `LLMProvider` protocol defined in
[`src/research/providers/base.py`](../../src/research/providers/base.py)
and return the `Completion` Provider_Contract (Req 2.11). Configuration
lives under `research.providers.{chat,summarisation,judge}.*`.

### `nvidia_nim` — cloud (default)

- **Data that leaves the host:** prompt, system instructions, retrieved
  context chunks, conversation history.
- **Default endpoint:** `https://integrate.api.nvidia.com/v1`.
- **Authentication:** `NVIDIA_NIM_API_KEY` (set in `.env.research`;
  referenced from `settings.yaml` as `${NVIDIA_NIM_API_KEY}`).
- **Installation:** no extra install — ships with the reference
  requirements.
- **Offline behavior:** refused at boot via `CloudProviderForbiddenError`
  when `LOHI_RESEARCH_OFFLINE=true`.

### `openai` — cloud

- **Data that leaves the host:** prompt + context to `api.openai.com`.
- **Default endpoint:** `https://api.openai.com/v1`.
- **Authentication:** `OPENAI_API_KEY`.
- **Installation:** `pip install openai` (already pinned in the research
  requirements).
- **Offline behavior:** refused at boot.

### `anthropic` — cloud

- **Data that leaves the host:** prompt + context to
  `api.anthropic.com`.
- **Default endpoint:** `https://api.anthropic.com/v1`.
- **Authentication:** `ANTHROPIC_API_KEY`.
- **Installation:** `pip install anthropic`.
- **Offline behavior:** refused at boot.

### `gemini` — cloud

- **Data that leaves the host:** prompt + context to Google's Generative
  Language API.
- **Default endpoint:** `https://generativelanguage.googleapis.com/v1`.
- **Authentication:** `GOOGLE_API_KEY`.
- **Installation:** `pip install google-generativeai`.
- **Offline behavior:** refused at boot.

### `groq` — cloud

- **Data that leaves the host:** prompt + context to `api.groq.com`.
- **Default endpoint:** `https://api.groq.com/openai/v1`.
- **Authentication:** `GROQ_API_KEY`.
- **Installation:** `pip install groq`.
- **Offline behavior:** refused at boot.

### `together` — cloud

- **Data that leaves the host:** prompt + context to `api.together.xyz`.
- **Default endpoint:** `https://api.together.xyz/v1`.
- **Authentication:** `TOGETHER_API_KEY`.
- **Installation:** `pip install together`.
- **Offline behavior:** refused at boot.

### `openrouter` — cloud (router)

- **Data that leaves the host:** prompt + context to
  `openrouter.ai`, which then routes the request to the upstream model
  named in `research.providers.<role>.model`. The upstream may be any
  provider OpenRouter supports — operators should treat this as sending
  data to both OpenRouter **and** the upstream provider.
- **Default endpoint:** `https://openrouter.ai/api/v1`.
- **Authentication:** `OPENROUTER_API_KEY`.
- **Installation:** no extra install (OpenAI-compatible over HTTP).
- **Offline behavior:** refused at boot.

### `ollama` — local (offline default)

- **Data that leaves the host:** **none.** Requests go to a locally-run
  Ollama daemon.
- **Default endpoint:** `http://localhost:11434`.
- **Authentication:** none (localhost-only by convention). Override the
  host with `OLLAMA_HOST` / `OLLAMA_BASE_URL` if Ollama runs on a
  different interface.
- **Installation:** install Ollama (`brew install ollama` or
  https://ollama.com), or start the `offline` docker-compose profile:
  `docker compose -f docker-compose.research.yml --profile offline up -d ollama`.
  Pull the configured model once: `ollama pull llama3.1:8b`.
- **Offline behavior:** the canonical offline LLM. The registry allows
  `ollama` regardless of `LOHI_RESEARCH_OFFLINE`.

---

## Embeddings providers

All embeddings adapters implement `EmbeddingsProvider`. Configuration
lives under `research.providers.embeddings.*`.

### `sentence_transformers` — local (default)

- **Data that leaves the host:** **none** after the model weights are
  downloaded. The first call to `embed()` downloads the model from Hugging
  Face (e.g. `BAAI/bge-small-en-v1.5`) and caches it under the user's
  Hugging Face cache directory (`~/.cache/huggingface/`). All subsequent
  embedding computation runs locally on CPU or GPU.
- **Default endpoint:** none (in-process).
- **Authentication:** none. Hugging Face token only required for gated
  models.
- **Installation:** `pip install sentence-transformers`. Model weights
  (~130 MB for `bge-small-en-v1.5`) download on first use.
- **Offline behavior:** the canonical offline embeddings provider —
  allowed regardless of `LOHI_RESEARCH_OFFLINE`. Pre-download weights
  before going offline: `huggingface-cli download BAAI/bge-small-en-v1.5`.

### `nvidia_nim` — cloud

- **Data that leaves the host:** the exact text chunks being embedded
  are sent to NVIDIA's hosted embeddings endpoint.
- **Default endpoint:** `https://integrate.api.nvidia.com/v1`.
- **Authentication:** `NVIDIA_NIM_API_KEY`.
- **Installation:** no extra install.
- **Offline behavior:** refused at boot.

### `openai` — cloud

- **Data that leaves the host:** text chunks sent to
  `api.openai.com/v1/embeddings`.
- **Default endpoint:** `https://api.openai.com/v1`.
- **Authentication:** `OPENAI_API_KEY`.
- **Installation:** `pip install openai`.
- **Offline behavior:** refused at boot.

### `ollama` — local

- **Data that leaves the host:** **none.** Embedding requests hit the
  local Ollama daemon's `/api/embeddings` endpoint.
- **Default endpoint:** `http://localhost:11434`.
- **Authentication:** none.
- **Installation:** same as the Ollama LLM adapter; pull an embeddings
  model (e.g. `ollama pull nomic-embed-text`).
- **Offline behavior:** allowed regardless of `LOHI_RESEARCH_OFFLINE`.

---

## Vector stores

All vector stores implement `VectorStore` and are local-capable by
design (Req 2.6, design §3.1). The
[`research.vector_store.backend`](../CONFIGURATION.md#lohi-research) key
accepts `auto | chroma | pgvector | qdrant | lancedb`; `auto` probes
Postgres for the `vector` extension once at boot and falls back to
Chroma if the probe misses (design §8).

### `chroma` — local (default)

- **Data that leaves the host:** none. Chroma runs embedded in-process.
- **Storage:** file-based persistence under `data/research/chroma/`
  (configurable via `research.vector_store.chroma.path`).
- **Authentication:** none.
- **Installation:** `pip install chromadb`. No container required.
- **Offline behavior:** fully offline — this is the default selection
  when no external Postgres with pgvector is detected.

### `pgvector` — local

- **Data that leaves the host:** none. Reuses the same `DATABASE_URL`
  as the gateway's Postgres (design §14) with the `vector` extension
  enabled.
- **Storage:** the existing LOHI-TRADE Postgres database. Schema
  configured via `research.vector_store.pgvector.schema` (default
  `public`). The Alembic migration conditionally creates the
  `embedding VECTOR(dim)` column on `research_chunks` when this
  backend is active.
- **Authentication:** reuses the gateway's Postgres credentials; no
  separate connection.
- **Installation:** enable the `vector` extension on the target
  Postgres (`CREATE EXTENSION IF NOT EXISTS vector;`) and run the
  research Alembic migrations.
- **Offline behavior:** fully offline — the Postgres instance stays
  local.

### `qdrant` — local or cloud (operator's choice)

- **Local mode:** point `research.vector_store.qdrant.url` at
  `http://localhost:6333` and start the `qdrant` docker-compose
  profile:
  ```bash
  docker compose -f docker-compose.research.yml --profile qdrant up -d qdrant
  ```
  Data persists under `data/research/qdrant/`. **No data leaves the
  host.**
- **Cloud mode:** point `qdrant.url` at a Qdrant Cloud cluster URL
  (e.g. `https://xyz.aws.cloud.qdrant.io:6333`) and set the
  `QDRANT_API_KEY` environment variable. In this configuration
  **embedding vectors, chunk text, and metadata are sent to Qdrant
  Cloud.**
- **Authentication (cloud):** `QDRANT_API_KEY` header.
- **Installation:** `pip install qdrant-client`; Docker only required
  for the local mode.
- **Offline behavior:** allowed by the registry regardless of
  `LOHI_RESEARCH_OFFLINE`. Operators who set `offline_mode: true`
  **should** keep `qdrant.url` pointing at localhost so the deployment
  is genuinely offline — the registry does not (and cannot) inspect
  the URL to enforce this.

### `lancedb` — local

- **Data that leaves the host:** none. LanceDB is file-based.
- **Storage:** `data/research/lance/` (configurable via
  `research.vector_store.lancedb.path`).
- **Authentication:** none.
- **Installation:** `pip install lancedb`.
- **Offline behavior:** fully offline.

---

## Fully-offline deployment

The refusal-at-boot guard only allows one offline-safe combination of
LLM + embeddings:

- **LLM:** `ollama` (local daemon; pull `llama3.1:8b` or equivalent).
- **Embeddings:** `sentence_transformers` *or* `ollama`.
- **Vector store:** any of `chroma`, `pgvector`, `qdrant` (local URL),
  or `lancedb`.

Activation — set `LOHI_RESEARCH_OFFLINE=true` in `.env.research`. The
registry raises `CloudProviderForbiddenError` at boot if any role still
resolves to a cloud adapter, so accidental misconfiguration fails fast
with a structured error naming both the provider and the role.

Example offline block in `config/settings.yaml`:

```yaml
research:
  offline_mode: ${LOHI_RESEARCH_OFFLINE:false}
  providers:
    chat:          { provider: ollama, model: llama3.1:8b }
    summarisation: { provider: ollama, model: llama3.1:8b }
    judge:         { provider: ollama, model: llama3.1:8b }
    embeddings:    { provider: sentence_transformers, model: BAAI/bge-small-en-v1.5 }
    reranker:      { provider: sentence_transformers, model: BAAI/bge-reranker-base, enabled: false }
  vector_store:
    backend: chroma
    chroma: { path: data/research/chroma }
```

See also the offline full-brief latency budget
(`research.latency_budgets.offline_full_brief_ms`, default 60 s, Req 15.5).

---

## Default cloud deployment

This is the reference configuration the launcher boots with out of the
box (design §16):

- **LLM:**
  - chat / judge → `nvidia_nim` `meta/llama-3.1-70b-instruct`
  - summarisation → `nvidia_nim` `meta/llama-3.1-8b-instruct`
- **Embeddings:** `sentence_transformers` `BAAI/bge-small-en-v1.5`
  (**local** — no text is sent to NVIDIA for embeddings by default).
- **Vector store:** `auto` (resolves to `pgvector` if the gateway's
  Postgres has the `vector` extension, else `chroma`).
- **Required env:** `NVIDIA_NIM_API_KEY` in `.env.research` (free tier
  at https://build.nvidia.com).

In this configuration, the only data that leaves the host is the
outgoing prompt + retrieved context sent to NVIDIA NIM for chat,
summarisation, and judging. Embeddings, retrieval, and all document
storage remain on-host.

---

## See also

- [`docs/CONFIGURATION.md`](../CONFIGURATION.md#lohi-research) — the
  full configuration key reference for the `research:` block.
- [`docs/research/REFUSAL_POLICY.md`](REFUSAL_POLICY.md) — what the
  system will and will not do with the data it processes.
- [`src/research/providers/registry.py`](../../src/research/providers/registry.py)
  — canonical list of registered adapters and the offline-mode
  enforcement.
- [`src/research/providers/errors.py`](../../src/research/providers/errors.py)
  — `CloudProviderForbiddenError` and related structured errors.
