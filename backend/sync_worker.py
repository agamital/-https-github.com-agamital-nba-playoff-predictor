"""
sync_worker.py — Railway background-worker alternative to APScheduler.

Use this when deploying as a Railway "Worker" service (no web port needed).
Set the start command to:  python sync_worker.py

Runs TWO loops in parallel threads:
  • 04:00 UTC  — full sync chain (boxscores + standings + play-in matchups + results)
  • 06:00, 07:00, 08:30 UTC — results-only catch-up so late-finishing play-in /
    playoff games are promoted within hours, not 24 h.
"""

import time
import sys
import os
import threading
from datetime import datetime, timedelta

_STANDINGS_CUTOFF = datetime(2026, 4, 14, 0, 0, 0)  # standings stop after Apr 13 games

sys.path.insert(0, os.path.dirname(__file__))

from main import (  # noqa: E402
    _standings_sync_job, sync_daily_boxscores, refresh_playin_matchups,
    NBA_API_AVAILABLE,
)


def _seconds_until_next(hour: int, minute: int = 0) -> float:
    """Return seconds until the next occurrence of HH:MM UTC."""
    now = datetime.utcnow()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _run_results_catchup(label: str):
    """sync play-in + playoff results and provisional leaders."""
    try:
        from game_processor import (
            sync_playin_results_from_api, sync_playoff_results_from_api,
            sync_series_provisional_leaders,
        )
        pi = sync_playin_results_from_api('2026')
        print(f"[Results Catchup {label}] Play-In: "
              f"processed={pi.get('processed',0)} promoted={pi.get('promoted',0)} "
              f"errors={len(pi.get('errors',[]))}")
        po = sync_playoff_results_from_api('2026')
        print(f"[Results Catchup {label}] Playoff: "
              f"updated={po.get('updated',0)} completed={po.get('completed',0)}")
        pl = sync_series_provisional_leaders('2026')
        print(f"[Results Catchup {label}] Leaders: updated={pl.get('series_updated',0)}")
    except Exception as e:
        print(f"[Results Catchup {label}] ERROR: {type(e).__name__}: {e}")


def _daily_sync_loop():
    """Full sync chain — fires once per day at 04:00 UTC."""
    print("[Worker] Daily sync loop started — fires at 04:00 UTC")
    while True:
        secs = _seconds_until_next(4)
        print(f"[Worker/Daily] Next full sync in {secs/3600:.1f}h (at ~04:00 UTC)")
        time.sleep(secs)

        run_at = datetime.utcnow()
        print(f"[Daily Auto-Sync] ── starting ({run_at.strftime('%Y-%m-%d %H:%M')} UTC) ──")

        for _bx_date in (None, run_at.strftime('%Y-%m-%d')):
            _label = "yesterday" if _bx_date is None else "today"
            try:
                bx = sync_daily_boxscores(date_str=_bx_date, season='2026',
                                          force=True, triggered_by='daily_auto')
                print(f"[Daily Auto-Sync] Boxscore ({_label}) — "
                      f"games={bx.get('games_processed',0)} players={bx.get('players_upserted',0)}")
            except Exception as e:
                print(f"[Daily Auto-Sync] Boxscore ({_label}) ERROR: {type(e).__name__}: {e}")

        try:
            ok = _standings_sync_job()   # also calls generate_matchups() + refresh_playin_matchups()
            print(f"[Daily Auto-Sync] Standings {'ok' if ok else 'skipped/failed'}")
        except Exception as e:
            print(f"[Daily Auto-Sync] Standings ERROR: {e}")

        _run_results_catchup("04:00")
        print(f"[Daily Auto-Sync] ── complete ({datetime.utcnow().strftime('%H:%M')} UTC) ──")


def _results_catchup_loop():
    """Results-only catch-up — fires at 06:00, 07:00, 08:30 UTC each day."""
    _FIRE_TIMES = [(6, 0), (7, 0), (8, 30)]
    print(f"[Worker] Results catch-up loop started — fires at "
          f"{', '.join(f'{h:02d}:{m:02d}' for h,m in _FIRE_TIMES)} UTC")
    idx = 0
    while True:
        h, m = _FIRE_TIMES[idx % len(_FIRE_TIMES)]
        secs = _seconds_until_next(h, m)
        time.sleep(secs)
        label = f"{h:02d}:{m:02d}"
        print(f"[Results Catchup] Firing at {label} UTC")
        _run_results_catchup(label)
        idx += 1


def run():
    t1 = threading.Thread(target=_daily_sync_loop, daemon=True, name="daily-sync")
    t2 = threading.Thread(target=_results_catchup_loop, daemon=True, name="results-catchup")
    t1.start()
    t2.start()
    print("[Worker] Both loops running — Ctrl-C to stop")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("[Worker] Shutting down")


if __name__ == "__main__":
    run()
