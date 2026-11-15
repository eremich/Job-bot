"""Tiny JSON store committed back to the repo by GitHub Actions."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .common import JOBS_FILE, Job, dump_json, norm_key


class Store:
    def __init__(self, keep_days: int = 21):
        self.keep_days = keep_days
        self.jobs: dict[str, Job] = {}
        if JOBS_FILE.exists():
            for d in json.loads(JOBS_FILE.read_text(encoding="utf-8")):
                j = Job.from_dict(d)
                self.jobs[j.id] = j
        self._keys = {norm_key(j.title, j.company) for j in self.jobs.values()}

    def is_new(self, job: Job) -> bool:
        return job.id not in self.jobs and norm_key(job.title, job.company) not in self._keys

    def add(self, job: Job) -> None:
        self.jobs[job.id] = job
        self._keys.add(norm_key(job.title, job.company))

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def save(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.keep_days)
        kept = [
            j for j in self.jobs.values()
            if datetime.fromisoformat(j.found_at) >= cutoff
        ]
        kept.sort(key=lambda j: j.found_at, reverse=True)
        dump_json(JOBS_FILE, [j.to_dict() for j in kept])
