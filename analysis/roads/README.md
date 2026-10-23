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

Both have one case dict per scenario in `CASES`: baseline, scenario_a and
scenario_b (the optimiser skips the baseline, see below).

## Method

**Network.** OSM walk network (osmnx 2.1.1, `network_type="walk"`) over
Bloemhof plus 500 m (over both buurten plus 500 m before 2026-10-22), so routes and betweenness near the edge see the streets
beyond it. Undirected, weighted by length in RD.

**Scenario.** `streets_for_scenario()` in `analysis/scenarios/scenario_world.py`
cuts the old streets out of the site interior and adds centrelines traced from
the new street surfaces, the same helper street H/W uses. The surfaces in the
Rhino model stop short of the edge streets in places, so each free end of a new
centreline is joined to the nearest street within 35 m by a straight connector
that crosses no new block. They assume the design's streets meet the edge
streets. Then every crossing or touch between a scenario street and any other
street becomes a junction, and an old street end within 5 m of a new street (or
a new end within 5 m of an old street) is joined to it. OSM's own crossings are
left alone, because there a crossing without a node is mostly a bridge. Graph
nodes closer than 0.5 m are merged into one junction. In Scenario A that is 18
free-end connectors, 8 crossings made junctions and 12 joins, 33 connectors, 135 m
in all after splitting; in Scenario B 7 connectors, 2 crossings and 6 joins.
Before 2026-10-23 the graph made no junction at those crossings and split two
ends 0.1 m apart into two nodes, so Scenario A's main street was cut in two and
its new streets did not meet Lange Hilleweg, Strevelsweg or Dubbelstraat. Eight
of the ten footpath links the optimiser chose then only repaired that. The edge streets themselves (Lange Hilleweg,
Sandelingstraat, Dortsmondstraat, Dubbelstraat, Strevelsweg) are kept whole by
name, because Strevelsweg runs up to 20 m inside the site outline.

**Homes.** BAG addresses with woonfunctie, one per dwelling. A scenario drops
the addresses in demolished buildings and adds the new blocks' dwellings,
estimated as footprint × storeys (height / 3 m) × 0.8 net/gross / 73 m², the
median BAG dwelling on the site today. That gives 1,920 dwellings in Scenario A
and 1,250 in Scenario B, against 1,027 today, each block's at its centroid.

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
150 m long, at most 20 m off the site, crossing no building and no water,
starting or ending on the design's own network (a new street or connector),
meeting the network only at their two nodes, and saving a detour of at least
1.5× the straight line. The own-network rule keeps out links that only mend a
gap OSM has today too, such as a footway ending 2 m short of Lange Hilleweg at
the site's west tip. Greedy adds the candidate that lowers J most, re-scores the
rest, and repeats up to ten times, stopping when no candidate lowers J by 1 mm.
The ceiling is J with all candidates at once.

## Results

Network over each area. An edge counts in an area if its midpoint lies in it.

| | study area, baseline | study area, Scenario A | study area, Scenario B | design site, baseline | design site, Scenario A | design site, Scenario B |
|---|---|---|---|---|---|---|
| nodes | 343 | 376 | 336 | 72 | 110 | 63 |
| edges | 537 | 597 | 531 | 90 | 156 | 78 |
| network length | 25.85 km | 26.96 km | 24.78 km | 4.83 km | 5.88 km | 3.68 km |
| avg edge length | 48.1 m | 45.2 m | 46.7 m | 53.7 m | 37.7 m | 47.2 m |
| intersection density | 402.1 /km² | 414.8 /km² | 376.7 /km² | 422.9 /km² | 513.5 /km² | 249.2 /km² |
| circuity | 1.023 | 1.018 | 1.019 | 1.032 | 1.007 | 1.004 |
| max edge betweenness | 0.1209 | 0.1183 | 0.1212 | 0.1067 | 0.1029 | 0.1129 |

Betweenness is a share of all shortest walks in the fetched network, so it
changes on the site whenever the network round it does.

Mean walk to the nearest destination, design site.

| | dwellings, baseline | dwellings, Scenario A | dwellings, Scenario B | site grid, baseline | site grid, Scenario A | site grid, Scenario B |
|---|---|---|---|---|---|---|
| shop | 234 m | 245 m | 230 m | 228 m | 217 m | 220 m |
| education | 269 m | 281 m | 255 m | 258 m | 259 m | 275 m |
| health care | 412 m | 434 m | 454 m | 411 m | 423 m | 420 m |
| rail stop | 637 m | 621 m | 602 m | 613 m | 593 m | 608 m |
| **mean of the four** | **387.9 m** | **395.3 m** | **385.2 m** | **377.4 m** | **372.9 m** | **380.6 m** |

**Scenario A's street grid makes everyday walks on the site slightly shorter.**
On the fixed grid the mean of the four falls from 377.4 m to 372.9 m, 4.5 m. The
new grid has more junctions (423 to 514 per km²) and straighter streets
(circuity 1.032 to 1.007). It gains on shops and rail stops and loses a little
on health care. Before the network was repaired (2026-10-23) this read as 10 m
longer; that was the broken junctions, not the design.

**Scenario B's makes them slightly longer.** The grid mean rises to 380.6 m,
3.2 m. B has far fewer streets on the site (3.68 km against 4.83 km today) and
fewer junctions (249 per km²), but they run straight (circuity 1.004), so it
loses on education and wins on rail stops.

**Residents' walks follow where they live as much as the network.** Site
dwellings go from 387.9 m to 395.3 m in Scenario A and 385.2 m in Scenario B.
A puts 1,920 estimated dwellings on the site and B 1,250, against 1,027 today.

**The neighbours do not notice.** Dwellings outside the site stay at 267.3 m
in every scenario.

**The 15-minute walk does not separate anything.** Every dwelling in the
study area reaches all four types within 15 min (1,200 m) in every scenario. The
5-minute share (400 m) is what varies. On the site no dwelling has a rail stop
within 5 min in either scenario, 2 % do today.

### Footpath links, Scenario A

25 candidates. J starts at 301.33 m, the ceiling is 300.50 m.

| # | length | J saved | J | site dwellings | site grid | of ceiling |
|---|---|---|---|---|---|---|
| 1 | 46 m | 0.60 m | 300.73 m | 393.0 m | 372.4 m | 72 % |
| 2 | 14 m | 0.18 m | 300.55 m | 392.3 m | 371.9 m | 94 % |
| 3 | 35 m | 0.02 m | 300.53 m | 392.3 m | 371.7 m | 97 % |
| 4 | 28 m | 0.02 m | 300.51 m | 392.2 m | 371.6 m | 99 % |
| 5 | 28 m | 0.01 m | 300.50 m | 392.2 m | 371.5 m | 100 % |

**Two links, 59 m of footpath, take 94 % of what all 25 candidates could
give.** Link 1 cuts diagonally across the south-west corner park to Strevelsweg.
Link 2 is a crossing of Strevelsweg in line with Jagerslaan: the road is a dual
carriageway and OSM has no crossing near there. After link 2 each link saves
under 0.03 m of J. The optimiser stops after five, when no candidate saves 1 mm.

### Footpath links, Scenario B

6 candidates. J starts at 289.80 m, the ceiling is 289.52 m.

| # | length | J saved | J | site dwellings | site grid | of ceiling |
|---|---|---|---|---|---|---|
| 1 | 71 m | 0.16 m | 289.64 m | 384.4 m | 379.2 m | 58 % |
| 2 | 48 m | 0.12 m | 289.52 m | 383.8 m | 378.2 m | 100 % |

**Two links reach the ceiling.** Link 1 is a park path from the central junction
across the green to the kept school block's path. Link 2 joins the end of a new
street to the north-east edge street.

J is over the whole study area, so its changes look small. The site columns
show where they land. Both layouts leave little for footpaths to add once their
streets are joined up properly: the ceilings are 0.83 m (A) and 0.28 m (B) below J.

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
