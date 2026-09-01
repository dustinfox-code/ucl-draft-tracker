// ============================================================================
// Sofascore COMPLETE harvester — BROWSER CONSOLE version.
//
// Grabs the WHOLE tournament in one run, including knockout rounds whose teams
// aren't decided yet (R16/QF/SF/Final). Those fixtures already exist on
// Sofascore as placeholder slots ("w98-w97", "w75-canada") — but a slot's slug
// AND customId are both derived from the two teams, so when its real teams
// resolve Sofascore mints a NEW slug + customId and the old placeholder URL
// 404s (verified 2026-07-06: every pre-harvested R16 placeholder link died
// once the R32 winners were drawn in). So undrawn slots are emitted as
// /event/{numeric id} instead — the numeric event id survives the draw (same
// pre-created event) and /event/{id} redirects to the canonical match page
// whatever it currently is. Resolved matches get their direct (stable) URL.
//
// HOW THE PAGE USES IT: index.html matches group games by team code + kickoff,
// and knockout games by KICKOFF TIME (unique per slot — verified no two
// knockout fixtures are within 3.5h of each other, and Sofascore's times match
// the feed exactly).
//
// SOURCES (the per-date /scheduled-events/{date} endpoint was retired — 404):
//   • group + already-resolved games: the season feed
//       /api/v1/unique-tournament/16/season/58210/events/{last,next}/{page}
//   • EVERY knockout slot (incl. undecided ones): the cup tree + per-event fetch
//       /api/v1/unique-tournament/16/season/58210/cuptrees   → numeric event ids
//       /api/v1/event/{id}                                    → customId, slug, teams
//   16 = FIFA World Cup (men), 58210 = the 2026 season. New season id (if ever):
//   /api/v1/unique-tournament/16/seasons
//
// HOW TO RUN: open www.sofascore.com, DevTools console, "allow pasting" if
// prompted, paste this whole file, Enter. Downloads sofascore.json (drop-in for
// data/sofascore.json) and copies it to the clipboard.
// ============================================================================
(async () => {
  const UT_ID = 16, SEASON_ID = 58210;

  const KNOWN = new Set(
    "ARG ESP ENG FRA BRA GER POR MEX COL BEL NED NOR SUI CAN TUR ECU URU USA CRO JPN MAR SEN PAR AUT EGY SCO CZE KOR BIH IRN CIV SWE ALG PAN AUS COD RSA UZB NZL TUN KSA CPV GHA JOR HAI IRQ QAT CUW".split(" ")
  );
  const NAME_TO_CODE = {
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
  };
  const CODE_ALIAS = {}; // fill if it warns about an unresolved nameCode, e.g. "DRC":"COD"

  const code = t => {
    if(!t) return null;
    const nc = t.nameCode;
    if(nc && CODE_ALIAS[nc]) return CODE_ALIAS[nc];
    if(nc && KNOWN.has(nc)) return nc;
    return (t.name && NAME_TO_CODE[t.name]) || null;
  };
  // Placeholder bracket slots before teams are known ("2A", "w74", "L77", "3A/3B").
  const isPlaceholder = n => !n || /[0-9/]/.test(n);
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  const byId = new Map();          // customId → {c, ts, url}; keep the most-resolved version
  const unresolved = new Set();
  // Fold a Sofascore event object into byId. c = the resolved codes (0, 1 or 2 of
  // them); a placeholder slot just has fewer — kickoff time carries the match.
  const consider = e => {
    if(!e || !e.id || !e.customId || !e.slug || !e.startTimestamp) return;
    const c1 = code(e.homeTeam), c2 = code(e.awayTeam);
    if(!c1 && !isPlaceholder(e.homeTeam?.name)) unresolved.add(`${e.homeTeam?.name} [${e.homeTeam?.nameCode}]`);
    if(!c2 && !isPlaceholder(e.awayTeam?.name)) unresolved.add(`${e.awayTeam?.name} [${e.awayTeam?.nameCode}]`);
    const c = [c1, c2].filter(Boolean);
    const entry = {
      c,
      ts: e.startTimestamp * 1000,
      // Undrawn slot → /event/{id}: survives the draw. Resolved → direct URL.
      url: c.length === 2
        ? `https://www.sofascore.com/football/match/${e.slug}/${e.customId}`
        : `https://www.sofascore.com/event/${e.id}`,
    };
    const prev = byId.get(e.id);
    if(!prev || entry.c.length > prev.c.length) byId.set(e.id, entry);
  };

  // ---- A) season feed: group + already-resolved games ------------------------
  async function fetchFeed(kind){
    const out = [];
    for(let page = 0; page < 50; page++){
      const r = await fetch(`/api/v1/unique-tournament/${UT_ID}/season/${SEASON_ID}/events/${kind}/${page}`, { headers: { accept: "application/json" } });
      if(r.status === 404) break;
      if(!r.ok){ console.warn(kind, "page", page, "HTTP", r.status); break; }
      const evs = (await r.json()).events || [];
      if(!evs.length) break;
      out.push(...evs);
      await sleep(150);
    }
    return out;
  }
  let feedCount = 0;
  for(const kind of ["last", "next"]){
    let evs = [];
    try{ evs = await fetchFeed(kind); }catch(err){ console.warn(kind, err.message); }
    feedCount += evs.length;
    evs.forEach(consider);
  }
  console.log(`feed: scanned ${feedCount} events`);

  // ---- B) cup tree: EVERY knockout slot, incl. undecided ones ----------------
  let bracketIds = new Set();
  try{
    const ctRes = await fetch(`/api/v1/unique-tournament/${UT_ID}/season/${SEASON_ID}/cuptrees`, { headers: { accept: "application/json" } });
    if(!ctRes.ok){ console.warn("cuptrees HTTP", ctRes.status, "— knockout slots may be incomplete"); }
    else{
      const trees = await ctRes.json();
      (function walk(o){
        if(Array.isArray(o)){ o.forEach(walk); return; }
        if(o && typeof o === "object"){
          if(Array.isArray(o.events)) for(const x of o.events) if(Number.isInteger(x)) bracketIds.add(x);
          for(const k in o) walk(o[k]);
        }
      })(trees);
      if(!bracketIds.size){
        console.warn("No event ids found in cuptrees — shape may differ. Top-level keys:", Object.keys(trees));
        console.warn("Paste this back to fix the walk:", JSON.stringify(trees).slice(0, 800));
      }
    }
  }catch(err){ console.warn("cuptrees", err.message); }
  console.log(`bracket: ${bracketIds.size} event ids referenced`);

  let fetched = 0, failed = 0;
  for(const id of bracketIds){
    try{
      const r = await fetch(`/api/v1/event/${id}`, { headers: { accept: "application/json" } });
      if(!r.ok){ failed++; console.warn("event", id, "HTTP", r.status); await sleep(150); continue; }
      consider((await r.json()).event);
      fetched++;
    }catch(err){ failed++; console.warn("event", id, err.message); }
    await sleep(150);
  }

  // ---- output ----------------------------------------------------------------
  const events = [...byId.values()].sort((a, b) => a.ts - b.ts);
  const ko = events.filter(e => e.c.length < 2).length;
  const json = JSON.stringify({ generated: new Date().toISOString(), count: events.length, events }, null, 2) + "\n";
  console.log(`%c✓ ${events.length} matches → sofascore.json`, "color:#56d364;font-weight:bold",
              `(bracket: fetched ${fetched}, ${failed} failed; ${ko} still-placeholder knockout slots included)`);
  if(unresolved.size) console.warn("⚠ unresolved real teams (add to NAME_TO_CODE / CODE_ALIAS, then re-run):", [...unresolved]);
  if(!events.length) console.warn("No matches found — run this ON www.sofascore.com. If every request 404'd, the season id may have changed (check /api/v1/unique-tournament/16/seasons).");

  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([json], { type: "application/json" }));
  a.download = "sofascore.json";
  document.body.appendChild(a); a.click(); a.remove();
  try{ copy(json); console.log("(also copied to clipboard — drop into data/sofascore.json)"); }catch{}
})();
