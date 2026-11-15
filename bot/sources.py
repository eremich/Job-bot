"""Job sources. Each fetcher returns a list[Job] and must never crash the run.

Only public APIs and RSS feeds are used — no scraping behind logins.
If a board changes its format, its fetcher fails, gets reported in Telegram,
and the other sources keep working.
"""
from __future__ import annotations

import json
import urllib.parse

import feedparser

from .common import Job, http, make_id, strip_html
from .email_alerts import NotConfigured, email_alerts

TIMEOUT = 25
DESC_LIMIT = 4000


def _desc(text: str | None) -> str:
    return strip_html(text)[:DESC_LIMIT]


# ── Bundesagentur für Arbeit (official, free) ─────────────────
def arbeitsagentur(cfg: dict) -> list[Job]:
    s = http()
    s.headers["X-API-Key"] = "jobboerse-jobsuche"  # public client id from the official docs
    root = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
    # The agency moves versions from time to time — try the newest first.
    paths = ["/pc/v6/jobs", "/pc/v4/jobs", "/pc/v4/app/jobs"]
    jobs: dict[str, Job] = {}
    last_err = None
    for q in cfg["search"]["queries"]:
        params = {
            "was": q,
            "wo": cfg["search"]["city"],
            "umkreis": cfg["search"]["radius_km"],
            "angebotsart": 1,          # Arbeit (not Ausbildung)
            "veroeffentlichtseit": 3,  # last 3 days
            "size": 50,
            "page": 1,
        }
        data = None
        for path in list(paths):
            r = s.get(root + path, params=params, timeout=TIMEOUT)
            if r.ok:
                data = r.json()
                paths[:] = [path] + [p for p in paths if p != path]  # remember the working one
                break
            last_err = f"{path}: HTTP {r.status_code}"
        if data is None:
            continue
        items = data.get("stellenangebote") or (data.get("_embedded") or {}).get("jobs") or []
        if not items:
            print(f"::notice title=arbeitsagentur-shape::{paths[0]} q={q} keys={list(data)[:12]} "
                  f"max={data.get('maxErgebnisse')} sample={json.dumps(data)[:600]}")
        for it in items:
            ref = it.get("refnr") or it.get("referenznummer")
            if not ref:
                continue
            ort = (it.get("arbeitsort") or {}).get("ort", "")
            jobs[ref] = Job(
                id=make_id("ba", ref),
                source="Arbeitsagentur",
                title=it.get("titel") or it.get("beruf", ""),
                company=it.get("arbeitgeber", ""),
                url=f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}",
                location=ort,
                description=it.get("beruf", ""),
                posted=it.get("aktuelleVeroeffentlichungsdatum", ""),
            )
    if not jobs and last_err:
        raise RuntimeError(f"all endpoints failed, last {last_err}")
    return list(jobs.values())


# ── Arbeitnow (Germany-focused board, free API) ───────────────
def arbeitnow(cfg: dict) -> list[Job]:
    out = []
    s = http()
    for page in (1, 2, 3):
        r = s.get("https://www.arbeitnow.com/api/job-board-api", params={"page": page}, timeout=TIMEOUT)
        r.raise_for_status()
        for it in r.json().get("data", []):
            loc = it.get("location", "")
            if it.get("remote"):
                loc = f"{loc} (remote)".strip()
            out.append(
                Job(
                    id=make_id("arbeitnow", it["slug"]),
                    source="Arbeitnow",
                    title=it.get("title", ""),
                    company=it.get("company_name", ""),
                    url=it.get("url", ""),
                    location=loc,
                    description=_desc(it.get("description")),
                    posted=str(it.get("created_at", "")),
                )
            )
    return out


# ── Berlin Startup Jobs (RSS, design category) ────────────────
def berlinstartupjobs(cfg: dict) -> list[Job]:
    return _rss(
        "https://berlinstartupjobs.com/design-ux/feed/",
        source="Berlin Startup Jobs",
        default_location="Berlin",
        split_company=" // ",
    )


# ── Remotive (remote, design category) ────────────────────────
def remotive(cfg: dict) -> list[Job]:
    r = http().get("https://remotive.com/api/remote-jobs", params={"category": "design", "limit": 100}, timeout=TIMEOUT)
    r.raise_for_status()
    return [
        Job(
            id=make_id("remotive", str(it["id"])),
            source="Remotive",
            title=it.get("title", ""),
            company=it.get("company_name", ""),
            url=it.get("url", ""),
            location=f"Remote: {it.get('candidate_required_location', '')}",
            description=_desc(it.get("description")),
            posted=it.get("publication_date", ""),
        )
        for it in r.json().get("jobs", [])
    ]


# ── Jobicy (remote, Europe) ───────────────────────────────────
def jobicy(cfg: dict) -> list[Job]:
    out = []
    for tag in ("product designer", "ux designer", "ui designer"):
        r = http().get(
            "https://jobicy.com/api/v2/remote-jobs",
            params={"count": 50, "geo": "europe", "tag": tag},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        for it in r.json().get("jobs", []) or []:
            out.append(
                Job(
                    id=make_id("jobicy", str(it.get("id"))),
                    source="Jobicy",
                    title=it.get("jobTitle", ""),
                    company=it.get("companyName", ""),
                    url=it.get("url", ""),
                    location=f"Remote: {it.get('jobGeo', '')}",
                    description=_desc(it.get("jobDescription") or it.get("jobExcerpt")),
                    posted=it.get("pubDate", ""),
                )
            )
    return out


# ── Himalayas (remote) ────────────────────────────────────────
def himalayas(cfg: dict) -> list[Job]:
    out = []
    for q in ("product designer", "ux designer"):
        r = http().get("https://himalayas.app/jobs/api/search", params={"q": q, "limit": 50}, timeout=TIMEOUT)
        r.raise_for_status()
        for it in r.json().get("jobs", []) or []:
            link = it.get("applicationLink") or it.get("guid") or ""
            locs = it.get("locationRestrictions") or []
            out.append(
                Job(
                    id=make_id("himalayas", link or it.get("title", "")),
                    source="Himalayas",
                    title=it.get("title", ""),
                    company=it.get("companyName", ""),
                    url=link,
                    location="Remote: " + (", ".join(locs) if locs else "anywhere"),
                    description=_desc(it.get("description") or it.get("excerpt")),
                    posted=str(it.get("pubDate", "")),
                )
            )
    return out


# ── RemoteOK ──────────────────────────────────────────────────
def remoteok(cfg: dict) -> list[Job]:
    r = http().get("https://remoteok.com/api", params={"tag": "design"}, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for it in r.json():
        if not isinstance(it, dict) or "id" not in it or "position" not in it:
            continue  # first element is a legal notice
        out.append(
            Job(
                id=make_id("remoteok", str(it["id"])),
                source="RemoteOK",
                title=it.get("position", ""),
                company=it.get("company", ""),
                url=it.get("url", ""),
                location=f"Remote: {it.get('location') or 'anywhere'}",
                description=_desc(it.get("description")),
                posted=it.get("date", ""),
            )
        )
    return out


# ── We Work Remotely (RSS) ────────────────────────────────────
def weworkremotely(cfg: dict) -> list[Job]:
    return _rss(
        "https://weworkremotely.com/categories/remote-design-jobs.rss",
        source="We Work Remotely",
        default_location="Remote",
        split_company=": ",
        company_first=True,
    )


# ── Djinni (RSS) ──────────────────────────────────────────────
def djinni(cfg: dict) -> list[Job]:
    out = []
    for kw in ("Product Designer", "UI/UX Designer"):
        url = "https://djinni.co/jobs/rss/?" + urllib.parse.urlencode({"primary_keyword": kw})
        out += _rss(url, source="Djinni", default_location="")
    return out


# ── RSS helper ────────────────────────────────────────────────
def _rss(url, source, default_location="", split_company=None, company_first=False) -> list[Job]:
    r = http().get(url, timeout=TIMEOUT)
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"Bad feed: {feed.bozo_exception}")
    out = []
    for e in feed.entries:
        title, company = e.get("title", ""), e.get("author", "")
        if split_company and split_company in title:
            a, b = title.split(split_company, 1)
            title, company = (b, a) if company_first else (a, b)
        out.append(
            Job(
                id=make_id(source, e.get("id") or e.get("link", title)),
                source=source,
                title=title.strip(),
                company=company.strip(),
                url=e.get("link", ""),
                location=e.get("region", "") or default_location,
                description=_desc(e.get("summary") or e.get("description")),
                posted=e.get("published", ""),
            )
        )
    return out


ALL = {
    "email_alerts": email_alerts,
    "arbeitsagentur": arbeitsagentur,
    "arbeitnow": arbeitnow,
    "berlinstartupjobs": berlinstartupjobs,
    "remotive": remotive,
    "jobicy": jobicy,
    "himalayas": himalayas,
    "remoteok": remoteok,
    "weworkremotely": weworkremotely,
    "djinni": djinni,
}


def fetch_all(cfg: dict) -> tuple[list[Job], dict[str, str]]:
    """Returns (jobs, status) where status maps source -> 'ok (N)' or error text."""
    jobs, status = [], {}
    for name, fn in ALL.items():
        if not cfg["sources"].get(name, False):
            continue
        try:
            got = fn(cfg)
            jobs += got
            status[name] = f"ok ({len(got)})"
        except NotConfigured:
            continue  # optional source, not set up yet
        except Exception as exc:  # noqa: BLE001 — one broken board must not kill the run
            status[name] = f"error: {type(exc).__name__}: {str(exc)[:120]}"
    return jobs, status
