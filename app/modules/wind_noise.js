/* =============================================================================
 * modules/wind_noise.js  —  component 5: wind + noise simulation
 * OWNER: <put your name here>
 *
 * Pedestrian-level wind comfort and road-traffic noise, baseline vs design.
 * Computed in  analysis/wind_noise/  and written as one JSON per scenario:
 *   data/processed/wind_baseline.json,  wind_scenario_a.json,  wind_scenario_b.json
 *   data/processed/noise_baseline.json, ...
 *
 * Expected shape — a regular grid, so it can be drawn as a coloured surface:
 * {
 *   "quantity": "wind_speed_ratio" | "noise_laeq_db",
 *   "level_m": 1.75,
 *   "bbox_rd": [xmin, ymin, xmax, ymax],   // EPSG:28992
 *   "shape": [ny, nx],
 *   "values": [[...], ...],                // row-major, null = no data
 *   "summary": { "mean": 0.42, "p95": 0.88, "exceedance_frac": 0.07 }
 * }
 * ========================================================================== */

const QUANTITIES = [
  { id: "wind",  label: "Wind (pedestrian level, 1.75 m)", prefix: "wind" },
  { id: "noise", label: "Road-traffic noise (Lden, 1.75 m)", prefix: "noise" },
];

function fileFor(ctx, prefix, scenario) {
  const p = ctx.config.dataSources.processed;
  const key =
    prefix === "wind"
      ? { baseline: "windBaseline", scenario_a: "windScenarioA", scenario_b: "windScenarioB" }[scenario]
      : { baseline: "noiseBaseline", scenario_a: "noiseScenarioA", scenario_b: "noiseScenarioB" }[scenario];
  // noise scenario files are not in config yet; derive the path by convention.
  return p[key] || `../data/processed/${prefix}_${scenario}.json`;
}

/* Noise bands: the Bkl reference values (53, 70 dB) are band edges, and the
 * colours are the report figure's (magma_r, analysis/wind_noise/noise.py),
 * so the map and docs/fig_noise_*.png read the same. */
const NOISE_EDGES = [35, 40, 45, 50, 53, 55, 60, 65, 70, 75, 80];
const NOISE_COLOURS = [
  "#fdda9c", "#feb67c", "#fc9065", "#f66c5c", "#e34e65", "#c53c74",
  "#a6317d", "#862781", "#671b80", "#491078", "#271258", "#0d0a29",
];
const noiseBand = (v) => {
  let i = 0;
  while (i < NOISE_EDGES.length && v >= NOISE_EDGES[i]) i++;
  return i;
};
const noiseLabel = (i) =>
  i === 0 ? `< ${NOISE_EDGES[0]}`
  : i === NOISE_EDGES.length ? `${NOISE_EDGES[i - 1]}+`
  : `${NOISE_EDGES[i - 1]}–${NOISE_EDGES[i]}`;

/* The grid as a PNG data URL, one cell per UPSCALE×UPSCALE block. The grid
 * is already warped to EPSG:4326 by noise.py (row 0 = north), so it can be
 * draped on its bbox_wgs84 as is; draping an RD-aligned grid on a lon/lat
 * rectangle would shift it ~30 m. Upscaling with flat blocks keeps the band
 * edges crisp, where Cesium's linear filtering would blur 5 m cells. */
function noiseImage(data) {
  const [ny, nx] = data.shape;
  // Up to 4x, but keep the long side within 4096 px — a texture size every
  // GPU accepts. At a 2 m grid that is already ~2x.
  const UPSCALE = Math.max(1, Math.min(4, Math.floor(4096 / Math.max(nx, ny))));
  const small = document.createElement("canvas");
  small.width = nx;
  small.height = ny;
  const sctx = small.getContext("2d");
  const img = sctx.createImageData(nx, ny);
  const rgb = NOISE_COLOURS.map((h) => [1, 3, 5].map((k) => parseInt(h.slice(k, k + 2), 16)));
  for (let r = 0; r < ny; r++) {
    const row = data.values[r];
    for (let c = 0; c < nx; c++) {
      const v = row[c];
      if (v == null) continue;                      // transparent: buildings, outside
      const [R, G, B] = rgb[noiseBand(v)];
      const o = 4 * (r * nx + c);
      img.data[o] = R; img.data[o + 1] = G; img.data[o + 2] = B; img.data[o + 3] = 255;
    }
  }
  sctx.putImageData(img, 0, 0);
  const big = document.createElement("canvas");
  big.width = nx * UPSCALE;
  big.height = ny * UPSCALE;
  const bctx = big.getContext("2d");
  bctx.imageSmoothingEnabled = false;
  bctx.drawImage(small, 0, 0, big.width, big.height);
  return big.toDataURL("image/png");
}

function noiseLegend() {
  const items = NOISE_COLOURS.map((c, i) =>
    `<span style="display:inline-flex;align-items:center;gap:3px;margin:0 6px 2px 0">` +
    `<i style="width:10px;height:10px;background:${c};display:inline-block;border-radius:2px"></i>` +
    `${noiseLabel(i)}</span>`).reverse().join("");
  return `<div class="muted" style="font-size:10px;line-height:1.5">Lden, dB: ${items}</div>`;
}

export async function setup(ctx) {
  const { Cesium, viewer } = ctx;
  const body = ctx.registerPanel({
    id: "wind_noise",
    title: "Wind & noise",
    subtitle: "baseline vs. design, pedestrian level",
    order: 40,
  });

  body.innerHTML = `
    <div class="seg" id="wnSeg">
      ${QUANTITIES.map((q, i) =>
        `<button data-q="${q.id}" class="${i === 0 ? "on" : ""}">${q.id}</button>`).join("")}
    </div>
    <div id="wnOut"></div>`;

  const out = body.querySelector("#wnOut");
  let quantity = "wind";
  let scenario = ctx.scenario();

  /* ---- noise map layer ---------------------------------------------------
   * Off by default and built on first tick, so startup does not wait on it.
   * Follows the scenario switch; a scenario without a noise run shows nothing
   * rather than leaving the previous scenario's map up. */
  let noiseShown = false;
  let noiseLayer = null;
  let noiseFor = null;                              // scenario the layer shows
  async function refreshNoiseLayer() {
    if (!noiseShown) {
      if (noiseLayer) noiseLayer.show = false;
      return;
    }
    if (noiseLayer && noiseFor === scenario) {
      noiseLayer.show = true;
      return;
    }
    if (noiseLayer) {
      viewer.imageryLayers.remove(noiseLayer, true);
      noiseLayer = null;
    }
    const want = scenario;
    const data = await ctx.loadJson(fileFor(ctx, "noise", want), { quiet: true });
    if (want !== scenario || !noiseShown) return;   // switched while loading
    noiseFor = want;
    if (!data?.values || !data.bbox_wgs84) {
      ctx.note(`Noise map: no run for ${want}`, "warn");
      return;
    }
    const [w, s, e, n] = data.bbox_wgs84;
    try {
      const provider = await Cesium.SingleTileImageryProvider.fromUrl(
        noiseImage(data), { rectangle: Cesium.Rectangle.fromDegrees(w, s, e, n) });
      if (want !== scenario || !noiseShown) return;
      noiseLayer = viewer.imageryLayers.addImageryProvider(provider);
      noiseLayer.alpha = 0.8;
    } catch (err) {
      console.warn("[wind_noise] noise overlay failed", err);
      ctx.note("Noise map: failed", "err");
    }
  }
  ctx.registerLayer({
    id: "noiseOverlay",
    label: "Road-traffic noise, Lden (NoiseModelling)",
    group: "Analysis",
    show: false,
    onToggle: (visible) => { noiseShown = visible; refreshNoiseLayer(); },
  });

  body.querySelectorAll("#wnSeg button").forEach((b) =>
    b.addEventListener("click", () => {
      body.querySelectorAll("#wnSeg button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      quantity = b.dataset.q;
      render();
    }),
  );

  async function render() {
    const q = QUANTITIES.find((x) => x.id === quantity);
    const path = fileFor(ctx, q.prefix, scenario);
    const data = await ctx.loadJson(path, { quiet: true });

    if (!data) {
      ctx.placeholder(out, {
        what: `${q.label} — not simulated yet for "${scenario}".`,
        produces: path.replace("../", ""),
        owner: "analysis/wind_noise/ + app/modules/wind_noise.js",
      });
      return;
    }

    const s = data.summary || {};
    const isNoise = q.id === "noise";
    const db = (v) => (v == null ? "—" : `${v} dB`);
    const pct = (v) => (v == null ? "—" : (v * 100).toFixed(1) + " %");
    out.innerHTML =
      `<table class="kv"><tbody>` +
      `<tr><td>quantity</td><td>${data.label ?? data.quantity ?? "—"}</td></tr>` +
      `<tr><td>level</td><td>${data.level_m ?? "—"} m</td></tr>` +
      `<tr><td>mean</td><td>${isNoise ? db(s.mean) : s.mean ?? "—"}</td></tr>` +
      `<tr><td>p95</td><td>${isNoise ? db(s.p95) : s.p95 ?? "—"}</td></tr>` +
      (isNoise
        ? `<tr><td>≥ ${s.exceedance_db ?? 53} dB</td><td>${pct(s.exceedance_frac)}</td></tr>` +
          `<tr><td>≥ ${s.limit_db ?? 70} dB</td><td>${pct(s.limit_frac)}</td></tr>`
        : `<tr><td>exceedance</td><td>${pct(s.exceedance_frac)}</td></tr>`) +
      `</tbody></table>` +
      (isNoise
        ? noiseLegend() +
          `<p class="muted">${s.unit ?? ""}. ${s.exceedance_db ?? 53} and ` +
          `${s.limit_db ?? 70} dB are the Bkl standard and limit values for ` +
          `municipal roads — façade values, shown here for reference. Traffic ` +
          `is estimated from OSM road type, not counted. Map: ` +
          `<em>Analysis → Road-traffic noise</em>.</p>`
        : "");
  }

  ctx.onScenarioChange((s) => { scenario = s; render(); refreshNoiseLayer(); });
}
