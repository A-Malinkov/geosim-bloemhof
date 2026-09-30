# analysis/knmi — weather dashboard and AI prediction

Component 4.4 · feeds `app/modules/knmi.js`

> Numbers here are generated from `data/processed/knmi_forecast.json`. If you
> retrain, regenerate this file — they go stale silently otherwise.

## Scripts

| Script | What it does | Writes |
|---|---|---|
| `fetch_knmi.py` | latest 10-minute sensor observation, plus hourly and daily history | `data/processed/knmi_current.json`, `knmi_daily_history.json`, `data/raw/knmi_hourly_344.json` |
| `train_forecast.py` | trains and compares forecast models, reports accuracy | `data/processed/knmi_forecast.json` |

```bash
python analysis/knmi/fetch_knmi.py        # ~2 min for 5 years of history
python analysis/knmi/train_forecast.py    # ~6 min with the LSTM
```

## Status

- [x] **4.4a real-time monitoring** — live self-refreshing panel (KNMI
      HARMONIE-AROME via Open-Meteo, in the browser) *and* real KNMI station
      sensor readings via Python
- [x] **4.4a aggregated history** — 2,090 daily records, 5 years, station 344
- [x] **4.4b AI prediction** — five models compared, accuracy reported

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

Predicting **temperature** and **wind speed** at +1 h, +6 h and +24 h, from
35,064 training hours, tested on 8,784 held-out hours.

**The split is chronological, never random.** Shuffling hours would put the hour
before and the hour after a test point into training, and every model would look
superb. This is the most common way a time-series result is quietly wrong.

### Temperature — MAE (°C), lower is better

| horizon | persistence | daily naive | ridge | grad. boosting | LSTM |
|---|---|---|---|---|---|
| +1h | 0.704 | 2.252 | 0.557 | **0.520** | 0.528 |
| +6h | 2.830 | 2.251 | 1.631 | **1.293** | 1.461 |
| +24h | 2.249 | 2.249 | **2.010** | 2.074 | 2.530 |

### Wind speed — MAE (m/s)

| horizon | persistence | daily naive | ridge | grad. boosting | LSTM |
|---|---|---|---|---|---|
| +1h | **0.531** | 1.854 | 0.568 | 0.564 | 0.560 |
| +6h | 1.444 | 1.852 | 1.161 | **1.125** | 1.290 |
| +24h | 1.847 | 1.847 | **1.598** | 1.661 | 2.044 |

### What the numbers actually say

**1. The LSTM never wins.** Competitive at +1 h and +6 h, and at +24 h it does
not even beat persistence. A real result, not a failed experiment: with ~35,000
training hours and strong lagged features, gradient boosting is a hard baseline,
and a 2-layer LSTM at 12 epochs does not clear it. It is also under-tuned — it
receives the full 47-feature vector including all lags, which is redundant for a
model that already sees the sequence. More epochs, a cleaner input
representation and a hyper-parameter search are the obvious next steps, and
honest "further work".

**2. At +1 h nothing beats persistence for wind.** Wind is so autocorrelated at
one hour that "the same as now" is the best available answer. A model that
cannot beat that has learned nothing — which is why `skill_vs_persistence` is
reported for every model rather than a bare MAE.

**3. The wind model systematically under-predicts strong winds.**

| condition | MAE (m/s) | bias |
|---|---|---|
| calm (<3 m/s) | 0.920 | +0.084 |
| moderate (3-8 m/s) | 1.150 | +0.032 |
| strong (>=8 m/s) | 1.651 | -0.527 |

Error grows by 1.8× from calm to strong winds and the bias turns sharply
negative: the model shaves about 0.5 m/s off exactly the conditions that
matter for pedestrian wind comfort. **Anyone using these forecasts to drive
component 4.5 should know they are conservative in precisely the wrong
direction.**

**4. Temperature is hardest in calm conditions** (MAE 1.45 °C against
1.13 °C in strong wind), which is physically sensible — calm clear nights
produce radiative cooling and inversions an hourly model cannot resolve.

Accuracy is broken down by season too, and is stable, so the model is not simply
exploiting the annual cycle.

## Limitations to state in the report

- The station is **8.0 km** from the study area, at an airport. Wind over an
  open airfield is stronger and less obstructed than in a Rotterdam street. Do
  not feed these numbers into a pedestrian-level model without a roughness
  correction.
- The live panel is **model output, not measurement**. The two sit side by side
  in the dashboard and will not match exactly; that gap is worth a sentence.
- Forecasts are point predictions with no uncertainty band. Quantile regression
  or an ensemble would give one and would be more honest for decision-making.
