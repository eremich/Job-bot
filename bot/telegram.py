"""Minimal Telegram Bot API client (no extra dependencies)."""
from __future__ import annotations

import html
from pathlib import Path

import requests

from .common import Job, env

API = "https://api.telegram.org/bot{token}/{method}"


def _call(method: str, files=None, **data):
    url = API.format(token=env("TELEGRAM_BOT_TOKEN"), method=method)
    if files:
        r = requests.post(url, data=data, files=files, timeout=60)
    else:
        r = requests.post(url, json=data, timeout=30)
    body = r.json()
    if not body.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {body}")
    return body["result"]


_CHAT = None


def chat_id() -> str:
    """TELEGRAM_CHAT_ID if set, otherwise the chat of whoever last wrote to the bot."""
    global _CHAT
    if _CHAT:
        return _CHAT
    _CHAT = env("TELEGRAM_CHAT_ID", required=False)
    if not _CHAT:
        for upd in reversed(_call("getUpdates")):
            msg = upd.get("message") or (upd.get("callback_query") or {}).get("message")
            if msg:
                _CHAT = str(msg["chat"]["id"])
                break
    if not _CHAT:
        raise SystemExit("Напиши боту в Telegram любое сообщение и запусти ещё раз")
    return _CHAT


def send_text(text: str, chat: str | None = None, **extra):
    return _call(
        "sendMessage",
        chat_id=chat or chat_id(),
        text=text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        **extra,
    )


def send_document(path: Path, caption: str = "", chat: str | None = None):
    with open(path, "rb") as fh:
        return _call(
            "sendDocument",
            files={"document": (path.name, fh, "application/pdf")},
            chat_id=chat or chat_id(),
            caption=caption,
            parse_mode="HTML",
        )


def esc(s: str) -> str:
    return html.escape(s or "", quote=False)


def score_badge(score: int | None) -> str:
    if score is None:
        return "⚪"
    return "🟢" if score >= 85 else "🟡" if score >= 70 else "🟠"


def job_card(job: Job) -> str:
    lines = [
        f"{score_badge(job.score)} <b>{esc(job.title)}</b>",
        f"🏢 {esc(job.company) or '—'}",
        f"📍 {esc(job.location) or '—'} · <i>{esc(job.source)}</i>",
    ]
    if job.score is not None:
        lines.append(f"⭐ <b>{job.score}/100</b> — {esc(job.why)}")
    return "\n".join(lines)


def send_job(job: Job, chat: str | None = None):
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "📄 CV + письмо", "callback_data": f"cv:{job.id}"},
                {"text": "🔗 Открыть", "url": job.url},
            ]
        ]
    }
    return send_text(job_card(job), chat=chat, reply_markup=keyboard)
