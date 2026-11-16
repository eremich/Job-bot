"""Source: XING job search (no public API — we read what the public site shows).

Strategy 1: public SEO listing pages (server-rendered links + JSON-LD).
Strategy 2: the site's own GraphQL endpoint, as a guest.
Each run emits a short ::notice:: so a format change is visible in GitHub.
"""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from .common import Job, http, make_id, strip_html

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)
JOB_LINK = re.compile(r"/jobs/([a-z0-9-]+-(\d{6,}))(?:[/?#]|$)")


def _session():
    s = http()
    s.headers.update({"User-Agent": UA, "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
                      "Accept-Language": "de-DE,de;q=0.9,en;q=0.8"})
    return s


def _from_html(html: str, city: str) -> list[Job]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: dict[str, Job] = {}
    # JSON-LD JobPosting blocks
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        items = data if isinstance(data, list) else data.get("itemListElement", [data])
        for it in items:
            it = it.get("item", it) if isinstance(it, dict) else {}
            if it.get("@type") != "JobPosting":
                continue
            url = it.get("url", "")
            m = JOB_LINK.search(url)
            if not m:
                continue
            org = it.get("hiringOrganization") or {}
            loc = ((it.get("jobLocation") or [{}])[0] if isinstance(it.get("jobLocation"), list) else it.get("jobLocation") or {})
            addr = (loc.get("address") or {}) if isinstance(loc, dict) else {}
            jobs[m.group(2)] = Job(
                id=make_id("xing", m.group(2)), source="XING", title=it.get("title", ""),
                company=org.get("name", "") if isinstance(org, dict) else "",
                url="https://www.xing.com/jobs/" + m.group(1),
                location=addr.get("addressLocality", "") or city,
                description=strip_html(it.get("description", ""))[:3000],
                posted=it.get("datePosted", ""),
            )
    # Plain links
    for a in soup.find_all("a", href=True):
        m = JOB_LINK.search(a["href"])
        if not m or m.group(2) in jobs:
            continue
        lines = [l.strip() for l in a.get_text("\n").split("\n") if l.strip()]
        if not lines:
            continue
        jobs[m.group(2)] = Job(
            id=make_id("xing", m.group(2)), source="XING", title=lines[0][:140],
            company=lines[1] if len(lines) > 1 else "",
            url="https://www.xing.com/jobs/" + m.group(1),
            location=lines[2] if len(lines) > 2 else city,
            description=" · ".join(lines)[:500],
        )
    return list(jobs.values())


def xing(cfg: dict) -> list[Job]:
    s = _session()
    city = cfg["search"]["city"]
    found: dict[str, Job] = {}
    diag = []
    for q in cfg["search"]["queries"]:
        slug = re.sub(r"[^a-z0-9]+", "-", q.lower()).strip("-")
        for url, params in (
            ("https://www.xing.com/jobs/search", {"keywords": q, "location": city, "sort": "date"}),
            (f"https://www.xing.com/jobs/t-{slug}", {}),
            (f"https://www.xing.com/jobs/{city.lower()}-{slug}", {}),
        ):
            try:
                r = s.get(url, params=params, timeout=25)
            except Exception as exc:  # noqa: BLE001
                diag.append(f"{url}: {type(exc).__name__}")
                continue
            got = _from_html(r.text, city) if r.ok else []
            for j in got:
                found[j.id] = j
            if q == cfg["search"]["queries"][0] and "t-" in url:
                t = r.text
                i = t.find("\\u002Fjobs\\u002F")
                j = t.find('"title"', i)
                k = t.rfind("<script", 0, i)
                print("::notice title=xing-ctx1::" + t[max(0, i - 900): i + 600])
                print("::notice title=xing-ctx2::" + t[max(0, j - 300): j + 900])
                print("::notice title=xing-ctx3::" + t[k: k + 300])
                gql = re.findall(r"[\"'](https?://[^\"']*(?:graphql|xing-one)[^\"']*)[\"']", r.text)[:2]
                diag.append(f"{url.split('xing.com')[1]} {r.status_code} len={len(r.text)} jobs={len(got)} "
                            f"ld={r.text.count('JobPosting')} links={len(JOB_LINK.findall(r.text))} gql={gql}")
    print("::notice title=xing-diag::" + " || ".join(diag)[:1500])
    return list(found.values())
