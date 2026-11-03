#!/usr/bin/env python3
"""
noise.py - road-traffic noise (Lden) around the design site, with NoiseModelling.

    python analysis/wind_noise/noise.py                         #every case, ~10 min each
    python analysis/wind_noise/noise.py --scenario scenario_a   #only these (baseline, scenario_a, scenario_b, final)
    python analysis/wind_noise/noise.py --refresh               #re-fetch OSM and 3DBAG
    python analysis/wind_noise/noise.py --figure-only           #redraw the figures from the stored JSON

Needs Java 11+ and NoiseModelling 6.0.0 outside the repo, by default in
~/tools/NoiseModelling_6.0.0 (or NOISEMODELLING_HOME), from
https://github.com/Universite-Gustave-Eiffel/NoiseModelling/releases/tag/v6.0.0

NoiseModelling implements CNOSSOS-EU. noise_pipeline.groovy runs the GUI's
chain headless, OSM import, road emission, receivers, propagation, isosurface.
OSM has no traffic counts, so flows and speeds come per road type from the EU
Good Practice Guide v2, speeds capped at maxspeed (else 50 km/h streets run at
80). Buildings are 3DBAG footprints with the usual height. Receivers sit at
1.75 m on a Delaunay grid over the site plus 200 m, triangles of 100 m2 at most
so squares are sampled. Every road within 250 m counts.

Limits. Traffic is not measured, so a street can be several dB off. Lean on
baseline against design, where that error is shared. Roads only. Flat ground.
Free-field levels at 1.75 m, so the Bkl facade values (53 and 70 dB Lden) are
reference lines and not a compliance test.

Writes data/processed/noise_<scenario>.json and docs/fig_noise_<scenario>.png.
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "morphology"))
from common.project import (DESIGN_SITE, PROCESSED, ROOT,  #noqa: E402
                            design_site_polygon, write_processed)

NM_HOME = pathlib.Path(os.environ.get(
    "NOISEMODELLING_HOME", pathlib.Path.home() / "tools" / "NoiseModelling_6.0.0"))
CACHE = ROOT / "cache" / "noise"          #gitignored, regenerable
DOCS = ROOT / "docs"

FENCE_BUFFER_M = 200      #receivers: design site + this
MAX_SRC_DIST_M = 250      #sources heard from up to this far
DATA_PAD_M = MAX_SRC_DIST_M + 50   #roads/buildings fetched this far past the fence
RECEIVER_HEIGHT_M = 1.75
GRID_M = 2.0              #regular grid for the app and the statistics
MAX_TRIANGLE_M2 = 100     #Delaunay receivers: largest triangle (default 2500)
#Propagation threads. NoiseModelling defaults to every core, and with 16
#threads on the dense receiver grid the JVM ran out of native memory and
#segfaulted (2026-10-14, ~4 GB free). Override with NOISE_THREADS.
THREADS = int(os.environ.get("NOISE_THREADS", min(8, os.cpu_count() or 1)))
BKL_STANDARD_DB = 53.0    #Bkl standard value, municipal roads, Lden
BKL_LIMIT_DB = 70.0       #Bkl limit value, municipal roads, Lden
ISO_CLASS = "35,40,45,50,53,55,60,65,70,75,80,200"

OVERPASS = "https://overpass-api.de/api/interpreter"
#Overpass answers 406 Not Acceptable without a User-Agent.
UA = "geosim-bloemhof/1.0 (TU Delft Geosimulation student project)"
BAG3D = "https://api.3dbag.nl/collections/pand/items"


#--- fetching
def http(url, data=None, tries=4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={
                "User-Agent": UA, "Accept": "application/json, */*"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read()
        except Exception as exc:
            if attempt == tries - 1:
                raise
            print(f"    retry {attempt + 1} after {type(exc).__name__}: {exc}")
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")


def fetch_osm(extent_rd, path):
    from pyproj import Transformer
    t = Transformer.from_crs("EPSG:28992", "EPSG:4326", always_xy=True)
    xmin, ymin, xmax, ymax = extent_rd
    lons, lats = t.transform([xmin, xmax, xmin, xmax], [ymin, ymin, ymax, ymax])
    s, w, n, e = min(lats), min(lons), max(lats), max(lons)
    #Ways in the box and their nodes only. Recursing relations as well drags
    #in whole bus routes reaching into Belgium (25 MB instead of ~3), and
    #Osmosis, NoiseModelling's OSM reader, needs `out meta` for versions.
    q = (f"[out:xml][timeout:180];"
         f"(way({s},{w},{n},{e}););(._;>;);out meta;")
    print(f"  OSM via Overpass, bbox {s:.5f},{w:.5f},{n:.5f},{e:.5f}")
    body = http(OVERPASS, urllib.parse.urlencode({"data": q}).encode())
    if b"<osm" not in body[:500]:
        raise RuntimeError(f"Overpass did not return OSM XML: {body[:300]!r}")
    path.write_bytes(body)
    print(f"    {len(body) / 1e6:.1f} MB")


def fetch_footprints(extent_rd, path):
    #3DBAG LoD0 footprints with heights, paged like fetch_buildings.py.
    xmin, ymin, xmax, ymax = extent_rd
    url = f"{BAG3D}?" + urllib.parse.urlencode(
        {"bbox": f"{xmin:.0f},{ymin:.0f},{xmax:.0f},{ymax:.0f}", "limit": 100})
    feats, seen, page = [], set(), 0
    while url:
        d = json.loads(http(url))
        sc, tl = d["metadata"]["transform"]["scale"], d["metadata"]["transform"]["translate"]
        for f in d.get("features", []):
            pid = f.get("id")
            obj = (f.get("CityObjects") or {}).get(pid)
            if not pid or pid in seen or not obj:
                continue
            lod0 = [g for g in obj.get("geometry", []) if str(g.get("lod")) == "0"]
            if not lod0:
                continue
            verts = f["vertices"]
            rings = []
            #MultiSurface: boundaries = [surface][ring][vertex index]
            for surface in lod0[0]["boundaries"]:
                rings.append([[[verts[i][0] * sc[0] + tl[0],
                                verts[i][1] * sc[1] + tl[1]] for i in ring]
                              for ring in surface])
            a = obj.get("attributes") or {}
            roof, ground = a.get("b3_h_dak_50p"), a.get("b3_h_maaiveld")
            seen.add(pid)
            feats.append({
                "type": "Feature",
                "geometry": {"type": "MultiPolygon",
                             "coordinates": [[r + [r[0]] for r in surf] for surf in rings]},
                "properties": {
                    "identificatie": pid,
                    "height_m": (round(roof - ground, 2)
                                 if roof is not None and ground is not None else None),
                    "bouwlagen": a.get("b3_bouwlagen"),
                },
            })
        page += 1
        if page % 20 == 0:
            print(f"    {len(feats)} footprints")
        nxt = [l for l in d.get("links", []) if l.get("rel") == "next"]
        url = nxt[0]["href"] if nxt else None
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    print(f"    {len(feats)} footprints")


#--- preparation
def buildings_for(scenario, extent_poly, src):
    #The BUILDINGS table for one scenario, as a GeoDataFrame (PK, HEIGHT).
    import geopandas as gpd
    from shapely.geometry import box  #noqa: F401
    from shapely.validation import make_valid

    b = gpd.read_file(src).set_crs("EPSG:28992", allow_override=True)
    b = b[b.representative_point().within(extent_poly)].copy()

    #A few hundred small sheds have no 3DBAG height; give them one storey
    #rather than dropping them, since they still screen the ground behind.
    missing = b["height_m"].isna() | (b["height_m"] <= 0)
    b.loc[missing, "height_m"] = 3.0
    print(f"  buildings: {len(b)} ({int(missing.sum())} without a height -> 3 m)")

    if scenario != "baseline":
        sys.path.insert(0, str(HERE.parent / "scenarios"))  #shared scenario geometry
        from scenario_world import buildings_for_scenario
        b = buildings_for_scenario(b, scenario)  #demolished 3DBAG ids out, new blocks in, height_m above ground
        #sources are unchanged: traffic still runs on the OSM network, including the old
        #interior streets the design removes. Edge-street traffic dominates the site, but
        #a source left inside a new block is screened by it, so check the map near the blocks.

        #the final design stands flats on shop podiums: two footprints on one spot. The podium
        #loses what the flats cover (wind_cfd_export.cut_overlaps), so no building sits inside
        #another; the flats' prism runs from the ground to their roof and screens for both
        from wind_cfd_export import cut_overlaps
        new = ~b["identificatie"].astype(str).str.startswith("NL.IMBAG")  #the scenario's own blocks
        rows, n_cut = cut_overlaps(list(zip(b.index[new], b.loc[new, "height_m"], b.geometry[new])))
        if n_cut:
            b.loc[[i for i, _, _ in rows], "geometry"] = [g for _, _, g in rows]
            print(f"  {n_cut} new blocks overlapped a taller one; the overlap is left to the taller")

    b["geometry"] = b.geometry.apply(make_valid).buffer(0)
    b = b[~b.geometry.is_empty]
    out = gpd.GeoDataFrame({"PK": np.arange(1, len(b) + 1),
                            "HEIGHT": b["height_m"].astype(float).values},
                           geometry=b.geometry.values, crs="EPSG:28992")
    return out


def write_maxspeeds(osm, path):
    #OSM way id -> posted speed limit (km/h), for the roads that have one.
    #
    #Import_OSM parses `maxspeed` but then assigns speeds by road TYPE anyway:
    #every primary/secondary road here comes out at 80 km/h although OSM tags
    #all of them 50. The pipeline caps each road at its posted limit.
    import re
    import xml.etree.ElementTree as ET
    rows = []
    for w in ET.parse(osm).getroot().iter("way"):
        tags = {t.get("k"): t.get("v") for t in w.iter("tag")}
        m = re.match(r"\s*(\d+)", tags.get("maxspeed") or "")
        if tags.get("highway") and m:
            rows.append(f"{w.get('id')},{int(m.group(1))}")
    path.write_text("ID_WAY,MAXSPEED\n" + "\n".join(rows) + "\n")
    return len(rows)


def write_geojson_rd(gdf, path):
    #Coordinates are RD New but the file carries no CRS member, so a plain
    #gpd.read_file() labels it WGS84. Readers must
    #.set_crs("EPSG:28992", allow_override=True), as height_width.py does.
    gdf.to_file(path, driver="GeoJSON")


#--- run NM
def run_noisemodelling(work, osm, buildings,
                       fence, maxspeed):
    #Windows ships a .bat launcher next to the shell script.
    runner = NM_HOME / "bin" / ("ScriptRunner.bat" if os.name == "nt" else "ScriptRunner")
    if not runner.exists():
        sys.exit(f"NoiseModelling not found at {NM_HOME}. Unpack "
                 "NoiseModelling_6.0.0.zip there or set NOISEMODELLING_HOME.")
    if not shutil.which("java") and not os.environ.get("JAVA_HOME"):
        sys.exit("Java >= 11 is required (e.g. sudo apt install openjdk-17-jre-headless).")
    cmd = [str(runner), "-w", str(work), "-s", str(HERE / "noise_pipeline.groovy"),
           "--osmPath", str(osm), "--buildingsPath", str(buildings),
           "--fencePath", str(fence), "--maxspeedPath", str(maxspeed),
           "--outDir", str(work),
           "--height", str(RECEIVER_HEIGHT_M), "--maxSrcDist", str(MAX_SRC_DIST_M),
           "--maxArea", str(MAX_TRIANGLE_M2), "--threads", str(THREADS),
           "--isoClass", ISO_CLASS]
    print("  running NoiseModelling (a few minutes)…")
    t0 = time.time()
    #ScriptRunner resolves bundled resources relative to its own folder.
    r = subprocess.run(cmd, cwd=NM_HOME, capture_output=True, text=True)
    log = work / "noisemodelling.log"
    log.write_text(r.stdout + "\n" + r.stderr)
    tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-25:])
    if r.returncode != 0 or not (work / "receivers_den.geojson").exists():
        sys.exit(f"NoiseModelling failed (exit {r.returncode}); full log in {log}\n{tail}")
    print(f"    done in {time.time() - t0:.0f}s")


#--- post-process
def to_grid(receivers, fence_poly, buildings):
    #Interpolate the Delaunay receivers onto a regular GRID_M grid in RD.
    #
    #Statistics are taken over grid cells, not receivers: the Delaunay grid is
    #densest along roads, so a mean over receivers would be pulled up toward the
    #loudest places. Cells inside buildings and outside the fence are NaN.
    from rasterio.features import geometry_mask
    from rasterio.transform import from_origin
    from scipy.interpolate import LinearNDInterpolator

    xmin, ymin, xmax, ymax = fence_poly.bounds
    xmin, ymin = np.floor(xmin / GRID_M) * GRID_M, np.floor(ymin / GRID_M) * GRID_M
    xmax, ymax = np.ceil(xmax / GRID_M) * GRID_M, np.ceil(ymax / GRID_M) * GRID_M
    nx, ny = int((xmax - xmin) / GRID_M), int((ymax - ymin) / GRID_M)
    transform = from_origin(xmin, ymax, GRID_M, GRID_M)

    xy = np.column_stack([receivers.geometry.x, receivers.geometry.y])
    interp = LinearNDInterpolator(xy, receivers["LDEN"].values)
    cx = xmin + (np.arange(nx) + 0.5) * GRID_M
    cy = ymax - (np.arange(ny) + 0.5) * GRID_M
    gx, gy = np.meshgrid(cx, cy)
    grid = interp(gx, gy).astype("float32")

    outside = geometry_mask([fence_poly], (ny, nx), transform, invert=False)
    inside_bld = geometry_mask(list(buildings.geometry), (ny, nx), transform, invert=True)
    grid[outside | inside_bld] = np.nan
    return grid, transform, (xmin, ymin, xmax, ymax)


def summary_of(values):
    v = values[np.isfinite(values)]
    return {
        "mean": round(float(v.mean()), 1),
        "p95": round(float(np.percentile(v, 95)), 1),
        "exceedance_frac": round(float((v >= BKL_STANDARD_DB).mean()), 3),
        "exceedance_db": BKL_STANDARD_DB,
        "limit_frac": round(float((v >= BKL_LIMIT_DB).mean()), 3),
        "limit_db": BKL_LIMIT_DB,
        "cells": int(v.size),
        "unit": f"open-ground cells of {GRID_M:.0f} m inside the design site + "
                f"{FENCE_BUFFER_M} m, outside buildings",
    }


PARAMS = {
    "refresh": "--refresh" in sys.argv,  #re-fetch OSM and 3DBAG
    "figure_only": "--figure-only" in sys.argv,  #redraw docs/fig_noise_<scenario>.png from the stored JSON, no NoiseModelling
}

CASES = [
    {"scenario": "baseline"},
    {"scenario": "scenario_a"},
    {"scenario": "scenario_b"},
    {"scenario": "final"},  #the Final Model; its flats on shop podiums are merged in buildings_for()
]


def run(p):
    #one case: PARAMS merged with one dict from CASES
    if p["figure_only"]:
        return redraw_figure(p["scenario"])

    import geopandas as gpd
    from shapely.geometry import box

    site = design_site_polygon()
    fence = site.buffer(FENCE_BUFFER_M)
    extent = box(*fence.buffer(DATA_PAD_M).bounds)
    print(f"Noise: {DESIGN_SITE['name']} + {FENCE_BUFFER_M} m, scenario {p['scenario']}")

    CACHE.mkdir(parents=True, exist_ok=True)
    osm = CACHE / "extent.osm"
    fp = CACHE / "footprints_3dbag.geojson"
    if p["refresh"] or not osm.exists():
        fetch_osm(extent.bounds, osm)
    if p["refresh"] or not fp.exists():
        print("  3DBAG footprints")
        fetch_footprints(extent.bounds, fp)

    work = CACHE / p["scenario"]
    if work.exists():
        shutil.rmtree(work)          #H2 database from a previous run
    work.mkdir(parents=True)
    bld = buildings_for(p["scenario"], extent, fp)
    write_geojson_rd(bld, work / "buildings.geojson")
    write_geojson_rd(gpd.GeoDataFrame({"PK": [1]}, geometry=[fence], crs="EPSG:28992"),
                     work / "fence.geojson")

    n = write_maxspeeds(osm, work / "maxspeed.csv")
    print(f"  {n} OSM roads with a posted speed limit")
    run_noisemodelling(work, osm, work / "buildings.geojson", work / "fence.geojson",
                       work / "maxspeed.csv")

    rcv = gpd.read_file(work / "receivers_den.geojson").set_crs("EPSG:28992", allow_override=True)
    rcv = rcv[np.isfinite(rcv["LDEN"])]
    print(f"  {len(rcv)} receivers, Lden {rcv['LDEN'].min():.1f}–{rcv['LDEN'].max():.1f} dB")

    grid, transform, bbox_rd = to_grid(rcv, fence, bld)
    summ = summary_of(grid)
    summ["receivers"] = int(len(rcv))
    print(f"  mean {summ['mean']} dB, p95 {summ['p95']} dB, "
          f"≥{BKL_STANDARD_DB:.0f} dB on {summ['exceedance_frac']:.0%} of open ground")

    from sky_view_factor import reproject_to_wgs84
    from rasterio.crs import CRS
    warped, bbox_wgs = reproject_to_wgs84(grid, transform, CRS.from_epsg(28992))
    values = [[None if not np.isfinite(x) else round(float(x), 1) for x in row]
              for row in warped]

    #indent=None: at 2 m the grid is ~200k values, and one per line would
    #make the file several times larger for the browser to download.
    write_processed(f"noise_{p['scenario']}.json", indent=None, payload={
        "quantity": "noise_lden_db",
        "label": "Road-traffic noise, Lden",
        "unit": "dB(A)",
        "scenario": p["scenario"],
        "level_m": RECEIVER_HEIGHT_M,
        "bbox_rd": [round(v, 1) for v in bbox_rd],
        "bbox_wgs84": [round(v, 7) for v in bbox_wgs],
        "shape": list(warped.shape),
        "values": values,
        "summary": summ,
        "method": {
            "model": "NoiseModelling 6.0.0, CNOSSOS-EU",
            "roads": "OpenStreetMap; traffic flows assigned by road type "
                     "(EU Good Practice Guide v2), not measured; speeds capped "
                     "at the OSM maxspeed",
            "diffraction": "vertical edges and over rooftops (horizontal)",
            "buildings": "3DBAG LoD0 footprints, height = roof (50th pct) - ground",
            "receivers": f"Delaunay grid at {RECEIVER_HEIGHT_M} m, design site + "
                         f"{FENCE_BUFFER_M} m",
            "max_source_distance_m": MAX_SRC_DIST_M,
            "grid_m": GRID_M,
            "max_receiver_triangle_m2": MAX_TRIANGLE_M2,
            "reference_lines": "Bkl municipal roads: 53 dB standard value, "
                               "70 dB limit value (façade values, used here as reference only)",
        },
        "limitations": [
            "Traffic is estimated from OSM road class, not counted.",
            "Roads only: no rail, tram, metro or industry.",
            "Flat ground; free-field levels at 1.75 m, not façade levels at 4 m.",
        ],
    })

    #Mapped from our own grid, not from CONTOURING_NOISE_MAP: NoiseModelling's
    #isosurface leaves holes where receivers DO have levels (checked: points
    #with 50-85 receivers within 25 m fell in no contour polygon), so the
    #contours are not exported.
    figure(grid, transform, bld, site, fence, p["scenario"], summ)
    return 0


def redraw_figure(scenario):
    #Warp the stored WGS84 grid back to a GRID_M RD grid and redraw the figure.
    import json
    from rasterio.crs import CRS
    from rasterio.transform import from_bounds, from_origin
    from rasterio.warp import Resampling, reproject

    d = json.loads((PROCESSED / f"noise_{scenario}.json").read_text())
    if d.get("_status") == "not_computed_yet":  #a stub, nothing to redraw
        print(f"noise_{scenario}.json is not computed yet, no figure")
        return 0
    src = np.array([[np.nan if v is None else v for v in row] for row in d["values"]],
                   dtype="float32")
    w, s_, e, n = d["bbox_wgs84"]
    x0, y0, x1, y1 = d["bbox_rd"]
    dst = np.full((int(round((y1 - y0) / GRID_M)), int(round((x1 - x0) / GRID_M))),
                  np.nan, dtype="float32")
    transform = from_origin(x0, y1, GRID_M, GRID_M)
    reproject(src, dst, src_transform=from_bounds(w, s_, e, n, src.shape[1], src.shape[0]),
              src_crs=CRS.from_epsg(4326), dst_transform=transform,
              dst_crs=CRS.from_epsg(28992), resampling=Resampling.nearest,
              src_nodata=np.nan, dst_nodata=np.nan)
    import geopandas as gpd
    site = design_site_polygon()
    fence = site.buffer(FENCE_BUFFER_M)
    bld = gpd.read_file(CACHE / "footprints_3dbag.geojson").set_crs(
        "EPSG:28992", allow_override=True)
    figure(dst, transform, bld, site, fence, scenario, d["summary"])
    return 0


def figure(grid, transform, buildings, site, fence, scenario, summ):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import geopandas as gpd
    from matplotlib.colors import BoundaryNorm, ListedColormap
    from matplotlib.patches import Patch

    edges = [float(x) for x in ISO_CLASS.split(",")]       #35 … 80, 200
    edges = [0.0] + edges
    labels = ([f"< {edges[1]:.0f}"] +
              [f"{a:.0f}-{b:.0f}" for a, b in zip(edges[1:-2], edges[2:-1])] +
              [f"{edges[-2]:.0f}+"])
    base = plt.get_cmap("magma_r", len(labels) + 2)
    cmap = ListedColormap([base(i + 1) for i in range(len(labels))])
    norm = BoundaryNorm(edges, cmap.N)

    xmin, ymax = transform * (0, 0)
    xmax, ymin = transform * (grid.shape[1], grid.shape[0])
    fig, ax = plt.subplots(figsize=(10, 8))
    ax.imshow(np.ma.masked_invalid(grid), cmap=cmap, norm=norm,
              extent=(xmin, xmax, ymin, ymax), interpolation="nearest")
    buildings.clip(fence.buffer(50)).plot(ax=ax, color="#555", linewidth=0)
    gpd.GeoSeries([site], crs="EPSG:28992").boundary.plot(ax=ax, color="#00b4d8", linewidth=2)
    fx0, fy0, fx1, fy1 = fence.bounds
    ax.set_xlim(fx0, fx1); ax.set_ylim(fy0, fy1)
    ax.legend(handles=[Patch(color=cmap(i), label=f"{l} dB")
                       for i, l in reversed(list(enumerate(labels)))],
              title="Lden", loc="upper left", bbox_to_anchor=(1.01, 1), frameon=False)
    ax.set_title(f"Road-traffic noise, Lden at {RECEIVER_HEIGHT_M} m: {scenario}\n"
                 f"mean {summ['mean']} dB, ≥{BKL_STANDARD_DB:.0f} dB on "
                 f"{summ['exceedance_frac']:.0%} of open ground (design site outlined)")
    ax.set_xlabel("RD x (m)"); ax.set_ylabel("RD y (m)")
    plt.tight_layout()
    out = DOCS / f"fig_noise_{scenario}.png"
    fig.savefig(out, dpi=150)
    print(f"[noise] wrote {out.relative_to(ROOT)}")


def main():
    only = sys.argv[sys.argv.index("--scenario") + 1:] if "--scenario" in sys.argv else None  #run only these cases
    for c in CASES:
        if only is None or c["scenario"] in only:
            run({**PARAMS, **c})
    return 0


if __name__ == "__main__":
    sys.exit(main())
