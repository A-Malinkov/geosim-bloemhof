# analysis/scenarios — Design scenarios + proposed massing

Component 1 + 9 · owner: _<name>_ · feeds `app/modules/scenarios.js`

## What to produce

Write `design_massing.geojson` into `data/processed/`.
Each of those files already exists as a stub containing a `_schema` block that
describes the exact shape `scenarios.js` expects — **read it before writing the real file**.
The app treats a stub as "no data" and shows a placeholder until you overwrite it.

## Notes

- Minimum: **two design scenarios plus the current situation.**
- **The massing goes inside the design site**: `DESIGN_SITE` in `analysis/common/project.py` (`design_site_polygon()` gives a shapely polygon in RD New), exported to `data/processed/design_site.geojson` and shown as the "Design site" layer. 13.24 ha between Lange Hilleweg, Sandelingstraat, Dortsmondstraat/Dubbelstraat and Strevelsweg, since 2026-10-21 including the block between the diagonal street, Dubbelstraat and Oudelandstraat, which scenario_a keeps (`KEEP_RD` in `import_rhino.py`).
- Simplest route: a GeoJSON of footprints in EPSG:4326, each with `scenario`, `height_m` and `use`, optionally `base_height_m`. `scenarios.js` extrudes them and applies the +43.62 m datum shift.
- **Both heights are metres above NAP, not above the ground.** `height_m` is the roof. Ground on the site is **−0.93 m NAP**, so a 21 m tall block has `height_m: 20.07`. Leave `base_height_m` out and it defaults to that ground level; do **not** set it to 0, or the building floats about 1 m above the street.
- Richer route: model in Blender/Rhino, export glTF, upload to Cesium ion as 3D Tiles, put the asset id in `config.js`.
- To make the other components respond to your scenarios, write per-scenario outputs with matching keys (`baseline`, `scenario_a`, `scenario_b`). Every module already listens for the switch.
- For SVF and wind per scenario, burn the massing into a copy of the AHN DSM and re-run the morphology and wind scripts.

## Scenario A comes from the team's Rhino model

`import_rhino.py` reads the `OPTION 1` layer tree of
`Group Project Q1 - Proposal Modelling_16.10.26.3dm` (from Modelling.zip on the
shared drive, copied to `data/raw/`, gitignored) and writes it as `scenario_a`.

```bash
python analysis/scenarios/import_rhino.py
```

Fixes it applies on the way in. The model stands on NAP 0, so each block keeps
its modelled height and is stood on the site ground instead. A block left at the
model origin is dropped. Footprints are clipped to the site. Since the site
took in the block added on 2026-10-21 none is cut, and two blocks (short 2 and
short 13) reach 17 and 203 m² into that block, clear of its buildings. Heights are read from the roof faces, because rhino3dm's Brep bounding
boxes are loose. Each roof level becomes its own flat extrusion, so the stepped
tower comes in as two parts.

The file also lists, per scenario, the 3DBAG buildings the design removes
(`demolishes`, BAG pand ids). The app hides them while that massing is shown.
For scenario_a the rule is the whole site, because OPTION 1 lays a new street
grid over all of it, except the block added on 2026-10-21 (`KEEP_RD`), whose 6
buildings stay. The other rule, `overlap`, removes only what a new block
covers. Set it per case in `CASES`.

The flat surfaces on the `New ROADS` sublayer go to `design_streets.geojson`,
merged into one shape and clipped to the site. The app drapes them on the ground
while that scenario's massing is shown. Green areas and fences are not imported yet.

`scenario_world.py` turns those files into what each analysis needs: a building
table (H/W, noise), a DSM and DTM with the scenario burned in (SVF, sun hours),
and street centrelines with the old interior grid swapped for the new one (H/W).

`OPTION 2` is not imported yet. In the 16.10 model it holds one freeform volume
that reaches 18 m below ground. Add it to `CASES` as `scenario_b` once it is
modelled as solids.

## Getting started

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import STUDY_AREA, PROCESSED, RAW, bbox_rd, bbox_wgs, write_processed
```
