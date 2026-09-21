/* =============================================================================
 * modules/roads.js  —  component 8: road network optimization
 * OWNER: <put your name here>
 *
 * Accessibility, traffic flow and connectivity, per scenario.
 * Computed in  analysis/roads/  (osmnx + networkx)  ->
 *   data/processed/road_metrics.json
 *
 * Expected shape (one entry per scenario):
 * {
 *   "baseline": {
 *     "metrics": { "n_nodes": 812, "n_edges": 1934, "avg_street_length_m": 94.2,
 *                  "intersection_density_km2": 118, "betweenness_max": 0.21,
 *                  "circuity": 1.06, "walk_15min_reach_frac": 0.68 },
 *     "geojson": "../data/processed/roads_baseline.geojson"
 *   },
 *   "scenario_a": { ... }
 * }
 * ========================================================================== */

const METRICS = [
  ["n_nodes",                  "Nodes",                   ""],
  ["n_edges",                  "Edges",                   ""],
  ["avg_street_length_m",      "Avg street length",       " m"],
  ["intersection_density_km2", "Intersection density",    " /km²"],
  ["circuity",                 "Circuity",                ""],
  ["betweenness_max",          "Max betweenness",         ""],
  ["walk_15min_reach_frac",    "15-min walk reach",       ""],
];

export async function setup(ctx) {
  const body = ctx.registerPanel({
    id: "roads",
    title: "Road network",
    subtitle: "accessibility · flow · connectivity",
    order: 60,
  });

  const data = await ctx.loadJson(ctx.config.dataSources.processed.roads);
  const out = document.createElement("div");
  body.appendChild(out);

  /* Per-scenario road geometry, loaded lazily and toggleable on the map. */
  const loaded = new Map();

  async function showGeometry(scenario) {
    for (const [, ds] of loaded) ds.show = false;
    if (loaded.has(scenario)) { loaded.get(scenario).show = true; return; }

    const path = data?.[scenario]?.geojson;
    if (!path) return;
    try {
      const ds = await ctx.Cesium.GeoJsonDataSource.load(path, {
        clampToGround: true,
        stroke: ctx.Cesium.Color.ORANGE,
        strokeWidth: 3,
      });
      await ctx.viewer.dataSources.add(ds);
      loaded.set(scenario, ds);
      ctx.registerLayer({
        id: `roads-${scenario}`,
        label: `Road network — ${scenario}`,
        group: "Analysis",
        show: true,
        target: ds,
      });
    } catch (err) {
      console.warn(`[roads] could not load ${path}`, err);
    }
  }

  function render(scenario) {
    if (!data) {
      ctx.placeholder(out, {
        what: "Road network analysis not run yet.",
        produces: "data/processed/road_metrics.json",
        owner: "analysis/roads/ + app/modules/roads.js",
      });
      return;
    }
    const m = data[scenario]?.metrics || {};
    const b = data.baseline?.metrics || {};
    out.innerHTML =
      `<table class="kv"><thead><tr><th>Metric</th><th>Value</th><th>vs baseline</th></tr></thead><tbody>` +
      METRICS.map(([k, label, unit]) => {
        const v = m[k], bv = b[k];
        let delta = "";
        if (v != null && bv != null && scenario !== "baseline") {
          const d = v - bv;
          delta = `<span class="delta ${d > 0 ? "up" : d < 0 ? "down" : ""}">${
            d >= 0 ? "+" : ""}${Number(d).toFixed(2)}</span>`;
        }
        return `<tr><td>${label}</td><td>${
          v == null ? "—" : Number(v).toLocaleString("en-GB", { maximumFractionDigits: 2 }) + unit
        }</td><td>${delta}</td></tr>`;
      }).join("") +
      `</tbody></table>`;
    showGeometry(scenario);
  }

  ctx.onScenarioChange(render);
}
