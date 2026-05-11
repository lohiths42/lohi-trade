"""Built-in LLM_Provider adapters (design §3.1).

Each module in this subpackage implements the `LLMProvider` protocol for a
concrete backend (NVIDIA NIM, OpenAI, Anthropic, Gemini, Groq, Together,
OpenRouter, Ollama). NVIDIA NIM is the default cloud provider; Ollama is the
default offline provider.
"""
