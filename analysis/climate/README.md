# analysis/climate - Climate 2050: design resilience

Built 2026-11-03. It links component 4.4 (KNMI weather) to 4.9 (scenario
comparison) and feeds `app/modules/climate.js`, the card **Climate 2050 — Design
Resilience**.

> Numbers here come from `data/processed/climate_knmi23.json` and
> `climate_resilience.json`. If you re-run either script, update this file and
> run `python analysis/check_docs.py`.

## Scripts

| Script | What it does | Writes |
|---|---|---|
| `fetch_knmi23.py` | downloads KNMI'23 key figures for 2050 (national average, De Bilt, Vlissingen) and parses them to numbers | `data/raw/knmi23_kerncijfers_2050.json`, `data/processed/climate_knmi23.json` |
| `design_resilience.py` | applies the 2050 hazards to the design indicators other components already computed | `data/processed/climate_resilience.json` |

```bash
python analysis/climate/fetch_knmi23.py               # ~10 s, 9 requests
python analysis/climate/fetch_knmi23.py --from-cache  # re-parse the committed download, offline
python analysis/climate/design_resilience.py          # ~5 s; after compare_scenarios.py and shadows.py
```

Tests (no new dependency):

```bash
python -m unittest tests/test_climate.py -v           # parsing, units, design maths, missing data, 4.4 intact
node --test tests/climate_app.test.mjs                # the card's logic: scenario choice, wording, narrative
```

## Two different things: forecast and scenario

| | Short-term AI forecast (4.4, `knmi.js`) | Long-term climate scenarios (this folder, `climate.js`) |
|---|---|---|
| horizon | +1, +6, +24 h | 2050, the 30-year mean of 2036–2065 |
| what | temperature and wind speed at station 344 | temperature, hot days, rainfall extremes, drought |
| made by | our models, trained on KNMI measurements 2021–2024 | KNMI, the official KNMI'23 scenarios |
| tested by | MAE against persistence and same-hour-yesterday | not testable against the future; KNMI states ranges and natural variability |
| used for | near-term monitoring | long-term design decisions |

The card says so at the top. The 2021–2025 hourly record is **not** run forward
to 2050 with the LSTM: a model fitted on five years of weather cannot produce a
climate projection. The card never calls KNMI'23 a forecast or our AI's output.

## Source

| | |
|---|---|
| publisher | KNMI (Royal Netherlands Meteorological Institute) |
| dataset | KNMI'23 climate scenarios, key figures ("kerncijfers") |
| portal | <https://klimaatscenarios-data.knmi.nl/kerncijfers> |
| endpoint | `https://klimaatscenarios-data.knmi.nl/api/v1/climate-table-data`, the JSON the portal page itself calls |
| publication | *KNMI'23 klimaatscenario's voor Nederland*, user report, March 2023 ([PDF](https://cdn.knmi.nl/system/data_center_publications/files/000/071/901/original/KNMI23_klimaatscenarios_gebruikersrapport_23-03.pdf)) |
| reference period | 1991–2020 |
| horizon | "2050" = 2036–2065, 30-year means |
| scenarios | Ld, Ln (low emissions, SSP1-2.6), Hd, Hn (high, SSP5-8.5): KNMI's core four. Md, Mn: KNMI's supplementary moderate-emission calculations. d = drier, n = wetter variant |
| coverage | national average (temperature: 5 stations, rainfall: 13 P13 stations); De Bilt and Vlissingen as single stations |
| units | °C, days per year, mm, % change |

Verified 2026-11-03: the endpoint answers JSON when asked with
`Accept: application/json` (HTTP 406 without it); the query format
`table_variables[key][]=value` was read from the portal's own JavaScript. The
scenario definitions (SSP1-2.6, SSP5-8.5), the reference period and the 2050
window are from the user report, pp. 5, 11, 14.

**Rotterdam is not a KNMI'23 location.** Hot-day counts exist per station only,
the hourly and daily rainfall extremes nationally only. So: rainfall from the
national average, hot days as a range between coastal Vlissingen (~80 km SW)
and inland De Bilt (~50 km ENE). What station 344 measured in 2021–2025 (28.6
summer days and 5.4 tropical days a year on average) is shown beside them as
observations, labelled as such: five years are weather, not a climate.

**The portal was revised after the report.** De Bilt, Hd: 54 summer days on the
portal, 52 in the March 2023 PDF (p. 63). The portal is KNMI's maintained
source and is used. The portal also notes it bias-corrected the absolute
rainfall extremes on 2026-04-22, leaving the relative changes alone.

**≈ / italics.** KNMI prints some changes in italics. The script checks what
that means against the 90 % natural-variability band of a 30-year mean (the
portal's "bereik" option): italic coincides with "the 1991–2020 mean lies inside
that band" in 165 of 168 cells, and the 3 others sit exactly on a rounded band
edge. The card marks those changes with ≈, "within natural variability".

## KNMI'23, 2050

| indicator | location | 1991–2020 | Ld | Ln | Md | Mn | Hd | Hn |
|---|---|---|---|---|---|---|---|---|
| mean temperature, year | NL | 10.5 °C | +0.9 | +0.9 | +1.2 | +1.1 | +1.6 | +1.5 |
| mean daily maximum, summer | NL | 21.7 °C | +1.4 | +1.2 | +1.6 | +1.3 | +2.2 | +1.7 |
| summer days, max ≥ 25 °C | De Bilt | 28 | 41 | 39 | 45 | 42 | 54 | 46 |
| summer days, max ≥ 25 °C | Vlissingen | 17 | 24.8 | 23.8 | 28 | 26 | 32 | 28 |
| tropical days, max ≥ 30 °C | De Bilt | 5.0 | 9.9 | 8.9 | 10.5 | 8.9 | 13.7 | 10.4 |
| tropical days, max ≥ 30 °C | Vlissingen | 2.3 | 4.0 | 3.6 | 4.6 | 3.8 | 5.9 | 4.6 |
| hourly rain exceeded once a year, summer | NL | 16 mm | +4 % (2–6) | +6 % (3–8) | +5 % (2–7) | +7 % (4–10) | +6 % (2–9) | +11 % (6–16) |
| daily rain exceeded once in 10 years, summer | NL | 48 mm | +4 % (1–6) | +5 % (2–7) | +5 % (2–7) | +6 % (3–10) | +6 % (2–9) | +9 % (5–14) |
| largest rainfall deficit Apr–Sep | NL | 160 mm | +22 % | +13 % | +25 % | +14 % | +35 % | +15 % |

Hot days are 1991–2020 + KNMI's change (KNMI's own future values are rounded,
e.g. 14 for 13.7). Ranges in brackets are KNMI's.

## Design resilience

Over the 13.24 ha design site. Inputs are 4.9's numbers
(`scenario_comparison.json`), so homes, roofs and green agree with the
comparison card. Rain in the hourly downpour exceeded once a year; heat in
tropical days. 2050 columns: Hn for rain (its largest increase), Hd for heat
(its largest).

| design | sealed | crown cover | summer shade | green per home | homes | runoff now | runoff 2050 Hn | on green, Hn | home-days ≥ 30 °C now | home-days 2050 Hd |
|---|---|---|---|---|---|---|---|---|---|---|
| Today | 70 % | 3.6 % | 5.1 % | 39 m² | 1,027 | 1,475 m³ | 1,637 m³ | 41 mm | 2,362–5,135 | 6,059–14,070 |
| Scenario A | 80 % | 5.2 % | 7.0 % | 14 m² | 1,920 | 1,691 m³ | 1,877 m³ | 72 mm | 4,416–9,600 | 11,328–26,304 |
| Scenario B | 64 % | 9.8 % | 2.5 % | 37 m² | 1,250 | 1,365 m³ | 1,515 m³ | 33 mm | 2,875–6,250 | 7,375–17,125 |
| Final design | 63 % | 7.3 % | 3.1 % | 62 m² | 777 | 1,333 m³ | 1,480 m³ | 31 mm | 1,787–3,885 | 4,584–10,645 |

What this says, and only this:

- **No design leads on everything.** The final design has the least sealed
  ground, the least runoff and the most green per home; Scenario B the most
  crown cover and the most winter daylight; Scenario A the most summer shade on
  open ground, from its taller blocks.
- **The climate cannot reorder the designs.** Every hazard here is regional and
  uniform over the site, so 2050 scales all four alike (+11 % runoff under Hn).
  It changes the size of the problem: A gains 186 m³ per downpour, the final
  design 147 m³.
- **The pond cannot buffer the site on its own.** To hold the 2050 Hn downpour
  the 671 m² pond would rise 2.2–2.8 m. Storage has to be spread over the green
  (rain gardens, wadis) and permeable paving.
- **Density and heat exposure trade off.** A houses the most people and so has
  the most home-days above 30 °C; the final design the fewest, partly because
  it builds 777 homes against 1,027 today.
- **Shade against daylight.** B keeps the most winter sun and has the least
  summer shade. Seasonal shade (deciduous trees, pergolas) over the sunniest
  open ground would serve both. This analysis does not say how many degrees any
  of it would cool.

## Equations and assumptions

| quantity | equation | assumption |
|---|---|---|
| 2050 storm depth | P₂₀₅₀ = P_ref · (1 + ΔP/100) | KNMI'23 change and range, national average |
| sealed area | A_sealed = A_site − A_green − A_water | green as 4.9 counts it (BGT today, kept + proposed green in a design); water 0 m² today (BGT waterdeel, probed 2026-11-03) |
| runoff | V = A_sealed · P / 1000 (m³) | coefficient 1 on sealed ground, 0 on green and water |
| load on green | d = V / A_green (mm) | runoff spread evenly over all green |
| pond rise | h = V / A_water (m) | the pond takes all runoff |
| crown cover | union of crown discs ∩ site / A_site | diameter `crown_m`; kept register trees + proposed trees at modelled size |
| summer shade | share of open ground with < 4 h direct sun on 21 June | shadows.py, clear sky, buildings and today's tree crowns |
| home-days | dwellings · hot days per year | range over Vlissingen and De Bilt |

## Limits and uncertainty

- Hazards are regional and uniform: they cannot rank the designs, only scale them.
- KNMI'23 is a set of six storylines, not a probability distribution: the
  scenarios are not equally likely and are not averaged.
- Proposed trees cast no shade in the sun-hours run, so the planted designs'
  summer shade is understated; their crowns count in crown cover at mature
  modelled size.
- Green includes gardens drawn whole, paving and all (`fetch_bgt_green.py`):
  green and permeable shares are upper bounds, sealed shares lower bounds.
- Runoff is bookkeeping, not hydrology: no infiltration capacity, saturated
  soil, sewer, slope, green roofs or timing.
- Register trees are municipal trees only; private trees are missing today.
- Flood vulnerability exists for today only (61 % of open ground high or very
  high); Cyrille's QGIS model has not been re-run per design.
- No temperature is computed. The card makes no claim of degrees of cooling.

## How to update

1. `python analysis/climate/fetch_knmi23.py` downloads afresh. It exits 2 and
   writes nothing if the portal does not answer or a core indicator has been
   renamed (indicators are matched on KNMI's exact Dutch wording in
   `INDICATORS`). `--from-cache` re-parses the committed download.
2. After any change to the designs, re-run `compare_scenarios.py`, then
   `python analysis/climate/design_resilience.py`.
3. Update the tables above, then `python analysis/check_docs.py`.

To add an indicator, add a line to `INDICATORS` in `fetch_knmi23.py`; the card
lists every indicator of the selected theme that has data at the selected
location, and offers no location or scenario without data.

## Where it fits in the assignment

- **4.4** asks for real-time and historical KNMI data and AI predictions with
  accuracy: that stays in the weather card, untouched. This card adds the
  *future conditions* half, from KNMI's official scenarios rather than our
  models, and says which is which.
- **4.9** compares scenarios: this adds one question to it, how each design
  meets the 2050 climate, from the same numbers.
- **Design objectives**: it gives the evidence for SuDS distributed over the
  green instead of one pond, for seasonal shade where the open layouts leave
  summer ground exposed, and for weighing density against heat exposure.

## Methodology summary for the report

> Long-term climate conditions are taken from the official KNMI'23 climate
> scenarios (KNMI, 2023), retrieved from KNMI's scenario portal for the 2050
> horizon (30-year mean 2036–2065) against the 1991–2020 reference, for all six
> storylines (Ld, Ln, Md, Mn, Hd, Hn). Rainfall extremes are national averages;
> hot-day counts are given for the nearest published stations, Vlissingen and De
> Bilt, as a range, since Rotterdam is not a KNMI'23 location. These regional
> hazards were combined with design indicators already computed for today,
> Scenario A, Scenario B and the final design on the 13.24 ha site: sealed
> area, green area, crown cover, summer shade from the direct-sun model and the
> number of homes. Runoff from sealed surfaces in the hourly downpour exceeded
> once a year was estimated as sealed area times rainfall depth (runoff
> coefficient 1 on sealed and 0 on green surfaces), and heat exposure as homes
> times tropical days per year. Because the hazards are uniform over the site,
> they scale all designs alike and do not change their order; the comparison
> therefore rests on the designs' own properties. No design performs best on all
> indicators: the final design has the least sealed ground and the most green per
> home, Scenario B the most crown cover, Scenario A the most summer shade and the
> most homes. These are bookkeeping proxies, not a hydrological or microclimate
> model, and no temperature reduction is claimed.
