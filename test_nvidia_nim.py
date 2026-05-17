#!/usr/bin/env python3
"""Secure NVIDIA NIM API test script — OpenAI-compatible endpoint.

Docs: https://docs.api.nvidia.com/nim/reference/

Usage:
    1. Rotate your exposed key at https://build.nvidia.com
    2. Add your NEW API key to .env.research:
       NVIDIA_NIM_API_KEY=nvapi-YOUR_NEW_KEY_HERE

    3. Run this script:
       python test_nvidia_nim.py "What is algorithmic trading?"

    4. Or test with specific model/params:
       python test_nvidia_nim.py --model google/gemma-3n-e4b-it --temp 0.2 "Your question"
"""

import argparse
import os
import sys
from pathlib import Path

import requests

# Load environment variables from .env.research
env_file = Path(__file__).parent / ".env.research"
if env_file.exists():
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file)
    except ImportError:
        pass

# Get API key from environment (NEVER hardcode!)
API_KEY = os.getenv("NVIDIA_NIM_API_KEY")
if not API_KEY:
    print("❌ ERROR: NVIDIA_NIM_API_KEY not found in .env.research")
    print("\nSteps to fix:")
    print("  1. Go to https://build.nvidia.com → API Keys")
    print("  2. Delete the exposed key")
    print("  3. Generate a new key")
    print("  4. Add to .env.research: NVIDIA_NIM_API_KEY=nvapi-YOUR_NEW_KEY_HERE")
    sys.exit(1)

INVOKE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

# Available models (ref: https://docs.api.nvidia.com/nim/reference/)
AVAILABLE_MODELS = {
    "gemma-3": "google/gemma-3n-e4b-it",
    "llama-70b": "meta/llama-3.1-70b-instruct",
    "llama-8b": "meta/llama-3.1-8b-instruct",
    "mistral": "mistralai/mistral-large",
    "nemotron": "nvidia/nemotron-mini",
}


def test_nvidia_nim(
    user_message: str,
    model: str = "google/gemma-3n-e4b-it",
    temperature: float = 0.2,
    max_tokens: int = 512,
    top_p: float = 0.7,
    stream: bool = True,
) -> None:
    """Test NVIDIA NIM API with secure credentials.

    Args:
        user_message: The prompt to send
        model: Model ID from available_models
        temperature: 0.0-2.0, controls randomness
        max_tokens: Maximum tokens in response
        top_p: Nucleus sampling parameter
        stream: Whether to stream response
    """

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "text/event-stream" if stream else "application/json",
    }

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": user_message}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "frequency_penalty": 0.0,
        "presence_penalty": 0.0,
        "stream": stream,
    }

    print(f"\n📤 Model: {model}")
    print(f"🌡️  Temperature: {temperature}")
    print(f"💬 Message: {user_message}")
    print("─" * 70)

    try:
        response = requests.post(
            INVOKE_URL, headers=headers, json=payload, stream=stream, timeout=30
        )
        response.raise_for_status()

        if stream:
            print("📥 Streaming response:")
            for line in response.iter_lines():
                if line:
                    decoded = line.decode("utf-8")
                    print(decoded)
        else:
            print("📥 Response:")
            import json

            print(json.dumps(response.json(), indent=2))

        print("─" * 70)
        print("✅ Success!\n")

    except requests.exceptions.HTTPError:
        if response.status_code == 401:
            print("❌ Authentication failed (401)")
            print("→ Check that NVIDIA_NIM_API_KEY in .env.research is correct")
            print("→ Make sure the key hasn't expired")
        elif response.status_code == 403:
            print("❌ Forbidden (403)")
            print("→ API key may not have access to this model")
        else:
            print(f"❌ HTTP Error {response.status_code}")
            print(f"→ {response.text}")
    except requests.exceptions.Timeout:
        print("❌ Request timed out (30s)")
        print("→ NVIDIA NIM may be slow or unreachable")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Test NVIDIA NIM API",
        epilog=f"Available models: {', '.join(AVAILABLE_MODELS.keys())}",
    )
    parser.add_argument("message", nargs="*", help="Message to send")
    parser.add_argument("--model", default="google/gemma-3n-e4b-it", help="Model ID")
    parser.add_argument("--temp", type=float, default=0.2, help="Temperature (0.0-2.0)")
    parser.add_argument("--tokens", type=int, default=512, help="Max tokens")
    parser.add_argument("--top-p", type=float, default=0.7, help="Top-p sampling")
    parser.add_argument("--no-stream", action="store_true", help="Disable streaming")

    args = parser.parse_args()

    # Resolve model alias
    model = AVAILABLE_MODELS.get(args.model, args.model)

    message = (
        " ".join(args.message)
        if args.message
        else "What is algorithmic trading and how can AI help?"
    )

    test_nvidia_nim(
        message,
        model=model,
        temperature=args.temp,
        max_tokens=args.tokens,
        top_p=args.top_p,
        stream=not args.no_stream,
    )
