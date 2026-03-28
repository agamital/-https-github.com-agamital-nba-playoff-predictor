"""
game_processor.py — Bracket automation infrastructure.

Provides two public functions:

  check_game_winner(game_id)
      Looks up a play-in game or playoff series by ID, verifies it is
      finished, and returns the winning team's ID.  Returns None if the
      game is not yet complete or ends in a tie.

  promote_team_in_bracket(winner_id, current_stage, season='2026')
      Given a winner and the stage they just won, determines where they
      belong next in the bracket and calls the appropriate main.py helper
      to advance them (or logs a placeholder if automation is not yet wired).

Designed to be imported by main.py or called from an admin endpoint.
All DB access goes through main.get_db_conn() so connection pooling and
credentials stay in one place.

Game stage constants
--------------------
STAGE_PLAYIN_7V8       — Play-In Game 1 (7 seed vs 8 seed)
STAGE_PLAYIN_9V10      — Play-In Game 2 (9 seed vs 10 seed)
STAGE_PLAYIN_ELIM      — Play-In Game 3 (elimination, winner → #8 seed)
STAGE_FIRST_ROUND      — Playoff First Round
STAGE_CONF_SEMIS       — Conference Semifinals
STAGE_CONF_FINALS      — Conference Finals
STAGE_NBA_FINALS       — NBA Finals
"""

import os
import sys

# Make main.py importable when this module is run directly
sys.path.insert(0, os.path.dirname(__file__))

# ---------------------------------------------------------------------------
# Stage constants — used as the current_stage argument
# ---------------------------------------------------------------------------
STAGE_PLAYIN_7V8   = "7v8"
STAGE_PLAYIN_9V10  = "9v10"
STAGE_PLAYIN_ELIM  = "elimination"
STAGE_FIRST_ROUND  = "First Round"
STAGE_CONF_SEMIS   = "Conference Semifinals"
STAGE_CONF_FINALS  = "Conference Finals"
STAGE_NBA_FINALS   = "NBA Finals"

# Ordered playoff progression used by promote_team_in_bracket
_PLAYOFF_NEXT = {
    STAGE_FIRST_ROUND: STAGE_CONF_SEMIS,
    STAGE_CONF_SEMIS:  STAGE_CONF_FINALS,
    STAGE_CONF_FINALS: STAGE_NBA_FINALS,
    STAGE_NBA_FINALS:  None,   # champion — no next stage
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_db():
    """Return a live psycopg2 connection via main.get_db_conn()."""
    from main import get_db_conn
    return get_db_conn()


def _log(msg: str):
    from datetime import datetime
    print(f"[GameProcessor {datetime.utcnow().strftime('%H:%M:%S')} UTC] {msg}")


# ---------------------------------------------------------------------------
# check_game_winner
# ---------------------------------------------------------------------------

def check_game_winner(game_id: int) -> int | None:
    """
    Check whether a play-in game OR playoff series is finished and return the
    winning team's ID.

    Lookup order:
      1. playin_games table  (status = 'completed', winner_id set)
      2. series table        (status = 'completed', winner_team_id set)

    Returns:
      int   — winning team_id  if game is completed and has a winner
      None  — if game is not finished, is tied, or cannot be found

    This function never raises — errors are logged and None is returned.
    """
    conn = None
    try:
        conn = _get_db()
        c = conn.cursor()

        # ── Check play-in games first ────────────────────────────────────
        c.execute(
            "SELECT status, winner_id, team1_id, team1_score, team2_id, team2_score "
            "FROM playin_games WHERE id = %s",
            (game_id,)
        )
        row = c.fetchone()
        if row:
            status, winner_id, t1_id, t1_score, t2_id, t2_score = row
            _log(f"play-in game {game_id}: status={status} winner_id={winner_id} "
                 f"score={t1_score}-{t2_score}")

            if status != 'completed':
                _log(f"Game {game_id} not finished (status='{status}') — no winner returned")
                return None

            # If winner_id already stored, trust it
            if winner_id:
                return int(winner_id)

            # Fall back to score comparison if winner_id was not stored
            if t1_score is not None and t2_score is not None:
                s1, s2 = int(t1_score), int(t2_score)
                if s1 == s2:
                    _log(f"Game {game_id} ended in a tie ({s1}-{s2}) — no promotion")
                    return None
                return int(t1_id) if s1 > s2 else int(t2_id)

            _log(f"Game {game_id} completed but scores/winner missing — no winner returned")
            return None

        # ── Check playoff series ─────────────────────────────────────────
        c.execute(
            "SELECT status, winner_team_id, home_team_id, away_team_id "
            "FROM series WHERE id = %s",
            (game_id,)
        )
        row = c.fetchone()
        if row:
            status, winner_id, home_id, away_id = row
            _log(f"series {game_id}: status={status} winner_team_id={winner_id}")

            if status != 'completed':
                _log(f"Series {game_id} not finished (status='{status}') — no winner returned")
                return None
            if winner_id:
                return int(winner_id)

            _log(f"Series {game_id} completed but winner_team_id missing")
            return None

        _log(f"Game/series with id={game_id} not found in DB")
        return None

    except Exception as e:
        _log(f"ERROR in check_game_winner({game_id}): {type(e).__name__}: {e}")
        return None
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


# ---------------------------------------------------------------------------
# promote_team_in_bracket
# ---------------------------------------------------------------------------

def promote_team_in_bracket(
    winner_id: int,
    current_stage: str,
    season: str = '2026',
    conference: str | None = None,
) -> dict:
    """
    Given a winner and the stage they just completed, advance them to the
    correct next slot in the bracket.

    Play-In stages trigger the existing main.py helpers:
      7v8 winner  → #7 seed (R1 Group B vs #2 seed)
      9v10 winner → feeds into Game 3 (elimination)
      elimination winner → #8 seed (R1 Group A vs #1 seed)

    Playoff stages log the next matchup (full automation wired via
    main._try_advance_bracket which is already called by set_series_result).

    Returns a dict with:
      promoted   bool   — True if promotion action was taken
      next_stage str    — the stage the team moves into (or 'Champion')
      message    str    — human-readable log of what happened
      winner_id  int    — echoed back for convenience
    """
    _log(f"promote_team_in_bracket: winner={winner_id} stage='{current_stage}' season={season}")

    # ── Safety: reject None / invalid winner ────────────────────────────
    if not winner_id:
        msg = "No winner_id provided — promotion aborted"
        _log(msg)
        return {"promoted": False, "next_stage": None, "message": msg, "winner_id": winner_id}

    # ── Play-In stages ───────────────────────────────────────────────────
    if current_stage in (STAGE_PLAYIN_7V8, STAGE_PLAYIN_9V10, STAGE_PLAYIN_ELIM):
        return _promote_from_playin(winner_id, current_stage, season, conference)

    # ── Playoff stages ────────────────────────────────────────────────────
    if current_stage in _PLAYOFF_NEXT:
        return _promote_from_playoff(winner_id, current_stage, season)

    msg = f"Unknown stage '{current_stage}' — no promotion logic defined"
    _log(msg)
    return {"promoted": False, "next_stage": None, "message": msg, "winner_id": winner_id}


def _promote_from_playin(winner_id: int, stage: str, season: str, conference: str | None) -> dict:
    """
    Delegate play-in promotion to main._try_create_r1_from_playin and
    main._try_create_playin_game3, which are already idempotent.
    """
    try:
        from main import get_db_conn, _try_create_r1_from_playin, _try_create_playin_game3
    except ImportError as e:
        msg = f"Could not import main helpers: {e}"
        _log(msg)
        return {"promoted": False, "next_stage": None, "message": msg, "winner_id": winner_id}

    conn = None
    try:
        conn = get_db_conn()
        c = conn.cursor()

        if stage == STAGE_PLAYIN_7V8:
            # Winner → #7 seed; also try creating Game 3 if 9v10 is done
            _try_create_r1_from_playin(c, season, game_type='7v8')
            _try_create_playin_game3(c, season)
            conn.commit()
            next_stage = STAGE_FIRST_ROUND
            msg = f"7v8 winner {winner_id} promoted → R1 #7 seed slot; Game 3 check run"

        elif stage == STAGE_PLAYIN_9V10:
            # Winner → Game 3 (via _try_create_playin_game3)
            _try_create_playin_game3(c, season)
            conn.commit()
            next_stage = STAGE_PLAYIN_ELIM
            msg = f"9v10 winner {winner_id} feeds → Play-In Game 3 (elimination)"

        else:  # elimination
            # Winner → #8 seed
            _try_create_r1_from_playin(c, season, game_type='elimination')
            conn.commit()
            next_stage = STAGE_FIRST_ROUND
            msg = f"Elimination winner {winner_id} promoted → R1 #8 seed slot"

        _log(msg)
        return {"promoted": True, "next_stage": next_stage, "message": msg, "winner_id": winner_id}

    except Exception as e:
        msg = f"Play-In promotion error ({stage}): {type(e).__name__}: {e}"
        _log(msg)
        if conn:
            try: conn.rollback()
            except Exception: pass
        return {"promoted": False, "next_stage": None, "message": msg, "winner_id": winner_id}
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def _promote_from_playoff(winner_id: int, current_stage: str, season: str) -> dict:
    """
    For playoff rounds, main._try_advance_bracket is already called automatically
    by set_series_result.  This function provides an explicit fallback/override path
    for manual or event-driven triggers.
    """
    next_stage = _PLAYOFF_NEXT.get(current_stage)

    if next_stage is None:
        msg = f"Team {winner_id} is the NBA Champion after {current_stage}!"
        _log(msg)
        return {"promoted": True, "next_stage": "Champion", "message": msg, "winner_id": winner_id}

    # Delegate to main._try_advance_bracket via a completed series lookup
    try:
        from main import get_db_conn, _try_advance_bracket
    except ImportError as e:
        msg = f"Could not import _try_advance_bracket: {e}"
        _log(msg)
        return {"promoted": False, "next_stage": next_stage, "message": msg, "winner_id": winner_id}

    conn = None
    try:
        conn = get_db_conn()
        c = conn.cursor()

        # Find the series this winner just won
        c.execute(
            "SELECT id, conference, bracket_group FROM series "
            "WHERE season = %s AND round = %s AND winner_team_id = %s AND status = 'completed' "
            "ORDER BY id DESC LIMIT 1",
            (season, current_stage, winner_id)
        )
        row = c.fetchone()
        if not row:
            msg = (f"No completed series found for winner={winner_id} "
                   f"stage='{current_stage}' season={season} — cannot advance bracket")
            _log(msg)
            return {"promoted": False, "next_stage": next_stage, "message": msg, "winner_id": winner_id}

        series_id, conference, bracket_group = row
        _try_advance_bracket(c, series_id, winner_id, conference, bracket_group, season)
        conn.commit()
        msg = (f"Team {winner_id} advanced from '{current_stage}' → '{next_stage}' "
               f"(series {series_id}, {conference} conf, group {bracket_group})")
        _log(msg)
        return {"promoted": True, "next_stage": next_stage, "message": msg, "winner_id": winner_id}

    except Exception as e:
        msg = f"Playoff promotion error ({current_stage}): {type(e).__name__}: {e}"
        _log(msg)
        if conn:
            try: conn.rollback()
            except Exception: pass
        return {"promoted": False, "next_stage": next_stage, "message": msg, "winner_id": winner_id}
    finally:
        if conn:
            try: conn.close()
            except Exception: pass
