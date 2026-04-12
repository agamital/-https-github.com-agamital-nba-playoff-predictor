"""
sync_worker.py — Railway background-worker alternative to APScheduler.

Use this when deploying as a Railway "Worker" service (no web port needed).
Set the start command to:  python sync_worker.py

The script sleeps until 04:00 UTC, runs the full sync chain once, then sleeps
until the next 04:00 UTC.  After _STANDINGS_CUTOFF the standings step is skipped
automatically (main.py guards it), but boxscores + playoff results keep running.
"""

import time
import sys
import os
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Standings cutoff: regular season ended April 12 2026.
# main.py:_standings_sync_job() self-skips after this date — no code change needed here.
# The worker itself keeps running indefinitely for boxscores + playoff results.
# ---------------------------------------------------------------------------
_STANDINGS_CUTOFF = datetime(2026, 4, 13, 0, 0, 0)  # exclusive — standings stop ON April 13
_DAILY_SYNC_HOUR  = 4                                 # 04:00 UTC

# Ensure the backend package is importable when run directly
sys.path.insert(0, os.path.dirname(__file__))

from main import (  # noqa: E402
    _standings_sync_job, sync_daily_boxscores, refresh_playin_matchups,
    NBA_API_AVAILABLE,
)


def _seconds_until_next_04utc() -> float:
    """Return seconds until the next 04:00 UTC wall-clock time."""
    now  = datetime.utcnow()
    next_run = now.replace(hour=_DAILY_SYNC_HOUR, minute=0, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    return (next_run - now).total_seconds()


def run():
    print(f"[Worker] Daily Auto-Sync worker started — fires at 04:00 UTC "
          f"(standings skip after {_STANDINGS_CUTOFF.date()}, boxscores run indefinitely)")

    while True:
        now = datetime.utcnow()

        # ── Sleep until 04:00 UTC ────────────────────────────────────────
        sleep_sec = _seconds_until_next_04utc()
        print(f"[Worker] Next Daily Auto-Sync in {sleep_sec / 3600:.1f}h "
              f"(at ~04:00 UTC) — sleeping…")
        time.sleep(sleep_sec)

        # ── Full sync chain ──────────────────────────────────────────────
        run_at = datetime.utcnow()
        print(f"[Daily Auto-Sync] ── Worker: starting daily full-chain sync "
              f"({run_at.strftime('%Y-%m-%d %H:%M')} UTC) ──")

        # Step 1 — Boxscores: yesterday + today
        for _bx_date in (None, run_at.strftime('%Y-%m-%d')):
            _label = "yesterday" if _bx_date is None else "today"
            try:
                bx = sync_daily_boxscores(date_str=_bx_date, season='2026',
                                          force=True, triggered_by='daily_auto')
                print(f"[Daily Auto-Sync] Boxscore ({_label}) — "
                      f"games={bx.get('games_processed',0)} "
                      f"players={bx.get('players_upserted',0)} "
                      f"errors={len(bx.get('errors',[]))}")
            except Exception as e:
                print(f"[Daily Auto-Sync] Boxscore ({_label}) ERROR: {type(e).__name__}: {e}")

        # Step 2 — Standings + player stats
        try:
            ok = _standings_sync_job()
            print(f"[Daily Auto-Sync] Standings sync {'succeeded' if ok else 'finished (no update)'}")
        except Exception as e:
            print(f"[Daily Auto-Sync] Standings sync ERROR: {e}")

        # Step 3 — Play-in matchups
        try:
            pim = refresh_playin_matchups('2026')
            print(f"[Daily Auto-Sync] Playin matchups — "
                  f"updated={len(pim.get('updated',[]))} skipped={len(pim.get('skipped',[]))}")
        except Exception as e:
            print(f"[Daily Auto-Sync] Playin matchups ERROR: {e}")

        # Step 4 — Play-in + playoff results (import lazily to avoid circular issues)
        try:
            from game_processor import (
                sync_playin_results_from_api, sync_playoff_results_from_api,
                sync_series_provisional_leaders,
            )
            pi = sync_playin_results_from_api('2026')
            print(f"[Daily Auto-Sync] Playin results — processed={pi.get('processed',0)}")
            po = sync_playoff_results_from_api('2026')
            print(f"[Daily Auto-Sync] Playoff results — updated={po.get('updated',0)}")
            pl = sync_series_provisional_leaders('2026')
            print(f"[Daily Auto-Sync] Provisional leaders — updated={pl.get('series_updated',0)}")
        except Exception as e:
            print(f"[Daily Auto-Sync] Results sync ERROR: {e}")

        print(f"[Daily Auto-Sync] ── Worker: complete "
              f"({datetime.utcnow().strftime('%H:%M')} UTC) ──")


if __name__ == "__main__":
    run()
