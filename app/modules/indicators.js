/* =============================================================================
 * modules/indicators.js  —  component 3: urban morphology indicators
 * OWNER: Atanas Malinkov
 *
 * Sky View Factor, built density (FSI/GSI), height variation, land-use mix.
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
  { key: "svf_mean",      label: "Sky View Factor (mean)", unit: "",    hint: "0 = fully enclosed, 1 = open sky" },
  { key: "fsi",           label: "FSI (floor space index)", unit: "",   hint: "gross floor area / plot area" },
  { key: "gsi",           label: "GSI (ground space index)", unit: "",  hint: "footprint / plot area" },
  { key: "layers",        label: "Storeys (L = FSI/GSI)",   unit: "",   hint: "mean number of floors" },
  { key: "osr",           label: "OSR (open space ratio)",  unit: "",   hint: "open space per m² of floor space" },
  { key: "height_mean_m", label: "Mean building height",    unit: " m", hint: "principal buildings only" },
  { key: "height_std_m",  label: "Height variation (σ)",    unit: " m", hint: "spread of building heights" },
  { key: "landuse_mix",   label: "Land-use mix (entropy)",  unit: "",   hint: "0 = single use, 1 = even mix" },
];

/* ---------------------------------------------------------------------------
 * Sky View Factor overlay.
 * sky_view_factor.py writes an RGBA PNG plus the bbox it covers, so we can
 * drape it straight onto the globe with a SingleTileImageryProvider.
 * ------------------------------------------------------------------------ */
async function addSvfOverlay(ctx, svf) {
  const { Cesium, viewer } = ctx;
  const bb = svf?.bbox_wgs84;
  if (!bb) return null;
  const [west, south, east, north] = bb;
  /* The image is ~1.8 MB and the layer is off by default, so it is loaded the
   * first time someone ticks the box rather than during startup — otherwise
   * every panel in the dashboard waits on a download nobody asked for.
   * The toggle is registered immediately so the layer list stays in a fixed
   * order regardless of how long the image takes. */
  let layer = null;
  let loading = null;

  async function ensureLoaded() {
    if (layer) return layer;
    if (!loading) {
      // fromUrl reads the image's real dimensions. The synchronous constructor
      // makes you supply tileWidth/tileHeight by hand, and they were wrong
      // (512 against a 1400 px image) — asserting a size you have not checked
      // is how an overlay silently ends up distorted.
      loading = Cesium.SingleTileImageryProvider.fromUrl(
        "../data/processed/svf_overlay.png",
        { rectangle: Cesium.Rectangle.fromDegrees(west, south, east, north) },
      ).then((provider) => {
        layer = viewer.imageryLayers.addImageryProvider(provider);
        layer.alpha = 0.85;
        return layer;
      }).catch((err) => {
        console.warn("[indicators] SVF overlay failed to load", err);
        ctx.note("SVF overlay: failed", "err");
        return null;
      });
    }
    return loading;
  }

  ctx.registerLayer({
    id: "svfOverlay",
    label: "Sky View Factor (AHN)",
    group: "Analysis",
    show: false,
    onToggle: async (visible) => {
      if (!visible) {
        if (layer) layer.show = false;
        return;
      }
      const l = await ensureLoaded();
      if (l) l.show = true;
    },
  });
  return true;
}

/* ---------------------------------------------------------------------------
 * Direct-sun / shadow overlay.
 * shadows.py writes an RGBA PNG of direct-sun hours plus the bbox it covers,
 * already warped to EPSG:4326, so it drapes straight onto the globe. Loaded
 * lazily on first toggle, exactly like the SVF overlay above.
 * ------------------------------------------------------------------------ */
async function addShadowOverlay(ctx, shadow) {
  const { Cesium, viewer } = ctx;
  const bb = shadow?.bbox_wgs84;
  if (!bb) return null;
  const [west, south, east, north] = bb;
  let layer = null;
  let loading = null;

  async function ensureLoaded() {
    if (layer) return layer;
    if (!loading) {
      loading = Cesium.SingleTileImageryProvider.fromUrl(
        "../data/processed/shadow_overlay.png",
        { rectangle: Cesium.Rectangle.fromDegrees(west, south, east, north) },
      ).then((provider) => {
        layer = viewer.imageryLayers.addImageryProvider(provider);
        layer.alpha = 0.85;
        return layer;
      }).catch((err) => {
        console.warn("[indicators] shadow overlay failed to load", err);
        ctx.note("Sun-hours overlay: failed", "err");
        return null;
      });
    }
    return loading;
  }

  ctx.registerLayer({
    id: "shadowOverlay",
    label: "Direct sun hours (AHN)",
    group: "Analysis",
    show: false,
    onToggle: async (visible) => {
      if (!visible) {
        if (layer) layer.show = false;
        return;
      }
      const l = await ensureLoaded();
      if (l) l.show = true;
    },
  });
  return true;
}

/* ---------------------------------------------------------------------------
 * Density grid overlay: one polygon per 100 m cell, shaded by FSI.
 * Written by analysis/morphology/density_height.py.
 * ------------------------------------------------------------------------ */
async function addDensityGrid(ctx) {
  const { Cesium, viewer } = ctx;
  const geo = await ctx.loadJson("../data/processed/density_grid.geojson",
                                 { quiet: true });
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
    e.polygon.material = Cesium.Color
      .fromCssColorString(`hsl(213, ${Math.round(45 + 40 * t)}%, ${Math.round(88 - 48 * t)}%)`)
      .withAlpha(sparse ? 0.25 : 0.72);
    e.polygon.outline = false;
    e.description =
      `<table>` +
      `<tr><td>FSI</td><td>${fsi.toFixed(2)}</td></tr>` +
      `<tr><td>GSI</td><td>${(p?.gsi?.getValue?.() ?? 0).toFixed(2)}</td></tr>` +
      `<tr><td>storeys</td><td>${p?.layers?.getValue?.() ?? "—"}</td></tr>` +
      `<tr><td>OSR</td><td>${p?.osr?.getValue?.() ?? "—"}</td></tr>` +
      `<tr><td>mean height</td><td>${p?.height_mean_m?.getValue?.() ?? "—"} m</td></tr>` +
      `<tr><td>height σ</td><td>${p?.height_std_m?.getValue?.() ?? "—"} m</td></tr>` +
      `<tr><td>buildings</td><td>${p?.n_buildings?.getValue?.() ?? "—"}</td></tr>` +
      `</table>`;
  }
  await viewer.dataSources.add(ds);
  ds.show = false;
  ctx.registerLayer({
    id: "densityGrid",
    label: `Density grid, FSI (${geo._cell_size_m ?? 100} m)`,
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
  const geo = await ctx.loadJson("../data/processed/landuse_grid.geojson",
                                 { quiet: true });
  if (!geo?.features?.length) return null;

  const vals = geo.features.filter((f) => !f.properties.sparse)
                           .map((f) => f.properties.shannon);
  const hi = vals.length ? Math.max(...vals) : 1;

  const ds = await Cesium.GeoJsonDataSource.load(geo, { clampToGround: true });
  for (const e of ds.entities.values) {
    const p = e.properties;
    const sh = p?.shannon?.getValue?.() ?? 0;
    const sparse = p?.sparse?.getValue?.() ?? false;
    const t = Math.max(0, Math.min(1, sh / (hi || 1)));
    e.polygon.material = Cesium.Color
      .fromCssColorString(`hsl(213, ${Math.round(45 + 40 * t)}%, ${Math.round(88 - 48 * t)}%)`)
      .withAlpha(sparse ? 0.2 : 0.72);
    e.polygon.outline = false;
    const share = (k) => {
      const v = p?.[`share_${k}`]?.getValue?.();
      return v ? `<tr><td>${k}</td><td>${(v * 100).toFixed(0)} %</td></tr>` : "";
    };
    e.description =
      `<table>` +
      `<tr><td>Shannon</td><td>${sh.toFixed(3)}</td></tr>` +
      `<tr><td>Simpson</td><td>${(p?.simpson?.getValue?.() ?? 0).toFixed(3)}</td></tr>` +
      `<tr><td>units</td><td>${p?.n_units?.getValue?.() ?? "—"}</td></tr>` +
      `<tr><td>dominant</td><td>${p?.dominant?.getValue?.() ?? "—"}</td></tr>` +
      `</table><hr><table>` +
      ["residential", "retail", "office", "industry", "education",
       "healthcare", "sport", "accommodation", "assembly"].map(share).join("") +
      `</table>`;
  }
  await viewer.dataSources.add(ds);
  ds.show = false;
  ctx.registerLayer({
    id: "landuseGrid",
    label: `Land-use mix (${geo._cell_size_m ?? 100} m)`,
    group: "Analysis",
    show: false,
    target: ds,
  });
  return ds;
}

/**
 * A compact per-buurt comparison table.
 *
 * The study area is two buurten and the brief is to analyse both, so a single
 * combined figure hides the finding: they have noticeably different fabric.
 */
function perBuurtTable(perBuurt, cols) {
  const names = Object.keys(perBuurt || {});
  if (names.length < 2) return "";
  return `<table class="kv"><thead><tr><th>by buurt</th>` +
    cols.map(([, label]) => `<th>${label}</th>`).join("") +
    `</tr></thead><tbody>` +
    names.map((n) => {
      const b = perBuurt[n];
      return `<tr><td>${n}</td>` +
        cols.map(([k, , dp]) =>
          `<td>${b[k] == null ? "—" : Number(b[k]).toFixed(dp)}</td>`).join("") +
        `</tr>`;
    }).join("") + `</tbody></table>`;
}

/** Small inline histogram, drawn as an SVG bar chart. */
function histogramSvg(hist, mean) {
  if (!hist?.counts?.length) return "";
  const counts = hist.counts;
  const max = Math.max(...counts) || 1;
  const w = 260, h = 64, bw = w / counts.length;
  const bars = counts.map((c, i) =>
    `<rect x="${(i * bw).toFixed(2)}" y="${(h - (c / max) * h).toFixed(2)}" ` +
    `width="${(bw - 0.6).toFixed(2)}" height="${((c / max) * h).toFixed(2)}" ` +
    `fill="#4dd0e1" opacity="0.85"/>`).join("");
  const mx = (mean * w).toFixed(1);
  return `<svg viewBox="0 0 ${w} ${h + 14}" width="100%" height="78" ` +
    `role="img" aria-label="SVF distribution">` +
    bars +
    `<line x1="${mx}" y1="0" x2="${mx}" y2="${h}" stroke="#ff8a3d" stroke-width="1.5"/>` +
    `<text x="0" y="${h + 11}" fill="#97a3b2" font-size="9">0</text>` +
    `<text x="${w / 2 - 8}" y="${h + 11}" fill="#97a3b2" font-size="9">0.5</text>` +
    `<text x="${w - 10}" y="${h + 11}" fill="#97a3b2" font-size="9">1</text>` +
    `</svg>`;
}

/**
 * The Spacematrix diagram (Berghauser Pont & Haupt 2010), drawn from the
 * per-cell points in density_summary.json.
 *
 * GSI on x, FSI on y. Those two fix the other two indicators, so the diagram
 * carries all four: L = FSI/GSI is a straight line through the origin, and
 * OSR = (1-GSI)/FSI is a curve. Plotting it is the whole point of computing
 * Spacematrix rather than a bare density figure — fabric types separate by
 * WHERE they sit, not by any single number, and two cells with the same FSI
 * can be a low sprawl or a tall point block depending on GSI.
 *
 * Points are coloured by buurt because that is the finding: a combined cloud
 * hides that the two neighbourhoods occupy different regions.
 *
 * There is a static matplotlib version in docs/fig_spacematrix.png. This one is
 * in the dashboard, and when the proposed massing exists it can be overplotted
 * to show the new fabric moving relative to the existing two.
 */
function spacematrixSvg(points, perBuurt) {
  if (!points?.length) return "";

  const W = 268, H = 200, PL = 30, PB = 22, PT = 6, PR = 6;
  const iw = W - PL - PR, ih = H - PT - PB;

  // Fixed axis maxima rather than data-driven ones: the scales must not move
  // when a scenario is added, or the "fabric moved" comparison is meaningless.
  const GMAX = 0.9, FMAX = 4.0;
  const px = (g) => PL + Math.min(g / GMAX, 1) * iw;
  const py = (f) => PT + ih - Math.min(f / FMAX, 1) * ih;

  const parts = [];

  // --- OSR isolines (curves): FSI = (1 - GSI) / OSR ------------------------
  for (const osr of [0.2, 0.5, 1.0, 2.0]) {
    const pts = [];
    for (let i = 0; i <= 40; i++) {
      const g = (i / 40) * GMAX;
      const f = (1 - g) / osr;
      if (f > FMAX || f < 0) continue;
      pts.push(`${px(g).toFixed(1)},${py(f).toFixed(1)}`);
    }
    if (pts.length < 2) continue;
    parts.push(`<polyline points="${pts.join(" ")}" fill="none" stroke="#3a4655" ` +
               `stroke-width="0.7" stroke-dasharray="1 2"/>`);
    const [lx, ly] = pts[0].split(",");
    parts.push(`<text x="${(+lx + 2).toFixed(1)}" y="${(+ly - 2).toFixed(1)}" ` +
               `fill="#5d6b7d" font-size="7">OSR ${osr}</text>`);
  }

  // --- L isolines (straight): FSI = L * GSI --------------------------------
  for (const L of [1, 2, 3, 4, 6]) {
    const gEnd = Math.min(GMAX, FMAX / L);
    parts.push(`<line x1="${px(0)}" y1="${py(0)}" x2="${px(gEnd).toFixed(1)}" ` +
               `y2="${py(L * gEnd).toFixed(1)}" stroke="#2f3a47" stroke-width="0.7"/>`);
    parts.push(`<text x="${(px(gEnd) - 1).toFixed(1)}" y="${(py(L * gEnd) + (L >= 4 ? 8 : -2)).toFixed(1)}" ` +
               `fill="#5d6b7d" font-size="7" text-anchor="end">L ${L}</text>`);
  }

  // --- the cells ----------------------------------------------------------
  const COL = { Bloemhof: "#4dd0e1", Hillesluis: "#ff8a3d" };
  for (const pt of points) {
    if (pt.gsi == null || pt.fsi == null) continue;
    const c = COL[pt.buurt] || "#5b6675";
    // Cells outside both buurten are context, not findings: drawn smaller and
    // dimmer so they cannot be mistaken for part of the neighbourhood.
    const r = pt.buurt ? 2.4 : 1.6;
    parts.push(`<circle cx="${px(pt.gsi).toFixed(1)}" cy="${py(pt.fsi).toFixed(1)}" ` +
               `r="${r}" fill="${c}" opacity="${pt.buurt ? 0.6 : 0.3}"/>`);
  }

  // --- the buurt aggregates, as crosses -----------------------------------
  for (const [name, b] of Object.entries(perBuurt || {})) {
    if (b?.gsi == null || b?.fsi == null) continue;
    const c = COL[name] || "#e7ecf2";
    const X = px(b.gsi), Y = py(b.fsi);
    parts.push(`<line x1="${(X - 5).toFixed(1)}" y1="${Y.toFixed(1)}" x2="${(X + 5).toFixed(1)}" ` +
               `y2="${Y.toFixed(1)}" stroke="${c}" stroke-width="1.6"/>` +
               `<line x1="${X.toFixed(1)}" y1="${(Y - 5).toFixed(1)}" x2="${X.toFixed(1)}" ` +
               `y2="${(Y + 5).toFixed(1)}" stroke="${c}" stroke-width="1.6"/>`);
  }

  // --- axes ---------------------------------------------------------------
  parts.push(`<line x1="${PL}" y1="${PT + ih}" x2="${PL + iw}" y2="${PT + ih}" ` +
             `stroke="#46525f" stroke-width="1"/>`);
  parts.push(`<line x1="${PL}" y1="${PT}" x2="${PL}" y2="${PT + ih}" ` +
             `stroke="#46525f" stroke-width="1"/>`);
  for (const g of [0, 0.3, 0.6, 0.9]) {
    parts.push(`<text x="${px(g).toFixed(1)}" y="${H - PB + 10}" fill="#97a3b2" ` +
               `font-size="8" text-anchor="middle">${g}</text>`);
  }
  for (const f of [0, 1, 2, 3, 4]) {
    parts.push(`<text x="${PL - 4}" y="${(py(f) + 3).toFixed(1)}" fill="#97a3b2" ` +
               `font-size="8" text-anchor="end">${f}</text>`);
  }
  parts.push(`<text x="${(PL + iw / 2).toFixed(0)}" y="${H - 1}" fill="#97a3b2" ` +
             `font-size="8" text-anchor="middle">GSI (coverage)</text>`);
  parts.push(`<text x="9" y="${(PT + ih / 2).toFixed(0)}" fill="#97a3b2" font-size="8" ` +
             `text-anchor="middle" transform="rotate(-90 9 ${(PT + ih / 2).toFixed(0)})">FSI</text>`);

  return `<svg viewBox="0 0 ${W} ${H}" width="100%" height="190" role="img" ` +
    `aria-label="Spacematrix: GSI against FSI, one point per 100 m grid cell">` +
    parts.join("") + `</svg>` +
    `<p class="muted" style="margin:2px 0 0">` +
    `<span style="color:${COL.Bloemhof}">●</span> Bloemhof ` +
    `<span style="color:${COL.Hillesluis}">●</span> Hillesluis ` +
    `<span style="color:#5b6675">●</span> outside both · crosses are the buurt ` +
    `aggregates. Thin lines are storeys (L), dashed are open space ratio (OSR).</p>`;
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
    const v = pts.filter((q) => q.buurt === n && q.fsi != null).map((q) => q.fsi);
    if (!v.length) return "";
    gridMean[n] = v.reduce((a, c) => a + c, 0) / v.length;
  }
  const [a, b] = names;
  const buurtOrder = Math.sign(dens.per_buurt[a].fsi - dens.per_buurt[b].fsi);
  const gridOrder = Math.sign(gridMean[a] - gridMean[b]);
  if (buurtOrder === 0 || gridOrder === 0 || buurtOrder === gridOrder) return "";

  const looser = buurtOrder < 0 ? a : b;   // lower FSI over the whole buurt
  return `<p class="muted"><strong>The two scales disagree.</strong> ` +
    `${looser} has the lower FSI over the whole buurt ` +
    `(${dens.per_buurt[looser].fsi.toFixed(3)} against ` +
    `${dens.per_buurt[looser === a ? b : a].fsi.toFixed(3)}) but the higher mean ` +
    `over built cells (${gridMean[looser].toFixed(2)} against ` +
    `${gridMean[looser === a ? b : a].toFixed(2)}). The buurt figure divides by all ` +
    `its land, gaps included; the grid mean only averages cells with at least ` +
    `${dens.parameters.min_buildings_per_cell} buildings. Quote the unit with the number.</p>`;
}

export async function setup(ctx) {
  const body = ctx.registerPanel({
    id: "indicators",
    title: "Urban morphology",
    subtitle: "Sky View Factor · density · height variation · land-use mix",
    order: 30,
  });

  /* ---- Sky View Factor -------------------------------------------------- */
  const svf = await ctx.loadJson("../data/processed/svf_summary.json", { quiet: true });
  const svfBox = document.createElement("div");
  body.appendChild(svfBox);

  if (svf?.open_ground) {
    // The clipped figure: the raster covers the bounding box, which takes in
    // the Maashaven where SVF is ~1.0 and would flatter the neighbourhood.
    const g = svf.combined?.open_ground || svf.open_ground;
    addSvfOverlay(ctx, svf);
    svfBox.innerHTML =
      `<h4>Sky View Factor</h4>` +
      `<table class="kv"><tbody>` +
      `<tr><td>mean</td><td>${g.mean.toFixed(3)}</td></tr>` +
      `<tr><td>median</td><td>${g.median.toFixed(3)}</td></tr>` +
      `<tr><td>p05 – p95</td><td>${g.p05.toFixed(2)} – ${g.p95.toFixed(2)}</td></tr>` +
      `</tbody></table>` +
      histogramSvg(svf.histogram, g.mean) +
      perBuurtTable(
        Object.fromEntries(Object.entries(svf.per_buurt || {}).map(
          ([n, v]) => [n, { svf: v.open_ground?.mean }])),
        [["svf", "SVF", 3]]) +
      `<p class="muted">At ${svf.parameters.observer_height_m} m above ground on open ` +
      `ground only (streets, gardens, squares). ${svf.parameters.n_directions} directions, ` +
      `${svf.parameters.search_radius_m} m radius, ${svf.parameters.cell_size_m} m cells. ` +
      `Cosine-weighted; the plain solid-angle value is ` +
      `${(svf.combined?.open_ground_geometric?.mean
          ?? svf.open_ground_geometric?.mean)?.toFixed(3) ?? "—"}. ` +
      `Toggle the map overlay under <em>Analysis</em>.</p>`;
  } else {
    ctx.placeholder(svfBox, {
      what: "Sky View Factor not computed yet.",
      produces: "data/processed/svf_summary.json",
      owner: "analysis/morphology/sky_view_factor.py",
    });
  }

  /* ---- direct sun / shadow ---------------------------------------------- */
  const shadow = await ctx.loadJson("../data/processed/shadow_summary.json",
                                    { quiet: true });
  const shadowBox = document.createElement("div");
  body.appendChild(shadowBox);

  if (shadow?.open_ground_sunlit_hours) {
    const g = shadow.combined?.open_ground_sunlit_hours
      || shadow.open_ground_sunlit_hours;
    addShadowOverlay(ctx, shadow);
    shadowBox.innerHTML =
      `<h4>Direct sun</h4>` +
      `<table class="kv"><tbody>` +
      `<tr><td>mean sun</td><td>${g.mean.toFixed(1)} h</td></tr>` +
      `<tr><td>median</td><td>${g.median.toFixed(1)} h</td></tr>` +
      `<tr><td>p05 – p95</td><td>${g.p05.toFixed(1)} – ${g.p95.toFixed(1)} h</td></tr>` +
      `</tbody></table>` +
      perBuurtTable(
        Object.fromEntries(Object.entries(shadow.per_buurt || {}).map(
          ([n, v]) => [n, { sun: v.open_ground_sunlit_hours?.mean }])),
        [["sun", "sun h", 1]]) +
      `<p class="muted">Hours of direct sun on open ground on ${shadow.date}, ` +
      `of ${shadow.daylight_hours.toFixed(1)} h of daylight. Ray-cast from the ` +
      `AHN surface every ${shadow.parameters.step_minutes} min; clear-sky, so an ` +
      `upper bound. Toggle the map overlay under <em>Analysis</em>.</p>`;
  } else {
    ctx.placeholder(shadowBox, {
      what: "Shadow / direct-sun analysis not computed yet.",
      produces: "data/processed/shadow_summary.json",
      owner: "analysis/morphology/shadows.py",
    });
  }

  /* ---- time-of-day sun scrubber ----------------------------------------- */
  /* A live sun scrubber: turn on the scene shadow map and move the clock, so
   * the 3DBAG buildings cast real shadows as you drag. Given its OWN dashboard
   * card near the top (order 6) rather than buried among the indicators, so it
   * is easy to find. This is the instantaneous companion to the direct-sun map,
   * which is the whole-day total. */
  {
    const { Cesium, viewer } = ctx;
    const scene = viewer.scene;
    scene.shadowMap.enabled = true;
    scene.shadowMap.softShadows = true;
    scene.shadowMap.size = 2048;
    scene.shadowMap.maximumDistance = 5000;
    scene.globe.enableLighting = true;
    viewer.clock.shouldAnimate = false;

    // Reference days for solar access: the equinox is the neutral average-sun
    // day and the planning standard; the solstices bracket best and worst case.
    // shadows.py defaults to the equinox, so match it here, and start on the
    // analysis day if it ran on one of these.
    const DAYS = [
      { label: "Equinox", date: "2026-03-20" },
      { label: "Summer",  date: "2026-06-21" },
      { label: "Winter",  date: "2026-12-21" },
    ];
    let dateStr = DAYS.find((d) => d.date === shadow?.date)?.date || "2026-03-20";
    const pad = (n) => String(n).padStart(2, "0");
    // NL is UTC+2 in summer, +1 in winter — from the month, only wrong within
    // the DST changeover, which none of the reference days fall in.
    const nlOffset = (d) =>
      Number(d.slice(5, 7)) >= 4 && Number(d.slice(5, 7)) <= 10 ? "+02:00" : "+01:00";

    const sunBody = ctx.registerPanel({
      id: "sun",
      title: "Sun & shadows",
      subtitle: "drag to move the sun — buildings cast live shadows",
      order: 6,
    });
    sunBody.innerHTML =
      `<div class="seg" id="sunDay">` +
      DAYS.map((d) =>
        `<button data-date="${d.date}"${d.date === dateStr ? ' class="on"' : ""}>` +
        `${d.label}</button>`).join("") +
      `</div>` +
      `<label class="slider">` +
      `<span>local time <output id="sunOut">12:00</output> · ` +
      `<span id="sunDate">${dateStr}</span></span>` +
      `<input type="range" id="sunTime" min="240" max="1320" step="10" value="720">` +
      `</label>` +
      `<label class="lrow"><input type="checkbox" id="sunShadows" checked>` +
      `<span>Cast shadows</span></label>` +
      `<p class="muted">One instant on the chosen reference day. The whole-day ` +
      `direct-sun total is under <em>Urban morphology</em>, the map overlay ` +
      `under <em>Analysis</em>.</p>`;

    const slider = sunBody.querySelector("#sunTime");
    const out = sunBody.querySelector("#sunOut");
    const dateEl = sunBody.querySelector("#sunDate");
    const setTime = (minutes) => {
      const hh = Math.floor(minutes / 60);
      const mm = minutes % 60;
      out.textContent = `${pad(hh)}:${pad(mm)}`;
      viewer.clock.currentTime = Cesium.JulianDate.fromIso8601(
        `${dateStr}T${pad(hh)}:${pad(mm)}:00${nlOffset(dateStr)}`);
      viewer.scene.requestRender?.();
    };
    slider.addEventListener("input", (e) => setTime(Number(e.target.value)));

    const dayBtns = [...sunBody.querySelectorAll("#sunDay button")];
    dayBtns.forEach((b) => b.addEventListener("click", () => {
      dayBtns.forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      dateStr = b.dataset.date;
      dateEl.textContent = dateStr;
      setTime(Number(slider.value));
    }));

    sunBody.querySelector("#sunShadows").addEventListener("change", (e) => {
      scene.shadowMap.enabled = e.target.checked;
      viewer.scene.requestRender?.();
    });

    setTime(720);
  }

  /* ---- density and height variation ------------------------------------- */
  const dens = await ctx.loadJson("../data/processed/density_summary.json",
                                  { quiet: true });
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
      `<tr><td>OSR</td><td>${b.osr.toFixed(2)}</td></tr>` +
      `<tr><td>height</td><td>${b.height_m.mean.toFixed(1)} m ± ${b.height_m.std.toFixed(1)}</td></tr>` +
      `<tr><td>tallest</td><td>${b.height_m.max.toFixed(1)} m</td></tr>` +
      `</tbody></table>` +
      perBuurtTable(dens.per_buurt, [
        ["gsi", "GSI", 3], ["fsi", "FSI", 3], ["layers", "storeys", 2],
      ]) +
      spacematrixSvg(dens.spacematrix, dens.per_buurt) +
      `<p class="muted">Spacematrix over ${b.land_area_ha} ha, ` +
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

  /* ---- land-use mix ------------------------------------------------------ */
  const lu = await ctx.loadJson("../data/processed/landuse_summary.json",
                                { quiet: true });
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
      comp.map((x) =>
        `<tr><td>${x.category}</td><td>${(x.share * 100).toFixed(1)} %</td></tr>`).join("") +
      `</tbody></table>` +
      perBuurtTable(lu.per_buurt, [
        ["shannon_area", "Shannon", 3], ["simpson_area", "Simpson", 3],
      ]) +
      `<p class="muted">Normalised Shannon entropy over ` +
      `${lu.parameters.n_categories_in_scheme} BAG use classes, weighted by ` +
      `usable floor area. 0 = one use only, 1 = an even mix. ` +
      `Built floor space only — parks, water and streets are not in BAG; ` +
      `use GSI above for the built/unbuilt split. ` +
      `Toggle the grid under <em>Analysis</em>.</p>`;
  } else {
    ctx.placeholder(luBox, {
      what: "Land-use mix not computed yet.",
      produces: "data/processed/landuse_summary.json",
      owner: "analysis/morphology/landuse_mix.py",
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
        const shown = v == null ? "—" : `${Number(v).toFixed(2)}${unit}`;
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
