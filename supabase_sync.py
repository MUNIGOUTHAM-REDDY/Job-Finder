"""Copy the application log into Supabase. Only new or changed rows are sent, so it's safe to run often.

  python3 supabase_sync.py <path to a job-applications checkout>

Needs SUPABASE_URL and SUPABASE_SECRET_KEY (environment or .env). Prints counts only: this runs in public logs.
"""
import base64
import gzip
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_env():
    f = HERE / ".env"
    for line in f.read_text().splitlines() if f.exists() else []:
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def call(path, rows=None):
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path
    headers = {"apikey": os.environ["SUPABASE_SECRET_KEY"], "Content-Type": "application/json",
               "User-Agent": "job-finder-sync", "Accept-Encoding": "gzip"}
    if rows is not None:
        headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
    body = None if rows is None else json.dumps(rows).encode()
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, body, headers), timeout=60) as r:
                text = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    text = gzip.decompress(text)
                return json.loads(text) if text else None
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == 3:
                raise SystemExit(f"supabase {path.split('?')[0]}: HTTP {e.code} {e.read()[:200]!r}")
        except OSError as e:
            if attempt == 3:
                raise SystemExit(f"supabase {path.split('?')[0]}: {e}")
        time.sleep(2 ** attempt)


def digest(value):
    return hashlib.sha1(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def push(table, pk, rows, batch_bytes=1_500_000):
    """Upsert the rows whose hash differs from what's stored."""
    have, start = {}, 0
    while True:
        page = call(f"{table}?select={pk},hash&order={pk}&limit=1000&offset={start}")
        have.update({r[pk]: r["hash"] for r in page})
        if len(page) < 1000:
            break
        start += 1000
    changed = [r for r in rows if have.get(r[pk]) != r["hash"]]
    batch, size = [], 0
    for r in changed:
        n = len(json.dumps(r))
        if batch and (size + n > batch_bytes or len(batch) >= 500):
            call(f"{table}?on_conflict={pk}", batch)
            batch, size = [], 0
        batch.append(r)
        size += n
    if batch:
        call(f"{table}?on_conflict={pk}", batch)
    print(f"supabase {table}: {len(rows)} local, {len(changed)} sent")


def clean(value):
    """Postgres jsonb can't hold NUL characters."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    return value


def main(root):
    apps = []
    for f in sorted((root / "applications").glob("*.json")):
        a = clean(json.loads(f.read_text()))
        apps.append({"key": a["key"], "track": a.get("track") or "design", "found_at": a.get("found_at"),
                     "data": a, "hash": digest(a)})
    jobs = {}
    for f in sorted((root / "jobs").glob("*/*.jsonl")):
        for line in f.read_text().splitlines():
            if line.strip():
                j = clean(json.loads(line))
                old = jobs.get(str(j["id"]))
                if not old or (j.get("seen_at") or "") >= (old["seen_at"] or ""):
                    jobs[str(j["id"])] = {"id": str(j["id"]), "track": j.get("track") or "design",
                                          "seen_at": j.get("seen_at"), "data": j, "hash": digest(j)}
    docs = []
    for name, path in (("profile", root / "profile.json"), ("overrides", root / "jobs" / "overrides.json")):
        if path.exists():
            d = clean(json.loads(path.read_text()))
            docs.append({"name": name, "data": d, "hash": digest(d)})
    resumes = []
    for f in sorted((root / "resumes").glob("*.pdf")):
        raw = f.read_bytes()
        resumes.append({"name": f.name, "pdf_base64": base64.b64encode(raw).decode(), "hash": hashlib.sha1(raw).hexdigest()})
    push("applications", "key", apps)
    push("jobs", "id", list(jobs.values()))
    push("docs", "name", docs)
    push("resumes", "name", resumes)


if __name__ == "__main__":
    if len(sys.argv) != 2 or not (Path(sys.argv[1]) / "applications").is_dir():
        sys.exit(__doc__)
    load_env()
    main(Path(sys.argv[1]).resolve())
