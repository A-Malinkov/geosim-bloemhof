#!/usr/bin/env python3
"""
height_width.py - street-canyon height-to-width ratio (H/W) per scenario.

Owner: Atanas Malinkov

    python analysis/morphology/height_width.py                        #all cases
    python analysis/morphology/height_width.py --scenario scenario_a  #only these
    python analysis/morphology/height_width.py --refresh              #re-fetch 3DBAG footprints

H/W after Oke (1988). OSM centrelines are sampled every 10 m. At each sample a
ray goes out on both sides, up to 60 m, to the first 3DBAG wall (sheds under
15 m2 or 3 m left out). W is facade to facade, H the mean of the two heights.
A sample is canyon only if both rays hit. Statistics are by street length, and
each sample counts for the buurt or site its point lies in.

Limits. One height per building (roof median). Gaps under 10 m are averaged
over. Dual carriageways are measured from each half.

Writes canyon_hw_<scenario>.json and .geojson in data/processed/ and
docs/fig_canyon_hw_<scenario>.png.
"""

import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "wind_noise"))
from common.project import (PROCESSED, RAW, ROOT, STUDY_AREA,  #noqa: E402
                            bbox_rd, buurt_polygons, design_site_polygon,
                            write_processed)

CACHE = ROOT / "cache" / "morphology"
DOCS = ROOT / "docs"

STEP_M = 10.0          #sample spacing along each street
MAX_RAY_M = 60.0       #how far to look for a façade on each side
#Drop sheds, keep houses. density_height.py's "principal" filter (>= 40 m2,
#>= 4 m) is wrong HERE: the median building on the design site is 36 m2, as a
#terraced house is its own BAG record, so it dropped half the street wall and
#rays slipped through the gaps (residential W 32 m instead of 20 m). With no
#filter at all W is 20.5 m, so sheds rarely act as a street wall anyway.
MIN_FOOTPRINT_M2 = 15
MIN_HEIGHT_M = 3.0
FETCH_PAD_M = 80       #footprints a little beyond the buurten, for edge streets
#Classes for the map and the shares. Oke's regimes for wind over canyons
#switch around H/W ~0.4 (isolated roughness) and ~0.7 (skimming flow).
CLASS_EDGES = [0.4, 0.7, 1.0, 1.5]
CLASS_LABELS = ["< 0.4 open", "0.4–0.7", "0.7–1.0", "1.0–1.5", "> 1.5 deep"]


def footprints(refresh):
    #3DBAG LoD0 footprints over the study area (+ pad), cached in cache/.
    import geopandas as gpd
    from noise import fetch_footprints          #same 3DBAG paging + LoD0 decoding

    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / "footprints_3dbag.geojson"
    if refresh or not path.exists():
        print("  fetching 3DBAG footprints for the study area (a few minutes)…")
        fetch_footprints(bbox_rd(FETCH_PAD_M), path)
    b = gpd.read_file(path).set_crs("EPSG:28992", allow_override=True)
    b = b[b["height_m"].notna()]
    b = b[(b.geometry.area >= MIN_FOOTPRINT_M2) & (b["height_m"] >= MIN_HEIGHT_M)]
    return b.reset_index(drop=True)


def sample_streets(roads):
    #Points every STEP_M along each street, with the unit normal there.
    import shapely
    pts, nrm, seg = [], [], []
    for i, g in enumerate(roads.geometry):
        L = g.length
        if L < STEP_M / 2:
            continue
        for d in np.arange(STEP_M / 2, L, STEP_M):
            p = g.interpolate(d)
            a = g.interpolate(max(d - 1.0, 0))
            b = g.interpolate(min(d + 1.0, L))
            tx, ty = b.x - a.x, b.y - a.y
            n = np.hypot(tx, ty)
            if n == 0:
                continue
            pts.append((p.x, p.y)); nrm.append((-ty / n, tx / n)); seg.append(i)
    return np.array(pts), np.array(nrm), np.array(seg)


def first_hits(origins, dirs, walls, heights):
    #Distance to, and height of, the first wall hit by each ray (NaN if none).
    import shapely
    ends = origins + dirs * MAX_RAY_M
    rays = shapely.linestrings(np.stack([origins, ends], axis=1))
    tree = shapely.STRtree(walls)
    ri, wi = tree.query(rays, predicate="intersects")
    dist = np.full(len(rays), np.nan)
    height = np.full(len(rays), np.nan)
    if len(ri):
        inter = shapely.intersection(rays[ri], walls[wi])
        d = shapely.distance(shapely.points(origins[ri]), inter)
        order = np.lexsort((d, ri))          #by ray, then nearest first
        ri, wi, d = ri[order], wi[order], d[order]
        first = np.r_[True, ri[1:] != ri[:-1]]
        dist[ri[first]] = d[first]
        height[ri[first]] = heights[wi[first]]
    return dist, height


def stats(hw, h, w, canyon_mask):
    #Length-weighted statistics for one area. Each sample = STEP_M of street.
    n = int(canyon_mask.size)
    c = canyon_mask
    out = {
        "street_km": round(n * STEP_M / 1000, 2),
        "canyon_share": round(float(c.mean()), 3) if n else None,
    }
    if c.sum() == 0:
        return out
    v = hw[c]
    counts = np.histogram(v, bins=[-np.inf] + CLASS_EDGES + [np.inf])[0]
    out.update({
        "hw": {"median": round(float(np.median(v)), 2), "mean": round(float(v.mean()), 2),
               "p10": round(float(np.percentile(v, 10)), 2),
               "p90": round(float(np.percentile(v, 90)), 2)},
        "h_m_median": round(float(np.median(h[c])), 1),
        "w_m_median": round(float(np.median(w[c])), 1),
        "classes": {lab: round(float(k / c.sum()), 3) for lab, k in zip(CLASS_LABELS, counts)},
    })
    return out


PARAMS = {
    "refresh": "--refresh" in sys.argv,  #re-fetch the 3DBAG footprints
}

CASES = [
    {"scenario": "baseline"},
    {"scenario": "scenario_a"},
    {"scenario": "scenario_b"},
    {"scenario": "final"},  #the Rhino Final Model, 2026-10-28
]


def run(p):
    #one case: PARAMS merged with one dict from CASES
    sys.path.insert(0, str(HERE.parent / "scenarios"))
    from scenario_world import buildings_for_scenario, streets_for_scenario  #no-ops for baseline

    import geopandas as gpd
    import shapely
    from shapely.geometry import box

    print(f"Street canyon H/W: {STUDY_AREA.name}, {p['scenario']}")
    b = footprints(p["refresh"])
    b = buildings_for_scenario(b, p["scenario"])  #demolished out, new blocks in
    walls = shapely.boundary(b.geometry.values)
    heights = b["height_m"].to_numpy(float)
    print(f"  {len(b)} buildings as street walls (sheds excluded)")

    roads = gpd.read_file(RAW / "osm_roads.geojson").to_crs(28992)
    roads = roads[roads.intersects(box(*bbox_rd(0)))].reset_index(drop=True)
    roads = streets_for_scenario(roads, p["scenario"]).reset_index(drop=True)  #old interior grid swapped for the new streets
    P, N, S = sample_streets(roads)

    #A sample inside a building (a passage under it) has no street wall.
    inside = shapely.STRtree(b.geometry.values).query(shapely.points(P), predicate="within")[0]
    keep = np.ones(len(P), bool); keep[np.unique(inside)] = False
    P, N, S = P[keep], N[keep], S[keep]
    print(f"  {len(P)} samples on {len(roads)} street segments")

    dl, hl = first_hits(P, N, walls, heights)
    dr, hr = first_hits(P, -N, walls, heights)
    canyon = np.isfinite(dl) & np.isfinite(dr)
    W = dl + dr
    H = (hl + hr) / 2
    HW = np.where(canyon, H / W, np.nan)

    #Assign samples to areas by the centreline point.
    pts = gpd.GeoSeries(shapely.points(P), crs="EPSG:28992")
    by_code = buurt_polygons()                       #keyed by buurt code
    polys = {name: by_code[code] for code, name in STUDY_AREA.buurten}
    areas = {name: pts.within(poly).to_numpy() for name, poly in polys.items()}
    areas_all = np.logical_or.reduce(list(areas.values()))
    site = pts.within(design_site_polygon()).to_numpy()

    def area_stats(mask):
        return stats(HW[mask], H[mask], W[mask], canyon[mask])

    summary = {
        "study_area": STUDY_AREA.name,
        "scenario": p["scenario"],
        "method": "street-canyon H/W (Oke 1988): perpendicular rays from OSM centrelines "
                  "to the first 3DBAG main-building façade on each side",
        "parameters": {"step_m": STEP_M, "max_ray_m": MAX_RAY_M,
                       "wall_min_footprint_m2": MIN_FOOTPRINT_M2, "wall_min_height_m": MIN_HEIGHT_M,
                       "class_edges": CLASS_EDGES},
        "unit": "street length; H/W statistics over canyon samples (buildings on both sides)",
        "per_buurt": {name: area_stats(m) for name, m in areas.items()},
        "combined": area_stats(areas_all),
        "design_site": area_stats(site),
        "limitations": [
            "One height per building (roof median), not eave height.",
            "Gaps in a street wall narrower than the 10 m sample spacing are averaged over.",
            "Dual carriageways are measured from each half's centreline.",
        ],
    }
    for k, v in [*summary["per_buurt"].items(), ("combined", summary["combined"]),
                 ("design site", summary["design_site"])]:
        hw = v.get("hw", {})
        print(f"  {k:12s} canyon {v['canyon_share']:.0%} of {v['street_km']} km, "
              f"H/W median {hw.get('median')}, H {v.get('h_m_median')} m, W {v.get('w_m_median')} m")
    write_processed(f"canyon_hw_{p['scenario']}.json", summary)

    #Per street segment, inside the buurten or the design site: median over its
    #canyon samples. The site counts too because Strevelsweg, its south edge,
    #runs ON the buurt boundary, so its centreline is in neither buurt.
    drawn = areas_all | site
    rows = []
    for i in np.unique(S[drawn]):
        m = (S == i) & drawn
        c = m & canyon
        r = roads.iloc[i]
        #osmnx stores tags as arrays (a segment merged from several ways can
        #carry several names), so take the distinct names in order.
        nm = r.get("name")
        nm = list(dict.fromkeys(np.atleast_1d(nm).tolist())) if nm is not None else []
        nm = [x for x in nm if isinstance(x, str) and x]
        if c.sum() == 0:  #no facade on both sides anywhere: kept as "no canyon" so the map shows every street
            rows.append({"geometry": r.geometry, "name": " / ".join(nm) or None,
                         "hw": None, "h_m": None, "w_m": None, "canyon_share": 0.0})
            continue
        rows.append({"geometry": r.geometry,
                     "name": " / ".join(nm) or None,
                     "hw": round(float(np.median(HW[c])), 2),
                     "h_m": round(float(np.median(H[c])), 1),
                     "w_m": round(float(np.median(W[c])), 1),
                     "canyon_share": round(float(c.sum() / m.sum()), 2)})
    seg = gpd.GeoDataFrame(rows, crs="EPSG:28992")
    out = PROCESSED / f"canyon_hw_{p['scenario']}.geojson"
    out.write_text(seg.to_crs(4326).to_json(drop_id=True))
    print(f"[height_width] wrote {out.relative_to(ROOT)} ({len(seg)} segments)")

    figure(seg, polys, p["scenario"], summary)
    return 0


def figure(seg, polys, scenario, summary):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import geopandas as gpd
    from matplotlib.colors import BoundaryNorm, ListedColormap
    from matplotlib.lines import Line2D

    colours = ["#c6dbef", "#6baed6", "#2171b5", "#08519c", "#08306b"]
    cmap = ListedColormap(colours)
    norm = BoundaryNorm([0] + CLASS_EDGES + [99], cmap.N)
    fig, ax = plt.subplots(figsize=(10, 8.5))
    gpd.GeoSeries(list(polys.values()), crs="EPSG:28992").boundary.plot(ax=ax, color="#999", linewidth=0.8)
    gpd.GeoSeries([design_site_polygon()], crs="EPSG:28992").boundary.plot(ax=ax, color="#d95f02", linewidth=1.6)
    open_ = seg["hw"].isna()  #segments with no canyon sample
    if open_.any():
        seg[open_].plot(ax=ax, color="#bbbbbb", linewidth=1.0, linestyle=(0, (3, 2)))  #grey dashed
    seg[~open_].plot(ax=ax, column="hw", cmap=cmap, norm=norm, linewidth=2.2)
    ax.legend(handles=[Line2D([0], [0], color=c, lw=3, label=l) for c, l in zip(colours, CLASS_LABELS)]
              + [Line2D([0], [0], color="#bbbbbb", lw=1, ls="--", label="no canyon")]  #open on a side
              + [Line2D([0], [0], color="#d95f02", lw=1.6, label="design site")],
              title="H/W", loc="upper left", bbox_to_anchor=(1.01, 1), frameon=False)
    c, s = summary["combined"], summary["design_site"]
    ax.set_title(f"Street canyon height-to-width ratio: {scenario}\n"
                 f"median H/W {c['hw']['median']} (both buurten), {s['hw']['median']} (design site); "
                 f"{c['canyon_share']:.0%} of street length is a canyon")
    ax.set_axis_off(); ax.set_aspect("equal")
    plt.tight_layout()
    out = DOCS / f"fig_canyon_hw_{scenario}.png"
    fig.savefig(out, dpi=150)
    print(f"[height_width] wrote {out.relative_to(ROOT)}")


def main():
    only = sys.argv[sys.argv.index("--scenario") + 1:] if "--scenario" in sys.argv else None  #run only these cases
    for c in CASES:
        if only is None or c["scenario"] in only:
            run({**PARAMS, **c})
            PARAMS["refresh"] = False  #fetched once is enough
    return 0


if __name__ == "__main__":
    sys.exit(main())
