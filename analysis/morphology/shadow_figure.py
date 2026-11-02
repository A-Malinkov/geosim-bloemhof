#!/usr/bin/env python3
"""
shadow_figure.py - direct-sun hours on the design site on three days.

Owner: Atanas Malinkov

    python analysis/morphology/shadows.py --scenario baseline    #equinox, 21 Jun, 21 Dec
    python analysis/morphology/shadow_figure.py

Writes docs/fig_shadow_site.png. Only open ground (nDSM < 2 m) is coloured.
Grey has no AHN ground (buildings, built-over gardens, water), green is objects
of 2 m or more, mostly trees.
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


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.windows import from_bounds

    site = design_site_polygon()
    x0, y0, x1, y1 = site.bounds
    x0, y0, x1, y1 = x0 - PAD_M, y0 - PAD_M, x1 + PAD_M, y1 + PAD_M

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.9), constrained_layout=True)
    for ax, (sfx, label) in zip(axes, DAYS):
        tif = PROCESSED / f"shadow_hours{sfx}.tif"
        summ = json.loads((PROCESSED / f"shadow_summary{sfx}.json").read_text())
        with rasterio.open(tif) as src:
            win = from_bounds(x0, y0, x1, y1, src.transform)
            hours = src.read(1, window=win)
            wt = src.window_transform(win)
        with rasterio.open(RAW / "ahn_ndsm_05m.tif") as src:
            ndsm = src.read(1, window=from_bounds(x0, y0, x1, y1, src.transform),
                            out_shape=hours.shape, resampling=Resampling.nearest,
                            masked=True).filled(np.nan)
        #Same mask as shadows.py's statistics. The AHN DTM is empty under
        #buildings, so roofs are NaN here, NOT >= 2 m: grey them as such.
        open_ground = np.isfinite(ndsm) & (ndsm < 2.0)
        tall = np.isfinite(ndsm) & (ndsm >= 2.0)          #tree crowns mostly
        extent = (wt.c, wt.c + wt.a * hours.shape[1], wt.f + wt.e * hours.shape[0], wt.f)
        day_h = summ["daylight_hours"]
        ax.set_facecolor("#9a9a9a")      #no AHN ground: buildings, built-over gardens, water
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
    fig.suptitle("Direct sun on open ground, clear sky. Grey: buildings and other cells with no "
                 "AHN ground. Green: trees and other objects over 2 m. Blue: design site", fontsize=12)
    out = ROOT / "docs" / "fig_shadow_site.png"
    fig.savefig(out, dpi=130)
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
