#!/usr/bin/env python3
"""
weight_sensitivity.py -- does the green programme win because it is better, or
because of the four weights we picked?

THE PROBLEM
-----------
ca_landuse.py ranks the scenarios on

    objective = 1.6*landuse_mix + 1.0*green_share + 0.8*max(0, 1 - d/400)
              + 1.1*min(1, homes / homes today)

and the green programme wins. Since 2026-10-30 the CA clears the design site and
rebuilds it, and the green programme asks for 120 housing cells against today's
160, so the housing term differs between programmes: the sweep varies all four
weights. Those weights were chosen by us. The README said so
and called a sensitivity sweep "the obvious next step", which is this file.

The margin is the reason it matters: green beats compact by about 0.02
while the spread between replicates of one scenario is about 0.003. A gap that
small is not obviously larger than the arbitrariness in the weights.

WHAT IT DOES
------------
Every CA replicate already stores its raw components, so the sweep needs
no re-run of the model: it re-scores the stored replicates under many weight
vectors and re-picks the best replicate each time, exactly as ca_landuse.py
does. Re-running the CA would give the same answer and take minutes.

Scaling all four weights leaves the ranking unchanged, so only the DIRECTION
matters. The sweep therefore walks the normalised simplex w_mix + w_green +
w_prox + w_housing = 1 on a lattice. A grid over raw weights would spend most of
its points re-testing the same ratios.

The CA's programmes are baseline, compact and green (keyed scenario_a and
scenario_b until 2026-10-27). They are not the Rhino design options.

Reported: which programme wins at each point, what share of the simplex each one
takes, where the default weights sit, and how far you have to move from them to
change the answer.

WHAT IT CANNOT TELL YOU
-----------------------
This sweeps the SCORING of the CA, which follows fixed transition rules and is
merely measured against the objective. It says nothing about the RL agent, which
optimises the objective directly: re-scoring a policy trained on one weight
vector under a different one is not the same experiment as training under that
vector, and pretending otherwise would flatter or damn the agent for free.
Retraining across the simplex is a separate, much slower job.

It also cannot tell you the objective contains the right four terms. A weight
sweep explores the space we chose; it does not question it.

    python analysis/abm_landuse/weight_sensitivity.py
    python analysis/abm_landuse/weight_sensitivity.py --step 0.01   # finer
"""
from __future__ import annotations

import argparse
import json
import pathlib

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"

#: The objective's weights: mix, green, walkability, housing; every model scores with these via components().
DEFAULT_W = (1.6, 1.0, 0.8, 1.1)  #housing added 2026-10-30, a bit above green and below mix (Atanas)
D_NORM = 400.0


def components(rep: dict, homes: float, homes_today: float) -> tuple[float, float, float, float]:
    """The four terms of the objective, before weighting.

    The one place the objective is defined: ca_landuse.py, rl_landuse.py and
    score_scenarios.py all score through it. A missing distance (no residential
    cell to measure from) scores as the worst case, not dropped, or scenarios get
    compared on different terms. Housing is homes against today, capped at 1: no
    net loss scores full marks, more homes earn nothing extra. Homes are housing
    cells for the grid models (CA, RL) and dwellings for the Rhino designs; each
    caller passes its own unit and its own today.
    """
    d = rep.get("mean_distance_to_amenity_m")
    d = D_NORM if d is None else d
    return (float(rep["landuse_mix"]),
            float(rep["green_share"]),
            max(0.0, 1.0 - d / D_NORM),
            min(1.0, homes / homes_today))  #no net loss of homes = 1


def simplex(step: float, d: int = 4) -> np.ndarray:
    """Lattice points on w_1 + ... + w_d = 1, all strictly positive.

    Zero weights are excluded: dropping a term is a different model, not a
    sensitivity of this one, and the corners would dominate the win shares.
    """
    from itertools import combinations
    n = int(round(1.0 / step))
    pts = []
    for cut in combinations(range(1, n), d - 1):  #d positive parts of n: choose d-1 cut points
        parts = np.diff((0, *cut, n))
        pts.append(parts / n)
    return np.array(pts, dtype=float)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--step", type=float, default=0.02,
                    help="lattice spacing on the weight simplex (default 0.02)")
    args = ap.parse_args()

    src = PROCESSED / "landuse_abm.json"
    if not src.exists():
        print(f"! {src.relative_to(ROOT)} missing -- run ca_landuse.py first")
        return 2
    abm = json.loads(src.read_text())
    if abm.get("_status") == "not_computed_yet":
        print("! landuse_abm.json is still a stub -- run ca_landuse.py first")
        return 2

    names = list(abm["scenarios"])
    homes_today = abm.get("homes_today_cells", abm["initial"]["score"]["residential_cells"])  #the CA counts housing cells on the site
    # components of every replicate, per scenario: (n_replicates, 4)
    comp4 = {k: np.array([components(r, r["residential_cells"], homes_today) for r in abm["scenarios"][k]["replicates"]])
             for k in names}
    n_rep = {k: len(v) for k, v in comp4.items()}
    print(f"re-scoring {sum(n_rep.values())} stored replicates "
          f"({', '.join(f'{k} {v}' for k, v in n_rep.items())})")

    # --- reproduce the published ranking, as a check on this script ----------
    w04 = np.array(DEFAULT_W)
    best0 = {k: float((comp4[k] @ w04).max()) for k in names}
    published = {r["scenario"]: r["objective_best"] for r in abm["ranking"]}
    drift = {k: abs(best0[k] - published[k]) for k in names}
    worst = max(drift.values())
    if worst > 5e-4:
        # If this fires, the objective here and the one in ca_landuse.py have
        # diverged and every number below is measuring the wrong thing.
        print("! FAILED to reproduce the published objectives from the stored "
              "replicates -- the objective in this script no longer matches "
              "ca_landuse.py:")
        for k in names:
            print(f"    {k:12} here {best0[k]:.4f}  published {published[k]:.4f}")
        return 1
    print(f"  reproduced the published objectives (max drift {worst:.2e})")

    comp, w0 = comp4, w04  #all four terms are swept
    # --- sweep ---------------------------------------------------------------
    W = simplex(args.step)
    # best replicate per scenario at every weight point: (n_points, n_scenarios)
    best = np.column_stack([(W @ comp[k].T).max(axis=1) for k in names])
    win = np.argmax(best, axis=1)
    order = np.sort(best, axis=1)
    margin = order[:, -1] - order[:, -2]

    counts = {names[i]: int((win == i).sum()) for i in range(len(names))}
    total = len(W)
    print(f"\n  {total:,} weight vectors on the simplex (step {args.step})")
    for k, c in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"    {k:12} wins {c:6,}  ({100*c/total:5.1f} % of the simplex)")

    # where the default sits, and the nearest point that flips the winner
    w0n = w0 / w0.sum()
    i0 = int(np.argmin(((W - w0n) ** 2).sum(axis=1)))
    default_winner = names[win[i0]]
    flip = win != win[i0]
    if flip.any():
        dist = np.sqrt(((W[flip] - w0n) ** 2).sum(axis=1))
        j = int(np.argmin(dist))
        flip_pt = W[flip][j]
        flip_to = names[win[flip][j]]
        flip_dist = float(dist[j])
    else:
        flip_pt, flip_to, flip_dist = None, None, None

    print(f"\n  default weights {DEFAULT_W} normalise to "
          f"({', '.join(f'{v:.3f}' for v in w0n)}) -> {default_winner} wins "
          f"by {margin[i0]:.4f}")
    if flip_to:
        print(f"  nearest flip: ({', '.join(f'{v:.2f}' for v in flip_pt)}) "
              f"-> {flip_to}, {flip_dist:.3f} away on the simplex")
    else:
        print("  no weight vector on the lattice changes the winner")

    # a readable slice: how the winner changes as the mix weight varies alone
    print("\n  holding green:prox:housing at the default ratio, varying the mix weight:")
    others = w0n[1:] / w0n[1:].sum()  #the other three weights' default proportions
    rows = []
    for wm in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        w = np.array([wm, *((1.0 - wm) * others)])
        vals = {k: float((comp[k] @ w).max()) for k in names}
        top = max(vals, key=vals.get)
        srt = sorted(vals.values(), reverse=True)
        rows.append({"w_mix": round(wm, 3), "winner": top,
                     "margin": round(srt[0] - srt[1], 4),
                     "objectives": {k: round(v, 4) for k, v in vals.items()}})
        print(f"    w_mix {wm:.1f} -> {top:12} margin {srt[0]-srt[1]:.4f}")

    out = {
        "method": "sensitivity of the CA scenario ranking to the objective weights",
        "_note": "The CA is not re-run. Every replicate stores its raw "
                 "objective components, so the sweep re-scores the stored "
                 "replicates and re-picks the best one, exactly as ca_landuse.py "
                 "does. Verified against the published ranking before sweeping.",
        "objective": "w_mix*landuse_mix + w_green*green_share + "
                     "w_prox*max(0, 1 - mean_home_to_amenity_m/400) + "
                     "w_housing*min(1, housing cells / housing cells today)",
        "default_weights": {"w_mix": DEFAULT_W[0], "w_green": DEFAULT_W[1],
                            "w_prox": DEFAULT_W[2], "w_housing": DEFAULT_W[3]},
        "_housing_note": "Since 2026-10-30 the green programme asks for fewer housing cells than "
                         "today, so the housing term differs between programmes and all four weights "
                         "are swept.",
        "default_weights_normalised": [round(float(v), 4) for v in w0n],
        "parameters": {
            "simplex_step": args.step,
            "n_weight_vectors": total,
            "replicates_per_scenario": n_rep,
            "zero_weights_excluded": True,
        },
        "default_winner": default_winner,
        "default_margin": round(float(margin[i0]), 4),
        "win_share": {k: round(c / total, 4) for k, c in counts.items()},
        "win_counts": counts,
        "nearest_flip": None if flip_to is None else {
            "weights": [round(float(v), 3) for v in flip_pt],
            "winner": flip_to,
            "simplex_distance": round(flip_dist, 4),
        },
        "mix_weight_slice": rows,
        "margin": {
            "at_default": round(float(margin[i0]), 4),
            "median_over_simplex": round(float(np.median(margin)), 4),
            "replicate_sd_at_default": {
                k: abm["scenarios"][k]["objective_sd"] for k in names
            },
        },
        "limitations": [
            "Sweeps the scoring of the CA only. The RL agent optimises the "
            "objective directly, so re-scoring its result under other weights "
            "is not the same as retraining under them.",
            "Explores the four terms we chose; it does not test whether they "
            "are the right four.",
            "Zero weights are excluded: dropping a term is a different model.",
        ],
    }
    path = PROCESSED / "landuse_weight_sensitivity.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(f"\n  wrote {path.relative_to(ROOT)}")

    # the headline, stated plainly
    share = counts[default_winner] / total
    print(f"\n  {default_winner} wins at the default weights and across "
          f"{100*share:.1f} % of the weight simplex.")
    if share < 0.5:
        print("  That is a MINORITY of the weight space: the published "
              "preference is weight-dependent and must be reported as such.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
