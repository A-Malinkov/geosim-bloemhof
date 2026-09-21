# analysis/knmi — KNMI weather + AI prediction

Component 4 · owner: _<name>_ · feeds `app/modules/knmi.js`

## What to produce

Write `knmi_current.json`, `knmi_daily_history.json`, `knmi_forecast.json` into `data/processed/`.
Each of those files already exists as a stub containing a `_schema` block that
describes the exact shape `knmi.js` expects — **read it before writing the real file**.
The app treats a stub as "no data" and shows a placeholder until you overwrite it.

## Notes

KNMI has two traps — read section 5 of the top-level README before you start.

- The dataset most tutorials use (`Actueel10mindataKNMIstations` v2) **stopped updating on 2025-10-02**. Use `10-minute-in-situ-meteorological-observations` version `1.0`.
- **The browser cannot call the KNMI API** (CORS preflight). Fetch in Python, write JSON, let the app read the JSON.
- Observations are NetCDF. `xarray` is already in `requirements.txt`; you may also want `netCDF4` or `h5netcdf`.
- Historical daily data: POST to `daggegevens.knmi.nl/klimatologie/daggegevens` with `stns=344&vars=TEMP:WIND:SUNR&start=YYYYMMDD&end=YYYYMMDD&fmt=json`. Values are in 0.1 units (TG 77 = 7.7 °C).
- For the AI part, scikit-learn is installed. Say what you predict, over what horizon, and report MAE/RMSE against a held-out period — a naive "tomorrow = today" baseline is the honest thing to beat.

## Getting started

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import STUDY_AREA, PROCESSED, RAW, bbox_rd, bbox_wgs, write_processed
```
