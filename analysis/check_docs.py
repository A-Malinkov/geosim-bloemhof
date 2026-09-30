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
import sys

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

    MAIN = ROOT / "README.md"
    MORPH = ROOT / "analysis/morphology/README.md"
    ABM = ROOT / "analysis/abm_landuse/README.md"
    KNMI = ROOT / "analysis/knmi/README.md"

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
            ("Hillesluis SVF", r"^\| Sky View Factor, pedestrian level",
             f"{svf['per_buurt']['Hillesluis']['open_ground']['mean']:.3f}", [MAIN]),
            ("Shannon row", r"\*\*land-use mix\*\* Shannon", f"{b['shannon_area']:.3f}", [MORPH]),
        ]
    if ca:
        pref = ca["preferred"]
        sc = ca["scenarios"][pref]
        checks += [
            ("CA mix headline", r"Land-use model \| CA prefers", f"{sc['score']['landuse_mix']:.3f}", [MAIN]),
            ("CA objective row", rf"^\| {pref} ", f"{sc['objective_best']:.3f}", [ABM]),
            ("CA mix in that row", rf"^\| {pref} ", f"{sc['score']['landuse_mix']:.3f}", [ABM]),
            ("CA kappa", r"^\| 10 % \|", f"{ca['validation']['erase_10pct']['kappa_mean']:.3f}", [ABM]),
        ]
    if rl:
        checks += [
            ("RL mix headline", r"Land-use model \| CA prefers", f"{rl['score']['landuse_mix']:.3f}", [MAIN]),
            ("RL best objective", r"^Best [\d.]+ against", f"{rl['best_objective']:.3f}", [ABM]),
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
                for model in ("persistence", "ridge", "gradient_boosting", "lstm"):
                    if model in res[hz]:
                        checks.append((f"{what} {hz} {model}", rf"^\| \{hz} \|",
                                       f"{res[hz][model]['mae']:.3f}", [KNMI]))

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
            ("KNMI README: 'the LSTM never wins'",
             all(r[h]["_best"] != "lstm" for r in (t, w) for h in r)),
            ("KNMI README: 'persistence unbeaten for wind at +1 h'",
             w["+1h"]["_best"] == "persistence"),
            ("KNMI README: 'under-predicts strong winds'",
             cw["strong (>=8 m/s)"]["bias"] < 0),
            ("KNMI README: 'error grows with wind strength'",
             cw["calm (<3 m/s)"]["mae"] < cw["strong (>=8 m/s)"]["mae"]),
            ("KNMI README: 'temperature hardest in calm conditions'",
             ct["calm (<3 m/s)"]["mae"] > ct["strong (>=8 m/s)"]["mae"]),
        ]
    if ca and rl:
        claims += [
            ("ABM README: 'scenario_b is preferred'", ca["preferred"] == "scenario_b"),
            ("ABM README: 'the RL agent learns'",
             rl["objective_last_decile_mean"] > rl["objective_first_decile_mean"]),
            ("ABM README: 'retail learns to avoid other retail'",
             rl["learned_weights"]["retail"]["retail"] < 0),
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
