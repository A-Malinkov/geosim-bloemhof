#!/usr/bin/env python3
"""
sky_view_factor.py — Sky View Factor for the study area from AHN.

WHAT SVF IS
-----------
The fraction of the sky hemisphere visible from a point. 1.0 = open field,
0.0 = fully enclosed. It drives how much longwave radiation a street can lose
at night, so it is the standard first indicator for urban heat, and it is also
a direct read on how enclosed a street feels.

HOW IT IS COMPUTED HERE
-----------------------
The multi-directional horizon-angle method (Zaksek, Ostir & Kokalj 2011,
"Sky-View Factor as a Relief Visualization Technique", Remote Sensing 3:398-415;
the same approach SAGA, RVT and SOLWEIG use).

For each cell, and for each of N compass directions, we walk outwards to a
search radius and record the greatest elevation angle of the obstruction
surface -- the horizon angle gamma. Then:

    SVF_radiation = (1/N) * sum( cos^2(gamma_i) )      <- reported as "SVF"
    SVF_geometric = 1 - (1/N) * sum( sin(gamma_i) )

Both are in the literature and they are not the same number. The cos^2 form is
cosine-weighted, i.e. it weights sky near the zenith more heavily, which is what
matters for radiation exchange; it is the one urban climatology means by "SVF".
The 1-sin form is the plain solid-angle fraction used in relief visualisation.
We write both so nobody has to guess which one a figure used.

PEDESTRIAN LEVEL
----------------
The observer sits 1.75 m above the GROUND (AHN DTM), not on top of the surface
model, because we care about what a person in the street sees. The obstruction
surface is the DSM, which includes buildings and tree crowns.

Note on AHN: the DTM is empty under buildings (only ~10% of building pixels
have a DTM value), so ground elevation is filled from the surrounding terrain.
Statistics are reported separately for open ground -- the pixels that are
actually street, garden and square -- since SVF on a roof is not meaningful.

USAGE
-----
    python analysis/morphology/fetch_ahn.py          # get the rasters first
    python analysis/morphology/sky_view_factor.py

    # quicker, coarser
    python analysis/morphology/sky_view_factor.py --resolution 1.0 --directions 8

    # a design scenario: demolition and new blocks burned into the DSM first
    python analysis/morphology/sky_view_factor.py --scenario scenario_a

OUTPUTS
-------
    data/processed/svf.tif              SVF raster (cos^2 form), EPSG:28992
    data/processed/svf_geometric.tif    SVF raster (1-sin form)
    data/processed/svf_overlay.png      colour ramp for draping in Cesium
    data/processed/svf_summary.json     statistics for the dashboard
    (a scenario run writes the same names with _<scenario> appended)

Figures for the report come from make_figures.py, run that afterwards.
    ... and merges svf_mean into morphology_indicators.json under "baseline"
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

import numpy as np
import rasterio
from rasterio.enums import Resampling

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import (  # noqa: E402
    PROCESSED, RAW, STUDY_AREA, bbox_rd, bbox_wgs, buurt_polygons,
    buurt_properties, design_site_polygon, study_area_polygon,
)

AHN_NODATA = 3.4028234663852886e38
OBSERVER_HEIGHT_M = 1.75      # eye level of a standing person


# --------------------------------------------------------------------- input
def load_raster(path: pathlib.Path, resolution: float | None):
    """Read a band as float32 with nodata as NaN, optionally resampled."""
    with rasterio.open(path) as src:
        if resolution and abs(resolution - src.res[0]) > 1e-9:
            scale = src.res[0] / resolution
            w, h = int(src.width * scale), int(src.height * scale)
            a = src.read(1, out_shape=(1, h, w),
                         resampling=Resampling.average).astype("float32")
            transform = src.transform * src.transform.scale(src.width / w,
                                                            src.height / h)
        else:
            a = src.read(1).astype("float32")
            transform = src.transform
        crs = src.crs
    a[a >= AHN_NODATA * 0.5] = np.nan
    a[a < -100] = np.nan
    return a, transform, crs


def fill_nan_nearest(a: np.ndarray, max_iter: int = 400) -> np.ndarray:
    """
    Fill NaN holes by iterative nearest-neighbour dilation.

    AHN leaves water and some building interiors empty. Left as NaN they act as
    infinitely deep pits, and a horizon search would see straight through them.
    Filling with the surrounding surface is the conservative choice.
    """
    out = a.copy()
    nan = ~np.isfinite(out)
    if not nan.any():
        return out
    for _ in range(max_iter):
        nan = ~np.isfinite(out)
        if not nan.any():
            break
        # average of the four neighbours that are known
        acc = np.zeros_like(out)
        cnt = np.zeros(out.shape, dtype="float32")
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            sh = shift(out, dr, dc)
            ok = np.isfinite(sh)
            acc[ok] += sh[ok]
            cnt[ok] += 1
        fillable = nan & (cnt > 0)
        if not fillable.any():
            break
        out[fillable] = acc[fillable] / cnt[fillable]
    # anything still empty (a huge hole) gets the global median
    still = ~np.isfinite(out)
    if still.any():
        out[still] = np.nanmedian(a)
    return out


def shift(a: np.ndarray, drow: int, dcol: int) -> np.ndarray:
    """a shifted so that out[i, j] == a[i + drow, j + dcol]; edges become NaN."""
    out = np.full_like(a, np.nan)
    h, w = a.shape
    sr0, sr1 = max(0, drow), h + min(0, drow)
    dr0, dr1 = max(0, -drow), h - max(0, drow)
    sc0, sc1 = max(0, dcol), w + min(0, dcol)
    dc0, dc1 = max(0, -dcol), w - max(0, dcol)
    if sr0 < sr1 and sc0 < sc1:
        out[dr0:dr1, dc0:dc1] = a[sr0:sr1, sc0:sc1]
    return out


# ----------------------------------------------------------------- algorithm
def sky_view_factor(surface: np.ndarray, observer: np.ndarray, cellsize: float,
                    radius_m: float = 100.0, n_directions: int = 16,
                    n_steps: int = 48, verbose: bool = True):
    """
    Horizon-angle SVF.

    surface   obstruction elevations (DSM), metres, no NaN
    observer  observer elevations, metres, no NaN (ground + eye height)
    returns   (svf_radiation, svf_geometric), both float32 in [0, 1]
    """
    radius_px = max(2, int(round(radius_m / cellsize)))
    # Geometric spacing: dense close in, sparse far out. Nearby geometry sets
    # the horizon angle, distant geometry only refines it.
    steps = np.unique(np.round(np.geomspace(1, radius_px, n_steps)).astype(int))

    acc_cos2 = np.zeros(surface.shape, dtype="float32")
    acc_sin = np.zeros(surface.shape, dtype="float32")

    t0 = time.time()
    for d in range(n_directions):
        az = 2.0 * np.pi * d / n_directions          # 0 = north, clockwise
        max_tan = np.full(surface.shape, -np.inf, dtype="float32")
        seen: set[tuple[int, int]] = set()
        for r in steps:
            drow = int(round(-r * np.cos(az)))       # north is -row
            dcol = int(round(r * np.sin(az)))
            if (drow, dcol) in seen or (drow == 0 and dcol == 0):
                continue
            seen.add((drow, dcol))
            dist = np.hypot(drow, dcol) * cellsize
            tan = (shift(surface, drow, dcol) - observer) / dist
            np.fmax(max_tan, tan, out=max_tan)       # fmax ignores NaN
        max_tan[~np.isfinite(max_tan)] = 0.0
        np.clip(max_tan, 0.0, None, out=max_tan)     # below horizontal = open sky
        gamma = np.arctan(max_tan)
        acc_cos2 += np.cos(gamma, dtype="float32") ** 2
        acc_sin += np.sin(gamma, dtype="float32")
        if verbose and sys.stdout.isatty():
            print(f"    direction {d + 1}/{n_directions} "
                  f"({np.degrees(az):5.1f} deg)  {time.time() - t0:5.1f}s", end="\r")
    if verbose:
        print(f"    {n_directions} directions, {len(steps)} radii, "
              f"{time.time() - t0:.1f}s{' ' * 20}")

    svf_rad = (acc_cos2 / n_directions).astype("float32")
    svf_geo = (1.0 - acc_sin / n_directions).astype("float32")
    return np.clip(svf_rad, 0, 1), np.clip(svf_geo, 0, 1)


# ------------------------------------------------------------------- outputs
def write_tif(path, arr, transform, crs):
    with rasterio.open(path, "w", driver="GTiff", height=arr.shape[0],
                       width=arr.shape[1], count=1, dtype="float32",
                       crs=crs, transform=transform, nodata=np.nan,
                       compress="deflate") as dst:
        dst.write(arr.astype("float32"), 1)
    print(f"  wrote {path.name}")


def reproject_to_wgs84(arr, transform, crs):
    """
    Warp an RD-gridded array to EPSG:4326.

    Needed because the overlay is draped on a lon/lat RECTANGLE in Cesium, and
    the RD square is not one: RD New is rotated slightly against WGS84, so the
    square's four corners do not share two longitudes. Taking the SW and NE
    corners as the rectangle misplaces the image by up to ~30 m — a third of a
    block. Warping first makes the rectangle exact.

    Returns (array, (west, south, east, north)).
    """
    from rasterio.warp import calculate_default_transform, reproject, Resampling

    h, w = arr.shape
    dst_crs = "EPSG:4326"
    left, top = transform * (0, 0)
    right, bottom = transform * (w, h)
    dst_transform, dw, dh = calculate_default_transform(
        crs, dst_crs, w, h, left=left, bottom=bottom, right=right, top=top)
    dst = np.full((dh, dw), np.nan, dtype="float32")
    reproject(source=arr, destination=dst,
              src_transform=transform, src_crs=crs,
              dst_transform=dst_transform, dst_crs=dst_crs,
              src_nodata=np.nan, dst_nodata=np.nan,
              resampling=Resampling.bilinear)
    west, north = dst_transform * (0, 0)
    east, south = dst_transform * (dw, dh)
    return dst, (west, south, east, north)


def write_overlay_png(path, arr, mask=None, max_px: int = 1400):
    """
    Colour-ramped PNG with transparency, for draping on the globe.

    Capped at `max_px` on the long side. At full 0.5 m resolution this would be
    3000x3000 and about 6 MB, which is a lot to hand a browser for what is only
    a visual overlay -- and it is the one derived raster small enough to keep in
    git, so the SVF layer works on a fresh clone. The GeoTIFFs keep full
    resolution and are gitignored.
    """
    import matplotlib
    matplotlib.use("Agg")
    from PIL import Image

    norm = np.clip((arr - 0.2) / 0.8, 0, 1)          # stretch 0.2..1.0
    cmap = matplotlib.colormaps["viridis"]           # cm.get_cmap went in mpl 3.9
    rgba = (cmap(np.nan_to_num(norm)) * 255).astype("uint8")
    alpha = np.where(np.isfinite(arr), 200, 0).astype("uint8")
    if mask is not None:
        alpha = np.where(mask, alpha, 40).astype("uint8")
    rgba[..., 3] = alpha

    img = Image.fromarray(rgba, mode="RGBA")
    if max(img.size) > max_px:
        scale = max_px / max(img.size)
        img = img.resize((int(img.width * scale), int(img.height * scale)),
                         Image.LANCZOS)
    img.save(path, optimize=True)
    print(f"  wrote {path.name}  ({img.width}x{img.height}, "
          f"{path.stat().st_size / 1e6:.1f} MB)")


def describe(a: np.ndarray) -> dict:
    v = a[np.isfinite(a)]
    if v.size == 0:
        return {}
    p = np.percentile(v, [5, 25, 50, 75, 95])
    return {
        "n_pixels": int(v.size),
        "mean": round(float(v.mean()), 4),
        "std": round(float(v.std()), 4),
        "min": round(float(v.min()), 4),
        "p05": round(float(p[0]), 4),
        "p25": round(float(p[1]), 4),
        "median": round(float(p[2]), 4),
        "p75": round(float(p[3]), 4),
        "p95": round(float(p[4]), 4),
        "max": round(float(v.max()), 4),
    }


# ---------------------------------------------------------------------- main
COMBINED = "_combined"  #key of the whole-study-area stats while they are collected


def main() -> int:
    ap = argparse.ArgumentParser(description="Sky View Factor from AHN",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--resolution", type=float, default=0.5,
                    help="working cell size in metres (0.5 = AHN native)")
    ap.add_argument("--radius", type=float, default=100.0,
                    help="horizon search radius in metres")
    ap.add_argument("--directions", type=int, default=32)
    ap.add_argument("--steps", type=int, default=48,
                    help="radial samples per direction")
    ap.add_argument("--observer-height", type=float, default=OBSERVER_HEIGHT_M)
    ap.add_argument("--no-clip-buurt", action="store_true",
                    help="skip the CBS neighbourhood-boundary statistics")
    ap.add_argument("--scenario", default="baseline",
                    choices=["baseline", "scenario_a", "scenario_b", "final"])  #final: the Rhino Final Model, 2026-10-28  #which built environment
    args = ap.parse_args()
    sfx = "" if args.scenario == "baseline" else f"_{args.scenario}"  #baseline keeps the original file names

    dsm_path, dtm_path = RAW / "ahn_dsm_05m.tif", RAW / "ahn_dtm_05m.tif"
    for p in (dsm_path, dtm_path):
        if not p.exists():
            print(f"missing {p}. Run: python analysis/morphology/fetch_ahn.py")
            return 1

    print(f"Sky View Factor — {STUDY_AREA.name}, {args.scenario}")
    print(f"  cell {args.resolution} m | radius {args.radius} m | "
          f"{args.directions} directions | observer {args.observer_height} m above ground")

    dsm, transform, crs = load_raster(dsm_path, args.resolution)
    dtm, _, _ = load_raster(dtm_path, args.resolution)
    #the crop below assumes the AHN rasters span the study area + 150 m; a stale download
    #(e.g. from before the study area changed) would silently analyse the wrong area
    have = (transform.c, transform.f + dsm.shape[0] * transform.e,
            transform.c + dsm.shape[1] * transform.a, transform.f)
    want = bbox_rd(150)
    if max(abs(a - b) for a, b in zip(have, want)) > 2 * args.resolution + 1:
        print(f"  AHN rasters span {[round(v) for v in have]}, but the study area + 150 m is "
              f"{[round(v) for v in want]}.\n  Re-download: python analysis/morphology/fetch_ahn.py --force")
        return 1
    print(f"  grid {dsm.shape[1]} x {dsm.shape[0]}")
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scenarios"))
    from scenario_world import burn_into_rasters  #demolition + new blocks, no-op for baseline
    dsm, dtm = burn_into_rasters(dsm, dtm, transform, args.scenario)

    # open ground = DTM known and the surface is within 2 m of it
    ndsm = dsm - dtm
    open_ground = np.isfinite(ndsm) & (ndsm < 2.0)
    print(f"  open ground (street / garden / square): {100 * open_ground.mean():.1f}% of cells")

    print("  filling nodata …")
    surface = fill_nan_nearest(dsm)                     # what blocks the sky
    ground = fill_nan_nearest(dtm)                      # where a person stands
    # under buildings the DTM is empty; the fill gives surrounding street level,
    # which is what we want for the observer.
    observer = ground + args.observer_height

    print("  computing horizon angles …")
    svf_rad, svf_geo = sky_view_factor(
        surface, observer, args.resolution,
        radius_m=args.radius, n_directions=args.directions, n_steps=args.steps)

    # crop off the context padding so the outputs cover the study area only
    pad_px = int(round(150 / args.resolution))
    sl = (slice(pad_px, -pad_px), slice(pad_px, -pad_px))
    svf_rad_c, svf_geo_c, og_c = svf_rad[sl], svf_geo[sl], open_ground[sl]
    transform_c = transform * transform.translation(pad_px, pad_px)

    # ---- statistics per buurt and overall ----------------------------------
    # The raster covers the bounding box of both buurten, which also takes in the
    # Maashaven and slivers of neighbouring buurten. Open water has SVF ~1.0 and
    # would drag the mean up, so every headline figure is clipped to real buurt
    # land and each buurt is reported separately.
    masks, buurt_stats = {}, {}
    if not args.no_clip_buurt:
        try:
            from rasterio.features import geometry_mask
            polys, props = buurt_polygons(), buurt_properties()
            for code, name in STUDY_AREA.buurten:
                m = ~geometry_mask([polys[code]], out_shape=svf_rad_c.shape,
                                   transform=transform_c, invert=False)
                masks[name] = m
                print(f"  {name:12} covers {100 * m.mean():5.1f}% of the raster")
            m_all = ~geometry_mask([study_area_polygon()], out_shape=svf_rad_c.shape,
                                   transform=transform_c, invert=False)
            masks[COMBINED] = m_all  #reserved key: a one-buurt study area shares its buurt's name
            for name, m in masks.items():
                code = next((c for c, n in STUDY_AREA.buurten if n == name), None)
                buurt_stats[name] = {
                    "code": code,
                    "inhabitants": (props.get(code, {}) or {}).get("aantalInwoners"),
                    "raster_coverage_fraction": round(float(m.mean()), 4),
                    "open_ground": describe(np.where(og_c & m, svf_rad_c, np.nan)),
                    "open_ground_geometric": describe(
                        np.where(og_c & m, svf_geo_c, np.nan)),
                }
            #the design site, where the scenarios differ
            m_site = ~geometry_mask([design_site_polygon()], out_shape=svf_rad_c.shape,
                                    transform=transform_c, invert=False)
            buurt_stats["_design_site"] = {"open_ground": describe(np.where(og_c & m_site, svf_rad_c, np.nan))}
        except Exception as exc:
            print(f"  ! buurt clipping skipped ({exc})")

    overlay_arr, overlay_bbox = reproject_to_wgs84(svf_rad_c, transform_c, crs)

    site_stats = buurt_stats.pop("_design_site", None)  #kept out of the per-buurt table
    stats = {
        "study_area": STUDY_AREA.name,
        "scenario": args.scenario,  #which built environment this is
        "method": "multi-directional horizon angle (Zaksek, Ostir & Kokalj 2011)",
        "formulation": {
            "svf": "mean(cos^2(gamma)) — cosine-weighted, urban-climate convention",
            "svf_geometric": "1 - mean(sin(gamma)) — plain solid-angle fraction",
        },
        "parameters": {
            "cell_size_m": args.resolution,
            "search_radius_m": args.radius,
            "n_directions": args.directions,
            "n_radial_steps": args.steps,
            "observer_height_m": args.observer_height,
            "surface": "AHN dsm_05m (buildings + tree crowns)"
                       + ("" if args.scenario == "baseline" else
                          f", with the {args.scenario} demolition and massing burned in"),  #see scenario_world.py
            "ground": "AHN dtm_05m, gaps filled by nearest-neighbour dilation",
        },
        "bbox_rd": [round(v, 1) for v in bbox_rd()],
        # The bbox the PNG is actually drawn on, from the warp — NOT the RD
        # square reprojected corner-to-corner, which is off by up to ~30 m
        # because RD New is rotated against WGS84.
        "bbox_wgs84": [round(v, 7) for v in overlay_bbox],
        "bbox_wgs84_rd_corners": [round(v, 7) for v in bbox_wgs()],
        "all_cells": describe(svf_rad_c),
        "open_ground": describe(np.where(og_c, svf_rad_c, np.nan)),
        "open_ground_geometric": describe(np.where(og_c, svf_geo_c, np.nan)),
        "per_buurt": {k: v for k, v in buurt_stats.items() if k != COMBINED},
        "combined": buurt_stats.get(COMBINED),
        "design_site": site_stats,  #open ground inside the design site
        "histogram": {
            "bin_edges": [round(x, 3) for x in np.linspace(0, 1, 41).tolist()],
            "counts": np.histogram(svf_rad_c[og_c & np.isfinite(svf_rad_c)],
                                   bins=40, range=(0, 1))[0].tolist(),
        },
    }

    print("  writing outputs …")
    write_tif(PROCESSED / f"svf{sfx}.tif", svf_rad_c, transform_c, crs)  #scenario runs get a suffix
    write_tif(PROCESSED / f"svf_geometric{sfx}.tif", svf_geo_c, transform_c, crs)

    # The GeoTIFFs stay in RD. The browser overlay was warped to EPSG:4326 above,
    # so the lon/lat rectangle Cesium drapes it on is genuinely where the data is.
    write_overlay_png(PROCESSED / f"svf_overlay{sfx}.png", overlay_arr)
    print(f"  overlay warped to EPSG:4326, bbox "
          f"{[round(v, 6) for v in overlay_bbox]}")

    (PROCESSED / f"svf_summary{sfx}.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(f"  wrote svf_summary{sfx}.json")

    # merge the headline number into the shared morphology indicators file
    mi_path = PROCESSED / "morphology_indicators.json"
    try:
        mi = json.loads(mi_path.read_text())
    except Exception:
        mi = {}
    mi.pop("_status", None)
    mi.setdefault(args.scenario, {})  #keyed by scenario
    headline = ((stats.get("combined") or {}).get("open_ground")
                or stats["open_ground"])
    mi[args.scenario]["svf_mean"] = headline["mean"]
    mi[args.scenario]["svf_median"] = headline["median"]
    if site_stats:
        mi[args.scenario]["svf_site_mean"] = site_stats["open_ground"]["mean"]  #design site only, where scenarios differ
    mi["_svf_source"] = "analysis/morphology/sky_view_factor.py"
    mi_path.write_text(json.dumps(mi, indent=2) + "\n")
    print("  merged svf_mean into morphology_indicators.json")
    print("  (run make_figures.py for the report figures)")

    og = stats["open_ground"]
    print()
    print("  SVF at pedestrian level, open ground:")
    print(f"     study-area square : mean {og['mean']:.3f}  median {og['median']:.3f}  "
          f"p05 {og['p05']:.3f}  p95 {og['p95']:.3f}  ({og['n_pixels']:,} cells)")
    for name, b in buurt_stats.items():
        bg = b.get("open_ground") or {}
        if bg:
            print(f"     {name:<17} : mean {bg['mean']:.3f}  median {bg['median']:.3f}  "
                  f"p05 {bg['p05']:.3f}  p95 {bg['p95']:.3f}  ({bg['n_pixels']:,} cells)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
