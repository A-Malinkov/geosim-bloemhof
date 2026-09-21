#!/usr/bin/env python3
"""
fetch_ahn.py — download AHN elevation rasters for the study area.

AHN (Actueel Hoogtebestand Nederland) via the PDOK WCS, 0.5 m:
    dsm_05m   digital SURFACE model  — includes buildings and tree crowns
    dtm_05m   digital TERRAIN model  — bare ground

Both are in EPSG:28992 (RD New) with heights in metres above NAP.
The difference (nDSM = DSM - DTM) is object height above ground, which is what
the Sky View Factor and the height-variation indicators actually need.

Usage
-----
    python analysis/morphology/fetch_ahn.py               # both, 600 m radius
    python analysis/morphology/fetch_ahn.py --radius 800
    python analysis/morphology/fetch_ahn.py --which dsm

Writes into data/raw/:
    ahn_dsm_05m.tif, ahn_dtm_05m.tif, ahn_ndsm_05m.tif
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import numpy as np
import rasterio
import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import RAW, SERVICES, STUDY_AREA, bbox_rd  # noqa: E402

# AHN's own nodata is the float32 maximum, which numpy will happily average
# into your results if you forget about it.
AHN_NODATA = 3.4028234663852886e38


def download_coverage(coverage: str, bbox: tuple[float, float, float, float],
                      out: pathlib.Path, timeout: int = 300) -> pathlib.Path:
    """GetCoverage a WCS 2.0.1 coverage over `bbox` (RD New) to a GeoTIFF."""
    xmin, ymin, xmax, ymax = bbox
    params = {
        "service": "WCS",
        "version": "2.0.1",
        "request": "GetCoverage",
        "coverageId": coverage,
        # WCS 2.0.1 wants one subset per axis; requests encodes these fine.
        "subset": [f"x({xmin:.0f},{xmax:.0f})", f"y({ymin:.0f},{ymax:.0f})"],
        "format": "image/tiff",
    }
    print(f"  requesting {coverage} over {tuple(round(v) for v in bbox)} …")
    r = requests.get(SERVICES["ahn_wcs"], params=params, timeout=timeout)
    r.raise_for_status()
    ctype = r.headers.get("content-type", "")
    if "tiff" not in ctype:
        raise RuntimeError(f"expected a GeoTIFF, got {ctype}: {r.text[:300]}")
    out.write_bytes(r.content)
    print(f"  -> {out.relative_to(RAW.parent.parent)}  ({len(r.content)/1e6:.1f} MB)")
    return out


def read_masked(path: pathlib.Path) -> tuple[np.ndarray, dict]:
    """Read band 1 as float32 with AHN's nodata turned into NaN."""
    with rasterio.open(path) as src:
        a = src.read(1).astype("float32")
        profile = src.profile
    a[a >= AHN_NODATA * 0.5] = np.nan
    a[a < -100] = np.nan
    return a, profile


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--radius", type=int, default=STUDY_AREA.radius_m,
                    help="half-width of the square around the study centre, in metres")
    ap.add_argument("--which", choices=("dsm", "dtm", "both"), default="both")
    ap.add_argument("--force", action="store_true", help="re-download even if present")
    args = ap.parse_args()

    # SVF needs context beyond the study area itself: a building 100 m outside
    # the edge still blocks sky inside it. Pad generously and crop later.
    pad = 150
    bbox = bbox_rd(args.radius + pad)
    print(f"AHN download — {STUDY_AREA.name}, radius {args.radius} m (+{pad} m context)")

    want = ("dsm", "dtm") if args.which == "both" else (args.which,)
    paths = {}
    for kind in want:
        out = RAW / f"ahn_{kind}_05m.tif"
        if out.exists() and not args.force:
            print(f"  {out.name} already there (use --force to refresh)")
        else:
            download_coverage(f"{kind}_05m", bbox, out)
        paths[kind] = out

    # nDSM = height of everything above bare ground
    if set(paths) == {"dsm", "dtm"}:
        dsm, profile = read_masked(paths["dsm"])
        dtm, _ = read_masked(paths["dtm"])
        if dsm.shape != dtm.shape:
            print(f"  ! DSM {dsm.shape} and DTM {dtm.shape} differ; skipping nDSM")
        else:
            ndsm = dsm - dtm
            ndsm[~np.isfinite(ndsm)] = np.nan
            profile.update(dtype="float32", nodata=np.nan, count=1, compress="deflate")
            out = RAW / "ahn_ndsm_05m.tif"
            with rasterio.open(out, "w", **profile) as dst:
                dst.write(ndsm.astype("float32"), 1)
            ok = np.isfinite(ndsm)
            print(f"  -> {out.name}: object heights "
                  f"{np.nanpercentile(ndsm[ok], 1):.1f} .. "
                  f"{np.nanpercentile(ndsm[ok], 99):.1f} m above ground (1–99 pct)")

    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
