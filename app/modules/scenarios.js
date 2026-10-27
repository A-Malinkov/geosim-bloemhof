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
 *                            "use": "residential" }
 *    and may carry `base_height_m`. Both are metres ABOVE NAP, not above the
 *    ground: height_m is the roof, base_height_m the underside. Leave the base
 *    out and it defaults to the site's ground level (-0.93 m NAP, measured from
 *    AHN and stored with the site). Ground here is below NAP 0, so a base of 0
 *    would leave every building floating about 1 m above the street.
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
  const layerHandles = new Map();  //scenario name -> registerLayer handle, keeps the layer checkbox in step
  for (const f of geo.features) {
    const name = f.properties?.scenario || "scenario_a";
    if (!byScenario.has(name)) byScenario.set(name, []);
    byScenario.get(name).push(f);
  }

  /* ---- demolition: hide the 3DBAG buildings a shown massing replaces ------ */
  //ids per scenario, written by analysis/scenarios/import_rhino.py
  const demolishes = new Map(Object.entries(geo.demolishes ?? {}).map(([k, ids]) => [k, new Set(ids)]));
  //existing buildings a scenario keeps as part of its design (keep_rd), shown in the scenario's colour
  const keeps = new Map(Object.entries(geo.keeps ?? {}).map(([k, ids]) => [k, new Set(ids)]));
  const shownMassing = new Set();  //scenarios whose massing is currently visible
  function applyDemolition() {
    //the 3DBAG tileset is loaded by layers.js; find it by the name it sets
    const ts = viewer.scene.primitives._primitives.find((p) => p.__name === "bag3d");
    if (!ts?.style) return;
    const hidden = new Set();  //union of the ids of every visible massing
    for (const name of shownMassing) for (const id of demolishes.get(name) ?? []) hidden.add(id);
    //custom show evaluator on the existing style, so the colour set in layers.js stays
    ts.style.show = hidden.size
      ? { evaluate: (feature) => !hidden.has(feature.getProperty("identificatie")) }
      : true;
    ts.__baseColor ??= ts.style.color;  //layers.js's colour, kept for every building not recoloured
    const tint = new Map();  //3DBAG id -> colour of the shown scenario that keeps it
    for (const name of shownMassing)
      for (const id of keeps.get(name) ?? []) tint.set(id, Cesium.Color.fromCssColorString(COLOURS[name] || "#ff8a3d"));  //3D tiles shade it a little darker than the massing
    const base = ts.__baseColor;
    ts.style.color = tint.size
      ? {  //custom colour expression: kept buildings take the scenario colour, the rest keep the base style
          evaluateColor: (feature, result) => {
            const c = tint.get(feature.getProperty("identificatie"));
            return c ? Cesium.Color.clone(c, result) : base.evaluateColor(feature, result);
          },
          evaluate(feature, result) { return this.evaluateColor(feature, result); },
        }
      : base;
    ts.makeStyleDirty();  //re-evaluate features already loaded
  }

  /* ---- new streets: flat surfaces draped on the ground, per scenario ----- */
  const streetsGeo = config.dataSources.processed.designStreets
    ? await ctx.loadJson(config.dataSources.processed.designStreets, { quiet: true }) : null;  //optional file
  const streetsByScenario = new Map();  //scenario name -> CustomDataSource of street polygons
  for (const f of streetsGeo?.features ?? []) {
    const name = f.properties?.scenario;
    if (!name) continue;
    if (!streetsByScenario.has(name)) {
      const ds = new Cesium.CustomDataSource(`streets-${name}`);
      ds.show = false;  //shown together with the massing
      await viewer.dataSources.add(ds);
      streetsByScenario.set(name, ds);
    }
    //hand-drawn footpaths (kind "path", import_rhino.py paths_rd): a line on the ground, either geometry type
    const paths = f.geometry?.type === "LineString" ? [f.geometry.coordinates]
      : f.geometry?.type === "MultiLineString" ? f.geometry.coordinates : [];
    for (const line of paths) {
      streetsByScenario.get(name).entities.add({
        name: f.properties.name ?? `${name} path`,
        description: `<table><tr><td>footpath</td><td>${f.properties.length_m ?? "—"} m</td></tr>` +
          `<tr><td>source</td><td>${f.properties.source ?? "—"}</td></tr></table>`,
        polyline: {
          positions: Cesium.Cartesian3.fromDegreesArray(line.flatMap(([x, y]) => [x, y])),
          clampToGround: true,  //follows the terrain like the street surfaces
          width: 4,
          material: Cesium.Color.fromCssColorString("#d9c39a"),  //gravel path
        },
      });
    }
    const polys = f.geometry?.type === "Polygon" ? [f.geometry.coordinates]
      : f.geometry?.type === "MultiPolygon" ? f.geometry.coordinates : [];
    for (const poly of polys) {
      const toCart = (ring) => Cesium.Cartesian3.fromDegreesArray(ring.flatMap(([x, y]) => [x, y]));  //lon/lat ring -> Cartesian
      streetsByScenario.get(name).entities.add({
        name: f.properties.name ?? `${name} streets`,
        description: `<table><tr><td>new streets</td><td>${f.properties.area_m2 ?? "—"} m²</td></tr></table>`,
        polygon: {
          hierarchy: new Cesium.PolygonHierarchy(toCart(poly[0]), poly.slice(1).map((h) => new Cesium.PolygonHierarchy(toCart(h)))),  //outer ring plus holes
          classificationType: Cesium.ClassificationType.TERRAIN,  //drape on the ground, over the aerial photo
          material: Cesium.Color.fromCssColorString("#4a4f57").withAlpha(0.95),  //asphalt grey
        },
      });
    }
  }

  /* ---- ground-floor amenities placed by analysis/roads/place_amenities.py --- */
  //shops, health practices and a school on the new blocks' ground floors, where they shorten walks most
  const amenGeo = await ctx.loadJson("../data/processed/design_amenities.geojson", { quiet: true });  //optional file
  const AMEN = { shop: ["#7b4fd0", "Shop"], health: ["#d63c7b", "Health care"], education: ["#1f2a44", "School"],
                 community: ["#b8860b", "Community hall"] };  //as in docs/fig_amenities.png
  const amenBy = new Map();  //scenario name -> CustomDataSource of amenity points
  for (const f of amenGeo?.features ?? []) {
    const { scenario: name, type, rank, block, floor_m2, status } = f.properties;
    const gone = status === "demolished";  //today's amenity that A and B demolish: drawn hollow
    if (!amenBy.has(name)) {
      const ds = new Cesium.CustomDataSource(`amenities-${name}`);
      ds.show = false;  //shown with the massing
      await viewer.dataSources.add(ds);
      amenBy.set(name, ds);
    }
    const [col, label] = AMEN[type] ?? ["#888888", type];
    amenBy.get(name).entities.add({
      name: status === "placed" ? `${label} (optimised placement)`  //placed by the p-median
        : name === "baseline" ? `${label} today${gone ? ", demolished in A and B" : ", kept"}`  //today's, from BAG
        : `${label} (kept community centre and school, fixed)`,  //the kept block, never moved
      description: `<table><tr><td>use</td><td>${label}</td></tr><tr><td>where</td><td>${block}</td></tr>` +
        (status === "placed" ? `<tr><td>pick</td><td>${rank} of its type</td></tr>` : "") +
        `<tr><td>floor area</td><td>${floor_m2} m²${status === "placed" ? " (today's median)" : " (BAG)"}</td></tr>` +
        `<tr><td>source</td><td>${status === "placed" ? "place_amenities.py, p-median on walking distance" : "BAG"}</td></tr></table>`,
      position: Cesium.Cartesian3.fromDegrees(...f.geometry.coordinates),
      point: {
        pixelSize: type === "education" ? 15 : 10,
        color: gone ? Cesium.Color.WHITE.withAlpha(0.15) : Cesium.Color.fromCssColorString(col),  //hollow when demolished
        outlineColor: gone ? Cesium.Color.fromCssColorString(col) : Cesium.Color.WHITE,
        outlineWidth: gone ? 3 : 2,
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,  //a ground-floor door, drawn over its own block
      },
    });
  }
  let amenOn = true;  //layer checkbox
  const showAmen = () => {  //the current scenario's amenities only, if ticked; an option's only while its massing shows
    for (const [n, ds] of amenBy) ds.show = amenOn && n === ctx.scenario() && (n === "baseline" || shownMassing.has(n));
    viewer.scene.requestRender();
  };
  if (amenBy.size) {
    ctx.registerLayer({
      id: "designAmenities",
      label: "Amenities: today's, kept and optimised",
      group: "Design",
      show: true,
      onToggle: (v) => { amenOn = v; showAmen(); },
    });
  }

  const lift = config.napToEllipsoidM;
  // default base = the design site's measured ground level (see DESIGN_SITE in
  // analysis/common/project.py); 0 only if the site file is unavailable
  const siteGeo = config.designSite?.boundary
    ? await ctx.loadJson(config.designSite.boundary, { quiet: true }) : null;
  const groundNap = siteGeo?.features?.[0]?.properties?.ground_nap_m;
  if (groundNap == null) console.warn("[scenarios] site ground level unknown; massing base defaults to NAP 0");
  const defaultBase = groundNap ?? 0;

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
            (p.building_height_m != null ? `<tr><td>building height</td><td>${p.building_height_m} m</td></tr>` : "") +  //as modelled, above ground
            `<tr><td>scenario</td><td>${name}</td></tr></table>`,
          polygon: {
            hierarchy: new Cesium.PolygonHierarchy(
              Cesium.Cartesian3.fromDegreesArray(ring.flatMap(([x, y]) => [x, y])),
            ),
            // NAP -> ellipsoid, so our massing sits with the 3DBAG buildings.
            height:          (p.base_height_m ?? defaultBase) + lift,
            extrudedHeight:  (p.height_m ?? 12) + lift,
            material:        colour.withAlpha(0.85),
            shadows:         Cesium.ShadowMode.ENABLED,  //cast and receive shadows for the sun slider
            outline:         true,
            outlineColor:    Cesium.Color.BLACK.withAlpha(0.5),
          },
        });
      }
    }

    await viewer.dataSources.add(collection);
    collection.show = false;
    byScenario.set(name, collection);

    layerHandles.set(name, ctx.registerLayer({  //keep the handle so a scenario switch can tick the checkbox
      id: `massing-${name}`,
      label: `Proposed massing — ${name}`,
      group: "Design",
      show: false,
      target: collection,
      onToggle: (visible) => {  //old buildings go when the new ones show, and come back when they hide
        if (visible) shownMassing.add(name); else shownMassing.delete(name);
        applyDemolition();
        const st = streetsByScenario.get(name);  //this scenario's new streets
        if (st) st.show = visible;  //streets follow the massing
        showAmen();  //and so do the placed amenities
      },
    }));  //end of registerLayer, handle stored
  }

  /* ---- summary table ---------------------------------------------------- */
  const summary = document.createElement("div");
  body.appendChild(summary);

  function render(scenario) {
    queueMicrotask(showAmen);  //after the massing switch below, so the amenities follow the scenario
    // show only the active scenario's massing
    for (const [name] of byScenario) layerHandles.get(name)?.setVisible(name === scenario);  //shows the massing and ticks its checkbox

    const ds = byScenario.get(scenario);
    if (!ds) {
      summary.innerHTML =
        (scenario === "baseline"
          ? `<p class="muted">Current situation — no proposed massing shown.</p>`
          : `<p class="muted">No massing for ${scenario} yet. Model it in Rhino and add it to ` +
            `<code>analysis/scenarios/import_rhino.py</code>.</p>`);  //a scenario without massing is not the current situation
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
    const nDemo = demolishes.get(scenario)?.size;  //existing buildings this scenario removes
    summary.innerHTML =
      `<table class="kv"><tbody>` +
      `<tr><td>volumes</td><td>${n}</td></tr>` +
      (nDemo != null ? `<tr><td>existing buildings removed</td><td>${nDemo}</td></tr>` : "") +  //hidden from the 3DBAG layer
      `<tr><td>max height</td><td>${max == null ? "—" : max.toFixed(1) + " m NAP"}</td></tr>` +
      `</tbody></table>`;
  }

  ctx.onScenarioChange(render);
  ctx.note(`Design massing: ${byScenario.size} scenario(s)`, "ok");
}
