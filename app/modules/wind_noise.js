/* =============================================================================
 * modules/wind_noise.js - component 5: wind + noise simulation
 * OWNER: <put your name here>
 *
 * Pedestrian-level wind comfort and road-traffic noise, baseline vs design.
 * Computed in  analysis/wind_noise/  and written as one JSON per scenario:
 *   data/processed/wind_<scenario>.json   (wind_cfd_import.py, from an OpenFOAM run)
 *   data/processed/noise_<scenario>.json  (noise.py)
 *
 * Expected shape: a regular grid, so it can be drawn as a coloured surface:
 * {
 *   "quantity": "wind_speed_ratio" | "noise_lden_db",
 *   "level_m": 1.5,
 *   "bbox_rd": [xmin, ymin, xmax, ymax],   // EPSG:28992
 *   "bbox_wgs84": [west, south, east, north],  // of the grid warped to EPSG:4326
 *   "shape": [ny, nx],
 *   "values": [[...], ...],                // row-major, row 0 = north, null = no data
 *   "summary": { "mean": 0.42, "p95": 0.88, "exceedance_frac": 0.07 }
 * }
 * ========================================================================== */

const QUANTITIES = [
  { id: "wind",  label: "Wind (pedestrian level, 1.5 m)", prefix: "wind" },
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
const noiseLabel = (i) =>
  i === 0 ? `< ${NOISE_EDGES[0]}`
  : i === NOISE_EDGES.length ? `${NOISE_EDGES[i - 1]}+`
  : `${NOISE_EDGES[i - 1]}–${NOISE_EDGES[i]}`;

/* The grid as a PNG data URL, one cell per UPSCALE×UPSCALE block, each value
 * coloured by the band it falls in. The grid is already warped to EPSG:4326
 * by the Python side (row 0 = north), so it can be draped on its bbox_wgs84
 * as is; draping an RD-aligned grid on a lon/lat rectangle would shift it
 * ~30 m. Upscaling with flat blocks keeps the band edges crisp, where
 * Cesium's linear filtering would blur 5 m cells. */
function gridImage(data, edges, colours) {
  const band = (v) => {
    let i = 0;
    while (i < edges.length && v >= edges[i]) i++;
    return i;
  };
  const [ny, nx] = data.shape;
  // Up to 4x, but keep the long side within 4096 px: a texture size every
  // GPU accepts. At a 2 m grid that is already ~2x.
  const UPSCALE = Math.max(1, Math.min(4, Math.floor(4096 / Math.max(nx, ny))));
  const small = document.createElement("canvas");
  small.width = nx;
  small.height = ny;
  const sctx = small.getContext("2d");
  const img = sctx.createImageData(nx, ny);
  const rgb = colours.map((h) => [1, 3, 5].map((k) => parseInt(h.slice(k, k + 2), 16)));
  for (let r = 0; r < ny; r++) {
    const row = data.values[r];
    for (let c = 0; c < nx; c++) {
      const v = row[c];
      if (v == null) continue;                      // transparent: buildings, outside
      const [R, G, B] = rgb[band(v)];
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

function legend(title, edges, colours, label) {
  const items = colours.map((c, i) =>
    `<span style="display:inline-flex;align-items:center;gap:3px;margin:0 6px 2px 0">` +
    `<i style="width:10px;height:10px;background:${c};display:inline-block;border-radius:2px"></i>` +
    `${label(i)}</span>`).reverse().join("");
  return `<div class="muted" style="font-size:10px;line-height:1.5">${title}: ${items}</div>`;
}
const noiseLegend = () => legend("Lden, dB", NOISE_EDGES, NOISE_COLOURS, noiseLabel);

/* Wind: the ratio of the local speed to the undisturbed inflow at the same
 * height (analysis/wind_noise/wind_cfd_import.py). Diverging around 1:
 * blue is sheltered, red is faster than open country. */
const WIND_EDGES = [0.25, 0.5, 0.75, 0.9, 1.1, 1.25, 1.5, 2.0];
const WIND_COLOURS = [
  "#2166ac", "#4393c3", "#92c5de", "#d1e5f0", "#f7f7f7",
  "#fddbc7", "#f4a582", "#d6604d", "#b2182b",
];
const windLabel = (i) =>
  i === 0 ? `< ${WIND_EDGES[0]}`
  : i === WIND_EDGES.length ? `${WIND_EDGES[i - 1]}+`
  : `${WIND_EDGES[i - 1]}–${WIND_EDGES[i]}`;
const windLegend = () => legend("speed ÷ inflow", WIND_EDGES, WIND_COLOURS, windLabel);

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

  /* ---- map layers ---------------------------------------------------------
   * One draped grid per quantity. Off by default and built on first tick, so
   * startup does not wait on it. Follows the scenario switch; a scenario
   * without a run shows nothing rather than leaving the previous map up. */
  function gridLayer({ prefix, name, edges, colours }) {
    let shown = false;
    let layer = null;
    let layerFor = null;                            // scenario the layer shows
    async function refresh() {
      if (!shown) {
        if (layer) layer.show = false;
        return;
      }
      if (layer && layerFor === scenario) {
        layer.show = true;
        return;
      }
      if (layer) {
        viewer.imageryLayers.remove(layer, true);
        layer = null;
      }
      const want = scenario;
      const data = await ctx.loadJson(fileFor(ctx, prefix, want), { quiet: true });
      if (want !== scenario || !shown) return;      // switched while loading
      layerFor = want;
      if (!data?.values || !data.bbox_wgs84) {
        ctx.note(`${name}: no run for ${want}`, "warn");
        return;
      }
      const [w, s, e, n] = data.bbox_wgs84;
      try {
        const provider = await Cesium.SingleTileImageryProvider.fromUrl(
          gridImage(data, edges, colours), { rectangle: Cesium.Rectangle.fromDegrees(w, s, e, n) });
        if (want !== scenario || !shown) return;
        layer = viewer.imageryLayers.addImageryProvider(provider);
        layer.alpha = 0.8;
      } catch (err) {
        console.warn(`[wind_noise] ${prefix} overlay failed`, err);
        ctx.note(`${name}: failed`, "err");
      }
    }
    return { refresh, toggle: (visible) => { shown = visible; refresh(); } };
  }

  const noiseMap = gridLayer({ prefix: "noise", name: "Noise map", edges: NOISE_EDGES, colours: NOISE_COLOURS });
  ctx.registerLayer({
    id: "noiseOverlay",
    label: "Road-traffic noise, Lden (NoiseModelling)",
    group: "Analysis",
    show: false,
    onToggle: noiseMap.toggle,
  });
  const windMap = gridLayer({ prefix: "wind", name: "Wind map", edges: WIND_EDGES, colours: WIND_COLOURS });
  ctx.registerLayer({
    id: "windOverlay",
    label: "Pedestrian wind, 1.5 m (OpenFOAM)",
    group: "Wind & noise",
    show: false,
    onToggle: windMap.toggle,
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
        what: `${q.label}, not simulated yet for "${scenario}".`,
        produces: path.replace("../", ""),
        owner: "analysis/wind_noise/ + app/modules/wind_noise.js",
      });
      return;
    }

    const s = data.summary || {};
    const isNoise = q.id === "noise";
    const db = (v) => (v == null ? "-" : `${v} dB`);
    const pct = (v) => (v == null ? "-" : (v * 100).toFixed(1) + " %");
    if (!isNoise) {
      const sv = data.solver || {};
      out.innerHTML =
        `<table class="kv"><tbody>` +
        `<tr><td>quantity</td><td>${data.label ?? data.quantity ?? "-"}</td></tr>` +
        `<tr><td>mean ratio</td><td>${s.mean ?? "-"} (${s.mean_ms ?? "-"} m/s)</td></tr>` +
        `<tr><td>p95 ratio</td><td>${s.p95 ?? "-"} (${s.p95_ms ?? "-"} m/s)</td></tr>` +
        `<tr><td>&gt; ${s.exceedance_ratio ?? 1.1}× inflow</td><td>${pct(s.exceedance_frac)}</td></tr>` +
        `<tr><td>&lt; ${s.sheltered_ratio ?? 0.5}× inflow</td><td>${pct(s.sheltered_frac)}</td></tr>` +
        `<tr><td>inflow at ${s.ref_height_m ?? data.level_m ?? "-"} m</td><td>${s.ref_ms ?? "-"} m/s</td></tr>` +
        `<tr><td>solver</td><td>${sv.iterations ?? "-"} iterations, ` +
        (sv.converged ? "converged"
          : sv.steady ? `steady (≤ ${sv.change_max_ms} m/s change since ${sv.change_since})`
          : "<b>not converged</b>") + `</td></tr>` +
        `</tbody></table>` +
        windLegend() +
        `<p class="muted">${s.unit ?? ""}. One run, wind from ` +
        `${data.wind_from_deg ?? 225}° at ${data.inflow?.uref_ms ?? 5} m/s (10 m): ` +
        `a comfort class needs the wind rose. Map: <em>Wind &amp; noise → Pedestrian wind</em>.</p>`;
      return;
    }
    out.innerHTML =
      `<table class="kv"><tbody>` +
      `<tr><td>quantity</td><td>${data.label ?? data.quantity ?? "-"}</td></tr>` +
      `<tr><td>level</td><td>${data.level_m ?? "-"} m</td></tr>` +
      `<tr><td>mean</td><td>${isNoise ? db(s.mean) : s.mean ?? "-"}</td></tr>` +
      `<tr><td>p95</td><td>${isNoise ? db(s.p95) : s.p95 ?? "-"}</td></tr>` +
      (isNoise
        ? `<tr><td>≥ ${s.exceedance_db ?? 53} dB</td><td>${pct(s.exceedance_frac)}</td></tr>` +
          `<tr><td>≥ ${s.limit_db ?? 70} dB</td><td>${pct(s.limit_frac)}</td></tr>`
        : `<tr><td>exceedance</td><td>${pct(s.exceedance_frac)}</td></tr>`) +
      `</tbody></table>` +
      (isNoise
        ? noiseLegend() +
          `<p class="muted">${s.unit ?? ""}. ${s.exceedance_db ?? 53} and ` +
          `${s.limit_db ?? 70} dB are the Bkl standard and limit values for ` +
          `municipal roads: façade values, shown here for reference. Traffic ` +
          `is estimated from OSM road type, not counted. Map: ` +
          `<em>Analysis → Road-traffic noise</em>.</p>`
        : "");
  }

  ctx.onScenarioChange((s) => { scenario = s; render(); noiseMap.refresh(); windMap.refresh(); });
}
