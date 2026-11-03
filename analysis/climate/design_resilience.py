#!/usr/bin/env python3
"""
design_resilience.py - how today, A, B and the final design meet the KNMI'23 climate of 2050.

Climate 2050 component, built 2026-11-03. Links the official projections
(fetch_knmi23.py) to the design indicators other components already computed,
so it adds no new simulation.

    python analysis/climate/design_resilience.py

Run after fetch_knmi23.py and compare_scenarios.py (and the shadows.py runs for
21 June). Reads
  climate_knmi23.json                    KNMI'23 2050 key figures
  scenario_comparison.json               dwellings, roofs, green, water, sun, SVF per design (4.9)
  shadow_summary*_2026-06-21.json        summer shade on the site's open ground
  trees*.geojson, design_planting.geojson  crowns of kept and proposed trees
  knmi_daily_history.json                observed days at station 344, for context only
  flood_summary.json                     Cyrille's flood vulnerability, today only
and writes data/processed/climate_resilience.json.

Two hazard x design calculations, both kept deliberately simple:

  Rain. Sealed-surface runoff of a design storm
      V = A_sealed * P / 1000                    [m3]
      A_sealed = A_site - A_green - A_water      [m2]  (roofs, streets, other paving)
      P_2050  = P_ref * (1 + dP / 100)           [mm]  (KNMI'23 change, with its range)
  and where that water could go: spread over the green, d = V / A_green (mm),
  or into the pond, h = V / A_water (m). Runoff coefficient 1 on sealed ground
  and 0 on green and water: a bookkeeping proxy, not a hydrological model.

  Heat. Hot days reach every design alike, so the climate enters as exposure:
      home-days = dwellings * tropical days per year
  with the tropical days of coastal Vlissingen and inland De Bilt as a range,
  beside what each design offers against it: crown cover, green per home and
  summer shade (open ground with under 4 h direct sun on 21 June).

Limits. Every hazard is regional and uniform over the site, so it scales all
designs alike and cannot reorder them: the ranking comes from the designs,
the climate sets the size. Proposed trees cast no shade in the sun-hours run
(no analysis sees them), and gardens are counted as green, paving included
(fetch_bgt_green.py), so green and permeable shares are upper bounds. No
infiltration capacity, sewer, slope or soil is modelled. Nothing here is a
temperature: no claim of degrees of cooling is made.
"""

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common.project import PROCESSED, design_site_polygon, to_rd  #noqa: E402

SCEN = ["baseline", "scenario_a", "scenario_b", "final"]
NAME = {"baseline": "Today", "scenario_a": "Scenario A", "scenario_b": "Scenario B", "final": "Final design"}
PARAMS = {
    "storms": ["p_hour_1y_summer", "p_day_10y_summer"],  #KNMI'23 design storms, national average
    "storm_location": "NLavg",  #the only KNMI'23 location with the rainfall extremes
    "heat_stations": ["Vlissingen", "De Bilt"],  #nearest published stations, coast and inland
    "heat_days": ["tropical_days", "summer_days"],  #hot-day counts, stations only
    "shade_day": "_2026-06-21",  #summer solstice run of shadows.py
    "obs_station": 344,  #Rotterdam The Hague Airport, observed, for context
    "obs_min_days": 360,  #a year counts as complete with this many daily records
    "water_today_m2": 0,  #BGT waterdeel on the site: none (probed 2026-11-03, 1 current polygon in the box, 0 m2 on the site)
}
OUT_PATH = PROCESSED / "climate_resilience.json"


def J(name):
    #a processed JSON, or None if missing or still a stub
    p = PROCESSED / name
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    return None if isinstance(d, dict) and d.get("_status") == "not_computed_yet" else d


def sfx(sc):
    #file suffix of a scenario run, the baseline keeps the plain names
    return "" if sc == "baseline" else f"_{sc}"


#--- pure calculations, unit-tested in tests/test_climate.py
def land_cover(site_m2, roof_m2, green_m2, water_m2):
    #site split into roofs, other sealed ground, green and water (m2 and shares)
    unsealed = green_m2 + water_m2
    sealed = max(0.0, site_m2 - unsealed)
    return {
        "site_m2": round(site_m2), "roof_m2": round(roof_m2), "green_m2": round(green_m2), "water_m2": round(water_m2),
        "sealed_m2": round(sealed), "paved_other_m2": round(max(0.0, sealed - roof_m2)),
        "sealed_share": round(sealed / site_m2, 4), "green_share": round(green_m2 / site_m2, 4),
        "unsealed_share": round(unsealed / site_m2, 4),
    }


def storm_depth(ref_mm, change_pct):
    #KNMI'23 percentage change applied to the reference depth
    return ref_mm * (1 + change_pct / 100.0)


def storm_load(sealed_m2, green_m2, water_m2, p_mm):
    #runoff of one storm from sealed ground, and how deep it would stand on green or in the pond
    v = sealed_m2 * p_mm / 1000.0
    return {
        "rain_mm": round(p_mm, 2),
        "runoff_m3": round(v),
        "depth_on_green_mm": round(1000.0 * v / green_m2) if green_m2 > 0 else None,
        "pond_rise_m": round(v / water_m2, 2) if water_m2 > 0 else None,
    }


def home_days(dwellings, days):
    #exposure: homes times hot days per year
    return round(dwellings * days)


def canopy_area(discs_rd, site):
    #crown discs (x, y, crown diameter m) -> union clipped to the site, m2
    from shapely.geometry import Point
    from shapely.ops import unary_union
    if not discs_rd:
        return 0.0
    u = unary_union([Point(x, y).buffer(d / 2.0, 32) for x, y, d in discs_rd if d and d > 0])
    return u.intersection(site).area


def observed_years(records, min_days):
    #observed hot days and wettest day per complete year at one station
    by = {}
    for r in records:
        by.setdefault(r["date"][:4], []).append(r)
    out = {}
    for y, rs in sorted(by.items()):
        if len(rs) < min_days:
            continue  #partial year: counts would be too low
        tx = [r["T_max_C"] for r in rs if r.get("T_max_C") is not None]
        pr = [r["precipitation_mm"] for r in rs if r.get("precipitation_mm") is not None]
        out[y] = {"n_days": len(rs), "summer_days": sum(t >= 25.0 for t in tx), "tropical_days": sum(t >= 30.0 for t in tx),
                  "wettest_day_mm": round(max(pr), 1) if pr else None}
    return out


#--- assembling the document
def hazards(clim):
    #design storms and hot days per KNMI'23 scenario, from climate_knmi23.json
    scen = list(clim["scenarios"])
    rain = {}
    for sid in PARAMS["storms"]:
        I = clim["locations"][PARAMS["storm_location"]]["indicators"][sid]
        ref = I["reference"]
        rain[sid] = {"label": I["label"], "location": PARAMS["storm_location"], "reference_mm": ref, "scenarios": {}}
        for s in scen:
            v = I["scenarios"][s]
            rng = v["change_range"] or [v["change"], v["change"]]
            rain[sid]["scenarios"][s] = {"change_pct": v["change"], "change_range_pct": v["change_range"],
                                         "mm": round(storm_depth(ref, v["change"]), 2),
                                         "mm_range": [round(storm_depth(ref, rng[0]), 2), round(storm_depth(ref, rng[1]), 2)]}
    heat = {}
    for hid in PARAMS["heat_days"]:
        heat[hid] = {"stations": {}}
        for st in PARAMS["heat_stations"]:
            I = clim["locations"][st]["indicators"][hid]
            heat[hid]["label"] = I["label"]
            heat[hid]["stations"][st] = {"reference": I["reference"],
                                         "scenarios": {s: round(I["reference"] + I["scenarios"][s]["change"], 1) for s in scen}}
    return {"rain": rain, "heat": heat}


def crowns(sc, site):
    #crown discs of the trees standing on the site in one design: kept register trees plus proposed ones
    import shapely
    f = "trees.geojson" if sc == "baseline" else f"trees_{sc}.geojson"
    discs = []
    for t in J(f)["features"]:
        x, y = to_rd(*t["geometry"]["coordinates"][:2])
        if shapely.contains_xy(site, x, y):  #trunk on the site, as compare_scenarios.py counts them
            discs.append((x, y, t["properties"].get("crown_m")))
    n_kept = len(discs)
    for p in (J("design_planting.geojson") or {}).get("features", []):
        q = p["properties"]
        if q["scenario"] == sc and q["kind"] == "tree":
            x, y = to_rd(*p["geometry"]["coordinates"][:2])
            discs.append((x, y, q.get("crown_m")))
    return discs, n_kept


def design(sc, cmp_, hz, site):
    #static indicators and the climate-dependent loads of one design
    c = cmp_[sc]
    water = c.get("water_area_m2", PARAMS["water_today_m2"] if sc == "baseline" else 0) or 0
    lc = land_cover(site.area, c["footprint_m2"], c["green_total_m2"], water)
    discs, n_kept = crowns(sc, site)
    canopy = canopy_area(discs, site)
    sh = J(f"shadow_summary{sfx(sc)}{PARAMS['shade_day']}.json")["design_site"]["open_ground_sunlit_hours"]
    open_m2 = sh["n_pixels"]  #1 m cells
    shade_m2 = sh["share_under_4h"] * open_m2
    homes = c["dwellings"]
    static = {
        **lc,
        "dwellings": homes,
        "trees": len(discs), "trees_kept": n_kept,
        "canopy_m2": round(canopy), "canopy_share": round(canopy / site.area, 4),
        "summer_sun_mean_h": c.get("sun_mean_h_0621"),  #open ground, 21 June
        "summer_shade_share": round(sh["share_under_4h"], 4),  #open ground with under 4 h direct sun, 21 June
        "summer_shade_m2": round(shade_m2),
        "winter_dark_share": c.get("sun_under2h_1221"),  #open ground with under 2 h sun, 21 Dec
        "svf_mean": c.get("svf_mean"),
        "green_per_home_m2": round(lc["green_m2"] / homes, 1),
        "canopy_per_home_m2": round(canopy / homes, 1),
        "shade_per_home_m2": round(shade_m2 / homes, 1),
        "walk_to_4_places_m": c.get("walk_dwellings_amen_m"),  #residents, with the placed amenities
    }
    rain = {}
    for sid, H in hz["rain"].items():
        load = lambda mm: storm_load(lc["sealed_m2"], lc["green_m2"], lc["water_m2"], mm)
        rain[sid] = {"reference": load(H["reference_mm"]), "scenarios": {}}
        for s, v in H["scenarios"].items():
            r = load(v["mm"])
            lo, hi = load(v["mm_range"][0]), load(v["mm_range"][1])
            r["runoff_m3_range"] = [lo["runoff_m3"], hi["runoff_m3"]]
            r["extra_runoff_m3"] = r["runoff_m3"] - rain[sid]["reference"]["runoff_m3"]
            rain[sid]["scenarios"][s] = r
    heat = {}
    for hid, H in hz["heat"].items():
        refs = [st["reference"] for st in H["stations"].values()]
        heat[hid] = {"reference": [home_days(homes, min(refs)), home_days(homes, max(refs))], "scenarios": {}}
        for s in next(iter(H["stations"].values()))["scenarios"]:
            vals = [st["scenarios"][s] for st in H["stations"].values()]
            heat[hid]["scenarios"][s] = [home_days(homes, min(vals)), home_days(homes, max(vals))]
    return {"label": NAME[sc], "static": static, "rain": rain, "heat_home_days": heat}


def main():
    print("Design resilience to the KNMI'23 climate of 2050")
    clim, cmp_ = J("climate_knmi23.json"), J("scenario_comparison.json")
    if not clim:
        print("  ! climate_knmi23.json missing: run analysis/climate/fetch_knmi23.py")
        return 2
    if not cmp_:
        print("  ! scenario_comparison.json missing: run analysis/comparison/compare_scenarios.py")
        return 2
    site = design_site_polygon()
    hz = hazards(clim)
    designs, skipped = {}, []
    for sc in SCEN:
        if sc not in cmp_ or not J(f"shadow_summary{sfx(sc)}{PARAMS['shade_day']}.json"):
            skipped.append(sc)  #a design without its inputs is left out, not guessed
            continue
        designs[sc] = design(sc, cmp_, hz, site)
        s = designs[sc]["static"]
        print(f"  {NAME[sc]:<13} sealed {100 * s['sealed_share']:.0f} %, canopy {100 * s['canopy_share']:.1f} %, "
              f"summer shade {100 * s['summer_shade_share']:.1f} %, {s['dwellings']:,} homes")

    hist = J("knmi_daily_history.json")
    obs = None
    if hist:
        yrs = observed_years(hist["records"], PARAMS["obs_min_days"])
        n = len(yrs) or 1
        obs = {"station": hist.get("station"), "source": hist.get("source"), "years": yrs,
               "mean": {k: round(sum(v[k] for v in yrs.values()) / n, 1) for k in ("summer_days", "tropical_days")},
               "note": ("Measured at Rotterdam The Hague Airport, complete years only. A handful of years is "
                        "weather, not climate: compare with the 30-year means with care.")}
    fl = J("flood_summary.json")
    flood = {"high_or_very_high_share": cmp_["baseline"].get("flood_high"), "source": fl.get("source") if fl else None,
             "scenarios": "not computed: Cyrille's QGIS model has to be re-run per scenario"} if fl else None

    doc = {
        "_written_by": "analysis/climate/design_resilience.py",
        "_note": ("Hazard x design bookkeeping over the 13.24 ha design site. Regional KNMI'23 hazards, uniform "
                  "over the site, applied to design indicators from the other components. Not a hydrological "
                  "model and not a microclimate simulation: no temperatures are computed."),
        "method": {
            "runoff": "V = A_sealed * P / 1000 m3, A_sealed = A_site - A_green - A_water; coefficient 1 sealed, 0 green and water",
            "storm_2050": "P_2050 = P_ref * (1 + dP/100); dP and its range from KNMI'23 (national average)",
            "depth_on_green": "d = V / A_green, the runoff spread evenly over all green (a SuDS loading ratio)",
            "pond_rise": "h = V / A_water, as if the pond took all runoff",
            "home_days": "dwellings * tropical (or summer) days per year, range over Vlissingen and De Bilt",
            "canopy": "union of crown discs (diameter crown_m) of trees on the site, clipped to it",
            "summer_shade": "share of open ground with under 4 h direct sun on 21 June (shadows.py)",
        },
        "limitations": [
            "Hazards are regional and uniform over the site: they scale every design alike and cannot change their order.",
            "Proposed trees cast no shade in the sun-hours run; their crowns are counted in canopy cover only, at modelled (mature) size.",
            "Green includes gardens drawn whole, paving and all (BGT erf today, Rhino gardens in the final design): green and permeable shares are upper bounds.",
            "No infiltration capacity, soil saturation, sewer capacity, green roofs or surface slope.",
            "Register trees are municipal trees only; private trees are missing from today's canopy.",
            "Rotterdam is not a KNMI'23 location; storms are national averages, hot days come from Vlissingen and De Bilt.",
            "Flood vulnerability exists for today only.",
        ],
        "site_m2": round(site.area),
        "scenarios": clim["scenarios"],
        "horizon": clim["horizon"],
        "reference_period": clim["reference_period"],
        "hazards": hz,
        "designs": designs,
        "skipped": skipped,
        "observed": obs,
        "flood_today": flood,
    }
    OUT_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  wrote {OUT_PATH.relative_to(PROCESSED.parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
