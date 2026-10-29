# Security notice

This repository previously contained credentials in tracked source files. On
October 29, 2026, the reachable Git history was rewritten to remove every
version of `client_secrets.json`, the legacy `auth.py`, and the old `setup.py`.
Only the current credential-free `setup.py` was then reintroduced.

Revoke and replace every previously committed credential before enabling the
workflow: GitHub token, Google OAuth client secret and refresh token, Groq,
Gemini, Anthropic, Pexels, Pixabay, Freesound, Jamendo, ElevenLabs, and Deepgram.
Store replacements only in GitHub **Settings → Secrets and variables → Actions**.

Previously exposed credentials must remain revoked because old clones, forks,
and caches may retain them. Never commit local token files; store active values
only as encrypted GitHub Actions secrets.
