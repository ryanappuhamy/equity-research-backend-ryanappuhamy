"""
Entry point for the weekly portfolio brief scheduler.

Keeps the scheduler running in the background, executing the weekly brief
job every Monday at 08:00 local time.

Usage:
    python run_scheduler.py
    python run_scheduler.py --now   # run once immediately, then keep scheduling
"""

import argparse
import time

import schedule

import scheduler as weekly_scheduler

POLL_INTERVAL_SECONDS = 60


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly portfolio brief scheduler")
    parser.add_argument(
        "--now",
        action="store_true",
        help="Run the weekly brief job immediately on startup",
    )
    args = parser.parse_args()

    weekly_scheduler.setup_schedule()

    if args.now:
        print("Scheduler: running weekly brief now (--now)")
        weekly_scheduler.run_weekly_brief()

    print(
        f"Scheduler running — weekly brief every Monday at 08:00 "
        f"(polling every {POLL_INTERVAL_SECONDS}s). Ctrl+C to stop."
    )

    try:
        while True:
            schedule.run_pending()
            time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nScheduler stopped.")


if __name__ == "__main__":
    main()
