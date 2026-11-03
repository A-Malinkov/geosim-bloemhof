# analysis/cbs - CBS socio-demographics

Component 6 · owner: _<name>_ · feeds `app/modules/cbs.js`

## What to produce

Write `cbs_indicators.json` into `data/processed/`.
Each of those files already exists as a stub containing a `_schema` block that
describes the exact shape `cbs.js` expects: **read it before writing the real file**.
The app treats a stub as "no data" and shows a placeholder until you overwrite it.

## Notes

- Table **86358NED** (Kerncijfers wijken en buurten 2026) is the newest; 2025 = 86165NED, 2024 = 85984NED. Older tables are useful for trends.
- The study area is **one buurt**: **BU05991081** (Bloemhof), gemeente **GM0599** (Hillesluis, BU05991082, was dropped on 2026-10-22). Compare against the gemeente and national figures: a number alone says nothing. The codes live in `STUDY_AREA.buurten` in `analysis/common/project.py`; read them from there rather than hard-coding.
- CBS OData does not reliably send CORS headers, so fetch in Python.
- CBS pads codes with spaces and uses `-99997`-style sentinels for "not applicable". Strip and filter both.
- `analysis/common/project.py` has `fetch_buurt()` for the boundary polygon, which also returns inhabitants and area.

## Getting started

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import STUDY_AREA, PROCESSED, RAW, bbox_rd, bbox_wgs, write_processed
```
