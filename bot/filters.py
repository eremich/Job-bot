"""Cheap rule-based prefilter so we only spend tokens on plausible jobs."""
from __future__ import annotations

import re

from .common import Job, norm_key


def prefilter(jobs: list[Job], cfg: dict) -> list[Job]:
    s = cfg["search"]
    must = [re.compile(p, re.I) for p in s["title_must_match"]]
    excl = [re.compile(p, re.I) for p in s["title_exclude"]]
    loc_ok = [w.lower() for w in s["location_ok"]]

    out, seen_keys = [], set()
    for j in jobs:
        if not j.title or not j.url:
            continue
        if not any(p.search(j.title) for p in must):
            continue
        if any(p.search(j.title) for p in excl):
            continue
        loc = j.location.lower()
        if loc and not any(w in loc for w in loc_ok):
            continue
        key = norm_key(j.title, j.company)
        if key in seen_keys:  # same job on two boards in one run
            continue
        seen_keys.add(key)
        out.append(j)
    return out
