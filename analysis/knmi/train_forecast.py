#!/usr/bin/env python3
"""
train_forecast.py — AI prediction of future weather at the study area.

Component 4.4b. Trains models to predict temperature and wind speed some hours
ahead from KNMI's own hourly station record, and reports how accurate they are.

WHAT IS PREDICTED, AND WHY THOSE TWO
------------------------------------
Temperature and wind speed, at +1 h, +6 h and +24 h. They are the two variables
the rest of this project actually consumes: wind drives the pedestrian comfort
work (4.5) and temperature drives the heat argument that Sky View Factor feeds.

MODELS COMPARED
---------------
    persistence        y(t+h) = y(t)                  the honest baseline
    daily naive        y(t+h) = y(t+h-24)             yesterday, same hour
    ridge              linear, on lagged features
    gradient boosting  HistGradientBoostingRegressor
    LSTM               2-layer recurrent net over the last 48 hours (PyTorch)

A model is only interesting if it beats persistence. Weather is highly
autocorrelated: at +1 h "same as now" is already excellent, and a model that
cannot beat it has learned nothing. Skill score = 1 - MAE_model / MAE_persistence
is reported for exactly that reason.

TRAIN, VALIDATION, TEST
-----------------------
The split is chronological, never random:

    train       2021-2023   the models learn from these hours
    validation  2024        settings and the best model are chosen here
    test        2025        scored once, at the end, and never used to choose

Shuffling hours would leak the answer: the hour before and the hour after a test
point would both be in training, and any model would look superb. An hour is
only used in a period if the hour it predicts lies in that period too, so no
target crosses a boundary.

On the validation year we choose: the ridge penalty, the gradient boosting
learning rate and tree depth, when the LSTM stops training (early stopping),
and which model is "best" at each horizon.

Accuracy is also broken down by season and by wind regime, because a mean error
over a whole year hides that every model struggles with storms.

LSTM IS OPTIONAL
----------------
PyTorch is ~780 MB, so it is not in the core requirements. Without it the script
runs everything else and says the LSTM was skipped. To include it:
    pip install --index-url https://download.pytorch.org/whl/cpu torch

USAGE
-----
    python analysis/knmi/fetch_knmi.py          # first, for the training data
    python analysis/knmi/train_forecast.py      # the published run, ~15 min with the LSTM
    python analysis/knmi/train_forecast.py --no-lstm

OUTPUT
------
    data/processed/knmi_forecast.json   metrics, breakdowns, predicted vs actual
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import PROCESSED, RAW, STUDY_AREA  # noqa: E402

TARGETS = {"temperature_C": "temperature (degC)",  #the two variables predicted, one model per variable and horizon
           "wind_speed_ms": "wind speed (m/s)"}
HORIZONS = [1, 6, 24]  #hours ahead
LAGS = [0, 1, 2, 3, 6, 12, 24, 48]  #hours back each input is also given at

VAL_START = np.datetime64("2024-01-01T00:00")  #first hour of the validation year
TEST_START = np.datetime64("2025-01-01T00:00")  #first hour of the test year

RIDGE_ALPHAS = [0.1, 1.0, 10.0, 100.0]  #ridge penalties tried on the validation year
BOOSTING_SETTINGS = [  #gradient boosting settings tried on the validation year
    {"learning_rate": 0.03, "max_depth": 4},
    {"learning_rate": 0.03, "max_depth": None},
    {"learning_rate": 0.1, "max_depth": 4},
    {"learning_rate": 0.1, "max_depth": None},
]

SEQ_LEN = 48  #hours of history the LSTM reads as one sequence
LSTM_HIDDEN = 64  #units in each of the two LSTM layers
LSTM_MAX_EPOCHS = 30  #upper limit; early stopping usually ends sooner
LSTM_PATIENCE = 3  #stop after this many epochs without a better validation error
BATCH_SIZE = 256


# ------------------------------------------------------------------- loading
#hourly station record written by fetch_knmi.py -> times and one array per variable
def load_hourly(station):
    path = RAW / f"knmi_hourly_{station}.json"
    if not path.exists():
        print(f"missing {path}\nRun: python analysis/knmi/fetch_knmi.py")
        sys.exit(1)
    rows = json.loads(path.read_text())["records"]
    rows.sort(key=lambda r: r["time"])  #chronological, so row i-1 is the hour before row i
    times = np.array([np.datetime64(r["time"]) for r in rows])

    cols = {}
    for key in ("temperature_C", "wind_speed_ms", "humidity_pct", "pressure_hPa",
                "dewpoint_C", "cloud_cover_octants", "wind_direction_deg"):
        cols[key] = np.array([np.nan if r.get(key) is None else float(r[key])
                              for r in rows])
    return times, cols


# ------------------------------------------------------------------ features
def build_features(times, cols):
    """47 columns: 5 variables at 8 lags, wind direction, time of day, season, cloud."""
    features = {}

    #each core variable now and at every lag in LAGS
    for key in ("temperature_C", "wind_speed_ms", "humidity_pct",
                "pressure_hPa", "dewpoint_C"):
        values = cols[key]
        for lag in LAGS:
            shifted = np.full(len(values), np.nan)  #the first `lag` hours have no value that far back
            shifted[lag:] = values[:len(values) - lag]
            features[f"{key}_lag{lag}"] = shifted

    #circular quantities as sine and cosine, so 359 deg sits next to 1 deg and 23:00 next to 00:00
    direction = np.radians(cols["wind_direction_deg"])
    features["wind_dir_sin"] = np.sin(direction)
    features["wind_dir_cos"] = np.cos(direction)

    hour_of_day = times.astype("datetime64[h]").astype(int) % 24
    features["hod_sin"] = np.sin(2 * np.pi * hour_of_day / 24)
    features["hod_cos"] = np.cos(2 * np.pi * hour_of_day / 24)

    #real day of year, so 1 January is day 0 in every year, leap years included
    day = times.astype("datetime64[D]")
    year_start = times.astype("datetime64[Y]").astype("datetime64[D]")
    day_of_year = (day - year_start).astype(int)
    features["doy_sin"] = np.sin(2 * np.pi * day_of_year / 365)
    features["doy_cos"] = np.cos(2 * np.pi * day_of_year / 365)

    features["cloud"] = cols["cloud_cover_octants"]

    names = list(features)
    X = np.column_stack([features[name] for name in names])
    return X, names


def shift_ahead(values, h):
    """The value h hours later, NaN where the record ends."""
    ahead = np.full(len(values), np.nan)
    ahead[:len(values) - h] = values[h:]
    return ahead


def split_rows(times, h):
    """Which rows are train, validation and test, for a forecast h hours ahead."""
    target_time = times + np.timedelta64(h, "h")  #the hour each row's forecast is about
    train = target_time < VAL_START
    val = (times >= VAL_START) & (target_time < TEST_START)
    test = times >= TEST_START
    return train, val, test


# ------------------------------------------------------------------- scoring
def mae(y_true, y_pred):
    """Mean absolute error over the hours where both values exist."""
    ok = np.isfinite(y_true) & np.isfinite(y_pred)
    return float(np.mean(np.abs(y_pred[ok] - y_true[ok])))


def metrics(y_true, y_pred):
    """MAE, RMSE, bias and R2 over the hours where both values exist."""
    ok = np.isfinite(y_true) & np.isfinite(y_pred)
    if ok.sum() < 2:
        return {}
    yt, yp = y_true[ok], y_pred[ok]
    err = yp - yt
    ss_res = np.sum(err ** 2)
    ss_tot = np.sum((yt - yt.mean()) ** 2)
    return {"n": int(ok.sum()),
            "mae": round(float(np.mean(np.abs(err))), 4),
            "rmse": round(float(np.sqrt(np.mean(err ** 2))), 4),
            "bias": round(float(np.mean(err)), 4),
            "r2": round(float(1 - ss_res / ss_tot), 4) if ss_tot > 0 else None}


# -------------------------------------------------------- ridge and boosting
def fit_ridge(X, y, train, val):
    """Try each ridge penalty, keep the one with the lowest validation MAE."""
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    best = None
    for alpha in RIDGE_ALPHAS:
        model = make_pipeline(StandardScaler(), Ridge(alpha=alpha))  #features standardised on the training rows
        model.fit(X[train], y[train])
        val_mae = mae(y[val], model.predict(X[val]))
        print(f"        ridge alpha {alpha:<5}  validation MAE {val_mae:.3f}")
        if best is None or val_mae < best["val_mae"]:
            best = {"model": model, "val_mae": val_mae, "settings": {"alpha": alpha}}
    return best


def fit_boosting(X, y, train, val):
    """Try each gradient boosting setting, keep the one with the lowest validation MAE."""
    from sklearn.ensemble import HistGradientBoostingRegressor

    best = None
    for settings in BOOSTING_SETTINGS:
        model = HistGradientBoostingRegressor(max_iter=300, random_state=0, **settings)
        model.fit(X[train], y[train])
        val_mae = mae(y[val], model.predict(X[val]))
        print(f"        boosting {settings}  validation MAE {val_mae:.3f}")
        if best is None or val_mae < best["val_mae"]:
            best = {"model": model, "val_mae": val_mae, "settings": settings}
    return best


# ---------------------------------------------------------------------- LSTM
def train_lstm(X, y, train, val, seed=0):
    """
    Two-layer LSTM over the last SEQ_LEN hours of the feature table.

    Trains on the training rows and stops when the validation error has not
    improved for LSTM_PATIENCE epochs, keeping the best epoch's weights.
    Returns a prediction for every row (NaN where there is no full window
    behind it) and the number of the epoch kept, or None and a reason.
    """
    try:
        import torch
        import torch.nn as nn
    except ImportError:
        return None, "PyTorch not installed"

    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)

    #standardise features and target with the training rows only, so nothing leaks from later years
    mean, std = X[train].mean(axis=0), X[train].std(axis=0)
    std[std == 0] = 1.0
    X_scaled = ((X - mean) / std).astype("float32")
    y_mean, y_std = y[train].mean(), y[train].std()

    #the input for row i is the SEQ_LEN hours ending at row i
    def windows(rows):
        return torch.tensor(np.stack([X_scaled[i - SEQ_LEN + 1:i + 1] for i in rows]))

    #two stacked LSTM layers, then a linear layer on the last time step
    class Net(nn.Module):
        def __init__(self, n_features):
            super().__init__()
            self.lstm = nn.LSTM(n_features, LSTM_HIDDEN, num_layers=2,
                                batch_first=True, dropout=0.1)
            self.head = nn.Linear(LSTM_HIDDEN, 1)

        def forward(self, x):
            out, _ = self.lstm(x)
            return self.head(out[:, -1, :]).squeeze(-1)

    #forecasts in the original units, in batches so memory stays small
    def predict(rows):
        net.eval()
        out = []
        with torch.no_grad():
            for start in range(0, len(rows), 1024):
                out.append(net(windows(rows[start:start + 1024])).numpy())
        return np.concatenate(out) * y_std + y_mean

    has_window = np.arange(len(X)) >= SEQ_LEN - 1  #the first rows have too little history
    train_rows = np.where(train & has_window)[0]
    val_rows = np.where(val)[0]

    net = Net(X.shape[1])
    optimizer = torch.optim.Adam(net.parameters(), lr=1e-3)  #Adam, fixed learning rate
    loss_fn = nn.SmoothL1Loss()  #less sensitive to storm outliers than squared error

    best_val, best_weights, best_epoch = np.inf, None, 0
    for epoch in range(1, LSTM_MAX_EPOCHS + 1):
        #one pass over the training windows, in random order
        net.train()
        rng.shuffle(train_rows)
        for start in range(0, len(train_rows), BATCH_SIZE):
            batch = train_rows[start:start + BATCH_SIZE]
            target = torch.tensor(((y[batch] - y_mean) / y_std).astype("float32"))
            optimizer.zero_grad()
            loss = loss_fn(net(windows(batch)), target)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)  #avoid sudden huge updates
            optimizer.step()

        #early stopping on the validation year
        val_mae = mae(y[val_rows], predict(val_rows))
        print(f"        LSTM epoch {epoch:2}  validation MAE {val_mae:.3f}")
        if val_mae < best_val:
            best_val, best_weights, best_epoch = val_mae, copy.deepcopy(net.state_dict()), epoch
        elif epoch - best_epoch >= LSTM_PATIENCE:
            break

    net.load_state_dict(best_weights)  #back to the best epoch
    pred = np.full(len(X), np.nan)
    rows = np.where(has_window)[0]
    pred[rows] = predict(rows)
    return pred, {"val_mae": best_val, "settings": {"epochs": best_epoch}}


# ---------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--station", type=int, default=STUDY_AREA.knmi_station)
    ap.add_argument("--no-lstm", action="store_true", help="skip the LSTM (no PyTorch needed)")
    args = ap.parse_args()

    print(f"Weather prediction — KNMI station {args.station}, {STUDY_AREA.name}")
    times, cols = load_hourly(args.station)
    X, feature_names = build_features(times, cols)  #same 47 inputs for every model

    #drop the first 48 hours: they have no full lag history
    times, X = times[max(LAGS):], X[max(LAGS):]
    cols = {key: values[max(LAGS):] for key, values in cols.items()}
    print(f"  {len(times):,} hourly records, {X.shape[1]} features, "
          f"{str(times[0])[:10]} to {str(times[-1])[:10]}")

    season_of_month = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring",
                       5: "spring", 6: "summer", 7: "summer", 8: "summer",
                       9: "autumn", 10: "autumn", 11: "autumn"}
    month = times.astype("datetime64[M]").astype(int) % 12 + 1
    season = np.array([season_of_month[m] for m in month])

    results = {}
    demo = None
    hours = {}  #rows per period, reported in the output

    #one fit per variable and horizon
    for target, label in TARGETS.items():
        now = cols[target]
        results[target] = {"label": label, "horizons": {}}
        print(f"\n  ==== {label} ====")

        for h in HORIZONS:
            print(f"     +{h} h:")
            y = shift_ahead(now, h)  #what we want to predict: the value h hours later
            train, val, test = split_rows(times, h)
            hours = {"train": int(train.sum()), "val": int(val.sum()), "test": int(test.sum())}

            #every model gives a forecast for every row; `chosen` holds what the validation year picked
            preds, chosen = {}, {}

            preds["persistence"] = now  #the value now, used as the forecast
            daily = np.full(len(now), np.nan)  #the value at the same hour yesterday: y(t+h-24)
            daily[24 - h:] = now[:len(now) - (24 - h)]
            preds["daily_naive"] = daily

            ridge = fit_ridge(X, y, train, val)
            preds["ridge"] = ridge["model"].predict(X)
            chosen["ridge"] = ridge

            boosting = fit_boosting(X, y, train, val)
            preds["gradient_boosting"] = boosting["model"].predict(X)
            chosen["gradient_boosting"] = boosting

            if not args.no_lstm:
                lstm_pred, lstm_info = train_lstm(X, y, train, val)
                if lstm_pred is None:
                    print(f"        LSTM skipped — {lstm_info}")
                else:
                    preds["lstm"] = lstm_pred
                    chosen["lstm"] = lstm_info

            #score every model on the test year, and record its validation error
            persistence_mae = metrics(y[test], preds["persistence"][test])["mae"]
            scores = {}
            for name, p in preds.items():
                m = metrics(y[test], p[test])
                m["skill_vs_persistence"] = round(1 - m["mae"] / persistence_mae, 4)
                m["val_mae"] = round(mae(y[val], p[val]), 4)
                if name in chosen:
                    m["settings"] = chosen[name]["settings"]
                scores[name] = m

            #the best model is the one with the lowest VALIDATION error, never the test error
            best = min(scores, key=lambda name: scores[name]["val_mae"])
            scores["_best"] = best
            results[target]["horizons"][f"+{h}h"] = scores
            print(f"     +{h:2d} h test MAE  " + "  ".join(
                f"{name}={scores[name]['mae']:.3f}" for name in preds))
            print(f"            best on validation: {best} "
                  f"(test MAE {scores[best]['mae']:.3f}, skill "
                  f"{scores[best]['skill_vs_persistence']:+.3f})")

            #breakdowns by season and wind regime, for the best model at +6 h
            if h != 6:
                continue
            p, yt = preds[best][test], y[test]
            by_season = {s: metrics(yt[season[test] == s], p[season[test] == s])
                         for s in ("winter", "spring", "summer", "autumn")}
            wind = cols["wind_speed_ms"][test]  #wind when the forecast is made, not at the target time
            by_wind = {"calm (<3 m/s)": metrics(yt[wind < 3], p[wind < 3]),
                       "moderate (3-8 m/s)": metrics(yt[(wind >= 3) & (wind < 8)],
                                                     p[(wind >= 3) & (wind < 8)]),
                       "strong (>=8 m/s)": metrics(yt[wind >= 8], p[wind >= 8])}
            results[target]["conditions"] = {"model": best, "horizon": f"+{h}h",
                                             "by_season": by_season, "by_wind_regime": by_wind}

            #the first fortnight of the test year for the app's chart, temperature only
            if target == "temperature_C":
                k = 24 * 14
                #label each point with the time it is ABOUT (t + h), not when the forecast was made
                t_about = times[test][:k] + np.timedelta64(h, "h")
                demo = {"variable": target, "model": best, "horizon": f"+{h}h",
                        "time_is": "the time each value refers to (t+h), not the "
                                   "time the forecast was issued",
                        "time": [str(t)[:16] for t in t_about],
                        "actual": [round(float(v), 2) for v in yt[:k]],
                        "predicted": [round(float(v), 2) for v in p[:k]]}

    #the dashboard's headline: temperature at the longest horizon
    headline = f"+{HORIZONS[-1]}h"
    headline_best = results["temperature_C"]["horizons"][headline]["_best"]
    b = results["temperature_C"]["horizons"][headline][headline_best]

    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "station": args.station,
        "source": f"KNMI hourly climatology, station {args.station}",
        "model": headline_best,
        "horizon": headline,
        "method": {
            "split": "chronological — never random; train 2021-2023, validation 2024, "
                     "test 2025. An hour is used in a period only if the hour it "
                     "predicts is in that period too",
            "train_hours": hours["train"],  #at +24 h; shorter horizons have a few more
            "val_hours": hours["val"],
            "test_hours": hours["test"],
            "tuning": f"on the validation year: ridge alpha from {RIDGE_ALPHAS}, gradient "
                      f"boosting from {BOOSTING_SETTINGS} (300 trees), LSTM early stopping "
                      f"(patience {LSTM_PATIENCE}, at most {LSTM_MAX_EPOCHS} epochs), and "
                      f"the best model per horizon by validation MAE",
            "features": f"{X.shape[1]} — lags {LAGS} of temperature, wind, "
                        f"humidity, pressure and dew point, plus cyclical "
                        f"hour-of-day, day-of-year and wind-direction encodings, "
                        f"and cloud cover",
            "lstm": {"seq_len": SEQ_LEN, "hidden": LSTM_HIDDEN, "layers": 2,
                     "max_epochs": LSTM_MAX_EPOCHS, "patience": LSTM_PATIENCE,
                     "loss": "SmoothL1"},
            "note": "skill_vs_persistence = 1 - MAE_model/MAE_persistence. "
                    "Positive means better than assuming nothing changes.",
        },
        "results": results,
        "demo_series": demo,
        #a flat metrics block for the dashboard
        "metrics": {"mae": b["mae"], "rmse": b["rmse"], "r2": b["r2"],
                    "variable": TARGETS["temperature_C"], "horizon": headline,
                    "model": headline_best},
    }

    (PROCESSED / "knmi_forecast.json").write_text(json.dumps(out, indent=2) + "\n")
    print("\n  wrote data/processed/knmi_forecast.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
