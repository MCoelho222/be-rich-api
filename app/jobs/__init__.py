"""Scheduled jobs (specs/operations.md §2).

Every job is idempotent, takes its inputs explicitly (database session, the
current time, external clients) and returns counts for the run log.
Run the scheduler with `python -m app.jobs`, or one job with
`python -m app.jobs run <job>`.
"""
