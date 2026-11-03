#!/usr/bin/env python3
"""
density_height.py - building density and height variation.

Owner: Atanas Malinkov

Spacematrix (Berghauser Pont & Haupt 2010) on a 100 m grid and over the whole
buurt. GSI = footprint / land, FSI = floor area / land, L = FSI / GSI storeys.
Floors come from b3_bouwlagen, otherwise height / measured storey height.
Sheds count for density; height statistics use buildings >= 40 m2 and >= 4 m.

SCENARIOS
---------
--scenario scenario_a|scenario_b|final takes the 3DBAG buildings the design
demolishes out and its new blocks in (design_massing.geojson, via
scenario_world.load_scenario). A new block's storeys are its own height over the
storey height measured above, the rule the 3DBAG buildings without a storey
count get. Flats stood on a shop podium (final design) add floors but no ground
cover, and count as one building with their podium, as in
compare_scenarios.py; the podium leaves the height statistics, the flats' roof
stands for the pair. Outputs carry a _<scenario> suffix; the baseline keeps the
plain names.

Runs every case in CASES; --scenario followed by case names selects a subset.
"""

import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import (  #noqa: E402
    PROCESSED, RAW, STUDY_AREA, bbox_rd, buurt_polygons, buurt_properties,
    study_area_polygon, to_wgs,
)

MIN_FOOTPRINT_M2 = 40.0     #below this it is an outbuilding, not a building
MIN_HEIGHT_M = 4.0          #single-storey garages are not "building height"


def load_buildings():
    path = RAW / "buildings_3dbag.geojson"
    if not path.exists():
        print(f"missing {path}\nRun: python analysis/morphology/fetch_buildings.py")
        sys.exit(1)
    feats = json.loads(path.read_text())["features"]
    x, y, area, floors_raw, height, ids = [], [], [], [], [], []
    for f in feats:
        p = f["properties"]
        a, h = p.get("b3_opp_grond"), p.get("height_m")
        if not a or a <= 0:
            continue
        x.append(f["geometry"]["coordinates"][0])
        y.append(f["geometry"]["coordinates"][1])
        area.append(a)
        floors_raw.append(p.get("b3_bouwlagen"))
        height.append(h if h is not None else np.nan)
        ids.append(p.get("identificatie"))  #to take out what a scenario demolishes
    return (np.array(x), np.array(y), np.array(area, dtype="float64"),
            np.array([f if f else np.nan for f in floors_raw], dtype="float64"),
            np.array(height, dtype="float64"), np.array(ids, dtype=object))


def scenario_blocks(scenario: str, storey_m: float):
    #the scenario's new blocks as building records: x, y, footprint, storeys, roof height above
    #ground, ground cover, building count, and whether they enter the height statistics
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scenarios"))
    from scenario_world import load_scenario
    new, gone = load_scenario(scenario)  #RD, height_m = roof above ground, own_height_m = the block itself
    raised = (new["height_m"] - new["own_height_m"]).to_numpy() > 0.5  #flats stood on a shop podium
    podium = np.zeros(len(new), dtype=bool)
    for g in new.geometry[raised]:  #the podium under a raised block: its roof is not the building's
        for j, h in enumerate(new.geometry):
            if not raised[j] and h.intersects(g) and h.intersection(g).area > 0.5 * h.area:
                podium[j] = True
    pt = new.geometry.representative_point()
    foot = new.geometry.area.to_numpy()
    rec = {
        "x": pt.x.to_numpy(), "y": pt.y.to_numpy(),
        "area": foot,
        "floors": np.maximum(1.0, np.round(new["own_height_m"].to_numpy(dtype=float) / storey_m)),
        "height": new["height_m"].to_numpy(dtype=float),
        "cover": np.where(raised, 0.0, foot),  #flats on a podium add floors, not ground cover
        "bcount": np.where(raised, 0, 1),  #a podium and the flats on it are one building
        "hstat": ~podium,
    }
    return rec, gone, int(raised.sum())


def measured_storey_height(floors, height):
    #Median metres per storey, from buildings where 3DBAG gives both.
    ok = np.isfinite(floors) & np.isfinite(height) & (floors >= 2)
    if ok.sum() < 30:
        return 3.0, 0
    return float(np.median(height[ok] / floors[ok])), int(ok.sum())


def describe(v):
    v = v[np.isfinite(v)]
    if v.size == 0:
        return {}
    return {"n": int(v.size),
            "mean": round(float(v.mean()), 3),
            "std": round(float(v.std()), 3),
            "median": round(float(np.median(v)), 3),
            "p10": round(float(np.percentile(v, 10)), 3),
            "p90": round(float(np.percentile(v, 90)), 3),
            "max": round(float(v.max()), 3)}


PARAMS = {
    "cell": 100.0,  #grid cell size, m
    "min_footprint": MIN_FOOTPRINT_M2,
    "min_height": MIN_HEIGHT_M,
    "min_buildings": 3,  #cells with fewer buildings are flagged sparse
}

CASES = [{"scenario": sc} for sc in ("baseline", "scenario_a", "scenario_b", "final")]


def run(p):
    #one case: PARAMS merged with the scenario from CASES
    sfx = "" if p['scenario'] == "baseline" else f"_{p['scenario']}"  #output file suffix

    print(f"Building density and height variation — {STUDY_AREA.name}, {p['scenario']}")
    x, y, area, floors_raw, height, ids = load_buildings()
    print(f"  {len(x):,} buildings with a footprint area")

    sh, n_sh = measured_storey_height(floors_raw, height)  #from today's 3DBAG in every scenario
    print(f"  storey height measured from {n_sh:,} buildings: {sh:.2f} m/floor")

    floors = floors_raw.copy()
    missing = ~np.isfinite(floors)
    est = np.maximum(1.0, np.round(height / sh))
    floors[missing] = est[missing]
    floors[~np.isfinite(floors)] = 1.0
    print(f"  floors: {int((~missing).sum()):,} from 3DBAG, "
          f"{int(missing.sum()):,} estimated from height")

    cover = area.copy()  #ground cover, for GSI; equal to the footprint for every 3DBAG building
    bcount = np.ones(len(x), dtype=int)  #buildings each record counts as
    hstat = np.ones(len(x), dtype=bool)  #records that enter the height statistics
    if p['scenario'] != "baseline":
        rec, gone, n_raised = scenario_blocks(p['scenario'], sh)
        keep = ~np.isin(ids, list(gone))  #demolished buildings out
        print(f"  {p['scenario']}: {int((~keep).sum()):,} buildings demolished, "
              f"{len(rec['x'])} new volumes ({n_raised} flats on a shop podium)")
        x, y, area, floors, height = (np.concatenate([v[keep], rec[k]]) for v, k in
                                      [(x, "x"), (y, "y"), (area, "area"), (floors, "floors"), (height, "height")])
        cover = np.concatenate([cover[keep], rec["cover"]])
        bcount = np.concatenate([bcount[keep], rec["bcount"]])
        hstat = np.concatenate([hstat[keep], rec["hstat"]])
        missing = np.concatenate([missing[keep], np.zeros(len(rec["x"]), dtype=bool)])  #new storeys are set, not missing

    gfa = area * floors

    principal = (area >= p['min_footprint']) & (height >= p['min_height']) & hstat
    print(f"  principal buildings (>= {p['min_footprint']:.0f} m2 and "
          f">= {p['min_height']:.0f} m): {int(principal.sum()):,} "
          f"({100 * principal.mean():.0f}%), holding "
          f"{100 * area[principal].sum() / area.sum():.0f}% of the built area")

    #--- grid
    xmin, ymin, xmax, ymax = bbox_rd()
    c = p["cell"]
    nx = int(np.ceil((xmax - xmin) / c))
    ny = int(np.ceil((ymax - ymin) / c))
    col = ((x - xmin) // c).astype(int)
    row = ((y - ymin) // c).astype(int)
    on_grid = (col >= 0) & (col < nx) & (row >= 0) & (row < ny)  #raw data can reach past the box; clamping piled it into edge cells
    flat = np.where(on_grid, row * nx + col, 0)
    ncell = nx * ny
    cell_area = c * c

    sum_area = np.bincount(flat, weights=np.where(on_grid, cover, 0), minlength=ncell)  #off-grid buildings weigh nothing
    sum_gfa = np.bincount(flat, weights=np.where(on_grid, gfa, 0), minlength=ncell)
    count = np.bincount(flat, weights=np.where(on_grid, bcount, 0).astype(float), minlength=ncell).astype(int)  #and are not counted

    pm = principal & np.isfinite(height) & on_grid  #height stats on grid buildings only
    p_flat, p_h = flat[pm], height[pm]
    p_cnt = np.bincount(p_flat, minlength=ncell)
    p_sum = np.bincount(p_flat, weights=p_h, minlength=ncell)
    p_sq = np.bincount(p_flat, weights=p_h ** 2, minlength=ncell)
    with np.errstate(invalid="ignore", divide="ignore"):
        h_mean = np.where(p_cnt > 0, p_sum / np.maximum(p_cnt, 1), np.nan)
        h_var = np.where(p_cnt > 1, p_sq / np.maximum(p_cnt, 1) - h_mean ** 2, np.nan)
        h_std = np.sqrt(np.maximum(h_var, 0))
        gsi = sum_area / cell_area
        fsi = sum_gfa / cell_area
        L = np.where(gsi > 0, fsi / np.maximum(gsi, 1e-9), np.nan)

    print(f"  grid {nx} x {ny} cells of {c:.0f} m; "
          f"{int((count > 0).sum())} contain buildings")

    #--- grid -> GeoJSON (WGS84)
    cells = []
    for i in range(ncell):
        if count[i] == 0:
            continue
        r, cc = divmod(i, nx)
        x0, y0 = xmin + cc * c, ymin + r * c
        ring = [to_wgs(x0, y0), to_wgs(x0 + c, y0),
                to_wgs(x0 + c, y0 + c), to_wgs(x0, y0 + c), to_wgs(x0, y0)]
        cells.append({
            "type": "Feature",
            "geometry": {"type": "Polygon",
                         "coordinates": [[[round(a, 7), round(b, 7)] for a, b in ring]]},
            "properties": {
                #grid indices travel with the cell: the RD->WGS84 transform is
                #not axis-aligned, so the row/col cannot be recovered from the
                #lon/lat afterwards without them
                "row": int(r),
                "col": int(cc),
                "gsi": round(float(gsi[i]), 4),
                "fsi": round(float(fsi[i]), 4),
                "layers": None if not np.isfinite(L[i]) else round(float(L[i]), 2),
                "height_mean_m": None if not np.isfinite(h_mean[i]) else round(float(h_mean[i]), 2),
                "height_std_m": None if not np.isfinite(h_std[i]) else round(float(h_std[i]), 2),
                "n_buildings": int(count[i]),
                "n_principal": int(p_cnt[i]),
                "sparse": bool(count[i] < p["min_buildings"]),
            },
        })
    (PROCESSED / f"density_grid{sfx}.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "_source": "3DBAG v20250903, aggregated by analysis/morphology/density_height.py"
                   + ("" if not sfx else f"; {p['scenario']}: design_massing.geojson's demolition and new blocks"),
        "_cell_size_m": c,
        "_grid": {"nx": nx, "ny": ny, "origin_rd": [xmin, ymin]},
        "features": cells,
    }) + "\n")
    print(f"  wrote density_grid{sfx}.geojson ({len(cells)} cells)")

    #--- aggregate per buurt and overall
    #The study area is two whole buurten, so each is reported separately and
    #together. The bounding box is derived from their union, so unlike the old
    #600 m square there is no partial-coverage correction to make: every
    #building in a buurt is inside the data we fetched.
    per_buurt, combined = {}, None
    try:
        import shapely.geometry as sg
        from shapely.prepared import prep

        polys, props = buurt_polygons(), buurt_properties()

        def stats_for(geom, label, code=None):
            pg = prep(geom)
            inside = np.array([pg.contains(sg.Point(px, py)) for px, py in zip(x, y)])
            land = geom.area
            if inside.sum() == 0 or land <= 0:
                return None
            bp = inside & principal & np.isfinite(height)
            g_ = float(cover[inside].sum() / land)
            f_ = float(gfa[inside].sum() / land)
            out = {
                "name": label,
                "code": code,
                "land_area_ha": round(land / 10_000, 2),
                "inhabitants": (props.get(code, {}) or {}).get("aantalInwoners"),
                "n_buildings": int(bcount[inside].sum()),
                "n_principal": int(bp.sum()),
                "gsi": round(g_, 4),
                "fsi": round(f_, 4),
                "layers": round(f_ / g_, 2) if g_ else None,
                "height_m": describe(height[bp]),
            }
            return out

        for code, name in STUDY_AREA.buurten:
            st = stats_for(polys[code], name, code)
            if st:
                per_buurt[name] = st
                print(f"  {name:12} {st['n_buildings']:5,} buildings on "
                      f"{st['land_area_ha']:6.1f} ha   GSI {st['gsi']:.3f}  "
                      f"FSI {st['fsi']:.3f}  {st['layers']:.2f} storeys")

        combined = stats_for(study_area_polygon(), STUDY_AREA.name)
        if combined:
            print(f"  {'combined':12} {combined['n_buildings']:5,} buildings on "
                  f"{combined['land_area_ha']:6.1f} ha   GSI {combined['gsi']:.3f}  "
                  f"FSI {combined['fsi']:.3f}  {combined['layers']:.2f} storeys")
    except Exception as exc:
        print(f"  ! buurt aggregates skipped ({exc})")

    #--- label each cell by buurt
    #The Spacematrix scatter is only worth drawing if the two buurten can be
    #told apart on it: they occupy visibly different parts of the diagram, and
    #a single undifferentiated cloud hides exactly the finding.
    cell_buurt = {}
    try:

        polys = buurt_polygons()
        prepped = [(name, prep(polys[code])) for code, name in STUDY_AREA.buurten]
        for i in range(ncell):
            if count[i] == 0:
                continue
            r, cc = divmod(i, nx)
            pt = sg.Point(xmin + cc * c + c / 2, ymin + r * c + c / 2)
            for name, pg in prepped:
                if pg.contains(pt):
                    cell_buurt[i] = name
                    break
    except Exception as exc:
        print(f"  ! per-cell buurt labels skipped ({exc})")

    #--- summary
    valid = count >= p["min_buildings"]
    summary = {
        "study_area": STUDY_AREA.name,
        **({} if not sfx else {"scenario": p['scenario'],
            "scenario_rule": "3DBAG minus the buildings design_massing.geojson demolishes, plus its new "
                             "blocks: storeys = own height / measured storey height; flats on a shop podium "
                             "add floors, not ground cover, and count as one building with the podium"}),
        "method": "Spacematrix (Berghauser Pont & Haupt 2010): GSI, FSI, L",
        "source": "3DBAG v20250903 (TU Delft), attributes b3_opp_grond / "
                  "b3_bouwlagen / b3_h_dak_50p / b3_h_maaiveld",
        "parameters": {
            "cell_size_m": c,
            "storey_height_m": round(sh, 3),
            "storey_height_source": f"median of {n_sh} buildings with both "
                                    f"b3_bouwlagen and a height",
            "principal_min_footprint_m2": p["min_footprint"],
            "principal_min_height_m": p["min_height"],
            "min_buildings_per_cell": p["min_buildings"],
        },
        "counts": {
            "buildings_total": int(bcount.sum()),
            "buildings_principal": int(principal.sum()),
            "floors_from_3dbag": int((~missing).sum()),
            "floors_estimated": int(missing.sum()),
            "outbuilding_share_of_count": round(float(1 - principal.mean()), 3),
            "outbuilding_share_of_built_area":
                round(float(1 - area[principal].sum() / area.sum()), 3),
        },
        "grid": {
            "n_cells_with_buildings": int((count > 0).sum()),
            "n_cells_used": int(valid.sum()),
            "gsi": describe(gsi[valid]),
            "fsi": describe(fsi[valid]),
            "layers": describe(L[valid]),
            "height_mean_m": describe(h_mean[valid]),
            "height_std_m": describe(h_std[valid]),
        },
        "per_buurt": per_buurt,
        "combined": combined,
        #One point per grid cell for the Spacematrix scatter in the app. The
        #buurt label comes from whichever polygon contains the cell CENTRE, so
        #a cell straddling the boundary is attributed to one side rather than
        #counted twice; cells whose centre falls outside both (the bounding box
        #is larger than the buurten) are labelled null and drawn in grey.
        "spacematrix": [
            {"gsi": round(float(gsi[i]), 4), "fsi": round(float(fsi[i]), 4),
             "layers": None if not np.isfinite(L[i]) else round(float(L[i]), 2),
             "height_mean_m": None if not np.isfinite(h_mean[i]) else round(float(h_mean[i]), 2),
             "height_std_m": None if not np.isfinite(h_std[i]) else round(float(h_std[i]), 2),
             "buurt": cell_buurt.get(i)}
            for i in range(ncell) if valid[i]
        ],
    }
    (PROCESSED / f"density_summary{sfx}.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"  wrote density_summary{sfx}.json")

    #merge the headline numbers into the shared indicators file
    mi_path = PROCESSED / "morphology_indicators.json"
    try:
        mi = json.loads(mi_path.read_text())
    except Exception:
        mi = {}
    mi.pop("_status", None)
    mi.setdefault(p['scenario'], {})
    head = combined or {}
    mi[p['scenario']]["fsi"] = head.get("fsi", summary["grid"]["fsi"].get("mean"))
    mi[p['scenario']]["gsi"] = head.get("gsi", summary["grid"]["gsi"].get("mean"))
    mi[p['scenario']]["layers"] = head.get("layers")
    mi[p['scenario']].pop("osr", None)  #clear the removed indicator from older outputs
    hs = head.get("height_m") or summary["grid"]["height_mean_m"]
    mi[p['scenario']]["height_mean_m"] = hs.get("mean")
    mi[p['scenario']]["height_std_m"] = hs.get("std")
    mi["_density_source"] = "analysis/morphology/density_height.py"
    mi_path.write_text(json.dumps(mi, indent=2) + "\n")
    print("  merged fsi / gsi / height into morphology_indicators.json")

    print()
    if combined:
        b = combined
        print(f"  {b['name']} over {b['land_area_ha']} ha:")
        print(f"     GSI {b['gsi']:.3f}   FSI {b['fsi']:.3f}   "
              f"L {b['layers']:.2f} storeys")
        h = b["height_m"]
        print(f"     building height {h['mean']:.1f} m mean, "
              f"sigma {h['std']:.1f} m, max {h['max']:.1f} m "
              f"({h['n']:,} principal buildings)")
    g = summary["grid"]
    print(f"  across {g['n_cells_used']} grid cells of {c:.0f} m:")
    print(f"     GSI {g['gsi']['mean']:.3f} +/- {g['gsi']['std']:.3f}   "
          f"FSI {g['fsi']['mean']:.3f} +/- {g['fsi']['std']:.3f}")
    print(f"     height variation within a cell: sigma "
          f"{g['height_std_m']['mean']:.2f} m on average, "
          f"up to {g['height_std_m']['max']:.2f} m")
    return 0


def main():
    #run every case by default, or only the names after --scenario
    only = sys.argv[sys.argv.index("--scenario") + 1:] if "--scenario" in sys.argv else None
    for case in CASES:
        if only is None or case["scenario"] in only:
            run({**PARAMS, **case})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
