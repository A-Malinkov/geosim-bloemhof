#!/usr/bin/env python3
"""
optimise_links.py — which new footpaths through the design site shorten
everyday walks the most.

Component 4.8. Built 2026-10-21. Uses the network, homes and destinations of
road_network.py, so run that first.

USAGE
-----
    python analysis/roads/optimise_links.py

OBJECTIVE
---------
Minimise J, the mean walking distance from a dwelling to the nearest shop,
school, health practice and rail stop, averaged over the four types with equal
weight and over every dwelling in the two buurten and on the site
(road_network.py's "mean_of_types_m" over the study area). The destinations are
the same in every scenario, so J moves only when the network or the homes do.

METHOD
------
  candidates  straight footpaths between two network nodes on the site (or
              within 20 m of it, so the edge streets count), 10 to 150 m
              long, at most 20 m of it off the site, that cross no building
              and no water of the scenario, start or end on the design's own
              network (new street or connector), meet the existing network only at their two
              nodes, and save a detour: the network route between the two
              nodes is at least 1.5 times the straight line.
  greedy      add the candidate that lowers J most, recompute, repeat until
              the budget of links is spent, the candidates run out, or no
              candidate lowers J by 1 mm any more. Every candidate is re-scored after
              each pick, because a link can make another one useless.
  ceiling     J with every candidate added at once: the most these candidates
              could ever give. Each pick is reported as a share of it, which
              shows the diminishing returns.

WHAT IT CANNOT TELL YOU
-----------------------
* Greedy is not guaranteed optimal. A pair of links that only help together
  is never picked.
* Space between new blocks is assumed public and walkable. Whether a link runs
  through a courtyard the design means to be private is a design decision the
  script cannot see. In the baseline that space is back gardens, so the
  baseline is not optimised.
* The new blocks' dwellings sit at their centroids (road_network.py), so a link
  that passes a block's real entrance is scored at its middle.
* Distance only. Lighting, overlooking, steps and gradients are not modelled.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scenarios"))
import road_network as rn  # noqa: E402
from common.project import PROCESSED, ROOT, design_site_polygon, to_wgs, write_processed  # noqa: E402

CASES = [
    {"scenario": "scenario_a", "budget": 10, "min_m": 10.0, "max_m": 150.0, "detour_min": 1.5, "reach_m": 20.0},
    {"scenario": "scenario_b", "budget": 10, "min_m": 10.0, "max_m": 150.0, "detour_min": 1.5, "reach_m": 20.0},
    #baseline: not run, its open land is private back gardens
]


# --------------------------------------------------------------- candidates
def candidates(net, scenario, c):
    #straight links between site nodes that cross no building and save a detour -> array (i, j, length)
    import geopandas as gpd
    import shapely
    from scipy.sparse.csgraph import dijkstra
    from scenario_world import buildings_for_scenario, site_footprints, water_for  #water_for: the scenario's pond
    site = design_site_polygon()
    fp = site_footprints()
    b = gpd.GeoDataFrame({"identificatie": [i for i, _ in fp], "height_m": np.nan},
                         geometry=[g for _, g in fp], crs=28992)
    b = buildings_for_scenario(b, scenario)  #the scenario's buildings, old ones demolished
    walls = list(b.geometry.buffer(-0.5).values)  #a link may brush a wall, not go through it
    walls += water_for(scenario)  #nor through the scenario's pond (two picks crossed it before 2026-10-23)
    walls = shapely.STRtree(walls)
    streets = shapely.STRtree(net["lines"].geometry.values)  #existing network lines
    on = np.flatnonzero(shapely.within(shapely.points(net["xy"]), site.buffer(c["reach_m"])))
    #nodes on the design's own network (new streets, connectors, joins): a link must use one, else it only
    #mends a gap OSM has today too (two picks joined an OSM footway ending 2 m short of a street, 2026-10-23)
    own = np.zeros(len(net["xy"]), bool)
    own[net["ij"][(net["lines"]["kind"] != "osm").to_numpy()].ravel()] = True
    G = rn.csr(net)
    D = dijkstra(G, directed=False, indices=on)[:, on]  #network distance between every pair of site nodes
    xy = net["xy"][on]
    out = []
    for a in range(len(on)):
        for b_ in range(a + 1, len(on)):
            L = float(np.hypot(*(xy[a] - xy[b_])))
            if not (c["min_m"] <= L <= c["max_m"]) or D[a, b_] < c["detour_min"] * L:
                continue  #too short, too long, or the network already goes nearly straight
            if not (own[on[a]] or own[on[b_]]):
                continue  #between two OSM nodes: a gap in today's network, not part of the design
            seg = shapely.LineString([xy[a], xy[b_]])
            if seg.difference(site).length > c["reach_m"]:
                continue  #mostly off the site: not ours to build
            if len(walls.query(seg, predicate="intersects")):
                continue  #through a building
            ends = shapely.MultiPoint([xy[a], xy[b_]]).buffer(0.5)
            hit = streets.query(seg, predicate="intersects")
            if any(not ends.contains(seg.intersection(net["lines"].geometry.values[h])) for h in hit):
                continue  #crosses or runs along an existing street away from its own two nodes
            out.append((on[a], on[b_], L))
    print(f"  {len(on)} site nodes, {len(out)} candidate links")
    return np.array(out)


# ------------------------------------------------------------------- scoring
def scorer(net, homes, dest, grid):
    #-> function(extra links) giving J over all dwellings, J over site dwellings and the site-grid mean
    hs = rn.snap(net, homes.geometry.values)
    gs = rn.snap(net, grid.geometry.values)
    ds = {k: rn.snap(net, pts.values) for k, pts in dest.items()}
    w = homes["w"].to_numpy()
    site = homes["site"].to_numpy()
    def score(extra=()):
        G = rn.csr(net, extra)
        D = {k: rn.dist_from(net, G, s) for k, s in ds.items()}  #node distances per type with the extra links
        h = np.mean([rn.to_points(net, d, hs) for d in D.values()], axis=0)  #mean over types per dwelling
        g = np.mean([rn.to_points(net, d, gs) for d in D.values()], axis=0)
        return (float(np.average(h, weights=w)), float(np.average(h[site], weights=w[site])), float(g.mean()))
    return score


MIN_GAIN_M = 0.001  #a pick must lower J by at least 1 mm, or the greedy stops: it no longer helps anyone


def greedy(score, cand, budget, start):
    #add the best remaining candidate, budget times; -> list of (index, scores after)
    #stops early when the candidates run out or the best one no longer lowers J (start = scores with none)
    chosen, picks, prev = [], [], start
    for step in range(budget):
        t = time.time()
        best, best_s = None, None
        for k in range(len(cand)):
            if k in chosen:
                continue
            s = score(cand[chosen + [k]])
            if best_s is None or s[0] < best_s[0]:
                best, best_s = k, s
        if best is None or prev[0] - best_s[0] < MIN_GAIN_M:
            print(f"  stopped after {step} links: " + ("no candidates left" if best is None else "no link lowers J any more"))
            break
        prev = best_s
        chosen.append(best)
        picks.append((best, best_s))
        print(f"  link {step + 1}: {cand[best][2]:5.1f} m, J {best_s[0]:.2f} m, "
              f"site dwellings {best_s[1]:.1f} m, site grid {best_s[2]:.1f} m  ({time.time() - t:.0f} s)")
    return picks


# --------------------------------------------------------------------- run
def run(case, p, dest, dwelling_m2, baseline_grid):
    #one scenario: candidates, ceiling, greedy picks, geojson of the picks
    sc = case["scenario"]
    print(f"\n{sc}")
    net = rn.network_for(sc, p)
    homes = rn.homes_for_scenario(sc, dwelling_m2, p)
    grid = rn.site_grid(p)
    cand = candidates(net, sc, case)
    score = scorer(net, homes, dest, grid)
    s0 = score()
    ceil = score(cand)
    print(f"  J now {s0[0]:.2f} m, with every candidate {ceil[0]:.2f} m")
    picks = greedy(score, cand, case["budget"], s0)
    steps, feats, prev = [], [], s0
    for r, (k, s) in enumerate(picks, 1):
        i, j, L = cand[k]
        a, b = net["xy"][int(i)], net["xy"][int(j)]
        steps.append({"rank": r, "length_m": round(float(L), 1),
                      "gain_m": round(prev[0] - s[0], 3),  #J saved by this link
                      "J_m": round(s[0], 2), "site_dwellings_m": round(s[1], 1), "site_grid_m": round(s[2], 1),
                      "share_of_ceiling": round((s0[0] - s[0]) / (s0[0] - ceil[0]), 3)})
        feats.append({"type": "Feature",
                      "properties": {"rank": r, "length_m": round(float(L), 1), "gain_m": steps[-1]["gain_m"]},
                      "geometry": {"type": "LineString",
                                   "coordinates": [[round(v, 6) for v in to_wgs(*a)], [round(v, 6) for v in to_wgs(*b)]]}})
        prev = s
    path = PROCESSED / f"road_links_{sc}.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")) + "\n")
    print(f"  wrote {path.relative_to(ROOT)}")
    return {
        "budget": case["budget"],
        "candidate_rule": {k: case[k] for k in ("min_m", "max_m", "detour_min", "reach_m")},
        "n_candidates": int(len(cand)),
        "J_before_m": round(s0[0], 2), "site_dwellings_before_m": round(s0[1], 1), "site_grid_before_m": round(s0[2], 1),
        "J_ceiling_m": round(ceil[0], 2), "site_grid_ceiling_m": round(ceil[2], 1),
        "site_grid_baseline_m": baseline_grid,  #today's network on the same grid, for reference
        "steps": steps,
        "geojson": f"../data/processed/road_links_{sc}.geojson",
    }


def main() -> int:
    p = rn.PARAMS
    print("Footpath link optimisation")
    metrics = json.loads((PROCESSED / "road_metrics.json").read_text())
    if "site_grid" not in metrics.get("baseline", {}):
        sys.exit("Run analysis/roads/road_network.py first.")
    dest, _, dwelling_m2 = rn.destinations()
    out = {
        "_objective": "J = mean walking distance from a dwelling to the nearest shop, education, health care and "
                      "rail stop, equal weights over the four types, dwelling-weighted over the study area and "
                      "the design site. Minimised by adding straight footpaths through the site, greedily.",
        "_method": "analysis/roads/optimise_links.py",
    }
    for case in CASES:  #one scenario per case
        out[case["scenario"]] = run(case, p, dest, dwelling_m2, metrics["baseline"]["site_grid"]["mean_of_types_m"])
    for sc in ("baseline", "scenario_a", "scenario_b"):
        if sc not in out:
            out[sc] = {"_status": "not_computed_yet",
                       "_note": "baseline: open land is private gardens" if sc == "baseline" else f"{sc} has no massing yet"}
    write_processed("road_links.json", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
