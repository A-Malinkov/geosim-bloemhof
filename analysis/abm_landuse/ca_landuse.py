#!/usr/bin/env python3
"""
ca_landuse.py — constrained cellular automaton for land-use configuration.

Component 4.7. Owner: Atanas Malinkov

WHAT IT DOES
------------
Builds a 25 m raster of the study area from real data, then lets land use evolve
under explicit transition rules towards a stated demand, and scores the
resulting configurations with the same indicators used in component 4.3. Run
several times with different demand and rule settings, it explores which spatial
arrangements score best — which is what "explore optimal land-use
configurations" asks for.

THE MODEL
---------
A constrained CA in the White & Engelen tradition (White, Engelen & Uljee 1997,
*The use of constrained cellular automata for high-resolution modelling of urban
dynamics*). Each cell has one state. Each step, every convertible cell gets a
transition potential for every state:

    P(i,k) = N(i,k) * S(i,k) * A(i,k) * v

    N  neighbourhood effect — the sum over neighbours within RADIUS of an
       influence weight for (candidate class k, neighbour class m), decayed by
       distance. This is where the spatial logic lives: shops want to be near
       streets and homes, industry repels housing, green begets green.
    S  suitability — hard physical limits. Water is never developable.
    A  accessibility — distance decay from the road network. Nothing gets built
       far from a street.
    v  stochastic perturbation, v = 1 + (-ln u)^alpha, u ~ U(0,1]. Without it a
       deterministic CA produces implausibly regular blocks and the same answer
       every run; with it, repeated runs sample a distribution of configurations.

Cells are then allocated to the classes with unmet demand, highest potential
first. Water and roads never convert. Existing uses resist conversion by an
inertia factor, so the model does not bulldoze a working neighbourhood to chase
a marginal gain.

WHAT IT IS NOT
--------------
Not a prediction of what Rotterdam will do. Demand is set by us, not derived
from a regional model, so this explores the CONSEQUENCES of a development
programme rather than forecasting one. Say that plainly in the report.

USAGE
-----
    python analysis/abm_landuse/fetch_landcover.py     # first
    python analysis/abm_landuse/ca_landuse.py
    python analysis/abm_landuse/ca_landuse.py --replicates 20 --steps 30

OUTPUT
------
    data/processed/landuse_abm.json   grids per step, shares, scores, ranking

PROGRAMMES, NOT THE RHINO SCENARIOS
-----------------------------------
The CA explores land-use PROGRAMMES over the whole buurt: "compact" and "green"
against the "baseline" (no programme). Until 2026-10-27 they were keyed
scenario_a and scenario_b, which clashed with the Rhino design options of the
same names. They are unrelated to those. The Rhino options are scored on the
same objective by score_scenarios.py.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import PROCESSED, RAW, STUDY_AREA, bbox_rd  # noqa: E402

# ---------------------------------------------------------------- the states
WATER, ROAD, GREEN, RESID, RETAIL, AMENITY, INDUSTRY, VACANT = range(8)
CLASSES = ["water", "road", "green", "residential", "retail",
           "amenity", "industry", "vacant"]
FIXED = {WATER, ROAD}                    # never convert
ACTIVE = [GREEN, RESID, RETAIL, AMENITY, INDUSTRY]   # classes demand applies to

#: Influence of a NEIGHBOUR of class m (column) on the potential of a cell
#: becoming class k (row). Positive attracts, negative repels. These are the
#: model's assumptions and the report should defend them, not hide them.
INFLUENCE = np.array([
    #  water  road  green  resid retail amenity indus vacant
    [   0.0,  0.0,  0.0,   0.0,  0.0,   0.0,   0.0,  0.0],   # water (fixed)
    [   0.0,  0.0,  0.0,   0.0,  0.0,   0.0,   0.0,  0.0],   # road  (fixed)
    [   0.3,  0.0,  1.0,   0.5,  0.0,   0.2,  -0.8,  0.2],   # green
    [   0.2,  0.5,  0.8,   1.0,  0.5,   0.6,  -1.2,  0.1],   # residential
    [   0.0,  1.2,  0.0,   0.9,  0.8,   0.4,  -0.3,  0.1],   # retail
    [   0.0,  0.8,  0.3,   1.0,  0.4,   0.3,  -0.4,  0.1],   # amenity
    [   0.6,  0.7, -0.6,  -1.2, -0.2,  -0.3,   1.2,  0.2],   # industry
    [   0.0,  0.0,  0.0,   0.0,  0.0,   0.0,   0.0,  0.0],   # vacant
])

RADIUS_CELLS = 4          # neighbourhood radius, in cells
DECAY = 2.0               # distance decay length, in cells
INERTIA = 1.6             # how strongly a cell resists leaving its current use
ALPHA = 0.6               # stochastic perturbation exponent


# ------------------------------------------------------------ initial raster
def rasterise(cell_m: float):
    """Build the starting grid from OSM land cover, OSM roads and BAG units."""
    import geopandas as gpd
    from rasterio.features import rasterize
    from rasterio.transform import from_origin

    xmin, ymin, xmax, ymax = bbox_rd()
    nx = int(round((xmax - xmin) / cell_m))
    ny = int(round((ymax - ymin) / cell_m))
    transform = from_origin(xmin, ymax, cell_m, cell_m)
    grid = np.full((ny, nx), VACANT, dtype="int16")

    lc_path = RAW / "osm_landcover.geojson"
    rd_path = RAW / "osm_roads.geojson"
    if not lc_path.exists():
        print(f"missing {lc_path}\nRun: python analysis/abm_landuse/fetch_landcover.py")
        sys.exit(1)

    lc = gpd.read_file(lc_path).to_crs("EPSG:28992")
    for cover, state in (("green", GREEN), ("water", WATER)):
        sub = lc[lc["cover"] == cover]
        if sub.empty:
            continue
        burn = rasterize([(g, 1) for g in sub.geometry if g and not g.is_empty],
                         out_shape=(ny, nx), transform=transform,
                         fill=0, all_touched=False, dtype="uint8")
        grid[burn == 1] = state

    road_frac = np.zeros((ny, nx), dtype="float32")
    if rd_path.exists():
        roads = gpd.read_file(rd_path).to_crs("EPSG:28992")
        # Buffering every centreline by half a cell put 41% of the study area
        # under tarmac — 44 km of road at 22.5 m width is 99 ha, more than the
        # square itself. Use realistic carriageway widths per OSM class instead,
        # and measure the AREA FRACTION of each cell on a 5 m sub-grid rather
        # than an all-or-nothing burn.
        widths = {"primary": 14.0, "secondary": 11.0, "secondary_link": 11.0,
                  "tertiary": 10.0, "residential": 8.0, "unclassified": 7.0,
                  "living_street": 6.0, "service": 5.0}

        def width_of(v):
            t = str(v).strip("[]'\" ").split("'")[0].split(",")[0].strip()
            return widths.get(t, 8.0)

        sub = 5.0                                  # sub-grid cell size, metres
        f = int(round(cell_m / sub))
        sub_t = from_origin(xmin, ymax, sub, sub)
        geoms = [(g.buffer(width_of(h) / 2.0), 1)
                 for g, h in zip(roads.geometry, roads.get("highway", [None] * len(roads)))
                 if g is not None and not g.is_empty]
        fine = rasterize(geoms, out_shape=(ny * f, nx * f), transform=sub_t,
                         fill=0, all_touched=False, dtype="uint8")
        road_frac = fine.reshape(ny, f, nx, f).mean(axis=(1, 3)).astype("float32")

    # BAG units win over land cover: a building standing on mapped grass is a
    # building. Each cell takes the class holding the most floor area in it.
    units = json.loads((RAW / "bag_verblijfsobjecten.geojson").read_text())["features"]
    bag_to_state = {
        "residential": RESID, "retail": RETAIL, "office": RETAIL,
        "education": AMENITY, "healthcare": AMENITY, "sport": AMENITY,
        "assembly": AMENITY, "accommodation": AMENITY,
        "industry": INDUSTRY, "detention": AMENITY, "other": VACANT,
    }
    area = np.zeros((ny, nx, len(CLASSES)), dtype="float32")
    for f in units:
        x, y = f["geometry"]["coordinates"]
        c = int((x - xmin) // cell_m)
        r = int((ymax - y) // cell_m)
        if not (0 <= r < ny and 0 <= c < nx):
            continue
        p = f["properties"]
        for cat in p["categories"]:
            st = bag_to_state.get(cat, VACANT)
            area[r, c, st] += p["area_per_category_m2"]
    built = area.sum(axis=2) > 0

    # Explicit priority, because the previous order let BAG overwrite 67% of the
    # road network: a cell with a building is a building cell, an unbuilt cell
    # that is mostly carriageway is road, then land cover, then vacant.
    #   1 water      physical, never developable
    #   2 building   BAG says something stands here
    #   3 road       >= half the cell is carriageway and nothing is built on it
    #   4 green/vacant  already in `grid` from land cover
    grid[(road_frac >= 0.5) & ~built] = ROAD
    grid[built] = area[built].argmax(axis=1).astype("int16")

    water_mask = np.zeros((ny, nx), dtype=bool)
    wsub = lc[lc["cover"] == "water"]
    if not wsub.empty:
        water_mask = rasterize([(g, 1) for g in wsub.geometry if g and not g.is_empty],
                               out_shape=(ny, nx), transform=transform,
                               fill=0, dtype="uint8") == 1
    grid[water_mask] = WATER
    return grid, transform, (nx, ny), road_frac


# -------------------------------------------------------------- CA machinery
def neighbourhood_stack(grid):
    """
    For each class, the distance-decayed count of neighbours of that class.

    Done with one convolution per class rather than a per-cell loop; on a
    48x48 grid the difference is seconds versus minutes over many replicates.
    """
    from scipy.signal import fftconvolve

    r = RADIUS_CELLS
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    d = np.hypot(yy, xx)
    kern = np.exp(-d / DECAY)  #influence falls off with distance
    kern[r, r] = 0.0                      # a cell does not influence itself
    kern[d > r] = 0.0

    out = np.zeros((len(CLASSES), *grid.shape), dtype="float32")
    for k in range(len(CLASSES)):
        out[k] = fftconvolve((grid == k).astype("float32"), kern, mode="same")
    return out


def accessibility(grid, road_frac=None, threshold=0.2):
    """
    Distance decay from the road SURFACE — nothing is built far from a street.

    Measured from the continuous carriageway fraction, not from cells whose
    final state happens to be ROAD. At 25 m most street cells also contain a
    building and are therefore labelled residential, so using the discrete state
    would leave the accessibility field full of holes and misstate every
    transition potential nearby. A cell counts as served if at least
    `threshold` of it is carriageway.
    """
    from scipy.ndimage import distance_transform_edt

    served = (road_frac >= threshold) if road_frac is not None else (grid == ROAD)
    if not served.any():
        return np.ones(grid.shape, dtype="float32")
    d = distance_transform_edt(~served).astype("float32")
    return np.exp(-d / 6.0)               # ~150 m e-folding at 25 m cells


def step(grid, demand, rng, suitability, road_frac=None):
    """One CA iteration: score every convertible cell, then allocate by demand."""
    nb = neighbourhood_stack(grid)
    acc = accessibility(grid, road_frac)
    convertible = ~np.isin(grid, list(FIXED))  #water and road never change

    pot = np.zeros((len(CLASSES), *grid.shape), dtype="float32")
    #transition potential P = N * S * A * v for every class and cell
    for k in ACTIVE:
        n = np.tensordot(INFLUENCE[k], nb, axes=(0, 0))      # neighbourhood effect
        v = 1.0 + (-np.log(rng.uniform(1e-9, 1.0, grid.shape))) ** ALPHA  #stochastic term v, so replicates differ
        p = (1.0 + np.maximum(n, 0.0)) * suitability[k] * acc * v  #negative neighbourhood effects floor at 0
        p[grid == k] *= INERTIA                              # incumbency
        pot[k] = p
    pot[:, ~convertible] = -np.inf  #fixed cells can never be chosen

    new = grid.copy()
    counts = {k: int((grid == k).sum()) for k in ACTIVE}
    # classes that want to grow, largest shortfall first
    wants = sorted(((k, demand.get(k, counts[k]) - counts[k]) for k in ACTIVE),
                   key=lambda t: -t[1])
    taken = np.zeros(grid.shape, dtype=bool)
    for k, deficit in wants:
        if deficit <= 0:
            continue
        cand = pot[k].copy()
        cand[grid == k] = -np.inf         # already this class
        cand[taken] = -np.inf             # one conversion per cell per step
        # never convert a cell whose own class is already short of its demand
        for other, od in wants:
            if other != k and od > 0:
                cand[grid == other] = -np.inf
        flat = cand.ravel()
        n_take = int(min(deficit, np.isfinite(flat).sum()))
        if n_take <= 0:
            continue
        idx = np.argpartition(flat, -n_take)[-n_take:]  #the n_take highest-potential cells convert
        idx = idx[np.isfinite(flat[idx])]
        rr, cc = np.unravel_index(idx, grid.shape)
        new[rr, cc] = k
        taken[rr, cc] = True
    return new


# ----------------------------------------------------------------- scoring
def shares(grid):
    tot = grid.size
    return {CLASSES[k]: round(float((grid == k).sum()) / tot, 4)
            for k in range(len(CLASSES))}


def shannon_mix(grid):
    """Normalised Shannon entropy over the five active classes."""
    counts = np.array([float((grid == k).sum()) for k in ACTIVE])
    tot = counts.sum()
    if tot <= 0:
        return 0.0
    p = counts[counts > 0] / tot  #share of each active class present
    return float(-(p * np.log(p)).sum() / math.log(len(ACTIVE)))


def amenity_access(grid, cell_m):
    """Mean distance from a home to the nearest amenity or shop, in metres."""
    from scipy.ndimage import distance_transform_edt
    target = np.isin(grid, [AMENITY, RETAIL])
    if not target.any() or not (grid == RESID).any():
        return None
    d = distance_transform_edt(~target) * cell_m
    return round(float(d[grid == RESID].mean()), 1)


def score(grid, cell_m):
    return {
        "landuse_mix": round(shannon_mix(grid), 4),
        "green_share": round(float((grid == GREEN).sum()) / grid.size, 4),
        "residential_cells": int((grid == RESID).sum()),
        "mean_distance_to_amenity_m": amenity_access(grid, cell_m),
    }


# ---------------------------------------------------------- map export
#: One colour per state, for the map overlays and the figures.
COLOURS = {
    "water":       (110, 160, 200),
    "road":        (150, 150, 150),
    "green":       ( 90, 165,  95),
    "residential": (232, 168, 120),
    "retail":      (235, 104,  52),
    "amenity":     ( 74,  58, 167),
    "industry":    (120, 110, 100),
    "vacant":      (228, 226, 218),
}


def export_grid_png(grid, transform, crs, path):
    """
    Write a grid as a georeferenced PNG warped to EPSG:4326.

    Warped, not simply reprojected corner-to-corner: RD New is rotated against
    WGS84, so a lon/lat rectangle built from two corners of the RD square
    misplaces the image by ~30 m. Returns the bbox the PNG really covers.
    """
    from PIL import Image
    from rasterio.warp import calculate_default_transform, reproject, Resampling

    h, w = grid.shape
    left, top = transform * (0, 0)
    right, bottom = transform * (w, h)
    dst_t, dw, dh = calculate_default_transform(
        crs, "EPSG:4326", w, h, left=left, bottom=bottom, right=right, top=top)
    dst = np.full((dh, dw), 255, dtype="uint8")
    reproject(source=grid.astype("uint8"), destination=dst,
              src_transform=transform, src_crs=crs,
              dst_transform=dst_t, dst_crs="EPSG:4326",
              src_nodata=255, dst_nodata=255,
              resampling=Resampling.nearest)      # nearest: classes, not values

    rgba = np.zeros((dh, dw, 4), dtype="uint8")
    for k, name in enumerate(CLASSES):
        m = dst == k
        rgba[m, :3] = COLOURS[name]
        rgba[m, 3] = 0 if name == "water" else 205   # let the river show through
    Image.fromarray(rgba, "RGBA").resize((dw * 6, dh * 6), Image.NEAREST) \
         .save(path, optimize=True)
    west, north = dst_t * (0, 0)
    east, south = dst_t * (dw, dh)
    return [round(west, 7), round(south, 7), round(east, 7), round(north, 7)]


# ------------------------------------------------------------- validation
def validate_regrow(grid0, suitability, cell_m, steps, frac, seed,
                    road_frac=None, rng_reps=5):
    """
    Can the CA put back what we take away?

    A CA run with demand equal to the current counts converts nothing — there is
    no deficit — so "the baseline does not change" validates nothing. The real
    test: erase a random `frac` of the developed cells, set demand back to the
    original counts, and see how much of the original map the model reproduces.

    Reported as overall agreement and as Cohen's kappa, which discounts the
    agreement you would get by chance from guessing the commonest class. Kappa
    is the standard measure for this in the CA land-use literature.
    """
    agrees, kappas = [], []
    for rep in range(rng_reps):
        rng = np.random.default_rng(seed + 1000 + rep)
        g = grid0.copy()
        dev = np.isin(g, ACTIVE)
        idx = np.flatnonzero(dev.ravel())
        erase = rng.choice(idx, size=int(len(idx) * frac), replace=False)
        g.ravel()[erase] = VACANT  #wipe a random share of the developed cells

        demand = {k: int((grid0 == k).sum()) for k in ACTIVE}  #ask for exactly what was there before
        for _ in range(steps):
            g = step(g, demand, rng, suitability, road_frac)  #same road-surface access as the scenario runs; it was left out, so validation used the old discrete-road access

        cmp_mask = np.isin(grid0, ACTIVE) | np.isin(g, ACTIVE)  #compare only cells developed before or after
        a, b = grid0[cmp_mask], g[cmp_mask]
        agree = float((a == b).mean())

        # Cohen's kappa
        labels = sorted(set(a.tolist()) | set(b.tolist()))
        n = len(a)
        pe = sum(((a == l).sum() / n) * ((b == l).sum() / n) for l in labels)  #agreement expected by chance
        kappa = (agree - pe) / (1 - pe) if pe < 1 else 0.0
        agrees.append(agree)
        kappas.append(kappa)
    return {"erased_fraction": frac,
            "agreement_mean": round(float(np.mean(agrees)), 4),
            "agreement_sd": round(float(np.std(agrees)), 4),
            "kappa_mean": round(float(np.mean(kappas)), 4),
            "kappa_sd": round(float(np.std(kappas)), 4),
            "n_runs": rng_reps}


# -------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cell", type=float, default=25.0)
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--replicates", type=int, default=12,
                    help="stochastic runs per scenario; the spread is the point")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    print(f"Cellular automaton land use — {STUDY_AREA.name}")
    grid0, transform, (nx, ny), road_frac = rasterise(args.cell)
    print(f"  grid {nx} x {ny} of {args.cell:.0f} m = {nx*ny:,} cells")
    served = (road_frac >= 0.2)
    print(f"  street-served cells: {served.sum():,} "
          f"({100*served.mean():.0f}%) — carriageway covers "
          f"{100*road_frac.mean():.0f}% of the area")
    s0 = shares(grid0)
    print("  initial state:")
    for k, v in sorted(s0.items(), key=lambda t: -t[1]):
        if v > 0:
            print(f"     {k:12} {100*v:5.1f}%  ({int(v*grid0.size):,} cells)")

    # suitability: water is never developable, everything else is allowed
    developable = (grid0 != WATER).astype("float32")
    suitability = {k: developable.copy() for k in ACTIVE}
    # keep industry off the residential core: only near existing industry/water
    from scipy.ndimage import binary_dilation
    ind_ok = binary_dilation(np.isin(grid0, [INDUSTRY, WATER]),
                             iterations=int(200 / args.cell))
    suitability[INDUSTRY] *= ind_ok.astype("float32")

    base = {k: int((grid0 == k).sum()) for k in ACTIVE}
    n_new = int(0.06 * grid0.size)            # the development programme
    print(f"\n  development programme: {n_new} cells "
          f"({n_new * args.cell**2 / 10_000:.1f} ha)")

    #land-use programmes, keyed by their own names so they never read as the Rhino scenario_a/scenario_b
    scenarios = {
        "baseline": dict(base),
        "compact": {**base, RESID: base[RESID] + n_new,
                    RETAIL: base[RETAIL] + n_new // 4,
                    AMENITY: base[AMENITY] + n_new // 6},  #was scenario_a until 2026-10-27
        "green": {**base, RESID: base[RESID] + int(n_new * 0.7),
                  GREEN: base[GREEN] + int(n_new * 0.5),
                  AMENITY: base[AMENITY] + n_new // 6},  #was scenario_b until 2026-10-27
    }
    labels = {
        "baseline": "reference: no development programme. Demand equals the "
                    "current counts so nothing converts — this is the comparison "
                    "state, NOT a validation of the model.",
        "compact": "compact: maximum housing plus mixed ground floors",
        "green": "green: less housing, more park and amenity",
    }

    out = {
        "method": "cellular_automata",
        "colours": COLOURS,
        "model": "constrained CA after White, Engelen & Uljee (1997)",
        "cell_size_m": args.cell,
        "bbox_rd": [round(v, 1) for v in bbox_rd()],
        "grid": {"nx": nx, "ny": ny, "origin_rd": [bbox_rd()[0], bbox_rd()[1]]},
        "classes": CLASSES,
        "fixed_classes": ["water", "road"],
        "parameters": {
            "steps": args.steps, "replicates": args.replicates,
            "neighbourhood_radius_cells": RADIUS_CELLS,
            "distance_decay_cells": DECAY, "inertia": INERTIA,
            "stochastic_alpha": ALPHA,
            "influence_matrix": INFLUENCE.tolist(),
            "influence_rows_are": "candidate class", 
            "influence_cols_are": "neighbour class",
        },
        "caveat": "Demand is set by us, not derived from a regional model. This "
                  "explores the consequences of a development programme, it does "
                  "not forecast one.",
        "_programmes_note": "The entries under 'scenarios' are land-use programmes "
                            "(baseline, compact, green) over the whole buurt. They are "
                            "NOT the Rhino design options scenario_a and scenario_b; those "
                            "are scored on the same objective in landuse_scenarios.json.",
        "initial": {"shares": s0, "score": score(grid0, args.cell)},
        "scenarios": {},
    }

    for name, demand in scenarios.items():
        print(f"\n  === {name} — {labels[name]} ===")
        best, best_obj, runs = None, -1e9, []
        for rep in range(args.replicates):
            rng = np.random.default_rng(args.seed + rep)
            g = grid0.copy()
            traj = [{"t": 0, "shares": s0}]
            keep_grids = [g.copy()]
            for t in range(1, args.steps + 1):
                g = step(g, demand, rng, suitability, road_frac)
                traj.append({"t": t, "shares": shares(g)})
                keep_grids.append(g.copy())
            sc = score(g, args.cell)
            # the objective the search is optimising: a mixed, green, walkable
            # outcome, with distance to amenity normalised to roughly 0..1
            d = sc["mean_distance_to_amenity_m"] or 400.0
            obj = (1.6 * sc["landuse_mix"] + 1.0 * sc["green_share"]
                   + 0.8 * max(0.0, 1 - d / 400.0))
            runs.append({"replicate": rep, "objective": round(obj, 4), **sc})
            if obj > best_obj:
                best_obj, best = obj, (g, traj, keep_grids)

        g, traj, keep_grids = best
        objs = np.array([r["objective"] for r in runs])
        mixes = np.array([r["landuse_mix"] for r in runs])
        print(f"     objective over {args.replicates} runs: "
              f"mean {objs.mean():.3f}  best {objs.max():.3f}  sd {objs.std():.3f}")
        print(f"     land-use mix: {mixes.mean():.3f} +/- {mixes.std():.3f}")
        sc = score(g, args.cell)
        print(f"     best run -> mix {sc['landuse_mix']:.3f}, "
              f"green {100*sc['green_share']:.1f}%, "
              f"amenity {sc['mean_distance_to_amenity_m']} m")

        # keep a handful of frames for the app slider, not all of them
        idx = sorted({0, *[round(i * args.steps / 5) for i in range(1, 6)]})
        frames = []
        for i in idx:
            fn = f"landuse_{name}_t{i:02d}.png"
            bbox = export_grid_png(keep_grids[i], transform, "EPSG:28992",
                                   PROCESSED / fn)
            frames.append({"t": int(i), "png": fn, "bbox_wgs84": bbox})
        out["scenarios"][name] = {
            "frames": frames,
            "label": labels[name],
            "demand_cells": {CLASSES[k]: v for k, v in demand.items()},
            "replicates": runs,
            "objective_mean": round(float(objs.mean()), 4),
            "objective_best": round(float(objs.max()), 4),
            "objective_sd": round(float(objs.std()), 4),
            "score": sc,
            "shares_final": shares(g),
            "trajectory": traj,
            "steps": [{"t": int(i), "grid": keep_grids[i].tolist()} for i in idx],
        }

    print("\n  === validation: erase and regrow ===")
    out["validation"] = {}
    for frac in (0.1, 0.25, 0.5):
        v = validate_regrow(grid0, suitability, args.cell, args.steps,
                            frac, args.seed, road_frac)
        out["validation"][f"erase_{int(frac*100)}pct"] = v
        print(f"     erased {int(frac*100):2d}% of developed cells -> "
              f"agreement {100*v['agreement_mean']:.1f}%  "
              f"kappa {v['kappa_mean']:.3f} +/- {v['kappa_sd']:.3f}")
    out["validation"]["_note"] = (
        "Erase a random share of developed cells, restore the original demand, "
        "and measure how much of the original map the CA reproduces. Kappa "
        "discounts chance agreement from guessing the commonest class.")

    ranking = sorted(out["scenarios"].items(),
                     key=lambda kv: -kv[1]["objective_best"])
    out["ranking"] = [{"scenario": k, "objective_best": v["objective_best"],
                       "landuse_mix": v["score"]["landuse_mix"]}
                      for k, v in ranking]
    out["preferred"] = ranking[0][0]

    (PROCESSED / "landuse_abm.json").write_text(json.dumps(out) + "\n")
    print("\n  wrote data/processed/landuse_abm.json")
    print(f"  preferred configuration: {out['preferred']}")
    for r in out["ranking"]:
        print(f"     {r['scenario']:12} objective {r['objective_best']:.3f}  "
              f"mix {r['landuse_mix']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
