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
- **Two routes for wind — pick one and say why.** (a) A real CFD solve: OpenFOAM (simpleFoam, k-ε, atmospheric boundary-layer inlet) on a watertight STL of the site and its surroundings. TU Delft's City4CFD builds that STL from footprints + heights, and the 3DBAG API serves LoD1.2/1.3/2.2 solids per building. Heavier, but it is what the Simulation criterion rewards. (b) A roughness/shelter model driven by the KNMI wind rose, or a simplified Lawson-criterion comparison. Either way, **say which you used and what it cannot tell you.**
- Concentrate on the **design site** (`design_site.geojson`): that is where the scenarios differ. For CFD it is also a budget question — the site alone holds ~1,078 BAG buildings (every terraced house is separate), so start with LoD1.2 and a trimmed surrounding area.
- Noise: a road-traffic propagation model over the road network from `analysis/roads/`, with building attenuation.
- Output a regular grid plus `bbox_wgs84` so the app can drape it — see the stub in `data/processed/wind_baseline.json`.
- **Warp the grid to EPSG:4326 before taking those bounds.** RD New is rotated slightly against WGS84, so an RD-aligned grid's four corners do not share two longitudes. Building a lon/lat rectangle from the SW and NE corners misplaces the overlay by about 30 m — a third of a block. This bit the Sky View Factor overlay; `reproject_to_wgs84()` in `analysis/morphology/sky_view_factor.py` is the fix, reuse it.
- What matters for the report is baseline vs. design, not the absolute numbers.

## Getting started

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import STUDY_AREA, PROCESSED, RAW, bbox_rd, bbox_wgs, write_processed
```
