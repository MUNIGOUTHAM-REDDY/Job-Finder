"""Second search: any job that can be started quickly, for income while the design search continues.

Remote, or on-site within ~4-6 km of HSR Layout Sector 7 (matched by locality name). Drops agency
job-drive posts and likely scams. Matches are tracked on the dashboard and sent as an hourly digest.
"""
import html
import re
from datetime import datetime, timedelta, timezone

from core import (CFG, HERE, L, LOC_BLOCKED, LOC_REMOTE, Seen, _inbox_add, _rx, _slim, age_hours, fill_experience,
                  log, norm_key, now, record_found, tg_send)

Q = CFG["quick"]
EXCLUDE, NEAR, FAR, AGENCY_CO = _rx(Q["exclude_titles"]), _rx(Q["near_hsr"]), _rx(Q["far_from_hsr"]), _rx(Q["agency_company"])
INCLUDE = re.compile(Q["include_titles_regex"], re.I)
AGENCY_TXT = re.compile("|".join(Q["agency_text"]), re.I)
SCAM_TXT = re.compile("|".join(Q["scam_text"]), re.I)
BLR = re.compile(r"bengaluru|bangalore", re.I)
PART_TIME = re.compile(r"part[- ]?time|freelanc|hourly|per hour|weekends? only|few hours", re.I)
IST = timezone(timedelta(hours=5, minutes=30))


def title_ok(title):
    """Entry-level roles you could start quickly (support, ops, sales, admin, data, design gigs...)."""
    return bool(INCLUDE.search(title)) and not EXCLUDE.search(title)


def location_ok(loc):
    """Cheap pass on the search card: remote, Bengaluru, or unknown."""
    return not loc or bool(BLR.search(loc)) or (bool(LOC_REMOTE.search(loc)) and not LOC_BLOCKED.search(loc))


def where(job):
    """('remote' | 'near' | 'area not stated', None) if acceptable, else (None, reason)."""
    loc, text = job["location"] or "", job["description"] or ""
    if LOC_REMOTE.search(loc) or re.search(r"work from home|\bwfh\b|fully remote|100% remote", job["title"] + " " + text[:1500], re.I):
        if not LOC_BLOCKED.search(loc):
            return "remote", None
    if NEAR.search(loc):
        return "near", None
    if FAR.search(loc):
        return None, "farther than 6 km from HSR"
    if loc and not BLR.search(loc):
        return None, "location"
    if NEAR.search(text[:3000]):
        return "near", None
    if FAR.search(text[:3000]):
        return None, "farther than 6 km from HSR"
    return "area not stated", None


def monthly(job):
    """Stated top salary per month, in rupees (None if not stated)."""
    return round(job["salary_max_lpa"] * 1e5 / 12) if job["salary_max_lpa"] else None


def reject_reason(job):
    text = f"{job['title']}\n{job['description'] or ''}"
    if not title_ok(job["title"]):
        return "title"
    if job.get("consultant") or AGENCY_CO.search(job["company"] or "") or AGENCY_TXT.search(text[:2500]):
        return "agency or job drive"
    if SCAM_TXT.search(text):
        return "possible scam"
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
        return "experience"
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
    _inbox_add("quick.json", [dict(_slim(j), track="quick", part_time=j.get("part_time"), where=j.get("where")) for j in fresh])

    # Hourly digest: queue now, send when an hour has passed since the last one.
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
    li, ok = src_linkedin.fetch(seen, dt.fromisoformat(last) if last else None,
                                searches=[(kw, place, places[place]) for kw, place in Q["linkedin_queries"]],
                                title_filter=title_ok, loc_filter=location_ok,
                                max_results=Q["linkedin_max_results"], detail_cap=Q["linkedin_max_details"])
    if ok:
        seen.meta["linkedin_last_run"] = now().isoformat()
    try:
        nk = src_naukri.fetch(seen, queries=[tuple(x) for x in Q["naukri_queries"]], title_filter=title_ok,
                              detail_cap=Q["naukri_max_details"], pages_per_query=1, job_age_days=3)
    except Exception as e:
        log("naukri (quick) failed:", e)
        nk = []
    process(li + nk, seen, "Quick jobs")
