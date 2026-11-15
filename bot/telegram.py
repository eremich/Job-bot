"""Minimal Telegram Bot API client (no extra dependencies)."""
from __future__ import annotations

import html
from pathlib import Path

import requests

from .common import DATA, Job, env

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
    saved = DATA / "chat_id.txt"
    _CHAT = env("TELEGRAM_CHAT_ID", required=False) or (saved.read_text().strip() if saved.exists() else "")
    if not _CHAT:
        updates = _call("getUpdates", allowed_updates=[])
        for upd in reversed(updates):
            src = (
                upd.get("message")
                or upd.get("edited_message")
                or upd.get("my_chat_member")
                or (upd.get("callback_query") or {}).get("message")
            )
            if src and src.get("chat", {}).get("type") == "private":
                _CHAT = str(src["chat"]["id"])
                break
        if _CHAT:
            saved.parent.mkdir(exist_ok=True)
            saved.write_text(_CHAT)  # committed by the workflow, so it survives Telegram's 24h update window
            print(f"[telegram] chat id detected and saved: {_CHAT}")
    if not _CHAT:
        me = _call("getMe")
        hook = _call("getWebhookInfo")
        kinds = [k for u in updates for k in u if k != "update_id"]
        raise SystemExit(
            f"Bot @{me.get('username')} (id {me.get('id')}) sees no private chat. "
            f"updates={len(updates)} kinds={kinds[:10]} webhook='{hook.get('url', '')}' "
            f"pending={hook.get('pending_update_count')}"
        )
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
