#!/usr/bin/env python3
"""
import_rhino.py — proposed massing from the team's Rhino model into the app.

USAGE
-----
    python analysis/scenarios/import_rhino.py

Reads the building solids of one Rhino layer tree per scenario and writes them
as extrudable footprints to data/processed/design_massing.geojson, and the flat
road surfaces of the same tree to data/processed/design_streets.geojson. Both
are drawn by app/modules/scenarios.js.

INPUT
-----
The Rhino model is ~94 MB and stays out of git (data/raw/*.3dm). Get it from
Modelling.zip on the shared drive:
    Modelling/Group Project Q1 - Proposal Modelling_16.10.26.3dm  ->  data/raw/
The model is in RD New (EPSG:28992), in MILLIMETRES, with z = 0 at NAP 0.

FIXES APPLIED ON THE WAY IN
---------------------------
* Datum. The blocks stand on z = 0 (NAP 0) in Rhino, but the site ground is
  DESIGN_SITE["ground_nap_m"] (-0.93 m NAP). We keep each block's modelled
  height and stand it on the ground: roof height_m = ground + (zmax - zmin).
  base_height_m is left out so scenarios.js defaults it to the site ground.
* Strays. A solid whose footprint does not touch the design site (one block was
  left at the model origin) is dropped and reported.
* Site edge. Footprints are clipped to the design site; the clipped area is
  reported per block.

WHAT EACH SCENARIO DEMOLISHES
-----------------------------
The output also lists, per scenario, the 3DBAG buildings the design removes
(`demolishes` in design_massing.geojson, BAG pand ids). The app hides those
when the massing is shown; noise.py and height_width.py are meant to drop them
too. Rule per case:
  "site"     every 3DBAG building on the design site. OPTION 1 lays a new
             street grid over the whole site, so keeping only the buildings it
             does not overlap would leave old rows standing in new courtyards.
  "overlap"  only buildings a new block overlaps by more than 1 m2.
Footprints come from the 3DBAG API (cached in cache/scenarios/, gitignored).

WHAT IT CANNOT TELL YOU
-----------------------
* Heights come from the roof faces, not the bounding box: rhino3dm's Brep
  boxes are loose (a flat 12 m block reported 13.2 m). Each horizontal roof
  level becomes its own flat extrusion from the ground, so a stepped block
  becomes stepped parts. Sloping roofs are not modelled; the importer reports
  any sloping area it skipped.
* The Rhino layers say tall / medium / short, not a use. use is set to
  "residential" because that is the brief, not because the model says so.
* Streets are the flat surfaces on the "New ROADS" sublayer, merged (several
  are drawn twice) and clipped to the site. The road outline curves on that
  layer are not used. Green areas and fences are not imported yet.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import RAW, DESIGN_SITE, design_site_polygon, to_rd, to_wgs, write_processed  # noqa: E402

import rhino3dm  #reads .3dm without Rhino installed
from shapely.geometry import Polygon, mapping  #footprint geometry
from shapely.ops import unary_union, transform  #merge triangles, reproject
from shapely.geometry import shape  #massing back from GeoJSON for the overlap rule
from scenario_world import site_footprints  #3DBAG footprints over the site, shared with the analyses

MODEL = RAW / "Group Project Q1 - Proposal Modelling_16.10.26.3dm"  #newest version in Modelling.zip

#one dict per scenario: which Rhino layer tree becomes which app scenario
CASES = [
    {"scenario": "scenario_a", "layer_prefix": "OPTION 1", "model": MODEL, "demolish": "site"},  #new grid over the whole site
    #OPTION 2 is unfinished in the 16.10 model (one freeform blob reaching 18 m below ground); add it once it is modelled
    #{"scenario": "scenario_b", "layer_prefix": "OPTION 2", "model": MODEL, "demolish": "overlap"},
]

MM = 1000.0  #Rhino units are millimetres
MIN_AREA_M2 = 1.0  #ignore slivers left over after clipping


def meshes(geom):
    #cached render meshes of a Brep or Extrusion, the only geometry rhino3dm can triangulate
    out = []
    if isinstance(geom, rhino3dm.Extrusion):
        m = geom.GetMesh(rhino3dm.MeshType.Any)  #one mesh for the whole extrusion
        if m: out.append(m)
    elif isinstance(geom, rhino3dm.Brep):
        for face in geom.Faces:
            m = face.GetMesh(rhino3dm.MeshType.Any)  #one mesh per Brep face
            if m: out.append(m)
    return out


def clean(polys):
    #union of triangles, hairline seams closed, collinear points dropped
    return unary_union(polys).buffer(0.01).buffer(-0.01).simplify(0.05)


def roof_parts(geom):
    #-> (whole footprint, base z, [(roof footprint, roof z)], sloping m2), all in metres, RD New
    tris, flat, slope = [], {}, 0.0
    allz = []
    for m in meshes(geom):
        V = [(p.X / MM, p.Y / MM, p.Z / MM) for p in m.Vertices]  #mm -> m
        allz += [v[2] for v in V]
        for i in range(len(m.Faces)):
            f = m.Faces[i]  #quad (a,b,c,d) or triangle with c == d
            for t in ((f[0], f[1], f[2]), (f[0], f[2], f[3]) if f[2] != f[3] else None):
                if not t:
                    continue
                a, b, c = (V[k] for k in t)
                p = Polygon([a[:2], b[:2], c[:2]])  #triangle projected to the ground
                if p.area < 1e-6:
                    continue  #vertical wall triangle
                tris.append(p)
                zs = (a[2], b[2], c[2])
                if max(zs) - min(zs) < 0.05:
                    flat.setdefault(round(zs[0], 1), []).append(p)  #horizontal: group by height, 12.0 and 12.01 merge
                else:
                    slope += p.area  #sloping face, reported not modelled
    if not tris:
        return None, None, [], 0.0
    base = min(allz)  #underside of the block
    levels = sorted(z for z in flat if z > base + 0.5)  #roof levels, floors excluded
    parts, covered = [], None
    for z in reversed(levels):  #highest roof first, so a lower roof never claims plan area under a higher one
        poly = clean(flat[z])
        if covered is not None:
            poly = poly.difference(covered)
        if poly.area >= MIN_AREA_M2:
            parts.append((poly, z))
            covered = poly if covered is None else covered.union(poly)
    return clean(tris), base, parts, slope


def import_option(c):
    #building solids of one layer tree -> list of GeoJSON features
    model = rhino3dm.File3dm.Read(str(c["model"]))
    if model is None:
        sys.exit(f"could not read {c['model']}")
    site = design_site_polygon()  #RD New
    ground = DESIGN_SITE["ground_nap_m"]  #-0.93 m NAP
    feats, n_by_class = [], {}
    for obj in model.Objects:
        layer = model.Layers[obj.Attributes.LayerIndex].FullPath
        if not layer.startswith(c["layer_prefix"] + "::") or "building" not in layer.lower():
            continue  #only the building sublayers of this option
        geom = obj.Geometry
        if not isinstance(geom, (rhino3dm.Brep, rhino3dm.Extrusion)):
            continue  #construction curves on the building layers
        bb = geom.GetBoundingBox()  #only used to say where a dropped block was
        fp, base, parts, slope = roof_parts(geom)
        sub = layer.split("::")[-1]  #e.g. "Tall buildings"
        if fp is None or not fp.intersects(site):
            print(f"  dropped  {sub:28} at x {bb.Min.X / MM:.0f}, y {bb.Min.Y / MM:.0f}: not on the design site")
            continue
        cls = sub.split()[0].lower()  #tall / medium / short
        n_by_class[cls] = n_by_class.get(cls, 0) + 1
        name = f"{c['scenario']} {cls} {n_by_class[cls]}"  #e.g. "scenario_a tall 1"
        cut = fp.area - fp.intersection(site).area  #m2 lost at the site edge
        print(f"  {name:22} {fp.intersection(site).area:7.0f} m2  roofs "
              + ", ".join(f"{z - base:.1f} m" for _, z in parts)
              + (f"  clipped {cut:.0f} m2 at site edge" if cut > 0.5 else "")
              + (f"  {slope:.0f} m2 sloping roof skipped" if slope > 0.5 else ""))
        for k, (poly, z) in enumerate(parts):  #one flat extrusion per roof level
            clipped = poly.intersection(site)  #keep only the part inside the site
            if clipped.area < MIN_AREA_M2:
                continue
            height = z - base  #modelled height of this part
            wgs = transform(lambda x, y, z=None: to_wgs(x, y), clipped)  #RD -> lon/lat
            wgs = transform(lambda x, y, z=None: (round(x, 7), round(y, 7)), wgs)  #~1 cm precision
            feats.append({
                "type": "Feature",
                "geometry": mapping(wgs),
                "properties": {
                    "scenario": c["scenario"],
                    "name": name if len(parts) == 1 else f"{name} part {k + 1}",  #stepped blocks get parts
                    "use": "residential",  #assumed, the model has no use
                    "height_class": cls,  #from the Rhino layer name
                    "height_m": round(ground + height, 2),  #roof in m NAP, block stood on the site ground
                    "building_height_m": round(height, 2),  #as modelled, for the info box
                    "footprint_m2": round(clipped.area, 1),
                    "rhino_layer": layer,
                },
            })
    return feats


def import_streets(c):
    #flat road surfaces of one layer tree -> one merged, site-clipped MultiPolygon feature
    model = rhino3dm.File3dm.Read(str(c["model"]))
    site = design_site_polygon()
    surfaces = []
    for obj in model.Objects:
        layer = model.Layers[obj.Attributes.LayerIndex].FullPath
        if not layer.startswith(c["layer_prefix"] + "::") or "roads" not in layer.lower():
            continue  #only the road sublayer of this option
        if isinstance(obj.Geometry, rhino3dm.Brep):  #surfaces only, the curves are outlines
            fp, _, _, _ = roof_parts(obj.Geometry)  #a flat surface projects to itself
            if fp is not None:
                surfaces.append(fp)
    if not surfaces:
        return []
    merged = unary_union(surfaces)  #duplicates and overlaps counted once
    streets = merged.intersection(site)  #nothing outside the design site
    print(f"  streets: {len(surfaces)} surfaces, {merged.area:.0f} m2 merged, "
          f"{merged.area - streets.area:.0f} m2 clipped at site edge")
    wgs = transform(lambda x, y, z=None: to_wgs(x, y), streets)  #RD -> lon/lat
    wgs = transform(lambda x, y, z=None: (round(x, 7), round(y, 7)), wgs)  #~1 cm precision
    return [{
        "type": "Feature",
        "geometry": mapping(wgs),
        "properties": {
            "scenario": c["scenario"],
            "name": f"{c['scenario']} new streets",
            "kind": "street",
            "area_m2": round(streets.area),
        },
    }]


def demolished(c, feats, footprints):
    #BAG pand ids this scenario removes, by the case's rule
    site = design_site_polygon()
    on_site = [(pid, g) for pid, g in footprints if g.representative_point().within(site)]  #outline crosses no building
    if c["demolish"] == "site":
        ids = [pid for pid, _ in on_site]
    else:
        new = unary_union([transform(lambda x, y, z=None: to_rd(x, y), shape(f["geometry"])) for f in feats])  #massing back to RD
        ids = [pid for pid, g in on_site if g.intersection(new).area > 1.0]  #overlapped by more than 1 m2
    print(f"  demolishes {len(ids)} of {len(on_site)} 3DBAG buildings on the site (rule '{c['demolish']}')")
    return sorted(ids)


def main():
    if not MODEL.exists():
        sys.exit(f"missing {MODEL}\nCopy it from Modelling.zip on the shared drive (see the docstring).")
    features, demolishes, streets = [], {}, []
    footprints = site_footprints()  #existing buildings, for the demolition lists
    for c in CASES:  #one Rhino layer tree per scenario
        print(f"{c['scenario']} <- {c['layer_prefix']} ({c['model'].name})")
        feats = import_option(c)
        features += feats
        demolishes[c["scenario"]] = demolished(c, feats, footprints)  #ids the app hides with this massing
        streets += import_streets(c)  #new street surfaces of the same option
    write_processed("design_massing.geojson", {
        "type": "FeatureCollection",
        "_written_by": "analysis/scenarios/import_rhino.py",
        "_source": f"{MODEL.name}, layers {', '.join(c['layer_prefix'] for c in CASES)}",
        "_note": "Polygons in EPSG:4326. height_m is the ROOF in m above NAP; base_height_m is "
                 "omitted so the app stands each block on the site ground "
                 f"({DESIGN_SITE['ground_nap_m']} m NAP). One flat extrusion per roof level of each Rhino solid.",
        "_demolishes_note": "BAG pand ids (3DBAG 'identificatie') removed by each scenario; "
                            "rule per scenario in import_rhino.py CASES.",
        "demolishes": demolishes,
        "features": features,
    }, indent=1)
    write_processed("design_streets.geojson", {
        "type": "FeatureCollection",
        "_written_by": "analysis/scenarios/import_rhino.py",
        "_source": f"{MODEL.name}, 'New ROADS' sublayers",
        "_note": "Polygons in EPSG:4326, one per scenario, draped on the ground by the app.",
        "features": streets,
    }, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
