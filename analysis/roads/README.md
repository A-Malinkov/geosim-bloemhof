# analysis/roads - Road network

Component 8 · owner: Atanas Malinkov (built 2026-10-21) · feeds `app/modules/roads.js`

The walking network per scenario, how far homes are from everyday destinations,
and where on the new blocks' ground floors shops and health practices shorten
them most (the kept school stays fixed; the second school is placed).

| script | does | writes |
|---|---|---|
| `road_network.py` | network metrics and walking distances per scenario | `data/processed/road_metrics.json`, `roads_<scenario>.geojson` |
| `place_amenities.py` | p-median placement of shops, health care and the second school on the new ground floors; the kept school stays fixed | `data/processed/amenity_placement.json`, `design_amenities.geojson`, `docs/fig_amenities.png` |
| `edge_access.py` | walk and drive distance from each site address to Lange Hilleweg and Strevelsweg | `data/processed/edge_access.json`, `edge_access_<scenario>.geojson` |

```bash
python analysis/roads/road_network.py      # first run fetches OSM into cache/roads/, about 3 min
python analysis/roads/place_amenities.py   # about 10 s
python analysis/roads/edge_access.py       # every case; first run fetches the OSM drive network, about 1 min
python analysis/roads/edge_access.py --scenario scenario_a --check   # a design option, verified against networkx
```

`road_network.py` has one case dict per scenario in `CASES`: baseline,
scenario_a, scenario_b and final.

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
street end gets both. In all, 43 connector pieces, 166 m, in Scenario A after
splitting and 16, 82 m, in B.

**No street or path ends in nothing.** Two rules close the dead ends a check of
every scenario found on the site (2026-10-28). Six OSM footways round the site
(along Strevelsweg, Weimanspad, at Lange Hilleweg) stop at the kerb, 6 to 7 m
short of the road's centreline, as OSM maps pavements: in every scenario, today
included, a footway end like that within 8 m of a street is joined to it
(`join_kerb_gaps`). And where a design's pond or blocks cut an old street
(Dubbelstraat, Oudelandstraat and Heer Daniëlstraat round the kept block), the
cut end is joined to the nearest street within 35 m by a straight line clear of
blocks and water, or the piece is dropped if there is none (`close_cut_ends`).
After both, no scenario has a dead end on the site; today keeps five service
driveways and three footways through its own yards, which the designs
demolish.

**Hand-drawn paths.** Scenario A has one path the Rhino model does not: 125 m
along the north edge of the green round the kept school, from the main street to
Dubbelstraat (`paths_rd` in `analysis/scenarios/import_rhino.py`, team decision
2026-10-23). The green's only path, the old diagonal, lies under the pond and a
block corner. The path is walked here and drawn in the app; it is not a street
canyon, so `height_width.py` leaves it out.
Before 2026-10-23 the graph made no junction at those crossings and split two
ends 0.1 m apart into two nodes, so Scenario A's main street was cut in two and
its new streets did not meet Lange Hilleweg, Strevelsweg or Dubbelstraat. The edge streets themselves (Lange Hilleweg,
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

**As lived.** Each scenario also gets a `with_amenities` block in
`road_metrics.json`: the same walks with today's own shops, health practices
and schools on the site (baseline), or with the ones `place_amenities.py` puts
on the option's ground floors. Those are the numbers to quote for residents; the
per-type tables below leave the site's amenities out everywhere and show the
network alone.

**Distance.** Each home and destination is snapped to the nearest point on the
nearest edge. Walking distance is the access leg plus the network distance, by
one Dijkstra per destination type from all its destinations at once (scipy).
Checked against an independent networkx implementation on 60 homes per scenario
and two destination types, max difference 0.000000 m.

**Two sets of origins on the site.** *Dwellings* move with who lives there, so
they mix the network effect with the new housing. The *site grid* is the same
332 points every 20 m in every scenario, so it moves with the network alone.

## Results

Network over each area. An edge counts in an area if its midpoint lies in it.

| | study area, baseline | study area, Scenario A | study area, Scenario B | design site, baseline | design site, Scenario A | design site, Scenario B |
|---|---|---|---|---|---|---|
| nodes | 343 | 381 | 336 | 75 | 119 | 68 |
| edges | 537 | 617 | 533 | 103 | 190 | 99 |
| network length | 25.84 km | 26.90 km | 24.65 km | 4.88 km | 5.89 km | 3.66 km |
| avg edge length | 48.1 m | 43.6 m | 46.3 m | 47.4 m | 31.0 m | 37.0 m |
| intersection density | 402.1 /km² | 419.8 /km² | 380.5 /km² | 445.6 /km² | 581.5 /km² | 309.6 /km² |
| circuity | 1.023 | 1.019 | 1.019 | 1.031 | 1.007 | 1.004 |
| max edge betweenness | 0.1212 | 0.1182 | 0.1211 | 0.1024 | 0.0958 | 0.1047 |

Betweenness is a share of all shortest walks in the fetched network, so it
changes on the site whenever the network round it does.

Mean walk to the nearest destination, design site.

| | dwellings, baseline | dwellings, Scenario A | dwellings, Scenario B | site grid, baseline | site grid, Scenario A | site grid, Scenario B |
|---|---|---|---|---|---|---|
| shop | 233 m | 245 m | 236 m | 226 m | 215 m | 216 m |
| education | 269 m | 278 m | 310 m | 257 m | 255 m | 280 m |
| health care | 412 m | 434 m | 414 m | 410 m | 420 m | 414 m |
| rail stop | 637 m | 621 m | 601 m | 612 m | 593 m | 596 m |
| **mean of the four** | **387.8 m** | **394.5 m** | **390.6 m** | **376.2 m** | **370.7 m** | **376.7 m** |

**Scenario A's street grid makes everyday walks on the site slightly shorter.**
On the fixed grid the mean of the four falls from 376.2 m to 370.7 m, 5.5 m. The
new grid has more junctions (446 to 582 per km²) and straighter streets
(circuity 1.031 to 1.007), and gains on shops, education and rail stops. That
needs the hand-drawn path through the green round the kept school: without it
that green has no path at all (the old diagonal lies under the pond and a block
corner), 75 grid points there walk 180 to 200 m further to a school, and the
mean is 377.8 m, level with today. Before the network was repaired
(2026-10-23) A read as 10 m longer; that was broken junctions, not the design.

**Scenario B's leaves them about where they are.** The grid mean is 376.7 m,
0.5 m above today. B has fewer streets on the site (3.66 km against 4.88 km
today) and fewer junctions (310 per km²), but they run straight (circuity 1.004),
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

### Final design

Run 2026-10-30 with `road_network.py --scenario final`, on the 30.10 model. A and B are on 27.10, which 30.10 leaves unchanged.

Its destinations are its own 50 shop units from the Rhino block names (31
podiums, 18 terraced houses split into a shop with flats on it, the shopping
centre: two joined
buildings, one marker) and the kept school. The model names no health practice,
so `place_amenities.py` turns 7 of the 49 shop units (the shopping centre stays
a shop) into health practices, picked by the same p-median as A and B use,
among those units only (`CONVERT`). That leaves 43 shops. The 20 terraced houses
the model names "WITH SHOPS" are homes on every floor (Atanas, 2026-10-30). Shop
floor holds no dwellings in the estimate: 777 dwellings on the site.

Site residents walk 355 m on the mean of the four types on the network alone,
269 m with its shops and health practices, against 317 m today with today's own
amenities. Shops are 117 m away, health care 126 m (365 m before the 7
practices). The 7 picked units bring the buurt-wide walk to health care from
321.7 to 271.5 m; 7 units picked at random do 283.3 m on average.
The curvy walkway the model draws on its vegetation layer is walked along its
centreline (670 m). The other pedestrian and bike surfaces are not walked separately:
all of them run within 5 m of a street.

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
| A, shop | 20 | 150.0 m | 102.1 m | 114.3 m | 215 → 86 m |
| A, health care | 7 | 347.0 m | 233.5 m | 259.0 m | 420 → 123 m |
| A, education | 1 | 247.7 m | 224.5 m | 235.2 m | 255 → 202 m |
| B, shop | 20 | 138.5 m | 113.7 m | 120.0 m | 216 → 108 m |
| B, health care | 7 | 334.3 m | 252.6 m | 274.9 m | 414 → 134 m |
| B, education | 1 | 249.5 m | 223.4 m | 241.0 m | 280 → 203 m |

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
With the placed shops and health practices and the kept school it is 253.7 m in A and 263.2 m in B.

The ground floors this takes are worth about 52 dwellings of floor area per
option (today's median unit: shop 69 m², health 33 m², school 2,183 m²), not
subtracted from the dwelling estimates.

What this cannot tell you: whether a shop survives at a spot (footfall, rent,
clustering, which the objective punishes rather than rewards), or whether a
block's ground floor can hold a school.
It places points by walking distance.

## Distance to the edge streets

`edge_access.py` (2026-10-27). How far every address on the design site is from
the site's two main edge streets, Lange Hilleweg (north-west) and Strevelsweg
(south), on foot and by car.

**Targets.** The stretch of each street along the site: its network nodes within
15 m of the site outline. Reaching any of them is arriving. An address on the
street itself is 0 m away by network.

**Walk.** The walk network above, clipped to the site + 15 m, so a walk cannot
leave the site and come back round the outside. The access leg from the BAG
point to the street counts.

**Drive.** OSM drive network (`network_type="drive"`: no footways, alleys or
service roads) with its one-way streets, over Bloemhof + 500 m and not clipped:
a one-way street can force a car out and back. The car starts on the street at
the address, so there is no access leg, and on a one-way street it leaves by the
end the traffic runs to. A one-way piece that leads into a dead end with no way
out is made two-way, because a car turns round there. In the baseline that only
happens at the edge of the fetched area (22 pieces, none within 50 m of the
site). A scenario adds the one-way stubs its design cuts short (Oudelandstraat,
Dubbelstraat).

**Origins.** The 1,027 BAG dwellings on the site, at 687 distinct points. Each
snaps to the nearest piece of the street in its own address, not just the
nearest street: the BAG point lies inside the building, and its nearest street
is often a back alley or a side street. Every baseline address found its own
street.

**Distance.** One Dijkstra run per street and mode, from a super-source joined
to the target nodes, on the reversed graph, so the distance runs from the
address to the street. With `--check` a sample of 60 addresses per mode and
street is recomputed with networkx: max difference 0.0 m in every case.

### Results, baseline

Dwelling-weighted, design site.

| | median | p90 | max | ≤ 100 m | ≤ 200 m | straight line, median |
|---|---|---|---|---|---|---|
| walk to Lange Hilleweg | 141.6 m | 320.1 m | 479.3 m | 35 % | 66 % | 93.5 m |
| walk to Strevelsweg | 264.1 m | 377.8 m | 525.2 m | 25 % | 32 % | 116.7 m |
| drive to Lange Hilleweg | 205.1 m | 555.0 m | 686.4 m | 30 % | 48 % | 93.5 m |
| drive to Strevelsweg | 660.4 m | 856.7 m | 953.6 m | 17 % | 17 % | 116.7 m |

**By car, Strevelsweg is a long way from almost the whole site.** The 17 % of
dwellings on Strevelsweg itself are on it already. The others cannot drive onto
it from inside the site. Oudelandstraat, at the east end, is one-way away from
Strevelsweg. The site's own carriageway of Lange Hilleweg is one-way north-east.
The strip of terraced rows along Strevelsweg has no street through it. The only
way onto Strevelsweg is the outer carriageway of Lange Hilleweg, beyond the
green strip, which runs south-west. A car gets there by driving north-east to the
crossing at Resedastraat and coming back. The median dwelling, on Koolzaadstraat,
drives 660 m to a street 117 m away in a straight line.

**On foot it is a detour too.** Walking to Strevelsweg is 2.3 times the straight
line at the median (264.1 m against 116.7 m): OSM has no path through the
terraced strip either, only round its two ends. Real gaps between the houses
would shorten this; OSM does not map them.

**Lange Hilleweg is the nearer edge street for most of the site:** 71 % of
dwellings on foot and 83 % by car.

### Scenarios: what the team still has to draw

Both scenarios run (`--scenario scenario_a`), but are not published yet,
because two inputs are design decisions:

- **Entrances of the new blocks.** Points in
  `data/processed/design_entrances.geojson` (WGS84, property `scenario`,
  optional `dwellings`), within 5 m of a block's wall. A block's estimated
  dwellings (the formula above) are shared over its entrances; a `dwellings`
  value on a point overrides its share. A block with no drawn entrance gets one
  every 15 m along its walls within 20 m of a street.
- **Car access of the new streets.** `CASES` in `edge_access.py`:
  `car_free_rd`, RD polygons over new streets cars may not use, and
  `oneway_rd`, RD lines drawn in the direction of travel. Hand-drawn footpaths
  are never driven. Left empty, every new street, link and connector is a
  two-way car street.

Until both are drawn, the output lists what it assumed under `assumptions`, and
the app shows it under the table.

### What it cannot tell you

- No turn restrictions, traffic or parking: a car starts on the street in front
  of the address, and the distance is metres, not minutes.
- No separate pavements in OSM here, so a walk crosses Strevelsweg anywhere for
  free. Strevelsweg and Lange Hilleweg are each two one-way carriageways in the
  drive network; reaching either side counts.
- The stretch "along the site" is the outline + 15 m. A junction just beyond a
  corner of the site does not count.

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
  a traffic forecast. Betweenness and the destination walks use the walk
  network only (the drive network is `edge_access.py`'s alone), and noise
  traffic still runs on the OSM roads (see `analysis/wind_noise/`).
- Distance only. Lighting, overlooking, steps and gradient are not modelled.
