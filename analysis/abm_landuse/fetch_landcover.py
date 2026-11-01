#!/usr/bin/env python3
"""
fetch_landcover.py - land cover that BAG cannot see, for the land-use ABM.

Owner: Atanas Malinkov

WHY THIS EXISTS
---------------
The land-use mix work (analysis/morphology/landuse_mix.py) is built on BAG
addressable units, which is right for a mix index but covers only BUILT FLOOR
SPACE. A cellular automaton needs the whole surface: it has to know which cells
are water (never developable), which are road (fixed), and which are green
(convertible, but losing them has a cost).

OSM supplies exactly those three. It is not authoritative the way BAG is, but
for "is this cell a park, a canal or a street" it is current, complete enough in
Rotterdam, and far better than CBS Bestand Bodemgebruik, whose newest edition is
2017 and resolves the whole study square into 10 polygons.

USAGE
-----
    python analysis/abm_landuse/fetch_landcover.py

OUTPUTS
-------
    data/raw/osm_landcover.geojson   green and water polygons, EPSG:28992
    data/raw/osm_roads.geojson       road centrelines, EPSG:28992
"""
from __future__ import annotations

import pathlib
import sys
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import RAW, STUDY_AREA, bbox_wgs  # noqa: E402

GREEN_TAGS = {
    "leisure": ["park", "garden", "pitch", "playground", "recreation_ground"],
    "landuse": ["grass", "meadow", "forest", "village_green", "allotments",
                "cemetery", "recreation_ground"],
    "natural": ["wood", "scrub", "grassland"],
}
WATER_TAGS = {"natural": ["water"], "waterway": ["riverbank", "dock", "canal",
                                                 "river", "stream"],
              "landuse": ["basin", "reservoir"]}


def main() -> int:
    import geopandas as gpd
    import osmnx as ox

    w, s, e, n = bbox_wgs()
    print(f"OSM land cover: {STUDY_AREA.name}")
    print(f"  bbox {w:.5f},{s:.5f},{e:.5f},{n:.5f}")

    frames = []
    for label, tags in (("green", GREEN_TAGS), ("water", WATER_TAGS)):
        try:
            g = ox.features_from_bbox((w, s, e, n), tags)
        except Exception as exc:
            print(f"  ! {label}: {type(exc).__name__} {exc}")
            continue
        g = g[g.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
        if g.empty:
            print(f"  {label}: none found")
            continue
        g = g.to_crs("EPSG:28992")
        keep = [c for c in ("landuse", "natural", "leisure", "name")
                if c in g.columns]
        g = g[keep + ["geometry"]].copy()
        g["cover"] = label
        frames.append(g)
        print(f"  {label}: {len(g)} polygons, "
              f"{g.geometry.area.sum() / 10_000:.1f} ha")

    if frames:
        out = gpd.GeoDataFrame(
            __import__("pandas").concat(frames, ignore_index=True),
            crs="EPSG:28992")
        # OSM columns can hold lists; GeoJSON cannot
        for c in out.columns:
            if c != "geometry":
                out[c] = out[c].astype(str)
        path = RAW / "osm_landcover.geojson"
        out.to_file(path, driver="GeoJSON")
        print(f"  wrote data/raw/{path.name}")

    # roads: centrelines, buffered into cells later
    try:
        G = ox.graph_from_bbox((w, s, e, n), network_type="drive",
                               simplify=True, truncate_by_edge=True)
        edges = ox.graph_to_gdfs(G, nodes=False).to_crs("EPSG:28992")
        keep = [c for c in ("highway", "name", "lanes") if c in edges.columns]
        edges = edges[keep + ["geometry"]].copy()
        for c in edges.columns:
            if c != "geometry":
                edges[c] = edges[c].astype(str)
        path = RAW / "osm_roads.geojson"
        edges.to_file(path, driver="GeoJSON")
        print(f"  roads: {len(edges)} segments, "
              f"{edges.geometry.length.sum() / 1000:.1f} km "
              f"-> data/raw/{path.name}")
    except Exception as exc:
        print(f"  ! roads: {type(exc).__name__} {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
