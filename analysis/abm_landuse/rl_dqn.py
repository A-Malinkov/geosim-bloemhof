#!/usr/bin/env python3
"""
rl_dqn.py - a convolutional deep Q-network for the same land-use problem.

Component 4.7, a second RL version. Owner: Atanas Malinkov

Grid, site, objective, reward and output are shared with rl_landuse.py, only
the agent differs. There a linear Q reads 13 features of 40 sampled cells, here
a CNN reads the grid and gives Q for every cell and use in one pass.

The network is fully convolutional over the site plus 6 cells. Channels are
one-hot land use, site and empty masks, road access, distance to water and the
site-wide share of each use, since the objective is a site-wide sum. Four 3x3
convolutions (two dilated, 2 and 4) see about 15 cells, a 1x1 gives Q per use.
Trained with replay, a target network every 500 steps, Double DQN, Huber loss
and Adam. Epsilon falls from 1 to 0.05 over the first 70 % of episodes.

Two results. best_objective is the best training episode, luck included.
greedy_objective is one run of the learned policy, what it actually learned.
hill_climb is the baseline, single-cell changes on the objective itself.

    python analysis/abm_landuse/rl_dqn.py   #the published run, 400 episodes, ~45 min

Needs PyTorch, CPU is enough, not in requirements.txt
    pip install --index-url https://download.pytorch.org/whl/cpu torch

Writes landuse_rl_dqn.json and landuse_rl_dqn_best.png in data/processed/.
"""

import json
import math
import pathlib
import sys
import time
from collections import deque

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import PROCESSED, STUDY_AREA, design_site_polygon  #noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ca_landuse import (  #noqa: E402
    CLASSES, COLOURS, FIXED, RESID, VACANT, WATER,
    accessibility, export_grid_png, rasterise,
)
from rl_landuse import PLACEABLE, objective, site_score  #noqa: E402

MARGIN = 6                      #cells of context around the site in the crop
N_GLOBAL = len(PLACEABLE) + 1   #site shares, progress


PARAMS = {
    "cell": 25.0,  #grid cell, m
    "episodes": 400,  #400 since 2026-10-30, as the linear agent, ~45 min on a CPU
    "gamma": 0.95,
    "lr": 5e-4,
    "batch": 64,
    "buffer": 20_000,
    "warmup": 500,  #transitions before learning
    "target_sync": 500,  #steps between target syncs
    "width": 48,  #conv channels
    "train_every": 4,  #env steps per gradient step
    "random_episodes": 30,  #episodes of a purely random policy, the baseline to beat
    "threads": 0,  #torch threads, 0 is the default
    "seed": 0,
    #tried on 2026-10-23, did not help, the defaults are the published run
    "action": "cell",  #"cell" picks cell and use, "use" fills cells in turn and picks only the use
    "order": "shuffle",  #cell order for action "use", "scan" is row by row
    "n_step": 1,  #n-step returns, 1 is one-step
    "eps_decay": 0.7,  #share of episodes over which epsilon falls
    "hill_climb": 56400,  #evaluations for the hill-climbing baseline, 0 is off
    "out_dir": str(PROCESSED),  #where the JSON and PNG go
    "tag": "",  #extra suffix for the output names
}


def main():
    p = PARAMS
    use_mode = p["action"] == "use"  #4 actions per step instead of every empty cell x use

    try:
        import torch
        import torch.nn as nn
    except ImportError:
        print("PyTorch is needed: pip install --index-url "
              "https://download.pytorch.org/whl/cpu torch")
        return 1
    from rasterio.features import rasterize as burn
    from scipy.ndimage import distance_transform_edt

    tag = p["tag"]  #one run since the housing rule went into the objective
    out_dir = pathlib.Path(p["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(p["seed"])
    if p["threads"]:
        torch.set_num_threads(p["threads"])
    rng = np.random.default_rng(p["seed"])
    t0 = time.time()

    print(f"Deep Q-network land-use allocation: {STUDY_AREA.name}")
    grid_now, transform, (nx, ny), road_frac = rasterise(p["cell"])
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
    homes_today = int((grid_now[site] == RESID).sum())  #housing cells on the site today, the housing term's reference
    base_obj = objective(grid_now, p["cell"], site, homes_today)
    base_score = site_score(grid_now, p["cell"], site)
    cleared_obj = objective(grid0, p["cell"], site, homes_today)
    print(f"  objective of the site today: {base_obj:.4f} ({homes_today} housing cells)")

    RES_I = PLACEABLE.index(RESID)
    site_c = torch.tensor(site[crop], dtype=torch.float32)
    static = torch.stack([site_c, torch.tensor(acc[crop]), torch.tensor(dist_water[crop])])  #inputs that never change during an episode
    placeable_t = torch.tensor(PLACEABLE)

    def allowed(n_resid, n_free):
        #every use is allowed at every step; the mask stays because the replay format carries it
        return np.ones(len(PLACEABLE), dtype=bool)

    def glob(counts, n_free, n_resid):
        #Site-wide context: shares of each placeable use, progress.
        placed = n_new - n_free
        shares = counts / max(1, n_new)
        return np.concatenate([shares, [placed / n_new]]).astype("float32")

    #stack every input channel: one-hot land use, empty mask, static layers, site-wide numbers
    def inputs(gc, fc, gl, cur=None):
        #Batch of network inputs from cropped grids (B,H,W), free masks, globals;
        #with --action use also the current cell (B,) as a flat crop index, -1 for none.
        B = gc.shape[0]
        onehot = torch.nn.functional.one_hot(gc.long(), len(CLASSES)).permute(0, 3, 1, 2).float()
        parts = [onehot, fc[:, None].float(), static[None].expand(B, -1, -1, -1),
                 gl[:, :, None, None].expand(-1, -1, H, W)]
        if use_mode:  #one more channel: which cell is being decided
            cm = torch.zeros(B, H * W)
            has = cur >= 0
            cm[has, cur[has]] = 1.0
            parts.append(cm.view(B, 1, H, W))
        return torch.cat(parts, dim=1)

    c_in = len(CLASSES) + 1 + 3 + N_GLOBAL + int(use_mode)  #8 one-hot + empty + 3 static + 6 site-wide (+ current cell)
    w = p["width"]

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
    opt = torch.optim.Adam(net.parameters(), lr=p["lr"])
    n_params = sum(t.numel() for t in net.parameters())
    print(f"  CNN: {n_params:,} parameters, {c_in} input channels; "
          f"{p['episodes']} episodes, replay {p['buffer']}, batch {p['batch']}")

    #replay: compact states (cropped grid + free mask + globals), rebuilt on sampling
    buf = deque(maxlen=p["buffer"])  #replay memory, oldest transitions fall out first

    def masked_q(q, free, ok):
        #q (B,4,H,W) -> flat (B, 4*H*W) with invalid actions at -inf.
        valid = free[:, None] & ok[:, :, None, None]
        return q.masked_fill(~valid, float("-inf")).flatten(1)

    #--action use: the current cell is given, the agent picks one of the 4 uses
    def act_use(g, free, counts, n_resid, eps, cur):
        n_free = int(free.sum())
        ok = allowed(n_resid, n_free)
        if rng.random() < eps:
            return int(rng.choice(np.flatnonzero(ok)))
        with torch.no_grad():
            x = inputs(torch.tensor(g[crop][None]), torch.tensor(free[crop][None]),
                       torch.tensor(glob(counts, n_free, n_resid)[None]), torch.tensor([cur]))
            q = net(x)[0].flatten(1)[:, cur].masked_fill(~torch.tensor(ok), float("-inf"))  #Q of each use at this cell
        return int(q.argmax())

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
    cells0 = np.argwhere(site & (grid0 == VACANT))  #the cells to fill, row by row (--action use)
    to_crop = lambda rc: int((rc[0] - r0) * W + (rc[1] - c0))  #grid cell -> flat crop index

    def run_episode(eps, learn=True):
        nonlocal steps
        g = grid0.copy()
        free = site & (g == VACANT)
        counts = np.zeros(len(PLACEABLE))
        n_resid = 0
        prev = cleared_obj
        order = (cells0[rng.permutation(len(cells0))] if p["order"] == "shuffle" else cells0) if use_mode else None
        pending = deque()  #n-step window: transitions waiting for their later rewards
        for t in range(n_new):
            n_free = int(free.sum())
            s_grid, s_free = g[crop].copy(), free[crop].copy()
            s_glob = glob(counts, n_free, n_resid)
            if use_mode:
                r_, c_ = order[t]
                cur = to_crop(order[t])
                ai = act_use(g, free, counts, n_resid, eps, cur)
            else:
                ai, r_, c_ = act(g, free, counts, n_resid, eps)
            g[r_, c_] = PLACEABLE[ai]
            free[r_, c_] = False
            counts[ai] += 1
            n_resid += PLACEABLE[ai] == RESID
            new = objective(g, p["cell"], site, homes_today)
            reward = (new - prev) * 100.0  #same reward as rl_landuse.py: change in the objective, times 100
            prev = new
            if not learn:
                continue
            done = not free.any()  #last placement of the episode: no bootstrap after it
            if use_mode or p["n_step"] > 1:
                nxt_cur = to_crop(order[t + 1]) if use_mode and not done else -1  #the cell decided next
                pending.append([s_grid, s_free, s_glob, ai, (r_ - r0) * W + (c_ - c0), reward,
                                g[crop].copy(), free[crop].copy(), glob(counts, n_free - 1, n_resid),
                                allowed(n_resid, n_free - 1), done, 1.0, nxt_cur])
                #once n rewards are in, or the episode ends, the oldest pending transition is complete
                while pending and (len(pending) >= p["n_step"] or done):
                    first = pending[0]
                    R, gp = 0.0, 1.0
                    for tr in pending:  #discounted sum of the next n rewards
                        R += gp * tr[5]
                        gp *= p["gamma"]
                    last = pending[-1]
                    buf.append((first[0], first[1], first[2], first[3], first[4], R,
                                last[6], last[7], last[8], last[9], last[10], gp, last[12]))
                    pending.popleft()
                    if not done:
                        break
            else:  #the published one-step path, unchanged
                buf.append((s_grid, s_free, s_glob, ai, (r_ - r0) * W + (c_ - c0), reward,
                            g[crop].copy(), free[crop].copy(),
                            glob(counts, n_free - 1, n_resid),
                            allowed(n_resid, n_free - 1), done))
            steps += 1
            if len(buf) >= p["warmup"] and steps % p["train_every"] == 0:  #learn every few steps once the buffer has enough
                train_step()
            if steps % p["target_sync"] == 0:  #refresh the target network
                tgt.load_state_dict(net.state_dict())
        return objective(g, p["cell"], site, homes_today), g

    #one gradient step on a random minibatch from the replay memory
    def train_step():
        batch = [buf[i] for i in rng.integers(len(buf), size=p["batch"])]
        if use_mode or p["n_step"] > 1:
            return train_step_n(batch)
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
            best = masked_q(net(xn), nf, nok).argmax(1, keepdim=True)     #Double DQN
            q_next = tgt(xn).flatten(1).gather(1, best).squeeze(1)  #...valued by the target network (Double DQN)
            q_next = torch.where(torch.isfinite(q_next), q_next, torch.zeros_like(q_next))  #no valid next action -> 0
            target = r + p["gamma"] * (1 - d) * q_next  #TD target, cut at the end of the episode
        loss = nn.functional.smooth_l1_loss(q_sa, target)  #Huber loss
        opt.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(net.parameters(), 10.0)  #cap the gradient so one big error cannot wreck the weights
        opt.step()

    #n-step / --action use version of the update: discount gamma^n, current-cell channel
    def train_step_n(batch):
        sg, sf, sgl, a, cell, r, ng, nf, ngl, nok, d, gp, ncur = zip(*batch)
        T = lambda v, **k: torch.tensor(np.stack(v) if isinstance(v[0], np.ndarray) else v, **k)
        sg, sf, sgl, ng, nf, ngl, nok = (T(v) for v in (sg, sf, sgl, ng, nf, ngl, nok))
        a, cell, ncur = torch.tensor(a), torch.tensor(cell), torch.tensor(ncur)
        r, d, gp = (torch.tensor(v, dtype=torch.float32) for v in (r, d, gp))
        cur = cell if use_mode else None
        q = net(inputs(sg, sf, sgl, cur)).flatten(1)
        q_sa = q.gather(1, (a * H * W + cell)[:, None]).squeeze(1)  #Q of the action taken
        with torch.no_grad():
            xn = inputs(ng, nf, ngl, ncur if use_mode else None)
            if use_mode:  #next decision: the 4 uses at the next cell
                at = ncur.clamp(min=0)
                qn = net(xn).flatten(2)[torch.arange(len(at)), :, at].masked_fill(~nok, float("-inf"))
                best = qn.argmax(1)
                q_next = tgt(xn).flatten(2)[torch.arange(len(at)), best, at]
                q_next = torch.where(torch.isfinite(qn.max(1).values), q_next, torch.zeros_like(q_next))
            else:
                best = masked_q(net(xn), nf, nok).argmax(1, keepdim=True)
                q_next = tgt(xn).flatten(1).gather(1, best).squeeze(1)
                q_next = torch.where(torch.isfinite(q_next), q_next, torch.zeros_like(q_next))
            target = r + gp * (1 - d) * q_next  #n-step TD target: gp = gamma^n
        loss = nn.functional.smooth_l1_loss(q_sa, target)
        opt.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(net.parameters(), 10.0)
        opt.step()

    #baseline: hill climbing on the objective itself, its own random generator
    def hill_climb(budget):
        hr = np.random.default_rng(p["seed"] + 1)
        cells = [tuple(c) for c in cells0]
        g = grid0.copy()
        uses = hr.choice(len(PLACEABLE), size=len(cells))  #a random start
        for (r_, c_), u in zip(cells, uses):
            g[r_, c_] = PLACEABLE[u]
        cur = objective(g, p["cell"], site, homes_today)
        best, best_g, evals, accepted = cur, g.copy(), 1, 0
        while evals < budget:
            i = int(hr.integers(len(cells)))
            r_, c_ = cells[i]
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

    steps = 0
    #the baseline to beat: the same problem with every action random
    rand = [run_episode(1.0, learn=False)[0] for _ in range(p["random_episodes"])]  #random policy: eps 1, no learning
    print(f"  random policy over {len(rand)} episodes: mean {np.mean(rand):.4f}, "
          f"best {np.max(rand):.4f}")
    curve, best_obj, best_grid = [], -1e9, None
    hc = None
    if p["hill_climb"]:
        th = time.time()
        hb, hg, he, ha = hill_climb(p["hill_climb"])
        hc = {"evaluations": he, "accepted_moves": ha, "best_objective": round(hb, 4),
              "score": site_score(hg, p["cell"], site), "seconds": round(time.time() - th, 1)}
        print(f"  hill climbing, {he} evaluations: best {hb:.4f} ({time.time() - th:.0f} s)")
    decay = max(1, int(p["eps_decay"] * p["episodes"]))
    for ep in range(p["episodes"]):
        eps = max(0.05, 1.0 - 0.95 * ep / decay)  #linear from 1.0 to 0.05 over the first eps_decay share of episodes
        final, g = run_episode(eps)
        curve.append(round(final, 4))
        if final > best_obj:
            best_obj, best_grid = final, g.copy()
        if ep % max(1, p["episodes"] // 10) == 0 or ep == p["episodes"] - 1:
            print(f"     episode {ep+1:4}/{p['episodes']}  eps {eps:.2f}  "
                  f"objective {final:.4f}  best {best_obj:.4f}  ({time.time()-t0:.0f} s)")

    greedy_obj, greedy_grid = run_episode(0.0, learn=False)  #what the network learned: no exploration
    score = site_score(best_grid, p["cell"], site)
    greedy_score = site_score(greedy_grid, p["cell"], site)
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
        "cell_size_m": p["cell"],
        "classes": CLASSES,
        "placeable_classes": [CLASSES[k] for k in PLACEABLE],
        "parameters": {"episodes": p["episodes"], "gamma": p["gamma"], "lr": p["lr"],
                       "batch": p["batch"], "buffer": p["buffer"], "warmup": p["warmup"],
                       "target_sync": p["target_sync"], "train_every": p["train_every"],
                       "eps_start": 1.0, "eps_end": 0.05,
                       "action": p["action"], "order": p["order"] if use_mode else None,
                       "n_step": p["n_step"], "eps_decay": p["eps_decay"],
                       "seed": p["seed"], "programme_cells": n_new},
        "homes_today_cells": homes_today,  #the housing term's reference
        "scope": "design_site",
        "scope_note": "Same problem as landuse_rl.json (site, objective, reward); "
                      "only the agent differs, so the two are directly comparable.",
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
        "greedy_objective": round(greedy_obj, 4),
        "random_policy": {"episodes": len(rand), "mean": round(float(np.mean(rand)), 4),
                          "sd": round(float(np.std(rand)), 4),
                          "best": round(float(np.max(rand)), 4)},
        "greedy_score": greedy_score,
        "hill_climb": hc,  #direct optimisation of the same objective, the baseline any learner should beat
        "training_seconds": round(secs, 1),
        "grid": {"nx": nx, "ny": ny},
        "colours": COLOURS,
        "png": f"landuse_rl_dqn{tag}_best.png",
        "bbox_wgs84": export_grid_png(best_grid, transform, "EPSG:28992",
                                      out_dir / f"landuse_rl_dqn{tag}_best.png"),
        "best_grid": best_grid.tolist(),
        "greedy_grid": greedy_grid.tolist(),
        "today_grid": grid_now.tolist(),
        "site_mask": site.astype(int).tolist(),
    }
    (out_dir / f"landuse_rl_dqn{tag}.json").write_text(json.dumps(out) + "\n")

    print(f"\n  learning: {first:.4f} (first 10% of episodes) -> {last:.4f} (last 10%)   "
          f"{'LEARNED' if last > first else 'NO IMPROVEMENT'}")
    print(f"  best objective {best_obj:.4f}, greedy policy {greedy_obj:.4f}, "
          f"random policy mean {np.mean(rand):.4f} (best {np.max(rand):.4f}), "
          f"site today {base_obj:.4f}"
          + (f", hill climbing {hc['best_objective']:.4f}" if hc else ""))
    for name, sc in (("best plan", score), ("greedy plan", greedy_score)):
        print(f"  {name:11} -> mix {sc['landuse_mix']:.3f}, green {100*sc['green_share']:.1f}%, "
              f"amenity {sc['mean_distance_to_amenity_m']} m, "
              f"{sc['residential_cells']} residential cells (today {base_score['residential_cells']})")
    print(f"  {secs:.0f} s; wrote {out_dir / f'landuse_rl_dqn{tag}.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
