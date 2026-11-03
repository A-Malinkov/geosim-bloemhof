# analysis/wind_noise - Wind + noise simulation

Component 5 · owner: _<name>_ · feeds `app/modules/wind_noise.js`

## What to produce

Write `wind_baseline.json`, `wind_scenario_a.json`, `wind_scenario_b.json`, and the `noise_*` equivalents into `data/processed/`.
Each of those files already exists as a stub containing a `_schema` block that
describes the exact shape `wind_noise.js` expects: **read it before writing the real file**.
The app treats a stub as "no data" and shows a placeholder until you overwrite it.

## Notes

- Pedestrian level means **1.75 m above ground**, same as the SVF, so the two are comparable.
- Building geometry: 3DBAG, or the AHN nDSM if you want a raster approach.
- **Two routes for wind: pick one and say why.** (a) A real CFD solve: OpenFOAM (simpleFoam, k-ε, atmospheric boundary-layer inlet) on a watertight STL of the site and its surroundings. TU Delft's City4CFD builds that STL from footprints + heights, and the 3DBAG API serves LoD1.2/1.3/2.2 solids per building. Heavier, but it is what the Simulation criterion rewards. (b) A roughness/shelter model driven by the KNMI wind rose, or a simplified Lawson-criterion comparison. Either way, **say which you used and what it cannot tell you.**
- Concentrate on the **design site** (`design_site.geojson`): that is where the scenarios differ. For CFD it is also a budget question: the site alone holds ~1,156 BAG buildings (every terraced house is separate), so start with LoD1.2 and a trimmed surrounding area.
- Noise: a road-traffic propagation model over the road network from `analysis/roads/`, with building attenuation.
- Output a regular grid plus `bbox_wgs84` so the app can drape it: see the stub in `data/processed/wind_baseline.json`.
- **Warp the grid to EPSG:4326 before taking those bounds.** RD New is rotated slightly against WGS84, so an RD-aligned grid's four corners do not share two longitudes. Building a lon/lat rectangle from the SW and NE corners misplaces the overlay by about 30 m: a third of a block. This bit the Sky View Factor overlay; `reproject_to_wgs84()` in `analysis/morphology/sky_view_factor.py` is the fix, reuse it.
- What matters for the report is baseline vs. design, not the absolute numbers.

## Getting started

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import STUDY_AREA, PROCESSED, RAW, bbox_rd, bbox_wgs, write_processed
```

## Noise: what exists (2026-10-14)

`noise.py` runs the road-traffic noise model for each scenario in its `CASES`:

```bash
python analysis/wind_noise/noise.py --scenario baseline   # ~10 min per scenario
python analysis/wind_noise/noise.py --refresh       # re-fetch OSM + 3DBAG first
```

It needs **Java ≥ 11** and **NoiseModelling 6.0.0** unpacked at
`~/tools/NoiseModelling_6.0.0` (or `NOISEMODELLING_HOME`), from
<https://github.com/Universite-Gustave-Eiffel/NoiseModelling/releases/tag/v6.0.0>.
The model chain: OSM import → road emission → Delaunay receivers →
propagation: is in `noise_pipeline.groovy`, run headless by `ScriptRunner`.
Inputs are cached in `cache/noise/` (gitignored).

Writes `data/processed/noise_baseline.json` (2 m Lden grid + summary) and
`docs/fig_noise_baseline.png`. `--scenario scenario_a`, `scenario_b` and `final`
are wired: `buildings_for()` takes the scenario's buildings from
`analysis/scenarios/scenario_world.py` (1,150 demolished, 22, 10 or 301 new
volumes). In the final design 49 flats stand on a shop podium with the same
footprint; the podium loses what the flats cover (`cut_overlaps()` from
`wind_cfd_export.py`), so no building sits inside another and the flats' prism,
ground to roof, screens for both. None has been run yet, because each needs
NoiseModelling. Traffic sources are unchanged, so cars still drive the old
interior streets the design removes; check the map near the new blocks.

The dense run needs more memory than a 16 GB laptop with an IDE open had:
the JVM segfaulted. To run it on another machine, follow
`RUN_NOISE_ON_ANOTHER_PC.md` (written for an AI agent, but readable).

Traps found on the way, all handled in the code:

- **Overpass answers 406** without a `User-Agent` header.
- **Osmosis needs `out meta`**, and recursing relations pulls in bus routes
  reaching Belgium. Fetch ways + their nodes only.
- **`LW_ROADS` is the source table** for `Noise_level_from_source`, not
  `tableSourcesEmission`: it already holds geometry and per-period power.
- **Over-the-roof diffraction is off by default.** Bloemhof's closed courtyards
  then have no sound path and come out at −92 dB on a third of the receivers.
  `confDiffHorizontal: true` fixes it, and takes the run from 2 to ~9 minutes.
- **`Import_OSM` ignores `maxspeed`**: 50 km/h main streets are modelled at
  80. The pipeline caps speeds at the OSM limit (−4.5 dB at the loudest spots).
- **The isosurface (`CONTOURING_NOISE_MAP`) has holes** where receivers do have
  levels, so the map is drawn from our own grid instead.
