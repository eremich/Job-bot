"""Source: XING job search (no public API).

XING's public search pages (e.g. xing.com/jobs/berlin-product-designer) are
server-rendered with an embedded Apollo cache: entries "VisibleJob:<id>": {...}.
We read those entries — the same data any visitor's browser receives.
A ::notice:: is emitted every run so a format change is visible in GitHub.
"""
from __future__ import annotations

import json
import re

from .common import Job, http, make_id

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)
_KEY = re.compile(r'"VisibleJob:[^"]+":\{')
_DEC = json.JSONDecoder()


def parse_page(html: str) -> list[Job]:
    jobs = {}
    for m in _KEY.finditer(html):
        try:
            obj, _ = _DEC.raw_decode(html, m.end() - 1)
        except ValueError:
            continue
        url, title = obj.get("url") or "", obj.get("title") or ""
        if not url or not title:
            continue
        num = (obj.get("slug") or url).rsplit("-", 1)[-1]
        ci = obj.get("companyInfo") or {}
        company = ci.get("companyNameOverride") or ((ci.get("company") or {}).get("companyName") or "")
        cities = [l.get("city") for l in obj.get("locations") or [] if l and l.get("city")]
        loc = ", ".join(dict.fromkeys(cities)) or ((obj.get("location") or {}).get("city") or "")
        bits = []
        et = (obj.get("employmentType") or {}).get("localizationValue")
        if et:
            bits.append(et)
        sal = obj.get("salary") or {}
        if sal.get("minimum"):
            kind = "estimate" if sal.get("__typename") == "SalaryEstimate" else "range"
            bits.append(f"salary {sal['minimum']}-{sal.get('maximum')} {sal.get('currency', '')} ({kind})")
        resp = (((obj.get("summaryV2") or {}).get("content") or {}).get("keyResponsibilities")) or []
        bits += resp
        jobs[num] = Job(
            id=make_id("xing", num),
            source="XING",
            title=title,
            company=company,
            url=url,
            location=loc,
            description=" · ".join(bits)[:2000],
            posted=obj.get("refreshedAt", ""),
        )
    return list(jobs.values())


def xing(cfg: dict) -> list[Job]:
    s = http()
    s.headers.update({"User-Agent": UA, "Accept": "text/html,*/*;q=0.8", "Accept-Language": "de-DE,de;q=0.9,en;q=0.8"})
    city = cfg["search"]["city"].lower()
    found: dict[str, Job] = {}
    diag = []
    for q in cfg["search"]["queries"]:
        slug = re.sub(r"[^a-z0-9]+", "-", q.lower()).strip("-")
        for path in (f"{city}-{slug}", f"t-{slug}"):  # Berlin + all of Germany (remote/hybrid show up there)
            r = s.get(f"https://www.xing.com/jobs/{path}", timeout=25)
            if not r.ok:
                diag.append(f"{path}:{r.status_code}")
                continue
            got = parse_page(r.content.decode("utf-8", "replace"))
            diag.append(f"{path}:{len(got)}")
            for j in got:
                found[j.id] = j
    print("::notice title=xing::" + " ".join(diag)[:900])
    if not found and diag:
        raise RuntimeError("XING page format changed — no jobs parsed (" + " ".join(diag[:4]) + ")")
    return list(found.values())
