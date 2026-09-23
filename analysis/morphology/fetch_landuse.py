#!/usr/bin/env python3
"""
fetch_landuse.py — BAG verblijfsobjecten (addressable units) for the study area.

Owner: Atanas Malinkov

SOURCE
------
PDOK BAG WFS, feature type `bag:verblijfsobject`. One record per addressable
unit — a flat, a shop, an office — each with:

    gebruiksdoel   its function (woonfunctie, winkelfunctie, kantoorfunctie, ...)
    oppervlakte    usable floor area in m2
    status         whether the unit is actually in use
    geom           a point, EPSG:28992

That combination is what a land-use mix index needs: a function AND a size.
Counting units alone would let a 40 m2 studio outweigh a 5,000 m2 supermarket.

WHY NOT CBS BESTAND BODEMGEBRUIK?
---------------------------------
It is the obvious "land use" dataset, and it was tried first. It is the wrong
tool at this scale: the newest edition on PDOK is **2017**, it resolves the
whole 144 ha study square into **10 polygons of 4 categories**, and its minimum
mapping unit (~1 ha) is larger than a city block here. It would produce a
land-use mix index that cannot vary within the neighbourhood. BAG gives ten
thousand records with current functions, so the index can actually resolve where
the mix is.

The trade-off, stated plainly: BAG only covers buildings with addressable units.
Parks, water, streets and squares are absent, so this is a mix of **built floor
space**, not of land cover. Pair it with GSI from density_height.py, which is
exactly the built/unbuilt split BAG cannot see.

MULTI-FUNCTION UNITS
--------------------
`gebruiksdoel` can be comma-separated ("winkelfunctie,woonfunctie") — a shop with
a flat above it, for instance. Floor area is split equally between the listed
functions rather than dropping the record or picking the first.

USAGE
-----
    python analysis/morphology/fetch_landuse.py

OUTPUT
------
    data/raw/bag_verblijfsobjecten.geojson   points, EPSG:28992
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import RAW, STUDY_AREA, bbox_rd  # noqa: E402

WFS = "https://service.pdok.nl/lv/bag/wfs/v2_0"
PAGE = 1000                                   # the server caps a page here

#: BAG gebruiksdoel -> the category we report. Keeps the plain BAG vocabulary
#: rather than inventing one, so the numbers can be checked against the source.
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

#: Only units that actually exist and are in use. BAG also carries planned,
#: under-construction and withdrawn records, which would inflate the mix.
STATUS_KEEP = {
    "Verblijfsobject in gebruik",
    "Verblijfsobject in gebruik (niet ingemeten)",
}


def get(url: str, tries: int = 4) -> dict:
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--radius", type=int, default=STUDY_AREA.radius_m)
    args = ap.parse_args()

    xmin, ymin, xmax, ymax = bbox_rd(args.radius)
    print(f"BAG verblijfsobjecten — {STUDY_AREA.name}, radius {args.radius} m")

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
            p = f["properties"]
            if p.get("status") not in STATUS_KEEP:
                dropped_status += 1
                continue
            area = p.get("oppervlakte")
            if not area or area <= 0:
                dropped_area += 1
                continue

            raw = (p.get("gebruiksdoel") or "").strip()
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
                    "id": p.get("identificatie"),
                    "categories": cats,               # 1+ per unit
                    "gebruiksdoel": raw,
                    "area_m2": float(area),
                    # a multi-function unit splits its floor area evenly
                    "area_per_category_m2": round(float(area) / len(cats), 2),
                    "bouwjaar": p.get("bouwjaar"),
                    "pand_id": p.get("pandidentificatie"),
                    "street": p.get("openbare_ruimte"),
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
        "_note": "Addressable units only — no parks, water or streets. "
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
