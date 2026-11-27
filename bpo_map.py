"""Build docs/bpo.json: BPO / call-centre / customer-support offices within 7 km of HSR Layout Sector 7,
from OpenStreetMap (Overpass). Run occasionally: python3 bpo_map.py"""
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

LAT, LON, RADIUS = 12.9116, 77.6474, 7000  # HSR Layout Sector 7
NAME = r"BPO|call ?cent|KPO|contact cent|customer (care|support|service)|teleperformance|concentrix|conduent|genpact|startek|firstsource|sutherland|alorica|foundever|ibex|taskus|ttec|infosys bpm|xl dynamics"
QUERY = f"""[out:json][timeout:25];(
 nwr["office"="call_centre"](around:{RADIUS},{LAT},{LON});
 nwr["name"~"{NAME}",i](around:{RADIUS},{LAT},{LON});
);out center tags 300;"""
SERVERS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
           "https://overpass.private.coffee/api/interpreter", "https://lz4.overpass-api.de/api/interpreter"]


def km(lat, lon):
    p = math.pi / 180
    a = math.sin((lat - LAT) * p / 2) ** 2 + math.cos(LAT * p) * math.cos(lat * p) * math.sin((lon - LON) * p / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def fetch():
    body = urllib.parse.urlencode({"data": QUERY}).encode()
    for attempt in range(3):
        for s in SERVERS:
            try:
                req = urllib.request.Request(s, body, {"User-Agent": "job-finder-map/1.0"})
                return json.load(urllib.request.urlopen(req, timeout=40))["elements"]
            except Exception as e:
                print("retry", s, type(e).__name__, file=sys.stderr)
        time.sleep(10 * (attempt + 1))
    sys.exit("Overpass unavailable; try again later")


out, seen = [], set()
for e in fetch():
    t, c = e.get("tags", {}), e.get("center") or e
    if not t.get("name") or "lat" not in c:
        continue
    key = (t["name"].lower(), round(c["lat"], 3), round(c["lon"], 3))
    if key in seen:
        continue
    seen.add(key)
    addr = ", ".join(t[k] for k in ("addr:housename", "addr:street", "addr:suburb", "addr:city") if t.get(k))
    out.append({"name": t["name"], "lat": round(c["lat"], 5), "lon": round(c["lon"], 5), "addr": addr,
                "web": t.get("website") or t.get("contact:website") or "", "km": round(km(c["lat"], c["lon"]), 1)})
out.sort(key=lambda x: x["km"])
Path(__file__).parent.joinpath("docs", "bpo.json").write_text(json.dumps({"center": [LAT, LON], "items": out}, indent=0))
print(len(out), "offices written")
