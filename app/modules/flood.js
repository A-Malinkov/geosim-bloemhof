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
 * Each checkbox follows the scenario switch, like the wind and noise maps: it
 * shows flood_summary[_scenario].json's image for the selected scenario. Only
 * today's city has been analysed, so a design scenario shows nothing (with a
 * notice) until a run for it is imported, rather than today's map under the
 * new buildings. Elevation is the AHN DTM, empty under buildings, so
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

  /* ---- one overlay per layer, following the scenario switch --------------- */
  //each scenario's summary, loaded once; baseline is the one already read
  const suffix = (sc) => (sc === "baseline" ? "" : `_${sc}`);
  const summaries = new Map([["baseline", Promise.resolve(data)]]);
  const summaryFor = (sc) => {
    if (!summaries.has(sc))
      summaries.set(sc, ctx.loadJson(`../data/processed/flood_summary${suffix(sc)}.json`, { quiet: true }));
    return summaries.get(sc);  //null while the scenario's run is a stub
  };
  let current = ctx.scenario();
  const refreshers = [];

  for (const L of data.layers) {
    const images = new Map();  //scenario -> Promise of its ImageryLayer, or null when there is no run
    let on = false;  //checkbox state, read again after an image loads
    const load = (sc) => {
      if (!images.has(sc)) {
        images.set(sc, summaryFor(sc).then(async (sum) => {
          const run = sum?.layers?.find((x) => x.id === L.id);
          if (!run) return null;  //not computed for this scenario
          const [w, s, e, n] = run.bbox_wgs84;
          const p = await Cesium.SingleTileImageryProvider.fromUrl(`../data/processed/${run.png}`, {
            rectangle: Cesium.Rectangle.fromDegrees(w, s, e, n),
          });
          const layer = viewer.imageryLayers.addImageryProvider(p);
          layer.alpha = 0.8;
          layer.show = false;  //refresh() decides
          return layer;
        }).catch((err) => {
          console.warn(`[flood] ${L.id} overlay failed for ${sc}`, err);
          ctx.note(`Flood layer "${L.label}": failed`, "err");
          return null;
        }));
      }
      return images.get(sc);
    };
    const refresh = () => {
      const want = current;
      if (on) load(want).then((l) => {
        if (!l && on && want === current) ctx.note(`${L.label}: no run for ${want}`, "warn");
      });
      //each image decides when it resolves, from the state at that moment
      for (const [sc, p] of images) p.then((l) => {
        if (l) l.show = on && sc === current;
        viewer.scene.requestRender();
      });
    };
    refreshers.push(refresh);
    ctx.registerLayer({
      id: `flood_${L.id}`,
      label: L.label,
      group: "Flood vulnerability",
      show: false,
      onToggle: (visible) => { on = visible; refresh(); },
    });
  }

  /* ---- panel: overall vulnerability shares per area ----------------------
   * The selected scenario's figures when it has a run, else today's, said so. */
  const pct = (v) => (v == null ? "—" : `${Math.round(v * 100)}`);
  const swatch = (c) =>
    `<i style="width:10px;height:10px;background:${c};display:inline-block;border-radius:2px;vertical-align:-1px"></i>`;

  function table(sum) {
    const overall = sum.layers.find((l) => l.id === "overall");
    const combined = sum.layers.find((l) => l.id === "combined");
    const classes = overall.legend.map((x) => x.label);
    return (
      `<table class="kv"><thead><tr><th>overall, % of ground</th>` +
      overall.legend.map((x) => `<th>${swatch(x.colour)} ${x.label.split(" ")[0]}</th>`).join("") +
      `<th>mean score</th></tr></thead><tbody>` +
      Object.keys(overall.stats)
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
      `</tbody></table>`
    );
  }

  async function render(sc) {
    const sum = await summaryFor(sc);
    if (sc !== current) return;  //switched again while loading
    const own = sum?.layers?.some((l) => l.id === "overall");
    body.innerHTML =
      (own || sc === "baseline" ? ""
        : `<p class="muted"><b>No flood run for ${sc}.</b> The table shows today's city; ` +
          `the map layers stay empty on this scenario.</p>`) +
      table(own ? sum : data) +
      `<p class="muted">Each factor is scored 1–4: distance to water (0–50 m = 4), ground ` +
      `level (below −0.99 m NAP = 4) and buildings per cell (more than 10 = 4). The combined ` +
      `score is their sum; <em>overall</em> bands it into four classes. Ground level comes from ` +
      `AHN, which is empty under buildings, so these describe the open ground. Analysis by ` +
      `Cyrille (QGIS); layers under <em>Flood vulnerability</em>, following the scenario switch.</p>`;
  }

  ctx.onScenarioChange((sc) => {
    current = sc;
    for (const r of refreshers) r();  //every ticked layer to the new scenario
    render(sc);
  });
}
