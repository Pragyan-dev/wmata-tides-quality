"""Export the TIDES marts to CSV, write datapackage.json, and validate both.

    .venv/bin/python scripts/export_tides.py [--date YYYY-MM-DD] [--out data/tides]

Columns are written in the exact order of the official TIDES v1.0 schema. Schema
fields the public feed cannot supply are written as empty columns. The package
is then checked two ways:
  1. datapackage.json against tides-datapackage-profile.json (JSON Schema).
  2. every CSV against its table schema with frictionless: types, required
     fields, enums, ranges, and primary key uniqueness.
Exit code is 1 if either check finds an error.
"""

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

import duckdb
import jsonschema
from frictionless import Package

ROOT = Path(__file__).resolve().parent.parent
SPEC_DIR = ROOT / "spec" / "tides-v1.0"
TABLES = ["vehicle_locations", "trips_performed", "stop_visits"]
PROFILE_URL = (
    "https://raw.githubusercontent.com/TIDES-transit/TIDES/v1.0/spec/tides-datapackage-profile.json"
)


def column_sql(field: dict, available: set[str]) -> str:
    """SQL for one output column, formatted the way Table Schema expects."""
    name = field["name"]
    if name not in available:
        return f'NULL AS "{name}"'
    kind = field.get("type")
    if kind == "datetime":
        # ISO 8601 with UTC offset, for example 2026-11-06T10:19:38-05:00.
        # DuckDB's %z writes "-05", so add ":00" when the offset has no minutes.
        return (
            f"regexp_replace(strftime(\"{name}\", '%Y-%m-%dT%H:%M:%S%z'), "
            f"'([+-][0-9]{{2}})$', '\\1:00') AS \"{name}\""
        )
    if kind == "date":
        return f'strftime("{name}", \'%Y-%m-%d\') AS "{name}"'
    return f'"{name}"'


def export(con, out_dir: Path, date: str | None) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "schemas").mkdir(exist_ok=True)
    counts = {}
    for table in TABLES:
        schema = json.loads((SPEC_DIR / f"{table}.schema.json").read_text())
        shutil.copy(SPEC_DIR / f"{table}.schema.json", out_dir / "schemas")
        available = {r[0] for r in con.execute(f"DESCRIBE tides.{table}").fetchall()}
        columns = ", ".join(column_sql(f, available) for f in schema["fields"])
        where = "WHERE service_date = ?" if date else ""
        params = [date] if date else []
        rel = f"SELECT {columns} FROM tides.{table} {where} ORDER BY ALL"
        path = out_dir / f"{table}.csv"
        con.execute(f"COPY ({rel}) TO '{path}' (HEADER, DELIMITER ',')", params)
        counts[table] = con.execute(f"SELECT count(*) FROM ({rel})", params).fetchone()[0]
    return counts


def write_datapackage(out_dir: Path, date: str | None, counts: dict[str, int]) -> dict:
    span = date or "all collected dates"
    package = {
        "profile": PROFILE_URL,
        "name": "wmata-bus-tides" + (f"-{date}" if date else ""),
        "title": f"WMATA Metrobus TIDES from public GTFS-Realtime, {span}",
        "description": (
            "TIDES tables built from WMATA's public bus GTFS-Realtime feeds. Stop visit "
            "times are inferred from vehicle positions, not recorded by onboard AVL. "
            "See docs/METHODOLOGY.md."
        ),
        "agency": "Washington Metropolitan Area Transit Authority (WMATA)",
        "licenses": [{"name": "CC-BY-4.0", "path": "https://creativecommons.org/licenses/by/4.0/"}],
        "contributors": [{"title": "Pragyan", "role": "author"}],
        "resources": [
            {
                "profile": "tabular-data-resource",
                "name": table,
                "tides-table": table,
                "title": table.replace("_", " ").title(),
                "path": f"{table}.csv",
                "schema": f"schemas/{table}.schema.json",
                "format": "csv",
                "mediatype": "text/csv",
                "encoding": "utf-8",
            }
            for table in TABLES
        ],
    }
    (out_dir / "datapackage.json").write_text(json.dumps(package, indent=2) + "\n")
    return package


def validate(out_dir: Path, package: dict) -> dict[str, dict]:
    """Validate the package. Returns {"datapackage" or table name: {valid, rows, errors}}."""
    profile = json.loads((SPEC_DIR / "tides-datapackage-profile.json").read_text())
    results = {}
    try:
        jsonschema.validate(package, profile)
        results["datapackage"] = {"valid": True, "rows": None, "errors": {}}
        print("datapackage.json: valid against tides-datapackage-profile.json")
    except jsonschema.ValidationError as exc:
        results["datapackage"] = {"valid": False, "rows": None, "errors": {"profile": 1}}
        print(f"datapackage.json: INVALID: {exc.message}")

    report = Package(str(out_dir / "datapackage.json")).validate()
    for task in report.tasks:
        errors = dict(Counter(e.type for e in task.errors))
        rows = task.stats.get("rows")
        results[task.name] = {"valid": task.valid, "rows": rows, "errors": errors}
        status = "valid" if task.valid else "INVALID"
        print(f"{task.name}: {status}, {rows} rows checked, errors: {errors or 'none'}")
        for error in task.errors[:3]:
            print(f"    e.g. {error.message}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="service date YYYY-MM-DD (default: all dates)")
    parser.add_argument("--db", default=str(ROOT / "data" / "warehouse.duckdb"))
    parser.add_argument("--out", default=str(ROOT / "data" / "tides"))
    args = parser.parse_args()

    out_dir = Path(args.out) / (args.date or "all")
    con = duckdb.connect(args.db, read_only=True)
    con.execute("SET TimeZone = 'America/New_York'")
    counts = export(con, out_dir, args.date)
    for table, n in counts.items():
        print(f"wrote {n} rows to {out_dir / (table + '.csv')}")
    package = write_datapackage(out_dir, args.date, counts)
    results = validate(out_dir, package)
    sys.exit(0 if all(r["valid"] for r in results.values()) else 1)


if __name__ == "__main__":
    main()
