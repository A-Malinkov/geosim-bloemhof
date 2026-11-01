#!/usr/bin/env python3
"""
fetch_ahn.py - download AHN elevation rasters for the study area.

AHN (Actueel Hoogtebestand Nederland) via the PDOK WCS, 0.5 m:
    dsm_05m   digital SURFACE model: includes buildings and tree crowns
    dtm_05m   digital TERRAIN model: bare ground

Both are in EPSG:28992 (RD New) with heights in metres above NAP.
The difference (nDSM = DSM - DTM) is object height above ground, which is what
the Sky View Factor and the height-variation indicators actually need.

Usage
-----
    python analysis/morphology/fetch_ahn.py               # DSM + DTM over the study area, 150 m padding
    python analysis/morphology/fetch_ahn.py --pad 300     # more context beyond the buurt edges
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


#: The WCS refuses any request whose output exceeds 4000 px on a side
#: ("Raster size out of range ... MAXSIZE=4000"). At 0.5 m that is 2000 m, and
#: the study area is wider than that, so downloads are tiled and mosaicked.
#: 1800 m leaves margin for rounding.
MAX_TILE_M = 1800.0


def _download_one(coverage: str, bbox, out: pathlib.Path, timeout: int = 600):
    xmin, ymin, xmax, ymax = bbox
    params = {
        "service": "WCS", "version": "2.0.1", "request": "GetCoverage",
        "coverageId": coverage,
        # WCS 2.0.1 wants one subset per axis; requests encodes these fine.
        "subset": [f"x({xmin:.0f},{xmax:.0f})", f"y({ymin:.0f},{ymax:.0f})"],
        "format": "image/tiff",
    }
    r = requests.get(SERVICES["ahn_wcs"], params=params, timeout=timeout)
    if r.status_code != 200:
        # the service explains itself in an OWS ExceptionReport; surface it
        msg = r.text[:400].replace("\n", " ")
        raise RuntimeError(f"AHN WCS HTTP {r.status_code}: {msg}")
    if "tiff" not in r.headers.get("content-type", ""):
        raise RuntimeError(f"expected a GeoTIFF, got "
                           f"{r.headers.get('content-type')}: {r.text[:300]}")
    out.write_bytes(r.content)
    return out


def download_coverage(coverage: str, bbox: tuple[float, float, float, float],
                      out: pathlib.Path, timeout: int = 600) -> pathlib.Path:
    """
    GetCoverage a WCS coverage over `bbox` (RD New) to a GeoTIFF.

    Tiles the request when the box is larger than the service will return in one
    go, and mosaics the pieces. The limit is a hard MAXSIZE=4000 px per side.
    """
    import math

    xmin, ymin, xmax, ymax = bbox
    nx = max(1, math.ceil((xmax - xmin) / MAX_TILE_M))
    ny = max(1, math.ceil((ymax - ymin) / MAX_TILE_M))
    print(f"  requesting {coverage} over {tuple(round(v) for v in bbox)} "
          f"({(xmax-xmin):.0f} x {(ymax-ymin):.0f} m)"
          + (f" as {nx}x{ny} tiles" if nx * ny > 1 else ""))

    if nx * ny == 1:
        _download_one(coverage, bbox, out, timeout)
        print(f"  -> data/raw/{out.name}  ({out.stat().st_size/1e6:.1f} MB)")
        return out

    dx, dy = (xmax - xmin) / nx, (ymax - ymin) / ny
    parts = []
    tmpdir = RAW / "_ahn_tiles"
    tmpdir.mkdir(exist_ok=True)
    try:
        for i in range(nx):
            for j in range(ny):
                bx = (xmin + i * dx, ymin + j * dy,
                      xmin + (i + 1) * dx, ymin + (j + 1) * dy)
                tile = tmpdir / f"{coverage}_{i}_{j}.tif"
                _download_one(coverage, bx, tile, timeout)
                parts.append(tile)
                print(f"     tile {len(parts)}/{nx*ny}  "
                      f"{tile.stat().st_size/1e6:.1f} MB")

        # Mosaic by hand rather than with rasterio.merge. AHN's nodata is the
        # float32 maximum (3.4e38), which merge refuses to carry ("cannot safely
        # be represented"), and it then fills the whole output with it: a 0.2 MB
        # constant raster that looks like a successful download. Pasting each
        # tile at its own offset sidesteps that entirely.
        res = None
        for path in parts:
            with rasterio.open(path) as src:
                res = src.res[0]
                break
        W = int(round((xmax - xmin) / res))
        H = int(round((ymax - ymin) / res))
        out_transform = rasterio.transform.from_origin(xmin, ymax, res, res)
        mosaic = np.full((H, W), AHN_NODATA, dtype="float32")
        for path in parts:
            with rasterio.open(path) as src:
                a = src.read(1).astype("float32")
                left, top = src.transform * (0, 0)
                col = int(round((left - xmin) / res))
                row = int(round((ymax - top) / res))
            h, w = a.shape
            r0, c0 = max(0, row), max(0, col)
            r1, c1 = min(H, row + h), min(W, col + w)
            if r1 <= r0 or c1 <= c0:
                continue
            sub = a[r0 - row:r1 - row, c0 - col:c1 - col]
            keep = sub < AHN_NODATA * 0.5          # do not paste nodata over data
            target = mosaic[r0:r1, c0:c1]
            target[keep] = sub[keep]
            mosaic[r0:r1, c0:c1] = target

        with rasterio.open(parts[0]) as src:
            profile = src.profile
        profile.update(height=H, width=W, transform=out_transform,
                       dtype="float32", count=1, nodata=AHN_NODATA,
                       compress="deflate")
        with rasterio.open(out, "w", **profile) as dst:
            dst.write(mosaic, 1)
        valid = (mosaic < AHN_NODATA * 0.5)
        print(f"  -> data/raw/{out.name}  ({out.stat().st_size/1e6:.1f} MB, "
              f"{W} x {H} px, {100*valid.mean():.0f}% valid)")
    finally:
        for p_ in parts:
            p_.unlink(missing_ok=True)
        if tmpdir.exists() and not any(tmpdir.iterdir()):
            tmpdir.rmdir()
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
    ap.add_argument("--pad", type=int, default=150,
                    help="context to fetch beyond the study-area edge, in metres. "
                         "SVF needs it: a building just outside still blocks sky inside.")
    ap.add_argument("--which", choices=("dsm", "dtm", "both"), default="both")
    ap.add_argument("--force", action="store_true", help="re-download even if present")
    args = ap.parse_args()

    bbox = bbox_rd(args.pad)
    print(f"AHN download: {STUDY_AREA.name} (+{args.pad} m context)")
    print(f"  box {bbox[2]-bbox[0]:.0f} x {bbox[3]-bbox[1]:.0f} m")

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
