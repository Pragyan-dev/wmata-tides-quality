# Methodology

This document explains how the pipeline turns WMATA's public bus GTFS-Realtime feed into
TIDES tables, and every assumption behind the inferred stop times. Each assumption lists
what it gets wrong.

All numbers come from one run on a fixed window: pings fetched on 2026-11-06 from 11:00 AM
to 2:00 PM Eastern (`scripts/build_snapshot.sh`). The window holds 250,685 distinct pings
from 999 vehicles. The Mac running the collector slept from 12:03:30 PM to 12:10:21 PM, so
the window has a 7-minute gap.

## 1. Inputs

| Input | Source | Notes |
|---|---|---|
| Vehicle positions | `bus-gtfsrt-vehiclepositions.pb`, every 30 s | GTFS-RT 1.0 per WMATA |
| Trip updates | `bus-gtfsrt-tripupdates.pb`, every 30 s | Used for skipped stops and trip status |
| Static GTFS | `bus-gtfs-static.zip`, daily | One version per date, keyed by SHA-256 |

WMATA's static GTFS has no `shape_dist_traveled` in `shapes.txt` or `stop_times.txt`.
The pipeline computes distance along each shape itself.

## 2. Staging

**Time zone.** All timestamps are stored as `TIMESTAMPTZ` and displayed in
America/New_York (the dbt session time zone). Exports write ISO 8601 with offset, for
example `2026-11-06T10:15:42-05:00`.

**Duplicate pings.** WMATA repeats a ping in later fetches until the bus reports again.
A ping is identified by `(vehicle_id, vehicle timestamp)`, and only the first fetch is kept.
In the window, 98.9% of pings appeared in exactly one fetch. `times_seen` keeps the count
for the stale-feed quality check.

**Service date.** A ping on a trip gets the trip's `start_date` from the feed. A ping with
no trip gets the local calendar date of its timestamp. 87.5% of pings in the window had a
trip.

**Schedule version.** Each service date uses the most recent static GTFS version downloaded
on or before that date (`int_service_date_feed_versions`). Static times convert to
timestamps using the GTFS rule: seconds after "noon minus 12 hours" local time on the
service date. This handles times past 24:00 and DST change days.

## 3. Stop arrival inference

The goal is one arrival time and one departure time per scheduled stop per trip. The
method runs in four dbt models, all plain SQL.

### 3.1 Shapes and stops in meters (`int_shape_segments`, `int_shape_stop_distances`)

Latitude and longitude convert to flat x/y meters around a fixed origin (38.9 N, 77.03 W)
with 110,540 m per degree of latitude and 86,680 m per degree of longitude. Each shape
becomes a chain of straight segments with the distance along the shape where each segment
starts. Each stop projects onto the nearest segment of each shape that serves it.

- Stops in the window sit a median of 5.0 m from their shape (90th percentile 10.0 m,
  99th percentile 16.5 m).
- 1.19% of the 16,673 stop placements are out of order: the nearest shape point puts the
  stop before an earlier stop in the sequence. This happens where a shape loops or doubles
  back. These stops get no inferred time.

**What it gets wrong.** The flat projection uses one scale for the whole region. Across the
service area (38.7 N to 39.2 N) the east-west scale is off by under 1%, which shifts
distances of a few hundred meters by a few meters. Picking the nearest segment fails on
loops; the method flags those stops instead of fixing them, so loop routes lose more
visits than straight routes.

### 3.2 Snapping pings to the trip's shape (`int_pings_snapped`)

Each ping on a trip is matched to the shape of its GTFS trip. A 250 m grid limits the
search to segments in the 3 x 3 cells around the ping.

- **Pass 1** takes the nearest segment within 100 m.
- **Pass 2** handles shapes that pass the same place twice. Among segments within 30 m of the
  best one, it picks the one whose distance along the shape is closest to the median pass 1
  result of the five pings centered on this one. Pass 2 changed the result for 4.33% of on-route
  pings.
- **Progress** is the running maximum of distance along the shape within the trip. A bus
  cannot go backward on its route, so jitter backward is ignored. Progress was ahead of
  the ping's own snapped position for 5.01% of on-route pings.

96.2% of the 219,347 trip pings in the window were within 100 m of their shape. The rest
are off route: detours, buses still on the previous trip's path, or bad positions. They
do not feed the inference.

**A finding about the feed.** The median ping is 0.29 m from its shape. Raw GPS is not that
accurate, so WMATA appears to publish positions already snapped to the route. This hides
most GPS drift from any downstream user, including this pipeline. It also means this
project cannot measure raw GPS error. The 90th percentile (18.0 m) and 99th percentile
(58.2 m) show that some pings are not snapped.

**What it gets wrong.** The running maximum cannot undo a forward jump. If one bad ping
lands 300 m ahead, progress stays there and stops in between get times that are too early.
Pass 2 reduces this but does not remove it. A trip whose `trip_id` is wrong in the feed
is matched to the wrong shape, and most of its pings fall off route.

### 3.3 Arrival and departure (`int_stop_visits_inferred`)

A stop at distance `d` along the shape has two edges:

- arrival edge at `d - 30 m`
- departure edge at `d + 30 m`

For each edge, an ASOF join finds the last ping at or before the edge and the first ping
after it. The time at the edge is interpolated linearly by distance between those two
pings. The gap between them is stored as `interpolation_gap_s`.

- The median gap was 32 s. 93.3% of inferred visits had a gap of 60 s or less, 94.4% had
  120 s or less, and 95.0% had 300 s or less. Most long gaps come from the 7-minute sleep
  gap.
- Dwell (departure minus arrival) had a median of 10 s, 10th percentile 5 s, 90th
  percentile 40 s, and 99th percentile 100 s.

**Layovers.** A bus often waits at the first stop. The first stop gets a departure time
(the moment the bus leaves the 30 m zone) and no arrival time. The last stop gets an
arrival time; its departure is not meaningful.

**What it gets wrong.**
- Linear interpolation assumes constant speed between pings. With a 32 s median gap, a bus
  that stops at a red light just before the stop zone gets an arrival time that is too
  early by up to the length of the stop.
- The 30 m zone defines arrival and departure. It does not see doors. A bus that stops 40 m
  short of the sign, or passes a stop without stopping, still gets times. Dwell measures time
  in the zone, not time with doors open.
- A bus that passes a stop with no ping inside the zone still gets times from the pings on
  each side. Whether it stopped is unknown.

### 3.4 Why a stop has no time (`no_visit_reason`)

| Reason | Visits | Share |
|---|---|---|
| Time inferred | 74,362 | 66.4% |
| `bus_never_reached_stop` (last on-route ping is before the stop) | 21,680 | 19.4% |
| `bus_first_seen_past_stop` (first on-route ping is after the stop) | 14,857 | 13.3% |
| `stop_not_placed_on_shape` (out-of-order stop, section 3.1) | 947 | 0.8% |
| `other` | 94 | 0.1% |

Total: 111,940 scheduled stop visits on 2,546 performed trips. Most of the first two
reasons come from the window edges: trips already underway at 11:00 AM or still running at
2:00 PM. 56 of these stops were also marked SKIPPED in TripUpdates, and stop_visits labels
them `Skipped` instead of `Missing`. Phase 3 quality filters measure on-time performance
with and without partial trips.

### 3.5 Consistency check

WMATA reports `current_status = STOPPED_AT` with a stop sequence on many pings. For 69,547
such pings that match a stop with both an inferred arrival and departure:

- 73.0% fall inside the inferred arrival-to-departure window
- 97.3% fall within 30 s of it
- 99.0% fall within 60 s of it
- 16.7% are before the inferred arrival, 10.2% are after the inferred departure

This is a consistency check, not ground truth. The same pings feed the inference, and
WMATA's own STOPPED_AT logic is not documented. A real accuracy test needs agency AVL
door events, which the public feed does not include.

## 4. TIDES output

The marts follow the TIDES v1.0 schemas (`spec/tides-v1.0/`). `scripts/export_tides.py`
writes the CSVs in schema column order, writes `datapackage.json`, and validates both:
the package descriptor against `tides-datapackage-profile.json`, and every row against its
table schema with frictionless (types, required fields, allowed values, ranges, primary
keys). The validator was tested on a copy with a bad enum value, an impossible date, and a
duplicate key, and reported all three.

**Key choices.**
- `trip_id_performed` is `<GTFS trip_id>-<vehicle_id>`. A trip that changes buses partway
  becomes two performed trips.
- `trip_type` is `In service` whenever the feed reports a trip_id. The feed has no deadhead
  flag, so a bus deadheading with a trip assigned is labeled in service.
- `stop_visits.schedule_relationship` is `Scheduled` when a time was inferred, `Skipped`
  when no time was inferred and TripUpdates marked the stop SKIPPED, and `Missing`
  otherwise.
- TIDES fields the public feed cannot supply are written as empty columns: device_id,
  pattern_id, gps_quality, odometer, schedule and headway deviation, operator_id,
  passenger counts, door events, ramp and lift data, and fare data.

**Issues in the TIDES v1.0 schema files.** `vehicle_locations.schema.json` uses the key
`foreignReferences` instead of the Table Schema key `foreignKeys`, so validators ignore it.
One of those references points to a `stop_times` resource and a `stop_sequence` field,
neither of which exists in TIDES v1.0. This pipeline checks referential integrity with dbt
tests instead (stop_visits to trips_performed).

## 5. Limits of the whole approach

A public real-time feed is a stand-in for an agency's internal AVL data, which is what TIDES
is designed for. AVL records every position at a fixed rate with door and odometer events.
The public feed is sampled every 30 s, already snapped to the route, and carries no doors,
passenger counts, or operator data. Every stop time here is an estimate from that sample.
