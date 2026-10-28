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

## Scenarios A, B and final come from the team's Rhino model

`import_rhino.py` reads the `OPTION 1`, `OPTION 2` and `Final Model` layer trees of
`Group Project Q1 - Proposal Modelling_27.10.26.3dm` (OneDrive zip from the team,
copied to `data/raw/`, gitignored) and writes them as `scenario_a`, `scenario_b`
and `final`. OPTION 2 comes out of 27.10 exactly as it did out of 23.10. OPTION 1's
18 boxes are saved without render meshes in 27.10 and are read from their
extrusion profiles instead, which moves each footprint by at most 2 m². The
shared pond shrank from 1,082 to 671 m² in 27.10.

### The final design

The `Final Model` is built from named Rhino blocks rather than plain solids: 155
terraced houses, 8 semi-detached pairs and 8 detached houses, 31 shop podiums (4 m) each with
a block of flats on top (to 16 m), 38 terraced houses with a ground-floor shop,
two elderly homes and a student building, 284 volumes in all. The block names
give each volume its use (`BLOCK_USE` in `import_rhino.py`), so here and only
here the massing says where the shops are. The large unnamed building in the
south-west corner (2,714 m², sloping roof averaged to 19 m) is the shopping
centre, set by location in CASES `use_at_rd` (team decision 2026-10-28). Its streets, one-way roads,
pedestrian paths, bike paths and parking come in as separate surface kinds, its
92 trees, 104 solid bushes and the house gardens as planting. It keeps the same
school block as A and B. No analysis has been run on it yet: every
`*_final.json` is a stub.

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
buildings stay: a school (Dubbelstraat), two community buildings and three
sheds. scenario_b keeps the same block, the team's decision of 2026-10-23. The other rule, `overlap`, removes only what a new block
covers. Set it per case in `CASES`.

The flat surfaces on the `New ROADS` sublayer go to `design_streets.geojson`,
merged into one shape and clipped to the site. The app drapes them on the ground
while that scenario's massing is shown. Fences are not imported.

Each option's `Proposed Vegetation` sublayer goes to `design_planting.geojson`,
kept apart from the massing so that no analysis sees the proposed trees (the
team's choice for SVF and heights). For scenario_a that is
64 trees and 124 shrubs (points at the trunk, with a height and crown measured
from each block after its instance transform) and 16 green patches, 2.11 ha. All
of it lies on the site and none of it on a new block or street. Both options draw
green over the buildings they keep (about 2,000 m², mostly over the school); that
is cut away, and a plant standing in a kept building is dropped. The one surface
on the top-level `Water feature?` layer (1,082 m², in the central green by
Dubbelstraat) is imported as water and cut out of the green. It is under
neither option. The same pond is scenario_b's: it lies wholly in OPTION 2's green,
12 m clear of its blocks, so both scenarios carry it. For scenario_b the layer
holds 99 trees, 86 shrubs (85 of them drawn as 4 m solids rather than blocks,
imported as points like the rest) and 9 green patches, 4.15 ha, after the pond
and 1,693 m² of green drawn under its new streets are cut away. The
blocks are generic shapes with no species, some bushes are scaled to 7.3 m and
one scenario_b tree to 50 m with a 38 m crown, so the sizes are what was drawn,
not a planting plan. The app shows them under
Vegetation (`app/modules/vegetation.js`) on their own scenario only. No analysis
uses them yet: SVF and sun hours burn in buildings only.

`scenario_world.py` turns those files into what each analysis needs: a building
table (H/W, noise), a DSM and DTM with the scenario burned in (SVF, sun hours),
and street centrelines with the old interior grid swapped for the new one (H/W).

`OPTION 2` (scenario_b) is ten freeform blocks, 7.3 to 27.2 m, 20,719 m² of
footprint, and 6,696 m² of new streets. Two need a fix on the way in. Tall 1 is
an open roof surface plus a separate wall, so the roof is stood on the ground
and the wall skipped. Medium 2's roof slopes everywhere, so it becomes one block
at its mean roof height, 10.8 m, against a 13.3 m peak. Its blocks, roads and
green cover 55 % of the site and overlap 1,008 of its 1,156 buildings, so the
rule is the whole site, minus the same kept block as scenario_a: no OPTION 2
block or street touches its buildings. It demolishes 1,150. SVF, sun hours, H/W and the
walk network have scenario_b runs.

## Getting started

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import STUDY_AREA, PROCESSED, RAW, bbox_rd, bbox_wgs, write_processed
```
