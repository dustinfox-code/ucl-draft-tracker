#!/usr/bin/env python3
"""Embed the current data/opta.json into draft.html as the boot snapshot.

The draft board boots synchronously from an embedded `SNAPSHOT` literal (so
draft night never depends on a fetch) and then upgrades itself from
data/opta.json if that file is fresher. This script regenerates the literal
between the <SNAPSHOT:START>/<SNAPSHOT:END> markers. Run it after
harvest-opta.py whenever you want the embedded fallback refreshed:

    python3 scripts/harvest-opta.py && python3 scripts/build-draft-snapshot.py

Only the fields the draft board uses are embedded (rankDist and live actuals
are dropped to keep the page small).
"""

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DRAFT = ROOT / "draft.html"
OPTA = ROOT / "data" / "opta.json"

FIELDS = ("avgPts", "top8", "po", "r16", "qf", "sf", "fin", "champ", "ptsDist")


def main() -> None:
    opta = json.loads(OPTA.read_text())
    snap = {
        "asOf": opta["asOf"],
        "teams": {
            code: {f: t[f] for f in FIELDS}
            for code, t in opta["teams"].items()
        },
    }
    literal = json.dumps(snap, ensure_ascii=False, separators=(",", ":"))
    html = DRAFT.read_text()
    new_html, n = re.subn(
        r"(// <SNAPSHOT:START>[^\n]*\n)(?:.*?)(\n// <SNAPSHOT:END>)",
        lambda m: m.group(1) + "const SNAPSHOT = " + literal + ";" + m.group(2),
        html,
        flags=re.S,
    )
    if n != 1:
        sys.exit("SNAPSHOT markers not found in draft.html")
    DRAFT.write_text(new_html)
    print(f"embedded snapshot asOf {snap['asOf']} ({len(literal)//1024} KB) into draft.html")


if __name__ == "__main__":
    main()
