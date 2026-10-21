# analysis/roads — Road network

Component 8 · owner: Atanas Malinkov (built 2026-10-21) · feeds `app/modules/roads.js`

The walking network per scenario, how far homes are from everyday destinations,
and which new footpaths through the design site would shorten those walks most.

| script | does | writes |
|---|---|---|
| `road_network.py` | network metrics and walking distances per scenario | `data/processed/road_metrics.json`, `roads_<scenario>.geojson` |
| `optimise_links.py` | greedy choice of new footpaths on the site | `data/processed/road_links.json`, `road_links_<scenario>.geojson` |

```bash
python analysis/roads/road_network.py      # first run fetches OSM into cache/roads/, about 3 min
python analysis/roads/optimise_links.py    # needs road_network.py's output, about 15 s
```

Both have one case dict per scenario in `CASES`. `scenario_b` is written as
not computed until it has massing.

## Method

**Network.** OSM walk network (osmnx 2.1.1, `network_type="walk"`) over the two
buurten plus 500 m, so routes and betweenness near the edge see the streets
beyond it. Undirected, weighted by length in RD.

**Scenario.** `streets_for_scenario()` in `analysis/scenarios/scenario_world.py`
cuts the old streets out of the site interior and adds centrelines traced from
the new street surfaces, the same helper street H/W uses. The surfaces in the
Rhino model stop short of the edge streets in places, so each free end of a new
centreline is joined to the nearest street within 35 m by a straight connector
that crosses no new block. 21 connectors, 123 m in all. They assume the design's
streets meet the edge streets.

**Homes.** BAG addresses with woonfunctie, one per dwelling. A scenario drops
the addresses in demolished buildings and adds the new blocks' dwellings,
estimated as footprint × storeys (height / 3 m) × 0.8 net/gross / 73 m², the
median BAG dwelling on the site today. That gives 1,910 dwellings in Scenario A
against 1,027 today, each block's at its centroid.

**Destinations.** Shops (BAG winkelfunctie), education (onderwijsfunctie),
health care (gezondheidszorgfunctie) and rail stops (OSM tram, metro and train).
The same set in every scenario. Destinations on the design site are left out of
all of them, so a difference between scenarios comes from the network and the
homes and not from shops the design removes. The site holds 20 shops, 1
education and 7 health care addresses today.

**Distance.** Each home and destination is snapped to the nearest point on the
nearest edge. Walking distance is the access leg plus the network distance, by
one Dijkstra per destination type from all its destinations at once (scipy).
Checked against an independent networkx implementation on 60 homes per scenario
and two destination types, max difference 0.000000 m.

**Two sets of origins on the site.** *Dwellings* move with who lives there, so
they mix the network effect with the new housing. The *site grid* is the same
311 points every 20 m in every scenario, so it moves with the network alone.

**Optimiser.** Objective J is the mean walking distance from a dwelling to the
nearest shop, education, health care and rail stop, equal weights over the
four, dwelling-weighted over the whole study area. Candidates are straight
footpaths between two network nodes on the site or within 20 m of it, 10 to
150 m long, at most 20 m off the site, crossing no building, meeting the network
only at their two nodes, and saving a detour of at least 1.5× the straight line.
Greedy adds the candidate that lowers J most, re-scores the rest, and repeats
ten times. The ceiling is J with all candidates at once.

## Results

Network over each area. An edge counts in an area if its midpoint lies in it.

| | study area, baseline | study area, Scenario A | design site, baseline | design site, Scenario A |
|---|---|---|---|---|
| nodes | 717 | 751 | 69 | 99 |
| edges | 1,089 | 1,125 | 87 | 106 |
| network length | 53.61 km | 54.55 km | 4.63 km | 5.00 km |
| avg edge length | 49.2 m | 48.5 m | 53.2 m | 47.2 m |
| intersection density | 373.7 /km² | 376.1 /km² | 428.1 /km² | 339.3 /km² |
| circuity | 1.022 | 1.020 | 1.033 | 1.007 |
| max edge betweenness | 0.0961 | 0.107 | 0.0788 | 0.107 |

Mean walk to the nearest destination, design site.

| | dwellings, baseline | dwellings, Scenario A | site grid, baseline | site grid, Scenario A |
|---|---|---|---|---|
| shop | 234 m | 260 m | 232 m | 272 m |
| education | 269 m | 312 m | 266 m | 340 m |
| health care | 412 m | 475 m | 406 m | 467 m |
| rail stop | 637 m | 650 m | 620 m | 636 m |
| **mean of the four** | **387.9 m** | **424.2 m** | **380.9 m** | **428.6 m** |

**Scenario A's street layout lengthens everyday walks on the site.** On the
fixed grid the mean of the four rises from 380.9 m to 428.6 m, 48 m. The
network is longer and straighter (circuity 1.033 to 1.007) but has fewer
junctions (428 to 339 per km²). The long east-west streets meet each other
only at the central north-south street and at their ends, so a walk across the
grain goes round.

**The neighbours barely notice.** Dwellings outside the site go from 242.4 m to
243.0 m.

**The new diagonal becomes the busiest walking route in the study area.** The
highest edge betweenness, 0.107, is on the site in Scenario A. Today the
highest is 0.0961, outside the site.

**The 15-minute walk does not separate anything.** Every dwelling in both
buurten reaches all four types within 15 min (1,200 m) in both scenarios. The
5-minute share (400 m) is what varies. On the site no dwelling has a rail stop
within 5 min in Scenario A, 2 % do today.

### Footpath links, Scenario A

99 candidates. J starts at 270.91 m, the ceiling is 265.94 m.

| # | length | J saved | J | site dwellings | site grid | of ceiling |
|---|---|---|---|---|---|---|
| 1 | 44 m | 1.26 m | 269.65 m | 416.1 m | 419.5 m | 25 % |
| 2 | 75 m | 0.84 m | 268.81 m | 410.6 m | 417.6 m | 42 % |
| 3 | 60 m | 1.03 m | 267.78 m | 403.9 m | 414.0 m | 63 % |
| 4 | 95 m | 0.55 m | 267.23 m | 400.3 m | 410.8 m | 74 % |
| 5 | 20 m | 0.52 m | 266.71 m | 397.0 m | 407.6 m | 85 % |
| 6 | 107 m | 0.46 m | 266.25 m | 393.9 m | 402.9 m | 94 % |
| 7 | 30 m | 0.15 m | 266.10 m | 393.0 m | 402.3 m | 97 % |
| 8 | 110 m | 0.05 m | 266.05 m | 392.7 m | 402.0 m | 98 % |
| 9 | 32 m | 0.04 m | 266.02 m | 392.5 m | 401.8 m | 99 % |
| 10 | 45 m | 0.02 m | 266.00 m | 392.3 m | 401.3 m | 99 % |

**Six links, 401 m of footpath, take 94 % of what all 99 candidates could
give.** Site dwellings come back from 424.2 m to 393.9 m, close to today's
387.9 m. After link 6 each link saves under 0.2 m of J. Link 3 saves more than
link 2 because it extends it, a pair greedy happened to find in order.

J is over the whole study area, so its changes look small. The site columns
show where they land.

## What it cannot tell you

- OSM's walk network is only as complete as OSM. Pavements are mostly not
  mapped separately here, so a street centreline stands for both pavements.
- Destinations come from BAG over the study bounding box only. Homes near the
  outer edge miss shops just beyond it, so their distances are too long. Equal
  in every scenario.
- BAG records what a building is registered for, not whether the shop is open.
- The new blocks' dwelling count is an estimate, and each block's dwellings sit
  at its centroid, not at its entrances.
- Betweenness weights every pair of nodes equally. It is network position, not
  a traffic forecast. There is no drive network here, and noise traffic still
  runs on the OSM roads (see `analysis/wind_noise/`).
- Greedy is not guaranteed optimal. A pair of links that only help together is
  never picked unless one helps alone.
- The optimiser assumes the ground between the new blocks is public and
  walkable. In the baseline that ground is back gardens, so the baseline is not
  optimised.
- Distance only. Lighting, overlooking, steps and gradient are not modelled.
