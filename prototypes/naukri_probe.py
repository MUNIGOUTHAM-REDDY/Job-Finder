"""Prototype: can a real Chrome window read Naukri search results?

Opens Naukri's date-sorted search page and captures the JSON the page itself
fetches (jobapi/v3/search), so we get structured data without parsing HTML.
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
HEADLESS = "--headed" not in sys.argv
URL = "https://www.naukri.com/ui-ux-designer-jobs?k=ui%20ux%20designer&sort=f&jobAge=1"

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        str(HERE / ".chrome-profile"), channel="chrome", headless=HEADLESS,
        viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = ctx.new_page()
    captured = []

    def on_response(r):
        if "jobapi/v3/search" in r.url:
            try:
                captured.append((r.status, r.json()))
            except Exception as e:
                captured.append((r.status, {"error": str(e)}))

    page.on("response", on_response)
    page.goto(URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(8000)

    print("headless:", HEADLESS, "| page title:", page.title())
    if not captured:
        print("no search API response captured")
        page.screenshot(path=str(HERE / "naukri_probe.png"))
    for status, data in captured:
        print("API status:", status)
        jobs = data.get("jobDetails", [])
        print("jobs returned:", len(jobs), "| total:", data.get("noOfJobs"))
        if jobs:
            (HERE / "naukri_sample.json").write_text(json.dumps(jobs[0], indent=2))
            print("fields:", sorted(jobs[0].keys()))
        for j in jobs[:8]:
            print("-", j.get("title"), "|", j.get("companyName"), "|",
                  j.get("footerPlaceholderLabel"), "|", j.get("createdDate"))
    ctx.close()
