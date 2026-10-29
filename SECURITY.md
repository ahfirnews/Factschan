# Security notice

This repository previously contained credentials in tracked source files. Those
values have been removed from the current tree, but removing a file does not
remove it from Git history.

Revoke and replace every previously committed credential before enabling the
workflow: GitHub token, Google OAuth client secret and refresh token, Groq,
Gemini, Anthropic, Pexels, Pixabay, Freesound, Jamendo, ElevenLabs, and Deepgram.
Store replacements only in GitHub **Settings → Secrets and variables → Actions**.

For a public repository, use GitHub's documented sensitive-data removal process
to rewrite history after rotating credentials. Rotation is required even if
history is later rewritten.
