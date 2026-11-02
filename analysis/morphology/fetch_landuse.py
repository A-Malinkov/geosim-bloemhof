#!/usr/bin/env python3
"""
fetch_landuse.py - BAG verblijfsobjecten (addressable units) for Bloemhof.

Owner: Atanas Malinkov

From the PDOK BAG WFS. One point per flat, shop or office, with gebruiksdoel
(its use), oppervlakte (floor area) and status. A use and a size is what a mix
index needs. A comma-separated gebruiksdoel (a shop with a flat above) splits
its floor area equally between the uses.

We tried CBS Bestand Bodemgebruik first. Its newest edition is 2017 and it
covers the old study square with 10 polygons, too coarse to vary inside a
neighbourhood. BAG only sees buildings, so parks and streets are missing.

    python analysis/morphology/fetch_landuse.py

Writes data/raw/bag_verblijfsobjecten.geojson, points in RD New.
"""

import collections
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import RAW, STUDY_AREA, bbox_rd  #noqa: E402

WFS = "https://service.pdok.nl/lv/bag/wfs/v2_0"
PAGE = 1000                                   #the server caps a page here

#BAG gebruiksdoel -> the category we report. Keeps the plain BAG vocabulary
#rather than inventing one, so the numbers can be checked against the source.
CATEGORIES = {
    "woonfunctie": "residential",
    "winkelfunctie": "retail",
    "kantoorfunctie": "office",
    "industriefunctie": "industry",
    "onderwijsfunctie": "education",
    "gezondheidszorgfunctie": "healthcare",
    "sportfunctie": "sport",
    "logiesfunctie": "accommodation",
    "bijeenkomstfunctie": "assembly",
    "celfunctie": "detention",
    "overige gebruiksfunctie": "other",
}

#Only units that actually exist and are in use. BAG also carries planned,
#under-construction and withdrawn records, which would inflate the mix.
STATUS_KEEP = {
    "Verblijfsobject in gebruik",
    "Verblijfsobject in gebruik (niet ingemeten)",
}


def get(url, tries=4):
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers={"Accept": "application/json"}),
                    timeout=180) as r:
                return json.load(r)
        except Exception as exc:
            if attempt == tries - 1:
                raise
            print(f"    retry {attempt + 1} after {type(exc).__name__}")
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


PARAMS = {
    "pad": 0,  #extra context beyond the study-area edge, m
}


def main():
    p = PARAMS

    xmin, ymin, xmax, ymax = bbox_rd(p["pad"])
    print(f"BAG verblijfsobjecten: {STUDY_AREA.name}")

    feats, start, t0 = [], 0, time.time()
    dropped_status, dropped_area, unknown = 0, 0, collections.Counter()

    while True:
        q = urllib.parse.urlencode({
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": "bag:verblijfsobject",
            "outputFormat": "application/json",
            "srsName": "EPSG:28992",
            "count": PAGE, "startIndex": start,
            "bbox": f"{xmin:.0f},{ymin:.0f},{xmax:.0f},{ymax:.0f},"
                    f"urn:ogc:def:crs:EPSG::28992",
        })
        page = get(f"{WFS}?{q}").get("features", [])
        if not page:
            break

        for f in page:
            pr = f["properties"]
            if pr.get("status") not in STATUS_KEEP:
                dropped_status += 1
                continue
            area = pr.get("oppervlakte")
            if not area or area <= 0:
                dropped_area += 1
                continue

            raw = (pr.get("gebruiksdoel") or "").strip()
            funcs = [g.strip().lower() for g in raw.split(",") if g.strip()]
            cats = []
            for g in funcs:
                if g in CATEGORIES:
                    cats.append(CATEGORIES[g])
                else:
                    unknown[g] += 1
                    cats.append("other")
            if not cats:
                cats = ["other"]

            x, y = f["geometry"]["coordinates"][:2]
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(x, 2), round(y, 2)]},
                "properties": {
                    "id": pr.get("identificatie"),
                    "categories": cats,               #1+ per unit
                    "gebruiksdoel": raw,
                    "area_m2": float(area),
                    #a multi-function unit splits its floor area evenly
                    "area_per_category_m2": round(float(area) / len(cats), 2),
                    "bouwjaar": pr.get("bouwjaar"),
                    "pand_id": pr.get("pandidentificatie"),
                    "street": pr.get("openbare_ruimte"),
                },
            })

        start += len(page)
        print(f"    {len(feats):,} units kept, {start:,} scanned, "
              f"{time.time() - t0:.0f}s")
        if len(page) < PAGE:
            break

    out = RAW / "bag_verblijfsobjecten.geojson"
    out.write_text(json.dumps({
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::28992"}},
        "_source": "BAG via PDOK WFS (bag:verblijfsobject), public task / CC0",
        "_note": "Addressable units only: no parks, water or streets. "
                 "Multi-function units split their floor area evenly across "
                 "their categories.",
        "features": feats,
    }) + "\n")

    by_cat = collections.Counter()
    area_cat = collections.Counter()
    for f in feats:
        for c in f["properties"]["categories"]:
            by_cat[c] += 1
            area_cat[c] += f["properties"]["area_per_category_m2"]

    print(f"\n  {len(feats):,} units kept in {time.time() - t0:.0f}s "
          f"({dropped_status:,} not in use, {dropped_area:,} without floor area)")
    print(f"  wrote data/raw/{out.name}")
    if unknown:
        print(f"  ! unmapped gebruiksdoel values -> 'other': {dict(unknown)}")
    total = sum(area_cat.values())
    print(f"\n  {'category':16} {'units':>7} {'floor area':>12}  share")
    for c, a in area_cat.most_common():
        print(f"  {c:16} {by_cat[c]:7,} {a:10,.0f} m2  {100 * a / total:5.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
