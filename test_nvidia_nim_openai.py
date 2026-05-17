#!/usr/bin/env python3
"""Secure NVIDIA NIM test using OpenAI-compatible client.

This demonstrates using the standard OpenAI SDK with NVIDIA NIM's
OpenAI-compatible endpoint. Much simpler than raw HTTP requests!

Docs: https://docs.api.nvidia.com/nim/reference/

Usage:
    1. Rotate your exposed key at https://build.nvidia.com
    2. Add to .env.research:
       NVIDIA_NIM_API_KEY=nvapi-YOUR_NEW_KEY_HERE

    3. Run this script:
       python test_nvidia_nim_openai.py "Your question here"

    4. Or test specific model:
       python test_nvidia_nim_openai.py --model gemma-2-2b-it "Question"
"""

import argparse
import os
import sys
from pathlib import Path

# Load environment variables from .env.research
env_file = Path(__file__).parent / ".env.research"
if env_file.exists():
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file)
    except ImportError:
        pass

# Validate API key
API_KEY = os.getenv("NVIDIA_NIM_API_KEY")
if not API_KEY:
    print("❌ ERROR: NVIDIA_NIM_API_KEY not found in .env.research")
    print("\nSteps to fix:")
    print("  1. Go to https://build.nvidia.com → API Keys")
    print("  2. Delete the exposed key")
    print("  3. Generate a new key")
    print("  4. Add to .env.research: NVIDIA_NIM_API_KEY=nvapi-YOUR_NEW_KEY_HERE")
    sys.exit(1)

try:
    from openai import OpenAI
except ImportError:
    print("❌ OpenAI package not installed")
    print("Install it with: pip install openai")
    sys.exit(1)

# NVIDIA NIM OpenAI-compatible endpoint
BASE_URL = "https://integrate.api.nvidia.com/v1"

# Available models (https://docs.api.nvidia.com/nim/reference/)
AVAILABLE_MODELS = {
    "gemma-2-2b": "google/gemma-2-2b-it",
    "gemma-3": "google/gemma-3n-e4b-it",
    "llama-70b": "meta/llama-3.1-70b-instruct",
    "llama-8b": "meta/llama-3.1-8b-instruct",
    "mistral": "mistralai/mistral-large",
    "nemotron": "nvidia/nemotron-mini",
}


def test_nvidia_nim(
    user_message: str,
    model: str = "google/gemma-2-2b-it",
    temperature: float = 0.2,
    max_tokens: int = 1024,
    top_p: float = 0.7,
    stream: bool = True,
) -> None:
    """Test NVIDIA NIM using OpenAI-compatible client.

    Args:
        user_message: The prompt to send
        model: Model ID
        temperature: 0.0-2.0, controls randomness
        max_tokens: Maximum tokens in response
        top_p: Nucleus sampling parameter
        stream: Whether to stream response
    """

    # Initialize OpenAI client pointing to NVIDIA NIM
    client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

    print(f"\n📤 Model: {model}")
    print(f"🌡️  Temperature: {temperature}, Top-P: {top_p}")
    print(f"💬 Message: {user_message}")
    print("─" * 70)

    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": user_message}],
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stream=stream,
        )

        if stream:
            print("📥 Streaming response:")
            for chunk in completion:
                if chunk.choices and chunk.choices[0].delta.content is not None:
                    print(chunk.choices[0].delta.content, end="", flush=True)
            print("\n")
        else:
            print("📥 Response:")
            print(completion.choices[0].message.content)

        print("─" * 70)
        print("✅ Success!\n")

    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "authentication" in error_msg.lower():
            print("❌ Authentication failed (401)")
            print("→ Check that NVIDIA_NIM_API_KEY in .env.research is correct")
        elif "403" in error_msg:
            print("❌ Forbidden (403)")
            print("→ API key may not have access to this model")
        else:
            print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Test NVIDIA NIM using OpenAI client",
        epilog=f"Available models: {', '.join(AVAILABLE_MODELS.keys())}",
    )
    parser.add_argument("message", nargs="*", help="Message to send")
    parser.add_argument("--model", default="google/gemma-2-2b-it", help="Model ID or alias")
    parser.add_argument("--temp", type=float, default=0.2, help="Temperature (0.0-2.0)")
    parser.add_argument("--tokens", type=int, default=1024, help="Max tokens")
    parser.add_argument("--top-p", type=float, default=0.7, help="Top-p sampling")
    parser.add_argument("--no-stream", action="store_true", help="Disable streaming")

    args = parser.parse_args()

    # Resolve model alias
    model = AVAILABLE_MODELS.get(args.model, args.model)

    message = (
        " ".join(args.message)
        if args.message
        else (
            "At NVIDIA's GPU Technology Conference (GTC), what are the latest "
            "developments in AI accelerators?"
        )
    )

    test_nvidia_nim(
        message,
        model=model,
        temperature=args.temp,
        max_tokens=args.tokens,
        top_p=args.top_p,
        stream=not args.no_stream,
    )
