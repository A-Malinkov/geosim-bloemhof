#!/usr/bin/env python3
"""
score_scenarios.py — the Rhino design options scored on the land-use objective.

Component 4.7, for the scenario comparison (4.9). Owner: Atanas Malinkov.
Built 2026-10-27.

The CA (ca_landuse.py) explores land-use PROGRAMMES (baseline, compact, green)
and the RL agents re-plan the site. Neither is the team's design. This script
takes the design itself, the Rhino options scenario_a and scenario_b, puts it on
the same 25 m grid and scores it with the same objective

    1.6 * land-use mix + 1.0 * green share + 0.8 * max(0, 1 - d / 400 m)

where d is the mean distance from a home to the nearest shop or amenity.

USAGE
-----
    python analysis/abm_landuse/score_scenarios.py

Reads data/processed/design_massing.geojson, design_streets.geojson and
design_planting.geojson (written by analysis/scenarios/import_rhino.py).

METHOD
------
Start from today's grid, built by ca_landuse.rasterise(). Only cells whose
centre lies in cleared_area(scenario) change (the site minus the block a
scenario keeps). Each of them is measured on a 5 m sub-grid and takes the first
class that applies, in the same priority order rasterise() uses for today:

    water        the pond covers the cell centre
    residential  a new block covers at least 25 % of the cell (all blocks are
                 residential in the model)
    road         new street surface covers at least half the cell, the same
                 threshold rasterise() uses for carriageway
    green        proposed green surface covers at least half the cell
    vacant       anything else

"Vacant" here is open ground the model does not programme: courtyards,
pavements and gardens between the blocks. It is NOT derelict land. It gets the
same label because rasterise() labels unbuilt, unpaved, unmapped ground in
today's grid vacant too, so the two are compared like with like. The variant
`open_ground_as_green` counts that ground as green instead, an upper bound on
the green share.

Scored over the design site (cell centre in the site, as rl_landuse.py does)
and over the whole buurt (as ca_landuse.py does). Baseline is today's grid
unchanged, and is asserted to reproduce the CA's and the RL agent's baseline
scores exactly.

WHAT IT CANNOT TELL YOU
-----------------------
* Every new block is residential, because the Rhino model says so. Ground-floor
  shops or services the team may intend are not in the model, so they are not
  scored.
* A 25 m cell cannot hold a building. The 25 % rule decides which cells count
  as built, and a different threshold moves the residential count.
* Distance is straight-line between cells, as in the CA and RL objective, not
  along streets. road_network.py measures walking distance on the network.
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scenarios"))
from common.project import PROCESSED, STUDY_AREA, design_site_polygon, to_rd  # noqa: E402
from ca_landuse import (AMENITY, GREEN, RESID, RETAIL, ROAD, VACANT, WATER, CLASSES,  # noqa: E402
                        rasterise, score as ca_score, shares)
from rl_landuse import objective as site_objective, site_score  # noqa: E402
from weight_sensitivity import DEFAULT_W, components  # noqa: E402

PARAMS = {
    "cell_m": 25.0,  #the CA's cell size
    "sub_m": 5.0,  #sub-grid for area fractions, as rasterise() uses for roads
    "block_min": 0.25,  #a new block on a quarter of the cell makes it residential
    "road_min": 0.5,  #street surface on half the cell makes it road, as in rasterise()
    "green_min": 0.5,  #proposed green on half the cell makes it green
}

CASES = [
    {"scenario": "baseline"},
    {"scenario": "scenario_a"},
    {"scenario": "scenario_b"},
]


# ------------------------------------------------------------------ inputs
def scenario_shapes(scenario):
    #RD shapely geometries of the scenario's blocks, street surfaces, green and water
    from shapely.geometry import shape
    from shapely.ops import transform, unary_union
    rd = lambda g: transform(lambda x, y, z=None: to_rd(x, y), g)  #lon/lat -> RD
    def load(name, keep):
        d = json.loads((PROCESSED / name).read_text())
        gs = [rd(shape(f["geometry"])) for f in d.get("features", [])
              if f["properties"].get("scenario") == scenario and keep(f["properties"])
              and f["geometry"]["type"] in ("Polygon", "MultiPolygon")]
        return unary_union(gs) if gs else None
    return {
        "block": load("design_massing.geojson", lambda p: True),
        "road": load("design_streets.geojson", lambda p: p.get("kind", "street") in ("street", "link")),  #paths are lines, too narrow for a cell
        "green": load("design_planting.geojson", lambda p: p.get("kind") == "green"),
        "water": load("design_planting.geojson", lambda p: p.get("kind") == "water"),
    }


def fraction(geom, shape_, transform, p):
    #share of each 25 m cell covered by geom, measured on the sub-grid
    from rasterio.features import rasterize
    from rasterio.transform import Affine
    ny, nx = shape_
    if geom is None or geom.is_empty:
        return np.zeros(shape_, dtype="float32")
    f = int(round(p["cell_m"] / p["sub_m"]))
    sub_t = transform * Affine.scale(1 / f)  #same origin, sub-cell size
    fine = rasterize([(geom, 1)], out_shape=(ny * f, nx * f), transform=sub_t, fill=0, dtype="uint8")
    return fine.reshape(ny, f, nx, f).mean(axis=(1, 3)).astype("float32")


def centre_mask(geom, shape_, transform):
    #cells whose centre lies in geom, the rule rl_landuse.py uses for the site
    from rasterio.features import rasterize
    if geom is None or geom.is_empty:
        return np.zeros(shape_, dtype=bool)
    return rasterize([(geom, 1)], out_shape=shape_, transform=transform, fill=0, dtype="uint8").astype(bool)


# ----------------------------------------------------------------- burn-in
def burn_scenario(grid0, transform, scenario, p, open_as=VACANT):
    #today's grid with the scenario burned into its cleared area
    from scenario_world import cleared_area
    if scenario == "baseline":
        return grid0.copy(), np.zeros(grid0.shape, dtype=bool)
    sh = scenario_shapes(scenario)
    cleared = centre_mask(cleared_area(scenario), grid0.shape, transform)
    g = grid0.copy()
    g[cleared] = open_as  #start from unprogrammed open ground
    for cls, frac_min, key in ((GREEN, p["green_min"], "green"), (ROAD, p["road_min"], "road"),
                               (RESID, p["block_min"], "block")):  #lowest priority first, so higher ones overwrite
        f = fraction(sh[key], g.shape, transform, p)
        g[cleared & (f >= frac_min)] = cls
    g[cleared & centre_mask(sh["water"], g.shape, transform)] = WATER  #the pond wins, as water does in rasterise()
    return g, cleared


def add_amenities(g, transform, scenario):
    #cells holding an amenity placed by analysis/roads/place_amenities.py: shop -> retail, health and school -> amenity
    path = PROCESSED / "design_amenities.geojson"
    if not path.exists():
        return g, 0
    g = g.copy()
    n = 0
    inv = ~transform  #RD -> (col, row)
    for f in json.loads(path.read_text())["features"]:
        pr = f["properties"]
        if pr["scenario"] != scenario or pr.get("fixed"):  #the kept school is already in today's grid
            continue
        col, row = inv * to_rd(*f["geometry"]["coordinates"])
        r, c = int(row), int(col)
        if 0 <= r < g.shape[0] and 0 <= c < g.shape[1]:
            g[r, c] = RETAIL if pr["type"] == "shop" else AMENITY  #a ground floor of the block becomes that use
            n += 1
    return g, n


def objective_of(sc):
    #the CA objective from a score dict, via weight_sensitivity.components so the formula lives in one place
    return float(np.dot(DEFAULT_W, components(sc)))


# --------------------------------------------------------------------- run
def run(case, p, grid0, transform, site):
    #one scenario: burn in, score over the site and the buurt, both open-ground rules
    sc = case["scenario"]
    out = {}
    for rule, open_as in (("open_ground_as_vacant", VACANT), ("open_ground_as_green", GREEN)):
        if sc == "baseline" and rule == "open_ground_as_green":
            continue  #nothing is cleared, so the rule changes nothing
        g, cleared = burn_scenario(grid0, transform, sc, p, open_as)
        buurt = ca_score(g, p["cell_m"])
        cells = g[site]
        out[rule] = {
            "site": {**site_score(g, p["cell_m"], site), "objective": round(site_objective(g, p["cell_m"], site), 4),
                     "class_cells": {CLASSES[k]: int((cells == k).sum()) for k in range(len(CLASSES))}},
            "buurt": {**buurt, "objective": round(objective_of(buurt), 4), "shares": shares(g)},
            "cleared_cells": int(cleared.sum()),
        }
    if sc != "baseline":  #the same, with the optimised ground-floor amenities in their cells
        g, cleared = burn_scenario(grid0, transform, sc, p, VACANT)
        g, n = add_amenities(g, transform, sc)
        buurt = ca_score(g, p["cell_m"])
        cells = g[site]
        out["with_amenities"] = {
            "site": {**site_score(g, p["cell_m"], site), "objective": round(site_objective(g, p["cell_m"], site), 4),
                     "class_cells": {CLASSES[k]: int((cells == k).sum()) for k in range(len(CLASSES))}},
            "buurt": {**buurt, "objective": round(objective_of(buurt), 4), "shares": shares(g)},
            "amenities_placed": n, "_rule": "open ground as vacant, plus place_amenities.py's amenities",
        }
    r = out["open_ground_as_vacant"]
    print(f"  {sc:10s} site: objective {r['site']['objective']:.3f}, mix {r['site']['landuse_mix']:.3f}, "
          f"green {100 * r['site']['green_share']:.1f} %, {r['site']['residential_cells']} homes cells, "
          f"amenity {r['site']['mean_distance_to_amenity_m']} m | buurt objective {r['buurt']['objective']:.3f}")
    if "with_amenities" in out:  #the amenity variant next to it
        a = out["with_amenities"]
        print(f"  {'':10s} with amenities: objective {a['site']['objective']:.3f}, mix {a['site']['landuse_mix']:.3f}, "
              f"{a['site']['residential_cells']} homes cells, amenity {a['site']['mean_distance_to_amenity_m']} m "
              f"({a['amenities_placed']} placed)")
    return out


def main() -> int:
    p = PARAMS
    print(f"Rhino options on the land-use objective — {STUDY_AREA.name}")
    grid0, transform, _, _ = rasterise(p["cell_m"])  #today's grid, exactly as the CA builds it
    site = centre_mask(design_site_polygon(), grid0.shape, transform)
    print(f"  grid {grid0.shape[1]} x {grid0.shape[0]}, design site {int(site.sum())} cells")
    res = {c["scenario"]: run(c, p, grid0, transform, site) for c in CASES}  #one entry per scenario

    #baseline must reproduce the CA's and the RL agent's own baseline scores, same grid and same functions
    abm = json.loads((PROCESSED / "landuse_abm.json").read_text())
    rl = json.loads((PROCESSED / "landuse_rl.json").read_text())
    b = res["baseline"]["open_ground_as_vacant"]
    assert b["buurt"]["objective"] == abm["scenarios"]["baseline"]["objective_best"], \
        (b["buurt"]["objective"], abm["scenarios"]["baseline"]["objective_best"])
    assert {k: b["buurt"][k] for k in abm["initial"]["score"]} == abm["initial"]["score"]
    assert b["site"]["objective"] == round(rl["baseline_objective"], 4), (b["site"]["objective"], rl["baseline_objective"])
    print(f"  baseline reproduces the CA's buurt objective {abm['scenarios']['baseline']['objective_best']} "
          f"and the RL agent's site objective {rl['baseline_objective']}")

    out = {
        "_written_by": "analysis/abm_landuse/score_scenarios.py",
        "_method": "Today's 25 m land-use grid (ca_landuse.rasterise) with each Rhino option burned into "
                   "cleared_area(scenario): pond -> water, new block on >= 25 % of a cell -> residential, "
                   "street surface on >= 50 % -> road, proposed green on >= 50 % -> green, else vacant. "
                   "Scored with the CA objective 1.6*mix + 1.0*green + 0.8*max(0, 1 - d/400) over the "
                   "design site and over the buurt.",
        "_open_ground": "open_ground_as_vacant labels unprogrammed open ground between blocks vacant, "
                        "the same rule rasterise() applies to today's grid. open_ground_as_green counts it "
                        "as green: an upper bound on the green share.",
        "_not_the_ca": "These are the team's design options. The CA's programmes (baseline, compact, "
                       "green in landuse_abm.json) are a different thing.",
        "parameters": p,
        "objective_weights": {"w_mix": DEFAULT_W[0], "w_green": DEFAULT_W[1], "w_prox": DEFAULT_W[2]},
        **res,
    }
    path = PROCESSED / "landuse_scenarios.json"
    path.write_text(json.dumps(out, indent=1) + "\n")
    print(f"  wrote data/processed/{path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
