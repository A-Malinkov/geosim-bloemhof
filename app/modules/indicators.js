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
      `<p class="muted">Spacematrix over ${b.land_area_ha} ha, ` +
      `${b.n_buildings.toLocaleString("en-GB")} buildings. Grid mean FSI ` +
      `${g.fsi.mean.toFixed(2)} across ${g.n_cells_used} cells of ` +
      `${dens.parameters.cell_size_m} m. Toggle the grid under <em>Analysis</em>.</p>`;
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
