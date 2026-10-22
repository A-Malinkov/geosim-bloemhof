"""
analysis/common/project.py — SHARED MODULE. Coordinator-owned.

The single source of truth for the study area, coordinate systems, paths and the
height datum, mirroring app/config.js. Import it from every analysis script so
nobody hard-codes a bounding box:

    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from common.project import STUDY_AREA, PROCESSED, bbox_rd, to_rd, to_wgs

THE STUDY AREA IS ONE BUURT, NOT A SQUARE
-----------------------------------------
Bloemhof (BU05991081) in Rotterdam-Zuid. Everything is analysed over it; the
design scenarios occupy only a small site inside it (see `DESIGN_SITE`).

From 2026-09-30 to 2026-10-22 the study area was Bloemhof AND Hillesluis
(BU05991082); the team narrowed it to Bloemhof alone on 2026-10-22. `buurten`
below is a tuple, so adding a buurt back is a one-line change plus re-runs.

Earlier versions of this file used a 600 m square around a point, which covered
75% of Bloemhof. `bbox_rd()` now derives its box from the
actual buurt polygons, so it cannot drift out of step with them again. It takes a
PADDING in metres, not a radius — several analyses need context beyond the edge
(a building just outside still blocks sky inside).
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass

import pyproj

# --------------------------------------------------------------------- paths
ROOT       = pathlib.Path(__file__).resolve().parents[2]
DATA       = ROOT / "data"
RAW        = DATA / "raw"
PROCESSED  = DATA / "processed"
DOCS       = ROOT / "docs"
for _d in (RAW, PROCESSED, DOCS):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- study area
@dataclass(frozen=True)
class StudyArea:
    name: str = "Bloemhof"
    municipality: str = "Rotterdam"
    wijk: str = "Feijenoord"
    #: CBS buurt code -> name. Analysis covers all of these.
    buurten: tuple[tuple[str, str], ...] = (
        ("BU05991081", "Bloemhof"),  #Hillesluis (BU05991082) dropped 2026-10-22
    )
    cbs_gemeente: str = "GM0599"
    #: Year of the CBS wijkenbuurten edition the boundaries come from.
    boundary_year: int = 2025
    #: Nearest KNMI synoptic station: 344 = Rotterdam The Hague Airport.
    knmi_station: int = 344

STUDY_AREA = StudyArea()

#: Where the design scenarios go. The brief is that scenarios occupy only a
#: small part of the study area, so this is a separate, smaller footprint:
#: everything is ANALYSED over the whole study area, but baseline / scenario_a /
#: scenario_b only differ inside this polygon.
#:
#: Chosen by the team on 2026-09-30: the blocks in south-west Bloemhof between
#: Lange Hilleweg (north-west), Sandelingstraat (north-east), Dortsmondstraat and
#: Dubbelstraat (south-east) and Strevelsweg (south), INCLUDING those edge streets.
#:
#: How the outline was made, so it can be redone:
#:   1. the team's freehand sketch on an app screenshot was georeferenced with a
#:      perspective fit on six Bloemhof boundary corners (residuals 0.4-4 m);
#:   2. the street blocks it covers were taken from the OSM street network
#:      (faces between centrelines, most >80 % inside the sketch);
#:   3. each edge street was added out to just short of the facades opposite,
#:      measured per edge from 3DBAG LoD0 footprints (Strevelsweg ~14-20 m,
#:      side streets ~7-15 m). Lange Hilleweg stops at the tree row of its
#:      central green strip (9 m): the strip itself is not in the site;
#:   4. the south-east corner runs down a party wall between two houses on
#:      Strevelsweg rather than through a house.
#: Extended 2026-10-14 at the team's request (marked-up app screenshot): the
#: strip of two terraced rows between Strevelsweg and the block of large
#: buildings and trees, east to the footpath at x 94158 (the gap between both
#: rows, 94154.0-94161.8), with Strevelsweg out to the facades opposite. That
#: block itself stays outside; the new north edge runs along the street in front
#: of it and passes south of a 2.5 m2 bin store. +1.13 ha, +72 buildings.
#: Checked: the outline crosses no building (0 m of 2,004 m inside a footprint;
#: closest facade 0.8 m). Part of it lies south of the buurt boundary, because
#: that boundary runs down the middle of Strevelsweg and the site takes in the
#: whole street.
#: Extended 2026-10-21 at Atanas's request (app screenshot): that block of large
#: buildings and trees is now in the site too, the triangle between the diagonal
#: street, Dubbelstraat and Oudelandstraat. Its notch, vertices (94045.0,
#: 433883.0) to (94136.6, 433976.9), is replaced by one edge from (94158.0,
#: 433881.0) to (94168.8, 433939.6), which crosses no building. +0.86 ha, 6
#: buildings (a school, assembly halls, workshops). Scenario A keeps them: the
#: site is where we measure, the triangle is not cleared (KEEP_RD in
#: analysis/scenarios/import_rhino.py).
#:
#: Vertices are RD New (EPSG:28992), counter-clockwise, not closed.
DESIGN_SITE = {
    "name": "Design site — south-west Bloemhof",
    "chosen": "2026-09-30",
    "source": "team sketch, snapped to street blocks; edge streets included "
              "out to the facades opposite; crosses no building",
    #: Ground level inside the site, median of the AHN DTM (0.5 m) over the
    #: polygon: p05 -1.17, p95 -0.62. This is the default BASE for massing.
    #: It is NOT 0: a building placed at NAP 0 would float about 1 m.
    "ground_nap_m": -0.93,
    "ring_rd": [
        (93616.8, 433795.9), (93690.6, 433797.7), (93696.1, 433798.0), (93696.1, 433799.3),
        (93713.8, 433800.0), (93713.7, 433800.5), (93764.6, 433802.1), (93767.9, 433802.3),
        (93767.8, 433802.8), (93933.6, 433808.0), (93933.5, 433812.1), (93989.9, 433814.1),
        (94158.0, 433815.5), (94158.0, 433881.0), (94168.8, 433939.6),
        (94211.3, 433976.9), (94222.4, 433976.9), (94236.6, 433988.9), (94237.5, 433989.1),
        (94241.0, 433992.0), (94242.1, 433990.7), (94261.1, 434001.4), (94258.9, 434004.0),
        (94260.0, 434005.0), (94248.4, 434025.5), (94245.3, 434022.8), (94243.6, 434024.7),
        (94240.1, 434022.7), (94202.3, 434064.9), (94112.4, 434168.2), (94088.1, 434196.6),
        (94088.5, 434196.9), (94086.3, 434199.5), (94087.4, 434200.4), (94077.8, 434211.5),
        (93802.4, 433972.2), (93797.1, 433968.2), (93645.8, 433837.0), (93615.4, 433835.9),
    ],
}

# ------------------------------------------------------------------ CRS bits
WGS84 = "EPSG:4326"
RD    = "EPSG:28992"          # Amersfoort / RD New, the Dutch national grid
RD_NAP = "EPSG:7415"          # RD New + NAP height
WGS84_3D = "EPSG:4979"

_to_rd  = pyproj.Transformer.from_crs(WGS84, RD, always_xy=True)
_to_wgs = pyproj.Transformer.from_crs(RD, WGS84, always_xy=True)


def to_rd(lon: float, lat: float) -> tuple[float, float]:
    """WGS84 lon/lat -> RD New x/y (metres)."""
    return _to_rd.transform(lon, lat)


def to_wgs(x: float, y: float) -> tuple[float, float]:
    """RD New x/y -> WGS84 lon/lat."""
    return _to_wgs.transform(x, y)


# ------------------------------------------------- buurt boundaries (cached)
WFS = "https://service.pdok.nl/cbs/wijkenbuurten/{year}/wfs/v1_0"
_CACHE = RAW / "study_area.geojson"
_polys: dict[str, object] | None = None


def _fetch_buurt_geojson(code: str, year: int) -> dict:
    """
    One buurt from the PDOK wijkenbuurten WFS.

    Note the service quirk: it IGNORES `cql_filter` and silently returns
    arbitrary features. An OGC Filter XML is required.
    """
    import requests

    flt = ("<Filter xmlns='http://www.opengis.net/fes/2.0'><PropertyIsEqualTo>"
           "<ValueReference>buurtcode</ValueReference>"
           f"<Literal>{code}</Literal></PropertyIsEqualTo></Filter>")
    r = requests.get(WFS.format(year=year), timeout=120, params={
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": "wijkenbuurten:buurten",
        "outputFormat": "application/json",
        "srsName": "EPSG:28992", "filter": flt})
    r.raise_for_status()
    feats = r.json().get("features", [])
    if not feats:
        raise LookupError(f"buurt {code} not found in the {year} layer")
    return feats[0]


def buurt_polygons(refresh: bool = False) -> dict[str, object]:
    """
    {buurt code: shapely geometry} for every buurt in the study area.

    Cached to data/raw/study_area.geojson so that the dozen scripts calling
    bbox_rd() do not each hit the WFS, and so the analysis still runs when PDOK
    is having a bad day.
    """
    global _polys
    import shapely.geometry as sg

    if _polys is not None and not refresh:
        return _polys

    wanted = [code for code, _ in STUDY_AREA.buurten]
    if _CACHE.exists() and not refresh:
        fc = json.loads(_CACHE.read_text())
        cached = {f["properties"]["buurtcode"]: sg.shape(f["geometry"])
                  for f in fc["features"]}
        if all(c in cached for c in wanted):  #the cache may hold more buurten than the study area
            _polys = {c: cached[c] for c in wanted}  #only the study-area buurten, in STUDY_AREA order
            return _polys

    feats = []
    for code, name in STUDY_AREA.buurten:
        f = _fetch_buurt_geojson(code, STUDY_AREA.boundary_year)
        f["properties"]["_name"] = name
        feats.append(f)
    _CACHE.write_text(json.dumps({
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::28992"}},
        "_source": f"CBS wijkenbuurten {STUDY_AREA.boundary_year} via PDOK WFS",
        "features": feats,
    }, default=str) + "\n")
    _polys = {f["properties"]["buurtcode"]: sg.shape(f["geometry"]) for f in feats}
    return _polys


def buurt_properties() -> dict[str, dict]:
    """{buurt code: CBS attributes} — inhabitants, area and the rest."""
    buurt_polygons()                       # ensure the cache exists
    fc = json.loads(_CACHE.read_text())
    wanted = {code for code, _ in STUDY_AREA.buurten}  #skip cached buurten outside the study area
    return {f["properties"]["buurtcode"]: f["properties"] for f in fc["features"]
            if f["properties"]["buurtcode"] in wanted}


def study_area_polygon():
    """The union of the study-area buurten, as one shapely geometry."""
    from shapely.ops import unary_union
    return unary_union(list(buurt_polygons().values()))


def fetch_buurt(code: str | None = None, year: int | None = None):
    """
    One buurt as (geometry, properties). Kept for scripts that want a single
    buurt; pass a code from STUDY_AREA.buurten.
    """
    import shapely.geometry as sg
    code = code or STUDY_AREA.buurten[0][0]
    if year in (None, STUDY_AREA.boundary_year):
        props = buurt_properties()
        if code in props:
            return buurt_polygons()[code], props[code]
    f = _fetch_buurt_geojson(code, year or STUDY_AREA.boundary_year)
    return sg.shape(f["geometry"]), f["properties"]


# ---------------------------------------------------------------- extents
def bbox_rd(pad_m: float = 0.0) -> tuple[float, float, float, float]:
    """
    Bounding box of the whole study area in RD New, optionally padded.

    `pad_m` is PADDING, not a radius. Analyses that see past their own edge —
    Sky View Factor most obviously, since a building outside the boundary still
    blocks sky inside it — should pass a pad and crop afterwards.
    """
    xmin, ymin, xmax, ymax = study_area_polygon().bounds
    return (xmin - pad_m, ymin - pad_m, xmax + pad_m, ymax + pad_m)


def bbox_wgs(pad_m: float = 0.0) -> tuple[float, float, float, float]:
    """
    The same box in WGS84: (west, south, east, north).

    Careful: RD New is rotated slightly against WGS84, so this rectangle is an
    approximation of the RD box, off by up to ~30 m at the corners. Fine for
    asking a service "give me roughly this area"; NOT fine for draping an image.
    Warp the raster instead — see reproject_to_wgs84() in sky_view_factor.py.
    """
    xmin, ymin, xmax, ymax = bbox_rd(pad_m)
    xs, ys = [], []
    for x, y in ((xmin, ymin), (xmax, ymin), (xmin, ymax), (xmax, ymax)):
        lon, lat = to_wgs(x, y)
        xs.append(lon); ys.append(lat)
    return (min(xs), min(ys), max(xs), max(ys))


def centre_rd() -> tuple[float, float]:
    c = study_area_polygon().centroid
    return (c.x, c.y)


def centre_wgs() -> tuple[float, float]:
    """(lon, lat) of the study-area centroid."""
    return to_wgs(*centre_rd())


# --------------------------------------------------------------- height datum
def nap_to_ellipsoid_offset(lon: float | None = None,
                            lat: float | None = None) -> float:
    """
    Metres to ADD to a NAP height to get a WGS84 ellipsoidal height.

    About +43.6 m here. Uses the official NSGI geoid grid
    (nl_nsgi_nlgeo2018.tif), downloaded on demand by PROJ, so the first call
    needs network access. Falls back to the cached constant and says so.
    """
    if lon is None or lat is None:
        lon, lat = centre_wgs()
    try:
        pyproj.network.set_network_enabled(True)
        grp = pyproj.transformer.TransformerGroup(RD_NAP, WGS84_3D)
        if not grp.transformers:
            raise RuntimeError("no usable transform")
        x, y = to_rd(lon, lat)
        _, _, h = grp.transformers[0].transform(x, y, 0.0)
        if abs(h) < 1.0:                       # PROJ fell back to a no-op
            raise RuntimeError("ballpark vertical transform, grid missing")
        return round(h, 3)
    except Exception as exc:                   # pragma: no cover
        print(f"[project] geoid grid unavailable ({exc}); using the cached constant")
        return NAP_TO_ELLIPSOID_M


#: Precomputed with PROJ 9.8.1 + nl_nsgi_nlgeo2018.tif over the study area.
NAP_TO_ELLIPSOID_M = 43.623

# ------------------------------------------------------------------- services
# Verified reachable 2026-09-30. Keep in step with app/config.js.
SERVICES = {
    "ahn_wcs":        "https://service.pdok.nl/rws/ahn/wcs/v1_0",
    "ahn_wms":        "https://service.pdok.nl/rws/ahn/wms/v1_0",
    "bag3d_tiles":    "https://data.3dbag.nl/v20250903/cesium3dtiles/lod22/tileset.json",
    "bag3d_api":      "https://api.3dbag.nl",
    "cbs_odata":      "https://opendata.cbs.nl/ODataApi/odata",
    "cbs_table":      "86358NED",
    "wijkenbuurten":  WFS.format(year=STUDY_AREA.boundary_year),
    "knmi_open_data": "https://api.dataplatform.knmi.nl/open-data/v1",
    "knmi_daily":     "https://www.daggegevens.knmi.nl/klimatologie/daggegevens",
    "pdok_locatie":   "https://api.pdok.nl/bzk/locatieserver/search/v3_1",
}

# The public anonymous KNMI key (valid to 2027-08-01 per KNMI's docs).
KNMI_ANONYMOUS_KEY = (
    "eyJvcmciOiI1ZTU1NGUxOTI3NGE5NjAwMDEyYTNlYjEiLCJpZCI6IjUzYTg1ZDBhMmQ5YzRk"
    "YzJiYWNlNzQ4NTQ2Zjk4ODExIiwiaCI6Im11cm11cjEyOCJ9"
)


# -------------------------------------------------------------------- helpers
def write_processed(filename: str, payload, *, indent: int = 2) -> pathlib.Path:
    """Write a result into data/processed/ where the web app can fetch it."""
    path = PROCESSED / filename
    path.write_text(json.dumps(payload, indent=indent, default=str) + "\n")
    print(f"[project] wrote {path.relative_to(ROOT)}")
    return path


def export_study_area_geojson() -> pathlib.Path:
    """
    Write the buurt boundaries to data/processed/ in WGS84 for the Cesium app.

    Converted vertex by vertex, which is the correct way: RD New is rotated
    against WGS84, so reprojecting only a bounding box would be ~30 m out.
    """
    polys, props = buurt_polygons(), buurt_properties()
    feats = []
    for code, name in STUDY_AREA.buurten:
        g = polys[code]
        parts = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
        coords = []
        for part in parts:
            ring = [list(to_wgs(x, y)) for x, y in part.exterior.coords]
            coords.append([[[round(a, 7), round(b, 7)] for a, b in ring]])
        p_ = props.get(code, {})
        feats.append({
            "type": "Feature",
            "geometry": {"type": "MultiPolygon", "coordinates": coords},
            "properties": {
                "buurtcode": code, "name": name,
                "inhabitants": p_.get("aantalInwoners"),
                "area_ha": round(g.area / 10_000, 2),
            },
        })
    path = PROCESSED / "study_area.geojson"
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "_source": f"CBS wijkenbuurten {STUDY_AREA.boundary_year} via PDOK",
        "_note": "Boundaries of the buurten analysed. Scenarios occupy only a "
                 "small site inside them; see DESIGN_SITE in project.py.",
        "bbox_wgs84": [round(v, 7) for v in bbox_wgs()],
        "features": feats,
    }) + "\n")
    return path


def design_site_polygon():
    """The scenario site as a shapely Polygon in RD New."""
    from shapely.geometry import Polygon
    return Polygon(DESIGN_SITE["ring_rd"])


def export_design_site_geojson() -> pathlib.Path:
    """
    Write the design site to data/processed/ in WGS84 for the Cesium app.

    Vertex by vertex, for the same reason as the buurt boundaries. The building
    count comes from the 3DBAG points fetched for the morphology indicators, so
    it is only written when that file exists; the polygon never depends on it.
    """
    site = design_site_polygon()
    ring = [list(to_wgs(x, y)) for x, y in site.exterior.coords]
    props = {
        "name": DESIGN_SITE["name"],
        "chosen": DESIGN_SITE["chosen"],
        "source": DESIGN_SITE["source"],
        "area_ha": round(site.area / 10_000, 2),
        "ground_nap_m": DESIGN_SITE["ground_nap_m"],
        "n_buildings": None,
    }
    raw = RAW / "buildings_3dbag.geojson"
    if raw.exists():
        from shapely.geometry import shape
        from shapely.prepared import prep
        ps = prep(site)
        feats = json.loads(raw.read_text()).get("features", [])
        props["n_buildings"] = sum(
            1 for f in feats if f.get("geometry") and ps.contains(shape(f["geometry"])))
    c = site.centroid
    path = PROCESSED / "design_site.geojson"
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "_source": "analysis/common/project.py (DESIGN_SITE)",
        "_note": "The small site the design scenarios occupy. Everything is "
                 "analysed over both buurten; baseline / scenario_a / scenario_b "
                 "differ only inside this polygon.",
        "centre_wgs84": [round(v, 7) for v in to_wgs(c.x, c.y)],
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Polygon",
                         "coordinates": [[[round(a, 7), round(b, 7)] for a, b in ring]]},
            "properties": props,
        }],
    }) + "\n")
    return path


def summary() -> str:
    props = buurt_properties()
    lines = [f"Study area: {STUDY_AREA.name}, {STUDY_AREA.municipality}"]
    polys = buurt_polygons()
    for code, name in STUDY_AREA.buurten:
        p = props.get(code, {})
        lines.append(f"  {name:12} {code}  {polys[code].area / 10_000:6.1f} ha  "
                     f"{p.get('aantalInwoners', '?'):>6} inhabitants")
    u = study_area_polygon()
    b = bbox_rd()
    lines += [
        f"  combined      {u.area / 10_000:.1f} ha",
        f"  bbox RD       {tuple(round(v) for v in b)}",
        f"  extent        {b[2] - b[0]:.0f} x {b[3] - b[1]:.0f} m",
        f"  centroid      {centre_wgs()[1]:.6f}, {centre_wgs()[0]:.6f}",
        f"  NAP -> ellipsoid +{NAP_TO_ELLIPSOID_M} m",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary())
    print(f"\nwrote {export_study_area_geojson().relative_to(ROOT)}")
    print(f"wrote {export_design_site_geojson().relative_to(ROOT)}")
