#!/usr/bin/env python3
"""Harvest Opta (Stats Perform) UCL simulation probabilities -> data/opta.json.

The Analyst (theanalyst.com) renders its Champions League PREDICTED table from
a public Stats Perform feed. That feed is Referer-gated (403 without
`Referer: https://theanalyst.com/`), so the tracker can't fetch it from the
browser; this script pulls it server-side and commits a compact snapshot the
GitHub Pages site serves same-origin.

Per team the feed carries (all verified against the live 2026/27 season):
  - avgPts          expected league-phase table points (typeId 3)
  - pointsDistribution  P(final table points = k)      (typeId 4)
  - rankDistribution    P(final league position = k)   (typeId 5)
  - rankPrediction      P(top 8) ["8th Finals"] and P(9-24) ["Play-off"]
  - per-KO-stage reach probabilities (typeId 1 on each knockout stage) and
    P(champion) (typeId 2 on the Final stage); champion sums to 100%.

Usage:  python3 scripts/harvest-opta.py          # rewrites data/opta.json
        python3 scripts/harvest-opta.py --list-seasons   # print tmcl ids

Stdlib only. Exits non-zero (leaving the previous snapshot untouched) if the
response is missing teams or the champion column stops summing to ~100%.
"""

import json
import pathlib
import re
import sys
import urllib.request

OUTLET = "1mjq6w6ezkxe611ykkj8rgz7f1"  # theanalyst.com's public embedded key
COMP = "4oogyu6o156iphvdvphwpck10"     # UEFA Champions League competition id
TMCL = "99jev9kv55deht65t6myggxlg"     # tournamentCalendar id: UCL 2026/27
BASE = "https://api.performfeeds.com/soccerdata"
HEADERS = {
    "Referer": "https://theanalyst.com/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
}

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "opta.json"
TEAMS_FILE = ROOT / "data" / "teams.json"

# feed stage name -> opta.json field. "8th Finals" is Opta's name for the R16.
STAGE_FIELDS = {
    "Knockout Round Play-offs": "po_reach",
    "8th Finals": "r16",
    "Quarter-finals": "qf",
    "Semi-finals": "sf",
    "Final": "fin",
}


def jsonp(url: str):
    req = urllib.request.Request(url, headers=HEADERS)
    raw = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
    body = re.sub(r"^[^(]*\(", "", raw.strip())
    body = re.sub(r"\);?\s*$", "", body)
    return json.loads(body)


def pct(s: str) -> float:
    return round(float(s.rstrip("%")) / 100.0, 6)


def list_seasons() -> None:
    cal = jsonp(f"{BASE}/tournamentcalendar/{OUTLET}?comp={COMP}&_fmt=jsonp&_rt=c&_clbk=TC")
    for tc in cal["competition"][0]["tournamentCalendar"]:
        print(f"{tc['id']}  {tc['name']}  active={tc.get('active')}")


def main() -> None:
    if "--list-seasons" in sys.argv:
        list_seasons()
        return

    by_opta_id = {
        t["optaId"]: t["code"] for t in json.loads(TEAMS_FILE.read_text())["teams"]
    }

    feed = jsonp(
        f"{BASE}/seasonandtournamentsimulations/{OUTLET}"
        f"?tmcl={TMCL}&_fmt=jsonp&_rt=c&_clbk=TM18"
    )
    stages = feed["stages"]["stage"]
    league = stages[0]["division"][0]["ranking"]

    teams: dict[str, dict] = {}
    unresolved = []
    for row in league:
        code = by_opta_id.get(row["contestantId"])
        if not code:
            unresolved.append(f"{row['contestantName']} ({row['contestantId']})")
            continue
        pred = row["overallPredictions"][0]
        t: dict = {
            "name": row["contestantShortName"],
            # live actuals (0s pre-season; useful once matchdays bank results)
            "played": row.get("matchesPlayed", 0),
            "pts": row.get("points", 0),
            "avgPts": None,
            "ptsDist": [],
            "rankDist": [],
            "top8": 0.0,
            "po": 0.0,
        }
        for p in pred["predictions"]["predicted"]:
            if p["typeId"] == "3":
                t["avgPts"] = float(p["value"])
            elif p["typeId"] == "4":
                t["ptsDist"] = [[int(d["value"]), pct(d["probability"])] for d in p["distribution"]]
            elif p["typeId"] == "5":
                t["rankDist"] = [[int(d["value"]), pct(d["probability"])] for d in p["distribution"]]
        for rp in pred.get("rankPrediction", []):
            if rp["rankStatus"] == "8th Finals":
                t["top8"] = pct(rp["value"])
            elif rp["rankStatus"] == "Play-off":
                t["po"] = pct(rp["value"])
        teams[code] = t

    # knockout-stage reach + champion probabilities
    for stage in stages[1:]:
        field = STAGE_FIELDS.get(stage["name"])
        for c in stage.get("contestants", {}).get("contestant", []):
            code = by_opta_id.get(c["id"])
            if not code or code not in teams:
                continue
            for p in c["predictions"][0]["predicted"]:
                if p["typeId"] == "1" and field:
                    teams[code][field] = pct(p["value"])
                elif p["typeId"] == "2":
                    teams[code]["champ"] = pct(p["value"])

    # sanity gates: never commit a broken snapshot
    if unresolved:
        sys.exit(f"unresolved Opta teams (add to data/teams.json): {unresolved}")
    if len(teams) != 36:
        sys.exit(f"expected 36 teams, got {len(teams)}")
    champ_sum = sum(t.get("champ", 0) for t in teams.values())
    if not 0.97 <= champ_sum <= 1.03:
        sys.exit(f"champion probabilities sum to {champ_sum:.4f}, expected ~1.0")
    for code, t in teams.items():
        missing = [f for f in ("avgPts", "top8", "r16", "qf", "sf", "fin", "champ") if t.get(f) is None]
        if missing:
            sys.exit(f"{code} missing fields: {missing}")

    out = {
        "asOf": feed["lastUpdated"],
        "tmcl": TMCL,
        "source": "Opta supercomputer via theanalyst.com (Stats Perform seasonandtournamentsimulations)",
        "teams": teams,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"wrote {OUT} · asOf {out['asOf']} · {len(teams)} teams · champ sum {champ_sum:.4f}")


if __name__ == "__main__":
    main()
