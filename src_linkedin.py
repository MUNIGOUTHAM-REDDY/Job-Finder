"""LinkedIn's logged-out job search. Never touches your LinkedIn account."""
import html
import re
import time
import urllib.error
import urllib.parse

from core import CFG, http_get, location_ok, log, new_job, now, parse_relative, strip_html, title_ok, usd_to_lpa

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{}"
# Country-wide searches (they include remote-in-that-country roles). Worldwide remote on LinkedIn
# is mostly US/EU-only, so remote-anywhere roles come from the remote boards instead.
PLACES = [("India", {"location": "India"}), ("Germany", {"location": "Germany"})]


def _g(pattern, s):
    m = re.search(pattern, s, re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))).strip(" ›") if m else ""


def _applicants(text):
    t = text.lower()
    if "first" in t:  # "Be among the first 25 applicants"
        return 0
    m = re.search(r"(\d[\d,]*)", t)
    return int(m.group(1).replace(",", "")) if m else None


def _search(keyword, params, window_secs):
    """Every result page (10 cards each) within the window. A generator, so cards from
    earlier pages are kept if a later page gets rate limited."""
    for start in range(0, CFG["linkedin_max_results_per_keyword"], 10):
        page = _search_page(keyword, params, window_secs, start)
        yield from page
        if len(page) < 10:
            break
        time.sleep(1.5)


def _search_page(keyword, params, window_secs, start):
    q = {"keywords": keyword, "f_TPR": f"r{window_secs}", "sortBy": "DD", "start": start, **params}
    page = http_get(SEARCH + "?" + urllib.parse.urlencode(q))
    cards = []
    for chunk in page.split("<li")[1:]:
        jid = re.search(r"jobPosting:(\d+)", chunk)
        if not jid:
            continue
        cards.append(dict(
            id=jid.group(1),
            title=_g(r'base-search-card__title">(.*?)</h3>', chunk),
            company=_g(r'base-search-card__subtitle">(.*?)</h4>', chunk),
            location=_g(r'job-search-card__location">(.*?)</span>', chunk),
            posted=_g(r"<time[^>]*>(.*?)</time>", chunk),
        ))
    return cards


def fetch(seen, last_run):
    # Look back to the last successful run (covers Mac sleep), at least 30 min, at most 24 h;
    # the very first run looks back the full 24 h.
    window = 86400 if not last_run else int(min(86400, max(1800, (now() - last_run).total_seconds() + 600)))
    cards, ok = {}, True
    for kw in CFG["search_keywords"]:
        for label, params in PLACES:
            if not ok:
                break
            try:
                for c in _search(kw, params, window):
                    c["place"] = label
                    cards.setdefault(c["id"], c)
            except Exception as e:
                log(f"  linkedin search '{kw}' {label}: {e}")
                # Rate limited: stop searching, keep what we have, retry the same window next run.
                ok = not (isinstance(e, urllib.error.HTTPError) and e.code == 429)
            time.sleep(1.5)

    candidates = []
    for c in cards.values():
        loc = c["location"] + (" (Remote)" if c["place"] == "Remote" else "")
        job = new_job(id=f"li:{c['id']}", source="LinkedIn", title=c["title"], company=c["company"],
                      location=loc, url=f"https://www.linkedin.com/jobs/view/{c['id']}",
                      posted_at=parse_relative(c["posted"]))
        if title_ok(job["title"]) and location_ok(loc) and not seen.has(job):
            candidates.append(job)
    return list(_details(candidates, seen)), ok


def _details(jobs, seen):
    # Newest first get details; any beyond the cap still go out, just without applicant counts.
    jobs = sorted(jobs, key=lambda j: j["posted_at"] or now(), reverse=True)
    cap = CFG["linkedin_max_details_per_run"]
    yield from jobs[cap:]
    for job in jobs[:cap]:
        try:
            d = http_get(DETAIL.format(job["id"].split(":")[1]))
        except Exception as e:
            log(f"  linkedin detail {job['id']}: {e}")
            yield job
            continue
        job["applicants_text"] = _g(r'num-applicants__caption[^>]*>(.*?)<', d) or \
            _g(r'num-applicants__figure[^>]*>(.*?)</', d)
        job["applicants"] = _applicants(job["applicants_text"]) if job["applicants_text"] else None
        posted = _g(r'posted-time-ago__text[^>]*>(.*?)<', d)
        job["posted_at"] = parse_relative(posted) or job["posted_at"]
        job["description"] = strip_html(re.search(r'show-more-less-html__markup[^>]*>(.*?)</div>', d, re.S).group(1)) \
            if "show-more-less-html__markup" in d else ""
        criteria = re.findall(r'description__job-criteria-text[^>]*>(.*?)<', d, re.S)
        level = html.unescape(criteria[0]).strip() if criteria else ""
        if level and level != "Not Applicable":
            job["exp_text"] = level  # replaced by years if the description states them
        if level in ("Director", "Executive"):
            job["exp_min"] = 10
        job["salary_text"] = _g(r'compensation__salary[^>]*>(.*?)<', d)
        m = re.findall(r"₹\s?([\d,.]+)\s*(?:L|LPA|lakh)?", job["salary_text"])
        if m:
            vals = [float(x.replace(",", "")) for x in m]
            vals = [v / 1e5 if v > 1000 else v for v in vals]  # rupees -> lakh
            job["salary_min_lpa"], job["salary_max_lpa"] = min(vals), max(vals)
        eur = [float(x.replace(",", "")) for x in re.findall(r"€\s?([\d,]+(?:\.\d+)?)\s*/yr", job["salary_text"])]
        if eur:
            job["salary_min_lpa"], job["salary_max_lpa"] = usd_to_lpa(min(eur), "EUR"), usd_to_lpa(max(eur), "EUR")
        time.sleep(1)
        yield job
