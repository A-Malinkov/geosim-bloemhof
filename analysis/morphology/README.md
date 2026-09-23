# analysis/morphology — urban morphology indicators

Owner: **Atanas Malinkov** · feeds `app/modules/indicators.js` and `app/modules/vegetation.js`

## Scripts

| Script | What it does | Writes |
|---|---|---|
| `fetch_ahn.py` | AHN DSM + DTM (0.5 m) over the study area via the PDOK WCS, and their difference | `data/raw/ahn_{dsm,dtm,ndsm}_05m.tif` |
| `fetch_trees.py` | Rotterdam municipal tree register, with ground level sampled from the DTM | `data/raw/rotterdam_trees_rd.geojson`, `data/processed/trees.geojson`, `data/processed/vegetation_summary.json` |
| `fetch_buildings.py` | 3DBAG footprint areas, storeys and heights via the OGC API | `data/raw/buildings_3dbag.geojson` |
| `sky_view_factor.py` | Sky View Factor by the multi-directional horizon-angle method | `data/processed/svf*.tif`, `svf_overlay.png`, `svf_summary.json` |
| `density_height.py` | Spacematrix density (GSI, FSI, L, OSR) and height variation | `data/processed/density_grid.geojson`, `density_summary.json` |
| `make_figures.py` | every report figure | `docs/fig_*.png` |

Run them in this order — the analyses need the downloads first.

```bash
python analysis/morphology/fetch_ahn.py         # AHN rasters       ~1 min
python analysis/morphology/fetch_trees.py       # tree register     ~30 s
python analysis/morphology/fetch_buildings.py   # 3DBAG buildings   ~1 min
python analysis/morphology/sky_view_factor.py   # SVF               ~40 s
python analysis/morphology/density_height.py    # density + height  ~15 s
python analysis/morphology/make_figures.py      # all figures       ~40 s
```

## Status

- [x] **3D vegetation** — 2,172 trees, 206 species, 15.1 trees/ha, 7.9 % canopy
      (upper bound). Rendered as batched 3D primitives by `app/modules/vegetation.js`.
- [x] **Sky View Factor** — mean 0.687, median 0.717 at 1.75 m above ground on
      open ground within Bloemhof.
- [x] **Building density** — GSI 0.324, FSI 1.024, L 3.16 storeys,
      OSR 0.66 over the 58.94 ha of Bloemhof inside the study area.
- [x] **Height variation** — 8.7 m mean, σ 2.8 m,
      tallest 30.1 m (1,830 principal buildings);
      within-cell σ averages 1.95 m.
- [ ] Land-use mix

## Sky View Factor — method

Multi-directional horizon angle, after Zakšek, Oštir & Kokalj (2011), *Sky-View
Factor as a Relief Visualization Technique*, Remote Sensing 3(2):398–415 — the
approach SAGA, RVT and SOLWEIG use.

For every cell and each of N compass directions, walk outwards to a search radius
and record the greatest elevation angle of the obstruction surface, γ. Then

```
SVF_radiation = (1/N) · Σ cos²(γᵢ)       ← reported as "SVF"
SVF_geometric = 1 − (1/N) · Σ sin(γᵢ)
```

Both appear in the literature and **they are not the same number** — for Bloemhof
they are 0.687 and 0.529. The cos² form is cosine-weighted, so sky near the zenith
counts for more; that is what governs radiation exchange and what urban
climatology means by SVF. The 1−sin form is the plain solid-angle fraction used in
relief visualisation. Both are written to `svf_summary.json`, so a figure never
has to leave the reader guessing.

### Choices worth defending in the report

- **Observer at 1.75 m above the DTM**, not on the surface model: we want what a
  person standing in the street sees, not what a roof sees.
- **Obstruction surface is the DSM**, so tree crowns count. Vegetation lowers SVF
  and that is a real effect, not noise.
- **Open-ground mask** (`nDSM < 2 m`): statistics exclude roofs, where SVF is
  meaningless. That is 46 % of the raster.
- **150 m of context is downloaded beyond the study area** and cropped off
  afterwards, because a building just outside the edge still blocks sky inside it.
- **AHN gaps are filled** by nearest-neighbour dilation. Left as nodata they act
  as bottomless pits and the horizon search sees straight through them.
- **Statistics are reported twice**: for the square study area and clipped to the
  CBS Bloemhof polygon. The square also covers the Maashaven and parts of
  Afrikaanderwijk.

### Parameters

Defaults: 0.5 m cells, 100 m search radius, 32 directions, 48 radial steps
(geometrically spaced — dense nearby, sparse far out, since nearby geometry sets
the horizon). About 37 s for a 3000 × 3000 grid. Running the script with no
arguments reproduces the numbers in the figures.

```bash
python analysis/morphology/sky_view_factor.py --resolution 1.0     # 4× faster
python analysis/morphology/sky_view_factor.py --directions 16      # ~2× faster
python analysis/morphology/sky_view_factor.py --radius 150         # taller context
```

**Resolution changes the answer — say which you used.** At 0.5 m the Bloemhof
mean is **0.685**; at 1.0 m it is **0.734**. Coarser cells average away narrow
obstructions, and tree crowns are exactly the thing that gets smoothed out, so a
coarse grid systematically reports the neighbourhood as more open than it is.
Use 0.5 m for anything quoted in the report; 1.0 m is for quick iteration.

### For the scenario comparison

SVF is where our design shows up most directly. To compare scenarios, burn the
proposed massing into a copy of the DSM and re-run. That work belongs in
`analysis/scenarios/`; keep `sky_view_factor.py` general and import it.

## Tree register — notes

- `HOOGTE` is a **class** ("12–15 m."), not a measurement. `height_m` is the class
  midpoint; `height_min_m`/`height_max_m` keep the bounds so nobody mistakes it
  for a survey value.
- `KROONOMVANG` is crown diameter in metres.
- Canopy cover treats crowns as circles and does not dissolve overlaps, so it is
  an **upper bound**. Use `shapely.unary_union` on buffered points if you need the
  real figure.
- Ground level per tree comes from the AHN DTM. The DTM is empty under buildings
  and over water, so those trees take the median of a widening neighbourhood.


## Density and height variation — method

**Spacematrix** (Berghauser Pont & Haupt 2010, TU Delft). Density is not one
number: a packed low-rise terrace and a tower in a park can share an FSI and be
nothing alike. Four quantities over a defined unit separate them:

```
GSI = built footprint / land area     coverage
FSI = gross floor area / land area    intensity
L   = FSI / GSI                       mean storeys
OSR = (1 - GSI) / FSI                 open space per m² of floor space
```

GSI and FSI fix the other two, so the GSI–FSI scatter with L and OSR isolines
characterises the fabric — that is `fig_spacematrix.png`.

### Results

| | Bloemhof (surveyed part) | 100 m grid |
|---|---|---|
| GSI | 0.324 | 0.311 ± 0.123 |
| FSI | 1.024 | 1.080 ± 0.564 |
| L (storeys) | 3.16 | 3.44 |
| OSR | 0.66 | 1.18 |
| Mean building height | 8.7 m | — |
| Height σ | 2.8 m | 1.95 m within cells |

### Choices worth defending in the report

- **The denominator is the surveyed area, not the whole buurt.** The study square
  covers 75% of Bloemhof. Dividing the buildings we found by the buurt's
  full 78.84 ha would understate density by a factor of
  1.34. This is an easy mistake to make and it is invisible in
  the output, so it is stated in `density_summary.json` as `coverage_fraction`.
- **Storey height is measured, not assumed.** Where 3DBAG gives both a storey
  count and a height, the median is **3.08 m per floor**. That measured value
  fills in the 2,553 buildings with no storey count, rather than a
  round 3 m.
- **Sheds are counted for density but not for height.** 45% of BAG *Pand*
  records here are outbuildings — garden sheds, garages, bergingen — holding only
  10% of the built area. They cover ground, so they belong in GSI and
  FSI. They are not what "mean building height" means, so height statistics use
  principal buildings only (≥ 40 m² footprint and ≥ 4 m tall). Including
  them would drag the median height down to about 6 m.
- **Height is measured above each building's own ground** (`b3_h_dak_50p` −
  `b3_h_maaiveld`), not above NAP zero. Ground across the study area runs from
  about −2 to +8 m NAP, so using raw roof elevation would make buildings on
  higher ground look taller.
- **Spacematrix is scale-sensitive.** An FSI at 100 m cells is not comparable
  with one at 50 m or at block level. The cell size is recorded with every
  result; quote it whenever you quote a number.
- **Buildings are assigned to the cell containing their centroid**, so a building
  straddling a cell edge lands wholly in one. At 100 m cells with ~10 m
  buildings this is a small effect. Footprint *area* is the exact
  `b3_opp_grond` attribute, never derived from geometry.

### For the scenario comparison

This is the most direct way to show what the design does. Add the proposed
massing's footprints and floor counts to the building set, re-run, and compare
GSI/FSI/L/OSR against the baseline — the Spacematrix plot will show the new
fabric moving relative to the existing one.
