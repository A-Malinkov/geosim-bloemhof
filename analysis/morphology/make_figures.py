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
    # viridis, as the app's SVF overlay (sky_view_factor.py): purple = enclosed,
    # yellow = open sky, so the report and the map read the same way.
    im = ax.imshow(shown, cmap="viridis", vmin=0.2, vmax=1.0, interpolation="nearest")

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


# ========================================================== 7. Spacematrix
def fig_spacematrix(dens):
    """
    The Spacematrix diagram: GSI against FSI, with L and OSR isolines.

    Berghauser Pont & Haupt (2010). The point of the plot is that FSI alone
    does not describe a fabric -- where a cell sits in this space tells you
    whether it is low-rise and packed, mid-rise with courtyards, or towers in
    open ground. L and OSR are not extra data, they are contours of the same
    two axes, which is why they are drawn rather than plotted.
    """
    pts = dens["spacematrix"]
    g = np.array([p["gsi"] for p in pts])
    f = np.array([p["fsi"] for p in pts])
    h = np.array([p["height_mean_m"] if p["height_mean_m"] is not None else np.nan
                  for p in pts])

    fig, ax = plt.subplots(figsize=(7.2, 6.2))
    tidy(ax, xgrid=True, ygrid=True)
    xmax = max(0.75, float(g.max()) * 1.12)
    ymax = max(2.5, float(f.max()) * 1.12)

    # L isolines: FSI = L * GSI, straight through the origin
    for L in (1, 2, 3, 4, 6, 8):
        ax.plot([0, xmax], [0, L * xmax], color=GRID, lw=0.9, zorder=1)
        yx = L * xmax
        tag = f"L {L}"          # "L 4" not a bare "4", so it cannot be read as OSR
        if yx <= ymax:
            ax.text(xmax * 0.99, yx, tag, color=MUTED, fontsize=7.5,
                    va="center", ha="right", zorder=1)
        else:
            ax.text(ymax / L, ymax * 0.99, tag, color=MUTED, fontsize=7.5,
                    va="top", ha="center", zorder=1)

    # OSR isolines: FSI = (1 - GSI) / OSR
    gg = np.linspace(0.001, min(0.99, xmax), 200)
    for osr in (0.2, 0.5, 1.0, 2.0):
        ax.plot(gg, (1 - gg) / osr, color=GRID, lw=0.9, ls="-", zorder=1)
        yi = (1 - 0.62) / osr
        if 0.05 < yi < ymax * 0.96:
            ax.text(0.62, yi, f" OSR {osr:g}", color=MUTED, fontsize=7.5,
                    va="bottom", ha="left", zorder=1)

    sc = ax.scatter(g, f, c=h, cmap=SEQ, vmin=4, vmax=22, s=26,
                    linewidths=0.4, edgecolors=SURFACE, zorder=3)

    # Mark each buurt, and the two together. Two adjacent buurten with different
    # fabric is the point of the plot: a single combined star would hide that one
    # is low and packed while the other is taller and more open.
    #
    # The labels go in a corner block, not beside the stars. Annotating each
    # point put text straight through the data cloud and the three captions
    # overlapped each other.
    marks = list((dens.get("per_buurt") or {}).values())
    comb = dens.get("combined")
    entries = [(b, False) for b in marks if b] + ([(comb, True)] if comb else [])
    for b, is_comb in entries:
        ax.scatter([b["gsi"]], [b["fsi"]], marker="*",
                   s=460 if is_comb else 320,
                   color=SERIES_2 if is_comb else INK,
                   edgecolors=SURFACE, linewidths=1.2, zorder=5)

    if entries:
        # One text line per entry, drawn separately so each star glyph carries
        # the colour of the marker it refers to. Two identical black stars with
        # a shared caption leaves the reader guessing which is which.
        # An explicit patch, not a text bbox: a bbox sized to placeholder
        # whitespace ends up far narrower than the lines drawn over it.
        import matplotlib.patches as mpatch
        h = 0.042 * len(entries) + 0.030
        ax.add_patch(mpatch.FancyBboxPatch(
            (0.012, 0.988 - h), 0.80, h,
            boxstyle="round,pad=0.006", transform=ax.transAxes,
            facecolor=SURFACE, edgecolor=GRID, linewidth=0.8, zorder=4))
        for i, (b, is_comb) in enumerate(entries):
            y = 0.972 - i * 0.042
            col = SERIES_2 if is_comb else INK
            ax.text(0.028, y, "\u2605", transform=ax.transAxes, va="top",
                    ha="left", fontsize=11, color=col, zorder=6)
            ax.text(0.058, y, f"{b['name']}:  GSI {b['gsi']:.2f}   "
                              f"FSI {b['fsi']:.2f}   {b['layers']:.1f} storeys",
                    transform=ax.transAxes, va="top", ha="left", fontsize=8.5,
                    color=INK, zorder=6,
                    fontweight="bold" if is_comb else "normal")

    ax.set_xlim(0, xmax); ax.set_ylim(0, ymax)
    ax.set_xlabel("GSI — ground space index (built footprint / land area)")
    ax.set_ylabel("FSI — floor space index (floor area / land area)")
    titled(ax, "Spacematrix — what kind of density is this?",
           f"one dot per {dens['parameters']['cell_size_m']:.0f} m cell · "
           f"grey lines are storeys (L) and open space ratio (OSR)")
    cb = fig.colorbar(sc, ax=ax, fraction=0.04, pad=0.02)
    cb.set_label("mean building height in cell (m)", color=INK_2, fontsize=8.5)
    cb.outline.set_visible(False)
    cb.ax.tick_params(colors=MUTED, length=0)
    save(fig, "fig_spacematrix.png")


# ================================================ 8. density + height maps
def fig_density_maps(dens, grid_geo):
    """FSI and within-cell height variation, as two small choropleths."""
    cell = dens["parameters"]["cell_size_m"]
    feats = grid_geo["features"]
    g = grid_geo.get("_grid") or {}
    nx, ny = g.get("nx"), g.get("ny")
    if not nx or "row" not in feats[0]["properties"]:
        print("  (density maps skipped — regenerate density_grid.geojson)")
        return

    def raster(key):
        a = np.full((ny, nx), np.nan)
        for f in feats:
            p = f["properties"]
            v = p.get(key)
            if v is None or p.get("sparse"):
                continue
            a[p["row"], p["col"]] = v
        return a[::-1]           # row 0 is the south edge; flip so north is up

    fig, axes = plt.subplots(1, 2, figsize=(7.4, 4.2))
    for ax, key, label in (
            (axes[0], "fsi", "FSI — floor space index"),
            (axes[1], "height_std_m", "height variation within cell (σ, m)")):
        a = raster(key)
        vm = float(np.nanpercentile(a, 97))
        im = ax.imshow(a, cmap=SEQ, vmin=0, vmax=vm, interpolation="nearest")
        ax.set_xticks([]); ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.set_title(label, loc="left", fontsize=9.5, color=INK, pad=6)
        cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
        cb.outline.set_visible(False)
        cb.ax.tick_params(colors=MUTED, length=0, labelsize=7.5)
    fig.suptitle(f"Density and height variation — {STUDY_AREA.name}, "
                 f"{cell:.0f} m cells",
                 x=0.012, ha="left", fontsize=11, fontweight="bold", color=INK)
    fig.text(0.012, 0.905, "cells with fewer than 3 buildings are left blank",
             fontsize=8.5, color=INK_2, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.89])
    save(fig, "fig_density_maps.png")


# ============================================================ 9. land-use mix
def fig_landuse(lu, grid_geo):
    """
    Composition of built floor space, and how the mix varies across the area.

    The composition bars are nominal categories, so they get ONE colour — a
    value ramp there would imply an order the categories do not have. The map
    encodes a magnitude (entropy), so it gets the sequential ramp.
    """
    comp = [c for c in lu["composition"] if c["share"] > 0][:9][::-1]
    names = [c["category"] for c in comp]
    shares = [100 * c["share"] for c in comp]

    g = grid_geo.get("_grid") or {}
    nx, ny = g.get("nx"), g.get("ny")
    a = np.full((ny, nx), np.nan)
    for f in grid_geo["features"]:
        pr = f["properties"]
        if pr.get("sparse"):
            continue
        a[pr["row"], pr["col"]] = pr["shannon"]
    a = a[::-1]

    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(7.4, 4.3),
                                  gridspec_kw={"width_ratios": [1.15, 1]})
    tidy(ax, xgrid=True)
    y = np.arange(len(comp))
    ax.barh(y, shares, color=SERIES_1, height=0.66, linewidth=0)
    ax.set_yticks(y, names, fontsize=8.5, color=INK)
    ax.set_xlabel("share of usable floor area (%)")
    ax.set_title("What the floor space is used for", loc="left",
                 fontsize=9.5, pad=6)
    top = max(shares)
    ax.text(top - 1, y[-1], f"{top:.0f}%", va="center", ha="right",
            fontsize=8.5, color="#ffffff", fontweight="bold")
    ax.set_xlim(0, top * 1.06)

    im = ax2.imshow(a, cmap=SEQ, vmin=0, vmax=float(np.nanmax(a)),
                    interpolation="nearest")
    ax2.set_xticks([]); ax2.set_yticks([])
    for sp in ax2.spines.values():
        sp.set_visible(False)
    ax2.set_title("Where the mix is (Shannon entropy)", loc="left",
                  fontsize=9.5, pad=6)
    cb = fig.colorbar(im, ax=ax2, fraction=0.046, pad=0.02)
    cb.outline.set_visible(False)
    cb.ax.tick_params(colors=MUTED, length=0, labelsize=7.5)

    o = lu["overall"]
    b = lu.get("combined") or {}
    fig.suptitle(f"Land-use mix — {STUDY_AREA.name}, Rotterdam",
                 x=0.012, ha="left", fontsize=11, fontweight="bold", color=INK)
    fig.text(0.012, 0.912,
             f"Shannon {b.get('shannon_area', o['shannon_area']):.3f} of a possible 1.0 · "
             f"{100 * o['dominant_share']:.0f}% of floor space is {o['dominant']} · "
             f"cells with fewer than 10 units left blank",
             fontsize=8.5, color=INK_2, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.885])
    save(fig, "fig_landuse_mix.png")


# ========================================================= 10. land-use ABM
LU_LEGEND = ("residential", "retail", "amenity", "green", "industry")


def lu_cmap(ca):
    from matplotlib.colors import ListedColormap
    classes = ca["classes"]
    cols = [tuple(c / 255 for c in ca["colours"][k]) for k in classes]
    return classes, cols, ListedColormap(cols)


def outline_site(ax, mask, color=INK, lw=1.2):
    """Trace the design-site cells, so the outline follows the 25 m grid.

    Padded by one empty cell, so the outline closes where the site runs off
    the model grid instead of being left open there.
    """
    a = np.pad(np.asarray(mask, dtype=float), 1)
    ny, nx = a.shape
    xlim, ylim = ax.get_xlim(), ax.get_ylim()
    ax.contour(np.arange(nx) - 1, np.arange(ny) - 1, a, levels=[0.5],
               colors=[color], linewidths=lw)
    ax.set_xlim(xlim); ax.set_ylim(ylim)


def fig_abm(ca, rl):
    """The CA scenarios over the whole study area, design site outlined."""
    import matplotlib.patches as mpatches

    classes, cols, cmap = lu_cmap(ca)
    names = list(ca["scenarios"].keys())
    site = rl.get("site_mask") if rl else None

    fig = plt.figure(figsize=(7.4, 3.2))
    gs = fig.add_gridspec(1, len(names), wspace=0.06, top=0.78, bottom=0.10,
                          left=0.01, right=0.99)
    for i, n in enumerate(names):
        sc = ca["scenarios"][n]
        ax = fig.add_subplot(gs[0, i])
        ax.imshow(np.array(sc["steps"][-1]["grid"], dtype="int16"), cmap=cmap,
                  vmin=0, vmax=len(classes) - 1, interpolation="nearest")
        if site:
            outline_site(ax, site)
        ax.set_xticks([]); ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_visible(False)
        star = " *" if n == ca.get("preferred") else ""
        ax.set_title(f"{n}{star}\nmix {sc['score']['landuse_mix']:.3f} · "
                     f"objective {sc['objective_best']:.3f}",
                     fontsize=8.5, color=INK, pad=4)

    handles = [mpatches.Patch(color=cols[classes.index(k)], label=k)
               for k in LU_LEGEND]
    if site:
        handles.append(mpatches.Patch(facecolor="none", edgecolor=INK,
                                      label="design site"))
    leg = fig.legend(handles=handles, frameon=False, fontsize=7.5,
                     ncol=len(handles), loc="lower center",
                     bbox_to_anchor=(0.5, 0.0), handlelength=1.1)
    for t in leg.get_texts():
        t.set_color(INK_2)

    fig.suptitle("Land-use scenarios from the cellular automaton",
                 x=0.012, y=1.0, ha="left", fontsize=11, fontweight="bold",
                 color=INK)
    fig.text(0.012, 0.915,
             "Bloemhof + Hillesluis, 25 m cells · rules are assumed, "
             "best of the replicates shown · * = preferred by the objective",
             fontsize=8.5, color=INK_2, ha="left")
    save(fig, "fig_landuse_abm.png")


def fig_rl_keep_housing(ca, rl):
    """The same agent with today's number of residential cells kept."""
    n = rl["baseline_score"]["residential_cells"]
    fig_rl_site(ca, rl, out="fig_landuse_rl_keep_housing.png",
                heading=f"The RL agent re-plans the site, keeping all {n} housing cells",
                plan_label=f"Plan with {n} housing cells kept")


def fig_rl_site(ca, rl, out="fig_landuse_rl_site.png",
                heading="The RL agent re-plans the design site",
                plan_label="RL agent's plan"):
    """The design site today against the RL agent's plan, and how it learned."""
    import matplotlib.patches as mpatches

    classes, cols, cmap = lu_cmap(ca)
    site = np.array(rl["site_mask"], dtype=bool)
    today = np.array(rl["today_grid"], dtype="int16")
    plan = np.array(rl["best_grid"], dtype="int16")

    rows, cols_ = np.where(site)
    m = 3                                  # cells of context around the site
    r0, r1 = max(0, rows.min() - m), min(site.shape[0], rows.max() + m + 1)
    c0, c1 = max(0, cols_.min() - m), min(site.shape[1], cols_.max() + m + 1)
    crop = (slice(r0, r1), slice(c0, c1))

    fig = plt.figure(figsize=(7.4, 5.6))
    gs = fig.add_gridspec(2, 2, height_ratios=[1.15, 1.0], hspace=0.38,
                          wspace=0.28, top=0.83, bottom=0.15, left=0.08,
                          right=0.98)

    base, best = rl["baseline_score"], rl["score"]
    for i, (title, g, sc) in enumerate((
            ("Design site today", today, base),
            (plan_label, plan, best))):
        ax = fig.add_subplot(gs[0, i])
        ax.imshow(g[crop], cmap=cmap, vmin=0, vmax=len(classes) - 1,
                  interpolation="nearest")
        # context outside the site is drawn, but washed out: it is fixed
        veil = np.where(site[crop], 0.0, 0.6)
        ax.imshow(np.dstack([np.full(veil.shape, c) for c in
                             to_rgba(SURFACE)[:3]] + [veil]),
                  interpolation="nearest")
        outline_site(ax, site[crop])
        ax.set_xticks([]); ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_visible(False)
        d = sc["mean_distance_to_amenity_m"]
        ax.set_title(f"{title}\nmix {sc['landuse_mix']:.3f} · green "
                     f"{100 * sc['green_share']:.0f} % · "
                     f"{'–' if d is None else f'{d:.0f} m'} to amenity",
                     fontsize=8.5, color=INK, pad=4)

    # what the site is made of, today vs plan
    ax = fig.add_subplot(gs[1, 0])
    tidy(ax, xgrid=True)
    keys = [k for k in LU_LEGEND + ("vacant",)
            if (today[site] == classes.index(k)).any()
            or (plan[site] == classes.index(k)).any()]
    y = np.arange(len(keys))
    n_today = [int((today[site] == classes.index(k)).sum()) for k in keys]
    n_plan = [int((plan[site] == classes.index(k)).sum()) for k in keys]
    h = 0.38
    ax.barh(y - h / 2, n_today, h, color=MUTED, label="today")
    ax.barh(y + h / 2, n_plan, h, color=[cols[classes.index(k)] for k in keys],
            label="RL plan")
    for yi, a, b in zip(y, n_today, n_plan):
        ax.text(max(a, b) + 2, yi, f"{a} → {b}", va="center", fontsize=7.5,
                color=INK_2)
    ax.set_yticks(y, keys)
    ax.invert_yaxis()
    ax.set_xlim(0, max(n_today + n_plan) * 1.35)
    ax.set_xlabel("cells in the design site")
    ax.set_title("Grey today, coloured the plan", loc="left", fontsize=8.5,
                 fontweight="normal", color=INK_2)

    # learning curve — today's objective is far below, so it is stated, not drawn
    ax2 = fig.add_subplot(gs[1, 1])
    tidy(ax2, ygrid=True)
    c = np.array(rl["learning_curve"])
    ax2.plot(c, color=SERIES_1, lw=0.9, alpha=0.45)
    k = max(1, len(c) // 20)
    smooth = np.convolve(c, np.ones(k) / k, mode="valid")
    ax2.plot(np.arange(len(smooth)) + k // 2, smooth, color=SERIES_2, lw=2)
    ax2.set_xlim(0, len(c) - 1)
    ax2.set_xlabel("RL training episode")
    ax2.set_ylabel("objective over the site")
    ax2.set_title(f"Best {rl['best_objective']:.3f}; the site today scores "
                  f"{rl['baseline_objective']:.3f}", loc="left", fontsize=8.5,
                  fontweight="normal", color=INK_2)

    handles = [mpatches.Patch(color=cols[classes.index(k)], label=k)
               for k in LU_LEGEND]
    leg = fig.legend(handles=handles, frameon=False, fontsize=7.5,
                     ncol=len(handles), loc="lower center",
                     bbox_to_anchor=(0.5, 0.0), handlelength=1.1)
    for t in leg.get_texts():
        t.set_color(INK_2)

    fig.suptitle(heading,
                 x=0.012, y=0.995, ha="left", fontsize=11, fontweight="bold",
                 color=INK)
    fig.text(0.012, 0.950,
             f"{rl['parameters']['programme_cells']}"
             " cells cleared and re-allocated · surroundings fixed and washed out "
             "· scored over the site only, not comparable with the CA\n"
             "The model grid ends at the buurt boundary, so the site's strip "
             "south of Strevelsweg is cut off at the bottom edge",
             fontsize=8.5, color=INK_2, ha="left", va="top")
    save(fig, out)


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

    dens_path = PROCESSED / "density_summary.json"
    grid_path = PROCESSED / "density_grid.geojson"
    if dens_path.exists() and grid_path.exists():
        dens = json.loads(dens_path.read_text())
        grid_geo = json.loads(grid_path.read_text())
        fig_spacematrix(dens)
        fig_density_maps(dens, grid_geo)
    else:
        print("  (skipping density figures — run density_height.py first)")

    lu_path = PROCESSED / "landuse_summary.json"
    lug_path = PROCESSED / "landuse_grid.geojson"
    if lu_path.exists() and lug_path.exists():
        fig_landuse(json.loads(lu_path.read_text()),
                    json.loads(lug_path.read_text()))
    else:
        print("  (skipping land-use figure — run landuse_mix.py first)")

    abm_path = PROCESSED / "landuse_abm.json"
    if abm_path.exists():
        abm = json.loads(abm_path.read_text())
        if abm.get("scenarios"):
            rl_path = PROCESSED / "landuse_rl.json"
            rl = json.loads(rl_path.read_text()) if rl_path.exists() else None
            fig_abm(abm, rl)
            if rl and rl.get("site_mask"):
                fig_rl_site(abm, rl)
            keep_path = PROCESSED / "landuse_rl_keep_housing.json"
            if keep_path.exists():
                fig_rl_keep_housing(abm, json.loads(keep_path.read_text()))
    else:
        print("  (skipping ABM figure — run ca_landuse.py first)")

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
