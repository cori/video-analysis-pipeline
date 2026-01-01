#!/usr/bin/env python3
"""Test script to verify Ollama connectivity and model availability."""

import asyncio
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.config import settings
from src.analysis.vision import OllamaVisionClient


async def main():
    """Test Ollama connection."""
    print(f"Testing Ollama connection to: {settings.ollama_host}")
    print(f"Expected model: {settings.ollama_model}")
    print()

    client = OllamaVisionClient()

    # Health check
    print("1. Testing connectivity...")
    is_healthy = await client.health_check()

    if not is_healthy:
        print("❌ Ollama is not accessible!")
        print(f"   Make sure Ollama is running at {settings.ollama_host}")
        await client.close()
        sys.exit(1)

    print("✅ Ollama is accessible")
    print()

    # Get available models
    print("2. Fetching available models...")
    models = await client.get_available_models()

    if not models:
        print("⚠️  No models found!")
        print("   Pull a vision model with: ollama pull llava:13b")
        await client.close()
        sys.exit(1)

    print(f"✅ Found {len(models)} model(s):")
    for model in models:
        marker = "👉" if model == settings.ollama_model else "  "
        print(f"   {marker} {model}")
    print()

    # Check if required model is available
    if settings.ollama_model not in models:
        print(f"⚠️  Required model '{settings.ollama_model}' not found!")
        print(f"   Pull it with: ollama pull {settings.ollama_model}")
        await client.close()
        sys.exit(1)

    print(f"✅ Required model '{settings.ollama_model}' is available")
    print()

    print("All checks passed! ✨")
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
