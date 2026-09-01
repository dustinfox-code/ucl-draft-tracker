#!/usr/bin/env python3
# ============================================================================
# Harvest Sofascore match-page URLs for the 2026 World Cup → data/sofascore.json
#
# The working CLI path. Sofascore blocks on TLS fingerprint (plain Node/curl
# get 403 even from a residential IP), so this uses curl_cffi to impersonate a
# Chrome TLS handshake:
#
#   pip install curl_cffi        (once)
#   python3 scripts/harvest-sofascore.py
#
# URL STABILITY — a placeholder slot ("w98-w97") gets a NEW slug + customId
# the moment its real teams are known (both are derived from the two teams),
# and the old placeholder URL 404s — verified 2026-07-06 when the pre-harvested
# R16 placeholder links all died. So undrawn slots are emitted as
# https://www.sofascore.com/event/{numeric id} instead: the numeric event id is
# the one identifier that survives the draw (the slot is the same pre-created
# event), and /event/{id} 301s to the canonical match page whatever it
# currently is. Resolved matches get their direct canonical URL (stable, no
# redirect hop). Net effect: one run covers the tournament; re-run only if
# fixtures are added/rescheduled, or cosmetically to upgrade /event/{id} links
# to direct URLs after a draw.
#
# SOURCES (same as the browser-console scripts):
#   /api/v1/unique-tournament/16/season/58210/events/{last,next}/{page}
#     group + resolved games; page from 0 until 404 (~16 events/page)
#   /api/v1/unique-tournament/16/season/58210/cuptrees → knockout event ids
#   /api/v1/event/{id} → customId, slug, teams for every knockout slot
#   16 = FIFA World Cup (men), 58210 = the 2026 season. New season id (if
#   ever): /api/v1/unique-tournament/16/seasons
#
# The season feed can drop an event or two when a page boundary shifts under
# live matches, so entries already in data/sofascore.json that are fully
# resolved are kept even if this run's feed missed them.
# ============================================================================
import json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path

try:
    from curl_cffi import requests
except ImportError:
    sys.exit("curl_cffi is required: pip install curl_cffi")

UT, SEASON = 16, 58210
BASE = "https://www.sofascore.com"
OUT = Path(__file__).resolve().parent.parent / "data" / "sofascore.json"

# Mirrors NAME_TO_CODE in index.html and the console scripts.
KNOWN = set("ARG ESP ENG FRA BRA GER POR MEX COL BEL NED NOR SUI CAN TUR ECU URU USA CRO JPN MAR SEN PAR AUT EGY SCO CZE KOR BIH IRN CIV SWE ALG PAN AUS COD RSA UZB NZL TUN KSA CPV GHA JOR HAI IRQ QAT CUW".split())
NAME_TO_CODE = {
    "Argentina":"ARG","Spain":"ESP","England":"ENG","France":"FRA","Brazil":"BRA",
    "Germany":"GER","Portugal":"POR","Mexico":"MEX","Colombia":"COL","Belgium":"BEL",
    "Netherlands":"NED","Norway":"NOR","Switzerland":"SUI","Canada":"CAN",
    "Turkey":"TUR","Türkiye":"TUR","Turkiye":"TUR",
    "Ecuador":"ECU","Uruguay":"URU","USA":"USA","United States":"USA",
    "Croatia":"CRO","Japan":"JPN","Morocco":"MAR","Senegal":"SEN","Paraguay":"PAR",
    "Austria":"AUT","Egypt":"EGY","Scotland":"SCO","Czechia":"CZE","Czech Republic":"CZE",
    "South Korea":"KOR","Korea Republic":"KOR","Korea, South":"KOR",
    "Bosnia & Herzegovina":"BIH","Bosnia and Herzegovina":"BIH","Bosnia-Herzegovina":"BIH",
    "Iran":"IRN","IR Iran":"IRN",
    "Ivory Coast":"CIV","Côte d'Ivoire":"CIV","Cote d'Ivoire":"CIV",
    "Sweden":"SWE","Algeria":"ALG","Panama":"PAN","Australia":"AUS",
    "DR Congo":"COD","Congo DR":"COD","Democratic Republic of Congo":"COD",
    "South Africa":"RSA","Uzbekistan":"UZB","New Zealand":"NZL","Tunisia":"TUN",
    "Saudi Arabia":"KSA","Cape Verde":"CPV","Cabo Verde":"CPV",
    "Ghana":"GHA","Jordan":"JOR","Haiti":"HAI","Iraq":"IRQ","Qatar":"QAT",
    "Curaçao":"CUW","Curacao":"CUW",
}
CODE_ALIAS = {}  # fill if it warns about an unresolved nameCode, e.g. "DRC":"COD"

sess = requests.Session(impersonate="chrome")

def get(path):
    return sess.get(BASE + path, headers={"accept": "application/json", "referer": BASE + "/"})

def code(t):
    if not t: return None
    nc = t.get("nameCode")
    if nc and nc in CODE_ALIAS: return CODE_ALIAS[nc]
    if nc and nc in KNOWN: return nc
    return NAME_TO_CODE.get(t.get("name"))

# Placeholder bracket slots before teams are known ("2A", "w74", "L77", "3A/3B").
def is_placeholder(n):
    return (not n) or bool(re.search(r"[0-9/]", n))

by_id, unresolved = {}, set()

def consider(e):
    if not e or not e.get("id") or not e.get("customId") or not e.get("slug") or not e.get("startTimestamp"): return
    c1, c2 = code(e.get("homeTeam")), code(e.get("awayTeam"))
    for c, t in ((c1, e.get("homeTeam")), (c2, e.get("awayTeam"))):
        if not c and t and not is_placeholder(t.get("name")):
            unresolved.add(f"{t.get('name')} [{t.get('nameCode')}]")
    resolved = [x for x in (c1, c2) if x]
    # Undrawn slot → /event/{id}: survives the draw. Resolved → direct URL.
    url = (f"{BASE}/football/match/{e['slug']}/{e['customId']}" if len(resolved) == 2
           else f"{BASE}/event/{e['id']}")
    entry = {"c": resolved, "ts": e["startTimestamp"] * 1000, "url": url}
    prev = by_id.get(e["id"])
    if not prev or len(entry["c"]) > len(prev["c"]):
        by_id[e["id"]] = entry

# ---- A) season feed: group + already-resolved games ------------------------
feed_count = 0
for kind in ("last", "next"):
    for page in range(50):
        r = get(f"/api/v1/unique-tournament/{UT}/season/{SEASON}/events/{kind}/{page}")
        if r.status_code == 404: break  # paged past the last page
        if r.status_code != 200:
            print(f"! {kind} page {page}: HTTP {r.status_code}", file=sys.stderr); break
        evs = r.json().get("events") or []
        if not evs: break
        feed_count += len(evs)
        for e in evs: consider(e)
        time.sleep(0.3)
print(f"feed: scanned {feed_count} events")

# ---- B) cup tree: every knockout slot, incl. undecided ones ----------------
bracket_ids = set()
r = get(f"/api/v1/unique-tournament/{UT}/season/{SEASON}/cuptrees")
if r.status_code == 200:
    def walk(o):
        if isinstance(o, list):
            for x in o: walk(x)
        elif isinstance(o, dict):
            if isinstance(o.get("events"), list):
                for x in o["events"]:
                    if isinstance(x, int): bracket_ids.add(x)
            for v in o.values(): walk(v)
    walk(r.json())
else:
    print(f"! cuptrees HTTP {r.status_code} — knockout slots may be incomplete", file=sys.stderr)
print(f"bracket: {len(bracket_ids)} event ids")

fetched = failed = 0
for eid in sorted(bracket_ids):
    r = get(f"/api/v1/event/{eid}")
    if r.status_code != 200:
        failed += 1; print(f"! event {eid}: HTTP {r.status_code}", file=sys.stderr)
    else:
        consider(r.json().get("event")); fetched += 1
    time.sleep(0.3)

# ---- C) rescue resolved entries the live feed missed this run --------------
def is_placeholder_slug(url):
    slug = url.rstrip("/").rsplit("/", 2)[-2]
    return any(re.fullmatch(r"[wl]\d+", part) for part in slug.split("-"))

rescued = 0
if OUT.exists():
    old = json.loads(OUT.read_text())
    for e in old.get("events", []):
        if len(e.get("c", [])) != 2 or is_placeholder_slug(e["url"]):
            continue
        dup = any(set(x["c"]) == set(e["c"]) and abs(x["ts"] - e["ts"]) < 36*3600000
                  for x in by_id.values() if len(x["c"]) == 2)
        if not dup:
            by_id[e["url"]] = e; rescued += 1
            print(f"rescued from previous file: {e['c']} {e['url']}")

# ---- output -----------------------------------------------------------------
events = sorted(by_id.values(), key=lambda e: e["ts"])
placeholders = sum(1 for e in events if len(e["c"]) < 2)
out = {"generated": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
       "count": len(events), "events": events}
OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
print(f"✓ wrote {len(events)} matches → {OUT.relative_to(Path.cwd()) if OUT.is_relative_to(Path.cwd()) else OUT}"
      f"  (bracket: {fetched} fetched, {failed} failed; {placeholders} still-placeholder slots; {rescued} rescued)")
if unresolved:
    print(f"⚠ unresolved teams (add to NAME_TO_CODE / CODE_ALIAS, then re-run):\n  " + "\n  ".join(sorted(unresolved)))
if not events:
    print("⚠ no matches found — if every request 403'd, curl_cffi may need an update; "
          "if every page 404'd, the season id may have changed (check /api/v1/unique-tournament/16/seasons).")
