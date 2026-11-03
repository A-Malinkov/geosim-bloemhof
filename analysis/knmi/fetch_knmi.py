#!/usr/bin/env python3
"""
fetch_knmi.py - KNMI station observations and history for the study area.

Component 4.4a, what KNMI's instruments measured. The live panel in the app is
KNMI's forecast model through Open-Meteo.

1. The latest 10-minute observation from the KNMI Open Data API, dataset
   "10-minute-in-situ-meteorological-observations" v1.0, NetCDF read with
   xarray. "Actueel10mindataKNMIstations" v2, the one most tutorials use,
   stopped updating on 2025-10-02.                   -> data/processed/knmi_current.json
2. Hourly history from the climatology service, five years, the training set.
                                                     -> data/raw/knmi_hourly_<station>.json
3. Daily history for the dashboard chart.            -> data/processed/knmi_daily_history.json

A browser cannot do this. The Authorization header triggers a CORS preflight
KNMI does not answer. The climatology service reports in tenths (T=190 is
19.0 degC) and RH=-1 means under 0.05 mm, all converted here.

    python analysis/knmi/fetch_knmi.py                 #current and 5 years
    python analysis/knmi/fetch_knmi.py --current-only  #quick refresh
"""

import datetime as dt
import json
import math
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.project import (  #noqa: E402
    KNMI_ANONYMOUS_KEY, PROCESSED, RAW, SERVICES, STUDY_AREA, centre_wgs,
)

OPEN_DATA = SERVICES["knmi_open_data"]
DATASET = "10-minute-in-situ-meteorological-observations"
VERSION = "1.0"
HOURLY = "https://www.daggegevens.knmi.nl/klimatologie/uurgegevens"
DAILY = SERVICES["knmi_daily"]

#NetCDF variable -> (label, unit). The 10-minute observation file has 97
#variables; these are the ones the dashboard and the model use.
OBS_VARS = {
    "ta": ("temperature", "degC"),
    "ff": ("wind_speed", "m/s"),
    "dd": ("wind_direction", "deg"),
    "fx": ("wind_gust", "m/s"),
    "rh": ("humidity", "%"),
    "pp": ("pressure_msl", "hPa"),
    "pg": ("precipitation_intensity", "mm/h"),
    "ss": ("sunshine", "min"),
}

#Hourly climatology fields -> (name, divisor). KNMI reports in tenths.
HOURLY_FIELDS = {
    "T":   ("temperature_C", 10.0),
    "TD":  ("dewpoint_C", 10.0),
    "FH":  ("wind_speed_ms", 10.0),     #hourly mean
    "FF":  ("wind_speed_10min_ms", 10.0),
    "FX":  ("wind_gust_ms", 10.0),
    "DD":  ("wind_direction_deg", 1.0),
    "U":   ("humidity_pct", 1.0),
    "P":   ("pressure_hPa", 10.0),
    "RH":  ("precipitation_mm", 10.0),  #-1 means "< 0.05 mm"
    "Q":   ("global_radiation_Jcm2", 1.0),
    "N":   ("cloud_cover_octants", 1.0),
}


def api_get(path, tries=6):
    #GET the Open Data API, retrying on 429.
    #
    #The anonymous key is shared by everyone using it worldwide, so HTTP 429
    #"Too Many Requests" is routine rather than exceptional: it showed up within
    #a handful of calls during development. KNMI sends no Retry-After header, and
    #the limit clears in roughly 15-30 s, so back off and try again. If you hit it
    #constantly, register your own key at developer.dataplatform.knmi.nl.
    last = None
    for attempt in range(tries):
        req = urllib.request.Request(f"{OPEN_DATA}{path}",
                                     headers={"Authorization": KNMI_ANONYMOUS_KEY})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code != 429:
                raise
            wait = 10 * (attempt + 1)
            print(f"    rate limited (429), waiting {wait}s "
                  f"[attempt {attempt + 1}/{tries}]")
            time.sleep(wait)
        except Exception as exc:
            last = exc
            time.sleep(4 * (attempt + 1))
    raise RuntimeError(f"KNMI Open Data unreachable after {tries} tries: {last}")


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


#--- 1. current
def fetch_current(prefer_station):
    try:
        import xarray as xr
    except ImportError:
        print("  ! xarray missing: pip install -r requirements.txt")
        return None

    listing = api_get(f"/datasets/{DATASET}/versions/{VERSION}/files"
                      "?maxKeys=1&orderBy=created&sorting=desc")
    files = listing.get("files") or []
    if not files:
        print("  ! KNMI returned no observation files")
        return None
    fn = files[0]["filename"]
    print(f"  newest observation file: {fn}")

    url = api_get(f"/datasets/{DATASET}/versions/{VERSION}/files/{fn}/url") \
        .get("temporaryDownloadUrl")
    if not url:
        print("  ! no temporary download URL returned")
        return None

    tmp = RAW / "_knmi_latest.nc"
    with urllib.request.urlopen(url, timeout=180) as r:
        tmp.write_bytes(r.read())

    ds = xr.open_dataset(tmp, engine="h5netcdf")
    ids = [str(s) for s in ds["station"].values]
    lats = [float(v) for v in ds["lat"].values]
    lons = [float(v) for v in ds["lon"].values]
    names = [n.decode() if isinstance(n, bytes) else str(n)
             for n in ds["stationname"].values]

    #Prefer the configured station; otherwise take the nearest one that
    #actually reports a temperature this interval.
    idx = None
    if prefer_station is not None:
        wanted = f"{prefer_station:05d}"
        for i, s in enumerate(ids):
            if s.endswith(str(prefer_station)) or s == wanted:
                idx = i
                break
    if idx is None:
        clon, clat = centre_wgs()
        order = sorted(range(len(ids)),
                       key=lambda i: haversine_km(clat, clon, lats[i], lons[i]))
        idx = order[0]

    clon, clat = centre_wgs()
    dist = haversine_km(clat, clon, lats[idx], lons[idx])
    values, missing = {}, []
    for var, (label, unit) in OBS_VARS.items():
        if var not in ds:
            missing.append(var)
            continue
        v = ds[var].isel(station=idx, time=0).values
        try:
            f = float(v)
        except Exception:
            f = float("nan")
        values[label] = None if f != f else round(f, 2)   #f != f detects NaN

    out = {
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": "KNMI Open Data, 10-minute in-situ meteorological observations",
        "source_file": fn,
        "observation_time": str(ds["time"].values[0]),
        "station": ids[idx],
        "station_name": names[idx],
        "station_lat": round(lats[idx], 4),
        "station_lon": round(lons[idx], 4),
        "distance_km": round(dist, 1),
        "units": {lbl: u for (lbl, u) in OBS_VARS.values()},
        "values": values,
    }
    ds.close()
    tmp.unlink(missing_ok=True)
    if missing:
        print(f"  (variables absent from this file: {', '.join(missing)})")
    print(f"  station {out['station']} {out['station_name']}: "
          f"{dist:.1f} km from the study area")
    return out


#--- 2 & 3. climatology
def post_json(url, data, timeout=300, tries=4,
              label=""):
    #POST to the KNMI climatology service, retrying transient failures.
    #
    #The service is intermittently slow and answers 502/503/504 under load: a
    #teammate hit a 504 on a request that completes in two seconds from here. It
    #recovers within seconds, so a single attempt is not enough and a traceback
    #is the wrong response to somebody else's busy server.
    #
    #Retries 5xx and timeouts with growing backoff. A 4xx is our fault, not
    #theirs, so it is raised immediately.
    last = None
    for attempt in range(tries):
        req = urllib.request.Request(url, data=data.encode(),
                                     headers={"Content-Type":
                                              "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code < 500:
                raise                      #a bad request will not fix itself
            wait = min(5 * (attempt + 1), 15)
            print(f"      {label}HTTP {exc.code} from KNMI, retrying in {wait}s "
                  f"[{attempt + 1}/{tries}]")
        except Exception as exc:           #timeouts, connection resets
            last = exc
            wait = min(5 * (attempt + 1), 15)
            print(f"      {label}{type(exc).__name__}, retrying in {wait}s "
                  f"[{attempt + 1}/{tries}]")
        if attempt < tries - 1:
            time.sleep(wait)
    raise RuntimeError(f"KNMI climatology unreachable after {tries} tries: {last}")


def fetch_hourly(station, years):
    #Hourly climatology, in yearly chunks so no single request is enormous.
    end = dt.date.today()
    rows = []
    missing = []
    consecutive_failures = 0
    for back in range(years, 0, -1):
        y0 = dt.date(end.year - back, 1, 1)
        y1 = min(dt.date(end.year - back, 12, 31), end)
        payload = urllib.parse.urlencode({
            "stns": station,
            "start": y0.strftime("%Y%m%d") + "01",
            "end": y1.strftime("%Y%m%d") + "24",
            "fmt": "json",
        })
        try:
            chunk = post_json(HOURLY, payload, label=f"{y0.year}: ")
            consecutive_failures = 0
        except Exception as exc:
            print(f"    {y0.year}: UNAVAILABLE: {exc}")
            missing.append(y0.year)
            consecutive_failures += 1
            if consecutive_failures >= 2:
                #Retries are for a service that is flaky. Two chunks failing
                #every retry means it is down, and grinding through the
                #remaining years costs minutes to learn the same thing.
                rest = [end.year - b for b in range(back - 1, 0, -1)]
                missing.extend(rest)
                print(f"    giving up on the remaining year(s): "
                      f"{', '.join(map(str, rest)) or 'none'}")
                break
            continue
        for r in chunk:
            row = {"time": f"{r['date'][:10]}T{int(r['hour']) - 1:02d}:00"}
            for key, (name, div) in HOURLY_FIELDS.items():
                v = r.get(key)
                if v is None:
                    row[name] = None
                elif key == "RH" and v == -1:
                    row[name] = 0.025          #KNMI's "< 0.05 mm" sentinel
                else:
                    row[name] = round(v / div, 3) if div != 1.0 else v
            rows.append(row)
        print(f"    {y0.year}: {len(chunk):,} hours (running total {len(rows):,})")
        time.sleep(0.4)                        #be polite to a free service

    #The service IGNORES the hour part of start/end and returns the day AFTER
    #the end date as well, so consecutive yearly chunks overlap by 24 hours.
    #Verified: asking for 2021-12-31 hours 20..24 returns all of 31 Dec AND all
    #of 1 Jan. Left in, those duplicates break the assumption that row i-1 is
    #one hour before row i, which is exactly what the lag features rely on.
    seen, deduped = set(), []
    for r in sorted(rows, key=lambda r: r["time"]):
        if r["time"] in seen:
            continue
        seen.add(r["time"])
        deduped.append(r)
    dropped = len(rows) - len(deduped)
    if dropped:
        print(f"    removed {dropped} duplicate hours from chunk overlaps")
    if missing:
        #A gap here is not cosmetic: train_forecast.py builds lag features on
        #the assumption that row i-1 is one hour before row i, and it would
        #happily train on a record with whole years missing.
        print(f"\n  !! {len(missing)} year(s) could not be fetched: "
              f"{', '.join(map(str, missing))}")
        print("     The training set is INCOMPLETE. Re-run when KNMI is "
              "responding rather than training on this.")
    return deduped, missing


def fetch_daily(station, years):
    end = dt.date.today()
    start = dt.date(end.year - years, 1, 1)
    payload = urllib.parse.urlencode({
        "stns": station,
        "vars": "TEMP:WIND:SUNR:PRCP",
        "start": start.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
        "fmt": "json",
    })
    raw = post_json(DAILY, payload, label="daily: ")
    out = []
    for r in raw:
        out.append({
            "date": r["date"][:10],
            "T_mean_C": None if r.get("TG") is None else r["TG"] / 10,
            "T_min_C": None if r.get("TN") is None else r["TN"] / 10,
            "T_max_C": None if r.get("TX") is None else r["TX"] / 10,
            "wind_mean_ms": None if r.get("FG") is None else r["FG"] / 10,
            "wind_max_gust_ms": None if r.get("FHX") is None else r["FHX"] / 10,
            "wind_dir_deg": r.get("DDVEC"),
            "sunshine_h": None if r.get("SQ") is None else max(r["SQ"], 0) / 10,
            "precipitation_mm": None if r.get("RH") is None else max(r["RH"], 0) / 10,
        })
    return out


PARAMS = {
    "station": STUDY_AREA.knmi_station,
    "years": 5,  #years of history for the training set
    "current_only": "--current-only" in sys.argv,  #quick refresh, no history
}


def main():
    p = PARAMS

    print(f"KNMI sensor data: station {p['station']}, "
          f"nearest to {STUDY_AREA.name}")

    print("\n1. latest 10-minute observation")
    cur = fetch_current(p["station"])
    if cur:
        (PROCESSED / "knmi_current.json").write_text(json.dumps(cur, indent=2) + "\n")
        print("  wrote data/processed/knmi_current.json")
        for k, v in cur["values"].items():
            if v is not None:
                print(f"     {k:26} {v} {cur['units'].get(k,'')}")
    if p["current_only"]:
        return 0

    print(f"\n2. hourly history, {p['years']} years (training set)")
    try:
        hourly, missing_years = fetch_hourly(p["station"], p["years"])
    except Exception as exc:
        print(f"  could not reach the KNMI climatology service: {exc}")
        hourly, missing_years = [], list(range(p["years"]))
    if hourly:
        path = RAW / f"knmi_hourly_{p['station']}.json"
        path.write_text(json.dumps({
            "station": p["station"],
            "source": HOURLY,
            "note": "KNMI reports in tenths; already converted here. "
                    "RH=-1 ('< 0.05 mm') stored as 0.025 mm.",
            "records": hourly,
        }) + "\n")
        print(f"  {len(hourly):,} hourly records -> data/raw/{path.name}")

    print(f"\n3. daily history, {p['years']} years (dashboard chart)")
    try:
        daily = fetch_daily(p["station"], p["years"])
    except Exception as exc:
        print(f"  could not fetch the daily series: {exc}")
        print("  The KNMI climatology service does this under load; it usually")
        print("  clears within minutes. Everything already written above is")
        print("  fine, and data/processed/knmi_daily_history.json keeps its")
        print("  previous contents. Re-run when it recovers.")
        daily = []
    if daily:
        (PROCESSED / "knmi_daily_history.json").write_text(json.dumps({
            "station": p["station"],
            "source": DAILY,
            "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "records": daily,
        }) + "\n")
        print(f"  {len(daily):,} daily records -> data/processed/knmi_daily_history.json")
        temps = [r["T_mean_C"] for r in daily if r["T_mean_C"] is not None]
        if temps:
            print(f"  mean daily temperature over the period: "
                  f"{sum(temps) / len(temps):.1f} degC")

    if missing_years or not daily:
        print("\n  Finished with gaps: see the messages above. The current "
              "observation was written; the history was not complete.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
