#!/usr/bin/env python3
"""
density_site.py - GSI, FSI and storeys on the design site, today and in every scenario.

The same method as density_height.py, so the numbers can stand next to the
buurt figures in the report:

    GSI = built footprint / site area
    FSI = floor area / site area          floor area = footprint x storeys
    L   = FSI / GSI                       mean storeys

TODAY: every 3DBAG building whose point lies on the design site. Storeys from
3DBAG where it gives them, otherwise height / storey height, rounded, at least
one, with the storey height measured from the buildings that have both (as in
density_height.py).

A SCENARIO: today's buildings minus the ones it demolishes, plus its new blocks
from design_massing.geojson. A new block has height / storey height storeys.
Flats stood on a shop podium (blocks with a base height) add floors but no
ground cover, because the podium below them is already counted.

USAGE
-----
    python analysis/morphology/density_site.py

OUTPUT
------
    data/processed/density_site.json   one entry per scenario
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scenarios"))
from common.project import PROCESSED, RAW, design_site_polygon  # noqa: E402
from density_height import measured_storey_height  # noqa: E402

SCENARIOS = ["baseline", "scenario_a", "scenario_b", "final"]


#every 3DBAG building on the design site: id, footprint, storeys
def buildings_today(site, storey_m):
    from shapely.geometry import Point
    feats = json.loads((RAW / "buildings_3dbag.geojson").read_text())["features"]
    rows = []
    for f in feats:
        p = f["properties"]
        area = p.get("b3_opp_grond")
        if not area or area <= 0:
            continue
        if not site.contains(Point(f["geometry"]["coordinates"])):
            continue
        floors = p.get("b3_bouwlagen")
        if not floors:  #missing in 3DBAG: estimate from the height
            h = p.get("height_m")
            floors = max(1, round(h / storey_m)) if h else 1
        rows.append({"id": p["identificatie"], "footprint": area, "floors": floors, "ground": True})
    return rows


#the scenario's new blocks: footprint, storeys, and whether they cover ground
def new_blocks(scenario, storey_m):
    import geopandas as gpd
    massing = json.loads((PROCESSED / "design_massing.geojson").read_text())
    feats = [f for f in massing["features"] if f["properties"]["scenario"] == scenario]
    blocks = gpd.GeoDataFrame.from_features(feats, crs=4326).to_crs(28992)  #RD metres, for the areas
    rows = []
    for f, geom in zip(feats, blocks.geometry):
        p = f["properties"]
        rows.append({"id": p["name"], "footprint": geom.area,
                     "floors": max(1, round(p["building_height_m"] / storey_m)),
                     "ground": "base_height_m" not in p})  #flats on a podium: floors, no ground cover
    gone = set(massing.get("demolishes", {}).get(scenario, []))
    return rows, gone


#GSI, FSI and L for a list of buildings over the site
def density(rows, site_area):
    footprint = sum(r["footprint"] for r in rows if r["ground"])
    floor_area = sum(r["footprint"] * r["floors"] for r in rows)
    gsi = footprint / site_area
    fsi = floor_area / site_area
    return {"buildings": sum(1 for r in rows if r["ground"]),
            "footprint_m2": round(footprint),
            "floor_area_m2": round(floor_area),
            "gsi": round(gsi, 3),
            "fsi": round(fsi, 3),
            "layers": round(fsi / gsi, 2) if gsi else None}


def main():
    site = design_site_polygon()

    #the storey height, measured exactly as in density_height.py
    feats = json.loads((RAW / "buildings_3dbag.geojson").read_text())["features"]
    floors = np.array([f["properties"].get("b3_bouwlagen") or np.nan for f in feats], dtype=float)
    height = np.array([f["properties"].get("height_m") if f["properties"].get("height_m") is not None
                       else np.nan for f in feats], dtype=float)
    storey_m, _ = measured_storey_height(floors, height)

    today = buildings_today(site, storey_m)
    out = {"_source": "analysis/morphology/density_site.py",
           "_method": "GSI, FSI and L over the design site, same rule as density_height.py: "
                      "3DBAG storeys, else height / storey height; new blocks height / storey height; "
                      "flats on a shop podium add floors, not ground cover",
           "site_area_ha": round(site.area / 10_000, 2),
           "storey_height_m": round(storey_m, 3)}

    print(f"Density on the design site ({site.area / 10_000:.2f} ha), storey height {storey_m:.2f} m")
    for sc in SCENARIOS:
        if sc == "baseline":
            rows = today
        else:
            new, gone = new_blocks(sc, storey_m)
            rows = [r for r in today if r["id"] not in gone] + new
        out[sc] = density(rows, site.area)
        d = out[sc]
        print(f"  {sc:11}  GSI {d['gsi']:.3f}  FSI {d['fsi']:.3f}  L {d['layers']:.2f}  "
              f"({d['buildings']} buildings)")

    (PROCESSED / "density_site.json").write_text(json.dumps(out, indent=2) + "\n")
    print("  wrote data/processed/density_site.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
