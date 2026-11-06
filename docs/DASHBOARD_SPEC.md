# Dashboard spec (Power BI)

This spec describes a Power BI report built on the CSV extracts in `data/powerbi/`. It lists
the data model, the Power Query steps, every DAX measure, and each page with its visuals.
The last section gives values from the 2026-11-06 snapshot so each measure can be checked
after it is built.

To create the extracts:

```bash
scripts/build_snapshot.sh
.venv/bin/python scripts/export_powerbi.py
```

## 1. Definitions

**On-time performance (OTP).** The default follows WMATA's published Metrobus definition:

- A timepoint departure is on time from 2 minutes early to 7 minutes late. OTP is on-time
  timepoints divided by timepoints delivered. Source: WMATA, *Metro Strategic
  Transformation Plan: Service Excellence Report, Performance Measure Definitions*, last
  updated July 2026,
  https://www.wmata.com/content/dam/wmata-com/about/records/SER%20Definitions.pdf
- The measure uses departures from timepoints, and the last timepoint of a trip counts as
  on time if the bus arrives no more than 7 minutes late. Source: WMATA, *Bus Service
  Guidelines*, Reliability section,
  https://www.wmata.com/content/dam/wmata-com/migrated-assets/initiatives/plans/upload/metrobus-service-guidelines.pdf
- Both accessed 2026-11-06.

The window is configurable. Change `otp_early_s` and `otp_late_s` in
`dbt_project/dbt_project.yml` and rebuild. The extracts then carry the new window in
`is_on_time`, `is_early`, and `is_late`.

**Headway adherence.** WMATA's Bus Service Guidelines measure headway-based service as the
share of timepoint departures within the scheduled headway plus 15%, rounded up to the next
minute. WMATA treats routes with scheduled headways of 12 minutes or better as
headway-based. `fact_headways.is_headway_on_time` and `is_frequent` follow this rule.

**Bunching.** This project's definition, not WMATA's: a bus is bunched when it departs a
timepoint less than 2 minutes after the bus scheduled just before it on the same route,
direction, and stop. A negative headway means the later-scheduled bus left first.
The threshold is `bunching_threshold_s` in `dbt_project.yml`.

**Quality levels.** Every timepoint event has `passes_moderate` and `passes_strict` flags
(definitions in `DATA_QUALITY.md` section 3). Strict events are a subset of moderate events.
The dashboard defaults to moderate. Headway extracts are built at the moderate level only.

## 2. Tables

| File | Grain | Use |
|---|---|---|
| `fact_timepoint_events.csv` | one timepoint of one performed trip | main fact table for OTP |
| `fact_headways.csv` | one pair of consecutive scheduled trips at one timepoint | headway and bunching fact |
| `dim_routes.csv` | route | names and colors |
| `dim_stops.csv` | stop | names and coordinates |
| `otp_by_route.csv`, `otp_by_stop.csv`, `otp_by_hour.csv`, `otp_by_route_hour.csv` | pre-aggregated at the moderate level | checking DAX results |
| `headway_by_route.csv` | route and direction | checking headway measures |
| `data_quality.csv` | date, route, check | data quality page |
| `dq_otp_sensitivity.csv` | quality level | sensitivity page |
| `dq_otp_filter_effects.csv` | one filter | sensitivity page |
| `dq_otp_sensitivity_by_route.csv` | route | sensitivity page |

Column descriptions are in `dbt_project/models/marts/metrics/_metrics.yml` and
`dbt_project/models/marts/quality/_quality.yml`, and in the dbt docs site.

## 3. Power Query

1. Get Data, Text/CSV, for each file. Use the first row as headers.
2. Set types:
   - `service_date`: Date
   - `scheduled_ts`, `actual_ts`: Date/Time (the files hold local America/New_York time
     with no offset)
   - every `is_*`, `passes_*`, `has_*`, `cut_by_window`, `overlaps_feed_gap`,
     `too_few_pings`: True/False
   - `deviation_s`, `interpolation_gap_s`, `*_headway_s`, `headway_ratio`, `*_pct`,
     `stop_lat`, `stop_lon`: Decimal Number
   - `direction_id`, `scheduled_hour`, `trip_stop_sequence`, counts: Whole Number
   - `route_id`, `stop_id`, `trip_id*`, `vehicle_id`: Text (route IDs such as `D6X` and stop
     IDs with leading zeros must stay text)
3. In `fact_timepoint_events`, add a column `quality_rank` (Whole Number):

   ```
   = Table.AddColumn(#"Changed Type", "quality_rank", each
       if [passes_strict] then 3
       else if [passes_moderate] then 2
       else if [actual_ts] <> null then 1
       else 0, Int64.Type)
   ```

   3 = strict, 2 = moderate, 1 = loose (has a time), 0 = no time inferred.

4. Add a table `Quality Level` with Enter Data:

   | Level | Order |
   |---|---|
   | Loose | 1 |
   | Moderate | 2 |
   | Strict | 3 |

## 4. Model

Relationships, all many-to-one, single direction:

| From | To |
|---|---|
| `fact_timepoint_events[route_id]` | `dim_routes[route_id]` |
| `fact_timepoint_events[stop_id]` | `dim_stops[stop_id]` |
| `fact_headways[route_id]` | `dim_routes[route_id]` |
| `fact_headways[stop_id]` | `dim_stops[stop_id]` |
| `dq_otp_sensitivity_by_route[route_id]` | `dim_routes[route_id]` |

`Quality Level` has no relationship; measures read it with `SELECTEDVALUE`.
`data_quality` has no relationship, because its `route_id` includes `ALL` (feed checks)
and `(no trip)` (pings without a trip).

Sort `Quality Level[Level]` by `Quality Level[Order]`.

## 5. Measures

Put the measures in a table named `_Measures`.

```dax
Min Quality Rank = SELECTEDVALUE('Quality Level'[Order], 2)

Timepoints Scheduled = COUNTROWS(fact_timepoint_events)

Timepoint Events =
VAR minRank = [Min Quality Rank]
RETURN CALCULATE(
    COUNTROWS(fact_timepoint_events),
    fact_timepoint_events[quality_rank] >= minRank
)

On-Time Events =
VAR minRank = [Min Quality Rank]
RETURN CALCULATE(
    COUNTROWS(fact_timepoint_events),
    fact_timepoint_events[quality_rank] >= minRank,
    fact_timepoint_events[is_on_time] = TRUE()
)

Early Events =
VAR minRank = [Min Quality Rank]
RETURN CALCULATE(
    COUNTROWS(fact_timepoint_events),
    fact_timepoint_events[quality_rank] >= minRank,
    fact_timepoint_events[is_early] = TRUE()
)

Late Events =
VAR minRank = [Min Quality Rank]
RETURN CALCULATE(
    COUNTROWS(fact_timepoint_events),
    fact_timepoint_events[quality_rank] >= minRank,
    fact_timepoint_events[is_late] = TRUE()
)

OTP % = DIVIDE([On-Time Events], [Timepoint Events])
Early % = DIVIDE([Early Events], [Timepoint Events])
Late % = DIVIDE([Late Events], [Timepoint Events])

Median Deviation (min) =
VAR minRank = [Min Quality Rank]
RETURN DIVIDE(
    CALCULATE(
        MEDIAN(fact_timepoint_events[deviation_s]),
        fact_timepoint_events[quality_rank] >= minRank
    ),
    60
)

Timepoint Coverage % =
DIVIDE(
    CALCULATE(COUNTROWS(fact_timepoint_events), fact_timepoint_events[quality_rank] >= 1),
    [Timepoints Scheduled]
)

Trips = DISTINCTCOUNT(fact_timepoint_events[trip_id_performed])

Headway Pairs = COUNTROWS(fact_headways)

Bunched % =
DIVIDE(
    CALCULATE(COUNTROWS(fact_headways), fact_headways[is_bunched] = TRUE()),
    [Headway Pairs]
)

Headway On-Time % (Frequent) =
DIVIDE(
    CALCULATE(
        COUNTROWS(fact_headways),
        fact_headways[is_frequent] = TRUE(),
        fact_headways[is_headway_on_time] = TRUE()
    ),
    CALCULATE(COUNTROWS(fact_headways), fact_headways[is_frequent] = TRUE())
)

Median Headway Ratio = MEDIAN(fact_headways[headway_ratio])

DQ Flagged % = DIVIDE(SUM(data_quality[n_flagged]), SUM(data_quality[n_checked]))
```

Format the `%` measures as Percentage with 1 decimal place and the others as Whole Number
or Decimal with 1 place.

## 6. Pages

Every page has a `Quality Level` slicer (single select, default Moderate) in the top right,
except the Data Quality page. Put the OTP definition in a text box at the bottom of the
Overview page.

### Page 1. Overview

| Visual | Fields |
|---|---|
| Card | OTP % |
| Card | Early % |
| Card | Late % |
| Card | Timepoint Events |
| Card | Trips |
| Card | Timepoint Coverage % |
| Clustered column chart | X: `fact_timepoint_events[scheduled_hour]`; Y: OTP %; tooltip: Timepoint Events |
| 100% stacked bar | Y: `dim_routes[route_short_name]`; values: On-Time Events, Early Events, Late Events; sorted by OTP % ascending; Top N filter 15 by Timepoint Events |
| Text box | OTP definition and sources from section 1 |

### Page 2. Routes

| Visual | Fields |
|---|---|
| Table | `dim_routes[route_label]`, `fact_timepoint_events[direction_id]`, Trips, Timepoint Events, OTP %, Early %, Late %, Median Deviation (min). Conditional formatting on OTP % (red under 70%, green at 85% and over) |
| Matrix (heatmap) | Rows: `dim_routes[route_short_name]`; Columns: `fact_timepoint_events[scheduled_hour]`; Values: OTP % with background color scale |
| Slicer | `dim_routes[route_short_name]` (search on) |
| Scatter | X: Timepoint Events; Y: OTP %; Details: `dim_routes[route_short_name]`. Shows which low OTP routes have enough events to trust |

Add a visual-level filter of Timepoint Events at least 30 on the table and scatter, and a
note that routes under 30 events are left out.

### Page 3. Stops

| Visual | Fields |
|---|---|
| Map (Azure Maps) | Latitude: `dim_stops[stop_lat]`; Longitude: `dim_stops[stop_lon]`; Size: Timepoint Events; Color: OTP % (diverging, center 77%); Tooltip: `dim_stops[stop_name]`, OTP %, Late % |
| Table | `dim_stops[stop_name]`, Timepoint Events, OTP %, Late %, Median Deviation (min); filter Timepoint Events at least 20; sort by OTP % ascending |

Filter the map to `dim_stops[is_timepoint] = True`.

### Page 4. Headways and Bunching

Headway measures are built at the moderate level only. Hide the Quality Level slicer on this
page and add a text box that says so.

| Visual | Fields |
|---|---|
| Card | Headway Pairs |
| Card | Bunched % |
| Card | Headway On-Time % (Frequent) |
| Card | Median Headway Ratio |
| Bar chart | Y: `dim_routes[route_short_name]`; X: Bunched %; Top N 10 by Bunched %, with a visual filter Headway Pairs at least 30 |
| Scatter | X: `fact_headways[scheduled_headway_s]` / 60; Y: `fact_headways[actual_headway_s]` / 60 (add as minute columns in Power Query); add a constant line y = 2 for the bunching threshold |
| Column chart | X: `fact_headways[headway_ratio]` binned at 0.25; Y: count of rows |

### Page 5. Data Quality

| Visual | Fields |
|---|---|
| Matrix | Rows: `data_quality[check_level]`, `data_quality[check_name]`; Values: sum of n_checked, sum of n_flagged, DQ Flagged % |
| Table | `dq_otp_sensitivity`: filter_level, timepoint_events, pct_of_loose_events, otp_pct, otp_change_vs_loose_pp |
| Bar chart | `dq_otp_filter_effects`: Y filter_name, X otp_change_pp; data labels on |
| Scatter | `dq_otp_sensitivity_by_route`: X loose_otp_pct, Y strict_otp_pct, Size strict_events, Details route_id; add a y = x line. Points far from the line are routes whose OTP depends on data quality |
| Table | `data_quality` filtered to check_name = off_route, route_id not `(no trip)`: route_id, n_checked, pct_flagged, sorted descending |

### Page 6. About

A text page with:

- the project question
- the data source (WMATA public GTFS-Realtime, polled every 30 s) and the window covered
- the limitation from the README: a public real-time feed is a stand-in for an agency's
  internal AVL data, which is what TIDES is designed for
- links to `METHODOLOGY.md` and `DATA_QUALITY.md`

## 7. Check values (2026-11-06, 11:00 AM to 2:00 PM)

With the extracts from that snapshot, the measures should show:

| Measure | Loose | Moderate | Strict |
|---|---|---|---|
| Timepoint Events | 11,990 | 10,713 | 2,068 |
| OTP % | 76.1% | 76.4% | 77.7% |
| Early % | 10.6% | 10.6% | 11.3% |
| Late % | 13.4% | 13.1% | 11.1% |

At Moderate:

| Check | Value |
|---|---|
| On-Time Events | 8,180 |
| Timepoints Scheduled | 18,041 |
| OTP % at scheduled hour 11 / 12 / 13 | 78.7% / 74.4% / 77.1% |
| Lowest OTP, 50+ events (route, direction) | P16 dir 0: 39.3% of 56 events |
| Highest OTP, 50+ events (route, direction) | A58 dir 0: 96.6% of 89 events |
| Headway Pairs | 7,024 |
| Bunched % | 3.1% |
| Headway On-Time % (Frequent) | 72.1% |
| Most bunched, 30+ pairs | D60 dir 0: 21.7% of 60 pairs |

Hours 10 and 14 have few events (137 and 36), because the window starts at 11:00 AM and
ends at 2:00 PM. Their OTP values describe only the trips that crossed the window edge.
The route and direction rows above come from `otp_by_route.csv`, which splits by
direction; put `direction_id` in the visual to match them.
