# analysis/knmi — weather dashboard and AI prediction

Component 4.4 · Owner: **Atanas Malinkov** · feeds `app/modules/knmi.js`

> Numbers here are generated from `data/processed/knmi_forecast.json`. If you
> retrain, regenerate this file — they go stale silently otherwise.

## Scripts

| Script | What it does | Writes |
|---|---|---|
| `fetch_knmi.py` | latest 10-minute sensor observation, plus hourly and daily history | `data/processed/knmi_current.json`, `knmi_daily_history.json`, `data/raw/knmi_hourly_344.json` |
| `train_forecast.py` | trains and compares forecast models, reports accuracy | `data/processed/knmi_forecast.json` |

```bash
python analysis/knmi/fetch_knmi.py        # ~2 min for 5 years of history
python analysis/knmi/train_forecast.py               # ~5 min with the LSTM; the published run
```

## Status

- [x] **4.4a real-time monitoring** — live self-refreshing panel (KNMI
      HARMONIE-AROME via Open-Meteo, in the browser) *and* real KNMI station
      sensor readings via Python
- [x] **4.4a aggregated history** — 2,090 daily records, 5 years, station 344
- [x] **4.4b AI prediction** — two models (gradient boosting, LSTM)
      against two naive baselines, accuracy reported

## Three data paths, and why there are three

| | Source | Where | What it is |
|---|---|---|---|
| Live, self-refreshing | Open-Meteo, `knmi_harmonie_arome_netherlands` | browser | KNMI's 2 km forecast **model**, updated hourly |
| Sensor readings | KNMI Open Data, 10-min in-situ observations | Python | what the **instruments measured** |
| History | KNMI climatology (hourly + daily) | Python | the training set and the dashboard chart |

The browser cannot call KNMI directly — the `Authorization` header triggers a
CORS preflight KNMI does not answer, and the observations are NetCDF. Open-Meteo
fills the live role because it needs no key and sends CORS headers.

**Latest reading:** 17.1 °C, wind 3.25 m/s, measured at
Rotterdam Airport (06344), 8.0 km from the study area.

### Three operational traps

- The dataset most tutorials use, `Actueel10mindataKNMIstations` v2, **stopped
  updating on 2025-10-02**. Use `10-minute-in-situ-meteorological-observations` v1.0.
- The anonymous API key is shared globally, so **HTTP 429 is routine**. KNMI
  sends no `Retry-After`; the limit clears in 15–30 s. `fetch_knmi.py` backs off
  and retries. Register your own key at developer.dataplatform.knmi.nl if it bites.
- The climatology service answers **502/503/504 under load**. A request that
  completes in two seconds from one machine can time out from another; a
  teammate hit a 504 on exactly that. `fetch_knmi.py` retries with backoff,
  stops after two consecutive dead chunks rather than grinding through the rest,
  leaves existing good files untouched, and **exits 2** when the history is
  incomplete. Do not train on a partial record: `train_forecast.py` builds lag
  features assuming row *i−1* is one hour before row *i*.
- The climatology service **ignores the hour part of `start`/`end`** and returns
  the day *after* your end date. Yearly chunks therefore overlap by 24 hours.
  Left in, those duplicates break the assumption that row *i−1* is one hour
  before row *i*, which every lag feature depends on. `fetch_knmi.py`
  deduplicates; the series is now 43,848 rows with every gap exactly 1.0 h.

## AI prediction — method and results

Predicting **temperature** and **wind speed** at +1 h, +6 h and +24 h at KNMI
station 344 (Rotterdam Airport). The record is split by date into three periods:

| period | years | hours (at +24 h) | used for |
|---|---|---|---|
| train | 2021–2023 | 26,208 | fitting the models |
| validation | 2024 | 8,760 | choosing settings, when to stop the LSTM, and the best model |
| test | 2025 | 8,784 | the scores below; never used to choose anything |

The first 48 hours of 2021 are dropped because they have no full lag history.
An hour only counts in a period if the hour it predicts is in that period too,
so no target crosses from one period into the next.

### The models

Two baselines and two models, all given the same inputs. This follows the
course assignments: a tree model and an LSTM, each scored against persistence.

| model | what it is | tried on the validation year |
|---|---|---|
| persistence | the value h hours later equals the value now. The baseline every model must beat | — |
| daily naive | the value h hours later equals the value 24 h before that, i.e. same hour yesterday | — |
| gradient boosting | scikit-learn `HistGradientBoostingRegressor`, 300 trees | learning rate 0.03 or 0.1, tree depth 4 or unlimited |
| LSTM | PyTorch, 2 layers of 64 units, dropout 0.1. Reads the last 48 hours of the feature table as a sequence. SmoothL1 loss, Adam (1e-3), batches of 256, gradients clipped at 1.0 | early stopping: up to 30 epochs, stops after 3 without a better validation error and keeps the best epoch |

**Inputs, 47 features per hour.** Temperature, wind speed, humidity, pressure
and dew point, each now and 1, 2, 3, 6, 12, 24 and 48 hours ago (40). Wind
direction as sine and cosine (2), hour of day and day of year as sine and cosine
(4), and cloud cover (1). Circular quantities are encoded as sine and cosine so
that 23:00 sits next to 00:00 and 359° next to 1°.

**Target.** The same variable h hours ahead. One model is trained per variable
and horizon, so 2 × 3 fits of each.

**Score.** Mean absolute error on the test year, and skill against persistence,
`1 − MAE_model / MAE_persistence`. Positive skill means the model beats "nothing
changes". The **best model** at each horizon is the one with the lowest error
on the **validation** year, baselines included, and only then is it scored on
2025. Picking it by its test score would make the test year part of the
training.

**The split is chronological, never random.** Shuffling hours would put the hour
before and the hour after a test point into training, and every model would look
superb. This is the most common way a time-series result is quietly wrong.

### Temperature — test MAE (°C), lower is better

Bold is the model the validation year chose.

| horizon | persistence | daily naive | grad. boosting | LSTM |
|---|---|---|---|---|
| +1h | 0.704 | 2.252 | **0.523** | 0.536 |
| +6h | 2.830 | 2.251 | **1.314** | 1.364 |
| +24h | 2.249 | 2.249 | **2.001** | 2.116 |

### Wind speed — test MAE (m/s)

| horizon | persistence | daily naive | grad. boosting | LSTM |
|---|---|---|---|---|
| +1h | **0.531** | 1.854 | 0.565 | 0.566 |
| +6h | 1.444 | 1.852 | **1.126** | 1.158 |
| +24h | 1.847 | 1.847 | 1.642 | **1.615** |

### What the validation year chose

| forecast | boosting learning rate, depth | LSTM epochs kept |
|---|---|---|
| temperature +1h | 0.03, unlimited | 13 |
| temperature +6h | 0.03, unlimited | 3 |
| temperature +24h | 0.03, 4 | 1 |
| wind +1h | 0.03, unlimited | 4 |
| wind +6h | 0.03, unlimited | 2 |
| wind +24h | 0.03, 4 | 1 |

The slower boosting learning rate wins every time. Early stopping matters more: in five of the six forecasts the LSTM is at its
best after 1–4 epochs and only gets worse after that. The fixed 12 epochs of
the earlier run trained it past that point.

### What the numbers actually say

**1. The LSTM wins once, and only just.** For wind at +24 h it is ahead of
gradient boosting on both years, by 0.025 m/s on 2024 and 0.027 m/s on 2025
(1.615 against 1.642). Everywhere else gradient boosting is ahead of it. With ~26,000 training hours and strong lagged
features, gradient boosting is a hard baseline, and the LSTM also receives the
full 47-feature vector including all lags, which is redundant for a model that
already sees the sequence. Its fast early stop says the same: it learns what it
can in a few passes and then starts to overfit. A cleaner input and a search
over its size are the obvious next steps, and honest "further work".

**2. At +1 h nothing beats persistence for wind,** on the validation year or the
test year. Wind is so autocorrelated at one hour that "the same as now" is the
best available answer. A model that cannot beat that has learned nothing, which
is why `skill_vs_persistence` is reported for every model rather than a bare MAE.

**3. The validation year picked the test-year winner every time.** In all six
forecasts the model with the lowest 2024 error also has the lowest 2025 error.
At +24 h the two models are a few hundredths apart, so that agreement is partly
luck. What is robust is that both trained models beat both baselines at +6 h
and +24 h.

**4. The wind model systematically under-predicts strong winds** (gradient
boosting at +6 h).

| condition | MAE (m/s) | bias |
|---|---|---|
| calm (<3 m/s) | 0.933 | +0.097 |
| moderate (3-8 m/s) | 1.149 | +0.039 |
| strong (>=8 m/s) | 1.616 | -0.413 |

Error grows by 1.7× from calm to strong winds and the bias turns sharply
negative: the model shaves about 0.4 m/s off exactly the conditions that
matter for pedestrian wind comfort. **Anyone using these forecasts to drive
component 4.5 should know they are conservative in precisely the wrong
direction.**

**5. Temperature is hardest in calm conditions** (MAE 1.47 °C against
1.13 °C in strong wind), which is physically sensible: calm clear nights
produce radiative cooling and inversions an hourly model cannot resolve.

Accuracy is broken down by season too. It varies by about a fifth (temperature
+6 h: 1.22 °C in autumn to 1.47 °C in spring), so the model is not simply
exploiting the annual cycle.

## Limitations to state in the report

- **A small search.** Only the four boosting settings in the model table were
  tried, and the LSTM's size was not searched at all. A larger search might
  help the LSTM most.
- **One validation year.** Settings and the best model were chosen on 2024
  alone. At +24 h the models are so close that another year could pick a
  different one.
- The condition breakdowns (by season and by wind regime) are for the
  **gradient boosting model at +6 h**, the model the validation year chose at
  the middle horizon.
- The LSTM fills nothing in: the record has no missing values after the first
  48 hours are dropped, so every input window is complete.
- The station is **8.0 km** from the study area, at an airport. Wind over an
  open airfield is stronger and less obstructed than in a Rotterdam street. Do
  not feed these numbers into a pedestrian-level model without a roughness
  correction.
- The live panel is **model output, not measurement**. The two sit side by side
  in the dashboard and will not match exactly; that gap is worth a sentence.
- Forecasts are point predictions with no uncertainty band. Quantile regression
  or an ensemble would give one and would be more honest for decision-making.
