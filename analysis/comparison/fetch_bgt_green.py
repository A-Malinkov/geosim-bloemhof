#!/usr/bin/env python3
"""
fetch_bgt_green.py - today's green on the design site, from the BGT.

Component 4.9. Built 2026-10-28 for the green-area row of the scenario
comparison (compare_scenarios.py).

USAGE
-----
    python analysis/comparison/fetch_bgt_green.py

WHAT IT FETCHES
---------------
The BGT (Basisregistratie Grootschalige Topografie) through PDOK's OGC API,
over the design site's box plus 20 m:
  begroeidterreindeel    every planted surface: public green, shrubs, grass
  onbegroeidterreindeel  only class "erf": the private plot round a house, how
                         the BGT records gardens
Only current versions are kept: the API also returns retired versions (a
feature with an eind_registratie), 471 of 782 planted parts on the first page
on 2026-10-28.

OUTPUT
------
    data/raw/bgt_green_site.geojson   polygons, EPSG:28992, with class and kind
                                      ("green" or "garden")

WHAT IT CANNOT TELL YOU
-----------------------
* An erf is the whole plot, paving and sheds included, so gardens count in
  full. The final design's gardens are drawn the same way (a 5 x 18 m plot per
  house), so the two are counted alike, but both overstate the planted area.
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import RAW, SERVICES, design_site_polygon, to_wgs  # noqa: E402

PARAMS = {
    "pad_m": 20.0,  #box round the site, so a polygon crossing its outline comes whole
    "page": 1000,  #features per request, the API's maximum
}
CASES = [  #one dict per BGT collection: which classes count, and as what
    {"collection": "begroeidterreindeel", "classes": None, "kind": "green"},  #every planted class
    {"collection": "onbegroeidterreindeel", "classes": ["erf"], "kind": "garden"},  #private plots only, not paving or sand
]


def fetch(c, p):
    #every current feature of one collection in the site box -> list of GeoJSON features (lon/lat)
    x0, y0, x1, y1 = design_site_polygon().buffer(p["pad_m"]).bounds
    (w, s), (e, n) = to_wgs(x0, y0), to_wgs(x1, y1)
    url = (f"{SERVICES['bgt_ogc']}/collections/{c['collection']}/items?f=json&limit={p['page']}"
           f"&bbox={w},{s},{e},{n}")
    out, pages = [], 0
    while url:  #follow the next links: the erf collection alone runs past one page
        d = json.load(urllib.request.urlopen(url, timeout=120))
        out += d["features"]
        pages += 1
        url = next((l["href"] for l in d.get("links", []) if l["rel"] == "next"), None)
    current = [f for f in out if not f["properties"].get("eind_registratie")]  #retired versions out
    keep = [f for f in current if c["classes"] is None or f["properties"].get("fysiek_voorkomen") in c["classes"]]
    print(f"  {c['collection']}: {len(out)} features in {pages} page(s), {len(current)} current, {len(keep)} kept")
    return keep


def main() -> int:
    import geopandas as gpd
    from collections import Counter
    p = PARAMS
    print("BGT green over the design site")
    rows = []
    for c in CASES:  #one collection per case
        for f in fetch(c, p):
            rows.append({"kind": c["kind"], "class": f["properties"].get("fysiek_voorkomen"),
                         "lokaal_id": f["properties"].get("lokaal_id"), "geometry": f["geometry"]})
    g = gpd.GeoDataFrame.from_features([{"type": "Feature", "geometry": r.pop("geometry"), "properties": r}
                                        for r in rows], crs=4326).to_crs(28992)
    g = g[g.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]  #surfaces only
    site = design_site_polygon()
    on = g[g.intersects(site)]
    print("  on the site: " + ", ".join(f"{k} {n}" for k, n in Counter(on["class"]).most_common()))
    print(f"  area on the site: green {on[on.kind == 'green'].intersection(site).area.sum():,.0f} m2, "
          f"gardens {on[on.kind == 'garden'].intersection(site).area.sum():,.0f} m2")
    path = RAW / "bgt_green_site.geojson"
    g.to_file(path, driver="GeoJSON")
    print(f"  wrote {path.relative_to(RAW.parent.parent)} ({len(g)} polygons)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
