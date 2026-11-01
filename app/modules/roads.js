/* =============================================================================
 * modules/roads.js - component 8: road network
 * OWNER: Atanas Malinkov
 *
 * The walking network per scenario, how far homes are from everyday
 * destinations.
 * Computed in  analysis/roads/  ->
 *   road_network.py   -> data/processed/road_metrics.json, roads_<scenario>.geojson
 *   edge_access.py    -> data/processed/edge_access.json, edge_access_<scenario>.geojson
 *                        (walk and drive distance from each site address to Lange Hilleweg and Strevelsweg)
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

const EDGE = "../data/processed/edge_access.json";  //edge_access.py: distance to the two edge streets
const EDGE_PICKS = [  //[mode, street key, button label]; the street keys are edge_access.py's TARGETS
  ["walk", "lange_hilleweg", "Walk · Lange Hilleweg"],
  ["walk", "strevelsweg", "Walk · Strevelsweg"],
  ["drive", "lange_hilleweg", "Drive · Lange Hilleweg"],
  ["drive", "strevelsweg", "Drive · Strevelsweg"],
];
const EDGE_BREAKS = [50, 100, 200, 400];  //metres
const EDGE_RAMP = ["#1a9850", "#91cf60", "#fee08b", "#fc8d59", "#d73027"];  //near to far
const EDGE_NONE = "#8a8f98";  //unreachable

export async function setup(ctx) {
  const { Cesium } = ctx;
  const body = ctx.registerPanel({
    id: "roads",
    title: "Road network",
    subtitle: "walking network · everyday destinations",
    order: 60,
  });

  const [data, edge] = await Promise.all([
    ctx.loadJson(ctx.config.dataSources.processed.roads),
    ctx.loadJson(EDGE, { quiet: true }),
  ]);
  const out = document.createElement("div");
  body.appendChild(out);

  const fmt = (v, d = 0, unit = "") =>
    v == null ? "-" : Number(v).toLocaleString("en-GB", { minimumFractionDigits: d, maximumFractionDigits: d }) + unit;
  //change against baseline; for distances and betweenness, up is worse
  const delta = (v, bv, d) => {
    if (v == null || bv == null) return "";
    const x = v - bv;
    const cls = Math.abs(x) < 0.5 * 10 ** -d ? "" : x > 0 ? "up" : "down";
    return `<span class="delta ${cls}">${x >= 0 ? "+" : ""}${x.toFixed(d)}</span>`;
  };

  /* ---------------------------------------------------------- map layers */
  const nets = new Map();   //scenario -> promise of {ds, handle} for the network
  const edges = new Map();  //scenario -> promise of {ds, handle} for the edge-street distances
  //checkbox choice per kind, kept across scenario switches; the distance points start off
  const wanted = new Map([[nets, true], [edges, false]]);
  let edgePick = { mode: "walk", street: "lange_hilleweg" };  //which distance colours the points
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
      group: "Mobility",  //with the transit stops; there is no separate Roads group any more
      show: wanted.get(nets),  //start as the user last left it, so registering does not reset the choice
      target: ds,
      onToggle: remember(nets, scenario),
    });
    return { ds, handle };
  }

  const edgeColour = (m) => Cesium.Color.fromCssColorString(
    m == null ? EDGE_NONE : EDGE_RAMP[EDGE_BREAKS.filter((t) => m > t).length]);

  function paintEdge(ds) {
    //colour every address point by the picked mode and street
    for (const e of ds.entities.values) e.point.color = edgeColour(e.edgeProps[`${edgePick.mode}_${edgePick.street}_m`]);
  }

  async function loadEdge(scenario) {
    //one point per address (or new-block entrance), coloured by its distance to the picked edge street
    const path = edge?.[scenario]?.geojson;
    if (!path) return null;
    const geo = await ctx.loadJson(path, { quiet: true });
    if (!geo) return null;
    const ds = new Cesium.CustomDataSource(`edge-access-${scenario}`);
    const m = (v) => (v == null ? "unreachable" : `${fmt(v, 0)} m`);
    for (const f of geo.features) {
      const p = f.properties;
      const e = ds.entities.add({
        name: p.label || "Address",
        position: Cesium.Cartesian3.fromDegrees(...f.geometry.coordinates),
        point: {
          pixelSize: Math.min(12, 5 + Math.sqrt(p.dwellings)),  //a door serving more dwellings drawn larger
          scaleByDistance: new Cesium.NearFarScalar(200, 1.0, 2500, 0.35),  //single doors when close, no blob from afar
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 1,
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,  //never hidden behind a building
        },
        description:
          `<table class="cesium-infoBox-defaultTable"><tbody>` +
          `<tr><th>Dwellings</th><td>${fmt(p.dwellings, p.new ? 1 : 0)}${p.new ? " (estimated, new block)" : ""}</td></tr>` +
          EDGE_PICKS.map(([mode, k, label]) => `<tr><th>${label}</th><td>${m(p[`${mode}_${k}_m`])}</td></tr>`).join("") +
          `</tbody></table>`,
      });
      e.edgeProps = p;
    }
    paintEdge(ds);
    await ctx.viewer.dataSources.add(ds);
    const handle = ctx.registerLayer({
      id: `roads-edge-${scenario}`,
      label: `Distance to edge streets (${scenario})`,
      group: "Mobility",
      show: wanted.get(edges),
      target: ds,
      onToggle: remember(edges, scenario),
    });
    return { ds, handle };
  }

  async function showLayers(scenario) {
    //only the current scenario's layers on, checkboxes kept in step
    for (const [map, load] of [[nets, loadNetwork], [edges, loadEdge]]) {
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
      (data[sc].with_amenities && data.baseline.with_amenities  //as lived: today's own amenities, or the placed ones
        ? row(sc === "baseline" ? "<b>with today's own amenities</b>"
              : sc === "final" ? "<b>with its labelled shops</b>" : "<b>with the placed amenities</b>",  //final: shops from the Rhino block names
              data[sc].with_amenities.areas.design_site.mean_of_types_m,
              data.baseline.with_amenities.areas.design_site.mean_of_types_m,
              data[sc].with_amenities.site_grid.mean_of_types_m,
              data.baseline.with_amenities.site_grid.mean_of_types_m, null)
        : "") +
      `</tbody></table>` +
      `<p class="muted">Mean network walk to the nearest of each. The rows per type leave the site's own amenities ` +
      `out in every scenario, today included, so they show the network alone. The last row is as lived: today with ` +
      `its own 20 shops, 7 health practices and school, A and B with the ones placed on their ground floors, ` +
      `the final design with the shops its Rhino model labels and no new health practice or school ` +  //final: nothing placed
      `(Amenities layer). <em>Dwellings</em>: ` +  //two measures since 2026-10-27
      `${fmt(site.dwellings)} on the site` +
      (sc === "baseline" ? " (BAG)" : `, ${fmt(data[sc].network.new_block_dwellings_est)} of them estimated for the new blocks`) +
      `, so it moves with who lives there. <em>Site grid</em>: the same ${fmt(grid.grid_points)} points ` +
      `in every scenario, so it moves with the network alone. ≤ 5 min is 400 m. ` +
      `Every home in the study area reaches all four within 15 min in every scenario ` +
      `(${fmt(100 * data[sc].metrics.walk_15min_reach_frac, 0, " %")}).</p>`;
  }

  function edgeBlock(sc) {
    //walk and drive distance from the site's addresses to Lange Hilleweg and Strevelsweg
    if (!edge) return "";
    const E = edge[sc];
    if (!E?.dwellings)
      return `<h4>Distance to the edge streets</h4><p class="muted">Not computed for "${sc}" yet ` +
        `(analysis/roads/edge_access.py --scenario ${sc}).</p>`;
    const B = edge.baseline?.dwellings;
    const showDelta = sc !== "baseline" && B;
    const near = edge._params.near_m[0];
    const legend = EDGE_RAMP.map((c, i) =>
      `<span class="lgd"><i style="background:${c}"></i>${i === 0 ? "≤ " + EDGE_BREAKS[0]
        : i === EDGE_RAMP.length - 1 ? "> " + EDGE_BREAKS[i - 1] : EDGE_BREAKS[i - 1] + "–" + EDGE_BREAKS[i]} m</span>`)
      .join("") + `<span class="lgd"><i style="background:${EDGE_NONE}"></i>unreachable</span>`;
    const lost = EDGE_PICKS.map(([mode, k]) => E.dwellings[mode][k].unreachable_dwellings).reduce((a, b) => a + b, 0);
    const o = E.origins;
    return `<h4>Distance to the edge streets, design site</h4>` +
      `<div class="seg" id="edgeMode">` + [["walk", "Walk"], ["drive", "Drive"]].map(([k, label]) =>
        `<button data-mode="${k}" class="${edgePick.mode === k ? "on" : ""}">${label}</button>`).join("") + `</div>` +
      `<div class="seg" id="edgeStreet">` + Object.entries(edge.targets).map(([k, name]) =>
        `<button data-street="${k}" class="${edgePick.street === k ? "on" : ""}">${name}</button>`).join("") + `</div>` +
      `<div class="lgdwrap">${legend}</div>` +
      `<table class="kv"><thead><tr><th></th><th>median</th><th>p90</th><th>max</th><th>≤ ${near} m</th></tr></thead><tbody>` +
      EDGE_PICKS.map(([mode, k, label]) => {
        const a = E.dwellings[mode][k], b = B?.[mode]?.[k];
        return `<tr><td>${label}</td><td>${fmt(a.median_m, 0, " m")} ${showDelta ? delta(a.median_m, b?.median_m, 0) : ""}</td>` +
          `<td>${fmt(a.p90_m, 0, " m")}</td><td>${fmt(a.max_m, 0, " m")}</td>` +
          `<td>${fmt(100 * a[`within_${near}m_frac`], 0, " %")}</td></tr>`;
      }).join("") +
      `</tbody></table>` +
      `<p class="muted">Network distance from each of ${fmt(E.dwellings.walk.lange_hilleweg.dwellings)} dwellings on the site ` +
      (sc === "baseline" ? "(BAG addresses)" : `(${fmt(o.bag_dwellings)} kept BAG addresses, ${fmt(o.new_block_dwellings_est)} estimated ` +
        `in the new blocks at ${fmt(o.entrances_drawn)} drawn and ${fmt(o.entrances_auto)} automatic entrances)`) +
      ` to the nearest point on the street's stretch along the site, weighted by dwellings. ` +
      `<em>Walk</em>: streets and paths on the site only, from the address. <em>Drive</em>: OSM car network with ` +
      `one-way streets, from the street in front; no turn restrictions or parking.` +
      (lost ? ` ${fmt(lost)} dwelling-routes cannot reach their street and are left out of the figures (grey).` : "") +
      ` Turn on “Distance to edge streets” in Mobility to see every address.</p>` +
      (E.assumptions?.length ? `<p class="muted"><b>Assumed:</b> ${E.assumptions.join(" ")}</p>` : "");
  }

  function bindEdge(sc) {
    //the mode and street buttons recolour the points and switch their layer on
    for (const b of out.querySelectorAll("#edgeMode button, #edgeStreet button")) {
      b.addEventListener("click", async () => {
        if (b.dataset.mode) edgePick.mode = b.dataset.mode;
        if (b.dataset.street) edgePick.street = b.dataset.street;
        for (const x of b.parentElement.children) x.classList.toggle("on", x === b);
        for (const p of edges.values()) {
          const layer = await p;
          if (layer) paintEdge(layer.ds);
        }
        wanted.set(edges, true);
        (await edges.get(sc))?.handle.setVisible(sc === ctx.scenario());
        ctx.viewer.scene.requestRender();
      });
    }
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
    out.innerHTML = networkTable(sc) + accessTable(sc) + edgeBlock(sc) +
      `<p class="muted">OSM walk network, 500 m beyond the buurten. Betweenness: share of shortest walks ` +
      `between all node pairs that use an edge. The map colours edges by it, light to dark. ` +
      `Destinations on the design site are left out in every scenario, so the comparison is the network ` +
      `and the homes, not the shops the design removes ` +
      `(${Object.entries(data.destinations_on_site_today || {}).filter(([, n]) => n).map(([k, n]) => `${n} ${k.replace("_", " ")}`).join(", ")} today).</p>`;
    bindEdge(sc);
    showLayers(sc);
  }

  ctx.onScenarioChange(render);
}
