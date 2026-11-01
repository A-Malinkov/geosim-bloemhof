#!/usr/bin/env python3
"""
fetch_transit.py - public-transport stops around Bloemhof and how often each line calls.

Reads the national GTFS timetable that OVapi publishes (every operator in the
Netherlands, rebuilt daily from the NDOV open data) and writes, for each stop
near the study area, every line that calls there and its frequency per
direction, for a representative weekday and Saturday.

Which stops: bus and tram stops within 400 m of the Bloemhof boundary, metro
and train within 800 m. Those are the usual walk-to-stop catchments, so a stop
just over the edge that residents use still counts. Platforms of one stop (one
per direction) are merged into a single landmark through GTFS `parent_station`.

How often: departures per hour per line and direction, counted from the
timetable, in four periods:
    peak       weekday 07:00-09:00
    day        weekday 10:00-16:00
    evening    weekday 20:00-23:00
    saturday   Saturday 10:00-16:00
The headway shown is 60 / departures per hour, i.e. the AVERAGE wait between
vehicles, not a guaranteed interval. The weekday and Saturday are picked from
the feed as the Tuesday-Thursday and Saturday with the most scheduled trips in
its first three weeks, so a holiday timetable is not mistaken for the norm.

The timetable is the current one and does not change with the design
scenarios: this is a reference layer, identical for baseline / scenario_a /
scenario_b.

Writes data/processed/transit_stops.json. The 242 MB feed is cached in
cache/transit/ (gitignored); pass --refresh to re-download it when newer.

Run:
    python analysis/transit/fetch_transit.py
    python analysis/transit/fetch_transit.py --refresh
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import io
import pathlib
import re
import sys
import zipfile

import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common.project import ROOT, RD, STUDY_AREA, study_area_polygon, write_processed  # noqa: E402

GTFS_URL = "https://gtfs.ovapi.nl/nl/gtfs-nl.zip"
#OVapi's usage policy asks clients to say who they are
USER_AGENT = "geosim-bloemhof (TU Delft student project; github.com/A-Malinkov/geosim-bloemhof)"
CACHE = ROOT / "cache" / "transit" / "gtfs-nl.zip"
OUT = "transit_stops.json"

#walk-to-stop catchment per mode, metres from the study-area boundary
CATCHMENT_M = {"bus": 400, "tram": 400, "metro": 800, "train": 800, "ferry": 800}
#periods as (day kind, first hour, end hour); departures from first <= h < end
PERIODS = {
    "peak":     ("weekday", 7, 9),
    "day":      ("weekday", 10, 16),
    "evening":  ("weekday", 20, 23),
    "saturday": ("saturday", 10, 16),
}
#GTFS route_type -> mode; the extended (100-1700) types are mapped by hundreds
BASIC_TYPES = {0: "tram", 1: "metro", 2: "train", 3: "bus", 4: "ferry"}
EXTENDED_TYPES = {1: "train", 2: "train", 4: "ferry", 7: "bus", 8: "bus", 9: "tram", 10: "ferry", 12: "ferry"}
MODE_RANK = {"train": 0, "metro": 1, "tram": 2, "bus": 3, "ferry": 4}  #rail-bound first in every list
MERGE_M = 250  #same-named stop areas closer than this are one landmark (metro + tram + bus at one square)
#platform suffixes the feed puts in stop names: "perron N", "(Perron G)", "[ H ]"
PLATFORM_RE = re.compile(r"\s*(\[[^\]]*\]|\(?\s*perron\s+\w+\s*\)?)\s*$", re.IGNORECASE)


def mode_of(route_type) -> str:
    #map a GTFS route_type, basic or extended, to one of our five modes
    t = int(route_type)
    if t in BASIC_TYPES:
        return BASIC_TYPES[t]
    if 400 <= t < 500:  #urban rail: metro / underground
        return "metro"
    return EXTENDED_TYPES.get(t // 100, "bus")


# --------------------------------------------------------------- download
def download(refresh: bool) -> pathlib.Path:
    #fetch the feed once; with --refresh, only re-download when the server has a newer one
    import requests
    if CACHE.exists() and not refresh:
        print(f"using cached {CACHE.relative_to(ROOT)} ({CACHE.stat().st_size / 1e6:.0f} MB)")
        return CACHE
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    if CACHE.exists():
        headers["If-Modified-Since"] = email.utils.formatdate(CACHE.stat().st_mtime, usegmt=True)
    print(f"downloading {GTFS_URL} (~240 MB) ...")
    with requests.get(GTFS_URL, headers=headers, stream=True, timeout=60) as r:
        if r.status_code == 304:
            print("  not modified, keeping the cached feed")
            return CACHE
        r.raise_for_status()
        tmp = CACHE.with_suffix(".part")
        with tmp.open("wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
        tmp.replace(CACHE)  #only replace the cache once the download is complete
    print(f"  saved {CACHE.relative_to(ROOT)} ({CACHE.stat().st_size / 1e6:.0f} MB)")
    return CACHE


def read(z: zipfile.ZipFile, name: str, **kw) -> pd.DataFrame:
    #one GTFS table as strings, so ids keep their leading zeros
    with z.open(name) as f:
        return pd.read_csv(io.TextIOWrapper(f, encoding="utf-8-sig"), dtype=str, keep_default_na=False, **kw)


# ------------------------------------------------------------ which stops
def nearby_stops(z) -> pd.DataFrame:
    #every boarding point within the widest catchment, with its distance to the study area
    import geopandas as gpd
    stops = read(z, "stops.txt")
    stops = stops[stops["location_type"].isin(["", "0"])].copy()  #platforms/poles only, not stations or entrances
    stops["lon"] = stops["stop_lon"].astype(float)
    stops["lat"] = stops["stop_lat"].astype(float)
    g = gpd.GeoDataFrame(stops, geometry=gpd.points_from_xy(stops.lon, stops.lat), crs="EPSG:4326").to_crs(RD)
    area = study_area_polygon()
    pad = max(CATCHMENT_M.values())
    xmin, ymin, xmax, ymax = area.bounds
    g = g.cx[xmin - pad:xmax + pad, ymin - pad:ymax + pad].copy()  #cheap box filter before the exact distance
    g["dist_m"] = g.geometry.distance(area)  #0 inside the buurt
    g = g[g["dist_m"] <= pad].copy()
    g["x"], g["y"] = g.geometry.x, g.geometry.y
    #one landmark per stop area; a pole without a parent stands alone
    g["group"] = np.where(g["parent_station"] != "", g["parent_station"], "pole:" + g["stop_id"])
    g = merge_same_name(pd.DataFrame(g.drop(columns="geometry")))
    print(f"{len(g)} boarding points within {pad} m of {STUDY_AREA.name}, in {g['group'].nunique()} stops")
    return g


def base_name(name: str) -> str:
    #"Rotterdam, Zuidplein (perron L)" -> "Zuidplein": the place prefix and the platform go
    return PLATFORM_RE.sub("", name.split(", ", 1)[-1]).strip()


def merge_same_name(g: pd.DataFrame) -> pd.DataFrame:
    #the feed gives metro, tram and bus at one place separate stop areas (Maashaven has four);
    #stop areas sharing a base name within MERGE_M of each other become one landmark
    g["base"] = g["stop_name"].map(base_name)
    cent = g.groupby("group").agg(base=("base", "first"), x=("x", "mean"), y=("y", "mean"))
    parent = {k: k for k in cent.index}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]  #path halving
            k = parent[k]
        return k

    keys = list(cent.index)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            same = cent.at[a, "base"] == cent.at[b, "base"]
            if same and np.hypot(cent.at[a, "x"] - cent.at[b, "x"], cent.at[a, "y"] - cent.at[b, "y"]) <= MERGE_M:
                parent[find(b)] = find(a)
    g["group"] = g["group"].map(find)
    return g


# ------------------------------------------------------------ which days
def active_services(z) -> pd.DataFrame:
    #(service_id, date) rows for every day a service runs; NL feeds use calendar_dates only
    cd = read(z, "calendar_dates.txt")
    added = cd[cd["exception_type"] == "1"][["service_id", "date"]]
    if "calendar.txt" in z.namelist():  #handle a weekly calendar too, should a feed carry one
        cal = read(z, "calendar.txt")
        days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        rows = []
        for _, c in cal.iterrows():
            d = dt.datetime.strptime(c["start_date"], "%Y%m%d").date()
            d1 = dt.datetime.strptime(c["end_date"], "%Y%m%d").date()
            while d <= d1:
                if c[days[d.weekday()]] == "1":
                    rows.append((c["service_id"], d.strftime("%Y%m%d")))
                d += dt.timedelta(days=1)
        removed = set(map(tuple, cd[cd["exception_type"] == "2"][["service_id", "date"]].values))
        weekly = pd.DataFrame([r for r in rows if r not in removed], columns=["service_id", "date"])
        added = pd.concat([added, weekly], ignore_index=True).drop_duplicates()
    return added


def pick_days(services: pd.DataFrame, trips: pd.DataFrame) -> dict[str, str]:
    #the busiest Tue-Thu and Saturday in the feed's first three weeks: a normal timetable, not a holiday one
    per_service = trips.groupby("service_id").size().rename("n")
    per_day = services.join(per_service, on="service_id").groupby("date")["n"].sum()
    day = {d: dt.datetime.strptime(d, "%Y%m%d").date() for d in per_day.index}
    end = min(day.values()) + dt.timedelta(days=21)
    pick = {}
    for kind, weekdays in (("weekday", (1, 2, 3)), ("saturday", (5,))):
        ok = [d for d, v in day.items() if v < end and v.weekday() in weekdays]
        if not ok:
            sys.exit(f"the feed has no {kind} in its first three weeks")
        pick[kind] = per_day[ok].idxmax()
    return pick


# ------------------------------------------------------------ frequencies
def departures(z, stop_ids: set[str], trip_ids: set[str]) -> pd.DataFrame:
    #stream the ~1 GB stop_times and keep only boardings at our stops on our days' trips
    keep = []
    cols = ["trip_id", "stop_id", "departure_time", "pickup_type"]
    with z.open("stop_times.txt") as f:
        reader = pd.read_csv(io.TextIOWrapper(f, encoding="utf-8-sig"), dtype=str,
                             keep_default_na=False, usecols=cols, chunksize=2_000_000)
        for i, chunk in enumerate(reader):
            m = chunk["stop_id"].isin(stop_ids) & chunk["trip_id"].isin(trip_ids)
            m &= chunk["pickup_type"] != "1"  #a stop where you cannot board (e.g. a terminus) is no departure
            keep.append(chunk[m])
            print(f"\r  stop_times: {(i + 1) * 2} M rows read", end="", flush=True)
    print()
    st = pd.concat(keep, ignore_index=True)
    #GTFS times run past 24:00 for after-midnight trips: keep the hour as is, 25 = 01 the next morning
    st["hour"] = st["departure_time"].str.split(":").str[0].astype(int)
    return st


def headway(per_hour: float) -> float | None:
    #average minutes between vehicles; None when nothing runs in the period
    return round(60.0 / per_hour, 1) if per_hour > 0 else None


def clock(t: str) -> str:
    #"25:10:00" -> "01:10", for first/last departure
    h, m, _ = t.split(":")
    return f"{int(h) % 24:02d}:{m}"


def line_entry(ls: pd.DataFrame, agency: pd.Series) -> dict:
    #one line at one stop: frequency per direction, and the busiest direction's as the line's
    r = ls.iloc[0]
    dirs = []
    dkey = "direction_id" if (ls["direction_id"] != "").all() else "trip_headsign"  #headsign when the feed has no direction
    for _, ds in ls.groupby(dkey):
        #a rider waits at one platform: count distinct trips per platform and take the busiest.
        #Loop lines (bus 66) call at both platforms of a stop in one direction, so pooling would double them
        per_hour = {}
        for p, (kind, h0, h1) in PERIODS.items():
            sel = ds[(ds["kind"] == kind) & (ds["hour"] >= h0) & (ds["hour"] < h1)]
            n = sel.groupby("stop_id")["trip_id"].nunique().max() if len(sel) else 0
            per_hour[p] = round(float(n) / (h1 - h0), 2)
        wk = ds[ds["kind"] == "weekday"].sort_values("departure_time")
        named = ds.loc[ds["trip_headsign"] != "", "trip_headsign"]
        dirs.append({
            #short runs share a direction with full ones (metro E: Den Haag and Rotterdam Centraal), so list the main two
            "headsign": " / ".join(named.value_counts().index[:2]),
            "per_hour": per_hour,
            "headway_min": {p: headway(v) for p, v in per_hour.items()},
            "weekday_departures": int(wk.groupby("stop_id")["trip_id"].nunique().max()) if len(wk) else 0,
            "first": clock(wk["departure_time"].iat[0]) if len(wk) else None,
            "last": clock(wk["departure_time"].iat[-1]) if len(wk) else None,
        })
    best = {p: max(d["per_hour"][p] for d in dirs) for p in PERIODS}
    return {
        "line": r["route_short_name"] or r["route_long_name"],
        "name": "" if r["route_long_name"].strip().lower() in ("", "lijn") else r["route_long_name"],  #RET's is just "lijn"
        "mode": r["mode"],
        "operator": agency.get(r["agency_id"], r["agency_id"]),
        "colour": f"#{r['route_color']}" if r["route_color"] else None,
        "text_colour": f"#{r['route_text_color']}" if r["route_text_color"] else None,
        "per_hour": best,
        "headway_min": {p: headway(v) for p, v in best.items()},
        "directions": sorted(dirs, key=lambda d: d["headsign"]),
    }


def build(z) -> dict:
    stops = nearby_stops(z)
    routes = read(z, "routes.txt")
    agency = read(z, "agency.txt").set_index("agency_id")["agency_name"]
    trips = read(z, "trips.txt", usecols=["route_id", "service_id", "trip_id", "trip_headsign", "direction_id"])
    services = active_services(z)
    days = pick_days(services, trips)
    print(f"representative days: weekday {days['weekday']}, saturday {days['saturday']}")

    #trips running on either chosen day, tagged with the day kind
    on_day = []
    for kind, date in days.items():
        sids = set(services.loc[services["date"] == date, "service_id"])
        t = trips[trips["service_id"].isin(sids)].copy()
        t["kind"] = kind
        on_day.append(t)
    day_trips = pd.concat(on_day, ignore_index=True)

    st = departures(z, set(stops["stop_id"]), set(day_trips["trip_id"]))
    #a trip can run on both days, so it joins once per day kind
    st = st.merge(day_trips, on="trip_id").merge(routes, on="route_id")
    st["mode"] = st["route_type"].map(mode_of)
    st = st.merge(stops[["stop_id", "group", "dist_m"]], on="stop_id")
    #a bus stop 700 m away is outside its catchment even though the metro next to it is not
    st = st[st["dist_m"] <= st["mode"].map(CATCHMENT_M)]
    print(f"{len(st)} departures on the two days at {st['group'].nunique()} stops")

    out_stops = []
    for gid, gs in st.groupby("group"):
        lines = [line_entry(ls, agency) for _, ls in gs.groupby("route_id")]
        lines.sort(key=lambda l: (MODE_RANK[l["mode"]], int(l["line"]) if l["line"].isdigit() else 9999, l["line"]))
        used = stops[stops["stop_id"].isin(gs["stop_id"])]  #only the platforms that have service
        out_stops.append({
            "id": gid,
            "name": used["base"].mode().iat[0],
            "full_names": sorted(used["stop_name"].unique()),
            "lon": round(float(used["lon"].mean()), 6),
            "lat": round(float(used["lat"].mean()), 6),
            "n_platforms": int(len(used)),
            "dist_to_study_area_m": round(float(used["dist_m"].min())),
            "modes": sorted({l["mode"] for l in lines}, key=MODE_RANK.get),
            "lines": lines,
        })
    out_stops.sort(key=lambda s: (s["dist_to_study_area_m"], s["name"]))

    feed = read(z, "feed_info.txt").iloc[0]
    iso = lambda d: f"{d[:4]}-{d[4:6]}-{d[6:]}"  # noqa: E731
    return {
        "label": "Public transport stops and line frequencies",
        "source": f"OVapi GTFS-NL ({GTFS_URL}), from NDOV open data; best-effort, no SLA",
        "feed_version": feed.get("feed_version", ""),
        "feed_valid": [iso(feed["feed_start_date"]), iso(feed["feed_end_date"])],
        "days": {k: iso(v) for k, v in days.items()},
        "periods": {p: {"day": k, "from_h": h0, "to_h": h1} for p, (k, h0, h1) in PERIODS.items()},
        "catchment_m": CATCHMENT_M,
        "scenario_independent": True,
        "notes": [
            "Timetabled departures, not punctuality: delays and cancellations are not in it.",
            "Headway = 60 / departures per hour, an average; an uneven timetable means longer waits at times.",
            "A line's frequency at a stop is that of its busiest direction and platform; per direction is in `directions`.",
            "Current timetable: identical for every design scenario.",
        ],
        "stops": out_stops,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="re-download the feed if the server has a newer one")
    args = ap.parse_args()
    path = download(args.refresh)
    with zipfile.ZipFile(path) as z:
        payload = build(z)
    write_processed(OUT, payload)
    for s in payload["stops"]:
        lines = ", ".join(f"{l['mode']} {l['line']} ({l['headway_min']['day'] or '-'} min)" for l in s["lines"])
        print(f"  {s['name']:40s} {s['dist_to_study_area_m']:5.0f} m  {lines}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
