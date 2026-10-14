# analysis/abm_landuse — agent-based land-use modelling

Component 4.7 · Owner: **Atanas Malinkov** · study area: Bloemhof + Hillesluis · feeds `app/modules/landuse.js`

> Numbers here are generated from `data/processed/landuse_abm.json` and
> `landuse_rl.json`. If you re-run the models, re-check this file.

## Scripts

| Script | What it does | Writes |
|---|---|---|
| `fetch_landcover.py` | OSM green, water and roads — the surface BAG cannot see | `data/raw/osm_landcover.geojson`, `osm_roads.geojson` |
| `ca_landuse.py` | constrained cellular automaton, scenarios, validation | `data/processed/landuse_abm.json` + frame PNGs |
| `rl_landuse.py` | Q-learning agent that re-plans the design site, scored on the same formula | `data/processed/landuse_rl.json` |
| `weight_sensitivity.py` | re-scores the stored replicates across the weight simplex | `data/processed/landuse_weight_sensitivity.json` |

```bash
python analysis/morphology/fetch_landuse.py      # BAG units — needed first
python analysis/abm_landuse/fetch_landcover.py   # ~30 s
python analysis/abm_landuse/ca_landuse.py        # ~10 s
python analysis/abm_landuse/rl_landuse.py --episodes 120   # ~90 s
python analysis/abm_landuse/weight_sensitivity.py  # ~2 s, no model re-run
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

Grid: 76 × 59 cells of 25 m. States: water, road, green, residential, retail, amenity, industry, vacant.
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
| 10 % | 86.3 % | **0.715** |
| 25 % | 73.1 % | 0.492 |
| 50 % | 57.7 % | 0.253 |

κ discounts the agreement you would get by guessing the commonest class. The
curve degrades as a neighbourhood-driven model should: with context intact it
reconstructs well; strip half the city and it cannot know where things were.
κ ≈ 0.71 at 10 % is in the range land-use CA papers report.

## Scenario results

Programme: 269 cells (16.8 ha), 12 stochastic replicates each.

| scenario | objective | land-use mix | green | home → amenity |
|---|---|---|---|---|
| baseline | 1.560 | 0.522 | 8.5 % | 80 m |
| scenario_a | 1.665 | 0.548 | 8.5 % | 48 m |
| scenario_b **★** | 1.686 | 0.550 | 11.5 % | 54 m |

```
objective = 1.6 · land-use mix + 1.0 · green share
          + 0.8 · max(0, 1 − mean home-to-amenity distance / 400 m)
```

**scenario_b wins.** Trading some housing for park and amenity beats
maximising housing: it gains more on mix and green than it loses on walkability.

### How much of that is the weights?

Those three weights are ours, and the gap between the top two scenarios is
0.0059 on a normalised scale, against a replicate spread of
σ 0.0035 and 0.0027. So the ranking deserves a
sensitivity check rather than a full stop.

`weight_sensitivity.py` re-scores every stored replicate across
4,851 weight vectors on the normalised simplex
w_mix + w_green + w_prox = 1, re-picking the best replicate at each point exactly
as `ca_landuse.py` does. The CA is not re-run: each replicate already stores its
three raw components, so the sweep is exact and takes seconds.

| scenario | share of the weight space it wins |
|---|---|
| scenario_b **★** | 71 % |
| scenario_a | 29 % |
| baseline | 0 % |

**scenario_b's win is robust in direction but not overwhelming.** It takes
71 % of the weight space, scenario_a takes the other 29 %, and
baseline never wins under any positive weighting — that last part is
the firm result. The nearest weights that flip the answer are
0.51 · 0.14 · 0.35 (favouring scenario_a),
0.20 away on the simplex, so the default is not sitting
on a knife edge. Scenario_a wins when walkability is weighted heavily against
green space, which is exactly the trade it makes.

Three methods agree on the shares: a 0.02 lattice (72 / 28), a 0.01 lattice
(71 / 29) and 200,000 uniform Dirichlet draws (71 / 29).

The script reproduces the published objectives from the stored replicates before
it sweeps, and exits 1 if it cannot. Injecting a wrong weight or a wrong distance
normaliser was checked to make it fail.

**What the sweep cannot do.** It sweeps the *scoring* of the CA. The RL agent
optimises the objective directly, so re-scoring its result under other weights is
not the same experiment as retraining under them, and it is excluded. It also
explores the three terms we chose without asking whether they are the right three.

## The RL agent

Q-learning, TD(0), **linear** function approximation, ε-greedy, 120 episodes.

**It works on the design site only**, not the whole study area. Every cell of the
site that is not road or water (179 of 180) is cleared, and each episode the
agent re-plans all of them one cell at a time; reward is the change in the
objective. The rest of Bloemhof and Hillesluis is fixed context: it feeds the
agent's neighbourhood features, and a shop just outside the site still counts
for walkability, but the agent cannot change it and is not scored on it.

The objective is the CA's formula, **computed over the site's cells**: mix and
green share of the site, and the mean distance from homes in the site to the
nearest shop or amenity anywhere. Because the CA is scored over both buurten,
**the two models' numbers are not comparable**, and the figures keep them apart
(`fig_landuse_abm.png` for the CA, `fig_landuse_rl_site.png` for the agent).

Linear rather than deep **on purpose** — the value here is that the weights can
be read and argued with. A DQN would score similarly and explain nothing. A
torch DQN is the obvious extension.

Learns: 2.364 over the first 10 % of episodes → 2.473 over the last 10 %.
Best 2.480 against 0.890 for the site today; its plan reaches mix 0.780,
48 % green and 26 m to the nearest amenity (today 0.164, 2 % and 94 m).

**It gets there by demolishing housing: 155 residential cells become 27.** Nothing
in the objective values homes, and both the mix and the green term reward
replacing them, so this is the objective working as written, not a bug. It is the
clearest finding of the site run: a "mixed, green, walkable" score alone would
plan a residential complex with almost no residents. A housing floor (a minimum
number of residential cells) is the obvious next constraint and is not in yet.

### The interesting disagreement

The agent learned that **retail should avoid other retail**: −18.0, its
strongest aversion. Our CA assumes the opposite — its matrix gives
retail→retail **+0.8**, i.e. shops cluster.

Read the weights within a row, not on their own. Every class carries about +45 on
*vacant* neighbours and a negative weight on everything else, because on a
cleared site the vacant count mainly tells the agent how early in the episode it
is. What separates the classes is which neighbour each avoids most, and each
avoids its own kind: retail→retail −18.0, amenity→amenity −20.1. That is the mix
term asking for uses to be spread out.

Both are defensible and the disagreement is informative. The objective rewards
*walkability* — mean distance from homes to the nearest shop — which is minimised
by spreading shops out. Real retail clusters for agglomeration economies, which
this objective does not represent at all. **The model is right about the
objective, and the objective is incomplete.** Worth a paragraph in the report,
and only running both models surfaces it.

### A second example: today's housing kept

`rl_landuse.py --keep-housing` adds one rule: the plan must contain exactly as
many residential cells as the site has today (155). Actions that would break it
are masked, and the objective is unchanged, so the two runs differ only in that
rule (`landuse_rl_keep_housing.json`, `fig_landuse_rl_keep_housing.png`).

Best 1.300 against 0.890 for the site today: mix 0.335, 6 % green and 46 m to
the nearest amenity. The 24 non-housing cells become 6 retail, 8 amenity and 10
green, scattered through the blocks.

**It does not learn.** The last 10 % of episodes average 1.265, the first 10 %
1.278; a 400-episode run did no better (1.286 → 1.230, best 1.307). With housing
fixed, the agent's only freedom is where to put 24 cells, and the linear agent
places them no better than its early, mostly random episodes. Read this plan as
an example layout, the best of 120 episodes, not as an optimum.

### A deep Q-network on the same problem

`rl_dqn.py` swaps the agent and keeps everything else: grid, site, objective,
reward, discount and the housing rule. The network is a fully convolutional CNN
over a crop of the grid around the site (one-hot land use, site and empty-cell
masks, access, distance to water, plus broadcast site-wide shares, progress and
housing quota), four 3x3 convolutions (two dilated) and a 1x1 head giving a
Q-value for every cell x use, 70,372 weights. It picks from all empty cells, not
40 sampled ones. DQN with replay, a target network, Double DQN targets, Huber
loss and Adam; one update every 4 steps; 120 episodes, about 34 min on CPU.
Needs PyTorch (CPU), which is optional (see `requirements.txt`).

It also reports what the linear script does not: a **random policy** on the same
problem (30 episodes), the baseline any agent has to beat, and one **greedy**
run of the learned policy with no exploration.

| objective over the site | random, mean | linear Q, best | DQN, best | DQN, greedy | DQN, end of training |
|---|---|---|---|---|---|
| no housing rule | 2.360 | **2.480** | 2.475 | 2.180 | 2.234 |
| today's housing kept | 1.281 | **1.300** | 1.295 | 1.250 | 1.169 |

**The DQN does not do better.** Its best episodes came early, while it was still
exploring; its greedy policy and its last episodes score *below the random
policy*. A CNN with 70,000 weights gets about 5,000 gradient steps in 120
episodes, far too few; the linear agent's 13 weights per use learn much faster
from the same experience. More episodes, reward shaping or a policy-gradient
method might change this, at hours of CPU per run. The random baseline also puts
the linear agent in proportion: on a cleared site, a random mix of four uses
already scores 2.36, so the agent's gain is 0.12, and under the housing rule
none (`fig_landuse_rl_comparison.png`).

## Honest limitations

- **Demand is set by us**, not derived from a regional model. This explores the
  consequences of a development programme; it does not forecast one.
- The RL agent optimises the objective **directly**, while the CA follows fixed
  rules and is merely *scored* on it. RL scoring higher is expected by
  construction and is **not** evidence that RL models cities better.
- The objective is a weighted sum of three terms we chose. The sweep above
  shows the winner is weight-dependent: scenario_b takes 71 % of the weight
  space and scenario_a the rest. Only "baseline never wins" holds regardless.
  Whether those three terms are the right three is still untested.
- The RL agent re-plans the design site with **no housing requirement**, and
  loses 83 % of the site's residential cells doing so (above).
- The land-use grid ends at the buurt bounding box, which cuts off the site's
  strip south of Strevelsweg: 11.25 of its 12.38 ha are modelled.
- The RL run is one seed. The CA's scenarios are spread over replicates; the
  agent's best plan is not.
- 25 m cells cannot represent a building. This allocates land use; turning that
  into massing is `analysis/scenarios/`.
- OSM land cover is not authoritative the way BAG is, though for "is this a
  park, a canal or a street" it is current and complete enough here.

## For component 4.9

The preferred configuration (scenario_b) is a land-use allocation, not a
building design. `analysis/scenarios/` turns it into massing, which can then be
fed back through the SVF, density and mix indicators to check the model was
right.
