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
  { id: "noise", label: "Noise (LAeq, façade/ground)",      prefix: "noise" },
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

export async function setup(ctx) {
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
    out.innerHTML =
      `<table class="kv"><tbody>` +
      `<tr><td>quantity</td><td>${data.quantity ?? "—"}</td></tr>` +
      `<tr><td>level</td><td>${data.level_m ?? "—"} m</td></tr>` +
      `<tr><td>grid</td><td>${(data.shape || []).join(" × ") || "—"}</td></tr>` +
      `<tr><td>mean</td><td>${s.mean ?? "—"}</td></tr>` +
      `<tr><td>p95</td><td>${s.p95 ?? "—"}</td></tr>` +
      `<tr><td>exceedance</td><td>${
        s.exceedance_frac == null ? "—" : (s.exceedance_frac * 100).toFixed(1) + " %"
      }</td></tr>` +
      `</tbody></table>` +
      `<p class="muted">TODO: drape the grid on the globe as a coloured overlay.</p>`;

    /* Drawing the grid on the map: build a Cesium.Rectangle from bbox (convert
     * EPSG:28992 -> WGS84 in Python and store bbox_wgs84 too), render the values
     * to an offscreen <canvas>, then add it as a SingleTileImageryProvider. */
  }

  ctx.onScenarioChange((s) => { scenario = s; render(); });
}
