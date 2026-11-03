#!/usr/bin/env python3
"""
edge_access.py - how far every address on the design site is from Lange
Hilleweg and Strevelsweg, on foot and by car, along the streets.

Component 4.8. Built 2026-10-27.

    python analysis/roads/edge_access.py                          #every case
    python analysis/roads/edge_access.py --scenario scenario_a    #only these
    python analysis/roads/edge_access.py --check                  #also verify against networkx

Needs road_network.py's cached walk network, fetches the OSM drive network into
cache/roads/ on first run. Writes data/processed/edge_access.json and
edge_access_<scenario>.geojson.

Targets are the network nodes of each edge street within 15 m of the site. The
walk uses road_network.py's network clipped to the site plus 15 m, so a walk
cannot go round the outside. The drive network keeps one-way streets and is not
clipped. A scenario gets the same street surgery minus the footpaths, its new
streets two-way unless CASES says otherwise, and a one-way dead end is made
two-way since a car turns round there. Origins are BAG dwellings, plus the new
blocks' entrances (drawn by the team, else one every 15 m along a street). An
address snaps to its own street if within 60 m. One Dijkstra per street and
mode on the reversed graph, so it is address to street.

Limits. No turns, traffic or parking, metres and not minutes. No separate
pavements, so crossing Strevelsweg is free. Entrances and car access of new
blocks are assumptions, written under "assumptions".
"""

import json
import pathlib
import sys
import unicodedata
import warnings

import numpy as np

warnings.filterwarnings("ignore")

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "scenarios"))
sys.path.insert(0, str(HERE))
import road_network as rn  #noqa: E402
from common.project import (PROCESSED, RAW, ROOT, STUDY_AREA, design_site_polygon,  #noqa: E402
                            study_area_polygon, to_rd, to_wgs)

DRIVE = rn.CACHE / "drive_osm.graphml"  #OSM drive network, buffered
OUT = PROCESSED / "edge_access.json"
ENTRANCES = PROCESSED / "design_entrances.geojson"  #drawn entrances of the new blocks, all scenarios

PARAMS = {
    "target_band_m": 15.0,  #a target-street node counts if it lies within this of the site outline
    "walk_band_m": 15.0,  #the walk network is clipped to the site + this
    "own_street_m": 60.0,  #an address snaps to its own street if a piece of it is this close
    "entrance_step_m": 15.0,  #automatic entrances: one per this many metres of street-facing wall
    "facade_street_m": 20.0,  #a wall point is street-facing if a street centreline is this close
    "entrance_block_m": 5.0,  #a drawn entrance belongs to the new block within this distance
    "oneway_match_m": 3.0,  #a new street piece is one-way if its midpoint lies this close to a drawn one-way line
    "near_m": [100, 200],  #reported shares within these distances
    "check_n": 60,  #origins per scenario, mode and street in the networkx check
}

TARGETS = {  #output key -> OSM / BAG street name
    "lange_hilleweg": "Lange Hilleweg",  #north-west edge
    "strevelsweg": "Strevelsweg",  #south edge
}
MODES = ("walk", "drive")

#Car access of each scenario's new streets, filled in by hand once the team decides it.
# car_free_rd: RD polygons (lists of (x, y)); a new street, link or connector whose midpoint
#              lies inside one is not driven. Hand-drawn footpaths are never driven.
# oneway_rd:   RD lines (lists of (x, y)) drawn in the direction of travel; a new street piece
#              whose midpoint lies within oneway_match_m of one is one-way that way.
#Left empty, every new street is a two-way car street, and the output says so.
CASES = {
    "baseline": {},
    "scenario_a": {"car_free_rd": [], "oneway_rd": []},
    "scenario_b": {"car_free_rd": [], "oneway_rd": []},
}


def norm(s):
    #street names compared without case or accent encoding differences
    return unicodedata.normalize("NFC", str(s)).casefold()


#--- inputs
def fetch_drive(refresh=False):
    #OSM drive network over the buurten + buffer, cached next to the walk network
    import osmnx as ox
    from shapely.ops import transform
    if DRIVE.exists() and not refresh:
        return
    rn.CACHE.mkdir(parents=True, exist_ok=True)
    poly = transform(lambda x, y, z=None: to_wgs(x, y), study_area_polygon().buffer(rn.PARAMS["buffer_m"]))
    print("  fetching the OSM drive network")
    ox.save_graphml(ox.graph_from_polygon(poly, network_type="drive", simplify=True), DRIVE)


def drive_edges():
    #the cached drive network as lines in RD, one per street piece, each with a oneway flag;
    #a one-way piece runs in the direction of travel
    import osmnx as ox
    G = ox.project_graph(ox.load_graphml(DRIVE), to_crs=28992)
    e = ox.graph_to_gdfs(G, nodes=False).reset_index()
    one = e["oneway"].astype(bool).to_numpy()
    u, v = e["u"].to_numpy(), e["v"].to_numpy()
    e = e[one | (u <= v)].copy()  #a two-way street is two directed edges in osmnx: keep one
    e["oneway"] = e["oneway"].astype(bool)
    e["highway"] = e["highway"].astype(str)
    e["name"] = e["name"].astype(str) if "name" in e else ""
    e["src"] = np.arange(len(e))  #original piece, to put a one-way piece back in its direction after cutting
    return e[["highway", "name", "oneway", "src", "geometry"]].reset_index(drop=True)


def orient_oneway(lines, orig):
    #cutting and splitting can flip a line; turn each one-way piece back the way its OSM street runs
    import shapely
    flips = 0
    geoms = list(lines.geometry.values)
    for k, (g, one, src) in enumerate(zip(geoms, lines["oneway"], lines["src"])):
        if not one or src != src:  #two-way, or a new street (src NaN)
            continue
        o = orig[int(src)]
        a, b = o.project(shapely.Point(g.coords[0])), o.project(shapely.Point(g.coords[-1]))
        if a > b + 1e-6:
            geoms[k] = shapely.reverse(g)
            flips += 1
    lines = lines.copy()
    lines["geometry"] = geoms
    return lines, flips


def lines_for(mode, scenario, case, notes):
    #street lines of one mode for the scenario, with columns kind and oneway
    import geopandas as gpd
    import shapely
    p = rn.PARAMS
    if mode == "walk":
        lines = rn.lines_for_scenario(rn.osm_edges(), scenario, p)
        lines["oneway"] = False
        area = design_site_polygon().buffer(PARAMS["walk_band_m"])
        lines["geometry"] = lines.geometry.intersection(area)  #walk on the site only
        lines = lines.explode(index_parts=False)
        lines = lines[lines.geometry.geom_type == "LineString"]
        lines = lines[lines.geometry.length > 0.05].reset_index(drop=True)
        return lines
    edges = drive_edges()
    orig = edges.geometry.values
    lines = rn.lines_for_scenario(edges, scenario, p)
    lines = lines[~lines["name"].astype(str).str.endswith(" path")]  #hand-drawn footpaths are not driven
    lines["oneway"] = lines["oneway"].fillna(False).astype(bool)
    lines, flips = orient_oneway(lines.reset_index(drop=True), orig)
    if flips:
        print(f"  drive: {flips} one-way pieces turned back to their direction of travel")
    if scenario == "baseline":
        return lines
    new = lines["kind"].isin(["new", "connector"]).to_numpy()
    mid = shapely.line_interpolate_point(lines.geometry.values, 0.5, normalized=True)
    free = [shapely.Polygon(r) for r in case.get("car_free_rd", [])]
    one = [shapely.LineString(r) for r in case.get("oneway_rd", [])]
    drop = new & np.array([any(f.contains(m) for f in free) for m in mid], bool) if free else np.zeros(len(lines), bool)
    geoms = list(lines.geometry.values)
    flags = lines["oneway"].to_numpy().copy()
    n_one = 0
    for k in np.flatnonzero(new & ~drop):
        for o in one:
            if o.distance(mid[k]) <= PARAMS["oneway_match_m"]:
                g = geoms[k]
                if o.project(shapely.Point(g.coords[0])) > o.project(shapely.Point(g.coords[-1])):
                    geoms[k] = shapely.reverse(g)  #drawn direction is the direction of travel
                flags[k] = True
                n_one += 1
                break
    lines = lines.copy()
    lines["geometry"], lines["oneway"] = geoms, flags
    lines = lines[~drop].reset_index(drop=True)
    print(f"  drive {scenario}: {int(drop.sum())} new pieces car-free, {n_one} one-way")
    if not free and not one:
        notes.append("No car access drawn for this scenario's new streets (CASES in edge_access.py): every "
                     "new street, street link and connector is taken as a two-way car street.")
    return gpd.GeoDataFrame(lines, crs=28992)


#--- origins
def blocks_for(scenario, dwelling_m2):
    #the scenario's new blocks merged per building (a stepped tower comes as parts), with estimated dwellings
    import geopandas as gpd
    from scenario_world import load_scenario
    new, _ = load_scenario(scenario)
    p = rn.PARAMS
    storeys = np.maximum(1, np.round(new["height_m"].to_numpy() / p["storey_m"]))
    new["dwellings"] = new.geometry.area.to_numpy() * storeys * p["net_to_gross"] / dwelling_m2  #road_network.py's estimate
    new["block"] = new["name"].astype(str).str.replace(r" part \d+$", "", regex=True)
    b = new.dissolve(by="block", aggfunc={"dwellings": "sum"}).reset_index()
    return gpd.GeoDataFrame(b[["block", "dwellings"]], geometry=b.geometry.values, crs=28992)


def drawn_entrances(scenario):
    #entrance points the team drew for the scenario (RD), [] if the file is a stub or has none
    import shapely
    if not ENTRANCES.exists():
        return []
    d = json.loads(ENTRANCES.read_text())
    if d.get("_status") == "not_computed_yet":
        return []
    out = []
    for f in d.get("features", []):
        if f["properties"].get("scenario") != scenario or f["geometry"]["type"] != "Point":
            continue
        x, y = to_rd(*f["geometry"]["coordinates"][:2])
        out.append((shapely.Point(x, y), f["properties"].get("dwellings")))
    return out


def auto_entrances(poly, streets, step, reach):
    #points along the block's walls that face a street, one per `step` m; at least one
    import shapely
    ring = shapely.LineString(poly.exterior.coords) if poly.geom_type == "Polygon" \
        else shapely.LineString(max(poly.geoms, key=lambda g: g.area).exterior.coords)
    n = max(1, int(ring.length // step))
    pts = [ring.interpolate((k + 0.5) * ring.length / n) for k in range(n)]
    d = np.array([streets.distance(q) for q in pts])  #to the nearest street centreline
    keep = [q for q, dk in zip(pts, d) if dk <= reach]
    return keep or [pts[int(np.argmin(d))]]


def origins_for(scenario, dwelling_m2, notes):
    #(GeoDataFrame RD with w, street, label, new) of the addresses on the site in the scenario
    import geopandas as gpd
    import pandas as pd
    import shapely
    site = design_site_polygon()
    bag = gpd.read_file(RAW / "bag_verblijfsobjecten.geojson").to_crs(28992)
    bag = bag[bag["gebruiksdoel"].fillna("").str.contains("woonfunctie") & bag.within(site)]
    o = gpd.GeoDataFrame({"w": 1.0, "street": bag["street"].fillna("").astype(str).values,
                          "label": bag["street"].fillna("").astype(str).values, "new": False},
                         geometry=bag.geometry.values, crs=28992)  #one BAG address = one dwelling
    if scenario == "baseline":
        return o.reset_index(drop=True), {"bag_dwellings": len(o)}
    from scenario_world import load_scenario
    _, gone = load_scenario(scenario)
    gone = {g.rsplit(".", 1)[-1] for g in gone}  #NL.IMBAG.Pand.<id> -> <id>, BAG's pand_id
    kept = ~bag["pand_id"].astype(str).isin(gone).to_numpy()
    o = o[kept]
    blocks = blocks_for(scenario, dwelling_m2)
    walk_lines = shapely.union_all(rn.lines_for_scenario(rn.osm_edges(), scenario, rn.PARAMS).geometry.values)
    drawn = drawn_entrances(scenario)
    rows, n_drawn, n_auto, auto_blocks = [], 0, 0, []
    owner = [int(np.argmin([b.distance(q) for b in blocks.geometry])) for q, _ in drawn]
    for k, b in blocks.iterrows():
        mine = [(q, dw) for (q, dw), j in zip(drawn, owner)
                if j == k and b.geometry.distance(q) <= PARAMS["entrance_block_m"]]
        if mine:
            pts = [q for q, _ in mine]
            fixed = [dw for _, dw in mine]
            n_drawn += len(pts)
        else:
            pts = auto_entrances(b.geometry, walk_lines, PARAMS["entrance_step_m"], PARAMS["facade_street_m"])
            fixed = [None] * len(pts)
            n_auto += len(pts)
            auto_blocks.append(b["block"])
        #drawn dwellings per entrance win; the rest of the estimate is shared over the others
        given = sum(f for f in fixed if f is not None)
        free = [f is None for f in fixed]
        each = max(0.0, b["dwellings"] - given) / max(1, sum(free))
        for q, f in zip(pts, fixed):
            rows.append({"w": float(f) if f is not None else each, "street": "", "label": b["block"],
                         "new": True, "geometry": q})
    stray = sum(1 for (q, _), j in zip(drawn, owner) if blocks.geometry[j].distance(q) > PARAMS["entrance_block_m"])
    if stray:
        notes.append(f"{stray} drawn entrances lie more than {PARAMS['entrance_block_m']:.0f} m from any new block "
                     "and were ignored.")
    if auto_blocks:
        notes.append(f"{len(auto_blocks)} of {len(blocks)} new blocks have no drawn entrances "
                     f"(data/processed/design_entrances.geojson): they got one every "
                     f"{PARAMS['entrance_step_m']:.0f} m along walls within {PARAMS['facade_street_m']:.0f} m "
                     f"of a street, {n_auto} in all.")
    new = gpd.GeoDataFrame(rows, crs=28992)
    print(f"  {scenario}: {int(kept.sum())} BAG dwellings kept, {blocks['dwellings'].sum():.0f} estimated in "
          f"{len(blocks)} new blocks at {n_drawn} drawn + {n_auto} automatic entrances")
    info = {"bag_dwellings": int(kept.sum()), "new_block_dwellings_est": round(float(blocks["dwellings"].sum())),
            "new_blocks": len(blocks), "entrances_drawn": n_drawn, "entrances_auto": n_auto}
    return gpd.GeoDataFrame(pd.concat([o, new], ignore_index=True), crs=28992), info


#--- routing
def snap_named(net, pts, streets):
    #points -> (edge index, distance along it, access distance), on the point's own street where possible
    import shapely
    geoms = net["lines"].geometry.values
    names = np.array([norm(n) for n in net["lines"]["name"]])
    idx = shapely.STRtree(geoms).query_nearest(pts, all_matches=False)[1]  #fallback: any street
    own = 0
    for s in set(streets):
        if not s:
            continue
        cand = np.flatnonzero(np.char.find(names.astype(str), norm(s)) >= 0)
        if not len(cand):
            continue
        sel = np.flatnonzero(np.asarray(streets) == s)
        j = shapely.STRtree(geoms[cand]).query_nearest(pts[sel], all_matches=False)[1]
        ok = shapely.distance(geoms[cand[j]], pts[sel]) <= PARAMS["own_street_m"]
        idx[sel[ok]] = cand[j[ok]]
        own += int(ok.sum())
    t = shapely.line_locate_point(geoms[idx], pts)
    acc = shapely.distance(geoms[idx], pts)
    return (idx, t, acc), own


def adjacency(net):
    #directed adjacency (shortest length per node pair), one extra node for the super-source
    n = len(net["xy"]) + 1
    ij, L = net["ij"], net["L"]
    two = ~net["lines"]["oneway"].to_numpy(bool)
    r = np.r_[ij[:, 0], ij[two, 1]]
    c = np.r_[ij[:, 1], ij[two, 0]]
    return rn.min_csr(r, c, np.r_[L, L[two]], (n, n))


def relax_traps(net):
    #one-way pieces that lead into a dead end with no way out become two-way: a car turns round there.
    #The design cuts old one-way streets short (Oudelandstraat, Dubbelstraat), and the network is cut off at
    #the edge of the fetched area; without this, an entrance on such a stub could reach nothing (2026-10-27)
    from scipy.sparse.csgraph import connected_components
    one = net["lines"]["oneway"].to_numpy(bool).copy()
    ij = net["ij"]
    relaxed = 0
    for _ in range(20):
        net["lines"]["oneway"] = one
        A = adjacency(net)[:-1, :-1].tocoo()
        nc, lab = connected_components(A, directed=True, connection="strong")
        leaves = np.zeros(nc, bool)
        cross = lab[A.row] != lab[A.col]
        leaves[lab[A.row[cross]]] = True  #a component with a link to another one has a way out
        sinks = np.flatnonzero(~leaves)
        if len(sinks) <= 1:
            break
        main = sinks[np.argmax([np.sum(lab == s) for s in sinks])]  #the network itself
        trap = np.isin(lab, sinks[sinks != main])
        flip = one & (trap[ij[:, 0]] | trap[ij[:, 1]])
        if not flip.any():
            break
        one[flip] = False
        relaxed += int(flip.sum())
    net["lines"]["oneway"] = one
    return relaxed


def target_of(net, street):
    #(target node ids, target edge mask) of the street's stretch along the site
    import shapely
    band = design_site_polygon().buffer(PARAMS["target_band_m"])
    names = np.array([norm(n) for n in net["lines"]["name"]])
    on = np.char.find(names.astype(str), norm(street)) >= 0
    inband = shapely.within(shapely.points(net["xy"]), band)
    ij = net["ij"]
    edge = on & (inband[ij[:, 0]] | inband[ij[:, 1]])
    nodes = np.unique(np.r_[ij[edge, 0][inband[ij[edge, 0]]], ij[edge, 1][inband[ij[edge, 1]]]])
    return nodes, edge


def dist_to(net, A, nodes):
    #network distance from every node TO the nearest target node: Dijkstra on the reversed graph
    import scipy.sparse as sp
    from scipy.sparse.csgraph import dijkstra
    n = A.shape[0] - 1
    S = sp.csr_matrix((np.full(len(nodes), 1e-9), (np.full(len(nodes), n), nodes)), shape=A.shape)
    return dijkstra(A.T.tocsr() + S, directed=True, indices=n)[:n]


def at_points(net, D, snapped, tedge, mode):
    #node distances -> distance from each snapped point; 0 m by network on the target street itself
    import shapely
    idx, t, acc = snapped
    i, j = net["ij"][idx, 0], net["ij"][idx, 1]
    L = net["L"][idx]
    one = net["lines"]["oneway"].to_numpy(bool)[idx]
    fwd = L - t + D[j]  #along the piece to its end node
    back = np.where(one, np.inf, t + D[i])  #against a one-way piece: not by car
    d = np.minimum(fwd, back)
    band = design_site_polygon().buffer(PARAMS["target_band_m"])
    on = tedge[idx] & shapely.within(shapely.line_interpolate_point(net["lines"].geometry.values[idx], t), band)
    d = np.where(on, 0.0, d)
    return d + (acc if mode == "walk" else 0.0)


def straight_to(net, tedge, pts):
    #straight-line distance from each point to the street's stretch along the site
    import shapely
    band = design_site_polygon().buffer(PARAMS["target_band_m"])
    g = shapely.union_all(net["lines"].geometry.values[tedge]).intersection(band)
    return shapely.distance(g, pts)


#--- metrics
def wquantile(d, w, q):
    o = np.argsort(d)
    cw = np.cumsum(w[o])
    return float(d[o][np.searchsorted(cw, q * cw[-1])])


def summary(d, w, straight, nearer):
    #dwelling-weighted statistics of one street's distances
    ok = np.isfinite(d)
    out = {"dwellings": round(float(w.sum())), "unreachable_dwellings": round(float(w[~ok].sum()))}
    if not ok.any():
        return out
    d, w, s, nr = d[ok], w[ok], straight[ok], nearer[ok]
    out.update({
        "mean_m": round(float(np.average(d, weights=w)), 1),
        "median_m": round(wquantile(d, w, 0.5), 1),
        "p90_m": round(wquantile(d, w, 0.9), 1),
        "max_m": round(float(d.max()), 1),
        **{f"within_{m}m_frac": round(float(np.average(d <= m, weights=w)), 3) for m in PARAMS["near_m"]},
        "straight_median_m": round(wquantile(s, w, 0.5), 1),
        "nearer_frac": round(float(np.average(nr, weights=w)), 3),  #share for which this is the nearer of the two
    })
    return out


def check(net, A, snapped, tnodes, tedge, mode, got, n):
    #independent check with networkx on a sample of origins; returns the largest difference in m
    import networkx as nx
    import shapely
    rng = np.random.default_rng(0)
    idx, t, acc = snapped
    g = nx.DiGraph()
    A = A.tocoo()
    for r, c, w in zip(A.row, A.col, A.data):
        g.add_edge(int(r), int(c), weight=float(w))
    for k in tnodes:
        g.add_edge(int(k), "T", weight=0.0)
    band = design_site_polygon().buffer(PARAMS["target_band_m"])
    worst = 0.0
    for k in rng.choice(len(idx), size=min(n, len(idx)), replace=False):
        e = idx[k]
        i, j, L = int(net["ij"][e, 0]), int(net["ij"][e, 1]), float(net["L"][e])
        q = shapely.line_interpolate_point(net["lines"].geometry.values[e], t[k])
        if tedge[e] and band.contains(q):
            want = 0.0
        else:
            h = g.copy()
            h.add_edge("o", j, weight=L - t[k])
            if not net["lines"]["oneway"].iloc[e]:
                h.add_edge("o", i, weight=t[k])
            try:
                want = nx.shortest_path_length(h, "o", "T", weight="weight")
            except nx.NetworkXNoPath:
                want = np.inf
        want += acc[k] if mode == "walk" else 0.0
        if np.isfinite(want) or np.isfinite(got[k]):
            worst = max(worst, abs(want - got[k]) if np.isfinite(want) and np.isfinite(got[k]) else np.inf)
    return worst


#--- run
def run(scenario, dwelling_m2, do_check):
    print(f"\n{scenario}")
    notes = []
    case = CASES[scenario]
    o, info = origins_for(scenario, dwelling_m2, notes)
    pts = o.geometry.values
    grid = rn.site_grid(rn.PARAMS)
    gpts = grid.geometry.values
    res = {"origins": info, "assumptions": notes, "network": {}, "dwellings": {}, "site_grid": {}, "check_max_diff_m": {}}
    cols = {}
    for mode in MODES:
        net = rn.build_graph(lines_for(mode, scenario, case, notes))
        relaxed = relax_traps(net) if mode == "drive" else 0
        if relaxed:
            print(f"  drive: {relaxed} one-way pieces in dead-end traps made two-way")
        A = adjacency(net)
        snapped, own = snap_named(net, pts, o["street"].tolist())
        gsn, _ = snap_named(net, gpts, [""] * len(gpts))
        res["network"][mode] = {"edges": int(len(net["L"])), "length_km": round(float(net["L"].sum() / 1000), 2),
                                "oneway_edges": int(net["lines"]["oneway"].sum()),
                                "oneway_trap_edges_made_two_way": relaxed,
                                "addresses_on_own_street_frac": round(own / max(1, int((o["street"] != "").sum())), 3)}
        d, s, dg, sg = {}, {}, {}, {}
        for key, street in TARGETS.items():
            tnodes, tedge = target_of(net, street)
            if not len(tnodes):
                sys.exit(f"No {mode} network nodes on {street} along the site: check TARGETS and the OSM names.")
            D = dist_to(net, A, tnodes)
            d[key], s[key] = at_points(net, D, snapped, tedge, mode), straight_to(net, tedge, pts)
            dg[key], sg[key] = at_points(net, D, gsn, tedge, mode), straight_to(net, tedge, gpts)
            res["network"][mode][f"{key}_target_nodes"] = int(len(tnodes))
            if do_check:
                res["check_max_diff_m"][f"{mode}_{key}"] = round(check(net, A, snapped, tnodes, tedge, mode,
                                                                       d[key], PARAMS["check_n"]), 6)
        k1, k2 = TARGETS
        res["dwellings"][mode] = {k: summary(d[k], o["w"].to_numpy(), s[k],
                                             d[k] < d[k2 if k == k1 else k1]) for k in TARGETS}
        res["site_grid"][mode] = {k: summary(dg[k], np.ones(len(gpts)), sg[k],
                                             dg[k] < dg[k2 if k == k1 else k1]) for k in TARGETS}
        for k in TARGETS:
            cols[f"{mode}_{k}_m"] = d[k]
            a = res["dwellings"][mode][k]
            print(f"  {mode:5s} to {TARGETS[k]:15s} median {a.get('median_m', '-')} m, p90 {a.get('p90_m', '-')} m, "
                  f"max {a.get('max_m', '-')} m, unreachable {a['unreachable_dwellings']} dwellings")
    res["site_grid"]["points"] = len(gpts)
    if not do_check:
        res.pop("check_max_diff_m")
    else:
        print("  networkx check, largest difference: " + ", ".join(f"{k} {v} m" for k, v in res["check_max_diff_m"].items()))
    res["geojson"] = f"../data/processed/edge_access_{scenario}.geojson"
    write_points(o, cols, scenario)
    return res


def write_points(o, cols, scenario):
    #one point per address location (dwellings at one point summed), WGS84, for the app
    from collections import OrderedDict
    groups = OrderedDict()
    for k, (g, w, street, label, new) in enumerate(zip(o.geometry, o["w"], o["street"], o["label"], o["new"])):
        key = (round(g.x, 1), round(g.y, 1), label)
        if key not in groups:
            groups[key] = {"w": 0.0, "k": k, "label": label, "new": bool(new)}
        groups[key]["w"] += float(w)
    feats = []
    for (x, y, _), v in groups.items():
        lon, lat = to_wgs(x, y)
        props = {"dwellings": round(v["w"], 1), "label": v["label"], "new": v["new"]}
        for c, arr in cols.items():
            val = arr[v["k"]]
            props[c] = round(float(val), 1) if np.isfinite(val) else None
        feats.append({"type": "Feature", "properties": props,
                      "geometry": {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]}})
    path = PROCESSED / f"edge_access_{scenario}.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":"),
                               ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  wrote {path.relative_to(ROOT)} ({len(feats)} points)")


def main():
    only = sys.argv[sys.argv.index("--scenario") + 1:] if "--scenario" in sys.argv else list(CASES)  #run only these cases
    refresh = "--refresh" in sys.argv  #re-fetch the OSM drive network
    check = "--check" in sys.argv  #verify a sample against networkx
    print(f"Distance to the edge streets: {STUDY_AREA.name}, design site")
    if not rn.WALK.exists():
        sys.exit("No cached walk network: run analysis/roads/road_network.py first.")
    fetch_drive(refresh)
    _, _, dwelling_m2 = rn.destinations()
    out = json.loads(OUT.read_text()) if OUT.exists() else {}
    out.update({
        "study_area": STUDY_AREA.name,
        "_method": "Network distance from each address on the design site to the stretch of Lange Hilleweg "
                   "and of Strevelsweg along the site. Walk: OSM walk network clipped to the site + 15 m, "
                   "access leg included. Drive: OSM drive network with one-way streets, from the point on the "
                   "street. Dijkstra from a super-source on the reversed graph. See analysis/roads/edge_access.py.",
        "_params": PARAMS,
        "targets": TARGETS,
    })
    for sc in CASES:
        out.setdefault(sc, {"_status": "not_computed_yet"})
    for sc in CASES:
        if sc in only:
            out[sc] = run(sc, dwelling_m2, check)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
