#!/usr/bin/env python3
"""Harvest the UCL 2026-27 schedule from ESPN -> data/fixtures.json.

ESPN's public scoreboard API is the tracker's primary results feed (there is
no openfootball 2026-27 UCL file). This script sweeps the whole season window
and commits a snapshot so the page always has the full schedule + last-known
scores even if ESPN is unreachable at view time; the page then overlays the
live scoreboard on top, joined by ESPN event id.

Per match: ESPN event id, kickoff (ms), round (ESPN season slug, e.g.
"league-phase", later "round-of-16"), matchday (league phase only, derived by
clustering match dates — ESPN doesn't expose the MD number), club codes from
data/teams.json (joined on ESPN displayName — never abbreviations), score and
state.

Usage: python3 scripts/harvest-fixtures.py     # rewrites data/fixtures.json
Stdlib only. Exits non-zero on unresolved team names or an implausibly small
schedule, leaving the previous snapshot untouched.
"""

import json
import pathlib
import sys
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "fixtures.json"
TEAMS_FILE = ROOT / "data" / "teams.json"

URL = ("https://site.api.espn.com/apis/site/v2/sports/soccer/uefa.champions/"
       "scoreboard?dates={month}&limit=400")
# Season window, swept one calendar month at a time. ESPN dropped support for
# YYYYMMDD-YYYYMMDD ranges (400 "Failed to get events endpoint", verified
# 2026-10-15); single days (YYYYMMDD) and months (YYYYMM) still work. Year
# queries (YYYY) also work but straddle seasons, so months it is.
SEASON_MONTHS = ["202609", "202610", "202611", "202612", "202701",
                 "202702", "202703", "202704", "202705", "202706"]


def main() -> None:
    # Case-insensitive: ESPN's casing drifts (Viking became "VIKING FK" in
    # Oct 2026) while the name itself stays a safe join key.
    by_espn_name = {
        t["espn"].casefold(): t["code"] for t in json.loads(TEAMS_FILE.read_text())["teams"]
    }
    # Counterintuitive but verified: ESPN 403s browser User-Agents coming from
    # non-browser TLS stacks, while the honest default Python-urllib UA passes.
    # Do NOT add a browser UA here. Any failed month raises, so a partial
    # sweep never overwrites the snapshot.
    events = []
    for month in SEASON_MONTHS:
        req = urllib.request.Request(URL.format(month=month))
        events += json.loads(urllib.request.urlopen(req, timeout=30).read()).get("events", [])
    events = list({ev["id"]: ev for ev in events}.values())  # month overlap safety

    matches, unresolved = [], set()
    for ev in events:
        comp = ev["competitions"][0]
        sides = {}
        for c in comp["competitors"]:
            name = c["team"].get("displayName")
            code = by_espn_name.get((name or "").casefold())
            if not code:
                unresolved.add(name)
                continue
            sides[c["homeAway"]] = {
                "code": code,
                "score": int(c["score"]) if c.get("score") not in (None, "") else None,
                "shootout": c.get("shootoutScore"),
                "winner": bool(c.get("winner")),
            }
        if len(sides) != 2:
            continue
        st = ev.get("status", {}).get("type", {})
        ts = int(datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).timestamp() * 1000)
        m = {
            "id": ev["id"],
            "ts": ts,
            "round": (ev.get("season") or {}).get("slug") or "league-phase",
            "md": None,
            "home": sides["home"]["code"],
            "away": sides["away"]["code"],
            "hs": sides["home"]["score"],
            "as": sides["away"]["score"],
            "hso": sides["home"]["shootout"],
            "aso": sides["away"]["shootout"],
            "state": st.get("state", "pre"),          # pre | in | post
            "completed": bool(st.get("completed")),
        }
        matches.append(m)

    if unresolved:
        sys.exit(f"unresolved ESPN team names (add to data/teams.json): {sorted(unresolved)}")
    if len(matches) < 100:
        sys.exit(f"only {len(matches)} matches from ESPN — refusing to overwrite snapshot")

    # Matchday for the league phase: cluster kickoff dates — a new matchday
    # starts whenever >3 days separate consecutive match dates.
    lg = sorted((m for m in matches if m["round"] == "league-phase"), key=lambda m: m["ts"])
    md, prev_ts = 0, None
    for m in lg:
        if prev_ts is None or m["ts"] - prev_ts > 3 * 86400_000:
            md += 1
        m["md"] = md
        prev_ts = m["ts"]
    if md not in (0, 8):
        print(f"warning: derived {md} league matchdays (expected 8)", file=sys.stderr)

    matches.sort(key=lambda m: m["ts"])
    out = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "count": len(matches),
        "matches": matches,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n")
    rounds = {}
    for m in matches:
        rounds[m["round"]] = rounds.get(m["round"], 0) + 1
    print(f"wrote {len(matches)} matches -> {OUT.name} · rounds: {rounds} · matchdays: {md}")


if __name__ == "__main__":
    main()
