"""Company careers pages (Greenhouse, Lever, Ashby) and remote job boards."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from core import CFG, http_json, location_ok, log, new_job, strip_html, title_ok, usd_to_lpa


def _ts(v):
    if not v:
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, timezone.utc)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def greenhouse(slug):
    data = http_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    return [new_job(id=f"gh:{slug}:{j['id']}", source="company site", title=j["title"],
                    company=j.get("company_name") or slug.title(),
                    location=(j.get("location") or {}).get("name", ""), url=j["absolute_url"],
                    posted_at=_ts(j.get("first_published") or j.get("updated_at")),
                    description=strip_html(j.get("content", "")))
            for j in data.get("jobs", [])]


def lever(slug):
    data = http_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    return [new_job(id=f"lv:{slug}:{j['id']}", source="company site", title=j["text"], company=slug.title(),
                    location=(j.get("categories") or {}).get("location", "") or "", url=j["hostedUrl"],
                    posted_at=_ts(j.get("createdAt")), description=j.get("descriptionPlain", ""))
            for j in data]


def ashby(slug):
    data = http_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
    out = []
    for j in data.get("jobs", []):
        loc = j.get("location", "") or ""
        if j.get("isRemote") and "remote" not in loc.lower():
            loc += " (Remote)"
        out.append(new_job(id=f"ab:{slug}:{j['id']}", source="company site", title=j["title"],
                           company=slug.title(), location=loc, url=j["jobUrl"],
                           posted_at=_ts(j.get("publishedAt")),
                           salary_text=(j.get("compensation") or {}).get("compensationTierSummary", "") or "",
                           description=j.get("descriptionPlain", "")))
    return out


def remotive(_):
    data = http_json("https://remotive.com/api/remote-jobs?category=design")
    return [new_job(id=f"rm:{j['id']}", source="Remotive", title=j["title"], company=j.get("company_name", ""),
                    location=(j.get("candidate_required_location") or "Remote") + " (Remote)", url=j["url"],
                    posted_at=_ts(j.get("publication_date") + "Z" if j.get("publication_date") else None),
                    salary_text=j.get("salary", ""), description=strip_html(j.get("description", "")))
            for j in data.get("jobs", [])]


def remoteok(_):
    data = http_json("https://remoteok.com/api?tag=design")
    out = []
    for j in data:
        if not isinstance(j, dict) or "position" not in j:
            continue
        lo, hi = j.get("salary_min") or 0, j.get("salary_max") or 0
        out.append(new_job(id=f"rok:{j['id']}", source="RemoteOK", title=j["position"],
                           company=j.get("company", ""), location=(j.get("location") or "Worldwide") + " (Remote)",
                           url=j.get("url", ""), posted_at=_ts(j.get("epoch")),
                           salary_min_lpa=usd_to_lpa(lo) if lo else None,
                           salary_max_lpa=usd_to_lpa(hi) if hi else None,
                           description=strip_html(j.get("description", ""))))
    return out


FETCHERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby}


def fetch():
    tasks = [(FETCHERS[k], s) for k in FETCHERS for s in CFG["companies"].get(k, [])]
    tasks += [(remotive, None), (remoteok, None)]

    def run(t):
        fn, slug = t
        try:
            return fn(slug)
        except Exception as e:
            log(f"  {fn.__name__}:{slug} failed: {e}")
            return []

    jobs = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        for found in ex.map(run, tasks):
            jobs += [j for j in found if title_ok(j["title"]) and location_ok(j["location"])]
    return jobs
