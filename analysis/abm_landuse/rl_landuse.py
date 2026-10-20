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
Episodic MDP over the DESIGN SITE only (DESIGN_SITE in common/project.py).
Every non-fixed cell inside the site is cleared, and each episode the agent
re-plans the whole site, one cell at a time. The rest of the study area stays
as it is: it is context, not something the agent may change or is scored on.

    state   the grid so far
    action  (cell, class) — develop this cell as that use
    reward  the change in the planning objective caused by that placement
            (times 100); there is no separate terminal bonus

    objective = 1.6 * land-use mix (Shannon)        over the site's cells
              + 1.0 * green share                  over the site's cells
              + 0.8 * walkability (1 - mean home-to-amenity distance / 400 m)
                      for homes inside the site; amenities outside count too

    the same formula the CA is scored on, but over the site, not both buurten,
    so the two values are NOT directly comparable.

Q(s, a) is linear in features of the candidate cell: how many neighbours of each
class it has, how reachable it is, whether it is currently vacant, and how close
it is to water. Linear rather than a deep network on purpose — the whole value
of the RL run here is that you can READ the learned weights and argue about
them. A DQN would score similarly and explain nothing. That is a deliberate
choice, not a limitation to hide. rl_dqn.py is the deep version, on the
same problem, and it does not score better.

Two of the 13 features are constant for every candidate: candidates are
always empty site cells, so is_vacant is 1 and is_green is 0. They act as
extra bias terms.

Trained with epsilon-greedy exploration and TD(0) updates.

USAGE
-----
    python analysis/abm_landuse/ca_landuse.py     # first — builds the raster
    python analysis/abm_landuse/rl_landuse.py
    python analysis/abm_landuse/rl_landuse.py --episodes 400
    python analysis/abm_landuse/rl_landuse.py --episodes 120 --keep-housing

--keep-housing adds one constraint: the plan must contain exactly as many
residential cells as the site has today. Actions that would break it are masked
(no more homes once the quota is met; only homes once the remaining cells are
all needed to reach it). The objective is unchanged, so the two runs differ
only in that rule. It writes landuse_rl_keep_housing.json instead.

OUTPUT
------
    data/processed/landuse_rl.json                learning curve, learned weights, best plan
    data/processed/landuse_rl_keep_housing.json   the same with --keep-housing
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import PROCESSED, STUDY_AREA, design_site_polygon  # noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ca_landuse import (  # noqa: E402
    AMENITY, CLASSES, COLOURS, FIXED, GREEN, RESID, RETAIL, VACANT, WATER,
    accessibility, export_grid_png, rasterise, shannon_mix,
)

PLACEABLE = [RESID, RETAIL, AMENITY, GREEN]     # what the agent may build
#13 numbers per candidate cell: 8 neighbour counts, access, two flags, water distance, constant
FEATURES = ([f"nb_{c}" for c in CLASSES] +
            ["access", "is_vacant", "is_green", "dist_water", "bias"])


def site_terms(grid, cell_m, site):
    """Mix, green share and mean home-to-amenity distance over the `site` cells.

    Distances are measured over the whole grid, so a shop across the site edge
    still serves a home inside it. Distance is None when the site has no homes.
    """
    from scipy.ndimage import distance_transform_edt
    cells = grid[site]
    target = np.isin(grid, [AMENITY, RETAIL])  #what a home needs to be near
    homes = site & (grid == RESID)  #only homes inside the site are scored
    d = None
    if target.any() and homes.any():
        d = float((distance_transform_edt(~target) * cell_m)[homes].mean())  #mean straight-line distance home -> nearest shop or amenity, m
    return shannon_mix(cells), float((cells == GREEN).sum()) / cells.size, d


def objective(grid, cell_m, site):
    mix, green, d = site_terms(grid, cell_m, site)
    walk = max(0.0, 1 - (d if d is not None else 400.0) / 400.0)  #1 at the door, 0 at 400 m or with no homes
    return 1.6 * mix + 1.0 * green + 0.8 * walk  #the same weights the CA is scored with


def site_score(grid, cell_m, site):
    mix, green, d = site_terms(grid, cell_m, site)
    return {"landuse_mix": round(mix, 4),
            "green_share": round(green, 4),
            "residential_cells": int((grid[site] == RESID).sum()),
            "mean_distance_to_amenity_m": None if d is None else round(d, 1)}


def neighbour_counts(grid, radius=4, decay=2.0):
    from scipy.signal import fftconvolve
    r = radius
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    d = np.hypot(yy, xx)
    kern = np.exp(-d / decay)  #nearer neighbours count more
    kern[r, r] = 0.0  #a cell is not its own neighbour
    kern[d > r] = 0.0  #round window of radius 4 cells
    return np.stack([fftconvolve((grid == k).astype("float32"), kern, mode="same")
                     for k in range(len(CLASSES))])


def features(grid, acc, dist_water):
    """Per-cell feature stack, shape (n_features, ny, nx)."""
    nb = neighbour_counts(grid)
    return np.concatenate([
        nb / 8.0,  #neighbour counts, scaled to roughly 0..1
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
    ap.add_argument("--keep-housing", action="store_true",
                    help="plan exactly as many residential cells as the site has today")
    args = ap.parse_args()
    tag = "_keep_housing" if args.keep_housing else ""

    from scipy.ndimage import distance_transform_edt

    print(f"RL land-use allocation — {STUDY_AREA.name}")
    from rasterio.features import rasterize as burn
    grid_now, transform, (nx, ny), road_frac = rasterise(args.cell)
    site = burn([(design_site_polygon(), 1)], out_shape=grid_now.shape,
                transform=transform).astype(bool)
    # the whole site is redeveloped: every cell that is not road or water is
    # cleared, and the agent decides what each one becomes
    grid0 = grid_now.copy()
    grid0[site & ~np.isin(grid_now, list(FIXED))] = VACANT
    n_new = int((site & (grid0 == VACANT)).sum())  #cells the agent places per episode
    print(f"  grid {nx} x {ny}; design site {int(site.sum())} cells, "
          f"{n_new} to re-plan ({n_new * args.cell**2 / 10_000:.1f} ha)")
    print(f"  {args.episodes} episodes, {len(PLACEABLE)} placeable classes, "
          f"{args.candidates} candidates per decision")

    dw = distance_transform_edt(grid0 != WATER).astype("float32")
    dist_water = np.clip(dw / 20.0, 0, 1)  #distance to water in cells, capped at 20 and scaled to 0..1
    base_obj = objective(grid_now, args.cell, site)
    base_score = site_score(grid_now, args.cell, site)
    cleared_obj = objective(grid0, args.cell, site)
    print(f"  objective of the site today: {base_obj:.4f}")
    quota = base_score["residential_cells"] if args.keep_housing else None
    if quota is not None:
        print(f"  housing rule: exactly {quota} residential cells, as today")

    def allowed(n_resid: int, n_free: int) -> np.ndarray:
        """Mask over PLACEABLE: which classes keep the housing rule satisfiable."""
        ok = np.ones(len(PLACEABLE), dtype=bool)
        if quota is not None:
            need = quota - n_resid
            if need <= 0:
                ok[PLACEABLE.index(RESID)] = False          # quota met: no more homes
            elif need >= n_free:
                ok[:] = False                               # every cell left must be a home
                ok[PLACEABLE.index(RESID)] = True
        return ok

    rng = np.random.default_rng(args.seed)
    W = np.zeros((len(PLACEABLE), len(FEATURES)), dtype="float64")  #the whole model: one weight per use and feature
    curve, best_obj, best_grid = [], -1e9, None

    for ep in range(args.episodes):
        #exploration rate, decaying from eps_start towards eps_end
        eps = args.eps_end + (args.eps_start - args.eps_end) * \
            math.exp(-3.0 * ep / max(1, args.episodes))
        g = grid0.copy()
        acc = accessibility(g, road_frac)  #roads do not change, so access is computed once per episode
        prev_obj = cleared_obj
        # only the cleared cells inside the design site may be built on
        free = site & (g == VACANT)
        n_resid = 0

        #one placement per step until the site is full
        for _ in range(n_new):
            idx = np.flatnonzero(free.ravel())
            if idx.size == 0:
                break
            cand = rng.choice(idx, size=int(min(args.candidates, idx.size)),
                              replace=False)
            F = features(g, acc, dist_water)
            Fc = F.reshape(F.shape[0], -1)[:, cand]              # (f, ncand)
            #linear Q for every (use, candidate) pair
            Q = W @ Fc                                            # (nclass, ncand)
            ok = allowed(n_resid, idx.size)
            Q[~ok] = -np.inf  #uses that would break the housing rule are never picked

            if rng.random() < eps:
                # unconstrained runs draw exactly as before, so they reproduce
                ai = (int(rng.integers(len(PLACEABLE))) if quota is None
                      else int(rng.choice(np.flatnonzero(ok))))
                ci = int(rng.integers(cand.size))
            else:
                ai, ci = np.unravel_index(int(np.argmax(Q)), Q.shape)
            cell, klass = int(cand[ci]), PLACEABLE[ai]
            phi = Fc[:, ci].astype("float64")  #features of the chosen cell, for the update

            r_, c_ = np.unravel_index(cell, g.shape)
            g[r_, c_] = klass
            free[r_, c_] = False
            n_resid += klass == RESID

            new_obj = objective(g, args.cell, site)
            reward = (new_obj - prev_obj) * 100.0     # scale: deltas are tiny
            prev_obj = new_obj

            # TD(0) with the greedy next-state value over a fresh candidate set
            nxt = np.flatnonzero(free.ravel())
            if nxt.size:
                samp = rng.choice(nxt, size=int(min(args.candidates, nxt.size)),
                                  replace=False)
                F2 = features(g, acc, dist_water).reshape(F.shape[0], -1)[:, samp]
                q_next = float((W @ F2)[allowed(n_resid, nxt.size)].max())
            else:
                q_next = 0.0
            target = reward + args.gamma * q_next  #TD(0) target: reward now plus discounted best Q next
            W[ai] += args.alpha * (target - float(W[ai] @ phi)) * phi  #gradient step on the chosen use's weights only
            np.clip(W, -50, 50, out=W)  #keep weights bounded so a bad step cannot run away

        final = objective(g, args.cell, site)
        curve.append(round(final, 4))  #objective at the end of each episode = the learning curve
        if final > best_obj:
            best_obj, best_grid = final, g.copy()
        if ep % max(1, args.episodes // 10) == 0 or ep == args.episodes - 1:
            print(f"     episode {ep+1:4}/{args.episodes}  eps {eps:.2f}  "
                  f"objective {final:.4f}  best {best_obj:.4f}")

    g = best_grid  #report the best episode's plan, which may include lucky exploration
    score = site_score(g, args.cell, site)
    d = score["mean_distance_to_amenity_m"]

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
                       "programme_cells": n_new,
                       "housing_rule": (f"exactly {quota} residential cells (as today)"
                                        if quota is not None else "none")},
        "scope": "design_site",
        "scope_note": "The agent re-plans every non-road, non-water cell of "
                      "the design site; the rest of the study area is fixed "
                      "context. All scores are over the site's cells only, so "
                      "they are not comparable with the CA's study-area scores.",
        "site_cells": int(site.sum()),
        "objective": "over the design site: 1.6*landuse_mix + 1.0*green_share + "
                     "0.8*max(0, 1 - mean_home_to_amenity_m/400)",
        "baseline_objective": round(base_obj, 4),
        "baseline_score": base_score,
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
        "png": f"landuse_rl{tag}_best.png",
        "bbox_wgs84": export_grid_png(g, transform, "EPSG:28992",
                                      PROCESSED / f"landuse_rl{tag}_best.png"),
        "best_grid": g.tolist(),
        "today_grid": grid_now.tolist(),
        "site_mask": site.astype(int).tolist(),
    }
    if quota is not None:
        assert score["residential_cells"] == quota, score   # the rule held
    (PROCESSED / f"landuse_rl{tag}.json").write_text(json.dumps(out) + "\n")

    print(f"\n  learning: {first:.4f} (first 10% of episodes) -> "
          f"{last:.4f} (last 10%)   {'LEARNED' if last > first else 'NO IMPROVEMENT'}")
    print(f"  best objective {best_obj:.4f} vs {base_obj:.4f} for the site today")
    print(f"  best plan -> mix {score['landuse_mix']:.3f}, "
          f"green {100*score['green_share']:.1f}%, amenity {d} m, "
          f"{score['residential_cells']} residential cells "
          f"(today {base_score['residential_cells']})")
    print("\n  what the agent learned (weight on each neighbour class):")
    for k, w in learned.items():
        top = sorted(((v, m) for m, v in w.items()), reverse=True)[:3]
        bot = sorted(((v, m) for m, v in w.items()))[:2]
        print(f"     {k:12} likes {', '.join(f'{m} {v:+.1f}' for v, m in top)}"
              f"  | avoids {', '.join(f'{m} {v:+.1f}' for v, m in bot)}")
    print(f"\n  wrote data/processed/landuse_rl{tag}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
