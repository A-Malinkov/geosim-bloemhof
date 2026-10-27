/* =============================================================================
 * modules/comparison.js  —  component 9: scenario comparison
 * OWNER: Atanas Malinkov
 *
 * Today against the two Rhino options on the design site, one row per
 * indicator, written by analysis/comparison/compare_scenarios.py into
 *   data/processed/scenario_comparison.json
 * Each scenario cell shows the value and its change against today, marked
 * better or worse by the indicator's own direction. There is no overall score
 * on purpose: adding the indicators up needs weights, and the weights would
 * pick the winner. The column of the scenario the app is on is highlighted.
 * ========================================================================== */

const PATH = "../data/processed/scenario_comparison.json";
const SCEN = [["baseline", "Today"], ["scenario_a", "A"], ["scenario_b", "B"]];
const ROWS = [  //key, label, digits, as a percentage
  ["dwellings", "Dwellings", 0, false],
  ["buildings_demolished", "Buildings demolished", 0, false],
  ["fsi", "FSI", 2, false],
  ["svf_mean", "Sky view factor", 2, false],
  ["sun_under2h_0320", "Under 2 h sun, equinox", 0, true],
  ["sun_under2h_1221", "Under 2 h sun, 21 Dec", 0, true],
  ["hw_median", "Street H/W, median", 2, false],
  ["trees_existing", "Existing trees kept", 0, false],  //today's trees still standing on the site
  ["trees_proposed", "Proposed trees", 0, false],  //new planting from the Rhino model
  ["n_shop", "Shops on the site", 0, false],  //today from BAG; options placed (p-median) + kept
  ["n_education", "Schools on the site", 0, false],  //the kept school stays fixed
  ["n_community", "Community halls on the site", 0, false],
  ["walk_dwellings_m", "Walk to 4 places, residents, housing only (m)", 0, false],
  ["walk_grid_m", "Walk to 4 places, site grid, housing only (m)", 0, false],
  ["walk_dwellings_amen_m", "… with placed amenities (m)", 0, false],  //place_amenities.py: shops, health, school on the ground floors
  ["intersections_km2", "Intersections /km²", 0, false],
  ["lu_objective", "Land-use objective", 3, false],
  ["lu_objective_amen", "… with placed amenities", 3, false],  //the same objective with the amenities in their cells
];

export async function setup(ctx) {
  const body = ctx.registerPanel({
    id: "comparison",
    title: "Scenario comparison",
    subtitle: "design site · today against A and B",
    order: 7,
  });
  const data = await ctx.loadJson(PATH, { quiet: true });
  if (!data?.baseline) {
    ctx.placeholder(body, {
      what: "Scenario comparison not computed yet.",
      produces: "data/processed/scenario_comparison.json",
      owner: "analysis/comparison/compare_scenarios.py",
    });
    return;
  }
  const better = Object.fromEntries((data.indicators || []).map((i) => [i.key, i.better]));  //"higher" / "lower" / null

  const fmt = (v, d, pct) => v == null ? "—"
    : (pct ? 100 * v : v).toLocaleString("en-GB", { minimumFractionDigits: d, maximumFractionDigits: d }) + (pct ? " %" : "");

  //change against today; .delta.down is the "good" colour and .delta.up the "bad" one in style.css
  function delta(key, v, b, d, pct) {
    if (v == null || b == null) return "";
    const x = (pct ? 100 : 1) * (v - b);
    if (Math.abs(x) < 0.5 * 10 ** -d) return "";
    const dir = better[key];
    const good = dir === "higher" ? x > 0 : dir === "lower" ? x < 0 : null;
    const cls = good == null ? "" : good ? "down" : "up";  //no direction: shown, not coloured
    const txt = x.toLocaleString("en-GB", { minimumFractionDigits: d, maximumFractionDigits: d });  //thousands separator
    return ` <span class="delta ${cls}">${x > 0 ? "+" : ""}${txt}</span>`;
  }

  function render(current) {
    const hl = (s) => s === current ? ' style="background:rgba(120,160,220,0.14)"' : "";  //the scenario the app is on
    const rows = ROWS.filter(([k]) => SCEN.some(([s]) => data[s]?.[k] != null));  //land use only once it is computed
    body.innerHTML =
      `<table class="kv"><thead><tr><th></th>` +
      SCEN.map(([s, n]) => `<th${hl(s)}>${n}</th>`).join("") + `</tr></thead><tbody>` +
      rows.map(([k, label, d, pct]) => {
        const b = data.baseline[k];
        return `<tr><td>${label}</td>` + SCEN.map(([s]) =>
          `<td${hl(s)}>${fmt(data[s][k], d, pct)}${s === "baseline" ? "" : delta(k, data[s][k], b, d, pct)}</td>`).join("") + `</tr>`;
      }).join("") +
      `</tbody></table>` +
      `<p class="muted">Over the 13.24 ha design site. Change against today, green where it is better by the ` +
      `indicator's own direction, red where worse, plain where there is no better direction (FSI, H/W). ` +
      `No overall score: adding these up needs weights, and the weights would pick the winner. ` +
      `Not computed: ${(data.not_computed || []).map((n) => `${n.name} (${n.state})`).join(", ")}. ` +
      `Figures in <code>docs/fig_compare_*.png</code>.</p>`;
  }

  ctx.onScenarioChange(render);
}
