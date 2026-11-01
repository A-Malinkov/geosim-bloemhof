#!/usr/bin/env python3
"""
import_rhino.py - proposed massing from the team's Rhino model into the app.

USAGE
-----
    python analysis/scenarios/import_rhino.py

Reads the building solids of one Rhino layer tree per scenario and writes them
as extrudable footprints to data/processed/design_massing.geojson, and the flat
road surfaces of the same tree to data/processed/design_streets.geojson. Both
are drawn by app/modules/scenarios.js. Proposed planting goes to
data/processed/design_planting.geojson, drawn by app/modules/vegetation.js.

INPUT
-----
The Rhino model is ~105 MB and stays out of git (data/raw/*.3dm). Get it from
the shared drive (30.10 came as a OneDrive zip):
    Group Project Q1 - Proposal Modelling_30.10.26.3dm  ->  data/raw/
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
* OPTION 2's freeform blocks. One is drawn as an open roof surface plus a
  separate wall: the roof is stood on the model ground and the wall, which has
  no plan area, is skipped. One has a roof that slopes everywhere: it becomes a
  single flat block at the area-weighted mean roof height (same volume), and
  the importer prints the peak it loses.

WHAT EACH SCENARIO DEMOLISHES
-----------------------------
The output also lists, per scenario, the 3DBAG buildings the design removes
(`demolishes` in design_massing.geojson, BAG pand ids). The app hides those
when the massing is shown; noise.py and height_width.py are meant to drop them
too. Rule per case:
  "site"     every 3DBAG building on the design site. OPTION 1 lays a new
             street grid over the whole site, so keeping only the buildings it
             does not overlap would leave old rows standing in new courtyards.
             OPTION 2 is cleared the same way: its blocks, roads and green
             cover 55 % of the site and overlap 1,008 of its 1,156 buildings.
             Both keep the same KEEP_RD block (school, community buildings).
  "overlap"  only buildings a new block overlaps by more than 1 m2.
A case can also name a "keep_rd" ring: part of the site the scenario leaves
standing (no demolition, old streets kept). It is written to the output as
`keep_rd` so scenario_world.py cuts streets only in the cleared part.
Footprints come from the 3DBAG API (cached in cache/scenarios/, gitignored).

WHAT IT CANNOT TELL YOU
-----------------------
* Heights come from the roof faces, not the bounding box: rhino3dm's Brep
  boxes are loose (a flat 12 m block reported 13.2 m). Each horizontal roof
  level becomes its own flat extrusion from the ground, so a stepped block
  becomes stepped parts. Sloping roofs are not modelled; the importer reports
  any sloping area it skipped, or averages a roof that is all slope (above).
* The Rhino layers say tall / medium / short, not a use. use is set to
  "residential" because that is the brief, not because the model says so.
  The exception is the Final Model, which places named Rhino blocks: "Shops"
  (a 4 m podium, with a "flats over shops" block stood on it via
  base_height_m), "Terraced House (4 storey) WITH SHOPS" (one 12 m solid,
  residential on every floor despite its name, Atanas 2026-10-30) and plain houses.
  In 30.10, 18 of those are split into a 4 m "ground Floor shops" block with
  an 8 m "(3 storey) above shops" block on it, and many houses are renamed
  copies ("Terraced House (4 storey) 12", "... copy copy"): block_use() strips
  the copy suffix before looking the name up. BLOCK_USE maps block names to
  uses, NAME_USE the two named solids (Elderly Home, Student accom building).
* OPTION 1's 18 boxes are Extrusions saved without render meshes in 25.10 and
  27.10. They are read from their profile and path instead (exact), which
  moves their footprints by at most 2 m2 against the meshed 23.10 import.
* Trees: data/processed/trees_<scenario>.geojson is the existing tree register
  minus the trees standing in a new block, on a new street or in new water.
  Proposed planting goes to its own file, see below.
* Streets are the flat surfaces on the "New ROADS" sublayer, merged (several
  are drawn twice) and clipped to the site. The Final Model's "One- Way Roads"
  count as street too. Its pedestrian paths, bike paths and parking become
  kind "pedestrian", "bike", "parking" (CASES surface_layers): drawn by the
  app, not traced or walked by any analysis yet. The road outline curves on that
  layer are not used. Fences are not imported.
* Planting comes from each option's "Proposed Vegetation" sublayer and goes
  to data/processed/design_planting.geojson, drawn by
  app/modules/vegetation.js. It is kept apart from the massing, so no
  analysis (SVF, sun hours, H/W) sees the proposed trees: the team's choice.
  Tree and bush blocks become points with a height and crown size measured
  from the block's mesh after its instance transform; the flat surfaces
  become green patches. The one surface on the top-level "Water feature?"
  layer is the pond of both options, cut out of their green. Closed solids
  on the layer (OPTION 2's 86 bushes) become shrub points, not green. Species are not
  modelled and the blocks are generic shapes, so the sizes are what was
  drawn, not a planting plan.
"""
from __future__ import annotations

import pathlib
import re  #copy suffixes on Rhino block names
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import RAW, DESIGN_SITE, design_site_polygon, to_rd, to_wgs, write_processed  # noqa: E402

import rhino3dm  #reads .3dm without Rhino installed
from shapely.geometry import Point, Polygon, mapping  #footprint geometry, planting points
from shapely.ops import unary_union, transform  #merge triangles, reproject
from shapely.geometry import shape  #massing back from GeoJSON for the overlap rule
from scenario_world import site_footprints  #3DBAG footprints over the site, shared with the analyses
import json  #tree register
from common.project import PROCESSED  #where trees.geojson lives

MODEL = RAW / "Group Project Q1 - Proposal Modelling_30.10.26.3dm"  #newest version: both options plus the Final Model
#the first 22.10 copy on the shared drive had OPTION 1's short buildings as mesh-less block instances (5 volumes
#instead of 22); 23.10 is solids again and gives OPTION 1 the same 22 volumes as 16.10
#27.10 adds the "Final Model" layer tree, built from named Rhino blocks (houses, shops), see BLOCK_USE
#30.10 changes only the Final Model: split shop terraces, renamed house copies, more paths, walkway merged into green
PLANTING_MODEL = MODEL

#one dict per scenario: which Rhino layer tree becomes which app scenario
#the block added to the site on 2026-10-21 (school, halls, workshops); OPTION 1 places nothing there, so it stays
KEEP_RD = [(94158.0, 433881.0), (94045.0, 433883.0), (94017.8, 433885.5), (94068.9, 433931.5),
           (94123.9, 433976.9), (94136.6, 433976.9), (94168.8, 433939.6)]

CASES = [
    {"scenario": "scenario_a", "layer_prefix": "OPTION 1", "model": MODEL, "demolish": "site",
     "keep_rd": KEEP_RD,  #new grid over the whole site except the 2026-10-21 block
     "planting_model": PLANTING_MODEL,  #"Proposed Vegetation" sublayer, see import_planting()
     #paths the team adds that are not in the Rhino model, RD polylines: the green round the kept school
     #lost its only path to the pond and a block corner, so one runs along its north edge, main street to
     #Dubbelstraat, 4.6 m or more clear of the school, pond, blocks and trees (team decision 2026-10-23)
     "paths_rd": [[(94041.0, 433960.5), (94100.0, 433960.5), (94150.0, 433959.0), (94163.0, 433950.0)]],
     "water_layer": "Water feature?"},  #top-level layer shared by both options, in OPTION 1's central green
    #OPTION 2 is a whole-site redesign: its blocks, roads and green cover 55 % of the site and overlap 1,008 of
    #its 1,156 buildings, so the site is cleared; the team keeps the same 2026-10-21 block as scenario_a
    #(school, community buildings, workshops): no OPTION 2 block or street touches its buildings
    {"scenario": "scenario_b", "layer_prefix": "OPTION 2", "model": MODEL, "demolish": "site",
     "keep_rd": KEEP_RD,  #same kept block as scenario_a, team decision 2026-10-23
     "planting_model": PLANTING_MODEL,  #"Proposed Vegetation - Copy" sublayer
     "water_layer": "Water feature?"},  #the shared pond: wholly in OPTION 2's green too, 12 m clear of its blocks
    #the Final Model (27.10): houses and shops placed as Rhino block instances, most of them on its vegetation
    #layer; it paves and plants inside the kept block's ring but builds on none of its buildings, so it keeps
    #the same block; its own green has a hole the shape of the shared pond
    {"scenario": "final", "layer_prefix": "Final Model", "model": MODEL, "demolish": "site",
     "keep_rd": KEEP_RD,  #same kept block as scenario_a and scenario_b
     "planting_model": PLANTING_MODEL,  #"Proposed Vegetation - Copy - Copy" sublayer, plus the house gardens
     "surface_layers": {"Pedestrian Paths": "pedestrian", "Bike Paths": "bike", "Parking Spaces": "parking"},  #own kinds, drawn not walked
     #uses the model does not name, by an RD point inside the solid: the large south-west building is the
     #shopping centre, and so is the 12 m building joined to its north side (Atanas, 2026-10-28)
     "use_at_rd": [((93749.0, 433853.0), "shopping centre"), ((93719.0, 433865.0), "shopping centre")],
     #the curvy strip on the vegetation layer (6,362 m2, ~9.5 m wide) is a walking path (Atanas, 2026-10-28):
     #drawn as kind "walkway", its centreline walked like a hand-drawn path; 30.10 merges it into one surface
     #with the green beside it, so its 27.10 outline is kept in a file (RD) and cut out of that green; it still
     #counts as green area (Atanas, 2026-10-30), see compare_scenarios.py and score_scenarios.py
     "walkway_rd": RAW / "walkway_final_rd.geojson",
     "water_layer": "Water feature?"},
]

#Rhino block name -> use of its building solids; the model has no use field, but the Final Model's blocks are named
BLOCK_USE = {
    "Shops": "shop",  #4 m ground-floor podium, a "flats over shops" block stands on each one
    "flats over shops (4 stories)": "residential",  #flats on top of the shop podium, 4 to 16 m
    "Flats above shops (4 floors)": "residential",  #defined in the model, never placed
    "Terraced House (4 storey) WITH SHOPS": "residential",  #one 12 m solid; homes on every floor despite the name (Atanas, 2026-10-30)
    "Terraced House (4 storey) ground Floor shops": "shop",  #30.10: 4 m ground floor of a split shop terrace
    "Terraced House (3 storey) above shops": "residential",  #30.10: 8 m of flats stood on that ground floor
    "Terraced House (4 storey)": "residential",
    "Semi-Detached House": "residential",
    "Detached House": "residential",
    "A house": "residential",
}


def block_use(name):
    #Rhino block name -> its BLOCK_USE name, or None; 30.10 copies blocks as "<name> 12", "<name>16", "<name> copy copy"
    if name in BLOCK_USE:
        return name
    base = re.sub(r"( copy)*( ?\d+)?$", "", name)  #strip the copy suffix Rhino adds
    return base if base in BLOCK_USE else None


#object name -> use, for the solids the Final Model draws directly and names
NAME_USE = {"Elderly Home": "elderly housing", "Student accom building": "student housing"}

MM = 1000.0  #Rhino units are millimetres
MIN_AREA_M2 = 1.0  #ignore slivers left over after clipping


def meshes(geom, xform=None):
    #cached render meshes of a Brep or Extrusion, the only geometry rhino3dm can triangulate
    #xform: a block instance's transform, applied to copies of the meshes (the definition sits at the origin)
    if xform is not None:
        out = []
        for m in meshes(geom):
            m = m.Duplicate()  #leave the definition's own mesh untouched
            m.Transform(xform)
            out.append(m)
        return out
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


def roof_parts(geom, xform=None):
    #-> (whole footprint, base z, [(roof footprint, roof z)], sloping m2), all in metres, RD New
    #xform: block instance transform, for a solid that is part of a block definition
    tris, flat, slope = [], {}, 0.0
    allz = []
    sloped = []  #(triangle, mean z) of sloping faces, for a block whose whole roof slopes
    for m in meshes(geom, xform):
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
                    sloped.append((p, sum(zs) / 3))
    if not tris and isinstance(geom, rhino3dm.Extrusion):
        #an extrusion saved without a render mesh (OPTION 1's 18 boxes in 25.10 and 27.10): read it exactly from
        #its profile and path, which is a vertical box when the path does not move in plan
        a, b = geom.PathStart, geom.PathEnd
        pl = geom.Profile3d(0, 0.0).TryGetPolyline()
        if pl is not None and len(pl) >= 4 and abs(a.X - b.X) < 1 and abs(a.Y - b.Y) < 1:
            pts = []
            for i in range(len(pl)):
                q = rhino3dm.Point3d(pl[i].X, pl[i].Y, pl[i].Z)
                if xform is not None:
                    q.Transform(xform)  #block instance
                pts.append((q.X / MM, q.Y / MM))
            poly = clean([Polygon(pts)])
            z0, z1 = sorted((a.Z / MM, b.Z / MM))  #underside and roof
            return poly, z0, [(poly, z1)], 0.0
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
    if not parts and len(flat) == 1 and not sloped and base > 0.5:
        #a lone flat surface off the ground (OPTION 2 "tall 1" is an open roof plus a separate wall):
        #a roof standing on the model ground, z = 0 = NAP 0, like every closed block
        z = next(iter(flat))
        parts, base = [(clean(flat[z]), z)], 0.0
    elif not parts and sloped:
        #the whole roof slopes (OPTION 2 "medium 2"): one flat block at the area-weighted mean roof height,
        #which keeps its volume; the peak is lost, the caller reports it
        area = sum(t.area for t, _ in sloped)
        z = sum(t.area * zz for t, zz in sloped) / area
        parts, slope = [(clean([t for t, _ in sloped]), z)], 0.0
    return clean(tris), base, parts, slope


def import_option(c):
    #building solids of one layer tree -> list of GeoJSON features
    model = rhino3dm.File3dm.Read(str(c["model"]))
    if model is None:
        sys.exit(f"could not read {c['model']}")
    site = design_site_polygon()  #RD New
    ground = DESIGN_SITE["ground_nap_m"]  #-0.93 m NAP
    feats, n_by_class, n_block = [], {}, {}
    members = {str(i) for d in model.InstanceDefinitions for i in d.GetObjectIds()}  #solids that belong to a block definition
    solids = []  #(layer, geometry, instance transform or None, Rhino block name or None, use)
    placed, n_dup = set(), 0  #block placements seen; 30.10 places 3 "above shops" blocks twice on the same spot
    for obj in model.Objects:
        layer = model.Layers[obj.Attributes.LayerIndex].FullPath
        if not layer.startswith(c["layer_prefix"] + "::"):
            continue  #only this option's layer tree
        geom = obj.Geometry
        if isinstance(geom, rhino3dm.InstanceReference):
            #a placed block (Final Model): its building solids, wherever the instance itself sits in the layers
            d = model.InstanceDefinitions.FindId(geom.ParentIdefId)
            base = block_use(d.Name) if d is not None else None  #a copied block counts as its original
            if base is None:
                continue  #trees and bushes, read by import_planting()
            x = geom.Xform
            at = (base, *(round(v, 3) for v in (x.M00, x.M01, x.M10, x.M11)), *(round(v) for v in (x.M03, x.M13, x.M23)))  #rotation and mm position
            if at in placed:
                n_dup += 1
                continue  #the same block placed twice at the same spot: one building, not two
            placed.add(at)
            for i in d.GetObjectIds():
                m = model.Objects.FindId(i)
                if m and "building" in model.Layers[m.Attributes.LayerIndex].FullPath.lower() \
                        and isinstance(m.Geometry, (rhino3dm.Brep, rhino3dm.Extrusion)):
                    solids.append((model.Layers[m.Attributes.LayerIndex].FullPath, m.Geometry, geom.Xform, d.Name, BLOCK_USE[base]))
            continue
        if "building" not in layer.lower() or str(obj.Attributes.Id) in members:
            continue  #only the building sublayers, and not the block definitions' own solids at the origin
        if not isinstance(geom, (rhino3dm.Brep, rhino3dm.Extrusion)):
            continue  #construction curves on the building layers
        solids.append((layer, geom, None, None, NAME_USE.get(obj.Attributes.Name, "residential")))
    for layer, geom, xform, block, use in solids:
        bb = geom.GetBoundingBox()  #only used to say where a dropped block was
        fp, base, parts, slope = roof_parts(geom, xform)
        sub = layer.split("::")[-1]  #e.g. "Tall buildings"
        if fp is None:
            print(f"  skipped  {sub:28} at x {bb.Min.X / MM:.0f}, y {bb.Min.Y / MM:.0f}: no plan area (a wall, or a stray at the origin)")
            continue  #OPTION 2 draws one block as an open roof plus a wall; the roof carries it
        if not fp.intersects(site):
            print(f"  dropped  {sub:28} at x {bb.Min.X / MM:.0f}, y {bb.Min.Y / MM:.0f}: not on the design site")
            continue
        cls = sub.split()[0].lower()  #tall / medium / short
        peak = max((p.Z / MM for m in meshes(geom, xform) for p in m.Vertices),
                   default=max((z for _, z in parts), default=base))  #true top from the mesh; the bounding box is loose; a mesh-less box: its roof
        if block:  #a placed block: named after it, one summary line per block name below
            key = block_use(block).lower().replace(" (4 storey)", "").replace(" (3 storey)", "").replace(" (4 stories)", "")  #e.g. "terraced house", copies counted with their original
            key = key.replace(" with shops", "")  #the WITH SHOPS terrace is all homes, so it is named and counted as a terraced house
            n_by_class[key] = n_by_class.get(key, 0) + 1
            name = f"{c['scenario']} {key} {n_by_class[key]}"
        else:
            n_by_class[cls] = n_by_class.get(cls, 0) + 1
            name = f"{c['scenario']} {cls} {n_by_class[cls]}"  #e.g. "scenario_a tall 1"
        raised = block is not None and base > 0.5  #a block standing on another (flats on the shop podium)
        use = next((u for pt, u in c.get("use_at_rd", []) if fp.contains(Point(pt))), use)  #a use set by location
        cut = fp.area - fp.intersection(site).area  #m2 lost at the site edge
        if block:
            b = block_use(block)  #copies summed under their original name
            n_block.setdefault(b, [0, 0.0, set()])
            n_block[b][0] += 1; n_block[b][1] += fp.intersection(site).area
            n_block[b][2].update(f"{z - (0 if raised else base):.1f} m" for _, z in parts)  #roof above the ground
        else:
            print(f"  {name:22} {fp.intersection(site).area:7.0f} m2  {use:16} roofs "
                + ", ".join(f"{z - base:.1f} m" for _, z in parts)
                + (f"  clipped {cut:.0f} m2 at site edge" if cut > 0.5 else "")
                + (f"  {slope:.0f} m2 sloping roof skipped" if slope > 0.5 else "")
                + (f"  peak {peak - base:.1f} m, roof averaged" if parts and peak > max(z for _, z in parts) + 1 else ""))  #all-sloping roof
        for k, (poly, z) in enumerate(parts):  #one flat extrusion per roof level
            clipped = poly.intersection(site)  #keep only the part inside the site
            if clipped.area < MIN_AREA_M2:
                continue
            height = z - base  #modelled height of this part
            wgs = transform(lambda x, y, z=None: to_wgs(x, y), clipped)  #RD -> lon/lat
            wgs = transform(lambda x, y, z=None: (round(x, 7), round(y, 7)), wgs)  #~1 cm precision
            props = {
                "scenario": c["scenario"],
                "name": name if len(parts) == 1 else f"{name} part {k + 1}",  #stepped blocks get parts
                "use": use,  #residential unless a block or object name says otherwise (BLOCK_USE, NAME_USE)
                "height_class": cls,  #from the Rhino layer name
                "height_m": round(ground + (z if raised else height), 2),  #roof in m NAP, block stood on the site ground
                "building_height_m": round(height, 2),  #as modelled, for the info box
                "footprint_m2": round(clipped.area, 1),
                "rhino_layer": layer,
            }
            if block:
                props["rhino_block"] = block  #the Rhino block the solid comes from
            if raised:
                props["base_height_m"] = round(ground + base, 2)  #underside in m NAP: stands on the podium below
            feats.append({"type": "Feature", "geometry": mapping(wgs), "properties": props})
    if n_dup:
        print(f"  {n_dup} block placements dropped: a second copy of the same block at the same spot")
    for block, (n, a, roofs) in sorted(n_block.items()):  #one line per placed block name
        print(f"  {n:4} x {block:38} {a:7.0f} m2  roofs {', '.join(sorted(roofs))}  use {BLOCK_USE[block]}")
    return feats


def import_streets(c):
    #flat road surfaces of one layer tree -> one merged, site-clipped MultiPolygon feature
    #plus, for a case with surface_layers, one feature per other paved kind (pedestrian, bike, parking)
    model = rhino3dm.File3dm.Read(str(c["model"]))
    site = design_site_polygon()
    kinds = c.get("surface_layers", {})  #sublayer name -> kind
    surfaces = {}  #kind -> flat surfaces
    for obj in model.Objects:
        layer = model.Layers[obj.Attributes.LayerIndex].FullPath
        if not layer.startswith(c["layer_prefix"] + "::"):
            continue  #only this option's layer tree
        sub = layer.split("::")[-1]
        kind = "street" if "roads" in sub.lower() else kinds.get(sub)  #the road sublayers, or a named paved one
        if kind and isinstance(obj.Geometry, rhino3dm.Brep):  #surfaces only, the curves are outlines
            fp, _, _, _ = roof_parts(obj.Geometry)  #a flat surface projects to itself
            if fp is not None:
                surfaces.setdefault(kind, []).append(fp)
    if c.get("walkway_rd"):
        surfaces["walkway"] = [walkway(c)]  #the walking path drawn on the green, outline from its file
    out, taken = [], None  #taken: area already drawn by an earlier kind, so no two drapes overlap
    for kind in ["street", "walkway", "pedestrian", "bike", "parking"]:  #the street surface stays whole, it is traced for centrelines
        if kind not in surfaces:
            continue
        merged = unary_union(surfaces[kind])  #duplicates and overlaps counted once
        part = merged.intersection(site)  #nothing outside the design site
        if taken is not None:
            part = part.difference(taken)
        taken = part if taken is None else taken.union(part)
        print(f"  {kind}: {len(surfaces[kind])} surfaces, {merged.area:.0f} m2 merged, "
              f"{merged.area - part.area:.0f} m2 clipped at site edge or under another kind")
        out.append(_to_wgs_feature(part, {
            "scenario": c["scenario"],
            "name": f"{c['scenario']} new streets" if kind == "street" else f"{c['scenario']} {kind}",
            "kind": kind,
            "area_m2": round(part.area),
        }))
    return out


LINK_TOL_M = 35.0  #street ends this close to an edge street get a link surface; road_network.py's snap_tol_m


def street_links(c, surface_rd, blocks_rd):
    #link surfaces where the Rhino street surface stops short of an edge street -> GeoJSON feature or []
    #at a free street end, or a sharp corner (two streets meeting at < 150 deg), within LINK_TOL_M of the edge
    #street; as wide as the street a few metres back, never through a new block. B's south corner stopped
    #14 m short of Strevelsweg and was not joined to it on the map or in the walk network (2026-10-23)
    import math
    import geopandas as gpd
    import shapely
    from shapely.geometry import LineString
    from shapely.ops import nearest_points
    from scenario_world import EDGE_BAND_M, EDGE_STREETS, centrelines
    site = design_site_polygon()
    roads = gpd.read_file(RAW / "osm_roads.geojson").to_crs(28992)
    edge = unary_union(roads[roads["name"].astype(str).str.contains("|".join(EDGE_STREETS))].geometry.values)
    edge = edge.difference(site.buffer(-EDGE_BAND_M))  #the edge streets round the site, not Dubbelstraat's stretch through it
    blocks = unary_union(blocks_rd).buffer(-0.5) if blocks_rd else None  #the option's new blocks, RD

    def heading(g, k):
        #direction away from end k over its first 5 m
        a = g.coords[k]
        b = g.interpolate(min(5.0, g.length) if k == 0 else max(g.length - 5.0, 0.0)).coords[0]
        return math.atan2(b[1] - a[1], b[0] - a[0])

    links, axes = [], []
    for part in getattr(surface_rd, "geoms", [surface_rd]):
        lines = centrelines(part)
        for i, g in enumerate(lines):
            for k in (0, -1):
                p = Point(g.coords[k])
                if any(j != i and lines[j].distance(p) < 0.5 and all(Point(lines[j].coords[kk]).distance(p) >= 0.5 for kk in (0, -1))
                       for j in range(len(lines))):
                    continue  #ends on another street's middle: a junction
                meet = [(j, kk) for j, h in enumerate(lines) for kk in (0, -1)
                        if (j, kk) != (i, k) and Point(h.coords[kk]).distance(p) < 0.5]
                if len(meet) > 1:
                    continue  #three or more streets: a junction
                if meet:  #two streets meeting: a corner only if they turn sharply
                    j, kk = meet[0]
                    turn = abs((math.degrees(heading(g, k) - heading(lines[j], kk)) + 180) % 360 - 180)
                    if turn > 150:
                        continue  #nearly straight: one street running on
                d = p.distance(edge)
                if not 1.0 < d <= LINK_TOL_M:
                    continue  #touching already, or too far
                seg = LineString([p, nearest_points(p, edge)[1]])
                if blocks is not None and seg.intersects(blocks):
                    continue  #would run through a new block
                back = g.interpolate(min(4.0, g.length / 2) if k == 0 else max(g.length - 4.0, g.length / 2))
                half = max(2.0, part.exterior.distance(back))  #half the street width a few metres back
                link = seg.buffer(half, cap_style="flat").difference(part).intersection(site)
                if link.area > 2.0:
                    links.append(link)
                    axes.append(seg)  #the walking line along the link, street end to edge street
    if not links:
        return []
    merged = unary_union(links)
    print(f"  street links: {len(links)} ends joined to the edge streets, {merged.area:.0f} m2")
    axes_wgs = [[[round(v, 7) for v in to_wgs(x, y)] for x, y in a.coords] for a in axes]  #lon/lat, for road_network.py
    return [_to_wgs_feature(merged, {"scenario": c["scenario"], "name": f"{c['scenario']} street links",
                                     "kind": "link", "area_m2": round(merged.area), "axes": axes_wgs})]


def design_paths(c, kept_rd=None):
    #a case's hand-drawn paths (paths_rd) -> GeoJSON lines, kind "path", drawn and walked like the streets
    #plus the centreline of its walkway (walkway_rd), cut out of the buildings it keeps (kept_rd)
    from shapely.geometry import LineString
    out = []
    if c.get("walkway_rd"):
        from scenario_world import centrelines
        for fp in [walkway(c).intersection(design_site_polygon())]:  #one walkway; the loop keeps the old layout
            lines = [g for part in getattr(fp, "geoms", [fp]) for g in centrelines(part, prune_m=15.0)]  #~1.5 widths: no fan of spurs where it widens
            if kept_rd is not None:
                lines = [p for g in lines for p in getattr(g.difference(kept_rd), "geoms", [g.difference(kept_rd)])
                         if not p.is_empty]  #no walking through a kept building
            for k, g in enumerate(lines, 1):
                out.append(_to_wgs_feature(g, {
                    "scenario": c["scenario"],
                    "name": f"{c['scenario']} walkway path {k}",
                    "kind": "path",
                    "length_m": round(g.length, 1),
                    "source": "centreline of the walkway surface (import_rhino.py CASES walkway_rd)",
                }))
            print(f"  walkway: {len(lines)} centreline pieces, {sum(g.length for g in lines):.0f} m, walked as paths")
    for k, pts in enumerate(c.get("paths_rd", []), 1):
        g = LineString(pts)
        out.append(_to_wgs_feature(g, {
            "scenario": c["scenario"],
            "name": f"{c['scenario']} path {k}",
            "kind": "path",
            "length_m": round(g.length, 1),
            "source": "added by the team, not in the Rhino model (import_rhino.py CASES paths_rd)",
        }))
    drawn = [f for f in out if f["properties"]["source"].startswith("added by the team")]  #paths_rd only
    if drawn:
        print(f"  paths: {len(drawn)} added by hand, {sum(f['properties']['length_m'] for f in drawn):.0f} m")
    return out


def walkway(c):
    #a case's walkway outline (RD polygon) from its walkway_rd file
    d = json.loads(pathlib.Path(c["walkway_rd"]).read_text())
    return unary_union([shape(f["geometry"]) for f in d["features"]])


def _to_wgs_feature(geom_rd, props):
    #RD geometry -> GeoJSON feature in lon/lat, ~1 cm precision
    wgs = transform(lambda x, y, z=None: to_wgs(x, y), geom_rd)
    wgs = transform(lambda x, y, z=None: (round(x, 7), round(y, 7)), wgs)
    return {"type": "Feature", "geometry": mapping(wgs), "properties": props}


def import_planting(c, streets_rd=None, kept_rd=None):
    #"Proposed Vegetation" sublayer -> tree and shrub points plus green surfaces, all on the design site
    #streets_rd: this option's new streets (RD); green drawn under them is cut away, as under the water
    #kept_rd: footprints of the existing buildings the scenario keeps (RD); green and plants inside them are dropped
    model = rhino3dm.File3dm.Read(str(c["planting_model"]))
    if model is None:
        sys.exit(f"could not read {c['planting_model']}")
    site = design_site_polygon()
    ground = DESIGN_SITE["ground_nap_m"]  #planting stands on the site ground, like the blocks
    #mesh vertices of each block definition (mm), one list per solid: trees are a crown and a trunk
    defs = {}
    for d in model.InstanceDefinitions:
        parts = []
        for i in d.GetObjectIds():
            o = model.Objects.FindId(i)
            V = [p for m in meshes(o.Geometry) for p in m.Vertices] if o else []
            if V:
                parts.append(V)
        defs[str(d.Id)] = (d.Name, parts)
    feats, n_off, n_kind, green, water = [], 0, {}, [], []
    for obj in model.Objects:
        layer = model.Layers[obj.Attributes.LayerIndex].FullPath
        geom = obj.Geometry
        if layer == c.get("water_layer") and isinstance(geom, rhino3dm.Brep):
            fp, _, _, _ = roof_parts(geom)  #flat surface, projects to itself
            if fp is not None and fp.intersects(site):
                water.append(fp.intersection(site))
            continue
        if not layer.startswith(c["layer_prefix"] + "::Proposed Vegetation"):
            continue  #only this option's planting; OPTION 2's layer is "Proposed Vegetation - Copy"
        if isinstance(geom, rhino3dm.InstanceReference):
            name, parts = defs.get(str(geom.ParentIdefId), ("?", []))
            if block_use(name):  #copied house blocks too
                #a house or shop block (Final Model): its garden, the flat surface on the vegetation layer, is green
                d = model.InstanceDefinitions.FindId(geom.ParentIdefId)
                for i in d.GetObjectIds():
                    m = model.Objects.FindId(i)
                    if m and isinstance(m.Geometry, rhino3dm.Brep) and "Vegetation" in model.Layers[m.Attributes.LayerIndex].FullPath:
                        fp, _, _, _ = roof_parts(m.Geometry, geom.Xform)  #placed by the instance transform
                        if fp is not None and fp.intersects(site):
                            green.append(fp.intersection(site))
                            n_kind["garden of " + block_use(name)] = n_kind.get("garden of " + block_use(name), 0) + 1  #copies under their original
                continue  #its building solids are read by import_option()
            if not parts:
                continue  #block with no render mesh, nothing to measure
            #every vertex placed by the instance transform (rotation and non-uniform scale included), mm -> m
            placed = []
            for V in parts:
                pts = []
                for p in V:
                    q = rhino3dm.Point3d(p.X, p.Y, p.Z)
                    q.Transform(geom.Xform)
                    pts.append((q.X / MM, q.Y / MM, q.Z / MM))
                placed.append(pts)
            allp = [p for pts in placed for p in pts]
            z0 = min(p[2] for p in allp)  #foot of the trunk or bush
            crown = max(placed, key=lambda pts: max(p[2] for p in pts))  #the solid reaching highest
            cx = [p[0] for p in crown]; cy = [p[1] for p in crown]
            x, y = geom.Xform.M03 / MM, geom.Xform.M13 / MM  #insertion point = trunk position
            kind = "tree" if name.lower().startswith("tree") else "shrub"  #Tree Basic 1-3 / Bushes, Bushes 2
            if not site.contains(Point(x, y)):
                n_off += 1
                continue  #planted outside the design site
            if kept_rd is not None and kept_rd.contains(Point(x, y)):
                n_kind["in a kept building, dropped"] = n_kind.get("in a kept building, dropped", 0) + 1
                continue  #OPTION 2 plants over the block it keeps
            n_kind[name] = n_kind.get(name, 0) + 1
            height = max(p[2] for p in allp) - z0  #modelled height, stood on the site ground below
            props = {
                "scenario": c["scenario"],
                "kind": kind,
                "block": name,  #Rhino block name
                "height_m": round(height, 1),  #above ground, the convention trees.geojson uses
                "crown_m": round(((max(cx) - min(cx)) + (max(cy) - min(cy))) / 2, 1),  #mean of the two plan extents
                "trunk_height_m": round(min(p[2] for p in crown) - z0, 1) if len(placed) > 1 else 0.0,  #crown base
                "ground_nap_m": ground,
                "proposed": True,
            }
            feats.append(_to_wgs_feature(Point(x, y), props))
        elif isinstance(geom, rhino3dm.Brep):
            fp, base, _, _ = roof_parts(geom)
            if fp is None or not fp.intersects(site):
                continue  #the block definitions' own solids, left at the model origin
            top = max(p.Z for m in meshes(geom) for p in m.Vertices) / MM  #true top, the bounding box is loose
            if top - base > 1.0 and kept_rd is not None and kept_rd.contains(fp.centroid):
                n_kind["in a kept building, dropped"] = n_kind.get("in a kept building, dropped", 0) + 1
                continue  #a solid bush standing in a building the scenario keeps
            if top - base > 1.0:
                #a closed solid standing up from the ground: OPTION 2 draws 86 bushes this way, not as blocks
                x0, y0, x1, y1 = fp.bounds
                c_ = fp.centroid
                n_kind["solid bush"] = n_kind.get("solid bush", 0) + 1
                feats.append(_to_wgs_feature(Point(c_.x, c_.y), {
                    "scenario": c["scenario"],
                    "kind": "shrub",
                    "block": "solid bush",  #not a block, a solid on the layer
                    "height_m": round(top - base, 1),
                    "crown_m": round(((x1 - x0) + (y1 - y0)) / 2, 1),  #mean plan extent, as for the blocks
                    "trunk_height_m": 0.0,
                    "ground_nap_m": ground,
                    "proposed": True,
                }))
                continue
            green.append(fp.intersection(site))  #flat surface: a green patch
    for k, n in sorted(n_kind.items()):
        print(f"  planting: {n:4} x {k}")
    if n_off:
        print(f"  planting: {n_off} instances outside the design site dropped")
    #water: one feature, cut out of the green below so the two drapes never overlap
    pond = unary_union(water) if water else None
    if pond is not None:
        print(f"  water: {len(water)} surface(s), {pond.area:.0f} m2")
        feats.append(_to_wgs_feature(pond, {
            "scenario": c["scenario"],
            "kind": "water",
            "name": f"{c['scenario']} water feature",
            "area_m2": round(pond.area),
            "rhino_layer": c["water_layer"],
        }))
    #green surfaces: overlaps counted once, the water taken out, then each separate patch its own feature
    merged = unary_union(green)
    if pond is not None:
        merged = merged.difference(pond)
    if kept_rd is not None and not kept_rd.is_empty:
        cut = merged.intersection(kept_rd).area
        merged = merged.difference(kept_rd)
        if cut > 0.5:
            print(f"  green: {cut:.0f} m2 over the buildings the scenario keeps cut away")
    if streets_rd is not None and not streets_rd.is_empty:
        cut = merged.intersection(streets_rd).area
        merged = merged.difference(streets_rd)
        if cut > 0.5:
            print(f"  green: {cut:.0f} m2 under the new streets cut away")
    patches = [g for g in getattr(merged, "geoms", [merged]) if g.area >= MIN_AREA_M2]
    print(f"  green: {len(green)} surfaces, {merged.area:.0f} m2 merged into {len(patches)} patches")
    for k, g in enumerate(sorted(patches, key=lambda g: -g.area)):
        feats.append(_to_wgs_feature(g, {
            "scenario": c["scenario"],
            "kind": "green",
            "name": f"{c['scenario']} green {k + 1}",
            "area_m2": round(g.area),
        }))
    return feats


def demolished(c, feats, footprints):
    #BAG pand ids this scenario removes, by the case's rule
    site = design_site_polygon()
    if c.get("keep_rd"):
        site = site.difference(Polygon(c["keep_rd"]))  #the part the scenario leaves standing is not demolished
    on_site = [(pid, g) for pid, g in footprints if g.representative_point().within(site)]  #outline crosses no building
    if c["demolish"] == "site":
        ids = [pid for pid, _ in on_site]
    else:
        new = unary_union([transform(lambda x, y, z=None: to_rd(x, y), shape(f["geometry"])) for f in feats])  #massing back to RD
        ids = [pid for pid, g in on_site if g.intersection(new).area > 1.0]  #overlapped by more than 1 m2
    print(f"  demolishes {len(ids)} of {len(on_site)} 3DBAG buildings on the site (rule '{c['demolish']}')")
    return sorted(ids)


def kept(c, footprints):
    #BAG pand ids standing in the part of the site this scenario keeps (keep_rd); the app colours them as the scenario
    if not c.get("keep_rd"):
        return []
    keep = design_site_polygon().intersection(Polygon(c["keep_rd"]))  #kept part, within the site
    ids = [pid for pid, g in footprints if g.representative_point().within(keep)]  #same test as demolished()
    print(f"  keeps {len(ids)} 3DBAG buildings on the site")
    return sorted(ids)


def write_trees(scenario, features, streets):
    #existing trees minus those inside this scenario's new blocks, streets or water -> trees_<scenario>.geojson
    trees = json.loads((PROCESSED / "trees.geojson").read_text())
    taken = unary_union([shape(f["geometry"]) for f in features + streets
                         if f["properties"]["scenario"] == scenario])  #lon/lat, fine for point-in-polygon
    keep = [t for t in trees["features"] if not taken.contains(shape(t["geometry"]))]
    print(f"  {scenario}: {len(trees['features']) - len(keep)} existing trees removed (in new blocks, streets or water)")
    out = {k: v for k, v in trees.items() if k != "features"}  #same header as trees.geojson
    out.update({"_written_by": "analysis/scenarios/import_rhino.py",
                "_note": f"Existing tree register minus trees inside the {scenario} blocks, streets and water. "
                         "Proposed planting is in design_planting.geojson, not here.",
                "features": keep})
    write_processed(f"trees_{scenario}.geojson", out, indent=None)


def main():
    if not MODEL.exists():
        sys.exit(f"missing {MODEL}\nCopy it from Modelling.zip on the shared drive (see the docstring).")
    features, demolishes, keeps, streets = [], {}, {}, []
    footprints = site_footprints()  #existing buildings, for the demolition lists
    for c in CASES:  #one Rhino layer tree per scenario
        print(f"{c['scenario']} <- {c['layer_prefix']} ({c['model'].name})")
        feats = import_option(c)
        features += feats
        demolishes[c["scenario"]] = demolished(c, feats, footprints)  #ids the app hides with this massing
        keeps[c["scenario"]] = kept(c, footprints)  #ids the app colours with this massing
        new_streets = import_streets(c)  #new street surfaces of the same option
        streets += new_streets
        blocks_rd = [transform(lambda x, y, z=None: to_rd(x, y), shape(f["geometry"])) for f in feats]  #massing back to RD
        for f in [f for f in new_streets if f["properties"]["kind"] == "street"]:  #paths and parking get no links
            streets += street_links(c, transform(lambda x, y, z=None: to_rd(x, y), shape(f["geometry"])), blocks_rd)  #to the edge streets
        kept_c = unary_union([g for i, g in footprints if i in set(keeps[c["scenario"]])]) if keeps[c["scenario"]] else None
        streets += design_paths(c, kept_c)  #paths the team added by hand, and walkway centrelines
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
        "_keep_note": "RD rings of site parts each scenario leaves standing, see KEEP_RD in import_rhino.py.",
        "keep_rd": {c["scenario"]: c.get("keep_rd") for c in CASES},  #read by scenario_world.cleared_area()
        "_keeps_note": "BAG pand ids standing in each scenario's keep_rd part of the site; "
                       "the app shows them in the scenario's colour as part of the design.",
        "keeps": keeps,
        "features": features,
    }, indent=1)
    write_processed("design_streets.geojson", {
        "type": "FeatureCollection",
        "_written_by": "analysis/scenarios/import_rhino.py",
        "_source": f"{MODEL.name}, 'New ROADS' sublayers",
        "_note": "EPSG:4326. kind 'street': one polygon per scenario, the Rhino street surfaces, draped on the "
                 "ground by the app. kind 'link': surfaces joining street ends that stop short of an edge street "
                 "to it (street_links), drawn and traced like the streets. kind 'path': lines the team added by "
                 "hand (CASES paths_rd), walked by road_network.py, not street canyons for height_width.py.",
        "features": streets,
    }, indent=1)
    street_rd = {}  #each option's street, link and walkway surfaces in RD, cut out of its green
    for f in streets:
        if f["properties"]["kind"] in ("street", "link", "walkway"):  #walkway: 30.10 draws green under it
            g = transform(lambda x, y, z=None: to_rd(x, y), shape(f["geometry"]))
            sc = f["properties"]["scenario"]
            street_rd[sc] = g if sc not in street_rd else street_rd[sc].union(g)
    fp_by_id = dict(footprints)  #pand id -> RD footprint
    kept_rd = {sc: unary_union([fp_by_id[i] for i in ids]) for sc, ids in keeps.items() if ids}  #kept buildings per scenario
    planting = [f for c in CASES if c.get("planting_model")
                for f in import_planting(c, street_rd.get(c["scenario"]), kept_rd.get(c["scenario"]))]  #trees, shrubs, green, water
    water = [f for f in planting if f["properties"]["kind"] == "water"]  #existing trees standing in new water go too
    for c in CASES:  #tree set per scenario
        write_trees(c["scenario"], features + water, streets)
    write_processed("design_planting.geojson", {
        "type": "FeatureCollection",
        "_written_by": "analysis/scenarios/import_rhino.py",
        "_source": ", ".join(f"{c['planting_model'].name}, '{c['layer_prefix']}::Proposed Vegetation'"
                             for c in CASES if c.get("planting_model")),
        "_note": "EPSG:4326. kind 'tree' / 'shrub': Points at the trunk, height_m above ground, crown_m the mean "
                 "plan extent, ground_nap_m the site ground (the model plants on NAP 0). kind 'green': planted "
                 "surfaces clipped to the site, minus the water. kind 'water': the 'Water feature?' surface. "
                 "Both draped on the ground by the app. Proposed only: the existing "
                 "trees kept by a scenario are in trees_<scenario>.geojson.",
        "features": planting,
    }, indent=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
