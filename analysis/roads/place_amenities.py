#!/usr/bin/env python3
"""
place_amenities.py — where in the new blocks the shops, health practices and
schools should go.

Component 4.8. Built 2026-10-27. Uses the network, homes and destinations of
road_network.py.

USAGE
-----
    python analysis/roads/place_amenities.py

WHY
---
Both Rhino options are housing only. The ground they clear holds 20 shops, 7
health-care addresses and 1 school today (BAG), and none come back. This puts
them back on the ground floors of the new blocks, where they shorten everyday
walks the most.

PROBLEM
-------
A p-median problem per amenity type (Hakimi 1964). For type k, choose p_k
sites S_k from the candidates to minimise

    J_k = sum_h w_h * min( d_h(existing k), min_{s in S_k} d_h(s) ) / sum_h w_h

the dwelling-weighted mean walking distance from every dwelling in the buurt
(and on the site) to its nearest destination of type k, existing or new. w_h is
one per BAG dwelling and the estimated dwellings for each new block. One
candidate holds one amenity.

  candidates  points every 15 m along the outline of each new block, kept only
              where a street or path is within 40 m, outside the kept block
              (never touched), snapped to the walk
              network like the homes, so the walk from the door to the path
              counts. B's blocks stand 11-36 m back from their paths (median
              per block), A's 3-18 m; a tighter limit shuts B out.
  budget      p_k = what the cleared ground holds today: shop 20, health 7,
              school 1. Like-for-like replacement, a choice we state.
  school      today the site has two schools. The one in the kept community
              centre stays exactly where it is, untouched, and is never moved
              (Atanas, 2026-10-27); it is an existing destination. The other,
              demolished, is replaced by one placed school like any other type.
  method      greedy (each pick the candidate that lowers J_k most), then
              vertex substitution (Teitz and Bart 1968): swap a chosen site for
              an unchosen one while that lowers J_k. Types are placed in the
              order health, shop, each taking only free candidates.
  floor area  each amenity takes the median ground-floor area of its type on
              the cleared ground today (BAG), lost to housing at 73 m2 per
              dwelling and 0.8 usable/gross. Reported, not fed back into the
              dwelling counts the weights use (a few dozen of ~1,900).

Also reported: J_k for p = 0 .. 2 p_k, so the diminishing returns show.

OUTPUT
------
    data/processed/design_amenities.geojson   placed amenities (points), per scenario
    data/processed/amenity_placement.json     per scenario and type: J before and after,
                                              site dwellings and site grid before/after,
                                              the p curve, floor area and dwellings lost

WHAT IT CANNOT TELL YOU
-----------------------
* Distance only. Whether a shop survives at a spot (footfall, rent, clustering
  with other shops) is not modelled, and the objective rewards spreading shops
  out, the opposite of how real retail behaves (see analysis/abm_landuse/).
* A school needs far more floor than a shop. Education is placed as a point;
  whether a block's ground floor can hold a school is a design question.
* One amenity per 15 m of facade, of any size.
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scenarios"))
import road_network as rn  # noqa: E402
from common.project import PROCESSED, RAW, ROOT, design_site_polygon, to_wgs, write_processed  # noqa: E402

CASES = [
    {"scenario": "scenario_a"},
    {"scenario": "scenario_b"},
]

PARAMS = {
    "spacing_m": 15.0,  #candidate every 15 m along a block outline
    "street_m": 40.0,  #a candidate needs a path this close; B's blocks stand 11-36 m back in green, the walk to the path is counted anyway
    "order": ["education", "health", "shop"],  #placed in this order, each from the candidates still free
    "fixed": {"education": "0599100000623494"},  #BAG pand of the kept school: stays where it is, never moved, never counted as placed
    "curve_factor": 2,  #report J for p = 0 .. 2 * budget
    "dwelling_m2": 73.0,  #usable floor per dwelling, the site's BAG median (as road_network.py)
    "random_draws": 200,  #random placements of the same number, the bar the optimiser has to clear
    "seed": 0,
}


# --------------------------------------------------------------- the inputs
def budgets():
    #what the cleared ground holds today per type (BAG), and their median floor area
    import geopandas as gpd
    from shapely.ops import unary_union
    from scenario_world import cleared_area
    cleared = unary_union([cleared_area(c["scenario"]) for c in CASES])
    bag = gpd.read_file(RAW / "bag_verblijfsobjecten.geojson").to_crs(28992)
    bag = bag[bag["gebruiksdoel"].notna() & bag.within(cleared)]
    out = {}
    for k, doel in rn.DEST.items():
        if doel == "rail":
            continue  #rail stops are not a design choice
        x = bag[bag["gebruiksdoel"].str.contains(doel)]
        out[k] = {"p": int(len(x)), "median_m2": float(x["area_m2"].median()) if len(x) else 0.0}
    return out


def candidates(scenario, net, p):
    #points along the new blocks' outlines that face a street -> GeoDataFrame with the block name
    import geopandas as gpd
    import shapely
    from scenario_world import cleared_area, load_scenario
    blocks, _ = load_scenario(scenario)
    kept = design_site_polygon().difference(cleared_area(scenario))  #the kept community centre and school: never touched
    streets = shapely.STRtree(net["lines"].geometry.values)
    rows = []
    for name, g in zip(blocks["name"], blocks.geometry):
        ring = g.exterior if g.geom_type == "Polygon" else max(g.geoms, key=lambda q: q.area).exterior
        for d in np.arange(p["spacing_m"] / 2, ring.length, p["spacing_m"]):  #evenly along the facade
            pt = ring.interpolate(d)
            if kept.buffer(0.5).contains(pt):
                continue  #a block reaching into the kept block gets no amenity there
            near = streets.query_nearest(pt, max_distance=p["street_m"], all_matches=False)  #a single point gives a flat index array
            if len(near):  #a street within reach: a door can open onto it
                rows.append({"block": name, "geometry": pt})
    c = gpd.GeoDataFrame(rows, crs=28992)
    print(f"  {scenario}: {len(c)} candidate ground-floor spots on {c['block'].nunique()} blocks")
    return c


SHOWN = {"shop": "winkelfunctie", "health": "gezondheidszorgfunctie", "education": "onderwijsfunctie",
         "community": "bijeenkomstfunctie"}  #amenity types drawn on the maps; community halls are shown, never placed


def today_on_site():
    #today's amenities on the design site (BAG): each with its type and whether the kept block keeps it
    import geopandas as gpd
    from scenario_world import cleared_area
    site = design_site_polygon()
    kept = site.difference(cleared_area(CASES[0]["scenario"]))  #the kept block, the same in both options
    bag = gpd.read_file(RAW / "bag_verblijfsobjecten.geojson").to_crs(28992)
    bag = bag[bag["gebruiksdoel"].notna() & bag.within(site)]
    rows = []
    for k, doel in SHOWN.items():
        for _, r in bag[bag["gebruiksdoel"].str.contains(doel)].iterrows():
            rows.append({"type": k, "kept": bool(r.geometry.within(kept)), "floor_m2": float(r["area_m2"]),
                         "street": str(r["street"]), "x": r.geometry.x, "y": r.geometry.y})
    return rows


def point_feature(scenario, row, **props):
    #one amenity as a GeoJSON point feature
    lon, lat = to_wgs(row["x"], row["y"])
    return {"type": "Feature",
            "properties": {"scenario": scenario, "type": row["type"], "floor_m2": round(row["floor_m2"]), **props},
            "geometry": {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]}}


def fixed_school(p):
    #RD location of the kept school: its BAG education address, never moved
    import geopandas as gpd
    bag = gpd.read_file(RAW / "bag_verblijfsobjecten.geojson").to_crs(28992)
    x = bag[(bag["pand_id"].astype(str) == p["fixed"]["education"]) & bag["gebruiksdoel"].fillna("").str.contains("onderwijs")]
    assert len(x), "the kept school is not in BAG"  #never place it anywhere else
    g = x.geometry.iloc[0]
    return g.x, g.y


# ------------------------------------------------------------ the p-median
def mean_dist(D, w):
    #dwelling-weighted mean of the nearest-destination distance
    return float(np.average(D, weights=w))


def greedy(base, C, w, p, free):
    #add p sites one at a time, each the one that lowers the mean most -> list of column indices
    cur, chosen = base.copy(), []
    for _ in range(p):
        gains = (w[:, None] * (cur[:, None] - np.minimum(cur[:, None], C[:, free]))).sum(axis=0)
        j = free[int(np.argmax(gains))]
        chosen.append(j)
        free = free[free != j]
        cur = np.minimum(cur, C[:, j])
    return chosen


def substitute(base, C, w, chosen, free):
    #vertex substitution: swap a chosen site for a free one while the mean falls
    def value(S):
        return mean_dist(np.minimum(base, C[:, S].min(axis=1)) if S else base, w)
    best = value(chosen)
    improved = True
    while improved:
        improved = False
        for i in range(len(chosen)):
            rest = chosen[:i] + chosen[i + 1:]
            part = np.minimum(base, C[:, rest].min(axis=1)) if rest else base  #without site i
            vals = (w[:, None] * np.minimum(part[:, None], C[:, free])).sum(axis=0) / w.sum()
            k = int(np.argmin(vals))
            if vals[k] < best - 1e-6:  #a strictly better swap
                old = chosen[i]
                chosen[i] = int(free[k])
                free = np.r_[free[free != free[k]], old]
                best = float(vals[k])
                improved = True
    return chosen, best


# --------------------------------------------------------------------- run
def run(case, p, dest, bud, dwelling_m2, rp):
    #one scenario: candidates, distance matrices, placement per type, the p curves
    sc = case["scenario"]
    print(f"\n{sc}")
    net = rn.network_for(sc, rp)
    G = rn.csr(net)
    homes = rn.homes_for_scenario(sc, dwelling_m2, rp)
    w = homes["w"].to_numpy()
    site = homes["site"].to_numpy()
    grid = rn.site_grid(rp)
    hs, gs = rn.snap(net, homes.geometry.values), rn.snap(net, grid.geometry.values)
    cand = candidates(sc, net, p)
    cs = rn.snap(net, cand.geometry.values)
    #distance from every home and grid point to every candidate: one Dijkstra per candidate
    CH = np.empty((len(homes), len(cand)))
    CG = np.empty((len(grid), len(cand)))
    for j in range(len(cand)):
        one = (cs[0][j:j + 1], cs[1][j:j + 1], cs[2][j:j + 1])
        D = rn.dist_from(net, G, one)
        CH[:, j] = rn.to_points(net, D, hs)
        CG[:, j] = rn.to_points(net, D, gs)
    free = np.arange(len(cand))
    res, feats = {}, []
    for k in p["order"]:
        Dk = rn.dist_from(net, G, rn.snap(net, dest[k].values))  #existing destinations of this type
        base, base_g = rn.to_points(net, Dk, hs), rn.to_points(net, Dk, gs)
        pk = bud[k]["p"]
        #greedy adds one site at a time, so one long run gives J for every p = 0, 1, 2, ... as its prefix
        long = greedy(base, CH, w, min(p["curve_factor"] * pk, len(free)), free.copy())
        cur, curve = base.copy(), [mean_dist(base, w)]
        for j in long:
            cur = np.minimum(cur, CH[:, j])
            curve.append(mean_dist(cur, w))
        chosen = list(long[:pk])  #the greedy start for the swaps
        assert len(chosen) == pk, f"{sc} {k}: only {len(chosen)} free spots for {pk}"  #never place fewer silently
        chosen, best = substitute(base, CH, w, chosen, free.copy()) if pk else ([], curve[0])
        rng = np.random.default_rng(p["seed"])
        rand = [mean_dist(np.minimum(base, CH[:, rng.choice(free, pk, replace=False)].min(axis=1)), w)
                for _ in range(p["random_draws"])] if pk else [curve[0]]  #same number of amenities on random free spots
        after = np.minimum(base, CH[:, chosen].min(axis=1)) if chosen else base
        after_g = np.minimum(base_g, CG[:, chosen].min(axis=1)) if chosen else base_g
        free = np.array([f for f in free if f not in set(chosen)])  #a spot holds one amenity
        lost = pk * bud[k]["median_m2"] / dwelling_m2  #dwellings the ground floors give up
        res[k] = {"p": pk, "J_before_m": round(curve[0], 1), "J_after_m": round(best, 1),
                  "J_greedy_m": round(curve[pk], 1),  #before the swaps
                  "J_random_mean_m": round(float(np.mean(rand)), 1), "J_random_best_m": round(float(np.min(rand)), 1),
                  "site_dwellings_before_m": round(mean_dist(base[site], w[site]), 1),
                  "site_dwellings_after_m": round(mean_dist(after[site], w[site]), 1),
                  "site_grid_before_m": round(float(base_g.mean()), 1), "site_grid_after_m": round(float(after_g.mean()), 1),
                  "curve_m": [round(v, 2) for v in curve],
                  "floor_m2": round(pk * bud[k]["median_m2"]), "dwellings_lost_est": round(lost, 1)}
        print(f"  {k:9s} p {pk:2d}: buurt {curve[0]:6.1f} -> {best:6.1f} m (greedy {curve[pk]:.1f}, random mean "
              f"{np.mean(rand):.1f}, best of {len(rand)} {np.min(rand):.1f}), site dwellings "
              f"{res[k]['site_dwellings_before_m']:6.1f} -> {res[k]['site_dwellings_after_m']:6.1f} m, "
              f"site grid {res[k]['site_grid_before_m']:6.1f} -> {res[k]['site_grid_after_m']:6.1f} m")
        for r, j in enumerate(chosen, 1):
            x, y = cand.geometry.values[j].x, cand.geometry.values[j].y
            lon, lat = to_wgs(x, y)
            feats.append({"type": "Feature",
                          "properties": {"scenario": sc, "type": k, "rank": r, "block": cand["block"].values[j],
                                         "floor_m2": round(bud[k]["median_m2"]), "status": "placed"},
                          "geometry": {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]}})
    #the four-type mean the rest of the project uses (rail stops unchanged)
    Dr = rn.dist_from(net, G, rn.snap(net, dest["rail_stop"].values))
    rail_h, rail_g = rn.to_points(net, Dr, hs), rn.to_points(net, Dr, gs)
    fixed_school(p)  #asserts the kept school is in BAG; main() draws it with the other kept amenities
    print(f"  education fixed at the kept school: buurt {res['education']['J_after_m']} m, "
          f"site dwellings {res['education']['site_dwellings_after_m']} m")
    four = lambda key, rail: round(float(np.mean([res[k][key] for k in p["order"]] + [rail])), 1)
    res["mean_of_four"] = {
        "site_dwellings_before_m": four("site_dwellings_before_m", mean_dist(rail_h[site], w[site])),
        "site_dwellings_after_m": four("site_dwellings_after_m", mean_dist(rail_h[site], w[site])),
        "site_grid_before_m": four("site_grid_before_m", float(rail_g.mean())),
        "site_grid_after_m": four("site_grid_after_m", float(rail_g.mean())),
    }
    res["n_candidates"] = int(len(cand))
    res["dwellings_lost_est"] = round(sum(res[k]["dwellings_lost_est"] for k in p["order"]), 1)
    m = res["mean_of_four"]
    print(f"  mean of four: site dwellings {m['site_dwellings_before_m']} -> {m['site_dwellings_after_m']} m, "
          f"site grid {m['site_grid_before_m']} -> {m['site_grid_after_m']} m; "
          f"about {res['dwellings_lost_est']:.0f} dwellings' floor area used")
    return res, feats


def today_with_own(dest, dwelling_m2, rp):
    #today with its own shops, health practices and schools where they are: the fair reference for "with amenities"
    import geopandas as gpd
    import pandas as pd
    from shapely.ops import unary_union
    from scenario_world import cleared_area
    cleared = unary_union([cleared_area(c["scenario"]) for c in CASES])
    bag = gpd.read_file(RAW / "bag_verblijfsobjecten.geojson").to_crs(28992)
    bag = bag[bag["gebruiksdoel"].notna() & bag.within(cleared)]
    net = rn.network_for("baseline", rp)
    G = rn.csr(net)
    homes = rn.homes_for_scenario("baseline", dwelling_m2, rp)
    w, site = homes["w"].to_numpy(), homes["site"].to_numpy()
    hs, gs = rn.snap(net, homes.geometry.values), rn.snap(net, rn.site_grid(rp).geometry.values)
    out = {}
    for k, doel in rn.DEST.items():
        pts = dest[k]
        if doel != "rail":  #put back what road_network.py leaves out on cleared ground
            own = bag[bag["gebruiksdoel"].str.contains(doel)].geometry
            pts = gpd.GeoSeries(pd.concat([pts, own], ignore_index=True), crs=28992)
        D = rn.dist_from(net, G, rn.snap(net, pts.values))
        h, g = rn.to_points(net, D, hs), rn.to_points(net, D, gs)
        out[k] = {"site_dwellings_m": round(mean_dist(h[site], w[site]), 1), "site_grid_m": round(float(g.mean()), 1)}
    out["mean_of_four"] = {q: round(float(np.mean([out[k][q] for k in rn.DEST])), 1) for q in ("site_dwellings_m", "site_grid_m")}
    print(f"  today with its own amenities: site dwellings {out['mean_of_four']['site_dwellings_m']} m, "
          f"site grid {out['mean_of_four']['site_grid_m']} m (mean of four)")
    return out


# ------------------------------------------------------------------ figure
TYPE_STYLE = {"shop": ("#7b4fd0", "o", "shop"), "health": ("#d63c7b", "P", "health care"),
              "education": ("#1f2a44", "*", "school"), "community": ("#b8860b", "s", "community hall")}  #colour, marker, label


def figure(out, feats):
    #today's amenities and each option's, on three maps, and the walk against the number placed
    sys.path.insert(0, str(HERE.parent / "comparison"))
    import matplotlib.pyplot as plt
    from shapely.geometry import shape
    from shapely.ops import transform as shp_t
    from compare_scenarios import COL, INK, INK2, NAME, J, save, style  #the comparison figures' look
    from common.project import to_rd
    style()
    site = design_site_polygon()
    massing = J("design_massing.geojson")
    fig = plt.figure(figsize=(16, 10.5))
    gs = fig.add_gridspec(2, 6, height_ratios=[1.15, 1])  #three maps on top, two curves below
    x0, y0, x1, y1 = site.bounds
    rd = lambda g: shp_t(lambda x, y, z=None: to_rd(x, y), shape(g))  #lon/lat -> RD
    titles = {"baseline": "Today", "scenario_a": "Scenario A: placed + kept", "scenario_b": "Scenario B: placed + kept"}
    for c, sc in enumerate(["baseline", "scenario_a", "scenario_b"]):
        ax = fig.add_subplot(gs[0, 2 * c:2 * c + 2])  #same width, same scale for all three
        for f in J(f"roads_{sc}.geojson")["features"]:  #the walk network the distances run on
            xy = np.array([to_rd(*q) for q in f["geometry"]["coordinates"]])
            ax.plot(*xy.T, color="#d3d1ca", lw=0.7, zorder=1)
        for f in massing["features"]:
            if f["properties"]["scenario"] == sc:
                g = rd(f["geometry"])
                for q in getattr(g, "geoms", [g]):
                    ax.fill(*q.exterior.xy, color="#c9c8c3", lw=0); ax.plot(*q.exterior.xy, color=INK2, lw=0.5)
        ax.plot(*site.exterior.xy, color=INK, lw=1)
        for k, (col, mk, lab) in TYPE_STYLE.items():
            mine = [f for f in feats if f["properties"]["scenario"] == sc and f["properties"]["type"] == k]
            for gone in (False, True):  #solid: stands in this scenario; hollow: today's, demolished in the options
                pts = [to_rd(*f["geometry"]["coordinates"]) for f in mine
                       if (f["properties"].get("status") == "demolished") == gone]
                if pts:
                    ax.scatter(*np.array(pts).T, s=170 if mk == "*" else 45, marker=mk, zorder=5, linewidths=1.2,
                               facecolors="none" if gone else col, edgecolors=col if gone else "white")
        ax.set_xlim(x0 - 10, x1 + 10); ax.set_ylim(y0 - 10, y1 + 10); ax.set_aspect("equal")
        ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
        for sp in ax.spines.values():
            sp.set_visible(False)
        n = {k: sum(1 for f in feats if f["properties"]["scenario"] == sc and f["properties"]["type"] == k) for k in TYPE_STYLE}
        ax.set_title(f"{titles[sc]}\n{n['shop']} shops, {n['health']} health, {n['education']} school"
                     f"{'s' if n['education'] != 1 else ''}, {n['community']} community halls", fontsize=11)  #the counts per map
    from matplotlib.lines import Line2D  #one legend for the three maps, off the maps
    handles = [Line2D([], [], ls="", marker=mk, markersize=11 if mk == "*" else 7, markerfacecolor=col,
                      markeredgecolor="white", label=lab) for col, mk, lab in TYPE_STYLE.values()]
    handles.append(Line2D([], [], ls="", marker="o", markersize=7, markerfacecolor="none", markeredgecolor=INK2,
                          label="hollow: today's, demolished in A and B"))
    fig.legend(handles=handles, loc="upper center", ncol=5, bbox_to_anchor=(0.5, 0.955), fontsize=10)
    res = json.loads((PROCESSED / "amenity_placement.json").read_text())
    for c, k in enumerate(["shop", "health", "education"]):
        ax = fig.add_subplot(gs[1, 2 * c:2 * c + 2])
        ax.xaxis.get_major_locator().set_params(integer=True)  #whole amenities only
        for sc in ["scenario_a", "scenario_b"]:
            r = res[sc][k]
            ax.plot(range(len(r["curve_m"])), r["curve_m"], color=COL[sc], lw=2, label=NAME[sc])
            ax.scatter([r["p"]], [r["J_after_m"]], color=COL[sc], zorder=4, s=30)  #the chosen number, after the swaps
            ax.scatter([r["p"]], [r["J_random_mean_m"]], color=COL[sc], marker="x", zorder=4, s=40)  #random placement, same number
        ax.axvline(res["scenario_a"][k]["p"], color=INK2, lw=0.8, ls="--")
        ax.set_ylim(0, None)
        ax.set_xlabel(f"{TYPE_STYLE[k][2]} placed in the new blocks")
        ax.set_ylabel("mean walk, every dwelling in the buurt (m)" if c == 0 else "")
        ax.set_title(f"{TYPE_STYLE[k][2].capitalize()}, as many as today = dashed line")
        if c == 0:
            ax.legend(fontsize=9, loc="upper right")
    fig.suptitle("Amenities on the site today and in each option. Shops, health care and the second school placed to "
                 "shorten walks (p-median); the kept block's school and halls stay where they are",
                 x=0.01, ha="left", fontweight="bold", fontsize=12)
    fig.tight_layout()
    save(fig, out)
    plt.close(fig)


def main() -> int:
    p, rp = PARAMS, rn.PARAMS
    print("Amenity placement on the new ground floors")
    dest, _, dwelling_m2 = rn.destinations()
    bud = budgets()
    print("  budgets (what the cleared ground holds today): "
          + ", ".join(f"{k} {v['p']} ({v['median_m2']:.0f} m2 each)" for k, v in bud.items()))
    out = {"_method": "p-median per type, greedy then vertex substitution, on the walk network of "
                      "road_network.py. See analysis/roads/place_amenities.py.",
           "_params": p, "budgets": bud,
           "baseline": {"today_with_own_amenities": today_with_own(dest, dwelling_m2, rp),  #the fair reference
                        "_note": "no new blocks today; these are today's walks with the site's own shops, health and schools"}}
    today = today_on_site()
    #today: every amenity on the site, marked kept or demolished in the options
    feats = [point_feature("baseline", r, rank=0, block=r["street"], status="kept" if r["kept"] else "demolished",
                           fixed=r["kept"]) for r in today]
    for case in CASES:  #one scenario per case
        out[case["scenario"]], f = run(case, p, dest, bud, dwelling_m2, rp)
        feats += f
        feats += [point_feature(case["scenario"], r, rank=0, block="kept community centre and school", status="kept",
                                fixed=True) for r in today if r["kept"]]  #the kept block's school and halls, never moved
    #how many of each type stand on the site: today, and each option (placed + kept)
    out["counts_on_site"] = {sc: {k: sum(1 for f in feats if f["properties"]["scenario"] == sc
                                         and f["properties"]["type"] == k) for k in SHOWN}
                             for sc in ["baseline"] + [c["scenario"] for c in CASES]}
    print("  amenities on the site: " + "; ".join(f"{sc} " + ", ".join(f"{k} {n}" for k, n in c.items())
                                                 for sc, c in out["counts_on_site"].items()))
    write_processed("amenity_placement.json", out)
    path = PROCESSED / "design_amenities.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "_written_by": "analysis/roads/place_amenities.py",
                                "features": feats}, separators=(",", ":")) + "\n")
    print(f"  wrote {path.relative_to(ROOT)} ({len(feats)} amenities)")
    figure("fig_amenities.png", feats)  #maps and diminishing returns
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
