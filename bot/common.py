"""Shared helpers: paths, config, Job model, HTTP session."""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
JOBS_FILE = DATA / "jobs.json"


def load_config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def load_facts() -> dict:
    return yaml.safe_load((ROOT / "profile" / "facts.yaml").read_text(encoding="utf-8"))


def env(name: str, required: bool = True) -> str:
    val = os.environ.get(name, "")
    if required and not val:
        raise SystemExit(f"Missing environment variable: {name}")
    return val


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", text))).strip()


def make_id(source: str, key: str) -> str:
    # Short, stable id — Telegram callback_data is limited to 64 bytes.
    return hashlib.sha1(f"{source}:{key}".encode()).hexdigest()[:12]


def norm_key(title: str, company: str) -> str:
    """Used to catch the same vacancy posted on several boards."""
    t = re.sub(r"\(.*?\)|[^a-z0-9äöüß ]", " ", title.lower())
    t = re.sub(r"\b(m|w|d|f|x|all genders?)\b", " ", t)
    c = re.sub(r"\b(gmbh|ag|se|ltd|inc|llc|ug|co|kg)\b|[^a-z0-9äöüß ]", " ", company.lower())
    return f"{_WS_RE.sub(' ', t).strip()}|{_WS_RE.sub(' ', c).strip()}"


@dataclass
class Job:
    id: str
    source: str
    title: str
    company: str
    url: str
    location: str = ""
    description: str = ""
    posted: str = ""
    # filled later
    score: int | None = None
    why: str = ""
    lang: str = ""
    found_at: str = field(default_factory=now_iso)
    sent: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def http() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (personal job-alert bot; contact via GitHub)",
            "Accept": "application/json, application/rss+xml, text/xml, */*",
        }
    )
    return s


def dump_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
