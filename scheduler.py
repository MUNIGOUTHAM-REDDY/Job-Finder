"""What to search, where, and when. Settings come from the dashboard's Searches tab (Supabase);
anything not set there falls back to config.json.

  python scheduler.py due                      print the searches to run now, and mark them started
  python scheduler.py report <search> ok|failed
  python scheduler.py publish                  send the built-in search terms to the dashboard
"""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "config.json").read_text())
IST = timezone(timedelta(hours=5, minutes=30))
STATE = HERE / "state" / "schedule.json"          # when each search last started
CACHE = HERE / "state" / "search-settings.json"   # last settings read, used if Supabase can't be reached
LATE = timedelta(minutes=90)                      # a set time missed by more than this is skipped
# In run order. "every" is the default repeat in minutes.
SEARCHES = {
    "company": {"every": 10, "sources": ("career_pages", "remotive", "remoteok", "hirist", "foundit", "cutshort", "wellfound")},
    "design_feeds": {"every": 10, "sources": ("linkedin", "naukri")},
    "quick": {"every": 20, "sources": ("linkedin", "naukri")},
}


def load_env():
    env = HERE / ".env"
    for line in env.read_text().splitlines() if env.exists() else []:
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def api(path, body=None):
    """GET, or PATCH when a body is given."""
    headers = {"apikey": os.environ["SUPABASE_SECRET_KEY"], "Content-Type": "application/json",
               "User-Agent": "job-finder-scheduler", "Prefer": "return=minimal"}
    req = urllib.request.Request(os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path,
                                 None if body is None else json.dumps(body).encode(), headers,
                                 method="GET" if body is None else "PATCH")
    with urllib.request.urlopen(req, timeout=20) as r:
        text = r.read()
        return json.loads(text) if text else None


def read_row(name):
    rows = api(f"settings?name=eq.{name}&select=data")
    return rows[0]["data"] if rows else {}


def write_row(name, data):
    api(f"settings?name=eq.{name}", {"data": data, "updated_at": datetime.now(timezone.utc).isoformat()})


def _read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


@lru_cache(maxsize=None)
def settings():
    if not os.environ.get("SUPABASE_SECRET_KEY"):
        return _read(CACHE)
    try:
        data = read_row("searches")
    except Exception as e:
        print("search settings unavailable, using the last copy:", type(e).__name__, file=sys.stderr)
        return _read(CACHE)
    CACHE.write_text(json.dumps(data))
    return data


def search(search_id):
    d = (settings().get("searches") or {}).get(search_id) or {}
    return {"enabled": d.get("enabled", True), "every": int(d.get("every", SEARCHES[search_id]["every"])),
            "times": [t for t in d.get("times", []) if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(t))],
            "off": set(d.get("off", []))}


def enabled(search_id, source):
    return source not in search(search_id)["off"]


# --- search terms (job roles) -----------------------------------------------------------

def default_terms(track):
    if track == "design":
        return list(CFG["search_keywords"])
    q = CFG["quick"]
    return list(dict.fromkeys(kw for kw, _ in q["linkedin_queries"] + q["naukri_queries"]))


def _clean(words):
    return list(dict.fromkeys(" ".join(str(w).lower().split()) for w in words if str(w).strip()))


def added(track):
    """Roles you added that aren't built in."""
    mine = (settings().get("roles") or {}).get(track) or {}
    return [t for t in _clean(mine.get("add", [])) if t not in default_terms(track)]


def terms(track):
    removed = set(_clean(((settings().get("roles") or {}).get(track) or {}).get("remove", [])))
    return [t for t in default_terms(track) if t not in removed] + added(track)


def is_added_role(track, title, exclude):
    """True if the title names a role you added. An excluded word inside that role doesn't count
    (add "sales executive" and it passes), but one elsewhere in the title still does."""
    for role in added(track):
        words = r"[\s/,&-]+".join(re.escape(w) for w in role.split())
        m = re.search(rf"(?<![a-z0-9]){words}s?(?![a-z0-9])", title, re.I)
        if m and not exclude.search(title[:m.start()] + " " + title[m.end():]):
            return True
    return False


def quick_queries():
    """(LinkedIn [keyword, place] pairs, Naukri [keyword, city] pairs) for the quick search."""
    q, on, new = CFG["quick"], set(terms("quick")), added("quick")
    linkedin = [p for p in q["linkedin_queries"] if p[0] in on] + [[r, place] for r in new for place in ("Bengaluru", "Remote")]
    naukri = [p for p in q["naukri_queries"] if p[0] in on] + [[r, "bangalore"] for r in new]
    return linkedin, naukri


# --- timing -----------------------------------------------------------------------------

def is_due(cfg, last, now):
    """last: when it last started (aware datetime) or None."""
    if not cfg["enabled"]:
        return False
    if cfg["every"] > 0 and (last is None or (now - last).total_seconds() >= cfg["every"] * 60 - 30):
        return True
    today = now.astimezone(IST).date()
    for t in cfg["times"]:
        hour, minute = map(int, t.split(":"))
        for day in (today, today - timedelta(days=1)):
            at = datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)
            if now - LATE <= at <= now and (last is None or last < at):
                return True
    return False


def last_runs():
    if STATE.exists():
        return _read(STATE)
    try:  # a fresh cloud run starts with no local state
        return {k: v["last"] for k, v in read_row("search_status").items()}
    except Exception:
        return {}


def due(now=None):
    now = now or datetime.now(timezone.utc)
    last = last_runs()
    ready = []
    for sid, info in SEARCHES.items():
        cfg = search(sid)
        if set(info["sources"]) <= cfg["off"]:
            continue
        if is_due(cfg, datetime.fromisoformat(last[sid]) if last.get(sid) else None, now):
            ready.append(sid)
            last[sid] = now.isoformat()
    STATE.write_text(json.dumps(last))
    return ready


def report(search_id, result):
    status = read_row("search_status")
    status[search_id] = {"last": last_runs().get(search_id), "finished": datetime.now(timezone.utc).isoformat(),
                         "ok": result == "ok"}
    write_row("search_status", status)


if __name__ == "__main__":
    load_env()
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "due":
        print(" ".join(due()))
    elif command == "report":
        report(sys.argv[2], sys.argv[3])
    elif command == "publish":
        write_row("search_defaults", {t: default_terms(t) for t in ("design", "quick")})
    else:
        sys.exit(__doc__)
