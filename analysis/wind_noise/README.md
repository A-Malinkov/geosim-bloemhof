# analysis/wind_noise — Wind + noise simulation

Component 5 · owner: _<name>_ · feeds `app/modules/wind_noise.js`

## What to produce

Write `wind_baseline.json`, `wind_scenario_a.json`, `wind_scenario_b.json`, and the `noise_*` equivalents into `data/processed/`.
Each of those files already exists as a stub containing a `_schema` block that
describes the exact shape `wind_noise.js` expects — **read it before writing the real file**.
The app treats a stub as "no data" and shows a placeholder until you overwrite it.

## Notes

- Pedestrian level means **1.75 m above ground**, same as the SVF, so the two are comparable.
- Building geometry: 3DBAG, or the AHN nDSM if you want a raster approach.
- A full CFD solve is out of scope. A defensible alternative is a roughness/shelter model driven by the KNMI wind rose, or a simplified Lawson-criterion comparison between scenarios. **Say which you used and what it cannot tell you.**
- Noise: a road-traffic propagation model over the road network from `analysis/roads/`, with building attenuation.
- Output a regular grid plus `bbox_wgs84` so the app can drape it — see the stub in `data/processed/wind_baseline.json`.
- **Warp the grid to EPSG:4326 before taking those bounds.** RD New is rotated slightly against WGS84, so the study square's four corners do not share two longitudes. Building a lon/lat rectangle from the SW and NE corners misplaces the overlay by about 30 m — a third of a block. This bit the Sky View Factor overlay; `reproject_to_wgs84()` in `analysis/morphology/sky_view_factor.py` is the fix, reuse it.
- What matters for the report is baseline vs. design, not the absolute numbers.

## Getting started

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import STUDY_AREA, PROCESSED, RAW, bbox_rd, bbox_wgs, write_processed
```
