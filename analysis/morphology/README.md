# analysis/morphology — urban morphology indicators

Owner: **Atanas Malinkov** · feeds `app/modules/indicators.js` and `app/modules/vegetation.js`

## Scripts

| Script | What it does | Writes |
|---|---|---|
| `fetch_ahn.py` | AHN DSM + DTM (0.5 m) over the study area via the PDOK WCS, and their difference | `data/raw/ahn_{dsm,dtm,ndsm}_05m.tif` |
| `fetch_trees.py` | Rotterdam municipal tree register, with ground level sampled from the DTM | `data/raw/rotterdam_trees_rd.geojson`, `data/processed/trees.geojson`, `data/processed/vegetation_summary.json` |
| `sky_view_factor.py` | Sky View Factor by the multi-directional horizon-angle method | `data/processed/svf*.tif`, `svf_overlay.png`, `svf_summary.json`, `docs/svf_map.png` |

Run them in that order — the other two need the AHN rasters.

```bash
python analysis/morphology/fetch_ahn.py
python analysis/morphology/fetch_trees.py
python analysis/morphology/sky_view_factor.py
```

## Status

- [x] **3D vegetation** — 2,172 trees, 206 species, 15.1 trees/ha, 7.9 % canopy
      (upper bound). Rendered as batched 3D primitives by `app/modules/vegetation.js`.
- [x] **Sky View Factor** — mean 0.687, median 0.717 at 1.75 m above ground on
      open ground within Bloemhof.
- [ ] Building density (FSI / GSI)
- [ ] Height variation
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
