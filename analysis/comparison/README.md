# analysis/comparison — Scenario comparison

Component 9 · owner: Atanas Malinkov (built 2026-10-27) · feeds `app/modules/comparison.js`

Today, scenario A and scenario B side by side on the design site, indicator by
indicator, from what the other components already wrote.

```bash
python analysis/comparison/compare_scenarios.py
```

It writes `data/processed/scenario_comparison.json` and the `docs/fig_compare_*.png`
figures. It needs the SVF and sun-hours rasters (`svf*.tif`, `shadow_hours*.tif`),
which are gitignored. Rebuild them with `sky_view_factor.py --scenario X` and
`shadows.py --scenario X` (three days each, see its docstring). The script
re-applies the scripts' open-ground rule to the rasters and stops if the mean on
the site does not reproduce the published one to 0.0005.

## How the scenarios are compared

**Same ground.** Every value is over the 13.24 ha design site, the only place
the scenarios differ.

**No overall score.** The indicators are not added up. A sum needs weights, and
the weights would pick the winner: the land-use sweep (`analysis/abm_landuse/`)
showed how much a ranking moves with them. Each indicator is shown on its own,
with the direction that counts as better, and the figures show the trade-offs.

**Better and worse are stated per indicator.** Fewer demolished buildings, more
sky, more sun in spring and winter, more trees, shorter walks and more
junctions count as better. Density (FSI, GSI), height, street H/W and summer sun
have no better direction here: more summer sun is also more heat, and H/W is
good or bad depending on the street. They are shown as context, not coloured.

**Means over open ground cover different ground.** Demolition opens up land and
new blocks cover it, so the open ground on the site is not the same in the three
runs. Shares (open ground under 2 h of sun) are given beside means.

**Two origins for walking.** *Residents* are weighted by dwellings, so they move
with where people live. The *site grid* is the same 332 points in every
scenario, so it moves with the network alone (`analysis/roads/`).

**Today counts its own shops.** Today's walks include the 20 shops, 7 health
practices and the school standing on the cleared ground, where they are. The
options are walked as modelled (housing only, those amenities gone), and again
with the shops, health practices and school that
`analysis/roads/place_amenities.py` puts back on their ground floors. A third
measure, *network only*, leaves the site's own amenities out of every scenario,
today included, so only the street network differs: that is what
`analysis/roads/` reports.

**Not computed is shown, not dropped.** Wind (OpenFOAM cases set up, not run),
noise for the scenarios (baseline only) and CBS demographics (not started) have
a row that says so. Flood vulnerability is today only.

## Results

| | Today | Scenario A | Scenario B | better |
|---|---|---|---|---|
| dwellings on the site | 1,027 | 1,920 | 1,250 | higher |
| buildings demolished | 0 | 1,150 | 1,150 | lower |
| FSI, floor area / site | 0.88 | 1.37 | 0.91 | context |
| GSI, footprint / site | 0.32 | 0.27 | 0.17 | context |
| tallest building | 30 m | 40 m | 27 m | context |
| sky view factor, mean | 0.71 | 0.65 | 0.78 | higher |
| sun at the equinox, mean | 4.3 h | 3.8 h | 6.0 h | higher |
| open ground under 2 h sun, equinox | 22 % | 40 % | 13 % | lower |
| open ground under 2 h sun, 21 Dec | 87 % | 87 % | 67 % | lower |
| sun on 21 Jun, mean | 8.6 h | 8.8 h | 10.2 h | context |
| street H/W, median | 0.39 | 0.48 | 0.28 | context |
| existing trees kept on the site | 104 | 86 | 93 | higher |
| proposed trees | n/a | 64 | 99 | higher |
| proposed green area | n/a | 21,135 m² | 41,499 m² | higher |
| proposed water area | n/a | 1,082 m² | 1,082 m² | higher |
| walk to 4 everyday places, residents, housing only | 317 m | 395 m | 391 m | lower |
| walk to 4 everyday places, site grid, housing only | 314 m | 371 m | 378 m | lower |
| residents, with the placed amenities | 317 m | 253 m | 263 m | lower |
| site grid, with the placed amenities | 314 m | 252 m | 261 m | lower |
| site grid, network only | 377 m | 371 m | 378 m | lower |
| network only, with the optimiser's footpaths | n/a | 370 m | 375 m | lower |
| intersection density | 423 /km² | 589 /km² | 287 /km² | higher |
| land-use objective J | 1.000 | 1.074 | 1.737 | higher |
| land-use mix | 0.229 | 0.308 | 0.532 | higher |
| green share of 25 m cells | 3 % | 5 % | 33 % | higher |
| land-use objective J, with the placed amenities | n/a | 1.762 | 2.256 | higher |
| land-use mix, with the placed amenities | n/a | 0.623 | 0.758 | higher |
| flood vulnerability high or very high | 61 % | not run | not run | lower |

Sources: dwellings from `road_metrics.json` (BAG today, the road network's
estimate in the scenarios), demolition and heights from `design_massing.geojson`,
FSI and GSI from the 3DBAG footprints on the site plus the new blocks with
storeys = round(height above ground / 3 m), sky and sun from `svf_summary*.json`
and `shadow_summary*.json`, H/W from `canyon_hw_*.json`, trees from
`trees.geojson` / `trees_<scenario>.geojson` plus the proposed trees in
`design_planting.geojson`, walking from `road_metrics.json`, `road_links.json` and
`amenity_placement.json` (today with its own amenities, and the placed ones),
land use from `landuse_scenarios.json` (the site, open ground between blocks
counted vacant as on today's grid), flood from `flood_summary.json`.

**A trades daylight for homes.** It nearly doubles the dwellings (1,027 to an
estimated 1,920) and its share of open ground with under 2 h of sun at the
equinox rises from 22 % to 40 %. Mean sky view drops from 0.71 to 0.65.

**B is brighter than today but adds few homes.** Open ground under 2 h of sun
falls to 13 % at the equinox and from 87 % to 67 % on 21 December, and it has
the most trees and twice A's proposed green. It demolishes the same 1,150
buildings to gain about 220 dwellings.

**Housing only makes everyday walks longer. Putting the amenities back makes
them shorter than today.** Today a resident of the site walks 317 m on average
to the nearest shop, school, health practice and rail stop. With the site's
shops and services demolished and not replaced, that becomes 395 m in A and
391 m in B. With 20 shops, 7 health practices and one school placed on the new
ground floors where they shorten walks most, it falls to 253 m in A and 263 m
in B. The street network alone barely matters: on the network-only measure A's
denser grid (589 junctions per km² against 423) saves 6 m and B's open layout
(287) changes nothing.

**B scores far higher on the land-use objective, for a reason to read with
care.** The objective (`analysis/abm_landuse/`) rewards mix and green and has no
term for homes. On its 25 m cells B keeps 48 residential cells against 160
today and A 99, because cells count ground covered, not dwellings. A low-rise
green plan with fewer, taller homes scores well by construction.

**Both demolish everything on the cleared part of the site**, 1,150 buildings,
1,027 homes, most of them built 1919–1940.

## Figures

| file | shows |
|---|---|
| `fig_compare_scorecard.png` | every indicator, shaded blue where better than today and red where worse, by its own direction; the not-computed rows |
| `fig_compare_tradeoff.png` | dwellings against shaded open ground, and against walking distance, housing only and with the placed amenities |
| `fig_compare_distributions.png` | the share of open ground at or below each sun-hours and SVF value, three days |
| `fig_compare_difference_maps.png` | scenario minus today, cell by cell, sun hours (equinox, 21 Dec) and SVF, new blocks drawn |
| `fig_compare_walking.png` | mean walk to each destination type, residents and site grid, today with its own amenities, the options housing only and with the placed amenities |
| `fig_compare_canyon.png` | canyon street length by H/W class |

## What it cannot tell you

- The scenario dwellings are an estimate (`analysis/roads/README.md`), and floor
  area uses one storey rule for every building, today's included.
- Means over open ground cover different ground in each scenario (above).
- No wind, noise or social indicator for the scenarios yet. Those are the first
  a jury asks about for 30–40 m towers and blocks fronting main roads.
- The difference maps compare cells that are open ground in both runs. Where a
  new block stands, or an old one stood, there is no difference to show.
- The proposed planting counts what is drawn in the Rhino model. It is not in
  the SVF or sun runs, which see today's trees only (minus those under new
  blocks and streets).
