"""Entry point #2 — runs when you press "📄 CV + письмо" in Telegram.

The model never writes experience bullets. It only:
  • picks which fact ids from profile/facts.yaml to show and in what order
  • writes a short summary and a cover letter
A second, independent check compares the summary and letter with the fact bank
and rejects any claim that is not backed by it (one retry, then a warning).

Usage:
  python -m bot.make_cv JOB_ID [--chat CHAT_ID] [--dry-run] [--plan plan.json]
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import telegram as tg
from .common import ROOT, Job, load_config, load_facts
from . import offline
from .llm import ask_json, provider
from .store import Store

OUT = ROOT / "out"

PLAN_SYSTEM = """You tailor a CV and cover letter for ONE candidate to ONE job.
You get a FACT BANK. It is the only truth about the candidate.

You MUST:
- Choose experience bullets ONLY by their fact id. Never write bullet text yourself.
- Use only skills/tools that literally appear in the fact bank.
- In the summary and the letter, state only things that are supported by the fact bank.
  No new numbers, employers, tools, years, titles, certificates or achievements.
  It is fine to connect real facts to the job's needs ("my work on X is relevant to your Y").
- About the company, use only what is in the job ad. Do not invent company facts.
- If the job asks for something the bank does not have, do NOT claim it. List it in "gaps".
- Letter: 3-4 short paragraphs, concrete, no clichés ("I am writing to apply", "passionate", "dynamic team").
  Tone: confident, warm, direct. Max ~230 words.

Reply with ONLY this JSON:
{
  "headline": "short CV headline, e.g. 'Product Designer — SaaS & AI interfaces'",
  "summary": "2-3 sentences",
  "experience": {"<experience id>": ["<fact id>", "..."]},
  "projects": ["<project id>", "..."],
  "skills": ["..."],
  "letter": {"greeting": "...", "paragraphs": ["...", "..."], "closing": "..."},
  "gaps": ["requirement from the ad that the bank does not cover"]
}"""

CHECK_SYSTEM = """You are a fact-checker. Compare TEXT with the FACT BANK.
List every claim about the candidate in TEXT that is NOT supported by the FACT BANK
(new numbers, tools, employers, years, titles, achievements, languages, degrees).
Statements about the company that come from the JOB AD are fine. Opinions/motivation are fine.
Reply with ONLY JSON: {"unsupported": ["claim", "..."]}"""


def _lang_for(job: Job, cfg: dict) -> str:
    lang = cfg["cv"].get("letter_language", "auto")
    return (job.lang or "en") if lang == "auto" else lang


def build_plan(job: Job, facts: dict, cfg: dict) -> tuple[dict, list[str]]:
    letter_lang = _lang_for(job, cfg)
    bank = yaml.safe_dump(facts, allow_unicode=True, sort_keys=False)
    job_txt = json.dumps(
        {"title": job.title, "company": job.company, "location": job.location, "ad": job.description},
        ensure_ascii=False,
    )
    lang_name = {"de": "German", "en": "English"}.get(letter_lang, "English")
    user = (
        f"FACT BANK:\n{bank}\n\nJOB:\n{job_txt}\n\n"
        f"Write the summary in {'German' if cfg['cv']['cv_language'] == 'de' else 'English'} "
        f"and the letter in {lang_name}. Today is {date.today():%d %B %Y}."
    )
    model = cfg["cv"]["model"]
    feedback = ""
    plan, unsupported = {}, []
    for _attempt in range(2):
        plan = ask_json(model, PLAN_SYSTEM, user + feedback, max_tokens=3000)
        text = plan.get("summary", "") + "\n\n" + "\n\n".join(plan.get("letter", {}).get("paragraphs", []))
        check = ask_json(
            cfg["scoring"]["model"],
            CHECK_SYSTEM,
            f"FACT BANK:\n{bank}\n\nJOB AD:\n{job_txt}\n\nTEXT:\n{text}",
            max_tokens=800,
        )
        unsupported = [c for c in check.get("unsupported", []) if c]
        if not unsupported:
            break
        feedback = "\n\nYour previous draft contained unsupported claims. Remove them:\n- " + "\n- ".join(unsupported)
    return plan, unsupported


def _filled(v) -> bool:
    return bool(v) and not str(v).strip().upper().startswith("TODO")


def assemble(plan: dict, facts: dict, cfg: dict) -> dict:
    """Turn the model's plan into template data. Unknown ids are silently dropped."""
    cv_lang = cfg["cv"]["cv_language"]
    exp_out = []
    chosen = plan.get("experience", {}) or {}
    for e in facts.get("experience", []):
        fact_by_id = {f["id"]: f for f in e.get("facts", [])}
        ids = [i for i in chosen.get(e["id"], []) if i in fact_by_id]
        if not ids:  # model skipped this job — still show it with its strongest facts
            ids = list(fact_by_id)[:3]
        bullets = [fact_by_id[i].get(cv_lang) or fact_by_id[i]["en"] for i in ids]
        dates = " – ".join(x for x in (e.get("start"), e.get("end")) if _filled(x))
        exp_out.append({**e, "bullets": bullets, "dates": dates})

    proj_by_id = {p["id"]: p for p in facts.get("projects", [])}
    projects = [proj_by_id[i] for i in plan.get("projects", []) if i in proj_by_id][:4]

    allowed = {s.lower(): s for s in facts.get("skills", []) + facts.get("tools", [])}
    skills = [allowed[s.lower()] for s in plan.get("skills", []) if s.lower() in allowed]
    for s in allowed.values():  # keep the rest after the tailored ones
        if s not in skills:
            skills.append(s)

    person = facts["person"]
    return {
        "person": {**person, "links": [l for l in person.get("links", []) if _filled(l.get("url"))]},
        "headline": plan.get("headline") or person.get("headline"),
        "summary": plan.get("summary", ""),
        "experience": exp_out,
        "projects": projects,
        "skills": skills,
        "education": [ed for ed in facts.get("education", [])],
        "languages": facts.get("languages", []),
        "letter": plan.get("letter", {}),
        "lang": cv_lang,
    }


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")[:40] or "Company"


def render_pdfs(data: dict, job: Job, letter_lang: str) -> tuple[Path, Path]:
    from weasyprint import HTML  # imported lazily: heavy

    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape())
    OUT.mkdir(exist_ok=True)
    name = _slug(data["person"]["name"])
    comp = _slug(job.company)
    ctx = {**data, "job": job, "today": date.today(), "letter_lang": letter_lang}

    cv_path = OUT / f"{name}_CV_{comp}.pdf"
    letter_path = OUT / f"{name}_{'Anschreiben' if letter_lang == 'de' else 'Cover_Letter'}_{comp}.pdf"
    base = str(ROOT / "templates")
    HTML(string=env.get_template("cv.html").render(**ctx), base_url=base).write_pdf(cv_path)
    HTML(string=env.get_template("letter.html").render(**ctx), base_url=base).write_pdf(letter_path)
    return cv_path, letter_path


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("job_id")
    ap.add_argument("--chat")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--plan", help="use a saved plan JSON instead of calling Claude (testing)")
    args = ap.parse_args(argv)

    cfg, facts = load_config(), load_facts()
    job = Store(cfg["storage"]["keep_days"]).get(args.job_id)
    if not job:
        msg = "Не нашёл эту вакансию — возможно, она старше срока хранения."
        print(msg)
        if not args.dry_run:
            tg.send_text(msg, chat=args.chat)
        return

    offline_note = ""
    if args.plan:
        plan, unsupported = json.load(open(args.plan, encoding="utf-8")), []
    elif provider() == "none":
        plan, unsupported = offline.plan(job, facts), []
        offline_note = "\nℹ️ Собрано без ИИ: письмо — шаблон, его стоит подправить."
    else:
        try:
            plan, unsupported = build_plan(job, facts, cfg)
        except Exception as exc:  # noqa: BLE001 — free AI quota exhausted etc.
            print(f"[make_cv] AI failed, using offline plan: {exc}")
            plan, unsupported = offline.plan(job, facts), []
            offline_note = "\nℹ️ ИИ сейчас недоступен (лимит?) — собрано без ИИ, письмо шаблонное."

    letter_lang = _lang_for(job, cfg)
    data = assemble(plan, facts, cfg)
    cv_path, letter_path = render_pdfs(data, job, letter_lang)
    print(f"Saved: {cv_path}\n       {letter_path}")

    notes = [f"✅ Готово для <b>{tg.esc(job.title)}</b> — {tg.esc(job.company)}"]
    gaps = [g for g in plan.get("gaps", []) if g]
    if gaps:
        notes.append("\n🧩 В вакансии просят, а в банке фактов нет:\n" + "\n".join(f"• {tg.esc(g)}" for g in gaps))
    if unsupported:
        notes.append("\n⚠️ Проверь вручную — проверка не подтвердила:\n" + "\n".join(f"• {tg.esc(u)}" for u in unsupported))
    if offline_note:
        notes.append(offline_note)
    notes.append(f'\n🔗 <a href="{tg.esc(job.url)}">Откликнуться</a>')

    if args.dry_run:
        print("\n".join(notes))
        return
    tg.send_document(cv_path, chat=args.chat)
    tg.send_document(letter_path, chat=args.chat)
    tg.send_text("\n".join(notes), chat=args.chat)


if __name__ == "__main__":
    main()
