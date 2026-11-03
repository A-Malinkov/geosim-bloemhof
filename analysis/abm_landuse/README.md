# analysis/abm_landuse - agent-based land-use modelling

Component 4.7 · Owner: **Atanas Malinkov** · study area: Bloemhof · feeds `app/modules/landuse.js`

> Numbers here are generated from `data/processed/landuse_abm.json` and
> `landuse_rl.json`. If you re-run the models, re-check this file.

## Scripts

| Script | What it does | Writes |
|---|---|---|
| `fetch_landcover.py` | OSM green, water and roads: the surface BAG cannot see | `data/raw/osm_landcover.geojson`, `osm_roads.geojson` |
| `ca_landuse.py` | neighbour-rule cellular automaton, land-use programmes | `data/processed/landuse_abm.json` + frame PNGs |
| `rl_landuse.py` | linear Q-learning agent that re-plans the design site, scored on the same formula, with random-policy and hill-climbing baselines | `data/processed/landuse_rl.json` |
| `weight_sensitivity.py` | re-scores the stored replicates across the weight simplex | `data/processed/landuse_weight_sensitivity.json` |
| `score_scenarios.py` | scores the Rhino design options on the same objective | `data/processed/landuse_scenarios.json` |

```bash
python analysis/morphology/fetch_landuse.py      # BAG units: needed first
python analysis/abm_landuse/fetch_landcover.py   # ~30 s
python analysis/abm_landuse/ca_landuse.py        # ~2 s
python analysis/abm_landuse/rl_landuse.py   # 400 episodes, the default
python analysis/abm_landuse/weight_sensitivity.py  # ~2 s, no model re-run; step 0.01, the published lattice
python analysis/abm_landuse/score_scenarios.py   # ~5 s, after analysis/scenarios/import_rhino.py
```

## Why two models

| | rules | what it tells you |
|---|---|---|
| **Cellular automaton** | **assumed**: four neighbour rules we wrote | what follows *from those assumptions* |
| **RL agent** | **learned**: given only the objective | what the objective *actually implies* |

Where they agree, the assumption is supported. Where they disagree, one of them
is worth arguing about, and they do disagree (below).

## The cellular automaton

A neighbour-rule CA, constrained by demand.

Grid: 42 × 39 cells of 25 m over Bloemhof's bounding box. States: water, road, green, residential, retail, amenity, industry, vacant.
For each programme the CA **clears the design site** (its 188 buildable cells
become vacant; roads and water stay) and **rebuilds all of it**. The rest of
Bloemhof stays as it is and is the context the site grows from. Inside the site
only vacant cells change, so it grows inwards from its edges.

Each step a vacant cell can take a use that one of its **8 neighbours** supports:

| use | grows next to | also needs |
|---|---|---|
| green | green | |
| residential | residential | |
| retail | residential | a street: at least 20 % of the cell is carriageway |
| amenity | residential | |
| industry | does not grow | |

A cell's score for a use is how many of its 8 neighbours support it. The uses
the programme asks for take the highest-scoring vacant cells first, each at most
its growth spread evenly over the 20 steps, so the site fills from its edges
inwards. A random tie-break orders cells with the same score, so the 12 replicates
differ. A run continues past the 20 steps while the programme is not met and
something can still grow (at most 20 more); cells no rule can reach then take
what the programme still lacks, so the whole site is built. In the green
programme that last rule places 0 to 10 cells per run (3 in its best run),
because the park closes off pockets that housing cannot reach; compact needs it
in no run.

Until 2026-10-30 this was a constrained CA after White, Engelen & Uljee (1997):
a 64-weight influence matrix over a radius of 4 cells, multiplied by
suitability, road access, a stochastic term and inertia. It ranked the
programmes the same way (green 1.374, compact 1.355) but every weight was an
assumption to defend, so it was replaced by the rules above. Until the same day
both CAs only added a programme of 98 cells to the buurt's vacant land and left
everything standing; now the CA rebuilds the cleared site, like the RL agents.

### Building the initial raster: a trap worth knowing

The first version buffered every OSM centreline by half a cell and burned it as
road. That put **41 % of the study area under tarmac**: 44 km of road at 22.5 m
width is 99 ha, more than the square itself, and BAG buildings then overwrote
**67 %** of it. Two errors partially cancelling, which happened to look
plausible and was indefensible.

Now: carriageway width per OSM class (primary 14 m … service 5 m), measured as
an **area fraction** on a 5 m sub-grid, giving **23 % carriageway** across the
study area. Priority is explicit: water, then building, then road, then land
cover.

And "on a street" is read from that continuous road **surface**, not from
cells whose final state is ROAD. At 25 m most street cells also contain a
building and are labelled residential, so the discrete state would leave most
streets out.

## Programme results

The CA rebuilds the cleared design site for two land-use **programmes**,
`compact` and `green`, against `baseline`, the site today. They are not the Rhino design options.
Until 2026-10-27 they were keyed `scenario_a` and `scenario_b`, which made the
app show them under the same names as the Rhino options. The Rhino options are
scored on the same objective further down.

Programmes for the 188 cleared cells (Atanas, 2026-10-30), 12 stochastic replicates each:

| programme | housing | shops | amenity | green |
|---|---|---|---|---|
| compact | 160 (today's) | 14 | 7 | 7 |
| green | 120 | 10 | 8 | 50 |

Scored over the design site, 189 cells, like the RL agents and the Rhino designs:

| programme | objective | land-use mix | green | housing cells | home → amenity |
|---|---|---|---|---|---|
| baseline | 2.100 | 0.229 | 3.2 % | 160 | 99 m |
| compact | 2.421 | 0.358 | 3.7 % | 160 | 44 m |
| green **★** | 2.710 | 0.577 | 26.5 % | 120 | 52 m |

```
objective = 1.6 · land-use mix + 1.0 · green share
          + 0.8 · max(0, 1 − mean home-to-amenity distance / 400 m)
          + 1.1 · min(1, homes / homes today)
```

The housing term went in on 2026-10-30. It scores homes against today, capped
at 1: keeping today's homes scores the full 1.1, more homes earn nothing extra,
and every home lost costs its share. A grid model only knows land, so the CA and
the RL agents count **housing cells**; the Rhino designs count **dwellings**,
so their storeys count (below). The two families are never compared.

**The green programme wins.** Its 40 fewer housing cells cost it 1.1 × 40 / 160 =
0.275 on the housing term, but its park and the wider mix gain more. Its homes
are a little further from a shop (52 m against 44 m), because the park takes
ground the shops could have lined.

### How much of that is the weights?

Those weights are ours, and the gap between the top two programmes is
0.0658 on a normalised scale, against a replicate spread of
σ 0.0123 and 0.0128. So the ranking deserves a
sensitivity check rather than a full stop.

`weight_sensitivity.py` re-scores every stored replicate across
156,849 weight vectors on the normalised simplex
w_mix + w_green + w_prox + w_housing = 1, re-picking the best replicate at each point exactly
as `ca_landuse.py` does. The CA is not re-run: each replicate already stores its
raw components, so the sweep is exact and takes seconds. All four weights are
swept, because the green programme's housing term (0.75) differs from compact's (1.0).

| programme | share of the weight space it wins |
|---|---|
| green **★** | 70 % |
| compact | 30 % |
| baseline | 0 % |

**green's win holds at the default and across 70 % of the weight
space.** Compact takes the other 30 %, and
baseline never wins under any positive weighting: that last part is
the firm result. The nearest weights that flip the answer are
0.28 · 0.15 · 0.20 · 0.37 (favouring compact),
0.16 away on the simplex. The default is not on a knife edge. Compact wins when
housing and walkability are weighted heavily against mix and green space, which
is exactly the trade it makes.

Two lattices agree on the shares: 0.02 (71 / 29) and 0.01 (70 / 30). (Over
both buurten 200,000 uniform Dirichlet draws also agreed with the lattices;
that check was not repeated for Bloemhof.)

The script reproduces the published objectives from the stored replicates before
it sweeps, and exits 1 if it cannot. Injecting a wrong weight or a wrong distance
normaliser was checked to make it fail.

**What the sweep cannot do.** It sweeps the *scoring* of the CA. The RL agent
optimises the objective directly, so re-scoring its result under other weights is
not the same experiment as retraining under them, and it is excluded. It also
explores the four terms we chose without asking whether they are the right four.

## The RL agent

Q-learning, TD(0), **linear** function approximation, ε-greedy, 400 episodes.

**It works on the design site only**, not the whole study area. Every cell of the
site that is not road or water (188 of 189) is cleared, and each episode the
agent re-plans all of them one cell at a time; reward is the change in the
objective. The rest of Bloemhof is fixed context: it feeds the
agent's neighbourhood features, and a shop just outside the site still counts
for walkability, but the agent cannot change it and is not scored on it.

The objective is the CA's formula, **computed over the site's cells**: mix and
green share of the site, and the mean distance from homes in the site to the
nearest shop or amenity anywhere. Since 2026-10-30 the CA rebuilds and scores the
same site, so **the CA's programmes and the agent's plans are on one scale**. They
still answer different questions: the CA lays out a programme we set, the agent
chooses the programme itself.

**What the agent sees.** For each candidate cell, 13 numbers: how many
neighbours of each of the 8 land-use classes it has within 4 cells
(distance-weighted), its road accessibility, whether it is vacant, whether it is
green, its distance to water, and a constant. Q for each of the 4 uses it may
place (residential, retail, amenity, green) is a weighted sum of those 13, so
the agent learns 4 × 13 weights. Because the agent only ever considers empty
site cells, "vacant" is always 1 and "green" always 0 for a candidate. Those two
add nothing beyond the constant.

**How it learns.** Each step it samples 40 empty cells and either picks the
best (cell, use) pair by Q or, with probability ε, a random one. ε falls from
0.9 towards 0.05. The reward is the change in the objective caused by that
placement, times 100. The weights follow the TD(0) update with learning rate
0.02 and discount 0.95, clipped to ±50.

Linear rather than deep **on purpose**: the value here is that the weights can
be read and argued with.

Its housing term counts the site's housing cells against today's 160.

Learns: 2.717 over the first 10 % of episodes → 2.814 over the last 10 %. Its
learned policy, one run with no exploration, scores 2.814.
Best 2.848 against 2.100 for the site today; its plan reaches mix 0.804,
30 % green and 28 m to the nearest amenity (today 0.229, 3 % and 99 m).

**400 episodes, not 120.** At 120 episodes the curve looked flat at about 2.78,
but trained longer it keeps rising until about episode 250 and levels off at
2.81 (`fig_landuse_rl_training.png`). Its learned policy goes from 2.774 at 120
episodes to 2.814 at 400, and keeps 108 housing cells instead of 50.

The site's cells depend on the grid, and the grid is anchored on the study-area
box's top edge. Narrowing the study area to Bloemhof on 2026-10-22 moved that
edge, so the site now covers 189 cells instead of 195. Same site, different
25 m cells.

**It still gives up housing: 160 housing cells become 76 in its best plan**, 108 in its learned policy. Before
the housing term nothing in the objective valued homes, and the agent kept 30.
With the term each lost housing cell costs 1.1 / 160 = 0.007, but turning the
first cells into shops, amenities and park still gains more on mix and green
than that. Hill climbing keeps 82, about half. A
higher housing weight would keep more. At
1.1 this is the trade the objective asks for.

### The interesting disagreement

The agent learned that **retail should avoid other retail**: −44.8, its
strongest aversion. Our CA has no such rule: it puts shops on streets next to
homes and lets them sit side by side wherever housing is densest. (The
influence-matrix CA it replaced went further and gave retail→retail **+0.8**,
so shops clustered.)

Read the weights within a row, not on their own. Every class carries about +37
to +38 on *vacant* neighbours and a negative weight on everything else, because
on a cleared site the vacant count mainly tells the agent how early in the
episode it is. What separates the classes is which neighbour each avoids most:
retail→retail −44.8, amenity→amenity −45.4. That is the mix term asking for uses
to be spread out.

Both are defensible and the disagreement is informative. The objective rewards
*walkability*, mean distance from homes to the nearest shop, which is minimised
by spreading shops out. Real retail clusters for agglomeration economies, which
this objective does not represent at all. **The model is right about the
objective, and the objective is incomplete.**

### Against two baselines

`rl_landuse.py` also runs two baselines on the same problem. A **random policy**
(30 episodes) is the baseline any agent has to beat. **Hill climbing** on the
objective itself (change one cell's use, keep the change if the objective does
not fall) is the direct optimiser any learner should beat.

| site re-plan | objective | housing cells |
|---|---|---|
| today | 2.100 | 160 |
| random policy, mean | 2.684 | |
| linear agent, best episode | 2.848 | 76 |
| linear agent, learned policy | 2.814 | 108 |
| hill climbing, 56,400 evaluations, about 8 s | **2.865** | 82 |

The random baseline puts the agent in proportion: on a cleared site a random mix
of four uses already scores 2.68, so the agent's learned policy gains 0.13 over
it (`fig_landuse_rl_training.png`).

A convolutional deep Q-network was tried on the same problem until 2026-11-03.
Its learned policy scored below the random policy, and it was dropped.

**Hill climbing beats the agent in about 8 seconds.** It reaches 2.865 and keeps
2,445 of its 56,400 moves. One evaluation of the objective takes about 0.15 ms,
so optimising it directly is the right tool here; reinforcement learning would
only earn its place by learning something that carries over, a policy for
another site, which none of these runs tests.

## Honest limitations

- **Demand is set by us**, not derived from a regional model. This explores the
  consequences of a development programme; it does not forecast one.
- The RL agent optimises the objective **directly**, while the CA follows fixed
  rules and is merely *scored* on it. RL scoring higher is expected by
  construction and is **not** evidence that RL models cities better.
- The objective is a weighted sum of four terms we chose. The sweep above
  shows the winner is weight-dependent: green takes 66 % of the weight
  space and compact the rest. Only "baseline never wins" holds regardless.
  Whether those four terms are the right four is still untested.
- The housing term values homes, but at weight 1.1 every optimiser still gives
  up about half of the site's housing cells for mix and green (above).
- The housing term counts housing cells in the grid models and dwellings for the
  Rhino designs. Within each family it is consistent; across them it is not, and
  nothing compares across them.
- The land-use grid ends at the buurt bounding box, which cuts off the site's
  strip south of Strevelsweg: 12.20 of its 13.24 ha are modelled.
- The RL run is one seed. The CA's programmes are spread over replicates; the
  agent's best plan is not.
- 25 m cells cannot represent a building. This allocates land use; turning that
  into massing is `analysis/scenarios/`.
- OSM land cover is not authoritative the way BAG is, though for "is this a
  park, a canal or a street" it is current and complete enough here.

## For component 4.9

The preferred programme (green) is a land-use allocation, not a building
design. The team's design is the two Rhino options, and those are what 4.9
compares. `score_scenarios.py` puts them on the land-use objective.

**The name clash is resolved (2026-10-27).** The CA's programmes used to be keyed
`scenario_a` and `scenario_b`, the same keys as the Rhino options, and one
scenario switch in the app drove both. They are now `compact` and `green`. The
land-use card has its own programme selector and no longer follows the
scenario switch. Only the Rhino-option table at its top does.

### The Rhino options on the same objective

`score_scenarios.py` burns each Rhino option into today's 25 m grid, inside the
part of the site the option clears (`cleared_area()`), and scores it with the
same objective. Pond is water, a new block on at least a quarter of a cell is
residential, street surface on half a cell is road, proposed green on half a
cell is green. Open ground the model leaves unprogrammed (courtyards, pavements,
gardens) is labelled vacant, the rule `rasterise()` applies to today's grid, so
the two are compared like with like. The housing term counts dwellings: BAG
today, `road_network.py`'s estimate for a design, which counts storeys. The
baseline reproduces the CA's site objective (2.100, within its rounding of the
distance) and the RL agent's (2.100) exactly, which the script asserts.

Over the design site, 189 cells:

| | objective | land-use mix | green | dwellings | housing term | residential cells | shop or amenity cells | home → amenity |
|---|---|---|---|---|---|---|---|---|
| baseline (today) | 2.100 | 0.229 | 3.2 % | 1,027 | 1.000 | 160 | 8 | 99 m |
| scenario_a | 2.196 | 0.318 | 5.8 % | 1,920 | 1.000 | 99 | 4 | 135 m |
| scenario_b | 2.840 | 0.530 | 33.3 % | 1,250 | 1.000 | 48 | 4 | 121 m |
| final | 2.955 | 0.728 | 29.6 % | 777 | 0.757 | 40 | 24 | 69 m |

Over the whole buurt the objective is 2.315 today, 2.331 for scenario_a,
2.462 for scenario_b and 2.469 for the final design, on the same grid and function.
Over the site they compare directly with the CA's programmes (compact 2.421, green 2.710).

**The final design scores highest and is the only one the housing term costs.**
A and B build more homes than they demolish and get the full 1.1. The final
design has 777 against today's 1,027, a housing term of 0.757, and still leads
on mix and shops.

**Both options score above today, scenario_b by far, and for the wrong reason
on mix.** The mix index counts green as one of its five uses. Housing replaced
by green raises it even though services are lost: the site's 8 shop or amenity
cells drop to the 4 of the kept school block, and the walk from a home to the
nearest one grows from 99 m to 135 m (A) and 121 m (B). scenario_b's lead is
mostly its 33 % green.

**Residential cells measure land, not homes.** scenario_a has fewer residential
cells than today (99 against 160) but about 1,920 estimated dwellings against
1,027, because its blocks are taller. That is why the housing term counts
dwellings for the designs, not cells.

**The open-ground rule matters.** Counted as green instead of vacant, the site
objective is 2.86 for scenario_a and 3.06 for scenario_b
(`open_ground_as_green` in the JSON). That is an upper bound: the model does
not say the courtyards are planted.

**With amenities on the ground floors.** `analysis/roads/place_amenities.py`
puts 20 shops, 7 health practices and a second school on the new blocks'
ground floors where they shorten walks most; the kept school stays fixed in the
kept block, already amenity on today's grid (`with_amenities` in the JSON: each
25 m cell holding a placed one becomes retail or amenity). The site objective
rises to 2.865 for scenario_a and 3.357 for scenario_b, mix to 0.623 and 0.755,
and the walk from a home to the nearest shop or amenity falls to 45.2 m (A) and
42.6 m (B), against
99 m today. A cell holds one use, so a shop cell stops counting as housing even
though the shop sits under flats: scenario_a's residential cells fall from 99
to 85.
