"""Score jobs 0-100 against the candidate profile with a cheap Claude model."""
from __future__ import annotations

import json

import yaml

from .common import Job
from . import offline
from .llm import LLMUnavailable, ask_json, provider

SYSTEM = """You are a strict recruiter screening job ads for ONE specific candidate.
Score each job 0-100 for how good a fit it is for this candidate AND how realistic it is that he gets an interview.

Scoring guide:
90-100 perfect fit: role, seniority, domain, location and language all match
70-89  good fit, minor gaps
50-69  possible but notable gaps (e.g. German C1 preferred, different domain)
0-49   wrong role, wrong level, a deal-breaker, or location he cannot work from

Hard rules:
- Any deal-breaker from the profile => score <= 30.
- "Fluent/native German required" => score <= 40. "German is a plus" is fine.
- Remote roles limited to US/Americas/Asia only => score <= 20.
- Judge only from the text given; do not invent details about the company.

Reply with ONLY a JSON array, one object per job, same order:
[{"id": "...", "score": 0-100, "why": "одно короткое предложение по-русски: почему подходит или нет", "lang": "en|de"}]
"lang" is the language the job ad is written in."""


def _profile_brief(facts: dict) -> str:
    brief = {
        "target": facts.get("target", {}),
        "summary": facts.get("summary_facts", []),
        "experience": [
            {"company": e["company"], "role": e.get("role"), "facts": [f["en"] for f in e.get("facts", [])]}
            for e in facts.get("experience", [])
        ],
        "skills": facts.get("skills", []),
    }
    return yaml.safe_dump(brief, allow_unicode=True, sort_keys=False)


def score_jobs(jobs: list[Job], facts: dict, cfg: dict) -> list[Job]:
    sc = cfg["scoring"]
    profile = _profile_brief(facts)
    use_ai = provider() != "none"
    for i in range(0, len(jobs), sc["batch_size"]):
        batch = jobs[i : i + sc["batch_size"]]
        payload = [
            {
                "id": j.id,
                "title": j.title,
                "company": j.company,
                "location": j.location,
                "description": j.description[:2500],
            }
            for j in batch
        ]
        if not use_ai:
            _offline(batch)
            continue
        user = f"CANDIDATE PROFILE:\n{profile}\n\nJOBS:\n{json.dumps(payload, ensure_ascii=False)}"
        try:
            results = ask_json(sc["model"], SYSTEM, user, max_tokens=200 + 120 * len(batch))
        except Exception as exc:  # noqa: BLE001 — AI down or out of free quota → keyword scoring
            print(f"[scoring] AI failed, using keyword scoring: {exc}")
            if isinstance(exc, LLMUnavailable):
                use_ai = False
            _offline(batch)
            continue
        by_id = {r.get("id"): r for r in results if isinstance(r, dict)}
        for j in batch:
            r = by_id.get(j.id)
            if r:
                j.score = int(r.get("score", 0))
                j.why = str(r.get("why", ""))[:300]
                j.lang = r.get("lang", "en") if r.get("lang") in ("en", "de") else "en"
    return jobs


def _offline(batch: list[Job]) -> None:
    for j in batch:
        j.score, j.why, j.lang = offline.score(j)
