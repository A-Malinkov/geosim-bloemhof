#!/usr/bin/env python3
"""
rl_landuse.py — a reinforcement-learning agent for land-use allocation.

Component 4.7, the RL half. Owner: Atanas Malinkov

WHY BOTH A CA AND AN RL AGENT
-----------------------------
They answer different questions, and running both is the point.

    ca_landuse.py   rules are ASSUMED. The influence matrix says shops like
                    streets and industry repels housing, because we said so.
                    It shows what follows FROM those assumptions.

    rl_landuse.py   rules are LEARNED. The agent is told only the objective and
                    has to discover where to put things. Its learned weights can
                    be read off and compared with the CA's hand-set matrix —
                    where they agree, the assumption is supported; where they
                    disagree, one of them is worth arguing about.

THE FORMULATION
---------------
Episodic MDP. Each episode the agent places a fixed development programme, one
cell at a time:

    state   the grid so far
    action  (cell, class) — develop this cell as that use
    reward  the change in the planning objective caused by that placement,
            plus a terminal bonus for the final objective

    objective = 1.6 * land-use mix (Shannon)
              + 1.0 * green share
              + 0.8 * walkability (1 - mean home-to-amenity distance / 400 m)

    the same objective the CA is scored on, so the two are comparable.

Q(s, a) is linear in features of the candidate cell: how many neighbours of each
class it has, how reachable it is, whether it is currently vacant, and how close
it is to water. Linear rather than a deep network on purpose — the whole value
of the RL run here is that you can READ the learned weights and argue about
them. A DQN would score similarly and explain nothing. That is a deliberate
choice, not a limitation to hide; a torch DQN is the obvious extension.

Trained with epsilon-greedy exploration and TD(0) updates.

USAGE
-----
    python analysis/abm_landuse/ca_landuse.py     # first — builds the raster
    python analysis/abm_landuse/rl_landuse.py
    python analysis/abm_landuse/rl_landuse.py --episodes 400

OUTPUT
------
    data/processed/landuse_rl.json   learning curve, learned weights, best plan
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import PROCESSED, STUDY_AREA, bbox_rd  # noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ca_landuse import (  # noqa: E402
    ACTIVE, AMENITY, CLASSES, COLOURS, GREEN, RESID, RETAIL, INDUSTRY, VACANT,
    WATER, ROAD, accessibility, amenity_access, export_grid_png, rasterise,
    shannon_mix,
)

PLACEABLE = [RESID, RETAIL, AMENITY, GREEN]     # what the agent may build
FEATURES = ([f"nb_{c}" for c in CLASSES] +
            ["access", "is_vacant", "is_green", "dist_water", "bias"])


def objective(grid, cell_m):
    mix = shannon_mix(grid)
    green = float((grid == GREEN).sum()) / grid.size
    d = amenity_access(grid, cell_m)
    walk = max(0.0, 1 - (d if d is not None else 400.0) / 400.0)
    return 1.6 * mix + 1.0 * green + 0.8 * walk


def neighbour_counts(grid, radius=4, decay=2.0):
    from scipy.signal import fftconvolve
    r = radius
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    d = np.hypot(yy, xx)
    kern = np.exp(-d / decay)
    kern[r, r] = 0.0
    kern[d > r] = 0.0
    return np.stack([fftconvolve((grid == k).astype("float32"), kern, mode="same")
                     for k in range(len(CLASSES))])


def features(grid, acc, dist_water):
    """Per-cell feature stack, shape (n_features, ny, nx)."""
    nb = neighbour_counts(grid)
    return np.concatenate([
        nb / 8.0,
        acc[None], (grid == VACANT).astype("float32")[None],
        (grid == GREEN).astype("float32")[None],
        dist_water[None],
        np.ones((1, *grid.shape), dtype="float32"),
    ])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cell", type=float, default=25.0)
    ap.add_argument("--episodes", type=int, default=250)
    ap.add_argument("--alpha", type=float, default=0.02, help="learning rate")
    ap.add_argument("--gamma", type=float, default=0.95)
    ap.add_argument("--eps-start", type=float, default=0.9)
    ap.add_argument("--eps-end", type=float, default=0.05)
    ap.add_argument("--candidates", type=int, default=40,
                    help="cells sampled per decision — the full grid is too many")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    from scipy.ndimage import distance_transform_edt

    print(f"RL land-use allocation — {STUDY_AREA.name}")
    grid0, transform, (nx, ny) = rasterise(args.cell)
    n_new = int(0.06 * grid0.size)
    print(f"  grid {nx} x {ny}, programme {n_new} cells "
          f"({n_new * args.cell**2 / 10_000:.1f} ha)")
    print(f"  {args.episodes} episodes, {len(PLACEABLE)} placeable classes, "
          f"{args.candidates} candidates per decision")

    dw = distance_transform_edt(grid0 != WATER).astype("float32")
    dist_water = np.clip(dw / 20.0, 0, 1)
    base_obj = objective(grid0, args.cell)
    print(f"  objective of the current situation: {base_obj:.4f}")

    rng = np.random.default_rng(args.seed)
    W = np.zeros((len(PLACEABLE), len(FEATURES)), dtype="float64")
    curve, best_obj, best_grid = [], -1e9, None

    for ep in range(args.episodes):
        eps = args.eps_end + (args.eps_start - args.eps_end) * \
            math.exp(-3.0 * ep / max(1, args.episodes))
        g = grid0.copy()
        acc = accessibility(g)
        prev_obj = base_obj
        # only undeveloped, non-fixed land may be built on
        free = (g == VACANT)

        for _ in range(n_new):
            idx = np.flatnonzero(free.ravel())
            if idx.size == 0:
                break
            cand = rng.choice(idx, size=int(min(args.candidates, idx.size)),
                              replace=False)
            F = features(g, acc, dist_water)
            Fc = F.reshape(F.shape[0], -1)[:, cand]              # (f, ncand)
            Q = W @ Fc                                            # (nclass, ncand)

            if rng.random() < eps:
                ai = int(rng.integers(len(PLACEABLE)))
                ci = int(rng.integers(cand.size))
            else:
                ai, ci = np.unravel_index(int(np.argmax(Q)), Q.shape)
            cell, klass = int(cand[ci]), PLACEABLE[ai]
            phi = Fc[:, ci].astype("float64")

            r_, c_ = np.unravel_index(cell, g.shape)
            g[r_, c_] = klass
            free[r_, c_] = False

            new_obj = objective(g, args.cell)
            reward = (new_obj - prev_obj) * 100.0     # scale: deltas are tiny
            prev_obj = new_obj

            # TD(0) with the greedy next-state value over a fresh candidate set
            nxt = np.flatnonzero(free.ravel())
            if nxt.size:
                samp = rng.choice(nxt, size=int(min(args.candidates, nxt.size)),
                                  replace=False)
                F2 = features(g, acc, dist_water).reshape(F.shape[0], -1)[:, samp]
                q_next = float((W @ F2).max())
            else:
                q_next = 0.0
            target = reward + args.gamma * q_next
            W[ai] += args.alpha * (target - float(W[ai] @ phi)) * phi
            np.clip(W, -50, 50, out=W)

        final = objective(g, args.cell)
        curve.append(round(final, 4))
        if final > best_obj:
            best_obj, best_grid = final, g.copy()
        if ep % max(1, args.episodes // 10) == 0 or ep == args.episodes - 1:
            print(f"     episode {ep+1:4}/{args.episodes}  eps {eps:.2f}  "
                  f"objective {final:.4f}  best {best_obj:.4f}")

    g = best_grid
    d = amenity_access(g, args.cell)
    score = {"landuse_mix": round(shannon_mix(g), 4),
             "green_share": round(float((g == GREEN).sum()) / g.size, 4),
             "residential_cells": int((g == RESID).sum()),
             "mean_distance_to_amenity_m": d}

    # what did it learn? average weight per neighbour class, per placeable class
    learned = {}
    for ai, k in enumerate(PLACEABLE):
        learned[CLASSES[k]] = {
            CLASSES[m]: round(float(W[ai][m]), 3) for m in range(len(CLASSES))
        } | {"access": round(float(W[ai][len(CLASSES)]), 3)}

    first = float(np.mean(curve[:max(1, len(curve)//10)]))
    last = float(np.mean(curve[-max(1, len(curve)//10):]))
    out = {
        "method": "reinforcement_learning",
        "algorithm": "Q-learning, TD(0), linear function approximation, "
                     "epsilon-greedy",
        "cell_size_m": args.cell,
        "classes": CLASSES,
        "placeable_classes": [CLASSES[k] for k in PLACEABLE],
        "features": FEATURES,
        "parameters": {"episodes": args.episodes, "alpha": args.alpha,
                       "gamma": args.gamma, "eps_start": args.eps_start,
                       "eps_end": args.eps_end,
                       "candidates_per_decision": args.candidates,
                       "programme_cells": n_new},
        "objective": "1.6*landuse_mix + 1.0*green_share + "
                     "0.8*max(0, 1 - mean_home_to_amenity_m/400)",
        "baseline_objective": round(base_obj, 4),
        "learning_curve": curve,
        "objective_first_decile_mean": round(first, 4),
        "objective_last_decile_mean": round(last, 4),
        "improvement_over_training": round(last - first, 4),
        "best_objective": round(best_obj, 4),
        "score": score,
        "learned_weights": learned,
        "caveat": "Linear Q-learning was chosen over a deep network so the "
                  "learned weights can be read and argued with. A DQN would "
                  "likely score similarly and explain nothing.",
        "grid": {"nx": nx, "ny": ny},
        "colours": COLOURS,
        "png": "landuse_rl_best.png",
        "bbox_wgs84": export_grid_png(g, transform, "EPSG:28992",
                                      PROCESSED / "landuse_rl_best.png"),
        "best_grid": g.tolist(),
    }
    (PROCESSED / "landuse_rl.json").write_text(json.dumps(out) + "\n")

    print(f"\n  learning: {first:.4f} (first 10% of episodes) -> "
          f"{last:.4f} (last 10%)   {'LEARNED' if last > first else 'NO IMPROVEMENT'}")
    print(f"  best objective {best_obj:.4f} vs {base_obj:.4f} for the current situation")
    print(f"  best plan -> mix {score['landuse_mix']:.3f}, "
          f"green {100*score['green_share']:.1f}%, amenity {d} m")
    print("\n  what the agent learned (weight on each neighbour class):")
    for k, w in learned.items():
        top = sorted(((v, m) for m, v in w.items()), reverse=True)[:3]
        bot = sorted(((v, m) for m, v in w.items()))[:2]
        print(f"     {k:12} likes {', '.join(f'{m} {v:+.1f}' for v, m in top)}"
              f"  | avoids {', '.join(f'{m} {v:+.1f}' for v, m in bot)}")
    print("\n  wrote data/processed/landuse_rl.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
