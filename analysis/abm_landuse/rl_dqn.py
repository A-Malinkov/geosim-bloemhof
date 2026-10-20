#!/usr/bin/env python3
"""
rl_dqn.py — a convolutional deep Q-network for the same land-use problem.

Component 4.7, a second RL version. Owner: Atanas Malinkov

rl_landuse.py stays as it is; this is the comparison. Everything that defines
the PROBLEM is shared with it — grid, design site, objective, reward, discount,
the --keep-housing rule and the output schema — so the two runs differ only in
the agent:

    rl_landuse.py   linear Q-learning on 13 hand-made features of a cell
                    (neighbour counts, access, ...); 40 sampled cells per step.
    rl_dqn.py       a CNN reads the grid itself and outputs Q for EVERY cell x
                    use in one pass; the agent picks from all empty cells.

THE NETWORK
-----------
Fully convolutional over a crop of the grid around the site (the site plus 6
cells). Input channels: one-hot land use (8), site mask, empty-cell mask,
road accessibility, distance to water, and broadcast "global" channels — the
current share of each placeable use on the site, the fraction of the site
placed, and the housing quota still to place — because the objective is a
site-wide sum, not a local one. Four 3x3 convolutions, two of them dilated
(2 and 4), give each cell a view about 15 cells across; a 1x1 convolution
outputs one Q-value per placeable use.

TRAINING
--------
DQN with experience replay, a target network synced every 500 steps, Double
DQN targets, Huber loss and Adam. Epsilon falls linearly from 1.0 to 0.05 over
the first 70 % of episodes. Actions that would break the housing rule are
masked out of both the choice and the bootstrap target.

Two numbers come out, and they are different things:
    best_objective     the best episode seen during training (what
                       rl_landuse.py reports — it can include lucky
                       exploration)
    greedy_objective   one run of the learned policy with no exploration at
                       the end — what the network actually learned

USAGE
-----
    python analysis/abm_landuse/rl_dqn.py --episodes 120
    python analysis/abm_landuse/rl_dqn.py --episodes 120 --keep-housing

Needs PyTorch (CPU is enough; not in requirements.txt, see the note there):
    pip install --index-url https://download.pytorch.org/whl/cpu torch

OUTPUT
------
    data/processed/landuse_rl_dqn.json                (and _keep_housing)
    data/processed/landuse_rl_dqn_best.png            (and _keep_housing)
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
import time
from collections import deque

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import PROCESSED, STUDY_AREA, design_site_polygon  # noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ca_landuse import (  # noqa: E402
    CLASSES, COLOURS, FIXED, RESID, VACANT, WATER,
    accessibility, export_grid_png, rasterise,
)
from rl_landuse import PLACEABLE, objective, site_score  # noqa: E402

MARGIN = 6                      # cells of context around the site in the crop
N_GLOBAL = len(PLACEABLE) + 2   # site shares, progress, quota left


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cell", type=float, default=25.0)
    ap.add_argument("--episodes", type=int, default=120)
    ap.add_argument("--gamma", type=float, default=0.95)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--buffer", type=int, default=20_000)
    ap.add_argument("--warmup", type=int, default=500, help="transitions before learning")
    ap.add_argument("--target-sync", type=int, default=500, help="steps between target syncs")
    ap.add_argument("--width", type=int, default=48, help="conv channels")
    ap.add_argument("--train-every", type=int, default=4, help="env steps per gradient step")
    ap.add_argument("--random-episodes", type=int, default=30,
                    help="episodes of a purely random policy, as the baseline to beat")
    ap.add_argument("--threads", type=int, default=0, help="torch threads (0 = default)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--keep-housing", action="store_true",
                    help="plan exactly as many residential cells as the site has today")
    args = ap.parse_args()

    try:
        import torch
        import torch.nn as nn
    except ImportError:
        print("PyTorch is needed: pip install --index-url "
              "https://download.pytorch.org/whl/cpu torch")
        return 1
    from rasterio.features import rasterize as burn
    from scipy.ndimage import distance_transform_edt

    tag = "_keep_housing" if args.keep_housing else ""
    torch.manual_seed(args.seed)
    if args.threads:
        torch.set_num_threads(args.threads)
    rng = np.random.default_rng(args.seed)
    t0 = time.time()

    print(f"Deep Q-network land-use allocation — {STUDY_AREA.name}")
    grid_now, transform, (nx, ny), road_frac = rasterise(args.cell)
    site = burn([(design_site_polygon(), 1)], out_shape=grid_now.shape,
                transform=transform).astype(bool)
    grid0 = grid_now.copy()
    grid0[site & ~np.isin(grid_now, list(FIXED))] = VACANT  #clear the site except roads and water, as in rl_landuse.py
    n_new = int((site & (grid0 == VACANT)).sum())

    rows, cols = np.where(site)
    r0, r1 = max(0, rows.min() - MARGIN), min(site.shape[0], rows.max() + MARGIN + 1)
    c0, c1 = max(0, cols.min() - MARGIN), min(site.shape[1], cols.max() + MARGIN + 1)
    crop = (slice(r0, r1), slice(c0, c1))  #the network only sees the site plus MARGIN cells around it
    H, W = r1 - r0, c1 - c0
    print(f"  grid {nx} x {ny}; design site {int(site.sum())} cells, {n_new} to re-plan; "
          f"network sees a {W} x {H} crop")

    acc = accessibility(grid0, road_frac).astype("float32")
    dw = distance_transform_edt(grid0 != WATER).astype("float32")
    dist_water = np.clip(dw / 20.0, 0, 1)
    base_obj = objective(grid_now, args.cell, site)
    base_score = site_score(grid_now, args.cell, site)
    cleared_obj = objective(grid0, args.cell, site)
    quota = base_score["residential_cells"] if args.keep_housing else None
    print(f"  objective of the site today: {base_obj:.4f}")
    if quota is not None:
        print(f"  housing rule: exactly {quota} residential cells, as today")

    RES_I = PLACEABLE.index(RESID)
    site_c = torch.tensor(site[crop], dtype=torch.float32)
    static = torch.stack([site_c, torch.tensor(acc[crop]), torch.tensor(dist_water[crop])])  #inputs that never change during an episode
    placeable_t = torch.tensor(PLACEABLE)

    def allowed(n_resid: int, n_free: int) -> np.ndarray:
        """Mask over PLACEABLE: which uses keep the housing rule satisfiable."""
        ok = np.ones(len(PLACEABLE), dtype=bool)
        if quota is not None:
            need = quota - n_resid
            if need <= 0:
                ok[RES_I] = False
            elif need >= n_free:
                ok[:] = False
                ok[RES_I] = True
        return ok

    def glob(counts: np.ndarray, n_free: int, n_resid: int) -> np.ndarray:
        """Site-wide context: shares of each placeable use, progress, quota left."""
        placed = n_new - n_free
        shares = counts / max(1, n_new)
        q_left = 0.0 if quota is None else max(0, quota - n_resid) / max(1, n_new)
        return np.concatenate([shares, [placed / n_new, q_left]]).astype("float32")

    #stack every input channel: one-hot land use, empty mask, static layers, site-wide numbers
    def inputs(gc: torch.Tensor, fc: torch.Tensor, gl: torch.Tensor) -> torch.Tensor:
        """Batch of network inputs from cropped grids (B,H,W), free masks, globals."""
        B = gc.shape[0]
        onehot = torch.nn.functional.one_hot(gc.long(), len(CLASSES)).permute(0, 3, 1, 2).float()
        return torch.cat([onehot, fc[:, None].float(),
                          static[None].expand(B, -1, -1, -1),
                          gl[:, :, None, None].expand(-1, -1, H, W)], dim=1)

    c_in = len(CLASSES) + 1 + 3 + N_GLOBAL  #8 one-hot + empty mask + 3 static + 6 site-wide = 18 channels
    w = args.width

    #fully convolutional: the same small network looks at every cell, dilations widen its view
    def make_net():
        return nn.Sequential(
            nn.Conv2d(c_in, w, 3, padding=1), nn.ReLU(),
            nn.Conv2d(w, w, 3, padding=2, dilation=2), nn.ReLU(),
            nn.Conv2d(w, w, 3, padding=4, dilation=4), nn.ReLU(),
            nn.Conv2d(w, w, 3, padding=1), nn.ReLU(),
            nn.Conv2d(w, len(PLACEABLE), 1))

    net, tgt = make_net(), make_net()
    tgt.load_state_dict(net.state_dict())
    opt = torch.optim.Adam(net.parameters(), lr=args.lr)
    n_params = sum(p.numel() for p in net.parameters())
    print(f"  CNN: {n_params:,} parameters, {c_in} input channels; "
          f"{args.episodes} episodes, replay {args.buffer}, batch {args.batch}")

    # replay: compact states (cropped grid + free mask + globals), rebuilt on sampling
    buf = deque(maxlen=args.buffer)  #replay memory, oldest transitions fall out first

    def masked_q(q: torch.Tensor, free: torch.Tensor, ok: torch.Tensor) -> torch.Tensor:
        """q (B,4,H,W) -> flat (B, 4*H*W) with invalid actions at -inf."""
        valid = free[:, None] & ok[:, :, None, None]
        return q.masked_fill(~valid, float("-inf")).flatten(1)

    #epsilon-greedy over every empty cell x use, not a sample of cells
    def act(g, free, counts, n_resid, eps):
        n_free = int(free.sum())
        ok = allowed(n_resid, n_free)
        fc = free[crop]
        if rng.random() < eps:
            ai = int(rng.choice(np.flatnonzero(ok)))
            idx = np.flatnonzero(fc.ravel())
            ci = int(rng.choice(idx))
        else:
            with torch.no_grad():
                x = inputs(torch.tensor(g[crop][None]), torch.tensor(fc[None]),
                           torch.tensor(glob(counts, n_free, n_resid)[None]))
                q = masked_q(net(x), torch.tensor(fc[None]), torch.tensor(ok[None]))
                flat = int(q.argmax())  #best (use, cell) pair over the whole crop
            ai, ci = divmod(flat, H * W)  #flat index -> use and cell
        r_, c_ = divmod(ci, W)
        return ai, r0 + r_, c0 + c_

    #fill the site once; with learn=False it only plays (random baseline, greedy run)
    def run_episode(eps, learn=True):
        nonlocal steps
        g = grid0.copy()
        free = site & (g == VACANT)
        counts = np.zeros(len(PLACEABLE))
        n_resid = 0
        prev = cleared_obj
        for _ in range(n_new):
            n_free = int(free.sum())
            s_grid, s_free = g[crop].copy(), free[crop].copy()
            s_glob = glob(counts, n_free, n_resid)
            ai, r_, c_ = act(g, free, counts, n_resid, eps)
            g[r_, c_] = PLACEABLE[ai]
            free[r_, c_] = False
            counts[ai] += 1
            n_resid += PLACEABLE[ai] == RESID
            new = objective(g, args.cell, site)
            reward = (new - prev) * 100.0  #same reward as rl_landuse.py: change in the objective, times 100
            prev = new
            if not learn:
                continue
            done = not free.any()  #last placement of the episode: no bootstrap after it
            buf.append((s_grid, s_free, s_glob, ai, (r_ - r0) * W + (c_ - c0), reward,
                        g[crop].copy(), free[crop].copy(),
                        glob(counts, n_free - 1, n_resid),
                        allowed(n_resid, n_free - 1), done))
            steps += 1
            if len(buf) >= args.warmup and steps % args.train_every == 0:  #learn every few steps once the buffer has enough
                train_step()
            if steps % args.target_sync == 0:  #refresh the target network
                tgt.load_state_dict(net.state_dict())
        return objective(g, args.cell, site), g

    #one gradient step on a random minibatch from the replay memory
    def train_step():
        batch = [buf[i] for i in rng.integers(len(buf), size=args.batch)]
        sg, sf, sgl, a, cell, r, ng, nf, ngl, nok, d = zip(*batch)
        sg = torch.tensor(np.stack(sg)); sf = torch.tensor(np.stack(sf))
        ng = torch.tensor(np.stack(ng)); nf = torch.tensor(np.stack(nf))
        sgl = torch.tensor(np.stack(sgl)); ngl = torch.tensor(np.stack(ngl))
        nok = torch.tensor(np.stack(nok))
        a = torch.tensor(a); cell = torch.tensor(cell)
        r = torch.tensor(r, dtype=torch.float32); d = torch.tensor(d, dtype=torch.float32)

        q = net(inputs(sg, sf, sgl)).flatten(1)
        q_sa = q.gather(1, (a * H * W + cell)[:, None]).squeeze(1)  #Q of the action actually taken
        with torch.no_grad():
            xn = inputs(ng, nf, ngl)
            best = masked_q(net(xn), nf, nok).argmax(1, keepdim=True)     # Double DQN
            q_next = tgt(xn).flatten(1).gather(1, best).squeeze(1)  #...valued by the target network (Double DQN)
            q_next = torch.where(torch.isfinite(q_next), q_next, torch.zeros_like(q_next))  #no valid next action -> 0
            target = r + args.gamma * (1 - d) * q_next  #TD target, cut at the end of the episode
        loss = nn.functional.smooth_l1_loss(q_sa, target)  #Huber loss
        opt.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(net.parameters(), 10.0)  #cap the gradient so one big error cannot wreck the weights
        opt.step()

    steps = 0
    # the baseline to beat: the same problem with every action random
    rand = [run_episode(1.0, learn=False)[0] for _ in range(args.random_episodes)]  #random policy: eps 1, no learning
    print(f"  random policy over {len(rand)} episodes: mean {np.mean(rand):.4f}, "
          f"best {np.max(rand):.4f}")
    curve, best_obj, best_grid = [], -1e9, None
    decay = max(1, int(0.7 * args.episodes))
    for ep in range(args.episodes):
        eps = max(0.05, 1.0 - 0.95 * ep / decay)  #linear from 1.0 to 0.05 over the first 70 % of episodes
        final, g = run_episode(eps)
        curve.append(round(final, 4))
        if final > best_obj:
            best_obj, best_grid = final, g.copy()
        if ep % max(1, args.episodes // 10) == 0 or ep == args.episodes - 1:
            print(f"     episode {ep+1:4}/{args.episodes}  eps {eps:.2f}  "
                  f"objective {final:.4f}  best {best_obj:.4f}  ({time.time()-t0:.0f} s)")

    greedy_obj, greedy_grid = run_episode(0.0, learn=False)  #what the network learned: no exploration
    if quota is not None:
        assert int((best_grid[site] == RESID).sum()) == quota
        assert int((greedy_grid[site] == RESID).sum()) == quota
    score = site_score(best_grid, args.cell, site)
    greedy_score = site_score(greedy_grid, args.cell, site)
    first = float(np.mean(curve[:max(1, len(curve) // 10)]))
    last = float(np.mean(curve[-max(1, len(curve) // 10):]))
    secs = time.time() - t0

    out = {
        "method": "reinforcement_learning",
        "algorithm": "Deep Q-network: fully convolutional CNN, experience replay, "
                     "target network, Double DQN, Huber loss, Adam, epsilon-greedy",
        "network": {"layers": "conv3x3, conv3x3 d2, conv3x3 d4, conv3x3 (ReLU), conv1x1",
                    "width": w, "input_channels": c_in, "parameters": n_params,
                    "crop_cells": [int(H), int(W)]},
        "cell_size_m": args.cell,
        "classes": CLASSES,
        "placeable_classes": [CLASSES[k] for k in PLACEABLE],
        "parameters": {"episodes": args.episodes, "gamma": args.gamma, "lr": args.lr,
                       "batch": args.batch, "buffer": args.buffer, "warmup": args.warmup,
                       "target_sync": args.target_sync, "train_every": args.train_every,
                       "eps_start": 1.0, "eps_end": 0.05,
                       "seed": args.seed, "programme_cells": n_new,
                       "housing_rule": (f"exactly {quota} residential cells (as today)"
                                        if quota is not None else "none")},
        "scope": "design_site",
        "scope_note": "Same problem as landuse_rl.json (site, objective, reward); "
                      "only the agent differs, so the two are directly comparable.",
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
        "greedy_objective": round(greedy_obj, 4),
        "random_policy": {"episodes": len(rand), "mean": round(float(np.mean(rand)), 4),
                          "sd": round(float(np.std(rand)), 4),
                          "best": round(float(np.max(rand)), 4)},
        "greedy_score": greedy_score,
        "training_seconds": round(secs, 1),
        "grid": {"nx": nx, "ny": ny},
        "colours": COLOURS,
        "png": f"landuse_rl_dqn{tag}_best.png",
        "bbox_wgs84": export_grid_png(best_grid, transform, "EPSG:28992",
                                      PROCESSED / f"landuse_rl_dqn{tag}_best.png"),
        "best_grid": best_grid.tolist(),
        "greedy_grid": greedy_grid.tolist(),
        "today_grid": grid_now.tolist(),
        "site_mask": site.astype(int).tolist(),
    }
    (PROCESSED / f"landuse_rl_dqn{tag}.json").write_text(json.dumps(out) + "\n")

    print(f"\n  learning: {first:.4f} (first 10% of episodes) -> {last:.4f} (last 10%)   "
          f"{'LEARNED' if last > first else 'NO IMPROVEMENT'}")
    print(f"  best objective {best_obj:.4f}, greedy policy {greedy_obj:.4f}, "
          f"random policy mean {np.mean(rand):.4f} (best {np.max(rand):.4f}), "
          f"site today {base_obj:.4f}")
    for name, sc in (("best plan", score), ("greedy plan", greedy_score)):
        print(f"  {name:11} -> mix {sc['landuse_mix']:.3f}, green {100*sc['green_share']:.1f}%, "
              f"amenity {sc['mean_distance_to_amenity_m']} m, "
              f"{sc['residential_cells']} residential cells (today {base_score['residential_cells']})")
    print(f"  {secs:.0f} s; wrote data/processed/landuse_rl_dqn{tag}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
