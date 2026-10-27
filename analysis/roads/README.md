# analysis/roads — Road network

Component 8 · owner: Atanas Malinkov (built 2026-10-21) · feeds `app/modules/roads.js`

The walking network per scenario, how far homes are from everyday destinations,
which new footpaths through the design site would shorten those walks most,
and where on the new blocks' ground floors shops and health practices shorten
them most (the kept school stays fixed; the second school is placed).

| script | does | writes |
|---|---|---|
| `road_network.py` | network metrics and walking distances per scenario | `data/processed/road_metrics.json`, `roads_<scenario>.geojson` |
| `optimise_links.py` | greedy choice of new footpaths on the site | `data/processed/road_links.json`, `road_links_<scenario>.geojson` |
| `place_amenities.py` | p-median placement of shops, health care and the second school on the new ground floors; the kept school stays fixed | `data/processed/amenity_placement.json`, `design_amenities.geojson`, `docs/fig_amenities.png` |

```bash
python analysis/roads/road_network.py      # first run fetches OSM into cache/roads/, about 3 min
python analysis/roads/optimise_links.py    # needs road_network.py's output, about 15 s
python analysis/roads/place_amenities.py   # about 10 s
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
nodes closer than 0.5 m are merged into one junction. Old streets under a
scenario's new blocks or its water are cut away first.

**Street links.** Where a Rhino street surface stops short of an edge street (a
free end, or two streets meeting in a sharp corner, within 35 m of it),
`import_rhino.py` adds a link surface as wide as the street, never through a
block, and the walk network walks its axis. That is 14 links in Scenario A and
10 in B; B's south corner stopped 14 m short of Strevelsweg and reached it only
by a 583 m detour before (2026-10-23). The free-end connectors stay, so a
street end gets both. In all, 43 connector pieces, 148 m, in Scenario A after
splitting and 16, 71 m, in B.

**Hand-drawn paths.** Scenario A has one path the Rhino model does not: 125 m
along the north edge of the green round the kept school, from the main street to
Dubbelstraat (`paths_rd` in `analysis/scenarios/import_rhino.py`, team decision
2026-10-23). The green's only path, the old diagonal, lies under the pond and a
block corner. The path is walked here and drawn in the app; it is not a street
canyon, so `height_width.py` leaves it out.
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
| nodes | 343 | 389 | 338 | 72 | 124 | 67 |
| edges | 537 | 627 | 535 | 90 | 191 | 92 |
| network length | 25.85 km | 27.09 km | 24.69 km | 4.83 km | 6.02 km | 3.65 km |
| avg edge length | 48.1 m | 43.2 m | 46.2 m | 53.7 m | 31.5 m | 39.7 m |
| intersection density | 402.1 /km² | 424.9 /km² | 380.5 /km² | 422.9 /km² | 589.1 /km² | 287.0 /km² |
| circuity | 1.023 | 1.018 | 1.019 | 1.032 | 1.007 | 1.004 |
| max edge betweenness | 0.1209 | 0.1173 | 0.1208 | 0.1067 | 0.1020 | 0.1116 |

Betweenness is a share of all shortest walks in the fetched network, so it
changes on the site whenever the network round it does.

Mean walk to the nearest destination, design site.

| | dwellings, baseline | dwellings, Scenario A | dwellings, Scenario B | site grid, baseline | site grid, Scenario A | site grid, Scenario B |
|---|---|---|---|---|---|---|
| shop | 234 m | 246 m | 236 m | 228 m | 216 m | 218 m |
| education | 269 m | 278 m | 310 m | 258 m | 254 m | 280 m |
| health care | 412 m | 434 m | 414 m | 411 m | 421 m | 416 m |
| rail stop | 637 m | 621 m | 601 m | 613 m | 593 m | 598 m |
| **mean of the four** | **387.9 m** | **394.8 m** | **390.6 m** | **377.4 m** | **371.2 m** | **378.0 m** |

**Scenario A's street grid makes everyday walks on the site slightly shorter.**
On the fixed grid the mean of the four falls from 377.4 m to 371.2 m, 6.2 m. The
new grid has more junctions (423 to 589 per km²) and straighter streets
(circuity 1.032 to 1.007), and gains on shops, education and rail stops. That
needs the hand-drawn path through the green round the kept school: without it
that green has no path at all (the old diagonal lies under the pond and a block
corner), 75 grid points there walk 180 to 200 m further to a school, and the
mean is 377.8 m, level with today. Before the network was repaired
(2026-10-23) A read as 10 m longer; that was broken junctions, not the design.

**Scenario B's leaves them about where they are.** The grid mean is 378.0 m,
0.6 m above today. B has fewer streets on the site (3.65 km against 4.83 km
today) and fewer junctions (287 per km²), but they run straight (circuity 1.004),
so it loses on education and wins on shops and rail stops. Its long walks to
school are in its large greens, which have no paths.

**Residents' walks follow where they live as much as the network.** Site
dwellings go from 387.9 m to 394.8 m in Scenario A and 390.6 m in Scenario B.
A puts 1,920 estimated dwellings on the site and B 1,250, against 1,027 today.

**The neighbours do not notice.** Dwellings outside the site stay at 267.3 m
in every scenario.

**The 15-minute walk does not separate anything.** Every dwelling in the
study area reaches all four types within 15 min (1,200 m) in every scenario. The
5-minute share (400 m) is what varies. On the site no dwelling has a rail stop
within 5 min in either scenario, 2 % do today.

### Footpath links, Scenario A

23 candidates. J starts at 301.45 m, the ceiling is 300.64 m.

| # | length | J saved | J | site dwellings | site grid | of ceiling |
|---|---|---|---|---|---|---|
| 1 | 46 m | 0.60 m | 300.86 m | 392.5 m | 370.7 m | 74 % |
| 2 | 14 m | 0.18 m | 300.67 m | 391.9 m | 370.2 m | 96 % |
| 3 | 35 m | 0.02 m | 300.65 m | 391.8 m | 370.0 m | 99 % |
| 4 | 28 m | 0.01 m | 300.64 m | 391.7 m | 370.0 m | 100 % |

**Two links, 59 m of footpath, take 96 % of what all 23 candidates could
give.** Link 1 cuts diagonally across the south-west corner park to Strevelsweg.
Link 2 is a crossing of Strevelsweg in line with Jagerslaan: the road is a dual
carriageway and OSM has no crossing near there. After link 2 each link saves
under 0.03 m of J. The optimiser stops after four, when no candidate saves 1 mm.

### Footpath links, Scenario B

10 candidates. J starts at 290.82 m, the ceiling is 290.07 m.

| # | length | J saved | J | site dwellings | site grid | of ceiling |
|---|---|---|---|---|---|---|
| 1 | 48 m | 0.53 m | 290.29 m | 387.9 m | 376.9 m | 71 % |
| 2 | 71 m | 0.16 m | 290.13 m | 387.0 m | 375.7 m | 93 % |
| 3 | 17 m | 0.06 m | 290.07 m | 386.7 m | 375.0 m | 100 % |

**Three links reach the ceiling.** Link 1 joins the end of a new street to the
north-east edge street. Link 2 is a park path from the central junction across
the green towards the kept school block. Link 3 crosses Strevelsweg from the
south corner, now that it is joined to it, to Jagerslaan.

J is over the whole study area, so its changes look small. The site columns
show where they land. Both layouts leave little for footpaths to add once their
streets are joined up properly: the ceilings are 0.81 m (A) and 0.75 m (B) below J.
The optimiser could not have found the path through the school green in A: a
candidate must join two street junctions, and that green had none.

## Amenities on the new ground floors

The Rhino model gives the new blocks no use, and the importer assumes housing.
The ground the options clear holds 20 shops, 7 health practices and 1 school
today (BAG), and none come back.

**The kept school stays fixed.** The kept block in the east of the site is the
community centre with its school (1,791 m²) and halls. It stays exactly where
it is, untouched, in every scenario: no model moves it and nothing is placed
inside the kept block. Today the site has two schools. The second, 2,183 m² on
Strevelsweg, 212 m west of the kept one, is demolished and gets one placed
school in its stead, like the shops and health practices. Four community and
assembly halls on the cleared ground go too and are not a destination type
here, so the kept block is the site's only community centre in both options.

`place_amenities.py` puts the shops and health practices back where they
shorten walks most. Per type it solves a p-median problem (Hakimi 1964):
choose p sites to minimise the dwelling-weighted mean walk from every dwelling
in the buurt to the nearest destination of that type, existing or new.
Candidates are points every 15 m along the new blocks' outlines with a street or
path within 40 m, outside the kept block, snapped to the walk network like the
homes (379 in A, 149 in B; B's blocks stand 11–36 m back in green, so a tighter
limit shut most of them out). p is like-for-like: 20 shops, 7 health practices,
1 school. Greedy picks, then vertex substitution (Teitz and Bart 1968). The
school is placed first, then health, then shops, from the spots still free. The distances were checked
against a fresh multi-source route to the existing plus the placed amenities:
identical to 0.1 m for every type in both options.

Mean walk from every dwelling in the buurt to the nearest of each type.

| | p | before | optimised | random placement, mean of 200 | site grid before → after |
|---|---|---|---|---|---|
| A, shop | 20 | 150.2 m | 101.5 m | 114.0 m | 216 → 89 m |
| A, health care | 7 | 346.9 m | 233.7 m | 258.8 m | 421 → 124 m |
| A, education | 1 | 247.6 m | 224.4 m | 235.0 m | 254 → 201 m |
| B, shop | 20 | 138.5 m | 113.7 m | 120.0 m | 218 → 107 m |
| B, health care | 7 | 334.3 m | 252.6 m | 275.2 m | 416 → 136 m |
| B, education | 1 | 249.5 m | 223.4 m | 241.2 m | 280 → 204 m |

**Today against the options.** `docs/fig_amenities.png` maps today's
amenities on the site (BAG: 20 shops, 7 health practices, 2 schools, 7
community halls; the ones the options demolish hollow) next to each option's
placed and kept ones (20 shops, 7 health, 2 schools, 3 halls). Today's shops line
Strevelsweg, the site's shopping street. The placement spreads them through the
blocks, because walking distance rewards spreading and footfall is not in it.

**Placed where it counts, the amenities beat random placement on every type**,
by 6 to 25 m across the whole buurt. The curves in `docs/fig_amenities.png`
show the diminishing returns: in B, shops after the 10th gain under 0.5 m
between them, because B's blocks offer few well-placed spots.

**On the site, walks become shorter than today.** Today, with its own shops and
services, a site resident walks 316.9 m to the nearest of the four types (site
grid 314.3 m). Housing only, that is 394.8 m in A and 390.6 m in B.
With the placed shops and health practices and the kept school it is 253.5 m in A and 263.2 m in B.

The ground floors this takes are worth about 52 dwellings of floor area per
option (today's median unit: shop 69 m², health 33 m², school 2,183 m²), not
subtracted from the dwelling estimates.

What this cannot tell you: whether a shop survives at a spot (footfall, rent,
clustering, which the objective punishes rather than rewards), or whether a
block's ground floor can hold a school.
It places points by walking distance.

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
