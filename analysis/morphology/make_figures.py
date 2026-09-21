#!/usr/bin/env python3
"""
make_figures.py — report figures for the morphology + vegetation work.

Owner: Atanas Malinkov

Run the three analysis scripts first, then this:
    python analysis/morphology/fetch_ahn.py
    python analysis/morphology/fetch_trees.py
    python analysis/morphology/sky_view_factor.py
    python analysis/morphology/make_figures.py

Writes PNGs into docs/ at 200 dpi, sized for a report page.

Design notes (so the figures stay consistent if you add more):
  * Sequential magnitude uses ONE hue, light to dark. Not viridis, not a rainbow.
  * Categorical series use fixed slots in a fixed order; never recoloured by rank.
  * A single-series chart gets no legend box — the title names it.
  * Labels are selective. A number on every bar is noise.
  * Gridlines are solid hairlines, never dashed, and sit behind the marks.
"""
from __future__ import annotations

import json
import pathlib
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.colors import LinearSegmentedColormap, to_rgba
from matplotlib.ticker import FuncFormatter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import DOCS, PROCESSED, RAW, STUDY_AREA  # noqa: E402

# ----------------------------------------------------------------- design tokens
SURFACE    = "#fcfcfb"
INK        = "#0b0b0b"
INK_2      = "#52514e"
MUTED      = "#898781"
GRID       = "#e1e0d9"
BASELINE   = "#c3c2b7"
SERIES_1   = "#2a78d6"   # blue
SERIES_2   = "#eb6834"   # orange
NEUTRAL    = "#dedcd4"   # for "not applicable" areas on maps

# one-hue sequential ramp, light -> dark
BLUE_RAMP = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
             "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281",
             "#0d366b"]
SEQ = LinearSegmentedColormap.from_list("seq_blue", BLUE_RAMP, N=256)

plt.rcParams.update({
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "font.family": ["DejaVu Sans"],
    "font.size": 9,
    "text.color": INK,
    "axes.labelcolor": INK_2,
    "axes.edgecolor": BASELINE,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.titlesize": 11,
    "axes.titleweight": "bold",
    "axes.titlecolor": INK,
    "axes.grid": False,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 200,
})


def tidy(ax, *, xgrid=False, ygrid=False):
    """Recessive grid behind the marks; no dashes."""
    ax.set_axisbelow(True)
    if xgrid:
        ax.xaxis.grid(True, color=GRID, linewidth=0.7, linestyle="-")
    if ygrid:
        ax.yaxis.grid(True, color=GRID, linewidth=0.7, linestyle="-")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)


def titled(ax, title, subtitle=None, pad=24):
    """
    Title above subtitle above the plot, with no overlap.

    matplotlib's title sits right on the axes top, so a subtitle placed at
    y>1 lands on top of it. Padding the title upwards first leaves a clean
    band for the subtitle.
    """
    ax.set_title(title, loc="left", pad=pad if subtitle else 10)
    if subtitle:
        ax.text(0, 1.015, subtitle, transform=ax.transAxes,
                va="bottom", ha="left", fontsize=8.5, color=INK_2)


def save(fig, name):
    path = DOCS / name
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    kb = path.stat().st_size / 1024
    print(f"  wrote docs/{name}  ({kb:.0f} kB)")


AHN_NODATA = 3.4028234663852886e38


def load_tif(path):
    with rasterio.open(path) as src:
        a = src.read(1).astype("float32")
        t, crs = src.transform, src.crs
    a[a >= AHN_NODATA * 0.5] = np.nan
    return a, t, crs


# =============================================================== 1. SVF map
def fig_svf_map(svf, open_ground, stats):
    fig, ax = plt.subplots(figsize=(7.2, 7.2))

    # Buildings and water are shown neutral: SVF on a roof is not meaningful,
    # and leaving them on the ramp would make them read as "very enclosed".
    ax.imshow(np.ones_like(svf), cmap=LinearSegmentedColormap.from_list(
        "n", [NEUTRAL, NEUTRAL]), vmin=0, vmax=1, interpolation="nearest")
    shown = np.where(open_ground, svf, np.nan)
    im = ax.imshow(shown, cmap=SEQ, vmin=0.2, vmax=1.0, interpolation="nearest")

    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    g = stats["open_ground"]
    titled(ax,
           f"Sky View Factor at pedestrian level — {STUDY_AREA.name}, Rotterdam",
           f"open ground only · mean {g['mean']:.2f} · "
           f"{stats['parameters']['n_directions']} directions · "
           f"{stats['parameters']['search_radius_m']:.0f} m radius · "
           f"{stats['parameters']['cell_size_m']} m cells")

    cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label("SVF  ·  0 = enclosed, 1 = open sky", color=INK_2, fontsize=8.5)
    cb.outline.set_visible(False)
    cb.ax.tick_params(colors=MUTED, length=0)

    # scale bar: the raster is 0.5 m cells
    px_per_m = 1.0 / stats["parameters"]["cell_size_m"]
    bar_m = 200
    x0, y0 = svf.shape[1] * 0.045, svf.shape[0] * 0.945
    ax.plot([x0, x0 + bar_m * px_per_m], [y0, y0], color=INK, lw=3,
            solid_capstyle="butt",
            path_effects=[pe.withStroke(linewidth=5.5, foreground=SURFACE)])
    ax.text(x0 + bar_m * px_per_m / 2, y0 - svf.shape[0] * 0.008, f"{bar_m} m",
            ha="center", va="bottom", fontsize=8, color=INK,
            path_effects=[pe.withStroke(linewidth=3, foreground=SURFACE)])

    ax.text(0.985, 0.982, "buildings & water not evaluated",
            transform=ax.transAxes, ha="right", va="top", fontsize=8,
            color=INK_2,
            bbox=dict(boxstyle="round,pad=0.45", fc=NEUTRAL, ec="none"))
    save(fig, "fig_svf_map.png")


# ====================================================== 2. SVF distribution
def fig_svf_distribution(svf, open_ground, stats):
    v = svf[open_ground & np.isfinite(svf)]
    g = stats["open_ground"]
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    tidy(ax, ygrid=True)

    counts, edges = np.histogram(v, bins=50, range=(0, 1))
    centres = (edges[:-1] + edges[1:]) / 2
    ax.bar(centres, counts / 1000, width=(edges[1] - edges[0]) * 0.86,
           color=SERIES_1, linewidth=0)

    ax.axvline(g["mean"], color=INK, lw=1.6)
    ax.annotate(f"mean {g['mean']:.2f}",
                xy=(g["mean"], counts.max() / 1000 * 0.94),
                xytext=(8, 0), textcoords="offset points",
                color=INK, fontsize=9, fontweight="bold", va="center")
    ax.annotate(f"p05 {g['p05']:.2f}", xy=(g["p05"], counts.max() / 1000 * 0.42),
                xytext=(6, 0), textcoords="offset points",
                color=INK_2, fontsize=8, va="center")
    ax.axvline(g["p05"], color=BASELINE, lw=1.2)

    ax.set_xlim(0, 1)
    ax.set_xlabel("Sky View Factor")
    ax.set_ylabel("cells (thousands)")
    titled(ax, "How enclosed is open ground in Bloemhof?",
           f"{len(v):,} cells of street, garden and square, at 1.75 m above ground")
    save(fig, "fig_svf_distribution.png")


# =========================================================== 3. tree species
def fig_species(veg):
    top = veg["top_species"][:12][::-1]
    names = [s["species"] for s in top]
    vals = [s["n"] for s in top]

    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    tidy(ax, xgrid=True)
    y = np.arange(len(top))
    # one colour: the bars are nominal categories, not a value ramp
    ax.barh(y, vals, color=SERIES_1, height=0.68, linewidth=0)
    ax.set_yticks(y, names, fontsize=8.5, color=INK)
    ax.set_xlabel("trees")
    titled(ax, f"Most common street trees — {veg['n_trees']:,} trees, "
               f"{veg['n_species']} species",
           f"the top 12 are {100 * sum(vals) / veg['n_trees']:.0f}% of all trees; "
           f"plane alone is {100 * max(vals) / veg['n_trees']:.0f}%")
    # label only the ends that carry the story
    for yi, v in zip(y, vals):
        if v == max(vals) or yi == 0:
            ax.text(v + max(vals) * 0.012, yi, f"{v}", va="center",
                    fontsize=8.5, color=INK, fontweight="bold")
    ax.set_xlim(0, max(vals) * 1.09)
    save(fig, "fig_tree_species.png")


# ====================================================== 4. tree height classes
def fig_height_classes(trees):
    order = ["<6 m.", "6-9 m.", "9-12 m.", "12-15 m.", "15-18 m.", "18-24 m.", "> 24 m."]
    labels = ["< 6", "6–9", "9–12", "12–15", "15–18", "18–24", "> 24"]
    counts = []
    for cls in order:
        counts.append(sum(1 for f in trees["features"]
                          if f["properties"].get("height_class") == cls))
    unknown = sum(1 for f in trees["features"]
                  if not f["properties"].get("height_class"))

    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    tidy(ax, ygrid=True)
    x = np.arange(len(order))
    ax.bar(x, counts, color=SERIES_1, width=0.66, linewidth=0)
    ax.set_xticks(x, labels)
    ax.set_xlabel("height class (m)")
    ax.set_ylabel("trees")
    titled(ax, "Tree height distribution",
           "the register records a class, not a measured height"
           + (f" · {unknown} trees unclassified" if unknown else ""))
    peak = int(np.argmax(counts))
    ax.text(peak, counts[peak] * 1.02, f"{counts[peak]}", ha="center",
            va="bottom", fontsize=9, color=INK, fontweight="bold")
    save(fig, "fig_tree_heights.png")


# ============================================================= 5. tree map
def fig_tree_map(trees_rd, veg):
    xs = np.array([f["geometry"]["coordinates"][0] for f in trees_rd["features"]])
    ys = np.array([f["geometry"]["coordinates"][1] for f in trees_rd["features"]])
    hs = np.array([f["properties"]["height_m"] for f in trees_rd["features"]])
    cr = np.array([f["properties"]["crown_m"] for f in trees_rd["features"]])

    fig, ax = plt.subplots(figsize=(7.2, 6.8))
    sc = ax.scatter(xs, ys, c=hs, s=(cr / 2) ** 2 * 1.6, cmap=SEQ,
                    vmin=4, vmax=27, linewidths=0.3, edgecolors=SURFACE, alpha=0.95)
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    titled(ax, f"Where the trees are — {veg['n_trees']:,} trees, "
               f"{veg['trees_per_hectare']} per hectare",
           "dot size is crown diameter · colour is height class midpoint")

    cb = fig.colorbar(sc, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label("tree height (m)", color=INK_2, fontsize=8.5)
    cb.outline.set_visible(False)
    cb.ax.tick_params(colors=MUTED, length=0)

    span_y = ys.max() - ys.min()
    x0 = xs.min() + (xs.max() - xs.min()) * 0.02
    y0 = ys.min() - span_y * 0.035          # below the dots, not on top of them
    ax.plot([x0, x0 + 200], [y0, y0], color=INK, lw=3, solid_capstyle="butt",
            path_effects=[pe.withStroke(linewidth=5.5, foreground=SURFACE)])
    ax.text(x0 + 100, y0 + span_y * 0.008, "200 m", ha="center", va="bottom",
            fontsize=8, color=INK,
            path_effects=[pe.withStroke(linewidth=3, foreground=SURFACE)])
    ax.set_ylim(y0 - span_y * 0.03, ys.max() + span_y * 0.03)
    save(fig, "fig_tree_map.png")


# ================================================ 6. what the trees do to SVF
def fig_canopy_effect(svf, open_ground, transform, trees_rd):
    """Compare SVF under tree crowns against open ground well away from trees."""
    from scipy.ndimage import distance_transform_edt

    cell = abs(transform.a)
    h, w = svf.shape
    xs = np.array([f["geometry"]["coordinates"][0] for f in trees_rd["features"]])
    ys = np.array([f["geometry"]["coordinates"][1] for f in trees_rd["features"]])
    cr = np.array([f["properties"]["crown_m"] for f in trees_rd["features"]]) / 2.0

    cols = np.floor((xs - transform.c) / transform.a).astype(int)
    rows = np.floor((ys - transform.f) / transform.e).astype(int)
    inside = (rows >= 0) & (rows < h) & (cols >= 0) & (cols < w)
    rows, cols, cr = rows[inside], cols[inside], cr[inside]

    seeds = np.zeros((h, w), dtype=bool)
    seeds[rows, cols] = True
    # distance in metres to the nearest tree trunk
    dist = distance_transform_edt(~seeds) * cell

    canopy = np.zeros((h, w), dtype=bool)
    for r, c, rad in zip(rows, cols, cr):
        rr = int(np.ceil(rad / cell))
        r0, r1 = max(0, r - rr), min(h, r + rr + 1)
        c0, c1 = max(0, c - rr), min(w, c + rr + 1)
        yy, xx = np.ogrid[r0:r1, c0:c1]
        canopy[r0:r1, c0:c1] |= ((yy - r) ** 2 + (xx - c) ** 2) * cell ** 2 <= rad ** 2

    under = svf[open_ground & canopy & np.isfinite(svf)]
    away = svf[open_ground & (dist > 15) & np.isfinite(svf)]

    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    tidy(ax, ygrid=True)
    bins = np.linspace(0, 1, 46)
    for data, colour, label in ((away, SERIES_1, "more than 15 m from any tree"),
                                (under, SERIES_2, "under a tree crown")):
        cnt, edges = np.histogram(data, bins=bins, density=True)
        centres = (edges[:-1] + edges[1:]) / 2
        ax.plot(centres, cnt, color=colour, lw=2, label=label)
        ax.fill_between(centres, cnt, color=to_rgba(colour, 0.13), linewidth=0)
        ax.axvline(data.mean(), color=colour, lw=1.1)

    ax.set_xlim(0, 1)
    ax.set_xlabel("Sky View Factor")
    ax.set_ylabel("density")
    drop = away.mean() - under.mean()
    titled(ax, "Street trees are doing real work on enclosure",
           f"mean SVF {away.mean():.2f} in the open vs {under.mean():.2f} under "
           f"canopy — a drop of {drop:.2f} ({100 * drop / away.mean():.0f}%)")
    leg = ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    for t in leg.get_texts():
        t.set_color(INK_2)
    save(fig, "fig_canopy_effect.png")
    return {"svf_open": round(float(away.mean()), 4),
            "svf_under_canopy": round(float(under.mean()), 4),
            "difference": round(float(drop), 4),
            "n_open_cells": int(away.size), "n_canopy_cells": int(under.size)}


# ==================================================================== main
def main() -> int:
    need = [PROCESSED / "svf.tif", PROCESSED / "svf_summary.json",
            PROCESSED / "vegetation_summary.json",
            RAW / "rotterdam_trees_rd.geojson", PROCESSED / "trees.geojson",
            RAW / "ahn_dsm_05m.tif", RAW / "ahn_dtm_05m.tif"]
    missing = [p for p in need if not p.exists()]
    if missing:
        print("missing inputs — run fetch_ahn.py, fetch_trees.py and "
              "sky_view_factor.py first:")
        for p in missing:
            print(f"   {p}")
        return 1

    print("Building figures…")
    svf, transform, _ = load_tif(PROCESSED / "svf.tif")
    stats = json.loads((PROCESSED / "svf_summary.json").read_text())
    veg = json.loads((PROCESSED / "vegetation_summary.json").read_text())
    trees = json.loads((PROCESSED / "trees.geojson").read_text())
    trees_rd = json.loads((RAW / "rotterdam_trees_rd.geojson").read_text())

    # rebuild the open-ground mask on the cropped SVF grid
    dsm, _, _ = load_tif(RAW / "ahn_dsm_05m.tif")
    dtm, _, _ = load_tif(RAW / "ahn_dtm_05m.tif")
    pad = (dsm.shape[0] - svf.shape[0]) // 2
    ndsm = (dsm - dtm)[pad:pad + svf.shape[0], pad:pad + svf.shape[1]]
    open_ground = np.isfinite(ndsm) & (ndsm < 2.0)

    fig_svf_map(svf, open_ground, stats)
    fig_svf_distribution(svf, open_ground, stats)
    fig_species(veg)
    fig_height_classes(trees)
    fig_tree_map(trees_rd, veg)
    effect = fig_canopy_effect(svf, open_ground, transform, trees_rd)

    # the canopy effect is a finding, not just a picture — keep the numbers
    veg["svf_canopy_effect"] = effect
    (PROCESSED / "vegetation_summary.json").write_text(json.dumps(veg, indent=2) + "\n")
    print(f"\n  canopy effect: SVF {effect['svf_open']} open vs "
          f"{effect['svf_under_canopy']} under canopy "
          f"(-{effect['difference']})")
    print("  added to vegetation_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
