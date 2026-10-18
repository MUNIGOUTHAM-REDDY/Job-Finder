"""Company careers pages (Greenhouse, Lever, Ashby, SmartRecruiters, Personio) and remote job boards."""
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import src_boards
from core import CFG, http_get, http_json, location_ok, log, new_job, strip_html, title_ok, usd_to_lpa


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


def smartrecruiters(slug):
    base = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
    out, offset = [], 0
    while True:
        data = http_json(f"{base}?limit=100&offset={offset}")
        for j in data.get("content", []):
            loc = j.get("location") or {}
            country = "India" if loc.get("country") == "in" else (loc.get("country") or "").upper()
            place = ", ".join(x for x in (loc.get("city"), country) if x)
            if loc.get("remote"):
                place += " (Remote)"
            out.append(new_job(id=f"sr:{slug}:{j['id']}", source="company site", title=j["name"],
                               company=(j.get("company") or {}).get("name") or slug.title(),
                               location=place,
                               url=f"https://jobs.smartrecruiters.com/{slug}/{j['id']}",
                               posted_at=_ts(j.get("releasedDate"))))
        offset += 100
        if offset >= data.get("totalFound", 0):
            break
    # The list has no descriptions; fetch them only for titles that could match.
    for job in out:
        if title_ok(job["title"]):
            d = http_json(f"{base}/{job['id'].split(':')[2]}")
            sections = (d.get("jobAd") or {}).get("sections") or {}
            job["description"] = strip_html(" ".join((v or {}).get("text", "") for v in sections.values()))
    return out


def personio(slug):
    """Personio (common with German companies) publishes every open role as one XML feed."""
    root = ET.fromstring(http_get(f"https://{slug}.jobs.personio.de/xml?language=en"))
    out = []
    for p in root.iter("position"):
        t = lambda tag: (p.findtext(tag) or "").strip()
        years = t("yearsOfExperience")  # "lt-1", "1-2", "2-5", "5-7", "7-10", "gt-10"
        lo, _, hi = years.replace("lt-", "0-").replace("gt-", "").partition("-")
        offices = [t("office")] + [(o.text or "").strip() for o in p.iter("location")]
        out.append(new_job(id=f"ps:{slug}:{t('id')}", source="company site", title=t("name"),
                           company=t("subcompany") or slug.title(), location=", ".join(o for o in offices if o),
                           url=f"https://{slug}.jobs.personio.de/job/{t('id')}?language=en",
                           posted_at=_ts(t("createdAt")),
                           exp_min=int(lo) if lo.isdigit() else None, exp_max=int(hi) if hi.isdigit() else None,
                           exp_text=f"{years.replace('lt-1', '0-1')} yrs" if years else "",
                           description=strip_html(" ".join(v.text or "" for v in p.iter("value")))))
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


FETCHERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "smartrecruiters": smartrecruiters,
            "personio": personio}


def fetch():
    tasks = [(FETCHERS[k], s) for k in FETCHERS for s in CFG["companies"].get(k, [])]
    tasks += [(remotive, None), (remoteok, None)] + [(fn, None) for fn in src_boards.FETCHERS]

    def run(t):
        fn, slug = t
        for attempt in (1, 2):  # one retry: with ~130 sources in parallel, a slow reply is common
            try:
                return fn(slug)
            except Exception as e:
                if attempt == 2:
                    log(f"  {fn.__name__}:{slug} failed: {e}")
        return []

    jobs = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        for found in ex.map(run, tasks):
            jobs += [j for j in found if title_ok(j["title"]) and location_ok(j["location"])]
    return jobs
