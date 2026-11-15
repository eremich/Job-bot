"""Cheap rule-based prefilter so we only spend tokens on plausible jobs."""
from __future__ import annotations

import re

from .common import Job, norm_key

# Remote jobs restricted to these regions are useless from Berlin…
_FAR = re.compile(
    r"united states|\busa?\b|canada|india|south africa|brazil|latin america|latam|apac|asia|australia"
    r"|philippines|mexico|argentina|colombia|nigeria|kenya|pakistan|new zealand|americas",
    re.I,
)
# …unless the same location also allows Germany/Europe.
_NEAR = re.compile(r"germany|deutschland|berlin|europe|\beu\b|emea|cet|anywhere|worldwide|world", re.I)


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
        if _FAR.search(j.location) and not _NEAR.search(j.location):
            continue
        key = norm_key(j.title, j.company)
        if key in seen_keys:  # same job on two boards in one run
            continue
        seen_keys.add(key)
        out.append(j)
    return out
