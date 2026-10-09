"""Indian job boards with open JSON: Hirist, Foundit, Cutshort, Wellfound. Plain HTTP, no browser."""
import json
import re
import urllib.parse
from datetime import datetime, timezone

from core import http_get, http_json, new_job, strip_html

# Each board searches differently, so each gets its own short list of queries.
HIRIST_QUERIES = ["ui ux designer", "product designer", "visual designer", "ux engineer"]
FOUNDIT_QUERIES = ["ui ux designer", "product designer", "visual designer", "ux designer"]
CUTSHORT_SLUGS = ["user-interface-ui-design-jobs", "user-experience-ux-design-jobs", "product-design-jobs"]
WELLFOUND_ROLES = ["ui-ux-designer", "product-designer"]


def _ms(v):
    return datetime.fromtimestamp(v / 1000, timezone.utc) if v else None


def _india(loc):
    return loc if "india" in loc.lower() else (loc + ", India" if loc else "India")


def hirist(_):
    jobs = []
    for q in HIRIST_QUERIES:
        for page in range(3):
            data = http_json("https://gladiator.hirist.tech/job/search?" + urllib.parse.urlencode(
                {"query": q, "page": page, "size": 20, "posting": 7}))
            for j in data.get("data") or []:
                show_sal = not j.get("hideSal") and j.get("maxSal")
                company = (j.get("companyData") or {}).get("companyName", "")
                title = j["title"].removeprefix(f"{company} - ") if company else j["title"]  # "Acme - UI Designer"
                jobs.append(new_job(
                    id=f"hr:{j['id']}", source="Hirist", title=title, company=company,
                    location=_india(", ".join(x.get("name", "") for x in j.get("locations") or [])),
                    url=j.get("jobDetailUrl", ""), posted_at=_ms(j.get("createdTimeMs")),
                    exp_min=j.get("min"), exp_max=j.get("max"),
                    exp_text=f"{j['min']}–{j['max']} yrs" if j.get("max") is not None else "",
                    salary_min_lpa=j["minSal"] if show_sal else None, salary_max_lpa=j["maxSal"] if show_sal else None,
                    applicants=j.get("applyCount"), views=j.get("hits"),
                    applicants_text=f"{j['applyCount']} applicants" if j.get("applyCount") is not None else "",
                    description=" ".join(t.get("name", "") for t in j.get("tags") or [])))
            if not data.get("hasMore"):
                break
    return jobs


def foundit(_):
    jobs = []
    for q in FOUNDIT_QUERIES:
        qs = urllib.parse.quote(q)
        # Foundit rejects "Accept: application/json" and requests without its own search page as referrer.
        raw = http_get(f"https://www.foundit.in/middleware/jobsearch?start=0&limit=50&query={qs}"
                       "&locations=India&sort=1&queryDerived=true",
                       headers={"Accept": "*/*", "Referer": f"https://www.foundit.in/srp/results?query={qs}"})
        for j in json.loads(raw).get("jobSearchResponse", {}).get("data") or []:
            # Most Foundit results are copies of LinkedIn posts, which we already read directly.
            if not j.get("title") or "linkedin.com" in (j.get("redirectUrl") or ""):
                continue
            exp = re.findall(r"\d+", j.get("exp") or "")
            lo = (j.get("minimumSalary") or {}).get("absoluteValue") or 0
            hi = (j.get("maximumSalary") or {}).get("absoluteValue") or 0
            hi = hi if hi >= 50000 else 0  # tiny values are placeholders, not salaries
            jobs.append(new_job(
                id=f"fi:{j['jobId']}", source="Foundit", title=j["title"], company=j.get("companyName", ""),
                location=_india(j.get("locations") or ""), url="https://www.foundit.in" + j.get("seoJdUrl", ""),
                posted_at=_ms(j.get("createdAt")), exp_text=j.get("exp") or "",
                exp_min=int(exp[0]) if exp else None, exp_max=int(exp[1]) if len(exp) > 1 else None,
                salary_min_lpa=lo / 1e5 if hi else None, salary_max_lpa=hi / 1e5 if hi else None,
                applicants=j.get("totalApplicants"),
                applicants_text=f"{j['totalApplicants']} applicants" if j.get("totalApplicants") is not None else "",
                description=strip_html(j.get("description") or "")))
    return jobs


def cutshort(_):
    jobs = []
    for slug in CUTSHORT_SLUGS:
        data = http_json(f"https://cutshort.io/backend-api/webpage/jobs/{slug}")
        for j in (data.get("data") or {}).get("pageData", {}).get("jobs") or []:
            exp, sal = j.get("expRange") or {}, j.get("salaryRange") or {}
            inr = sal.get("currency") == "INR" and sal.get("max")
            loc = j.get("locationsText") or ""
            if j.get("remoteType") and "remote" in str(j["remoteType"]).lower():
                loc = (loc + " (Remote)").strip()
            jobs.append(new_job(
                id=f"cs:{j['_id']}", source="Cutshort", title=j.get("headline", ""),
                company=(j.get("companyDetails") or {}).get("name", ""), location=loc or "India",
                url=j.get("publicUrl", ""),
                posted_at=datetime.fromtimestamp(int(j["_id"][:8], 16), timezone.utc),  # ObjectId holds the creation time
                exp_min=exp.get("min"), exp_max=exp.get("max"),
                exp_text=f"{exp['min']}–{exp['max']} yrs" if exp.get("max") is not None else "",
                salary_min_lpa=sal["min"] / 1e5 if inr else None, salary_max_lpa=sal["max"] / 1e5 if inr else None,
                salary_text=j.get("salaryRangeText") or "",
                description=" ".join(j.get("allSkills") or [])))
    return jobs


def wellfound(_):
    jobs = []
    for role in WELLFOUND_ROLES:
        page = http_get(f"https://wellfound.com/role/l/{role}/india")
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
        if not m:
            raise RuntimeError("no __NEXT_DATA__ (likely a bot check)")
        state = json.loads(m.group(1))["props"]["pageProps"]["apolloState"]["data"]
        for key, startup in state.items():
            if not key.startswith("StartupResult:"):
                continue
            for ref in startup.get("highlightedJobListings") or []:
                j = state.get(ref.get("__ref", ""), {})
                if not j.get("title"):
                    continue
                loc = ", ".join(j.get("locationNames") or []) or "India"
                if j.get("remote"):
                    loc += " (Remote)"
                jobs.append(new_job(
                    id=f"wf:{j['id']}", source="Wellfound", title=j["title"], company=startup.get("name", ""),
                    location=loc, url=f"https://wellfound.com/jobs/{j['id']}-{j.get('slug', '')}",
                    posted_at=datetime.fromtimestamp(j["liveStartAt"], timezone.utc) if j.get("liveStartAt") else None,
                    exp_min=j.get("yearsExperienceMin"), salary_text=j.get("compensation") or ""))
    return jobs


FETCHERS = [hirist, foundit, cutshort, wellfound]
