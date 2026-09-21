# analysis/abm_landuse — Agent-based land-use model

Component 7 · owner: _<name>_ · feeds `app/modules/landuse.js`

## What to produce

Write `landuse_abm.json` into `data/processed/`.
Each of those files already exists as a stub containing a `_schema` block that
describes the exact shape `landuse.js` expects — **read it before writing the real file**.
The app treats a stub as "no data" and shows a placeholder until you overwrite it.

## Notes

- Cellular automata or reinforcement learning — pick one and justify it.
- Suggested cell size 10 m over the study bbox (`bbox_rd()` in `common/project.py`).
- Initial state can come from BAG use codes, OSM land use, or the AHN nDSM.
- Store every time step so the app can animate the slider that is already wired up.
- Report the transition rules explicitly; an ABM whose rules are not stated cannot be assessed.

## Getting started

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import STUDY_AREA, PROCESSED, RAW, bbox_rd, bbox_wgs, write_processed
```
