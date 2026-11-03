/* =============================================================================
 * modules/comparison.js - component 9: scenario comparison
 * OWNER: Atanas Malinkov
 *
 * Today against the Rhino options and the final design on the site, one row per
 * indicator, written by analysis/comparison/compare_scenarios.py into
 *   data/processed/scenario_comparison.json
 * Each scenario cell shows the value and its change against today, green when
 * it goes up and red when it goes down (since 2026-11-03). There is no overall score
 * on purpose: adding the indicators up needs weights, and the weights would
 * pick the winner. The column of the scenario the app is on is highlighted.
 * ========================================================================== */

const PATH = "../data/processed/scenario_comparison.json";
const SCEN = [["baseline", "Today"], ["scenario_a", "A"], ["scenario_b", "B"], ["final", "Final"]];  //final: the Rhino Final Model
const ROWS = [  //key, label, digits, as a percentage
  ["dwellings", "Dwellings", 0, false],
  ["buildings_demolished", "Buildings demolished", 0, false],
  ["fsi", "FSI", 2, false],
  ["svf_mean", "Sky view factor", 2, false],
  ["sun_under2h_0320", "Under 2 h sun, equinox", 0, true],
  ["sun_under2h_1221", "Under 2 h sun, 21 Dec", 0, true],
  ["hw_median", "Street H/W, median", 2, false],
  ["trees_existing", "Existing trees kept", 0, false],  //today's trees still standing on the site
  ["green_total_m2", "Green area, gardens incl. (m²)", 0, false],  //BGT today, kept + proposed green (+ walkway) in a design
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
  ["wind_over11", "Windier than open country (> 1.1)", 0, true],  //OpenFOAM, open ground at 1.5 m
  ["noise_mean_db", "Road noise Lden, site + 200 m (dB)", 1, false],  //NoiseModelling
  ["noise_over53", "Above 53 dB Lden, site + 200 m", 0, true],
  ["flood_high_new", "Flood vulnerability high or very high", 0, true],  //Cyrille's new method, all ground
];

export async function setup(ctx) {
  const body = ctx.registerPanel({
    id: "comparison",
    title: "Scenario comparison",
    subtitle: "design site · today against A, B and the final design",
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
  const fmt = (v, d, pct) => v == null ? "-"
    : (pct ? 100 * v : v).toLocaleString("en-GB", { minimumFractionDigits: d, maximumFractionDigits: d }) + (pct ? " %" : "");

  //change against today, coloured by its sign: green up, red down (Atanas, 2026-11-03)
  function delta(key, v, b, d, pct) {
    if (v == null || b == null) return "";
    const x = (pct ? 100 : 1) * (v - b);
    if (Math.abs(x) < 0.5 * 10 ** -d) return "";
    const colour = x > 0 ? "var(--ok)" : "var(--err)";  //every row, whatever its better direction
    const txt = x.toLocaleString("en-GB", { minimumFractionDigits: d, maximumFractionDigits: d });  //thousands separator
    return ` <span class="delta" style="color:${colour}">${x > 0 ? "+" : ""}${txt}</span>`;
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
          `<td${hl(s)}>${fmt(data[s]?.[k], d, pct)}${s === "baseline" ? "" : delta(k, data[s]?.[k], b, d, pct)}</td>`).join("") + `</tr>`;  //a scenario missing from an older file shows a dash
      }).join("") +
      `</tbody></table>` +
      `<p class="muted">Over the 13.24 ha design site. Change against today, green where the value goes up, ` +
      `red where it goes down. A rise is not always better: more shade or longer walks show green too. ` +  //sign, not judgement
      `No overall score: adding these up needs weights, and the weights would pick the winner. ` +
      `Not computed: ${(data.not_computed || []).map((n) => `${n.name} (${n.state})`).join(", ")}. ` +
      `Figures in <code>docs/fig_compare_*.png</code>.</p>`;
  }

  ctx.onScenarioChange(render);
}
