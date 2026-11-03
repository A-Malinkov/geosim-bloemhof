#!/usr/bin/env python3
"""
make_figures.py - report figures for morphology and vegetation.

Owner: Atanas Malinkov

    python analysis/morphology/fetch_ahn.py
    python analysis/morphology/fetch_trees.py
    python analysis/morphology/sky_view_factor.py
    python analysis/morphology/make_figures.py

Writes PNGs into docs/ at 200 dpi. Magnitude in one hue light to dark, fixed
colours per category, no legend for a single series, solid hairline grids.
"""

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
from common.project import DOCS, PROCESSED, RAW, STUDY_AREA  #noqa: E402

#--- design tokens
SURFACE    = "#fcfcfb"
INK        = "#0b0b0b"
INK_2      = "#52514e"
MUTED      = "#898781"
GRID       = "#e1e0d9"
BASELINE   = "#c3c2b7"
SERIES_1   = "#2a78d6"   #blue
SERIES_2   = "#eb6834"   #orange
NEUTRAL    = "#dedcd4"   #for "not applicable" areas on maps

#one-hue sequential ramp, light -> dark
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
    #Recessive grid behind the marks; no dashes.
    ax.set_axisbelow(True)
    if xgrid:
        ax.xaxis.grid(True, color=GRID, linewidth=0.7, linestyle="-")
    if ygrid:
        ax.yaxis.grid(True, color=GRID, linewidth=0.7, linestyle="-")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)


def titled(ax, title, subtitle=None, pad=24):
    #Title above subtitle above the plot, with no overlap.
    #
    #matplotlib's title sits right on the axes top, so a subtitle placed at
    #y>1 lands on top of it. Padding the title upwards first leaves a clean
    #band for the subtitle.
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


#=============================================================== 1. SVF map
def fig_svf_map(svf, open_ground, stats):
    fig, ax = plt.subplots(figsize=(7.2, 7.2))

    #Buildings and water are shown neutral: SVF on a roof is not meaningful,
    #and leaving them on the ramp would make them read as "very enclosed".
    ax.imshow(np.ones_like(svf), cmap=LinearSegmentedColormap.from_list(
        "n", [NEUTRAL, NEUTRAL]), vmin=0, vmax=1, interpolation="nearest")
    shown = np.where(open_ground, svf, np.nan)
    #viridis, as the app's SVF overlay (sky_view_factor.py): purple = enclosed,
    #yellow = open sky, so the report and the map read the same way.
    im = ax.imshow(shown, cmap="viridis", vmin=0.2, vmax=1.0, interpolation="nearest")

    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    g = stats["open_ground"]
    titled(ax,
           f"Sky View Factor at pedestrian level: {STUDY_AREA.name}, Rotterdam",
           f"open ground only · mean {g['mean']:.2f} · "
           f"{stats['parameters']['n_directions']} directions · "
           f"{stats['parameters']['search_radius_m']:.0f} m radius · "
           f"{stats['parameters']['cell_size_m']} m cells")

    cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label("SVF  ·  0 = enclosed, 1 = open sky", color=INK_2, fontsize=8.5)
    cb.outline.set_visible(False)
    cb.ax.tick_params(colors=MUTED, length=0)

    #scale bar: the raster is 0.5 m cells
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


#====================================================== 2. SVF distribution
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


#====================================================== 4. tree height classes
def in_bloemhof(trees_rd):
    #The register trees inside the buurt polygon, the same clip as the statistics.
    from shapely.geometry import Point
    from common.project import study_area_polygon
    area = study_area_polygon()
    return [f for f in trees_rd["features"] if area.contains(Point(f["geometry"]["coordinates"]))]


def fig_height_classes(trees_rd):
    trees = {"features": in_bloemhof(trees_rd)}  #Bloemhof only, not the whole download box (2026-11-01)
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
    titled(ax, f"Tree height distribution: {len(trees['features']):,} trees in {STUDY_AREA.name}",
           "the register records a class, not a measured height"
           + (f" · {unknown} trees unclassified" if unknown else ""))
    peak = int(np.argmax(counts))
    ax.text(peak, counts[peak] * 1.02, f"{counts[peak]}", ha="center",
            va="bottom", fontsize=9, color=INK, fontweight="bold")
    save(fig, "fig_tree_heights.png")


#============================================================= 5. tree map
def fig_tree_map(trees_rd, veg):
    from common.project import study_area_polygon
    feats = in_bloemhof(trees_rd)  #Bloemhof only, not the whole download box (2026-11-01)
    xs = np.array([f["geometry"]["coordinates"][0] for f in feats])
    ys = np.array([f["geometry"]["coordinates"][1] for f in feats])
    hs = np.array([f["properties"]["height_m"] for f in feats])
    cr = np.array([f["properties"]["crown_m"] for f in feats])
    b = veg.get("combined") or {}  #the clipped statistics, so the title matches the dots

    fig, ax = plt.subplots(figsize=(7.2, 6.8))
    sc = ax.scatter(xs, ys, c=hs, s=(cr / 2) ** 2 * 1.6, cmap=SEQ,
                    vmin=4, vmax=27, linewidths=0.3, edgecolors=SURFACE, alpha=0.95)
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    area = study_area_polygon()
    for r in ([area] if area.geom_type == "Polygon" else list(area.geoms)):  #the buurt boundary
        bx, by = r.exterior.xy
        ax.plot(bx, by, color=INK, lw=1.0, zorder=0)
    titled(ax, f"Where the trees are: {len(feats):,} trees in {STUDY_AREA.name}, "
               f"{b.get('trees_per_hectare', '-')} per hectare",
           "dot size is crown diameter · colour is height class midpoint · black line: buurt boundary")

    cb = fig.colorbar(sc, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label("tree height (m)", color=INK_2, fontsize=8.5)
    cb.outline.set_visible(False)
    cb.ax.tick_params(colors=MUTED, length=0)

    span_y = ys.max() - ys.min()
    x0 = xs.min() + (xs.max() - xs.min()) * 0.02
    y0 = ys.min() - span_y * 0.035          #below the dots, not on top of them
    ax.plot([x0, x0 + 200], [y0, y0], color=INK, lw=3, solid_capstyle="butt",
            path_effects=[pe.withStroke(linewidth=5.5, foreground=SURFACE)])
    ax.text(x0 + 100, y0 + span_y * 0.008, "200 m", ha="center", va="bottom",
            fontsize=8, color=INK,
            path_effects=[pe.withStroke(linewidth=3, foreground=SURFACE)])
    ax.set_ylim(y0 - span_y * 0.03, ys.max() + span_y * 0.03)
    save(fig, "fig_tree_map.png")


#======================================================== 7. density maps
def fig_density_maps(dens, grid_geo):
    #GSI and FSI per 100 m cell as two plain maps, with the buurt outline.
    #
    #The simple student version of density (2026-11-01): how much ground is
    #built on, and how much floor space there is, cell by cell. Replaces the
    #Spacematrix scatter in the report.
    from common.project import study_area_polygon
    cell = dens["parameters"]["cell_size_m"]
    feats = grid_geo["features"]
    g = grid_geo.get("_grid") or {}
    nx, ny, origin = g.get("nx"), g.get("ny"), g.get("origin_rd")
    if not nx or not origin or "row" not in feats[0]["properties"]:
        print("  (density maps skipped: regenerate density_grid.geojson)")
        return

    def raster(key):
        a = np.full((ny, nx), np.nan)
        for f in feats:
            q = f["properties"]
            v = q.get(key)
            if v is None or q.get("sparse"):
                continue
            a[q["row"], q["col"]] = v  #row 0 is the south edge
        return a

    x0, y0 = origin
    extent = [x0, x0 + nx * cell, y0, y0 + ny * cell]  #RD metres, so the outline fits
    area = study_area_polygon()
    rings = [area] if area.geom_type == "Polygon" else list(area.geoms)
    b = dens.get("combined") or {}

    fig, axes = plt.subplots(1, 2, figsize=(7.4, 4.2))
    for ax, key, label, vmax, whole in (
            (axes[0], "gsi", "GSI: share of the land built on", 0.6, b.get("gsi")),
            (axes[1], "fsi", "FSI: floor area per m² of land", 2.5, b.get("fsi"))):
        im = ax.imshow(raster(key), cmap=SEQ, vmin=0, vmax=vmax, origin="lower",
                       extent=extent, interpolation="nearest")
        for r in rings:  #the buurt boundary the statistics are clipped to
            xs, ys = r.exterior.xy
            ax.plot(xs, ys, color=INK, lw=1.0)
        ax.set_aspect("equal")
        ax.set_xticks([]); ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_visible(False)
        title = label if whole is None else f"{label}\nwhole buurt: {whole:.2f}"
        ax.set_title(title, loc="left", fontsize=9.5, color=INK, pad=6)
        cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
        cb.outline.set_visible(False)
        cb.ax.tick_params(colors=MUTED, length=0, labelsize=7.5)
    fig.suptitle(f"Density of {STUDY_AREA.name}, {cell:.0f} m cells",
                 x=0.012, ha="left", fontsize=11, fontweight="bold", color=INK)
    fig.text(0.012, 0.905, "black line: buurt boundary · cells with fewer than 3 "
             "buildings are left blank", fontsize=8.5, color=INK_2, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.89])
    save(fig, "fig_density_maps.png")


def fig_density_site(site):
    #GSI and FSI on the design site, today and in each scenario, as two bar charts.
    names = [("baseline", "Today"), ("scenario_a", "Scenario A"),
             ("scenario_b", "Scenario B"), ("final", "Final design")]
    names = [(k, label) for k, label in names if k in site]
    labels = [label for _, label in names]
    colors = [NEUTRAL] + [SERIES_1] * (len(names) - 1)  #today in grey, the designs in blue

    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.4))
    for ax, key, title in ((axes[0], "gsi", "GSI: share of the site built on"),
                           (axes[1], "fsi", "FSI: floor area per m² of site")):
        tidy(ax, ygrid=True)
        vals = [site[k][key] for k, _ in names]
        ax.bar(labels, vals, color=colors, width=0.62, linewidth=0)
        for i, v in enumerate(vals):  #the value on each bar
            ax.text(i, v, f"{v:.2f}", ha="center", va="bottom", fontsize=8.5, color=INK)
        ax.set_ylim(0, max(vals) * 1.18)
        ax.tick_params(axis="x", labelsize=8)
        ax.set_title(title, loc="left", fontsize=9.5, color=INK, pad=6)
    fig.suptitle(f"Density on the design site ({site['site_area_ha']} ha)",
                 x=0.012, ha="left", fontsize=11, fontweight="bold", color=INK)
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    save(fig, "fig_density_site.png")


def fig_building_heights(dens):
    #One plain map: every building in the buurt, coloured by height class.
    from shapely.geometry import Point
    from common.project import design_site_polygon, study_area_polygon
    p = dens["parameters"]
    area = study_area_polygon()
    feats = json.loads((RAW / "buildings_3dbag.geojson").read_text())["features"]
    xs, ys, fp, hs = [], [], [], []
    for f in feats:  #buildings inside the buurt only, same clip as the statistics
        x, y = f["geometry"]["coordinates"]
        a, h = f["properties"].get("b3_opp_grond"), f["properties"].get("height_m")
        if not a or a <= 0 or h is None or not area.contains(Point(x, y)):
            continue
        xs.append(x); ys.append(y); fp.append(a); hs.append(h)
    xs, ys, fp, hs = map(np.array, (xs, ys, fp, hs))
    main = (fp >= p["principal_min_footprint_m2"]) & (hs >= p["principal_min_height_m"])  #sheds apart, as in the height statistics

    classes = [(0, 6, "under 6 m, 1–2 storeys", BLUE_RAMP[1]),  #four plain classes instead of a colour bar
               (6, 9, "6–9 m, 2–3 storeys", BLUE_RAMP[5]),
               (9, 15, "9–15 m, 3–5 storeys", BLUE_RAMP[8]),
               (15, 1e9, "15 m and taller", BLUE_RAMP[12])]
    fig, ax = plt.subplots(figsize=(7.2, 6.8))
    size = lambda a: np.clip(a / 10, 5, 90)  #dot area follows the footprint
    ax.scatter(xs[~main], ys[~main], s=size(fp[~main]), c=NEUTRAL, linewidths=0,
               label="sheds and small structures")
    for lo, hi, label, col in classes:
        m = main & (hs >= lo) & (hs < hi)
        ax.scatter(xs[m], ys[m], s=size(fp[m]), c=col, linewidths=0.2, edgecolors=SURFACE,
                   label=f"{label} ({m.sum():,})")
    for geom, lw, ls in ((area, 1.0, "-"), (design_site_polygon(), 1.4, "--")):  #buurt and design site outlines
        for g in getattr(geom, "geoms", [geom]):
            ax.plot(*g.exterior.xy, color=INK, lw=lw, ls=ls)
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    c = dens["combined"]
    titled(ax, f"Building heights: {STUDY_AREA.name}",
           f"GSI {c['gsi']:.2f} · FSI {c['fsi']:.2f} · {c['layers']:.1f} storeys on average · "
           "dashed line is the design site")
    ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False, fontsize=8,
              markerscale=1.6, labelcolor=INK_2)

    x0, y0 = xs.max() - 200, ys.min() - 60  #scale bar bottom right, clear of the site outline
    ax.plot([x0, x0 + 200], [y0, y0], color=INK, lw=3, solid_capstyle="butt")
    ax.text(x0 + 100, y0 + 12, "200 m", ha="center", va="bottom", fontsize=8, color=INK)
    save(fig, "fig_building_heights.png")


#============================================================ 9. land-use mix
def fig_landuse(lu, grid_geo):
    #Composition of built floor space, and how the mix varies across the area.
    #
    #The composition bars are nominal categories, so they get ONE colour: a
    #value ramp there would imply an order the categories do not have. The map
    #encodes a magnitude (entropy), so it gets the sequential ramp.
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
    fig.suptitle(f"Land-use mix: {STUDY_AREA.name}, Rotterdam",
                 x=0.012, ha="left", fontsize=11, fontweight="bold", color=INK)
    fig.text(0.012, 0.912,
             f"Shannon {b.get('shannon_area', o['shannon_area']):.3f} of a possible 1.0 · "
             f"{100 * o['dominant_share']:.0f}% of floor space is {o['dominant']} · "
             f"cells with fewer than 10 units left blank",
             fontsize=8.5, color=INK_2, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.885])
    save(fig, "fig_landuse_mix.png")


#========================================================= 10. land-use ABM
LU_LEGEND = ("residential", "retail", "amenity", "green", "industry")


def lu_cmap(ca):
    from matplotlib.colors import ListedColormap
    classes = ca["classes"]
    cols = [tuple(c / 255 for c in ca["colours"][k]) for k in classes]
    return classes, cols, ListedColormap(cols)


def outline_site(ax, mask, color=INK, lw=1.2):
    #Trace the design-site cells, so the outline follows the 25 m grid.
    #
    #Padded by one empty cell, so the outline closes where the site runs off
    #the model grid instead of being left open there.
    a = np.pad(np.asarray(mask, dtype=float), 1)
    ny, nx = a.shape
    xlim, ylim = ax.get_xlim(), ax.get_ylim()
    ax.contour(np.arange(nx) - 1, np.arange(ny) - 1, a, levels=[0.5],
               colors=[color], linewidths=lw)
    ax.set_xlim(xlim); ax.set_ylim(ylim)


def fig_abm(ca, rl):
    #The CA land-use programmes over the whole study area, design site outlined.
    import matplotlib.patches as mpatches

    classes, cols, cmap = lu_cmap(ca)
    names = list(ca["scenarios"].keys())
    site = rl.get("site_mask") if rl else None
    crop = (slice(None), slice(None))
    if site:  #since 2026-10-30 the CA rebuilds the design site: show the site with 3 cells of context
        rows, cols_ = np.where(np.array(site, dtype=bool))
        crop = (slice(max(0, rows.min() - 3), rows.max() + 4), slice(max(0, cols_.min() - 3), cols_.max() + 4))

    fig = plt.figure(figsize=(7.4, 3.2))
    gs = fig.add_gridspec(1, len(names), wspace=0.06, top=0.78, bottom=0.10,
                          left=0.01, right=0.99)
    for i, n in enumerate(names):
        sc = ca["scenarios"][n]
        ax = fig.add_subplot(gs[0, i])
        ax.imshow(np.array(sc["steps"][-1]["grid"], dtype="int16")[crop], cmap=cmap,
                  vmin=0, vmax=len(classes) - 1, interpolation="nearest")
        if site:
            outline_site(ax, np.array(site, dtype=bool)[crop].tolist())  #the outline in the cropped frame
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

    fig.suptitle("Land-use programmes from the cellular automaton",  #programmes, not the Rhino scenario_a/b
                 x=0.012, y=1.0, ha="left", fontsize=11, fontweight="bold",
                 color=INK)
    fig.text(0.012, 0.915,
             "Design site cleared and rebuilt, 25 m cells · rules are assumed · "  #the CA rebuilds the site since 2026-10-30
             "best of 12 runs · * = preferred by the objective · "
             "not the Rhino design options",  #say it on the figure too
             fontsize=8.5, color=INK_2, ha="left")
    save(fig, "fig_landuse_abm.png")


def fig_rl_training(lin):
    #Training curve of the RL agent, against the random policy and hill climbing.
    fig, ax = plt.subplots(figsize=(7.4, 3.6))
    fig.subplots_adjust(top=0.80, bottom=0.15, left=0.09, right=0.80)
    tidy(ax, ygrid=True)
    for run, col, name in ((lin, SERIES_1, "linear Q-learning"),):  #one agent
        c = np.array(run["learning_curve"])
        x = np.arange(1, len(c) + 1)
        ax.plot(x, c, color=col, lw=0.8, alpha=0.35)  #every episode
        k = 10  #10-episode running mean
        sm = np.convolve(c, np.ones(k) / k, mode="valid")
        ax.plot(x[k - 1:], sm, color=col, lw=2.0)
        ax.text(x[-1] + 2, sm[-1], name, color=col, fontsize=8.5, va="center", zorder=5,
                bbox=dict(facecolor=ax.get_facecolor(), edgecolor="none", pad=1.5))  #direct label at the line end, readable over the other curve
    rnd = lin["random_policy"]["mean"]  #both baselines live in landuse_rl.json
    ax.axhline(rnd, color=MUTED, lw=1.2, ls="--")
    ax.text(ax.get_xlim()[1], rnd, " random policy", color=INK_2, fontsize=8.5, va="center")
    if lin.get("hill_climb"):  #the direct optimiser the agent should beat
        hc = lin["hill_climb"]["best_objective"]
        ax.axhline(hc, color=INK, lw=1.2, ls=":")
        ax.text(ax.get_xlim()[1], hc, " hill climbing", color=INK, fontsize=8.5, va="center")
    ax.set_xlabel("training episode")
    ax.set_ylabel("objective over the design site")
    fig.suptitle("How the RL agent learns", x=0.012, y=0.99, ha="left",
                 fontsize=11, fontweight="bold", color=INK)
    fig.text(0.012, 0.905, f"Objective at the end of each episode, thin; 10-episode mean, thick · "
             f"the site today scores {lin['baseline_objective']:.3f}", fontsize=8.5, color=INK_2, ha="left")
    save(fig, "fig_landuse_rl_training.png")


def fig_rl_site(ca, rl, out="fig_landuse_rl_site.png",
                heading="The RL agent re-plans the design site",
                plan_label="RL agent's plan"):
    #The design site today against the RL agent's plan, and how it learned.
    import matplotlib.patches as mpatches

    classes, cols, cmap = lu_cmap(ca)
    site = np.array(rl["site_mask"], dtype=bool)
    today = np.array(rl["today_grid"], dtype="int16")
    plan = np.array(rl["best_grid"], dtype="int16")

    rows, cols_ = np.where(site)
    m = 3                                  #cells of context around the site
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
        #context outside the site is drawn, but washed out: it is fixed
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

    #what the site is made of, today vs plan
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

    #learning curve: today's objective is far below, so it is stated, not drawn
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


#==================================================================== main
def main():
    need = [PROCESSED / "svf.tif", PROCESSED / "svf_summary.json",
            PROCESSED / "vegetation_summary.json",
            RAW / "rotterdam_trees_rd.geojson", PROCESSED / "trees.geojson",
            RAW / "ahn_dsm_05m.tif", RAW / "ahn_dtm_05m.tif"]
    missing = [p for p in need if not p.exists()]
    if missing:
        print("missing inputs: run fetch_ahn.py, fetch_trees.py and "
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

    #rebuild the open-ground mask on the cropped SVF grid, the way sky_view_factor.py does
    dsm, _, _ = load_tif(RAW / "ahn_dsm_05m.tif")
    dtm, _, _ = load_tif(RAW / "ahn_dtm_05m.tif")
    pad = (dsm.shape[0] - svf.shape[0]) // 2
    ndsm = (dsm - dtm)[pad:pad + svf.shape[0], pad:pad + svf.shape[1]]
    if stats["parameters"].get("trees") is False:  #trees left out: outside the footprints the surface is the ground
        from sky_view_factor import building_mask
        ndsm = np.where(building_mask(svf.shape, transform), ndsm, ndsm * 0)  #nan stays nan where the DTM has no value
    open_ground = np.isfinite(ndsm) & (ndsm < 2.0)

    fig_svf_map(svf, open_ground, stats)
    fig_svf_distribution(svf, open_ground, stats)
    fig_height_classes(trees_rd)
    fig_tree_map(trees_rd, veg)

    dens_path = PROCESSED / "density_summary.json"
    grid_path = PROCESSED / "density_grid.geojson"
    if dens_path.exists() and grid_path.exists():
        dens = json.loads(dens_path.read_text())
        grid_geo = json.loads(grid_path.read_text())
        fig_density_maps(dens, grid_geo)
        site_path = PROCESSED / "density_site.json"  #the scenarios on the design site, density_site.py
        if site_path.exists():
            fig_density_site(json.loads(site_path.read_text()))
    else:
        print("  (skipping density figures: run density_height.py first)")

    lu_path = PROCESSED / "landuse_summary.json"
    lug_path = PROCESSED / "landuse_grid.geojson"
    if lu_path.exists() and lug_path.exists():
        fig_landuse(json.loads(lu_path.read_text()),
                    json.loads(lug_path.read_text()))
    else:
        print("  (skipping land-use figure: run landuse_mix.py first)")

    abm_path = PROCESSED / "landuse_abm.json"
    if abm_path.exists():
        abm = json.loads(abm_path.read_text())
        if abm.get("scenarios"):
            rl_path = PROCESSED / "landuse_rl.json"
            rl = json.loads(rl_path.read_text()) if rl_path.exists() else None
            fig_abm(abm, rl)
            if rl and rl.get("site_mask"):
                fig_rl_site(abm, rl)
            if rl and rl.get("random_policy"):  #the training curve against both baselines
                fig_rl_training(rl)
    else:
        print("  (skipping ABM figure: run ca_landuse.py first)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
