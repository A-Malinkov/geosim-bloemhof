#!/usr/bin/env python3
"""
import_rhino.py — proposed massing from the team's Rhino model into the app.

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
Modelling.zip on the shared drive:
    Modelling/Group Project Q1 - Proposal Modelling_23.10.26.3dm  ->  data/raw/
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
* Trees: data/processed/trees_<scenario>.geojson is the existing tree register
  minus the trees standing in a new block, on a new street or in new water.
  Proposed planting goes to its own file, see below.
* Streets are the flat surfaces on the "New ROADS" sublayer, merged (several
  are drawn twice) and clipped to the site. The road outline curves on that
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

MODEL = RAW / "Group Project Q1 - Proposal Modelling_23.10.26.3dm"  #newest version, both options and their planting
#the first 22.10 copy on the shared drive had OPTION 1's short buildings as mesh-less block instances (5 volumes
#instead of 22); 23.10 is solids again and gives OPTION 1 the same 22 volumes as 16.10
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
    sloped = []  #(triangle, mean z) of sloping faces, for a block whose whole roof slopes
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
                    sloped.append((p, sum(zs) / 3))
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
        if fp is None:
            print(f"  skipped  {sub:28} at x {bb.Min.X / MM:.0f}, y {bb.Min.Y / MM:.0f}: no plan area (a wall, or a stray at the origin)")
            continue  #OPTION 2 draws one block as an open roof plus a wall; the roof carries it
        if not fp.intersects(site):
            print(f"  dropped  {sub:28} at x {bb.Min.X / MM:.0f}, y {bb.Min.Y / MM:.0f}: not on the design site")
            continue
        cls = sub.split()[0].lower()  #tall / medium / short
        peak = max(p.Z for m in meshes(geom) for p in m.Vertices) / MM  #true top from the mesh; the bounding box is loose
        n_by_class[cls] = n_by_class.get(cls, 0) + 1
        name = f"{c['scenario']} {cls} {n_by_class[cls]}"  #e.g. "scenario_a tall 1"
        cut = fp.area - fp.intersection(site).area  #m2 lost at the site edge
        print(f"  {name:22} {fp.intersection(site).area:7.0f} m2  roofs "
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


def design_paths(c):
    #a case's hand-drawn paths (paths_rd) -> GeoJSON lines, kind "path", drawn and walked like the streets
    from shapely.geometry import LineString
    out = []
    for k, pts in enumerate(c.get("paths_rd", []), 1):
        g = LineString(pts)
        out.append(_to_wgs_feature(g, {
            "scenario": c["scenario"],
            "name": f"{c['scenario']} path {k}",
            "kind": "path",
            "length_m": round(g.length, 1),
            "source": "added by the team, not in the Rhino model (import_rhino.py CASES paths_rd)",
        }))
    if out:
        print(f"  paths: {len(out)} added by hand, {sum(f['properties']['length_m'] for f in out):.0f} m")
    return out


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
        for f in new_streets:
            streets += street_links(c, transform(lambda x, y, z=None: to_rd(x, y), shape(f["geometry"])), blocks_rd)  #to the edge streets
        streets += design_paths(c)  #paths the team added by hand
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
    street_rd = {}  #each option's street and link surfaces in RD, cut out of its green
    for f in streets:
        if f["properties"]["kind"] in ("street", "link"):
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
