# analysis/abm_landuse — agent-based land-use modelling

Component 4.7 · Owner: **Atanas Malinkov** · feeds `app/modules/landuse.js`

## Scripts

| Script | What it does | Writes |
|---|---|---|
| `fetch_landcover.py` | OSM green, water and roads — the surface BAG cannot see | `data/raw/osm_landcover.geojson`, `osm_roads.geojson` |
| `ca_landuse.py` | constrained cellular automaton, scenarios, validation | `data/processed/landuse_abm.json` + frame PNGs |
| `rl_landuse.py` | Q-learning agent over the same objective | `data/processed/landuse_rl.json` |

```bash
python analysis/abm_landuse/fetch_landcover.py   # ~30 s
python analysis/abm_landuse/ca_landuse.py        # ~5 s
python analysis/abm_landuse/rl_landuse.py        # ~40 s
```

`ca_landuse.py` needs `data/raw/bag_verblijfsobjecten.geojson`, so run
`analysis/morphology/fetch_landuse.py` first.

## Why two models

They answer different questions, and running both is the point.

| | rules | what it tells you |
|---|---|---|
| **Cellular automaton** | **assumed** — an influence matrix we wrote | what follows *from those assumptions* |
| **RL agent** | **learned** — given only the objective | what the objective *actually implies*, discovered |

Where the two agree, the assumption is supported. Where they disagree, one of
them is worth arguing about — and they do disagree, interestingly (below).

## The cellular automaton

Constrained CA after **White, Engelen & Uljee (1997)**, *The use of constrained
cellular automata for high-resolution modelling of urban dynamics*.

Grid: 48 × 48 cells of 25 m over the study square.
States: water, road, green, residential, retail, amenity, industry, vacant. Water and road never convert.

Initial state from real data: OSM water and green, OSM roads buffered to one
cell, and BAG units on top (a building standing on mapped grass is a building).

Each step, every convertible cell gets a transition potential for every state:

```
P(i,k) = N(i,k) · S(i,k) · A(i,k) · v
```

- **N** neighbourhood effect — influence weights per (candidate class, neighbour
  class) with distance decay. *This is where the spatial logic lives.*
- **S** suitability — water is never developable; industry is confined to within
  200 m of existing industry or the port.
- **A** accessibility — exponential decay from the road network.
- **v** stochastic perturbation, `1 + (-ln u)^α`. Without it the CA produces
  implausibly regular blocks and returns the same answer every run.

Cells are then allocated to classes with unmet demand, highest potential first.
Existing uses resist conversion by an inertia factor, so the model does not
bulldoze a working neighbourhood for a marginal gain.

## Validation — erase and regrow

A CA run with demand equal to current counts converts nothing, so "the baseline
did not change" validates **nothing**. The real test: erase a random share of
developed cells, restore the original demand, and see how much of the actual map
the model rebuilds.

| erased | agreement | Cohen's κ |
|---|---|---|
| 10 % | 87.2 % | **0.655** |
| 25 % | 77.5 % | 0.460 |
| 50 % | 66.3 % | 0.251 |

κ discounts the agreement you would get by guessing the commonest class. The
curve degrades exactly as a neighbourhood-driven model should: with most of the
context intact it reconstructs well; strip half the city and it cannot know
where things were. κ 0.66 at 10 % is in the range land-use CA papers report.

## Scenario results

Development programme: 138 cells (8.6 ha), 12 stochastic replicates each.

| scenario | objective | land-use mix | green | home → amenity |
|---|---|---|---|---|
| baseline | 1.321 | 0.408 | 4.6 % | 89 m |
| scenario_a | 1.429 | 0.445 | 4.6 % | 65 m |
| scenario_b **★** | 1.469 | 0.460 | 7.6 % | 72 m |

```
objective = 1.6 · land-use mix + 1.0 · green share
          + 0.8 · max(0, 1 − mean home-to-amenity distance / 400 m)
```

**scenario_b wins.** Trading some housing for park and amenity beats
maximising housing: it gains more on mix and green than it loses on walkability.
That is a concrete, defensible argument for the design.

## The RL agent

Q-learning, TD(0), **linear** function approximation, ε-greedy,
120 episodes. Episodic MDP: each episode the agent places the same
development programme one cell at a time; reward is the change in the objective.

Linear rather than a deep network **on purpose** — the value of the RL run here
is that the learned weights can be read and argued with. A DQN would score
similarly and explain nothing. That is a deliberate choice; a torch DQN is the
obvious extension.

It learns: objective 1.554 over the first 10 % of episodes →
1.605 over the last 10 %, best 1.616 against 1.321 today.

### The interesting disagreement

The agent learned that **retail should avoid other retail** (weight
-0.4) while being drawn to housing (+0.7). Our CA assumes the
opposite — its matrix gives retail→retail **+0.8**, i.e. shops cluster.

Both are defensible and the disagreement is informative. The objective rewards
*walkability* — mean distance from homes to the nearest shop — which is minimised
by spreading shops out. Real retail clusters because of agglomeration
economies, which this objective does not represent at all. **The model is right
about the objective and the objective is incomplete.** That is worth a paragraph
in the report, and it is the sort of thing only running both models surfaces.

## Honest limitations

- **Demand is set by us**, not derived from a regional model. This explores the
  consequences of a development programme; it does not forecast one.
- The RL agent optimises the objective **directly**, while the CA follows fixed
  rules and is merely *scored* on it. RL scoring higher is expected by
  construction and is **not** evidence that RL models cities better.
- The objective is a weighted sum of three terms we chose. Different weights
  give a different winner; a sensitivity sweep over them is the obvious next
  step and is not done.
- 25 m cells cannot represent a building. This is a land-use allocation model,
  not a design tool — it says *what should go roughly where*, and
  `analysis/scenarios/` turns that into massing.
- OSM land cover is not authoritative the way BAG is, though for "is this a
  park, a canal or a street" it is current and complete enough here.

## For component 4.9

The preferred configuration (scenario_b) is a land-use allocation, not a
building design. Turning it into massing — footprints with heights and functions
— is what `analysis/scenarios/` does, and the resulting design can then be fed
back through the SVF, density and mix indicators to check the model was right.
