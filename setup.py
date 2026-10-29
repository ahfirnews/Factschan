#!/usr/bin/env python3
"""Safely copy local environment values into GitHub Actions secrets."""

import os
import shutil
import subprocess


SECRET_NAMES = (
    "YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN",
    "PEXELS_API_KEY", "PIXABAY_API_KEY", "FREESOUND_API_KEY", "JAMENDO_CLIENT_ID",
    "DEEPGRAM_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY",
    "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "CEREBRAS_API_KEY", "MISTRAL_API_KEY",
    "NVIDIA_API_KEY", "HF_TOKEN", "SAMBANOVA_API_KEY", "COHERE_API_KEY",
    "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_AI_GATEWAY_ID",
)


def main() -> None:
    if not shutil.which("gh"):
        raise SystemExit("Install GitHub CLI and authenticate with `gh auth login` first.")
    configured = 0
    for name in SECRET_NAMES:
        value = os.getenv(name, "").strip()
        if not value:
            continue
        subprocess.run(["gh", "secret", "set", name], input=value, text=True, check=True)
        print(f"Configured {name}")
        configured += 1
    print(f"Configured {configured} repository secrets. No secret values were written to disk.")


if __name__ == "__main__":
    main()
