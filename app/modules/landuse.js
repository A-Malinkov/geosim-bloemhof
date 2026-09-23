/* =============================================================================
 * modules/landuse.js  —  component 7: agent-based land-use modelling
 * OWNER: Atanas Malinkov
 *
 * Shows two models of how land use could evolve, and lets you watch them run.
 *
 *   Cellular automaton   analysis/abm_landuse/ca_landuse.py   -> landuse_abm.json
 *       Rules are ASSUMED — an influence matrix saying shops want streets and
 *       industry repels housing. Shows what follows from those assumptions.
 *
 *   RL agent             analysis/abm_landuse/rl_landuse.py   -> landuse_rl.json
 *       Rules are LEARNED — the agent is given only the objective. Its weights
 *       can be read off and compared with the CA's matrix.
 *
 * MAP RENDERING
 * -------------
 * Each simulation frame is a small PNG exported by Python, already warped to
 * EPSG:4326. Rendering ~2,300 cells as Cesium polygons per frame would be slow,
 * and building the rectangle from RD corners in JS would misplace it by ~30 m
 * because RD New is rotated against WGS84 — the same trap that caught the Sky
 * View Factor overlay. Python warps it; the browser just drapes it.
 *
 * Frames load lazily, one imagery layer per frame, cached after first use.
 * ========================================================================== */

export async function setup(ctx) {
  const { Cesium, viewer } = ctx;

  const body = ctx.registerPanel({
    id: "landuse",
    title: "Land-use model",
    subtitle: "cellular automaton + reinforcement learning",
    order: 50,
  });

  const ca = await ctx.loadJson(ctx.config.dataSources.processed.landuse,
                                { quiet: true });
  const rl = await ctx.loadJson("../data/processed/landuse_rl.json",
                                { quiet: true });

  if (!ca?.scenarios) {
    ctx.placeholder(body, {
      what: "Land-use model has not been run yet.",
      produces: "data/processed/landuse_abm.json",
      owner: "analysis/abm_landuse/ca_landuse.py",
    });
    return;
  }

  /* ---- map frames ------------------------------------------------------- */
  const cache = new Map();          // png -> ImageryLayer, once loaded
  const pending = new Map();        // png -> in-flight load promise
  let reqId = 0;                    // only the newest request may show itself

  /**
   * Show one frame, hiding the rest.
   *
   * Two things have to be handled or layers leak. Dragging the slider fires
   * many calls at once, so: (1) concurrent requests for the SAME png must share
   * one load, otherwise each creates its own layer and only the last reaches
   * the cache — the orphans are then invisible to the hide loop and stay on
   * screen forever; (2) a slow load that resolves after the user has moved on
   * must not show itself, hence the request sequence.
   */
  async function showFrame(png, bbox) {
    if (!png) return;
    const mine = ++reqId;

    let layer = cache.get(png);
    if (!layer) {
      let load = pending.get(png);
      if (!load) {
        const [w, s, e, n] = bbox;
        load = Cesium.SingleTileImageryProvider.fromUrl(
          `../data/processed/${png}`,
          { rectangle: Cesium.Rectangle.fromDegrees(w, s, e, n) },
        ).then((provider) => {
          const l = viewer.imageryLayers.addImageryProvider(provider);
          l.__png = png;
          l.alpha = 0.8;
          l.show = false;
          cache.set(png, l);
          pending.delete(png);
          return l;
        }).catch((err) => {
          console.warn("[landuse] frame failed to load", png, err);
          pending.delete(png);
          return null;
        });
        pending.set(png, load);
      }
      layer = await load;
      if (!layer) return;
    }
    if (mine !== reqId) return;          // superseded while loading
    for (const l of cache.values()) l.show = false;
    layer.show = layerOn;
  }

  let layerOn = false;
  ctx.registerLayer({
    id: "landuseModel",
    label: "Land-use simulation",
    group: "Analysis",
    show: false,
    onToggle: (v) => {
      layerOn = v;
      reqId++;                           // invalidate anything still loading
      for (const l of cache.values()) l.show = false;
      if (v) render();
    },
  });

  /* ---- panel ------------------------------------------------------------ */
  const names = Object.keys(ca.scenarios);
  const legend = Object.entries(ca.colours || {})
    .filter(([k]) => !["water", "road", "vacant"].includes(k))
    .map(([k, c]) =>
      `<span class="lgd"><i style="background:rgb(${c.join(",")})"></i>${k}</span>`)
    .join("");

  const maxT = Math.max(...ca.scenarios[names[0]].frames.map((f) => f.t));
  body.innerHTML = `
    <table class="kv"><tbody>
      <tr><td>model</td><td>${ca.model ?? ca.method}</td></tr>
      <tr><td>cells</td><td>${ca.grid.nx} × ${ca.grid.ny} at ${ca.cell_size_m} m</td></tr>
      <tr><td>replicates</td><td>${ca.parameters.replicates} per scenario</td></tr>
    </tbody></table>

    <h4>Scenario ranking</h4>
    <table class="kv"><thead><tr><th>scenario</th><th>objective</th><th>mix</th></tr></thead>
    <tbody>${ca.ranking.map((r) => {
      const win = r.scenario === ca.preferred;
      return `<tr><td>${win ? "★ " : ""}${r.scenario}</td>` +
             `<td>${r.objective_best.toFixed(3)}</td>` +
             `<td>${r.landuse_mix.toFixed(3)}</td></tr>`;
    }).join("")}</tbody></table>

    <h4>Watch it evolve</h4>
    <div class="seg" id="luScen">
      ${names.map((n, i) =>
        `<button data-s="${n}" class="${i === 0 ? "on" : ""}">${n.replace("scenario_", "")}</button>`).join("")}
    </div>
    <label class="slider">
      <span>step <output id="luOut">0</output> of ${maxT}</span>
      <input type="range" id="luStep" min="0" max="${ca.scenarios[names[0]].frames.length - 1}" value="0">
    </label>
    <p class="lgdwrap">${legend}</p>
    <div id="luInfo"></div>
    <div id="luRl"></div>
    <p class="muted">${ca.caveat}</p>`;

  const segs = [...body.querySelectorAll("#luScen button")];
  const slider = body.querySelector("#luStep");
  const outEl = body.querySelector("#luOut");
  const info = body.querySelector("#luInfo");
  let active = names[0];

  function render() {
    const sc = ca.scenarios[active];
    const i = Math.min(+slider.value, sc.frames.length - 1);
    const fr = sc.frames[i];
    outEl.textContent = fr.t;
    showFrame(fr.png, fr.bbox_wgs84);
    const s = sc.score;
    const sh = sc.trajectory[Math.min(fr.t, sc.trajectory.length - 1)].shares;
    info.innerHTML =
      `<p class="muted">${sc.label}</p>` +
      `<table class="kv"><tbody>` +
      `<tr><td>land-use mix</td><td>${s.landuse_mix.toFixed(3)}</td></tr>` +
      `<tr><td>green share</td><td>${(s.green_share * 100).toFixed(1)} %</td></tr>` +
      `<tr><td>home → amenity</td><td>${s.mean_distance_to_amenity_m} m</td></tr>` +
      `<tr><td>objective</td><td>${sc.objective_best.toFixed(3)} ` +
      `<span class="muted">(± ${sc.objective_sd.toFixed(3)} over runs)</span></td></tr>` +
      `</tbody></table>` +
      `<p class="muted">at step ${fr.t}: residential ${(sh.residential * 100).toFixed(1)} %, ` +
      `green ${(sh.green * 100).toFixed(1)} %, retail ${(sh.retail * 100).toFixed(1)} %</p>`;
  }

  segs.forEach((b) => b.addEventListener("click", () => {
    segs.forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    active = b.dataset.s;
    render();
  }));
  slider.addEventListener("input", render);

  /* ---- validation + RL --------------------------------------------------- */
  const v = ca.validation || {};
  const vrows = Object.entries(v).filter(([k]) => !k.startsWith("_"))
    .map(([k, x]) => `<tr><td>${k.replace("erase_", "erased ").replace("pct", " %")}</td>` +
                     `<td>${(x.agreement_mean * 100).toFixed(1)} %</td>` +
                     `<td>${x.kappa_mean.toFixed(3)}</td></tr>`).join("");

  body.querySelector("#luRl").innerHTML =
    (vrows ? `<h4>Validation</h4>` +
      `<table class="kv"><thead><tr><th>test</th><th>agreement</th><th>κ</th></tr></thead>` +
      `<tbody>${vrows}</tbody></table>` +
      `<p class="muted">Erase a share of developed cells, restore the original ` +
      `demand, and see how much of the real map the CA rebuilds. κ discounts ` +
      `chance agreement.</p>` : "") +
    (rl ? `<h4>RL agent</h4>` +
      `<table class="kv"><tbody>` +
      `<tr><td>algorithm</td><td>${rl.algorithm}</td></tr>` +
      `<tr><td>episodes</td><td>${rl.parameters.episodes}</td></tr>` +
      `<tr><td>learned</td><td>${rl.objective_first_decile_mean.toFixed(3)} → ` +
      `${rl.objective_last_decile_mean.toFixed(3)} ` +
      `<span class="delta ${rl.improvement_over_training > 0 ? "down" : "up"}">` +
      `${rl.improvement_over_training > 0 ? "+" : ""}${rl.improvement_over_training.toFixed(3)}</span></td></tr>` +
      `<tr><td>best objective</td><td>${rl.best_objective.toFixed(3)} ` +
      `<span class="muted">vs ${rl.baseline_objective.toFixed(3)} today</span></td></tr>` +
      `<tr><td>its land-use mix</td><td>${rl.score.landuse_mix.toFixed(3)}</td></tr>` +
      `<tr><td>home → amenity</td><td>${rl.score.mean_distance_to_amenity_m} m</td></tr>` +
      `</tbody></table>` +
      `<p class="muted">The RL agent optimises this objective directly, while the ` +
      `CA follows fixed rules and is merely scored on it — so a higher number is ` +
      `expected and is <em>not</em> evidence that RL models cities better.</p>`
      : `<p class="muted">RL agent not run yet — ` +
        `<code>analysis/abm_landuse/rl_landuse.py</code></p>`);

  // the scenario switcher at the top of the dashboard drives this too
  ctx.onScenarioChange((s) => {
    if (names.includes(s)) {
      active = s;
      segs.forEach((x) => x.classList.toggle("on", x.dataset.s === s));
      render();
    }
  });

  render();
  ctx.note(`Land use: CA + RL, best ${ca.preferred}`, "ok");
}
