#!/usr/bin/env python3
"""
landuse_mix.py - land-use mix indices for the study area.

Owner: Atanas Malinkov

WHAT A MIX INDEX IS
-------------------
A single number for "how mixed are the uses here". Two are computed, because
they answer slightly different questions and disagree in useful ways:

    Shannon entropy (normalised)   H = -sum(p_i * ln p_i) / ln(N)
        0 = one use only, 1 = all N categories in equal shares.
        The standard in transport and urban-form research (Cervero & Kockelman
        1997; Frank et al. 2005). Sensitive to rare categories.

    Simpson diversity              D = 1 - sum(p_i^2)
        The chance that two randomly drawn square metres have different uses.
        Dominated by the big categories, so it barely moves when a single small
        office appears. Reported alongside as a robustness check.

WEIGHTED BY FLOOR AREA, NOT UNIT COUNT
--------------------------------------
p_i is category i's share of usable floor area. Counting units instead would let
a 40 m2 studio outweigh a 5,000 m2 supermarket. Unit-count versions are reported
too, so the difference is visible rather than hidden in a methods choice.

THE DENOMINATOR
---------------
N is the full BAG gebruiksdoel vocabulary (11 categories), fixed a priori, not
"the categories that happen to occur here". Otherwise a cell containing only
homes and one shop would score higher than a cell containing only homes purely
because its category list is shorter, and cells could not be compared with each
other or with another neighbourhood.

WHAT THIS DOES NOT COVER
------------------------
BAG holds addressable units, so parks, water, streets and squares are invisible
to it. This is a mix of BUILT FLOOR SPACE. For the built/unbuilt split use GSI
from density_height.py. See fetch_landuse.py for why CBS Bestand Bodemgebruik
was rejected for this job.

USAGE
-----
    python analysis/morphology/fetch_landuse.py     # first
    python analysis/morphology/landuse_mix.py

OUTPUTS
-------
    data/processed/landuse_grid.geojson   100 m grid, WGS84, for the app
    data/processed/landuse_summary.json   indices, composition, per-cell values
    ... and merges landuse_mix into morphology_indicators.json under "baseline"
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import (  # noqa: E402
    PROCESSED, RAW, STUDY_AREA, bbox_rd, buurt_polygons, buurt_properties,
    study_area_polygon, to_wgs,
)

#: The full BAG vocabulary. N = 11 regardless of what occurs locally.
ALL_CATEGORIES = ["residential", "retail", "office", "industry", "education",
                  "healthcare", "sport", "accommodation", "assembly",
                  "detention", "other"]
N_CATEGORIES = len(ALL_CATEGORIES)


def shannon(shares: dict[str, float], n: int = N_CATEGORIES) -> float:
    """Normalised Shannon entropy over a fixed category count."""
    tot = sum(shares.values())
    if tot <= 0 or n < 2:
        return 0.0
    h = 0.0
    for v in shares.values():
        p = v / tot
        if p > 0:
            h -= p * math.log(p)
    return h / math.log(n)


def simpson(shares: dict[str, float]) -> float:
    """1 - sum(p^2). Independent of N, so no denominator choice to defend."""
    tot = sum(shares.values())
    if tot <= 0:
        return 0.0
    return 1.0 - sum((v / tot) ** 2 for v in shares.values())


def load_units():
    path = RAW / "bag_verblijfsobjecten.geojson"
    if not path.exists():
        print(f"missing {path}\nRun: python analysis/morphology/fetch_landuse.py")
        sys.exit(1)
    feats = json.loads(path.read_text())["features"]
    x, y, cats, area = [], [], [], []
    for f in feats:
        p = f["properties"]
        x.append(f["geometry"]["coordinates"][0])
        y.append(f["geometry"]["coordinates"][1])
        cats.append(p["categories"])
        area.append(p["area_per_category_m2"])
    return np.array(x), np.array(y), cats, np.array(area, dtype="float64")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cell", type=float, default=100.0)
    ap.add_argument("--min-units", type=int, default=10,
                    help="cells with fewer units are flagged sparse; entropy on "
                         "a handful of units is noise")
    args = ap.parse_args()

    print(f"Land-use mix: {STUDY_AREA.name}")
    x, y, cats, area = load_units()
    print(f"  {len(x):,} addressable units, {N_CATEGORIES} categories in the scheme")

    # ------------------------------------------------------------ whole area
    import shapely
    in_area = shapely.contains_xy(study_area_polygon(), x, y)  #the download's box is bigger than the study area
    print(f"  {int(in_area.sum()):,} of them inside the study area")
    area_by, count_by = Counter(), Counter()
    for ok, cs, a in zip(in_area, cats, area):
        if not ok:
            continue  #whole-area figures cover the study area only, like every other indicator
        for c in cs:
            area_by[c] += a
            count_by[c] += 1
    total_area = sum(area_by.values())

    overall = {
        "shannon_area": round(shannon(area_by), 4),
        "shannon_count": round(shannon(count_by), 4),
        "simpson_area": round(simpson(area_by), 4),
        "simpson_count": round(simpson(count_by), 4),
        "n_categories_in_scheme": N_CATEGORIES,
        "n_categories_present": int(sum(1 for v in area_by.values() if v > 0)),
        "dominant": area_by.most_common(1)[0][0],
        "dominant_share": round(area_by.most_common(1)[0][1] / total_area, 4),
    }

    # ------------------------------------------------------------------ grid
    xmin, ymin, xmax, ymax = bbox_rd()
    c = args.cell
    nx = int(np.ceil((xmax - xmin) / c))
    ny = int(np.ceil((ymax - ymin) / c))
    col = ((x - xmin) // c).astype(int)
    row = ((y - ymin) // c).astype(int)
    on_grid = (col >= 0) & (col < nx) & (row >= 0) & (row < ny)  #units past the box are dropped, not clamped into edge cells
    flat = row * nx + col

    per_cell_area: dict[int, Counter] = {}
    per_cell_count: dict[int, Counter] = {}
    for i, ok, cs, a in zip(flat, on_grid, cats, area):
        if not ok:
            continue  #outside the grid
        pa = per_cell_area.setdefault(int(i), Counter())
        pc = per_cell_count.setdefault(int(i), Counter())
        for cat in cs:
            pa[cat] += a
            pc[cat] += 1

    cells, spacem = [], []
    for i, pa in sorted(per_cell_area.items()):
        pc = per_cell_count[i]
        n_units = sum(pc.values())
        r, cc = divmod(i, nx)
        x0, y0 = xmin + cc * c, ymin + r * c
        ring = [to_wgs(x0, y0), to_wgs(x0 + c, y0), to_wgs(x0 + c, y0 + c),
                to_wgs(x0, y0 + c), to_wgs(x0, y0)]
        dom = pa.most_common(1)[0]
        props = {
            "row": int(r), "col": int(cc),
            "shannon": round(shannon(pa), 4),
            "simpson": round(simpson(pa), 4),
            "n_units": int(n_units),
            "n_categories": int(sum(1 for v in pa.values() if v > 0)),
            "floor_area_m2": round(sum(pa.values()), 1),
            "dominant": dom[0],
            "dominant_share": round(dom[1] / sum(pa.values()), 3),
            "sparse": bool(n_units < args.min_units),
        }
        for cat in ALL_CATEGORIES:
            props[f"share_{cat}"] = round(pa.get(cat, 0.0) / sum(pa.values()), 4)
        cells.append({
            "type": "Feature",
            "geometry": {"type": "Polygon",
                         "coordinates": [[[round(a, 7), round(b, 7)] for a, b in ring]]},
            "properties": props,
        })
        if not props["sparse"]:
            spacem.append(props["shannon"])

    (PROCESSED / "landuse_grid.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "_source": "BAG verblijfsobjecten, aggregated by "
                   "analysis/morphology/landuse_mix.py",
        "_cell_size_m": c,
        "_grid": {"nx": nx, "ny": ny, "origin_rd": [xmin, ymin]},
        "features": cells,
    }) + "\n")
    print(f"  wrote landuse_grid.geojson ({len(cells)} cells, "
          f"{len(spacem)} with >= {args.min_units} units)")

    # ------------------------------------------- aggregate per buurt and overall
    # Both buurten are reported separately and together. The bounding box is the
    # union of their polygons, so every unit in a buurt is inside the data.
    per_buurt, combined = {}, None
    try:
        import shapely.geometry as sg
        from shapely.prepared import prep

        polys, props = buurt_polygons(), buurt_properties()

        def stats_for(geom, label, code=None):
            pg = prep(geom)
            inside = np.array([pg.contains(sg.Point(px, py)) for px, py in zip(x, y)])
            ba, bc = Counter(), Counter()
            for keep, cs, a in zip(inside, cats, area):
                if not keep:
                    continue
                for cat in cs:
                    ba[cat] += a
                    bc[cat] += 1
            if not ba:
                return None
            tot = sum(ba.values())
            return {
                "name": label,
                "code": code,
                "land_area_ha": round(geom.area / 10_000, 2),
                "inhabitants": (props.get(code, {}) or {}).get("aantalInwoners"),
                "n_units": int(sum(bc.values())),
                "floor_area_m2": round(tot, 1),
                "shannon_area": round(shannon(ba), 4),
                "shannon_count": round(shannon(bc), 4),
                "simpson_area": round(simpson(ba), 4),
                "dominant": ba.most_common(1)[0][0],
                "dominant_share": round(ba.most_common(1)[0][1] / tot, 4),
                "composition": [
                    {"category": k, "floor_area_m2": round(v, 1),
                     "share": round(v / tot, 4), "units": bc[k]}
                    for k, v in ba.most_common()
                ],
            }

        for code, name in STUDY_AREA.buurten:
            st = stats_for(polys[code], name, code)
            if st:
                per_buurt[name] = st
                print(f"  {name:12} {st['n_units']:6,} units   "
                      f"Shannon {st['shannon_area']:.3f}   Simpson {st['simpson_area']:.3f}   "
                      f"{100*st['dominant_share']:.0f}% {st['dominant']}")
        combined = stats_for(study_area_polygon(), STUDY_AREA.name)
        if combined:
            print(f"  {'combined':12} {combined['n_units']:6,} units   "
                  f"Shannon {combined['shannon_area']:.3f}   "
                  f"Simpson {combined['simpson_area']:.3f}")
    except Exception as exc:
        print(f"  ! buurt aggregates skipped ({exc})")

    arr = np.array(spacem) if spacem else np.array([0.0])
    summary = {
        "study_area": STUDY_AREA.name,
        "method": "normalised Shannon entropy and Simpson diversity over BAG "
                  "gebruiksdoel, weighted by usable floor area",
        "source": "BAG verblijfsobjecten via PDOK WFS",
        "parameters": {
            "cell_size_m": c,
            "min_units_per_cell": args.min_units,
            "n_categories_in_scheme": N_CATEGORIES,
            "categories": ALL_CATEGORIES,
            "weighting": "usable floor area (oppervlakte); multi-function units "
                         "split their area evenly across their functions",
        },
        "caveat": "BAG covers addressable units only. Parks, water, streets and "
                  "squares are invisible to it, so this is a mix of BUILT FLOOR "
                  "SPACE, not of land cover. Pair with GSI from density_height.py.",
        "overall": overall,
        "composition": [
            {"category": k, "floor_area_m2": round(v, 1),
             "share": round(v / total_area, 4), "units": count_by[k]}
            for k, v in area_by.most_common()
        ],
        "grid": {
            "n_cells": len(cells),
            "n_cells_used": int(len(spacem)),
            "shannon": {
                "mean": round(float(arr.mean()), 4),
                "std": round(float(arr.std()), 4),
                "min": round(float(arr.min()), 4),
                "median": round(float(np.median(arr)), 4),
                "max": round(float(arr.max()), 4),
            },
        },
        "per_buurt": per_buurt,
        "combined": combined,
    }
    (PROCESSED / "landuse_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("  wrote landuse_summary.json")

    mi_path = PROCESSED / "morphology_indicators.json"
    try:
        mi = json.loads(mi_path.read_text())
    except Exception:
        mi = {}
    mi.pop("_status", None)
    mi.setdefault("baseline", {})
    head = combined or overall
    mi["baseline"]["landuse_mix"] = head.get("shannon_area", overall["shannon_area"])
    mi["baseline"]["landuse_simpson"] = head.get("simpson_area", overall["simpson_area"])
    mi["_landuse_source"] = "analysis/morphology/landuse_mix.py"
    mi_path.write_text(json.dumps(mi, indent=2) + "\n")
    print("  merged landuse_mix into morphology_indicators.json")

    print()
    o = overall
    print(f"  whole study area: Shannon {o['shannon_area']:.3f} (floor area), "
          f"{o['shannon_count']:.3f} (unit count)")
    print(f"                    Simpson {o['simpson_area']:.3f}")
    print(f"  dominant use: {o['dominant']} at "
          f"{100 * o['dominant_share']:.1f}% of floor space")
    print(f"  {o['n_categories_present']} of {N_CATEGORIES} categories present")
    g = summary["grid"]["shannon"]
    print(f"  per 100 m cell: mean {g['mean']:.3f}, "
          f"range {g['min']:.3f} – {g['max']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
