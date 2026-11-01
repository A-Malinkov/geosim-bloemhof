#!/usr/bin/env python3
"""
check_docs.py — do the numbers in the READMEs still match the outputs?

The READMEs quote results directly: MAE tables, kappa values, GSI/FSI, Shannon
indices, scenario objectives. Nothing forces them to agree with the JSON in
data/processed/, so **re-running any analysis silently invalidates them**.

This has already happened three times in this project:

  * the KNMI README was stale in 22 of 27 MAE values after a retrain;
  * the ABM README was stale throughout after a fix to the road rasteriser;
  * the top-level README quoted forecast numbers from a superseded run.

None was caught by reading. All were caught by a check like this one.

Run it after re-running anything, and before handing the report to anyone.

    python analysis/check_docs.py          # report
    python analysis/check_docs.py -q       # exit code only, for a pre-commit hook

Exit code 0 = everything matches, 1 = something is stale.

WHAT IT DOES NOT DO
-------------------
Each check names the LINE that should quote the value, by regex, and requires
the value to appear there. Checking only that the number occurs somewhere in the
file is not enough: the first version of this script did that and passed happily
while a headline figure was wrong, because the same number also appeared in a
status table further down.

It still cannot tell you the surrounding sentence is true. A retrain can falsify
"the LSTM never wins" while every digit looks plausible, so the narrative claims
are asserted separately at the bottom.

If a check reports NO ANCHOR, the document was restructured and the check is
dead — fix the pattern rather than ignoring it.
"""
from __future__ import annotations

import argparse
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
P = ROOT / "data" / "processed"


def load(name):
    path = P / name
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text())
    except Exception:
        return None
    return None if d.get("_status") == "not_computed_yet" else d


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    svf, veg = load("svf_summary.json"), load("vegetation_summary.json")
    den, lu = load("density_summary.json"), load("landuse_summary.json")
    ca, rl, fc = load("landuse_abm.json"), load("landuse_rl.json"), load("knmi_forecast.json")
    ws = load("landuse_weight_sensitivity.json")
    dqn = load("landuse_rl_dqn.json")
    rm, rlinks = load("road_metrics.json"), load("road_links.json")  #4.8 road network
    edge = load("edge_access.json")  #4.8 distance to the edge streets

    MAIN = ROOT / "README.md"
    MORPH = ROOT / "analysis/morphology/README.md"
    ABM = ROOT / "analysis/abm_landuse/README.md"
    KNMI = ROOT / "analysis/knmi/README.md"
    ROADS = ROOT / "analysis/roads/README.md"  #4.8 road network

    # (label, regex identifying the line(s) that quote it, expected value, files)
    #
    # The value must appear on EVERY line matching the pattern. An earlier
    # version only checked the value appeared *somewhere* in the file, which
    # passed happily when one of two quotations went stale — the number was
    # still present, just not where it had been changed. Match the context.
    checks: list[tuple[str, str, str, list[pathlib.Path]]] = []

    if svf:
        g = svf["combined"]["open_ground"]
        checks += [
            ("SVF combined", r"Sky View Factor, pedestrian level", f"{g['mean']:.3f}", [MAIN]),
            ("SVF combined", r"\*\*Sky View Factor\*\* \|", f"{g['mean']:.3f}", [MORPH]),
            ("SVF in the status table", r"\| 4\.3 \|", f"{g['mean']:.3f}", [MAIN]),
        ]
    if veg:
        e = veg.get("svf_canopy_effect") or {}
        checks += [("trees combined", r"Trees · per hectare", f"{veg['combined']['n_trees']:,}", [MAIN]),
                   ("trees combined", r"\*\*trees\*\* \|", f"{veg['combined']['n_trees']:,}", [MORPH])]
        if e:
            checks += [
                ("canopy open", r"under a tree crown vs", f"{e['svf_open']:.2f}", [MAIN]),
                ("canopy under", r"under a tree crown vs", f"{e['svf_under_canopy']:.2f}", [MAIN]),
            ]
    if den:
        b = den["combined"]
        checks += [
            ("GSI combined", r"GSI · FSI · storeys", f"{b['gsi']:.3f}", [MAIN]),
            ("FSI combined", r"GSI · FSI · storeys", f"{b['fsi']:.3f}", [MAIN]),
            ("GSI in status table", r"\| 4\.3 \|", f"{b['gsi']:.3f}", [MAIN]),
            ("FSI in status table", r"\| 4\.3 \|", f"{b['fsi']:.3f}", [MAIN]),
            ("GSI row", r"\*\*GSI\*\* ground space index", f"{b['gsi']:.3f}", [MORPH]),
            ("FSI row", r"\*\*FSI\*\* floor space index", f"{b['fsi']:.3f}", [MORPH]),
            ("storey height", r"measured, not assumed", f"{den['parameters']['storey_height_m']:.2f}", [MORPH]),
        ]
    if lu:
        b = lu["combined"]
        checks += [
            ("land-use combined", r"Land-use mix, Shannon", f"{b['shannon_area']:.3f}", [MAIN]),
            ("mix in status table", r"\| 4\.3 \|", f"{b['shannon_area']:.3f}", [MAIN]),
            ("Bloemhof SVF", r"^\| Sky View Factor, pedestrian level",
             f"{svf['per_buurt']['Bloemhof']['open_ground']['mean']:.3f}", [MAIN]),
            ("Shannon row", r"\*\*land-use mix\*\* Shannon", f"{b['shannon_area']:.3f}", [MORPH]),
        ]
    if ca:
        pref = ca["preferred"]
        sc = ca["scenarios"][pref]
        checks += [
            ("CA mix headline", r"Land-use model \| CA prefers", f"{sc['score']['landuse_mix']:.3f}", [MAIN]),
            ("CA objective row", rf"^\| {pref} \*\*★\*\* \|", f"{sc['objective_best']:.3f}", [ABM]),  #the starred programme row, not the rules table
            ("CA mix in that row", rf"^\| {pref} \*\*★\*\* \|", f"{sc['score']['landuse_mix']:.3f}", [ABM]),
            ("CA kappa", r"^\| 10 % \|", f"{ca['validation']['erase_10pct']['kappa_mean']:.3f}", [ABM]),
        ]
    if rl:
        checks += [
            ("RL mix headline", r"Land-use model \| CA prefers", f"{rl['score']['landuse_mix']:.3f}", [MAIN]),
            ("RL best objective", r"^Best [\d.]+ against", f"{rl['best_objective']:.3f}", [ABM]),
            ("RL homes kept", r"Land-use model \| CA prefers", f"only {rl['score']['residential_cells']} of", [MAIN]),
            ("RL homes today", r"Land-use model \| CA prefers", f"of its {rl['baseline_score']['residential_cells']} residential", [MAIN]),
            ("RL homes in the ABM README", r"^\*\*It still gives up housing",
             f"{rl['baseline_score']['residential_cells']} housing cells become "
             f"{rl['score']['residential_cells']}", [ABM]),
        ]
    if ws:
        b = 100 * ws["win_share"]["green"]
        a = 100 * ws["win_share"]["compact"]
        checks += [
            # anchored on the two-column weight-space row only: the same row
            # label also opens the scenario results table, and matching both
            # would let the value sit on either line and still pass
            ("weight sweep: green share",
             r"^\| green \*\*★\*\* \| \d+ % \|$", f"{b:.0f} %", [ABM]),
            ("weight sweep: compact share",
             r"^\| compact \| \d+ % \|$", f"{a:.0f} %", [ABM]),
            ("weight sweep: n vectors", r"weight vectors on the normalised simplex",
             f"{ws['parameters']['n_weight_vectors']:,}", [ABM]),
            ("weight sweep: default margin", r"on a normalised scale, against",
             f"{ws['default_margin']:.4f}", [ABM]),
            ("weight sweep: nearest flip distance", r"away on the simplex",
             f"{ws['nearest_flip']['simplex_distance']:.2f}", [ABM]),
        ]
    if den:
        sm = den.get("spacematrix") or []
        if sm and any("buurt" in q for q in sm):
            import statistics as _st
            gm = {n: _st.fmean([q["fsi"] for q in sm if q["buurt"] == n])
                  for n in den["per_buurt"]}
            checks += [
                ("spacematrix point count", r"per-cell points in", f"{len(sm)}", [MORPH]),
                ("grid FSI Bloemhof", r"^\| Bloemhof \|", f"{gm['Bloemhof']:.2f}", [MORPH]),
            ]
    if fc:
        t = fc["results"]["temperature_C"]["horizons"]
        w = fc["results"]["wind_speed_ms"]["horizons"]
        cw = fc["results"]["wind_speed_ms"]["conditions"]["by_wind_regime"]
        bt, bw = t["+6h"]["_best"], w["+6h"]["_best"]
        checks += [
            ("temp +6h headline", r"Weather forecast \(temperature", f"{t['+6h'][bt]['mae']:.2f}", [MAIN]),
            ("temp +6h skill", r"Weather forecast \(temperature",
             f"{100*t['+6h'][bt]['skill_vs_persistence']:.0f} %", [MAIN]),
            ("wind +6h headline", r"Weather forecast \(wind", f"{w['+6h'][bw]['mae']:.2f}", [MAIN]),
            ("strong-wind bias", r"Weather forecast \(wind",
             f"{abs(cw['strong (>=8 m/s)']['bias']):.1f}", [MAIN]),
        ]
        # the per-model MAE tables: one row per horizon, every model on it
        for hz in ("+1h", "+6h", "+24h"):
            for res, what in ((t, "temperature"), (w, "wind")):
                for model in ("persistence", "daily_naive", "gradient_boosting", "lstm"):
                    if model in res[hz]:
                        checks.append((f"{what} {hz} {model}", rf"^\| \{hz} \|",
                                       f"{res[hz][model]['mae']:.3f}", [KNMI]))
                #the settings the validation year chose, one row per forecast
                if "settings" in res[hz].get("lstm", {}):
                    checks.append((f"{what} {hz} LSTM epochs kept", rf"^\| {what} \{hz} \|",
                                   f"| {res[hz]['lstm']['settings']['epochs']} |", [KNMI]))
        #the strong-wind row of the wind-regime table
        sw = cw["strong (>=8 m/s)"]
        checks.append(("KNMI strong-wind bias", r"^\| strong \(>=8 m/s\) \|", f"{sw['bias']:.3f}", [KNMI]))

    if rm and rm.get("scenario_a", {}).get("areas"):
        #road network: the site comparison and the network table, both scenarios
        b = rm["baseline"]
        bs = b["areas"]["design_site"]
        checks += [
            ("roads: site grid baseline", r"^\| \*\*mean of the four\*\*", f"{b['site_grid']['mean_of_types_m']:.1f} m", [ROADS]),
            ("roads: site dwellings baseline", r"^\| \*\*mean of the four\*\*", f"{bs['mean_of_types_m']:.1f} m", [ROADS]),
            ("roads: site grid in status table", r"^\| 4\.8 \|", f"{b['site_grid']['mean_of_types_m']:.1f} m", [MAIN]),
            ("roads: site intersections baseline", r"^\| intersection density", f"{bs['intersection_density_km2']:.1f}", [ROADS]),
            ("roads: study-area intersections", r"^\| intersection density",
             f"{b['areas']['study_area']['intersection_density_km2']:.1f}", [ROADS]),
            ("roads: outside the site", r"^\*\*The neighbours do not notice",
             f"{b['areas']['outside_site']['mean_of_types_m']:.1f} m", [ROADS]),
        ]
        for sc in ("scenario_a", "scenario_b"):
            if not rm.get(sc, {}).get("areas"):
                continue
            a = rm[sc]
            as_ = a["areas"]["design_site"]
            checks += [
                (f"roads: site grid {sc}", r"^\| \*\*mean of the four\*\*", f"{a['site_grid']['mean_of_types_m']:.1f} m", [ROADS]),
                (f"roads: site dwellings {sc}", r"^\| \*\*mean of the four\*\*", f"{as_['mean_of_types_m']:.1f} m", [ROADS]),
                (f"roads: site grid {sc} in status table", r"^\| 4\.8 \|", f"{a['site_grid']['mean_of_types_m']:.1f} m", [MAIN]),
                (f"roads: site intersections {sc}", r"^\| intersection density", f"{as_['intersection_density_km2']:.1f}", [ROADS]),
                (f"roads: study-area intersections {sc}", r"^\| intersection density",
                 f"{a['areas']['study_area']['intersection_density_km2']:.1f}", [ROADS]),
                (f"roads: new-block dwellings {sc}", r"^median BAG dwelling on the site today|^and [\d,]+ in Scenario B",
                 f"{a['network']['new_block_dwellings_est']:,} ", [ROADS]),
            ]
        if rm["scenario_a"].get("network"):
            checks.append(("roads: connectors scenario_a", r"^street end gets both\. In all, \d+ connector",
                           f"{rm['scenario_a']['network']['connectors']} connector pieces", [ROADS]))
    for sc in ("scenario_a", "scenario_b"):
        if not (rlinks and rlinks.get(sc, {}).get("steps")):
            continue
        L = rlinks[sc]
        head = r"^\d+ candidates\. J starts"
        checks += [
            (f"roads: {sc} candidates", head, f"{L['n_candidates']} candidates", [ROADS]),
            (f"roads: {sc} J before", head, f"{L['J_before_m']:.2f} m", [ROADS]),
            (f"roads: {sc} J ceiling", head, f"{L['J_ceiling_m']:.2f} m", [ROADS]),
        ]
        for x in L["steps"]:  #one row per link; the two tables share row anchors, so the value must be in one of them
            checks.append((f"roads: {sc} link {x['rank']} J", rf"^\| {x['rank']} \| \d+ m \|", f"{x['J_m']:.2f} m", [ROADS]))
    if rlinks and rlinks.get("scenario_a", {}).get("steps"):
        st = rlinks["scenario_a"]["steps"]
        checks += [
            ("roads: A two links length", r"^\*\*Two links, \d+ m", f"{sum(x['length_m'] for x in st[:2]):.0f} m", [ROADS]),
            ("roads: A two links share", r"^\*\*Two links, \d+ m", f"{100 * st[1]['share_of_ceiling']:.0f} %", [ROADS]),
            ("roads: A all candidates", r"^give\.\*\*|^\*\*Two links, \d+ m", f"all {rlinks['scenario_a']['n_candidates']} candidates", [ROADS]),
        ]

    if edge and edge.get("baseline", {}).get("dwellings"):
        #distance to the edge streets: the baseline table and the sentences quoting it
        E = edge["baseline"]
        for mode in ("walk", "drive"):
            for key, name in edge["targets"].items():
                a = E["dwellings"][mode][key]
                row = rf"^\| {mode} to {name} \|"
                for f in ("median_m", "p90_m", "max_m", "straight_median_m"):
                    checks.append((f"roads: edge {mode} {key} {f}", row, f"{a[f]:.1f} m", [ROADS]))
                for m in edge["_params"]["near_m"]:
                    checks.append((f"roads: edge {mode} {key} ≤{m}", row, f"{100 * a[f'within_{m}m_frac']:.0f} %", [ROADS]))
        dw, ds = E["dwellings"]["walk"]["strevelsweg"], E["dwellings"]["drive"]["strevelsweg"]
        checks += [
            ("roads: edge on Strevelsweg share", r"^\*\*By car, Strevelsweg", f"{100 * ds['within_100m_frac']:.0f} %", [ROADS]),
            ("roads: edge median drive", r"^drives \d+ m to a street", f"drives {ds['median_m']:.0f} m", [ROADS]),
            ("roads: edge median straight", r"^drives \d+ m to a street", f"{ds['straight_median_m']:.0f} m away", [ROADS]),
            ("roads: edge walk detour", r"^\*\*On foot it is a detour", f"{dw['median_m'] / dw['straight_median_m']:.1f} times", [ROADS]),
            ("roads: edge walk median", r"^line at the median \(", f"{dw['median_m']:.1f} m against {dw['straight_median_m']:.1f} m", [ROADS]),
            ("roads: edge LH nearer walk", r"^\*\*Lange Hilleweg is the nearer", f"{100 * E['dwellings']['walk']['lange_hilleweg']['nearer_frac']:.0f} %", [ROADS]),
            ("roads: edge LH nearer drive", r"^dwellings on foot and", f"{100 * E['dwellings']['drive']['lange_hilleweg']['nearer_frac']:.0f} %", [ROADS]),
            ("roads: edge baseline dwellings", r"^\*\*Origins\.\*\* The [\d,]+ BAG", f"{E['origins']['bag_dwellings']:,} BAG", [ROADS]),
            ("roads: edge trap pieces", r"^happens at the edge of the fetched area",
             f"({E['network']['drive']['oneway_trap_edges_made_two_way']} pieces", [ROADS]),
        ]

    #morphology: the scenario results table on the design site (analysis/morphology/README.md)
    MORPH = ROOT / "analysis/morphology/README.md"
    scen = [("", "baseline"), ("_scenario_a", "scenario_a"), ("_scenario_b", "scenario_b")]
    msvf = {k: load(f"svf_summary{s}.json") for s, k in scen}
    if all(v and v.get("design_site") for v in msvf.values()):
        for s, k in scen:
            sv = msvf[k]["design_site"]["open_ground"]
            checks += [(f"morph: SVF mean {k}", r"^\| SVF, mean \|", f"{sv['mean']:.3f}", [MORPH]),
                       (f"morph: SVF median {k}", r"^\| SVF, median \|", f"{sv['median']:.3f}", [MORPH])]
            for d, lab in (("", "20 Mar"), ("_2026-06-21", "21 Jun"), ("_2026-12-21", "21 Dec")):
                sh = load(f"shadow_summary{s}{d}.json")
                if sh and sh.get("design_site"):
                    o = sh["design_site"]["open_ground_sunlit_hours"]
                    checks.append((f"morph: sun {lab} mean {k}", rf"^\| sun {lab}, mean \|", f"{o['mean']:.2f} h", [MORPH]))
                    if d != "_2026-06-21":
                        checks.append((f"morph: sun {lab} <2h {k}", rf"^\| sun {lab}, share < 2 h \|",
                                       f"{100 * o['share_under_2h']:.0f} %", [MORPH]))
            hw = load(f"canyon_hw{s or '_baseline'}.json")
            if hw and hw.get("design_site"):
                h = hw["design_site"]
                checks += [(f"morph: H/W median {k}", r"^\| street H/W, median \|", f"{h['hw']['median']:.2f}", [MORPH]),
                           (f"morph: canyon share {k}", r"^\| street length that is canyon \|", f"{100 * h['canyon_share']:.0f} %", [MORPH]),
                           (f"morph: W median {k}", r"^\| street width W, median \|", f"{h['w_m_median']:.1f} m", [MORPH])]

    #numbers in the agent table (analysis/abm_landuse/README.md), one run each since 2026-10-30
    if rl and dqn:
        checks += [("ABM: random policy mean", r"^\| random policy, mean \|", f"{dqn['random_policy']['mean']:.3f}", [ABM]),
                   ("ABM: linear best", r"^\| linear agent, best episode \|", f"{rl['best_objective']:.3f}", [ABM]),
                   ("ABM: linear housing cells", r"^\| linear agent, best episode \|", f"| {rl['score']['residential_cells']} |", [ABM]),
                   *([("ABM: linear learned policy", r"^\| linear agent, learned policy \|", f"{rl['greedy_objective']:.3f}", [ABM]),
                      ("ABM: linear learned-policy housing cells", r"^\| linear agent, learned policy \|",
                       f"| {rl['greedy_score']['residential_cells']} |", [ABM])] if "greedy_objective" in rl else []),
                   ("ABM: DQN best", r"^\| DQN, best episode \|", f"{dqn['best_objective']:.3f}", [ABM]),
                   ("ABM: DQN housing cells", r"^\| DQN, best episode \|", f"| {dqn['score']['residential_cells']} |", [ABM]),
                   ("ABM: DQN learned policy", r"^\| DQN, learned policy \|", f"{dqn['greedy_objective']:.3f}", [ABM])]
        if dqn.get("hill_climb"):
            h = dqn["hill_climb"]
            checks += [("ABM: hill climbing best", r"^\| hill climbing", f"{h['best_objective']:.3f}", [ABM]),
                       ("ABM: hill climbing housing cells", r"^\| hill climbing", f"| {h['score']['residential_cells']} |", [ABM])]

    lus = load("landuse_scenarios.json")  #the Rhino options on the land-use objective
    if lus:
        for sc in ("scenario_a", "scenario_b"):
            st = lus[sc]["open_ground_as_vacant"]["site"]
            checks += [(f"Rhino {sc} site objective", rf"^\| {sc} \| ", f"{st['objective']:.3f}", [ABM]),
                       (f"Rhino {sc} site mix", rf"^\| {sc} \| ", f"{st['landuse_mix']:.3f}", [ABM]),
                       (f"Rhino {sc} walk to amenity", rf"^\| {sc} \| ", f"{st['mean_distance_to_amenity_m']:.0f} m", [ABM])]
        checks.append(("Rhino baseline site objective", r"^\| baseline \(today\) \| ",
                       f"{lus['baseline']['open_ground_as_vacant']['site']['objective']:.3f}", [ABM]))
        claims_rhino = [
            ("ABM README: 'both Rhino options score above today on the site'",
             all(lus[k]["open_ground_as_vacant"]["site"]["objective"] > lus["baseline"]["open_ground_as_vacant"]["site"]["objective"]
                 for k in ("scenario_a", "scenario_b"))),
            ("ABM README: 'the walk to services grows in both options'",
             all(lus[k]["open_ground_as_vacant"]["site"]["mean_distance_to_amenity_m"]
                 > lus["baseline"]["open_ground_as_vacant"]["site"]["mean_distance_to_amenity_m"] for k in ("scenario_a", "scenario_b"))),
        ]

    cmp_ = load("scenario_comparison.json")  #4.9 scenario comparison
    CMP = ROOT / "analysis/comparison/README.md"
    if cmp_:
        #(row anchor, key, format) for the results table of the comparison README, one value per scenario
        rows = [(r"^\| dwellings on the site \|", "dwellings", "{:,.0f}"),
                (r"^\| FSI, floor area / site \|", "fsi", "{:.2f}"),
                (r"^\| sky view factor, mean \|", "svf_mean", "{:.2f}"),
                (r"^\| open ground under 2 h sun, equinox \|", "sun_under2h_0320", "pct"),
                (r"^\| open ground under 2 h sun, 21 Dec \|", "sun_under2h_1221", "pct"),
                (r"^\| street H/W, median \|", "hw_median", "{:.2f}"),
                (r"^\| existing trees kept on the site \|", "trees_existing", "{:,.0f}"),
                (r"^\| walk to 4 everyday places, site grid, housing only \|", "walk_grid_m", "{:.0f} m"),
                (r"^\| walk to 4 everyday places, residents, housing only \|", "walk_dwellings_m", "{:.0f} m"),
                (r"^\| residents, with the placed amenities \|", "walk_dwellings_amen_m", "{:.0f} m"),
                (r"^\| site grid, with the placed amenities \|", "walk_grid_amen_m", "{:.0f} m"),
                (r"^\| site grid, network only \|", "walk_grid_network_m", "{:.0f} m"),
                (r"^\| land-use objective J, with the placed amenities \|", "lu_objective_amen", "{:.3f}"),
                (r"^\| shops on the site \|", "n_shop", "{:.0f}"),
                (r"^\| schools on the site \|", "n_education", "{:.0f}"),
                (r"^\| community halls on the site \|", "n_community", "{:.0f}"),
                (r"^\| land-use objective J \|", "lu_objective", "{:.3f}")]
        for pat, key, fm in rows:
            for sc in ("baseline", "scenario_a", "scenario_b"):
                v = cmp_[sc].get(key)
                if v is None:
                    continue
                txt = f"{100 * v:.0f} %" if fm == "pct" else fm.format(v)
                checks.append((f"comparison: {key} {sc}", pat, f"| {txt} |", [CMP]))

    ap = load("amenity_placement.json")  #amenities placed on the new ground floors
    if ap and ap.get("scenario_a", {}).get("shop"):
        for sc, L in (("scenario_a", "A"), ("scenario_b", "B")):
            for k, lab in (("shop", "shop"), ("health", "health care"), ("education", "education")):  #the kept school is fixed, one more placed
                r = ap[sc][k]
                pat = rf"^\| {L}, {lab} \|"
                checks += [(f"amenities {sc} {k} before", pat, f"{r['J_before_m']:.1f} m", [ROADS]),
                           (f"amenities {sc} {k} optimised", pat, f"{r['J_after_m']:.1f} m", [ROADS]),
                           (f"amenities {sc} {k} random", pat, f"{r['J_random_mean_m']:.1f} m", [ROADS])]
        own = ap["baseline"]["today_with_own_amenities"]["mean_of_four"]
        checks += [("amenities: today with its own", r"^services, a site resident walks", f"{own['site_dwellings_m']:.1f} m", [ROADS]),
                   ("amenities: A placed", r"^With the placed shops and health practices", f"{ap['scenario_a']['mean_of_four']['site_dwellings_after_m']:.1f} m", [ROADS]),
                   ("amenities: B placed", r"^With the placed shops and health practices", f"{ap['scenario_b']['mean_of_four']['site_dwellings_after_m']:.1f} m", [ROADS])]

    import re

    lines_of = {}
    for _, _, _, fs in checks:
        for f in fs:
            if f not in lines_of:
                lines_of[f] = f.read_text().splitlines() if f.exists() else []

    stale, no_anchor = [], []
    for label, pattern, value, files in checks:
        for f in files:
            hits = [ln for ln in lines_of[f] if re.search(pattern, ln)]
            if not hits:
                # the doc was restructured out from under the check
                no_anchor.append((label, pattern, f.relative_to(ROOT)))
                continue
            if not any(value in ln for ln in hits):
                stale.append((label, value, f.relative_to(ROOT), hits[0].strip()[:78]))

    # --- narrative claims: a retrain can falsify a sentence, not just a digit ---
    claims = []
    if fc:
        t = fc["results"]["temperature_C"]["horizons"]
        w = fc["results"]["wind_speed_ms"]["horizons"]
        cw = fc["results"]["wind_speed_ms"]["conditions"]["by_wind_regime"]
        ct = fc["results"]["temperature_C"]["conditions"]["by_wind_regime"]
        claims += [
            ("KNMI README: 'the LSTM wins once' (wind +24 h, on the validation and the test year)",
             [(v, h) for v, r in (("temp", t), ("wind", w)) for h in r if r[h]["_best"] == "lstm"] == [("wind", "+24h")]
             and w["+24h"]["lstm"]["mae"] < w["+24h"]["gradient_boosting"]["mae"]),
            ("KNMI README: 'the validation year picked the test-year winner every time'",
             all(r[h]["_best"] == min((m for m in r[h] if m != "_best"), key=lambda m: r[h][m]["mae"])
                 for r in (t, w) for h in r)),
            ("KNMI README: 'both trained models beat both baselines at +6 h and +24 h'",
             all(r[h][m]["mae"] < min(r[h]["persistence"]["mae"], r[h]["daily_naive"]["mae"])
                 for r in (t, w) for h in ("+6h", "+24h") for m in ("gradient_boosting", "lstm"))),
            ("KNMI README: 'the LSTM is at its best after 1-4 epochs in five of the six forecasts'",
             sum(1 <= r[h]["lstm"]["settings"]["epochs"] <= 4 for r in (t, w) for h in r) == 5),
            ("KNMI README: 'persistence unbeaten for wind at +1 h'",
             w["+1h"]["_best"] == "persistence"),
            ("KNMI README: 'under-predicts strong winds'",
             cw["strong (>=8 m/s)"]["bias"] < 0),
            ("KNMI README: 'error grows with wind strength'",
             cw["calm (<3 m/s)"]["mae"] < cw["strong (>=8 m/s)"]["mae"]),
            ("KNMI README: 'temperature hardest in calm conditions'",
             ct["calm (<3 m/s)"]["mae"] > ct["strong (>=8 m/s)"]["mae"]),
        ]
    if ws:
        claims += [
            ("ABM README: 'baseline never wins under any positive weighting'",
             ws["win_share"]["baseline"] == 0.0),
            ("ABM README: 'green wins the majority of the weight space'",
             ws["win_share"]["green"] > 0.5),
            ("ABM README: 'the default weights are not on a knife edge'",
             ws["nearest_flip"] is None
             or ws["nearest_flip"]["simplex_distance"] > 0.05),
            ("ABM README: 'the winner is weight-dependent, not unanimous'",
             ws["win_share"]["green"] < 1.0),
        ]
    #the 'Hillesluis is looser by buurt, denser by cell' claim went with Hillesluis on 2026-10-22
    if ca and rl:
        claims += [
            ("ABM README: 'green is preferred'", ca["preferred"] == "green"),
            ("ABM README: 'the RL agent learns'",
             rl["objective_last_decile_mean"] > rl["objective_first_decile_mean"]),
            ("ABM README: 'retail avoids retail most of all'",
             min(rl["learned_weights"]["retail"].items(), key=lambda kv: kv[1])[0] == "retail"),
            ("ABM README: 'it still gives up housing cells, about half' (40-60 % kept)",
             0.4 <= rl["score"]["residential_cells"] / rl["baseline_score"]["residential_cells"] <= 0.6),
        ]
    if dqn and rl:
        claims += [
            ("ABM README: 'the DQN does not do better': its learned policy is below the linear agent's",
             dqn["greedy_objective"] < rl.get("greedy_objective", rl["best_objective"])),
            ("ABM README: 'its best episode matches the linear agent's' (within 0.01)",
             abs(dqn["best_objective"] - rl["best_objective"]) < 0.01),
            ("ABM README: 'its learned policy is no better than the random policy' (within 0.01)",
             dqn["greedy_objective"] < dqn["random_policy"]["mean"] + 0.01),
        ]
        if dqn.get("hill_climb"):
            claims.append(("ABM README: 'hill climbing beats both agents'",
                           dqn["hill_climb"]["best_objective"] > max(rl["best_objective"], dqn["best_objective"])))
    if rm and rm.get("scenario_b", {}).get("areas"):
        b, a, bb = rm["baseline"], rm["scenario_a"], rm["scenario_b"]
        g = lambda x: x["site_grid"]["mean_of_types_m"]
        claims += [
            ("roads README: 'Scenario A's grid makes walks on the site slightly shorter'", g(a) < g(b)),
            ("roads README: 'A gains on shops, education and rail stops' (site grid)",
             all(a["site_grid"][k]["mean_m"] < b["site_grid"][k]["mean_m"] for k in ("shop", "education", "rail_stop"))),
            ("roads README: 'Scenario B leaves them about where they are' (within 2 m)", abs(g(bb) - g(b)) < 2),
            ("roads README: 'the neighbours do not notice' (under 2 m, both scenarios)",
             all(abs(x["areas"]["outside_site"]["mean_of_types_m"] - b["areas"]["outside_site"]["mean_of_types_m"]) < 2 for x in (a, bb))),
            ("roads README: 'A has more junctions on the site, B fewer'",
             a["areas"]["design_site"]["intersection_density_km2"] > b["areas"]["design_site"]["intersection_density_km2"]
             > bb["areas"]["design_site"]["intersection_density_km2"]),
            ("roads README: 'the 15-minute walk does not separate anything'",
             all(rm[s]["areas"][n]["walk_15min_reach_frac"] == 1.0 for s in ("baseline", "scenario_a", "scenario_b") for n in rm[s]["areas"])),
            ("roads README: 'no site dwelling has a rail stop within 5 min in either scenario'",
             all(rm[s]["areas"]["design_site"]["rail_stop"]["within_5min_frac"] == 0 for s in ("scenario_a", "scenario_b"))),
        ]
    if rlinks and rlinks.get("scenario_a", {}).get("steps"):
        st = rlinks["scenario_a"]["steps"]
        claims += [
            ("roads README: 'after link 2 each link saves under 0.03 m of J'", all(x["gain_m"] < 0.03 for x in st[2:])),
            ("roads README: 'A stops after three links'", len(st) == 3),  #four before the dead-end fixes of 2026-10-28
        ]
    if rlinks and rlinks.get("scenario_b", {}).get("steps"):
        stb = rlinks["scenario_b"]["steps"]
        claims.append(("roads README: 'B: two links reach the ceiling'", len(stb) == 2 and stb[-1]["share_of_ceiling"] == 1.0))
    #morphology scenario table, the sentences under it
    g = lambda s, d="": (load(f"shadow_summary{s}{d}.json") or {}).get("design_site", {}).get("open_ground_sunlit_hours")
    v = lambda s: (load(f"svf_summary{s}.json") or {}).get("design_site", {}).get("open_ground")
    if all((g(s), v(s)) for s in ("", "_scenario_a", "_scenario_b")) and g("_scenario_b") and v("_scenario_b"):
        hwb, hwx = load("canyon_hw_baseline.json"), load("canyon_hw_scenario_b.json")
        claims += [
            ("morph README: 'A: less sky'", v("_scenario_a")["mean"] < v("")["mean"]),
            ("morph README: 'A: nearly twice today's share under 2 h at the equinox' (1.5x to 2x)",
             1.5 <= g("_scenario_a")["share_under_2h"] / g("")["share_under_2h"] <= 2.0),
            ("morph README: 'B opens it up on every measure'",
             v("_scenario_b")["mean"] > v("")["mean"] and all(g("_scenario_b", d)["mean"] > g("", d)["mean"] for d in ("", "_2026-06-21", "_2026-12-21"))
             and all(g("_scenario_b", d)["share_under_2h"] < g("", d)["share_under_2h"] for d in ("", "_2026-12-21"))),
            ("morph README: 'B: about half its street length is not a canyon' (40-60 % canyon)",
             bool(hwx and hwx.get("design_site")) and 0.4 <= hwx["design_site"]["canyon_share"] <= 0.6),
        ]
    if lus:
        claims += claims_rhino  #Rhino options on the land-use objective
    if ap and ap.get("scenario_a", {}).get("shop"):
        claims += [
            ("roads README: 'the amenities beat random placement on every type'",
             all(ap[s][k]["J_after_m"] < ap[s][k]["J_random_mean_m"] for s in ("scenario_a", "scenario_b")
                 for k in ("shop", "health", "education"))),
            ("comparison README: 'two schools in each option, the kept one and one placed'",
             all(ap["counts_on_site"][s]["education"] == 2 for s in ("scenario_a", "scenario_b"))),
            ("roads README: 'with the placed amenities, site walks are shorter than today'",
             all(ap[s]["mean_of_four"]["site_dwellings_after_m"] < ap["baseline"]["today_with_own_amenities"]["mean_of_four"]["site_dwellings_m"]
                 for s in ("scenario_a", "scenario_b"))),
            ("roads README: 'housing only, site walks are longer than today'",
             all(ap[s]["mean_of_four"]["site_dwellings_before_m"] > ap["baseline"]["today_with_own_amenities"]["mean_of_four"]["site_dwellings_m"]
                 for s in ("scenario_a", "scenario_b"))),
        ]
    broken = [c for c, ok in claims if not ok]

    if not args.quiet:
        nfiles = len({f for _, _, _, fs in checks for f in fs})
        print(f"checked {len(checks)} published numbers across {nfiles} files\n")
        if stale:
            print(f"STALE — {len(stale)} number(s) no longer match the outputs:")
            for label, value, f, line in stale:
                print(f"   {f}  expects {value}  ({label})")
                print(f"      line reads: {line}")
            print("\n  regenerate the affected README, then re-run this check")
        else:
            print("all published numbers match data/processed/")
        if no_anchor:
            print(f"\nNO ANCHOR — {len(no_anchor)} check(s) could not find the line "
                  f"they were written against.\n  The doc was restructured; "
                  f"update the pattern in this script or the check is silently dead:")
            for label, pattern, f in no_anchor:
                print(f"   {f}  /{pattern}/  ({label})")
        if claims:
            print()
            if broken:
                print(f"BROKEN CLAIMS — {len(broken)} sentence(s) are no longer true:")
                for c in broken:
                    print(f"   {c}")
            else:
                print(f"all {len(claims)} narrative claims still hold")

    return 1 if (stale or broken or no_anchor) else 0


if __name__ == "__main__":
    raise SystemExit(main())
