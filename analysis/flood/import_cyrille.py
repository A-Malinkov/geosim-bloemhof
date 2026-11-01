#!/usr/bin/env python3
"""
import_cyrille.py - bring Cyrille's QGIS flood-vulnerability rasters into the app.

Analysis: Cyrille Kummer (QGIS, Oct 2026, team OneDrive: SHARED AREA / QGIS /
QGIS Files - UPDATED / BZO_NEW_*.tif). This script does not recompute it: it
clips, warps and colours it for the web app, and summarises it per buurt.

USAGE
-----
    python analysis/flood/import_cyrille.py [RASTER_DIR]

RASTER_DIR defaults to cache/flood/raw/ (gitignored). It must hold the
BZO_NEW_*.tif files listed in LAYERS below: extract them from the shared
folder's QGIS.zip. They are 76 MB each and are NOT committed.

WHAT THE LAYERS ARE (checked on every cell, see README)
-----------------------
Each factor is scored 1 (low) .. 4 (high), per "QGIS Layer Coding.pdf":
  water proximity   0–50 / 50–100 / 100–250 / 250+ m to water      -> 4..1
  elevation (m NAP) < −0.99 / −0.99..−0.67 / −0.67..1.46 / > 1.46   -> 4..1
  building density  > 10 / 5–10 / 1–5 / ≤ 1 buildings per cell      -> 4..1
  hazard            water + elevation, 2–8, banded                   -> 1..4
  combined score    density + water + elevation, 3–12
  overall           combined banded: ≤ 5.25 / –7.5 / –9.75 / > 9.75  -> 1..4

Elevation comes from the AHN DTM, which is empty under buildings, so every
layer that uses it (hazard, combined, overall) covers open ground only.

OUTPUT
------
  data/processed/flood_<id>.png      coloured overlay, warped to EPSG:4326
  data/processed/flood_summary.json  layers, legends, bounds, shares per area
  docs/fig_flood_overall.png, docs/fig_flood_factors.png   report figures
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common.project import (PROCESSED, ROOT, STUDY_AREA,  # noqa: E402
                            buurt_polygons, design_site_polygon, write_processed)

RAW = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "cache" / "flood" / "raw"
MAX_PX = 2000          # long side of the overlay PNG (~1.35 m per pixel)

# Colours are Cyrille's, from the QGIS project (QGIS_Final.Project.Updated.2.qgz).
RISK4 = ["#1a9641", "#c4e687", "#fec981", "#d7191c"]
LAYERS = [
    {"id": "overall", "file": "CityRisk", "label": "Overall flood vulnerability",
     "kind": "classes", "values": [1, 2, 3, 4],
     "colours": ["#5d82aa", "#62bb7d", "#fb9f50", "#7a0403"],
     "labels": ["1 low", "2", "3", "4 high"],
     "about": "combined score banded into four classes"},
    {"id": "combined", "file": "BuildingDensity,WaterProximity,Elevation",
     "label": "Combined risk score", "kind": "ramp",
     "stops": [(0, "#65bec9"), (2, "#c8f181"), (4, "#b0ce66"), (5, "#f0e072"),
               (6, "#efa569"), (8, "#ad5043"), (10, "#58313a")],
     "about": "building density + water proximity + elevation, each 1–4"},
    {"id": "hazard", "file": "HazardMap", "label": "Water hazard (proximity + elevation)",
     "kind": "classes", "values": [1, 2, 3, 4], "colours": RISK4,
     "labels": ["1 low", "2", "3", "4 high"],
     "about": "water proximity + elevation, banded"},
    {"id": "water", "file": "WaterProximityRisk", "label": "Distance to water",
     "kind": "classes", "values": [1, 2, 3, 4],
     "colours": ["#f7fbff", "#deebf7", "#4292c6", "#08306b"],
     "labels": ["250 m +", "100–250 m", "50–100 m", "0–50 m"],
     "about": "scored 1–4"},
    {"id": "elevation", "file": "ElevationRisk", "label": "Low ground",
     "kind": "classes", "values": [1, 2, 3, 4], "colours": RISK4,
     "labels": ["> 1.46 m", "−0.67…1.46 m", "−0.99…−0.67 m", "< −0.99 m NAP"],
     "about": "AHN ground level, scored 1–4"},
    {"id": "density", "file": "BuildingDensity4Raster", "label": "Building density",
     "kind": "bins", "edges": [1, 5, 10],
     "colours": ["#fdf2d3", "#fba18b", "#922c79", "#000004"],
     "labels": ["≤ 1", "1–5", "5–10", "> 10 buildings"],
     "about": "buildings per grid cell"},
    {"id": "roads", "file": "RoadsWaterProximityRisk", "label": "Roads near water",
     "kind": "classes", "values": [1, 2, 3, 4],
     "colours": ["#faebdd", "#f16144", "#851e5a", "#03051a"],
     "labels": ["250 m +", "100–250 m", "50–100 m", "0–50 m"],
     "about": "road distance to water, scored 1–4"},
]


def hex_rgb(h):
    return [int(h[i:i + 2], 16) for i in (1, 3, 5)]


def read(name):
    import rasterio
    with rasterio.open(RAW / f"BZO_NEW_{name}.tif") as r:
        a = r.read(1).astype("float32")
        a[(a <= -9999) | (a < -1e30)] = np.nan
        return a, r.transform, r.crs


def warp(a, transform, crs):
    """Warp to EPSG:4326 with NEAREST resampling: these are class rasters,
    and bilinear would invent class 2.5 along every edge. Warping first (not
    draping the RD box) avoids the ~30 m RD rotation error (CLAUDE.md)."""
    from rasterio.warp import calculate_default_transform, reproject, Resampling
    h, w = a.shape
    left, top = transform * (0, 0)
    right, bottom = transform * (w, h)
    scale = MAX_PX / max(w, h)
    dt, dw, dh = calculate_default_transform(crs, "EPSG:4326", w, h, left=left,
                                             bottom=bottom, right=right, top=top,
                                             dst_width=int(w * scale), dst_height=int(h * scale))
    dst = np.full((dh, dw), np.nan, dtype="float32")
    reproject(a, dst, src_transform=transform, src_crs=crs, dst_transform=dt,
              dst_crs="EPSG:4326", src_nodata=np.nan, dst_nodata=np.nan,
              resampling=Resampling.nearest)
    west, north = dt * (0, 0)
    east, south = dt * (dw, dh)
    return dst, (west, south, east, north)


def colourise(a, L):
    rgba = np.zeros(a.shape + (4,), dtype="uint8")
    ok = np.isfinite(a)
    if L["kind"] == "classes":
        for v, c in zip(L["values"], L["colours"]):
            m = ok & (np.rint(a) == v)
            rgba[m, :3] = hex_rgb(c); rgba[m, 3] = 255
    elif L["kind"] == "bins":
        idx = np.digitize(a, L["edges"], right=True)
        for i, c in enumerate(L["colours"]):
            m = ok & (idx == i)
            rgba[m, :3] = hex_rgb(c); rgba[m, 3] = 255
    else:  # ramp: linear between Cyrille's stops
        xs = [s for s, _ in L["stops"]]
        cs = np.array([hex_rgb(c) for _, c in L["stops"]], float)
        for k in range(3):
            rgba[..., k] = np.interp(np.nan_to_num(a), xs, cs[:, k]).astype("uint8")
        rgba[ok, 3] = 255
    return rgba


def shares(a, L, mask):
    """Area shares inside one polygon, over cells where the layer has data."""
    v = a[mask & np.isfinite(a)]
    if v.size == 0:
        return None
    out = {"covered_share": round(float(v.size / mask.sum()), 3)}
    if L["kind"] == "classes":
        out["shares"] = {lab: round(float(np.mean(np.rint(v) == val)), 3)
                         for val, lab in zip(L["values"], L["labels"])}
    elif L["kind"] == "bins":
        idx = np.digitize(v, L["edges"], right=True)
        out["shares"] = {lab: round(float(np.mean(idx == i)), 3) for i, lab in enumerate(L["labels"])}
    else:
        out.update({"mean": round(float(v.mean()), 2), "median": float(np.median(v))})
    return out


def main() -> int:
    import rasterio.features
    from PIL import Image

    missing = [L["file"] for L in LAYERS if not (RAW / f"BZO_NEW_{L['file']}.tif").exists()]
    if missing:
        sys.exit(f"Missing rasters in {RAW}: {missing}. Extract them from the shared "
                 "folder's QGIS.zip (QGIS/QGIS Files - UPDATED/).")

    by_code = buurt_polygons()
    areas = {name: by_code[code] for code, name in STUDY_AREA.buurten}
    areas["Design site"] = design_site_polygon()

    summary = {
        "source": "Cyrille Kummer, QGIS flood-vulnerability analysis (team OneDrive, "
                  "QGIS Files - UPDATED, 2026-10-02); imported, not recomputed",
        "scenario": "baseline",
        "cell_size_m": 0.5,
        "note": "Elevation is the AHN DTM, empty under buildings: hazard, combined and "
                "overall cover open ground only. Shares are of cells with data.",
        "layers": [],
    }
    masks = None
    for L in LAYERS:
        a, tr, crs = read(L["file"])
        if masks is None:
            masks = {n: rasterio.features.geometry_mask([p], a.shape, tr, invert=True)
                     for n, p in areas.items()}
        w, bbox = warp(a, tr, crs)
        Image.fromarray(colourise(w, L), "RGBA").save(PROCESSED / f"flood_{L['id']}.png", optimize=True)
        legend = ([{"label": lab, "colour": c} for lab, c in zip(L["labels"], L["colours"])]
                  if L["kind"] != "ramp" else
                  [{"label": str(s), "colour": c} for s, c in L["stops"]])
        entry = {"id": L["id"], "label": L["label"], "about": L["about"], "kind": L["kind"],
                 "png": f"flood_{L['id']}.png", "bbox_wgs84": [round(b, 7) for b in bbox],
                 "legend": legend, "source_file": f"BZO_NEW_{L['file']}.tif",
                 "stats": {n: shares(a, L, m) for n, m in masks.items()}}
        summary["layers"].append(entry)
        site = entry["stats"]["Design site"]
        print(f"  {L['id']:9s} {w.shape[1]}x{w.shape[0]} px   design site: "
              f"{site.get('shares') or {'mean': site.get('mean')}}")

    write_processed("flood_summary.json", summary)

    global summary_overall
    ov = next(l for l in summary["layers"] if l["id"] == "overall")["stats"]
    summary_overall = {n: (v["shares"]["3"] + v["shares"]["4 high"]) for n, v in ov.items()}
    figures(areas)
    return 0


def figures(areas) -> None:
    """Report figures: overall map, and the three factors side by side."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import geopandas as gpd
    from matplotlib.colors import ListedColormap, BoundaryNorm
    from matplotlib.patches import Patch

    DOCS = ROOT / "docs"
    lay = {L["id"]: L for L in LAYERS}

    def panel(ax, lid, step=4):
        L = lay[lid]
        a, tr, _ = read(L["file"])
        a = a[::step, ::step]
        x0, y1 = tr * (0, 0)
        x1, y0 = tr * (a.shape[1] * step, a.shape[0] * step)
        if L["kind"] == "classes":
            cmap, bounds = ListedColormap(L["colours"]), [v - 0.5 for v in L["values"]] + [L["values"][-1] + 0.5]
        else:  # bins
            cmap, bounds = ListedColormap(L["colours"]), [-1e9] + L["edges"] + [1e9]
        ax.imshow(np.ma.masked_invalid(a), cmap=cmap, norm=BoundaryNorm(bounds, cmap.N),
                  extent=(x0, x1, y0, y1), interpolation="nearest")
        gpd.GeoSeries([areas[n] for n in areas if n != "Design site"], crs=28992).boundary.plot(
            ax=ax, color="#333", linewidth=0.8)
        gpd.GeoSeries([areas["Design site"]], crs=28992).boundary.plot(ax=ax, color="#00b4d8", linewidth=1.8)
        ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_axis_off()
        return [Patch(color=c, label=l) for c, l in zip(L["colours"], L["labels"])]

    fig, ax = plt.subplots(figsize=(10, 7))
    handles = panel(ax, "overall", step=2)
    ax.legend(handles=handles[::-1] + [Patch(facecolor="none", edgecolor="#00b4d8", label="design site")],
              title="vulnerability", loc="upper left", bbox_to_anchor=(1.01, 1), frameon=False)
    s = summary_overall
    ax.set_title("Overall flood vulnerability (Cyrille, QGIS): open ground, 0.5 m\n"
                 f"classes 3–4: design site {s['Design site']:.0%}, " +
                 ", ".join(f"{n} {s[n]:.0%}" for _, n in STUDY_AREA.buurten))  #every study-area buurt, however many
    plt.tight_layout(); fig.savefig(DOCS / "fig_flood_overall.png", dpi=140); plt.close(fig)

    fig, axs = plt.subplots(1, 3, figsize=(15, 4.6))
    for ax, lid, title in zip(axs, ["water", "elevation", "density"],
                              ["distance to water", "ground level (m NAP)", "buildings per cell"]):
        h = panel(ax, lid)
        ax.set_title(title)
        ax.legend(handles=h[::-1], loc="lower left", fontsize=7, frameon=True, framealpha=0.85)
    fig.suptitle("The three factors behind it, each scored 1–4 (dark = higher risk)")
    plt.tight_layout(); fig.savefig(DOCS / "fig_flood_factors.png", dpi=130); plt.close(fig)
    print("[flood] wrote docs/fig_flood_overall.png, docs/fig_flood_factors.png")


if __name__ == "__main__":
    sys.exit(main())
