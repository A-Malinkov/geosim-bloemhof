#!/usr/bin/env python3
"""
rl_landuse.py - a reinforcement-learning agent for land use on the design site.

Component 4.7, the RL half. Owner: Atanas Malinkov

The CA follows rules we set. This agent only gets the objective and has to find
where things go, and its weights can be read and set against the CA's rules.

The site is cleared and re-planned one cell at a time each episode. The rest of
Bloemhof is context and is not scored.
    state   the grid so far
    action  a cell and a use
    reward  100 x the change in the objective
    objective = 1.6 mix + 1.0 green share + 0.8 walkability (1 - d / 400 m)
              + 1.1 min(1, housing cells / housing cells today), over the site
Q is linear in 13 features of a cell (neighbours of each use, access, water).
Linear on purpose, so the weights can be read. Two features are constant for
every candidate and act as bias terms. Epsilon-greedy with TD(0) updates.
Two baselines run beside it, a random policy and hill climbing on the objective
itself. Hill climbing beats the agent in seconds.

    python analysis/abm_landuse/ca_landuse.py     #first, builds the grid
    python analysis/abm_landuse/rl_landuse.py

Writes data/processed/landuse_rl.json.
"""

import json
import math
import pathlib
import sys
import time

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import PROCESSED, STUDY_AREA, design_site_polygon  #noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from weight_sensitivity import DEFAULT_W, components  #noqa: E402  #the objective, defined once
from ca_landuse import (  #noqa: E402
    AMENITY, CLASSES, COLOURS, FIXED, GREEN, RESID, RETAIL, VACANT, WATER,
    accessibility, export_grid_png, rasterise, shannon_mix,
)

PLACEABLE = [RESID, RETAIL, AMENITY, GREEN]     #what the agent may build
#13 numbers per candidate cell: 8 neighbour counts, access, two flags, water distance, constant
FEATURES = ([f"nb_{c}" for c in CLASSES] +
            ["access", "is_vacant", "is_green", "dist_water", "bias"])


def site_terms(grid, cell_m, site):
    #Mix, green share and mean home-to-amenity distance over the `site` cells.
    #
    #Distances are measured over the whole grid, so a shop across the site edge
    #still serves a home inside it. Distance is None when the site has no homes.
    from scipy.ndimage import distance_transform_edt
    cells = grid[site]
    target = np.isin(grid, [AMENITY, RETAIL])  #what a home needs to be near
    homes = site & (grid == RESID)  #only homes inside the site are scored
    d = None
    if target.any() and homes.any():
        d = float((distance_transform_edt(~target) * cell_m)[homes].mean())  #mean straight-line distance home -> nearest shop or amenity, m
    return shannon_mix(cells), float((cells == GREEN).sum()) / cells.size, d


def objective(grid, cell_m, site, homes_today, homes=None):
    #the planning objective over the site; homes default to the site's housing cells, score_scenarios.py passes dwellings
    mix, green, d = site_terms(grid, cell_m, site)
    if homes is None:
        homes = int((grid[site] == RESID).sum())
    terms = {"landuse_mix": mix, "green_share": green, "mean_distance_to_amenity_m": d}
    return float(np.dot(DEFAULT_W, components(terms, homes, homes_today)))  #the same function the CA is scored with


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
    #Per-cell feature stack, shape (n_features, ny, nx).
    nb = neighbour_counts(grid)
    return np.concatenate([
        nb / 8.0,  #neighbour counts, scaled to roughly 0..1
        acc[None], (grid == VACANT).astype("float32")[None],
        (grid == GREEN).astype("float32")[None],
        dist_water[None],
        np.ones((1, *grid.shape), dtype="float32"),
    ])


PARAMS = {
    "cell": 25.0,  #grid cell, m
    "episodes": 400,  #400 since 2026-10-30, the curve still rose at 120 and levels off after about 250
    "alpha": 0.02,  #learning rate
    "gamma": 0.95,
    "eps_start": 0.9,
    "eps_end": 0.05,
    "candidates": 40,  #cells sampled per decision, the full grid is too many
    "seed": 0,
    "random_episodes": 30,  #episodes of a purely random policy, the baseline to beat
    "hill_climb": 56400,  #evaluations for the hill-climbing baseline, 0 is off
}


def main():
    p = PARAMS
    tag = ""  #one run since the housing rule went into the objective

    from scipy.ndimage import distance_transform_edt

    print(f"RL land-use allocation: {STUDY_AREA.name}")
    from rasterio.features import rasterize as burn
    grid_now, transform, (nx, ny), road_frac = rasterise(p["cell"])
    site = burn([(design_site_polygon(), 1)], out_shape=grid_now.shape,
                transform=transform).astype(bool)
    #the whole site is redeveloped: every cell that is not road or water is
    #cleared, and the agent decides what each one becomes
    grid0 = grid_now.copy()
    grid0[site & ~np.isin(grid_now, list(FIXED))] = VACANT
    n_new = int((site & (grid0 == VACANT)).sum())  #cells the agent places per episode
    print(f"  grid {nx} x {ny}; design site {int(site.sum())} cells, "
          f"{n_new} to re-plan ({n_new * p['cell']**2 / 10_000:.1f} ha)")
    print(f"  {p['episodes']} episodes, {len(PLACEABLE)} placeable classes, "
          f"{p['candidates']} candidates per decision")

    dw = distance_transform_edt(grid0 != WATER).astype("float32")
    dist_water = np.clip(dw / 20.0, 0, 1)  #distance to water in cells, capped at 20 and scaled to 0..1
    homes_today = int((grid_now[site] == RESID).sum())  #housing cells on the site today, the housing term's reference
    base_obj = objective(grid_now, p["cell"], site, homes_today)
    base_score = site_score(grid_now, p["cell"], site)
    cleared_obj = objective(grid0, p["cell"], site, homes_today)
    print(f"  objective of the site today: {base_obj:.4f} ({homes_today} housing cells)")

    rng = np.random.default_rng(p["seed"])
    W = np.zeros((len(PLACEABLE), len(FEATURES)), dtype="float64")  #the whole model: one weight per use and feature
    curve, best_obj, best_grid = [], -1e9, None

    def run_episode(eps, learn=True):
        #one episode: fill the site cell by cell; learn=False only plays, for the learned policy without exploration
        g = grid0.copy()
        acc = accessibility(g, road_frac)  #roads do not change, so access is computed once per episode
        prev_obj = cleared_obj
        #only the cleared cells inside the design site may be built on
        free = site & (g == VACANT)

        #one placement per step until the site is full
        for _ in range(n_new):
            idx = np.flatnonzero(free.ravel())
            if idx.size == 0:
                break
            cand = rng.choice(idx, size=int(min(p["candidates"], idx.size)),
                              replace=False)
            F = features(g, acc, dist_water)
            Fc = F.reshape(F.shape[0], -1)[:, cand]              #(f, ncand)
            #linear Q for every (use, candidate) pair
            Q = W @ Fc                                            #(nclass, ncand)

            if rng.random() < eps:
                ai = int(rng.integers(len(PLACEABLE)))  #explore: a random use on a random candidate
                ci = int(rng.integers(cand.size))
            else:
                ai, ci = np.unravel_index(int(np.argmax(Q)), Q.shape)
            cell, klass = int(cand[ci]), PLACEABLE[ai]
            phi = Fc[:, ci].astype("float64")  #features of the chosen cell, for the update

            r_, c_ = np.unravel_index(cell, g.shape)
            g[r_, c_] = klass
            free[r_, c_] = False

            new_obj = objective(g, p["cell"], site, homes_today)
            reward = (new_obj - prev_obj) * 100.0     #scale: deltas are tiny
            prev_obj = new_obj

            if not learn:
                continue  #playing only: no update
            #TD(0) with the greedy next-state value over a fresh candidate set
            nxt = np.flatnonzero(free.ravel())
            if nxt.size:
                samp = rng.choice(nxt, size=int(min(p["candidates"], nxt.size)),
                                  replace=False)
                F2 = features(g, acc, dist_water).reshape(F.shape[0], -1)[:, samp]
                q_next = float((W @ F2).max())
            else:
                q_next = 0.0
            target = reward + p["gamma"] * q_next  #TD(0) target: reward now plus discounted best Q next
            W[ai] += p["alpha"] * (target - float(W[ai] @ phi)) * phi  #gradient step on the chosen use's weights only
            np.clip(W, -50, 50, out=W)  #keep weights bounded so a bad step cannot run away

        return objective(g, p["cell"], site, homes_today), g

    for ep in range(p["episodes"]):
        #exploration rate, decaying from eps_start towards eps_end
        eps = p["eps_end"] + (p["eps_start"] - p["eps_end"]) * \
            math.exp(-3.0 * ep / max(1, p["episodes"]))
        final, g = run_episode(eps)
        curve.append(round(final, 4))  #objective at the end of each episode = the learning curve
        if final > best_obj:
            best_obj, best_grid = final, g.copy()
        if ep % max(1, p["episodes"] // 10) == 0 or ep == p["episodes"] - 1:
            print(f"     episode {ep+1:4}/{p['episodes']}  eps {eps:.2f}  "
                  f"objective {final:.4f}  best {best_obj:.4f}")

    greedy_obj, greedy_grid = run_episode(0.0, learn=False)  #the learned policy itself: no exploration, no update

    #baseline 1: a random use on a random empty cell at every step, its own generator so training is untouched
    def random_episode(rr):
        g = grid0.copy()
        free = site & (g == VACANT)
        for _ in range(n_new):
            rr.random()  #the draw an epsilon-greedy step makes, kept so the published baseline reproduces
            ai = int(rr.choice(np.arange(len(PLACEABLE))))
            r_, c_ = np.unravel_index(int(rr.choice(np.flatnonzero(free.ravel()))), g.shape)
            g[r_, c_] = PLACEABLE[ai]
            free[r_, c_] = False
        return objective(g, p["cell"], site, homes_today)

    rr = np.random.default_rng(p["seed"])
    rand = [random_episode(rr) for _ in range(p["random_episodes"])]
    print(f"  random policy over {len(rand)} episodes: mean {np.mean(rand):.4f}, best {np.max(rand):.4f}")

    #baseline 2: hill climbing on the objective itself, from a random plan, one cell changed at a time
    def hill_climb(budget):
        hr = np.random.default_rng(p["seed"] + 1)
        cells = [tuple(c) for c in np.argwhere(site & (grid0 == VACANT))]
        g = grid0.copy()
        for (r_, c_), u in zip(cells, hr.choice(len(PLACEABLE), size=len(cells))):  #a random start
            g[r_, c_] = PLACEABLE[u]
        cur = objective(g, p["cell"], site, homes_today)
        best, best_g, evals, accepted = cur, g.copy(), 1, 0
        while evals < budget:
            r_, c_ = cells[int(hr.integers(len(cells)))]
            old = g[r_, c_]
            g[r_, c_] = hr.choice([u for u in PLACEABLE if u != old])  #one cell to another use
            new = objective(g, p["cell"], site, homes_today); evals += 1
            if new >= cur:  #accept equal moves too, so it can walk along plateaus
                cur, accepted = new, accepted + 1
            else:
                g[r_, c_] = old
            if cur > best:
                best, best_g = cur, g.copy()
        return best, best_g, evals, accepted

    hc = None
    if p["hill_climb"]:
        th = time.time()
        hb, hg, he, ha = hill_climb(p["hill_climb"])
        hc = {"evaluations": he, "accepted_moves": ha, "best_objective": round(hb, 4),
              "score": site_score(hg, p["cell"], site), "seconds": round(time.time() - th, 1),
              "grid": hg.tolist()}  #the plan itself, for the figure next to the RL agent's
        print(f"  hill climbing, {he} evaluations: best {hb:.4f} ({time.time() - th:.0f} s)")
    greedy_score = site_score(greedy_grid, p["cell"], site)
    g = best_grid  #report the best episode's plan, which may include lucky exploration
    score = site_score(g, p["cell"], site)
    d = score["mean_distance_to_amenity_m"]

    #what did it learn? average weight per neighbour class, per placeable class
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
        "cell_size_m": p["cell"],
        "classes": CLASSES,
        "placeable_classes": [CLASSES[k] for k in PLACEABLE],
        "features": FEATURES,
        "parameters": {"episodes": p["episodes"], "alpha": p["alpha"],
                       "gamma": p["gamma"], "eps_start": p["eps_start"],
                       "eps_end": p["eps_end"],
                       "candidates_per_decision": p["candidates"],
                       "programme_cells": n_new},
        "homes_today_cells": homes_today,  #the housing term's reference
        "scope": "design_site",
        "scope_note": "The agent re-plans every non-road, non-water cell of "
                      "the design site; the rest of the study area is fixed "
                      "context. All scores are over the site's cells only, so "
                      "they are not comparable with the CA's study-area scores.",
        "site_cells": int(site.sum()),
        "objective": "over the design site: 1.6*landuse_mix + 1.0*green_share + "
                     "0.8*max(0, 1 - mean_home_to_amenity_m/400) + "
                     "1.1*min(1, housing cells / housing cells today)",
        "baseline_objective": round(base_obj, 4),
        "baseline_score": base_score,
        "learning_curve": curve,
        "objective_first_decile_mean": round(first, 4),
        "objective_last_decile_mean": round(last, 4),
        "improvement_over_training": round(last - first, 4),
        "best_objective": round(best_obj, 4),
        "score": score,
        "greedy_objective": round(greedy_obj, 4),  #one run of the learned policy, no exploration
        "greedy_score": greedy_score,
        "random_policy": {"episodes": len(rand), "mean": round(float(np.mean(rand)), 4),
                          "sd": round(float(np.std(rand)), 4), "best": round(float(np.max(rand)), 4)},  #the baseline to beat
        "hill_climb": hc,  #direct optimisation of the same objective, the baseline any learner should beat
        "learned_weights": learned,
        "caveat": "Linear Q-learning was chosen so the learned weights can be "
                  "read and argued with. Hill climbing on the objective itself "
                  "scores higher in seconds: the objective is cheap to compute.",
        "grid": {"nx": nx, "ny": ny},
        "colours": COLOURS,
        "png": f"landuse_rl{tag}_best.png",
        "bbox_wgs84": export_grid_png(g, transform, "EPSG:28992",
                                      PROCESSED / f"landuse_rl{tag}_best.png"),
        "best_grid": g.tolist(),
        "today_grid": grid_now.tolist(),
        "site_mask": site.astype(int).tolist(),
    }
    (PROCESSED / f"landuse_rl{tag}.json").write_text(json.dumps(out) + "\n")

    print(f"\n  learning: {first:.4f} (first 10% of episodes) -> "
          f"{last:.4f} (last 10%)   {'LEARNED' if last > first else 'NO IMPROVEMENT'}")
    print(f"  best objective {best_obj:.4f} vs {base_obj:.4f} for the site today; "
          f"learned policy {greedy_obj:.4f} ({greedy_score['residential_cells']} housing cells)")
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
