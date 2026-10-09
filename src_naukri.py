"""Naukri, read through a real (off-screen) Chrome window, since it blocks plain scripts."""
import re
import urllib.parse
from datetime import datetime, timedelta, timezone

from core import CFG, HERE, log, new_job, strip_html, title_ok

IST = timezone(timedelta(hours=5, minutes=30))


def _salary_from_label(label):
    """'4-7 Lacs P.A.' / '10,000/month' / '15,000-25,000/month' -> (min, max) in LPA."""
    t = (label or "").replace(",", "")
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", t)]
    if not nums:
        return None, None
    if re.search(r"lac|lakh", t, re.I):
        return min(nums), max(nums)
    if re.search(r"month", t, re.I):
        return min(nums) * 12 / 1e5, max(nums) * 12 / 1e5
    return None, None


def _from_search(j):
    sal = j.get("salaryDetail") or {}
    lo = hi = None
    if not sal.get("hideSalary") and sal.get("maximumSalary"):
        lo, hi = sal["minimumSalary"] / 1e5, sal["maximumSalary"] / 1e5
    ph = {p.get("type"): p.get("label") for p in j.get("placeholders", [])}
    if hi is None:
        lo, hi = _salary_from_label(ph.get("salary"))
    created = j.get("createdDate")
    return new_job(
        id=f"nk:{j['jobId']}", source="Naukri", title=j.get("title", ""), company=j.get("companyName", ""),
        location=(ph.get("location") or "") + ", India", url="https://www.naukri.com" + j.get("jdURL", ""),
        posted_at=datetime.fromtimestamp(created / 1000, timezone.utc) if created else None,
        exp_min=int(j["minimumExperience"]) if str(j.get("minimumExperience", "")).isdigit() else None,
        exp_max=int(j["maximumExperience"]) if str(j.get("maximumExperience", "")).isdigit() else None,
        exp_text=j.get("experienceText") or ph.get("experience", ""), salary_min_lpa=lo, salary_max_lpa=hi,
        salary_text=ph.get("salary", ""), description=strip_html(j.get("jobDescription", "")),
        rating=(lambda a: f"{a['AggregateRating']} ({a['ReviewsCount']} reviews)" if a and a.get("AggregateRating") else "")
        (j.get("ambitionBoxData")),
    )


def _add_detail(job, d):
    jd = d.get("jobDetails", {})
    job["applicants"] = jd.get("applyCount")
    job["applicants_text"] = f"{job['applicants']} applicants" if job["applicants"] is not None else ""
    job["views"] = jd.get("viewCount")
    try:
        job["posted_at"] = datetime.strptime(jd["createdDate"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
    except (KeyError, TypeError, ValueError):
        pass
    job["openings"] = jd.get("vacancy")
    job["description"] = strip_html(jd.get("description", "")) or job["description"]
    cd = jd.get("companyDetail") or {}
    job["company_about"] = strip_html(cd.get("details", ""))[:300]
    job["company_address"] = cd.get("address", "")
    job["consultant"] = bool(jd.get("consultant"))
    if jd.get("consultant") and cd.get("hiringFor") and cd["hiringFor"] != job["company"]:
        job["company"] += f" (for {cd['hiringFor']})"
    amb = (d.get("ambitionBoxDetails") or {}).get("companyInfo") or {}
    if amb.get("AggregateRating"):
        job["rating"] = f"{amb['AggregateRating']} ({amb.get('ReviewsCount', '?')} reviews)"


def fetch(seen):
    from playwright.sync_api import sync_playwright

    jobs = {}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(HERE / ".chrome-profile"), channel="chrome", headless=False,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled", "--window-position=-2400,0"],
        )
        page = ctx.new_page()
        try:
            pages = [(kw, n) for kw in CFG["search_keywords"] for n in range(1, CFG.get("naukri_pages_per_keyword", 1) + 1)]
            for kw, n in pages:
                slug = re.sub(r"\s+", "-", kw.strip()) + "-jobs" + ("" if n == 1 else f"-{n}")
                url = f"https://www.naukri.com/{slug}?k={urllib.parse.quote(kw)}&sort=f&jobAge=1"
                try:
                    with page.expect_response(lambda r: "jobapi/v3/search" in r.url, timeout=30000) as resp:
                        page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    for j in resp.value.json().get("jobDetails", []):
                        job = _from_search(j)
                        if title_ok(job["title"]) and not seen.has(job):
                            jobs.setdefault(job["id"], job)
                except Exception as e:
                    log(f"  naukri search '{kw}' page {n}: {e}")
                page.wait_for_timeout(1500)

            # Only open detail pages for fresh, plausible matches (they cost ~5 s each).
            ranked = sorted(jobs.values(), key=lambda j: j["posted_at"] or datetime.min.replace(tzinfo=timezone.utc),
                            reverse=True)
            for job in ranked[:CFG["naukri_max_details_per_run"]]:
                try:
                    with page.expect_response(lambda r: "jobapi/v4/job/" in r.url, timeout=30000) as resp:
                        page.goto(job["url"], wait_until="domcontentloaded", timeout=45000)
                    _add_detail(job, resp.value.json())
                except Exception as e:
                    log(f"  naukri detail {job['id']}: {e}")
                page.wait_for_timeout(1000)
        finally:
            ctx.close()
    return list(jobs.values())
