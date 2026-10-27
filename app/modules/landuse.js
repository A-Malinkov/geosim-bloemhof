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
 *       can be read off and compared with the CA's matrix. A second example
 *       keeps today's housing (--keep-housing -> landuse_rl_keep_housing.json),
 *       and a convolutional DQN (rl_dqn.py -> landuse_rl_dqn*.json) is run on
 *       the same problem for comparison. The "Optimiser plan (RL)" layer shows
 *       the linear agent's plan for either rule; the housing-kept plans of both
 *       agents also have their own layers.
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
 *
 * PROGRAMMES, NOT SCENARIOS. The CA's runs are land-use programmes (baseline,
 * compact, green) over the whole buurt, and the RL agents re-plan the site.
 * Neither is a Rhino design option, so neither follows the scenario switch:
 * the card has its own programme selector. What does follow the switch is the
 * Rhino option scored on the same objective (score_scenarios.py ->
 * landuse_scenarios.json).
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
  const ws = await ctx.loadJson("../data/processed/landuse_weight_sensitivity.json",
                                { quiet: true });
  const rl = await ctx.loadJson("../data/processed/landuse_rl.json",
                                { quiet: true });
  const rlKeep = await ctx.loadJson("../data/processed/landuse_rl_keep_housing.json",
                                    { quiet: true });
  const dqn = await ctx.loadJson("../data/processed/landuse_rl_dqn.json",
                                 { quiet: true });
  const dqnKeep = await ctx.loadJson("../data/processed/landuse_rl_dqn_keep_housing.json",
                                     { quiet: true });
  const rhino = await ctx.loadJson("../data/processed/landuse_scenarios.json",
                                   { quiet: true });  //the Rhino options on the same objective, keyed by scenario

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
    label: "Land-use programmes (CA, not the Rhino options)",  //programmes are not the scenario switch's options
    group: "Analysis",
    show: false,
    onToggle: async (v) => {
      layerOn = v;
      if (!v) { showFrame(null); return; }
      await preload();
      render();
    },
  });

  /* ---- optimiser plan layer ---------------------------------------------
   * One layer for the RL plans; the panel's switch picks which rule. Each plan
   * is one PNG already warped to EPSG:4326 by export_grid_png(). */
  const plans = {};
  if (rl?.png && rl?.bbox_wgs84) plans.free = rl;
  if (rlKeep?.png && rlKeep?.bbox_wgs84) plans.keep = rlKeep;
  const planLayers = {};
  let planOn = false;
  let planKey = "free";

  async function showPlan() {
    const key = planKey;  //the plan wanted when this call started
    const run = plans[key];
    if (planOn && run && !planLayers[key]) {
      //store the promise at once, so a second toggle while loading does not add the image twice
      planLayers[key] = (async () => {
        try {
          const [w, s2, e, n] = run.bbox_wgs84;
          const provider = await Cesium.SingleTileImageryProvider.fromUrl(
            `../data/processed/${run.png}`,
            { rectangle: Cesium.Rectangle.fromDegrees(w, s2, e, n) });
          const l = viewer.imageryLayers.addImageryProvider(provider);
          l.alpha = 0.8;
          l.show = false;  //the loop below decides
          return l;
        } catch (err) {
          console.warn("[landuse] optimiser plan failed to load", run.png, err);
          ctx.note("Optimiser plan: failed to load", "err");
          return null;
        }
      })();
    }
    for (const [k, p] of Object.entries(planLayers)) {
      const l = await p;
      if (l) l.show = planOn && k === planKey;  //read the state after loading, not before
    }
    viewer.scene.requestRender();
  }

  if (Object.keys(plans).length) {
    ctx.registerLayer({
      id: "landuseRlPlan",
      label: "RL site re-plan (not a Rhino option)",  //the agent's own plan for the site
      group: "Analysis",
      show: false,
      onToggle: async (v) => { planOn = v; await showPlan(); },
    });
  }

  /* ---- housing-kept plans as their own layers ----------------------------
   * The --keep-housing runs of both agents, each a standalone layer so they
   * can be shown without the panel switch. Loaded on first toggle. */
  function planLayer(id, label, run) {
    if (!run?.png || !run?.bbox_wgs84) return;  //run missing or still a stub
    let loading = null;  //Promise of the image layer, created on first tick
    let on = false;  //checkbox state
    ctx.registerLayer({
      id, label, group: "Land use", show: false,
      onToggle: async (v) => {
        on = v;
        if (v && !loading) {
          loading = (async () => {
            try {
              const [w, s2, e, n] = run.bbox_wgs84;
              const provider = await Cesium.SingleTileImageryProvider.fromUrl(
                `../data/processed/${run.png}`,
                { rectangle: Cesium.Rectangle.fromDegrees(w, s2, e, n) });
              const l = viewer.imageryLayers.addImageryProvider(provider);
              l.alpha = 0.8;
              return l;
            } catch (err) {
              console.warn("[landuse] plan layer failed to load", run.png, err);
              ctx.note(`${label}: failed to load`, "err");
              return null;
            }
          })();
        }
        const l = loading ? await loading : null;
        if (l) l.show = on;  //the state now, so unticking during the load wins
        viewer.scene.requestRender();
      },
    });
  }
  planLayer("landuseRlKeepLinear", "RL site re-plan, housing kept (linear)", rlKeep);  //linear Q-learning
  planLayer("landuseRlKeepDqn", "RL site re-plan, housing kept (DQN)", dqnKeep);  //convolutional DQN best episode

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
      <tr><td>replicates</td><td>${ca.parameters.replicates} per programme</td></tr>
    </tbody></table>

    <div id="luRhino"></div>

    <h4>Land-use programmes (CA) — not the Rhino options</h4>
    <p class="muted">Development programmes over the whole buurt, set by us. They do
    not change with the scenario switch above.</p>
    <table class="kv"><thead><tr><th>programme</th><th>objective</th><th>mix</th></tr></thead>
    <tbody>${ca.ranking.map((r) => {
      const win = r.scenario === ca.preferred;
      return `<tr><td>${win ? "★ " : ""}${r.scenario}</td>` +
             `<td>${r.objective_best.toFixed(3)}</td>` +
             `<td>${r.landuse_mix.toFixed(3)}</td></tr>`;
    }).join("")}</tbody></table>

    <div id="luSens"></div>

    <h4>Watch a programme evolve</h4>
    <div class="seg" id="luScen">
      ${names.map((n, i) =>
        `<button data-s="${n}" class="${i === 0 ? "on" : ""}">${n}</button>`).join("")}
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

  /* ---- how much of the ranking is our choice of weights? ----------------
   * The ranking above is a single number per scenario and reads as a verdict.
   * It is a verdict under three weights we picked, and the gap between the top
   * two is small. weight_sensitivity.py sweeps the normalised weight simplex
   * and reports how much of it each scenario wins, which is the honest version
   * of the same claim. Without this the panel overstates its own result. */
  const sens = body.querySelector("#luSens");
  if (ws?.win_share) {
    const shares = Object.entries(ws.win_share)
      .filter(([, v]) => v > 0)
      .sort((a, b) => b[1] - a[1]);
    const w = ws.default_weights;
    const bars = shares.map(([k, v]) =>
      `<tr><td>${k}</td><td>${(100 * v).toFixed(0)} %` +
      `<span style="display:inline-block;height:6px;vertical-align:middle;` +
      `margin-left:5px;width:${(v * 70).toFixed(0)}px;background:` +
      `${k === ws.default_winner ? "var(--accent)" : "#5b6675"}"></span></td></tr>`).join("");
    const never = Object.entries(ws.win_share).filter(([, v]) => v === 0).map(([k]) => k);
    sens.innerHTML =
      `<h4>Is that ranking robust?</h4>` +
      `<table class="kv"><thead><tr><th>wins across the weight space</th><th></th></tr></thead>` +
      `<tbody>${bars}</tbody></table>` +
      `<p class="muted">The objective weights ` +
      `(${w.w_mix} · ${w.w_green} · ${w.w_prox} for mix, green and walkability) ` +
      `are ours, so the ranking is re-scored across ` +
      `${ws.parameters.n_weight_vectors.toLocaleString("en-GB")} weight vectors on the ` +
      `normalised simplex. <strong>${ws.default_winner}</strong> wins at our weights, ` +
      `by ${ws.default_margin.toFixed(4)}, and across ` +
      `${(100 * ws.win_share[ws.default_winner]).toFixed(0)} % of the space` +
      (never.length ? `; ${never.join(" and ")} never wins` : "") + `. ` +
      (ws.nearest_flip
        ? `The nearest weights that change the answer are ` +
          `${ws.nearest_flip.weights.join(" · ")} (favouring ` +
          `${ws.nearest_flip.winner}). `
        : `No weighting on the lattice changes the answer. `) +
      `Note the margin against the spread between replicates of one scenario ` +
      `(${Object.entries(ws.margin.replicate_sd_at_default)
             .filter(([, x]) => x > 0)
             .map(([k, x]) => `${k} σ ${x.toFixed(4)}`).join(", ")}): the ` +
      `preference is a preference, not a large difference.</p>`;
  } else if (sens) {
    sens.innerHTML = `<p class="muted">Weight sensitivity not computed — ` +
      `<code>analysis/abm_landuse/weight_sensitivity.py</code></p>`;
  }

  body.querySelector("#luRl").innerHTML =
    (vrows ? `<h4>Validation</h4>` +
      `<table class="kv"><thead><tr><th>test</th><th>agreement</th><th>κ</th></tr></thead>` +
      `<tbody>${vrows}</tbody></table>` +
      `<p class="muted">Erase a share of developed cells, restore the original ` +
      `demand, and see how much of the real map the CA rebuilds. κ discounts ` +
      `chance agreement.</p>` : "") +
    (rl ? `<h4>RL agent — re-plans the design site, not a Rhino option</h4>` +
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
      (rl.baseline_score ?
        `<tr><td>residential cells</td><td>${rl.score.residential_cells} ` +
        `<span class="muted">vs ${rl.baseline_score.residential_cells} today</span></td></tr>` : "") +
      `</tbody></table>` +
      (rl.scope === "design_site" ?
        `<p class="muted">The agent re-plans every cell of the design site and is ` +
        `scored over the site alone, so its numbers are not comparable with the ` +
        `CA's above.</p>` : "") +
      `<p class="muted">The agent is linear Q-learning: it scores each empty cell ` +  //what the agent sees and learns
      `from ${rl.features?.length ?? 13} numbers (neighbours of each land use, road access, ` +
      `distance to water and a few flags) and learns one weight per number for each ` +
      `use it may place, so its preferences can be read off.</p>` +
      `<p class="muted">The RL agent optimises this objective directly, while the ` +
      `CA follows fixed rules and is merely scored on it — so a higher number is ` +
      `expected and is <em>not</em> evidence that RL models cities better.</p>` +
      planSwitch() + comparisonTable()
      : `<p class="muted">RL agent not run yet — ` +
        `<code>analysis/abm_landuse/rl_landuse.py</code></p>`);

  function planSwitch() {
    if (!plans.free || !plans.keep) return "";
    return `<h4>Optimiser plan on the map</h4>` +
      `<div class="seg" id="luPlan">` +
      `<button data-p="free" class="on">no housing rule</button>` +
      `<button data-p="keep">housing kept</button></div>` +
      `<p class="muted" id="luPlanInfo"></p>`;
  }

  function planInfo() {
    const r = plans[planKey];
    const el = body.querySelector("#luPlanInfo");
    if (!r || !el) return;
    el.innerHTML = `${planKey === "keep" ? "All " + r.baseline_score.residential_cells +
      " housing cells kept" : "No rule on housing"}: objective ` +
      `${r.best_objective.toFixed(3)}, mix ${r.score.landuse_mix.toFixed(3)}, ` +
      `${(r.score.green_share * 100).toFixed(0)} % green, ` +
      `${r.score.residential_cells} housing cells. Switch on ` +
      `<em>RL site re-plan</em> under Land use to see it.`;
  }

  function comparisonTable() {
    const rows = [["no housing rule", rl, dqn], ["housing kept", rlKeep, dqnKeep]]
      .filter(([, a, b]) => a && b?.random_policy);
    if (!rows.length) return "";
    const f = (x) => (x == null ? "—" : x.toFixed(3));
    return `<h4>Linear agent vs deep Q-network</h4>` +
      `<table class="kv"><thead><tr><th>rule</th><th>random</th><th>linear</th>` +
      `<th>DQN best</th><th>DQN greedy</th></tr></thead><tbody>` +
      rows.map(([n, a, b]) => `<tr><td>${n}</td><td>${f(b.random_policy.mean)}</td>` +
        `<td>${f(a.best_objective)}</td><td>${f(b.best_objective)}</td>` +
        `<td>${f(b.greedy_objective)}</td></tr>`).join("") +
      `</tbody></table>` +
      `<p class="muted">Same site, objective and reward; only the agent differs. ` +
      `<em>Random</em> is the mean of a purely random policy, the baseline to beat. ` +
      `<em>Best</em> is the best training episode; <em>greedy</em> is one run of ` +
      `the DQN's learned policy with no exploration. The DQN is a convolutional ` +  //what the DQN is
      `network that reads the grid itself and scores every cell and use at once.</p>` +
      verdict(rows);  //what the numbers say, from the numbers
  }

  //one sentence on the comparison, generated so it cannot outlive a re-run
  function verdict(rows) {
    const below = rows.filter(([, , b]) => b.greedy_objective < b.random_policy.mean).map(([n]) => n);
    const linearWins = rows.every(([, a, b]) => a.best_objective >= b.best_objective);
    const parts = [];
    if (linearWins) parts.push("the linear agent's best plan beats or matches the DQN's under every rule");
    if (below.length) parts.push(`the DQN's learned policy scores below the random baseline (${below.join(", ")}), ` +
      `so with ${rows[0][2].parameters?.episodes ?? "these"} episodes it has not learned the problem`);
    return parts.length ? `<p class="muted">Result: ${parts.join("; ")}.</p>` : "";
  }

  const planBtns = [...body.querySelectorAll("#luPlan button")];
  planBtns.forEach((b) => b.addEventListener("click", async () => {
    planBtns.forEach((x) => x.classList.toggle("on", x === b));
    planKey = b.dataset.p;
    planInfo();
    await showPlan();
  }));
  planInfo();

  /* ---- the Rhino option on the same objective --------------------------
   * The only part of this card that follows the scenario switch: the team's
   * design scored like the CA's programmes, over the site and the buurt. */
  const rhinoEl = body.querySelector("#luRhino");
  function renderRhino(sc) {
    const runs = ["baseline", "scenario_a", "scenario_b"].filter((k) => rhino?.[k]?.open_ground_as_vacant);
    if (!runs.length) {
      rhinoEl.innerHTML = `<p class="muted">Rhino options not scored yet — ` +
        `<code>analysis/abm_landuse/score_scenarios.py</code></p>`;
      return;
    }
    const f = (x, d = 3) => (x == null ? "—" : x.toFixed(d));
    rhinoEl.innerHTML =
      `<h4>The design options on this objective</h4>` +
      `<table class="kv"><thead><tr><th>design site</th><th>objective</th><th>mix</th>` +
      `<th>green</th><th>home → amenity</th></tr></thead><tbody>` +
      runs.map((k) => {
        const s = rhino[k].open_ground_as_vacant.site;
        return `<tr${k === sc ? ' style="font-weight:600"' : ""}><td>${k === sc ? "▸ " : ""}${k}</td>` +  //the switch's scenario in bold
          `<td>${f(s.objective)}</td><td>${f(s.landuse_mix)}</td>` +
          `<td>${f(100 * s.green_share, 0)} %</td><td>${f(s.mean_distance_to_amenity_m, 0)} m</td></tr>`;
      }).join("") +
      `</tbody></table>` +
      `<p class="muted">The Rhino options burned into today's 25 m grid and scored like the ` +
      `programmes below. Mix counts green as a use, so housing replaced by green raises it ` +
      `even with fewer shops. Open ground the model leaves unprogrammed counts as vacant; ` +
      `counted as green the site objective would be ` +
      runs.filter((k) => rhino[k].open_ground_as_green)
        .map((k) => `${f(rhino[k].open_ground_as_green.site.objective)} (${k})`).join(", ") + `.</p>`;
  }
  ctx.onScenarioChange(renderRhino);  //the programmes below no longer follow the switch, this does

  render();
  ctx.note(`Land use: CA + RL, best programme ${ca.preferred}`, "ok");
}
