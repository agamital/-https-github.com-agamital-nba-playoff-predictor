"""
sync_worker.py — Railway background-worker alternative to APScheduler.

Use this when deploying as a Railway "Worker" service (no web port needed).
Set the start command to:  python sync_worker.py

The script runs _standings_sync_job() immediately on start, then sleeps 6 hours
and repeats.  It stops automatically after _STANDINGS_SYNC_CUTOFF (April 20 2026).
"""

import time
import sys
import os
from datetime import datetime

# ---------------------------------------------------------------------------
# Cutoff: stop syncing after end-of-day April 20 2026.
# Keep in sync with main.py:_STANDINGS_SYNC_CUTOFF.
# ---------------------------------------------------------------------------
_CUTOFF = datetime(2026, 4, 21, 0, 0, 0)   # exclusive — stops ON April 21
_INTERVAL_SECONDS = 12 * 60 * 60           # 12 hours (2x/day to conserve RapidAPI quota)

# Ensure the backend package is importable when run directly
sys.path.insert(0, os.path.dirname(__file__))

from main import _standings_sync_job, NBA_API_AVAILABLE  # noqa: E402


def run():
    print(f"[Worker] Standings sync worker started — runs every {_INTERVAL_SECONDS // 3600}h (2x/day) until {_CUTOFF.date()}")

    if not NBA_API_AVAILABLE:
        print("[Worker] nba_api not installed — worker cannot fetch standings. Exiting.")
        sys.exit(1)

    while True:
        now = datetime.utcnow()
        if now >= _CUTOFF:
            print(f"[Worker] Regular season ended ({_CUTOFF.date()}). Entering static mode — worker exiting.")
            sys.exit(0)

        print(f"[Worker] Running sync at {now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        try:
            ok = _standings_sync_job()
            print(f"[Worker] Sync {'succeeded' if ok else 'finished (no update)'}")
        except Exception as e:
            print(f"[Worker] Sync error: {e}")

        next_run = datetime.utcnow()
        sleep_until = now.replace(second=0, microsecond=0)
        # Sleep exactly _INTERVAL_SECONDS from the start of this run
        elapsed = (datetime.utcnow() - now).total_seconds()
        sleep_for = max(0, _INTERVAL_SECONDS - elapsed)
        print(f"[Worker] Next sync in {sleep_for / 3600:.1f}h — sleeping…")
        time.sleep(sleep_for)


if __name__ == "__main__":
    run()
