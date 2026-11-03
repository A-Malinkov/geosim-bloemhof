#!/usr/bin/env python3
"""
fetch_knmi23.py - KNMI'23 climate scenarios for 2050, as a static JSON for the app.

Climate 2050 component, built 2026-11-03. Sits beside component 4.4 (KNMI weather)
and feeds 4.9 (scenario comparison) through design_resilience.py.

    python analysis/climate/fetch_knmi23.py               #download, parse, write
    python analysis/climate/fetch_knmi23.py --from-cache  #re-parse data/raw only, no network

Reads the KNMI'23 key-figure tables ("kerncijfers") from KNMI's official scenario
portal, klimaatscenarios-data.knmi.nl, through the JSON endpoint its own page
calls (/api/v1/climate-table-data). Three requests per location: the change
against 1991-2020 ("trend"), the future value itself ("waarde"), and the 90 %
band of natural variation of a 30-year mean ("bereik"). Locations: the national
average and the two published stations nearest Rotterdam, De Bilt (inland,
~50 km ENE) and Vlissingen (coast, ~80 km SW). Rotterdam itself is not a
location in the KNMI'23 tables, and hot-day counts exist per station only.

Writes
  data/raw/knmi23_kerncijfers_2050.json    every response as received (provenance, --from-cache)
  data/processed/climate_knmi23.json       the indicators the app uses, parsed to numbers

Exit 2 when the portal does not answer or a core indicator is missing: the app
then keeps the previous file rather than showing half a table.

Limits. These are 30-year means for 2036-2065 under six storylines, not a
forecast of any year or day. Values are national or for a station, not for the
design site. The portal's numbers were revised after the March 2023 user report
(De Bilt Hd summer days: 54 on the portal, 52 in the PDF, p. 63); the portal is
KNMI's maintained source, so it is used.
"""

import datetime as dt
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common.project import PROCESSED, RAW  #noqa: E402

PARAMS = {
    "api": "https://klimaatscenarios-data.knmi.nl/api/v1/climate-table-data",  #the portal's own table endpoint
    "portal": "https://klimaatscenarios-data.knmi.nl/kerncijfers",  #the page a person can check it on
    "report": ("https://cdn.knmi.nl/system/data_center_publications/files/000/071/901/original/"
               "KNMI23_klimaatscenarios_gebruikersrapport_23-03.pdf"),  #KNMI'23 user report, March 2023
    "year": "2050",  #horizon: the 30-year mean over 2036-2065
    "scenarios": ["Ld", "Ln", "Md", "Mn", "Hd", "Hn"],
    "locations": {"NLavg": "Netherlands average", "De Bilt": "De Bilt", "Vlissingen": "Vlissingen"},
    "timeout_s": 60,
    "from_cache": "--from-cache" in sys.argv,
}
RAW_PATH = RAW / "knmi23_kerncijfers_2050.json"
OUT_PATH = PROCESSED / "climate_knmi23.json"

#KNMI'23 storylines, wording checked against the user report (p. 11, p. 14)
SCENARIOS = {
    "Ld": {"emissions": "low", "variant": "dry", "label": "Low emissions, dry", "pathway": "SSP1-2.6", "core": True},
    "Ln": {"emissions": "low", "variant": "wet", "label": "Low emissions, wet", "pathway": "SSP1-2.6", "core": True},
    "Md": {"emissions": "moderate", "variant": "dry", "label": "Moderate emissions, dry", "pathway": None, "core": False},
    "Mn": {"emissions": "moderate", "variant": "wet", "label": "Moderate emissions, wet", "pathway": None, "core": False},
    "Hd": {"emissions": "high", "variant": "dry", "label": "High emissions, dry", "pathway": "SSP5-8.5", "core": True},
    "Hn": {"emissions": "high", "variant": "wet", "label": "High emissions, wet", "pathway": "SSP5-8.5", "core": True},
}

#indicators the app shows: id -> (theme, KNMI season, variable, indicator, English label, core)
#matched on KNMI's exact Dutch wording, so a renamed row fails loudly instead of vanishing
INDICATORS = {
    "t_mean_year": ("temperature", "Jaar", "Temperatuur", "gemiddelde", "Mean temperature, year", True),
    "tmax_mean_summer": ("temperature", "Zomer", "Temperatuur", "gemiddeld dagmaximum",
                         "Mean daily maximum, summer", True),
    "warmest_day": ("temperature", "Jaar", "Temperatuur", "warmste dag per jaar", "Warmest day of the year", False),
    "summer_days": ("temperature", "Jaar", "Temperatuur", "aantal zomerse dagen (max temp ≥ 25 °C)",
                    "Summer days, max ≥ 25 °C", False),
    "tropical_days": ("temperature", "Jaar", "Temperatuur", "aantal tropische dagen (max temp ≥ 30 °C)",
                      "Tropical days, max ≥ 30 °C", False),
    "days_35": ("temperature", "Jaar", "Temperatuur", "aantal dagen met max. temp. ≥ 35 °C",
                "Days with max ≥ 35 °C", False),
    "tropical_nights": ("temperature", "Jaar", "Temperatuur", "aantal tropische nachten (min temp ≥ 20 °C)",
                        "Tropical nights, min ≥ 20 °C", False),
    "p_hour_1y_summer": ("precipitation", "Zomer", "Neerslag", "uurlijkse neerslag die eens per jaar wordt overschreden",
                         "Hourly rainfall exceeded once a year, summer", True),
    "p_day_10y_summer": ("precipitation", "Zomer", "Neerslag",
                         "1-daagse neerslagsom die eens in de 10 jaar wordt overschreden",
                         "Daily rainfall exceeded once in 10 years, summer", True),
    "p_mean_summer": ("precipitation", "Zomer", "Neerslag", "gemiddelde hoeveelheid", "Rainfall, summer total", True),
    "p_mean_winter": ("precipitation", "Winter", "Neerslag", "gemiddelde hoeveelheid", "Rainfall, winter total", True),
    "p_days10_winter": ("precipitation", "Winter", "Neerslag", "aantal dagen ≥ 10 mm",
                        "Winter days with ≥ 10 mm rain", False),
    "deficit_summer": ("precipitation", "Zomer", "Droogte", "maximaal neerslagtekort april t/m september",
                       "Largest rainfall deficit, Apr-Sep (drought)", True),
}
CORE_LOCATION = "NLavg"  #every core indicator must be there, or the run fails

UNITS = {"°C": "°C", "dagen": "days", "dag": "days", "mm": "mm", "%": "%", "cm": "cm", "mm/jaar": "mm/yr",
         "W/m²": "W/m²", "m/s": "m/s", "uur": "hours"}
NUM = r"[+\-−]?\d+(?:[.,]\d+)?"  #KNMI writes a decimal comma, and sometimes a real minus sign


def to_float(s):
    #"+0,9" / "−1" / "48,0" -> float
    return float(s.replace("−", "-").replace(",", ".").replace("+", ""))


def norm_unit(u):
    #KNMI's Dutch unit words -> English, unknown units kept as written
    u = (u or "").strip()
    return UNITS.get(u, u) or None


def parse_cell(text):
    """One table cell -> {"value", "range", "unit"}.

    "+4 (1 – 6)%"   -> value 4, range [1, 6], unit %     (change with KNMI's uncertainty range)
    "11,1 – 11,7°C" -> value None, range [11.1, 11.7]     (a band, from the "bereik" request)
    "28 dagen"      -> value 28, unit days
    " " or None     -> all None
    """
    t = (text or "").strip()
    if not t:
        return {"value": None, "range": None, "unit": None}
    band = re.fullmatch(rf"({NUM})\s*[–-]\s*({NUM})\s*(.*)", t)
    if band and " " in t:  #"-1%" is a single negative number, a band has spaces round its dash
        return {"value": None, "range": [to_float(band[1]), to_float(band[2])], "unit": norm_unit(band[3])}
    m = re.fullmatch(rf"({NUM})\s*(?:\(\s*({NUM})\s*[–-]\s*({NUM})\s*\))?\s*(.*)", t)
    if not m:
        raise ValueError(f"unparsed KNMI cell: {text!r}")
    rng = [to_float(m[2]), to_float(m[3])] if m[2] is not None else None
    return {"value": to_float(m[1]), "range": rng, "unit": norm_unit(m[4])}


def query(location, data_type, bands=False):
    #query string the portal builds: table_variables[key][]=value (see its frontend bundle)
    q = [("table_variables[climate_variables][]", "All"), ("table_variables[seasons][]", "All")]
    q += [("table_variables[scenarios][]", s) for s in PARAMS["scenarios"]]
    q += [("table_variables[years][]", PARAMS["year"]), ("table_variables[station]", location),
          ("table_variables[data_type]", data_type)]
    if bands:
        q += [("table_variables[natural_variations][]", "bereik")]  #90 % band of a 30-year mean
    return q


def download():
    #every response, as received -> dict keyed "location|request"
    import requests
    out = {}
    for loc in PARAMS["locations"]:
        for name, dtype, bands in (("trend", "trend", False), ("waarde", "waarde", False), ("bereik", "trend", True)):
            r = requests.get(PARAMS["api"], params=query(loc, dtype, bands),
                             headers={"Accept": "application/json"}, timeout=PARAMS["timeout_s"])
            r.raise_for_status()  #406 without the Accept header, see README
            out[f"{loc}|{name}"] = r.json()
            print(f"  {loc:<11} {name:<7} {len(out[f'{loc}|{name}']['table_view']['rows'])} rows")
    return out


def columns(table):
    #column index of the reference and of each scenario in one response
    cols = table["table_view"]["columns"]["data_columns"]
    idx = {"reference": next(i for i, c in enumerate(cols) if c.startswith("Klimatologie"))}
    for i, c in enumerate(cols):
        m = re.fullmatch(rf"{PARAMS['year']} (\w\w)", c.strip())
        if m:
            idx[m[1]] = i
            if i + 1 < len(cols) and cols[i + 1].startswith("Bandbreedte"):
                idx[f"{m[1]}_band"] = i + 1  #the band column follows its scenario
    return idx


def rows_by_key(table):
    #(season, variable, indicator) -> row
    return {(r["season"], r["variable"], r["indicator"]): r for r in table["table_view"]["rows"]}


def build(raw):
    """Parsed responses -> the climate_knmi23.json document (no network, testable)."""
    locations, missing, italic_checks = {}, [], []
    for loc, loc_label in PARAMS["locations"].items():
        trend, value, band = (raw.get(f"{loc}|{k}") for k in ("trend", "waarde", "bereik"))
        if not trend or not value:
            missing.append(f"{loc}: no response")
            continue
        ci, cv = columns(trend), columns(value)
        cb = columns(band) if band else {}
        rt, rv = rows_by_key(trend), rows_by_key(value)
        rb = rows_by_key(band) if band else {}
        inds = {}
        for iid, (theme, season, var, ind, label, core) in INDICATORS.items():
            key = (season, var, ind)
            if key not in rt:
                if core and loc == CORE_LOCATION:
                    missing.append(f"{loc}: {iid} ({season} / {var} / {ind})")
                continue
            ref = parse_cell(rt[key]["data_columns"][ci["reference"]]["value"])
            scen = {}
            for s in PARAMS["scenarios"]:
                if s not in ci:
                    continue
                cell = rt[key]["data_columns"][ci[s]]
                ch = parse_cell(cell["value"])
                fut = parse_cell(rv[key]["data_columns"][cv[s]]["value"]) if key in rv and s in cv else {"value": None}
                nb = parse_cell(rb[key]["data_columns"][cb[f"{s}_band"]]["value"]) \
                    if key in rb and f"{s}_band" in cb else {"range": None}
                italic = cell.get("style") == "italic"
                scen[s] = {
                    "change": ch["value"],
                    "change_unit": ch["unit"],
                    "change_range": ch["range"],  #KNMI's own uncertainty range, extreme rainfall only
                    "future": fut["value"],  #KNMI's future value, rounded by KNMI
                    "natural_variability_30y": nb["range"],  #90 % of 30-year means fall in here
                    "within_natural_variability": italic,  #italic in KNMI's table
                }
                if nb["range"] and ref["value"] is not None:  #does italic mean "today's mean is inside the band"?
                    inside = nb["range"][0] <= ref["value"] <= nb["range"][1]
                    italic_checks.append(inside == italic)
            inds[iid] = {"theme": theme, "label": label, "knmi": {"season": season, "variable": var, "indicator": ind},
                         "unit": ref["unit"], "reference": ref["value"], "scenarios": scen}
        locations[loc] = {"label": loc_label, "indicators": inds}

    gw = {}
    t0 = raw.get(f"{CORE_LOCATION}|trend")
    if t0:  #global warming that each storyline assumes
        ci = columns(t0)
        for row in t0["table_view"].get("trend_rows", []):
            base = "1991-2020" if "1991-2020" in row["title"] else "1850-1900" if "1850-1900" in row["title"] else None
            if base:
                gw[base] = {s: parse_cell(row["data_columns"][ci[s]]["value"])["value"]
                            for s in PARAMS["scenarios"] if s in ci}

    n_ok = sum(italic_checks)
    return {
        "_written_by": "analysis/climate/fetch_knmi23.py",
        "_note": ("Official KNMI'23 climate scenarios: 30-year means for 2036-2065 against 1991-2020. "
                  "Projections under six storylines, not forecasts of any particular year or day, and not "
                  "produced by this project's models."),
        "source": {
            "publisher": "KNMI (Royal Netherlands Meteorological Institute)",
            "dataset": "KNMI'23 climate scenarios, key figures (kerncijfers)",
            "portal": PARAMS["portal"],
            "api": PARAMS["api"],
            "report": PARAMS["report"],
            "report_title": "KNMI'23 klimaatscenario's voor Nederland, gebruikersrapport (KNMI, March 2023)",
            "retrieved": None,  #set by main(), kept out of build() so a test is deterministic
        },
        "reference_period": "1991-2020",
        "horizon": {"label": PARAMS["year"], "period": "2036-2065"},
        "geographic_coverage": ("Netherlands average (temperature: De Bilt, De Kooy, Eelde, Vlissingen, Maastricht; "
                                "rainfall: 13 P13 stations) and two single stations. Rotterdam is not a KNMI'23 "
                                "location; De Bilt (inland) and Vlissingen (coast) are the nearest published stations."),
        "scenarios": {s: SCENARIOS[s] for s in PARAMS["scenarios"]},
        "global_warming_C": gw,
        "locations": locations,
        "italic_check": {"cells": len(italic_checks), "agree": n_ok,
                         "rule": "italic in KNMI's table <=> the 1991-2020 mean lies inside the 90 % band of the "
                                 "future 30-year mean (natural variability)"},
        "notes": {
            "rainfall_extremes_reference": ("Reference amounts of extreme rainfall are the STOWA 2019-19 statistics "
                                            "(user report, footnote 3); the portal bias-corrected their absolute "
                                            "values on 2026-04-22, the relative changes were not changed."),
            "moderate": "M scenarios are KNMI's supplementary moderate-emission calculations; L and H are the core four.",
            "low_same_2050_2100": "In L the warming stabilises after 2050, so KNMI gives L the same numbers for 2050 and 2100.",
        },
        "_missing": missing,
    }


def main():
    p = PARAMS
    print("KNMI'23 key figures, 2050")
    if p["from_cache"]:
        if not RAW_PATH.exists():
            print(f"  ! {RAW_PATH.relative_to(RAW.parent.parent)} missing: run without --from-cache once")
            return 2
        cache = json.loads(RAW_PATH.read_text(encoding="utf-8"))
        raw, retrieved = cache["responses"], cache["retrieved"]
    else:
        try:
            raw = download()
        except Exception as err:  #portal down or changed: keep the previous files
            print(f"  ! KNMI'23 portal did not answer ({err}); nothing written. "
                  f"Re-parse the last download with --from-cache.")
            return 2
        retrieved = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        RAW_PATH.write_text(json.dumps({"retrieved": retrieved, "api": p["api"], "responses": raw},
                                       ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  wrote {RAW_PATH.relative_to(RAW.parent.parent)}")

    doc = build(raw)
    doc["source"]["retrieved"] = retrieved
    if doc["_missing"]:
        print("  ! missing: " + "; ".join(doc["_missing"]))
        return 2
    ic = doc["italic_check"]
    print(f"  italic flag matches the natural-variability band in {ic['agree']} of {ic['cells']} cells")
    for loc, L in doc["locations"].items():
        print(f"  {L['label']:<20} {len(L['indicators'])} indicators")
    OUT_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  wrote {OUT_PATH.relative_to(PROCESSED.parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
