/* =============================================================================
 * modules/landuse.js  —  component 7: agent-based / CA land-use model
 * OWNER: <put your name here>
 *
 * Cellular automata or reinforcement learning over the study area.
 * Computed in  analysis/abm_landuse/  ->  data/processed/landuse_abm.json
 *
 * Expected shape:
 * {
 *   "method": "cellular_automata" | "reinforcement_learning",
 *   "cell_size_m": 10,
 *   "bbox_rd": [xmin, ymin, xmax, ymax],
 *   "classes": ["residential", "commercial", "green", "water", "infrastructure"],
 *   "steps": [ { "t": 0, "grid": [[0,1,...], ...] }, { "t": 1, ... } ],
 *   "shares": [ { "t": 0, "residential": 0.41, ... } ]
 * }
 * ========================================================================== */

export async function setup(ctx) {
  const body = ctx.registerPanel({
    id: "landuse",
    title: "Land-use model",
    subtitle: "agent-based / cellular automata",
    order: 50,
  });

  const data = await ctx.loadJson(ctx.config.dataSources.processed.landuse);

  if (!data) {
    ctx.placeholder(body, {
      what: "Land-use model has not been run yet.",
      produces: "data/processed/landuse_abm.json",
      owner: "analysis/abm_landuse/ + app/modules/landuse.js",
    });
    return;
  }

  const steps = data.steps || [];
  body.innerHTML = `
    <table class="kv"><tbody>
      <tr><td>method</td><td>${data.method ?? "—"}</td></tr>
      <tr><td>cell size</td><td>${data.cell_size_m ?? "—"} m</td></tr>
      <tr><td>classes</td><td>${(data.classes || []).length}</td></tr>
      <tr><td>steps</td><td>${steps.length}</td></tr>
    </tbody></table>
    ${steps.length > 1 ? `
      <label class="slider">
        <span>step <output id="luOut">0</output></span>
        <input type="range" id="luStep" min="0" max="${steps.length - 1}" value="0">
      </label>` : ""}
    <p class="muted">TODO: render the grid as a draped overlay per time step.</p>`;

  const slider = body.querySelector("#luStep");
  if (slider) {
    slider.addEventListener("input", (e) => {
      body.querySelector("#luOut").textContent = e.target.value;
      // TODO: redraw the grid for steps[e.target.value]
    });
  }
}
