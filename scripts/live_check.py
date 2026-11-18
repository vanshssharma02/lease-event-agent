"""Utility script to verify OpenRouter API connectivity and model accessibility.

Sends a minimal probe request to OpenRouter using the configured API key and model slug.
Reports:
  - Model availability and HTTP latency
  - Response text
  - Token consumption (prompt + completion)
  - Estimated API cost or free-tier usage status
"""

import os
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI
from app.config import settings


def run_live_check():
    print("=" * 78)
    print("  LEASE-EVENT-AGENT: OPENROUTER LIVE MODEL CONNECTIVITY CHECK")
    print("=" * 78)

    api_key = os.getenv("OPENROUTER_API_KEY") or settings.OPENROUTER_API_KEY
    model = os.getenv("LLM_MODEL") or settings.LLM_MODEL

    print(f"\nConfigured Model: {model}")
    print(f"Fallback Model:   {settings.LLM_FALLBACK_MODEL}")

    if not api_key:
        print("\n[WARNING] OPENROUTER_API_KEY is not set in environment or .env file.")
        print("To run live inference with OpenRouter:")
        print("  1. Obtain a free/paid API key from https://openrouter.ai/keys")
        print("  2. In PowerShell:  $env:OPENROUTER_API_KEY=\"your_key_here\"")
        print("  3. In Bash:        export OPENROUTER_API_KEY=\"your_key_here\"")
        print("  4. Set LLM_MODE=live in .env or environment")
        print("\nThe system remains 100% operational offline in LLM_MODE=mock.")
        return False

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    prompt = "Ping test: confirm you are an LLM agent ready to parse commercial lease events. Reply in 10 words or less."

    print(f"\nDispatching test probe to OpenRouter API endpoint...")
    t0 = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=50,
        )
        t1 = time.perf_counter()
        duration_ms = round((t1 - t0) * 1000.0, 2)

        content = response.choices[0].message.content.strip()
        usage = response.usage

        print(f"\n[SUCCESS] Response received in {duration_ms} ms:")
        print(f"  \"{content}\"")
        if usage:
            print(f"\nToken Accounting:")
            print(f"  - Prompt tokens:     {usage.prompt_tokens}")
            print(f"  - Completion tokens: {usage.completion_tokens}")
            print(f"  - Total tokens:      {usage.total_tokens}")

        print("\nModel slug verified and ready for live execution.")
        return True

    except Exception as e:
        print(f"\n[ERROR] Connection or model verification failed: {e}")
        print("Common causes:")
        print("  1. Invalid or expired OPENROUTER_API_KEY")
        print("  2. Model slug no longer available on OpenRouter (check https://openrouter.ai/models)")
        print("  3. Rate limit reached on free-tier model")
        return False


if __name__ == "__main__":
    success = run_live_check()
    sys.exit(0 if success else 1)
