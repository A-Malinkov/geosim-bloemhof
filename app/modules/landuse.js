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
  /* Every frame is a ~3 KB PNG and there are fewer than twenty of them, so all
   * of them are loaded once when the layer is first switched on. Frame changes
   * are then a synchronous `show` flag — no promises in the path the slider
   * drives. An earlier version created layers lazily per frame and the async
   * bookkeeping was subtly wrong: frames loaded and cached, but the visible
   * layer never changed. Preloading is both simpler and correct. */
  const layers = new Map();         // png -> ImageryLayer
  let preloaded = null;             // the one-shot preload promise
  let layerOn = false;

  function allFrames() {
    const out = [];
    for (const sc of Object.values(ca.scenarios)) {
      for (const f of sc.frames) out.push(f);
    }
    return out;
  }

  async function preload() {
    if (preloaded) return preloaded;
    preloaded = (async () => {
      await Promise.all(allFrames().map(async (f) => {
        if (layers.has(f.png)) return;
        try {
          const [w, s2, e, n] = f.bbox_wgs84;
          const provider = await Cesium.SingleTileImageryProvider.fromUrl(
            `../data/processed/${f.png}`,
            { rectangle: Cesium.Rectangle.fromDegrees(w, s2, e, n) },
          );
          const l = viewer.imageryLayers.addImageryProvider(provider);
          l.alpha = 0.8;
          l.show = false;
          layers.set(f.png, l);
        } catch (err) {
          console.warn("[landuse] frame failed to load", f.png, err);
        }
      }));
    })();
    return preloaded;
  }

  /** Show exactly one frame, or none. Synchronous once preloaded. */
  function showFrame(png) {
    for (const [name, l] of layers) l.show = layerOn && name === png;
  }

  ctx.registerLayer({
    id: "landuseModel",
    label: "Land-use simulation",
    group: "Analysis",
    show: false,
    onToggle: async (v) => {
      layerOn = v;
      if (!v) { showFrame(null); return; }
      await preload();
      render();
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
    showFrame(fr.png);
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
