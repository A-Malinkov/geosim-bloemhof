/* =============================================================================
 * modules/vegetation.js - 3D vegetation models
 * OWNER: Atanas Malinkov
 *
 * Builds our OWN 3D trees from the Rotterdam tree register, rather than only
 * using the municipality's prebuilt tileset.
 *
 * Why bother, when layers.js already loads Rotterdam's 3D tree tileset?
 * Because that tileset is a sealed mesh. You cannot count it, query it, or take
 * a tree out of it for a design scenario. These trees come from the register
 * (2,172 of them in the study area, 206 species), so we can add, remove and
 * re-measure them, which is what components 5 (wind) and 9 (scenarios) need.
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
    const shrub = p.kind === "shrub";  //proposed bushes and hedges: a crown standing on the ground, no trunk
    const trunkH = shrub ? 0 : Math.max(0.8, Math.min(p.trunk_height_m ?? total * 0.4, total * 0.8));
    const crownH = Math.max(1.2, total - trunkH);
    const crownR = Math.max(0.8, (p.crown_m ?? 5) / 2);
    const trunkR = Math.max(0.08, (p.trunk_diameter_cm ?? 30) / 200);

    if (!shrub) trunks.push(new Cesium.GeometryInstance({
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
      id: { ...p, kind: p.kind ?? "tree" },  //register trees have no kind; proposed ones say tree or shrub
    }));
  }

  const appearance = new Cesium.PerInstanceColorAppearance({
    translucent: false,
    closed: true,
  });
  // Cesium primitives cast NO shadow unless asked (ShadowMode.DISABLED is the
  // default), so without this the trees stood in full sun under the sun slider
  // while every building around them cast a shadow.
  const shadows = Cesium.ShadowMode.ENABLED;
  return [
    trunks.length && new Cesium.Primitive({ geometryInstances: trunks, appearance, asynchronous: true, shadows }),
    crowns.length && new Cesium.Primitive({ geometryInstances: crowns, appearance, asynchronous: true, shadows }),
  ].filter(Boolean);  //a shrub-only set has no trunks, and an empty Primitive throws
}

/* ========================================================================== */
export async function setup(ctx) {
  const { viewer, config } = ctx;

  const body = ctx.registerPanel({
    id: "vegetation",
    title: "Vegetation",
    subtitle: "Rotterdam tree register: 3D models",
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

  /* One tree set per scenario. The checkbox and the scenario switch both go
   * through apply(), so neither can show a set the other has hidden. */
  const sets = new Map([["baseline", Promise.resolve(prims)]]);  //scenario -> Promise of its primitives, null when it has no tree file
  let treesOn = true;  //layer checkbox
  let current = ctx.scenario();  //scenario the app is on

  function load(scenario) {
    //trees_<scenario>.geojson built once and cached, hidden until apply() decides
    if (!sets.has(scenario)) {
      sets.set(scenario, ctx.loadJson(`../data/processed/trees_${scenario}.geojson`, { quiet: true })
        .then((alt) => {
          if (!alt?.features?.length) return null;  //no scenario planting: today's trees stand in
          const ps = buildPrimitives(ctx, alt.features);
          ps.forEach((p) => { p.show = false; viewer.scene.primitives.add(p); });
          return ps;
        }));
    }
    return sets.get(scenario);
  }

  async function apply() {
    //show exactly one set: the current scenario's, or today's if it has none; nothing if unticked
    const sc = current;
    const own = await load(sc);
    if (sc !== current) return;  //switched again while loading, the newer call decides
    const showing = own ? sc : "baseline";
    for (const [k, p] of sets) {
      const ps = await p;
      if (ps) ps.forEach((x) => { x.show = treesOn && k === showing; });
    }
    viewer.scene.requestRender();  //low-power mode redraws only when asked
  }

  ctx.registerLayer({
    id: "treeModels",
    label: `3D trees from register (${geo.features.length})`,
    group: "Vegetation",
    show: true,
    onToggle: (v) => { treesOn = v; apply(); },  //checkbox hides whichever set is showing
  });

  /* ---- panel ------------------------------------------------------------ */
  const s = stats || {};
  const h = s.height_m || {};
  const c = s.canopy || {};
  const cr = s.crown_m || {};

  body.innerHTML =
    `<table class="kv"><tbody>` +
    `<tr><td>trees</td><td>${(s.n_trees ?? geo.features.length).toLocaleString("en-GB")}</td></tr>` +
    `<tr><td>density</td><td>${s.trees_per_hectare ?? "-"} / ha</td></tr>` +
    `<tr><td>species</td><td>${s.n_species ?? "-"}</td></tr>` +
    `<tr><td>mean height</td><td>${h.mean ?? "-"} m</td></tr>` +
    `<tr><td>mean crown</td><td>${cr.mean ?? "-"} m</td></tr>` +
    `<tr><td>canopy cover</td><td>${
      c.cover_fraction == null ? "-" : (c.cover_fraction * 100).toFixed(1) + " %"
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

  /* ---- click anything to show what is selected -------------------------- */
  // A single floater, top-centre so it clears the bottom-left status chips.
  const selChip = document.createElement("div");
  selChip.hidden = true;
  selChip.style.cssText =
    "position:absolute;left:50%;top:12px;transform:translateX(-50%);z-index:12;" +
    "max-width:60%;padding:4px 10px;border-radius:12px;font-size:11px;" +
    "background:#1b2129ee;border:1px solid #2c3541;color:#e7ecf2;" +
    "backdrop-filter:blur(8px);pointer-events:none;white-space:nowrap;" +
    "overflow:hidden;text-overflow:ellipsis";
  viewer.container.appendChild(selChip);

  const C = ctx.Cesium;
  function describe(picked) {
    if (!picked) return null;
    const id = picked.id;
    if (id && id.proposed)  //planting from the Rhino model: a generic block, no species
      return `Proposed ${id.kind} (${id.block}) · ${id.height_m} m, crown ${id.crown_m} m · ${id.scenario}`;
    if (id && (id.kind === "tree" || id.kind === "tree-trunk"))
      return (
        `${id.species_nl || id.species} · ${id.height_class || id.height_m + " m"}` +
        `${id.street ? " · " + id.street : ""}`
      );
    if (id && id.__photo) return id.__photo.caption || "Photo";
    if (id && id.name) return id.name; // named entities (design site, buurten, …)
    if (C.Cesium3DTileFeature && picked instanceof C.Cesium3DTileFeature) {
      for (const key of ["name", "identificatie", "gml_id", "fid"]) {
        const ids = picked.getPropertyIds ? picked.getPropertyIds() : [];
        if (ids.includes(key)) return `Building ${picked.getProperty(key)}`;
      }
      return "Building";
    }
    return null;
  }

  const handler = new C.ScreenSpaceEventHandler(viewer.scene.canvas);
  handler.setInputAction((click) => {
    const label = describe(viewer.scene.pick(click.position));
    if (!label) {
      selChip.hidden = true;
      return;
    }
    selChip.textContent = `Selected: ${label}`;
    selChip.hidden = false;
  }, C.ScreenSpaceEventType.LEFT_CLICK);

  ctx.note(`Vegetation: ${geo.features.length} trees`, "ok");

  /* ---- scenario hook ----------------------------------------------------
   * Scenarios can keep, remove or add trees. Drop a
   * data/processed/trees_<scenario>.geojson next to trees.geojson and it will
   * replace the baseline set when that scenario is selected. */
  ctx.onScenarioChange((scenario) => { current = scenario; apply(); });  //apply() keeps the checkbox state

  /* ---- proposed planting -------------------------------------------------
   * Trees, shrubs and green surfaces drawn in the Rhino model, imported by
   * analysis/scenarios/import_rhino.py. Shown only on their own scenario. */
  const plant = await ctx.loadJson("../data/processed/design_planting.geojson", { quiet: true });
  if (!plant?.features?.length) return;  //no scenario has planting yet
  const C2 = ctx.Cesium;
  const planting = new Map();  //scenario -> { tree, shrub, green, counts }
  for (const f of plant.features) {
    const p = f.properties || {};
    if (!planting.has(p.scenario)) planting.set(p.scenario, { feats: { tree: [], shrub: [], green: [], water: [] } });
    planting.get(p.scenario).feats[p.kind]?.push(f);
  }
  async function drape(id, feats, what, colour) {
    //flat surfaces draped on the terrain, as the new streets are; hidden until applyPlanting() decides
    const ds = new C2.CustomDataSource(id);
    ds.show = false;
    const toCart = (ring) => C2.Cartesian3.fromDegreesArray(ring.flat());
    for (const f of feats) {
      const polys = f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates;  //shapely can return either
      for (const poly of polys) {
        ds.entities.add({
          name: f.properties.name,
          description: `<table><tr><td>${what}</td><td>${f.properties.area_m2} m²</td></tr></table>`,
          polygon: {
            hierarchy: new C2.PolygonHierarchy(toCart(poly[0]), poly.slice(1).map((h) => new C2.PolygonHierarchy(toCart(h)))),  //holes kept
            classificationType: C2.ClassificationType.TERRAIN,  //drape on the ground, over the aerial photo
            material: C2.Color.fromCssColorString(colour).withAlpha(0.85),
          },
        });
      }
    }
    await viewer.dataSources.add(ds);
    return ds;
  }
  const areaOf = (feats) => feats.reduce((a, f) => a + (f.properties.area_m2 ?? 0), 0);  //m²

  for (const [sc, set] of planting) {
    const { tree, shrub, green, water } = set.feats;
    //trees and shrubs as batched primitives, like the register trees
    set.tree = buildPrimitives(ctx, tree);
    set.shrub = buildPrimitives(ctx, shrub);
    [...set.tree, ...set.shrub].forEach((x) => { x.show = false; viewer.scene.primitives.add(x); });
    set.green = await drape(`planting-green-${sc}`, green, "proposed green", "#6fbf4a");  //grass green, water already cut out
    set.water = await drape(`planting-water-${sc}`, water, "proposed water", "#3d8fd6");  //pond blue
    set.area = areaOf(green);
    set.waterArea = areaOf(water);
  }

  //panel: proposed planting of the current scenario under the register figures; before the layers, whose onToggle renders it at once
  const plantBox = document.createElement("div");
  body.appendChild(plantBox);

  const plantOn = { tree: true, shrub: true, green: true, water: true };  //one checkbox per kind
  function applyPlanting() {
    //each kind shows only on its own scenario, and only when its checkbox is ticked
    for (const [sc, set] of planting) {
      const here = sc === current;
      set.tree.forEach((x) => { x.show = plantOn.tree && here; });
      set.shrub.forEach((x) => { x.show = plantOn.shrub && here; });
      set.green.show = plantOn.green && here;
      set.water.show = plantOn.water && here;
    }
    renderPlanting();
    viewer.scene.requestRender();  //low-power mode redraws only when asked
  }

  //labels name the scenarios that have planting, e.g. "Proposed trees (scenario_a: 64)"
  const having = (kind) => [...planting].filter(([, s]) => s.feats[kind].length);  //scenarios with this kind only
  const count = (kind) => having(kind).map(([sc, s]) => `${sc}: ${s.feats[kind].length}`).join(", ");
  const LABELS = {
    tree: `Proposed trees (${count("tree")})`,
    shrub: `Proposed shrubs (${count("shrub")})`,
    green: `Proposed green areas (${having("green").map(([sc, s]) => `${sc}: ${(s.area / 1e4).toFixed(2)} ha`).join(", ")})`,
    water: `Proposed water (${having("water").map(([sc, s]) => `${sc}: ${s.waterArea.toLocaleString("en-GB")} m²`).join(", ")})`,
  };
  for (const kind of ["tree", "shrub", "green", "water"]) {
    if (![...planting.values()].some((s) => s.feats[kind].length)) continue;  //no scenario has this kind, no checkbox
    ctx.registerLayer({
      id: `planting-${kind}`,
      label: LABELS[kind],
      group: "Vegetation",
      show: true,  //on, but only visible on a scenario that has planting
      onToggle: (v) => { plantOn[kind] = v; applyPlanting(); },
    });
  }

  function renderPlanting() {
    const set = planting.get(current);
    plantBox.innerHTML = !set ? "" :
      `<h4>Proposed planting: ${current}</h4>` +
      `<table class="kv"><tbody>` +
      `<tr><td>new trees</td><td>${set.feats.tree.length}</td></tr>` +
      `<tr><td>new shrubs</td><td>${set.feats.shrub.length}</td></tr>` +
      `<tr><td>green areas</td><td>${set.feats.green.length} · ${(set.area / 1e4).toFixed(2)} ha</td></tr>` +
      (set.waterArea ? `<tr><td>water</td><td>${set.waterArea.toLocaleString("en-GB")} m²</td></tr>` : "") +  //"Water feature?" layer
      `</tbody></table>` +
      `<p class="muted">From the Rhino model's generic blocks: sizes as drawn, no species.</p>`;
  }

  ctx.onScenarioChange((scenario) => { current = scenario; applyPlanting(); });  //not relying on handler order
  applyPlanting();
}
