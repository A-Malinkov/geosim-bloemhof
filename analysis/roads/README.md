# analysis/roads — Road network optimization

Component 8 · owner: _<name>_ · feeds `app/modules/roads.js`

## What to produce

Write `road_metrics.json` plus `roads_<scenario>.geojson` into `data/processed/`.
Each of those files already exists as a stub containing a `_schema` block that
describes the exact shape `roads.js` expects — **read it before writing the real file**.
The app treats a stub as "no data" and shows a placeholder until you overwrite it.

## Notes

- `osmnx` 2.x and `networkx` are installed. Note the 2.x API differs from most tutorials: `ox.graph_from_point(...)`, `ox.routing.*`, `ox.stats.*`.
- Download with a buffer well beyond the study area, or edge effects will distort betweenness.
- Useful metrics: intersection density, average street length, circuity, betweenness centrality, and 15-minute walking reach.
- Export each scenario network as GeoJSON in WGS84; `roads.js` already loads and toggles it per scenario.
- "Optimization" needs a stated objective. Accessibility to what, for whom?

## Getting started

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import STUDY_AREA, PROCESSED, RAW, bbox_rd, bbox_wgs, write_processed
```
