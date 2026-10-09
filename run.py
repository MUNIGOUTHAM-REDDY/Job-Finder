#!/usr/bin/env python3
"""Run one check.

  python run.py --mac        LinkedIn + Naukri (on your Mac, every 10 min)
  python run.py --cloud      company career sites + remote boards (GitHub Actions)
  python run.py --test       send a sample alert to Telegram
"""
import sys
from datetime import datetime, timedelta, timezone

from core import CFG, HERE, Seen, format_alert, load_env, log, new_job, now, process, tg_send

IST = timezone(timedelta(hours=5, minutes=30))


def quiet_hours_skip(seen):
    """At night, check only every few hours. Returns True if this run should be skipped."""
    q = CFG["night"]
    hour = now().astimezone(IST).hour
    night = hour >= q["start_hour"] or hour < q["end_hour"]
    last = seen.meta.get("last_check")
    if night and last and (now() - datetime.fromisoformat(last)).total_seconds() < q["every_hours"] * 3600 - 300:
        return True
    seen.meta["last_check"] = now().isoformat()
    return False


def company_platforms():
    companies = sum(len(v) for v in CFG["companies"].values())
    return [(f"Company career sites ({companies} companies)", "company site", ""),
            ("Remotive", "Remotive", ""), ("RemoteOK", "RemoteOK", "")]


def mac():
    """LinkedIn + Naukri. Company sites run in the cloud (cloud())."""
    import src_linkedin
    import src_naukri

    seen = Seen(HERE / "state" / "seen-mac.json")
    if quiet_hours_skip(seen):
        return
    last = seen.meta.get("linkedin_last_run")
    li_jobs, ok = src_linkedin.fetch(seen, datetime.fromisoformat(last) if last else None)
    if ok:
        seen.meta["linkedin_last_run"] = now().isoformat()
    nk_note = ""
    try:
        nk_jobs = src_naukri.fetch(seen)
    except Exception as e:
        log("naukri failed:", e)
        nk_jobs, nk_note = [], "couldn't load this time"
    process(li_jobs + nk_jobs, seen, "LinkedIn + Naukri",
            [("LinkedIn", "LinkedIn", "" if ok else "rate limited, will retry"), ("Naukri", "Naukri", nk_note)])


def cloud():
    """Company career sites + remote boards, on GitHub Actions."""
    import src_ats

    seen = Seen(HERE / "state" / "seen-cloud.json")
    if quiet_hours_skip(seen):
        return
    process(src_ats.fetch(), seen, "company sites", company_platforms())


def test():
    job = new_job(id="test", source="Naukri", title="UI/UX Designer (sample alert)", company="Test Company",
                  location="Indiranagar, Bengaluru", url="https://www.naukri.com", exp_text="1-3 Yrs",
                  posted_at=now() - timedelta(minutes=12), applicants=5, applicants_text="5 applicants",
                  views=7, openings=2, salary_min_lpa=5, salary_max_lpa=7, rating="4.1 (120 reviews)",
                  contacts={"emails": ["careers@example.in"], "phones": [], "from": "sample"})
    print("sent" if tg_send(format_alert(job)) else "not sent (check .env)")


if __name__ == "__main__":
    load_env()
    {"--mac": mac, "--cloud": cloud, "--test": test}.get(next(iter(sys.argv[1:]), ""), lambda: print(__doc__))()
