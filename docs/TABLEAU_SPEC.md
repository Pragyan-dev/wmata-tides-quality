# Dashboard spec (Tableau)

This spec builds the same dashboard as `DASHBOARD_SPEC.md` in Tableau, which runs on macOS.
It uses the same CSV extracts. Definitions (on-time window, headway rule, bunching, quality
levels) and their sources are in `DASHBOARD_SPEC.md` section 1, and the check values are in
section 7 of that file. Both apply here unchanged.

## 1. Software

- **Tableau Public** (free, macOS and Windows). Workbooks save only to your public Tableau
  Public profile, not to your disk. The data here is public WMATA data, so this is fine.
- **Tableau Desktop** can save `.twbx` files locally. Students can usually get a free license
  through Tableau for Students.

Create the extracts first:

```bash
scripts/build_snapshot.sh
```

```bash
.venv/bin/python scripts/export_powerbi.py
```

The files land in `data/powerbi/`. The folder name is historical; the CSVs are plain and
work in any tool.

## 2. Data source

### 2.1 Connect

1. Connect, To a File, Text file, and pick `data/powerbi/fact_timepoint_events.csv`.
2. In the data source pane, drag these onto the canvas so Tableau creates **relationships**
   (the noodle, not a join):
   - `dim_routes.csv`, related on `route_id = route_id`
   - `dim_stops.csv`, related on `stop_id = stop_id`
3. Add a second data source the same way for `fact_headways.csv`, related to
   `dim_routes.csv` on `route_id` and `dim_stops.csv` on `stop_id`.
4. Add `data_quality.csv`, `dq_otp_sensitivity.csv`, `dq_otp_filter_effects.csv`, and
   `dq_otp_sensitivity_by_route.csv` as separate single-table data sources. They are
   already aggregated.

Keep every connection **Live**, or use an extract; both work at this size.

### 2.2 Data types

Tableau guesses types from the first rows. Fix these in the data source pane by clicking
the type icon above each column:

| Columns | Type | Why |
|---|---|---|
| `route_id`, `stop_id`, `stop_code`, `trip_id*`, `prev_trip_id`, `vehicle_id` | String | IDs like `D6X` must stay text, and both sides of a relationship need the same type |
| `scheduled_ts`, `actual_ts` | Date & Time | Local America/New_York time, no offset |
| `service_date` | Date | |
| `is_*`, `passes_*`, `has_coverage_gap`, `overlaps_feed_gap`, `cut_by_window`, `too_few_pings`, `is_complete`, `is_frequent`, `is_bunched`, `is_headway_on_time`, `is_timepoint` | Boolean | The files write `true` / `false` |
| `stop_lat` | Number (decimal), Geographic Role: Latitude | |
| `stop_lon` | Number (decimal), Geographic Role: Longitude | |
| `direction_id`, `scheduled_hour` | Number (whole), then **Convert to Dimension** | Used as categories |

If Tableau leaves a Boolean column as String, the calculated fields below still work if
you replace `[is_on_time]` with `[is_on_time] = "true"`.

## 3. Parameter and calculated fields

All of these go in the `fact_timepoint_events` data source unless noted.

**Parameter `Quality Level`:** data type String, allowable values List: `Loose`, `Moderate`,
`Strict`. Current value `Moderate`. Right-click it and Show Parameter on every dashboard.

```
// Quality Rank
// 3 = strict, 2 = moderate, 1 = loose (has a time), 0 = no time inferred
IF [passes_strict] THEN 3
ELSEIF [passes_moderate] THEN 2
ELSEIF NOT ISNULL([actual_ts]) THEN 1
ELSE 0
END
```

```
// Min Rank
CASE [Quality Level]
    WHEN "Loose" THEN 1
    WHEN "Moderate" THEN 2
    WHEN "Strict" THEN 3
END
```

```
// In Quality Level
[Quality Rank] >= [Min Rank]
```

Put **In Quality Level = True** on the Filters shelf of every OTP sheet, then right-click
it, Apply to Worksheets, All Using This Data Source. Every OTP measure below then counts
only events at the selected level.

```
// Timepoint Events
COUNT([trip_id_performed])
```

```
// On-Time Events
SUM(IIF([is_on_time], 1, 0))
```

```
// OTP %
SUM(IIF([is_on_time], 1, 0)) / COUNT([trip_id_performed])
```

```
// Early %
SUM(IIF([is_early], 1, 0)) / COUNT([trip_id_performed])
```

```
// Late %
SUM(IIF([is_late], 1, 0)) / COUNT([trip_id_performed])
```

```
// Median Deviation (min)
MEDIAN([deviation_s]) / 60
```

```
// Trips
COUNTD([trip_id_performed])
```

```
// Timepoint Coverage %   (do NOT put the In Quality Level filter on this sheet)
SUM(IIF(NOT ISNULL([actual_ts]), 1, 0)) / COUNT([trip_id_performed])
```

In the `fact_headways` data source:

```
// Headway Pairs
COUNT([trip_id])
```

```
// Bunched %
SUM(IIF([is_bunched], 1, 0)) / COUNT([trip_id])
```

```
// Headway On-Time % (Frequent)
SUM(IIF([is_frequent] AND [is_headway_on_time], 1, 0)) / SUM(IIF([is_frequent], 1, 0))
```

```
// Scheduled Headway (min)
[scheduled_headway_s] / 60
```

```
// Actual Headway (min)
[actual_headway_s] / 60
```

In the `data_quality` data source:

```
// DQ Flagged %
SUM([n_flagged]) / SUM([n_checked])
```

Format every `%` field as Percentage with 1 decimal place (right-click, Default Properties,
Number Format).

## 4. Sheets

Build each sheet, then place them on the dashboards in section 5.

| Sheet | Data source | Build |
|---|---|---|
| KPI OTP | timepoint events | Text mark; OTP % on Text. Make one sheet each for Early %, Late %, Timepoint Events, Trips |
| KPI Coverage | timepoint events | Text mark; Timepoint Coverage %. No quality filter on this sheet |
| OTP by Hour | timepoint events | Columns: `scheduled_hour` (dimension); Rows: OTP %; Bar mark; Timepoint Events on Tooltip |
| Route Mix | timepoint events | Rows: `route_short_name`; Columns: Measure Values with On-Time Events, plus `SUM(IIF([is_early],1,0))` and `SUM(IIF([is_late],1,0))`; Bar mark, Analysis, Percentage of, Table Across. Filter Top 15 by Timepoint Events. Sort by OTP % ascending |
| Route Table | timepoint events | Rows: `route_label`, `direction_id`; Measure Values: Trips, Timepoint Events, OTP %, Early %, Late %, Median Deviation (min). Filter Timepoint Events at least 30 |
| Route Hour Heatmap | timepoint events | Rows: `route_short_name`; Columns: `scheduled_hour`; Square mark; Color: OTP %, Red-Green Diverging, center 0.77 |
| Route Scatter | timepoint events | Columns: Timepoint Events; Rows: OTP %; Detail: `route_short_name`; Circle mark. Filter Timepoint Events at least 30 |
| Stop Map | timepoint events | Double-click `stop_lon` then `stop_lat` (Tableau draws a map); Detail: `stop_id`; Size: Timepoint Events; Color: OTP % diverging centered at 0.77; Tooltip: `stop_name`, OTP %, Late %. Filter `is_timepoint` = True |
| Stop Table | timepoint events | Rows: `stop_name`; Measure Values: Timepoint Events, OTP %, Late %, Median Deviation (min). Filter Timepoint Events at least 20; sort OTP % ascending |
| KPI Headways | headways | Text marks for Headway Pairs, Bunched %, Headway On-Time % (Frequent), `MEDIAN([headway_ratio])` |
| Bunching by Route | headways | Rows: `route_short_name`; Columns: Bunched %; Bar mark. Filters: Headway Pairs at least 30; Top 10 by Bunched % |
| Headway Scatter | headways | Columns: `AVG(Scheduled Headway (min))`; Rows: `AVG(Actual Headway (min))`; Detail: `trip_id`, `stop_id` (one mark per pair). Analysis, Reference Line on Rows, constant 2, label "bunching threshold" |
| Headway Ratio Histogram | headways | Right-click `headway_ratio`, Create, Bins, size 0.25. Columns: the bin; Rows: Headway Pairs |
| DQ Checks | data_quality | Rows: `check_level`, `check_name`; Measure Values: `SUM(n_checked)`, `SUM(n_flagged)`, DQ Flagged % |
| Sensitivity | dq_otp_sensitivity | Rows: `filter_level` (sort by `level_order`); Measure Values: `timepoint_events`, `pct_of_loose_events`, `otp_pct`, `otp_change_vs_loose_pp` |
| Filter Effects | dq_otp_filter_effects | Rows: `filter_name`; Columns: `otp_change_pp`; Bar mark; labels on |
| Route Sensitivity | dq_otp_sensitivity_by_route | Columns: `loose_otp_pct`; Rows: `strict_otp_pct`; Size: `strict_events`; Detail: `route_id`. Add a calculated field equal to `[loose_otp_pct]` on a dual axis (Line mark, synchronized) to draw y = x |
| Off-Route Routes | data_quality | Filter `check_name` = `off_route` and `route_id` not `(no trip)`; Rows: `route_id`; Columns: `pct_flagged`; sort descending |

The OTP and quality sheets need the `In Quality Level` filter from section 3. Headway sheets
are built at the moderate level only, so they get no quality filter; add a caption saying
so.

## 5. Dashboards

Use size Automatic, or Fixed 1366 x 768. Show the `Quality Level` parameter control in the
top right of every dashboard except Data Quality.

| Dashboard | Sheets |
|---|---|
| Overview | KPI OTP, Early %, Late %, Timepoint Events, Trips, Coverage across the top; OTP by Hour; Route Mix; a Text object with the OTP definition and sources from `DASHBOARD_SPEC.md` section 1 |
| Routes | Route Table; Route Hour Heatmap; Route Scatter. Use Route Table as a filter (Dashboard, Actions, Filter) for the other two |
| Stops | Stop Map (large); Stop Table. Highlight action from the table to the map |
| Headways and Bunching | KPI Headways; Bunching by Route; Headway Scatter; Headway Ratio Histogram; a caption saying headways are at the moderate quality level |
| Data Quality | DQ Checks; Sensitivity; Filter Effects; Route Sensitivity; Off-Route Routes |
| About | Text only: the project question, the data source and window, the limitation that a public real-time feed is a stand-in for an agency's internal AVL data, which is what TIDES is designed for, and links to `METHODOLOGY.md` and `DATA_QUALITY.md` |

To present them in order, add a **Story** with one story point per dashboard.

## 6. Check your numbers

Use the check values in `DASHBOARD_SPEC.md` section 7. For example, with `Quality Level` set
to Moderate, KPI OTP should show 76.4% on 10,713 timepoint events, and with Strict it
should show 77.7% on 2,068. If a number is off, the usual cause is a Boolean column read as
String (section 2.2) or the `In Quality Level` filter missing from a sheet.
