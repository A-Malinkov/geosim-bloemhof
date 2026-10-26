/* =============================================================================
 * modules/transit.js  —  public-transport stops and how often each line calls
 *
 * Computed in  analysis/transit/fetch_transit.py  from the national GTFS
 * timetable (OVapi) and written to  data/processed/transit_stops.json:
 * {
 *   "days": { "weekday": "YYYY-MM-DD", "saturday": "..." },
 *   "periods": { "peak": {day, from_h, to_h}, "day": ..., "evening": ..., "saturday": ... },
 *   "stops": [ { id, name, lon, lat, dist_to_study_area_m, modes: ["metro", ...],
 *                lines: [ { line, name, mode, operator,
 *                           per_hour: {peak, day, evening, saturday},
 *                           headway_min: {...},             //busiest direction
 *                           directions: [ { headsign, per_hour, headway_min, first, last } ] } ] } ]
 * }
 *
 * Each stop is a landmark on the map: its name, a glyph per mode, and a badge
 * per line coloured by how often it comes in the chosen period. The timetable
 * is today's, so it is the same for every design scenario.
 * ========================================================================== */

const DATA = "../data/processed/transit_stops.json";

const PERIODS = [
  ["peak", "Peak", "weekday 07–09"],
  ["day", "Day", "weekday 10–16"],
  ["evening", "Evening", "weekday 20–23"],
  ["saturday", "Sat", "Saturday 10–16"],
];

//headway classes, minutes between vehicles: green = turn up and go, red = check the timetable
const CLASSES = [
  { max: 5, bg: "#1a9850", fg: "#ffffff", label: "≤ 5 min" },
  { max: 10, bg: "#66bd63", fg: "#0b1a0e", label: "≤ 10" },
  { max: 15, bg: "#fee08b", fg: "#2b2200", label: "≤ 15" },
  { max: 30, bg: "#fdae61", fg: "#2b1300", label: "≤ 30" },
  { max: Infinity, bg: "#d73027", fg: "#ffffff", label: "> 30" },
];
const NONE = { bg: "#3a434f", fg: "#97a3b2", label: "none" };

const MODES = {
  train: { glyph: "S", bg: "#ffc917", fg: "#003082", label: "Train" },
  metro: { glyph: "M", bg: "#e2001a", fg: "#ffffff", label: "Metro" },
  tram: { glyph: "T", bg: "#0a74b8", fg: "#ffffff", label: "Tram" },
  bus: { glyph: "B", bg: "#4a5563", fg: "#ffffff", label: "Bus" },
  ferry: { glyph: "F", bg: "#00a3c4", fg: "#ffffff", label: "Ferry" },
};

const classOf = (h) => (h == null ? NONE : CLASSES.find((c) => h <= c.max));

//"4.8" -> "5", "7.5" -> "7.5", "352.9" -> "<1/h"
function fmtHeadway(h, unit = "′") {
  if (h == null) return "–";
  if (h > 60) return "<1/h";
  const r = h < 10 ? Math.round(h * 2) / 2 : Math.round(h);
  return `${r}${unit}`;
}

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

/* ---- the landmark image ----------------------------------------------------
 * Drawn on a canvas at 2x so it stays sharp: the name on top, then one row
 * per mode (glyph + line badges, wrapped at PER_ROW), then a pointer whose
 * tip is the stop's position. */
const PER_ROW = 6;
const DPR = 2;
const PAD = 5, GAP = 4, NAME_H = 15, ROW_H = 30, BADGE_H = 26, GLYPH = 20, BADGE_MIN_W = 28, STEM = 8;

function drawStop(stop, period, modes = stop.modes) {
  const rows = [];
  for (const mode of modes) {
    const lines = stop.lines.filter((l) => l.mode === mode);
    for (let i = 0; i < lines.length; i += PER_ROW) rows.push({ mode, lines: lines.slice(i, i + PER_ROW), first: i === 0 });
  }
  const c = document.createElement("canvas");
  const g = c.getContext("2d");
  const lineFont = "700 12px system-ui, sans-serif";
  const hwFont = "600 9.5px system-ui, sans-serif";
  const nameFont = "600 11px system-ui, sans-serif";

  //measure every badge first, so the canvas can be sized to the widest row
  const badgeW = (l) => {
    g.font = lineFont;
    const a = g.measureText(l.line).width;
    g.font = hwFont;
    const b = g.measureText(fmtHeadway(l.headway_min[period])).width;
    return Math.max(BADGE_MIN_W, Math.ceil(Math.max(a, b)) + 10);
  };
  const rowW = rows.map((r) => GLYPH + GAP + r.lines.reduce((s, l) => s + badgeW(l) + GAP, 0) - GAP);
  g.font = nameFont;
  const nameW = Math.ceil(g.measureText(stop.name).width);
  const w = PAD * 2 + Math.max(nameW, ...rowW);
  const bodyH = PAD + NAME_H + rows.length * ROW_H + PAD - (ROW_H - BADGE_H);
  const h = bodyH + STEM;
  c.width = w * DPR;
  c.height = h * DPR;
  g.scale(DPR, DPR);

  //panel and pointer
  g.fillStyle = "rgba(27,33,41,0.93)";
  g.strokeStyle = "#536171";
  g.lineWidth = 1;
  g.beginPath();
  g.roundRect(0.5, 0.5, w - 1, bodyH - 1, 6);
  g.fill();
  g.stroke();
  g.beginPath();
  g.moveTo(w / 2 - STEM, bodyH - 1);
  g.lineTo(w / 2, h);
  g.lineTo(w / 2 + STEM, bodyH - 1);
  g.closePath();
  g.fill();

  //name
  g.font = nameFont;
  g.fillStyle = "#e7ecf2";
  g.textBaseline = "middle";
  g.textAlign = "left";
  g.fillText(stop.name, PAD, PAD + NAME_H / 2);

  //rows: a mode glyph on each mode's first row, then the badges
  let y = PAD + NAME_H;
  for (const r of rows) {
    let x = PAD;
    const m = MODES[r.mode] ?? MODES.bus;
    if (r.first) {
      g.fillStyle = m.bg;
      g.beginPath();
      g.arc(x + GLYPH / 2, y + BADGE_H / 2, GLYPH / 2, 0, Math.PI * 2);
      g.fill();
      g.fillStyle = m.fg;
      g.font = "800 11px system-ui, sans-serif";
      g.textAlign = "center";
      g.fillText(m.glyph, x + GLYPH / 2, y + BADGE_H / 2 + 0.5);
    }
    x += GLYPH + GAP;
    for (const l of r.lines) {
      const bw = badgeW(l);
      const k = classOf(l.headway_min[period]);
      g.fillStyle = k.bg;
      g.beginPath();
      g.roundRect(x, y, bw, BADGE_H, 4);
      g.fill();
      g.fillStyle = k.fg;
      g.textAlign = "center";
      g.font = lineFont;
      g.fillText(l.line, x + bw / 2, y + 9);
      g.font = hwFont;
      g.fillText(fmtHeadway(l.headway_min[period]), x + bw / 2, y + 20);
      x += bw + GAP;
    }
    y += ROW_H;
  }
  return c;
}

//the info box: every line and direction with its headway in each period
function describe(stop, data) {
  const th = PERIODS.map(([, label, sub]) => `<th title="${esc(sub)}">${label}</th>`).join("");
  const rows = stop.lines.flatMap((l) =>
    l.directions.map((d, i) =>
      `<tr>${i === 0 ? `<td rowspan="${l.directions.length}"><b>${esc(MODES[l.mode]?.label ?? l.mode)} ${esc(l.line)}</b><br><small>${esc(l.operator)}</small></td>` : ""}` +
      `<td>→ ${esc(d.headsign || "—")}</td>` +
      PERIODS.map(([p]) => `<td>${fmtHeadway(d.headway_min[p], " min")}</td>`).join("") +
      `<td>${d.first ? `${d.first}–${d.last}` : "not on weekdays"}</td></tr>`));
  return (
    `<p>${stop.dist_to_study_area_m > 0 ? `${stop.dist_to_study_area_m} m outside Bloemhof` : "Inside Bloemhof"}` +
    ` · ${stop.n_platforms} platform${stop.n_platforms === 1 ? "" : "s"}</p>` +
    `<table style="border-collapse:collapse;font-size:12px" cellpadding="3">` +
    `<tr><th>Line</th><th>Towards</th>${th}<th>Weekday</th></tr>${rows.join("")}</table>` +
    `<p style="font-size:11px">Average minutes between departures, from the timetable for ` +
    `${esc(data.days.weekday)} (weekday) and ${esc(data.days.saturday)} (Saturday). ` +
    `Last column: first and last weekday departure.</p>`
  );
}

export async function setup(ctx) {
  const { Cesium, viewer } = ctx;
  const body = ctx.registerPanel({
    id: "transit",
    title: "Public transport",
    subtitle: "stops near Bloemhof · how often each line comes · current timetable, all scenarios",
    order: 65,
  });

  const data = await ctx.loadJson(DATA, { quiet: true });
  if (!data?.stops?.length) {
    ctx.placeholder(body, {
      what: "Public-transport stops and line frequencies — not computed yet.",
      produces: "data/processed/transit_stops.json",
      owner: "analysis/transit/fetch_transit.py + app/modules/transit.js",
    });
    return;
  }

  let period = "day";

  /* ---- map: one landmark per stop, drawing only the lines whose layer is
   * ticked. Two checkboxes (rail, bus) filter lines, not stops, so a stop
   * served by both keeps its buses when metro and tram are switched off --- */
  const shown = { rail: true, bus: true };
  const isShown = (mode) => shown[mode === "bus" ? "bus" : "rail"];
  const stopsDs = new Cesium.CustomDataSource("transit-stops");
  const entities = new Map();  //stop id -> entity
  for (const s of data.stops) {
    const e = stopsDs.entities.add({
      name: s.name,
      position: Cesium.Cartesian3.fromDegrees(s.lon, s.lat),
      billboard: {
        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,  //never hidden behind a building
        scaleByDistance: new Cesium.NearFarScalar(300, 1.25, 5000, 0.55),
      },
      description: describe(s, data),
    });
    e.transitStop = s;
    entities.set(s.id, e);
  }
  function redraw() {
    //re-render every landmark for the chosen period and the ticked modes; hide a stop with nothing left
    for (const e of entities.values()) {
      const modes = e.transitStop.modes.filter(isShown);
      e.show = modes.length > 0;
      if (!e.show) continue;
      const c = drawStop(e.transitStop, period, modes);
      e.billboard.image = c;
      e.billboard.width = c.width / DPR;
      e.billboard.height = c.height / DPR;
    }
    viewer.scene.requestRender();
  }
  await viewer.dataSources.add(stopsDs);
  const toggle = (kind) => (visible) => { shown[kind] = visible; redraw(); };
  //off at startup; picking a stop in the card switches on what it needs
  const layers = {
    rail: ctx.registerLayer({ id: "transitRail", label: "Metro & tram lines at stops", group: "Mobility", show: false, onToggle: toggle("rail") }),
    bus: ctx.registerLayer({ id: "transitBus", label: "Bus lines at stops", group: "Mobility", show: false, onToggle: toggle("bus") }),
  };

  /* ---- dashboard card -------------------------------------------------- */
  const nLines = new Set(data.stops.flatMap((s) => s.lines.map((l) => `${l.mode} ${l.line}`))).size;
  const legend = [...CLASSES, NONE].map((k) =>
    `<span class="lgd"><i style="background:${k.bg}"></i>${k.label}</span>`).join("");
  const modeKey = Object.values(MODES)
    .filter((m) => data.stops.some((s) => s.modes.includes(Object.keys(MODES).find((k) => MODES[k] === m))))
    .map((m) => `<span class="lgd"><i style="background:${m.bg};border-radius:50%"></i>${m.glyph} ${m.label}</span>`).join("");
  body.innerHTML =
    `<div class="seg" id="ptSeg">${PERIODS.map(([p, label, sub]) =>
      `<button data-p="${p}" title="${sub}" class="${p === period ? "on" : ""}">${label}</button>`).join("")}</div>` +
    `<p class="muted" id="ptWhen" style="margin:6px 0 2px"></p>` +
    `<div class="lgdwrap">${legend}</div><div class="lgdwrap">${modeKey}</div>` +
    `<div id="ptDetail" hidden></div>` +
    `<table class="kv"><tbody id="ptRows"></tbody></table>` +
    `<p class="muted">${data.stops.length} stops, ${nLines} lines: bus and tram within ` +
    `${data.catchment_m.bus} m of Bloemhof, metro within ${data.catchment_m.metro} m. ` +
    `Average minutes between vehicles in the busiest direction, from the timetable ` +
    `(OVapi GTFS, weekday ${esc(data.days.weekday)}, Saturday ${esc(data.days.saturday)}); ` +
    `delays are not in it. Click a stop to fly there.</p>`;

  const rowsEl = body.querySelector("#ptRows");
  const whenEl = body.querySelector("#ptWhen");
  function renderPanel() {
    whenEl.textContent = `Showing ${PERIODS.find(([p]) => p === period)[2]}`;
    rowsEl.innerHTML = data.stops.map((s) => {
      const badges = s.lines.map((l) => {
        const k = classOf(l.headway_min[period]);
        return `<span title="${esc(MODES[l.mode]?.label ?? l.mode)} ${esc(l.line)}${l.name ? ` · ${esc(l.name)}` : ""}" ` +
          `style="display:inline-block;margin:0 3px 2px 0;padding:0 4px;border-radius:3px;font-size:10.5px;` +
          `background:${k.bg};color:${k.fg}"><b>${esc(l.line)}</b> ${fmtHeadway(l.headway_min[period])}</span>`;
      }).join("");
      return `<tr data-id="${esc(s.id)}" style="cursor:pointer"><td>${esc(s.name)}<br>` +
        `<small>${s.dist_to_study_area_m > 0 ? `${s.dist_to_study_area_m} m out` : "inside"}</small></td>` +
        `<td>${badges}</td></tr>`;
    }).join("");
  }
  renderPanel();

  body.querySelectorAll("#ptSeg button").forEach((b) =>
    b.addEventListener("click", () => {
      body.querySelectorAll("#ptSeg button").forEach((x) => x.classList.toggle("on", x === b));
      period = b.dataset.p;
      redraw();
      renderPanel();
    }));

  rowsEl.addEventListener("click", (ev) => {
    //fly to the stop and open its timetable summary
    const id = ev.target.closest("tr[data-id]")?.dataset.id;
    const e = id && entities.get(id);
    if (!e) return;
    const s = e.transitStop;
    //a stop whose lines are all switched off would be an invisible target: switch its layers on
    if (!s.modes.some(isShown))
      for (const kind of new Set(s.modes.map((m) => (m === "bus" ? "bus" : "rail")))) layers[kind].setVisible(true);
    viewer.selectedEntity = e;
    viewer.camera.flyToBoundingSphere(
      new Cesium.BoundingSphere(Cesium.Cartesian3.fromDegrees(s.lon, s.lat), 60),
      { offset: new Cesium.HeadingPitchRange(viewer.camera.heading, Cesium.Math.toRadians(-45), 600), duration: 1.2 });
  });

  ctx.note(`Public transport: ${data.stops.length} stops`, "ok");

  /* ---- selected stop: its full table in the card, wherever it was picked
   * (map click or list), so it does not depend on Cesium's info box -------- */
  const detail = body.querySelector("#ptDetail");
  viewer.selectedEntityChanged.addEventListener((e) => {
    const s = e?.transitStop;
    detail.hidden = !s;
    if (!s) return;
    detail.innerHTML = `<h4 style="margin:8px 0 4px">${esc(s.name)}</h4>` +
      describe(s, data).replace(/font-size:12px/, "font-size:11px;width:100%");
    detail.scrollIntoView({ block: "nearest", behavior: "smooth" });
  });
}
