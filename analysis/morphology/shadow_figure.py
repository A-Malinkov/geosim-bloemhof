#!/usr/bin/env python3
"""
shadow_figure.py - direct-sun hours on the design site on three days, per scenario.

Owner: Atanas Malinkov

    python analysis/morphology/shadows.py                                  #every scenario, three days
    python analysis/morphology/shadow_figure.py                            #every case in CASES
    python analysis/morphology/shadow_figure.py --scenario scenario_a      #only these

Writes docs/fig_shadow_site.png (today) and docs/fig_shadow_site_<scenario>.png.
Only open ground (nDSM < 2 m) is coloured. Grey has no AHN ground (buildings,
built-over gardens, water) or is a new block, green is objects of 2 m or more,
mostly trees. A design's mask comes from scenario_world.burn_into_rasters(), the
same burn-in shadows.py ran on, so the figure masks what the statistics counted.
"""

import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import PROCESSED, RAW, design_site_polygon  #noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
DAYS = [("_2026-12-21", "21 December"), ("", "20 March (equinox)"), ("_2026-06-21", "21 June")]
PAD_M = 120          #context around the site
NAMES = {"baseline": "today", "scenario_a": "scenario A", "scenario_b": "scenario B",
         "final": "final design"}  #figure titles
CASES = [{"scenario": sc} for sc in NAMES]  #one figure per scenario


def masks(sc, hb, shape, wt):
    #(open ground, tall objects, new blocks) on the hours grid for one scenario
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.windows import from_bounds

    def read(name):
        #one AHN raster over the hours array's own bounds, so the grids match cell for cell
        with rasterio.open(RAW / name) as src:
            return src.read(1, window=from_bounds(hb[0], hb[1], hb[2], hb[3], src.transform),
                            out_shape=shape, resampling=Resampling.nearest,
                            masked=True).filled(np.nan)

    if sc == "baseline":
        #Same mask as shadows.py's statistics. The AHN DTM is empty under
        #buildings, so roofs are NaN here, NOT >= 2 m: grey them as such.
        ndsm = read("ahn_ndsm_05m.tif")
        new = np.zeros(shape, dtype=bool)
    else:
        #the design burned in as shadows.py did: demolished and new streets flat, new blocks raised
        from rasterio.features import rasterize
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scenarios"))
        from scenario_world import burn_into_rasters, load_scenario
        dsm, dtm = burn_into_rasters(read("ahn_dsm_05m.tif"), read("ahn_dtm_05m.tif"), wt, sc)
        ndsm = dsm - dtm  #NaN where the DTM is empty: kept buildings
        blocks, _ = load_scenario(sc)
        new = rasterize([(g, 1) for g in blocks.geometry], out_shape=shape, transform=wt,
                        dtype="uint8").astype(bool)  #new blocks are buildings, not tall objects
    open_ground = np.isfinite(ndsm) & (ndsm < 2.0) & ~new
    tall = np.isfinite(ndsm) & (ndsm >= 2.0) & ~new  #tree crowns mostly
    return open_ground, tall, new


def run(p):
    #one figure: the three days of one scenario
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import rasterio
    from rasterio.transform import array_bounds
    from rasterio.windows import Window, from_bounds  #Window: to cut the box to the raster

    sc = p["scenario"]
    pre = "" if sc == "baseline" else f"_{sc}"  #shadows.py's file names: _<scenario>, then the day
    site = design_site_polygon()
    x0, y0, x1, y1 = site.bounds
    x0, y0, x1, y1 = x0 - PAD_M, y0 - PAD_M, x1 + PAD_M, y1 + PAD_M

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.9), constrained_layout=True)
    for ax, (sfx, label) in zip(axes, DAYS):
        tif = PROCESSED / f"shadow_hours{pre}{sfx}.tif"
        summ = json.loads((PROCESSED / f"shadow_summary{pre}{sfx}.json").read_text())
        with rasterio.open(tif) as src:
            #whole cells, cut to the raster: the box runs past the raster's south edge
            win = (from_bounds(x0, y0, x1, y1, src.transform).round_offsets().round_lengths()
                   .intersection(Window(0, 0, src.width, src.height)))
            hours = src.read(1, window=win)
            wt = src.window_transform(win)
        hb = array_bounds(*hours.shape, wt)  #what the hours array really covers
        open_ground, tall, _ = masks(sc, hb, hours.shape, wt)
        extent = (wt.c, wt.c + wt.a * hours.shape[1], wt.f + wt.e * hours.shape[0], wt.f)
        day_h = summ["daylight_hours"]
        ax.set_facecolor("#9a9a9a")      #no AHN ground: buildings, built-over gardens, water; and new blocks
        im = ax.imshow(np.where(open_ground, hours, np.nan), extent=extent, cmap="plasma",
                       vmin=0, vmax=day_h, interpolation="nearest")
        ax.imshow(np.where(tall, 1.0, np.nan), extent=extent, cmap="Greens",
                  vmin=0, vmax=1.6, interpolation="nearest")
        xs, ys = site.exterior.xy
        ax.plot(xs, ys, color="#00b7ff", lw=1.6)
        s = summ["design_site"]["open_ground_sunlit_hours"]
        ax.set_title(f"{label}: {day_h:.1f} h daylight\n"
                     f"site median {s['median']:.1f} h, {100 * s['share_under_2h']:.0f} % under 2 h",
                     fontsize=11)
        ax.set_xlim(x0, x1); ax.set_ylim(max(y0, extent[2]), min(y1, extent[3]))
        ax.set_xticks([]); ax.set_yticks([])
        cb = fig.colorbar(im, ax=ax, shrink=0.8, orientation="horizontal", pad=0.02)
        cb.set_label("hours of direct sun on open ground")
    if sc == "baseline":  #today's title as before
        fig.suptitle("Direct sun on open ground, clear sky. Grey: buildings and other cells with no "
                     "AHN ground. Green: trees and other objects over 2 m. Blue: design site", fontsize=12)
    else:
        fig.suptitle(f"Direct sun on open ground, {NAMES[sc]}, clear sky. Grey: buildings, new blocks and "
                     "cells with no AHN ground. Green: trees and other objects over 2 m. Blue: design site",
                     fontsize=12)
    out = ROOT / "docs" / f"fig_shadow_site{pre}.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print(f"wrote {out.relative_to(ROOT)}")


def main():
    #every case by default, or only the names after --scenario
    only = sys.argv[sys.argv.index("--scenario") + 1:] if "--scenario" in sys.argv else None
    for c in CASES:
        if only is None or c["scenario"] in only:
            run(c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
