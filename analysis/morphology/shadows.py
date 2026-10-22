#!/usr/bin/env python3
"""
shadows.py — direct-sun / shadow hours over the study area from AHN.

Owner: Atanas Malinkov  (morphology, same component as sky_view_factor.py)

WHAT THIS IS
------------
There is no "shadow dataset" to download: a shadow is geometry x sun position x
time, so it is only valid for one instant. What you CAN import is the surface it
is cast from — the AHN DSM — which fetch_ahn.py already fetches for the Sky View
Factor. This script casts the sun across a day over that surface and adds up, for
every cell, how many hours of DIRECT sun it receives. It is the same horizon-ray
idea as sky_view_factor.py, run once per sun position instead of over a full
hemisphere.

HOW
---
For a sun at azimuth `a` and elevation `e`, a cell is in shadow if, walking
towards the sun, any surface point rises above the sun ray leaving that cell:
a point at horizontal distance d blocks the sun when its height exceeds
`z0 + d*tan(e)`, i.e. `(height - d*tan(e)) > z0`. Marching outwards and keeping
the running maximum of `height - d*tan(e)` gives the test for the whole raster at
once (the same vectorised march sky_view_factor.py uses).

The sun's position comes from the NOAA solar-position algorithm, implemented
here in plain Python so the script needs no extra dependency.

OBSERVER SURFACE
----------------
Shadows are evaluated on the AHN DSM (buildings + tree crowns block the sun),
and the headline statistics are reported on OPEN GROUND only — streets, gardens
and squares, the nDSM < 2 m mask — because sun hours on a roof are not what a
resident experiences. This mirrors sky_view_factor.py exactly.

LIMITATIONS (state them, per the course rubric)
-----------------------------------------------
- One clear-sky day. No clouds, no atmosphere: this is geometric direct-sun
  duration, an upper bound, not measured insolation.
- The DSM includes tree crowns as solid, so summer foliage over-shades a little.
- Low winter sun casts very long shadows; --radius caps the search, so a distant
  high-rise beyond it is ignored. The default is generous but finite.

USAGE
-----
    python analysis/morphology/fetch_ahn.py          # get the rasters first
    python analysis/morphology/shadows.py            # equinox, 1 m, 30 min steps
    python analysis/morphology/shadows.py --date 2026-06-21 --step-minutes 15
    python analysis/morphology/shadows.py --date 2026-12-21 --resolution 0.5
    python analysis/morphology/shadows.py --scenario scenario_a   # demolition + new blocks burned in

OUTPUTS
-------
    data/processed/shadow_hours.tif      direct-sun hours raster, EPSG:28992 (gitignored)
    data/processed/shadow_overlay.png    colour ramp for draping in Cesium
    data/processed/shadow_summary.json   statistics for the dashboard
    (a scenario run appends _<scenario> to the names, before any --suffix)
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import (  # noqa: E402
    PROCESSED, RAW, STUDY_AREA, bbox_rd, bbox_wgs, buurt_polygons,
    buurt_properties, centre_wgs, design_site_polygon, study_area_polygon,
)
# Reuse the raster machinery from the SVF script rather than duplicate it: the
# loader, the edge-safe shift, the RD->WGS84 warp and the stats helper are all
# exactly what shadow casting needs. Importing it is side-effect free (its work
# is under `if __name__ == "__main__"`).
from sky_view_factor import (  # noqa: E402
    describe, fill_nan_nearest, load_raster, reproject_to_wgs84, shift, write_tif,
)


# ------------------------------------------------------------ solar position
def solar_position(dt: datetime, lat_deg: float, lon_deg: float):
    """
    Sun elevation and azimuth for a UTC instant, via the NOAA algorithm.

    Returns (elevation_deg, azimuth_deg) with azimuth measured clockwise from
    north. Elevation is geometric (no atmospheric refraction) — for casting
    shadows we only care whether the sun is above the horizon and from where.
    lon is east-positive.
    """
    # fractional day -> Julian day -> Julian century (NOAA)
    frac = (dt.hour + dt.minute / 60 + dt.second / 3600) / 24
    y, m = dt.year, dt.month
    day = dt.day + frac
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    jd = int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + day + b - 1524.5
    jc = (jd - 2451545.0) / 36525.0

    geom_long = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360
    geom_anom = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    ecc = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    anom_r = math.radians(geom_anom)
    sun_eq = (math.sin(anom_r) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
              + math.sin(2 * anom_r) * (0.019993 - 0.000101 * jc)
              + math.sin(3 * anom_r) * 0.000289)
    true_long = geom_long + sun_eq
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(125.04 - 1934.136 * jc))
    mean_obliq = 23 + (26 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60) / 60
    obliq = mean_obliq + 0.00256 * math.cos(math.radians(125.04 - 1934.136 * jc))
    decl = math.degrees(math.asin(math.sin(math.radians(obliq))
                                  * math.sin(math.radians(app_long))))

    var_y = math.tan(math.radians(obliq / 2)) ** 2
    long_r = math.radians(geom_long)
    eq_time = 4 * math.degrees(
        var_y * math.sin(2 * long_r)
        - 2 * ecc * math.sin(anom_r)
        + 4 * ecc * var_y * math.sin(anom_r) * math.cos(2 * long_r)
        - 0.5 * var_y * var_y * math.sin(4 * long_r)
        - 1.25 * ecc * ecc * math.sin(2 * anom_r))

    time_min = dt.hour * 60 + dt.minute + dt.second / 60
    true_solar = (time_min + eq_time + 4 * lon_deg) % 1440   # lon east-positive
    hour_angle = true_solar / 4 - 180
    if hour_angle < -180:
        hour_angle += 360

    lat_r = math.radians(lat_deg)
    decl_r = math.radians(decl)
    ha_r = math.radians(hour_angle)
    cos_zen = (math.sin(lat_r) * math.sin(decl_r)
               + math.cos(lat_r) * math.cos(decl_r) * math.cos(ha_r))
    cos_zen = max(-1.0, min(1.0, cos_zen))
    zenith = math.degrees(math.acos(cos_zen))
    elevation = 90 - zenith

    sin_zen = math.sin(math.radians(zenith))
    if abs(sin_zen) < 1e-9:
        return elevation, 180.0
    cos_az = ((math.sin(lat_r) * cos_zen - math.sin(decl_r))
              / (math.cos(lat_r) * sin_zen))
    cos_az = max(-1.0, min(1.0, cos_az))
    az = math.degrees(math.acos(cos_az))
    azimuth = (az + 180) % 360 if hour_angle > 0 else (540 - az) % 360
    return elevation, azimuth


# ----------------------------------------------------------- shadow casting
def shadow_mask(surface: np.ndarray, cellsize: float, sun_az_deg: float,
                sun_elev_deg: float, radius_m: float, n_steps: int) -> np.ndarray:
    """
    Boolean shadow mask for one sun position (True = the cell is in shadow).

    Marches towards the sun and keeps the running maximum of `height - d*tan(e)`;
    a cell is shadowed when that exceeds its own surface height.
    """
    if sun_elev_deg <= 0:
        return np.ones(surface.shape, dtype=bool)          # sun below horizon
    tan_e = math.tan(math.radians(sun_elev_deg))
    az = math.radians(sun_az_deg)
    radius_px = max(2, int(round(radius_m / cellsize)))
    # dense near, sparse far: nearby geometry sets the shadow, distant refines it
    steps = np.unique(np.round(np.geomspace(1, radius_px, n_steps)).astype(int))

    max_block = np.full(surface.shape, -np.inf, dtype="float32")
    for r in steps:
        drow = int(round(-r * math.cos(az)))               # north is -row
        dcol = int(round(r * math.sin(az)))
        if drow == 0 and dcol == 0:
            continue
        dist = math.hypot(drow, dcol) * cellsize
        cand = shift(surface, drow, dcol) - dist * tan_e   # NaN off the edge
        np.fmax(max_block, cand, out=max_block)            # fmax ignores NaN
    return max_block > (surface + 0.05)


def day_times(date: datetime, step_minutes: int):
    """Sampled UTC instants from 02:00 to 21:00 — wide enough for NL daylight."""
    t = date.replace(hour=2, minute=0, second=0, microsecond=0)
    end = date.replace(hour=21, minute=0, second=0, microsecond=0)
    out = []
    while t <= end:
        out.append(t)
        t += timedelta(minutes=step_minutes)
    return out


# ------------------------------------------------------------------- outputs
def write_hours_overlay(path, arr, vmax, cmap_name="plasma",
                        mask=None, max_px: int = 1400):
    """Colour-ramped, transparent PNG of sun hours, for draping on the globe."""
    import matplotlib
    matplotlib.use("Agg")
    from PIL import Image

    norm = np.clip(arr / max(vmax, 1e-6), 0, 1)
    cmap = matplotlib.colormaps[cmap_name]
    rgba = (cmap(np.nan_to_num(norm)) * 255).astype("uint8")
    alpha = np.where(np.isfinite(arr), 205, 0).astype("uint8")
    if mask is not None:
        alpha = np.where(mask, alpha, 45).astype("uint8")
    rgba[..., 3] = alpha

    img = Image.fromarray(rgba, mode="RGBA")
    if max(img.size) > max_px:
        scale = max_px / max(img.size)
        img = img.resize((int(img.width * scale), int(img.height * scale)),
                         Image.LANCZOS)
    img.save(path, optimize=True)
    print(f"  wrote {path.name}  ({img.width}x{img.height}, "
          f"{path.stat().st_size / 1e6:.1f} MB)")


# ---------------------------------------------------------------------- main
COMBINED = "_combined"  #key of the whole-study-area stats while they are collected


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Direct-sun / shadow hours from AHN",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default="2026-03-20",
                    help="day to simulate, YYYY-MM-DD (default: spring equinox)")
    ap.add_argument("--step-minutes", type=int, default=30,
                    help="sun sampling interval in minutes")
    ap.add_argument("--resolution", type=float, default=1.0,
                    help="working cell size in metres (0.5 = AHN native)")
    ap.add_argument("--radius", type=float, default=300.0,
                    help="shadow search radius in metres (caps long low-sun shadows)")
    ap.add_argument("--steps", type=int, default=80,
                    help="radial samples per sun position")
    ap.add_argument("--no-clip-buurt", action="store_true",
                    help="skip the CBS neighbourhood-boundary statistics")
    ap.add_argument("--suffix", default="",
                    help="append to output names (e.g. _2026-12-21) so extra days "
                         "do not overwrite the app's files")
    ap.add_argument("--scenario", default="baseline",
                    choices=["baseline", "scenario_a", "scenario_b"])  #which built environment
    args = ap.parse_args()

    dsm_path, dtm_path = RAW / "ahn_dsm_05m.tif", RAW / "ahn_dtm_05m.tif"
    for p in (dsm_path, dtm_path):
        if not p.exists():
            print(f"missing {p}. Run: python analysis/morphology/fetch_ahn.py")
            return 1

    try:
        date = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        print(f"bad --date {args.date!r}; expected YYYY-MM-DD")
        return 1

    lon, lat = centre_wgs()
    print(f"Direct-sun hours — {STUDY_AREA.name}")
    print(f"  {args.date} | cell {args.resolution} m | radius {args.radius} m | "
          f"sun every {args.step_minutes} min")

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
    print(f"  scenario {args.scenario}")

    ndsm = dsm - dtm
    open_ground = np.isfinite(ndsm) & (ndsm < 2.0)
    print(f"  open ground (street / garden / square): "
          f"{100 * open_ground.mean():.1f}% of cells")

    print("  filling nodata …")
    surface = fill_nan_nearest(dsm)          # what casts and receives shadow

    times = day_times(date, args.step_minutes)
    shadow_hours = np.zeros(surface.shape, dtype="float32")
    step_h = args.step_minutes / 60.0
    sun_steps = 0
    print(f"  casting {len(times)} sun positions …")
    for dt in times:
        elev, az = solar_position(dt, lat, lon)
        if elev <= 0:
            continue
        sun_steps += 1
        shadow_hours += shadow_mask(
            surface, args.resolution, az, elev, args.radius, args.steps) * step_h
        if sys.stdout.isatty():
            print(f"    {dt:%H:%M} UTC  elev {elev:4.1f}°  az {az:5.1f}°   "
                  f"{sun_steps} up", end="\r")
    daylight_h = sun_steps * step_h
    sunlit_hours = daylight_h - shadow_hours
    print(f"\n  {sun_steps} sun-up steps, {daylight_h:.2f} h of daylight sampled")

    # crop most of the 150 m context padding, but keep 50 m: the design site's
    # south edge (Strevelsweg) runs ~31 m past the buurt bounding box. Stats
    # are clipped to polygons, so the margin only adds overlay, not counts.
    pad_px = int(round((150 - 50) / args.resolution))
    sl = (slice(pad_px, -pad_px), slice(pad_px, -pad_px))
    sun_c, og_c = sunlit_hours[sl], open_ground[sl]
    transform_c = transform * transform.translation(pad_px, pad_px)

    # ---- statistics per buurt and combined, clipped to real buurt land -----
    masks, buurt_stats, site_stats = {}, {}, None
    if not args.no_clip_buurt:
        try:
            from rasterio.features import geometry_mask
            polys, props = buurt_polygons(), buurt_properties()
            for code, name in STUDY_AREA.buurten:
                m = ~geometry_mask([polys[code]], out_shape=sun_c.shape,
                                   transform=transform_c, invert=False)
                masks[name] = m
                print(f"  {name:12} covers {100 * m.mean():5.1f}% of the raster")
            m_all = ~geometry_mask([study_area_polygon()], out_shape=sun_c.shape,
                                   transform=transform_c, invert=False)
            masks[COMBINED] = m_all  #reserved key: a one-buurt study area shares its buurt's name
            for name, m in masks.items():
                code = next((c for c, n in STUDY_AREA.buurten if n == name), None)
                buurt_stats[name] = {
                    "code": code,
                    "inhabitants": (props.get(code, {}) or {}).get("aantalInwoners"),
                    "raster_coverage_fraction": round(float(m.mean()), 4),
                    "open_ground_sunlit_hours": describe(
                        np.where(og_c & m, sun_c, np.nan)),
                }
            # the design site: a small polygon inside Bloemhof, edge streets included
            m_site = ~geometry_mask([design_site_polygon()], out_shape=sun_c.shape,
                                    transform=transform_c, invert=False)
            site_og = np.where(og_c & m_site, sun_c, np.nan)
            site_stats = describe(site_og)
            v = site_og[np.isfinite(site_og)]
            site_stats["share_under_2h"] = round(float((v < 2).mean()), 4)
            site_stats["share_under_4h"] = round(float((v < 4).mean()), 4)
        except Exception as exc:
            print(f"  ! buurt clipping skipped ({exc})")
            site_stats = None

    overlay_arr, overlay_bbox = reproject_to_wgs84(sun_c, transform_c, crs)

    stats = {
        "study_area": STUDY_AREA.name,
        "scenario": args.scenario,  #which built environment this is
        "method": "ray-cast direct-sun accumulation from the AHN DSM",
        "solar_position": "NOAA solar-position algorithm (geometric, no refraction)",
        "date": args.date,
        "parameters": {
            "cell_size_m": args.resolution,
            "search_radius_m": args.radius,
            "n_radial_steps": args.steps,
            "step_minutes": args.step_minutes,
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "surface": "AHN dsm_05m (buildings + tree crowns)"
                       + ("" if args.scenario == "baseline" else
                          f", with the {args.scenario} demolition and massing burned in"),  #see scenario_world.py
        },
        "daylight_hours": round(daylight_h, 3),
        "n_sun_steps": sun_steps,
        "bbox_rd": [round(v, 1) for v in bbox_rd()],
        # The bbox the PNG is actually drawn on, from the warp — NOT the RD
        # square reprojected corner-to-corner, which is off by up to ~30 m.
        "bbox_wgs84": [round(v, 7) for v in overlay_bbox],
        "bbox_wgs84_rd_corners": [round(v, 7) for v in bbox_wgs()],
        "all_cells_sunlit_hours": describe(sun_c),
        "open_ground_sunlit_hours": describe(np.where(og_c, sun_c, np.nan)),
        "per_buurt": {k: v for k, v in buurt_stats.items() if k != COMBINED},
        "combined": buurt_stats.get(COMBINED),
        "design_site": {"open_ground_sunlit_hours": site_stats} if site_stats else None,
        "histogram": {
            "bin_edges": [round(x, 3) for x in
                          np.linspace(0, max(daylight_h, 1e-6), 25).tolist()],
            "counts": np.histogram(
                sun_c[og_c & np.isfinite(sun_c)], bins=24,
                range=(0, max(daylight_h, 1e-6)))[0].tolist(),
        },
        "_note": "Geometric clear-sky direct-sun hours on one day, an upper "
                 "bound: no clouds, tree crowns treated as solid, shadows from "
                 "obstructions beyond --radius ignored.",
    }

    print("  writing outputs …")
    sfx = ("" if args.scenario == "baseline" else f"_{args.scenario}") + args.suffix  #scenario first, then the day
    write_tif(PROCESSED / f"shadow_hours{sfx}.tif", sun_c, transform_c, crs)
    write_hours_overlay(PROCESSED / f"shadow_overlay{sfx}.png", overlay_arr,
                        vmax=max(daylight_h, 1e-6))
    (PROCESSED / f"shadow_summary{sfx}.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(f"  wrote shadow_summary{sfx}.json")

    og = stats["open_ground_sunlit_hours"]
    print()
    print(f"  Direct sun on open ground, {args.date} "
          f"({daylight_h:.1f} h daylight):")
    print(f"     study area : mean {og['mean']:.2f} h  median {og['median']:.2f} h  "
          f"p05 {og['p05']:.2f}  p95 {og['p95']:.2f}  ({og['n_pixels']:,} cells)")
    for name, b in buurt_stats.items():
        bg = b.get("open_ground_sunlit_hours") or {}
        if bg:
            print(f"     {name:<12}: mean {bg['mean']:.2f} h  median {bg['median']:.2f} h  "
                  f"p05 {bg['p05']:.2f}  p95 {bg['p95']:.2f}  ({bg['n_pixels']:,} cells)")
    if site_stats:
        print(f"     design site : mean {site_stats['mean']:.2f} h  median {site_stats['median']:.2f} h  "
              f"< 2 h {100 * site_stats['share_under_2h']:.0f}%  "
              f"({site_stats['n_pixels']:,} cells)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
