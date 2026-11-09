"""Export the metrics and quality tables to CSV for Power BI.

    .venv/bin/python scripts/export_powerbi.py [--out data/powerbi]

Timestamps are written as local America/New_York time without an offset
(2026-11-06 10:15:42), which Power BI reads as Date/Time. Booleans are written as
true/false. docs/DASHBOARD_SPEC.md describes every table and how to model it.
"""

import argparse
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent

TABLES = {
    # fact tables
    "fact_timepoint_events": "metrics.timepoint_events",
    "fact_headways": "metrics.headways",
    # dimensions
    "dim_routes": "metrics.dim_routes",
    "dim_stops": "metrics.dim_stops",
    # pre-aggregated metrics (for checking DAX measures)
    "otp_by_route": "metrics.otp_by_route",
    "otp_by_stop": "metrics.otp_by_stop",
    "otp_by_hour": "metrics.otp_by_hour",
    "otp_by_route_hour": "metrics.otp_by_route_hour",
    "headway_by_route": "metrics.headway_by_route",
    # data quality
    "data_quality": "quality.data_quality",
    "dq_otp_sensitivity": "quality.dq_otp_sensitivity",
    "dq_otp_filter_effects": "quality.dq_otp_filter_effects",
    "dq_otp_sensitivity_by_route": "quality.dq_otp_sensitivity_by_route",
}


def select_sql(con, table: str) -> str:
    """SELECT that formats TIMESTAMPTZ columns as local time text."""
    columns = []
    for name, kind, *_ in con.execute(f"DESCRIBE {table}").fetchall():
        if kind == "TIMESTAMP WITH TIME ZONE":
            columns.append(f'strftime("{name}", \'%Y-%m-%d %H:%M:%S\') AS "{name}"')
        else:
            columns.append(f'"{name}"')
    return f"SELECT {', '.join(columns)} FROM {table} ORDER BY ALL"


def export_all(db: str, out: Path) -> dict[str, int]:
    """Write every table in TABLES to out/<name>.csv. Returns row counts."""
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(db, read_only=True)
    con.execute("SET TimeZone = 'America/New_York'")
    counts = {}
    for name, table in TABLES.items():
        con.execute(f"COPY ({select_sql(con, table)}) TO '{out / (name + '.csv')}' (HEADER)")
        counts[name] = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(ROOT / "data" / "warehouse.duckdb"))
    parser.add_argument("--out", default=str(ROOT / "data" / "powerbi"))
    args = parser.parse_args()

    out = Path(args.out)
    for name, rows in export_all(args.db, out).items():
        print(f"{rows:>8} rows  {out / (name + '.csv')}")


if __name__ == "__main__":
    main()
