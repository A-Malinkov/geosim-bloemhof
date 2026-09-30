"""
analysis/common/project.py — SHARED MODULE. Coordinator-owned.

The single source of truth for the study area, coordinate systems, paths and the
height datum, mirroring app/config.js. Import it from every analysis script so
nobody hard-codes a bounding box:

    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from common.project import STUDY_AREA, PROCESSED, bbox_rd, to_rd, to_wgs

THE STUDY AREA IS TWO BUURTEN, NOT A SQUARE
-------------------------------------------
Bloemhof (BU05991081) and Hillesluis (BU05991082), adjacent buurten in
Rotterdam-Zuid, 169 ha and about 26,000 inhabitants between them. Everything is
analysed over BOTH; the design scenarios occupy only a small site inside them
(see `DESIGN_SITE`).

Earlier versions of this file used a 600 m square around a point, which covered
75% of Bloemhof and none of Hillesluis. `bbox_rd()` now derives its box from the
actual buurt polygons, so it cannot drift out of step with them again. It takes a
PADDING in metres, not a radius — several analyses need context beyond the edge
(a building just outside still blocks sky inside).
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, asdict

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
    name: str = "Bloemhof & Hillesluis"
    municipality: str = "Rotterdam"
    wijk: str = "Feijenoord"
    #: CBS buurt code -> name. Analysis covers all of these.
    buurten: tuple[tuple[str, str], ...] = (
        ("BU05991081", "Bloemhof"),
        ("BU05991082", "Hillesluis"),
    )
    cbs_gemeente: str = "GM0599"
    #: Year of the CBS wijkenbuurten edition the boundaries come from.
    boundary_year: int = 2025
    #: Nearest KNMI synoptic station: 344 = Rotterdam The Hague Airport.
    knmi_station: int = 344

STUDY_AREA = StudyArea()

#: Where the design scenarios go. The brief is that scenarios occupy only a
#: small part of the study area, so this is a separate, smaller footprint.
#: PLACEHOLDER — set it to the real site once the team picks one. Nothing in the
#: analysis depends on it; only components 4.1 and 4.9 do.
DESIGN_SITE = {
    "_status": "placeholder — the team has not chosen the site yet",
    "centre_rd": (94403.0, 434360.0),   # the seam between the two buurten
    "radius_m": 150,
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

    if _CACHE.exists() and not refresh:
        fc = json.loads(_CACHE.read_text())
        _polys = {f["properties"]["buurtcode"]: sg.shape(f["geometry"])
                  for f in fc["features"]}
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
    return {f["properties"]["buurtcode"]: f["properties"] for f in fc["features"]}


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
