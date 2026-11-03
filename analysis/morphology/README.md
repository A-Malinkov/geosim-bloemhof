# analysis/morphology - urban morphology indicators

Owner: **Atanas Malinkov** · feeds `app/modules/indicators.js` and `app/modules/vegetation.js`

> Numbers here are generated from `data/processed/*.json`. Re-run an analysis and
> they go stale silently: regenerate this file and run
> `python analysis/check_docs.py`.

**The study area is one buurt, Bloemhof** (78.8 ha). Until 2026-10-22 it was
Bloemhof and Hillesluis together; every indicator was re-run when the team
narrowed it. Every indicator below is clipped to the buurt polygon, so the
numerator and denominator always share one boundary.

## Scripts

| Script | What it does | Writes |
|---|---|---|
| `fetch_ahn.py` | AHN DSM + DTM (0.5 m) via the PDOK WCS, tiled and mosaicked | `data/raw/ahn_{dsm,dtm,ndsm}_05m.tif` |
| `fetch_trees.py` | Rotterdam municipal tree register, ground level from the DTM | `data/raw/rotterdam_trees_rd.geojson`, `data/processed/trees.geojson`, `vegetation_summary.json` |
| `fetch_buildings.py` | 3DBAG footprint areas, storeys and heights via the OGC API | `data/raw/buildings_3dbag.geojson` |
| `fetch_landuse.py` | BAG addressable units: function and floor area per unit | `data/raw/bag_verblijfsobjecten.geojson` |
| `sky_view_factor.py` | SVF by the multi-directional horizon-angle method | `data/processed/svf*.tif`, `svf_overlay.png`, `svf_summary.json` |
| `density_height.py` | Spacematrix density (GSI, FSI, L) and height variation | `data/processed/density_grid[_<scenario>].geojson`, `density_summary[_<scenario>].json` |
| `landuse_mix.py` | Shannon land-use mix index | `data/processed/landuse_grid[_<scenario>].geojson`, `landuse_summary[_<scenario>].json` |
| `shadows.py` | direct-sun hours over one clear day, ray-cast from the AHN DSM | `data/processed/shadow_hours.tif` (gitignored), `shadow_overlay.png`, `shadow_summary.json` |
| `height_width.py` | street-canyon height-to-width ratio from OSM centrelines and 3DBAG footprints | `data/processed/canyon_hw_baseline.json`, `canyon_hw_baseline.geojson`, `docs/fig_canyon_hw_baseline.png` |
| `make_figures.py` | every report figure | `docs/fig_*.png` |

```bash
python analysis/common/project.py               # boundaries + study_area.geojson
python analysis/morphology/fetch_ahn.py         # ~30 s, tiled
python analysis/morphology/fetch_trees.py       # ~20 s
python analysis/morphology/fetch_buildings.py   # ~80 s
python analysis/morphology/fetch_landuse.py     # ~10 s
python analysis/morphology/sky_view_factor.py   # ~6 min per scenario, all four
python analysis/morphology/density_height.py    # ~1 min
python analysis/morphology/landuse_mix.py       # ~1 min
python analysis/morphology/shadows.py           # ~30 s per scenario and day, 12 runs
python analysis/morphology/height_width.py      # ~90 s first time (fetches footprints), then ~15 s per scenario
python analysis/morphology/make_figures.py      # ~1 min
```

Design scenarios. `sky_view_factor.py`, `shadows.py`, `height_width.py`,
`density_height.py` and `landuse_mix.py` run
every case in their `CASES`, and `--scenario scenario_a` (or any list) runs only those. The scenario's demolition and new
blocks come from `analysis/scenarios/scenario_world.py`, which reads what
`import_rhino.py` wrote. SVF and sun hours burn them into the AHN surface. H/W
swaps the buildings and replaces the old streets inside the site with the new
ones. Density and land-use mix take the demolished buildings out and add the new
blocks (see *Density and land-use mix per scenario* below). Outputs get a
`_<scenario>` suffix, the baseline keeps its names, and the app switches between them.

```bash
python analysis/morphology/sky_view_factor.py --scenario scenario_a   # ~6 min
python analysis/morphology/shadows.py --scenario scenario_a           # ~30 s per day, all three days
python analysis/morphology/height_width.py --scenario scenario_a      # ~15 s
python analysis/morphology/density_height.py --scenario scenario_a    # ~1 min
python analysis/morphology/landuse_mix.py --scenario scenario_a       # ~1 min, after density_height.py
```

## Status: all four indicators complete

| indicator | Bloemhof |
|---|---|
| **Sky View Factor** | **0.784** |
| **GSI** ground space index | **0.333** |
| **FSI** floor space index | **1.003** |
| **L** storeys | **3.01** |
| **mean building height** | **8.5 m** |
| **height variation σ** | **2.9 m** |
| **land-use mix** Shannon | **0.267** |
| **trees** | **1,204** |
| **trees per hectare** | **15.3** |
| **canopy cover** | **6.6 %** |

Bloemhof is dense, low and enclosed, and mono-functional: 86 % of its floor
space is residential. Against Hillesluis next door, which the study area
covered until 2026-10-22, it was the denser, more enclosed, less mixed and less
green of the two (Hillesluis: GSI 0.24, Shannon 0.42, 17.7 trees/ha, SVF 0.75 with trees).
If the design is meant to address a deficit, those are the ones the indicators
point at.

## Sky View Factor: method

Multi-directional horizon angle, after Zakšek, Oštir & Kokalj (2011), *Sky-View
Factor as a Relief Visualization Technique*, Remote Sensing 3(2):398–415: the
approach SAGA, RVT and SOLWEIG use.

For every cell and each of N compass directions, walk outwards to a search radius
and record the greatest elevation angle of the obstruction surface, γ. Then

```
SVF_radiation = (1/N) · Σ cos²(γᵢ)       ← reported as "SVF"
SVF_geometric = 1 − (1/N) · Σ sin(γᵢ)
```

Both are in the literature and **they are not the same number**: here they are
0.784 and 0.629. The cos² form is cosine-weighted, so sky near the
zenith counts for more; that governs radiation exchange and is what urban
climatology means by SVF. Both go into `svf_summary.json`.

### Choices worth defending

- **Observer at 1.75 m above the DTM**, not on the surface model: what a person
  in the street sees, not what a roof sees.
- **Buildings only, no trees** (since 2026-11-02). Outside the 3DBAG footprints,
  widened 0.5 m for eaves, the DSM is set to the ground, so tree crowns, walls
  and cars do not block the sky. With trees the Bloemhof mean was 0.696.
- **Open-ground mask** (`nDSM < 2 m` on the tree-free surface, so the ground under
  a crown counts): statistics exclude roofs, where SVF is
  meaningless.
- **0.5 m cells, 32 directions, 100 m search radius.** Resolution changes the
  answer: coarser cells blur building edges and narrow streets and report the
  place as more open than it is. Quote the cell size with the number.
- **150 m of context is downloaded beyond the boundary** and cropped afterwards,
  because a building just outside still blocks sky inside.
- **AHN gaps are filled** by nearest-neighbour dilation. Left as nodata they act
  as bottomless pits and the horizon search sees straight through them.

## Density: Spacematrix

Berghauser Pont & Haupt (2010). Density is not one number: a packed low-rise
terrace and a tower in a park can share an FSI and be nothing alike.

```
GSI = built footprint / land area     coverage
FSI = gross floor area / land area    intensity
L   = FSI / GSI                       mean storeys
```

- **Storey height is measured, not assumed**: 3.06 m, the median over
  buildings where 3DBAG gives both a count and a height. It fills in the
  3,696 buildings with no storey count.
- **Sheds count for density but not for height.** 44 % of BAG *Pand*
  records are outbuildings holding 10 % of the built area. (This share, the
  storey height and the 3,696 are measured over the whole 3DBAG download,
  which still covers the two-buurt box from before 2026-10-22; every density
  figure itself is clipped to Bloemhof.) They cover
  ground, so they belong in GSI and FSI, but they are not what "building height"
  means: statistics use principal buildings only (≥ 40 m², ≥ 4 m).
- **Height is above each building's own ground** (`b3_h_dak_50p − b3_h_maaiveld`),
  not above NAP zero.
- **Spacematrix is scale-sensitive.** An FSI at 100 m cells is not comparable
  with one at 50 m. Quote the cell size.

### The maps

`make_figures.py` writes `docs/fig_density_maps.png`: GSI and FSI per 100 m
cell, with the buurt boundary. The Spacematrix scatter (GSI against FSI) was
dropped from the report and the app on 2026-11-01 as more than the project
needs. The 107 per-cell points in `density_summary.json` it was drawn from are kept.

Each point carries a `buurt` label, assigned by whichever polygon contains the
cell **centre**: 81 Bloemhof,
26 outside it (the bounding box is larger
than the buurt). Buildings outside the grid are dropped, not clamped into the
edge cells (`np.clip` on the cell index did that after the study area shrank and
the raw downloads did not, giving a 100 m cell a GSI of 5.9).

### The two scales give different numbers

| | FSI over the whole buurt | mean FSI over built cells |
|---|---|---|
| Bloemhof | 1.003 | 0.97 |

Both are correct. The buurt figure divides floor area by all of its land, gaps
included; the grid mean averages only cells holding at least 3 buildings, so it
describes built fabric and ignores the gaps. This is the modifiable areal unit
problem arriving in a number we publish, which is why the cell size travels with
every figure. With two buurten the scales even ranked them in opposite orders;
the app states such a reversal in the panel, generated from the data, so it only
appears when there is one.

### Density on the design site, per scenario

`density_site.py` computes GSI, FSI and L over the 13.24 ha design site, today and
in each scenario, with the same storey rule as above. A scenario keeps the
buildings it does not demolish and adds its new blocks (height / 3.06 m storeys);
flats on a shop podium add floors but no ground cover. Output:
`data/processed/density_site.json`, shown in the app's density card (it follows
the scenario switch) and in `docs/fig_density_site.png`.

| design site | GSI | FSI | storeys |
|---|---|---|---|
| today | 0.32 | 0.92 | 2.9 |
| scenario_a | 0.27 | 1.37 | 5.0 |
| scenario_b | 0.17 | 0.86 | 5.0 |
| final | 0.17 | 0.75 | 4.5 |

Every design covers less of the site than today and builds higher; only
scenario_a adds floor space. The comparison (`analysis/comparison/`) uses height /
3 m for every building, so its FSI differs from these by up to 0.05.

## Land-use mix: method

Shannon entropy (normalised) over BAG `gebruiksdoel`,
**weighted by usable floor area**.

- Weighting by floor area rather than unit count roughly doubles the measured mix
  (0.144 → 0.267): most units are residential but non-residential
  ones are individually much larger. Both are reported.
- **N is the full 11-class BAG vocabulary, fixed a priori**, not "classes present
  here", otherwise cells with shorter category lists score spuriously high.
- Multi-function units (a shop with a flat above) split their floor area evenly.
- **BAG covers addressable units only.** Parks, water and streets are invisible
  to it, so this is a mix of *built floor space*. Pair it with GSI for the
  built/unbuilt split. CBS Bestand Bodemgebruik was tried and rejected: newest
  edition 2017, and it resolves the area into a handful of polygons.

## Direct sun and shadows

Added by Stefan. Two parts that answer different questions:

- **`shadows.py`: how many hours of direct sun a place gets over a whole day.**
  It casts the sun across one clear day (equinox by default, every 30 min) over
  the AHN surface model and counts, per 1 m cell, the hours it is sunlit.
  Reported on open ground only, over the buurt and the design site, like the SVF.
- **The "Sun & shadows" card in the app: one instant.** It opens on *Live*:
  the sun as it stands right now in Rotterdam, clear-sky, for orientation only.
  Pick a reference day (equinox, summer or winter solstice) or drag the time, and
  the 3DBAG buildings cast live shadows in Cesium. Switch on *Plain white ground*
  under Imagery to see them without the photo's own shadows.

Both were checked: the sun position in Cesium, in `shadows.py` and in an
independent calculation agree to 0.1°, and a synthetic 40 m tower casts its
shadow in the right direction (within 1°) and to the right length in both.

Results, direct sun on open ground (clear sky, 1 m cells, sun every 30 min).
All three days are app overlays, picked with the day buttons in the Direct sun
section of the morphology card. The solstices carry their date as a file suffix
(`DAYS` in `shadows.py`) so they do not overwrite the equinox:

| Day | Daylight | Bloemhof | Design site (median, share < 2 h) |
|---|---|---|---|
| 21 Dec | 7.5 h | 0.61 h | 0.0 h, 87 % |
| 20 Mar | 12.0 h | 4.28 h | 4.0 h, 22 % |
| 21 Jun | 16.5 h | 8.14 h | 9.0 h, 1 % |

The Bloemhof column is a mean. (Hillesluis, in the study area until 2026-10-22,
got 1.90 / 5.81 / 9.84 h: Bloemhof is the shadier, consistent with its lower
SVF.) These figures are from the AHN re-download of 2026-10-22, which sits on
AHN's own 0.5 m grid; the earlier mosaic was offset by about half a cell, and at
1 m that alone moved the equinox mean from 4.44 h to 4.28 h and the site's
share under 2 h from 20 % to 22 %. SVF did not move (0.696 both times, with trees then). In winter most of the site's open ground gets no direct sun at all:
streets ≈ 11 m wide between ~7 m walls are fully shaded by a sun that peaks at
about 15°. `shadow_figure.py` draws the three days over the site
(`docs/fig_shadow_site.png`).

The script keeps 50 m of the 150 m padding in its outputs, because the design
site's south edge (Strevelsweg) runs ~31 m past the buurt bounding box.

Limits, as the script states: a clear-sky upper bound, not measured sunshine;
tree crowns block as if solid; obstructions beyond the search radius (300 m) are
ignored. In the live view, fine stripes can appear on roofs when zoomed far
out: Cesium's shadow map has limited detail over a large view. Close up the
shadows are clean.

## Street canyons: height-to-width ratio

`height_width.py` samples every street centreline every 10 m and casts a ray
perpendicular to it on both sides, up to 60 m, to the first building façade.
W is façade to façade, H the mean of the two buildings' heights, and a point
counts as a canyon only with a building on both sides. Statistics are by street
length, clipped to the buurt and to the design site.

Baseline (from `canyon_hw_baseline.json`):

| | H/W median | wall height H | width W | street length that is canyon |
|---|---|---|---|---|
| Bloemhof | 0.42 | 8.0 m | 19.9 m | 67 % |
| design site | 0.39 | 7.3 m | 22.9 m | 76 % |

Bloemhof's streets are low walls on fairly narrow streets. On the
design site the interior side streets are mostly ≈ 11 m wide with 6–8 m walls
(H/W 0.4–0.6, length-weighted median 0.51), while Lange Hilleweg along its
north-west edge is a 56 m avenue with ~8 m walls, H/W 0.14.

**One filter had to change.** Street walls exclude sheds (< 15 m² or < 3 m).
The density analysis's "principal building" filter (≥ 40 m², ≥ 4 m) was tried
first and is wrong here: the median building on the design site is 36 m²,
because each terraced house is its own BAG record, so that filter removed half
the street wall and rays slipped through the gaps. Residential streets came out
32 m wide instead of 20 m. With no filter at all they are 20.5 m, so sheds
rarely act as street walls anyway.

**Limits.** One height per building (the roof median, not the eave), gaps
narrower than the 10 m sample spacing are averaged over, and dual
carriageways are measured from each half's centreline.

## Scenario results, design site

Open ground only for SVF and sun hours, street length for H/W. Generated from
`svf_summary*.json`, `shadow_summary*.json` and `canyon_hw*.json`; checked by
`analysis/check_docs.py`.

| | baseline | Scenario A | Scenario B | Final design |
|---|---|---|---|---|
| SVF, mean | 0.785 | 0.704 | 0.848 | 0.822 |
| SVF, median | 0.817 | 0.696 | 0.893 | 0.858 |
| sun 20 Mar, mean | 4.30 h | 3.78 h | 5.97 h | 5.84 h |
| sun 21 Jun, mean | 8.61 h | 8.81 h | 10.19 h | 10.29 h |
| sun 21 Dec, mean | 0.53 h | 0.49 h | 1.32 h | 1.11 h |
| sun 20 Mar, share < 2 h | 22 % | 40 % | 13 % | 22 % |
| sun 21 Dec, share < 2 h | 87 % | 87 % | 67 % | 71 % |
| street H/W, median | 0.39 | 0.48 | 0.28 | 0.28 |
| street length that is canyon | 76 % | 74 % | 47 % | 60 % |
| street width W, median | 22.9 m | 24.6 m | 47.1 m | 38.3 m |

Demolition opens ground, so the open-ground means cover different areas in
each column: quote the shares next to the means (CLAUDE.md). Scenario A's
rows of 12 to 20 m blocks close the site in, with less sky and nearly twice
today's share of open ground under 2 h of equinox sun. Scenario B puts a smaller
built footprint in a park and opens it up on every measure. Its streets are
wide and few, so about half of its street length is not a canyon at all.

## Density and land-use mix per scenario

Over the whole buurt (78.8 ha), so a design moves these less than the design-site
figures above. Generated from `density_summary*.json` and `landuse_summary*.json`;
checked by `analysis/check_docs.py`.

| | baseline | Scenario A | Scenario B | Final design |
|---|---|---|---|---|
| GSI, whole buurt | 0.333 | 0.325 | 0.308 | 0.307 |
| FSI, whole buurt | 1.003 | 1.078 | 0.993 | 0.974 |
| storeys (L), whole buurt | 3.01 | 3.32 | 3.22 | 3.17 |
| land-use mix, Shannon (floor area) | 0.267 | 0.235 | 0.252 | 0.282 |
| land-use mix, Shannon (units) | 0.144 | 0.122 | 0.130 | 0.166 |
| floor space not housing | 13.7 % | 11.8 % | 12.9 % | 15.6 % |

How a scenario is built:

- **Density.** The 3DBAG buildings a design demolishes leave, its new blocks
  join. A block's storeys are its own height over the storey height measured
  from 3DBAG (3.06 m), the rule 3DBAG buildings without a storey count get.
  Flats on a shop podium (final design) add floor area but no ground cover and
  count as one building with the podium, as in `compare_scenarios.py`. That
  script uses a flat 3 m storey, so its design-site FSI for B (0.905) is higher
  than the same site summed here with 3.06 m (0.860); the GSI is identical.
- **Land-use mix.** The BAG units in demolished buildings leave (by `pand_id`).
  A new block's floor space is footprint × storeys × the usable/gross ratio
  measured from today's all-housing buildings (0.791), given to the use the Rhino
  model names: housing, or retail for shops and the shopping centre. The
  amenities `place_amenities.py` places take their floor area out of their
  block's housing; the final design's seven shop units it makes health practices
  move from retail to healthcare. Units are estimated from today's median unit
  size per use, so unit counts and the sparse-cell flag stay comparable.
- **A and B name no uses.** Their blocks are all housing except the placed
  amenities (20 shops, 7 health practices, one school), so their mix is the
  p-median's, not the team's: it falls below today's because they add homes and
  little else. The final design names every block, so its figure is the design's.

## For the scenario comparison

These indicators are the measuring stick. Density on the design site per
scenario is in `density_site.py` (above); SVF, sun hours and H/W have their own
scenario runs.
