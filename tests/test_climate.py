#!/usr/bin/env python3
"""
test_climate.py - tests for the Climate 2050 component (analysis/climate/).

    python -m unittest tests/test_climate.py -v

Standard library unittest only, no new dependency. Runs offline: the parsing
tests use small hand-written KNMI tables, the reproducibility tests the
committed download in data/raw/ and skip when it is missing.

Covers parsing and units, scenario selection, the design indicators, the
climate-adjusted comparison, missing or incomplete inputs, and that the
short-term AI forecast (component 4.4) is untouched.
"""

import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))
sys.path.insert(0, str(ROOT / "analysis" / "climate"))

import design_resilience as dr  #noqa: E402
import fetch_knmi23 as fk  #noqa: E402

PROCESSED = ROOT / "data" / "processed"
RAW = ROOT / "data" / "raw" / "knmi23_kerncijfers_2050.json"


def load(name):
    p = PROCESSED / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


#--- a miniature KNMI table, in the portal's own shape
def table(cols, rows, trend_rows=()):
    return {"table_view": {"columns": {"legend": ["Seizoen", "Variabele", "Indicator"], "data_columns": cols},
                           "trend_rows": list(trend_rows), "rows": rows}}


def row(season, var, ind, cells):
    return {"season": season, "variable": var, "indicator": ind,
            "data_columns": [c if isinstance(c, dict) else {"value": c} for c in cells]}


SCEN = ["Ld", "Ln", "Md", "Mn", "Hd", "Hn"]
COLS = ["Klimatologie 1991-2020"] + [f"2050 {s}" for s in SCEN]
BAND_COLS = ["Klimatologie 1991-2020"] + [x for s in SCEN for x in (f"2050 {s}", "Bandbreedte 30-jaar gemiddelde")]
T_KEY = ("Jaar", "Temperatuur", "gemiddelde")
P_KEY = ("Zomer", "Neerslag", "uurlijkse neerslag die eens per jaar wordt overschreden")


def mini_raw(drop=None):
    #NLavg with two indicators; De Bilt and Vlissingen with one, so the build has something everywhere
    trend = table(COLS, [
        row(*T_KEY, ["10,5°C", "+0,9°C", "+0,9°C", "+1,2°C", "+1,1°C", "+1,6°C", "+1,5°C"]),
        row(*P_KEY, ["16 mm", "+4 (2 – 6)%", "+6 (3 – 8)%", "+5 (2 – 7)%", "+7 (4 – 10)%", "+6 (2 – 9)%",
                     {"value": "+11 (6 – 16)%"}]),
        row("Zomer", "Neerslag", "gemiddelde hoeveelheid",
            ["235 mm", {"value": "-8%"}, {"value": "-2%", "style": "italic"}, "-9%", {"value": "-2%", "style": "italic"},
             "-13%", {"value": "-5%", "style": "italic"}]),
    ], trend_rows=[{"title": "Wereldwijde temperatuurstijging ten opzichte van 1991-2020",
                    "data_columns": [{"value": None}] + [{"value": v} for v in
                                                         ["0,8°C", "0,8°C", "1,1°C", "1,1°C", "1,5°C", "1,5°C"]]}])
    value = table(COLS, [row(*T_KEY, ["10,5°C", "11,4°C", "11,4°C", "11,7°C", "11,6°C", "12,1°C", "12,0°C"]),
                         row(*P_KEY, ["16 mm", "17 mm", "17 mm", "17 mm", "17 mm", "17 mm", "18 mm"])])
    band = table(BAND_COLS, [row(*T_KEY, ["10,5°C"] + [x for v in ["+0,9°C"] * 6 for x in (v, "11,1 – 11,7°C")])])
    raw = {}
    for loc in fk.PARAMS["locations"]:
        raw[f"{loc}|trend"], raw[f"{loc}|waarde"], raw[f"{loc}|bereik"] = trend, value, band
    if drop:
        raw.pop(drop)
    return raw


class ParseCell(unittest.TestCase):
    #KNMI writes Dutch numbers and units; every shape that occurs in the 2050 table

    def test_change_with_range(self):
        self.assertEqual(fk.parse_cell("+4 (1 – 6)%"), {"value": 4.0, "range": [1.0, 6.0], "unit": "%"})
        self.assertEqual(fk.parse_cell("+24 (16 – 34) cm"), {"value": 24.0, "range": [16.0, 34.0], "unit": "cm"})

    def test_decimal_comma_and_units(self):
        self.assertEqual(fk.parse_cell("10,5°C"), {"value": 10.5, "range": None, "unit": "°C"})
        self.assertEqual(fk.parse_cell("28 dagen")["unit"], "days")
        self.assertEqual(fk.parse_cell("0,0 dagen")["value"], 0.0)
        self.assertEqual(fk.parse_cell("48,0 mm"), {"value": 48.0, "range": None, "unit": "mm"})
        self.assertEqual(fk.parse_cell("3 mm/jaar")["unit"], "mm/yr")
        self.assertEqual(fk.parse_cell("258 uur")["unit"], "hours")

    def test_signs(self):
        self.assertEqual(fk.parse_cell("-1%")["value"], -1.0)  #a negative number, not a band
        self.assertIsNone(fk.parse_cell("-1%")["range"])
        self.assertEqual(fk.parse_cell("−0,1 m/s")["value"], -0.1)  #real minus sign
        self.assertEqual(fk.parse_cell("+1,6°C")["value"], 1.6)

    def test_band(self):
        self.assertEqual(fk.parse_cell("11,1 – 11,7°C"), {"value": None, "range": [11.1, 11.7], "unit": "°C"})
        self.assertEqual(fk.parse_cell("800 – 902 mm")["range"], [800.0, 902.0])

    def test_blank_and_garbage(self):
        self.assertEqual(fk.parse_cell(" "), {"value": None, "range": None, "unit": None})
        self.assertEqual(fk.parse_cell(None)["value"], None)
        with self.assertRaises(ValueError):
            fk.parse_cell("n.v.t.")


class Build(unittest.TestCase):
    #raw responses -> climate_knmi23.json, offline

    def test_values_and_scenarios(self):
        d = fk.build(mini_raw())
        I = d["locations"]["NLavg"]["indicators"]["t_mean_year"]
        self.assertEqual(I["reference"], 10.5)
        self.assertEqual(I["unit"], "°C")
        self.assertEqual(list(I["scenarios"]), SCEN)  #every scenario offered, in KNMI's order
        self.assertEqual(I["scenarios"]["Hd"]["change"], 1.6)
        self.assertEqual(I["scenarios"]["Hd"]["future"], 12.1)
        self.assertEqual(I["scenarios"]["Hd"]["natural_variability_30y"], [11.1, 11.7])
        P = d["locations"]["NLavg"]["indicators"]["p_hour_1y_summer"]
        self.assertEqual(P["scenarios"]["Hn"]["change_unit"], "%")
        self.assertEqual(P["scenarios"]["Hn"]["change_range"], [6.0, 16.0])
        self.assertEqual(d["global_warming_C"]["1991-2020"]["Hd"], 1.5)

    def test_italic_flag(self):
        I = fk.build(mini_raw())["locations"]["NLavg"]["indicators"]["p_mean_summer"]
        self.assertTrue(I["scenarios"]["Ln"]["within_natural_variability"])
        self.assertFalse(I["scenarios"]["Hd"]["within_natural_variability"])

    def test_missing_core_indicator_is_reported(self):
        raw = mini_raw()
        raw["NLavg|trend"] = table(COLS, [r for r in raw["NLavg|trend"]["table_view"]["rows"]
                                          if (r["season"], r["variable"], r["indicator"]) != T_KEY])
        self.assertTrue(any("t_mean_year" in m for m in fk.build(raw)["_missing"]))

    def test_missing_response_is_reported(self):
        d = fk.build(mini_raw(drop="Vlissingen|trend"))
        self.assertIn("Vlissingen: no response", d["_missing"])
        self.assertNotIn("Vlissingen", d["locations"])

    def test_no_band_request_still_builds(self):
        d = fk.build(mini_raw(drop="NLavg|bereik"))
        self.assertIsNone(d["locations"]["NLavg"]["indicators"]["t_mean_year"]["scenarios"]["Hd"]["natural_variability_30y"])

    def test_build_is_deterministic(self):
        self.assertIsNone(fk.build(mini_raw())["source"]["retrieved"])


@unittest.skipUnless(RAW.exists(), "no KNMI'23 download in data/raw")
class RealDownload(unittest.TestCase):
    #the committed download, checked against figures read off the portal and the user report

    @classmethod
    def setUpClass(cls):
        cls.raw = json.loads(RAW.read_text(encoding="utf-8"))
        cls.doc = fk.build(cls.raw["responses"])

    def test_nothing_missing(self):
        self.assertEqual(self.doc["_missing"], [])

    def test_known_values(self):
        L = self.doc["locations"]
        self.assertEqual(L["NLavg"]["indicators"]["t_mean_year"]["reference"], 10.5)  #user report table 1
        self.assertEqual(L["NLavg"]["indicators"]["p_hour_1y_summer"]["reference"], 16.0)
        self.assertEqual(L["De Bilt"]["indicators"]["summer_days"]["reference"], 28.0)  #user report p. 63
        sd = L["De Bilt"]["indicators"]["summer_days"]["scenarios"]["Hd"]
        self.assertEqual(sd["future"], L["De Bilt"]["indicators"]["summer_days"]["reference"] + sd["change"])

    def test_extremes_only_national(self):
        #hot days are per station, hourly extremes national only: the app must not offer the others
        L = self.doc["locations"]
        self.assertNotIn("summer_days", L["NLavg"]["indicators"])
        self.assertNotIn("p_hour_1y_summer", L["De Bilt"]["indicators"])

    def test_italic_rule_holds(self):
        ic = self.doc["italic_check"]
        self.assertGreaterEqual(ic["agree"] / ic["cells"], 0.95)

    def test_processed_file_reproduces(self):
        out = load("climate_knmi23.json")
        self.assertIsNotNone(out)
        doc = dict(self.doc, source=dict(self.doc["source"], retrieved=self.raw["retrieved"]))
        self.assertEqual(json.loads(json.dumps(doc)), out)


class DesignMaths(unittest.TestCase):
    #the pure calculations of design_resilience.py

    def test_land_cover(self):
        lc = dr.land_cover(1000.0, 200.0, 300.0, 50.0)
        self.assertEqual(lc["sealed_m2"], 650)
        self.assertEqual(lc["paved_other_m2"], 450)
        self.assertAlmostEqual(lc["sealed_share"] + lc["unsealed_share"], 1.0)
        self.assertEqual(dr.land_cover(100.0, 10.0, 120.0, 0.0)["sealed_m2"], 0)  #never negative

    def test_storm_depth_units(self):
        self.assertAlmostEqual(dr.storm_depth(16.0, 11.0), 17.76)  #percent, not fraction
        self.assertAlmostEqual(dr.storm_depth(16.0, 0.0), 16.0)
        self.assertAlmostEqual(dr.storm_depth(48.0, -2.0), 47.04)

    def test_storm_load(self):
        s = dr.storm_load(10000.0, 2000.0, 500.0, 16.0)  #16 mm on 1 ha sealed = 160 m3
        self.assertEqual(s["runoff_m3"], 160)
        self.assertEqual(s["depth_on_green_mm"], 80)
        self.assertEqual(s["pond_rise_m"], 0.32)
        none = dr.storm_load(10000.0, 0.0, 0.0, 16.0)  #no green, no pond: no division by zero
        self.assertIsNone(none["depth_on_green_mm"])
        self.assertIsNone(none["pond_rise_m"])

    def test_home_days(self):
        self.assertEqual(dr.home_days(1000, 5.4), 5400)

    def test_canopy_union(self):
        from shapely.geometry import box
        site = box(-100, -100, 100, 100)
        one = dr.canopy_area([(0, 0, 10)], site)
        self.assertAlmostEqual(one, 78.5, delta=0.5)  #pi * 5^2
        self.assertAlmostEqual(dr.canopy_area([(0, 0, 10), (0, 0, 10)], site), one, delta=0.01)  #overlap once
        self.assertAlmostEqual(dr.canopy_area([(100, 0, 10)], site), one / 2, delta=0.5)  #clipped to the site
        self.assertEqual(dr.canopy_area([], site), 0.0)
        self.assertEqual(dr.canopy_area([(0, 0, None)], site), 0.0)  #no crown, no canopy

    def test_observed_years(self):
        recs = [{"date": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}", "T_max_C": 25.0 if i < 3 else 30.0 if i < 5 else 10.0,
                 "precipitation_mm": float(i % 7)} for i in range(336)]
        recs += [{"date": "2025-01-01", "T_max_C": 31.0, "precipitation_mm": 1.0}]  #a partial year
        y = dr.observed_years(recs, 300)
        self.assertEqual(list(y), ["2024"])  #the partial year is left out
        self.assertEqual(y["2024"]["summer_days"], 5)  #25.0 counts: thresholds are inclusive
        self.assertEqual(y["2024"]["tropical_days"], 2)
        self.assertEqual(y["2024"]["wettest_day_mm"], 6.0)


class MissingInputs(unittest.TestCase):

    def test_stub_reads_as_missing(self):
        import tempfile
        old = dr.PROCESSED
        with tempfile.TemporaryDirectory() as tmp:
            dr.PROCESSED = pathlib.Path(tmp)
            (dr.PROCESSED / "x.json").write_text('{"_status": "not_computed_yet"}', encoding="utf-8")
            try:
                self.assertIsNone(dr.J("x.json"))
                self.assertIsNone(dr.J("absent.json"))
            finally:
                dr.PROCESSED = old

    def test_main_refuses_without_projections(self):
        old = dr.J
        dr.J = lambda name: None
        try:
            self.assertEqual(dr.main(), 2)  #nothing written, the app keeps the previous file
        finally:
            dr.J = old


@unittest.skipUnless(load("climate_resilience.json"), "climate_resilience.json not computed")
class ClimateAdjusted(unittest.TestCase):
    #the committed design comparison obeys its own equations

    @classmethod
    def setUpClass(cls):
        cls.d = load("climate_resilience.json")
        cls.cmp = load("scenario_comparison.json")

    def test_runoff_equation(self):
        for sc, D in self.d["designs"].items():
            sealed = D["static"]["sealed_m2"]
            for sid, H in self.d["hazards"]["rain"].items():
                self.assertAlmostEqual(D["rain"][sid]["reference"]["runoff_m3"], sealed * H["reference_mm"] / 1000, delta=1)
                for s, v in H["scenarios"].items():
                    r = D["rain"][sid]["scenarios"][s]
                    self.assertAlmostEqual(r["runoff_m3"], sealed * v["mm"] / 1000, delta=1)
                    lo, hi = r["runoff_m3_range"]
                    self.assertLessEqual(lo, r["runoff_m3"])
                    self.assertGreaterEqual(hi, r["runoff_m3"])
                    if v["change_pct"] > 0:
                        self.assertGreater(r["extra_runoff_m3"], 0)

    def test_inputs_match_the_comparison(self):
        #one source of truth: homes, roofs and green are 4.9's numbers
        for sc, D in self.d["designs"].items():
            self.assertEqual(D["static"]["dwellings"], self.cmp[sc]["dwellings"])
            self.assertEqual(D["static"]["roof_m2"], self.cmp[sc]["footprint_m2"])
            self.assertEqual(D["static"]["green_m2"], self.cmp[sc]["green_total_m2"])

    def test_uniform_hazard_cannot_reorder(self):
        #the README's claim: the climate scales every design alike, the order comes from the designs
        rain = self.d["hazards"]["rain"]["p_hour_1y_summer"]["scenarios"]
        order = lambda s: sorted(self.d["designs"], key=lambda k: self.d["designs"][k]["rain"]["p_hour_1y_summer"]["scenarios"][s]["runoff_m3"])
        self.assertTrue(all(order(s) == order(next(iter(rain))) for s in rain))

    def test_home_days(self):
        st = self.d["hazards"]["heat"]["tropical_days"]["stations"]
        for sc, D in self.d["designs"].items():
            for s, (lo, hi) in D["heat_home_days"]["tropical_days"]["scenarios"].items():
                vals = [v["scenarios"][s] for v in st.values()]
                self.assertEqual((lo, hi), (dr.home_days(D["static"]["dwellings"], min(vals)),
                                            dr.home_days(D["static"]["dwellings"], max(vals))))

    def test_all_four_designs_and_six_scenarios(self):
        self.assertEqual(set(self.d["designs"]), {"baseline", "scenario_a", "scenario_b", "final"})
        self.assertEqual(set(self.d["hazards"]["rain"]["p_hour_1y_summer"]["scenarios"]), set(SCEN))

    def test_today_has_no_pond(self):
        self.assertIsNone(self.d["designs"]["baseline"]["rain"]["p_hour_1y_summer"]["reference"]["pond_rise_m"])


class ForecastPreserved(unittest.TestCase):
    #the short-term AI forecast (4.4) stays as it was: its output, its card and its place in the app

    def test_forecast_output_intact(self):
        fc = load("knmi_forecast.json")
        self.assertIsNotNone(fc)
        for var in ("temperature_C", "wind_speed_ms"):
            hz = fc["results"][var]["horizons"]
            self.assertEqual(set(hz), {"+1h", "+6h", "+24h"})
            for h in hz.values():
                self.assertIn("_best", h)

    def test_weather_card_still_registered(self):
        main = (ROOT / "app" / "main.js").read_text(encoding="utf-8")
        self.assertIn('["knmi", setupKnmi]', main)
        self.assertLess(main.index('["knmi", setupKnmi]'), main.index('["climate", setupClimate]'))
        self.assertIn('id: "knmi"', (ROOT / "app" / "modules" / "knmi.js").read_text(encoding="utf-8"))

    def test_climate_card_stays_separate(self):
        js = (ROOT / "app" / "modules" / "climate.js").read_text(encoding="utf-8")
        self.assertIn('id: "climate"', js)
        self.assertNotIn('id: "knmi"', js)
        self.assertNotIn("knmi_forecast", js)  #never relabels the AI forecast, never reads it
        self.assertNotIn("api.dataplatform.knmi.nl", js)  #no browser call to KNMI (CORS, see CLAUDE.md)


if __name__ == "__main__":
    unittest.main()
