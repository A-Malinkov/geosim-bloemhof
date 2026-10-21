#!/usr/bin/env python3
"""
scenario_world.py — the built environment of one scenario, for the analyses.

Every analysis that depends on buildings (sky view factor, sun hours, street
H/W, noise) needs the same answer to "what stands where in scenario X". This
module gives it, from the two files import_rhino.py writes:

    data/processed/design_massing.geojson   new blocks + per-scenario demolition list
    data/processed/design_streets.geojson   new street surfaces

Three entry points, all a no-op for "baseline":

    buildings_for_scenario(b, scenario)       GeoDataFrame of footprints (RD) with
                                              height_m above ground: drops the
                                              demolished ids, appends the new blocks
    burn_into_rasters(dsm, dtm, transform, scenario)
                                              AHN DSM/DTM arrays with the demolished
                                              buildings flattened to ground and the
                                              new blocks raised to their roofs
    streets_for_scenario(roads, scenario)     street centrelines (RD): OSM streets in
                                              the site interior swapped for centrelines
                                              traced from the new street surfaces
    cleared_area(scenario)                    the part of the site the scenario rebuilds

Ground for demolished and new buildings is the site ground level,
DESIGN_SITE["ground_nap_m"] (AHN DTM median over the site). The DTM is empty
under buildings, so there is no better local value to use.

WHAT IT CANNOT TELL YOU
-----------------------
* Old back-garden trees on demolished lots stay in the DSM, except where a new
  block or street now is; the new design's planting is not added.
* Demolished footprints are widened by 0.5 m before flattening, so eaves and
  the AHN's soft building edges go with them.
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common.project import DESIGN_SITE, PROCESSED, ROOT, design_site_polygon, to_rd  # noqa: E402

FOOTPRINTS = ROOT / "cache" / "scenarios" / "footprints_site.geojson"  #3DBAG LoD0 over the site, gitignored
DEMOLISH_PAD_M = 0.5  #widen demolished footprints so eaves and soft AHN edges go too
EDGE_BAND_M = 15.0  #OSM streets this close to the site outline are the kept edge streets
EDGE_STREETS = ("Lange Hilleweg", "Sandelingstraat", "Dortsmondstraat", "Dubbelstraat",
                "Strevelsweg")  #the site's edge streets, kept whole: Strevelsweg runs up to 20 m inside the outline


# ------------------------------------------------------------------- inputs
def site_footprints():
    #3DBAG footprints around the design site as (id, shapely geometry in RD), fetched once and cached
    from shapely.geometry import shape
    if not FOOTPRINTS.exists():
        sys.path.insert(0, str(HERE.parent / "wind_noise"))
        from noise import fetch_footprints  #same 3DBAG paging and LoD0 decoding as the noise model
        FOOTPRINTS.parent.mkdir(parents=True, exist_ok=True)
        x0, y0, x1, y1 = design_site_polygon().bounds
        print("  fetching 3DBAG footprints over the design site (about a minute)")
        fetch_footprints((x0 - 20, y0 - 20, x1 + 20, y1 + 20), FOOTPRINTS)  #20 m pad
    return [(f["properties"]["identificatie"], shape(f["geometry"]))
            for f in json.loads(FOOTPRINTS.read_text())["features"]]


def load_scenario(scenario: str):
    #-> (new blocks as GeoDataFrame in RD with height_m above ground, set of demolished ids); exits if missing
    import geopandas as gpd
    path = PROCESSED / "design_massing.geojson"
    d = json.loads(path.read_text())
    feats = [f for f in d.get("features", []) if f["properties"].get("scenario") == scenario]
    if d.get("_status") == "not_computed_yet" or not feats:
        sys.exit(f"No massing for {scenario} in {path.relative_to(ROOT)}. "
                 "Run analysis/scenarios/import_rhino.py, or add the scenario there.")
    new = gpd.GeoDataFrame.from_features(feats, crs="EPSG:4326").to_crs(28992)
    new["height_m"] = new["building_height_m"].astype(float)  #above ground, like 3DBAG heights here
    return new[["name", "height_m", "geometry"]], set(d.get("demolishes", {}).get(scenario, []))


def cleared_area(scenario: str):
    #the part of the design site the scenario rebuilds (RD): the site minus what import_rhino.py says it keeps
    from shapely.geometry import Polygon
    site = design_site_polygon()
    keep = json.loads((PROCESSED / "design_massing.geojson").read_text()).get("keep_rd", {}).get(scenario)
    return site.difference(Polygon(keep)) if keep else site


# ---------------------------------------------------------------- buildings
def buildings_for_scenario(b, scenario: str, id_col: str = "identificatie"):
    #3DBAG footprints (RD, height_m above ground) -> the same table for the scenario
    import geopandas as gpd
    import pandas as pd
    if scenario == "baseline":
        return b
    new, gone = load_scenario(scenario)
    kept = b[~b[id_col].isin(gone)]  #demolished buildings removed
    print(f"  {scenario}: {len(b) - len(kept)} existing buildings removed, {len(new)} new blocks added")
    new = new.rename(columns={"name": id_col})  #new blocks keep their name as id
    return gpd.GeoDataFrame(pd.concat([kept, new[[id_col, "height_m", "geometry"]]], ignore_index=True),
                            crs=b.crs)


# ------------------------------------------------------------------ rasters
def burn_into_rasters(dsm, dtm, transform, scenario: str):
    #AHN DSM and DTM (NAP, same grid) -> copies with the scenario's demolition and new blocks burned in
    if scenario == "baseline":
        return dsm, dtm
    from rasterio.features import rasterize
    new, gone = load_scenario(scenario)
    ground = DESIGN_SITE["ground_nap_m"]  #site ground level, m NAP
    dsm, dtm = dsm.copy(), dtm.copy()
    old = [g.buffer(DEMOLISH_PAD_M) for pid, g in site_footprints() if pid in gone]  #demolished, widened
    if old:
        m = rasterize([(g, 1) for g in old], out_shape=dsm.shape, transform=transform, dtype="uint8").astype(bool)
        dsm[m] = ground  #flattened to the ground: now open ground
        dtm[m] = ground  #the DTM had no value under the old buildings
        print(f"  {scenario}: {len(old)} demolished buildings flattened, {m.sum():,} cells")
    #new streets: flat at ground level, so old crowns and sheds standing there go
    from shapely.geometry import shape
    from shapely.ops import transform as shp_transform
    d = json.loads((PROCESSED / "design_streets.geojson").read_text())
    streets = [shp_transform(lambda x, y, z=None: to_rd(x, y), shape(f["geometry"]))
               for f in d.get("features", []) if f["properties"].get("scenario") == scenario]
    if streets:
        m = rasterize([(g, 1) for g in streets], out_shape=dsm.shape, transform=transform, dtype="uint8").astype(bool)
        dsm[m] = ground  #street surface
        dtm[m] = ground
        print(f"  {scenario}: new streets flattened, {m.sum():,} cells")
    #new blocks, lowest first so a taller part wins where parts touch
    shapes = [(g, ground + h) for g, h in sorted(zip(new.geometry, new.height_m), key=lambda t: t[1])]
    roof = rasterize(shapes, out_shape=dsm.shape, transform=transform, fill=np.nan, dtype="float32")
    m = np.isfinite(roof)
    dsm[m] = roof[m]  #raised to the roof
    dtm[m] = ground  #standing on the site ground, so nDSM = building height and it is not open ground
    print(f"  {scenario}: {len(new)} new blocks burned in, {m.sum():,} cells")
    return dsm, dtm


# ------------------------------------------------------------------ streets
def centrelines(poly, step: float = 1.0, prune_m: float = 6.0):
    #approximate medial axis of a street polygon: Voronoi edges of its densified outline that lie inside it
    import shapely
    from shapely.ops import linemerge
    pts = shapely.get_coordinates(shapely.segmentize(poly.boundary, step))  #outline every `step` m
    edges = shapely.voronoi_polygons(shapely.multipoints(pts), only_edges=True)
    inner = poly.buffer(-step)  #keep edges well inside, the ones near the outline are spokes
    lines = [e for e in shapely.get_parts(edges) if inner.contains(e)]
    if not lines:
        return []
    merged = list(shapely.get_parts(linemerge(shapely.union_all(lines))))  #join the short Voronoi edges into runs
    #count how many runs meet at each end point; a run with a free end is a spur
    ends = [tuple(np.round(g.coords[k], 3)) for g in merged for k in (0, -1)]
    degree = {e: ends.count(e) for e in ends}
    def spur(g):
        return min(degree[tuple(np.round(g.coords[0], 3))], degree[tuple(np.round(g.coords[-1], 3))]) == 1
    return [g for g in merged if g.length >= prune_m or not spur(g)]  #drop short dead ends only, keep short links at junctions


def streets_for_scenario(roads, scenario: str):
    #OSM street centrelines (GeoDataFrame, RD) -> centrelines for the scenario
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import shape
    if scenario == "baseline":
        return roads
    site = cleared_area(scenario)  #the kept block's streets stay
    interior = site.buffer(-EDGE_BAND_M)  #inside this, the old grid is gone
    kept = roads.copy()
    edge = kept["name"].astype(str).str.contains("|".join(EDGE_STREETS)) if "name" in kept else False  #edge streets by name
    kept["geometry"] = kept.geometry.difference(interior).where(~edge, kept.geometry)  #cut the old interior streets away, edge streets stay whole
    cut = ~kept.geometry.geom_equals(roads.geometry)  #shortened by the cut
    kept = kept[~kept.geometry.is_empty]
    stub = cut[kept.index] & kept.geometry.within(site) & (kept.geometry.length < 2 * EDGE_BAND_M)  #leftover ends of interior streets, untouched short edges stay
    kept = kept[~stub]
    d = json.loads((PROCESSED / "design_streets.geojson").read_text())
    polys = [shape(f["geometry"]) for f in d.get("features", []) if f["properties"].get("scenario") == scenario]
    from shapely.ops import transform
    lines = []
    for p in polys:
        p_rd = transform(lambda x, y, z=None: to_rd(x, y), p)  #lon/lat -> RD
        for part in getattr(p_rd, "geoms", [p_rd]):
            lines += centrelines(part)
    print(f"  {scenario}: OSM streets cut out of the site interior, {len(lines)} new centrelines "
          f"({sum(g.length for g in lines):.0f} m) added")
    new = gpd.GeoDataFrame({"name": [f"{scenario} new street"] * len(lines)}, geometry=lines, crs=roads.crs)
    return gpd.GeoDataFrame(pd.concat([kept, new], ignore_index=True), crs=roads.crs)
