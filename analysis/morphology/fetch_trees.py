#!/usr/bin/env python3
"""
fetch_trees.py - the Rotterdam municipal tree register for the study area.

SOURCE
------
Gemeente Rotterdam publishes its tree register as an ArcGIS MapServer layer:
    https://diensten.rotterdam.nl/arcgis/rest/services/SB_Infra/Bomen/MapServer/0
Points in EPSG:28992, one per managed tree, with height class, crown
size, trunk diameter, planting year and condition.

WHY NOT JUST USE THE 3D TILES?
------------------------------
The app also loads Rotterdam's ready-made 3D tree tileset, which looks good but
is a sealed mesh: you cannot query it, count it, or remove a tree for a design
scenario. This register is the underlying data, so with it we can
  * place our own 3D vegetation that scenarios can add to and subtract from,
  * feed tree crowns into the Sky View Factor and wind calculations,
  * report tree count, heights and canopy cover as indicators.
Species are not kept (dropped 2026-11-01: more detail than the project needs).

HEIGHTS
-------
HOOGTE is a class ("12-15 m."), not a number, so it is mapped to the class
midpoint and the class bounds are kept alongside it so nobody mistakes the
midpoint for a measurement. Ground level under each tree is sampled from the
AHN DTM, so the app can place trees without querying terrain at runtime.

USAGE
-----
    python analysis/morphology/fetch_ahn.py      # for the ground heights
    python analysis/morphology/fetch_trees.py

OUTPUTS
-------
    data/raw/rotterdam_trees_rd.geojson      as delivered, EPSG:28992
    data/processed/trees.geojson             WGS84, for the Cesium app
    data/processed/vegetation_summary.json   canopy cover, heights, stats
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np
import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import (  # noqa: E402
    PROCESSED, RAW, STUDY_AREA, bbox_rd, buurt_polygons,
    study_area_polygon, to_wgs,
)

SERVICE = ("https://diensten.rotterdam.nl/arcgis/rest/services"
           "/SB_Infra/Bomen/MapServer/0/query")
PAGE = 1000

#: HOOGTE class -> (low, high, representative height in metres).
HEIGHT_CLASSES = {
    "<6 m.":     (0.0, 6.0, 4.5),
    "6-9 m.":    (6.0, 9.0, 7.5),
    "9-12 m.":   (9.0, 12.0, 10.5),
    "12-15 m.":  (12.0, 15.0, 13.5),
    "15-18 m.":  (15.0, 18.0, 16.5),
    "18-24 m.":  (18.0, 24.0, 21.0),
    "> 24 m.":   (24.0, 30.0, 26.5),
}
DEFAULT_HEIGHT_M = 9.0          # used when HOOGTE is empty


def fetch_all(bbox) -> list[dict]:
    """Page through the service; it caps each response at 2000 records."""
    xmin, ymin, xmax, ymax = bbox
    base = {
        "geometry": f"{xmin},{ymin},{xmax},{ymax}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": 28992, "outSR": 28992,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": ",".join([
            "ID", "HOOGTE", "KROONOMVANG", "DIAMETER", "STAMLENGTE", "AANLEGJAAR",
            "CONDITIE", "BOOMSTATUS", "STRAAT", "WIJK", "BEHEERGROEP",
        ]),
        "returnGeometry": "true",
        "f": "json",
    }
    feats, offset = [], 0
    while True:
        params = dict(base, resultOffset=offset, resultRecordCount=PAGE)
        r = requests.get(SERVICE, params=params, timeout=120)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(data["error"])
        batch = data.get("features", [])
        feats.extend(batch)
        print(f"  fetched {len(feats)} trees…", end="\r" if sys.stdout.isatty() else "\n")
        if len(batch) < PAGE and not data.get("exceededTransferLimit"):
            break
        if not batch:
            break
        offset += len(batch)
    print(f"  fetched {len(feats)} trees{' ' * 12}")
    return feats


def load_cached(bbox) -> list[dict]:
    #rebuild service-shaped records from data/raw/rotterdam_trees_rd.geojson, for when the service is down
    xmin, ymin, xmax, ymax = bbox
    fc = json.loads((RAW / "rotterdam_trees_rd.geojson").read_text())
    feats = []
    for f in fc["features"]:
        x, y = f["geometry"]["coordinates"]
        if not (xmin <= x <= xmax and ymin <= y <= ymax):  #same envelope test the service applies
            continue
        p = f["properties"]
        feats.append({"geometry": {"x": x, "y": y}, "attributes": {  #props back to the service's field names
            "ID": p.get("id"),
            "HOOGTE": p.get("height_class"), "KROONOMVANG": p.get("crown_m"),
            "DIAMETER": p.get("trunk_diameter_cm"), "STAMLENGTE": p.get("trunk_height_m"),
            "AANLEGJAAR": p.get("planted"), "CONDITIE": p.get("condition"),
            "STRAAT": p.get("street"), "WIJK": p.get("wijk")}})
    print(f"  {len(feats)} of {len(fc['features'])} cached trees inside the box")
    return feats


def sample_ground(xs, ys):
    """Ground level (m NAP) under each tree, from the AHN DTM."""
    import rasterio
    path = RAW / "ahn_dtm_05m.tif"
    if not path.exists():
        print("  ! no AHN DTM yet: run fetch_ahn.py; using 0.0 m NAP for all trees")
        return np.zeros(len(xs), dtype="float32")

    AHN_NODATA = 3.4028234663852886e38
    with rasterio.open(path) as src:
        arr = src.read(1).astype("float32")
        arr[arr >= AHN_NODATA * 0.5] = np.nan
        arr[arr < -100] = np.nan
        t = src.transform
    # src.index() does not vectorise in rasterio 1.5, so invert the affine
    # transform ourselves: for a north-up raster a > 0 and e < 0.
    cols = np.floor((xs - t.c) / t.a).astype(int)
    rows = np.floor((ys - t.f) / t.e).astype(int)
    rows = np.clip(rows, 0, arr.shape[0] - 1)
    cols = np.clip(cols, 0, arr.shape[1] - 1)
    g = arr[rows, cols]

    # The DTM is empty under buildings and over water. Widen the search for
    # those trees until a real ground value turns up.
    missing = ~np.isfinite(g)
    for win in (2, 4, 8, 16, 32):
        if not missing.any():
            break
        idx = np.flatnonzero(missing)
        for i in idx:
            r0, r1 = max(0, rows[i] - win), min(arr.shape[0], rows[i] + win + 1)
            c0, c1 = max(0, cols[i] - win), min(arr.shape[1], cols[i] + win + 1)
            patch = arr[r0:r1, c0:c1]
            if np.isfinite(patch).any():
                g[i] = float(np.nanmedian(patch))
        missing = ~np.isfinite(g)
    if missing.any():
        g[missing] = float(np.nanmedian(arr))
        print(f"  ! {int(missing.sum())} trees fell back to the area median ground level")
    return g.astype("float32")


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pad", type=int, default=0,
                    help="extra context beyond the study-area edge, in metres")
    ap.add_argument("--from-cache", action="store_true",
                    help="use data/raw/rotterdam_trees_rd.geojson instead of the service")  #service answered 404 on 2026-10-22
    args = ap.parse_args()

    bbox = bbox_rd(args.pad)
    print(f"Rotterdam tree register: {STUDY_AREA.name}")
    try:
        feats = load_cached(bbox) if args.from_cache else fetch_all(bbox)  #cache mode skips the network
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "?"
        print(f"\n  the Rotterdam tree service returned HTTP {code}.")
        print("  This host (diensten.rotterdam.nl) goes down from time to time and")
        print("  it is nothing to do with this code: the 3D tilesets on")
        print("  www.3drotterdam.nl are a different host and are unaffected.")
        print("  data/processed/trees.geojson is committed, so the app and every")
        print("  downstream analysis keep working. Try again later.")
        return 2
    except requests.RequestException as exc:
        print(f"\n  could not reach the tree service: {type(exc).__name__} {exc}")
        print("  data/processed/trees.geojson is committed; nothing is blocked.")
        return 2
    if not feats:
        print("no trees returned")
        return 1

    xs = np.array([f["geometry"]["x"] for f in feats], dtype="float64")
    ys = np.array([f["geometry"]["y"] for f in feats], dtype="float64")
    print("  sampling ground level from the AHN DTM…")
    ground = sample_ground(xs, ys)

    raw_features, app_features = [], []
    heights, crowns, no_height = [], [], 0

    for f, x, y, gz in zip(feats, xs, ys, ground):
        a = f["attributes"]
        cls = (a.get("HOOGTE") or "").strip()
        lo, hi, mid = HEIGHT_CLASSES.get(cls, (None, None, None))
        if mid is None:
            mid = DEFAULT_HEIGHT_M
            no_height += 1
        crown = a.get("KROONOMVANG")
        crown_m = float(crown) if crown else max(2.5, mid * 0.45)
        trunk = a.get("STAMLENGTE")
        try:
            trunk_m = float(trunk)
        except (TypeError, ValueError):
            trunk_m = round(mid * 0.4, 1)
        trunk_m = min(trunk_m, mid * 0.8)

        heights.append(mid)
        crowns.append(crown_m)

        lon, lat = to_wgs(x, y)
        props = {
            "id": a.get("ID"),
            "height_class": cls or None,
            "height_m": mid,
            "height_min_m": lo,
            "height_max_m": hi,
            "crown_m": crown_m,
            "trunk_height_m": trunk_m,
            "trunk_diameter_cm": a.get("DIAMETER"),
            "planted": a.get("AANLEGJAAR"),
            "condition": a.get("CONDITIE"),
            "street": a.get("STRAAT"),
            "wijk": a.get("WIJK"),
            "ground_nap_m": round(float(gz), 2),
        }
        raw_features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(x, 3), round(y, 3)]},
            "properties": props,
        })
        app_features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]},
            "properties": props,
        })

    if not args.from_cache:  #in cache mode keep the full raw download rather than overwrite it with a subset
        (RAW / "rotterdam_trees_rd.geojson").write_text(json.dumps({
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::28992"}},
            "features": raw_features,
        }) + "\n")
        print("  wrote data/raw/rotterdam_trees_rd.geojson")

    (PROCESSED / "trees.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "_source": "Gemeente Rotterdam tree register (SB_Infra/Bomen)",
        "_note": "height_m is the midpoint of the HOOGTE class, not a measurement. "
                 "ground_nap_m is sampled from the AHN DTM; add the NAP->ellipsoid "
                 "offset before placing these in Cesium.",
        "features": app_features,
    }) + "\n")
    print("  wrote data/processed/trees.geojson")

    heights = np.array(heights)
    crowns = np.array(crowns)

    # Density and canopy cover must use the SAME extent for numerator and
    # denominator. The register is queried over the bounding box, which is
    # larger than the buurten, so counting every tree fetched against the buurt
    # area overstates density by about two thirds. Clip to the polygons.
    import shapely.geometry as sg
    from shapely.prepared import prep
    polys = buurt_polygons()
    xs_rd = np.array([f["geometry"]["coordinates"][0] for f in raw_features])
    ys_rd = np.array([f["geometry"]["coordinates"][1] for f in raw_features])

    def clip_stats(geom, label, code=None):
        pg = prep(geom)
        m = np.array([pg.contains(sg.Point(a, b)) for a, b in zip(xs_rd, ys_rd)])
        if not m.any():
            return None
        c = crowns[m]
        canopy = float(np.sum(math.pi * (c / 2.0) ** 2))
        return {
            "name": label, "code": code,
            "area_ha": round(geom.area / 10_000, 2),
            "n_trees": int(m.sum()),
            "trees_per_hectare": round(float(m.sum() / (geom.area / 10_000)), 2),
            "canopy_cover_fraction": round(canopy / geom.area, 4),
            "height_mean_m": round(float(heights[m].mean()), 2),
            "crown_mean_m": round(float(c.mean()), 2),
        }

    per_buurt = {}
    for code, name in STUDY_AREA.buurten:
        st = clip_stats(polys[code], name, code)
        if st:
            per_buurt[name] = st
    combined = clip_stats(study_area_polygon(), STUDY_AREA.name)

    area_m2 = study_area_polygon().area
    canopy_m2 = float(np.sum(math.pi * (crowns / 2.0) ** 2))

    summary = {
        "study_area": STUDY_AREA.name,
        "source": "Gemeente Rotterdam tree register, layer SB_Infra/Bomen/0",
        "_extent_note": "n_trees counts every tree in the query bounding box, "
                        "which is larger than the buurten. Density and canopy "
                        "cover live in `per_buurt` and `combined`, where the "
                        "numerator and denominator share one polygon.",
        "per_buurt": per_buurt,
        "combined": combined,
        "n_trees": len(app_features),
        "n_trees_in_buurten": (combined or {}).get("n_trees"),
        "trees_per_hectare": (combined or {}).get("trees_per_hectare"),
        "area_m2": area_m2,
        "canopy": {
            # the clipped figure, so numerator and denominator share a polygon
            "cover_fraction": (combined or {}).get("canopy_cover_fraction"),
            "total_m2_bounding_box": round(canopy_m2, 1),
            "_note": "cover_fraction is measured inside the buurten. Crowns are "
                     "modelled as circles of diameter KROONOMVANG and overlaps "
                     "are counted twice, so it is an upper bound. "
                     "total_m2_bounding_box covers the larger query box and must "
                     "not be divided by the buurt area.",
        },
        "height_m": {
            "mean": round(float(heights.mean()), 2),
            "median": round(float(np.median(heights)), 2),
            "std": round(float(heights.std()), 2),
            "max": round(float(heights.max()), 2),
            "unknown_class": no_height,
        },
        "crown_m": {
            "mean": round(float(crowns.mean()), 2),
            "median": round(float(np.median(crowns)), 2),
            "max": round(float(crowns.max()), 2),
        },
    }
    (PROCESSED / "vegetation_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("  wrote data/processed/vegetation_summary.json")

    print()
    print(f"  {summary['n_trees']:,} trees fetched over the bounding box")
    for name, st in per_buurt.items():
        print(f"     {name:12} {st['n_trees']:5,} trees  {st['trees_per_hectare']:5.1f}/ha  "
              f"canopy {100*st['canopy_cover_fraction']:4.1f}%")
    if combined:
        print(f"     {'combined':12} {combined['n_trees']:5,} trees  "
              f"{combined['trees_per_hectare']:5.1f}/ha  "
              f"canopy {100*combined['canopy_cover_fraction']:4.1f}%")
    print(f"  mean height {summary['height_m']['mean']} m, "
          f"mean crown {summary['crown_m']['mean']} m")
    print(f"  canopy cover {100 * summary['canopy']['cover_fraction']:.1f}% (upper bound)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
