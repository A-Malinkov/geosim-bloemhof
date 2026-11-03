/* =============================================================================
 * modules/climate.js - Climate 2050: design resilience
 *
 * Long-term companion to the KNMI weather card (4.4) and the scenario comparison
 * (4.9). The weather card forecasts the next 1-24 h with our own models; this
 * card shows KNMI's OFFICIAL KNMI'23 climate scenarios, 30-year means for
 * 2036-2065 against 1991-2020, and what they mean for today, A, B and the final
 * design. Nothing here is produced by our AI, and nothing is a forecast of a day.
 *
 * Reads two static files, so no external API has to be up:
 *   data/processed/climate_knmi23.json      analysis/climate/fetch_knmi23.py
 *   data/processed/climate_resilience.json  analysis/climate/design_resilience.py
 *
 * The map is not recoloured by climate: the projections are regional and
 * uniform over the site, so a street-level "2050 temperature" map would be
 * invented. Instead the card switches on the existing layers that carry the
 * spatial part (sun hours, trees and planting, flood vulnerability).
 *
 * The helpers above setup() are pure and tested in tests/climate_app.test.mjs.
 * ========================================================================== */

export const CLIMATE_PATH = "../data/processed/climate_knmi23.json";
export const RESILIENCE_PATH = "../data/processed/climate_resilience.json";
export const DESIGNS = ["baseline", "scenario_a", "scenario_b", "final"];  //rows, in the app's order
export const THEMES = {
  temperature: { label: "Temperature", headline: { NLavg: "tmax_mean_summer", station: "summer_days" } },
  precipitation: { label: "Precipitation", headline: { NLavg: "p_hour_1y_summer", station: "p_mean_summer" } },
};
const LOC_NOTE = { NLavg: "national average", "De Bilt": "inland station, ~50 km", Vlissingen: "coastal station, ~80 km" };

/* ---------------------------------------------------------------- helpers */
export const nf = (v, d = 0) => v == null || Number.isNaN(v) ? "–"
  : Number(v).toLocaleString("en-GB", { minimumFractionDigits: d, maximumFractionDigits: d });
export const pct = (v, d = 0) => v == null ? "–" : `${nf(100 * v, d)} %`;

//digits that suit a unit and a size
export function digits(v, unit) {
  if (unit === "°C") return 1;
  if (unit === "days") return Math.abs(v) < 10 ? 1 : 0;
  if (unit === "mm") return Math.abs(v) < 100 ? 1 : 0;
  return 0;
}
export const fmtVal = (v, unit) => v == null ? "–" : `${nf(v, digits(v, unit))}${unit === "°C" ? " °C" : unit ? ` ${unit}` : ""}`;

//value of an indicator in a period: KNMI's change applied to the reference (absolute or percentage)
export function applyChange(ref, change, changeUnit) {
  if (ref == null || change == null) return null;
  return changeUnit === "%" ? ref * (1 + change / 100) : ref + change;
}

//one indicator in one period -> {value, change, changeUnit, range, band, withinNatVar}
export function valueFor(I, period, scen) {
  if (!I) return null;
  if (period === "reference") return { value: I.reference, change: null, range: null, band: null, withinNatVar: false };
  const c = I.scenarios?.[scen];
  if (!c || c.change == null) return null;
  const range = c.change_range ? c.change_range.map((x) => applyChange(I.reference, x, c.change_unit)) : null;
  return { value: applyChange(I.reference, c.change, c.change_unit), change: c.change, changeUnit: c.change_unit,
           changeRange: c.change_range, range, band: c.natural_variability_30y, withinNatVar: !!c.within_natural_variability };
}

//scenarios that have at least one number somewhere: the only ones offered
export function availableScenarios(clim) {
  if (!clim?.scenarios) return [];
  return Object.keys(clim.scenarios).filter((s) => Object.values(clim.locations || {}).some((L) =>
    Object.values(L.indicators || {}).some((I) => I.scenarios?.[s]?.change != null)));
}

//indicators of a theme at a location, in the file's order
export function indicatorsFor(clim, loc, theme) {
  const inds = clim?.locations?.[loc]?.indicators || {};
  return Object.entries(inds).filter(([, I]) => I.theme === theme && I.reference != null);
}

//locations with at least one indicator of the theme
export function availableLocations(clim, theme) {
  return Object.keys(clim?.locations || {}).filter((l) => indicatorsFor(clim, l, theme).length);
}

//indicator to chart when the theme or location changes
export function defaultIndicator(clim, loc, theme) {
  const list = indicatorsFor(clim, loc, theme).map(([k]) => k);
  const want = THEMES[theme]?.headline[loc === "NLavg" ? "NLavg" : "station"];
  return list.includes(want) ? want : list[0] ?? null;
}

//the scenario with the largest change of an indicator, for the "most extreme" hint
export function mostExtreme(I, scenarios) {
  let best = null;
  for (const s of scenarios) {
    const c = I?.scenarios?.[s]?.change;
    if (c != null && (best == null || Math.abs(c) > Math.abs(I.scenarios[best].change))) best = s;
  }
  return best;
}

//design-level values for the theme in a climate state, from climate_resilience.json
const STORM = "p_hour_1y_summer";
export function designRow(res, sc, scen) {
  const D = res?.designs?.[sc];
  if (!D) return null;
  const s = D.static, r = D.rain?.[STORM], h = D.heat_home_days?.tropical_days;
  return {
    id: sc, label: D.label, static: s,
    rainRef: r?.reference ?? null, rain: r?.scenarios?.[scen] ?? null,
    heatRef: h?.reference ?? null, heat: h?.scenarios?.[scen] ?? null,
  };
}

//best and worst design on one measure; ties keep the first
export function extremes(rows, get, better) {
  const vals = rows.map((r) => ({ r, v: get(r) })).filter((x) => x.v != null);
  if (vals.length < 2) return { best: null, worst: null };
  const sorted = [...vals].sort((a, b) => better === "higher" ? b.v - a.v : a.v - b.v);
  return { best: sorted[0], worst: sorted[sorted.length - 1] };
}

//measures each theme ranks designs on: getter, which way is better, and how to say best and worst
export const MEASURES = {
  temperature: [
    { get: (r) => r.static.canopy_share, better: "higher", best: "most crown cover", worst: "least crown cover" },
    { get: (r) => r.static.summer_shade_share, better: "higher", best: "most summer shade", worst: "least summer shade" },
    { get: (r) => r.static.green_per_home_m2, better: "higher", best: "most green per home", worst: "least green per home" },
    { get: (r) => r.heat?.[1], better: "lower", best: "fewest home-days ≥ 30 °C", worst: "most home-days ≥ 30 °C" },
    { get: (r) => r.static.winter_dark_share, better: "lower", best: "most winter daylight", worst: "least winter daylight" },
  ],
  precipitation: [  //storm runoff itself is left out: it follows sealed ground one to one
    { get: (r) => r.static.sealed_share, better: "lower", best: "least sealed ground", worst: "most sealed ground" },
    { get: (r) => r.rain?.depth_on_green_mm, better: "lower", best: "lightest load on green", worst: "heaviest load on green" },
    { get: (r) => r.rain?.extra_runoff_m3, better: "lower", best: "smallest 2050 increase", worst: "largest 2050 increase" },
  ],
};

//strengths and weaknesses of every design against the others -> {id: {plus: [], minus: []}}
export function implications(rows, theme) {
  const out = Object.fromEntries(rows.map((r) => [r.id, { plus: [], minus: [] }]));
  for (const m of MEASURES[theme] || []) {
    const { best, worst } = extremes(rows, m.get, m.better);
    if (!best || best.v === worst.v) continue;  //a tie says nothing
    out[best.r.id].plus.push(m.best);
    out[worst.r.id].minus.push(m.worst);
  }
  return out;
}

//"What does this mean for our design?": sentences built from the numbers, no adjectives the data cannot carry
export function narrative(clim, res, scen, theme) {
  const out = [];
  const sc = clim?.scenarios?.[scen];
  const rows = DESIGNS.map((d) => designRow(res, d, scen)).filter(Boolean);
  const plans = rows.filter((r) => r.id !== "baseline");
  if (!sc || plans.length < 2) return out;
  const name = (r) => r.label;
  const tag = `${scen} (${sc.label.toLowerCase()})`;
  if (theme === "temperature") {
    const H = res.hazards?.heat?.tropical_days?.stations || {}, S = res.hazards?.heat?.summer_days?.stations || {};
    const span = (st, k) => { const v = Object.values(st).map((x) => k === "ref" ? x.reference : x.scenarios[scen]);
      const lo = Math.min(...v), hi = Math.max(...v);
      return `${nf(lo, digits(lo, "days"))}–${nf(hi, digits(hi, "days"))}`; };
    if (Object.keys(S).length) out.push(`Under ${tag} the 30-year average of summer days (≥ 25 °C) goes from ${span(S, "ref")} to ` +
      `${span(S, "fut")} a year, tropical days (≥ 30 °C) from ${span(H, "ref")} to ${span(H, "fut")} ` +
      `(Vlissingen–De Bilt). The same for every design: the climate sets the size, the design sets the exposure.`);
    const can = extremes(plans, (r) => r.static.canopy_share, "higher");
    out.push(`Most crown cover: <b>${name(can.best.r)}</b> (${pct(can.best.v, 1)} of the site, ${nf(can.best.r.static.canopy_per_home_m2, 1)} m² per home), ` +
      `least: ${name(can.worst.r)} (${pct(can.worst.v, 1)}). Today: ${pct(res.designs.baseline?.static.canopy_share, 1)}. Proposed trees count at their modelled size.`);
    const sh = extremes(plans, (r) => r.static.summer_shade_share, "higher");
    out.push(`Most summer shade on open ground: <b>${name(sh.best.r)}</b> (${pct(sh.best.v, 1)} under 4 h of sun on 21 June), ` +
      `least: ${name(sh.worst.r)} (${pct(sh.worst.v, 1)}). That shade is cast by buildings and today's trees only: ` +
      `proposed trees are not in the sun model, so planted designs are understated.`);
    const ex = extremes(plans, (r) => r.heat?.[1], "lower");
    out.push(`Exposure grows with the number of homes: ${name(ex.worst.r)} has the most home-days ≥ 30 °C ` +
      `(${nf(ex.worst.r.heat[0])}–${nf(ex.worst.r.heat[1])} a year), ${name(ex.best.r)} the fewest ` +
      `(${nf(ex.best.r.heat[0])}–${nf(ex.best.r.heat[1])}). Density and heat exposure trade off; shade per home ` +
      `is ${plans.map((r) => `${nf(r.static.shade_per_home_m2, 1)} m² in ${name(r)}`).join(", ")}.`);
    const wd = extremes(plans, (r) => r.static.winter_dark_share, "lower");
    out.push(`Shade against daylight: ${name(wd.best.r)} keeps the most winter sun (${pct(wd.best.v)} of open ground under 2 h on 21 Dec, ` +
      `today ${pct(res.designs.baseline?.static.winter_dark_share)})` + (wd.best.r.id === sh.best.r.id ? ` and the most summer shade. `
        : ` but has ${pct(wd.best.r.static.summer_shade_share, 1)} summer shade, against ${pct(sh.best.v, 1)} in ${name(sh.best.r)}: ` +
          `the openness that lets winter sun in leaves summer ground exposed. `) +
      `Seasonal shade (deciduous trees, pergolas) over the sunniest open ground would serve both; the analysis does not say how many degrees it would cool.`);
  } else {
    const H = res.hazards?.rain?.[STORM];
    const h = H?.scenarios?.[scen];
    if (h) out.push(`Under ${tag} the hourly downpour exceeded once a year grows from ${nf(H.reference_mm, 1)} mm to ${nf(h.mm, 1)} mm ` +
      `(${h.change_pct > 0 ? "+" : ""}${nf(h.change_pct)} %` + (h.change_range_pct ? `, KNMI range ${nf(h.change_range_pct[0])}–${nf(h.change_range_pct[1])} %` : "") +
      `). National average: a 30-year statistic, not a storm on any given day.`);
    const se = extremes(plans, (r) => r.static.sealed_share, "lower");
    out.push(`Least sealed ground: <b>${name(se.best.r)}</b> (${pct(se.best.v)}), so the least runoff from that downpour, ` +
      `${nf(se.best.r.rain?.runoff_m3)} m³ in 2050; most sealed: ${name(se.worst.r)} (${pct(se.worst.v)}, ${nf(se.worst.r.rain?.runoff_m3)} m³). ` +
      `Today: ${pct(res.designs.baseline?.static.sealed_share)}.`);
    const gl = extremes(plans, (r) => r.rain?.depth_on_green_mm, "lower");
    out.push(`Led onto its green (rain gardens, wadis), the runoff would stand ${nf(gl.best.v)} mm deep in ${name(gl.best.r)} and ` +
      `${nf(gl.worst.v)} mm in ${name(gl.worst.r)}, if spread evenly: green next to the paving it drains is what SuDS needs.`);
    const ponds = plans.filter((r) => r.rain?.pond_rise_m != null);
    if (ponds.length) out.push(`The ${nf(ponds[0].static.water_m2)} m² pond would have to rise ` +
      `${nf(Math.min(...ponds.map((r) => r.rain.pond_rise_m)), 1)}–${nf(Math.max(...ponds.map((r) => r.rain.pond_rise_m)), 1)} m to hold it: ` +
      `on its own it cannot buffer the site, storage has to be spread over the green and permeable paving.`);
    const ext = extremes(plans, (r) => r.rain?.extra_runoff_m3, "lower");
    out.push(`2050 adds the same ${nf(h?.change_pct)} % to every design, so it does not reorder them; in volume it adds ` +
      `${nf(ext.best.v)} m³ in ${name(ext.best.r)} and ${nf(ext.worst.v)} m³ in ${name(ext.worst.r)}.`);
    const fl = res.flood_today?.high_or_very_high_share;
    if (fl != null) out.push(`Today ${pct(fl)} of the site's open ground is rated high or very high flood vulnerability (Cyrille, QGIS); ` +
      `not yet computed for the designs.`);
  }
  const leads = implications(plans, theme);
  const lead = plans.filter((r) => leads[r.id].plus.length);
  if (lead.length > 1) out.push(`No design leads on everything: ${lead.map((r) => `${name(r)}: ${leads[r.id].plus.join(", ")}`).join("; ")}.`);
  else if (lead.length === 1) out.push(`${name(lead[0])} leads on every ${theme === "temperature" ? "heat" : "rain"} measure here: ` +
    `${leads[lead[0].id].plus.join(", ")}.`);
  const homes = extremes(plans, (r) => r.static.dwellings, "lower");  //fewest and most homes among the designs
  const few = homes.best, today = res.designs.baseline?.static.dwellings;
  if (few && today && few.v < today) out.push(`Trade-off: ${name(few.r)} builds ${nf(few.v)} homes against ${nf(today)} today` +
    (theme === "temperature" ? `: part of its green per home and its low heat exposure comes from housing fewer people.`
      : `, ${name(homes.worst.r)} ${nf(homes.worst.v)} on ${pct(homes.worst.r.static.sealed_share)} sealed ground: less sealing came with fewer homes.`));
  return out;
}

/* -------------------------------------------------------------- the chart */
//horizontal bars: reference + every scenario, the KNMI range as a whisker, natural variability as a band
function barChart(I, scenarios, period, scen) {
  const rows = [["reference", "1991–2020", valueFor(I, "reference")]]
    .concat(scenarios.map((s) => [s, s, valueFor(I, "2050", s)])).filter(([, , v]) => v?.value != null);
  if (rows.length < 2) return `<p class="muted">No data for this indicator.</p>`;
  const all = rows.flatMap(([, , v]) => [v.value, ...(v.range || []), ...(v.band || [])]).filter((x) => x != null);
  const lo0 = I.unit === "°C" ? Math.floor(Math.min(...all) - 1) : 0;  //temperatures need no zero
  const hi0 = Math.max(...all) * 1.04;
  const w = 290, rowH = 17, padL = 64, padR = 52, h = rows.length * rowH + 14;
  const X = (v) => padL + (v - lo0) / (hi0 - lo0 || 1) * (w - padL - padR);
  const bars = rows.map(([key, lab, v], i) => {
    const y = 4 + i * rowH, on = key === "reference" ? period === "reference" : period !== "reference" && key === scen;
    const fill = key === "reference" ? "#6f7c8c" : on ? "var(--accent)" : "#3a4656";
    const band = v.band ? `<rect x="${X(v.band[0]).toFixed(1)}" y="${y + 1}" width="${Math.max(1, X(v.band[1]) - X(v.band[0])).toFixed(1)}" height="${rowH - 4}" fill="#ffffff14" stroke="#ffffff30" stroke-dasharray="2 2"><title>90 % of 30-year means fall in ${fmtVal(v.band[0], I.unit)}–${fmtVal(v.band[1], I.unit)} (natural variability)</title></rect>` : "";
    const whisk = v.range ? `<line x1="${X(v.range[0]).toFixed(1)}" x2="${X(v.range[1]).toFixed(1)}" y1="${y + rowH / 2 - 1}" y2="${y + rowH / 2 - 1}" stroke="var(--text)" stroke-width="1.2"><title>KNMI range ${fmtVal(v.range[0], I.unit)}–${fmtVal(v.range[1], I.unit)}</title></line>` : "";
    return `<g class="clim-bar" data-s="${key}" style="cursor:pointer">` +
      `<text x="${padL - 6}" y="${y + rowH / 2 + 2}" text-anchor="end" font-size="10" fill="${on ? "var(--text)" : "var(--text-dim)"}"${on ? ' font-weight="700"' : ""}>${lab}</text>` +
      band +
      `<rect x="${X(lo0)}" y="${y + 3}" width="${Math.max(1, X(v.value) - X(lo0)).toFixed(1)}" height="${rowH - 8}" rx="2" fill="${fill}"/>` + whisk +
      `<text x="${(Math.max(X(v.value), X(v.range?.[1] ?? v.value)) + 4).toFixed(1)}" y="${y + rowH / 2 + 2}" font-size="10" fill="var(--text)">${v.withinNatVar ? "≈" : ""}${fmtVal(v.value, I.unit)}</text></g>`;
  }).join("");
  return `<svg viewBox="0 0 ${w} ${h}" width="100%" role="img" aria-label="${I.label}: 1991–2020 and 2050 per scenario">${bars}` +
    `<text x="${padL}" y="${h - 1}" font-size="9" fill="var(--text-dim)">${I.unit === "°C" ? `axis from ${lo0} °C` : "axis from 0"}</text></svg>`;
}

/* ================================================================= setup */
export async function setup(ctx) {
  const body = ctx.registerPanel({
    id: "climate",
    title: "Climate 2050 — Design Resilience",
    subtitle: "KNMI'23 official scenarios (not our AI) · today, A, B and the final design",
    order: 11,  //right after the KNMI weather card (10)
  });
  body.innerHTML = `<p class="muted">Loading climate scenarios…</p>`;

  const [clim, res] = await Promise.all([ctx.loadJson(CLIMATE_PATH, { quiet: true }), ctx.loadJson(RESILIENCE_PATH, { quiet: true })]);
  if (!clim?.locations) {
    ctx.placeholder(body, {
      what: "KNMI'23 climate scenarios not fetched yet.",
      produces: "data/processed/climate_knmi23.json",
      owner: "analysis/climate/fetch_knmi23.py",
    });
    return;
  }

  const scenarios = availableScenarios(clim);
  const st = {  //what the card shows; the design highlight follows the app's scenario switch
    period: "2050", scen: scenarios.includes("Hd") ? "Hd" : scenarios[0], theme: "temperature",
    loc: "De Bilt", ind: null, design: ctx.scenario?.() ?? "baseline",
  };
  if (!availableLocations(clim, st.theme).includes(st.loc)) st.loc = availableLocations(clim, st.theme)[0];
  st.ind = defaultIndicator(clim, st.loc, st.theme);

  const seg = (id, items, on) => `<div class="seg" id="${id}">` +
    items.map(([v, lab, title]) => `<button data-v="${v}"${v === on ? ' class="on"' : ""}${title ? ` title="${title}"` : ""}>${lab}</button>`).join("") + `</div>`;

  body.innerHTML =
    `<div class="feed feed--ok" style="margin-bottom:8px"><strong>Long-term climate</strong>: KNMI'23 projections, ` +
    `30-year averages for 2036–2065 against 1991–2020. Not a forecast of any day, and not made by our models. ` +
    `For the next 1–24 h see <em>KNMI weather</em>: our gradient-boosting / LSTM forecast, tested by MAE against baselines.</div>` +
    `<div id="clCtl"></div><div id="clActive" class="muted" style="font-size:11px;margin:-2px 0 6px"></div>` +
    `<div id="clChart"></div><div id="clTable"></div><div id="clObs"></div>` +
    `<h4>Design resilience</h4><div id="clDesign"></div>` +
    `<h4>What does this mean for our design?</h4><div id="clMeaning"></div>` +
    `<div id="clMap"></div><div id="clSrc"></div>`;
  const $ = (id) => body.querySelector(`#${id}`);

  function controls() {
    const locs = availableLocations(clim, st.theme);
    $("clCtl").innerHTML =
      seg("clPeriod", [["reference", "1991–2020"], ["2050", "2050 (2036–65)"]], st.period) +
      seg("clScen", scenarios.map((s) => [s, s, `${clim.scenarios[s].label}${clim.scenarios[s].pathway ? `, ${clim.scenarios[s].pathway}` : ""}` +
        `${clim.scenarios[s].core ? "" : " (supplementary)"}`]), st.scen) +
      seg("clTheme", Object.entries(THEMES).map(([k, t]) => [k, t.label]), st.theme) +
      seg("clLoc", locs.map((l) => [l, clim.locations[l].label.replace("Netherlands average", "NL average"), LOC_NOTE[l]]), st.loc);
    $("clScen").style.opacity = st.period === "reference" ? 0.45 : 1;  //scenarios only matter for 2050
    const bind = (id, key, after) => $(id).querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      st[key] = b.dataset.v;
      if (after) after();
      render();
    }));
    bind("clPeriod", "period");
    bind("clScen", "scen", () => { st.period = "2050"; });  //picking a scenario means looking at 2050
    bind("clTheme", "theme", () => {
      if (!availableLocations(clim, st.theme).includes(st.loc)) st.loc = availableLocations(clim, st.theme)[0];
      st.ind = defaultIndicator(clim, st.loc, st.theme);
    });
    bind("clLoc", "loc", () => { st.ind = defaultIndicator(clim, st.loc, st.theme); });
  }

  function climateView() {
    const S = clim.scenarios[st.scen];
    const I = clim.locations[st.loc].indicators[st.ind];
    const ext = mostExtreme(I, scenarios);
    $("clActive").innerHTML = `Showing <b>${st.period === "reference" ? "1991–2020 (reference)" : `2050 (2036–2065) · ${st.scen}, ${S.label.toLowerCase()}`}</b>` +
      ` · ${clim.locations[st.loc].label} · ${I.unit ?? ""}` + (ext && st.period !== "reference" ? ` · largest change: ${ext}` : "");
    $("clChart").innerHTML = `<div style="font-size:11px;margin-bottom:2px">${I.label}</div>` + barChart(I, scenarios, st.period, st.scen) +
      `<p class="muted" style="font-size:10px;margin:2px 0 6px">Bars: 30-year mean. Dashed box: 90 % range of 30-year means ` +
      `(natural variability). Line: KNMI's uncertainty range. ≈: change within natural variability. Click a bar to pick a scenario.</p>`;
    $("clChart").querySelectorAll(".clim-bar").forEach((g) => g.addEventListener("click", () => {
      if (g.dataset.s === "reference") st.period = "reference";
      else { st.period = "2050"; st.scen = g.dataset.s; }
      render();
    }));
    const rows = indicatorsFor(clim, st.loc, st.theme);
    $("clTable").innerHTML = `<table class="kv"><thead><tr><th></th><th>1991–2020</th><th>${st.period === "reference" ? "–" : `2050 ${st.scen}`}</th></tr></thead><tbody>` +
      rows.map(([k, J]) => {
        const v = valueFor(J, "2050", st.scen);
        const ch = v?.change == null ? "" : ` <span class="delta">${v.change > 0 ? "+" : ""}${nf(v.change, v.changeUnit === "°C" ? 1 : digits(v.change, v.changeUnit))}${v.changeUnit === "%" ? " %" : v.changeUnit === "°C" ? " °C" : ""}` +
          (v.changeRange ? ` (${nf(v.changeRange[0])}–${nf(v.changeRange[1])})` : "") + `</span>`;
        const sel = k === st.ind ? ' style="background:rgba(120,160,220,0.14)"' : "";
        return `<tr data-k="${k}"${sel} style="cursor:pointer"><td${sel}>${J.label}</td><td>${fmtVal(J.reference, J.unit)}</td>` +
          `<td>${st.period === "reference" || !v ? "–" : `${v.withinNatVar ? "≈" : ""}${fmtVal(v.value, J.unit)}${ch}`}</td></tr>`;
      }).join("") + `</tbody></table>`;
    $("clTable").querySelectorAll("tr[data-k]").forEach((tr) => tr.addEventListener("click", () => { st.ind = tr.dataset.k; render(); }));

    const ob = res?.observed;
    if (ob?.years && Object.keys(ob.years).length) {
      const ys = Object.entries(ob.years);
      const yr = `${ys[0][0]}–${ys[ys.length - 1][0]}`;
      const span = (k) => `${nf(Math.min(...ys.map(([, v]) => v[k])), 1)}–${nf(Math.max(...ys.map(([, v]) => v[k])), 1)}`;
      $("clObs").innerHTML = `<p class="muted" style="font-size:11px;margin:6px 0 0"><b>Measured</b>, not projected, at Rotterdam airport ` +
        `(station ${ob.station}), ${yr}: ` + (st.theme === "temperature"
          ? `${nf(ob.mean.summer_days, 1)} summer days and ${nf(ob.mean.tropical_days, 1)} tropical days a year on average (single years ${span("summer_days")} and ${span("tropical_days")}).`
          : `wettest day of each year ${span("wettest_day_mm")} mm (daily totals, not the hourly statistic above).`) +
        ` ${ys.length} years is weather, not a 30-year climate.</p>`;
    } else $("clObs").innerHTML = "";
  }

  function designView() {
    if (!res?.designs) {
      ctx.placeholder($("clDesign"), { what: "Design resilience not computed yet.", produces: "data/processed/climate_resilience.json",
        owner: "analysis/climate/design_resilience.py" });
      $("clMeaning").innerHTML = "";
      return;
    }
    const rows = DESIGNS.map((d) => designRow(res, d, st.scen)).filter(Boolean);
    const imp = implications(rows, st.theme);
    const storm = res.hazards?.rain?.[STORM];
    const span = (v) => v ? `${nf(v[0])}–${nf(v[1])}` : "–";
    const T = st.theme === "temperature";
    //the climate-dependent number goes in the two climate columns, the design's own indicators in the line below
    const cols = T
      ? { caption: `Home-days ≥ 30 °C a year: homes × tropical days, Vlissingen–De Bilt`,
          cur: (r) => span(r.heatRef), fut: (r) => span(r.heat),
          facts: (r) => `${nf(r.static.dwellings)} homes · crown ${pct(r.static.canopy_share, 1)} · shade ${pct(r.static.summer_shade_share, 1)} · ` +
            `${nf(r.static.green_per_home_m2)} m² green per home` }
      : { caption: `Runoff from sealed ground, m³, in the hourly downpour exceeded once a year ` +
            `(${nf(storm?.reference_mm, 0)} mm now, ${nf(storm?.scenarios?.[st.scen]?.mm, 1)} mm in 2050 ${st.scen})`,
          cur: (r) => nf(r.rainRef?.runoff_m3),
          fut: (r) => r.rain ? `${nf(r.rain.runoff_m3)} <span class="delta muted">+${nf(r.rain.extra_runoff_m3)}</span>` : "–",
          facts: (r) => `sealed ${pct(r.static.sealed_share)} · on green ${nf(r.rainRef?.depth_on_green_mm)} → ${nf(r.rain?.depth_on_green_mm)} mm` +
            (r.rain?.pond_rise_m != null ? ` · pond +${nf(r.rain.pond_rise_m, 1)} m` : "") };
    const hl = (id) => id === st.design ? ' style="background:rgba(120,160,220,0.14)"' : "";
    const on = (p) => (p === "reference") === (st.period === "reference") ? ' style="color:var(--accent)"' : "";
    $("clDesign").innerHTML =
      `<p class="muted" style="font-size:11px;margin:0 0 4px">${cols.caption}</p>` +
      `<table class="kv"><thead><tr><th>Design</th><th${on("reference")}>Now</th><th${on("2050")}>2050 · ${st.scen}</th></tr></thead><tbody>` +
      rows.map((r) => `<tr${hl(r.id)}><td style="border-bottom:none"><button class="clim-design" data-d="${r.id}" title="Switch the app to this design" ` +
        `style="all:unset;cursor:pointer;color:var(--accent)">${r.label}</button></td><td style="border-bottom:none">${cols.cur(r)}</td>` +
        `<td style="border-bottom:none">${cols.fut(r)}</td></tr>` +
        `<tr${hl(r.id)}><td colspan="3" style="font-size:11px;padding-top:0;color:var(--text-dim)">${cols.facts(r)}<br>` +
        [...imp[r.id].plus.map((t) => `<span style="color:var(--ok)">+ ${t}</span>`), ...imp[r.id].minus.map((t) => `<span style="color:var(--err)">− ${t}</span>`)]
          .join(" · ") + `</td></tr>`).join("") +
      `</tbody></table>` +
      `<p class="muted" style="font-size:10px;margin:4px 0 0">Over the ${nf(res.site_m2 / 1e4, 2)} ha design site. ` +
      (T ? `Shade: open ground under 4 h of direct sun on 21 June, from buildings and today's trees.`
        : `Coefficient 1 on sealed ground, 0 on green and water: a proxy, not a drainage model. "On green": the runoff spread over all green.`) +
      ` + / − mark the best and worst of the four. Click a design to switch the app to it.</p>`;
    $("clDesign").querySelectorAll(".clim-design").forEach((b) => b.addEventListener("click", () => {
      const sel = document.getElementById("scenarioSelect");  //the app's own switch, so every module follows
      if (!sel || ![...sel.options].some((o) => o.value === b.dataset.d)) return;
      sel.value = b.dataset.d;
      sel.dispatchEvent(new Event("change"));
    }));
    const lines = narrative(clim, res, st.scen, st.theme);
    $("clMeaning").innerHTML = lines.length
      ? `<ul style="margin:0;padding-left:16px;font-size:12px">${lines.map((l) => `<li style="margin-bottom:4px">${l}</li>`).join("")}</ul>`
      : `<p class="muted">Not enough designs computed to compare.</p>`;
  }

  //switch on existing map layers by ticking their own checkboxes, so the layer panel stays in charge
  function showLayers(ids, extra) {
    const missing = [];
    for (const id of ids) {
      const box = document.getElementById(`lyr-${id}`);
      if (!box) { missing.push(id); continue; }
      if (!box.checked) { box.checked = true; box.dispatchEvent(new Event("change")); }
    }
    if (extra) extra();
    if (missing.length === ids.length) ctx.note("Climate: those map layers are not loaded", "warn");
  }
  function mapView() {
    const btns = st.theme === "temperature"
      ? [["Summer sun hours, 21 June", () => showLayers(["shadowOverlay"], () =>
            document.querySelector('#panel-indicators button[data-sfx="_2026-06-21"]')?.click())],  //the morphology card's day button
         ["Trees and planting", () => showLayers(["treeModels", "planting-tree", "planting-green"])]]
      : [["Green and water", () => showLayers(["planting-green", "planting-water"])],
         ["Flood vulnerability (today only)", () => showLayers(["flood_overall"])]];
    $("clMap").innerHTML = `<h4>On the map</h4><div class="seg">` + btns.map(([l], i) => `<button data-i="${i}">${l}</button>`).join("") +
      `</div><p class="muted" style="font-size:10px;margin:-4px 0 0">Existing layers of the selected design. The 2050 climate is ` +
      `regional, so it is not painted on streets.</p>`;
    $("clMap").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => btns[+b.dataset.i][1]()));
  }

  function sources() {
    const s = clim.source || {};
    $("clSrc").innerHTML = `<details style="margin-top:8px;font-size:11px"><summary class="muted" style="cursor:pointer">Sources, method and limits</summary>` +
      `<p><b>Projections</b>: ${s.dataset}, ${s.publisher}. <a href="${s.portal}" target="_blank" rel="noopener" style="color:var(--accent)">Portal</a> · ` +
      `<a href="${s.report}" target="_blank" rel="noopener" style="color:var(--accent)">user report</a> · retrieved ${String(s.retrieved || "?").slice(0, 10)}.</p>` +
      `<p>Reference ${clim.reference_period}; 2050 = ${clim.horizon?.period}, 30-year means. ${clim.geographic_coverage}</p>` +
      `<p>Scenarios: L and H are KNMI's core storylines (SSP1-2.6, SSP5-8.5), M is supplementary; d = drier, n = wetter. ` +
      `Global warming against 1850–1900 in 2050: ${Object.entries(clim.global_warming_C?.["1850-1900"] || {}).map(([k, v]) => `${k} ${nf(v, 1)} °C`).join(", ")}.</p>` +
      `<p>≈ marks a change KNMI prints in italics; it coincides with today's mean lying inside the natural-variability band in ` +
      `${clim.italic_check?.agree} of ${clim.italic_check?.cells} cells.</p>` +
      (res?.method ? `<p><b>Design calculation</b>: ${Object.values(res.method).join("; ")}.</p>` +
        `<p><b>Limits</b>:</p><ul style="padding-left:16px;margin:0">${(res.limitations || []).map((l) => `<li>${l}</li>`).join("")}</ul>` : "") +
      `<p class="muted">analysis/climate/README.md has the full method.</p></details>`;
  }

  function render() {
    controls();
    climateView();
    designView();
    mapView();
  }
  render();
  sources();
  ctx.onScenarioChange((sc) => { st.design = sc; designView(); });  //highlight the design the app is on
  ctx.note(`Climate 2050: KNMI'23, ${scenarios.length} scenarios`, "ok");
}
