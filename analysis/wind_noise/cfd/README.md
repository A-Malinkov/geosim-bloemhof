# CFD wind simulation: design site

An OpenFOAM v2412 steady-RANS (`simpleFoam`, k-ε, atmospheric-boundary-layer
inlet) wind study of the design site, built from the assignment template and
adapted to our massing. Four cases sit in an **identical domain and mesh**, so the
only thing that changes the result is the design:

| case | geometry |
|---|---|
| `baseline` | the 1,156 3DBAG buildings now standing on the site |
| `scenario_a` | those demolished, the 22 new massing blocks, **plus the kept block** (school/halls/workshops, circled on the BAG: 6 BAG records, `keep_rd`) welded in as a solid obstacle |
| `scenario_b` | the same, with OPTION 2's 10 blocks (tallest 27.2 m) |
| `final` | the same, with the Final Model's 301 volumes (tallest 25 m). Flats on a shop podium share its footprint: the 49 podiums lie wholly under their flats, so the flats' prism (ground to roof) stands for both and no solid sits inside another |

The domain is fitted to all four together. `scenario_b` and `final` are lower
and no wider than the other two, so adding them (2026-10-31) changed neither the
domain nor the baseline and scenario_a cases: their uploads stay valid.

## How the geometry is made

The STL the solver meshes is NOT edited by hand: it is generated:

```bash
python analysis/wind_noise/wind_cfd_export.py     # writes cache/wind/geometry/b_*.stl
python analysis/wind_noise/cfd_scaffold.py        # writes cfd/<case>/ and copies the STL in
```

`wind_cfd_export.py` reuses `analysis/scenarios/scenario_world.buildings_for_scenario()`
(the same demolish/keep/add logic the noise and SVF runs use), extrudes each
footprint from **z=0 to its height above ground**, and rotates everything so the
**prevailing SW wind (from 225°) blows along +x**: the inlet direction the ABL
case expects. There is **no +43.62 m NAP offset here**: OpenFOAM's ground is a
flat wall at z=0, unlike the Cesium app.

## Domain (Blocken 2015, §5.1–5.2)

With the tallest building H = 40 m (the scenario_a tower): 5H upwind, 15H
downwind, 5H lateral, ≥5H top, snapped to a 10 m grid → x [−500, 830],
y [−410, 340], z [0, 240] m, base cell 20 m (66×38×12). Measured frontal-area
blockage **2.82 %** (< 3 % target). snappyHexMesh refines the facades and a
ground box to ~5 m: modest, to fit the TU Delft server. `addLayers` is off.

## Running (TU Delft server, https://ronna.tudelft.nl/openfoam/)

ronna is **not a terminal**: you upload a zip of case inputs, the server meshes
(`surfaceFeatureExtract` → `blockMesh` → `snappyHexMesh`) and solves
(`simpleFoam`) on its own, and you download the result zip. There is no
`./Allrun` to run and no `checkMesh` to type; the logs are on the job page.

Upload only these four folders: **no `Allrun*`, no `constant/polyMesh` or
`constant/triSurface`, no time directories.** The zips are prebuilt by:

```bash
python analysis/wind_noise/cfd_scaffold.py        # writes cache/wind/<case>_ronna.zip
```
→ `cache/wind/baseline_ronna.zip`, `scenario_a_ronna.zip`, `scenario_b_ronna.zip`,
`final_ronna.zip`.

**The STL must be referenced as `b_orig.stl`.** The server copies the single
uploaded `.stl` to `constant/triSurface/b_orig.stl` regardless of its name, so
`snappyHexMeshDict` and `surfaceFeatureExtractDict` reference `b_orig.stl` /
`b_orig.eMesh` (the *patch* is still named `buildings`, which the boundary
conditions use). Referencing any other name makes snappy silently find no
geometry and return the empty background box (30,096 cells, no `buildings`
patch): the one failure we hit first.

After the job succeeds, download it and read the logs on the job page for
converging residuals (stops at 1e-4 via `residualControl`, else the 2000-iter
cap). The 1,156-building `baseline` is the heavy mesh; if it times out, drop the
facade refinement `level (2 2)` → `(1 1)` and the ground box level `2` → `1` in
`system/snappyHexMeshDict`, regenerate, and say so in the report.

## Post-processing (ParaView, Tasks 2 & 4)

```bash
touch wind.foam      # or: copy nul wind.foam   (Windows)
```

Open `wind.foam`, then at **pedestrian level z = 1.75 m** (same as our SVF, so
the two are comparable): a `Slice`, and a `Threshold` on |U| > 5 m/s for the
gust hotspots. Compare `baseline` against each design case on the same colour scale.

## On the map (the app)

Download each finished job's results zip from ronna and import it:

```bash
python analysis/wind_noise/wind_cfd_import.py baseline   path/to/baseline_results.zip
python analysis/wind_noise/wind_cfd_import.py scenario_a path/to/scenario_a_results.zip
python analysis/wind_noise/wind_cfd_import.py scenario_b path/to/scenario_b_results.zip
python analysis/wind_noise/wind_cfd_import.py final      path/to/final_results.zip
```

Each writes `data/processed/wind_<case>.json`: the cells cut by **z = 1.5 m**
(`--level` to change it), sampled on a 2 m grid over the design site + 50 m and
warped to EPSG:4326. The value is the **wind-speed ratio**, |U| over the
undisturbed inflow at the same height: the inlet's log-law profile
(`ABLConditions`) at each cell's centre height, ~2.6 m on the site. It does not
depend on the 5 m/s chosen for the inlet. The profile is not measured upwind:
the refinement box stops 30 m before the buildings, so upwind cells are 20 m
tall, centred at 10 m, where the wind is ~70 % faster. They check the profile
instead (`inflow.profile_check`: 5.01 m/s measured against 5.00 m/s for the
baseline run). In the app: *Wind & noise → Pedestrian wind, 1.5 m*, following
the scenario switch, and the `wind` tab of the Wind & noise card (share of open
ground above 1.1× and below 0.5× the inflow, solver convergence).

**A run stopped at the 2000-iteration cap can still be usable.** The importer
compares the last two saved fields and calls the run steady if no cell changed
by more than 0.1 m/s. The baseline run stopped with residuals on a plateau
(p 7e-4, k and ε 3e-4, against a 1e-4 target) but its field changed at most
0.02 m/s between iterations 1500 and 2000.

The script reads OpenFOAM's binary files with numpy, no ParaView needed
(checked against ParaView's own slice: identical to 6e-7 m/s). It refuses a run
without a `buildings` patch (the empty-box failure above) and a result whose STL
is not this case's `cache/wind/geometry/b_<case>.stl` (`--force` to override).

**The slice reads the first cell layer.** Ground cells are ~5 m, so z = 1.5 m
and z = 1.75 m cut the same cells and show the same map.

## Report checklist (TODO questions, answered in the case files)

Each filled TODO carries a `// Q…` comment with the choice and reason:
`blockMeshDict` (domain), `snappyHexMeshDict` (refinement), `controlDict`
(endTime/deltaT), `fvSchemes` (div(phi,U)), `fvSolution` (p solver, tolerances),
`transportProperties` (nu), `0.orig/U` and `0.orig/nut` (ABL BCs),
`0.orig/include/ABLConditions` (z0, Uref, Zref).

**Things to state as limitations:** the mesh is coarse for a pedestrian-comfort
study (server budget); a single wind direction/speed (SW, 5 m/s): results scale
linearly with inlet speed but a full comfort assessment needs the KNMI wind rose;
no surrounding context beyond the site, so inflow shelter from the wider
neighbourhood is not represented.
