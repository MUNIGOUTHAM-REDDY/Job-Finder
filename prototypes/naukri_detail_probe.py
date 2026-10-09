import json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
HERE = Path(__file__).resolve().parent
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(HERE/".chrome-profile"), channel="chrome", headless=False,
        args=["--disable-blink-features=AutomationControlled","--window-position=-2400,0"])
    page = ctx.new_page()
    search, detail = [], []
    page.on("response", lambda r: (search if "jobapi/v3/search" in r.url else detail if "jobapi/v4/job/" in r.url else []).append(r))
    page.goto("https://www.naukri.com/product-designer-jobs?k=product%20designer&sort=f&jobAge=1", wait_until="domcontentloaded")
    page.wait_for_timeout(7000)
    jobs = search[0].json()["jobDetails"]
    j = next(x for x in jobs if "design" in x["title"].lower() and x.get("jdURL"))
    print("opening:", j["title"], "|", j["companyName"])
    page.goto("https://www.naukri.com" + j["jdURL"], wait_until="domcontentloaded")
    page.wait_for_timeout(7000)
    for r in detail:
        try:
            d = r.json()
        except Exception:
            continue
        jd = d.get("jobDetails", d)
        keys = {k: jd[k] for k in jd if any(w in k.lower() for w in ("appl", "view", "creat", "open", "vacan"))}
        print("detail API keys of interest:", json.dumps(keys, default=str)[:600])
    txt = page.inner_text("body")
    import re
    print("page text:", re.findall(r"(Applicants?:?\s*[\d,+]+|Openings?:?\s*\d+|Posted:?\s*[^\n]+)", txt)[:5])
    ctx.close()
