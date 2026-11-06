"""`python -m collector rows-per-minute --date YYYY-MM-DD`: rows per minute from Parquet."""

import duckdb

from collector import config


def rows_per_minute(date: str) -> list[tuple]:
    """(minute, vp_fetches, vp_rows, tu_fetches, tu_rows) for each local minute with data."""
    con = duckdb.connect()
    for feed in config.FEEDS:
        files = sorted((config.PARSED_DIR / feed / f"date={date}").glob("*.parquet"))
        if not files:
            con.execute(f"CREATE TABLE {feed} (fetch_ts_utc BIGINT)")
            continue
        con.read_parquet([str(p) for p in files]).create_view(feed)

    return con.execute(
        """
        WITH t AS (
            SELECT 'vp' AS feed, fetch_ts_utc FROM vehicle_positions
            UNION ALL
            SELECT 'tu', fetch_ts_utc FROM trip_updates
        )
        SELECT strftime(make_timestamp(fetch_ts_utc * 1000000)
                        AT TIME ZONE 'UTC' AT TIME ZONE ?, '%H:%M') AS minute,
               count(DISTINCT fetch_ts_utc) FILTER (WHERE feed = 'vp') AS vp_fetches,
               count(*) FILTER (WHERE feed = 'vp') AS vp_rows,
               count(DISTINCT fetch_ts_utc) FILTER (WHERE feed = 'tu') AS tu_fetches,
               count(*) FILTER (WHERE feed = 'tu') AS tu_rows
        FROM t GROUP BY minute ORDER BY minute
        """,
        [str(config.AGENCY_TZ)],
    ).fetchall()


def print_rows_per_minute(date: str) -> None:
    result = rows_per_minute(date)
    if not result:
        print(f"no parsed data for {date}")
        return
    print(f"{'minute':<8}{'vp fetches':>11}{'vp rows':>9}{'tu fetches':>12}{'tu rows':>9}")
    for minute, vpf, vpr, tuf, tur in result:
        print(f"{minute:<8}{vpf:>11}{vpr:>9}{tuf:>12}{tur:>9}")
    print(f"\n{len(result)} minutes with data. A full minute has 2 fetches per feed.")
