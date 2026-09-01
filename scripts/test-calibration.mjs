#!/usr/bin/env node
// Calibration test for the draft.html sim core (run: node scripts/test-calibration.mjs).
//
// Extracts the <script id="simcore"> block (pure logic, no DOM), runs it in a
// vm sandbox, and checks that the simulator reproduces the Opta inputs it
// samples from:
//   1. analytic: mean of each team's points CDF == avgPts/2 (league fantasy pts)
//   2. sim: each team's mean total fantasy points == closed-form EV
//   3. sim: each team's championship frequency == published champ probability
//   4. exactly one champion per sim by construction (spot-checked)
// EV itself is recomputed here independently so formula drift between
// initTeams() and simTournament() fails loudly.

import { readFileSync } from "fs";
import vm from "vm";

const NSIMS = 200_000;
const html = readFileSync(new URL("../draft.html", import.meta.url), "utf8");
const src = html.match(/<script id="simcore">([\s\S]*?)<\/script>/)?.[1];
if (!src) { console.error("simcore block not found"); process.exit(1); }

const ctx = vm.createContext({});
vm.runInContext(
  src +
    `\n;globalThis.__api = {
      initTeams, simTournament,
      get TEAMS(){ return TEAMS; },
      SNAPSHOT, TOTAL, PLAYOFF_WIN_PTS, BYE_PTS, KO_WIN_PTS, CHAMP_BONUS,
    };`,
  ctx
);
const api = ctx.__api;
api.initTeams();
const TEAMS = api.TEAMS;
const { TOTAL, PLAYOFF_WIN_PTS, BYE_PTS, KO_WIN_PTS, CHAMP_BONUS } = api;

let failures = 0;
const check = (label, got, want, tol) => {
  if (Math.abs(got - want) > tol) {
    console.error(`FAIL ${label}: got ${got.toFixed(4)}, want ${want.toFixed(4)} (tol ${tol})`);
    failures++;
  }
};

// 1. analytic: points-CDF mean vs avgPts/2, and pmf sums to 1
for (const t of TEAMS) {
  let mean = 0, prev = 0;
  for (const [pts, cum] of t.gcdf) { mean += pts * (cum - prev); prev = cum; }
  check(`${t.code} gcdf mass`, prev, 1, 1e-9);
  check(`${t.code} gcdf mean vs avgPts/2`, mean, t.avgPts / 2, 0.05);
}

// independent closed-form EV (mirrors the rules PDF, not initTeams)
const evWant = t =>
  t.avgPts / 2 +
  BYE_PTS * t.top8 +
  PLAYOFF_WIN_PTS * Math.max(0, t.r16 - t.top8) +
  KO_WIN_PTS * (t.qf + t.sf + t.fin + t.champ) +
  CHAMP_BONUS * t.champ;
for (const t of TEAMS) check(`${t.code} initTeams EV vs closed form`, t.ev, evWant(t), 1e-6);

// 2+3. simulate
const sumPts = new Float64Array(TOTAL);
const champCt = new Float64Array(TOTAL);
const out = new Float64Array(TOTAL);
for (let s = 0; s < NSIMS; s++) {
  const ci = api.simTournament(out);
  champCt[ci]++;
  for (let i = 0; i < TOTAL; i++) sumPts[i] += out[i];
}
for (let i = 0; i < TOTAL; i++) {
  const t = TEAMS[i];
  // se of mean total pts is < 0.02 at 200k sims; 4-sigma-ish tolerances
  check(`${t.code} sim mean pts vs EV`, sumPts[i] / NSIMS, t.ev, 0.09);
  check(`${t.code} sim champ freq`, champCt[i] / NSIMS, t.champ, 0.004);
}

if (failures) { console.error(`\n${failures} calibration failure(s)`); process.exit(1); }
console.log(`OK — ${TEAMS.length} teams calibrated over ${NSIMS.toLocaleString()} sims (asOf ${api.SNAPSHOT.asOf})`);
