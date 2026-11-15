"""Source: job-alert emails (LinkedIn, Xing, StepStone, Indeed, Glassdoor…).

The boards do the searching; we only read the alerts they email you.
Setup: Gmail filter puts alert emails under the label "Jobs" (any name — see
EMAIL_LABEL), and the bot reads that label over IMAP with a Gmail app password.

Parsing is deliberately generic: every link whose text looks like a design job
title is a job. That survives most redesigns of the alert emails.
"""
from __future__ import annotations

import email
import imaplib
import os
import re
from datetime import datetime, timedelta
from email.header import decode_header, make_header

from bs4 import BeautifulSoup

from .common import Job, make_id


class NotConfigured(Exception):
    pass


SENDERS = {
    "linkedin": "LinkedIn",
    "xing": "Xing",
    "stepstone": "StepStone",
    "indeed": "Indeed",
    "glassdoor": "Glassdoor",
    "jobs.ch": "jobs.ch",
    "wellfound": "Wellfound",
}

_CANON = [
    (re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(\d+)"), "https://www.linkedin.com/jobs/view/{}"),
    (re.compile(r"xing\.com/jobs/([\w-]+-\d+)"), "https://www.xing.com/jobs/{}"),
]


def _canonical(url: str) -> str:
    for rx, tpl in _CANON:
        m = rx.search(url)
        if m:
            return tpl.format(m.group(1))
    return url


def _source_name(sender: str) -> str:
    s = sender.lower()
    for key, name in SENDERS.items():
        if key in s:
            return name
    return "Email alert"


def parse_alert_html(html_body: str, sender: str, title_patterns: list[re.Pattern]) -> list[Job]:
    soup = BeautifulSoup(html_body, "html.parser")
    source = _source_name(sender)
    found: dict[str, Job] = {}
    for a in soup.find_all("a", href=True):
        title = " ".join(a.get_text(" ").split())
        if not (4 <= len(title) <= 140) or not any(p.search(title) for p in title_patterns):
            continue
        url = _canonical(a["href"])
        # Context = the nearest block around the link (title, company, location usually live there)
        block, ctx_lines = a, []
        for _ in range(5):
            block = block.parent
            if block is None:
                break
            lines = [l.strip() for l in block.get_text("\n").split("\n") if l.strip()]
            if len(lines) >= 3:
                ctx_lines = lines
                break
        try:
            i = ctx_lines.index(title)
            after = ctx_lines[i + 1 : i + 4]
        except ValueError:
            after = ctx_lines[:3]
        company = after[0] if after and len(after[0]) < 80 else ""
        location = after[1] if len(after) > 1 and len(after[1]) < 80 else ""
        key = make_id(source, url)
        if key not in found:
            found[key] = Job(
                id=key,
                source=source,
                title=title,
                company=company,
                url=url,
                location=location,
                description=" · ".join(ctx_lines)[:600],
            )
    return list(found.values())


def _body_html(msg) -> str:
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
    return ""


def email_alerts(cfg: dict) -> list[Job]:
    user = os.environ.get("EMAIL_USER")
    pwd = os.environ.get("EMAIL_APP_PASSWORD")
    if not (user and pwd):
        raise NotConfigured("EMAIL_USER / EMAIL_APP_PASSWORD not set")
    label = os.environ.get("EMAIL_LABEL", "Jobs")
    host = os.environ.get("EMAIL_IMAP_HOST", "imap.gmail.com")
    patterns = [re.compile(p, re.I) for p in cfg["search"]["title_must_match"]]

    since = (datetime.now() - timedelta(days=2)).strftime("%d-%b-%Y")
    jobs: list[Job] = []
    with imaplib.IMAP4_SSL(host) as M:
        M.login(user, pwd)
        typ, _ = M.select(f'"{label}"', readonly=True)
        if typ != "OK":
            raise RuntimeError(f'IMAP folder/label "{label}" not found')
        _, data = M.search(None, "SINCE", since)
        for num in data[0].split()[-60:]:
            _, msg_data = M.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            sender = str(make_header(decode_header(msg.get("From", ""))))
            body = _body_html(msg)
            if body:
                jobs += parse_alert_html(body, sender, patterns)
    return jobs
