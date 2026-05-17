# NVIDIA NIM Integration Guide

This guide shows how to integrate NVIDIA NIM into the Lohi-Trade research system using the OpenAI-compatible API.

## 🔐 Security Setup (CRITICAL)

Your API keys have been exposed in chat. You **MUST** rotate them:

1. Go to https://build.nvidia.com → API Keys
2. **Delete all existing keys**
3. Generate a **new API key**
4. Add to `.env.research`:
   ```bash
   NVIDIA_NIM_API_KEY=nvapi-YOUR_NEW_KEY_HERE
   LOHI_RESEARCH_OFFLINE=false
   ```

⚠️ **Never commit `.env.research` to git** — it's in `.gitignore` for this reason.

---

## 📦 Installation

### Option 1: Install Research Dependencies
```bash
# Install just research module
pip install -e ".[research]"

# Or install everything including research
pip install -e ".[all]"
```

This includes:
- `openai` — OpenAI-compatible SDK (works with NVIDIA NIM)
- `anthropic` — Anthropic Claude (optional alternate provider)
- `groq` — Groq API (optional alternate provider)
- `sentence-transformers` — Local embeddings
- `chromadb` — Vector database for research

### Option 2: Install Specific Package
```bash
pip install openai anthropic
```

---

## 🧪 Testing

Two test scripts are provided:

### Test 1: OpenAI SDK (Recommended - Simpler)
```bash
python test_nvidia_nim_openai.py "Explain algorithmic trading"

# With custom model
python test_nvidia_nim_openai.py --model gemma-2-2b "Question here"

# With custom temperature
python test_nvidia_nim_openai.py --temp 0.5 --tokens 2048 "Your question"
```

### Test 2: Raw HTTP (For Advanced Users)
```bash
python test_nvidia_nim.py "Your question"
```

---

## 🔧 Configuration

Edit `config/settings.yaml` to customize the research providers:

```yaml
research:
  enabled: true
  offline_mode: false  # Set to true to use Ollama instead
  providers:
    chat:
      provider: nvidia_nim
      model: google/gemma-2-2b-it  # Fast, efficient
      api_key: ${NVIDIA_NIM_API_KEY}
      temperature: 0.2
      max_tokens: 512
      top_p: 0.7
    summarisation:
      provider: nvidia_nim
      model: meta/llama-3.1-8b-instruct  # Better for summarization
      api_key: ${NVIDIA_NIM_API_KEY}
    judge:
      provider: nvidia_nim
      model: meta/llama-3.1-70b-instruct  # Powerful reasoning
      api_key: ${NVIDIA_NIM_API_KEY}
```

---

## 📚 Available Models

| Model ID | Type | Speed | Quality | Use Case |
|----------|------|-------|---------|----------|
| `google/gemma-2-2b-it` | Fast | ⚡⚡⚡ | ⭐⭐⭐ | Quick queries |
| `google/gemma-3n-e4b-it` | Balanced | ⚡⚡ | ⭐⭐⭐⭐ | General purpose |
| `meta/llama-3.1-8b-instruct` | Efficient | ⚡⚡ | ⭐⭐⭐⭐ | Summarization |
| `meta/llama-3.1-70b-instruct` | Powerful | ⚡ | ⭐⭐⭐⭐⭐ | Complex reasoning |
| `mistralai/mistral-large` | Advanced | ⚡ | ⭐⭐⭐⭐⭐ | Trading analysis |

More models at: https://docs.api.nvidia.com/nim/reference/

---

## 💻 Code Examples

### Example 1: Using OpenAI SDK (Recommended)
```python
from openai import OpenAI

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key="your_api_key_here"
)

completion = client.chat.completions.create(
    model="google/gemma-2-2b-it",
    messages=[
        {"role": "user", "content": "Explain algorithmic trading"}
    ],
    temperature=0.2,
    max_tokens=512,
    stream=True
)

for chunk in completion:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

### Example 2: With Environment Variables (Secure)
```python
import os
from openai import OpenAI
from dotenv import load_dotenv

# Load from .env.research
load_dotenv(".env.research")

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.getenv("NVIDIA_NIM_API_KEY")
)

# Use client...
```

### Example 3: Async Streaming
```python
import asyncio
from openai import AsyncOpenAI

async def chat():
    client = AsyncOpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=os.getenv("NVIDIA_NIM_API_KEY")
    )

    stream = await client.chat.completions.create(
        model="google/gemma-2-2b-it",
        messages=[{"role": "user", "content": "Hello"}],
        stream=True
    )

    async for chunk in stream:
        if chunk.choices[0].delta.content:
            print(chunk.choices[0].delta.content, end="")

asyncio.run(chat())
```

---

## 🚀 Integration with Lohi-Research

The research system automatically loads these settings:

1. **At startup**: `src/research/providers/llm/nvidia_nim.py` uses your config
2. **Agents use it**: Budget, Fundamentals, Macro, News Sentiment, Technicals agents all use the configured LLM
3. **No code changes needed**: Just set your API key in `.env.research`

---

## 🆓 Free Tier

NVIDIA NIM offers a free tier. Typical usage:
- Queries: 100s per month free
- No credit card required to get started
- Perfect for testing and development

---

## 🆘 Troubleshooting

### "NVIDIA_NIM_API_KEY not found"
→ Add it to `.env.research`: `NVIDIA_NIM_API_KEY=nvapi-YOUR_KEY`

### "Authentication failed (401)"
→ Check that:
  - Key is correct in `.env.research`
  - Key hasn't been rotated/deleted
  - No extra whitespace around the key

### "Model not found"
→ Check the model name at https://docs.api.nvidia.com/nim/reference/

### "Rate limited"
→ You're on the free tier. Wait a few seconds and retry.

---

## 📖 Documentation

- NVIDIA NIM Docs: https://docs.api.nvidia.com/nim/reference/
- OpenAI SDK: https://github.com/openai/openai-python
- Lohi-Trade Research: See `docs/ARCHITECTURE.md`

---

## ✅ Next Steps

1. **Rotate your API key** at https://build.nvidia.com
2. **Add to `.env.research`**:
   ```
   NVIDIA_NIM_API_KEY=nvapi-YOUR_NEW_KEY_HERE
   LOHI_RESEARCH_OFFLINE=false
   ```
3. **Install dependencies**:
   ```bash
   pip install -e ".[research]"
   ```
4. **Test it**:
   ```bash
   python test_nvidia_nim_openai.py "Test question"
   ```
5. **Start research**:
   ```bash
   ./start-research.sh
   ```
