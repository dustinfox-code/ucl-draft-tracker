#!/usr/bin/env python3
# ============================================================================
# Harvest Sofascore match-page URLs for UCL 2026-27 → data/sofascore.json
#
# The working CLI path. Sofascore blocks on TLS fingerprint (plain Node/curl
# get 403 even from a residential IP), so this uses curl_cffi to impersonate a
# Chrome TLS handshake:
#
#   pip install curl_cffi        (once; venv works too)
#   python3 scripts/harvest-sofascore.py
#
# URL STABILITY — a placeholder slot gets a NEW slug + customId the moment its
# real teams are known (both are derived from the two teams), and the old
# placeholder URL 404s — learned the hard way in the WC repo (2026-07-06) when
# every pre-harvested R16 placeholder link died. So undrawn slots are emitted
# as https://www.sofascore.com/event/{numeric id}: the numeric event id is the
# one identifier that survives the draw, and /event/{id} 301s to the canonical
# match page whatever it currently is. Resolved matches get their direct
# canonical URL (stable, no redirect hop).
#
# SOURCES:
#   /api/v1/unique-tournament/7/season/96518/events/{last,next}/{page}
#     league phase + resolved games; page from 0 until 404 (~16 events/page)
#   /api/v1/unique-tournament/7/season/96518/cuptrees → knockout event ids
#   /api/v1/event/{id} → customId, slug, teams for every knockout slot
#   7 = UEFA Champions League, 96518 = the 2026/27 season. New season id (if
#   ever): /api/v1/unique-tournament/7/seasons
#
# The 26/27 "season" on Sofascore also contains July/August qualifying rounds
# (81 clubs!), so events before MIN_TS (league-phase start) are skipped —
# qualifiers would otherwise leak in as half-resolved placeholder entries.
# Club nameCodes collide across the wider feed (VIK = Viking AND Víkingur
# Reykjavík, SHA = Shakhtar AND Shamrock Rovers), so resolution goes full
# name first, alias second, nameCode last.
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

UT, SEASON = 7, 96518
MIN_TS = int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp())  # skip qualifying rounds
BASE = "https://www.sofascore.com"
OUT = Path(__file__).resolve().parent.parent / "data" / "sofascore.json"

# Internal club codes (mirrors data/teams.json and index.html).
KNOWN = set("AEK ROM ARS AVL ATM BAR BAY BOD BVB BRU COM BET FEN FEY GAL INT LSK LEN LIL LIV MCI MUN NAP POR PSG PSV RBL RMA SAB SHK SLA SLO SCP VFB VIK VIL".split())
NAME_TO_CODE = {
    "AEK Athens":"AEK","AS Roma":"ROM","Arsenal":"ARS","Aston Villa":"AVL",
    "Atlético Madrid":"ATM","Atletico Madrid":"ATM",
    "Bodø/Glimt":"BOD","Bodo/Glimt":"BOD","FK Bodø/Glimt":"BOD",
    "Borussia Dortmund":"BVB","Club Brugge KV":"BRU","Club Brugge":"BRU",
    "Como":"COM","Como 1907":"COM",
    "FC Barcelona":"BAR","Barcelona":"BAR",
    "FC Bayern München":"BAY","Bayern München":"BAY","Bayern Munich":"BAY",
    "FC Porto":"POR","Porto":"POR",
    "Fenerbahçe":"FEN","Fenerbahce":"FEN",
    "Feyenoord":"FEY","Galatasaray":"GAL",
    "Inter":"INT","Inter Milan":"INT","FC Internazionale":"INT",
    "LASK":"LSK","LASK Linz":"LSK",
    "Lille":"LIL","Lille OSC":"LIL",
    "Liverpool FC":"LIV","Liverpool":"LIV",
    "Manchester City":"MCI","Manchester United":"MUN",
    "PSV Eindhoven":"PSV","PSV":"PSV",
    "Paris Saint-Germain":"PSG","RB Leipzig":"RBL",
    "RC Lens":"LEN","Lens":"LEN",
    "Real Betis":"BET","Real Madrid":"RMA",
    "SK Slavia Praha":"SLA","Slavia Praha":"SLA","Slavia Prague":"SLA",
    "SSC Napoli":"NAP","Napoli":"NAP",
    "Sabah FK":"SAB","Sabah":"SAB",
    "Shakhtar Donetsk":"SHK",
    "Sporting CP":"SCP","Sporting Lisbon":"SCP",
    "VfB Stuttgart":"VFB","Stuttgart":"VFB",
    "Viking FK":"VIK","Viking":"VIK",
    "Villarreal":"VIL","Villarreal CF":"VIL",
    "ŠK Slovan Bratislava":"SLO","Slovan Bratislava":"SLO",
}
# Sofascore nameCode → our code, where they differ (name match wins first).
CODE_ALIAS = {"B/G":"BOD","LASK":"LSK","SBH":"SAB","SHA":"SHK","RCL":"LEN",
              "FCB":"BAY","FCP":"POR","ASR":"ROM"}

sess = requests.Session(impersonate="chrome")

def get(path):
    return sess.get(BASE + path, headers={"accept": "application/json", "referer": BASE + "/"})

def code(t):
    if not t: return None
    byname = NAME_TO_CODE.get(t.get("name"))
    if byname: return byname
    nc = t.get("nameCode")
    if nc and nc in CODE_ALIAS: return CODE_ALIAS[nc]
    if nc and nc in KNOWN: return nc
    return None

# Placeholder bracket slots before teams are known. Club names can legitimately
# contain digits and slashes (Bodø/Glimt), so this is deliberately narrow:
# w98/L12-style tokens, "Winner/Loser of …", and seed-pair labels like "9/10".
def is_placeholder(n):
    if not n: return True
    if re.fullmatch(r"[WL]\d+", n, re.I): return True
    if re.search(r"\b(winner|loser|play-?off|seed)\b", n, re.I): return True
    if re.fullmatch(r"\d{1,2}(st|nd|rd|th)?([-/]\d{1,2}(st|nd|rd|th)?)*( place)?", n, re.I): return True
    return False

by_id, unresolved = {}, set()

def consider(e):
    if not e or not e.get("id") or not e.get("customId") or not e.get("slug") or not e.get("startTimestamp"): return
    if e["startTimestamp"] < MIN_TS: return  # qualifying rounds
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

# ---- A) season feed: league phase + already-resolved games ------------------
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
          "if every page 404'd, the season id may have changed (check /api/v1/unique-tournament/7/seasons).")
