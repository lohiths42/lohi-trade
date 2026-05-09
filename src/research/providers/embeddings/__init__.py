"""Built-in Embeddings_Provider adapters (design §3.1).

Each module implements the `EmbeddingsProvider` protocol for a concrete
backend (local `sentence-transformers` with BAAI/bge-small-en-v1.5 as the
default, NVIDIA NIM embeddings, OpenAI embeddings, Ollama embeddings).
"""
