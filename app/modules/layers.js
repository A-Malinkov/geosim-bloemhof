/* =============================================================================
 * modules/layers.js  —  component 2: data layers
 * OWNER: <put your name here>
 *
 * Aerial imagery, AHN height data, existing buildings (3DBAG), Rotterdam 3D
 * trees and green surfaces. Every layer registers its own toggle.
 *
 * ---------------------------------------------------------------------------
 * THE HEIGHT OFFSET PROBLEM — read this before adding a Dutch tileset.
 *
 * Cesium positions everything against the WGS84 ellipsoid. Dutch municipal 3D
 * data is normally in NAP. At Bloemhof the difference is +43.62 m, so a
 * NAP-referenced tileset dropped in unchanged is sunk by ~43.6 m: trees end up
 * buried, buildings poke out of the ground by only their top few metres.
 *
 * `applyHeightOffset()` below fixes it by translating the tileset along the
 * local up vector at the study area. Set the per-tileset value in config.js.
 * Ctrl+click the map to print a height probe and check your work.
 * ========================================================================== */

/**
 * Shift a tileset vertically by `metres` along the local up direction.
 * This is the standard Cesium fix: build an ENU translation at the tileset's
 * own centre and write it into tileset.modelMatrix.
 */
function applyHeightOffset(tileset, metres, Cesium) {
  if (!metres) return;
  const c = Cesium.Cartographic.fromCartesian(tileset.boundingSphere.center);
  const from = Cesium.Cartesian3.fromRadians(c.longitude, c.latitude, c.height);
  const to   = Cesium.Cartesian3.fromRadians(c.longitude, c.latitude, c.height + metres);
  const delta = Cesium.Cartesian3.subtract(to, from, new Cesium.Cartesian3());
  tileset.modelMatrix = Cesium.Matrix4.fromTranslation(delta);
}

/** Load a 3D Tiles tileset, register its toggle, and report failures softly. */
async function addTileset(ctx, { key, label, group, show, styleFn = null }) {
  const { Cesium, viewer, config } = ctx;
  const spec = config.layers[key];
  if (!spec) {
    console.warn(`[layers] no config entry for "${key}"`);
    return null;
  }
  try {
    const tileset = await Cesium.Cesium3DTileset.fromUrl(spec.url, {
      maximumScreenSpaceError: 16,
      // Dutch tilesets are large; cap memory so the tab stays usable.
      cacheBytes: 384 * 1024 * 1024,
      skipLevelOfDetail: true,
    });

    tileset.__name = key;            // handy when poking around in the console
    tileset.__heightOffsetM = spec.heightOffsetM ?? 0;
    applyHeightOffset(tileset, spec.heightOffsetM, Cesium);
    if (styleFn) styleFn(tileset, Cesium);

    viewer.scene.primitives.add(tileset);
    ctx.registerLayer({ id: key, label, group, show, target: tileset });

    if (config.debug) {
      const c = Cesium.Cartographic.fromCartesian(tileset.boundingSphere.center);
      console.log(
        `[layers] ${key}: bounding-sphere centre at ${c.height.toFixed(1)} m ellipsoid ` +
        `after a ${spec.heightOffsetM ?? 0} m offset`,
      );
    }
    ctx.note(`${label}: loaded`, "ok");
    return tileset;
  } catch (err) {
    console.error(`[layers] "${label}" failed to load from ${spec.url}`, err);
    ctx.note(`${label}: FAILED`, "err");
    // Still register a (dead) toggle so the panel shows what was attempted.
    ctx.registerLayer({ id: key, label: `${label} (failed)`, group, show: false });
    return null;
  }
}

/* ========================================================================== */
export async function setup(ctx) {
  const { Cesium, viewer, config } = ctx;
  const L = config.layers;

  /* ---------------------------------------------------------------- imagery */
  /* PDOK Luchtfoto RGB, WMTS, EPSG:3857.
   * Two details that break this if you get them wrong:
   *   1. the TileMatrix identifiers are zero-padded ("00".."21"), so we must
   *      pass explicit tileMatrixLabels — Cesium's default "0","1",… 404s;
   *   2. the matrix set is a standard WebMercatorQuad, so WebMercatorTilingScheme. */
  let aerial = null;
  try {
    const labels = Array.from({ length: L.pdokAerial.maximumLevel + 1 }, (_, i) =>
      String(i).padStart(2, "0"),
    );
    const provider = new Cesium.WebMapTileServiceImageryProvider({
      url: `${L.pdokAerial.url}/${L.pdokAerial.layer}/{TileMatrixSet}/{TileMatrix}/{TileCol}/{TileRow}.jpeg`,
      layer: L.pdokAerial.layer,
      style: "default",
      format: L.pdokAerial.format,
      tileMatrixSetID: L.pdokAerial.tileMatrixSetID,
      tileMatrixLabels: labels,
      tilingScheme: new Cesium.WebMercatorTilingScheme(),
      maximumLevel: L.pdokAerial.maximumLevel,
      credit: new Cesium.Credit(L.pdokAerial.credit),
    });
    aerial = viewer.imageryLayers.addImageryProvider(provider);
    ctx.registerLayer({
      id: "aerial",
      label: `Aerial photo (PDOK ${L.pdokAerial.layer})`,
      group: "Imagery",
      show: true,
      target: aerial,
    });
    ctx.note("PDOK aerial: loaded", "ok");
  } catch (err) {
    console.error("[layers] PDOK aerial imagery failed", err);
    ctx.note("PDOK aerial: FAILED", "err");
  }

  /* OpenStreetMap, as a fallback/orientation basemap. Off by default. */
  try {
    const osm = viewer.imageryLayers.addImageryProvider(
      new Cesium.OpenStreetMapImageryProvider({ url: "https://tile.openstreetmap.org/" }),
    );
    osm.show = false;
    // draw underneath the aerial photo
    viewer.imageryLayers.lower(osm);
    ctx.registerLayer({
      id: "osm", label: "OpenStreetMap (fallback)", group: "Imagery",
      show: false, target: osm,
    });
  } catch (err) {
    console.warn("[layers] OSM basemap unavailable", err);
  }

  /* AHN surface model as a draped overlay — a quick visual read on relief.
   * Quantitative AHN work belongs in analysis/morphology (WCS, 0.5 m rasters). */
  try {
    const ahn = viewer.imageryLayers.addImageryProvider(
      new Cesium.WebMapServiceImageryProvider({
        url: L.ahnWms.url,
        layers: L.ahnWms.layers,
        parameters: { transparent: true, format: "image/png" },
        credit: new Cesium.Credit(L.ahnWms.credit),
      }),
    );
    ahn.show = false;
    ahn.alpha = 0.7;
    ctx.registerLayer({
      id: "ahn", label: `AHN height (${L.ahnWms.layers})`, group: "Imagery",
      show: false, target: ahn,
    });
  } catch (err) {
    console.warn("[layers] AHN WMS unavailable", err);
  }

  /* ------------------------------------------------------- existing buildings */
  await addTileset(ctx, {
    key: "bag3d",
    label: "Existing buildings (3DBAG LoD2.2)",
    group: "3D city model",
    show: true,
    styleFn: (ts, Cs) => {
      // Neutral grey so our own massing can read as a different colour.
      ts.style = new Cs.Cesium3DTileStyle({
        color: "color('#9e9e9e')",
      });
      ts.colorBlendMode = Cs.Cesium3DTileColorBlendMode.REPLACE;
    },
  });

  /* ------------------------------------------------------------------- trees */
  /* Rotterdam's prebuilt tree tileset. Off by default because vegetation.js
   * draws the same trees from the register, and those we can query and edit.
   * Turn this on to compare the two, or if the register download is missing. */
  await addTileset(ctx, {
    key: "rotterdamTrees",
    label: "Trees (Rotterdam 3D tileset)",
    group: "Vegetation",
    show: false,
  });

  await addTileset(ctx, {
    key: "rotterdamGreen",
    label: "Green surfaces (Rotterdam 3D)",
    group: "Vegetation",
    show: false,
  });

  /* Textured trees are much heavier — leave off until someone needs a render. */
  await addTileset(ctx, {
    key: "rotterdamTreesTextured",
    label: "Trees, textured (heavy)",
    group: "Vegetation",
    show: false,
  });

  /* ---------------------------------------------------- study area boundaries */
  /* The real buurt polygons, written by analysis/common/project.py. Drawing a
   * circle round a centre point was fine when the study area WAS a circle; it
   * is now two adjacent buurten with a ragged shared edge, and a circle would
   * misrepresent what is actually being analysed. */
  const sa = config.studyArea;
  try {
    const ds = await Cesium.GeoJsonDataSource.load(sa.boundaries, {
      clampToGround: true,
      fill: Cesium.Color.CYAN.withAlpha(0.06),
    });
    /* Cesium cannot outline a polygon that is clamped to terrain — it warns and
     * silently drops the stroke. Draw each boundary as a ground polyline
     * instead, which is the supported way to get a visible edge. */
    const rings = [];
    for (const ent of ds.entities.values) {
      const hier = ent.polygon?.hierarchy?.getValue?.(Cesium.JulianDate.now());
      if (!hier) continue;
      for (const part of [hier, ...(hier.holes || [])]) {
        if (part?.positions?.length) rings.push(part.positions);
      }
      ent.polygon.outline = false;
    }
    for (const positions of rings) {
      ds.entities.add({
        polyline: {
          positions: [...positions, positions[0]],
          width: 3,
          material: Cesium.Color.CYAN.withAlpha(0.9),
          clampToGround: true,
        },
      });
    }
    for (const ent of ds.entities.values) {
      const p = ent.properties;
      const nm = p?.name?.getValue?.() ?? "";
      ent.name = `${nm} (buurt)`;
      ent.description =
        `<table>` +
        `<tr><td>buurt</td><td>${nm}</td></tr>` +
        `<tr><td>code</td><td>${p?.buurtcode?.getValue?.() ?? "—"}</td></tr>` +
        `<tr><td>area</td><td>${p?.area_ha?.getValue?.() ?? "—"} ha</td></tr>` +
        `<tr><td>inhabitants</td><td>${
          (p?.inhabitants?.getValue?.() ?? 0).toLocaleString("en-GB")}</td></tr>` +
        `</table>`;
    }
    await viewer.dataSources.add(ds);
    ctx.registerLayer({
      id: "studyArea",
      label: `Study area — ${sa.buurten.map((b) => b.name).join(" + ")}`,
      group: "Reference",
      show: true,
      target: ds,
    });
  } catch (err) {
    console.warn("[layers] study-area boundaries failed to load", err);
    ctx.note("Study area boundaries: FAILED", "err");
  }

  /* ---------------------------------------------------------------- credits */
  ctx.note(
    "Data: PDOK · 3DBAG (TU Delft) · Rotterdam 3D · AHN",
    "info",
  );
}
