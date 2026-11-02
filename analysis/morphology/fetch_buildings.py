#!/usr/bin/env python3
"""
fetch_buildings.py - 3DBAG building attributes for Bloemhof.

Owner: Atanas Malinkov

From the 3DBAG OGC API (api.3dbag.nl/collections/pand/items), which serves
CityJSON in EPSG:7415. We keep one point per building with
    b3_opp_grond    ground-floor area, for GSI
    b3_bouwlagen    storeys, for FSI (null above 5 floors)
    b3_h_dak_50p    median roof, m NAP
    b3_h_maaiveld   ground at the building, m NAP
    b3_dak_type     flat or slanted
Height is roof minus the building's own ground, since ground runs from about
-2 to +8 m NAP here.

    python analysis/morphology/fetch_buildings.py

Writes data/raw/buildings_3dbag.geojson, points in RD New.
"""

import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import RAW, STUDY_AREA, bbox_rd  #noqa: E402

API = "https://api.3dbag.nl/collections/pand/items"
PAGE = 100          #the server caps a page at 100 CityObjects regardless

WANTED = ("b3_opp_grond", "b3_bouwlagen", "b3_h_dak_50p", "b3_h_dak_70p",
          "b3_h_maaiveld", "b3_dak_type", "b3_kwaliteitsindicator",
          "b3_volume_lod12", "b3_volume_lod22")


def get(url, tries=4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except Exception as exc:
            if attempt == tries - 1:
                raise
            print(f"    retry {attempt + 1} after {type(exc).__name__}")
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("unreachable")


def centroid(vertices, transform):
    #Mean of a feature's vertices, decoded through the CityJSON transform.
    if not vertices:
        return None
    sc, tl = transform["scale"], transform["translate"]
    n = len(vertices)
    sx = sum(v[0] for v in vertices) / n
    sy = sum(v[1] for v in vertices) / n
    return (sx * sc[0] + tl[0], sy * sc[1] + tl[1])


PARAMS = {
    "pad": 0,  #extra context beyond the study-area edge, m
}


def main():
    p = PARAMS

    xmin, ymin, xmax, ymax = bbox_rd(p["pad"])
    print(f"3DBAG buildings: {STUDY_AREA.name}")
    print(f"  bbox RD {xmin:.0f},{ymin:.0f},{xmax:.0f},{ymax:.0f}")

    q = urllib.parse.urlencode(
        {"bbox": f"{xmin:.0f},{ymin:.0f},{xmax:.0f},{ymax:.0f}", "limit": PAGE})
    url = f"{API}?{q}"

    feats, seen = [], set()
    total = None
    t0 = time.time()
    page = 0
    while url:
        d = get(url)
        if total is None:
            total = d.get("numberMatched")
            print(f"  {total} CityObjects to page through "
                  f"(Pand + BuildingPart, so roughly {total // 2} buildings)")
        transform = d["metadata"]["transform"]

        for f in d.get("features", []):
            pand_id = f.get("id")
            if not pand_id or pand_id in seen:
                continue
            obj = (f.get("CityObjects") or {}).get(pand_id)
            if not obj:
                continue
            attrs = obj.get("attributes") or {}
            c = centroid(f.get("vertices"), transform)
            if c is None:
                continue
            #the API pages by CityObject, so a bbox page can spill slightly
            #outside the requested box; keep the study area clean
            if not (xmin <= c[0] <= xmax and ymin <= c[1] <= ymax):
                continue
            seen.add(pand_id)

            props = {"identificatie": pand_id}
            props.update({k: attrs.get(k) for k in WANTED})
            roof, ground = attrs.get("b3_h_dak_50p"), attrs.get("b3_h_maaiveld")
            props["height_m"] = (round(roof - ground, 2)
                                 if roof is not None and ground is not None else None)
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Point",
                             "coordinates": [round(c[0], 2), round(c[1], 2)]},
                "properties": props,
            })

        page += 1
        if page % 20 == 0:
            print(f"    {len(feats)} buildings, {time.time() - t0:.0f}s")
        nxt = [l for l in d.get("links", []) if l.get("rel") == "next"]
        url = nxt[0]["href"] if nxt else None

    out = RAW / "buildings_3dbag.geojson"
    out.write_text(json.dumps({
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::28992"}},
        "_source": "3DBAG v20250903 via https://api.3dbag.nl (CC BY 4.0, TU Delft)",
        "_note": "One representative point per Pand. Footprint AREA is the exact "
                 "b3_opp_grond attribute, not derived from geometry. "
                 "height_m = b3_h_dak_50p - b3_h_maaiveld.",
        "features": feats,
    }) + "\n")

    hs = [f["properties"]["height_m"] for f in feats
          if f["properties"]["height_m"] is not None]
    no_floors = sum(1 for f in feats if not f["properties"].get("b3_bouwlagen"))
    print(f"\n  {len(feats):,} buildings in {time.time() - t0:.0f}s")
    print(f"  wrote data/raw/{out.name}")
    if hs:
        hs_sorted = sorted(hs)
        print(f"  height: median {hs_sorted[len(hs)//2]:.1f} m, "
              f"max {max(hs):.1f} m, {len(hs):,} with a height")
    print(f"  storey count missing for {no_floors:,} "
          f"({100 * no_floors / max(1, len(feats)):.0f}%): those fall back to height/3 m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
