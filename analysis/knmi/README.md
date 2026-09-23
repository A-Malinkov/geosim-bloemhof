# analysis/knmi — weather dashboard and AI prediction

Component 4.4 · feeds `app/modules/knmi.js`

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

- [x] **4.4a real-time monitoring** — live self-refreshing panel (KNMI HARMONIE-AROME
      via Open-Meteo, in the browser) *and* real KNMI station sensor readings via Python
- [x] **4.4a aggregated history** — 2,090 daily records, 5 years, station 344
- [x] **4.4b AI prediction** — five models compared, accuracy reported

## Three data paths, and why there are three

| | Source | Where | What it is |
|---|---|---|---|
| Live, self-refreshing | Open-Meteo, `knmi_harmonie_arome_netherlands` | browser | KNMI's 2 km forecast **model**, updated hourly |
| Sensor readings | KNMI Open Data, 10-min in-situ observations | Python | what the **instruments measured** |
| History | KNMI climatology (hourly + daily) | Python | the training set and the dashboard chart |

The browser cannot call KNMI directly — the `Authorization` header triggers a CORS
preflight KNMI does not answer, and the observations are NetCDF. Open-Meteo fills
the live role because it needs no key and sends CORS headers.

**Current reading:** 17.8 °C, wind 3.05 m/s,
measured at Rotterdam Airport (06344), 8.0 km from the study area.

### Two operational traps

- The dataset most tutorials use, `Actueel10mindataKNMIstations` v2, **stopped
  updating on 2025-10-02**. Use `10-minute-in-situ-meteorological-observations` v1.0.
- The anonymous API key is shared globally, so **HTTP 429 is routine**. KNMI sends
  no `Retry-After`; the limit clears in 15–30 s. `fetch_knmi.py` backs off and
  retries. Register your own key at developer.dataplatform.knmi.nl if it bites.

## AI prediction — method and results

Predicting **temperature** and **wind speed** at +1 h, +6 h and +24 h, from
35,136 training hours (2021–2024), tested on
8,808 held-out hours (2025).

**The split is chronological, never random.** Shuffling hours would put the hour
before and the hour after a test point into training, and every model would look
superb. This is the most common way a time-series result is quietly wrong.

### Temperature — MAE (°C), lower is better

| horizon | persistence | daily naive | ridge | grad. boosting | LSTM |
|---|---|---|---|---|---|
| +1h | 0.703 | 2.249 | 0.556 | **0.517** | 0.531 |
| +6h | 2.824 | 2.248 | 1.628 | **1.278** | 1.502 |
| +24h | 2.246 | 2.246 | **2.009** | 2.037 | 2.486 |

### Wind speed — MAE (m/s)

| horizon | persistence | daily naive | ridge | grad. boosting | LSTM |
|---|---|---|---|---|---|
| +1h | **0.529** | 1.855 | 0.568 | 0.564 | 0.564 |
| +6h | 1.443 | 1.853 | 1.163 | **1.138** | 1.343 |
| +24h | 1.850 | 1.850 | **1.602** | 1.690 | 2.030 |

### What the numbers actually say

**1. The LSTM never wins.** It is competitive at +1 h and +6 h and clearly worse
at +24 h — where it does not even beat persistence. This is a real result, not a
failed experiment, and it is worth stating plainly in the report: with ~35,000
training hours and strong lagged features, gradient boosting is a very hard
baseline, and a 2-layer LSTM trained for 12 epochs does not clear it. It is also
under-tuned: it receives the full 47-feature vector including all lags, which is
redundant for a model that already sees the sequence. More epochs, a cleaner
input representation, and proper hyper-parameter search are the obvious next
steps, and honest "further work".

**2. At +1 h, nothing beats persistence for wind.** Wind is so autocorrelated at
one hour that "the same as now" is already the best available answer. A model
that cannot beat that has learned nothing, which is exactly why
`skill_vs_persistence` is reported for every model rather than a bare MAE.

**3. The wind model systematically under-predicts strong winds.**

| condition | MAE (m/s) | bias |
|---|---|---|
| calm (<3 m/s) | 0.929 | +0.061 |
| moderate (3-8 m/s) | 1.158 | +0.030 |
| strong (>=8 m/s) | 1.698 | -0.599 |

Error nearly doubles from calm to strong winds, and the bias turns sharply
negative: the model shaves about 0.6 m/s off exactly the conditions that matter
for pedestrian wind comfort. **Anyone using these forecasts to drive component
4.5 should know the predictions are conservative in precisely the wrong
direction.**

**4. Temperature is hardest in calm conditions** (MAE
1.42 °C vs
1.12 °C in strong wind),
which is physically sensible — calm clear nights produce strong radiative
cooling and inversions that an hourly model cannot resolve.

Accuracy is broken down by season too; it is stable (MAE 1.20–1.41 °C), so the
model is not simply exploiting the annual cycle.

## Limitations to state in the report

- The station is **8.0 km** from the study area, at an airport. Wind at an
  open airfield is systematically stronger and less obstructed than in a
  Rotterdam street. Do not feed these numbers into a pedestrian-level model
  without a roughness correction.
- The live panel is **model output, not measurement**. The two are shown side by
  side in the dashboard and will not match exactly; that gap is itself worth a
  sentence in the report.
- Forecasts are point predictions with no uncertainty band. Quantile regression
  or an ensemble would give one, and would be more honest for decision-making.
