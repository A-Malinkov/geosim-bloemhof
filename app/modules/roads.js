/* =============================================================================
 * modules/roads.js  —  component 8: road network
 * OWNER: Atanas Malinkov
 *
 * The walking network per scenario, how far homes are from everyday
 * destinations, and the footpath links an optimiser would add.
 * Computed in  analysis/roads/  ->
 *   road_network.py   -> data/processed/road_metrics.json, roads_<scenario>.geojson
 *   optimise_links.py -> data/processed/road_links.json, road_links_<scenario>.geojson
 *
 * road_metrics.json, one entry per scenario:
 * {
 *   "baseline": {
 *     "metrics": { n_nodes, n_edges, avg_street_length_m, intersection_density_km2,
 *                  circuity, betweenness_max, walk_15min_reach_frac },   //study area
 *     "areas": { "<area>": { ...metrics, street_length_km, dwellings,
 *                            shop|education|health|rail_stop: { mean_m, within_5min_frac, ... },
 *                            mean_of_types_m } },
 *     "site_grid": { same destination block, over a fixed 20 m grid on the site },
 *     "geojson": "../data/processed/roads_baseline.geojson"
 *   },
 *   "scenario_b": { "_status": "not_computed_yet" }
 * }
 * ========================================================================== */

const METRICS = [
  ["n_nodes",                  "Nodes",                0, ""],
  ["n_edges",                  "Edges",                0, ""],
  ["street_length_km",         "Network length",       2, " km"],
  ["avg_street_length_m",      "Avg edge length",      1, " m"],
  ["intersection_density_km2", "Intersection density", 0, " /km²"],
  ["circuity",                 "Circuity",             3, ""],
  ["betweenness_max",          "Max betweenness",      3, ""],
];

const DEST = [  //destination types written by road_network.py
  ["shop",      "Shop"],
  ["education", "Education"],
  ["health",    "Health care"],
  ["rail_stop", "Tram / metro / train"],
];

const BREAKS = [0.005, 0.015, 0.035, 0.06];  //edge betweenness classes, roughly the 50/75/90/97th percentiles in the baseline
const RAMP = ["#fde7c8", "#f9c27e", "#f08a4b", "#d4493a", "#8e1b2f"];  //light = local street, dark = through route

export async function setup(ctx) {
  const { Cesium } = ctx;
  const body = ctx.registerPanel({
    id: "roads",
    title: "Road network",
    subtitle: "walking network · everyday destinations · footpath links",
    order: 60,
  });

  const [data, links] = await Promise.all([
    ctx.loadJson(ctx.config.dataSources.processed.roads),
    ctx.loadJson(ctx.config.dataSources.processed.roadLinks),
  ]);
  const out = document.createElement("div");
  body.appendChild(out);

  const fmt = (v, d = 0, unit = "") =>
    v == null ? "—" : Number(v).toLocaleString("en-GB", { minimumFractionDigits: d, maximumFractionDigits: d }) + unit;
  //change against baseline; for distances and betweenness, up is worse
  const delta = (v, bv, d) => {
    if (v == null || bv == null) return "";
    const x = v - bv;
    const cls = Math.abs(x) < 0.5 * 10 ** -d ? "" : x > 0 ? "up" : "down";
    return `<span class="delta ${cls}">${x >= 0 ? "+" : ""}${x.toFixed(d)}</span>`;
  };

  /* ---------------------------------------------------------- map layers */
  const nets = new Map();   //scenario -> promise of {ds, handle} for the network
  const picks = new Map();  //scenario -> promise of {ds, handle} for the optimiser's links
  const wanted = new Map([[nets, true], [picks, true]]);  //checkbox choice per kind, kept across scenario switches
  //a tick or untick on the current scenario's layer is the user's choice; the switch's own hiding is not
  const remember = (map, scenario) => (v) => { if (scenario === ctx.scenario()) wanted.set(map, v); };

  async function loadNetwork(scenario) {
    //the scenario's walk network, coloured by edge betweenness
    const path = data?.[scenario]?.geojson;
    if (!path) return null;
    const ds = await Cesium.GeoJsonDataSource.load(path, { clampToGround: true });
    for (const e of ds.entities.values) {
      const b = e.properties?.betweenness?.getValue() ?? 0;
      const k = BREAKS.filter((t) => b >= t).length;  //class 0..4
      e.polyline.material = Cesium.Color.fromCssColorString(RAMP[k]);
      e.polyline.width = 1.5 + k;  //busier edges drawn wider
    }
    await ctx.viewer.dataSources.add(ds);
    const handle = ctx.registerLayer({
      id: `roads-${scenario}`,
      label: `Walk network, betweenness (${scenario})`,
      group: "Roads",
      show: wanted.get(nets),  //start as the user last left it, so registering does not reset the choice
      target: ds,
      onToggle: remember(nets, scenario),
    });
    return { ds, handle };
  }

  async function loadLinks(scenario) {
    //the optimiser's footpath links with their rank
    const path = links?.[scenario]?.geojson;
    if (!path) return null;
    const ds = await Cesium.GeoJsonDataSource.load(path, { clampToGround: true });
    const green = Cesium.Color.fromCssColorString("#1a9850");
    for (const e of ds.entities.values) {
      e.polyline.material = new Cesium.PolylineDashMaterialProperty({ color: green, dashLength: 12 });
      e.polyline.width = 5;
      const pos = e.polyline.positions.getValue(Cesium.JulianDate.now());
      e.position = Cesium.Cartesian3.midpoint(pos[0], pos[pos.length - 1], new Cesium.Cartesian3());  //label at the middle
      e.label = new Cesium.LabelGraphics({
        text: String(e.properties.rank.getValue()),
        font: "bold 15px sans-serif",
        fillColor: Cesium.Color.WHITE,
        outlineColor: green,
        outlineWidth: 4,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      });
    }
    await ctx.viewer.dataSources.add(ds);
    const handle = ctx.registerLayer({
      id: `roads-links-${scenario}`,
      label: `Optimiser footpath links (${scenario})`,
      group: "Roads",
      show: wanted.get(picks),  //start as the user last left it
      target: ds,
      onToggle: remember(picks, scenario),
    });
    return { ds, handle };
  }

  async function showLayers(scenario) {
    //only the current scenario's layers on, checkboxes kept in step
    for (const [map, load] of [[nets, loadNetwork], [picks, loadLinks]]) {
      if (!map.has(scenario)) {  //store the promise at once, so two quick switches load a layer only once
        map.set(scenario, load(scenario).catch((err) => {
          console.warn(`[roads] could not load layer for ${scenario}`, err);
          return null;
        }));
      }
      for (const [s, p] of map) {
        const layer = await p;
        if (ctx.scenario() !== scenario) return;  //switched again while loading, the newer call sets visibility
        layer?.handle.setVisible(s === scenario && wanted.get(map));  //only the current scenario's, and only if wanted
      }
    }
    ctx.viewer.scene.requestRender();  //layers loaded asynchronously, so ask for a redraw
  }

  /* ------------------------------------------------------------- the card */
  function networkTable(sc) {
    const a = data[sc].areas, ab = data.baseline.areas;
    const showDelta = sc !== "baseline";
    return `<h4>Walking network</h4>` +
      `<table class="kv"><thead><tr><th></th><th>Study area</th><th>Design site</th>` +
      (showDelta ? `<th>site vs base</th>` : "") + `</tr></thead><tbody>` +
      METRICS.map(([k, label, d, unit]) =>
        `<tr><td>${label}</td><td>${fmt(a.study_area[k], d, unit)}</td><td>${fmt(a.design_site[k], d, unit)}</td>` +
        (showDelta ? `<td>${delta(a.design_site[k], ab.design_site[k], d)}</td>` : "") + `</tr>`).join("") +
      `</tbody></table>`;
  }

  function accessTable(sc) {
    const site = data[sc].areas.design_site, siteB = data.baseline.areas.design_site;
    const grid = data[sc].site_grid, gridB = data.baseline.site_grid;
    const showDelta = sc !== "baseline";
    const row = (label, v, bv, gv, gbv, near) =>
      `<tr><td>${label}</td><td>${fmt(v, 0, " m")} ${showDelta ? delta(v, bv, 0) : ""}</td>` +
      `<td>${fmt(gv, 0, " m")} ${showDelta ? delta(gv, gbv, 0) : ""}</td>` +
      `<td>${near == null ? "" : fmt(100 * near, 0, " %")}</td></tr>`;
    return `<h4>Walk to everyday destinations, design site</h4>` +
      `<table class="kv"><thead><tr><th></th><th>dwellings</th><th>site grid</th><th>≤ 5 min</th></tr></thead><tbody>` +
      DEST.map(([k, label]) => row(label, site[k]?.mean_m, siteB[k]?.mean_m, grid[k]?.mean_m, gridB[k]?.mean_m,
                                   site[k]?.within_5min_frac)).join("") +
      row("<b>mean of the four</b>", site.mean_of_types_m, siteB.mean_of_types_m,
          grid.mean_of_types_m, gridB.mean_of_types_m, null) +
      `</tbody></table>` +
      `<p class="muted">Mean network walk to the nearest of each. <em>Dwellings</em>: ` +
      `${fmt(site.dwellings)} on the site` +
      (sc === "baseline" ? " (BAG)" : `, ${fmt(data[sc].network.new_block_dwellings_est)} of them estimated for the new blocks`) +
      `, so it moves with who lives there. <em>Site grid</em>: the same ${fmt(grid.grid_points)} points ` +
      `in every scenario, so it moves with the network alone. ≤ 5 min is 400 m. ` +
      `Every home in the study area reaches all four within 15 min in every scenario ` +
      `(${fmt(100 * data[sc].metrics.walk_15min_reach_frac, 0, " %")}).</p>`;
  }

  function linksBlock(sc) {
    const L = links?.[sc];
    if (!L?.steps) return "";
    const total = L.steps.reduce((s, x) => s + x.length_m, 0);
    return `<h4>Footpath links the optimiser adds</h4>` +
      `<table class="kv"><thead><tr><th>#</th><th>length</th><th>J saved</th><th>site dwellings</th><th>of ceiling</th></tr></thead><tbody>` +
      L.steps.map((x) =>
        `<tr><td>${x.rank}</td><td>${fmt(x.length_m, 0, " m")}</td><td>${fmt(x.gain_m, 2, " m")}</td>` +
        `<td>${fmt(x.site_dwellings_m, 0, " m")}</td><td>${fmt(100 * x.share_of_ceiling, 0, " %")}</td></tr>`).join("") +
      `</tbody></table>` +
      `<p class="muted">Objective J: mean walk from a dwelling to the nearest shop, education, health care and ` +
      `rail stop, over all ${fmt(data[sc].areas.study_area.dwellings)} dwellings, now ${fmt(L.J_before_m, 2, " m")}. ` +
      `Greedy, one straight footpath at a time, from ${L.n_candidates} candidates that cross no block and save a ` +
      `detour of at least ${L.candidate_rule.detour_min}×. All candidates together would reach ` +
      `${fmt(L.J_ceiling_m, 2, " m")} (the ceiling). Site dwellings start at ${fmt(L.site_dwellings_before_m, 0, " m")}, ` +
      `today's layout gives ${fmt(data.baseline.areas.design_site.mean_of_types_m, 0, " m")}. ` +
      `${L.steps.length} links, ${fmt(total, 0, " m")} in all. ` +
      `Assumes the ground between blocks is public. Dashed green on the map, numbered by rank.</p>`;
  }

  function render(sc) {
    if (!data) {
      ctx.placeholder(out, {
        what: "Road network analysis not run yet.",
        produces: "data/processed/road_metrics.json",
        owner: "analysis/roads/road_network.py + app/modules/roads.js",
      });
      return;
    }
    if (!data[sc]?.areas) {
      ctx.placeholder(out, {
        what: `Road network not computed for "${sc}" yet (no massing).`,
        produces: `data/processed/road_metrics.json → ${sc}`,
        owner: "analysis/roads/road_network.py, CASES",
      });
      showLayers(sc);
      return;
    }
    out.innerHTML = networkTable(sc) + accessTable(sc) + linksBlock(sc) +
      `<p class="muted">OSM walk network, 500 m beyond the buurten. Betweenness: share of shortest walks ` +
      `between all node pairs that use an edge. The map colours edges by it, light to dark. ` +
      `Destinations on the design site are left out in every scenario, so the comparison is the network ` +
      `and the homes, not the shops the design removes ` +
      `(${Object.entries(data.destinations_on_site_today || {}).filter(([, n]) => n).map(([k, n]) => `${n} ${k.replace("_", " ")}`).join(", ")} today).</p>`;
    showLayers(sc);
  }

  ctx.onScenarioChange(render);
}
