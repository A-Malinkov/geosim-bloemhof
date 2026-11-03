# analysis/flood - flood / water vulnerability (Cyrille's QGIS analysis)

The analysis is Cyrille's, done in QGIS (team OneDrive: SHARED AREA / QGIS /
QGIS Files - UPDATED, 2 Oct 2026). `import_cyrille.py` does **not** recompute
it: it clips, warps and colours the rasters for the app, summarises them per
buurt and for the design site, and draws two report figures.

```bash
# 1. from the shared folder's QGIS.zip, extract into cache/flood/raw/ (gitignored):
#    BZO_NEW_{CityRisk, BuildingDensity,WaterProximity,Elevation, HazardMap,
#             WaterProximityRisk, ElevationRisk, BuildingDensity4Raster,
#             RoadsWaterProximityRisk}.tif   (76 MB each)
# 2. then:
python analysis/flood/import_cyrille.py            # ~10 s
```

Writes `data/processed/flood_<layer>.png` (overlays warped to EPSG:4326, nearest
resampling), `flood_summary.json`, `docs/fig_flood_overall.png` and
`docs/fig_flood_factors.png`. The app shows them through `app/modules/flood.js`
under **Flood vulnerability**.

## What the layers are

Checked on every cell of the rasters, not taken from file names:

- each factor is scored 1–4 (`QGIS Layer Coding.pdf`): distance to water
  (0–50 m = 4), ground level (< −0.99 m NAP = 4), buildings per cell (> 10 = 4);
- **combined** = density + water + elevation scores (100 % of cells match);
- **overall** (`CityRisk`) = combined banded at 5.25 / 7.5 / 9.75 (100 % match);
- **hazard** = water + elevation, banded (100 % match).

Design site, open ground: 61 % in overall classes 3–4 (Bloemhof 46 %).
Statistics are over Bloemhof only since 2026-10-22; the overlays still show
Cyrille's full raster, which reaches into Hillesluis. The water along Lange Hilleweg that drives the site's
water-proximity score is real: OSM has a 772 m water body there.

## Limits

- Ground level is the AHN DTM, empty under buildings, so hazard, combined and
  overall cover open ground only (62 % of cells).
- "Buildings per cell" counts buildings, not floor area or coverage, so many
  small buildings score higher than one large one.
- Today's city has all seven layers. The final design has only the new method's
  overall layer (below), which today has too. Scenario A and B have no run: the
  app's layers follow the scenario switch and show nothing (with a notice) there,
  and `flood_summary_scenario_a.json` / `_scenario_b.json` are stubs.

## The new method: today and the final design

On 2026-11-03 Cyrille sent two overall rasters made with a newer method, on the same
0.5 m grid as today's: `OverallRiskOldReclassified.tif` (today's city) and
`OverallRiskFinalMassing.tif` (the final massing). Copy both to `cache/flood/raw/`, then

```bash
python analysis/flood/import_cyrille.py --scenario baseline final
```

adds them as their own layer, `overall_new`: `flood_overall_new.png` goes into
`flood_summary.json` beside the old seven layers, and `flood_overall_new_final.png`
into `flood_summary_final.json`. A full re-import of the old layers puts today's
new-method run back when its raster is there.

The new method gives every cell a class, ground under buildings included (100 % of
Bloemhof covered against 64.5 % in the old run), so it is not the old overall layer.
Outside the design site, where both runs have a class, today and the final design
agree in all but 83 of 17.1 million cells, so the two are comparable. Class 1 is
absent on the site and covers only 65 cells in Bloemhof.

| design site, % of ground | 2 | 3 | 4 | 3–4 |
|---|---|---|---|---|
| today | 18 | 73 | 9 | 82 |
| final design | 20 | 63 | 17 | 80 |

The final design moves ground both ways: classes 3–4 fall from 82 % to 80 %, but
class 4 almost doubles. The app's flood card shows both rows, and the scenario
comparison carries the 3–4 share as `flood_high_new`. Today's old-method share
(61 % of open ground) stays as `flood_high`, today only.

## Adding a design scenario

Of the three factors, a design changes **building density** (its buildings
replace today's) and, where it adds water (the shared pond in every option,
`design_planting.geojson`), **water proximity**. Ground level is today's AHN in
every scenario. So a scenario run is Cyrille's QGIS model re-run with:

1. the scenario's buildings instead of today's: 3DBAG minus
   `design_massing.geojson`'s `demolishes[<scenario>]`, plus its blocks
   (`scenario_world.buildings_for_scenario()` gives the table in Python);
2. the scenario's water added to the water layer (the pond polygon in
   `design_planting.geojson`, `kind: water`);
3. the same scoring rules and the same raster grid as today's run.

Export the same seven `BZO_NEW_*.tif` files per scenario. `import_cyrille.py` does
not take a scenario yet: it needs a `--scenario` flag that reads them from
`cache/flood/raw_<scenario>/` and writes `flood_<layer>_<scenario>.png` and
`flood_summary_<scenario>.json` (with `"scenario": "<scenario>"`). Then `flood.js`
picks them up unchanged. Alternatively, port the three scoring rules above to
Python and compute every scenario here; that would also let the app compare
them on the same footing as density and SVF.
