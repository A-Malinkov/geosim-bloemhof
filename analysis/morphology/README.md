# analysis/morphology — urban morphology indicators

Owner: **Atanas Malinkov** · feeds `app/modules/indicators.js` and `app/modules/vegetation.js`

> Numbers here are generated from `data/processed/*.json`. Re-run an analysis and
> they go stale silently — regenerate this file and run
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
| `density_height.py` | Spacematrix density (GSI, FSI, L, OSR) and height variation | `data/processed/density_grid.geojson`, `density_summary.json` |
| `landuse_mix.py` | Shannon and Simpson land-use mix indices | `data/processed/landuse_grid.geojson`, `landuse_summary.json` |
| `shadows.py` | direct-sun hours over one clear day, ray-cast from the AHN DSM | `data/processed/shadow_hours.tif` (gitignored), `shadow_overlay.png`, `shadow_summary.json` |
| `height_width.py` | street-canyon height-to-width ratio from OSM centrelines and 3DBAG footprints | `data/processed/canyon_hw_baseline.json`, `canyon_hw_baseline.geojson`, `docs/fig_canyon_hw_baseline.png` |
| `make_figures.py` | every report figure | `docs/fig_*.png` |

```bash
python analysis/common/project.py               # boundaries + study_area.geojson
python analysis/morphology/fetch_ahn.py         # ~30 s, tiled
python analysis/morphology/fetch_trees.py       # ~20 s
python analysis/morphology/fetch_buildings.py   # ~80 s
python analysis/morphology/fetch_landuse.py     # ~10 s
python analysis/morphology/sky_view_factor.py   # ~6 min
python analysis/morphology/density_height.py    # ~1 min
python analysis/morphology/landuse_mix.py       # ~1 min
python analysis/morphology/shadows.py           # ~30 s, equinox; --date 2026-06-21 for summer
python analysis/morphology/height_width.py      # ~90 s first time (fetches footprints), then ~15 s
python analysis/morphology/make_figures.py      # ~1 min
```

Design scenarios. `sky_view_factor.py`, `shadows.py` and `height_width.py` take
`--scenario scenario_a` (or `scenario_b`). The scenario's demolition and new
blocks come from `analysis/scenarios/scenario_world.py`, which reads what
`import_rhino.py` wrote. SVF and sun hours burn them into the AHN surface. H/W
swaps the buildings and replaces the old streets inside the site with the new
ones. Outputs get a `_<scenario>` suffix, the baseline keeps its names, and the
app switches between them.

```bash
python analysis/morphology/sky_view_factor.py --scenario scenario_a   # ~6 min
python analysis/morphology/shadows.py --scenario scenario_a           # ~30 s per day
python analysis/morphology/height_width.py --scenario scenario_a      # ~15 s
```

## Status — all four indicators complete

| indicator | Bloemhof |
|---|---|
| **Sky View Factor** | **0.696** |
| **GSI** ground space index | **0.333** |
| **FSI** floor space index | **1.003** |
| **L** storeys | **3.01** |
| **OSR** | **0.67** |
| **mean building height** | **8.5 m** |
| **height variation σ** | **2.9 m** |
| **land-use mix** Shannon | **0.267** |
| **trees** | **1,204** |
| **trees per hectare** | **15.3** |
| **canopy cover** | **6.6 %** |

Bloemhof is dense, low and enclosed, and mono-functional: 86 % of its floor
space is residential. Against Hillesluis next door, which the study area
covered until 2026-10-22, it was the denser, more enclosed, less mixed and less
green of the two (Hillesluis: GSI 0.24, Shannon 0.42, 17.7 trees/ha, SVF 0.75).
If the design is meant to address a deficit, those are the ones the indicators
point at.

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

Both are in the literature and **they are not the same number** — here they are
0.696 and 0.526. The cos² form is cosine-weighted, so sky near the
zenith counts for more; that governs radiation exchange and is what urban
climatology means by SVF. Both go into `svf_summary.json`.

### Choices worth defending

- **Observer at 1.75 m above the DTM**, not on the surface model: what a person
  in the street sees, not what a roof sees.
- **Obstruction surface is the DSM**, so tree crowns count. Vegetation lowering
  SVF is a real effect, not noise.
- **Open-ground mask** (`nDSM < 2 m`): statistics exclude roofs, where SVF is
  meaningless.
- **0.5 m cells, 32 directions, 100 m search radius.** Resolution changes the
  answer — coarser cells average away tree crowns and report the place as more
  open than it is. Quote the cell size with the number.
- **150 m of context is downloaded beyond the boundary** and cropped afterwards,
  because a building just outside still blocks sky inside.
- **AHN gaps are filled** by nearest-neighbour dilation. Left as nodata they act
  as bottomless pits and the horizon search sees straight through them.

### Vegetation effect

0.70 in the open against 0.35 under a tree crown, a drop of
0.35 (50 %), over Bloemhof's raster (0.79 against 0.46 over the earlier
two-buurt raster). Street trees are doing measurable work on enclosure,
which connects the vegetation component directly to the morphology one.

## Density — Spacematrix

Berghauser Pont & Haupt (2010). Density is not one number: a packed low-rise
terrace and a tower in a park can share an FSI and be nothing alike.

```
GSI = built footprint / land area     coverage
FSI = gross floor area / land area    intensity
L   = FSI / GSI                       mean storeys
OSR = (1 - GSI) / FSI                 open space per m² of floor space
```

- **Storey height is measured, not assumed** — 3.06 m, the median over
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

### The diagram, and why it is worth plotting

GSI and FSI fix the other two indicators, so a GSI–FSI scatter carries all four:
L is a straight line through the origin, OSR is a curve. Fabric types separate by
*where* they sit, which no single number shows. `make_figures.py` writes the static
`docs/fig_spacematrix.png`; `app/modules/indicators.js` draws the same diagram in
the dashboard from the 107 per-cell points in `density_summary.json`, coloured
by buurt, so the proposed massing can later be overplotted to show the new fabric
move relative to the existing one.

Each point carries a `buurt` label, assigned by whichever polygon contains the
cell **centre** — 81 Bloemhof,
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

## Land-use mix — method

Shannon entropy (normalised) and Simpson diversity over BAG `gebruiksdoel`,
**weighted by usable floor area**.

- Weighting by floor area rather than unit count roughly doubles the measured mix
  (0.144 → 0.267): most units are residential but non-residential
  ones are individually much larger. Both are reported.
- **N is the full 11-class BAG vocabulary, fixed a priori**, not "classes present
  here" — otherwise cells with shorter category lists score spuriously high.
- Multi-function units (a shop with a flat above) split their floor area evenly.
- **BAG covers addressable units only.** Parks, water and streets are invisible
  to it, so this is a mix of *built floor space*. Pair it with GSI for the
  built/unbuilt split. CBS Bestand Bodemgebruik was tried and rejected: newest
  edition 2017, and it resolves the area into a handful of polygons.

## Direct sun and shadows

Added by Stefan. Two parts that answer different questions:

- **`shadows.py` — how many hours of direct sun a place gets over a whole day.**
  It casts the sun across one clear day (equinox by default, every 30 min) over
  the AHN surface model and counts, per 1 m cell, the hours it is sunlit.
  Reported on open ground only, over the buurt and the design site, like the SVF.
- **The "Sun & shadows" card in the app — one instant.** It opens on *Live*:
  the sun as it stands right now in Rotterdam, clear-sky, for orientation only.
  Pick a reference day (equinox, summer or winter solstice) or drag the time, and
  the 3DBAG buildings cast live shadows in Cesium. Switch on *Plain white ground*
  under Imagery to see them without the photo's own shadows.

Both were checked: the sun position in Cesium, in `shadows.py` and in an
independent calculation agree to 0.1°, and a synthetic 40 m tower casts its
shadow in the right direction (within 1°) and to the right length in both.

Results, direct sun on open ground (clear sky, 1 m cells, sun every 30 min).
The equinox run is the app's overlay; the solstices use `--suffix` so they do
not overwrite it:

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
share under 2 h from 20 % to 22 %. SVF did not move (0.696 both times). In winter most of the site's open ground gets no direct sun at all:
streets ≈ 11 m wide between ~7 m walls are fully shaded by a sun that peaks at
about 15°. `shadow_figure.py` draws the three days over the site
(`docs/fig_shadow_site.png`).

The script keeps 50 m of the 150 m padding in its outputs, because the design
site's south edge (Strevelsweg) runs ~31 m past the buurt bounding box.

Limits, as the script states: a clear-sky upper bound, not measured sunshine;
tree crowns block as if solid; obstructions beyond `--radius` (300 m) are
ignored. In the live view, fine stripes can appear on roofs when zoomed far
out: Cesium's shadow map has limited detail over a large view. Close up the
shadows are clean.

## Street canyons — height-to-width ratio

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
| SVF, mean | 0.714 | 0.647 | 0.784 | 0.763 |
| SVF, median | 0.744 | 0.646 | 0.825 | 0.807 |
| sun 20 Mar, mean | 4.30 h | 3.78 h | 5.97 h | 5.79 h |
| sun 21 Jun, mean | 8.61 h | 8.81 h | 10.19 h | 10.25 h |
| sun 21 Dec, mean | 0.53 h | 0.49 h | 1.32 h | 1.09 h |
| sun 20 Mar, share < 2 h | 22 % | 40 % | 13 % | 22 % |
| sun 21 Dec, share < 2 h | 87 % | 87 % | 67 % | 72 % |
| street H/W, median | 0.39 | 0.48 | 0.28 | 0.29 |
| street length that is canyon | 76 % | 74 % | 47 % | 60 % |
| street width W, median | 22.9 m | 24.6 m | 47.1 m | 38.1 m |

Demolition opens ground, so the open-ground means cover different areas in
each column: quote the shares next to the means (CLAUDE.md). Scenario A's
rows of 12 to 20 m blocks close the site in, with less sky and nearly twice
today's share of open ground under 2 h of equinox sun. Scenario B puts a smaller
built footprint in a park and opens it up on every measure. Its streets are
wide and few, so about half of its street length is not a canyon at all.

## For the scenario comparison

These indicators are the measuring stick. Add the proposed massing, re-run, and
compare — the Spacematrix plot will show the new fabric moving relative to the
existing one.
