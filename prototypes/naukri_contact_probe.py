import json, re
from pathlib import Path
from playwright.sync_api import sync_playwright
HERE = Path(__file__).resolve().parent
def walk(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items(): yield from walk(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o[:3]): yield from walk(v, f"{path}[{i}]")
    else: yield path, o
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(HERE/".chrome-profile"), channel="chrome", headless=False,
        args=["--disable-blink-features=AutomationControlled","--window-position=-2400,0"])
    page = ctx.new_page(); search, detail = [], []
    page.on("response", lambda r: (search if "jobapi/v3/search" in r.url else detail if "jobapi/v4/job/" in r.url else []).append(r))
    page.goto("https://www.naukri.com/ui-ux-designer-jobs?k=ui%20ux%20designer&sort=f&jobAge=3", wait_until="domcontentloaded")
    page.wait_for_timeout(7000)
    jobs = [x for x in search[0].json()["jobDetails"] if re.search(r"ui|ux|product design|visual", x["title"], re.I)][:4]
    for j in jobs:
        detail.clear()
        page.goto("https://www.naukri.com" + j["jdURL"], wait_until="domcontentloaded"); page.wait_for_timeout(5000)
        d = next((r.json() for r in detail if r.ok), {})
        print("\n==", j["title"], "|", j["companyName"])
        for k, v in walk(d):
            if v in (None, "", [], False): continue
            if re.search(r"compan|recruit|contact|email|phone|mobile|website|address|hr|consult|employer", k, re.I):
                print(f"  {k} = {str(v)[:120]}")
        jd = re.sub("<[^>]+>", " ", json.dumps(d))
        print("  emails in JD:", set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", jd)), "| phones:", set(re.findall(r"(?:\+91[\s-]?)?[6-9]\d{9}", jd)))
    ctx.close()
