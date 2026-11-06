import importlib.util
from pathlib import Path

import duckdb

spec = importlib.util.spec_from_file_location(
    "export_tides", Path(__file__).resolve().parent.parent / "scripts" / "export_tides.py"
)
export_tides = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export_tides)


def test_missing_fields_become_empty_columns():
    sql = export_tides.column_sql({"name": "odometer", "type": "number"}, available={"speed"})
    assert sql == 'NULL AS "odometer"'


def test_datetime_written_as_iso_8601_with_full_offset():
    con = duckdb.connect()
    con.execute("SET TimeZone = 'America/New_York'")
    con.execute("CREATE TABLE t AS SELECT timestamptz '2026-11-06 15:15:42+00' AS event_timestamp")
    sql = export_tides.column_sql(
        {"name": "event_timestamp", "type": "datetime"}, {"event_timestamp"}
    )
    assert con.execute(f"SELECT {sql} FROM t").fetchone()[0] == "2026-11-06T10:15:42-05:00"


def test_date_written_as_iso_date():
    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT date '2026-11-06' AS service_date")
    sql = export_tides.column_sql({"name": "service_date", "type": "date"}, {"service_date"})
    assert con.execute(f"SELECT {sql} FROM t").fetchone()[0] == "2026-11-06"
