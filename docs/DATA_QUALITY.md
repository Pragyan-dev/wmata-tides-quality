# Data quality

This document answers the project question: how trustworthy is WMATA's public real-time
bus feed as a source for on-time performance? It lists every check the pipeline runs, what
the checks found, how much on-time performance moves when bad data is filtered out, and how
this pipeline compares with prior work on the same raw files.

All numbers come from one window: pings fetched on 2026-11-06 from 11:00 AM to 2:00 PM
Eastern, 250,685 distinct pings from 999 vehicles. To reproduce them:

```bash
scripts/build_snapshot.sh
.venv/bin/python scripts/report.py
.venv/bin/python scripts/compare_gtfs_rt_to_tides.py
```

Three hours on one weekday midday is a small sample. The numbers describe this window,
not WMATA bus service in general.

## 1. Checks

dbt runs 110 models and tests on every build. The tests cover:

- **Not null and uniqueness** on every primary key, including the TIDES composite keys.
- **Accepted values** on every enum: GTFS-RT `current_status`, trip and stop
  `schedule_relationship`, `occupancy_status`, and the TIDES enum fields.
- **Referential integrity to static GTFS** for the feed's trip_id, route_id, and stop_id
  (severity warn, because a mismatch is a finding, not a failure), and stop_visits to
  trips_performed (severity error).

Custom checks live in `dbt_project/models/marts/quality`. Thresholds are dbt vars in
`dbt_project.yml`.

| Level | Check | Rule |
|---|---|---|
| Feed | failed_fetch | no 200 response after retries |
| Feed | empty_feed | 200 response with zero entities |
| Feed | stale_feed | header timestamp unchanged from the previous fetch |
| Feed | missed_polls | more than 45 s since the previous fetch |
| Ping | missing_position | no latitude or longitude |
| Ping | outside_service_area | outside the bounding box of all stops plus 2 km |
| Ping | impossible_speed | implied speed from the vehicle's previous ping over 35 m/s (about 78 mph), on a jump of at least 200 m |
| Ping | stale_ping | already 120 s old when first fetched, or repeated by the feed for 120 s |
| Ping | off_route | on a trip, but more than 100 m from that trip's shape |
| Ping | trip_not_in_static, stop_not_in_static | feed ID not in that date's static GTFS |
| Trip | too_few_pings | fewer than 10 on-route pings |
| Trip | coverage_gap | two consecutive pings more than 120 s apart |
| Trip | overlaps_feed_gap | trip running while the collector missed polls |
| Trip | cut_by_window | scheduled to start before or end after the collected window |
| Trip | incomplete_timepoints | at least one timepoint has no inferred time |
| Trip | scheduled_trip_not_observed | scheduled entirely inside the window, but no vehicle was seen operating it |
| Stop visit | no_inferred_visit, timepoint_no_inferred_visit | no arrival or departure inferred |

The `data_quality` mart summarizes every check by service date and route: rows checked,
rows flagged, and share flagged.

## 2. Results

| Level | Check | Checked | Flagged | Share |
|---|---|---|---|---|
| Feed | vehicle_positions failed / empty / stale | 347 | 0 / 0 / 0 | 0% |
| Feed | trip_updates failed / empty / stale | 347 | 0 / 0 / 0 | 0% |
| Feed | missed_polls (each feed) | 347 | 1 gap, 13 polls | 0.29% |
| Ping | missing_position | 250,685 | 0 | 0% |
| Ping | outside_service_area | 250,685 | 0 | 0% |
| Ping | impossible_speed | 250,685 | 18 | 0.01% |
| Ping | stale_ping | 250,685 | 918 | 0.37% |
| Ping | off_route | 250,685 | 8,254 | 3.29% |
| Ping | trip_not_in_static | 250,685 | 0 | 0% |
| Ping | stop_not_in_static | 250,685 | 0 | 0% |
| Trip | too_few_pings | 2,594 | 204 | 7.86% |
| Trip | coverage_gap | 2,594 | 775 | 29.88% |
| Trip | overlaps_feed_gap | 2,594 | 612 | 23.59% |
| Trip | cut_by_window | 2,594 | 1,131 | 43.60% |
| Trip | incomplete_timepoints | 2,594 | 1,735 | 66.89% |
| Trip | scheduled_trip_not_observed | 1,488 | 58 | 3.90% |
| Stop visit | no_inferred_visit | 111,940 | 35,420 | 31.64% |
| Stop visit | timepoint_no_inferred_visit | 18,041 | 6,023 | 33.39% |

### What the results mean

**The feed itself was reliable.** No fetch failed, came back empty, or repeated its header
timestamp. The vehicle positions header was a median of 3 s old when fetched (99th
percentile 6.5 s, maximum 8 s). Trip updates were a median of 5 s old (maximum 11 s). Pings
were a median of 8 s old when first fetched (99.9th percentile 32 s). The only missed polls
were the 13 lost while the collector's laptop slept, a 427 s gap.

**IDs match the schedule.** Every trip_id, route_id, and stop_id in the window exists in
that day's static GTFS.

**Positions look clean because WMATA snaps them.** No ping was outside the service area or
missing a position, and the median tagged ping is 0.28 m from its shape
(METHODOLOGY.md section 3.2). This suggests WMATA publishes positions already snapped to
the route. Clean positions in the public feed do not prove clean GPS on the bus.

**A few vehicles jump.** 18 pings from 8 vehicles implied impossible speeds. Vehicle 2986
alone had 8. The largest jump was 5,255 m, and the fastest implied speed was 178.3 m/s.

**Off-route pings cluster on a few routes.** 3.29% of all pings were off route. Among
routes with at least 500 trip pings, D94 had the most at 21.4%, then A40 (16.8%), F23
(16.2%), P33 (16.0%), and P87 (15.6%). These can be real detours or buses tagged with
their next trip while still finishing the previous one.

**Occupancy is often missing.** 54.2% of pings report `NO_DATA_AVAILABLE` for occupancy.

**Trip completeness is the largest problem.** Two thirds of trips have at least one
timepoint with no time. Much of that comes from the window: 43.60% of trips were cut by its
edges and 23.59% overlapped the sleep gap. On the 866 trips fully inside the window with no
missed polls, 489 (56.5%) have every timepoint. The rest lose mostly the last timepoint:
the feed changes the bus to its next trip before it reaches the last stop and never
reports it `STOPPED_AT` there (0 of 12,975 pings that target a trip's last stop).

## 3. Sensitivity of on-time performance

On-time performance follows WMATA's published definition: a timepoint departure is on time
from 2 minutes early to 7 minutes late, and the last timepoint is on time if its arrival is
no more than 7 minutes late (see `DASHBOARD_SPEC.md` for sources). It is computed at three
quality filter levels.

| Level | Keeps | Timepoint events | Trips | Routes | OTP | Early | Late |
|---|---|---|---|---|---|---|---|
| Loose | every timepoint with an inferred time | 11,990 | 2,324 | 109 | 76.06% | 10.55% | 13.39% |
| Moderate | interpolation gap 120 s or less, off-route share 20% or less, 10+ on-route pings | 10,713 | 2,152 | 109 | 76.36% | 10.55% | 13.10% |
| Strict | moderate, plus gap 60 s or less, off-route 5% or less, shape-method times only, no impossible-speed or stale pings, no coverage gap, no missed polls, trip inside the window, every timepoint inferred | 2,068 | 370 | 92 | 77.66% | 11.27% | 11.07% |

Moderate filtering keeps 89.3% of events and moves OTP by 0.30 points. Strict filtering
keeps 17.2% of events and moves OTP by 1.60 points.

### Which filter matters

Each filter applied alone, sorted by how much it moves OTP from 76.06%:

| Filter alone | Events kept | OTP | Change |
|---|---|---|---|
| Time from shape method only | 92.2% | 74.86% | -1.20 pp |
| No coverage gap on the trip | 58.2% | 76.71% | +0.65 pp |
| All timepoints on the trip inferred | 48.2% | 76.71% | +0.65 pp |
| Interpolation gap 120 s or less | 93.8% | 76.53% | +0.47 pp |
| Interpolation gap 60 s or less | 92.7% | 76.48% | +0.42 pp |
| Trip inside the window | 72.9% | 75.71% | -0.35 pp |
| No stale ping on the trip | 86.4% | 76.25% | +0.19 pp |
| No missed polls during the trip | 65.9% | 76.18% | +0.12 pp |
| Off-route share 5% or less | 92.1% | 75.97% | -0.09 pp |
| 10+ on-route pings | 99.3% | 76.14% | +0.08 pp |
| No impossible-speed ping | 99.7% | 76.01% | -0.05 pp |

Dropping first-stop times from the feed-sequence fallback lowers OTP by 1.20 points. Those
events are first timepoints, where buses start on schedule more often, so this is partly a
change in which timepoints are counted, not only a change in accuracy. Filters that drop
long interpolation gaps raise OTP by under half a point.

### Routes move more than the system

For the 22 routes with at least 100 loose and 30 strict events, strict minus loose OTP had
a median of +1.58 points, a 10th percentile of -3.38 points, and a 90th percentile of +7.62
points. The range was -6.03 to +22.17 points.

| Route | Loose events | Strict events | Loose OTP | Strict OTP | Change |
|---|---|---|---|---|---|
| D40 | 183 | 32 | 71.58% | 93.75% | +22.17 pp |
| D6X | 183 | 52 | 80.87% | 100.00% | +19.13 pp |
| C37 | 140 | 43 | 71.43% | 79.07% | +7.64 pp |
| M12 | 164 | 39 | 82.32% | 89.74% | +7.42 pp |
| D60 | 195 | 66 | 65.13% | 71.21% | +6.08 pp |

The strict samples per route are small (32 to 66 events), so a single trip moves a route's
number by several points.

### Answer to the project question

For a systemwide midday number, data quality in the public feed moved on-time performance
by less than 2 points: 76.06% with no filtering, 77.66% with strict filtering. For a single
route, the same filters moved it by up to 22 points. The feed is usable for a systemwide
trend. It is not reliable enough to rank individual routes without quality filters and
larger samples, and the strict filter that makes route numbers defensible keeps only 17.2%
of timepoint events.

## 4. Known gaps in the checks

- No check can measure raw GPS error, because WMATA appears to snap positions before
  publishing (section 2).
- Missed trips are only bounded, not measured. Of 1,488 trips scheduled entirely inside
  the window, no vehicle was seen operating 58 (3.9%), or 38 of 883 (4.3%) when trips that
  overlap the sleep gap are left out. A trip can be unobserved because it was missed, or
  because its bus sent no trip_id or a wrong one; the feed cannot tell these apart.
- The service area check is a bounding box, not WMATA's real service boundary. A ping on a
  road inside the box but outside the service area passes.
- Stop arrival accuracy has only a consistency check (METHODOLOGY.md section 3.5), not a
  check against ground truth.

## 5. Comparison with gtfs-rt-to-tides

[evansiroky/gtfs-rt-to-tides](https://github.com/evansiroky/gtfs-rt-to-tides) converts
collected GTFS-RT into TIDES vehicle_locations and trips_performed. It has no stop_visits.
It ran on the same 347 vehicle positions files and 347 trip updates files, at commit
`16a09eb` (2024-10-24), with its pinned dependencies in a separate virtual environment
(`.venv-compare`, gtfs_kit 6.1.1, gtfs-realtime-bindings 1.0.0). This repository's raw layout
matches its expected layout, so no files were converted.

### Running it unmodified

| Script | Result |
|---|---|
| parse_vehicle_positions_for_day.py | Wrote 0 data rows and exited with code 0 |
| parse_trip_updates_for_day.py | Ran, but stopped reading at 11:59:59 AM: 2,149 observed trips |

Two problems caused this:

1. **A leftover debug exit.** The vehicle positions parser calls `sys.exit()` on the first
   ping whose trip has a `start_date`. WMATA sets `start_date` on every trip ping, so the
   script stops at the first one. It exits with code 0, so the failure is silent.
2. **Text comparison of GTFS times.** The parsers take the day's last scheduled time from
   `gtfs_kit.get_start_and_end_times`, which compares times as text. WMATA writes 1,107,973
   of its 4,176,900 stop times with a one-digit hour, and `"9:59:59"` sorts after
   `"26:10:00"` as text. gtfs_kit reports the service day ending at 9:59:59, the parsers add
   2 hours, and every file after 11:59:59 AM is skipped.

For the comparison below, a copy in `data/compare/patched/` removes the 3 debug lines and
replaces the end time with the numeric maximum. Nothing else changed.

### Results (patched copy)

| Measure | This pipeline | gtfs-rt-to-tides |
|---|---|---|
| vehicle_locations rows | 250,685 | 250,685 |
| Same position, same trip_id on matched pings | 250,685 of 250,685 | |
| vehicle_locations valid against TIDES v1.0 | yes | no |
| trips_performed rows | 2,594 | 14,069 (3,751 observed, 10,318 `Missing`) |
| trips_performed valid against TIDES v1.0 | yes | no |
| stop_visits | 111,940 rows | not produced |

**What both get right.** Both pipelines dedupe to exactly the same 250,685 pings, with the
same positions and trip IDs. This pipeline dedupes on vehicle and timestamp; theirs on
vehicle, position, bearing, speed, and timestamp. The two keys select the same pings.

**Where gtfs-rt-to-tides does not match TIDES.**
- vehicle_locations names its key `location_ping` instead of the required
  `location_ping_id`.
- It writes GTFS-RT enum numbers instead of TIDES values: `1` instead of `Stopped at` and
  `0` instead of `Scheduled`. 219,347 rows fail on `current_status` and 219,347 on
  `schedule_relationship`.
- It writes `0` for heading when the feed does not send a bearing (133,770 pings). This
  pipeline writes empty, because heading 0 means due north.
- trips_performed adds every scheduled trip it did not see as `Missing`. TIDES does not allow
  `Missing` in trips_performed.schedule_relationship (10,318 errors), and those rows have no
  vehicle_id, which TIDES requires (11,287 errors: the 10,318 `Missing` rows plus 969
  observed trips whose trip updates carried no vehicle).
- 23 trips have a start or end time of 1969-12-31, from a stop time update with neither an
  arrival nor a departure time (Unix time 0).

**Where gtfs-rt-to-tides does something this pipeline does not.** Listing scheduled trips
that never appeared is the right idea: it shows missed service, which this pipeline
only bounds with a separate quality model (section 4). In TIDES it needs a valid way to
say so, since trips_performed requires a vehicle.

**Trip start and end times.** gtfs-rt-to-tides takes them from TripUpdates, using the last
time reported for the lowest and highest stop sequence it saw. This pipeline infers them
from VehiclePositions. On 2,518 trips in both outputs with one vehicle, the start stop
matched on 2,019 trips and the end stop on 2,288. Where the stop matched and both had a
time, the two start times differed by a median of 15.1 s (90th percentile 117.5 s, 1,706
trips), and the end times by a median of 12.4 s (90th percentile 194.5 s, 1,281 trips).
Neither can be called right without AVL ground truth. A start stop mismatch usually means
the trip was already underway when the window began: gtfs-rt-to-tides then reports the first
stop it saw, while this pipeline reports the scheduled first stop.

**Trip identity.** gtfs-rt-to-tides uses the GTFS trip_id as `trip_id_performed`. This
pipeline uses trip_id plus vehicle_id, because 36 trips in the window were operated by more
than one bus.
