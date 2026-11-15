"""No-AI fallback: works with llm.provider = none, or when the free AI tier is exhausted.

Scoring is a transparent keyword formula; the CV picks facts by tag overlap;
the letter is a simple template filled ONLY with facts from the bank.
"""
from __future__ import annotations

import re

from .common import Job

PENALTIES = [
    (r"fließend(e|es)? deutsch|deutsch\W+(c1|c2)|muttersprach|verhandlungssicher(e|es)? deutsch"
     r"|fluent german|native german|german \(c1|german c1|german c2", -35, "нужен свободный немецкий"),
    (r"\b(us|usa|u\.s\.) only|united states only|americas only|north america only|must be (based|located) in the us",
     -50, "только США/Америка"),
    (r"\bjunior\b|\bintern\b|werkstudent|praktik", -40, "уровень junior/стажёр"),
]
BONUSES = [
    (r"product design", 12, "роль Product Designer"),
    (r"\bsenior\b", 8, "уровень Senior"),
    (r"berlin", 10, "Берлин"),
    (r"remote.*(europe|eu\b|emea|germany|deutschland|cet)|(europe|eu|emea|germany).*remote", 6, "remote в Европе"),
    (r"design system|designsystem", 6, "дизайн-система"),
    (r"\bai\b|\bki\b|llm|agent", 6, "AI-продукт"),
    (r"saas|b2b", 6, "SaaS/B2B"),
    (r"research|nutzerforschung|interview", 4, "исследования"),
    (r"automation|workflow|automatisierung", 6, "автоматизация/воркфлоу"),
    (r"fintech|banking|payment", 4, "финтех"),
    (r"health|medical|patient|gesundheit", 4, "healthcare"),
    (r"english|englisch", 4, "рабочий язык английский"),
]


def score(job: Job) -> tuple[int, str, str]:
    text = f"{job.title} {job.location} {job.description}".lower()
    s, plus, minus = 50, [], []
    for rx, pts, why in BONUSES:
        if re.search(rx, text):
            s += pts
            plus.append(why)
    for rx, pts, why in PENALTIES:
        if re.search(rx, text):
            s += pts
            minus.append(why)
    s = max(0, min(100, s))
    why = (("+ " + ", ".join(plus[:4])) if plus else "") + (("; − " + ", ".join(minus)) if minus else "")
    de_hits = len(re.findall(r"\b(und|wir|sie|für|mit|die|der|das|ihre)\b", text))
    lang = "de" if de_hits > 8 else "en"
    return s, (why.strip("; ") or "по ключевым словам") + " (без ИИ)", lang


def _words(s: str) -> set[str]:
    return set(re.findall(r"[a-zäöüß]{3,}", s.lower()))


def plan(job: Job, facts: dict) -> dict:
    jt = _words(f"{job.title} {job.description}")

    def rel(tags, text):
        tagw = set()
        for t in tags or []:
            tagw |= _words(t.replace("-", " "))
        return 2 * len(tagw & jt) + len(_words(text) & jt) * 0.2

    exp = {}
    for e in facts.get("experience", []):
        fs = e.get("facts", [])
        ranked = sorted(fs, key=lambda f: -rel(f.get("tags"), f["en"]))
        exp[e["id"]] = [f["id"] for f in ranked[:5]]

    projects = sorted(facts.get("projects", []), key=lambda p: -rel(p.get("tags"), p["en"]))
    best_facts = [
        f for e in facts.get("experience", [])
        for f in sorted(e.get("facts", []), key=lambda f: -rel(f.get("tags"), f["en"]))[:2]
    ][:2]
    first = facts.get("experience", [{}])[0].get("company", "")

    if job.lang == "de":
        greeting = "Sehr geehrte Damen und Herren,"
        paras = [
            f"mit großem Interesse habe ich Ihre Ausschreibung als {job.title} gelesen und bewerbe mich hiermit.",
            f"Bei {first} habe ich unter anderem: " + "; ".join((f.get('de') or f['en']) for f in best_facts) + ".",
            "Gerne zeige ich Ihnen meine Case Studies in einem persönlichen Gespräch.",
        ]
        closing = "Mit freundlichen Grüßen"
    else:
        greeting = f"Dear {job.company or 'hiring'} team,"
        paras = [
            f"I'm applying for the {job.title} role at {job.company}.",
            f"At {first}, my work included: " + "; ".join(f['en'][0].lower() + f['en'][1:] for f in best_facts) + ".",
            "I'd be glad to walk you through these case studies in a call.",
        ]
        closing = "Best regards,"

    return {
        "headline": facts["person"].get("headline"),
        "summary": ". ".join(s.rstrip(".") for s in facts.get("summary_facts", [])) + ".",
        "experience": exp,
        "projects": [p["id"] for p in projects[:3]],
        "skills": [],
        "letter": {"greeting": greeting, "paragraphs": paras, "closing": closing},
        "gaps": [],
    }
