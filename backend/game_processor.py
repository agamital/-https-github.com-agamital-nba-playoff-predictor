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
# RapidAPI scoreboard — Play-In detection
# ---------------------------------------------------------------------------
# Endpoint: nba-api-free-data scoreboard
# Response shape: { "response": { "Events": [ <event>, ... ] } }
# Play-In events: event['season']['type'] == 5  OR  slug == 'play-in-season'
# Finished:       event['status']['type']['name'] == 'STATUS_FINAL'
#                 event['status']['type']['completed'] == True
_RAPIDAPI_SCOREBOARD_URL = (
    "https://nba-api-free-data.p.rapidapi.com/nba-scoreboard"
)

# Seed-pair → stage mapping for stage inference when DB lookup fails
_SEED_PAIR_TO_STAGE = {
    frozenset({7, 8}):  STAGE_PLAYIN_7V8,
    frozenset({9, 10}): STAGE_PLAYIN_9V10,
}


def _espn_team_name_to_nba_id(display_name: str) -> int | None:
    """Map an ESPN displayName to our canonical NBA team ID."""
    from main import _APINBA_NAME_TO_ID
    # Direct match
    tid = _APINBA_NAME_TO_ID.get(display_name)
    if tid:
        return tid
    # Partial match on last word (team nickname)
    nickname = display_name.split()[-1] if display_name else ""
    for name, tid in _APINBA_NAME_TO_ID.items():
        if name.endswith(nickname):
            return tid
    return None


def _infer_stage_from_db(team1_id: int, team2_id: int, season: str) -> str | None:
    """
    Look up which play-in game_type these two teams are scheduled for
    in our playin_games table.  Returns the game_type string or None.
    """
    conn = None
    try:
        conn = _get_db()
        c = conn.cursor()
        c.execute(
            """SELECT game_type FROM playin_games
               WHERE season = %s
                 AND ((team1_id = %s AND team2_id = %s)
                   OR (team1_id = %s AND team2_id = %s))
               LIMIT 1""",
            (season, team1_id, team2_id, team2_id, team1_id)
        )
        row = c.fetchone()
        return row[0] if row else None
    except Exception as e:
        _log(f"_infer_stage_from_db error: {e}")
        return None
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def _upsert_playin_result(team1_id: int, team2_id: int,
                          winner_id: int, game_type: str,
                          season: str, conference: str) -> int | None:
    """
    Upsert a finished play-in game result into playin_games and return
    the DB row id.  Idempotent: if the row already has a winner_id set,
    it is not overwritten.
    """
    conn = None
    try:
        conn = _get_db()
        c = conn.cursor()

        # Try to find existing row
        c.execute(
            """SELECT id, winner_id FROM playin_games
               WHERE season = %s AND game_type = %s
                 AND ((team1_id = %s AND team2_id = %s)
                   OR (team1_id = %s AND team2_id = %s))
               LIMIT 1""",
            (season, game_type, team1_id, team2_id, team2_id, team1_id)
        )
        existing = c.fetchone()

        if existing:
            row_id, existing_winner = existing
            if existing_winner:
                _log(f"playin_games row {row_id} already has winner={existing_winner} — skipping")
                return row_id
            # Update winner and status
            c.execute(
                """UPDATE playin_games
                   SET winner_id = %s, status = 'completed'
                   WHERE id = %s""",
                (winner_id, row_id)
            )
            conn.commit()
            _log(f"Updated playin_games row {row_id}: winner_id={winner_id}")
            return row_id
        else:
            # Insert new row
            c.execute(
                """INSERT INTO playin_games
                   (season, conference, game_type, team1_id, team2_id,
                    winner_id, status)
                   VALUES (%s, %s, %s, %s, %s, %s, 'completed')
                   RETURNING id""",
                (season, conference, game_type, team1_id, team2_id, winner_id)
            )
            row_id = c.fetchone()[0]
            conn.commit()
            _log(f"Inserted playin_games row {row_id}: {game_type} winner={winner_id}")
            return row_id

    except Exception as e:
        _log(f"_upsert_playin_result error: {e}")
        if conn:
            try: conn.rollback()
            except Exception: pass
        return None
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


# ---------------------------------------------------------------------------
# sync_playin_results_from_api  — public entry point
# ---------------------------------------------------------------------------

def sync_playin_results_from_api(season: str = "2026") -> dict:
    """
    Fetch the NBA scoreboard from RapidAPI, detect finished Play-In games,
    persist results to playin_games, and trigger bracket promotion.

    Steps:
      1. GET /nba-scoreboard with RAPIDAPI credentials
      2. Filter Events where season.type==5 or slug=='play-in-season'
      3. For each STATUS_FINAL + completed==true event:
         a. Extract competitors + scores
         b. Map ESPN team names → NBA team IDs
         c. Identify current_stage via DB lookup or seed-pair fallback
         d. Upsert result into playin_games
         e. Call promote_team_in_bracket(winner_id, current_stage, season)
      4. Return summary dict for logging / API response

    Returns:
      {
        "processed": int,   total finished play-in events seen
        "promoted":  int,   successful bracket promotions
        "skipped":   int,   events skipped (not finished / unmappable)
        "errors":    list,  error messages for debugging
        "details":   list,  per-game processing log
      }
    """
    import requests as _http

    try:
        from main import _RAPIDAPI_KEY, _RAPIDAPI_HOST
    except ImportError as e:
        return {"processed": 0, "promoted": 0, "skipped": 0,
                "errors": [f"Cannot import main: {e}"], "details": []}

    summary = {"processed": 0, "promoted": 0, "skipped": 0, "errors": [], "details": []}

    # ── 1. Fetch scoreboard ──────────────────────────────────────────────
    if not _RAPIDAPI_KEY:
        err = "RAPIDAPI_KEY not set — cannot fetch scoreboard"
        _log(err)
        summary["errors"].append(err)
        return summary

    try:
        _log(f"GET {_RAPIDAPI_SCOREBOARD_URL} (season={season})")
        resp = _http.get(
            _RAPIDAPI_SCOREBOARD_URL,
            headers={"x-rapidapi-key": _RAPIDAPI_KEY, "x-rapidapi-host": _RAPIDAPI_HOST},
            timeout=10,
        )
        _log(f"Scoreboard HTTP {resp.status_code}")
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        err = f"Scoreboard fetch failed: {type(e).__name__}: {e}"
        _log(err)
        summary["errors"].append(err)
        return summary

    # ── 2. Extract Events array ──────────────────────────────────────────
    # Shape: data['response']['Events']  (capital E confirmed by user)
    resp_obj = data.get("response", data)  # handle bare-list or nested
    if isinstance(resp_obj, dict):
        events = resp_obj.get("Events") or resp_obj.get("events") or []
    elif isinstance(resp_obj, list):
        events = resp_obj
    else:
        events = []

    _log(f"Total events in scoreboard: {len(events)}")

    # ── 3. Filter Play-In events ─────────────────────────────────────────
    playin_events = []
    for ev in events:
        season_obj = ev.get("season") or {}
        is_playin = (
            season_obj.get("type") == 5
            or str(season_obj.get("type", "")).lower() == "5"
            or "play-in" in str(season_obj.get("slug", "")).lower()
            or "play-in" in str(season_obj.get("name", "")).lower()
        )
        if is_playin:
            playin_events.append(ev)

    _log(f"Play-In events found: {len(playin_events)}")

    # ── 4. Process each finished Play-In event ───────────────────────────
    for ev in playin_events:
        event_id  = ev.get("id", "?")
        event_name = ev.get("name") or ev.get("shortName") or str(event_id)

        # Check completion
        status_obj = ev.get("status") or {}
        status_type = status_obj.get("type") or {}
        is_final     = status_type.get("name") == "STATUS_FINAL"
        is_completed = bool(status_type.get("completed"))

        if not (is_final and is_completed):
            _log(f"Event {event_id} not finished (name={status_type.get('name')}) — skip")
            summary["skipped"] += 1
            continue

        summary["processed"] += 1

        # Extract competitors from competitions[0].competitors
        competitions = ev.get("competitions") or [{}]
        competitors  = competitions[0].get("competitors") or []

        if len(competitors) < 2:
            msg = f"Event {event_id}: fewer than 2 competitors — skipping"
            _log(msg)
            summary["errors"].append(msg)
            summary["skipped"] += 1
            continue

        # Map ESPN competitor → NBA team id, score, seed, winner flag
        teams_info = []
        for comp in competitors:
            t_obj  = comp.get("team") or {}
            t_name = t_obj.get("displayName") or t_obj.get("name") or ""
            t_id   = _espn_team_name_to_nba_id(t_name)
            score  = comp.get("score")
            seed   = comp.get("curatedRank", {}).get("current") or comp.get("seed")
            winner = bool(comp.get("winner"))
            teams_info.append({
                "name":   t_name,
                "nba_id": t_id,
                "score":  int(score) if score is not None else None,
                "seed":   int(seed) if seed is not None else None,
                "winner": winner,
            })

        _log(f"Event {event_id} ({event_name}): "
             f"{teams_info[0]['name']}({teams_info[0]['score']}) vs "
             f"{teams_info[1]['name']}({teams_info[1]['score']})")

        # Resolve team IDs
        t1, t2 = teams_info[0], teams_info[1]
        if not t1["nba_id"] or not t2["nba_id"]:
            msg = (f"Event {event_id}: could not map team(s) to NBA IDs — "
                   f"'{t1['name']}'→{t1['nba_id']}  '{t2['name']}'→{t2['nba_id']}")
            _log(msg)
            summary["errors"].append(msg)
            summary["skipped"] += 1
            continue

        # Determine winner by flag, then by score
        winner_info = next((t for t in teams_info if t["winner"]), None)
        if winner_info is None:
            s1, s2 = t1["score"], t2["score"]
            if s1 is None or s2 is None or s1 == s2:
                msg = f"Event {event_id}: tie or missing score ({s1} vs {s2}) — no promotion"
                _log(msg)
                summary["errors"].append(msg)
                summary["skipped"] += 1
                continue
            winner_info = t1 if s1 > s2 else t2

        winner_nba_id = winner_info["nba_id"]

        # Infer stage — DB lookup first (most reliable), then seed-pair fallback
        stage = _infer_stage_from_db(t1["nba_id"], t2["nba_id"], season)
        if not stage:
            seeds = frozenset(t["seed"] for t in teams_info if t["seed"] is not None)
            stage = _SEED_PAIR_TO_STAGE.get(seeds)
            if stage:
                _log(f"Event {event_id}: stage inferred from seeds {seeds} → {stage}")
            else:
                # If both seeds are 7-10 but not a known pair → elimination game
                if seeds and all(7 <= s <= 10 for s in seeds):
                    stage = STAGE_PLAYIN_ELIM
                    _log(f"Event {event_id}: seeds {seeds} not 7v8/9v10 → treating as elimination")
                else:
                    msg = f"Event {event_id}: cannot determine stage (seeds={seeds}) — skip"
                    _log(msg)
                    summary["errors"].append(msg)
                    summary["skipped"] += 1
                    continue

        # Infer conference from either team
        from main import _NBA_TEAM_CONFERENCE
        conf = (_NBA_TEAM_CONFERENCE.get(t1["name"])
                or _NBA_TEAM_CONFERENCE.get(t2["name"])
                or _NBA_TEAM_CONFERENCE.get(winner_info["name"])
                or "")
        if conf not in ("East", "West"):
            conf = ""   # upsert will still work; conference is informational

        # Persist result to DB
        row_id = _upsert_playin_result(
            t1["nba_id"], t2["nba_id"],
            winner_nba_id, stage, season, conf
        )
        if row_id is None:
            msg = f"Event {event_id}: DB upsert failed — skipping promotion"
            _log(msg)
            summary["errors"].append(msg)
            summary["skipped"] += 1
            continue

        # Verify via check_game_winner (uses our DB — source of truth)
        verified_winner = check_game_winner(row_id)
        if verified_winner is None:
            msg = (f"Event {event_id} (db row {row_id}): STATUS_FINAL but "
                   f"check_game_winner returned None — API/DB mismatch, skipping promotion")
            _log(msg)
            summary["errors"].append(msg)
            summary["skipped"] += 1
            continue

        # Promote winner in bracket
        result = promote_team_in_bracket(verified_winner, stage, season=season)
        detail = {
            "event_id":    event_id,
            "event_name":  event_name,
            "stage":       stage,
            "winner":      winner_info["name"],
            "winner_id":   verified_winner,
            "promoted":    result["promoted"],
            "next_stage":  result["next_stage"],
            "message":     result["message"],
        }
        summary["details"].append(detail)

        if result["promoted"]:
            summary["promoted"] += 1
            _log(f"✓ Promoted {winner_info['name']} ({stage} → {result['next_stage']})")
        else:
            _log(f"✗ Promotion failed for {winner_info['name']}: {result['message']}")

    _log(f"sync_playin_results_from_api done — "
         f"processed={summary['processed']} promoted={summary['promoted']} "
         f"skipped={summary['skipped']} errors={len(summary['errors'])}")
    return summary


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
