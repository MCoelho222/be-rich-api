"""`python -m app.jobs` starts the scheduler; `python -m app.jobs run <job>` runs one job."""

import argparse
import logging
import sys

from app.core.config import get_settings
from app.jobs.runner import JOBS, run_job, serve


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.jobs", description="Be Rich scheduled jobs")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="run one job now and exit")
    run.add_argument("job", choices=sorted(JOBS))
    sub.add_parser("list", help="list the jobs and their schedules")
    args = parser.parse_args(argv)

    logging.basicConfig(level=get_settings().log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.command == "run":
        return 0 if run_job(args.job) is not None else 1
    if args.command == "list":
        for job in JOBS.values():
            print(f"{job.name:20} {job.trigger}")
        return 0
    serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
