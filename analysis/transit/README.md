# analysis/transit — public-transport stops and line frequencies

Feeds `app/modules/transit.js`. A reference layer: today's timetable, the same
for every design scenario.

## What it does

`fetch_transit.py` reads the national GTFS timetable and writes
`data/processed/transit_stops.json`: every stop near Bloemhof, every line that
calls there, and how often it comes per direction.

```bash
python analysis/transit/fetch_transit.py            # ~2 min; downloads the feed on first run
python analysis/transit/fetch_transit.py --refresh  # re-download if OVapi has a newer feed
```

| choice | value | why |
|---|---|---|
| source | OVapi GTFS-NL, `https://gtfs.ovapi.nl/nl/gtfs-nl.zip` | every operator in the country, rebuilt daily from NDOV open data |
| which stops | bus and tram within 400 m of the Bloemhof boundary, metro and train within 800 m | usual walk-to-stop catchments; a stop just over the edge still serves the buurt |
| one landmark | platforms sharing a GTFS `parent_station`, then same-named stop areas within 250 m | the feed gives the metro, tram and bus at one square separate stop areas |
| periods | peak weekday 07–09, day 10–16, evening 20–23, Saturday 10–16 | |
| days | busiest Tue–Thu and Saturday in the feed's first three weeks | keeps a holiday timetable from passing as the norm; the dates are in the JSON |
| frequency | distinct trips per hour at the busiest platform, per direction; a line's figure is its busiest direction | a rider waits at one platform |
| headway | 60 / departures per hour | an **average** |

## Traps

- **The feed is 242 MB** zipped, and `stop_times.txt` is over 1 GB unzipped.
  It is cached in `cache/transit/` (gitignored) and streamed in chunks, keeping
  only the nearby stops.
- **OVapi asks for a `User-Agent`** that identifies you, and offers no SLA.
- **NL feeds carry no `calendar.txt`**: service days come from
  `calendar_dates.txt` alone. The script handles both.
- **Times run past 24:00** (`25:10:00` is 01:10 the next morning).
- **Loop lines call at both platforms in one direction.** Bus 66 passes Lange
  Hilleweg twice per trip, 24 minutes apart, under the same `direction_id`.
  Pooling the platforms doubled its frequency; counting per platform fixes it.
- **Short runs share a direction.** Metro E southbound mixes Den Haag and
  Rotterdam Centraal trips, so it averages about 5 minutes on an uneven
  pattern: the stop list shows both headsigns.
- **RET's `route_long_name` is just "lijn"**, so it is dropped.

## What it cannot tell you

- It is the **timetable**, not what ran: delays and cancellations are not in it.
- A headway is an average. An uneven timetable has longer gaps at times.
- Lines with no departures in a period (night buses, the odd school or airport
  run) show as "none" for that period. The stop details still list them, with
  their first and last weekday departure.
- It does not change with the design. If a scenario moved a stop or a route,
  this layer would not know.
