"""Command line: python -m collector {run,status,rows-per-minute,reparse}"""

import argparse
import time

from collector.storage import local_date


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m collector")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="poll the feeds until stopped")
    sub.add_parser("status", help="is the collector running, and is data arriving")
    today = local_date(int(time.time()))
    for name, help_text in [
        ("rows-per-minute", "rows per minute from parsed Parquet"),
        ("reparse", "rebuild Parquet from raw .pb files"),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--date", default=today, help="local date YYYY-MM-DD (default: today)")
    args = parser.parse_args()

    if args.command == "run":
        from collector.main import run

        run()
    elif args.command == "status":
        from collector.status import print_status

        print_status()
    elif args.command == "rows-per-minute":
        from collector.count import print_rows_per_minute

        print_rows_per_minute(args.date)
    elif args.command == "reparse":
        from collector.reparse import reparse

        reparse(args.date)


if __name__ == "__main__":
    main()
