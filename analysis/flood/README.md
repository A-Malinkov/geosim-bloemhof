# analysis/flood — flood / water vulnerability (Cyrille's QGIS analysis)

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
- Baseline only. To compare scenarios it would have to be ported to Python and
  re-run with the massing; the scoring rules above are all it needs.
