# WMATA bus GTFS-Realtime to TIDES

Work in progress. This project asks how trustworthy public real-time bus data is as a source
for on-time performance. Phase 1, the feed collector, is built. Later phases add dbt models,
TIDES output, data quality checks, and metrics.

## Phase 1: collector

The collector polls two WMATA bus GTFS-Realtime feeds every 30 seconds and downloads the bus
static GTFS feed once per day.

| Feed | URL |
|---|---|
| Vehicle positions | `https://api.wmata.com/gtfs/bus-gtfsrt-vehiclepositions.pb` |
| Trip updates | `https://api.wmata.com/gtfs/bus-gtfsrt-tripupdates.pb` |
| Static GTFS | `https://api.wmata.com/gtfs/bus-gtfs-static.zip` |

The endpoints come from the GTFS API listing on the WMATA developer portal
(developer.wmata.com). The API key goes in the `api_key` request header.

### Setup

```bash
~/.local/bin/python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # then paste your key after WMATA_API_KEY=
```

### Run

Run in the foreground (Ctrl+C to stop):

```bash
.venv/bin/python -m collector run
```

Run in the background:

```bash
scripts/start.sh
```

Check that it is still running and that data is arriving:

```bash
.venv/bin/python -m collector status
```

Rows per minute for a date:

```bash
.venv/bin/python -m collector rows-per-minute --date 2026-11-06
```

Stop:

```bash
scripts/stop.sh
```

The background run uses `nohup` and `caffeinate`. It survives closing the terminal. It stops
when the Mac sleeps (for example when the lid closes), and it does not restart after a crash
or reboot.

### Output

```
data/
  raw/wmata_bus/<YYYY-MM-DD>/vehicle_positions_url/<epoch>-<YYYY-MM-DD-HH-MM-SS>.pb
  raw/wmata_bus/<YYYY-MM-DD>/trip_updates_url/<epoch>-<YYYY-MM-DD-HH-MM-SS>.pb
  raw/wmata_bus/<YYYY-MM-DD>/schedule/gtfs.zip (+ gtfs.zip.sha256)
  parsed/vehicle_positions/date=<YYYY-MM-DD>/<epoch>.parquet
  parsed/trip_updates/date=<YYYY-MM-DD>/<epoch>.parquet
  logs/collector.log
  logs/fetches.csv     one line per fetch: status, bytes, entities, feed age, errors
```

Dates are America/New_York calendar dates. The raw layout matches
[gtfs-rt-to-tides](https://github.com/evansiroky/gtfs-rt-to-tides), so its parser can read
these files directly.

Raw protobuf is the source of truth. To rebuild Parquet after a parser change:

```bash
.venv/bin/python -m collector reparse --date 2026-11-06
```

### Disk use

First run, 2026-11-06, 10:19 AM to 1:44 PM: 321 polling cycles with 0 failed fetches. The
cycles used 207.0 MB of raw protobuf and 77.4 MB of Parquet, an average of 886 KB per cycle.
At 2,880 cycles per day that is 2.55 GB per day, plus 35 MB for the daily static GTFS zip.
This is a daytime rate. Overnight service runs fewer buses, so a full day should use less.
The full-day number is [X] GB until a complete day is collected.

### Known gap from sleep

On the first run the Mac went to sleep when the lid closed at 12:03:30 PM and woke at
12:10:21 PM. The collector saved nothing in that window, then resumed on the next poll with
no errors and logged "tick ran long, skipping 13 poll(s)". Keep the lid open, or connect
power and an external display, to avoid gaps. Phase 3 reports coverage gaps like this one.
