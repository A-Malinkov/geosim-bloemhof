# analysis/abm_landuse — agent-based land-use modelling

Component 4.7 · Owner: **Atanas Malinkov** · feeds `app/modules/landuse.js`

> Numbers here are generated from `data/processed/landuse_abm.json` and
> `landuse_rl.json`. If you re-run the models, re-check this file.

## Scripts

| Script | What it does | Writes |
|---|---|---|
| `fetch_landcover.py` | OSM green, water and roads — the surface BAG cannot see | `data/raw/osm_landcover.geojson`, `osm_roads.geojson` |
| `ca_landuse.py` | constrained cellular automaton, scenarios, validation | `data/processed/landuse_abm.json` + frame PNGs |
| `rl_landuse.py` | Q-learning agent over the same objective | `data/processed/landuse_rl.json` |

```bash
python analysis/morphology/fetch_landuse.py      # BAG units — needed first
python analysis/abm_landuse/fetch_landcover.py   # ~30 s
python analysis/abm_landuse/ca_landuse.py        # ~10 s
python analysis/abm_landuse/rl_landuse.py        # ~40 s
```

## Why two models

| | rules | what it tells you |
|---|---|---|
| **Cellular automaton** | **assumed** — an influence matrix we wrote | what follows *from those assumptions* |
| **RL agent** | **learned** — given only the objective | what the objective *actually implies* |

Where they agree, the assumption is supported. Where they disagree, one of them
is worth arguing about — and they do disagree (below).

## The cellular automaton

Constrained CA after **White, Engelen & Uljee (1997)**, *The use of constrained
cellular automata for high-resolution modelling of urban dynamics*.

Grid: 48 × 48 cells of 25 m. States: water, road, green, residential, retail, amenity, industry, vacant.
Water and road never convert.

```
P(i,k) = N(i,k) · S(i,k) · A(i,k) · v
```

- **N** neighbourhood effect — influence weights per (candidate class, neighbour
  class), distance-decayed. *This is where the spatial logic lives.*
- **S** suitability — water is never developable; industry stays within 200 m of
  existing industry or the port.
- **A** accessibility — exponential decay from the road **surface**.
- **v** stochastic perturbation `1 + (-ln u)^α`. Without it the CA makes
  implausibly regular blocks and returns the same answer every run.

### Building the initial raster — a trap worth knowing

The first version buffered every OSM centreline by half a cell and burned it as
road. That put **41 % of the study area under tarmac** — 44 km of road at 22.5 m
width is 99 ha, more than the square itself — and BAG buildings then overwrote
**67 %** of it. Two errors partially cancelling, which happened to look
plausible and was indefensible.

Now: carriageway width per OSM class (primary 14 m … service 5 m), measured as
an **area fraction** on a 5 m sub-grid, giving **17 % carriageway** across the
study area. Priority is explicit — water, then building, then road, then land
cover.

And accessibility is measured from that continuous road **surface**, not from
cells whose final state is ROAD. At 25 m most street cells also contain a
building and are labelled residential, so using the discrete state left the
accessibility field full of holes.

## Validation — erase and regrow

A CA run with demand equal to current counts converts nothing, so "the baseline
did not change" validates **nothing**. The real test: erase a random share of
developed cells, restore the original demand, see how much of the real map comes
back.

| erased | agreement | Cohen's κ |
|---|---|---|
| 10 % | 85.7 % | **0.657** |
| 25 % | 73.0 % | 0.425 |
| 50 % | 59.1 % | 0.201 |

κ discounts the agreement you would get by guessing the commonest class. The
curve degrades as a neighbourhood-driven model should: with context intact it
reconstructs well; strip half the city and it cannot know where things were.
κ ≈ 0.66 at 10 % is in the range land-use CA papers report.

## Scenario results

Programme: 138 cells (8.6 ha), 12 stochastic replicates each.

| scenario | objective | land-use mix | green | home → amenity |
|---|---|---|---|---|
| baseline | 1.391 | 0.440 | 6.4 % | 89 m |
| scenario_a | 1.503 | 0.473 | 6.4 % | 59 m |
| scenario_b **★** | 1.533 | 0.482 | 9.4 % | 66 m |

```
objective = 1.6 · land-use mix + 1.0 · green share
          + 0.8 · max(0, 1 − mean home-to-amenity distance / 400 m)
```

**scenario_b wins.** Trading some housing for park and amenity beats
maximising housing: it gains more on mix and green than it loses on walkability.

## The RL agent

Q-learning, TD(0), **linear** function approximation, ε-greedy, 120 episodes.
Each episode it places the same programme one cell at a time; reward is the
change in the objective.

Linear rather than deep **on purpose** — the value here is that the weights can
be read and argued with. A DQN would score similarly and explain nothing. A
torch DQN is the obvious extension.

Learns: 1.612 over the first 10 % of episodes → 1.669 over the last 10 %.
Best 1.678 against 1.391 today; its plan reaches mix 0.560 and
46 m to the nearest amenity.

### The interesting disagreement

The agent learned that **retail should avoid other retail**
(-0.5) while being drawn to housing (+0.7). Our CA assumes the opposite —
its matrix gives retail→retail **+0.8**, i.e. shops cluster.

Both are defensible and the disagreement is informative. The objective rewards
*walkability* — mean distance from homes to the nearest shop — which is minimised
by spreading shops out. Real retail clusters for agglomeration economies, which
this objective does not represent at all. **The model is right about the
objective, and the objective is incomplete.** Worth a paragraph in the report,
and only running both models surfaces it.

## Honest limitations

- **Demand is set by us**, not derived from a regional model. This explores the
  consequences of a development programme; it does not forecast one.
- The RL agent optimises the objective **directly**, while the CA follows fixed
  rules and is merely *scored* on it. RL scoring higher is expected by
  construction and is **not** evidence that RL models cities better.
- The objective is a weighted sum of three terms we chose. Different weights
  give a different winner; a sensitivity sweep is the obvious next step and is
  not done.
- The RL agent may only build on currently vacant land, so it cannot propose
  redevelopment. The CA can convert any non-fixed cell.
- 25 m cells cannot represent a building. This allocates land use; turning that
  into massing is `analysis/scenarios/`.
- OSM land cover is not authoritative the way BAG is, though for "is this a
  park, a canal or a street" it is current and complete enough here.

## For component 4.9

The preferred configuration (scenario_b) is a land-use allocation, not a
building design. `analysis/scenarios/` turns it into massing, which can then be
fed back through the SVF, density and mix indicators to check the model was
right.
