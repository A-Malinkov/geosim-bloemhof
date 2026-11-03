# analysis/

Python analyses. Each subfolder belongs to one component and one person; see the
table in the top-level [README](../README.md#2-who-owns-what).

`common/project.py` is **shared**: the study area, CRS transforms, paths, service
URLs and the NAP↔ellipsoid offset live there. Import it, do not copy from it, and
route changes through the coordinator.

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import STUDY_AREA, PROCESSED, RAW, bbox_rd, bbox_wgs, fetch_buurt
```

Everything you write goes to `data/processed/` as JSON, which the app fetches.
That is the only coupling between Python and JavaScript.
