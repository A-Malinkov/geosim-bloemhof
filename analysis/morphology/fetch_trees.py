#!/usr/bin/env python3
"""
fetch_trees.py — the Rotterdam municipal tree register for the study area.

SOURCE
------
Gemeente Rotterdam publishes its tree register as an ArcGIS MapServer layer:
    https://diensten.rotterdam.nl/arcgis/rest/services/SB_Infra/Bomen/MapServer/0
Points in EPSG:28992, one per managed tree, with species, height class, crown
size, trunk diameter, planting year and condition.

WHY NOT JUST USE THE 3D TILES?
------------------------------
The app also loads Rotterdam's ready-made 3D tree tileset, which looks good but
is a sealed mesh: you cannot query it, count it, or remove a tree for a design
scenario. This register is the underlying data, so with it we can
  * place our own 3D vegetation that scenarios can add to and subtract from,
  * feed tree crowns into the Sky View Factor and wind calculations,
  * report species mix and canopy cover as indicators.

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
    data/processed/vegetation_summary.json   species mix, canopy cover, stats
"""
from __future__ import annotations

import collections
import json
import math
import pathlib
import sys

import numpy as np
import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import (  # noqa: E402
    PROCESSED, RAW, STUDY_AREA, bbox_rd, to_wgs,
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
            "ID", "BOOMSORTIMENT", "BOOMSORTIMENT_NEDERLANDS", "GESLACHT",
            "HOOGTE", "KROONOMVANG", "DIAMETER", "STAMLENGTE", "AANLEGJAAR",
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


def sample_ground(xs, ys):
    """Ground level (m NAP) under each tree, from the AHN DTM."""
    import rasterio
    path = RAW / "ahn_dtm_05m.tif"
    if not path.exists():
        print("  ! no AHN DTM yet — run fetch_ahn.py; using 0.0 m NAP for all trees")
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
    bbox = bbox_rd()
    print(f"Rotterdam tree register — {STUDY_AREA.name}, "
          f"{STUDY_AREA.radius_m} m radius")
    feats = fetch_all(bbox)
    if not feats:
        print("no trees returned")
        return 1

    xs = np.array([f["geometry"]["x"] for f in feats], dtype="float64")
    ys = np.array([f["geometry"]["y"] for f in feats], dtype="float64")
    print("  sampling ground level from the AHN DTM…")
    ground = sample_ground(xs, ys)

    raw_features, app_features = [], []
    species = collections.Counter()
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

        sp = (a.get("BOOMSORTIMENT") or "onbekend").strip()
        species[sp] += 1
        heights.append(mid)
        crowns.append(crown_m)

        lon, lat = to_wgs(x, y)
        props = {
            "id": a.get("ID"),
            "species": sp,
            "species_nl": a.get("BOOMSORTIMENT_NEDERLANDS"),
            "genus": a.get("GESLACHT"),
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

    (RAW / "rotterdam_trees_rd.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::28992"}},
        "features": raw_features,
    }) + "\n")
    print(f"  wrote data/raw/rotterdam_trees_rd.geojson")

    (PROCESSED / "trees.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "_source": "Gemeente Rotterdam tree register (SB_Infra/Bomen)",
        "_note": "height_m is the midpoint of the HOOGTE class, not a measurement. "
                 "ground_nap_m is sampled from the AHN DTM; add the NAP->ellipsoid "
                 "offset before placing these in Cesium.",
        "features": app_features,
    }) + "\n")
    print(f"  wrote data/processed/trees.geojson")

    heights = np.array(heights)
    crowns = np.array(crowns)
    area_m2 = (2 * STUDY_AREA.radius_m) ** 2
    canopy_m2 = float(np.sum(math.pi * (crowns / 2.0) ** 2))

    summary = {
        "study_area": STUDY_AREA.name,
        "source": "Gemeente Rotterdam tree register, layer SB_Infra/Bomen/0",
        "n_trees": len(app_features),
        "trees_per_hectare": round(len(app_features) / (area_m2 / 10_000), 2),
        "area_m2": area_m2,
        "canopy": {
            "total_m2": round(canopy_m2, 1),
            "cover_fraction": round(canopy_m2 / area_m2, 4),
            "_note": "crowns modelled as circles of diameter KROONOMVANG; "
                     "overlapping crowns are counted twice, so this is an upper bound",
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
        "top_species": [{"species": s, "n": n,
                         "share": round(n / len(app_features), 4)}
                        for s, n in species.most_common(12)],
        "n_species": len(species),
    }
    (PROCESSED / "vegetation_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"  wrote data/processed/vegetation_summary.json")

    print()
    print(f"  {summary['n_trees']:,} trees  "
          f"({summary['trees_per_hectare']} per hectare, {summary['n_species']} species)")
    print(f"  mean height {summary['height_m']['mean']} m, "
          f"mean crown {summary['crown_m']['mean']} m")
    print(f"  canopy cover {100 * summary['canopy']['cover_fraction']:.1f}% (upper bound)")
    print("  most common:")
    for s in summary["top_species"][:5]:
        print(f"     {s['n']:5d}  {s['species']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
