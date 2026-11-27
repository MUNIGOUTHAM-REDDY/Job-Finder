"""Second search: any job that can be started quickly, for income while the design search continues.

Remote, or on-site within ~4-6 km of HSR Layout Sector 7 (matched by locality name). Drops agency
job-drive posts and likely scams. Matches are tracked on the dashboard and sent as an hourly digest.
"""
import html
import re
from datetime import datetime, timedelta, timezone

import scheduler
from core import (CFG, HERE, L, LOC_BLOCKED, LOC_REMOTE, Seen, _inbox_add, _rx, _slim, age_hours, fill_experience,
                  log, norm_key, now, record_found, tg_send)

Q = CFG["quick"]
EXCLUDE, AGENCY_CO = _rx(Q["exclude_titles"]), _rx(Q["agency_company"])
HOME = (Q["home"]["lat"], Q["home"]["lon"])
AREAS = sorted(Q["areas"].items(), key=lambda kv: -len(kv[0]))  # longest names first ("hsr layout" before "hsr")
AREA_RX = [(name, ll, re.compile(rf"(?<![a-z]){re.escape(name)}(?![a-z])", re.I)) for name, ll in AREAS]
INCLUDE = re.compile(Q["include_titles_regex"], re.I)
AGENCY_TXT = re.compile("|".join(Q["agency_text"]), re.I)
SCAM_TXT = re.compile("|".join(Q["scam_text"]), re.I)
NOT_FRESHER = re.compile("|".join(Q["not_fresher_text"]), re.I)
AGENCY_VAGUE = re.compile("|".join(Q["agency_vague_text"]), re.I)
PAY_FIGURE = re.compile(r"(?:₹|rs\.?|inr)\s?\d[\d,]{2,}|\b\d{2}(?:\.\d)?\s?k\b|\b\d{2},\d{3}\b|\d+(?:\.\d+)?\s?(?:lpa|lacs?|lakhs?)\b", re.I)
LOCATION_LINE = re.compile(r"location\s*[:\-]", re.I)
OPENING_DETAIL = re.compile(r"\bprocess\b|\bvoice\b|\bchat\b|non[- ]?voice|\bshifts?\b|\bpackage\b|\bctc\b", re.I)


def agency_worth_it(job):
    """Agency posts are worth keeping when they list concrete openings, not 'jobs for all professionals'."""
    text = job["description"] or ""
    if len(text) < 250:
        return False  # not enough detail to judge
    pay = len(PAY_FIGURE.findall(text))
    places = len(LOCATION_LINE.findall(text)) + sum(1 for _, _, rx in AREA_RX if rx.search(text))
    detail = len(OPENING_DETAIL.findall(text))
    if AGENCY_VAGUE.search(text) and not (pay >= 2 and places >= 2):
        return False
    return pay >= 1 and places >= 1 and detail >= 2


SALES = re.compile(Q["sales_title_regex"], re.I)
OTHER_LANG = rf"(?:{'|'.join(Q['other_languages'])})"
LANG_IN_TITLE = re.compile(rf"(?<![a-z]){OTHER_LANG}(?![a-z])", re.I)
# an other language mentioned close to a requirement word, in either order
LANG_NEEDED = re.compile(rf"(?<![a-z]){OTHER_LANG}(?![a-z])[^.\n]{{0,60}}(?:language|speak|speaking|fluen|proficien|must|required|mandatory|native|communicat|knowledge)"
                         rf"|(?:language|speak|speaking|fluen|proficien|must|required|mandatory|native|communicat|knowledge)[^.\n]{{0,60}}(?<![a-z]){OTHER_LANG}(?![a-z])", re.I)
LI_SENIOR_LEVELS = {"Associate", "Mid-Senior level", "Director", "Executive"}  # LinkedIn's seniority field
BLR = re.compile(r"bengaluru|bangalore", re.I)
PART_TIME = re.compile(r"part[- ]?time|freelanc|hourly|per hour|weekends? only|few hours", re.I)
IST = timezone(timedelta(hours=5, minutes=30))


def title_ok(title):
    """Entry-level roles you could start quickly (support, ops, sales, admin, data, design gigs...)."""
    if scheduler.is_added_role("quick", title, EXCLUDE):
        return True
    return bool(INCLUDE.search(title)) and not EXCLUDE.search(title)


def location_ok(loc):
    """Cheap pass on the search card: remote, Bengaluru, or unknown."""
    return not loc or bool(BLR.search(loc)) or (bool(LOC_REMOTE.search(loc)) and not LOC_BLOCKED.search(loc))


def km(a, b):
    import math
    (la1, lo1), (la2, lo2) = a, b
    p = math.pi / 180
    h = math.sin((la2 - la1) * p / 2) ** 2 + math.cos(la1 * p) * math.cos(la2 * p) * math.sin((lo2 - lo1) * p / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def nearest_area(text):
    """(area, km from home) for the closest known Bengaluru area named in text, or (None, None)."""
    best = (None, None)
    for name, ll, rx in AREA_RX:
        if rx.search(text):
            d = km(HOME, ll)
            if best[1] is None or d < best[1]:
                best = (name, d)
    return best


def where(job):
    """('remote' | 'near' | 'area not stated', None) if acceptable, else (None, reason)."""
    loc, text = job["location"] or "", job["description"] or ""
    says_remote = LOC_REMOTE.search(loc) or re.search(r"work from home|\bwfh\b|fully remote|100% remote|remote (?:role|job|position|work)",
                                                      job["title"] + " " + text[:1500], re.I)
    # A remote-filtered LinkedIn search whose card shows only the country is the remote filter working;
    # a card naming a city is often a promoted on-site job, so it needs proof from the post itself.
    if says_remote or (job.get("from_remote_search") and loc.strip().lower() in ("india", "")):
        if not LOC_BLOCKED.search(loc):
            return "remote", None
    area, d = nearest_area(loc)
    if area is None and loc and not BLR.search(loc):
        return None, "location"
    if area is None:
        area, d = nearest_area(text[:3000])
    if area is not None:
        job["area"], job["distance_km"] = area.title(), round(d, 1)
        return ("near", None) if d <= Q["max_km"] else (None, "farther than 6 km from HSR")
    return "area not stated", None


def monthly(job):
    """Stated top salary per month, in rupees (None if not stated)."""
    return round(job["salary_max_lpa"] * 1e5 / 12) if job["salary_max_lpa"] else None


def reject_reason(job):
    text = f"{job['title']}\n{job['description'] or ''}"
    if not title_ok(job["title"]):
        return "title"
    if job.get("consultant") or AGENCY_CO.search(job["company"] or "") or AGENCY_TXT.search(text[:2500]):
        if not agency_worth_it(job):
            return "agency or job drive"
        job["agency"] = True
    if SCAM_TXT.search(text):
        return "possible scam"
    if SALES.search(job["title"]) and (LANG_IN_TITLE.search(job["title"]) or LANG_NEEDED.search(job["description"] or "")):
        return "needs another language"
    part_time = bool(PART_TIME.search(text))
    job["part_time"] = part_time
    pay = monthly(job)
    if part_time and pay and pay > Q["max_monthly_part_time_believable"]:
        return "possible scam"
    place, why = where(job)
    if why:
        return why
    job["where"] = place
    if job["exp_min"] is not None and job["exp_min"] > Q["max_experience_min_years"]:
        return "not for freshers"
    if job["source"] == "LinkedIn" and (job["exp_text"] or "").strip() in LI_SENIOR_LEVELS:
        return "not for freshers"
    if NOT_FRESHER.search(job["description"] or ""):
        return "not for freshers"
    if not part_time and pay and pay < Q["min_monthly_salary_full_time"]:
        return "salary"
    a = age_hours(job)
    if a is not None and a > Q["max_age_hours"]:
        return "too old"
    return None


def digest_line(job):
    e = html.escape
    pay = monthly(job)
    bits = [("Part-time" if job.get("part_time") else "Full-time"),
            {"remote": "🏠 Remote", "near": "📍 Near HSR", "area not stated": "📍 Bengaluru (area not stated)"}.get(job.get("where"), ""),
            f"₹{pay // 1000}k/mo" if pay else "",
            job["exp_text"] or ""]
    return (f'• <a href="{e(job["url"])}"><b>{e(job["title"][:70])}</b></a> · {e(job["company"][:40])}\n'
            f'   {e("  ·  ".join(b for b in bits if b))}')


def process(jobs, seen, label):
    fresh, reasons, batch, found = [], {}, set(), []
    for job in jobs:
        if seen.has(job) or norm_key(job) in batch:
            continue
        batch.add(norm_key(job))
        r = reject_reason(fill_experience(job))
        if r != "title":
            found.append((job, r or "alerted"))
        if r:
            reasons[r] = reasons.get(r, 0) + 1
            continue
        fresh.append(job)
    for j in fresh:
        seen.add(j)
    record_found(found, track="quick")
    _inbox_add("quick.json", [dict(_slim(j), track="quick", part_time=j.get("part_time"), where=j.get("where"),
                                   area=j.get("area"), distance_km=j.get("distance_km")) for j in fresh])

    # Hourly digest: queue now, send when an hour has passed since the last one.
    if not Q.get("telegram", True):  # turned off by Muni (17 Nov): quick jobs are tracked on the dashboard only
        seen.meta.pop("pending", None)
        log(f"{label}: {len(jobs)} checked, {len(fresh)} matched, skipped {reasons}")
        seen.save()
        return fresh
    rank = {"remote": 0, "near": 1, "area not stated": 2}
    pending = seen.meta.setdefault("pending", [])
    pending += [{"line": digest_line(j), "rank": rank.get(j.get("where"), 3)} for j in fresh]
    last = seen.meta.get("last_digest")
    if pending and (not last or (now() - datetime.fromisoformat(last)).total_seconds() >= 3300):
        pending.sort(key=lambda p: p.get("rank", 3))
        cap = Q.get("digest_max_lines", 15)
        msg = f"💼 <b>Quick jobs</b>  ·  {len(pending)} new  ·  {datetime.now(IST):%I:%M %p}"
        for p in pending[:cap]:
            msg += "\n\n" + p["line"]
        if len(pending) > cap:
            msg += f"\n\n+{len(pending) - cap} more on the dashboard (Quick jobs → Board)"
        if tg_send(msg[:4000]):
            seen.meta["pending"], seen.meta["last_digest"] = [], now().isoformat()
    log(f"{label}: {len(jobs)} checked, {len(fresh)} matched, skipped {reasons}")
    seen.save()
    return fresh


def run():
    import src_linkedin
    import src_naukri
    from datetime import datetime as dt

    seen = Seen(HERE / "state" / "seen-quick.json")
    seen.first_run = False  # no "is live" message or 24 h backfill burst for this search
    places = {"Bengaluru": {"location": "Bengaluru, Karnataka, India"}, "Remote": {"location": "India", "f_WT": "2"}}
    last = seen.meta.get("linkedin_last_run")
    linkedin_queries, naukri_queries = scheduler.quick_queries()
    li, nk = [], []
    if scheduler.enabled("quick", "linkedin"):
        li, ok = src_linkedin.fetch(seen, dt.fromisoformat(last) if last else None,
                                    searches=[(kw, place, places[place]) for kw, place in linkedin_queries],
                                    title_filter=title_ok, loc_filter=location_ok,
                                    max_results=Q["linkedin_max_results"], detail_cap=Q["linkedin_max_details"])
        if ok:
            seen.meta["linkedin_last_run"] = now().isoformat()
    if scheduler.enabled("quick", "naukri"):
        try:
            nk = src_naukri.fetch(seen, queries=[tuple(x) for x in naukri_queries], title_filter=title_ok,
                                  detail_cap=Q["naukri_max_details"], pages_per_query=1, job_age_days=3)
        except Exception as e:
            log("naukri (quick) failed:", e)
    process(li + nk, seen, "Quick jobs")
