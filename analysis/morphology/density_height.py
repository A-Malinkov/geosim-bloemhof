#!/usr/bin/env python3
"""
density_height.py — building density and height variation for the study area.

Owner: Atanas Malinkov

METHOD: SPACEMATRIX
-------------------
Density is not one number. A dense low-rise terrace and a tower in a park can
share a floor-space index and be nothing alike. Spacematrix (Berghauser Pont &
Haupt, TU Delft, 2010) separates them with four quantities computed over a
defined aggregation unit:

    GSI = built footprint / land area          coverage      0-1
    FSI = gross floor area / land area         intensity
    L   = FSI / GSI                            mean storeys
    OSR = (1 - GSI) / FSI                      open space per m2 of floor space

GSI and FSI together fix the other two, so a GSI-FSI scatter with L and OSR
isolines characterises the urban fabric. That plot is produced by
make_figures.py as fig_spacematrix.png.

AGGREGATION UNIT
----------------
A 100 m grid, plus one aggregate over the CBS Bloemhof polygon. The grid gives
a map; the buurt figure gives a number to quote. Spacematrix is scale-sensitive
by construction, so the cell size is reported with every result and you should
never compare an FSI at one cell size against another.

FLOORS
------
b3_bouwlagen where 3DBAG provides it. It is missing for about 44% of records --
overwhelmingly small structures, not tall ones -- so the rest fall back to
height / storey height, where storey height is MEASURED from the buildings that
have both (median ~3.08 m here) rather than assumed.

SHEDS
-----
A third of BAG "Pand" records in this area are under 15 m2: garden sheds,
garages, bergingen. They genuinely cover ground, so they count towards GSI and
FSI. They are NOT buildings in the sense that "mean building height" means, so
height statistics are computed over principal buildings only -- footprint
>= 40 m2 and height >= 4 m by default. Both filters are reported.

USAGE
-----
    python analysis/morphology/fetch_buildings.py      # first
    python analysis/morphology/density_height.py

OUTPUTS
-------
    data/processed/density_grid.geojson   100 m grid, WGS84, for the app
    data/processed/density_summary.json   headline figures + Spacematrix points
    ... and merges fsi / gsi / height_mean_m / height_std_m into
        morphology_indicators.json under "baseline"
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import (  # noqa: E402
    PROCESSED, RAW, STUDY_AREA, bbox_rd, fetch_buurt, to_wgs,
)

MIN_FOOTPRINT_M2 = 40.0     # below this it is an outbuilding, not a building
MIN_HEIGHT_M = 4.0          # single-storey garages are not "building height"


def load_buildings():
    path = RAW / "buildings_3dbag.geojson"
    if not path.exists():
        print(f"missing {path}\nRun: python analysis/morphology/fetch_buildings.py")
        sys.exit(1)
    feats = json.loads(path.read_text())["features"]
    x, y, area, floors_raw, height = [], [], [], [], []
    for f in feats:
        p = f["properties"]
        a, h = p.get("b3_opp_grond"), p.get("height_m")
        if not a or a <= 0:
            continue
        x.append(f["geometry"]["coordinates"][0])
        y.append(f["geometry"]["coordinates"][1])
        area.append(a)
        floors_raw.append(p.get("b3_bouwlagen"))
        height.append(h if h is not None else np.nan)
    return (np.array(x), np.array(y), np.array(area, dtype="float64"),
            np.array([f if f else np.nan for f in floors_raw], dtype="float64"),
            np.array(height, dtype="float64"))


def measured_storey_height(floors, height):
    """Median metres per storey, from buildings where 3DBAG gives both."""
    ok = np.isfinite(floors) & np.isfinite(height) & (floors >= 2)
    if ok.sum() < 30:
        return 3.0, 0
    return float(np.median(height[ok] / floors[ok])), int(ok.sum())


def describe(v):
    v = v[np.isfinite(v)]
    if v.size == 0:
        return {}
    return {"n": int(v.size),
            "mean": round(float(v.mean()), 3),
            "std": round(float(v.std()), 3),
            "median": round(float(np.median(v)), 3),
            "p10": round(float(np.percentile(v, 10)), 3),
            "p90": round(float(np.percentile(v, 90)), 3),
            "max": round(float(v.max()), 3)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cell", type=float, default=100.0, help="grid cell size, m")
    ap.add_argument("--min-footprint", type=float, default=MIN_FOOTPRINT_M2)
    ap.add_argument("--min-height", type=float, default=MIN_HEIGHT_M)
    ap.add_argument("--min-buildings", type=int, default=3,
                    help="cells with fewer buildings are reported but flagged sparse")
    args = ap.parse_args()

    print(f"Building density and height variation — {STUDY_AREA.name}")
    x, y, area, floors_raw, height = load_buildings()
    print(f"  {len(x):,} buildings with a footprint area")

    sh, n_sh = measured_storey_height(floors_raw, height)
    print(f"  storey height measured from {n_sh:,} buildings: {sh:.2f} m/floor")

    floors = floors_raw.copy()
    missing = ~np.isfinite(floors)
    est = np.maximum(1.0, np.round(height / sh))
    floors[missing] = est[missing]
    floors[~np.isfinite(floors)] = 1.0
    print(f"  floors: {int((~missing).sum()):,} from 3DBAG, "
          f"{int(missing.sum()):,} estimated from height")

    gfa = area * floors

    principal = (area >= args.min_footprint) & (height >= args.min_height)
    print(f"  principal buildings (>= {args.min_footprint:.0f} m2 and "
          f">= {args.min_height:.0f} m): {int(principal.sum()):,} "
          f"({100 * principal.mean():.0f}%), holding "
          f"{100 * area[principal].sum() / area.sum():.0f}% of the built area")

    # ---------------------------------------------------------------- grid
    xmin, ymin, xmax, ymax = bbox_rd()
    c = args.cell
    nx = int(np.ceil((xmax - xmin) / c))
    ny = int(np.ceil((ymax - ymin) / c))
    col = np.clip(((x - xmin) // c).astype(int), 0, nx - 1)
    row = np.clip(((y - ymin) // c).astype(int), 0, ny - 1)
    flat = row * nx + col
    ncell = nx * ny
    cell_area = c * c

    sum_area = np.bincount(flat, weights=area, minlength=ncell)
    sum_gfa = np.bincount(flat, weights=gfa, minlength=ncell)
    count = np.bincount(flat, minlength=ncell)

    pm = principal & np.isfinite(height)
    p_flat, p_h = flat[pm], height[pm]
    p_cnt = np.bincount(p_flat, minlength=ncell)
    p_sum = np.bincount(p_flat, weights=p_h, minlength=ncell)
    p_sq = np.bincount(p_flat, weights=p_h ** 2, minlength=ncell)
    with np.errstate(invalid="ignore", divide="ignore"):
        h_mean = np.where(p_cnt > 0, p_sum / np.maximum(p_cnt, 1), np.nan)
        h_var = np.where(p_cnt > 1, p_sq / np.maximum(p_cnt, 1) - h_mean ** 2, np.nan)
        h_std = np.sqrt(np.maximum(h_var, 0))
        gsi = sum_area / cell_area
        fsi = sum_gfa / cell_area
        L = np.where(gsi > 0, fsi / np.maximum(gsi, 1e-9), np.nan)
        osr = np.where(fsi > 0, (1 - gsi) / np.maximum(fsi, 1e-9), np.nan)

    print(f"  grid {nx} x {ny} cells of {c:.0f} m; "
          f"{int((count > 0).sum())} contain buildings")

    # ------------------------------------------------- grid -> GeoJSON (WGS84)
    cells = []
    for i in range(ncell):
        if count[i] == 0:
            continue
        r, cc = divmod(i, nx)
        x0, y0 = xmin + cc * c, ymin + r * c
        ring = [to_wgs(x0, y0), to_wgs(x0 + c, y0),
                to_wgs(x0 + c, y0 + c), to_wgs(x0, y0 + c), to_wgs(x0, y0)]
        cells.append({
            "type": "Feature",
            "geometry": {"type": "Polygon",
                         "coordinates": [[[round(a, 7), round(b, 7)] for a, b in ring]]},
            "properties": {
                # grid indices travel with the cell: the RD->WGS84 transform is
                # not axis-aligned, so the row/col cannot be recovered from the
                # lon/lat afterwards without them
                "row": int(r),
                "col": int(cc),
                "gsi": round(float(gsi[i]), 4),
                "fsi": round(float(fsi[i]), 4),
                "layers": None if not np.isfinite(L[i]) else round(float(L[i]), 2),
                "osr": None if not np.isfinite(osr[i]) else round(float(osr[i]), 3),
                "height_mean_m": None if not np.isfinite(h_mean[i]) else round(float(h_mean[i]), 2),
                "height_std_m": None if not np.isfinite(h_std[i]) else round(float(h_std[i]), 2),
                "n_buildings": int(count[i]),
                "n_principal": int(p_cnt[i]),
                "sparse": bool(count[i] < args.min_buildings),
            },
        })
    (PROCESSED / "density_grid.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "_source": "3DBAG v20250903, aggregated by analysis/morphology/density_height.py",
        "_cell_size_m": c,
        "_grid": {"nx": nx, "ny": ny, "origin_rd": [xmin, ymin]},
        "features": cells,
    }) + "\n")
    print(f"  wrote density_grid.geojson ({len(cells)} cells)")

    # -------------------------------------------------- aggregate over Bloemhof
    buurt_stats, buurt_props = None, {}
    try:
        import shapely.geometry as sg
        from shapely.prepared import prep
        geom, buurt_props = fetch_buurt()

        # The denominator MUST be the part of the buurt we actually surveyed.
        # The study square covers only ~75% of Bloemhof, so dividing the
        # buildings we found by the buurt's full area would understate density
        # by about a third. Intersect first, then use that area.
        survey = geom.intersection(sg.box(*bbox_rd()))
        coverage = survey.area / geom.area if geom.area else 0.0
        pgeom = prep(survey)
        inside = np.array([pgeom.contains(sg.Point(px, py)) for px, py in zip(x, y)])
        land = survey.area
        if coverage < 0.999:
            print(f"  note: the study square covers {100 * coverage:.1f}% of "
                  f"{buurt_props.get('buurtnaam')}; density is computed over that "
                  f"part only ({land / 10_000:.1f} ha of "
                  f"{geom.area / 10_000:.1f} ha)")
        if inside.sum() > 0:
            bp = inside & principal & np.isfinite(height)
            buurt_stats = {
                "name": buurt_props.get("buurtnaam"),
                "code": STUDY_AREA.cbs_buurt,
                "buurt_area_ha": round(float(geom.area) / 10_000, 2),
                "surveyed_area_ha": round(float(land) / 10_000, 2),
                "coverage_fraction": round(float(coverage), 4),
                "_denominator_note": "GSI and FSI use the surveyed area (buurt "
                                     "clipped to the study square), not the full "
                                     "buurt, so they are not diluted by the part "
                                     "outside the study area.",
                "land_area_m2": round(float(land), 1),
                "land_area_ha": round(float(land) / 10_000, 2),
                "n_buildings": int(inside.sum()),
                "n_principal": int(bp.sum()),
                "gsi": round(float(area[inside].sum() / land), 4),
                "fsi": round(float(gfa[inside].sum() / land), 4),
                "height_m": describe(height[bp]),
            }
            g_, f_ = buurt_stats["gsi"], buurt_stats["fsi"]
            buurt_stats["layers"] = round(f_ / g_, 2) if g_ else None
            buurt_stats["osr"] = round((1 - g_) / f_, 3) if f_ else None
            print(f"  {buurt_stats['name']}: {buurt_stats['n_buildings']:,} buildings "
                  f"on {buurt_stats['land_area_ha']} ha surveyed")
    except Exception as exc:
        print(f"  ! buurt aggregate skipped ({exc})")

    # ------------------------------------------------------------- summary
    valid = count >= args.min_buildings
    summary = {
        "study_area": STUDY_AREA.name,
        "method": "Spacematrix (Berghauser Pont & Haupt 2010): GSI, FSI, L, OSR",
        "source": "3DBAG v20250903 (TU Delft), attributes b3_opp_grond / "
                  "b3_bouwlagen / b3_h_dak_50p / b3_h_maaiveld",
        "parameters": {
            "cell_size_m": c,
            "storey_height_m": round(sh, 3),
            "storey_height_source": f"median of {n_sh} buildings with both "
                                    f"b3_bouwlagen and a height",
            "principal_min_footprint_m2": args.min_footprint,
            "principal_min_height_m": args.min_height,
            "min_buildings_per_cell": args.min_buildings,
        },
        "counts": {
            "buildings_total": int(len(x)),
            "buildings_principal": int(principal.sum()),
            "floors_from_3dbag": int((~missing).sum()),
            "floors_estimated": int(missing.sum()),
            "outbuilding_share_of_count": round(float(1 - principal.mean()), 3),
            "outbuilding_share_of_built_area":
                round(float(1 - area[principal].sum() / area.sum()), 3),
        },
        "grid": {
            "n_cells_with_buildings": int((count > 0).sum()),
            "n_cells_used": int(valid.sum()),
            "gsi": describe(gsi[valid]),
            "fsi": describe(fsi[valid]),
            "layers": describe(L[valid]),
            "osr": describe(osr[valid]),
            "height_mean_m": describe(h_mean[valid]),
            "height_std_m": describe(h_std[valid]),
        },
        "buurt": buurt_stats,
        "spacematrix": [
            {"gsi": round(float(gsi[i]), 4), "fsi": round(float(fsi[i]), 4),
             "height_mean_m": None if not np.isfinite(h_mean[i]) else round(float(h_mean[i]), 2)}
            for i in range(ncell) if valid[i]
        ],
    }
    (PROCESSED / "density_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("  wrote density_summary.json")

    # merge the headline numbers into the shared indicators file
    mi_path = PROCESSED / "morphology_indicators.json"
    try:
        mi = json.loads(mi_path.read_text())
    except Exception:
        mi = {}
    mi.pop("_status", None)
    mi.setdefault("baseline", {})
    head = buurt_stats or {}
    mi["baseline"]["fsi"] = head.get("fsi", summary["grid"]["fsi"].get("mean"))
    mi["baseline"]["gsi"] = head.get("gsi", summary["grid"]["gsi"].get("mean"))
    mi["baseline"]["layers"] = head.get("layers")
    mi["baseline"]["osr"] = head.get("osr")
    hstat = head.get("height_m") or summary["grid"]["height_mean_m"]
    mi["baseline"]["height_mean_m"] = hstat.get("mean")
    mi["baseline"]["height_std_m"] = hstat.get("std")
    mi["_density_source"] = "analysis/morphology/density_height.py"
    mi_path.write_text(json.dumps(mi, indent=2) + "\n")
    print("  merged fsi / gsi / height into morphology_indicators.json")

    print()
    if buurt_stats:
        b = buurt_stats
        print(f"  {b['name']} over the {b['surveyed_area_ha']} ha surveyed "
              f"({100 * b['coverage_fraction']:.0f}% of the buurt):")
        print(f"     GSI {b['gsi']:.3f}   FSI {b['fsi']:.3f}   "
              f"L {b['layers']:.2f} storeys   OSR {b['osr']:.2f}")
        h = b["height_m"]
        print(f"     building height {h['mean']:.1f} m mean, "
              f"sigma {h['std']:.1f} m, max {h['max']:.1f} m "
              f"({h['n']:,} principal buildings)")
    g = summary["grid"]
    print(f"  across {g['n_cells_used']} grid cells of {c:.0f} m:")
    print(f"     GSI {g['gsi']['mean']:.3f} +/- {g['gsi']['std']:.3f}   "
          f"FSI {g['fsi']['mean']:.3f} +/- {g['fsi']['std']:.3f}")
    print(f"     height variation within a cell: sigma "
          f"{g['height_std_m']['mean']:.2f} m on average, "
          f"up to {g['height_std_m']['max']:.2f} m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
