"""Entry point #1 — runs twice a day.

fetch all boards -> prefilter -> skip already seen -> score with Claude ->
send the best ones to Telegram -> remember everything in data/jobs.json

Flags:
  --dry-run          print to console instead of sending to Telegram
  --fixture FILE     use jobs from a JSON file instead of the real boards (testing)
  --no-llm           skip Claude scoring (testing)
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from . import telegram as tg
from .common import Job, load_config, load_facts
from .filters import prefilter
from .scoring import score_jobs
from .sources import fetch_all
from .store import Store


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fixture")
    ap.add_argument("--no-llm", action="store_true")
    args = ap.parse_args(argv)

    cfg, facts = load_config(), load_facts()
    store = Store(cfg["storage"]["keep_days"])

    if args.fixture:
        raw = [Job.from_dict(d) for d in json.load(open(args.fixture, encoding="utf-8"))]
        status = {"fixture": f"ok ({len(raw)})"}
    else:
        raw, status = fetch_all(cfg)

    candidates = prefilter(raw, cfg)
    fresh = [j for j in candidates if store.is_new(j)]
    print(f"raw={len(raw)} prefiltered={len(candidates)} new={len(fresh)}")
    for k, v in status.items():
        print(f"  {k}: {v}")

    if fresh and not args.no_llm:
        score_jobs(fresh, facts, cfg)

    sc = cfg["scoring"]
    good = sorted(
        (j for j in fresh if j.score is not None and j.score >= sc["min_score"]),
        key=lambda j: j.score,
        reverse=True,
    )[: sc["max_per_run"]]
    if args.no_llm:
        good = fresh[: sc["max_per_run"]]

    for j in fresh:
        store.add(j)

    # ── Telegram ──
    ok = sum(1 for v in status.values() if v.startswith("ok"))
    when = datetime.now(ZoneInfo("Europe/Berlin")).strftime("%d.%m %H:%M")
    header = (
        f"🔎 <b>Подборка {when}</b>\n"
        f"Новых: {len(fresh)} · подходят: {len(good)} · источники: {ok}/{len(status)}"
    )
    broken = [f"• {k}: {tg.esc(v)}" for k, v in status.items() if not v.startswith("ok")]
    if broken:
        header += "\n\n⚠️ Не ответили:\n" + "\n".join(broken)

    if args.dry_run:
        print("\n" + header + "\n")
        for j in good:
            print(tg.job_card(j), "\n   ", j.url, "\n")
    else:
        if not good:
            header += "\n\nПодходящих новых вакансий нет — проверю в следующий раз."
        tg.send_text(header)  # always report, so silence never means "broken"
        for j in good:
            tg.send_job(j)
            j.sent = True

    store.save()


if __name__ == "__main__":
    main()
