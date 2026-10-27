#!/usr/bin/env python3
"""
road_network.py — the walking network per scenario, its structure and how far
homes are from everyday destinations.

Component 4.8. Built 2026-10-21.

USAGE
-----
    python analysis/roads/road_network.py               # every case in CASES
    python analysis/roads/road_network.py --refresh     # re-fetch the OSM network and stops

The first run fetches the OSM walk network and the public-transport stops
(about three minutes) into cache/roads/ (gitignored).

METHOD
------
  network   OSM walk network (osmnx network_type="walk": streets, footways,
            paths, pedestrian areas), fetched over the two buurten plus a
            500 m buffer so betweenness and distances near the edge see the
            streets beyond it. Undirected, edge weight = length in RD.
  scenario  streets_for_scenario() (analysis/scenarios/scenario_world.py)
            cuts the old streets out of the site interior and adds centrelines
            of the new street surfaces. Those surfaces stop short of the edge
            streets in places, so every free end of a new centreline is joined
            to the nearest other street by a straight connector if one is
            within 35 m and the connector crosses no new block. The connectors
            are an assumption that the design's streets meet the edge streets.
            Then every crossing or touch between a scenario street and any
            other street becomes a junction (OSM's own crossings are left
            alone: those are mostly bridges), and an old street end within
            5 m of a new street, or a new end within 5 m of an old street,
            is joined to it. Graph nodes closer than 0.5 m are one junction.
            Without these the graph had streets that cross on the map but not
            in the network, and the footpath optimiser picked links that only
            repaired them (fixed 2026-10-23).
  homes     BAG addresses with woonfunctie inside the buurten or the site, one
            per dwelling. A scenario drops the addresses in demolished
            buildings and adds the new blocks' dwellings, estimated as
            footprint x storeys (height / 3 m) x 0.8 net/gross / the median
            BAG dwelling size on the site today, placed at the block centroid.
  dest.     shops (BAG winkelfunctie), education (onderwijsfunctie), health
            care (gezondheidszorgfunctie) and rail stops (OSM tram, metro and
            train stops). THE SAME SET IN EVERY SCENARIO: destinations on
            ground a scenario clears are left out of all of them, so a
            difference between scenarios is the network and the homes, not
            shops the design removes. How many that ground holds today is
            reported. Buildings a scenario keeps stay destinations.
  distance  each home and destination is snapped to the nearest point on the
            nearest edge. Walking distance = access to the edge + network
            distance, by Dijkstra from all destinations of a type at once.

Metrics, per area (each buurt, both together, the design site). An edge
belongs to an area if its midpoint lies in it, a node if it lies in it, so
numerator and denominator share one polygon (CLAUDE.md rule 5).

  n_nodes, n_edges           graph nodes and edges in the area
  avg_street_length_m        mean edge length
  intersection_density_km2   nodes joining 3+ streets, per km2 of the area
  circuity                   total edge length / total straight end-to-end length
  betweenness_max            highest edge betweenness in the area (exact,
                             length-weighted, normalised, over the whole
                             buffered network)
  walk_15min_reach_frac      share of homes with all four destination types
                             within 15 min walk (1,200 m at 4.8 km/h)

WHAT IT CANNOT TELL YOU
-----------------------
* OSM's walk network is only as complete as OSM. Pavements are mostly not
  mapped separately here, so the street centreline stands for both pavements.
* Destinations come from BAG over the study bounding box only. Homes near the
  outer edge have shops just outside it that are not counted, so their
  distances are too long. Equal in every scenario.
* BAG says what a building is registered for, not whether a shop is open.
* The new blocks' dwelling count is an estimate, and every dwelling of a block
  sits at its centroid.
* Betweenness weights every pair of nodes equally. It is a measure of network
  position, not a traffic forecast.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore")

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "scenarios"))
from common.project import (PROCESSED, RAW, ROOT, STUDY_AREA, buurt_polygons,  # noqa: E402
                            design_site_polygon, study_area_polygon, to_rd, to_wgs, write_processed)

CACHE = ROOT / "cache" / "roads"  #gitignored

PARAMS = {
    "buffer_m": 500,  #network fetched this far beyond the buurten
    "snap_tol_m": 35.0,  #free ends of new streets joined to a street this close
    "join_tol_m": 5.0,  #an old street end this close to a new street (or the reverse) is joined to it
    "node_tol_m": 0.5,  #graph nodes closer than this are one junction
    "walk_m_per_min": 80.0,  #4.8 km/h
    "reach_min": 15,  #the 15-minute walk
    "near_min": 5,  #a short walk, 400 m: every home reaches everything within 15 min, so this is what varies
    "grid_m": 20.0,  #spacing of the fixed origin grid over the design site
    "storey_m": 3.0,  #storey height for the new blocks' dwelling estimate
    "net_to_gross": 0.8,  #usable floor area / gross floor area, assumed
}

def extent_key(buffer_m):
    #short key of the area the OSM cache covers: a changed study area gets a fresh download, not the old network
    import hashlib
    b = study_area_polygon().buffer(buffer_m).bounds
    return hashlib.sha1(",".join(f"{v:.0f}" for v in b).encode()).hexdigest()[:8]


WALK = CACHE / f"walk_osm_{extent_key(PARAMS['buffer_m'])}.graphml"  #OSM walk network, buffered, for this study area
STOPS = CACHE / f"pt_stops_{extent_key(PARAMS['buffer_m'])}.geojson"  #OSM public-transport stops, same area

DEST = {  #destination type -> BAG gebruiksdoel, or "rail" for OSM stops
    "shop": "winkelfunctie",
    "education": "onderwijsfunctie",
    "health": "gezondheidszorgfunctie",
    "rail_stop": "rail",
}

CASES = [
    {"scenario": "baseline"},
    {"scenario": "scenario_a"},
    {"scenario": "scenario_b"},  #OPTION 2, imported 2026-10-23
]


# ------------------------------------------------------------------- inputs
def fetch(p, refresh=False):
    #OSM walk network and stops over the buurten + buffer, cached in cache/roads/
    import osmnx as ox
    from shapely.ops import transform
    CACHE.mkdir(parents=True, exist_ok=True)
    poly = transform(lambda x, y, z=None: to_wgs(x, y), study_area_polygon().buffer(p["buffer_m"]))
    if refresh or not WALK.exists():
        print("  fetching the OSM walk network (about two minutes)")
        ox.save_graphml(ox.graph_from_polygon(poly, network_type="walk", simplify=True), WALK)
    if refresh or not STOPS.exists():
        print("  fetching OSM public-transport stops")
        tags = {"railway": ["tram_stop", "station", "subway_entrance"], "highway": "bus_stop",
                "public_transport": "stop_position"}
        g = ox.features_from_polygon(poly, tags).reset_index()
        for c in g.columns:
            if c != "geometry":
                g[c] = g[c].astype(str)  #OSM columns can hold lists, GeoJSON cannot
        g.to_file(STOPS, driver="GeoJSON")


def osm_edges():
    #the cached walk network as undirected edge lines in RD
    import osmnx as ox
    G = ox.convert.to_undirected(ox.project_graph(ox.load_graphml(WALK), to_crs=28992))
    e = ox.graph_to_gdfs(G, nodes=False).reset_index()
    e["highway"] = e["highway"].astype(str)
    e["name"] = e["name"].astype(str) if "name" in e else ""
    return e[["highway", "name", "geometry"]]


def destinations():
    #destination points (RD) per type; everything on ground a scenario clears left out
    import geopandas as gpd
    from shapely.ops import unary_union
    from scenario_world import cleared_area
    site = unary_union([cleared_area(c["scenario"]) for c in CASES if c["scenario"] != "baseline"])  #kept buildings stay destinations
    bag = gpd.read_file(RAW / "bag_verblijfsobjecten.geojson").to_crs(28992)
    bag = bag[bag["gebruiksdoel"].notna()]
    on_site = bag.within(site)
    stops = gpd.read_file(STOPS).to_crs(28992)
    col = lambda c: stops[c] if c in stops else ""  #a tag no stop carries is not a column
    rail = stops[col("railway").isin(["tram_stop", "station", "stop"]) | (col("tram") == "yes")
                 | (col("subway") == "yes") | (col("train") == "yes")]
    rail = rail[col("highway")[rail.index] != "bus_stop"] if "highway" in stops else rail  #bus platforms tagged tram=yes are not rail
    rail = rail.set_geometry(rail.geometry.centroid)  #platforms can be lines or areas
    out, removed = {}, {}
    for k, doel in DEST.items():
        if doel == "rail":
            pts = rail
        else:
            pts = bag[bag["gebruiksdoel"].str.contains(doel)]  #gebruiksdoel can be comma-separated
        inside = pts.within(site)
        out[k] = pts[~inside].geometry.reset_index(drop=True)
        removed[k] = int(inside.sum())  #what the site holds today
    print("  destinations " + ", ".join(f"{k} {len(v)}" for k, v in out.items())
          + " (site excluded: " + ", ".join(f"{k} {v}" for k, v in removed.items()) + ")")
    return out, removed, float(bag[on_site & bag["gebruiksdoel"].str.contains("woonfunctie")]["area_m2"].median())


def dest_with_amenities(dest, scenario):
    #destinations as the scenario is lived: today with its own site amenities, an option with those placed on its
    #ground floors by place_amenities.py; None if that has not run
    import geopandas as gpd
    from shapely.geometry import Point
    path = PROCESSED / "design_amenities.geojson"
    if not path.exists():
        return None
    want = "demolished" if scenario == "baseline" else "placed"  #today's own on cleared ground / the option's placed ones
    feats = [f for f in json.loads(path.read_text())["features"]
             if f["properties"]["scenario"] == scenario and f["properties"].get("status") == want]
    out = {}
    for k, pts in dest.items():
        add = [Point(*to_rd(*f["geometry"]["coordinates"])) for f in feats if f["properties"]["type"] == k]
        out[k] = gpd.GeoSeries(list(pts.values) + add, crs=28992) if add else pts  #the kept block is already in dest
    return out


def homes_for_scenario(scenario, dwelling_m2, p):
    #dwellings as (points RD, weight, on-site flag, new-block flag) for the scenario
    import geopandas as gpd
    import pandas as pd
    from scenario_world import load_scenario
    site = design_site_polygon()
    bag = gpd.read_file(RAW / "bag_verblijfsobjecten.geojson").to_crs(28992)
    bag = bag[bag["gebruiksdoel"].fillna("").str.contains("woonfunctie")]
    bag = bag[bag.within(study_area_polygon().union(site))]  #the buurten, plus the site's part south of them
    h = gpd.GeoDataFrame({"w": np.ones(len(bag)), "new": np.zeros(len(bag), bool)},
                         geometry=bag.geometry.values, crs=28992)  #one BAG address = one dwelling
    if scenario != "baseline":
        new, gone = load_scenario(scenario)
        gone = {g.rsplit(".", 1)[-1] for g in gone}  #NL.IMBAG.Pand.<id> -> <id>, BAG's pand_id
        h = h[~bag["pand_id"].astype(str).isin(gone).values]
        storeys = np.maximum(1, np.round(new["height_m"].to_numpy() / p["storey_m"]))
        n = new.geometry.area.to_numpy() * storeys * p["net_to_gross"] / dwelling_m2  #estimated dwellings per block
        nb = gpd.GeoDataFrame({"w": n, "new": True}, geometry=new.geometry.centroid.values, crs=28992)
        print(f"  {scenario}: {len(bag) - len(h)} dwellings demolished, {n.sum():.0f} estimated in "
              f"{len(new)} new blocks ({dwelling_m2:.0f} m2 each)")
        h = gpd.GeoDataFrame(pd.concat([h, nb], ignore_index=True), crs=28992)
    h["site"] = h.within(site)
    return h.reset_index(drop=True)


# ------------------------------------------------------------------ network
def lines_for_scenario(edges, scenario, p):
    #edge lines for the scenario, with connectors joining the new streets' free ends to the network
    import geopandas as gpd
    import pandas as pd
    import shapely
    from scenario_world import load_scenario, streets_for_scenario
    s = streets_for_scenario(edges, scenario, paths=True).explode(index_parts=False).reset_index(drop=True)  #with hand-drawn paths
    s["kind"] = np.where(s["name"].astype(str).str.endswith(("new street", " path", " link")), "new", "osm")  #design streets, paths, links
    if scenario == "baseline":
        return s
    blocks = shapely.union_all(load_scenario(scenario)[0].geometry.values).buffer(-0.5)  #a connector may touch a wall
    key = lambda c: (round(c[0], 1), round(c[1], 1))  #end points shared by two lines are a junction
    link = s["name"].astype(str).str.endswith(" link").to_numpy()  #link axes do not make a street end a junction
    ends = pd.Series([key(g.coords[k]) for g, lk in zip(s.geometry, link) if not lk for k in (0, -1)]).value_counts()
    tree = shapely.STRtree(s.geometry.values)
    cuts = {}  #line index -> distances along it where a connector lands
    conn = []
    for i, g in enumerate(s.geometry):
        if s.at[i, "kind"] != "new" or link[i]:
            continue  #free ends of the design's own streets only; a link axis already ends on its edge street
        for k in (0, -1):
            c = g.coords[k]
            if ends[key(c)] > 1:
                continue  #already a junction
            pt = shapely.Point(c)
            cand = [j for j in tree.query(pt.buffer(p["snap_tol_m"])) if j != i and not link[j]]  #not its own link axis
            if not cand:
                continue
            j = min(cand, key=lambda j: s.geometry[j].distance(pt))
            if s.geometry[j].distance(pt) < 0.05:
                continue  #already on a street (a link axis ends on its edge street): node_scenario_lines joins it
            d = s.geometry[j].project(pt)
            q = s.geometry[j].interpolate(d)
            seg = shapely.LineString([c, q.coords[0]])
            if seg.length > p["snap_tol_m"] or seg.intersects(blocks):
                continue  #too far, or through a new block: stays a dead end
            cuts.setdefault(j, []).append(d)
            conn.append(seg)
    #split each target line where connectors land, so they share a node
    from shapely.ops import substring
    rows = []
    for i, g in enumerate(s.geometry):
        ds = sorted(set([0.0] + [d for d in cuts.get(i, []) if 0.05 < d < g.length - 0.05] + [g.length]))
        for a, b in zip(ds[:-1], ds[1:]):
            rows.append({**s.iloc[i].drop("geometry").to_dict(), "geometry": substring(g, a, b)})
    rows += [{"highway": "connector", "name": f"{scenario} connector", "kind": "connector", "geometry": g}
             for g in conn]
    out = gpd.GeoDataFrame(rows, crs=s.crs)
    print(f"  {scenario}: {len(conn)} connectors, {sum(g.length for g in conn):.0f} m, join the new streets' free ends")
    return node_scenario_lines(out, blocks, scenario, p)


def split_at(g, ds):
    #line -> pieces cut at the given distances along it
    from shapely.ops import substring
    ds = sorted(set([0.0] + [d for d in ds if 0.05 < d < g.length - 0.05] + [g.length]))
    return [substring(g, a, b) for a, b in zip(ds[:-1], ds[1:])]


def node_scenario_lines(lines, blocks, scenario, p):
    #make every meeting of a scenario street with another street a junction:
    #1 crossings and touches in a line's interior, 2 ends that stop just short of the other family's street
    import geopandas as gpd
    import shapely
    geoms = list(lines.geometry.values)
    old = (lines["kind"] == "osm").to_numpy()
    site = design_site_polygon().buffer(25)  #the design and the edge streets round it
    tree = shapely.STRtree(geoms)
    cuts, joins = {}, []
    #1 crossings: split both lines where a scenario line meets another one away from shared ends
    n_cross = 0
    for i, j in zip(*tree.query(geoms, predicate="intersects")):
        if i >= j or (old[i] and old[j]):
            continue  #OSM against OSM: a crossing with no node there is a bridge or tunnel
        x = geoms[i].intersection(geoms[j])
        pts = [q for q in getattr(x, "geoms", [x]) if q.geom_type == "Point"]
        pts += [shapely.Point(c) for q in getattr(x, "geoms", [x]) if q.geom_type == "LineString" for c in (q.coords[0], q.coords[-1])]  #overlap: its two ends
        for q in pts:
            di, dj = geoms[i].project(q), geoms[j].project(q)
            inner_i = 0.05 < di < geoms[i].length - 0.05
            inner_j = 0.05 < dj < geoms[j].length - 0.05
            if inner_i or inner_j:  #not merely two ends meeting, which is a junction already
                cuts.setdefault(i, []).append(di)
                cuts.setdefault(j, []).append(dj)
                n_cross += 1
    #2 near misses: an end within join_tol of the other family's line, not touching it
    for i, g in enumerate(geoms):
        for c in (g.coords[0], g.coords[-1]):
            pt = shapely.Point(c)
            if not pt.within(site):
                continue
            near = [j for j in tree.query(pt.buffer(p["join_tol_m"]))
                    if old[j] != old[i] and geoms[j].distance(pt) <= p["join_tol_m"]]  #the tree only checks boxes
            meets = lambda j: geoms[j].intersects(pt) or min(shapely.Point(geoms[j].coords[0]).distance(pt),
                                                             shapely.Point(geoms[j].coords[-1]).distance(pt)) < p["node_tol_m"]
            if not near or any(meets(j) for j in near):
                continue  #nothing of the other family near, or it already meets one: exactly, or at an end within node_tol
            #a gap of even 4 cm is a gap: a link axis aimed at osm_roads.geojson ended 0.04 m off the walk network's street
            j = min(near, key=lambda j: geoms[j].distance(pt))
            d = geoms[j].project(pt)
            seg = shapely.LineString([c, geoms[j].interpolate(d).coords[0]])
            if seg.intersects(blocks):
                continue  #would go through a new block
            cuts.setdefault(j, []).append(d)
            joins.append(seg)
    rows = []
    for i, g in enumerate(geoms):
        for piece in split_at(g, cuts.get(i, [])):
            rows.append({**lines.iloc[i].drop("geometry").to_dict(), "geometry": piece})
    rows += [{"highway": "connector", "name": f"{scenario} join", "kind": "connector", "geometry": g} for g in joins]
    print(f"  {scenario}: {n_cross} crossings made junctions, {len(joins)} near-miss ends joined "
          f"({sum(g.length for g in joins):.0f} m)")
    return gpd.GeoDataFrame(rows, crs=lines.crs)


def build_graph(lines, node_tol_m=PARAMS["node_tol_m"]):
    #lines -> nodes (xy), edges (i, j, length), keeping the largest connected component
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree
    ends = np.array([c[:2] for g in lines.geometry for c in (g.coords[0], g.coords[-1])])
    #ends closer than node_tol_m are one node: rounding to a 0.1 m grid split two ends 0.1 m apart into
    #two nodes and cut scenario_a's main street in two (2026-10-23); OSM ends that are one node coincide exactly
    pairs = np.array(sorted(cKDTree(ends).query_pairs(node_tol_m)), dtype=int).reshape(-1, 2)  #includes identical ends
    m = len(ends)
    _, lab = connected_components(sp.coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(m, m)),
                                  directed=False)
    uniq, first = np.unique(lab, return_index=True)
    xy = list(ends[first])  #one position per cluster, the first end found
    ij = lab.reshape(-1, 2)
    L = lines.geometry.length.to_numpy()
    n = len(xy)
    A = sp.coo_matrix((np.ones(len(ij)), (ij[:, 0], ij[:, 1])), shape=(n, n))
    nc, lab = connected_components(A, directed=False)
    big = np.bincount(lab).argmax()
    keep = lab[ij[:, 0]] == big
    print(f"  graph: {n} nodes, {len(ij)} edges, {nc} components; "
          f"{(~keep).sum()} edges outside the largest dropped")
    return {"xy": np.array(xy), "ij": ij[keep], "L": L[keep], "lines": lines[keep].reset_index(drop=True)}


def min_csr(r, c, d, shape):
    #sparse matrix keeping the smallest value per (row, col); scipy would add duplicates up
    import scipy.sparse as sp
    order = np.lexsort((d, c, r))
    r, c, d = r[order], c[order], d[order]
    first = np.r_[True, (r[1:] != r[:-1]) | (c[1:] != c[:-1])]
    return sp.csr_matrix((d[first], (r[first], c[first])), shape=shape)


def csr(net, extra=()):
    #symmetric adjacency with the shortest length per node pair, plus extra (i, j, L) links
    ij, L = net["ij"], net["L"]
    if len(extra):
        e = np.asarray(extra, float)
        ij = np.vstack([ij, e[:, :2].astype(int)])
        L = np.concatenate([L, e[:, 2]])
    n = len(net["xy"]) + 1  #last index is the super-source used for many-to-nearest distances
    return min_csr(np.r_[ij[:, 0], ij[:, 1]], np.r_[ij[:, 1], ij[:, 0]], np.r_[L, L], (n, n))


def snap(net, pts):
    #points -> (edge index, distance along it, access distance) on the nearest edge
    import shapely
    geoms = net["lines"].geometry.values
    tree = shapely.STRtree(geoms)
    idx = tree.query_nearest(pts, all_matches=False)[1]
    t = shapely.line_locate_point(geoms[idx], pts)
    acc = shapely.distance(geoms[idx], pts)
    #line direction can run j -> i; t is measured from the line's first point, which is node i
    return idx, t, acc


def dist_from(net, G, snapped):
    #walking distance from every node to the nearest of a set of snapped points (super-source Dijkstra)
    from scipy.sparse.csgraph import dijkstra
    idx, t, acc = snapped
    n = G.shape[0] - 1
    i, j = net["ij"][idx, 0], net["ij"][idx, 1]
    L = net["L"][idx]
    rows = np.r_[np.full(len(idx), n), np.full(len(idx), n)]
    cols = np.r_[i, j]
    w = np.r_[acc + t, acc + (L - t)] + 1e-9  #from the point along the edge to either end
    S = min_csr(rows, cols, w, G.shape)  #two points on one node: the nearer one counts
    d = dijkstra(G + S, directed=True, indices=n)  #the super-source only has outgoing links
    return d[:n]


def to_points(net, D, snapped):
    #node distances -> distance at each snapped point
    idx, t, acc = snapped
    i, j = net["ij"][idx, 0], net["ij"][idx, 1]
    return acc + np.minimum(D[i] + t, D[j] + net["L"][idx] - t)


# ------------------------------------------------------------------ metrics
def areas():
    #name -> polygon (RD) for every area reported
    by_code = buurt_polygons()
    a = {name: by_code[code] for code, name in STUDY_AREA.buurten}
    a["study_area"] = study_area_polygon()
    a["outside_site"] = a["study_area"].difference(design_site_polygon())  #the neighbours: same homes in every scenario
    a["design_site"] = design_site_polygon()
    return a


def edge_betweenness(net):
    #exact length-weighted edge betweenness over the whole buffered network, normalised
    import networkx as nx
    g = nx.Graph()
    for (i, j), L in zip(net["ij"], net["L"]):
        if i != j and (not g.has_edge(i, j) or g[i][j]["length"] > L):
            g.add_edge(int(i), int(j), length=float(L))
    eb = nx.edge_betweenness_centrality(g, weight="length", normalized=True)
    return np.array([eb.get((int(i), int(j)), eb.get((int(j), int(i)), 0.0)) if i != j else 0.0
                     for i, j in net["ij"]])


def structure(net, eb, poly):
    #the stub's network metrics for one area
    import shapely
    mid = shapely.line_interpolate_point(net["lines"].geometry.values, 0.5, normalized=True)
    e = shapely.within(mid, poly)
    nodes_in = shapely.within(shapely.points(net["xy"]), poly)
    ij, L = net["ij"], net["L"]
    nb = {}  #distinct neighbours per node, so parallel edges and self loops do not count twice
    for i, j in ij:
        if i != j:
            nb.setdefault(i, set()).add(j); nb.setdefault(j, set()).add(i)
    deg = np.array([len(nb.get(k, ())) for k in range(len(net["xy"]))])
    straight = np.hypot(*(net["xy"][ij[:, 0]] - net["xy"][ij[:, 1]]).T)
    ok = e & (straight > 0)
    return {
        "n_nodes": int(nodes_in.sum()),
        "n_edges": int(e.sum()),
        "avg_street_length_m": round(float(L[e].mean()), 1),
        "intersection_density_km2": round(float(((deg >= 3) & nodes_in).sum() / (poly.area / 1e6)), 1),
        "circuity": round(float(L[ok].sum() / straight[ok].sum()), 3),
        "betweenness_max": round(float(eb[e].max()), 4),
        "street_length_km": round(float(L[e].sum() / 1000), 2),
    }


def access(dist, homes, mask, p):
    #dwelling-weighted distances to each destination type for the homes in mask
    reach = p["walk_m_per_min"] * p["reach_min"]
    near = p["walk_m_per_min"] * p["near_min"]
    w = homes["w"].to_numpy()[mask]
    out = {"dwellings": round(float(w.sum()))}
    all_ok = np.ones(mask.sum(), bool)
    for k, d in dist.items():
        dk = d[mask]
        out[k] = {"mean_m": round(float(np.average(dk, weights=w)), 1),
                  "within_15min_frac": round(float(np.average(dk <= reach, weights=w)), 3),
                  "within_5min_frac": round(float(np.average(dk <= near, weights=w)), 3)}
        all_ok &= dk <= reach
    out["mean_of_types_m"] = round(float(np.mean([out[k]["mean_m"] for k in dist])), 1)  #the optimiser's objective
    out["walk_15min_reach_frac"] = round(float(np.average(all_ok, weights=w)), 3)
    return out


def site_grid(p):
    #fixed origins: a regular grid over the design site, the same points in every scenario
    import geopandas as gpd
    import shapely
    site = design_site_polygon()
    x0, y0, x1, y1 = site.bounds
    xs, ys = np.meshgrid(np.arange(x0, x1, p["grid_m"]), np.arange(y0, y1, p["grid_m"]))
    pts = shapely.points(xs.ravel(), ys.ravel())
    pts = pts[shapely.within(pts, site)]
    return gpd.GeoDataFrame({"w": np.ones(len(pts))}, geometry=pts, crs=28992)


def write_geojson(net, eb, scenario):
    #edges near the study area in WGS84, with length, betweenness and kind, for the app
    import shapely
    from shapely.ops import transform
    keep = shapely.intersects(net["lines"].geometry.values, study_area_polygon().buffer(100))
    feats = []
    for g, L, b, kind in zip(net["lines"].geometry[keep], net["L"][keep], eb[keep], net["lines"]["kind"][keep]):
        w = transform(lambda x, y, z=None: to_wgs(x, y), g.simplify(0.5))  #0.5 m: the traced centrelines carry a vertex every metre
        feats.append({"type": "Feature",
                      "properties": {"length_m": round(float(L), 1), "betweenness": round(float(b), 5), "kind": kind},
                      "geometry": {"type": "LineString", "coordinates": [[round(x, 6), round(y, 6)] for x, y in w.coords]}})
    path = PROCESSED / f"roads_{scenario}.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")) + "\n")
    print(f"  wrote {path.relative_to(ROOT)} ({len(feats)} edges)")


# --------------------------------------------------------------------- run
def network_for(scenario, p):
    #the scenario's graph, ready to route on; shared with optimise_links.py
    return build_graph(lines_for_scenario(osm_edges(), scenario, p))


def run(case, p, dest, dwelling_m2):
    #one scenario: network, metrics per area, accessibility, geojson
    import shapely
    sc = case["scenario"]
    print(f"\n{sc}")
    net = network_for(sc, p)
    G = csr(net)
    homes = homes_for_scenario(sc, dwelling_m2, p)
    hs = snap(net, homes.geometry.values)
    grid = site_grid(p)
    gs = snap(net, grid.geometry.values)
    D = {k: dist_from(net, G, snap(net, pts.values)) for k, pts in dest.items()}  #node distances per type
    dist = {k: to_points(net, d, hs) for k, d in D.items()}  #at each home
    dist_grid = {k: to_points(net, d, gs) for k, d in D.items()}  #at each grid point on the site
    print("  edge betweenness (exact, a minute or two)")
    eb = edge_betweenness(net)
    res = {"areas": {}, "geojson": f"../data/processed/roads_{sc}.geojson"}
    hp = shapely.points(np.c_[homes.geometry.x, homes.geometry.y])
    for name, poly in areas().items():
        m = shapely.within(hp, poly)
        res["areas"][name] = {**structure(net, eb, poly), **access(dist, homes, m, p)}
    g = access(dist_grid, grid, np.ones(len(grid), bool), p)  #same origins in every scenario: the network's effect alone
    g["grid_points"] = g.pop("dwellings")
    res["site_grid"] = g
    dw = dest_with_amenities(dest, sc)
    if dw is not None:  #the same walks with the scenario's amenities: today's own, or the placed ones
        D2 = {k: dist_from(net, G, snap(net, pts.values)) for k, pts in dw.items()}
        d2 = {k: to_points(net, d, hs) for k, d in D2.items()}
        g2 = access({k: to_points(net, d, gs) for k, d in D2.items()}, grid, np.ones(len(grid), bool), p)
        g2["grid_points"] = g2.pop("dwellings")
        res["with_amenities"] = {
            "_note": "today with its own shops, health and schools on the site; an option with the ones "
                     "place_amenities.py puts on its ground floors (the kept school is in both)",
            "areas": {name: access(d2, homes, shapely.within(hp, poly), p) for name, poly in areas().items()},
            "site_grid": g2}
        wa = res["with_amenities"]
        print(f"  with amenities: site dwellings {wa['areas']['design_site']['mean_of_types_m']} m, "
              f"site grid {g2['mean_of_types_m']} m, study area {wa['areas']['study_area']['mean_of_types_m']} m")
    res["metrics"] = {k: res["areas"]["study_area"][k] for k in
                      ("n_nodes", "n_edges", "avg_street_length_m", "intersection_density_km2",
                       "circuity", "betweenness_max", "walk_15min_reach_frac")}  #the stub's shape, for the card
    res["network"] = {"connectors": int((net["lines"]["kind"] == "connector").sum()),
                      "connector_length_m": round(float(net["L"][(net["lines"]["kind"] == "connector").to_numpy()].sum()), 1),
                      "new_street_length_m": round(float(net["L"][(net["lines"]["kind"] == "new").to_numpy()].sum()), 1),
                      "new_block_dwellings_est": round(float(homes["w"][homes["new"]].sum()))}
    write_geojson(net, eb, sc)
    for name in ("study_area", "outside_site", "design_site"):
        a = res["areas"][name]
        print(f"  {name:12s} mean of types {a['mean_of_types_m']:6.1f} m, all four within 15 min "
              f"{a['walk_15min_reach_frac']:.3f}, {a['dwellings']} dwellings, "
              f"intersections {a['intersection_density_km2']}/km2")
    print(f"  site grid    mean of types {g['mean_of_types_m']:6.1f} m over {g['grid_points']} points "
          + ", ".join(f"{k} {g[k]['mean_m']:.0f} m" for k in DEST))
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="re-fetch the OSM walk network and stops")
    args = ap.parse_args()
    p = PARAMS
    print(f"Walking network — {STUDY_AREA.name}")
    fetch(p, args.refresh)
    dest, removed, dwelling_m2 = destinations()
    out = {
        "study_area": STUDY_AREA.name,
        "_method": "OSM walk network (osmnx), buffered 500 m; scenario streets from scenario_world.py; "
                   "distances from BAG dwellings to the nearest destination of each type, destinations on "
                   "the design site excluded in every scenario. See analysis/roads/road_network.py.",
        "_params": p,
        "destinations_on_site_today": removed,
        "dwelling_m2_site_median": dwelling_m2,
    }
    for case in CASES:  #one scenario per case
        out[case["scenario"]] = run(case, p, dest, dwelling_m2)
    for sc in ("baseline", "scenario_a", "scenario_b"):
        if sc not in out:
            out[sc] = {"_status": "not_computed_yet", "_note": f"{sc} has no massing yet"}  #keyed for 4.9 all the same
    write_processed("road_metrics.json", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
