/* =============================================================================
 * modules/flood.js - flood / water vulnerability (Cyrille's QGIS analysis)
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
 * shows flood_summary[_scenario].json's image for the selected scenario. A
 * design scenario without a run shows nothing (with a notice), rather than
 * today's map under the new buildings. Elevation is the AHN DTM, empty under
 * buildings, so hazard / combined / overall describe open ground.
 *
 *   overall_new = overall vulnerability with Cyrille's 2026-11-03 method, on all
 *                 ground, for today and the final design (since 2026-11-03).
 *                 The card compares the two; the old layers are today only.
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
   * The new method's table compares today with the selected design when it has
   * a run; the old method's table is today only. */
  const pct = (v) => (v == null ? "—" : `${Math.round(v * 100)}`);
  const swatch = (c) =>
    `<i style="width:10px;height:10px;background:${c};display:inline-block;border-radius:2px;vertical-align:-1px"></i>`;

  //rows: [label, stats of one area, mean score or undefined]; mean adds the old method's combined-score column
  function table(head, legend, rows, mean) {
    const classes = legend.map((x) => x.label);
    return (
      `<table class="kv"><thead><tr><th>${head}</th>` +
      legend.map((x) => `<th>${swatch(x.colour)} ${x.label.split(" ")[0]}</th>`).join("") +
      (mean ? `<th>mean score</th>` : `<th>3–4</th>`) + `</tr></thead><tbody>` +
      rows
        .map(([label, st, m]) => {
          const s = st?.shares || {};
          return (
            `<tr><td>${label}</td>` +
            classes.map((c) => `<td>${pct(s[c])}</td>`).join("") +
            (mean ? `<td>${m == null ? "—" : m.toFixed(1)}</td>`
              : `<td><b>${pct(s["3"] == null ? null : s["3"] + s["4 high"])}</b></td>`) +  //high or very high
            `</tr>`
          );
        })
        .join("") +
      `</tbody></table>`
    );
  }

  async function render(sc) {
    const sum = sc === "baseline" ? data : await summaryFor(sc);
    if (sc !== current) return;  //switched again while loading
    const overall = data.layers.find((l) => l.id === "overall");
    const combined = data.layers.find((l) => l.id === "combined");
    const today = data.layers.find((l) => l.id === "overall_new");  //today's run with the new method
    const run = sc === "baseline" ? null : sum?.layers?.find((l) => l.id === "overall_new");  //the design's
    const rows = today ? Object.keys(today.stats).flatMap((a) =>
      [[`${a}, today`, today.stats[a]], ...(run ? [[`${a}, ${sc}`, run.stats[a]]] : [])]) : [];
    body.innerHTML =
      (sc === "baseline" || run ? ""
        : `<p class="muted"><b>No flood run for ${sc}.</b> The tables show today's city; ` +
          `the map layers stay empty on this scenario.</p>`) +
      (today ? table("new method, % of all ground", today.legend, rows) +
        `<p class="muted">${today.method_note}</p>` : "") +
      table("old method, % of open ground, today", overall.legend,
        Object.keys(overall.stats).map((a) => [a, overall.stats[a], combined?.stats[a]?.mean]), true) +
      `<p class="muted">Each factor is scored 1–4: distance to water (0–50 m = 4), ground ` +
      `level (below −0.99 m NAP = 4) and buildings per cell (more than 10 = 4). The combined ` +
      `score is their sum; <em>overall</em> bands it into four classes. In the old method ground level comes from ` +
      `AHN, which is empty under buildings, so its layers describe the open ground. Analysis by ` +
      `Cyrille (QGIS); layers under <em>Flood vulnerability</em>, following the scenario switch.</p>`;
  }

  ctx.onScenarioChange((sc) => {
    current = sc;
    for (const r of refreshers) r();  //every ticked layer to the new scenario
    render(sc);
  });
}
