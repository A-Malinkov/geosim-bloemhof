"""
analysis/common/project.py — SHARED MODULE. Coordinator-owned.

The single source of truth for the study area, coordinate systems, paths and
the height datum, mirroring app/config.js. Import it from every analysis script
so nobody hard-codes a bounding box:

    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from common.project import STUDY_AREA, PROCESSED, bbox_rd, to_rd, to_wgs

If the study area moves, change it in app/config.js AND here.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, asdict
from typing import Iterable

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
    wijk: str = "Feijenoord"
    municipality: str = "Rotterdam"
    lon: float = 4.494925          # WGS84
    lat: float = 51.895119
    rd_x: float = 93583.28         # EPSG:28992 (Amersfoort / RD New)
    rd_y: float = 434443.82
    radius_m: int = 600
    cbs_buurt: str = "BU05991081"
    cbs_gemeente: str = "GM0599"
    knmi_station: int = 344        # Rotterdam The Hague Airport

STUDY_AREA = StudyArea()

# ------------------------------------------------------------------ CRS bits
WGS84 = "EPSG:4326"
RD    = "EPSG:28992"          # Amersfoort / RD New — the Dutch national grid
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


def bbox_rd(radius_m: int | None = None) -> tuple[float, float, float, float]:
    """Square study-area bbox in RD New: (xmin, ymin, xmax, ymax)."""
    r = STUDY_AREA.radius_m if radius_m is None else radius_m
    return (STUDY_AREA.rd_x - r, STUDY_AREA.rd_y - r,
            STUDY_AREA.rd_x + r, STUDY_AREA.rd_y + r)


def bbox_wgs(radius_m: int | None = None) -> tuple[float, float, float, float]:
    """Same bbox in WGS84: (west, south, east, north)."""
    xmin, ymin, xmax, ymax = bbox_rd(radius_m)
    west, south = to_wgs(xmin, ymin)
    east, north = to_wgs(xmax, ymax)
    return (west, south, east, north)


# --------------------------------------------------------------- height datum
def nap_to_ellipsoid_offset(lon: float | None = None,
                            lat: float | None = None) -> float:
    """
    Metres to ADD to a NAP height to get a WGS84 ellipsoidal height.

    About +43.62 m at the study area. Uses the official NSGI geoid grid
    (nl_nsgi_nlgeo2018.tif), downloaded on demand by PROJ, so this needs
    network access the first time. Falls back to the constant if PROJ cannot
    get the grid — and says so.
    """
    lon = STUDY_AREA.lon if lon is None else lon
    lat = STUDY_AREA.lat if lat is None else lat
    try:
        pyproj.network.set_network_enabled(True)
        grp = pyproj.transformer.TransformerGroup(RD_NAP, WGS84_3D)
        if grp.unavailable_operations and not grp.transformers:
            raise RuntimeError("no usable transform")
        x, y = to_rd(lon, lat)
        _, _, h = grp.transformers[0].transform(x, y, 0.0)
        if abs(h) < 1.0:                       # ballpark no-op transform
            raise RuntimeError("PROJ fell back to a ballpark vertical transform")
        return round(h, 3)
    except Exception as exc:                   # pragma: no cover
        print(f"[project] geoid grid unavailable ({exc}); using the cached constant")
        return NAP_TO_ELLIPSOID_M


#: Precomputed with PROJ 9.8.1 + nl_nsgi_nlgeo2018.tif at the study centre.
NAP_TO_ELLIPSOID_M = 43.623

# ------------------------------------------------------------------- services
# Verified reachable 2026-09-21. Keep in step with app/config.js.
SERVICES = {
    "ahn_wcs":        "https://service.pdok.nl/rws/ahn/wcs/v1_0",
    "ahn_wms":        "https://service.pdok.nl/rws/ahn/wms/v1_0",
    "bag3d_tiles":    "https://data.3dbag.nl/v20250903/cesium3dtiles/lod22/tileset.json",
    "bag3d_api":      "https://api.3dbag.nl",
    "cbs_odata":      "https://opendata.cbs.nl/ODataApi/odata",
    "cbs_table":      "86358NED",
    "wijkenbuurten":  "https://service.pdok.nl/cbs/wijkenbuurten/2025/wfs/v1_0",
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
def write_processed(filename: str, payload: dict | list, *, indent: int = 2) -> pathlib.Path:
    """Write a result into data/processed/ where the web app can fetch it."""
    path = PROCESSED / filename
    path.write_text(json.dumps(payload, indent=indent, default=str) + "\n")
    print(f"[project] wrote {path.relative_to(ROOT)}")
    return path


def summary() -> str:
    a = asdict(STUDY_AREA)
    return (f"Study area: {a['name']} ({a['wijk']}), {a['municipality']}\n"
            f"  WGS84  {a['lat']:.6f}, {a['lon']:.6f}\n"
            f"  RD     {a['rd_x']:.1f}, {a['rd_y']:.1f}\n"
            f"  bbox RD {tuple(round(v,1) for v in bbox_rd())}\n"
            f"  NAP -> ellipsoid +{NAP_TO_ELLIPSOID_M} m")


if __name__ == "__main__":
    print(summary())


# ------------------------------------------------------- neighbourhood boundary
def fetch_buurt(code: str | None = None, year: int = 2025):
    """
    The CBS neighbourhood polygon, as a shapely geometry in RD New.

    Note the service quirk: PDOK's wijkenbuurten WFS ignores `cql_filter`
    and silently returns arbitrary features. It needs an OGC Filter XML,
    which is what this sends.

    Returns (geometry, properties).
    """
    import requests
    import shapely.geometry as sg

    code = code or STUDY_AREA.cbs_buurt
    url = SERVICES["wijkenbuurten"].replace("/2025/", f"/{year}/")
    params = {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": "wijkenbuurten:buurten",
        "outputFormat": "application/json",
        "srsName": "EPSG:28992",
        "filter": ("<Filter xmlns='http://www.opengis.net/fes/2.0'>"
                   "<PropertyIsEqualTo><ValueReference>buurtcode</ValueReference>"
                   f"<Literal>{code}</Literal></PropertyIsEqualTo></Filter>"),
    }
    r = requests.get(url, params=params, timeout=120)
    r.raise_for_status()
    feats = r.json().get("features", [])
    if not feats:
        raise LookupError(f"buurt {code} not found in the {year} layer")
    return sg.shape(feats[0]["geometry"]), feats[0]["properties"]
