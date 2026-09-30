# analysis/scenarios — Design scenarios + proposed massing

Component 1 + 9 · owner: _<name>_ · feeds `app/modules/scenarios.js`

## What to produce

Write `design_massing.geojson` into `data/processed/`.
Each of those files already exists as a stub containing a `_schema` block that
describes the exact shape `scenarios.js` expects — **read it before writing the real file**.
The app treats a stub as "no data" and shows a placeholder until you overwrite it.

## Notes

- Minimum: **two design scenarios plus the current situation.**
- **The massing goes inside the design site**: `DESIGN_SITE` in `analysis/common/project.py` (`design_site_polygon()` gives a shapely polygon in RD New), exported to `data/processed/design_site.geojson` and shown as the "Design site" layer. 11.25 ha between Lange Hilleweg, Sandelingstraat, Dortsmondstraat/Dubbelstraat and Strevelsweg.
- Simplest route: a GeoJSON of footprints in EPSG:4326, each with `scenario`, `height_m` and `use`, optionally `base_height_m`. `scenarios.js` extrudes them and applies the +43.62 m datum shift.
- **Both heights are metres above NAP, not above the ground.** `height_m` is the roof. Ground on the site is **−0.95 m NAP**, so a 21 m tall block has `height_m: 20.05`. Leave `base_height_m` out and it defaults to that ground level; do **not** set it to 0, or the building floats about 1 m above the street.
- Richer route: model in Blender/Rhino, export glTF, upload to Cesium ion as 3D Tiles, put the asset id in `config.js`.
- To make the other components respond to your scenarios, write per-scenario outputs with matching keys (`baseline`, `scenario_a`, `scenario_b`). Every module already listens for the switch.
- For SVF and wind per scenario, burn the massing into a copy of the AHN DSM and re-run the morphology and wind scripts.

## Getting started

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import STUDY_AREA, PROCESSED, RAW, bbox_rd, bbox_wgs, write_processed
```
