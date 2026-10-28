#!/usr/bin/env python3
"""
compare_scenarios.py — baseline, scenario A and scenario B side by side, on the
design site (component 4.9).

Built 2026-10-27. Reads what the other components already wrote to
data/processed/ and the SVF and sun-hours rasters, so run those first.

USAGE
-----
    python analysis/comparison/compare_scenarios.py

The rasters (svf*.tif, shadow_hours*.tif) are gitignored. Rebuild them with
sky_view_factor.py and shadows.py, per scenario and day (see their docstrings).

WHAT IT DOES
------------
  indicators  one value per scenario for each indicator, every one over the
              design site (13.24 ha) unless the label says otherwise, each with
              its source file and the direction that counts as better. Some
              have no better direction (density, height, summer sun): they are
              context, shown but not coloured.
  no ranking  there is deliberately no overall score. Adding the indicators up
              needs weights, and the weights would decide the winner (the
              land-use sweep in analysis/abm_landuse/ showed how much). The
              figures show each indicator and the trade-offs instead.
  not run     wind and noise for the scenarios, and CBS demographics, have no
              results. They are listed as not computed, not left out.

OUTPUTS
-------
  data/processed/scenario_comparison.json   indicator values keyed baseline / scenario_a / scenario_b
  docs/fig_compare_scorecard.png            every indicator, coloured better / worse than today
  docs/fig_compare_tradeoff.png             homes against shade and against walking distance
  docs/fig_compare_distributions.png        sun hours (3 days) and SVF on the site's open ground
  docs/fig_compare_difference_maps.png      scenario minus today, sun hours and SVF, maps
  docs/fig_compare_walking.png              walk to each destination type
  docs/fig_compare_canyon.png               street H/W classes by street length

WHAT IT CANNOT TELL YOU
-----------------------
* Means over open ground cover different ground in each scenario, because
  demolition opens up land and new blocks cover it. Shares are given beside them.
* Dwellings in the scenarios are an estimate (road_network.py), and floor area
  uses one storey rule for every building (height / 3 m, rounded).
* No wind, noise or social indicator yet, which are the ones a jury asks about
  first for towers and main-road frontages.
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "scenarios"))
sys.path.insert(0, str(HERE.parent / "morphology"))
from common.project import PROCESSED, RAW, ROOT, design_site_polygon, to_rd  # noqa: E402

DOCS = ROOT / "docs"
SCEN = ["baseline", "scenario_a", "scenario_b", "final"]  #final: the Rhino Final Model, 2026-10-28
NAME = {"baseline": "Today", "scenario_a": "Scenario A", "scenario_b": "Scenario B", "final": "Final design"}
SHORT = {"baseline": "Today", "scenario_a": "A", "scenario_b": "B", "final": "Final"}  #column heads and dot labels

#reference palette of the dataviz skill: categorical slots 1-4 (validated, contrast WARN for 3 and 4: every mark is
#labelled by name), diverging blue/red, ink
COL = {"baseline": "#2a78d6", "scenario_a": "#eb6834", "scenario_b": "#1baf7a", "final": "#eda100"}
INK, INK2, MUTED, SURFACE, GRID = "#0b0b0b", "#52514e", "#8a8984", "#fcfcfb", "#e4e3df"
BETTER, WORSE, MID = "#2a78d6", "#e34948", "#f0efec"

STOREY_M = 3.0  #storey rule for floor area, every building in every scenario (same as road_network.py)
DAYS = [("2026-03-20", "", "Equinox, 20 Mar"), ("2026-06-21", "_2026-06-21", "Summer, 21 Jun"),
        ("2026-12-21", "_2026-12-21", "Winter, 21 Dec")]


def J(name):
    #a processed JSON, or None if missing or still a stub
    p = PROCESSED / name
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    return None if d.get("_status") == "not_computed_yet" else d


def sfx(sc):
    #file suffix of a scenario run, the baseline keeps the plain names
    return "" if sc == "baseline" else f"_{sc}"


# ------------------------------------------------------------------ indicators
def programme(sc):
    #what stands on the site: buildings, floor area, dwellings
    import geopandas as gpd
    from scenario_world import buildings_for_scenario, site_footprints
    site = design_site_polygon()
    fp = site_footprints()  #3DBAG footprints round the site, with height_m above ground
    heights = {f["properties"]["identificatie"]: f["properties"].get("height_m")
               for f in json.loads((ROOT / "cache/scenarios/footprints_site.geojson").read_text())["features"]}
    b = gpd.GeoDataFrame({"identificatie": [i for i, _ in fp], "height_m": [heights.get(i) for i, _ in fp]},
                         geometry=[g for _, g in fp], crs=28992)
    b = b[b.geometry.representative_point().within(site)]  #the site outline crosses no building
    n_today = len(b)
    b = buildings_for_scenario(b, sc)  #demolished out, new blocks in
    b = b[b.geometry.representative_point().within(site)]
    h = b["height_m"].astype(float).fillna(STOREY_M)  #a record without a height counts as one storey
    storeys = np.maximum(1, np.round(h / STOREY_M))
    foot = b.geometry.area
    massing = J("design_massing.geojson") or {}
    new = [f["properties"] for f in massing.get("features", []) if f["properties"]["scenario"] == sc]
    rm = J("road_metrics.json")
    return {
        "buildings_demolished": len((massing.get("demolishes") or {}).get(sc, [])),
        "buildings_on_site": int(len(b)),
        "new_volumes": len(new),
        "max_height_m": round(float(h.max()), 1),  #tallest building standing on the site, kept ones included
        "footprint_m2": round(float(foot.sum())),
        "gfa_m2": round(float((foot * storeys).sum())),
        "gsi": round(float(foot.sum()) / site.area, 3),
        "fsi": round(float((foot * storeys).sum()) / site.area, 3),
        "dwellings": rm[sc]["areas"]["design_site"]["dwellings"],  #BAG today, road_network.py estimate in the scenarios
        "_n_today": n_today,
    }


def daylight(sc):
    #SVF, sun hours and street canyons on the site, from the published summaries
    svf = J(f"svf_summary{sfx(sc)}.json")["design_site"]["open_ground"]
    out = {"svf_mean": svf["mean"], "svf_open_ground_cells": svf["n_pixels"]}
    for date, dsfx, _ in DAYS:
        s = J(f"shadow_summary{sfx(sc)}{dsfx}.json")["design_site"]["open_ground_sunlit_hours"]
        k = date[5:].replace("-", "")
        out[f"sun_mean_h_{k}"] = s["mean"]
        out[f"sun_under2h_{k}"] = s["share_under_2h"]
    hw = J(f"canyon_hw_{sc}.json")["design_site"]
    out.update({"hw_median": hw["hw"]["median"], "hw_h_m": hw["h_m_median"], "hw_w_m": hw["w_m_median"],
                "canyon_share": hw["canyon_share"], "street_km": hw["street_km"], "_hw_classes": hw["classes"]})
    return out


def green(sc):
    #trees standing on the site, and the proposed planting
    import shapely
    from shapely.geometry import shape
    from shapely.ops import transform
    site = design_site_polygon()
    rd = lambda g: transform(lambda x, y, z=None: to_rd(x, y), g)  #lon/lat -> RD
    f = "trees.geojson" if sc == "baseline" else f"trees_{sc}.geojson"
    pts = [to_rd(*t["geometry"]["coordinates"][:2]) for t in J(f)["features"]]
    kept = int(shapely.contains_xy(site, *np.array(pts).T).sum())
    plant = [p for p in (J("design_planting.geojson") or {}).get("features", []) if p["properties"]["scenario"] == sc]
    area = lambda kind: round(sum(rd(shape(p["geometry"])).intersection(site).area
                                  for p in plant if p["properties"]["kind"] == kind))
    new_trees = sum(1 for p in plant if p["properties"]["kind"] == "tree")
    out = {"trees_existing": kept, "trees_total": kept + new_trees, "green_total_m2": green_total(sc)}
    if sc != "baseline":  #proposed planting only exists in the designs, today's gardens are not in this count
        out.update({"trees_proposed": new_trees,  #n/a today, like the green and water areas
                    "shrubs_proposed": sum(1 for p in plant if p["properties"]["kind"] == "shrub"),
                    "green_area_m2": area("green"), "water_area_m2": area("water")})
    return out


def green_total(sc):
    #all green on the site, public and gardens in one number (Atanas, 2026-10-28), overlaps counted once:
    #today the BGT's planted surfaces plus its erf (gardens, fetch_bgt_green.py); a design keeps today's green
    #in the block it keeps and the public verges in the edge-street band, less what it builds or paves there,
    #and adds its own green patches (the final design's house gardens among them) and its walkway
    import geopandas as gpd
    from shapely.geometry import shape
    from shapely.ops import transform, unary_union
    from scenario_world import EDGE_BAND_M, cleared_area
    path = RAW / "bgt_green_site.geojson"
    if not path.exists():
        print("  ! data/raw/bgt_green_site.geojson missing: run analysis/comparison/fetch_bgt_green.py")
        return None
    site = design_site_polygon()
    bgt = gpd.read_file(path)
    if sc == "baseline":
        return round(unary_union(bgt.geometry.values).intersection(site).area)
    rd = lambda g: transform(lambda x, y, z=None: to_rd(x, y), g)  #lon/lat -> RD
    keep = site.difference(cleared_area(sc))  #the block the design leaves standing
    band = site.difference(site.buffer(-EDGE_BAND_M)).intersection(cleared_area(sc))  #edge streets and their verges
    kept = unary_union([unary_union(bgt.geometry.values).intersection(keep),
                        unary_union(bgt[bgt["kind"] == "green"].geometry.values).intersection(band)])  #no demolished house's garden
    built = [rd(shape(f["geometry"])) for f in (J("design_massing.geojson") or {}).get("features", [])
             if f["properties"]["scenario"] == sc]
    paved = [rd(shape(f["geometry"])) for f in (J("design_streets.geojson") or {}).get("features", [])
             if f["properties"]["scenario"] == sc and f["geometry"]["type"] in ("Polygon", "MultiPolygon")
             and f["properties"]["kind"] != "walkway"]
    plant = [p for p in (J("design_planting.geojson") or {}).get("features", []) if p["properties"]["scenario"] == sc]
    water = [rd(shape(p["geometry"])) for p in plant if p["properties"]["kind"] == "water"]
    kept = kept.difference(unary_union([g.buffer(0) for g in built + paved + water]))  #what the design puts on it
    new = [rd(shape(p["geometry"])) for p in plant if p["properties"]["kind"] == "green"]
    walk = [rd(shape(f["geometry"])) for f in (J("design_streets.geojson") or {}).get("features", [])
            if f["properties"]["scenario"] == sc and f["properties"]["kind"] == "walkway"]  #the final design's path, counted green
    return round(unary_union([kept] + [g.buffer(0) for g in new + walk]).intersection(site).area)


def mobility(sc):
    #walking to everyday destinations, from road_network.py and optimise_links.py
    rm = J("road_metrics.json")[sc]
    a, g = rm["areas"]["design_site"], rm["site_grid"]
    out = {"walk_dwellings_m": a["mean_of_types_m"], "walk_grid_m": g["mean_of_types_m"],
           "intersections_km2": a["intersection_density_km2"], "circuity": a["circuity"]}
    for t in ("shop", "education", "health", "rail_stop"):
        out[f"walk_{t}_m"] = a[t]["mean_m"]
        out[f"walk_grid_{t}_m"] = g[t]["mean_m"]
        out[f"near5_{t}"] = a[t]["within_5min_frac"]
    links = (J("road_links.json") or {}).get(sc) or {}
    if links.get("steps"):
        out["links_n"] = len(links["steps"])
        out["links_m"] = round(sum(s["length_m"] for s in links["steps"]))
        out["walk_grid_after_links_m"] = links["steps"][-1]["site_grid_m"]
    out["walk_grid_network_m"] = g["mean_of_types_m"]  #network only: the site's own amenities left out in every scenario
    ap = J("amenity_placement.json") or {}
    am = ap.get(sc) or {}
    own = (ap.get("baseline") or {}).get("today_with_own_amenities")
    if sc == "baseline" and own:  #today really has its shops, health and schools: count them, it is the fair today
        out["walk_dwellings_m"], out["walk_grid_m"] = own["mean_of_four"]["site_dwellings_m"], own["mean_of_four"]["site_grid_m"]
        for t in ("shop", "education", "health", "rail_stop"):
            out[f"walk_{t}_m"], out[f"walk_grid_{t}_m"] = own[t]["site_dwellings_m"], own[t]["site_grid_m"]
            out[f"walk_{t}_amen_m"], out[f"walk_grid_{t}_amen_m"] = own[t]["site_dwellings_m"], own[t]["site_grid_m"]
        out["walk_dwellings_amen_m"], out["walk_grid_amen_m"] = out["walk_dwellings_m"], out["walk_grid_m"]  #today keeps its own
    if "mean_of_four" in am:  #with the shops, health practices and school place_amenities.py puts on the ground floors
        out["walk_dwellings_amen_m"] = am["mean_of_four"]["site_dwellings_after_m"]
        out["walk_grid_amen_m"] = am["mean_of_four"]["site_grid_after_m"]
        for t in ("shop", "education", "health"):
            out[f"walk_{t}_amen_m"], out[f"walk_grid_{t}_amen_m"] = am[t]["site_dwellings_after_m"], am[t]["site_grid_after_m"]
        out["walk_rail_stop_amen_m"], out["walk_grid_rail_stop_amen_m"] = out["walk_rail_stop_m"], out["walk_grid_rail_stop_m"]  #no new stops
    elif sc != "baseline" and rm.get("with_amenities"):  #final: nothing placed, its labelled shops walked by road_network.py
        wa = rm["with_amenities"]
        a2, g2 = wa["areas"]["design_site"], wa["site_grid"]
        out["walk_dwellings_amen_m"], out["walk_grid_amen_m"] = a2["mean_of_types_m"], g2["mean_of_types_m"]
        for t in ("shop", "education", "health", "rail_stop"):
            out[f"walk_{t}_amen_m"], out[f"walk_grid_{t}_amen_m"] = a2[t]["mean_m"], g2[t]["mean_m"]
    return out


def landuse(sc):
    #the Rhino options scored on the land-use objective, if the land-use run has written them
    d = J("landuse_scenarios.json")
    s = (d or {}).get(sc) or {}
    s = s.get("open_ground_as_vacant", s)  #the rule today's grid uses, so the three are scored alike
    s = s.get("site", s.get("design_site", s))  #over the design site, like every other indicator here
    keys = {"objective": "lu_objective", "landuse_mix": "lu_mix", "green_share": "lu_green_share",
            "mean_distance_to_amenity_m": "lu_amenity_m", "residential_cells": "lu_residential_cells"}
    out = {v: s[k] for k, v in keys.items() if isinstance(s.get(k), (int, float))}
    wa = ((d or {}).get(sc) or {}).get("with_amenities", {}).get("site", {})  #the same with the placed amenities
    if "objective" in wa:
        out.update({"lu_objective_amen": wa["objective"], "lu_mix_amen": wa["landuse_mix"],
                    "lu_amenity_m_amen": wa["mean_distance_to_amenity_m"]})
    return out


def amenities(sc):
    #shops, health practices, schools and community halls on the site: today's (BAG), the options' placed + kept
    c = ((J("amenity_placement.json") or {}).get("counts_on_site") or {}).get(sc) or {}
    if not c:  #final: not placed, counted from its markers (labelled shops plus the kept block)
        feats = [f["properties"] for f in (J("design_amenities.geojson") or {}).get("features", [])
                 if f["properties"]["scenario"] == sc]
        if feats:
            c = {k: sum(1 for f in feats if f["type"] == k) for k in ("shop", "health", "education", "community")}
    return {f"n_{k}": v for k, v in c.items()}


def flood(sc):
    #Cyrille's flood vulnerability, today only
    d = J("flood_summary.json")
    if sc != "baseline" or not d:
        return {}
    sh = [l for l in d["layers"] if l["id"] == "overall"][0]["stats"]["Design site"]["shares"]
    return {"flood_high": round(sh["3"] + sh["4 high"], 3)}


#indicator metadata: key, theme, label, unit, better direction ("higher" / "lower" / None = context), digits, source
INDICATORS = [
    ("dwellings", "Programme", "Dwellings on the site", "", "higher", 0, "road_metrics.json"),
    ("buildings_demolished", "Programme", "Buildings demolished", "", "lower", 0, "design_massing.geojson"),
    ("fsi", "Programme", "FSI (floor area / site)", "", None, 2, "3DBAG + design_massing.geojson"),
    ("gsi", "Programme", "GSI (footprint / site)", "", None, 2, "3DBAG + design_massing.geojson"),
    ("max_height_m", "Programme", "Tallest building", " m", None, 0, "design_massing.geojson"),
    ("svf_mean", "Daylight", "Sky view factor, mean", "", "higher", 2, "svf_summary*.json"),
    ("sun_mean_h_0320", "Daylight", "Sun hours, equinox, mean", " h", "higher", 1, "shadow_summary*.json"),
    ("sun_under2h_0320", "Daylight", "Under 2 h sun, equinox", "%", "lower", 0, "shadow_summary*.json"),
    ("sun_under2h_1221", "Daylight", "Under 2 h sun, 21 Dec", "%", "lower", 0, "shadow_summary*_2026-12-21.json"),
    ("sun_mean_h_0621", "Daylight", "Sun hours, 21 Jun, mean", " h", None, 1, "shadow_summary*_2026-06-21.json"),
    ("hw_median", "Daylight", "Street H/W, median", "", None, 2, "canyon_hw_*.json"),
    ("trees_existing", "Green and water", "Existing trees kept", "", "higher", 0, "trees*.geojson"),  #today's trees still standing
    ("trees_proposed", "Green and water", "Proposed trees", "", "higher", 0, "design_planting.geojson"),  #new planting, not seen by SVF or sun
    ("green_total_m2", "Green and water", "Green area, total, gardens included", " m²", "higher", 0, "BGT + design_planting.geojson"),
    ("green_area_m2", "Green and water", "Proposed green area", " m²", "higher", 0, "design_planting.geojson"),
    ("water_area_m2", "Green and water", "Proposed water area", " m²", "higher", 0, "design_planting.geojson"),
    ("n_shop", "Amenities", "Shops on the site", "", "higher", 0, "amenity_placement.json"),
    ("n_health", "Amenities", "Health practices on the site", "", "higher", 0, "amenity_placement.json"),
    ("n_education", "Amenities", "Schools on the site", "", "higher", 0, "amenity_placement.json"),
    ("n_community", "Amenities", "Community halls on the site", "", "higher", 0, "amenity_placement.json"),
    ("walk_dwellings_m", "Walking", "Walk to 4 places, residents, housing only", " m", "lower", 0, "road_metrics.json + amenity_placement.json"),
    ("walk_grid_m", "Walking", "Walk to 4 places, site grid, housing only", " m", "lower", 0, "road_metrics.json + amenity_placement.json"),
    ("walk_dwellings_amen_m", "Walking", "Residents, with placed amenities", " m", "lower", 0, "amenity_placement.json"),
    ("walk_grid_amen_m", "Walking", "Site grid, with placed amenities", " m", "lower", 0, "amenity_placement.json"),
    ("walk_grid_network_m", "Walking", "Site grid, network only", " m", "lower", 0, "road_metrics.json"),
    ("walk_grid_after_links_m", "Walking", "Site grid, amenities + optimiser footpaths", " m", "lower", 0, "road_links.json"),  #the optimiser walks to the placed amenities since 2026-10-27
    ("intersections_km2", "Walking", "Intersection density", " /km²", "higher", 0, "road_metrics.json"),
    ("lu_objective", "Land use", "Land-use objective J", "", "higher", 3, "landuse_scenarios.json"),
    ("lu_mix", "Land use", "Land-use mix", "", "higher", 3, "landuse_scenarios.json"),
    ("lu_green_share", "Land use", "Green share of cells", "%", "higher", 0, "landuse_scenarios.json"),
    ("lu_objective_amen", "Land use", "Objective J, with placed amenities", "", "higher", 3, "landuse_scenarios.json"),
    ("lu_mix_amen", "Land use", "Mix, with placed amenities", "", "higher", 3, "landuse_scenarios.json"),
    ("flood_high", "Today only", "Flood vulnerability high or very high", "%", "lower", 0, "flood_summary.json"),
]
NOT_RUN = [("Wind", "pedestrian wind comfort", "OpenFOAM cases set up, not run"),
           ("Noise", "road-traffic noise, Lden", "baseline only, scenarios not run"),
           ("CBS", "socio-demographics", "not started")]
NOT_TODAY = {"green_area_m2", "water_area_m2", "walk_grid_after_links_m",  #no today value: proposed planting, optimiser
             "lu_objective_amen", "lu_mix_amen"}  #and the land use with placed amenities
PERCENT = {"sun_under2h_0320", "sun_under2h_1221", "lu_green_share", "flood_high"}


def collect():
    #every indicator for every scenario
    out = {}
    for sc in SCEN:
        v = {}
        for f in (programme, daylight, green, mobility, amenities, landuse, flood):
            v.update(f(sc))
        out[sc] = v
        print(f"  {sc}: {len(v)} values")
    return out


# --------------------------------------------------------------------- rasters
def site_open_ground(sc, res, keep_pad):
    #open ground on the design site, on the grid of the published raster: the scripts' own rule, re-applied
    from rasterio.features import geometry_mask
    from scenario_world import burn_into_rasters
    from sky_view_factor import load_raster
    dsm, transform, _ = load_raster(RAW / "ahn_dsm_05m.tif", res)
    dtm, _, _ = load_raster(RAW / "ahn_dtm_05m.tif", res)
    dsm, dtm = burn_into_rasters(dsm, dtm, transform, sc)  #demolition and new blocks, no-op for baseline
    nd = dsm - dtm
    og = np.isfinite(nd) & (nd < 2.0)  #same open-ground rule as both scripts
    pad = int(round((150 - keep_pad) / res))  #the scripts crop the context padding before writing
    og = og[pad:-pad, pad:-pad]
    tc = transform * transform.translation(pad, pad)
    site = ~geometry_mask([design_site_polygon()], out_shape=og.shape, transform=tc, invert=False)
    return og & site, tc


def site_values(c):
    #raster values on the site's open ground, checked against the published mean
    import rasterio
    out = {}
    for sc in SCEN:
        with rasterio.open(PROCESSED / c["tif"].format(s=sfx(sc))) as src:
            a = src.read(1)
        m, tc = site_open_ground(sc, c["res"], c["keep_pad"])
        assert m.shape == a.shape, (c["tif"], sc, m.shape, a.shape)
        v = a[m & np.isfinite(a)]
        pub = c["published"](sc)
        assert abs(v.mean() - pub) < 5e-4, f"{c['tif']} {sc}: raster mean {v.mean():.4f} vs published {pub}"
        out[sc] = {"values": v, "grid": np.where(m, a, np.nan), "transform": tc}
        print(f"  {c['tif'].format(s=sfx(sc))}: {v.size:,} open-ground cells on the site, mean {v.mean():.4f} = published")
    return out


RASTERS = {  #raster -> how to read it, and the published mean it must reproduce
    "svf": {"tif": "svf{s}.tif", "res": 0.5, "keep_pad": 0,
            "published": lambda sc: J(f"svf_summary{sfx(sc)}.json")["design_site"]["open_ground"]["mean"]},
    **{f"sun{dsfx}": {"tif": "shadow_hours{s}" + dsfx + ".tif", "res": 1.0, "keep_pad": 50,
                      "published": (lambda dsfx: lambda sc: J(f"shadow_summary{sfx(sc)}{dsfx}.json")
                                    ["design_site"]["open_ground_sunlit_hours"]["mean"])(dsfx)}
       for _, dsfx, _ in DAYS},
}


# ---------------------------------------------------------------------- figures
def style():
    #one light style for every figure, sized to read on a slide
    import matplotlib as mpl
    mpl.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "font.size": 11, "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
        "text.color": INK, "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "legend.frameon": False,
    })


def save(fig, name):
    #200 dpi PNG into docs/
    fig.savefig(DOCS / name, dpi=200, bbox_inches="tight")
    print(f"  wrote docs/{name}")


def fmt(v, key, unit, d):
    #a value as the scorecard prints it
    if v is None:
        return "—"
    if key in PERCENT:
        return f"{100 * v:.0f} %"
    return f"{v:,.{d}f}{unit}"


def fig_scorecard(c, data):
    #every indicator, each scenario cell shaded by how it compares with today in the indicator's better direction
    import matplotlib.pyplot as plt
    from matplotlib.colors import to_rgb
    rows = [i for i in INDICATORS if any(data[s].get(i[0]) is not None for s in SCEN)]
    themes = list(dict.fromkeys(r[1] for r in rows)) + ["Not computed"]
    lines = []  #(kind, payload) in drawing order
    for t in themes:
        lines.append(("theme", t))
        if t == "Not computed":
            lines += [("notrun", n) for n in NOT_RUN]
        else:
            lines += [("ind", r) for r in rows if r[1] == t]
    fig, ax = plt.subplots(figsize=(c["w"], 0.34 * len(lines) + 1.2))
    ax.set_xlim(0, 10); ax.set_ylim(len(lines), -1.2); ax.axis("off")
    cx = {"label": 0.0, "baseline": 4.7, "scenario_a": 5.95, "scenario_b": 7.2, "final": 8.45, "better": 9.55}
    hw = 0.6  #half a column's width
    for k in SCEN:
        ax.add_patch(plt.Rectangle((cx[k] - hw, -1.15), 2 * hw, 0.12, color=COL[k], lw=0))  #identity bar above each column
        ax.text(cx[k], -0.65, SHORT[k], ha="center", va="center", fontweight="bold")
    ax.text(cx["better"] + 0.2, -0.65, "better", ha="center", va="center", color=INK2)
    blend = lambda a, b, t: tuple((1 - t) * x + t * y for x, y in zip(to_rgb(a), to_rgb(b)))
    for y, (kind, p) in enumerate(lines):
        if kind == "theme":
            ax.text(cx["label"], y + 0.1, p.upper(), fontsize=9.5, fontweight="bold", color=INK2, va="center")
            continue
        if kind == "notrun":
            name, what, why = p
            ax.text(cx["label"] + 0.2, y + 0.1, f"{name}, {what}", va="center")
            ax.text((cx["scenario_a"] + cx["scenario_b"]) / 2, y + 0.1, why, ha="center", va="center", color=MUTED, style="italic")
            continue
        key, _, label, unit, better, d, _ = p
        ax.text(cx["label"] + 0.2, y + 0.1, label, va="center")
        base = data["baseline"].get(key)
        for s in SCEN:
            v = data[s].get(key)
            fill = MID
            if s != "baseline" and better and v is not None and base is not None:
                sign = 1 if better == "higher" else -1
                #relative change, positive = better; from zero any change counts as full
                rel = sign * (v - base) / abs(base) if base else sign * np.sign(v) * 10.0
                t = min(1.0, abs(rel) / c["full_at"])  #full colour at this relative change
                fill = blend(MID, BETTER if rel > 0 else WORSE, 0.15 + 0.6 * t) if abs(rel) >= c["min_change"] else MID
            ax.add_patch(plt.Rectangle((cx[s] - hw, y - 0.36), 2 * hw, 0.92, color=fill, lw=0))
            ax.add_patch(plt.Rectangle((cx[s] - hw, y - 0.36), 2 * hw, 0.92, fill=False, ec=SURFACE, lw=2))  #2 px gap
            ax.text(cx[s], y + 0.1, "n/a" if v is None and s == "baseline" and key in NOT_TODAY else fmt(v, key, unit, d),
                    ha="center", va="center", color=MUTED if v is None else INK)
        ax.text(cx["better"] + 0.2, y + 0.1, {"higher": "↑ higher", "lower": "↓ lower"}.get(better, "context"),
                ha="center", va="center", color=INK2 if better else MUTED, fontsize=9.5)
    ax.text(0, len(lines) + 0.2, "Shading against today: blue better, red worse, darker = bigger change "
            f"(full at ±{100 * c['full_at']:.0f} %). Grey = today, a change under {100 * c['min_change']:.0f} %, "
            "or an indicator with no better direction. "
            "All values over the 13.24 ha design site.", fontsize=9, color=INK2, va="top", wrap=True)
    ax.set_title("Today against the Rhino options and the final design, indicator by indicator", loc="left", pad=4)
    save(fig, c["out"])
    plt.close(fig)


def fig_tradeoff(c, data):
    #homes against shade, and homes against walking distance: the two trade-offs a jury will ask about
    import matplotlib.pyplot as plt
    fig, axs = plt.subplots(1, 2, figsize=(c["w"], 4.2))
    for ax, (key, title, label, pct) in zip(axs, c["panels"]):
        for s in SCEN:
            x, y = data[s]["dwellings"], data[s][key] * (100 if pct else 1)
            ax.scatter(x, y, s=110, color=COL[s], edgecolor=SURFACE, linewidth=2, zorder=3)
            arrow = bool((c.get("then") or {}).get(key))  #this panel draws the arrow to the option with its amenities
            then = "" if s == "baseline" or not c.get("then") or (s == "final" and arrow) \
                else ", without its shops" if s == "final" else ", housing only"  #walking panel: "Final" alone, B's label sits close
            below = (s == "final" and not arrow) or (s == "baseline" and arrow)  #clear of each other: final below on the shade panel, today below on the walking panel
            flip = s == "baseline" and arrow  #walking panel: today's label below-left, clear of B's arrow
            ax.annotate(SHORT[s] + then, (x, y), xytext=(-8 if flip else 8, -16 if below else 6), ha="right" if flip else "left",
                        textcoords="offset points", color=INK, fontsize=10.5)
            k2 = (c.get("then") or {}).get(key)  #the same option with the placed amenities, as a hollow dot
            if k2 and s != "baseline" and data[s].get(k2) is not None:
                y2 = data[s][k2]
                ax.annotate("", (x, y2), (x, y), arrowprops=dict(arrowstyle="->", color=COL[s], lw=1.4))
                ax.scatter(x, y2, s=110, facecolor=SURFACE, edgecolor=COL[s], linewidth=2, zorder=3)
                ax.annotate("with its shops" if s == "final" else "with amenities", (x, y2), xytext=(10, -4) if s == "final" else (8, -14),
                            textcoords="offset points", color=INK2, fontsize=10)  #final: level with its dot, clear of today's line
        b = data["baseline"]
        ax.axhline(b[key] * (100 if pct else 1), color=MUTED, lw=1, ls=(0, (4, 3)), zorder=1)  #today's level
        ax.set_xlabel("Dwellings on the design site")
        ax.set_ylabel(label)
        ax.set_title(title)
        ax.set_ylim(0, max(data[s][key] * (100 if pct else 1) for s in SCEN) * 1.2)  #from zero, so a small change looks small
        lo, hi = ax.get_xlim(); ax.set_xlim(lo - 80, hi + 220)
    fig.suptitle("More homes cost daylight in A, not in B or the final design. Shops on the ground floors shorten walks", x=0.01, ha="left",
                 fontweight="bold", fontsize=13)
    fig.tight_layout()
    save(fig, c["out"])
    plt.close(fig)


def fig_distributions(c, rasters):
    #share of the site's open ground at or below each value: sun hours on three days, and SVF
    import matplotlib.pyplot as plt
    panels = [(f"sun{dsfx}", title, "Direct sun (h)") for _, dsfx, title in DAYS] + [("svf", "Sky view factor", "SVF")]
    fig, axs = plt.subplots(1, 4, figsize=(c["w"], 3.8), sharey=True)
    for ax, (k, title, xl) in zip(axs, panels):
        for s in SCEN:
            v = np.sort(rasters[k][s]["values"])
            ax.plot(v, np.arange(1, v.size + 1) / v.size * 100, color=COL[s], lw=2, label=NAME[s])
        ax.set_title(title); ax.set_xlabel(xl)
    axs[0].set_ylabel("Share of open ground at or below (%)")
    axs[0].legend(loc="upper left")
    fig.suptitle("Open ground on the design site: a curve further right means more sun or sky",
                 x=0.01, ha="left", fontweight="bold", fontsize=13)
    fig.tight_layout()
    save(fig, c["out"])
    plt.close(fig)


def fig_difference(c, rasters):
    #scenario minus today, cell by cell where both are open ground, new blocks outlined
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    from shapely.geometry import shape
    from shapely.ops import transform as shp_t
    cmap = LinearSegmentedColormap.from_list("div", [WORSE, MID, BETTER])  #red = less, blue = more
    cmap.set_bad(SURFACE)
    site = design_site_polygon()
    massing = J("design_massing.geojson")
    cols = [("sun", "Sun hours, equinox", 6, " h"), ("sun_2026-12-21", "Sun hours, 21 Dec", 3, " h"),
            ("svf", "Sky view factor", 0.4, "")]
    designs = [s for s in SCEN if s != "baseline"]
    fig, axs = plt.subplots(len(designs), 3, figsize=(c["w"], 4.3 * len(designs)))
    x0, y0, x1, y1 = site.bounds
    for r, s in enumerate(designs):  #one row per design
        for k, (key, title, lim, unit) in enumerate(cols):
            ax = axs[r, k]
            a, b = rasters[key][s], rasters[key]["baseline"]
            t = a["transform"]
            ext = (t.c, t.c + t.a * a["grid"].shape[1], t.f + t.e * a["grid"].shape[0], t.f)
            im = ax.imshow(a["grid"] - b["grid"], cmap=cmap, vmin=-lim, vmax=lim, extent=ext, interpolation="nearest")
            for f in massing["features"]:
                if f["properties"]["scenario"] == s:
                    g = shp_t(lambda x, y, z=None: to_rd(x, y), shape(f["geometry"]))
                    for p in getattr(g, "geoms", [g]):
                        ax.fill(*p.exterior.xy, color="#c9c8c3", lw=0)  #new block
                        ax.plot(*p.exterior.xy, color=INK2, lw=0.6)
            ax.plot(*site.exterior.xy, color=INK, lw=1)
            ax.set_xlim(x0 - 10, x1 + 10); ax.set_ylim(y0 - 10, y1 + 10)
            ax.set_xticks([]); ax.set_yticks([]); ax.grid(False); ax.set_aspect("equal")
            for sp in ax.spines.values():
                sp.set_visible(False)
            ax.set_title(f"{NAME[s]}, {title[0].lower() + title[1:]}")  #"Scenario A, sun hours, 21 Dec"
            cb = fig.colorbar(im, ax=ax, shrink=0.7, pad=0.02)
            cb.set_label(f"change{unit}", color=INK2); cb.outline.set_visible(False)
    fig.suptitle("Scenario minus today on open ground: blue more, red less. Grey = new block, blank = not open ground in both",
                 x=0.01, ha="left", fontweight="bold", fontsize=12)
    fig.tight_layout()
    save(fig, c["out"])
    plt.close(fig)


def fig_walking(c, data):
    #mean walk to each destination type, residents and the fixed site grid
    import matplotlib.pyplot as plt
    types = [("shop", "Shop"), ("education", "Education"), ("health", "Health\ncare"), ("rail_stop", "Tram, metro\nor train")]
    fig, axs = plt.subplots(1, 2, figsize=(c["w"], 4.0), sharey=True)
    for ax, (pre, title) in zip(axs, [("walk_", "Residents of the site (dwelling-weighted)"),
                                       ("walk_grid_", "Fixed 20 m grid over the site")]):
        x = np.arange(len(types))
        series = [("baseline", "", "Today (its own amenities)"), ("scenario_a", "", "A, housing only"),
                  ("scenario_a", "_amen", "A, with placed amenities"), ("scenario_b", "", "B, housing only"),
                  ("scenario_b", "_amen", "B, with placed amenities"), ("final", "", "Final, without its shops"),
                  ("final", "_amen", "Final, with its labelled shops")]  #housing only solid, with amenities hatched
        series = [q for q in series if all(data[q[0]].get(f"{pre}{t}{q[1]}_m") is not None for t, _ in types)]
        w = 0.8 / len(series)
        for i, (s, suf, lab) in enumerate(series):
            vals = [data[s][f"{pre}{t}{suf}_m"] for t, _ in types]
            ax.bar(x + (i - (len(series) - 1) / 2) * w, vals, w - 0.02, zorder=3, label=lab,
                   color=SURFACE if suf else COL[s], edgecolor=COL[s], hatch="///" if suf else None, linewidth=1.2)
        ax.set_xticks(x, [l for _, l in types])
        ax.set_title(title); ax.grid(axis="x", visible=False)
    axs[0].set_ylabel("Mean walk to the nearest (m)")
    h, l = axs[0].get_legend_handles_labels()
    fig.suptitle("Walking distance to everyday places, lower is better", x=0.01, ha="left", fontweight="bold", fontsize=13)
    fig.tight_layout(rect=(0, 0.13, 1, 1))  #room below for the legend
    fig.legend(h, l, loc="lower center", ncol=4, fontsize=10)  #below the bars, so it covers none
    save(fig, c["out"])
    plt.close(fig)


def fig_canyon(c, data):
    #street length by H/W class: how enclosed the site's streets are
    import matplotlib.pyplot as plt
    classes = list(data["baseline"]["_hw_classes"])
    ramp = ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]  #sequential blue, open -> deep
    fig, ax = plt.subplots(figsize=(c["w"], 0.7 * len(SCEN) + 0.7))
    for i, s in enumerate(SCEN):
        left = 0
        for k, cl in enumerate(classes):
            v = 100 * data[s]["_hw_classes"][cl]
            ax.barh(i, v, left=left, color=ramp[k], edgecolor=SURFACE, linewidth=2,
                    label=cl if i == 0 else None, zorder=3)
            if v >= 7:
                ax.text(left + v / 2, i, f"{v:.0f}", ha="center", va="center", fontsize=9.5,
                        color=INK if k < 2 else SURFACE)
            left += v
    ax.set_yticks(range(len(SCEN)), [f"{NAME[s]}  (median {data[s]['hw_median']:.2f})" for s in SCEN])
    ax.invert_yaxis(); ax.set_xlim(0, 100); ax.grid(axis="y", visible=False)
    ax.set_xlabel("Share of canyon street length on the site (%)")
    ax.legend(title="H/W", ncol=5, loc="upper center", bbox_to_anchor=(0.5, -0.32), fontsize=9.5)
    ax.set_title("How enclosed the streets are: height of the walls over the width between them")
    save(fig, c["out"])
    plt.close(fig)


FIGURES = [  #one dict per figure: the function and its control parameters
    {"fn": fig_scorecard, "out": "fig_compare_scorecard.png", "w": 10.5, "full_at": 0.5, "min_change": 0.02},
    {"fn": fig_tradeoff, "out": "fig_compare_tradeoff.png", "w": 11,
     "panels": [("sun_under2h_0320", "Shade at the equinox, lower is better", "Open ground under 2 h sun (%)", True),
                ("walk_grid_m", "Walking, lower is better", "Mean walk to 4 everyday places, site grid (m)", False)],
     "then": {"walk_grid_m": "walk_grid_amen_m"}},  #arrow from housing only to the option with the placed amenities
    {"fn": fig_distributions, "out": "fig_compare_distributions.png", "w": 13, "rasters": True},
    {"fn": fig_difference, "out": "fig_compare_difference_maps.png", "w": 13, "rasters": True},
    {"fn": fig_walking, "out": "fig_compare_walking.png", "w": 11},
    {"fn": fig_canyon, "out": "fig_compare_canyon.png", "w": 10},
]


# ------------------------------------------------------------------------- run
def main() -> int:
    print("Scenario comparison, design site")
    data = collect()
    out = {
        "_written_by": "analysis/comparison/compare_scenarios.py",
        "_note": "Every value over the design site (13.24 ha) unless the label says otherwise. No overall score: "
                 "the indicators are not added up, because the weights would decide the ranking.",
        "storey_rule": f"storeys = max(1, round(height above ground / {STOREY_M} m)), every building in every scenario",
        "indicators": [{"key": k, "theme": t, "label": l, "unit": u, "better": b, "source": src}
                       for k, t, l, u, b, _, src in INDICATORS],
        "not_computed": [{"name": n, "what": w, "state": s} for n, w, s in NOT_RUN],
    }
    for sc in SCEN:
        out[sc] = {k: v for k, v in data[sc].items() if not k.startswith("_")}
        out[sc]["hw_classes"] = data[sc]["_hw_classes"]
    (PROCESSED / "scenario_comparison.json").write_text(json.dumps(out, indent=1) + "\n")
    print("  wrote data/processed/scenario_comparison.json")
    style()
    rasters = None
    for c in FIGURES:  #one figure per case
        if c.get("rasters"):
            if rasters is None:
                print("  reading the rasters, checking each against its published mean")
                rasters = {k: site_values(rc) for k, rc in RASTERS.items()}
            c["fn"](c, rasters)
        else:
            c["fn"](c, data)
    if not J("landuse_scenarios.json"):
        print("  ! landuse_scenarios.json missing: no land-use rows; re-run once it exists")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
