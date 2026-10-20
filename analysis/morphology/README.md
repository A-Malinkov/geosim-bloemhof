# analysis/morphology — urban morphology indicators

Owner: **Atanas Malinkov** · feeds `app/modules/indicators.js` and `app/modules/vegetation.js`

> Numbers here are generated from `data/processed/*.json`. Re-run an analysis and
> they go stale silently — regenerate this file and run
> `python analysis/check_docs.py`.

**The study area is two buurten**, Bloemhof and Hillesluis, analysed separately
and together. Every indicator below is clipped to the buurt polygons, so the
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

| indicator | Bloemhof | Hillesluis | both |
|---|---|---|---|
| **Sky View Factor** | 0.696 | 0.748 | **0.726** |
| **GSI** ground space index | 0.333 | 0.241 | **0.284** |
| **FSI** floor space index | 1.003 | 0.922 | **0.960** |
| **L** storeys | 3.01 | 3.82 | **3.38** |
| **OSR** | 0.67 | 0.82 | **0.75** |
| **mean building height** | 8.5 m | 11.2 m | **9.5 m** |
| **height variation σ** | 2.9 m | 2.5 m | **3.1 m** |
| **land-use mix** Shannon | 0.267 | 0.422 | **0.351** |
| **trees** | 1,204 | 1,598 | **2,802** |
| **trees per hectare** | 15.3 | 17.7 | **16.6** |
| **canopy cover** | 6.6 % | 9.0 % | **7.9 %** |

### The two buurten are not the same place

Worth a paragraph in the report, because it is the main thing comparing them buys:

- **Hillesluis is less built-up but taller.** GSI 0.24 against Bloemhof's
  0.33, yet 3.8 storeys against 3.0. Similar floor space
  (FSI 0.92 vs 1.00) delivered by a different fabric.
- **Hillesluis is markedly more mixed.** Shannon 0.422 against 0.267;
  86 % of Bloemhof's floor space is residential against
  74 % in Hillesluis.
- **Hillesluis is greener and more open.** 17.7 trees/ha against 15.3,
  canopy 9.0 % against 6.6 %, and SVF
  0.75 against 0.70.

Bloemhof is the denser, more enclosed, more mono-functional of the two. If the
design is meant to address a deficit, Bloemhof is where the indicators say it is.

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
0.726 and 0.576. The cos² form is cosine-weighted, so sky near the
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

0.79 in the open against 0.46 under a tree crown, a drop of
0.33 (42 %). Street trees are doing measurable work on enclosure,
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
  records are outbuildings holding 10 % of the built area. They cover
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
the dashboard from the 200 per-cell points in `density_summary.json`, coloured
by buurt, so the proposed massing can later be overplotted to show the new fabric
move relative to the existing two.

Each point now carries a `buurt` label, assigned by whichever polygon contains the
cell **centre** — 81 Bloemhof,
68 Hillesluis,
51 outside both (the bounding box is larger
than the buurten). A cell on the boundary goes to one side rather than being counted
twice.

### The two scales disagree, and that is the finding

| | FSI over the whole buurt | mean FSI over built cells |
|---|---|---|
| Bloemhof | 1.003 | 0.97 |
| Hillesluis | 0.922 | 1.24 |

Hillesluis reads as the **looser** buurt at buurt scale and the **denser** one at
cell scale. Both are correct. The buurt figure divides floor area by all of its
land, gaps included, and Hillesluis has more gaps; the grid mean averages only
cells holding at least 3 buildings, so it
describes built fabric and ignores the gaps. This is the modifiable areal unit
problem arriving in a number we publish, which is why the cell size travels with
every figure. The app states the reversal in the panel, generated from the data so
it disappears if a re-run removes it.

## Land-use mix — method

Shannon entropy (normalised) and Simpson diversity over BAG `gebruiksdoel`,
**weighted by usable floor area**.

- Weighting by floor area rather than unit count roughly doubles the measured mix
  (0.160 → 0.351): most units are residential but non-residential
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
  Reported on open ground only, per buurt and combined, like the SVF.
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

| Day | Daylight | Bloemhof | Hillesluis | Design site (median, share < 2 h) |
|---|---|---|---|---|
| 21 Dec | 7.5 h | 0.65 h | 1.90 h | 0.0 h, 87 % |
| 20 Mar | 12.0 h | 4.44 h | 5.81 h | 4.5 h, 20 % |
| 21 Jun | 16.5 h | 8.35 h | 9.84 h | 9.0 h, 1 % |

Buurt columns are means. Bloemhof is shadier than Hillesluis, consistent with its
lower SVF. In winter most of the site's open ground gets no direct sun at all:
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
length, clipped to each buurt and to the design site.

Baseline (from `canyon_hw_baseline.json`):

| | H/W median | wall height H | width W | street length that is canyon |
|---|---|---|---|---|
| Bloemhof | 0.42 | 8.0 m | 19.9 m | 67 % |
| Hillesluis | 0.45 | 12.1 m | 29.1 m | 56 % |
| both | 0.43 | 9.8 m | 22.4 m | 61 % |
| design site | 0.41 | 7.3 m | 22.9 m | 76 % |

The two buurten land on almost the same H/W by opposite routes: Bloemhof has
low walls on narrow streets, Hillesluis taller walls on wider ones. On the
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

## For the scenario comparison

These indicators are the measuring stick. Add the proposed massing, re-run, and
compare — the Spacematrix plot will show the new fabric moving relative to the
existing two.
