/* =============================================================================
 * modules/vegetation.js  —  3D vegetation models
 * OWNER: Atanas Malinkov
 *
 * Builds our OWN 3D trees from the Rotterdam tree register, rather than only
 * using the municipality's prebuilt tileset.
 *
 * Why bother, when layers.js already loads Rotterdam's 3D tree tileset?
 * Because that tileset is a sealed mesh. You cannot count it, query it, or take
 * a tree out of it for a design scenario. These trees come from the register
 * (2,172 of them in the study area, 206 species), so we can add, remove and
 * re-measure them — which is what components 5 (wind) and 9 (scenarios) need.
 *
 * Geometry: a cylinder trunk and an ellipsoid crown per tree, batched into two
 * Cesium Primitives. One draw call each, so a couple of thousand trees costs
 * almost nothing, whereas 4,000 Entities would crawl.
 *
 * HEIGHTS: data/processed/trees.geojson carries `ground_nap_m`, sampled from the
 * AHN DTM in Python. We add CONFIG.napToEllipsoidM to get an ellipsoidal height,
 * so the trees line up with the 3DBAG buildings without querying terrain.
 *
 * Produced by: analysis/morphology/fetch_trees.py
 * ========================================================================== */

const TRUNK_COLOUR = "#6b4f3a";

/** Crown colour varies a little with height so a street does not read as a hedge. */
function crownColour(Cesium, heightM) {
  const t = Math.max(0, Math.min(1, (heightM - 4) / 18));
  return Cesium.Color.fromCssColorString(
    `hsl(${Math.round(104 - 14 * t)}, ${Math.round(38 + 14 * t)}%, ${Math.round(42 - 10 * t)}%)`,
  );
}

function buildPrimitives(ctx, features) {
  const { Cesium, config } = ctx;
  const lift = config.napToEllipsoidM;
  const trunks = [];
  const crowns = [];

  for (const f of features) {
    const p = f.properties || {};
    const [lon, lat] = f.geometry.coordinates;
    const ground = (p.ground_nap_m ?? 0) + lift;

    const total = Math.max(2, p.height_m ?? 9);
    const trunkH = Math.max(0.8, Math.min(p.trunk_height_m ?? total * 0.4, total * 0.8));
    const crownH = Math.max(1.2, total - trunkH);
    const crownR = Math.max(0.8, (p.crown_m ?? 5) / 2);
    const trunkR = Math.max(0.08, (p.trunk_diameter_cm ?? 30) / 200);

    trunks.push(new Cesium.GeometryInstance({
      geometry: new Cesium.CylinderGeometry({
        length: trunkH,
        topRadius: trunkR * 0.8,
        bottomRadius: trunkR,
        vertexFormat: Cesium.PerInstanceColorAppearance.VERTEX_FORMAT,
      }),
      modelMatrix: Cesium.Transforms.eastNorthUpToFixedFrame(
        Cesium.Cartesian3.fromDegrees(lon, lat, ground + trunkH / 2),
      ),
      attributes: {
        color: Cesium.ColorGeometryInstanceAttribute.fromColor(
          Cesium.Color.fromCssColorString(TRUNK_COLOUR),
        ),
      },
      id: { kind: "tree-trunk", ...p },
    }));

    crowns.push(new Cesium.GeometryInstance({
      geometry: new Cesium.EllipsoidGeometry({
        radii: new Cesium.Cartesian3(crownR, crownR, crownH / 2),
        stackPartitions: 8,
        slicePartitions: 10,
        vertexFormat: Cesium.PerInstanceColorAppearance.VERTEX_FORMAT,
      }),
      modelMatrix: Cesium.Transforms.eastNorthUpToFixedFrame(
        Cesium.Cartesian3.fromDegrees(lon, lat, ground + trunkH + crownH / 2),
      ),
      attributes: {
        color: Cesium.ColorGeometryInstanceAttribute.fromColor(
          crownColour(Cesium, total).withAlpha(0.95),
        ),
      },
      id: { kind: "tree", ...p },
    }));
  }

  const appearance = new Cesium.PerInstanceColorAppearance({
    translucent: false,
    closed: true,
  });
  return [
    new Cesium.Primitive({ geometryInstances: trunks, appearance, asynchronous: true }),
    new Cesium.Primitive({ geometryInstances: crowns, appearance, asynchronous: true }),
  ];
}

/* ========================================================================== */
export async function setup(ctx) {
  const { viewer, config } = ctx;

  const body = ctx.registerPanel({
    id: "vegetation",
    title: "Vegetation",
    subtitle: "Rotterdam tree register — 3D models",
    order: 25,
  });

  const geo = await ctx.loadJson("../data/processed/trees.geojson", { quiet: true });
  const stats = await ctx.loadJson("../data/processed/vegetation_summary.json", { quiet: true });

  if (!geo || !geo.features?.length) {
    ctx.placeholder(body, {
      what: "Tree register not downloaded yet.",
      produces: "data/processed/trees.geojson",
      owner: "analysis/morphology/fetch_trees.py",
    });
    return;
  }

  /* ---- 3D trees --------------------------------------------------------- */
  const prims = buildPrimitives(ctx, geo.features);
  prims.forEach((p) => viewer.scene.primitives.add(p));

  ctx.registerLayer({
    id: "treeModels",
    label: `3D trees from register (${geo.features.length})`,
    group: "Vegetation",
    show: true,
    onToggle: (v) => prims.forEach((p) => { p.show = v; }),
  });

  /* ---- panel ------------------------------------------------------------ */
  const s = stats || {};
  const h = s.height_m || {};
  const c = s.canopy || {};
  const cr = s.crown_m || {};

  body.innerHTML =
    `<table class="kv"><tbody>` +
    `<tr><td>trees</td><td>${(s.n_trees ?? geo.features.length).toLocaleString("en-GB")}</td></tr>` +
    `<tr><td>density</td><td>${s.trees_per_hectare ?? "—"} / ha</td></tr>` +
    `<tr><td>species</td><td>${s.n_species ?? "—"}</td></tr>` +
    `<tr><td>mean height</td><td>${h.mean ?? "—"} m</td></tr>` +
    `<tr><td>mean crown</td><td>${cr.mean ?? "—"} m</td></tr>` +
    `<tr><td>canopy cover</td><td>${
      c.cover_fraction == null ? "—" : (c.cover_fraction * 100).toFixed(1) + " %"
    }</td></tr>` +
    `</tbody></table>` +
    (s.top_species?.length
      ? `<h4>Most common species</h4>` +
        `<table class="kv"><tbody>` +
        s.top_species.slice(0, 6).map((x) =>
          `<tr><td>${x.species}</td><td>${x.n}</td></tr>`).join("") +
        `</tbody></table>`
      : "") +
    `<p class="muted">Crown area is an upper bound: overlapping crowns count twice.</p>`;

  /* ---- click a tree to inspect it --------------------------------------- */
  const handler = new ctx.Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
  handler.setInputAction((click) => {
    const picked = viewer.scene.pick(click.position);
    const id = picked?.id;
    if (!id || (id.kind !== "tree" && id.kind !== "tree-trunk")) return;
    console.log("[vegetation] tree:", id);
    ctx.note(
      `${id.species_nl || id.species} · ${id.height_class || id.height_m + " m"}` +
      `${id.street ? " · " + id.street : ""}`,
      "info",
    );
  }, ctx.Cesium.ScreenSpaceEventType.LEFT_CLICK);

  ctx.note(`Vegetation: ${geo.features.length} trees`, "ok");

  /* ---- scenario hook ----------------------------------------------------
   * Scenarios can keep, remove or add trees. Drop a
   * data/processed/trees_<scenario>.geojson next to trees.geojson and it will
   * replace the baseline set when that scenario is selected. */
  let extra = null;
  ctx.onScenarioChange(async (scenario) => {
    if (scenario === "baseline") {
      prims.forEach((p) => { p.show = true; });
      if (extra) extra.forEach((p) => { p.show = false; });
      return;
    }
    const alt = await ctx.loadJson(
      `../data/processed/trees_${scenario}.geojson`, { quiet: true });
    if (!alt?.features?.length) {
      // no scenario-specific planting yet: keep the existing trees visible
      prims.forEach((p) => { p.show = true; });
      if (extra) extra.forEach((p) => { p.show = false; });
      return;
    }
    if (extra) extra.forEach((p) => viewer.scene.primitives.remove(p));
    extra = buildPrimitives(ctx, alt.features);
    extra.forEach((p) => viewer.scene.primitives.add(p));
    prims.forEach((p) => { p.show = false; });
  });
}
