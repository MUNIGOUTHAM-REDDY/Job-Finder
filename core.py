"""Shared pieces: job shape, filters, tiers, de-duplication, contacts, Telegram."""
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "config.json").read_text())
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
USD_INR, EUR_INR = 88, 95  # rough, only used to compare remote salaries


e_ = html.escape


def now():
    return datetime.now(timezone.utc)


def log(*a):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}]", *a, flush=True)


def load_env():
    env = HERE / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def http_get(url, timeout=20, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def http_json(url, timeout=20):
    return json.loads(http_get(url, timeout, {"Accept": "application/json"}))


def strip_html(s):
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s or "", flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>|</p>|</li>|</div>", "\n", s, flags=re.I)
    return re.sub(r"[ \t]+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def new_job(**kw):
    """A job is a plain dict; every source fills what it can."""
    job = dict(id=None, source="", title="", company="", location="", url="",
               posted_at=None, applicants=None, applicants_text="", views=None, openings=None,
               exp_min=None, exp_max=None, exp_text="", salary_min_lpa=None, salary_max_lpa=None,
               salary_text="", description="", company_about="", company_address="",
               rating="", consultant=False, contacts={})
    job.update(kw)
    return job


# --- matching ----------------------------------------------------------------

def _rx(words):
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(w) for w in words) + r")(?![a-z0-9])", re.I)


T = CFG["titles"]
DESIGN, DESIGN_ENG, EXCLUDE, SIGNALS = (_rx(T["design"]), _rx(T["design_engineering"]),
                                        _rx(T["exclude"]), _rx(T["design_signals"]))
L = CFG["locations"]
LOC_OK, LOC_REMOTE, LOC_BLOCKED = _rx(L["allow"]), _rx(L["remote_words"]), _rx(L["remote_blocked"])
F = CFG["filters"]


def title_ok(title):
    """Cheap first pass on the title alone (before fetching details)."""
    if EXCLUDE.search(title):
        return False
    return bool(DESIGN.search(title) or DESIGN_ENG.search(title))


def location_ok(loc):
    if not loc or LOC_OK.search(loc):
        return True
    return bool(LOC_REMOTE.search(loc)) and not LOC_BLOCKED.search(loc)


def age_hours(job):
    return None if not job["posted_at"] else (now() - job["posted_at"]).total_seconds() / 3600


EXP = re.compile(r"(?<![\d.])(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*(\d{1,2}))?\s*\+?\s*(?:years?|yrs?)", re.I)


def fill_experience(job):
    """Read 'X-Y years of experience' from the description when the source has no structured value."""
    if job["exp_min"] is not None or not job["description"]:
        return job
    text = job["description"]
    for m in EXP.finditer(text):
        after, before = text[m.end():m.end() + 30].lower(), text[max(0, m.start() - 25):m.start()].lower()
        if re.match(r"\s*(ago|old)", after) or not (re.match(r"[^.\n]{0,20}exp", after) or "exp" in before):
            continue
        lo, hi = int(m.group(1)), int(m.group(2)) if m.group(2) else None
        if lo > 20 or (hi is not None and (hi < lo or hi > 25)):
            continue
        job["exp_min"], job["exp_max"] = lo, hi
        job["exp_text"] = f"{lo}–{hi} yrs" if hi else f"{lo}+ yrs"
        return job
    return job


def reject_reason(job):
    """Full check once details are known. Returns None if the job passes."""
    if not title_ok(job["title"]):
        return "title"
    if DESIGN_ENG.search(job["title"]) and not DESIGN.search(job["title"]):
        # "Design Engineer" is usually mechanical/chip work in India: demand UI signals.
        if job["description"] and len(SIGNALS.findall(job["description"])) < 2:
            return "design-eng without UI signals"
    if not location_ok(job["location"]):
        return "location"
    if job["exp_min"] is not None and job["exp_min"] > F["max_experience_min_years"]:
        return "experience"
    if job["salary_max_lpa"] and job["salary_max_lpa"] < F["min_salary_lpa"]:
        return "salary"
    a = age_hours(job)
    if a is not None and a > F["max_age_hours"]:
        return "too old"
    if job["applicants"] is not None and job["applicants"] >= F["max_applicants"]:
        return "too many applicants"
    return None


def tier(job):
    a, n = age_hours(job), job["applicants"]
    for t in CFG["tiers"]:
        if (a is None or a <= t["max_age_hours"]) and (n is None or n < t["max_applicants"]):
            return t["label"]
    return CFG["tiers"][-1]["label"]


def parse_relative(text):
    """'3 hours ago', '45 minutes ago', 'Just now', '1 day ago' -> datetime."""
    t = (text or "").lower()
    if "just" in t or "few" in t or "moment" in t:
        return now()
    m = re.search(r"(\d+)\s*(second|minute|min|hour|hr|day|week|month)", t)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    secs = {"second": 1, "minute": 60, "min": 60, "hour": 3600, "hr": 3600,
            "day": 86400, "week": 604800, "month": 2592000}[unit]
    return now() - timedelta(seconds=n * secs)


def usd_to_lpa(amount_per_year, currency="USD"):
    rate = EUR_INR if currency == "EUR" else USD_INR
    return round(amount_per_year * rate / 1e5, 1)


# --- de-duplication ------------------------------------------------------------

def norm_key(job):
    co = re.sub(r"\b(pvt|private|ltd|limited|inc|llc|technologies|technology|solutions|india)\b|[^a-z0-9]",
                "", job["company"].lower())
    ti = re.sub(r"[^a-z0-9]", "", job["title"].lower())
    return f"{co}|{ti}"


class Seen:
    """Remembers alerted jobs by source id and by company+title, for 21 days."""

    def __init__(self, path):
        self.path = Path(path)
        self.first_run = not self.path.exists()
        data = {} if self.first_run else json.loads(self.path.read_text())
        self.items = data.get("items", {})
        self.meta = data.get("meta", {})

    def has(self, job):
        return job["id"] in self.items or norm_key(job) in self.items

    def add(self, job):
        ts = now().isoformat()
        self.items[job["id"]] = ts
        self.items[norm_key(job)] = ts

    def save(self):
        cutoff = (now() - timedelta(days=21)).isoformat()
        self.items = {k: v for k, v in self.items.items() if v >= cutoff}
        self.path.parent.mkdir(exist_ok=True)
        self.path.write_text(json.dumps({"meta": self.meta, "items": self.items}, indent=0))


# --- contacts --------------------------------------------------------------------

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<![\d/=_-])(?:\+91[\s-]?|0)?(?:[6-9]\d{4}[\s-]?\d{5}|\d{2,4}[\s-]\d{6,8})(?![\d/_-])")
JUNK_EMAIL = re.compile(r"\.(png|jpe?g|gif|svg|webp)$|example\.|sentry|wixpress|noreply|no-reply|domain\.com", re.I)
SKIP_DOMAINS = ("naukri", "linkedin", "ambitionbox", "glassdoor", "indeed", "wikipedia", "facebook",
                "instagram", "twitter", "x.com", "youtube", "crunchbase", "zaubacorp", "tofler",
                "justdial", "duckduckgo", "foundit", "instahyre", "wellfound", "quora", "economictimes")


def _pick_emails(found):
    found = [e for e in dict.fromkeys(found) if not JUNK_EMAIL.search(e)]
    rank = lambda e: (0 if re.match(r"(hr|career|jobs|talent|hiring|recruit|people)", e, re.I) else 1)
    return sorted(found, key=rank)[:2]


def _pick_phones(found):
    out = []
    for p in dict.fromkeys(found):
        digits = re.sub(r"\D", "", p)
        if 10 <= len(digits) <= 13 and len(set(digits)) > 3:
            out.append(p.strip())
    return out[:2]


def find_website(company):
    try:
        q = urllib.parse.quote(f"{company} official website India")
        page = http_get(f"https://html.duckduckgo.com/html/?q={q}", timeout=10)
    except Exception:
        return None
    for href in re.findall(r'class="result__a" href="([^"]+)"', page):
        m = re.search(r"uddg=([^&]+)", href)
        url = urllib.parse.unquote(m.group(1)) if m else href
        host = urllib.parse.urlparse(url).netloc.lower()
        if host and not any(d in host for d in SKIP_DOMAINS):
            return f"https://{host}"
    return None


def enrich_contacts(job):
    """Best effort: contacts written in the posting, then the company's own site."""
    text = job["description"]
    contacts = {"emails": _pick_emails(EMAIL.findall(text)), "phones": _pick_phones(PHONE.findall(text)),
                "from": "job post" if EMAIL.search(text) else "", "website": None}
    if not job["consultant"] and (not contacts["emails"] or not contacts["phones"]):
        site = find_website(job["company"])
        if site:
            contacts["website"] = site
            emails, phones = [], []
            try:
                home = http_get(site, timeout=10)
                pages = [home]
                links = re.findall(r'href="([^"#]+)"', home)
                for l in [l for l in links if re.search(r"contact|career|about|jobs", l, re.I)][:3]:
                    try:
                        pages.append(http_get(urllib.parse.urljoin(site, l), timeout=8))
                    except Exception:
                        pass
                for p in pages:
                    t = strip_html(p) + " " + " ".join(re.findall(r'mailto:([^"?]+)', p))
                    emails += EMAIL.findall(t)
                    phones += re.findall(r"\+91[\s-]?\d[\d\s-]{8,12}\d", t)
            except Exception:
                pass
            if not contacts["emails"]:
                contacts["emails"] = _pick_emails(emails)
            if not contacts["phones"]:
                contacts["phones"] = _pick_phones(phones)
            if emails or phones:
                contacts["from"] = contacts["from"] or "company website"
    job["contacts"] = contacts
    return job


# --- telegram ----------------------------------------------------------------------

def tg_send(text, silent=False):
    token, chat = os.environ.get("TG_BOT_TOKEN"), os.environ.get("TG_CHAT_ID")
    if not (token and chat):
        log("telegram not configured; message would be:\n" + text)
        return False
    body = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true",
                                   "disable_notification": "true" if silent else "false"}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", body, timeout=15)
        return True
    except Exception as e:
        log("telegram failed:", e)
        return False


def _ago(job):
    a = age_hours(job)
    if a is None:
        return "Just posted"
    if a < 1:
        return f"{max(1, int(a * 60))} min ago"
    return f"{a:.0f} hr ago" if a < 24 else f"{a / 24:.0f} d ago"


def _salary(job):
    lo, hi = job["salary_min_lpa"], job["salary_max_lpa"]
    if not hi:
        return job["salary_text"] if job["salary_text"] and "disclosed" not in job["salary_text"].lower() \
            else "Salary not disclosed"
    rng = f"₹{lo:g}–{hi:g} LPA" if lo and lo != hi else f"₹{hi:g} LPA"
    return rng + f" (₹{(lo or hi) * 1e5 / 12 / 1000:.0f}k–{hi * 1e5 / 12 / 1000:.0f}k/mo)"


def format_alert(job):
    """One role as a compact card. Minimal icons: one per line, tier dot on top."""
    e = lambda s: html.escape(str(s or ""))
    c = job["contacts"]
    stats = [_ago(job)]
    if job["applicants_text"] or job["applicants"] is not None:
        stats.append(job["applicants_text"] if job["applicants"] != 0 else "Under 25 applicants")
    if job["views"] is not None:
        stats.append(f"{job['views']} views")
    if job["openings"]:
        stats.append(f"{job['openings']} openings")
    exp = job["exp_text"] if job["exp_text"] and "applicable" not in job["exp_text"].lower() else "Experience not specified"
    role = [exp, _salary(job)]
    company = ["Recruitment agency" if job["consultant"] else "Direct employer"]
    if job["rating"]:
        company.append(f"{job['rating']} on AmbitionBox")

    lines = [f"{tier(job)}", "", f"<b>{e(job['title'])}</b>",
             f"{e(job['company'])}  ·  {e(job['location'] or 'Location n/a')}", "",
             f"🕒  {e('  ·  '.join(stats))}",
             f"💼  {e('  ·  '.join(role))}",
             f"🏢  {e('  ·  '.join(company))}"]
    if job["company_address"] and job["company_address"].lower() not in job["location"].lower():
        lines.append(f"📍  {e(job['company_address'][:110])}")
    contact = c.get("emails", []) + c.get("phones", [])
    if contact:
        lines.append(f"✉️  {e('  ·  '.join(contact))}" + (f"  <i>({e(c['from'])})</i>" if c.get("from") else ""))
    elif c.get("website"):
        lines.append(f"🌐  {e(c['website'])}")
    q = urllib.parse.quote
    people = f"https://www.linkedin.com/search/results/people/?keywords={q(job['company'] + ' recruiter OR talent')}"
    mgr = f"https://www.linkedin.com/search/results/people/?keywords={q(job['company'] + ' design manager')}"
    lines += ["", f'<a href="{e(job["url"])}"><b>View on {e(job["source"])} →</b></a>   '
                  f'<a href="{people}">Recruiter</a>  ·  <a href="{mgr}">Design manager</a>']
    return "\n".join(lines)


def process(jobs, seen, label, platforms):
    """Filter, then send every new matching role as its own card."""
    fresh, reasons = [], {}
    for job in jobs:
        if seen.has(job):
            continue
        r = reject_reason(fill_experience(job))
        if r:
            reasons[r] = reasons.get(r, 0) + 1
            continue
        fresh.append(job)
    fresh.sort(key=lambda j: (age_hours(j) if age_hours(j) is not None else 0), reverse=True)  # newest last

    if seen.first_run:
        tg_send(f"<b>Job Finder is live</b>  ·  {e_(label)}\n"
                f"{len(fresh)} matching role{'s' if len(fresh) != 1 else ''} open right now"
                + (", listed below." if fresh else ". New ones will arrive here as they're posted."))
    if not fresh and not seen.first_run:
        counts = {}
        for j in jobs:
            counts[j["source"]] = counts.get(j["source"], 0) + 1
        lines = [f"• {e_(name)}  ·  {counts.get(key, 0)} design roles checked" + (f"  <i>({e_(note)})</i>" if note else "")
                 for name, key, note in platforms]
        tg_send(f"🔍 <b>No new matching roles</b>  ·  {datetime.now(timezone(timedelta(hours=5, minutes=30))):%I:%M %p}\n"
                + "\n".join(lines), silent=True)
    for j in fresh:
        enrich_contacts(j)
        if tg_send(format_alert(j)):
            seen.add(j)
        time.sleep(1.1)  # Telegram allows ~1 message/second per chat
    log(f"{label}: {len(jobs)} checked, {len(fresh)} alerted, skipped {reasons}")
    seen.save()
    return fresh


if __name__ == "__main__":
    sys.exit("run run.py instead")
