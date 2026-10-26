# CFD wind simulation — design site

An OpenFOAM v2412 steady-RANS (`simpleFoam`, k-ε, atmospheric-boundary-layer
inlet) wind study of the design site, built from the assignment template and
adapted to our massing. Two cases sit in an **identical domain and mesh**, so the
only thing that changes the result is the design:

| case | geometry |
|---|---|
| `baseline` | the 1,156 3DBAG buildings now standing on the site |
| `scenario_a` | those demolished, the 22 new massing blocks, **plus the kept block** (school/halls/workshops, circled on the BAG — 6 BAG records, `keep_rd`) welded in as a solid obstacle |

## How the geometry is made

The STL the solver meshes is NOT edited by hand — it is generated:

```bash
python analysis/wind_noise/wind_cfd_export.py     # writes cache/wind/geometry/b_*.stl
python analysis/wind_noise/cfd_scaffold.py        # writes cfd/<case>/ and copies the STL in
```

`wind_cfd_export.py` reuses `analysis/scenarios/scenario_world.buildings_for_scenario()`
(the same demolish/keep/add logic the noise and SVF runs use), extrudes each
footprint from **z=0 to its height above ground**, and rotates everything so the
**prevailing SW wind (from 225°) blows along +x** — the inlet direction the ABL
case expects. There is **no +43.62 m NAP offset here**: OpenFOAM's ground is a
flat wall at z=0, unlike the Cesium app.

## Domain (Blocken 2015, §5.1–5.2)

With the tallest building H = 40 m (the scenario_a tower): 5H upwind, 15H
downwind, 5H lateral, ≥5H top, snapped to a 10 m grid → x [−500, 830],
y [−410, 340], z [0, 240] m, base cell 20 m (66×38×12). Measured frontal-area
blockage **2.82 %** (< 3 % target). snappyHexMesh refines the facades and a
ground box to ~5 m — modest, to fit the TU Delft server. `addLayers` is off.

## Running (TU Delft server, https://ronna.tudelft.nl/openfoam/)

ronna is **not a terminal** — you upload a zip of case inputs, the server meshes
(`surfaceFeatureExtract` → `blockMesh` → `snappyHexMesh`) and solves
(`simpleFoam`) on its own, and you download the result zip. There is no
`./Allrun` to run and no `checkMesh` to type; the logs are on the job page.

Upload only these four folders — **no `Allrun*`, no `constant/polyMesh` or
`constant/triSurface`, no time directories.** The zips are prebuilt by:

```bash
python analysis/wind_noise/cfd_scaffold.py        # writes cache/wind/<case>_ronna.zip
```
→ `cache/wind/baseline_ronna.zip`, `cache/wind/scenario_a_ronna.zip`.

**The STL must be referenced as `b_orig.stl`.** The server copies the single
uploaded `.stl` to `constant/triSurface/b_orig.stl` regardless of its name, so
`snappyHexMeshDict` and `surfaceFeatureExtractDict` reference `b_orig.stl` /
`b_orig.eMesh` (the *patch* is still named `buildings`, which the boundary
conditions use). Referencing any other name makes snappy silently find no
geometry and return the empty background box (30,096 cells, no `buildings`
patch) — the one failure we hit first.

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
gust hotspots. Compare `baseline` vs `scenario_a` on the same colour scale.

## Report checklist (TODO questions, answered in the case files)

Each filled TODO carries a `// Q…` comment with the choice and reason:
`blockMeshDict` (domain), `snappyHexMeshDict` (refinement), `controlDict`
(endTime/deltaT), `fvSchemes` (div(phi,U)), `fvSolution` (p solver, tolerances),
`transportProperties` (nu), `0.orig/U` and `0.orig/nut` (ABL BCs),
`0.orig/include/ABLConditions` (z0, Uref, Zref).

**Things to state as limitations:** the mesh is coarse for a pedestrian-comfort
study (server budget); a single wind direction/speed (SW, 5 m/s) — results scale
linearly with inlet speed but a full comfort assessment needs the KNMI wind rose;
no surrounding context beyond the site, so inflow shelter from the wider
neighbourhood is not represented.
