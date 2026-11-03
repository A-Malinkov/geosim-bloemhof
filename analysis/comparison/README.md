# analysis/comparison - Scenario comparison

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
with the shops, health practices and second school that
`analysis/roads/place_amenities.py` puts back on their ground floors. The
community centre and school in the kept block stays fixed where it is. A third
measure, *network only*, leaves the site's own amenities out of every scenario,
today included, so only the street network differs: that is what
`analysis/roads/` reports.

**Not computed is shown, not dropped.** CBS demographics describe today's
residents only and have a row that says so. Flood vulnerability is today only.
Wind (OpenFOAM, the design site's open ground at 1.5 m) and road noise
(NoiseModelling, the site plus 200 m) run for every scenario since 2026-11-03.

## Results

| | Today | Scenario A | Scenario B | Final design | better |
|---|---|---|---|---|---|
| dwellings on the site | 1,027 | 1,920 | 1,250 | 777 | higher |
| buildings demolished | 0 | 1,150 | 1,150 | 1,150 | lower |
| FSI, floor area / site | 0.88 | 1.37 | 0.91 | 0.75 | context |
| GSI, footprint / site | 0.32 | 0.27 | 0.17 | 0.17 | context |
| tallest building | 30 m | 40 m | 27 m | 25 m | context |
| sky view factor, mean | 0.78 | 0.70 | 0.85 | 0.82 | higher |
| sun at the equinox, mean | 4.3 h | 3.8 h | 6.0 h | 5.8 h | higher |
| open ground under 2 h sun, equinox | 22 % | 40 % | 13 % | 22 % | lower |
| open ground under 2 h sun, 21 Dec | 87 % | 87 % | 67 % | 71 % | lower |
| sun on 21 Jun, mean | 8.6 h | 8.8 h | 10.2 h | 10.3 h | context |
| street H/W, median | 0.39 | 0.48 | 0.28 | 0.28 | context |
| existing trees kept on the site | 104 | 86 | 93 | 82 | higher |
| proposed trees | n/a | 64 | 98 | 92 | higher |
| green area, total, gardens included | 40,229 m² | 26,054 m² | 46,454 m² | 48,423 m² | higher |
| proposed green area | n/a | 21,545 m² | 41,910 m² | 38,411 m² | higher |
| proposed water area | n/a | 671 m² | 671 m² | 671 m² | higher |
| shops on the site | 20 | 20 | 20 | 43 | higher |
| health practices on the site | 7 | 7 | 7 | 7 | higher |
| schools on the site | 2 | 2 | 2 | 1 | higher |
| community halls on the site | 7 | 3 | 3 | 3 | higher |
| walk to 4 everyday places, residents, housing only | 317 m | 394 m | 391 m | 355 m | lower |
| walk to 4 everyday places, site grid, housing only | 314 m | 371 m | 377 m | 368 m | lower |
| residents, with the placed amenities | 317 m | 254 m | 263 m | 269 m | lower |
| site grid, with the placed amenities | 314 m | 251 m | 260 m | 278 m | lower |
| site grid, network only | 376 m | 371 m | 377 m | 368 m | lower |
| intersection density | 446 /km² | 582 /km² | 310 /km² | 702 /km² | higher |
| land-use objective J | 2.100 | 2.196 | 2.840 | 2.955 | higher |
| land-use mix | 0.229 | 0.318 | 0.530 | 0.728 | higher |
| green share of 25 m cells | 3 % | 6 % | 33 % | 30 % | higher |
| land-use objective J, with the placed amenities | n/a | 2.865 | 3.357 | 3.041 | higher |
| land-use mix, with the placed amenities | n/a | 0.623 | 0.755 | 0.779 | higher |
| wind-speed ratio at 1.5 m, mean | 0.52 | 0.55 | 0.79 | 0.68 | context |
| open ground windier than open country (ratio > 1.1) | 3 % | 4 % | 10 % | 6 % | lower |
| open ground sheltered (ratio < 0.5) | 53 % | 48 % | 17 % | 27 % | context |
| road noise Lden, mean, site + 200 m | 56.0 dB | 56.6 dB | 57.0 dB | 56.8 dB | lower |
| above 53 dB Lden, site + 200 m | 68 % | 69 % | 72 % | 70 % | lower |
| above 70 dB Lden, site + 200 m | 11 % | 11 % | 12 % | 11 % | lower |
| flood vulnerability high or very high | 61 % | not run | not run | not run | lower |

Sources: dwellings from `road_metrics.json` (BAG today, the road network's
estimate in the scenarios), demolition and heights from `design_massing.geojson`,
FSI and GSI from the 3DBAG footprints on the site plus the new blocks with
storeys = round(height above ground / 3 m) (flats stood on a shop podium: their own
height, and no ground cover of their own), sky and sun from `svf_summary*.json`
and `shadow_summary*.json`, H/W from `canyon_hw_*.json`, trees from
`trees.geojson` / `trees_<scenario>.geojson` plus the proposed trees in
`design_planting.geojson`, walking from `road_metrics.json` and
`amenity_placement.json` (today with its own amenities, and the placed ones),
land use from `landuse_scenarios.json` (the site, open ground between blocks
counted vacant as on today's grid), flood from `flood_summary.json`.

**A trades daylight for homes.** It nearly doubles the dwellings (1,027 to an
estimated 1,920) and its share of open ground with under 2 h of sun at the
equinox rises from 22 % to 40 %. Mean sky view drops from 0.78 to 0.70.

**B is brighter than today but adds few homes.** Open ground under 2 h of sun
falls to 13 % at the equinox and from 87 % to 67 % on 21 December, and it has
the most trees and twice A's proposed green. It demolishes the same 1,150
buildings to gain about 220 dwellings.

**The final design keeps today's sun at the equinox, with fewer homes than today.**
It estimates 777 dwellings, fewer than today's 1,027, on terraced and
semi-detached houses up to 25 m. Open ground under 2 h of sun at the equinox
stays at today's 22 % and falls from 87 % to 71 % on 21 December; mean sky view
rises from 0.78 to 0.82. It is the only design that names its shops: 50 shop
units from the Rhino block names, against today's 20. The model has no health
practice, so 7 of those units become one, picked by the same optimiser as A and
B use but only among the model's own shop units: 43 shops, 7 health practices
and one school (the kept one). Its residents walk 269 m to the four everyday
places, 48 m less than today.

**Housing only makes everyday walks longer. Putting the amenities back makes
them shorter than today.** Today a resident of the site walks 317 m on average
to the nearest shop, school, health practice and rail stop. With the site's
shops and services demolished and not replaced, that becomes 394 m in A and
391 m in B. With 20 shops, 7 health practices and a second school placed on the
new ground floors where they shorten walks most, and the kept school, it falls
to 254 m in A and 263 m in B. The street network alone barely matters: on the network-only measure A's
denser grid (582 junctions per km² against 446) saves 5 m and B's open layout
(310) changes nothing.

**B scores far higher on the land-use objective, for a reason to read with
care.** The objective (`analysis/abm_landuse/`) rewards mix and green, and since
2026-10-30 homes against today's, capped at today. A and B both build more homes
than they demolish, so both get the full housing term and A's extra homes earn
nothing. The gap is mix and green: B has 33 % green against A's 6 %. On its 25 m
cells B keeps 48 residential cells against 160 today and A 99, because cells
count ground covered, not dwellings. The final design scores highest even
though the housing term costs it: 777 homes against today's 1,027.

**Both demolish everything on the cleared part of the site**, 1,150 buildings,
1,027 homes, most of them built 1919–1940.

**Amenities: shops, health and the second school come back, four halls do
not.** Today's site holds 20 shops, 7 health practices, 2 schools and 7
community halls (BAG). The options keep the community centre and school block
(1 school, 3 halls, fixed) and get 20 shops, 7 health practices and 1 school
placed on their ground floors (`analysis/roads/place_amenities.py`). Four
halls are gone. Today's shops line Strevelsweg, the site's
shopping street. The placement spreads them through the blocks instead,
because it minimises walking distance and knows nothing of footfall.
`docs/fig_amenities.png` maps all three.

## Figures

| file | shows |
|---|---|
| `fig_compare_scorecard.png` | every indicator, shaded blue where better than today and red where worse, by its own direction; the not-computed rows |
| `fig_compare_tradeoff.png` | dwellings against shaded open ground, and against walking distance, housing only and with the placed amenities |
| `fig_compare_distributions.png` | the share of open ground at or below each sun-hours and SVF value, three days |
| `fig_compare_difference_maps.png` | scenario minus today, cell by cell, sun hours (equinox, 21 Dec) and SVF, new blocks drawn |
| `fig_compare_walking.png` | mean walk to each destination type, residents and site grid, today with its own amenities, the options housing only and with the placed amenities |
| `fig_compare_canyon.png` | canyon street length by H/W class |
| `fig_amenities.png` (from `analysis/roads/place_amenities.py`) | today's amenities on the site, demolished ones hollow, and each option's placed and kept ones |

## What it cannot tell you

- The scenario dwellings are an estimate (`analysis/roads/README.md`), and floor
  area uses one storey rule for every building, today's included.
- Means over open ground cover different ground in each scenario (above).
- No social indicator for the scenarios: CBS describes today's residents.
- Noise covers the site plus 200 m, so its shares are not over the same area as
  the other rows. Its traffic still runs on the OSM network, old interior streets
  included (`analysis/wind_noise/README.md`).
- The difference maps compare cells that are open ground in both runs. Where a
  new block stands, or an old one stood, there is no difference to show.
- The proposed planting counts what is drawn in the Rhino model. It is not in
  the sun runs, which see today's trees only (minus those under new blocks and
  streets). The SVF sees no trees at all, only buildings.
