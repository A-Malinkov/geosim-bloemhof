/* =============================================================================
 * modules/flood.js  —  flood / water vulnerability (Cyrille's QGIS analysis)
 * OWNER: Cyrille Kummer (analysis) · imported by analysis/flood/import_cyrille.py
 *
 * Seven 0.5 m rasters from the team's QGIS project, warped to EPSG:4326 and
 * coloured with Cyrille's own classes. One checkbox per layer under
 * "Flood vulnerability"; each PNG is fetched on first tick, not at startup.
 *
 *   overall   = combined score banded 1–4          (CityRisk)
 *   combined  = density + water + elevation, 3–12
 *   hazard    = water proximity + elevation, banded 1–4
 *   water / elevation / density / roads = the single factors
 *
 * Baseline only: this is an import of a finished analysis, not a model that
 * re-runs per scenario. Elevation is the AHN DTM, empty under buildings, so
 * hazard / combined / overall describe open ground.
 * ========================================================================== */

export async function setup(ctx) {
  const { Cesium, viewer } = ctx;
  const data = await ctx.loadJson("../data/processed/flood_summary.json", { quiet: true });

  const body = ctx.registerPanel({
    id: "flood",
    title: "Flood vulnerability",
    subtitle: "water proximity · low ground · building density (Cyrille, QGIS)",
    order: 35,
  });

  if (!data?.layers?.length) {
    ctx.placeholder(body, {
      what: "Flood vulnerability not imported yet.",
      produces: "data/processed/flood_summary.json",
      owner: "analysis/flood/import_cyrille.py",
    });
    return;
  }

  /* ---- one lazily-loaded overlay per layer ------------------------------- */
  for (const L of data.layers) {
    let layer = null;
    let loading = null;
    let on = false;  //checkbox state, read again after the image loads
    const ensure = () => {
      if (layer) return Promise.resolve(layer);
      if (!loading) {
        const [w, s, e, n] = L.bbox_wgs84;
        loading = Cesium.SingleTileImageryProvider.fromUrl(`../data/processed/${L.png}`, {
          rectangle: Cesium.Rectangle.fromDegrees(w, s, e, n),
        })
          .then((p) => {
            layer = viewer.imageryLayers.addImageryProvider(p);
            layer.alpha = 0.8;
            return layer;
          })
          .catch((err) => {
            console.warn(`[flood] ${L.id} overlay failed`, err);
            ctx.note(`Flood layer "${L.label}": failed`, "err");
            return null;
          });
      }
      return loading;
    };
    ctx.registerLayer({
      id: `flood_${L.id}`,
      label: `${L.label} (baseline)`,  //Cyrille's analysis is of today's city, not re-run per scenario
      group: "Flood vulnerability",
      show: false,
      onToggle: async (visible) => {
        on = visible;
        const l = visible ? await ensure() : layer;
        if (l) l.show = on;  //unticking while the image loads keeps it hidden
        viewer.scene.requestRender();
      },
    });
  }

  /* ---- panel: overall vulnerability shares per area ---------------------- */
  const overall = data.layers.find((l) => l.id === "overall");
  const combined = data.layers.find((l) => l.id === "combined");
  const areas = Object.keys(overall.stats);
  const classes = overall.legend.map((x) => x.label);
  const pct = (v) => (v == null ? "—" : `${Math.round(v * 100)}`);
  const swatch = (c) =>
    `<i style="width:10px;height:10px;background:${c};display:inline-block;border-radius:2px;vertical-align:-1px"></i>`;

  body.innerHTML =
    `<table class="kv"><thead><tr><th>overall, % of ground</th>` +
    overall.legend.map((x) => `<th>${swatch(x.colour)} ${x.label.split(" ")[0]}</th>`).join("") +
    `<th>mean score</th></tr></thead><tbody>` +
    areas
      .map((a) => {
        const s = overall.stats[a]?.shares || {};
        const m = combined?.stats[a]?.mean;
        return (
          `<tr><td>${a}</td>` +
          classes.map((c) => `<td>${pct(s[c])}</td>`).join("") +
          `<td>${m == null ? "—" : m.toFixed(1)}</td></tr>`
        );
      })
      .join("") +
    `</tbody></table>` +
    `<p class="muted">Each factor is scored 1–4: distance to water (0–50 m = 4), ground ` +
    `level (below −0.99 m NAP = 4) and buildings per cell (more than 10 = 4). The combined ` +
    `score is their sum; <em>overall</em> bands it into four classes. Ground level comes from ` +
    `AHN, which is empty under buildings, so these describe the open ground. Analysis by ` +
    `Cyrille (QGIS); layers under <em>Flood vulnerability</em>.</p>`;
}
