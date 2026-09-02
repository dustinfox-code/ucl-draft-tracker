# UCL 2026-27 Draft League — Draft Board + Live Tracker

Draft-night decision engine and season-long live tracker for a 6-manager
Champions League team draft (6 clubs each, all 36 league-phase clubs drafted).
Port of [wc-draft-tracker](https://github.com/dustinfox-code/wc-draft-tracker)
to the UCL's Swiss format, with the Opta supercomputer replacing Silver
Bulletin as the prediction engine.

## League scoring

| Milestone | Points |
|---|---|
| League-phase win / draw (8 games) | 1.5 / 0.5 (= half of real table points) |
| Top-8 league-phase finish (knockout bye) | 6 |
| Each knockout-round win (tie, not leg) | 5 |
| Knockout play-off win (Feb, seeds 9–24) | 5 (commissioner-confirmed 2026-09-02) |
| Winning the final | 10 (5 win + 5 champion bonus) |

Knockout points go to the winner of the **tie** — two-legged everywhere except
the final, decided on aggregate — never to individual legs. The play-off-win
value lives in the `PLAYOFF_WIN_PTS` constant near the top of both
`draft.html` and `index.html` (kept in sync). League fantasy points are
exactly half the real table points, so totals land on halves (a formatter
handles `13.5`).

## What's here

- **`draft.html`** — the draft board / simulator. Team values come verbatim
  from the **Opta supercomputer** (see below): expected league points,
  P(top 8), P(reach each knockout round), P(champion), and the full
  league-points distribution per club. The board shows EV under league
  scoring, floor/ceiling percentiles, VORP against the projected survivor at
  your next pick, availability tags from an adaptive opponent model (blend of
  Opta-EV rank and UEFA-coefficient rank — the coefficient is also the
  autodraft order), and an advisory P(win league) Monte Carlo per candidate.
  Boots from an embedded snapshot (draft night never depends on a fetch),
  upgrades itself from `data/opta.json` when fresher.
  **TODO after the draft-order lottery:** set `MANAGERS` order + `YOU` in
  `draft.html`.
- **`index.html`** — the live tracker: manager standings with banked +
  projected totals, next-match hero/nowbar/watch list, the 36-row league
  phase table (top-8 / play-off / eliminated bands, pts → GD → GF), match
  tabs, and Sofascore deep links. Live scores overlay from ESPN's public
  scoreboard (30 s poll), joined to the bundled schedule **by ESPN event id**.
  **TODO after draft night:** fill `ROSTERS` in `index.html`, then freeze the
  draft-day baseline: `cp data/opta.json data/pre-draft.json` (the "vs draft"
  column compares against it).
- **`data/opta.json`** — harvested Opta probabilities (see below).
- **`data/fixtures.json`** — ESPN schedule/results snapshot (fallback when
  ESPN is unreachable at view time; the live overlay upserts on top).
- **`data/teams.json`** — the club identity crosswalk: internal 3-letter code
  ↔ Opta contestantId ↔ ESPN displayName ↔ UEFA coefficient rank. The name
  maps in `index.html`, `draft.html`, and `scripts/harvest-sofascore.py`
  mirror it — update all of them if a club identity ever changes.
- **`data/sofascore.json`** — `{fixture → Sofascore match URL}` behind the ↗
  links.
- **`.github/workflows/harvest.yml`** — nightly Action: re-harvests Opta +
  ESPN, re-embeds the draft-board snapshot, commits on diff.

## The prediction engine (replaces Silver Bulletin)

The Analyst's UCL predictions page is powered by a Stats Perform feed that
carries everything the old Datawrapper harvest carried, updated daily
(~06:30 UTC):

```
https://api.performfeeds.com/soccerdata/seasonandtournamentsimulations/1mjq6w6ezkxe611ykkj8rgz7f1?tmcl=99jev9kv55deht65t6myggxlg&_fmt=jsonp&_rt=c&_clbk=TM18
```

- The outlet key is theanalyst.com's own public embedded key (find it in
  `wp-content/plugins/the-analyst-sdapi/build/blocks/soccer/league-tables/view.js`
  if it ever rotates).
- `tmcl` = tournamentCalendar id (UCL 2026/27). Other seasons:
  `python3 scripts/harvest-opta.py --list-seasons`.
- **Referer-gated**: 403 without `Referer: https://theanalyst.com/`, so it
  must be harvested server-side — the page reads the committed
  `data/opta.json` instead (fallback chain: fresh fetch → localStorage →
  pre-draft baseline).
- Per team: `avgPts` (expected table points), points + rank distributions,
  P(top 8) / P(9–24), and per-stage reach probabilities + P(champion)
  (champion column sums to 100%). Resolved rounds go to 0/100% during the
  season, so the projection formula stays exact all year:

  `EV = avgPts/2 + 6·top8 + PLAYOFF_WIN_PTS·(r16−top8) + 5·(qf+sf+fin+champ) + 5·champ`

Refresh manually with `python3 scripts/harvest-opta.py && python3
scripts/build-draft-snapshot.py` (stdlib only). Both harvesters refuse to
overwrite a good snapshot with a broken response.

## Live results feeds

ESPN's keyless scoreboard is the primary source (there is no openfootball
2026-27 UCL feed): `site.api.espn.com/.../soccer/uefa.champions/scoreboard`.
Gotcha, verified: **ESPN 403s browser User-Agents sent from non-browser TLS
stacks** — `scripts/harvest-fixtures.py` deliberately sends no UA. Join ESPN
teams by `displayName`, never abbreviation (ESPN's "MUN" is Bayern Munich).

Two-legged ties (play-off, R16, QF, SF) are paired by round + team pair and
decided on aggregate, then the deciding leg's shootout (no away-goals rule).
The Final is single-leg.

## Updating the Sofascore links

Same TLS-fingerprint situation as the WC repo — plain Node/curl get 403'd, so
the harvester uses `curl_cffi` (`pip install curl_cffi`, or a venv):

```sh
python3 scripts/harvest-sofascore.py   # rewrites data/sofascore.json
```

UCL is `unique-tournament 7`, season `96518` (2026/27). The Sofascore
"season" also contains the July/August **qualifying rounds** (81 clubs!), so
events before Sept 1 are filtered out. Club nameCodes collide in the wider
feed (VIK = Viking *and* Víkingur Reykjavík; SHA = Shakhtar *and* Shamrock
Rovers) — resolution is by full name first. Placeholder detection is narrow
because club names legitimately contain slashes (Bodø/Glimt).

**Re-run after the knockout play-off draw** (the KO cup tree doesn't exist on
Sofascore until then) — undrawn slots are stored as stable
`/event/{id}` URLs, the lesson learned in the WC repo when placeholder slugs
died on draw day.

## Tests

```sh
node scripts/test-calibration.mjs   # sim core reproduces every Opta marginal (200k sims)
node scripts/test-scoring.mjs       # scoring engine fixtures + headless boot/render smoke test
```

Run both before committing changes to either HTML file.

## v2 features

- **Knockout bracket panel**: tie-level columns (play-offs → final) with
  aggregate scores, per-leg results, deciding-leg shootouts as superscripts,
  live cells, owner chips, and Sofascore links. Ties appear as they're drawn;
  undrawn slots render as dashed TBD cells, so the bracket fills in round by
  round with no code changes.
- **Clinch / elimination detection** (league phase): conservative,
  points-only bounds — a rival "can still catch" a team when its
  3-per-game ceiling reaches the team's current points (ties count as
  caught), and a team is "passed" only by rivals already above its ceiling.
  Sound by construction: can fire a matchday late, never wrongly. (Exact
  Swiss-table clinching with 3/1/0 points is NP-hard — Kern & Paulusma — so
  exactness isn't on the table.) Drives: the gold **unconfirmed +6** badge
  for clinched top-8 finishes, 🔒/✓/✕ markers in the league table, and
  tighter "max possible" bounds (elim-from-top-8 teams drop to the play-off
  route; out teams to zero).
- **Same-tie collision handling** in "Max possible total": two roster clubs
  meeting in an undecided tie count once, not twice. Remaining looseness:
  undrawn future rounds are capped only by the one-champion rule (an exact
  seeded-tree DP would need the published bracket; the WC repo's
  `maxKOsubtree` is the template if that itch needs scratching in February).
