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
  try {
    const layer = viewer.imageryLayers.addImageryProvider(
      new Cesium.SingleTileImageryProvider({
        url: "../data/processed/svf_overlay.png",
        rectangle: Cesium.Rectangle.fromDegrees(west, south, east, north),
        tileWidth: 512,
        tileHeight: 512,
      }),
    );
    layer.show = false;
    layer.alpha = 0.85;
    ctx.registerLayer({
      id: "svfOverlay",
      label: "Sky View Factor (AHN)",
      group: "Analysis",
      show: false,
      target: layer,
    });
    return layer;
  } catch (err) {
    console.warn("[indicators] SVF overlay failed", err);
    return null;
  }
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
    const g = svf.open_ground;
    await addSvfOverlay(ctx, svf);
    svfBox.innerHTML =
      `<h4>Sky View Factor</h4>` +
      `<table class="kv"><tbody>` +
      `<tr><td>mean</td><td>${g.mean.toFixed(3)}</td></tr>` +
      `<tr><td>median</td><td>${g.median.toFixed(3)}</td></tr>` +
      `<tr><td>p05 – p95</td><td>${g.p05.toFixed(2)} – ${g.p95.toFixed(2)}</td></tr>` +
      `</tbody></table>` +
      histogramSvg(svf.histogram, g.mean) +
      `<p class="muted">At ${svf.parameters.observer_height_m} m above ground on open ` +
      `ground only (streets, gardens, squares). ${svf.parameters.n_directions} directions, ` +
      `${svf.parameters.search_radius_m} m radius, ${svf.parameters.cell_size_m} m cells. ` +
      `Cosine-weighted; the plain solid-angle value is ` +
      `${svf.open_ground_geometric?.mean?.toFixed(3) ?? "—"}. ` +
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

  if (dens?.buurt) {
    await addDensityGrid(ctx);
    const b = dens.buurt;
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
      `<p class="muted">Spacematrix over ${b.surveyed_area_ha} ha ` +
      `(${Math.round(b.coverage_fraction * 100)}% of ${b.name}), ` +
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
