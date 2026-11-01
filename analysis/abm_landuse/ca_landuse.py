#!/usr/bin/env python3
"""
ca_landuse.py - a simple constrained cellular automaton for land-use configuration.

Component 4.7. Owner: Atanas Malinkov

WHAT IT DOES
------------
Builds a 25 m raster of the study area from real data, then lets land use evolve
under explicit transition rules towards a stated demand, and scores the
resulting configurations with the same indicators used in component 4.3. Run
several times with different demand and rule settings, it explores which spatial
arrangements score best, which is what "explore optimal land-use
configurations" asks for.

THE MODEL
---------
A neighbour-rule CA, constrained by demand. Each cell has one state. Only
VACANT cells change: nothing that stands is demolished. Each step, a vacant
cell can take a use that one of its 8 neighbours supports (RULES):

    green        next to green
    residential  next to residential
    retail       next to residential, and the cell is on a street
    amenity      next to residential
    industry     does not grow

A cell's score for a use is the number of its 8 neighbours that support it.
The classes the programme asks for (demand) take the highest-scoring vacant
cells first, at most their growth spread evenly over the steps, so a run grows
outwards from what exists. A random tie-break orders cells with the same score,
so repeated runs give different maps. Water and roads never convert.

Until 2026-10-30 this was a constrained CA after White, Engelen & Uljee (1997):
a 64-weight influence matrix over a radius of 4 cells, times suitability, road
access, a stochastic term and inertia. It ranked the programmes the same way
but was hard to explain and every weight was an assumption to defend.

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
from common.project import PROCESSED, RAW, STUDY_AREA, bbox_rd, design_site_polygon  # noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from weight_sensitivity import DEFAULT_W, components  # noqa: E402  #the objective, defined once

# ---------------------------------------------------------------- the states
WATER, ROAD, GREEN, RESID, RETAIL, AMENITY, INDUSTRY, VACANT = range(8)
CLASSES = ["water", "road", "green", "residential", "retail",
           "amenity", "industry", "vacant"]
FIXED = {WATER, ROAD}                    # never convert
ACTIVE = [GREEN, RESID, RETAIL, AMENITY, INDUSTRY]   # classes demand applies to

#the model's rules: which neighbours support each use, and whether it needs a street; industry has none, so it never grows
RULES = {
    GREEN:   {"next_to": [GREEN], "street": False},  #parks grow out of parks
    RESID:   {"next_to": [RESID], "street": False},  #housing grows out of housing
    RETAIL:  {"next_to": [RESID], "street": True},   #a shop needs customers next door and a street
    AMENITY: {"next_to": [RESID], "street": False},  #a school or health practice serves the homes around it
}
STREET_FRAC = 0.2  #a cell is on a street if at least this share of it is carriageway

#the programmes: cells of each use on the cleared design site (188 buildable cells); today has 160 housing, 8 shop or amenity, 6 green
PROGRAMMES = {
    "compact": {RESID: 160, RETAIL: 14, AMENITY: 7, GREEN: 7},  #today's housing kept, more shops (Atanas, 2026-10-30)
    "green": {RESID: 120, RETAIL: 10, AMENITY: 8, GREEN: 50},  #a quarter less housing for a park
}


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
        # under tarmac: 44 km of road at 22.5 m width is 99 ha, more than the
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
def neighbour_counts(grid):
    #for each class, how many of a cell's 8 neighbours have it (Moore neighbourhood)
    from scipy.ndimage import convolve
    kern = np.ones((3, 3), dtype="int16")
    kern[1, 1] = 0  #a cell is not its own neighbour
    return np.stack([convolve((grid == k).astype("int16"), kern, mode="constant") for k in range(len(CLASSES))])


def accessibility(grid, road_frac=None, threshold=0.2):  #not used by the CA any more; the RL agents use it as a feature
    """
    Distance decay from the road SURFACE, nothing is built far from a street.

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


def growth_rates(grid, demand, steps):
    #cells each class may take per step: its growth spread evenly over the run, so the map grows step by step
    return {k: math.ceil(max(0, demand.get(k, 0) - int((grid == k).sum())) / steps) for k in RULES}


def step(grid, demand, rng, street, rate, allowed=None):
    """One CA step: vacant cells take the uses their neighbours support, until demand is met.
    allowed: cells that may convert (the cleared design site); None lets every vacant cell convert."""
    nb = neighbour_counts(grid)
    new = grid.copy()
    taken = np.zeros(grid.shape, dtype=bool)  #one conversion per cell per step
    #classes still short of demand, largest shortfall first
    wants = sorted(((k, demand.get(k, 0) - int((grid == k).sum())) for k in RULES), key=lambda t: -t[1])
    for k, deficit in wants:
        n_take = min(deficit, rate.get(k, 0))
        if n_take <= 0:
            continue
        rule = RULES[k]
        score = sum(nb[m] for m in rule["next_to"]).astype("float32")  #how many neighbours support this use
        ok = (grid == VACANT) & ~taken & (score >= 1)  #only vacant land, and only next to a supporting neighbour
        if allowed is not None:
            ok &= allowed  #only inside the area being rebuilt
        if rule["street"]:
            ok &= street  #shops only on a street
        cand = np.where(ok, score + rng.uniform(0, 1, grid.shape), -np.inf).ravel()  #random tie-break within a score
        n_take = int(min(n_take, np.isfinite(cand).sum()))
        if n_take <= 0:
            continue
        idx = np.argpartition(cand, -n_take)[-n_take:]  #the best-supported cells convert
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


def amenity_access(grid, cell_m, mask=None):
    """Mean distance from a home to the nearest amenity or shop, in metres.
    mask: only homes inside it count; shops and amenities anywhere on the grid serve them."""
    from scipy.ndimage import distance_transform_edt
    target = np.isin(grid, [AMENITY, RETAIL])
    homes = (grid == RESID) if mask is None else (grid == RESID) & mask
    if not target.any() or not homes.any():
        return None
    d = distance_transform_edt(~target) * cell_m
    return round(float(d[homes].mean()), 1)


def score(grid, cell_m, mask=None):
    #the objective's terms over the whole grid, or over the cells of mask (the design site, as the RL agents score)
    cells = grid if mask is None else grid[mask]
    return {
        "landuse_mix": round(shannon_mix(cells), 4),
        "green_share": round(float((cells == GREEN).sum()) / cells.size, 4),
        "residential_cells": int((cells == RESID).sum()),
        "mean_distance_to_amenity_m": amenity_access(grid, cell_m, mask),
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
def validate_regrow(grid0, street, cell_m, steps, frac, seed, rng_reps=5):
    """
    Can the CA put back what we take away?

    A CA run with demand equal to the current counts converts nothing: there is
    no deficit, so "the baseline does not change" validates nothing. The real
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
        rate = growth_rates(g, demand, steps)  #the erased cells come back over the run
        for _ in range(steps):
            g = step(g, demand, rng, street, rate)  #the same rules as the programme runs

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

    print(f"Cellular automaton land use: {STUDY_AREA.name}")
    grid0, transform, (nx, ny), road_frac = rasterise(args.cell)
    print(f"  grid {nx} x {ny} of {args.cell:.0f} m = {nx*ny:,} cells")
    served = (road_frac >= STREET_FRAC)
    print(f"  street-served cells: {served.sum():,} "
          f"({100*served.mean():.0f}%): carriageway covers "
          f"{100*road_frac.mean():.0f}% of the area")
    s0 = shares(grid0)
    print("  initial state:")
    for k, v in sorted(s0.items(), key=lambda t: -t[1]):
        if v > 0:
            print(f"     {k:12} {100*v:5.1f}%  ({int(v*grid0.size):,} cells)")

    street = road_frac >= STREET_FRAC  #cells a shop may take

    #the design site, cell centre inside it (as rl_landuse.py and score_scenarios.py use it)
    from rasterio.features import rasterize as burn
    site = burn([(design_site_polygon(), 1)], out_shape=grid0.shape, transform=transform).astype(bool)
    cleared = grid0.copy()
    cleared[site & ~np.isin(grid0, list(FIXED))] = VACANT  #the site cleared except roads and water, as the RL agents start
    n_site = int((site & (cleared == VACANT)).sum())  #cells to rebuild
    homes_today = int((grid0[site] == RESID).sum())  #housing cells on the site today, the housing term's reference
    print(f"\n  design site {int(site.sum())} cells, {n_site} cleared and rebuilt; {homes_today} housing cells today")

    #land-use programmes on the cleared site, keyed by their own names so they never read as the Rhino scenario_a/scenario_b
    scenarios = {"baseline": {k: int((grid0 == k).sum()) for k in RULES}}  #today: demand met, nothing converts
    for name, prog in PROGRAMMES.items():
        assert sum(prog.values()) == n_site, (name, sum(prog.values()), n_site)  #every cleared cell gets a use
        scenarios[name] = {k: int((cleared == k).sum()) + prog.get(k, 0) for k in RULES}  #the rest of the grid plus the site's programme
    labels = {
        "baseline": "today: the design site as it stands, nothing cleared.",
        "compact": "compact: the design site cleared and rebuilt with today's housing and more shops",
        "green": "green: the design site cleared and rebuilt with a quarter less housing and a park",
    }

    out = {
        "method": "cellular_automata",
        "colours": COLOURS,
        "model": "neighbour-rule CA: the design site is cleared and its cells take the uses their 8 neighbours support, until the programme is met",
        "cell_size_m": args.cell,
        "bbox_rd": [round(v, 1) for v in bbox_rd()],
        "grid": {"nx": nx, "ny": ny, "origin_rd": [bbox_rd()[0], bbox_rd()[1]]},
        "classes": CLASSES,
        "fixed_classes": ["water", "road"],
        "parameters": {
            "steps": args.steps, "replicates": args.replicates,
            "neighbourhood": "Moore, the 8 surrounding cells",
            "rules": {CLASSES[k]: {"next_to": [CLASSES[m] for m in r["next_to"]], "street": r["street"]}
                      for k, r in RULES.items()},  #industry has no rule: it never grows
            "street_frac": STREET_FRAC,
            "converts": "the design site's cells, cleared first (roads and water stay); outside the site nothing changes",
            "growth": "each class's growth spread evenly over the steps, best-supported cells first, random tie-break",
        },
        "caveat": "Demand is set by us, not derived from a regional model. This "
                  "explores the consequences of a development programme, it does "
                  "not forecast one.",
        "_programmes_note": "The entries under 'scenarios' are land-use programmes "
                            "(baseline, compact, green) on the cleared design site, scored over the "
                            "site like the RL agents. They are NOT the Rhino design options "
                            "scenario_a and scenario_b; those are scored on the same objective in "
                            "landuse_scenarios.json.",
        "initial": {"shares": s0, "score": score(grid0, args.cell)},  #the whole grid today
        "initial_site": score(grid0, args.cell, site),  #the design site today
        "site_cells": int(site.sum()),
        "rebuilt_cells": n_site,
        "homes_today_cells": homes_today,  #the housing term's reference
        "programmes_site_cells": {n: {CLASSES[k]: v for k, v in prog.items()} for n, prog in PROGRAMMES.items()},
        "scenarios": {},
    }

    for name, demand in scenarios.items():
        print(f"\n  === {name}: {labels[name]} ===")
        best, best_obj, runs = None, -1e9, []
        for rep in range(args.replicates):
            rng = np.random.default_rng(args.seed + rep)
            g = (grid0 if name == "baseline" else cleared).copy()  #a programme starts from the cleared site
            traj = [{"t": 0, "shares": shares(g)}]  #the start: today, or the cleared site
            keep_grids = [g.copy()]
            rate = growth_rates(g, demand, args.steps)  #cells per step per class
            for t in range(1, args.steps + 1):
                g = step(g, demand, rng, street, rate, allowed=site)  #only the site changes
                traj.append({"t": t, "shares": shares(g)})
                keep_grids.append(g.copy())
            extra = 0  #steps past the last one, while cells are still short of the programme and something can still grow
            while extra < args.steps and any(demand[k] > int((g == k).sum()) for k in RULES):
                g2 = step(g, demand, rng, street, {k: max(1, rate[k]) for k in RULES}, allowed=site)
                if (g2 == g).all():
                    break  #nothing can grow any more: the rest stays unmet and is reported
                g, extra = g2, extra + 1
            filled = 0  #cells no rule could reach take what the programme still lacks, so the whole site is built
            left = np.flatnonzero((site & (g == VACANT)).ravel())
            for k in sorted(RULES, key=lambda k: int((g == k).sum()) - demand[k]):  #largest shortfall first
                short = demand[k] - int((g == k).sum())
                if short > 0 and left.size:
                    take = rng.choice(left, size=min(short, left.size), replace=False)
                    g.ravel()[take] = k
                    left = np.setdiff1d(left, take)
                    filled += len(take)
            keep_grids[-1] = g.copy()  #the last frame shows the finished site
            sc = score(g, args.cell, site)  #over the design site, as the RL agents are scored
            #the objective: mixed, green, walkable, and no net loss of housing cells against today
            obj = float(np.dot(DEFAULT_W, components(sc, sc["residential_cells"], homes_today)))
            runs.append({"replicate": rep, "objective": round(obj, 4), "extra_steps": extra, "filled_cells": filled, **sc})
            if obj > best_obj:
                best_obj, best = obj, (g, traj, keep_grids)

        g, traj, keep_grids = best
        objs = np.array([r["objective"] for r in runs])
        mixes = np.array([r["landuse_mix"] for r in runs])
        print(f"     objective over {args.replicates} runs: "
              f"mean {objs.mean():.3f}  best {objs.max():.3f}  sd {objs.std():.3f}")
        print(f"     land-use mix: {mixes.mean():.3f} +/- {mixes.std():.3f}")
        sc = score(g, args.cell, site)
        unmet = {CLASSES[k]: demand[k] - int((g == k).sum()) for k in RULES if demand[k] > int((g == k).sum())}  #demand the rules could not place
        if unmet:
            print(f"     unmet demand in the best run: {unmet} cells")
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
            "unmet_demand_cells": unmet,  #empty when every class got its cells
            "shares_final": shares(g),
            "trajectory": traj,
            "steps": [{"t": int(i), "grid": keep_grids[i].tolist()} for i in idx],
        }

    print("\n  === validation: erase and regrow ===")
    out["validation"] = {}
    for frac in (0.1, 0.25, 0.5):
        v = validate_regrow(grid0, street, args.cell, args.steps,
                            frac, args.seed)
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
