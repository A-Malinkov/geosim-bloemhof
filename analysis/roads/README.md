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
that crosses no new block. 18 connectors, 117 m in all. They assume the design's
streets meet the edge streets. The edge streets themselves (Lange Hilleweg,
Sandelingstraat, Dortsmondstraat, Dubbelstraat, Strevelsweg) are kept whole by
name, because Strevelsweg runs up to 20 m inside the site outline.

**Homes.** BAG addresses with woonfunctie, one per dwelling. A scenario drops
the addresses in demolished buildings and adds the new blocks' dwellings,
estimated as footprint × storeys (height / 3 m) × 0.8 net/gross / 73 m², the
median BAG dwelling on the site today. That gives 1,920 dwellings in Scenario A
against 1,027 today, each block's at its centroid.

**Destinations.** Shops (BAG winkelfunctie), education (onderwijsfunctie),
health care (gezondheidszorgfunctie) and rail stops (OSM tram, metro and train).
The same set in every scenario. Destinations on ground a scenario clears are left
out of all of them, so a difference between scenarios comes from the network and
the homes and not from shops the design removes. That ground holds 20 shops, 1
education and 7 health care addresses today. The block Scenario A keeps (added
to the site on 2026-10-21) stays a destination, school included.

**Distance.** Each home and destination is snapped to the nearest point on the
nearest edge. Walking distance is the access leg plus the network distance, by
one Dijkstra per destination type from all its destinations at once (scipy).
Checked against an independent networkx implementation on 60 homes per scenario
and two destination types, max difference 0.000000 m.

**Two sets of origins on the site.** *Dwellings* move with who lives there, so
they mix the network effect with the new housing. The *site grid* is the same
332 points every 20 m in every scenario, so it moves with the network alone.

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
| nodes | 717 | 747 | 72 | 105 |
| edges | 1,089 | 1,126 | 90 | 126 |
| network length | 53.61 km | 54.70 km | 4.83 km | 5.86 km |
| avg edge length | 49.2 m | 48.6 m | 53.7 m | 46.5 m |
| intersection density | 373.7 /km² | 376.7 /km² | 422.9 /km² | 453.1 /km² |
| circuity | 1.022 | 1.020 | 1.032 | 1.007 |
| max edge betweenness | 0.0961 | 0.0955 | 0.0788 | 0.0813 |

Mean walk to the nearest destination, design site.

| | dwellings, baseline | dwellings, Scenario A | site grid, baseline | site grid, Scenario A |
|---|---|---|---|---|
| shop | 234 m | 250 m | 228 m | 222 m |
| education | 269 m | 300 m | 258 m | 283 m |
| health care | 412 m | 450 m | 411 m | 444 m |
| rail stop | 637 m | 628 m | 613 m | 600 m |
| **mean of the four** | **387.9 m** | **407.2 m** | **377.4 m** | **387.3 m** |

**Scenario A's street layout makes everyday walks on the site slightly
longer.** On the fixed grid the mean of the four rises from 377.4 m to 387.3 m,
10 m. The new grid has more junctions (423 to 453 per km²) and straighter streets
(circuity 1.032 to 1.007). It loses on education and health care, which lie
across the long east-west streets, and gains a little on shops and rail stops.

**Residents walk further than the grid suggests.** Site dwellings go from
387.9 m to 407.2 m. Most of the 19 m is where the dwellings are, not the
network. The new blocks hold 1,920 estimated dwellings, against 1,027 today.

**The neighbours do not notice.** Dwellings outside the site stay at 242.4 m.

**The 15-minute walk does not separate anything.** Every dwelling in both
buurten reaches all four types within 15 min (1,200 m) in both scenarios. The
5-minute share (400 m) is what varies. On the site no dwelling has a rail stop
within 5 min in Scenario A, 2 % do today.

### Footpath links, Scenario A

60 candidates. J starts at 267.92 m, the ceiling is 265.45 m.

| # | length | J saved | J | site dwellings | site grid | of ceiling |
|---|---|---|---|---|---|---|
| 1 | 44 m | 1.00 m | 266.93 m | 400.7 m | 380.2 m | 40 % |
| 2 | 95 m | 0.64 m | 266.29 m | 396.6 m | 375.7 m | 66 % |
| 3 | 46 m | 0.35 m | 265.94 m | 394.3 m | 375.2 m | 80 % |
| 4 | 30 m | 0.12 m | 265.82 m | 393.5 m | 374.7 m | 85 % |
| 5 | 11 m | 0.09 m | 265.72 m | 392.9 m | 374.3 m | 89 % |
| 6 | 32 m | 0.08 m | 265.65 m | 392.5 m | 373.6 m | 92 % |
| 7 | 21 m | 0.04 m | 265.61 m | 392.2 m | 373.2 m | 94 % |
| 8 | 45 m | 0.07 m | 265.54 m | 391.8 m | 372.7 m | 96 % |
| 9 | 45 m | 0.02 m | 265.52 m | 391.6 m | 372.0 m | 97 % |
| 10 | 50 m | 0.02 m | 265.50 m | 391.5 m | 371.9 m | 98 % |

**Two links, 139 m of footpath, bring the site grid back below today's.** After
link 2 it is 375.7 m, against 377.4 m now. Link 1 opens the north tip to Lange
Hilleweg, link 2 runs east from the central street to Dubbelstraat.

**Six links, 258 m, take 92 % of what all 60 candidates could give.** After
link 6 each link saves under 0.1 m of J. Site dwellings come back from 407.2 m
to 392.5 m, close to today's 387.9 m.

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
