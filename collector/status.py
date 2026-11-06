"""`python -m collector status`: is it running, and is data arriving?"""

import os
import time

import duckdb

from collector import config
from collector.storage import local_date


def process_alive() -> int | None:
    """PID if the collector process is running, else None."""
    if not config.PID_FILE.exists():
        return None
    pid = int(config.PID_FILE.read_text().strip())
    try:
        os.kill(pid, 0)  # signal 0 only checks that the process exists
    except ProcessLookupError:
        return None
    except PermissionError:
        return pid
    return pid


def disk_bytes(since_ts: int | None = None, date: str | None = None) -> int:
    """Bytes of raw .pb and parsed Parquet files. Filter by local date or by epoch."""
    total = 0
    raw_files = list(config.RAW_DIR.glob("*/*_url/*.pb"))
    parsed_files = list(config.PARSED_DIR.glob("*/*/*.parquet"))
    files = raw_files + parsed_files
    for path in files:
        epoch = int(path.stem.split("-")[0])
        if since_ts is not None and epoch < since_ts:
            continue
        if date is not None and local_date(epoch) != date:
            continue
        total += path.stat().st_size
    return total


def print_status() -> None:
    now = int(time.time())
    pid = process_alive()
    print(f"collector: {'RUNNING, pid ' + str(pid) if pid else 'NOT RUNNING'}")

    if not config.FETCH_LOG.exists():
        print("no fetches logged yet")
        return

    con = duckdb.connect()
    con.read_csv(str(config.FETCH_LOG), header=True).create_view("f")

    print("\nlast 60 minutes, per feed:")
    rows = con.execute(
        """
        SELECT feed,
               count(*) AS fetches,
               count(*) FILTER (WHERE http_status = 200) AS ok,
               count(*) FILTER (WHERE error IS NOT NULL) AS errors,
               count(*) FILTER (WHERE entity_count = 0) AS empty,
               round(avg(bytes) FILTER (WHERE http_status = 200) / 1024) AS avg_kb,
               ? - max(fetch_ts_utc) FILTER (WHERE http_status = 200) AS last_ok_age_s
        FROM f
        WHERE fetch_ts_utc >= ? - 3600
        GROUP BY feed ORDER BY feed
        """,
        [now, now],
    ).fetchall()
    print(
        f"  {'feed':<18}{'fetches':>8}{'ok':>6}{'errors':>8}{'empty':>7}{'avg KB':>8}"
        f"{'last ok':>10}"
    )
    for feed, fetches, ok, errors, empty, avg_kb, age in rows:
        age_txt = f"{age}s ago" if age is not None else "never"
        print(
            f"  {feed:<18}{fetches:>8}{ok:>6}{errors:>8}{empty:>7}{avg_kb or 0:>8.0f}{age_txt:>10}"
        )

    print("\nrows written per minute, last 10 minutes (local time):")
    per_minute = con.execute(
        """
        SELECT strftime(make_timestamp(fetch_ts_utc * 1000000)
                        AT TIME ZONE 'UTC' AT TIME ZONE ?, '%H:%M') AS minute,
               sum(rows_written) FILTER (WHERE feed = 'vehicle_positions') AS vp,
               sum(rows_written) FILTER (WHERE feed = 'trip_updates') AS tu
        FROM f
        WHERE fetch_ts_utc >= ? - 600 AND feed != 'static'
        GROUP BY minute ORDER BY minute
        """,
        [str(config.AGENCY_TZ), now],
    ).fetchall()
    print(f"  {'minute':<8}{'vehicle_positions':>19}{'trip_updates':>14}")
    for minute, vp, tu in per_minute:
        print(f"  {minute:<8}{vp or 0:>19}{tu or 0:>14}")

    today = local_date(now)
    print(f"\ndisk used today ({today}): {disk_bytes(date=today) / 1e6:.1f} MB (raw + parsed)")

    # Project from polling cycles actually completed in the last hour, not from
    # clock time, so the number is right even a few minutes after start.
    cycles = con.execute(
        "SELECT count(*) FROM f WHERE feed = 'vehicle_positions' AND http_status = 200 "
        "AND fetch_ts_utc >= ? - 3600",
        [now],
    ).fetchall()[0][0]
    if cycles:
        last_hour = disk_bytes(since_ts=now - 3600)
        per_day = last_hour / cycles * (86400 / config.POLL_SECONDS)
        print(
            f"last 60 minutes: {last_hour / 1e6:.1f} MB over {cycles} polling cycles, "
            f"projected {per_day / 1e9:.2f} GB/day"
        )
        print("  (assumes every cycle today looks like recent ones; overnight service is lighter)")
