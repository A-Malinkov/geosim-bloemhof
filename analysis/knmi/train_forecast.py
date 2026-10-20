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

VALIDATION
----------
Chronological split, never random. Training 2021-2024, testing on the most
recent full year. Shuffling hours would leak the answer: the hour before and
the hour after a test point would both be in training, and any model would look
superb. This is the single most common way a time-series result is wrong.

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
    python analysis/knmi/train_forecast.py --epochs 12   # the published run
    python analysis/knmi/train_forecast.py --horizons 1 3 6 12 24 --epochs 30

OUTPUT
------
    data/processed/knmi_forecast.json   metrics, breakdowns, predicted vs actual
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import PROCESSED, RAW, STUDY_AREA  # noqa: E402

TARGETS = {"temperature_C": "temperature (degC)",  #the two variables predicted, one model per variable and horizon
           "wind_speed_ms": "wind speed (m/s)"}
LAGS = [0, 1, 2, 3, 6, 12, 24, 48]  #hours back each input is also given at
SEQ_LEN = 48  #hours of history the LSTM reads as one sequence


# ------------------------------------------------------------------- loading
#hourly station record written by fetch_knmi.py -> times and one array per variable
def load_hourly(station: int):
    path = RAW / f"knmi_hourly_{station}.json"
    if not path.exists():
        print(f"missing {path}\nRun: python analysis/knmi/fetch_knmi.py")
        sys.exit(1)
    rows = json.loads(path.read_text())["records"]
    rows.sort(key=lambda r: r["time"])  #chronological, so row i-1 is the hour before row i
    times = np.array([np.datetime64(r["time"]) for r in rows])

    cols = {}
    for key in ("temperature_C", "wind_speed_ms", "wind_gust_ms", "humidity_pct",
                "pressure_hPa", "dewpoint_C", "cloud_cover_octants",
                "wind_direction_deg", "global_radiation_Jcm2"):
        cols[key] = np.array([np.nan if r.get(key) is None else float(r[key])
                              for r in rows], dtype="float64")
    return times, cols


def build_features(times, cols):
    """Lagged values plus cyclical time and wind-direction encodings."""
    #47 columns: 5 variables x 8 lags, wind direction, time of day, season, cloud
    n = len(times)
    hours = times.astype("datetime64[h]").astype(int)
    hod = (hours % 24).astype("float64")
    # Real day-of-year, not days-since-epoch % 365: the latter drifts a day
    # every leap year, so 1 January maps to 13 in 2021 but 14 in 2025 and the
    # seasonal feature slowly desynchronises from the actual season.
    days = times.astype("datetime64[D]")
    year_start = times.astype("datetime64[Y]").astype("datetime64[D]")
    doy = (days - year_start).astype("timedelta64[D]").astype("float64")

    feats, names = [], []
    #each core variable now and at every lag in LAGS
    for key in ("temperature_C", "wind_speed_ms", "humidity_pct",
                "pressure_hPa", "dewpoint_C"):
        v = cols[key]
        for lag in LAGS:
            shifted = np.full(n, np.nan)
            if lag == 0:
                shifted = v.copy()
            else:
                shifted[lag:] = v[:-lag]  #value `lag` hours earlier; the first `lag` rows stay NaN
            feats.append(shifted)
            names.append(f"{key}_lag{lag}")

    # wind direction is circular: 359 deg and 1 deg are adjacent
    wd = np.radians(cols["wind_direction_deg"])
    feats += [np.sin(wd), np.cos(wd)]
    names += ["wind_dir_sin", "wind_dir_cos"]
    # so are hour-of-day and day-of-year
    feats += [np.sin(2 * np.pi * hod / 24), np.cos(2 * np.pi * hod / 24),
              np.sin(2 * np.pi * doy / 365), np.cos(2 * np.pi * doy / 365)]
    names += ["hod_sin", "hod_cos", "doy_sin", "doy_cos"]
    feats.append(cols["cloud_cover_octants"])
    names.append("cloud")
    return np.column_stack(feats), names


#MAE, RMSE, bias and R2 over the hours where both values exist
def metrics(y_true, y_pred):
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    if m.sum() < 2:
        return {}
    yt, yp = y_true[m], y_pred[m]
    err = yp - yt
    ss_res = float(np.sum(err ** 2))
    ss_tot = float(np.sum((yt - yt.mean()) ** 2))
    return {"n": int(m.sum()),
            "mae": round(float(np.mean(np.abs(err))), 4),
            "rmse": round(float(np.sqrt(np.mean(err ** 2))), 4),
            "bias": round(float(np.mean(err)), 4),
            "r2": round(1 - ss_res / ss_tot, 4) if ss_tot > 0 else None}


# ---------------------------------------------------------------------- LSTM
def train_lstm(Xtr, ytr, Xte, seq_len, epochs, hidden=64, seed=0):
    """
    Two-layer LSTM over the last `seq_len` hours of the feature matrix.

    Returns test predictions, or None if PyTorch is not installed.
    """
    try:
        import torch
        import torch.nn as nn
    except ImportError:
        return None, "PyTorch not installed"

    torch.manual_seed(seed)
    np.random.seed(seed)

    #every run of seq_len consecutive hours, as one training sample
    def windows(X):
        n, f = X.shape
        idx = np.arange(seq_len)[None, :] + np.arange(n - seq_len + 1)[:, None]
        return X[idx]                       # (samples, seq_len, features)

    mu, sd = np.nanmean(Xtr, axis=0), np.nanstd(Xtr, axis=0)  #scaling from the training period only
    sd[sd == 0] = 1.0
    norm = lambda X: np.nan_to_num((X - mu) / sd, nan=0.0)  #standardise; missing values become the training mean (0)

    Wtr, Wte = windows(norm(Xtr)), windows(norm(Xte))
    ytr_w = ytr[seq_len - 1:]  #target of each window is the one for its last hour
    ok = np.isfinite(ytr_w)
    Wtr, ytr_w = Wtr[ok], ytr_w[ok]
    if len(Wtr) < 500:
        return None, "not enough training windows"

    ym, ys = float(np.mean(ytr_w)), float(np.std(ytr_w) or 1.0)  #the target is standardised too

    #two stacked LSTM layers, then a linear layer on the last time step
    class Net(nn.Module):
        def __init__(self, f):
            super().__init__()
            self.lstm = nn.LSTM(f, hidden, num_layers=2, batch_first=True,
                                dropout=0.1)
            self.head = nn.Linear(hidden, 1)

        def forward(self, x):
            out, _ = self.lstm(x)
            return self.head(out[:, -1, :]).squeeze(-1)

    dev = torch.device("cpu")
    net = Net(Wtr.shape[2]).to(dev)
    opt = torch.optim.Adam(net.parameters(), lr=1e-3)  #Adam, fixed learning rate, not tuned
    lossf = nn.SmoothL1Loss()                # robust to storm outliers

    Xt = torch.tensor(Wtr, dtype=torch.float32)
    yt = torch.tensor((ytr_w - ym) / ys, dtype=torch.float32)
    ds = torch.utils.data.TensorDataset(Xt, yt)
    dl = torch.utils.data.DataLoader(ds, batch_size=256, shuffle=True)  #windows shuffled within the training period only

    net.train()
    for ep in range(epochs):
        tot = 0.0
        for xb, yb in dl:
            opt.zero_grad()
            loss = lossf(net(xb), yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step()
            tot += loss.item() * len(xb)
        if ep % 5 == 0 or ep == epochs - 1:
            print(f"        epoch {ep + 1:3}/{epochs}  loss {tot / len(ds):.4f}")

    #predict the test period, back on the original scale
    net.eval()
    with torch.no_grad():
        pred = net(torch.tensor(Wte, dtype=torch.float32)).numpy() * ys + ym
    full = np.full(len(Xte), np.nan)
    full[seq_len - 1:] = pred  #the first seq_len-1 test hours have no full window and stay NaN
    return full, None


# ---------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--station", type=int, default=STUDY_AREA.knmi_station)
    ap.add_argument("--horizons", type=int, nargs="+", default=[1, 6, 24])
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--no-lstm", action="store_true")
    args = ap.parse_args()

    #scikit-learn models, imported here so --help stays fast
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler

    print(f"Weather prediction — KNMI station {args.station}, {STUDY_AREA.name}")
    times, cols = load_hourly(args.station)
    X, feat_names = build_features(times, cols)  #same 47 inputs for every model
    print(f"  {len(times):,} hourly records, {X.shape[1]} features")
    print(f"  {str(times[0])[:10]} to {str(times[-1])[:10]}")

    # Chronological split: hold out the FINAL 12 MONTHS of whatever range we
    # actually have. Deriving the year from the last timestamp is a trap — the
    # record ends at 2026-01-01T00:00, so "the last year present" is 2026 and
    # the test set collapses to 24 hours.
    cutoff = times[-1].astype("datetime64[D]") - np.timedelta64(365, "D")
    split = int(np.searchsorted(times, cutoff))
    if not (0.3 * len(times) < split < 0.95 * len(times)):
        split = int(len(times) * 0.8)       # fall back to 80/20
    print(f"  train {str(times[0])[:10]}..{str(times[split-1])[:10]} "
          f"({split:,} h)  |  test {str(times[split])[:10]}..{str(times[-1])[:10]} "
          f"({len(times)-split:,} h)")

    months = times.astype("datetime64[M]").astype(int) % 12 + 1
    season_of = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring",
                 5: "spring", 6: "summer", 7: "summer", 8: "summer",
                 9: "autumn", 10: "autumn", 11: "autumn"}

    results = {}
    demo = None

    #one fit per variable and horizon
    for target, label in TARGETS.items():
        y_all = cols[target]
        results[target] = {"label": label, "horizons": {}}
        print(f"\n  ==== {label} ====")

        for h in args.horizons:
            y = np.full(len(y_all), np.nan)
            y[:-h] = y_all[h:]                       # value h hours later

            Xtr, ytr = X[:split], y[:split]
            Xte, yte = X[split:], y[split:]
            tr_ok = np.isfinite(ytr)  #drop training hours whose target is missing

            preds = {}
            # baselines
            preds["persistence"] = y_all[split:]  #the value now, used as the forecast
            # "same hour yesterday": the target at t+h is predicted by y(t+h-24)
            src_idx = np.arange(len(y_all)) + h - 24
            naive = np.full(len(y_all), np.nan)
            ok_idx = (src_idx >= 0) & (src_idx < len(y_all))
            naive[ok_idx] = y_all[src_idx[ok_idx]]
            preds["daily_naive"] = naive[split:]

            #linear model: fill gaps with the training median, standardise, L2 penalty 1.0
            ridge = make_pipeline(SimpleImputer(strategy="median"),
                                  StandardScaler(), Ridge(alpha=1.0))
            ridge.fit(Xtr[tr_ok], ytr[tr_ok])
            preds["ridge"] = ridge.predict(Xte)

            #300 boosted trees, settings chosen once and not searched
            gb = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.08,
                                               max_depth=None, random_state=0)
            gb.fit(Xtr[tr_ok], ytr[tr_ok])
            preds["gradient_boosting"] = gb.predict(Xte)

            if not args.no_lstm:
                print(f"     LSTM, +{h} h:")
                lstm_pred, why = train_lstm(Xtr, ytr, Xte, SEQ_LEN, args.epochs)
                if lstm_pred is not None:
                    preds["lstm"] = lstm_pred
                else:
                    print(f"        skipped — {why}")

            base_mae = metrics(yte, preds["persistence"]).get("mae")  #the score every model is measured against
            hz = {}
            for name, p in preds.items():
                m = metrics(yte, p)
                if not m:
                    continue                 # a baseline with no overlap is dropped
                if base_mae:
                    m["skill_vs_persistence"] = round(1 - m["mae"] / base_mae, 4)
                hz[name] = m
            if not hz:
                print(f"     +{h} h: no model produced comparable predictions")
                continue

            best = min(hz, key=lambda k: hz[k]["mae"])  #best by test MAE, baselines included
            hz["_best"] = best
            results[target]["horizons"][f"+{h}h"] = hz

            print(f"     +{h:2d} h  " + "  ".join(
                f"{k}={hz[k]['mae']:.3f}" for k in
                ("persistence", "ridge", "gradient_boosting", "lstm") if k in hz))
            print(f"            best: {best} "
                  f"(MAE {hz[best]['mae']:.3f}, skill "
                  f"{hz[best].get('skill_vs_persistence', 0):+.3f})")

            # conditions breakdown, on the best model at the middle horizon
            if h == args.horizons[len(args.horizons) // 2]:
                bp = preds[best]
                cond = {"by_season": {}, "by_wind_regime": {}}
                s_te = np.array([season_of[m] for m in months[split:]])
                for s in ("winter", "spring", "summer", "autumn"):
                    sel = s_te == s
                    if sel.sum() > 24:
                        cond["by_season"][s] = metrics(yte[sel], bp[sel])
                w = cols["wind_speed_ms"][split:]  #wind at the time the forecast is issued, not at the target time
                for lab, sel in (("calm (<3 m/s)", w < 3),
                                 ("moderate (3-8 m/s)", (w >= 3) & (w < 8)),
                                 ("strong (>=8 m/s)", w >= 8)):
                    if np.nansum(sel) > 24:
                        cond["by_wind_regime"][lab] = metrics(yte[sel], bp[sel])
                results[target]["conditions"] = {"model": best, "horizon": f"+{h}h",
                                                 **cond}

                if target == "temperature_C" and demo is None:
                    k = 24 * 14                      # a fortnight for the chart
                    # Label each point with the time it is ABOUT (t + h), not
                    # the time the forecast was issued from. Plotting a +6 h
                    # value against t shifts the whole series six hours left.
                    t_demo = (times[split:] + np.timedelta64(h, "h"))[:k]
                    demo = {
                        "variable": target, "model": best, "horizon": f"+{h}h",
                        "time_is": "the time each value refers to (t+h), not the "
                                   "time the forecast was issued",
                        "time": [str(t)[:16] for t in t_demo],
                        "actual": [None if not np.isfinite(v) else round(float(v), 2)
                                   for v in yte[:k]],
                        "predicted": [None if not np.isfinite(v) else round(float(v), 2)
                                      for v in bp[:k]],
                    }

    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "station": args.station,
        "source": "KNMI hourly climatology, station 344",
        "model": results["temperature_C"]["horizons"][
            f"+{args.horizons[-1]}h"]["_best"],
        "horizon": f"+{max(args.horizons)}h",
        "method": {
            "split": "chronological — never random; shuffling hours leaks the "
                     "answer because neighbouring hours would straddle the split",
            "train_hours": int(split),
            "test_hours": int(len(times) - split),
            "features": f"{X.shape[1]} — lags {LAGS} of temperature, wind, "
                        f"humidity, pressure and dew point, plus cyclical "
                        f"hour-of-day, day-of-year and wind-direction encodings, "
                        f"and cloud cover",  #cloud cover was missing from this description
            "lstm": {"seq_len": SEQ_LEN, "hidden": 64, "layers": 2,
                     "epochs": args.epochs, "loss": "SmoothL1"},
            "note": "skill_vs_persistence = 1 - MAE_model/MAE_persistence. "
                    "Positive means better than assuming nothing changes.",
        },
        "results": results,
        "demo_series": demo,
    }
    # a flat metrics block for the dashboard
    t0 = "temperature_C"
    h0 = f"+{args.horizons[-1]}h"
    b = results[t0]["horizons"][h0][results[t0]["horizons"][h0]["_best"]]
    out["metrics"] = {"mae": b["mae"], "rmse": b["rmse"], "r2": b["r2"],
                      "variable": TARGETS[t0], "horizon": h0,
                      "model": results[t0]["horizons"][h0]["_best"]}

    (PROCESSED / "knmi_forecast.json").write_text(json.dumps(out, indent=2) + "\n")
    print("\n  wrote data/processed/knmi_forecast.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
