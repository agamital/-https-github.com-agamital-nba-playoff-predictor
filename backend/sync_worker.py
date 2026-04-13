"""
sync_worker.py — Railway background-worker alternative to APScheduler.

Use this when deploying as a Railway "Worker" service (no web port needed).
Set the start command to:  python sync_worker.py

Runs the full sync chain at 04:00, 05:00, 06:00, 07:00, 08:00, 09:00 UTC
every day so play-in / playoff results and bracket advancements are picked up
within ~1 hour of a game finishing.
"""

import time
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from main import (  # noqa: E402
    _standings_sync_job, sync_daily_boxscores, refresh_playin_matchups,
    _auto_sync_leaders_actuals, NBA_API_AVAILABLE,
)

# Fire at these UTC hours each day
_SYNC_HOURS = (4, 5, 6, 7, 8, 9)


def _seconds_until_next_fire() -> tuple[float, int]:
    """Return (seconds_to_wait, target_hour) for the next scheduled fire time."""
    now = datetime.utcnow()
    candidates = []
    for h in _SYNC_HOURS:
        t = now.replace(hour=h, minute=0, second=0, microsecond=0)
        if t <= now:
            t += timedelta(days=1)
        candidates.append((t, h))
    candidates.sort()
    nxt, hr = candidates[0]
    return (nxt - now).total_seconds(), hr


def _run_full_chain():
    utc_now = datetime.utcnow()
    label = utc_now.strftime('%H:%M')
    print(f"[Auto-Sync {label}] ── starting full-chain sync ──")

    # Step 1 — Boxscores: yesterday + today
    for _bx_date in (None, utc_now.strftime('%Y-%m-%d')):
        _lbl = "yesterday" if _bx_date is None else "today"
        try:
            bx = sync_daily_boxscores(date_str=_bx_date, season='2026',
                                      force=True, triggered_by='auto_sync')
            print(f"[Auto-Sync {label}] Boxscore ({_lbl}) — "
                  f"games={bx.get('games_processed',0)} "
                  f"players={bx.get('players_upserted',0)}")
        except Exception as e:
            print(f"[Auto-Sync {label}] Boxscore ({_lbl}) ERROR: {type(e).__name__}: {e}")

    # Step 2 — Standings (also calls generate_matchups + refresh_playin_matchups)
    try:
        ok = _standings_sync_job()
        print(f"[Auto-Sync {label}] Standings — ok={ok}")
    except Exception as e:
        print(f"[Auto-Sync {label}] Standings ERROR: {type(e).__name__}: {e}")

    try:
        from game_processor import (
            sync_playin_results_from_api, sync_playoff_results_from_api,
            sync_series_provisional_leaders,
        )
        # Step 3 — Series leaders first so _finalize_series scores them when series completes
        pl = sync_series_provisional_leaders('2026')
        print(f"[Auto-Sync {label}] Leaders — updated={pl.get('series_updated',0)}")

        # Step 3b — Playoff Highs: MAX single-game stat across all playoff games
        la = _auto_sync_leaders_actuals('2026')
        if not la.get('skipped'):
            print(f"[Auto-Sync {label}] Playoff Highs — "
                  f"pts={la.get('actual',{}).get('scorer')} "
                  f"scored={la.get('predictions_scored',0)}")

        # Step 4 — Play-In results + bracket promotion
        pi = sync_playin_results_from_api('2026')
        print(f"[Auto-Sync {label}] Play-In — "
              f"processed={pi.get('processed',0)} promoted={pi.get('promoted',0)} "
              f"errors={len(pi.get('errors',[]))}")

        # Step 5 — Playoff results + bracket advancement + leader scoring
        po = sync_playoff_results_from_api('2026')
        print(f"[Auto-Sync {label}] Playoff — "
              f"updated={po.get('updated',0)} completed={po.get('completed',0)}")
    except Exception as e:
        print(f"[Auto-Sync {label}] Results ERROR: {type(e).__name__}: {e}")

    print(f"[Auto-Sync {label}] ── complete ({datetime.utcnow().strftime('%H:%M')} UTC) ──")


def run():
    print(f"[Worker] Full-chain sync worker started — fires at "
          f"{', '.join(f'{h:02d}:00' for h in _SYNC_HOURS)} UTC each day")

    while True:
        secs, next_hr = _seconds_until_next_fire()
        print(f"[Worker] Next sync in {secs/3600:.1f}h (at {next_hr:02d}:00 UTC) — sleeping…")
        time.sleep(secs)
        _run_full_chain()


if __name__ == "__main__":
    run()
