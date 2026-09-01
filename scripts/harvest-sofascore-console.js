// ============================================================================
// Sofascore harvester — BROWSER CONSOLE version (the reliable one).
//
// Sofascore's Cloudflare blocks non-browser TLS fingerprints, so Node's fetch
// gets 403'd even from a residential IP. Running here instead works because the
// request is same-origin and rides your real browser session that already
// cleared Cloudflare — the exact same call the site makes itself.
//
// HOW TO RUN
//   1. Open https://www.sofascore.com in your browser (any page on the site).
//   2. Open DevTools → Console (Cmd-Opt-J on Chrome, Cmd-Opt-C on Safari after
//      enabling the Develop menu). If it warns about pasting, type "allow
//      pasting" and press Enter, then paste.
//   3. Paste this whole file and press Enter. It downloads sofascore.json
//      (also copies it to your clipboard).
//   4. Move that file to data/sofascore.json in the repo, commit, push.
//
// Re-run after each knockout round's draw resolves to pick up new fixtures.
//
// SOURCE: the per-date /api/v1/sport/football/scheduled-events/{date} endpoint
// was retired by Sofascore (it now 404s for every date). We read the World Cup
// season directly instead:
//   /api/v1/unique-tournament/16/season/58210/events/{last|next}/{page}
// 16 = FIFA World Cup (men), 58210 = the 2026 season. "last" = played/live,
// "next" = upcoming; page each from 0 until a 404, then merge. If Sofascore
// ever re-IDs the season, get the new id from
//   /api/v1/unique-tournament/16/seasons
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
  // Knockout slots are seeded before teams are known ("2A", "1C", "3A/3B…", "G1");
  // skip them quietly instead of flagging them as unresolved real countries.
  const isPlaceholder = n => !n || /[0-9/]/.test(n);

  // Page an events feed ("last" = played/live, "next" = upcoming) until a 404,
  // which is how Sofascore signals "no more pages".
  async function fetchFeed(kind){
    const out = [];
    for(let page = 0; page < 50; page++){            // guard: WC is ~104 matches
      const r = await fetch(`/api/v1/unique-tournament/${UT_ID}/season/${SEASON_ID}/events/${kind}/${page}`, { headers: { accept: "application/json" } });
      if(r.status === 404) break;                    // paged past the last page
      if(!r.ok){ console.warn(kind, "page", page, "HTTP", r.status); break; }
      const evs = (await r.json()).events || [];
      if(!evs.length) break;
      out.push(...evs);
      await new Promise(r => setTimeout(r, 150));     // be polite
    }
    return out;
  }

  const byId = new Map(), unresolved = new Set();
  let scanned = 0;
  for(const kind of ["last", "next"]){
    let evs = [];
    try{ evs = await fetchFeed(kind); }
    catch(err){ console.warn(kind, err.message); }
    scanned += evs.length;
    for(const e of evs){
      const c1 = code(e.homeTeam), c2 = code(e.awayTeam);
      if(!c1 && !isPlaceholder(e.homeTeam?.name)) unresolved.add(`${e.homeTeam?.name} [${e.homeTeam?.nameCode}]`);
      if(!c2 && !isPlaceholder(e.awayTeam?.name)) unresolved.add(`${e.awayTeam?.name} [${e.awayTeam?.nameCode}]`);
      if(!c1 || !c2 || !e.customId || !e.slug) continue;
      byId.set(e.customId, {                          // dedupe if a match is in both feeds
        c: [c1, c2],
        ts: e.startTimestamp * 1000,
        url: `https://www.sofascore.com/football/match/${e.slug}/${e.customId}`,
      });
    }
  }

  const events = [...byId.values()].sort((a, b) => a.ts - b.ts);
  const json = JSON.stringify({ generated: new Date().toISOString(), count: events.length, events }, null, 2) + "\n";
  console.log(`%c✓ ${events.length} World Cup matches`, "color:#56d364;font-weight:bold", `(scanned ${scanned} events)`);
  if(unresolved.size) console.warn("⚠ unresolved teams (add to NAME_TO_CODE / CODE_ALIAS, then re-run):", [...unresolved]);
  if(!events.length) console.warn("No matches found — if you saw HTTP 403, run this ON www.sofascore.com; if every page 404'd, the season id may have changed (check /api/v1/unique-tournament/16/seasons).");

  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([json], { type: "application/json" }));
  a.download = "sofascore.json";
  document.body.appendChild(a); a.click(); a.remove();
  try{ copy(json); console.log("(also copied to clipboard — paste into data/sofascore.json)"); }catch{}
})();
