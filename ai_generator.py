"""Dynamic multi-provider script generation for Fact Voltage.

Every provider with a catalog endpoint is queried at runtime. Retired model IDs
are therefore skipped without a code release. The SQLite reserve remains the
final, deterministic fallback when all configured free tiers are unavailable.
"""

from __future__ import annotations

import json
import os
import random
import re
import secrets
from typing import Callable

import requests


TOPICS = (
    "space objects with impossible scale",
    "animal abilities that outperform technology",
    "human body systems working every second",
    "ancient inventions still used today",
    "ocean discoveries and deep sea survival",
    "engineering records and megastructures",
    "weather extremes measured on Earth",
    "everyday objects with surprising design reasons",
    "computer technology milestones",
    "geography comparisons that change perspective",
    "food science facts hidden in daily life",
    "time and distance comparisons across history",
    "plants and fungi with unusual survival strategies",
    "materials with extreme physical properties",
    "transport machines ranked by speed or scale",
    "scientific discoveries that began by accident",
)

SYSTEM_PROMPT = """You write original 30-second YouTube Shorts for Fact Voltage,
a cinematic countdown and comparison channel.

Return ONLY one JSON object with these fields:
title, script, topic, tags, visual_queries, hook_overlay, hook_accent.

Rules:
- title: 5-10 words, under 70 characters, specific, unique, curiosity-driven.
- script: 70-90 spoken words. Open with the strongest contradiction in the first
  sentence, rank exactly three verified facts from #3 to #1, include a concrete
  number or comparison in every rank, and end with "Subscribe for another fact
  surge." Never invent a statistic or claim an uncertainty is settled.
- topic: a concise, searchable subject.
- tags: exactly 8 useful tags without # symbols.
- visual_queries: exactly 3 literal, filmable searches in order, one for each
  ranked fact. Name the visible subject, action, setting, and framing.
- hook_overlay: 4-7 punchy words; hook_accent: 1-3 words.
- No greeting, filler, recycled generic title, unsupported superlative, medical
  advice, graphic violence, or private-person allegation.
"""


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _parse_json(text: str) -> dict:
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    match = re.search(r"\{.*\}", cleaned, re.S)
    if not match:
        raise ValueError("provider returned no JSON object")
    return json.loads(match.group(0))


def _normalized_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def validate_package(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("script package is not an object")
    title = str(data.get("title", "")).strip()
    script = " ".join(str(data.get("script", "")).split())
    topic = " ".join(str(data.get("topic", "")).split())
    tags = data.get("tags")
    visual_queries = data.get("visual_queries")
    overlay = " ".join(str(data.get("hook_overlay", "")).split())
    accent = " ".join(str(data.get("hook_accent", "")).split())
    if not 5 <= len(title.split()) <= 11 or len(title) >= 80:
        raise ValueError("title packaging is invalid")
    if not 65 <= len(script.split()) <= 100:
        raise ValueError("script length is invalid")
    if not re.search(r"(?:#|number\s*)3", script, re.I):
        raise ValueError("script has no #3 rank")
    if not re.search(r"(?:#|number\s*)1", script, re.I):
        raise ValueError("script has no #1 rank")
    if "subscribe for another fact surge" not in script.casefold():
        script = script.rstrip(" .!") + ". Subscribe for another fact surge."
    if not isinstance(tags, list) or len(tags) < 5:
        raise ValueError("tags are missing")
    if (
        not isinstance(visual_queries, list)
        or len(visual_queries) != 3
        or any(len(str(query).split()) < 4 for query in visual_queries)
    ):
        raise ValueError("three concrete visual queries are required")
    if not 4 <= len(overlay.split()) <= 7 or not 1 <= len(accent.split()) <= 3:
        raise ValueError("hook packaging is invalid")
    return {
        "title": title,
        "normalized_title": _normalized_title(title),
        "script": script,
        "topic": topic or title,
        "tags": [str(tag).strip() for tag in tags if str(tag).strip()][:12],
        "visual_queries": [" ".join(str(query).split()) for query in visual_queries],
        "hook_overlay": overlay,
        "hook_accent": accent,
        "source": str(data.get("source", "ai")),
    }


def _text_models(items: list[dict], preferred: tuple[str, ...] = ()) -> list[str]:
    blocked = ("audio", "embed", "guard", "image", "moderation", "rerank", "speech", "tts", "video", "whisper")
    available = [
        str(item.get("id", "")) for item in items
        if item.get("id")
        and item.get("active", True) is not False
        and not any(term in str(item.get("id", "")).casefold() for term in blocked)
    ]
    ordered = [model for model in preferred if model in available]
    ordered.extend(model for model in available if model not in ordered)
    return ordered[:12]


def _discover_openai_models(name: str, url: str, key: str, preferred: tuple[str, ...]) -> list[str]:
    try:
        response = requests.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=(8, 20))
        response.raise_for_status()
        payload = response.json()
        models = _text_models(payload if isinstance(payload, list) else payload.get("data", []), preferred)
        if models:
            print(f"[AI] {name}: discovered {len(models)} active text models")
            return models
    except Exception as error:
        print(f"[AI] {name} catalog unavailable ({type(error).__name__})")
    return list(preferred)


def _openai_provider(
    name: str,
    chat_url: str,
    model_url: str,
    key_name: str,
    preferred: tuple[str, ...],
    prompt: str,
) -> dict | None:
    key = _env(key_name)
    if not key:
        return None
    models = _discover_openai_models(name, model_url, key, preferred)
    for model in models:
        for json_mode in (True, False):
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.85,
                "max_tokens": 700,
            }
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            try:
                response = requests.post(
                    chat_url,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=body,
                    timeout=(8, 35),
                )
                if response.status_code == 429:
                    return None
                if response.status_code in (400, 404, 422) and json_mode:
                    continue
                response.raise_for_status()
                package = _parse_json(response.json()["choices"][0]["message"]["content"])
                package["source"] = f"{name}:{model}"
                return validate_package(package)
            except Exception:
                continue
    return None


def _openrouter(prompt: str) -> dict | None:
    key = _env("OPENROUTER_API_KEY")
    if not key:
        return None
    return _openai_direct("OpenRouter Free", "https://openrouter.ai/api/v1/chat/completions", key, ["openrouter/free"], prompt)


def _openai_direct(name: str, url: str, key: str, models: list[str], prompt: str) -> dict | None:
    for model in models:
        try:
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
                    "temperature": 0.85,
                    "max_tokens": 700,
                },
                timeout=(8, 35),
            )
            if response.status_code == 429:
                return None
            response.raise_for_status()
            data = _parse_json(response.json()["choices"][0]["message"]["content"])
            data["source"] = f"{name}:{model}"
            return validate_package(data)
        except Exception:
            continue
    return None


def _huggingface(prompt: str) -> dict | None:
    key = _env("HF_TOKEN")
    if not key:
        return None
    models: list[str] = []
    try:
        response = requests.get(
            "https://huggingface.co/api/models",
            headers={"Authorization": f"Bearer {key}"},
            params={"pipeline_tag": "text-generation", "inference": "warm", "sort": "trendingScore", "limit": 12},
            timeout=(8, 20),
        )
        response.raise_for_status()
        models = [f"{item['id']}:fastest" for item in response.json() if item.get("id")][:8]
    except Exception:
        pass
    return _openai_direct(
        "Hugging Face Router",
        "https://router.huggingface.co/v1/chat/completions",
        key,
        models or ["openai/gpt-oss-120b:fastest"],
        prompt,
    )


def _gemini(prompt: str) -> dict | None:
    key = _env("GEMINI_API_KEY")
    if not key:
        return None
    try:
        catalog = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": key, "pageSize": 1000},
            timeout=(8, 20),
        )
        catalog.raise_for_status()
        models = [
            item.get("name", "").removeprefix("models/")
            for item in catalog.json().get("models", [])
            if "generateContent" in item.get("supportedGenerationMethods", [])
            and "flash" in item.get("name", "").casefold()
        ]
        for model in models[:10]:
            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": key},
                json={
                    "contents": [{"parts": [{"text": SYSTEM_PROMPT + "\n\n" + prompt}]}],
                    "generationConfig": {"temperature": 0.85, "maxOutputTokens": 700, "responseMimeType": "application/json"},
                },
                timeout=(8, 35),
            )
            if response.status_code == 429:
                return None
            if response.status_code in (400, 404):
                continue
            response.raise_for_status()
            data = _parse_json(response.json()["candidates"][0]["content"]["parts"][0]["text"])
            data["source"] = f"Gemini:{model}"
            return validate_package(data)
    except Exception:
        return None
    return None


def _claude(prompt: str) -> dict | None:
    key = _env("ANTHROPIC_API_KEY") or _env("CLAUDE_API_KEY")
    if not key:
        return None
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
    try:
        catalog = requests.get("https://api.anthropic.com/v1/models", headers=headers, params={"limit": 1000}, timeout=(8, 20))
        catalog.raise_for_status()
        models = [item.get("id", "") for item in catalog.json().get("data", []) if item.get("id")]
        for model in models[:10]:
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json={"model": model, "max_tokens": 700, "system": SYSTEM_PROMPT, "messages": [{"role": "user", "content": prompt}]},
                timeout=(8, 35),
            )
            if response.status_code == 429:
                return None
            if response.status_code in (400, 404):
                continue
            response.raise_for_status()
            data = _parse_json(response.json()["content"][0]["text"])
            data["source"] = f"Claude:{model}"
            return validate_package(data)
    except Exception:
        return None
    return None


GENERIC_PROVIDERS = (
    ("Groq", "https://api.groq.com/openai/v1/chat/completions", "https://api.groq.com/openai/v1/models", "GROQ_API_KEY", ("openai/gpt-oss-20b",)),
    ("Cerebras", "https://api.cerebras.ai/v1/chat/completions", "https://api.cerebras.ai/v1/models", "CEREBRAS_API_KEY", ("llama3.1-8b",)),
    ("Mistral", "https://api.mistral.ai/v1/chat/completions", "https://api.mistral.ai/v1/models", "MISTRAL_API_KEY", ("mistral-small-latest",)),
    ("NVIDIA NIM", "https://integrate.api.nvidia.com/v1/chat/completions", "https://integrate.api.nvidia.com/v1/models", "NVIDIA_API_KEY", ("meta/llama-3.3-70b-instruct",)),
)


def generate_package(reject_candidate: Callable[[dict], bool] | None = None) -> dict | None:
    topic = random.choice(TOPICS)
    seed = secrets.token_hex(6)
    prompt = (
        f"Create one never-repeated episode about: {topic}.\n"
        f"Uniqueness seed: {seed}. Never print the seed.\n"
        "Choose three distinct, verifiable examples and make every visual query match its spoken rank."
    )
    callers: list[Callable[[str], dict | None]] = [
        lambda value, item=item: _openai_provider(*item, value)
        for item in GENERIC_PROVIDERS
    ]
    callers.extend((_openrouter, _huggingface, _gemini, _claude))
    for caller in callers:
        package = caller(prompt)
        if package is None:
            continue
        if reject_candidate and reject_candidate(package):
            print("[AI] Rejected previously used title/script; trying next provider")
            continue
        print(f"[AI] Accepted unique package via {package['source']}")
        return package
    return None


def configured_provider_count() -> int:
    generic = sum(bool(_env(item[3])) for item in GENERIC_PROVIDERS)
    routed = sum(bool(_env(name)) for name in ("OPENROUTER_API_KEY", "HF_TOKEN", "GEMINI_API_KEY"))
    return generic + routed + bool(_env("ANTHROPIC_API_KEY") or _env("CLAUDE_API_KEY"))


def catalog_health() -> dict[str, str]:
    """Check model catalogs without consuming generation quota."""
    result: dict[str, str] = {}
    for name, _, model_url, key_name, preferred in GENERIC_PROVIDERS:
        key = _env(key_name)
        if not key:
            result[name] = "not configured"
            continue
        try:
            response = requests.get(model_url, headers={"Authorization": f"Bearer {key}"}, timeout=(8, 20))
            response.raise_for_status()
            payload = response.json()
            models = _text_models(payload if isinstance(payload, list) else payload.get("data", []), preferred)
            result[name] = f"ok ({len(models)} candidates)" if models else "catalog empty"
        except Exception as error:
            result[name] = f"error ({type(error).__name__})"
    checks = (
        ("OpenRouter Free", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1/models", "bearer"),
        ("Hugging Face Router", "HF_TOKEN", "https://huggingface.co/api/models?pipeline_tag=text-generation&inference=warm&limit=5", "bearer"),
        ("Gemini", "GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000", "google"),
        ("Claude", "ANTHROPIC_API_KEY", "https://api.anthropic.com/v1/models?limit=1000", "anthropic"),
    )
    for name, key_name, url, auth_type in checks:
        key = _env(key_name)
        if name == "Claude" and not key:
            key = _env("CLAUDE_API_KEY")
        if not key:
            result[name] = "not configured"
            continue
        headers: dict[str, str] = {}
        params: dict[str, str] = {}
        if auth_type == "bearer":
            headers["Authorization"] = f"Bearer {key}"
        elif auth_type == "google":
            params["key"] = key
        else:
            headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
        try:
            response = requests.get(url, headers=headers, params=params, timeout=(8, 20))
            response.raise_for_status()
            payload = response.json()
            if name == "Gemini":
                count = sum(
                    "generateContent" in item.get("supportedGenerationMethods", [])
                    for item in payload.get("models", [])
                )
            elif isinstance(payload, list):
                count = len(payload)
            else:
                count = len(payload.get("data", []))
            result[name] = f"ok ({count} candidates)" if count else "catalog empty"
        except Exception as error:
            result[name] = f"error ({type(error).__name__})"
    return result
