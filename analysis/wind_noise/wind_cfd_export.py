#!/usr/bin/env python3
"""
wind_cfd_export.py — watertight building STLs for the OpenFOAM wind model.

Turns the design site's buildings into a flat-ground STL that snappyHexMesh can
mesh. Each footprint is extruded from z=0 (the OpenFOAM ground wall) up to its
height ABOVE GROUND. There is no NAP offset here: unlike the Cesium app, the
OpenFOAM domain stands on a flat ground plane at z=0, so heights above ground
are exactly what the solver wants.

Per case:
    baseline     the 3DBAG buildings now standing on the design site
    scenario_a   those demolished (the keep_rd survivors stay), the 22 new
                 massing blocks added. The kept block (school, halls and
                 workshops, circled on the BAG) is NOT in the demolition list,
                 so it survives buildings_for_scenario() and is welded into the
                 STL as a solid obstacle.

The geometry is moved to a local metric frame centred on the site and ROTATED so
the prevailing wind (from the SW, 225 deg) blows along +x. That is the inlet
direction the OpenFOAM ABL case expects (flowDir (1 0 0)): the SW edge of the
site becomes the inlet side (xMin), the NE edge the outlet (xMax).

Writes, per case, into cache/wind/geometry/ (gitignored, regenerable):
    b_<case>.stl         one watertight solid per building, concatenated
    b_<case>.meta.json   centre, rotation, local bounds, counts, kept ids

Run:
    python analysis/wind_noise/wind_cfd_export.py                 # both cases
    python analysis/wind_noise/wind_cfd_export.py --wind-from 225 # pick a wind
    python analysis/wind_noise/wind_cfd_export.py --cases scenario_a
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "scenarios"))
from common.project import ROOT, design_site_polygon  # noqa: E402
from scenario_world import load_scenario, site_footprints  # noqa: E402
from scenario_world import FOOTPRINTS  # noqa: E402

OUT = ROOT / "cache" / "wind" / "geometry"
DEFAULT_WIND_FROM = 225.0  #prevailing wind in the Netherlands is from the south-west
MIN_HEIGHT_M = 3.0  #one storey for the few sheds 3DBAG gives no height


def load_footprints():
    #3DBAG LoD0 footprints over the design site as a GeoDataFrame (RD, height_m above ground)
    import geopandas as gpd
    site_footprints()  #fetches cache/scenarios/footprints_site.geojson if missing (keeps height_m)
    b = gpd.read_file(FOOTPRINTS).set_crs("EPSG:28992", allow_override=True)
    missing = b["height_m"].isna() | (b["height_m"] <= 0)  #sheds without a 3DBAG height
    b.loc[missing, "height_m"] = MIN_HEIGHT_M  #give them one storey rather than dropping them
    return b


def buildings_for_case(b, case: str, site):
    #the buildings standing on the site for one case, as (id, height_m, shapely geom in RD)
    if case == "baseline":
        on_site = b[b.representative_point().within(site)].copy()
        rows = list(zip(on_site["identificatie"], on_site["height_m"], on_site.geometry))
        return rows, []  #no kept-list to report for the baseline
    #scenario: demolished ids out, keep_rd survivors in, new blocks appended
    sys.path.insert(0, str(HERE.parent / "scenarios"))
    from scenario_world import buildings_for_scenario
    scen = buildings_for_scenario(b, case)  #id col "identificatie", height_m above ground
    on_site = scen[scen.representative_point().within(site)].copy()
    original = set(b["identificatie"])  #3DBAG ids, to tell survivors from new blocks
    kept = on_site[on_site["identificatie"].isin(original)]["identificatie"].tolist()
    rows = list(zip(on_site["identificatie"], on_site["height_m"], on_site.geometry))
    return rows, kept


def to_local(geom, cx, cy, alpha_deg):
    #RD geometry -> site-centred, rotated frame: wind-from bearing B -> +x needs a (B+90) deg ccw turn
    from shapely.affinity import rotate, translate
    g = translate(geom, xoff=-cx, yoff=-cy)  #site centroid to the origin
    return rotate(g, alpha_deg, origin=(0, 0), use_radians=False)


def polygons(geom):
    #yield the Polygon parts of any (multi)polygon / collection, dropping empties
    from shapely.geometry import MultiPolygon, Polygon
    from shapely.validation import make_valid
    geom = make_valid(geom).buffer(0)
    if geom.is_empty:
        return
    if isinstance(geom, Polygon):
        yield geom
    elif isinstance(geom, MultiPolygon):
        yield from (g for g in geom.geoms if not g.is_empty)
    else:  #GeometryCollection from make_valid: keep only the polygonal parts
        for g in getattr(geom, "geoms", []):
            if isinstance(g, (Polygon, MultiPolygon)):
                yield from polygons(g)


def build_mesh(rows, cx, cy, alpha_deg):
    #extrude each footprint from z=0 to its height, in the local frame; return one concatenated mesh
    import trimesh
    meshes = []
    for _id, h, geom in rows:
        h = float(h)
        if not np.isfinite(h) or h <= 0:
            continue
        for poly in polygons(to_local(geom, cx, cy, alpha_deg)):
            if poly.area < 1e-3:  #slivers would make snappyHexMesh unhappy
                continue
            try:
                meshes.append(trimesh.creation.extrude_polygon(poly, height=h))
            except Exception as e:  #a pathological footprint should not sink the whole export
                print(f"    skipped one part of {_id}: {e}")
    if not meshes:
        return None
    return trimesh.util.concatenate(meshes)


def export_case(b, case: str, site, cx, cy, alpha_deg, wind_from):
    rows, kept = buildings_for_case(b, case, site)
    print(f"  {case}: {len(rows)} buildings on the site"
          + (f", {len(kept)} kept 3DBAG survivors" if case != "baseline" else ""))
    mesh = build_mesh(rows, cx, cy, alpha_deg)
    if mesh is None:
        sys.exit(f"no geometry built for {case}")
    OUT.mkdir(parents=True, exist_ok=True)
    stl = OUT / f"b_{case}.stl"
    mesh.export(stl)  #binary STL, what snappyHexMesh and the assignment use
    xmin, ymin, zmin = mesh.bounds[0]
    xmax, ymax, zmax = mesh.bounds[1]
    meta = {
        "case": case,
        "wind_from_deg": wind_from,
        "rotation_deg_ccw": alpha_deg,
        "note": "local frame, metres, ground at z=0, heights above ground; "
                "+x points downwind (wind blows from -x inlet to +x outlet)",
        "centre_rd": [round(cx, 2), round(cy, 2)],
        "n_buildings": len(rows),
        "n_triangles": int(len(mesh.faces)),
        "watertight": bool(mesh.is_watertight),
        "local_bounds_m": {
            "xMin": round(float(xmin), 2), "xMax": round(float(xmax), 2),
            "yMin": round(float(ymin), 2), "yMax": round(float(ymax), 2),
            "zMin": round(float(zmin), 2), "zMax": round(float(zmax), 2),
        },
        "footprint_span_m": [round(float(xmax - xmin), 2), round(float(ymax - ymin), 2)],
        "max_height_m": round(float(zmax), 2),
        "kept_bag_ids": kept,
    }
    (OUT / f"b_{case}.meta.json").write_text(json.dumps(meta, indent=2))
    print(f"    wrote {stl.relative_to(ROOT)}  "
          f"({meta['n_triangles']} tris, span {meta['footprint_span_m']} m, "
          f"max {meta['max_height_m']} m, watertight={meta['watertight']})")
    return meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wind-from", type=float, default=DEFAULT_WIND_FROM,
                    help="bearing the wind blows FROM, met. degrees (225 = SW, default)")
    ap.add_argument("--cases", nargs="+", default=["baseline", "scenario_a"],
                    help="cases to export (default: baseline scenario_a)")
    args = ap.parse_args()

    #a wind FROM bearing B must be turned (B+90) deg ccw to point downwind along +x
    alpha_deg = (args.wind_from + 90.0) % 360.0
    site = design_site_polygon()
    cx, cy = site.centroid.x, site.centroid.y
    print(f"site centre RD ({cx:.1f}, {cy:.1f}); wind from {args.wind_from:.0f} deg "
          f"-> rotate {alpha_deg:.0f} deg ccw so it blows along +x")

    b = load_footprints()
    #make sure the kept block really is a scenario_a survivor, not just assumed
    keep = load_scenario("scenario_a")  #(new blocks, demolished ids)
    demolished = keep[1]
    print(f"scenario_a demolishes {len(demolished)} 3DBAG ids; the keep_rd block is excluded from that list")

    metas = {case: export_case(b, case, site, cx, cy, alpha_deg, args.wind_from)
             for case in args.cases}

    if "scenario_a" in metas:
        kept = metas["scenario_a"]["kept_bag_ids"]
        if kept:
            print(f"\nKept circled building(s) present in scenario_a: {len(kept)} 3DBAG record(s)")
            for k in kept:
                print(f"    {k}")
        else:
            print("\nWARNING: no kept 3DBAG survivors found on the site in scenario_a")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
