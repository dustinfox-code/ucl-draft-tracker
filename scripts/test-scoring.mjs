#!/usr/bin/env node
// Scoring-engine tests for index.html (run: node scripts/test-scoring.mjs).
//
// Loads the page's script in a vm sandbox with DOM/fetch/localStorage stubs —
// which smoke-tests boot + render() on empty data — then feeds synthetic
// fixtures through computeTies / computeScores / maxPointsLeft:
//   league halves (win 1.5 / draw 0.5), table order pts→GD→GF, top-8 bye
//   banking only when all 36 have played 8, two-leg aggregates incl. a
//   deciding-leg shootout, the PLAYOFF_WIN_PTS flag, Final = 10 + champion,
//   and the optimistic max-points bound.

import { readFileSync } from "fs";
import vm from "vm";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const src = html.match(/<script>([\s\S]*)<\/script>/)?.[1];
if (!src) { console.error("script block not found"); process.exit(1); }

// --- headless DOM/browser stubs ---------------------------------------------
const elem = () => {
  const listNode = { innerHTML: "", value: "", className: "", style: {}, dataset: {},
    options: [], classList: { add(){}, remove(){}, toggle(){} },
    addEventListener(){}, };
  return listNode;
};
const elements = {};
const documentStub = {
  getElementById: id => (elements[id] = elements[id] || elem()),
  querySelector: () => elem(),
  querySelectorAll: () => [],
  addEventListener(){},
  createElement: () => elem(),
  head: { appendChild(){} },
  body: { style: {} },
  hidden: true,
};
const ctx = vm.createContext({
  document: documentStub,
  localStorage: { getItem: () => null, setItem(){}, removeItem(){} },
  fetch: () => Promise.reject(new Error("offline test")),
  setInterval(){}, setTimeout: (f) => { /* don't run timers */ },
  console,
});
vm.runInContext(src + `
;globalThis.__api = { computeTies, computeScores, maxPointsLeft, koMeta, TEAMS, ROSTERS,
  PLAYOFF_WIN_PTS, BYE_PTS, KO_WIN_PTS, CHAMP_BONUS, LEAGUE_ROUND };`, ctx);
const A = ctx.__api;

let failures = 0;
const eq = (label, got, want) => {
  const ok = typeof want === "number" ? Math.abs(got - want) < 1e-9 : got === want;
  if (!ok) { console.error(`FAIL ${label}: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`); failures++; }
};

let nextId = 1;
const M = (round, home, away, hs, as, opts = {}) => ({
  id: String(nextId++), ts: opts.ts ?? Date.parse("2026-09-08T18:00Z") + nextId * 3600_000,
  round, md: opts.md ?? null, home, away, hs, as,
  hso: opts.hso ?? null, aso: opts.aso ?? null,
  state: "post", completed: true,
});

// --- 1. league halves + table order -----------------------------------------
{
  const ms = [
    M(A.LEAGUE_ROUND, "ARS", "BAY", 2, 0, { md: 1 }), // ARS 3 real pts → 1.5 fantasy
    M(A.LEAGUE_ROUND, "RMA", "PSG", 1, 1, { md: 1 }), // draw → 0.5 each
  ];
  const S = A.computeScores(ms, []);
  eq("ARS fantasy 1.5", S.T.ARS.pts, 1.5);
  eq("BAY fantasy 0",   S.T.BAY.pts, 0);
  eq("RMA fantasy 0.5", S.T.RMA.pts, 0.5);
  eq("no bye before league done", S.T.ARS.top8, false);
  eq("league not done", S.leagueDone, false);
  // table order: pts desc, then GD, then GF
  eq("table leader", S.table[0].code, "ARS");
}

// --- 2. full league phase → top-8 bye banks ----------------------------------
{
  // synthetic full schedule: 8 matchdays, pair team i with team (i+md) mod 36;
  // each pairing counted once per md ⇒ everyone plays exactly 8.
  const codes = A.TEAMS.map(t => t.code);
  const ms = [];
  for (let md = 1; md <= 8; md++) {
    const used = new Set();
    for (let i = 0; i < 36 && used.size < 36; i++) {
      if (used.has(i)) continue;
      let j = (i + md) % 36;
      while (used.has(j) || j === i) j = (j + 1) % 36;
      used.add(i); used.add(j);
      // low-index team always wins 2-0 → final table ≈ index order
      ms.push(M(A.LEAGUE_ROUND, codes[Math.min(i,j)], codes[Math.max(i,j)],
        codes[Math.min(i,j)] === codes[i] && i < j ? 2 : 2, 0, { md }));
    }
  }
  const S = A.computeScores(ms, []);
  eq("full league done", S.leagueDone, true);
  eq("everyone played 8", S.table.every(t => t.gp === 8), true);
  const top8 = S.table.slice(0, 8);
  eq("top-8 all get bye", top8.every(t => t.top8), true);
  eq("9th gets no bye", S.table[8].top8, false);
  eq("24th (last playoff spot) not out", S.table[23].out, false);
  eq("25th is out", S.table[24].out, true);
  eq("pos numbering", S.table[24].pos, 25);
  const leader = S.table[0];
  eq("leader banked = lg/2 + 6", S.T[leader.code].pts, leader.realPts / 2 + A.BYE_PTS);
}

// --- 3. two-leg tie: aggregate, deciding-leg pens, playoff flag --------------
{
  const t0 = Date.parse("2027-02-17T20:00Z");
  const ms = [
    // playoff tie: leg1 BET home beats VIK 1-0; leg2 VIK home wins 1-0; pens 4-2 to VIK
    M("knockout-round-playoffs", "BET", "VIK", 1, 0, { ts: t0 }),
    M("knockout-round-playoffs", "VIK", "BET", 1, 0, { ts: t0 + 7 * 86400_000, hso: 4, aso: 2 }),
    // R16 tie decided on aggregate
    M("round-of-16", "ARS", "PSG", 0, 2, { ts: t0 + 20 * 86400_000 }),
    M("round-of-16", "PSG", "ARS", 1, 1, { ts: t0 + 27 * 86400_000 }),
    // Final (single leg)
    M("final", "PSG", "BAY", 1, 0, { ts: t0 + 100 * 86400_000 }),
  ];
  const ties = A.computeTies(ms);
  eq("three ties", ties.length, 3);
  const po = ties.find(t => t.km.key === "po");
  eq("po decided on pens", po.winner, "VIK");
  const r16 = ties.find(t => t.km.key === "r16");
  eq("r16 aggregate winner", r16.winner, "PSG");
  const S = A.computeScores(ms, ties);
  eq("VIK playoff points", S.T.VIK.koPts, A.PLAYOFF_WIN_PTS);
  eq("PSG = R16 win + Final 10", S.T.PSG.koPts, A.KO_WIN_PTS + A.KO_WIN_PTS + A.CHAMP_BONUS);
  eq("PSG champion", S.T.PSG.champion, true);
  eq("BET out after losing tie", S.T.BET.out, true);
  eq("incomplete tie ignored", A.computeTies([ms[0]])[0].done, false);
}

// --- 4. optimistic max-points bound ------------------------------------------
{
  A.ROSTERS["Dustin Fox"].push("ARS", "BAY", "COM");
  const S = A.computeScores([], []); // season not started
  // per team: 8 games ×1.5 + bye 6 + R16/QF/SF wins 15 = 33; +10 once for a champion
  const want = 3 * (12 + A.BYE_PTS + 3 * A.KO_WIN_PTS) + (A.KO_WIN_PTS + A.CHAMP_BONUS);
  eq("pre-season max bound", A.maxPointsLeft("Dustin Fox", S, []), want);
  A.ROSTERS["Dustin Fox"].length = 0;
}

if (failures) { console.error(`\n${failures} scoring failure(s)`); process.exit(1); }
console.log("OK — scoring engine fixtures pass (boot + render smoke-tested with stubs)");
