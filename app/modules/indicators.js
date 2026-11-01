/* =============================================================================
 * modules/indicators.js - component 3: urban morphology indicators
 * OWNER: Atanas Malinkov
 *
 * Sky View Factor, built density (FSI/GSI), height variation, land-use mix,
 * street-canyon height-to-width ratio.
 * Computed in  analysis/morphology/  and written to
 *   data/processed/morphology_indicators.json
 *
 * Expected shape (one entry per scenario):
 * {
 *   "baseline":   { "svf_mean": 0.62, "fsi": 1.15, "gsi": 0.34,
 *                   "height_mean_m": 12.4, "height_std_m": 4.1, "landuse_mix": 0.71 },
 *   "scenario_a": { ... },
 *   "scenario_b": { ... }
 * }
 * ========================================================================== */

const INDICATORS = [
  {
    key: "svf_mean",
    label: "Sky View Factor (mean)",
    unit: "",
    hint: "0 = fully enclosed, 1 = open sky",
  },
  {
    key: "fsi",
    label: "FSI (floor space index)",
    unit: "",
    hint: "gross floor area / plot area",
  },
  {
    key: "gsi",
    label: "GSI (ground space index)",
    unit: "",
    hint: "footprint / plot area",
  },
  {
    key: "layers",
    label: "Storeys (L = FSI/GSI)",
    unit: "",
    hint: "mean number of floors",
  },
  {
    key: "height_mean_m",
    label: "Mean building height",
    unit: " m",
    hint: "principal buildings only",
  },
  {
    key: "height_std_m",
    label: "Height variation (σ)",
    unit: " m",
    hint: "spread of building heights",
  },
  {
    key: "landuse_mix",
    label: "Land-use mix (entropy)",
    unit: "",
    hint: "0 = single use, 1 = even mix",
  },
];

//file suffix of a scenario run: baseline keeps the original names
const runSuffix = (scenario) => (scenario === "baseline" ? "" : `_${scenario}`);

/* ---------------------------------------------------------------------------
 * Raster overlays that follow the scenario switch: Sky View Factor and direct
 * sun. sky_view_factor.py and shadows.py write, per scenario, an RGBA PNG
 * already warped to EPSG:4326 plus a summary JSON holding the bbox it covers
 * (<base>_overlay[_scenario].png, <base>_summary[_scenario].json), so the PNG
 * drapes straight onto the globe with a SingleTileImageryProvider.
 * A dated run appends its day to the name (shadow_overlay_final_2026-06-21.png);
 * setDay() picks which day is shown, "" being the default run.
 * ------------------------------------------------------------------------ */
function addScenarioOverlay(ctx, { id, label, base }) {
  const { Cesium, viewer } = ctx;
  const layers = new Map();  //scenario + day suffix -> Promise of its ImageryLayer, or null when there is no run
  let shown = false;  //layer checkbox state
  let current = ctx.scenario();  //scenario the app is on
  let day = "";  //day suffix of the run shown, "" for the default day

  //Images are ~2 MB and the layer is off by default, so each scenario's image
  //loads the first time it is actually needed, not during startup.
  function load(scenario, d) {
    const key = runSuffix(scenario) + d;  //file suffix of this run, scenario then day
    if (!layers.has(key)) {
      layers.set(key, (async () => {
        const sum = await ctx.loadJson(`../data/processed/${base}_summary${key}.json`, { quiet: true });
        const bb = sum?.bbox_wgs84;  //the warped bbox, not the RD square's corners
        if (!bb) return null;  //no run for this scenario
        try {
          //fromUrl reads the image's real size; the synchronous constructor needs
          //tileWidth/tileHeight by hand, and a wrong guess distorts the overlay silently
          const provider = await Cesium.SingleTileImageryProvider.fromUrl(
            `../data/processed/${base}_overlay${key}.png`,
            { rectangle: Cesium.Rectangle.fromDegrees(...bb) },
          );
          const layer = viewer.imageryLayers.addImageryProvider(provider);
          layer.alpha = 0.85;
          layer.show = false;  //refresh() decides
          return layer;
        } catch (err) {
          console.warn(`[indicators] ${label} overlay failed to load`, err);
          ctx.note(`${label}: overlay failed`, "err");
          return null;
        }
      })());
    }
    return layers.get(key);
  }

  //show exactly the current scenario's image, or nothing if it has no run
  async function refresh() {
    for (const p of layers.values()) {
      const l = await p;
      if (l) l.show = false;  //hide every scenario's image first
    }
    viewer.scene.requestRender();  //the hiding happened after awaits, so ask for a redraw
    if (!shown) return;
    const want = current, wantDay = day;
    const l = await load(want, wantDay);
    if (want !== current || wantDay !== day || !shown) return;  //switched while loading
    if (l) l.show = true;
    else ctx.note(`${label}: no run for ${want}`, "warn");
    viewer.scene.requestRender();  //the image appears after loading, so ask for a redraw
  }

  ctx.registerLayer({
    id,
    label,
    group: "Analysis",
    show: false,
    onToggle: (visible) => { shown = visible; refresh(); },  //checkbox
  });
  ctx.onScenarioChange((sc) => { current = sc; refresh(); });  //scenario switch
  return { setDay: (d) => { day = d; refresh(); } };  //day switch, from the card
}

/* ---------------------------------------------------------------------------
 * Density grid overlay: one polygon per 100 m cell, shaded by FSI.
 * Written by analysis/morphology/density_height.py.
 * ------------------------------------------------------------------------ */
async function addDensityGrid(ctx) {
  const { Cesium, viewer } = ctx;
  const geo = await ctx.loadJson("../data/processed/density_grid.geojson", {
    quiet: true,
  });
  if (!geo?.features?.length) return null;

  const vals = geo.features
    .filter((f) => !f.properties.sparse)
    .map((f) => f.properties.fsi);
  const hi = vals.length ? Math.max(...vals) : 2;

  const ds = await Cesium.GeoJsonDataSource.load(geo, { clampToGround: true });
  for (const e of ds.entities.values) {
    const p = e.properties;
    const fsi = p?.fsi?.getValue?.() ?? 0;
    const sparse = p?.sparse?.getValue?.() ?? false;
    // single-hue ramp, light = low intensity, matching the report figures
    const t = Math.max(0, Math.min(1, fsi / hi));
    e.polygon.material = Cesium.Color.fromCssColorString(
      `hsl(213, ${Math.round(45 + 40 * t)}%, ${Math.round(88 - 48 * t)}%)`,
    ).withAlpha(sparse ? 0.25 : 0.72);
    e.polygon.outline = false;
    // Without a name the info box title falls back to the entity's UUID.
    e.name = `Density cell · FSI ${fsi.toFixed(2)}`;
    e.description =
      `<table>` +
      `<tr><td>FSI</td><td>${fsi.toFixed(2)}</td></tr>` +
      `<tr><td>GSI</td><td>${(p?.gsi?.getValue?.() ?? 0).toFixed(2)}</td></tr>` +
      `<tr><td>storeys</td><td>${p?.layers?.getValue?.() ?? "-"}</td></tr>` +
      `<tr><td>mean height</td><td>${p?.height_mean_m?.getValue?.() ?? "-"} m</td></tr>` +
      `<tr><td>height σ</td><td>${p?.height_std_m?.getValue?.() ?? "-"} m</td></tr>` +
      `<tr><td>buildings</td><td>${p?.n_buildings?.getValue?.() ?? "-"}</td></tr>` +
      `</table>`;
  }
  await viewer.dataSources.add(ds);
  ds.show = false;
  ctx.registerLayer({
    id: "densityGrid",
    label: `Density grid, FSI (${geo._cell_size_m ?? 100} m, baseline)`,  //not re-run per scenario, so say which
    group: "Analysis",
    show: false,
    target: ds,
  });
  return ds;
}

/* ---------------------------------------------------------------------------
 * Land-use mix grid: one polygon per cell, shaded by Shannon entropy.
 * Written by analysis/morphology/landuse_mix.py.
 * ------------------------------------------------------------------------ */
async function addLanduseGrid(ctx) {
  const { Cesium, viewer } = ctx;
  const geo = await ctx.loadJson("../data/processed/landuse_grid.geojson", {
    quiet: true,
  });
  if (!geo?.features?.length) return null;

  const vals = geo.features
    .filter((f) => !f.properties.sparse)
    .map((f) => f.properties.shannon);
  const hi = vals.length ? Math.max(...vals) : 1;

  const ds = await Cesium.GeoJsonDataSource.load(geo, { clampToGround: true });
  for (const e of ds.entities.values) {
    const p = e.properties;
    const sh = p?.shannon?.getValue?.() ?? 0;
    const sparse = p?.sparse?.getValue?.() ?? false;
    const t = Math.max(0, Math.min(1, sh / (hi || 1)));
    e.polygon.material = Cesium.Color.fromCssColorString(
      `hsl(213, ${Math.round(45 + 40 * t)}%, ${Math.round(88 - 48 * t)}%)`,
    ).withAlpha(sparse ? 0.2 : 0.72);
    e.polygon.outline = false;
    e.name = `Land-use mix cell · Shannon ${sh.toFixed(2)}`;
    const share = (k) => {
      const v = p?.[`share_${k}`]?.getValue?.();
      return v
        ? `<tr><td>${k}</td><td>${(v * 100).toFixed(0)} %</td></tr>`
        : "";
    };
    e.description =
      `<table>` +
      `<tr><td>Shannon</td><td>${sh.toFixed(3)}</td></tr>` +
      `<tr><td>Simpson</td><td>${(p?.simpson?.getValue?.() ?? 0).toFixed(3)}</td></tr>` +
      `<tr><td>units</td><td>${p?.n_units?.getValue?.() ?? "-"}</td></tr>` +
      `<tr><td>dominant</td><td>${p?.dominant?.getValue?.() ?? "-"}</td></tr>` +
      `</table><hr><table>` +
      [
        "residential",
        "retail",
        "office",
        "industry",
        "education",
        "healthcare",
        "sport",
        "accommodation",
        "assembly",
      ]
        .map(share)
        .join("") +
      `</table>`;
  }
  await viewer.dataSources.add(ds);
  ds.show = false;
  ctx.registerLayer({
    id: "landuseGrid",
    label: `Land-use mix (${geo._cell_size_m ?? 100} m, baseline)`,  //not re-run per scenario, so say which
    group: "Analysis",
    show: false,
    target: ds,
  });
  return ds;
}

/**
 * A compact per-buurt comparison table.
 *
 * When the study area holds more than one buurt, a single combined figure
 * hides how different their fabric is. With one buurt (Bloemhof only, since
 * 2026-10-22) the table is skipped.
 */
function perBuurtTable(perBuurt, cols) {
  const names = Object.keys(perBuurt || {});
  if (names.length < 2) return "";
  return (
    `<table class="kv"><thead><tr><th>by buurt</th>` +
    cols.map(([, label]) => `<th>${label}</th>`).join("") +
    `</tr></thead><tbody>` +
    names
      .map((n) => {
        const b = perBuurt[n];
        return (
          `<tr><td>${n}</td>` +
          cols
            .map(
              ([k, , dp]) =>
                `<td>${b[k] == null ? "-" : Number(b[k]).toFixed(dp)}</td>`,
            )
            .join("") +
          `</tr>`
        );
      })
      .join("") +
    `</tbody></table>`
  );
}

/**
 * Street-canyon H/W (height_width.py): one polyline per street segment,
 * coloured by its median H/W in the report figure's classes. Built on first
 * tick, and swapped on a scenario change; a scenario without a run shows
 * nothing rather than the previous scenario's streets.
 */
const HW_EDGES = [0.4, 0.7, 1.0, 1.5];
const HW_COLOURS = ["#c6dbef", "#6baed6", "#2171b5", "#08519c", "#08306b"];
const HW_LABELS = ["< 0.4 open", "0.4–0.7", "0.7–1.0", "1.0–1.5", "> 1.5 deep"];
const hwClass = (v) => {
  let i = 0;
  while (i < HW_EDGES.length && v >= HW_EDGES[i]) i++;
  return i;
};

function addCanyonLayer(ctx) {
  const { Cesium, viewer } = ctx;
  let shown = false;
  let ds = null;
  let dsFor = null;
  let scenario = ctx.scenario();

  async function refresh() {
    if (!shown) {
      if (ds) ds.show = false;
      return;
    }
    if (ds && dsFor === scenario) {
      ds.show = true;
      return;
    }
    if (ds) {
      viewer.dataSources.remove(ds, true);
      ds = null;
    }
    const want = scenario;
    const geo = await ctx.loadJson(`../data/processed/canyon_hw_${want}.geojson`, { quiet: true });
    if (want !== scenario || !shown) return;
    dsFor = want;
    if (!geo?.features?.length) {
      ctx.note(`Street canyon H/W: no run for ${want}`, "warn");
      return;
    }
    const d = new Cesium.CustomDataSource(`canyon_hw_${want}`);
    for (const f of geo.features) {
      const p = f.properties;
      //a street cut in two (scenario runs remove the old interior grid) is a MultiLineString: draw each part
      const lines = f.geometry.type === "MultiLineString" ? f.geometry.coordinates : [f.geometry.coordinates];
      const open = p.hw == null;  //no facade on both sides: drawn grey as "no canyon"
      for (const c of lines) d.entities.add({  //one polyline per part
        name: `${p.name || "Street"} · ${open ? "no canyon" : `H/W ${p.hw.toFixed(2)}`}`,
        polyline: {
          positions: Cesium.Cartesian3.fromDegreesArray(c.flat()),
          width: open ? 3 : 5,  //thinner for open streets
          clampToGround: true,
          material: open
            ? new Cesium.PolylineDashMaterialProperty({ color: Cesium.Color.fromCssColorString("#bbbbbb") })  //grey dashed
            : Cesium.Color.fromCssColorString(HW_COLOURS[hwClass(p.hw)]),
        },
        description: open
          ? `<p>Not a street canyon: no façade on both sides within 60 m anywhere along it, so it has no H/W.</p>`  //why it is grey
          : `<table>` +
          `<tr><td>H/W (median)</td><td>${p.hw.toFixed(2)}</td></tr>` +
          `<tr><td>wall height H</td><td>${p.h_m} m</td></tr>` +
          `<tr><td>façade to façade W</td><td>${p.w_m} m</td></tr>` +
          `<tr><td>canyon share</td><td>${Math.round(p.canyon_share * 100)} % of segment</td></tr>` +
          `</table>`,
      });
    }
    if (want !== scenario || !shown) return;  //switched or unticked while the entities were built
    if (ds) viewer.dataSources.remove(ds, true);  //a second load finished first: replace it, never stack two
    ds = d;
    await viewer.dataSources.add(d);
    viewer.scene.requestRender();
  }

  ctx.registerLayer({
    id: "canyonHw",
    label: "Street canyon H/W",
    group: "Analysis",
    show: false,
    onToggle: (visible) => { shown = visible; refresh(); },
  });
  ctx.onScenarioChange((s) => { scenario = s; refresh(); });
}

/** Small inline histogram, drawn as an SVG bar chart. */
function histogramSvg(hist, mean) {
  if (!hist?.counts?.length) return "";
  const counts = hist.counts;
  const max = Math.max(...counts) || 1;
  const w = 260,
    h = 64,
    bw = w / counts.length;
  const bars = counts
    .map(
      (c, i) =>
        `<rect x="${(i * bw).toFixed(2)}" y="${(h - (c / max) * h).toFixed(2)}" ` +
        `width="${(bw - 0.6).toFixed(2)}" height="${((c / max) * h).toFixed(2)}" ` +
        `fill="#4dd0e1" opacity="0.85"/>`,
    )
    .join("");
  const mx = (mean * w).toFixed(1);
  return (
    `<svg viewBox="0 0 ${w} ${h + 14}" width="100%" height="78" ` +
    `role="img" aria-label="SVF distribution">` +
    bars +
    `<line x1="${mx}" y1="0" x2="${mx}" y2="${h}" stroke="#ff8a3d" stroke-width="1.5"/>` +
    `<text x="0" y="${h + 11}" fill="#97a3b2" font-size="9">0</text>` +
    `<text x="${w / 2 - 8}" y="${h + 11}" fill="#97a3b2" font-size="9">0.5</text>` +
    `<text x="${w - 10}" y="${h + 11}" fill="#97a3b2" font-size="9">1</text>` +
    `</svg>`
  );
}

/**
 * Spacematrix is scale-sensitive by construction, and here the two aggregation
 * units disagree about which buurt is denser. That is worth saying out loud
 * rather than leaving a reader to trip over it.
 *
 * The buurt FSI divides floor area by ALL the buurt's land, including open and
 * industrial tracts. The grid mean averages only cells holding at least three
 * buildings, so it describes the built fabric and ignores the gaps. Hillesluis
 * has more of those gaps, so it reads as the looser buurt at buurt scale and
 * the denser one at cell scale.
 *
 * The sentence is generated from the data and only appears if the reversal is
 * actually present, so it cannot outlive the numbers that motivated it.
 */
function scaleEffectNote(dens) {
  const pts = dens.spacematrix || [];
  const names = Object.keys(dens.per_buurt || {});
  if (names.length !== 2 || !pts.length) return "";

  const gridMean = {};
  for (const n of names) {
    const v = pts
      .filter((q) => q.buurt === n && q.fsi != null)
      .map((q) => q.fsi);
    if (!v.length) return "";
    gridMean[n] = v.reduce((a, c) => a + c, 0) / v.length;
  }
  const [a, b] = names;
  const buurtOrder = Math.sign(dens.per_buurt[a].fsi - dens.per_buurt[b].fsi);
  const gridOrder = Math.sign(gridMean[a] - gridMean[b]);
  if (buurtOrder === 0 || gridOrder === 0 || buurtOrder === gridOrder)
    return "";

  const looser = buurtOrder < 0 ? a : b; // lower FSI over the whole buurt
  return (
    `<p class="muted"><strong>The two scales disagree.</strong> ` +
    `${looser} has the lower FSI over the whole buurt ` +
    `(${dens.per_buurt[looser].fsi.toFixed(3)} against ` +
    `${dens.per_buurt[looser === a ? b : a].fsi.toFixed(3)}) but the higher mean ` +
    `over built cells (${gridMean[looser].toFixed(2)} against ` +
    `${gridMean[looser === a ? b : a].toFixed(2)}). The buurt figure divides by all ` +
    `its land, gaps included; the grid mean only averages cells with at least ` +
    `${dens.parameters.min_buildings_per_cell} buildings. Quote the unit with the number.</p>`
  );
}

export async function setup(ctx) {
  const body = ctx.registerPanel({
    id: "indicators",
    title: "Urban morphology",
    subtitle: "Sky View Factor · density · height variation · land-use mix · street H/W",
    order: 30,
  });

  /* ---- Sky View Factor and direct sun, per scenario ---------------------- */
  //map overlays, each following the scenario switch
  addScenarioOverlay(ctx, { id: "svfOverlay", label: "Sky View Factor (AHN)", base: "svf" });
  const shadowOverlay = addScenarioOverlay(ctx, { id: "shadowOverlay", label: "Direct sun hours (AHN)", base: "shadow" });

  //days shadows.py was run for, with the file suffix of each ("" is the equinox default)
  const SUN_DAYS = [
    { label: "Equinox", sfx: "" },
    { label: "21 Jun", sfx: "_2026-06-21" },
    { label: "21 Dec", sfx: "_2026-12-21" },
  ];
  let sunDay = "";  //day shown in the direct-sun card and overlay

  const svfBox = document.createElement("div");
  body.appendChild(svfBox);
  const sunDayBox = document.createElement("div");  //day buttons, kept outside shadowBox so a re-render leaves them
  sunDayBox.innerHTML =
    `<h4>Direct sun</h4>` +
    `<div class="seg">` +
    SUN_DAYS.map((d) => `<button data-sfx="${d.sfx}"${d.sfx === sunDay ? ' class="on"' : ""}>${d.label}</button>`).join("") +
    `</div>`;
  body.appendChild(sunDayBox);
  const shadowBox = document.createElement("div");
  body.appendChild(shadowBox);
  const sunBtns = [...sunDayBox.querySelectorAll("button")];
  sunBtns.forEach((b) => b.addEventListener("click", () => {
    sunBtns.forEach((x) => x.classList.toggle("on", x === b));  //highlight the chosen day
    sunDay = b.dataset.sfx;
    shadowOverlay.setDay(sunDay);  //map overlay follows
    renderShadow(ctx.scenario());  //and the card's numbers
  }));

  //summary JSON of one run, baseline or a scenario, optionally of a dated run
  const summary = (base, sc, day = "") =>
    ctx.loadJson(`../data/processed/${base}_summary${runSuffix(sc)}${day}.json`, { quiet: true });

  //one table row for the design site, with the baseline value beside a scenario's
  const siteRow = (label, v, vBase, digits, unit = "") =>
    v == null ? "" :
      `<tr><td>${label}</td><td>${v.toFixed(digits)}${unit}` +
      (vBase != null ? ` <span class="muted">(baseline ${vBase.toFixed(digits)}${unit})</span>` : "") +
      `</td></tr>`;

  async function renderSvf(sc) {
    const [svf, svfBase] = await Promise.all([summary("svf", sc), sc === "baseline" ? null : summary("svf", "baseline")]);
    if (sc !== ctx.scenario()) return;  //switched while loading
    if (!svf?.open_ground) {
      ctx.placeholder(svfBox, {
        what: `Sky View Factor not computed for "${sc}" yet.`,
        produces: `data/processed/svf_summary${runSuffix(sc)}.json`,
        owner: `analysis/morphology/sky_view_factor.py${sc === "baseline" ? "" : ` --scenario ${sc}`}`,
      });
      return;
    }
    // The clipped figure: the raster covers the bounding box, which takes in
    // the Maashaven where SVF is ~1.0 and would flatter the neighbourhood.
    const g = svf.combined?.open_ground || svf.open_ground;
    svfBox.innerHTML =
      `<h4>Sky View Factor</h4>` +
      `<table class="kv"><tbody>` +
      `<tr><td>mean</td><td>${g.mean.toFixed(3)}</td></tr>` +
      `<tr><td>median</td><td>${g.median.toFixed(3)}</td></tr>` +
      `<tr><td>p05 – p95</td><td>${g.p05.toFixed(2)} – ${g.p95.toFixed(2)}</td></tr>` +
      siteRow("design site mean", svf.design_site?.open_ground?.mean,
              svfBase?.design_site?.open_ground?.mean, 3) +  //where the scenarios differ
      `</tbody></table>` +
      histogramSvg(svf.histogram, g.mean) +
      perBuurtTable(
        Object.fromEntries(
          Object.entries(svf.per_buurt || {}).map(([n, v]) => [
            n,
            { svf: v.open_ground?.mean },
          ]),
        ),
        [["svf", "SVF", 3]],
      ) +
      `<p class="muted">At ${svf.parameters.observer_height_m} m above ground on open ` +
      `ground only (streets, gardens, squares). ${svf.parameters.n_directions} directions, ` +
      `${svf.parameters.search_radius_m} m radius, ${svf.parameters.cell_size_m} m cells. ` +
      `Cosine-weighted; the plain solid-angle value is ` +
      `${
        (
          svf.combined?.open_ground_geometric?.mean ??
          svf.open_ground_geometric?.mean
        )?.toFixed(3) ?? "-"
      }. ` +
      (sc === "baseline" ? "" : `Scenario run: demolition and new blocks burned into the AHN surface. `) +  //say what changed
      `Toggle the map overlay under <em>Analysis</em>.</p>`;
  }

  async function renderShadow(sc) {
    const day = sunDay;
    const [shadow, shadowBase] = await Promise.all([summary("shadow", sc, day), sc === "baseline" ? null : summary("shadow", "baseline", day)]);
    if (sc !== ctx.scenario() || day !== sunDay) return;  //switched while loading
    if (!shadow?.open_ground_sunlit_hours) {
      ctx.placeholder(shadowBox, {
        what: `Direct-sun analysis not computed for "${sc}" on this day yet.`,
        produces: `data/processed/shadow_summary${runSuffix(sc)}${day}.json`,
        owner: `analysis/morphology/shadows.py${sc === "baseline" ? "" : ` --scenario ${sc}`}` +
          (day ? ` --date ${day.slice(1)} --suffix ${day}` : ""),  //a dated run needs both flags
      });
      return;
    }
    const g =
      shadow.combined?.open_ground_sunlit_hours ||
      shadow.open_ground_sunlit_hours;
    const site = shadow.design_site?.open_ground_sunlit_hours;  //design site, open ground
    const siteBase = shadowBase?.design_site?.open_ground_sunlit_hours;
    shadowBox.innerHTML =
      `<table class="kv"><tbody>` +
      `<tr><td>mean sun</td><td>${g.mean.toFixed(1)} h</td></tr>` +
      `<tr><td>median</td><td>${g.median.toFixed(1)} h</td></tr>` +
      `<tr><td>p05 – p95</td><td>${g.p05.toFixed(1)} – ${g.p95.toFixed(1)} h</td></tr>` +
      siteRow("design site mean", site?.mean, siteBase?.mean, 1, " h") +  //where the scenarios differ
      siteRow("site under 2 h", site?.share_under_2h != null ? 100 * site.share_under_2h : null,
              siteBase?.share_under_2h != null ? 100 * siteBase.share_under_2h : null, 0, " %") +
      `</tbody></table>` +
      perBuurtTable(
        Object.fromEntries(
          Object.entries(shadow.per_buurt || {}).map(([n, v]) => [
            n,
            { sun: v.open_ground_sunlit_hours?.mean },
          ]),
        ),
        [["sun", "sun h", 1]],
      ) +
      `<p class="muted">Hours of direct sun on open ground on ${shadow.date}, ` +
      `of ${shadow.daylight_hours.toFixed(1)} h of daylight. Ray-cast from the ` +
      `AHN surface every ${shadow.parameters.step_minutes} min; clear-sky, so an ` +
      `upper bound. The map overlay runs from no sun to the whole day's ` +
      `${shadow.daylight_hours.toFixed(1)} h, so its colours are per day. ` +  //each PNG is scaled to its own daylight
      (sc === "baseline" ? "" : `Demolition adds open ground, so the site means cover ` +
        `different areas: compare the shares too. `) +  //the denominators differ between scenarios
      `Toggle the map overlay under <em>Analysis</em>.</p>`;
  }

  ctx.onScenarioChange((sc) => { renderSvf(sc); renderShadow(sc); });  //also runs once at startup

  /* ---- time-of-day sun scrubber ----------------------------------------- */
  /* A live sun scrubber: turn on the scene shadow map and move the clock, so
   * the 3DBAG buildings cast real shadows as you drag. Given its OWN dashboard
   * card near the top (order 6) rather than buried among the indicators, so it
   * is easy to find. This is the instantaneous companion to the direct-sun map,
   * which is the whole-day total.
   *
   * It opens on LIVE: the sun as it stands right now in Rotterdam, clear-sky.
   * That is for orientation only: the analysis day is the equinox, which is
   * what shadows.py computes, and the reference days are one click away. */
  {
    const { Cesium, viewer, config } = ctx;
    const { Cartesian3 } = Cesium;
    const scene = viewer.scene;
    scene.shadowMap.enabled = true;
    scene.shadowMap.softShadows = true;
    scene.shadowMap.size = 2048;
    scene.shadowMap.maximumDistance = 5000;
    scene.globe.enableLighting = true;
    viewer.clock.shouldAnimate = false;

    // Reference days for solar access: the equinox is the neutral average-sun
    // day and the planning standard; the solstices bracket best and worst case.
    // shadows.py defaults to the equinox.
    const DAYS = [
      { label: "Equinox", date: "2026-03-20" },
      { label: "Summer", date: "2026-06-21" },
      { label: "Winter", date: "2026-12-21" },
    ];
    const pad = (n) => String(n).padStart(2, "0");

    // Rotterdam wall-clock parts of an instant, and the UTC offset of a date.
    // Both go through Europe/Amsterdam, so DST is right on any date. The
    // offset is taken at 12:00 UTC, after the changeover hour (01:00 UTC), and
    // the slider starts at 04:00, so the changeover day is right too.
    const nlFmt = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Europe/Amsterdam", year: "numeric", month: "2-digit",
      day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    });
    const nlParts = (date) => Object.fromEntries(
      nlFmt.formatToParts(date).map((x) => [x.type, x.value]));
    const offFmt = new Intl.DateTimeFormat("en-US", {
      timeZone: "Europe/Amsterdam", timeZoneName: "shortOffset",
    });
    const nlOffset = (d) => {
      const z = offFmt.formatToParts(new Date(`${d}T12:00:00Z`))
        .find((x) => x.type === "timeZoneName").value;          // "GMT+2"
      return `+${pad(Number(z.replace("GMT", "")))}:00`;
    };
    const today = () => {
      const p = nlParts(new Date());
      return `${p.year}-${p.month}-${p.day}`;
    };

    // Sun altitude over the study area, from the same solar ephemeris and
    // frame Cesium uses to light the scene, so "the sun is down" agrees with
    // what is drawn. -0.833° is the conventional sunrise/sunset altitude
    // (refraction plus the sun's radius), which is what published times use.
    const site = Cartesian3.fromDegrees(config.studyArea.lon, config.studyArea.lat);
    const up = Cesium.Ellipsoid.WGS84.geodeticSurfaceNormal(site, new Cartesian3());
    const SUNRISE_ALT = -0.833;
    const sunAltDeg = (t) => {
      const inertial = Cesium.Simon1994PlanetaryPositions
        .computeSunPositionInEarthInertialFrame(t);
      const fixed = Cesium.Matrix3.multiplyByVector(
        Cesium.Transforms.computeTemeToPseudoFixedMatrix(t), inertial, new Cartesian3());
      const dir = Cartesian3.normalize(
        Cartesian3.subtract(fixed, site, new Cartesian3()), new Cartesian3());
      return Cesium.Math.toDegrees(Math.asin(Cartesian3.dot(dir, up)));
    };
    // Next sunrise after t, to 5 minutes; null if none within a day.
    const nextSunrise = (t) => {
      for (let m = 5; m <= 24 * 60; m += 5) {
        const s = Cesium.JulianDate.addMinutes(t, m, new Cesium.JulianDate());
        if (sunAltDeg(s) >= SUNRISE_ALT) return Cesium.JulianDate.toDate(s);
      }
      return null;
    };

    // Shadows on/off lives in the layer panel (Performance), with the other
    // expensive rendering switches, so there is one control for it.
    const PERF = ` Shadows can be switched off under <em>Performance</em>.`;
    const NOTE_LIVE =
      `Live: this moment in Rotterdam, clear-sky. The analysis uses the ` +
      `equinox: the whole-day direct-sun total is under <em>Urban ` +
      `morphology</em>, the map overlay under <em>Analysis</em>.` + PERF;
    const NOTE_FIXED =
      `One instant on the chosen day. The whole-day direct-sun total is under ` +
      `<em>Urban morphology</em>, the map overlay under <em>Analysis</em>.` + PERF;

    let dateStr = today();
    const sunBody = ctx.registerPanel({
      id: "sun",
      title: "Sun & shadows",
      subtitle: "Live for right now in Rotterdam, or drag to move the sun",
      order: 6,
    });
    sunBody.innerHTML =
      `<div class="seg" id="sunDay">` +
      DAYS.map((d) => `<button data-date="${d.date}">${d.label}</button>`).join("") +
      `<button data-live class="on" title="Follow the current time in Rotterdam">Live</button>` +
      `</div>` +
      `<label class="slider">` +
      `<span>local time <output id="sunOut">12:00</output> · ` +
      `<span id="sunDate">${dateStr}</span></span>` +
      `<input type="range" id="sunTime" min="240" max="1320" step="10" value="720">` +
      `</label>` +
      `<p class="muted" id="sunNight" hidden></p>` +
      `<p class="muted" id="sunNote">${NOTE_LIVE}</p>`;

    const slider = sunBody.querySelector("#sunTime");
    const out = sunBody.querySelector("#sunOut");
    const dateEl = sunBody.querySelector("#sunDate");
    const nightEl = sunBody.querySelector("#sunNight");
    const noteEl = sunBody.querySelector("#sunNote");
    const dayBtns = [...sunBody.querySelectorAll("#sunDay button")];

    const setTime = (minutes) => {
      const hh = Math.floor(minutes / 60);
      const mm = minutes % 60;
      out.textContent = `${pad(hh)}:${pad(mm)}`;
      viewer.clock.currentTime = Cesium.JulianDate.fromIso8601(
        `${dateStr}T${pad(hh)}:${pad(mm)}:00${nlOffset(dateStr)}`,
      );
      viewer.scene.requestRender?.();
    };

    /* LIVE: the Cesium clock follows the system clock (SYSTEM_CLOCK step), so
     * the sun and shadows match this moment and keep moving. The slider
     * covers 04:00–22:00, so at night it sits at an end while the readout
     * shows the real time and a note says when the sun comes up. */
    let liveTimer = null;
    const showLive = () => {
      const p = nlParts(new Date());
      out.textContent = `${p.hour}:${p.minute}`;
      dateEl.textContent = `${p.year}-${p.month}-${p.day} (live)`;
      slider.value = Number(p.hour) * 60 + Number(p.minute);
      const now = Cesium.JulianDate.now();
      const down = sunAltDeg(now) < SUNRISE_ALT;
      nightEl.hidden = !down;
      if (down) {
        const rise = nextSunrise(now);
        const r = rise && nlParts(rise);
        nightEl.textContent = r
          ? `Sun is down: rises at ${r.hour}:${r.minute}.`
          : "Sun is down.";
      }
    };
    const stopLive = () => {
      if (!liveTimer) return;
      clearInterval(liveTimer);
      liveTimer = null;
      viewer.clock.clockStep = Cesium.ClockStep.SYSTEM_CLOCK_MULTIPLIER;
      viewer.clock.shouldAnimate = false;
      nightEl.hidden = true;
      noteEl.innerHTML = NOTE_FIXED;
    };
    const startLive = () => {
      viewer.clock.clockStep = Cesium.ClockStep.SYSTEM_CLOCK;
      viewer.clock.currentTime = Cesium.JulianDate.now();
      viewer.clock.shouldAnimate = true;
      noteEl.innerHTML = NOTE_LIVE;
      showLive();
      liveTimer = setInterval(showLive, 15000);
    };

    // Dragging out of Live stays on today rather than jumping to a reference
    // day: "what about later today?" is the question being asked.
    slider.addEventListener("input", (e) => {
      if (liveTimer) {
        stopLive();
        dayBtns.forEach((x) => x.classList.remove("on"));
        dateStr = today();
        dateEl.textContent = dateStr;
      }
      setTime(Number(e.target.value));
    });

    dayBtns.forEach((b) => b.addEventListener("click", () => {
      dayBtns.forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      if (b.hasAttribute("data-live")) {
        if (!liveTimer) startLive();
        return;
      }
      stopLive();
      dateStr = b.dataset.date;
      dateEl.textContent = dateStr;
      setTime(Number(slider.value));
    }));

    startLive();
  }

  /* ---- density and height variation ------------------------------------- */
  const dens = await ctx.loadJson("../data/processed/density_summary.json", {
    quiet: true,
  });
  const densBox = document.createElement("div");
  body.appendChild(densBox);

  if (dens?.combined) {
    await addDensityGrid(ctx);
    const b = dens.combined;
    const g = dens.grid;
    densBox.innerHTML =
      `<h4>Density &amp; height</h4>` +
      `<table class="kv"><tbody>` +
      `<tr><td>GSI</td><td>${b.gsi.toFixed(3)}</td></tr>` +
      `<tr><td>FSI</td><td>${b.fsi.toFixed(3)}</td></tr>` +
      `<tr><td>storeys (L)</td><td>${b.layers.toFixed(2)}</td></tr>` +
      `<tr><td>height</td><td>${b.height_m.mean.toFixed(1)} m ± ${b.height_m.std.toFixed(1)}</td></tr>` +
      `<tr><td>tallest</td><td>${b.height_m.max.toFixed(1)} m</td></tr>` +
      `</tbody></table>` +
      perBuurtTable(dens.per_buurt, [
        ["gsi", "GSI", 3],
        ["fsi", "FSI", 3],
        ["layers", "storeys", 2],
      ]) +
      `<p class="muted">Over ${b.land_area_ha} ha, ` +  //the Spacematrix diagram was removed on 2026-11-01
      `${b.n_buildings.toLocaleString("en-GB")} buildings. Grid mean FSI ` +
      `${g.fsi.mean.toFixed(2)} across ${g.n_cells_used} cells of ` +
      `${dens.parameters.cell_size_m} m. Toggle the grid under <em>Analysis</em>.</p>` +
      scaleEffectNote(dens);
  } else {
    ctx.placeholder(densBox, {
      what: "Building density and height variation not computed yet.",
      produces: "data/processed/density_summary.json",
      owner: "analysis/morphology/density_height.py",
    });
  }

  // density on the design site, today next to the chosen scenario (density_site.py)
  const site = await ctx.loadJson("../data/processed/density_site.json", { quiet: true });
  if (site?.baseline) {
    const siteBox = document.createElement("div");
    body.appendChild(siteBox);
    const renderSite = (sc) => {
      const now = site[sc] ? sc : "baseline";  //a scenario without massing shows today only
      const t = site.baseline, s = site[now];
      const row = (label, k, d) =>
        `<tr><td>${label}</td><td>${t[k].toFixed(d)}</td>` +
        (now === "baseline" ? "" : `<td>${s[k].toFixed(d)}</td>`) + `</tr>`;
      siteBox.innerHTML =
        `<h4>Density on the design site</h4>` +
        `<table class="kv"><thead><tr><th></th><th>today</th>` +
        (now === "baseline" ? "" :
          `<th>${(ctx.config.scenarios || []).find((x) => x.id === now)?.label ?? now}</th>`) +  //label from config.js
        `</tr></thead><tbody>` +
        row("GSI", "gsi", 2) + row("FSI", "fsi", 2) + row("storeys (L)", "layers", 1) +
        `</tbody></table>` +
        `<p class="muted">Over the ${site.site_area_ha} ha design site, same storey rule as above. ` +
        `Follows the scenario switch.</p>`;
    };
    ctx.onScenarioChange(renderSite);  //also runs once at startup
  }

  /* ---- land-use mix ------------------------------------------------------ */
  const lu = await ctx.loadJson("../data/processed/landuse_summary.json", {
    quiet: true,
  });
  const luBox = document.createElement("div");
  body.appendChild(luBox);

  if (lu?.overall) {
    await addLanduseGrid(ctx);
    const o = lu.overall;
    const b = lu.combined || {};
    const comp = (b.composition || lu.composition || []).slice(0, 6);
    const head = b.shannon_area ?? o.shannon_area;
    luBox.innerHTML =
      `<h4>Land-use mix</h4>` +
      `<table class="kv"><tbody>` +
      `<tr><td>Shannon (area)</td><td>${head.toFixed(3)}</td></tr>` +
      `<tr><td>Shannon (units)</td><td>${(b.shannon_count ?? o.shannon_count).toFixed(3)}</td></tr>` +
      `<tr><td>Simpson</td><td>${(b.simpson_area ?? o.simpson_area).toFixed(3)}</td></tr>` +
      `<tr><td>dominant use</td><td>${o.dominant} (${(o.dominant_share * 100).toFixed(0)} %)</td></tr>` +
      `</tbody></table>` +
      `<table class="kv"><thead><tr><th>use</th><th>floor area</th></tr></thead><tbody>` +
      comp
        .map(
          (x) =>
            `<tr><td>${x.category}</td><td>${(x.share * 100).toFixed(1)} %</td></tr>`,
        )
        .join("") +
      `</tbody></table>` +
      perBuurtTable(lu.per_buurt, [
        ["shannon_area", "Shannon", 3],
        ["simpson_area", "Simpson", 3],
      ]) +
      `<p class="muted">Normalised Shannon entropy over ` +
      `${lu.parameters.n_categories_in_scheme} BAG use classes, weighted by ` +
      `usable floor area. 0 = one use only, 1 = an even mix. ` +
      `Built floor space only: parks, water and streets are not in BAG; ` +
      `use GSI above for the built/unbuilt split. ` +
      `Toggle the grid under <em>Analysis</em>.</p>`;
  } else {
    ctx.placeholder(luBox, {
      what: "Land-use mix not computed yet.",
      produces: "data/processed/landuse_summary.json",
      owner: "analysis/morphology/landuse_mix.py",
    });
  }

  /* ---- street canyon height-to-width -------------------------------------- */
  const hw = await ctx.loadJson("../data/processed/canyon_hw_baseline.json", {
    quiet: true,
  });
  const hwBox = document.createElement("div");
  body.appendChild(hwBox);

  if (hw?.combined?.hw) {
    addCanyonLayer(ctx);
    const c = hw.combined;
    const site = hw.design_site || {};
    const flat = (o) => ({
      hw: o.hw?.median, h: o.h_m_median, w: o.w_m_median,
      canyon: o.canyon_share == null ? null : o.canyon_share * 100,
    });
    const rows = { ...Object.fromEntries(Object.entries(hw.per_buurt || {}).map(([n, v]) => [n, flat(v)])) };
    if (site.hw) rows["Design site"] = flat(site);
    const legend = HW_COLOURS.map((col, i) =>
      `<span style="display:inline-flex;align-items:center;gap:3px;margin:0 6px 2px 0">` +
      `<i style="width:12px;height:4px;background:${col};display:inline-block"></i>${HW_LABELS[i]}</span>`,
    ).join("") +
      `<span style="display:inline-flex;align-items:center;gap:3px;margin:0 6px 2px 0">` +
      `<i style="width:12px;height:0;border-top:2px dashed #bbbbbb;display:inline-block"></i>no canyon</span>`;  //grey dashed streets
    hwBox.innerHTML =
      `<h4>Street canyons (H/W)</h4>` +
      `<table class="kv"><tbody>` +
      `<tr><td>H/W median</td><td>${c.hw.median.toFixed(2)}</td></tr>` +
      `<tr><td>p10 – p90</td><td>${c.hw.p10.toFixed(2)} – ${c.hw.p90.toFixed(2)}</td></tr>` +
      `<tr><td>wall height H</td><td>${c.h_m_median} m</td></tr>` +
      `<tr><td>width W</td><td>${c.w_m_median} m</td></tr>` +
      `<tr><td>street that is canyon</td><td>${(c.canyon_share * 100).toFixed(0)} %</td></tr>` +
      `</tbody></table>` +
      perBuurtTable(rows, [["hw", "H/W", 2], ["w", "W m", 1], ["canyon", "canyon %", 0]]) +
      `<div class="muted" style="font-size:10px;line-height:1.5">${legend}</div>` +
      `<p class="muted">Façade-to-façade width and mean wall height, sampled every ` +
      `${hw.parameters.step_m} m along every street; a point counts as canyon only with ` +
      `buildings on both sides within ${hw.parameters.max_ray_m} m. Below ~0.4 each ` +
      `building meets the wind on its own; above ~0.7 the wind skims over the roofs and ` +
      `the street below is sheltered but traps heat (Oke 1988). ` +
      `Toggle the streets under <em>Analysis</em>.</p>`;
  } else {
    ctx.placeholder(hwBox, {
      what: "Street canyon H/W not computed yet.",
      produces: "data/processed/canyon_hw_baseline.json",
      owner: "analysis/morphology/height_width.py",
    });
  }

  /* ---- the rest of the morphology indicators ---------------------------- */
  const data = await ctx.loadJson(ctx.config.dataSources.processed.morphology);
  const rest = document.createElement("div");
  body.appendChild(rest);

  if (!data) {
    ctx.placeholder(rest, {
      what: "Density, height variation and land-use mix not computed yet.",
      produces: "data/processed/morphology_indicators.json",
      owner: "analysis/morphology/ + app/modules/indicators.js",
    });
    return;
  }

  const table = document.createElement("table");
  table.className = "kv";
  rest.appendChild(table);

  function render(scenario) {
    const s = data[scenario] || {};
    const base = data.baseline || {};
    table.innerHTML =
      `<thead><tr><th>Indicator</th><th>Value</th><th>vs baseline</th></tr></thead><tbody>` +
      INDICATORS.map(({ key, label, unit, hint }) => {
        const v = s[key];
        const b = base[key];
        const shown = v == null ? "-" : `${Number(v).toFixed(2)}${unit}`;
        let delta = "";
        if (v != null && b != null && scenario !== "baseline") {
          const d = v - b;
          const cls = d > 0 ? "up" : d < 0 ? "down" : "";
          delta = `<span class="delta ${cls}">${d >= 0 ? "+" : ""}${d.toFixed(2)}</span>`;
        }
        return `<tr title="${hint}"><td>${label}</td><td>${shown}</td><td>${delta}</td></tr>`;
      }).join("") +
      `</tbody>`;
  }

  ctx.onScenarioChange(render);
}
