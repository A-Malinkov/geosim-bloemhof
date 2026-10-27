# Geosimulation final project — Bloemhof, Rotterdam

An interactive CesiumJS web app backed by Python geospatial analysis. We design a
residential complex in **Bloemhof** (wijk Feijenoord, Rotterdam-Zuid) and justify
it with geospatial analysis and simulation.

**Study area: the buurt Bloemhof**, 78.8 ha and about 13,700 people. Everything
is *analysed* over it; the design scenarios occupy only a small site inside it.
(Until 2026-10-22 the study area also took in Hillesluis next door; the team
narrowed it to Bloemhof and every analysis was re-run.)

The boundaries come from the CBS wijkenbuurten service, not from hand-typed
coordinates. They are defined in exactly two places —
[`app/config.js`](app/config.js) for the app and
[`analysis/common/project.py`](analysis/common/project.py) for the analyses.
Change the buurt codes there if the area moves, then re-run the analyses.

---

> **Using an AI assistant on this project?** Point it at
> [CLAUDE.md](CLAUDE.md) (or [AGENTS.md](AGENTS.md) for tools that read that
> instead). They carry the conventions and the data-source traps that cost us
> the most time, so an assistant starting cold does not rediscover them.

## 1. Getting set up





### Get the project

```bash
git clone https://github.com/A-Malinkov/geosim-bloemhof.git
cd geosim-bloemhof
```

(Or copy the folder out of the shared cloud folder — either works. **Do not copy
a `.venv`**; you make your own in step 2.)

### Add your Cesium ion token — do this first

The token is **not** in the repository. Copy the template and paste your own:

```bash
cp app/config.local.example.js app/config.local.js
```

then open `app/config.local.js` and put your token in it. Get one free at
<https://ion.cesium.com/tokens>. `config.local.js` is gitignored, so your token
never reaches GitHub.

Without a token the app still runs — PDOK imagery, 3DBAG buildings, the Rotterdam
tilesets and every dashboard panel work. You only lose Cesium World Terrain, so
the ground is a smooth ellipsoid instead of real relief.

### Python environment
Python 3.10+ (this was built and tested on 3.14.3).

```bash
cd "<project folder>"
python3 -m venv ~/.venvs/geosim-rotterdam        # keep it OUTSIDE the shared folder
source ~/.venvs/geosim-rotterdam/bin/activate    # Windows: ...\Scripts\activate
pip install -r requirements.txt
python analysis/common/project.py                # should print the study area
```

> **Why outside the folder?** The environment is ~1 GB. If it sits in the project
> it gets synced to everyone, and a venv is not portable between machines anyway —
> it hard-codes absolute paths. Everyone builds their own from `requirements.txt`.

`requirements.txt` uses `pyogrio` rather than `fiona`. GeoPandas 1.x uses pyogrio
by default, it ships binary wheels, and unlike fiona it does not need a system
GDAL install. If you add a package, add it to `requirements.txt` and tell the team.

### Run the app
The app is plain HTML/JS — no build step — but it **must** be served over HTTP.
Opening `index.html` as a `file://` URL breaks ES modules and every fetch.

```bash
python3 -m http.server 8000          # from the PROJECT ROOT, not from app/
```
then open <http://localhost:8000/app/index.html>.

Serve from the project root so the app can reach `../data/processed/`.

**VS Code Live Server**: right-click `app/index.html` → *Open with Live Server*.
Check its root is the project folder; if the data files 404, use `http.server`.

---

## 2. Who owns what

**Only edit your own module and your own analysis folder.**

| # | Component | Your JS file | Your analysis folder |
|---|-----------|--------------|----------------------|
| 1 | 3D city model + proposed massing | `app/modules/scenarios.js` | `analysis/scenarios/` |
| 2 | Data layers (imagery, AHN, buildings) | `app/modules/layers.js` | — |
| 2b| **3D vegetation** — *Atanas Malinkov* | `app/modules/vegetation.js` | `analysis/morphology/` |
| 3 | **Morphology indicators (SVF, density, height, land-use mix)** — *Atanas Malinkov* | `app/modules/indicators.js` | `analysis/morphology/` |
| 4 | KNMI weather + AI prediction | `app/modules/knmi.js` | `analysis/knmi/` |
| 5 | Wind + noise simulation | `app/modules/wind_noise.js` | `analysis/wind_noise/` |
| 6 | CBS socio-demographics | `app/modules/cbs.js` | `analysis/cbs/` |
| 7 | **Agent-based land-use model** — *Atanas Malinkov* | `app/modules/landuse.js` | `analysis/abm_landuse/` |
| 8 | Road network optimization | `app/modules/roads.js` | `analysis/roads/` |
| 8b| Public-transport stops and frequencies | `app/modules/transit.js` | `analysis/transit/` |
| 9 | Design scenarios | `app/modules/scenarios.js` | `analysis/scenarios/` |

### Shared files — go through one person
`app/main.js` · `app/index.html` · `app/style.css` · `app/config.js` ·
`analysis/common/project.py`

(`app/config.local.js` is yours alone and is never committed — put your token
there, nothing else.)

These are the only files two people can collide on. If you need something added
there, ask the coordinator rather than editing it yourself. In practice you
should almost never need to, because of the module contract below.

---

## 3. How a module works

Every file in `app/modules/` exports one function:

```js
export async function setup(ctx) { … }
```

`main.js` calls it and passes `ctx`. **Everything you need is on `ctx`, so you can
add layers and dashboard panels without touching any shared file.**

| `ctx` member | What it does |
|---|---|
| `ctx.viewer`, `ctx.Cesium` | the Cesium viewer and namespace |
| `ctx.config` | everything from `config.js` |
| `ctx.registerLayer({id, label, group, show, target \| onToggle})` | adds a checkbox to the left panel, returns `{ setVisible(bool) }` |
| `ctx.registerPanel({id, title, subtitle, order})` | adds a dashboard card, returns an empty `<div>` to fill |
| `ctx.onScenarioChange(fn)` | `fn(scenario)` runs on every scenario switch, and once at startup |
| `ctx.loadJson(path)` | fetches a file from `data/processed/`, returns `null` if missing or still a stub |
| `ctx.placeholder(el, {...})` | the standard "not built yet" block |
| `ctx.note(text, "ok"\|"warn"\|"err")` | adds a chip to the status bar |

If your `setup()` throws, main.js catches it, logs it and carries on — one broken
module will not take the app down.

The left panel groups layers into collapsible sections. Which group a layer
lands in, the order of the groups and which start open are set in `config.js`
under `layerPanel`, so the panel can be tidied without editing anyone's module.

Reuse the CSS classes in `style.css` (`.kv`, `.ph`, `.muted`, `.delta`, `.seg`,
`.feed`) instead of adding global styles.

### The data hand-off
Python writes JSON into `data/processed/`; the app fetches it. That is the only
coupling between the two halves, so you can work on either side independently.

Each expected file already exists as a **stub** containing `"_status":
"not_computed_yet"` and a `_schema` block describing what to put in it.
`ctx.loadJson()` treats a stub as "no data", so the app shows the placeholder
panel until you overwrite it with real output. **Read the stub before you write
the real file** — it tells you the shape the JS expects.

---

## 4. The height datum — read this before adding any 3D layer

Cesium places everything relative to the **WGS84 ellipsoid**. Dutch data is almost
always in **NAP** (Normaal Amsterdams Peil). At Bloemhof these differ by
**+43.62 m**, computed with PROJ 9.8.1 and the official NSGI geoid grid
`nl_nsgi_nlgeo2018.tif` (EPSG:7415 → EPSG:4979).

Drop a NAP-referenced tileset into Cesium unchanged and it sits 43.6 m too low:
trees buried, buildings showing only their top few metres. This is the single most
common bug in Dutch Cesium projects.

Current state, each value verified rather than assumed:

| Layer | Offset | How we know |
|---|---|---|
| 3DBAG buildings | **0 m** | content CRS is EPSG:4978 (earth-centred), so geometry is already ellipsoidal. Confirmed in-browser: roofs reach +28 m above terrain. |
| Rotterdam 3D trees / green | **+43.62 m** | decoded a leaf tile: its `RTC_CENTER` sits at ellipsoid height ≈ 0 m where real ground is ≈ +43 m. Confirmed in-browser: canopies reach +18 m with the offset, only +1.5 m without. |
| Our massing (`scenarios.js`) | **+43.62 m** | `height_m` in the GeoJSON is metres above NAP, lifted on render |
| Trees from the register (`vegetation.js`) | **+43.62 m** | `ground_nap_m` sampled from the AHN DTM in Python |

Per-layer values live in `config.js` under `layers.*.heightOffsetM`.

**To check your own layer:** `Ctrl+click` anywhere on the map. The console prints
the height of the surface under the cursor and the terrain height at the same
pixel, in both ellipsoid and NAP. If your layer is ~43 m out, you will see it.

---

## 5. Data sources

All verified reachable on 2026-09-21. URLs live in `config.js` and
`analysis/common/project.py`.

| What | Source | Notes |
|---|---|---|
| Aerial imagery | PDOK Luchtfoto RGB WMTS, `Actueel_orthoHR` | EPSG:3857. TileMatrix labels are zero-padded (`"00"`…`"21"`) — Cesium's defaults 404. |
| Buildings | 3DBAG v20250903 LoD2.2, TU Delft | CC BY 4.0 |
| Trees, green (3D Tiles) | Rotterdam 3D | NAP heights, see above |
| Tree register | Gemeente Rotterdam `SB_Infra/Bomen` ArcGIS | 2,172 trees in the study area, 206 species |
| Elevation | AHN via PDOK WCS, `dsm_05m` / `dtm_05m` | 0.5 m, EPSG:28992, NAP heights |
| Neighbourhoods | PDOK CBS wijkenbuurten 2025 WFS | ⚠ ignores `cql_filter`; needs an OGC Filter XML |
| Demographics | CBS StatLine OData `86358NED` (2026) | 2025 = `86165NED`, 2024 = `85984NED` |
| Weather, live | Open-Meteo, KNMI HARMONIE-AROME 2 km | browser-callable, no key, CC BY 4.0 |
| Weather, sensors | KNMI Data Platform Open Data API | Python only — see the warning below |
| Weather, historical | `daggegevens.knmi.nl`, station 344 | JSON, no CORS → Python only |
| Public transport | OVapi GTFS-NL (`gtfs.ovapi.nl/nl/gtfs-nl.zip`), from NDOV open data | 242 MB; Python only, cached in `cache/transit/`. Set a `User-Agent`. See `analysis/transit/README.md` |

### ⚠ KNMI: two traps, and how the live feed works around them
1. **The dataset everyone's tutorial uses is dead.** `Actueel10mindataKNMIstations`
   v2 stopped updating on 2025-10-02. The live one is
   `10-minute-in-situ-meteorological-observations` version `1.0`.
2. **The browser cannot call the KNMI API.** A plain `curl` GET succeeds and even
   returns `Access-Control-Allow-Origin: *`, which is misleading: the browser
   sends a CORS preflight first because of the `Authorization` header, and KNMI's
   `OPTIONS` response has no CORS headers, so the fetch is blocked. Do not re-add
   a `fetch()` to `api.dataplatform.knmi.nl` in the app — it fails in every browser.

**So the weather dashboard uses two paths, and it needs both:**

| | Source | Where | What it is |
|---|---|---|---|
| **Live, self-refreshing** | Open-Meteo, model `knmi_harmonie_arome_netherlands` | browser, direct | KNMI's own HARMONIE-AROME forecast model, 2 km grid, hourly updates |
| **Actual sensor readings** | KNMI Open Data + `daggegevens` | Python → JSON | the real station observations §4.4 asks for — *still to be written* |

Open-Meteo needs no key and sends CORS headers, so the page polls it every
5 minutes and updates itself. That is what makes the dashboard genuinely live
rather than a file someone regenerates by hand — which the rubric distinguishes
between. The panel labels which is which, so nobody mistakes model output for a
sensor reading.

Open-Meteo's free tier is 10,000 calls/day (we use ~288) and its data is
**CC BY 4.0 — the attribution in the panel must stay**.

The AHN, 3DBAG, Rotterdam 3D and PDOK services all send `Access-Control-Allow-Origin: *`
and work fine from the browser.

---

## 6. Folder layout

```
app/
  index.html  main.js  style.css  config.js     ← shared, coordinator-owned
  modules/                                      ← one file per component
  assets/
analysis/
  common/project.py                             ← shared: study area, CRS, paths
  morphology/  knmi/  wind_noise/  cbs/
  abm_landuse/  roads/  scenarios/  transit/
data/
  raw/                                          ← downloads, as delivered
  processed/                                    ← JSON the app reads
docs/                                           ← figures for the report
```

Rasters are the bulk of the project: ~50 MB in `data/raw/` (AHN) and ~38 MB of
SVF GeoTIFFs, against ~250 KB of code. **They are gitignored** — all of it is
rebuilt in about two minutes by the scripts in section 7, and git handles large
binaries badly. The small `.json`, `.geojson` and `docs/*.png` results *are*
committed, because those are the actual findings. So a fresh clone is ~5 MB and
you run the scripts once to fill in the rest.

---

## Project status

Maintained by hand. Run `python analysis/check_docs.py` to verify the
numbers here still match `data/processed/`.

| # | Component | Status | Owner |
|---|---|---|---|
| 4.1 | 3D city model + proposed massing | existing buildings ✅ · design site chosen ✅ · scenario_a massing ✅ (Rhino OPTION 1) · scenario_b massing ✅ (Rhino OPTION 2) | — |
| 4.2 | Geospatial data layers | ✅ done | — |
| 4.3 | Urban morphological indicators | ✅ done — SVF 0.696, GSI 0.333, FSI 1.003, mix 0.267, Bloemhof; plus street H/W and direct-sun hours. SVF, sun hours and H/W also run for both scenarios | Atanas |
| 4.4 | KNMI sensors + AI prediction | ✅ done — live feed, sensors, 5 y history, model comparison | Atanas |
| 4.5 | Wind + noise simulation | 🟡 noise done (baseline, NoiseModelling 6.0.0) · scenario_a wired, not run · wind not started | — |
| 4.6 | CBS socio-demographics | ❌ not started | — |
| 4.7 | Agent-based land-use model | ✅ done — CA + RL, prefers the `green` programme; Rhino options scored on the same objective | Atanas |
| 4.8 | Road network optimization | ✅ done — walk network and walks to everyday destinations for baseline, scenario_a and scenario_b, footpath-link optimiser on both scenarios. Site grid 377.4 m today → 371.2 m in scenario_a, 378.0 m in scenario_b | Atanas |
| 4.9 | Scenario comparison | ✅ done — indicator by indicator on the design site, no overall score (`analysis/comparison/`, six figures, app card). Wind, scenario noise and CBS shown as not computed | Atanas |

**6 of 9 complete.** The remaining components carry the heaviest rubric
weight, and 4.9 depends on all of them writing outputs keyed
`baseline` / `scenario_a` / `scenario_b` — which the module contract already
does, so do not build anything that cannot be re-run per scenario.

## 7. What already works

Components **2b (3D vegetation)** and **3 (all four morphology indicators)** are
done, and the weather dashboard is live (Atanas Malinkov). To reproduce from
scratch:

```bash
source ~/.venvs/geosim-rotterdam/bin/activate

python analysis/common/project.py                # buurt boundaries          (~5 s)
python analysis/morphology/fetch_ahn.py          # AHN DSM + DTM, tiled      (~30 s)
python analysis/morphology/fetch_trees.py        # tree register; --from-cache if the service is down
python analysis/morphology/fetch_buildings.py    # 5,804 buildings from 3DBAG(~1 min)
python analysis/morphology/sky_view_factor.py    # SVF raster + statistics   (~40 s)
python analysis/morphology/density_height.py     # Spacematrix density       (~15 s)
python analysis/morphology/fetch_landuse.py      # 9,880 BAG units           (~5 s)
python analysis/morphology/landuse_mix.py        # land-use mix indices      (~5 s)
python analysis/morphology/make_figures.py       # report figures into docs/ (~40 s)

python analysis/knmi/fetch_knmi.py               # sensors + 5 y history     (~2 min)
python analysis/knmi/train_forecast.py           # train + score the models  (~6 min)

python analysis/abm_landuse/fetch_landcover.py   # OSM green/water/roads     (~30 s)
python analysis/abm_landuse/ca_landuse.py        # cellular automaton        (~5 s)
python analysis/abm_landuse/rl_landuse.py --episodes 120  # RL agent, design site  (~90 s)
python analysis/abm_landuse/weight_sensitivity.py # objective-weight sweep    (~2 s)

python analysis/roads/road_network.py            # walk network, per scenario (~3 min first run)
python analysis/roads/optimise_links.py          # footpath links, both scenarios (~15 s)

python analysis/transit/fetch_transit.py         # stops + line frequencies (~2 min, 242 MB feed on first run)
```

> The LSTM needs PyTorch, which is **not** in `requirements.txt` (~780 MB).
> `pip install --index-url https://download.pytorch.org/whl/cpu torch` if you
> want it; without it the script runs the other four models and says so.

Then reload the app: the **Vegetation** and **Urban morphology** panels fill in,
and *Sky View Factor* appears under **Analysis** in the layer panel.

### Headline numbers

Every figure is clipped to the buurt polygon, so numerator and denominator
share one boundary.

| indicator | Bloemhof |
|---|---|
| Sky View Factor, pedestrian level | **0.696** |
| GSI · FSI · storeys | **0.333 · 1.003 · 3.01** |
| Mean building height | **8.5 m** (σ 2.9) |
| Land-use mix, Shannon | **0.267** |
| Trees · per hectare | **1,204 · 15.3** |
| Canopy cover | **6.6 %** |

Bloemhof is dense, low, enclosed and mono-functional: 86 % of its floor space is
residential.

Other results:

| | |
|---|---|
| SVF under a tree crown vs 15 m from any tree | **0.35 vs 0.70** — trees remove 50 % of visible sky |
| Weather forecast (temperature, +6 h) | MAE 1.29 °C, 54 % better than assuming no change |
| Weather forecast (wind, +6 h) | MAE 1.13 m/s — but it under-predicts strong winds by 0.5 m/s |
| Land-use model | CA prefers the **green** programme (mix 0.391); RL agent re-planning the design site reaches mix 0.779, but keeps only 30 of its 160 residential cells |

### Figures (`docs/`)

| File | What it shows |
|---|---|
| `fig_svf_map.png` | SVF across the study area, buildings and water excluded |
| `fig_svf_distribution.png` | how enclosed open ground is, with mean and p05 |
| `fig_canopy_effect.png` | SVF under canopy vs in the open — the vegetation finding |
| `fig_tree_species.png` | the 12 commonest species |
| `fig_tree_heights.png` | tree height-class distribution |
| `fig_tree_map.png` | where the trees are, sized by crown, coloured by height |
| `fig_spacematrix.png` | GSI–FSI scatter with storey and OSR isolines — what kind of density this is |
| `fig_density_maps.png` | FSI and within-cell height variation across the study area |
| `fig_landuse_mix.png` | what the floor space is used for, and where the mix is |
| `fig_landuse_abm.png` | the CA's land-use scenarios over the study area, design site outlined |
| `fig_landuse_rl_site.png` | the design site today vs the RL agent's plan, what changed, and the learning curve |

Everything else is a wired-up skeleton waiting for its owner.

> **Note on the study area.** It is the whole buurt Bloemhof, taken from the CBS
> boundary — not a square round a point, which an earlier version used, and no
> longer Hillesluis as well (dropped 2026-10-22). Statistics are clipped to the buurt polygon; the data
> is fetched over a padded box so that buildings just outside still count as
> obstructions. The design scenarios occupy only the smaller design site inside.

---

## 8. Troubleshooting

| Symptom | Cause |
|---|---|
| Blank page, "Loading CesiumJS…" stuck | no internet, or the CDN is blocked — Cesium loads from cdnjs |
| Dashboard panels all say "not computed yet" | normal until you run the analysis scripts |
| `data/processed/*.json` 404s | you served from `app/` instead of the project root |
| Buildings or trees float / sink ~43 m | height datum — see section 4, and Ctrl+click to probe |
| A draped raster sits ~30 m off | you built a lon/lat rectangle from RD corners; warp the raster to EPSG:4326 first |
| Terrain missing, everything flat | the Cesium ion token in `config.js` expired |
| `pip install` fails building fiona/GDAL | you re-added `fiona`; use `pyogrio` |
| Console shows a 404 for `config.local.js` | you skipped the token step — `cp app/config.local.example.js app/config.local.js` |
| SVF layer or panels empty after cloning | the rasters are not in git by design; run the four scripts in section 7 |
