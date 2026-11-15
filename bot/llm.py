"""LLM wrapper that always returns parsed JSON.

Providers (config.yaml → llm.provider):
  gemini    — Google Gemini API free tier, no card needed (GEMINI_API_KEY)
  anthropic — Claude API, paid (ANTHROPIC_API_KEY)
  none      — no AI at all: rule-based scoring and CV (see bot/offline.py)
"""
from __future__ import annotations

import json
import re
import time

import requests

from .common import env, load_config


class LLMUnavailable(Exception):
    pass


def provider() -> str:
    return (load_config().get("llm", {}) or {}).get("provider", "gemini")


def ask_json(model: str, system: str, user: str, max_tokens: int = 4000):
    p = provider()
    if p == "gemini":
        text = _gemini(model, system, user, max_tokens)
    elif p == "anthropic":
        text = _anthropic(model, system, user, max_tokens)
    else:
        raise LLMUnavailable("llm.provider is 'none'")
    return parse_json(text)


# ── Gemini (free tier) ────────────────────────────────────────
def _gemini(model: str, system: str, user: str, max_tokens: int) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "maxOutputTokens": max_tokens,
            "temperature": 0.4,
        },
    }
    # Free tier has low per-minute limits → back off and retry on 429/503.
    for attempt in range(5):
        r = requests.post(url, params={"key": env("GEMINI_API_KEY")}, json=body, timeout=120)
        if r.status_code in (429, 500, 503):
            time.sleep(15 * (attempt + 1))
            continue
        if r.status_code == 404:
            raise LLMUnavailable(
                f"Gemini model '{model}' not found — check the current free model names in Google AI Studio "
                "and update config.yaml"
            )
        r.raise_for_status()
        cands = r.json().get("candidates") or []
        parts = (cands[0].get("content") or {}).get("parts", []) if cands else []
        text = "".join(p.get("text", "") for p in parts)
        if text:
            return text
        raise LLMUnavailable(f"Gemini returned no text: {r.text[:300]}")
    raise LLMUnavailable("Gemini rate limit — tried 5 times")


# ── Claude API (paid) ─────────────────────────────────────────
def _anthropic(model: str, system: str, user: str, max_tokens: int) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=env("ANTHROPIC_API_KEY"))
    msg = client.messages.create(
        model=model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": user}]
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def parse_json(text: str):
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    return json.loads(text[min(starts) if starts else 0 :])
