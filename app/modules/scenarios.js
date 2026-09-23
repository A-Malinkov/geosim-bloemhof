/* =============================================================================
 * modules/scenarios.js  —  components 1 + 9: proposed massing & design scenarios
 * OWNER: <put your name here>
 *
 * Owns OUR OWN design: the proposed residential massing, and at least two
 * scenarios compared against the current situation.
 *
 * The scenario <select> in the sidebar is shared UI built by main.js; this
 * module only reacts to it via ctx.onScenarioChange(). Every other module gets
 * the same callback, so switching scenario updates the whole app at once.
 *
 * TWO WAYS TO GET THE MASSING IN
 * ------------------------------
 * A. Quick, no pipeline (what this file does): a GeoJSON of footprints with a
 *    `height_m` (and optional `base_height_m`) property, extruded by Cesium.
 *    Draw the footprints in QGIS, or generate them in analysis/scenarios/.
 *      -> data/processed/design_massing.geojson
 *    Features must carry:  { "scenario": "scenario_a", "height_m": 21,
 *                            "base_height_m": 0, "use": "residential" }
 *
 * B. Proper 3D models: export from Blender/Rhino as glTF, upload to Cesium ion
 *    as 3D Tiles, and load by asset id. Put the id in config.js when you do.
 *
 * HEIGHT DATUM: heights here are treated as metres above NAP, and lifted by
 * CONFIG.napToEllipsoidM so they line up with the 3DBAG buildings and terrain.
 * ========================================================================== */

const COLOURS = {
  scenario_a: "#ff8a3d",
  scenario_b: "#4dd0e1",
  baseline:   "#9e9e9e",
};

export async function setup(ctx) {
  const { Cesium, viewer, config } = ctx;

  const body = ctx.registerPanel({
    id: "scenarios",
    title: "Design scenarios",
    subtitle: "our proposed residential complex",
    order: 5,
  });

  const geo = await ctx.loadJson(config.dataSources.processed.designMassing, { quiet: true });

  /* ---- no design yet: say so clearly and stop ---------------------------- */
  if (!geo || !geo.features?.length) {
    ctx.placeholder(body, {
      what: "No proposed massing yet. Add footprints with a height_m property "
          + "and a scenario name, and they will appear here and on the map.",
      produces: "data/processed/design_massing.geojson",
      owner: "analysis/scenarios/ + app/modules/scenarios.js",
    });
    ctx.note("Design massing: none yet", "warn");
    return;
  }

  /* ---- build one entity collection per scenario -------------------------- */
  const byScenario = new Map();
  for (const f of geo.features) {
    const name = f.properties?.scenario || "scenario_a";
    if (!byScenario.has(name)) byScenario.set(name, []);
    byScenario.get(name).push(f);
  }

  const lift = config.napToEllipsoidM;

  for (const [name, features] of byScenario) {
    const collection = new Cesium.CustomDataSource(`massing-${name}`);
    const colour = Cesium.Color.fromCssColorString(COLOURS[name] || "#ff8a3d");

    for (const f of features) {
      const p = f.properties || {};
      const rings = f.geometry?.type === "Polygon"
        ? [f.geometry.coordinates[0]]
        : f.geometry?.type === "MultiPolygon"
          ? f.geometry.coordinates.map((poly) => poly[0])
          : [];

      for (const ring of rings) {
        collection.entities.add({
          name: p.name || `${name} block`,
          description:
            `<table><tr><td>use</td><td>${p.use ?? "—"}</td></tr>` +
            `<tr><td>height</td><td>${p.height_m ?? "—"} m NAP</td></tr>` +
            `<tr><td>scenario</td><td>${name}</td></tr></table>`,
          polygon: {
            hierarchy: new Cesium.PolygonHierarchy(
              Cesium.Cartesian3.fromDegreesArray(ring.flatMap(([x, y]) => [x, y])),
            ),
            // NAP -> ellipsoid, so our massing sits with the 3DBAG buildings.
            height:          (p.base_height_m ?? 0) + lift,
            extrudedHeight:  (p.height_m ?? 12) + lift,
            material:        colour.withAlpha(0.85),
            outline:         true,
            outlineColor:    Cesium.Color.BLACK.withAlpha(0.5),
          },
        });
      }
    }

    await viewer.dataSources.add(collection);
    collection.show = false;
    byScenario.set(name, collection);

    ctx.registerLayer({
      id: `massing-${name}`,
      label: `Proposed massing — ${name}`,
      group: "Design",
      show: false,
      target: collection,
    });
  }

  /* ---- summary table ---------------------------------------------------- */
  const summary = document.createElement("div");
  body.appendChild(summary);

  function render(scenario) {
    // show only the active scenario's massing
    for (const [name, ds] of byScenario) ds.show = name === scenario;

    const ds = byScenario.get(scenario);
    if (!ds) {
      summary.innerHTML =
        `<p class="muted">Current situation — no proposed massing shown.</p>`;
      return;
    }
    const n = ds.entities.values.length;
    // Cesium Property.getValue takes a JulianDate. A ConstantProperty tolerates
    // an omitted one, but a time-varying property would return undefined, so
    // pass the clock time rather than relying on that.
    const now = viewer.clock.currentTime;
    const heights = ds.entities.values
      .map((e) => e.polygon?.extrudedHeight?.getValue?.(now))
      .filter((h) => h != null)
      .map((h) => h - ctx.config.napToEllipsoidM);
    const max = heights.length ? Math.max(...heights) : null;
    summary.innerHTML =
      `<table class="kv"><tbody>` +
      `<tr><td>volumes</td><td>${n}</td></tr>` +
      `<tr><td>max height</td><td>${max == null ? "—" : max.toFixed(1) + " m NAP"}</td></tr>` +
      `</tbody></table>`;
  }

  ctx.onScenarioChange(render);
  ctx.note(`Design massing: ${byScenario.size} scenario(s)`, "ok");
}
