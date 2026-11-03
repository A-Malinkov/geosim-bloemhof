/* tests/climate_app.test.mjs - logic of app/modules/climate.js, no browser needed.
 *
 *     node --test tests/climate_app.test.mjs
 *
 * Node's built-in test runner, no dependency. Pure helpers only: the DOM part
 * of the card is checked in the browser (see analysis/climate/README.md). */

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import * as C from "../app/modules/climate.js";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (f) => {
  const p = path.join(ROOT, "data", "processed", f);
  return fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, "utf8")) : null;
};
const clim = read("climate_knmi23.json");
const res = read("climate_resilience.json");

//a two-location, two-scenario miniature in the shape fetch_knmi23.py writes
const mini = {
  scenarios: { Ld: { label: "Low emissions, dry" }, Hd: { label: "High emissions, dry" }, Xx: { label: "no data" } },
  locations: {
    NLavg: { label: "Netherlands average", indicators: {
      tmax_mean_summer: { theme: "temperature", unit: "°C", reference: 21.7, label: "Tmax",
        scenarios: { Ld: { change: 1.4, change_unit: "°C" }, Hd: { change: 2.2, change_unit: "°C", natural_variability_30y: [23.4, 24.3] } } },
      p_hour_1y_summer: { theme: "precipitation", unit: "mm", reference: 16, label: "hour",
        scenarios: { Ld: { change: 4, change_unit: "%", change_range: [2, 6] }, Hd: { change: 6, change_unit: "%", within_natural_variability: true } } },
    } },
    "De Bilt": { label: "De Bilt", indicators: {
      summer_days: { theme: "temperature", unit: "days", reference: 28, label: "summer days",
        scenarios: { Ld: { change: 13, change_unit: "days" }, Hd: { change: 26, change_unit: "days" } } },
    } },
  },
};

test("units: absolute and percentage changes", () => {
  assert.equal(C.applyChange(10.5, 1.6, "°C"), 12.1);
  assert.ok(Math.abs(C.applyChange(16, 11, "%") - 17.76) < 1e-9);
  assert.equal(C.applyChange(null, 1, "°C"), null);
  assert.equal(C.applyChange(28, null, "days"), null);
  assert.equal(C.fmtVal(12.14, "°C"), "12.1 °C");
  assert.equal(C.fmtVal(54, "days"), "54 days");
  assert.equal(C.fmtVal(5.04, "days"), "5.0 days");
  assert.equal(C.fmtVal(null, "mm"), "–");
});

test("valueFor: reference, 2050, range and the natural-variability flag", () => {
  const I = mini.locations.NLavg.indicators.p_hour_1y_summer;
  assert.equal(C.valueFor(I, "reference").value, 16);
  const v = C.valueFor(I, "2050", "Ld");
  assert.ok(Math.abs(v.value - 16.64) < 1e-9);
  assert.deepEqual(v.range.map((x) => +x.toFixed(2)), [16.32, 16.96]);
  assert.equal(C.valueFor(I, "2050", "Hd").withinNatVar, true);
  assert.equal(C.valueFor(I, "2050", "Xx"), null);  //no data: nothing invented
  assert.equal(C.valueFor(undefined, "2050", "Ld"), null);
});

test("scenario selection offers only scenarios with data", () => {
  assert.deepEqual(C.availableScenarios(mini), ["Ld", "Hd"]);
  assert.deepEqual(C.availableScenarios({}), []);
  assert.equal(C.mostExtreme(mini.locations["De Bilt"].indicators.summer_days, ["Ld", "Hd"]), "Hd");
});

test("locations and indicators follow the theme", () => {
  assert.deepEqual(C.availableLocations(mini, "temperature"), ["NLavg", "De Bilt"]);
  assert.deepEqual(C.availableLocations(mini, "precipitation"), ["NLavg"]);  //hot days per station, extremes national
  assert.equal(C.defaultIndicator(mini, "De Bilt", "temperature"), "summer_days");
  assert.equal(C.defaultIndicator(mini, "De Bilt", "precipitation"), null);
  assert.equal(C.defaultIndicator(mini, "NLavg", "precipitation"), "p_hour_1y_summer");
});

test("implications: best and worst wording follows the measure, ties say nothing", () => {
  const row = (id, winter, canopy) => ({ id, static: { winter_dark_share: winter, canopy_share: canopy, summer_shade_share: 0.05,
    green_per_home_m2: 10, sealed_share: 0.5 }, heat: [1, 2] });
  const imp = C.implications([row("a", 0.9, 0.05), row("b", 0.6, 0.10)], "temperature");
  assert.ok(imp.b.plus.includes("most winter daylight"));  //least dark ground = most daylight, not the reverse
  assert.ok(imp.a.minus.includes("least winter daylight"));
  assert.ok(imp.b.plus.includes("most crown cover"));
  assert.ok(!imp.a.plus.concat(imp.b.plus).some((t) => t.includes("shade")));  //equal shade: no claim either way
});

test("missing designs and missing files", () => {
  assert.equal(C.designRow(null, "final", "Hd"), null);
  assert.equal(C.designRow({ designs: {} }, "final", "Hd"), null);
  assert.deepEqual(C.narrative(mini, { designs: {} }, "Hd", "temperature"), []);  //nothing to compare, nothing said
  assert.deepEqual(C.narrative(null, res, "Hd", "temperature"), []);
});

test("real data: every scenario and theme reads cleanly", { skip: !(clim && res) }, () => {
  for (const s of C.availableScenarios(clim)) {
    for (const th of Object.keys(C.THEMES)) {
      const lines = C.narrative(clim, res, s, th);
      assert.ok(lines.length >= 4, `${s} ${th}: too few lines`);
      for (const l of lines) assert.ok(!/NaN|undefined|null|Infinity/.test(l), `${s} ${th}: ${l}`);
      assert.ok(lines[0].includes(s), "the first line names the active scenario");
    }
  }
});

test("real data: the narrative is honest about trade-offs", { skip: !(clim && res) }, () => {
  const heat = C.narrative(clim, res, "Hd", "temperature").join(" ");
  assert.match(heat, /No design leads on everything/);  //heat measures split between the designs
  assert.match(heat, /not in the sun model/);  //the shade limit is said where shade is ranked
  assert.match(heat, /does not say how many degrees/);  //no cooling claim
  const rain = C.narrative(clim, res, "Hn", "precipitation").join(" ");
  assert.match(rain, /does not reorder them/);  //uniform hazard: honest about what 2050 changes
  assert.match(rain, /Trade-off: .* homes against .* today/);  //less sealing came with fewer homes
});

test("real data: design rows match the resilience file", { skip: !res }, () => {
  const r = C.designRow(res, "scenario_a", "Hn");
  assert.equal(r.rain.runoff_m3, res.designs.scenario_a.rain.p_hour_1y_summer.scenarios.Hn.runoff_m3);
  assert.deepEqual(r.heatRef, res.designs.scenario_a.heat_home_days.tropical_days.reference);
});
