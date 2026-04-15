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
# ESPN free scoreboard — same event format as the RapidAPI proxy, no key needed.
# Query by date: ?dates=YYYYMMDD
_ESPN_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
)

# RapidAPI fallback (used only if ESPN is unreachable)
_RAPIDAPI_SCOREBOARD_URL = (
    "https://nba-api-free-data.p.rapidapi.com/nba-scoreboard"
)


def _fetch_nba_events_for_sync(summary: dict) -> list:
    """
    Return a flat list of NBA scoreboard events covering today + the past 7 days.

    Tries ESPN's free API first (no quota, same ESPN-format JSON).
    Falls back to RapidAPI only if every ESPN request fails.

    On total failure, appends to summary['errors'] and returns [].
    """
    import requests as _http
    from datetime import datetime, timedelta

    headers_espn = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    today      = datetime.utcnow().date()
    all_events = []
    espn_ok    = False

    for days_ago in range(7):          # today + 6 previous days
        check_date = today - timedelta(days=days_ago)
        date_str   = check_date.strftime("%Y%m%d")
        try:
            resp = _http.get(
                _ESPN_SCOREBOARD_URL,
                params={"dates": date_str},
                headers=headers_espn,
                timeout=10,
            )
            if resp.status_code == 200:
                data       = resp.json()
                day_events = data.get("events") or []
                all_events.extend(day_events)
                espn_ok    = True
                _log(f"ESPN {date_str}: {len(day_events)} events")
            else:
                _log(f"ESPN {date_str}: HTTP {resp.status_code} — skipping")
        except Exception as e:
            _log(f"ESPN {date_str} fetch error: {type(e).__name__}: {e}")

    if espn_ok:
        _log(f"ESPN total events (7-day window): {len(all_events)}")
        return all_events

    # ── RapidAPI PRIMARY fallback (api-basketball-nba, 1500/day) ────────
    _log("ESPN unavailable — trying PRIMARY RapidAPI (api-basketball-nba)")
    try:
        from main import _RAPIDAPI_KEY, _RAPIDAPI_HOST_PRIMARY, _RAPIDAPI_PRIMARY_SCOREBOARD_URL
        if not _RAPIDAPI_KEY:
            raise ValueError("RAPIDAPI_KEY not set")
        primary_events = []
        for days_ago in range(7):
            check_date = today - timedelta(days=days_ago)
            params = {
                "year":  check_date.strftime("%Y"),
                "month": check_date.strftime("%m"),
                "day":   check_date.strftime("%d"),
                "limit": 20,
            }
            try:
                resp = _http.get(
                    _RAPIDAPI_PRIMARY_SCOREBOARD_URL,
                    headers={"x-rapidapi-key": _RAPIDAPI_KEY,
                             "x-rapidapi-host": _RAPIDAPI_HOST_PRIMARY},
                    params=params,
                    timeout=12,
                )
                if resp.status_code == 200:
                    day_events = resp.json().get("events") or []
                    primary_events.extend(day_events)
                    _log(f"PRIMARY RapidAPI {check_date}: {len(day_events)} events")
                else:
                    _log(f"PRIMARY RapidAPI {check_date}: HTTP {resp.status_code}")
            except Exception as e:
                _log(f"PRIMARY RapidAPI {check_date} error: {type(e).__name__}: {e}")
        if primary_events:
            _log(f"PRIMARY RapidAPI total events (7-day): {len(primary_events)}")
            return primary_events
    except Exception as e:
        _log(f"PRIMARY RapidAPI setup error: {type(e).__name__}: {e}")

    # ── RapidAPI SECONDARY fallback (nba-api-free-data, monthly quota) ──
    _log("Primary RapidAPI unavailable — falling back to SECONDARY RapidAPI")
    try:
        from main import _RAPIDAPI_KEY, _RAPIDAPI_HOST
        if not _RAPIDAPI_KEY:
            raise ValueError("RAPIDAPI_KEY not set")
        resp = _http.get(
            _RAPIDAPI_SCOREBOARD_URL,
            headers={"x-rapidapi-key": _RAPIDAPI_KEY,
                     "x-rapidapi-host": _RAPIDAPI_HOST},
            timeout=10,
        )
        resp.raise_for_status()
        data     = resp.json()
        resp_obj = data.get("response", data)
        if isinstance(resp_obj, dict):
            events = resp_obj.get("Events") or resp_obj.get("events") or []
        elif isinstance(resp_obj, list):
            events = resp_obj
        else:
            events = []
        _log(f"SECONDARY RapidAPI fallback: {len(events)} events")
        return events
    except Exception as e:
        err = f"All scoreboard sources failed: {type(e).__name__}: {e}"
        _log(err)
        summary["errors"].append(err)
        return []

# Seed-pair → stage mapping for stage inference when DB lookup fails
_SEED_PAIR_TO_STAGE = {
    frozenset({7, 8}):  STAGE_PLAYIN_7V8,
    frozenset({9, 10}): STAGE_PLAYIN_9V10,
}

# ESPN competition type abbreviation → our round name
# These come from competitions[0]['type']['abbreviation']
_ESPN_TYPE_TO_ROUND = {
    "RD16":  STAGE_FIRST_ROUND,      # First Round  (16 teams remain)
    "QTR":   STAGE_CONF_SEMIS,       # Conference Semifinals (quarterfinals)
    "SEMI":  STAGE_CONF_FINALS,      # Conference Finals (semi-finals of finals)
    "FINAL": STAGE_NBA_FINALS,       # NBA Finals
    # Fallbacks seen in the wild
    "1":     STAGE_FIRST_ROUND,
    "2":     STAGE_CONF_SEMIS,
    "3":     STAGE_CONF_FINALS,
    "4":     STAGE_NBA_FINALS,
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
    summary = {"processed": 0, "promoted": 0, "skipped": 0, "errors": [], "details": []}

    # ── 1. Fetch events — ESPN free API (7-day window), RapidAPI fallback ─
    events = _fetch_nba_events_for_sync(summary)
    if not events:
        return summary

    _log(f"Total events to scan for play-in: {len(events)}")

    # Pre-fetch all play-in team pairs (any status) for fallback matching.
    # ESPN sometimes returns play-in games with season.type=3 instead of 5.
    try:
        from main import get_db_conn as _get_db
        _pc = _get_db()
        _pcur = _pc.cursor()
        _pcur.execute(
            "SELECT team1_id, team2_id FROM playin_games WHERE season=%s", (season,)
        )
        _playin_pairs = {frozenset(r) for r in _pcur.fetchall()}
        _pc.close()
    except Exception as _e:
        _playin_pairs = set()
        _log(f"Could not pre-fetch play-in pairs: {_e}")

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
        # Fallback: match by team IDs against our playin_games table
        if not is_playin and _playin_pairs:
            comps = (ev.get("competitions") or [{}])[0].get("competitors") or []
            if len(comps) >= 2:
                t_ids = frozenset(filter(None, (
                    _espn_team_name_to_nba_id(
                        (c.get("team") or {}).get("displayName") or
                        (c.get("team") or {}).get("name") or ""
                    ) for c in comps[:2]
                )))
                if t_ids and t_ids in _playin_pairs:
                    is_playin = True
                    _log(f"Fallback match: event {ev.get('id')} → play-in via team IDs")
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
# sync_playoff_results_from_api  — public entry point
# ---------------------------------------------------------------------------

def sync_playoff_results_from_api(season: str = "2026") -> dict:
    """
    Fetch the NBA scoreboard from RapidAPI, detect finished Playoff games,
    update series win counts, and trigger bracket promotion when a team
    reaches 4 wins.

    Steps:
      1. GET /nba-scoreboard with RAPIDAPI credentials
      2. Filter Events where season.type==3 (post-season)
      3. For each STATUS_FINAL + completed==true event:
         a. Extract home/away teams + scores
         b. Map ESPN team names → NBA team IDs
         c. Look up the active series in our DB for those two teams
         d. Determine winner from score or winner flag
         e. Increment home_wins / away_wins in the series row
         f. If either side reaches 4 wins → mark series completed + call
            promote_team_in_bracket() for full bracket advancement
      4. Return summary dict

    Returns:
      {
        "processed": int,   total finished playoff games seen
        "updated":   int,   series rows updated
        "completed": int,   series marked as completed this run
        "skipped":   int,   games skipped (unmappable / already processed)
        "errors":    list,  error messages
        "details":   list,  per-game processing log
      }

    Idempotency:
      The function tracks which ESPN event IDs it has already applied in the
      series_processed_events table (created on first call).  A game is
      never counted twice even if the endpoint is called multiple times while
      the scoreboard still shows recent finished games.
    """
    summary = {"processed": 0, "updated": 0, "completed": 0,
               "skipped": 0, "errors": [], "details": []}

    # ── 0. Ensure dedup table exists ─────────────────────────────────────
    _ensure_processed_events_table()

    # ── 1. Fetch events — ESPN free API (7-day window), RapidAPI fallback ─
    events = _fetch_nba_events_for_sync(summary)
    if not events:
        return summary

    _log(f"Total events to scan for playoffs: {len(events)}")

    # Pre-fetch active series team pairs for fallback matching.
    # ESPN sometimes returns playoff games with unexpected season types.
    try:
        from main import get_db_conn as _get_db2
        _sc = _get_db2()
        _scur = _sc.cursor()
        _scur.execute(
            "SELECT home_team_id, away_team_id FROM series WHERE season=%s AND status='active'",
            (season,)
        )
        _series_pairs = {frozenset(r) for r in _scur.fetchall()}
        _sc.close()
    except Exception as _e2:
        _series_pairs = set()
        _log(f"Could not pre-fetch series pairs: {_e2}")

    # ── 3. Filter Playoff events ─────────────────────────────────────────
    playoff_events = []
    for ev in events:
        season_obj = ev.get("season") or {}
        s_type = season_obj.get("type")
        s_slug = str(season_obj.get("slug", "")).lower()
        is_playoff = (
            s_type == 3 or str(s_type) == "3"
            or "post-season" in s_slug or "playoff" in s_slug
        )
        # Fallback: match by team IDs against our active series
        if not is_playoff and _series_pairs:
            comps = (ev.get("competitions") or [{}])[0].get("competitors") or []
            if len(comps) >= 2:
                t_ids = frozenset(filter(None, (
                    _espn_team_name_to_nba_id(
                        (c.get("team") or {}).get("displayName") or
                        (c.get("team") or {}).get("name") or ""
                    ) for c in comps[:2]
                )))
                if t_ids and t_ids in _series_pairs:
                    is_playoff = True
                    _log(f"Fallback match: event {ev.get('id')} → playoff via team IDs")
        if is_playoff:
            playoff_events.append(ev)

    _log(f"Playoff events found: {len(playoff_events)}")

    # ── 4. Process each finished Playoff game ────────────────────────────
    for ev in playoff_events:
        event_id   = str(ev.get("id", ""))
        event_name = ev.get("name") or ev.get("shortName") or event_id

        # Skip already-processed games (idempotency guard)
        if _is_event_processed(event_id, "playoff"):
            _log(f"Event {event_id} already processed — skip")
            summary["skipped"] += 1
            continue

        # Check completion
        status_obj  = ev.get("status") or {}
        status_type = status_obj.get("type") or {}
        is_final     = status_type.get("name") == "STATUS_FINAL"
        is_completed = bool(status_type.get("completed"))

        if not (is_final and is_completed):
            summary["skipped"] += 1
            continue

        summary["processed"] += 1

        # Extract competition info
        competitions = ev.get("competitions") or [{}]
        comp0        = competitions[0]
        competitors  = comp0.get("competitors") or []

        if len(competitors) < 2:
            msg = f"Event {event_id}: fewer than 2 competitors — skipping"
            _log(msg)
            summary["errors"].append(msg)
            summary["skipped"] += 1
            continue

        # Determine round from competition type abbreviation
        comp_type_abbr = (comp0.get("type") or {}).get("abbreviation", "")
        round_name     = _ESPN_TYPE_TO_ROUND.get(comp_type_abbr.upper())
        _log(f"Event {event_id} ({event_name}): comp_type={comp_type_abbr!r} → round={round_name!r}")

        # Map competitors
        teams_info = []
        for comp in competitors:
            t_obj   = comp.get("team") or {}
            t_name  = t_obj.get("displayName") or t_obj.get("name") or ""
            t_id    = _espn_team_name_to_nba_id(t_name)
            score   = comp.get("score")
            winner  = bool(comp.get("winner"))
            home_away = comp.get("homeAway", "").lower()   # "home" | "away"
            teams_info.append({
                "name":     t_name,
                "nba_id":   t_id,
                "score":    int(score) if score is not None else None,
                "winner":   winner,
                "home_away": home_away,
            })

        t_home = next((t for t in teams_info if t["home_away"] == "home"), teams_info[0])
        t_away = next((t for t in teams_info if t["home_away"] == "away"), teams_info[1])

        _log(f"  {t_home['name']}(home,{t_home['score']}) vs "
             f"{t_away['name']}(away,{t_away['score']})")

        if not t_home["nba_id"] or not t_away["nba_id"]:
            msg = (f"Event {event_id}: cannot map team IDs — "
                   f"'{t_home['name']}'→{t_home['nba_id']}  "
                   f"'{t_away['name']}'→{t_away['nba_id']}")
            _log(msg)
            summary["errors"].append(msg)
            summary["skipped"] += 1
            continue

        # Determine game winner
        winner_info = next((t for t in teams_info if t["winner"]), None)
        if winner_info is None:
            s_h, s_a = t_home["score"], t_away["score"]
            if s_h is None or s_a is None or s_h == s_a:
                msg = f"Event {event_id}: tie/missing score ({s_h}-{s_a}) — skip"
                _log(msg)
                summary["errors"].append(msg)
                summary["skipped"] += 1
                continue
            winner_info = t_home if s_h > s_a else t_away

        winner_nba_id = winner_info["nba_id"]

        # Look up the active series in our DB
        series_row = _find_series(t_home["nba_id"], t_away["nba_id"], season)
        if series_row is None:
            msg = (f"Event {event_id}: no active series found for "
                   f"{t_home['name']} vs {t_away['name']} (season={season})")
            _log(msg)
            summary["errors"].append(msg)
            summary["skipped"] += 1
            continue

        (series_id, db_home_id, db_away_id,
         cur_home_wins, cur_away_wins,
         db_round, conf, bracket_group,
         db_home_seed, db_away_seed) = series_row

        # If round_name couldn't be inferred from ESPN, use what's in the DB
        if not round_name:
            round_name = db_round
            _log(f"  round_name fallback from DB: {round_name!r}")

        # Increment win for the correct side
        if winner_nba_id == db_home_id:
            new_home_wins = cur_home_wins + 1
            new_away_wins = cur_away_wins
        else:
            new_home_wins = cur_home_wins
            new_away_wins = cur_away_wins + 1

        total_games = new_home_wins + new_away_wins
        series_winner_id = None
        new_status = "active"

        if new_home_wins >= 4:
            series_winner_id = db_home_id
            new_status       = "completed"
        elif new_away_wins >= 4:
            series_winner_id = db_away_id
            new_status       = "completed"

        # Persist the updated score
        ok = _update_series_score(
            series_id,
            new_home_wins, new_away_wins,
            series_winner_id, new_status,
            total_games if new_status == "completed" else None,
        )
        if not ok:
            msg = f"Event {event_id}: DB update failed for series {series_id}"
            _log(msg)
            summary["errors"].append(msg)
            summary["skipped"] += 1
            continue

        # Mark event as processed (idempotency)
        _mark_event_processed(event_id, "playoff", series_id)
        summary["updated"] += 1

        # Build human-readable score line
        score_str = _series_score_str(
            t_home["name"], new_home_wins,
            t_away["name"], new_away_wins,
            winner_nba_id if new_status == "completed" else None,
            winner_info["name"],
        )
        _log(f"Series ID {series_id}: {score_str}")

        detail = {
            "event_id":    event_id,
            "event_name":  event_name,
            "series_id":   series_id,
            "round":       round_name,
            "score":       score_str,
            "completed":   new_status == "completed",
            "winner_id":   series_winner_id,
        }
        summary["details"].append(detail)

        # If series is now complete, score predictions + advance bracket
        if new_status == "completed":
            summary["completed"] += 1
            _finalize_series(
                series_id, series_winner_id, total_games,
                round_name, conf, bracket_group,
                db_home_id, db_away_id, db_home_seed, db_away_seed,
                season,
            )
            promo = promote_team_in_bracket(
                series_winner_id, round_name, season=season
            )
            detail["promoted"]   = promo["promoted"]
            detail["next_stage"] = promo["next_stage"]
            _log(f"  → {promo['message']}")

    _log(f"sync_playoff_results_from_api done — "
         f"processed={summary['processed']} updated={summary['updated']} "
         f"completed={summary['completed']} skipped={summary['skipped']} "
         f"errors={len(summary['errors'])}")
    return summary


# ---------------------------------------------------------------------------
# Helpers for sync_playoff_results_from_api
# ---------------------------------------------------------------------------

def _ensure_processed_events_table():
    """Create series_processed_events dedup table if it doesn't exist."""
    conn = None
    try:
        conn = _get_db()
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS series_processed_events (
                event_id   TEXT NOT NULL,
                event_type TEXT NOT NULL DEFAULT 'playoff',
                series_id  INTEGER,
                processed_at TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (event_id, event_type)
            )
        """)
        conn.commit()
    except Exception as e:
        _log(f"_ensure_processed_events_table error: {e}")
        if conn:
            try: conn.rollback()
            except Exception: pass
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def _is_event_processed(event_id: str, event_type: str = "playoff") -> bool:
    conn = None
    try:
        conn = _get_db()
        c = conn.cursor()
        c.execute(
            "SELECT 1 FROM series_processed_events WHERE event_id=%s AND event_type=%s",
            (event_id, event_type)
        )
        return c.fetchone() is not None
    except Exception:
        return False
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def _mark_event_processed(event_id: str, event_type: str, series_id: int | None):
    conn = None
    try:
        conn = _get_db()
        c = conn.cursor()
        c.execute(
            """INSERT INTO series_processed_events (event_id, event_type, series_id)
               VALUES (%s, %s, %s)
               ON CONFLICT (event_id, event_type) DO NOTHING""",
            (event_id, event_type, series_id)
        )
        conn.commit()
    except Exception as e:
        _log(f"_mark_event_processed error: {e}")
        if conn:
            try: conn.rollback()
            except Exception: pass
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def _find_series(team1_id: int, team2_id: int, season: str):
    """
    Return the active (or most recent) series row for two teams in a season.
    Returns tuple or None.
    """
    conn = None
    try:
        conn = _get_db()
        c = conn.cursor()
        c.execute(
            """SELECT id,
                      home_team_id, away_team_id,
                      COALESCE(home_wins, 0), COALESCE(away_wins, 0),
                      round, conference, COALESCE(bracket_group, 'A'),
                      COALESCE(home_seed, 0), COALESCE(away_seed, 0)
               FROM series
               WHERE season = %s
                 AND status != 'completed'
                 AND ((home_team_id = %s AND away_team_id = %s)
                   OR (home_team_id = %s AND away_team_id = %s))
               ORDER BY id DESC
               LIMIT 1""",
            (season, team1_id, team2_id, team2_id, team1_id)
        )
        return c.fetchone()
    except Exception as e:
        _log(f"_find_series error: {e}")
        return None
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def _update_series_score(series_id: int,
                         home_wins: int, away_wins: int,
                         winner_id: int | None, status: str,
                         actual_games: int | None) -> bool:
    conn = None
    try:
        conn = _get_db()
        c = conn.cursor()
        c.execute(
            """UPDATE series
               SET home_wins = %s,
                   away_wins = %s,
                   winner_team_id = %s,
                   status = %s,
                   actual_games = COALESCE(%s, actual_games)
               WHERE id = %s""",
            (home_wins, away_wins, winner_id, status, actual_games, series_id)
        )
        conn.commit()
        return True
    except Exception as e:
        _log(f"_update_series_score error: {e}")
        if conn:
            try: conn.rollback()
            except Exception: pass
        return False
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def _finalize_series(series_id: int, winner_id: int, actual_games: int,
                     round_name: str, conf: str, bracket_group: str,
                     home_id: int, away_id: int,
                     home_seed: int, away_seed: int,
                     season: str):
    """
    Score predictions and trigger bracket advancement for a just-completed
    series.  Mirrors the core of main.set_series_result().
    """
    try:
        from main import get_db_conn, _recalculate_all_points, _try_advance_bracket
        from scoring import calculate_series_points, calculate_series_leader_points
    except ImportError as e:
        _log(f"_finalize_series: cannot import main helpers: {e}")
        return

    conn = None
    try:
        conn = get_db_conn()
        c = conn.cursor()

        # Read actual series leaders (computed by sync_series_provisional_leaders)
        c.execute(
            "SELECT actual_leading_scorer, actual_leading_rebounder, actual_leading_assister "
            "FROM series WHERE id = %s",
            (series_id,)
        )
        leaders_row = c.fetchone() or (None, None, None)
        actual_leaders = {
            "scorer":    leaders_row[0],
            "rebounder": leaders_row[1],
            "assister":  leaders_row[2],
        }

        # Score predictions (winner + games + leaders)
        c.execute(
            "SELECT id, predicted_winner_id, predicted_games, "
            "       leading_scorer, leading_rebounder, leading_assister "
            "FROM predictions WHERE series_id = %s",
            (series_id,)
        )
        for pred_id, pred_winner_id, pred_games, pred_scorer, pred_rebounder, pred_assister in c.fetchall():
            winner_correct = pred_winner_id == winner_id
            games_correct  = pred_games == actual_games
            games_diff     = abs(pred_games - actual_games) if pred_games is not None else None
            pred_seed      = home_seed if pred_winner_id == home_id else (
                             away_seed if pred_winner_id == away_id else None)
            pts = calculate_series_points(
                round_name, home_seed, away_seed, pred_seed,
                winner_correct=winner_correct,
                games_correct=games_correct,
                games_diff=games_diff,
            )
            # Add leader prediction points (10 pts each, only if actual leaders known)
            pts += calculate_series_leader_points(
                predicted={"scorer": pred_scorer, "rebounder": pred_rebounder, "assister": pred_assister},
                actual=actual_leaders,
            )
            c.execute(
                "UPDATE predictions SET is_correct = %s, points_earned = %s WHERE id = %s",
                (1 if winner_correct else 0, pts, pred_id)
            )

        _recalculate_all_points(c)
        _try_advance_bracket(c, series_id, season, round_name, conf, bracket_group, winner_id)
        conn.commit()
        _log(f"_finalize_series: series {series_id} scored + bracket advanced "
             f"(leaders: scorer={actual_leaders['scorer']}, "
             f"reb={actual_leaders['rebounder']}, ast={actual_leaders['assister']})")

    except Exception as e:
        _log(f"_finalize_series error for series {series_id}: {type(e).__name__}: {e}")
        if conn:
            try: conn.rollback()
            except Exception: pass
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def _series_score_str(home_name: str, home_wins: int,
                      away_name: str, away_wins: int,
                      winner_id: int | None, winner_name: str) -> str:
    if winner_id is not None:
        return f"{winner_name} wins series {max(home_wins, away_wins)}-{min(home_wins, away_wins)}"
    leader = home_name if home_wins > away_wins else away_name
    lead_w = max(home_wins, away_wins)
    trail_w = min(home_wins, away_wins)
    if lead_w == trail_w:
        return f"Series tied {home_wins}-{away_wins}"
    return f"{leader} leads {lead_w}-{trail_w}"


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

        # Map stage → game_type string used in playin_games table
        _stage_to_gtype = {
            STAGE_PLAYIN_7V8:  '7v8',
            STAGE_PLAYIN_9V10: '9v10',
            STAGE_PLAYIN_ELIM: 'elimination',
        }
        gtype = _stage_to_gtype.get(stage)

        # Look up the actual game_id row so we pass the correct (c, game_id, winner_id, season)
        game_id = None
        if gtype:
            c.execute(
                "SELECT id FROM playin_games WHERE season=%s AND game_type=%s AND winner_id=%s",
                (season, gtype, winner_id)
            )
            row = c.fetchone()
            game_id = row[0] if row else None

        if stage == STAGE_PLAYIN_7V8:
            # Winner → #7 seed; also try creating Game 3 if 9v10 is done
            if game_id:
                _try_create_r1_from_playin(c, game_id, winner_id, season)
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
            if game_id:
                _try_create_r1_from_playin(c, game_id, winner_id, season)
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


# ---------------------------------------------------------------------------
# sync_series_provisional_leaders
# ---------------------------------------------------------------------------

def sync_series_provisional_leaders(season: str = "2026") -> dict:
    """
    Compute provisional statistical leaders for every playoff series that has
    at least one completed game.

    For active series the results are *provisional* (more games may change
    the leader).  For completed series without leaders already set, this
    fills in the final values.

    Method:
      1. For each target series, look up the ESPN event IDs that have been
         processed and recorded in series_processed_events (one row per
         completed game in that series).
      2. Aggregate points / rebounds / assists per player from player_game_stats
         using those exact event IDs.
      3. Write the leader name into series.actual_leading_scorer /
         actual_leading_rebounder / actual_leading_assister.

    Returns:
      {"series_checked": int, "series_updated": int, "errors": list}
    """
    result = {"series_checked": 0, "series_updated": 0, "errors": []}
    conn = None
    try:
        conn = _get_db()
        c = conn.cursor()

        # Target: active series + completed series still missing leaders
        c.execute("""
            SELECT s.id, ht.abbreviation, at.abbreviation, s.status
            FROM series s
            JOIN teams ht ON s.home_team_id = ht.id
            JOIN teams at ON s.away_team_id = at.id
            WHERE s.season = %s
              AND (
                  s.status = 'active'
                  OR (s.status = 'completed'
                      AND s.actual_leading_scorer IS NULL)
              )
        """, (season,))
        target_series = c.fetchall()
        result["series_checked"] = len(target_series)

        for series_id, home_abbr, away_abbr, series_status in target_series:
            abbrs = [home_abbr.upper(), away_abbr.upper()]

            # Get ESPN event IDs for completed games in this series
            c.execute("""
                SELECT event_id
                FROM series_processed_events
                WHERE series_id = %s AND event_type = 'playoff'
            """, (series_id,))
            event_ids = [r[0] for r in c.fetchall()]

            if not event_ids:
                # No completed games recorded yet — nothing to compute
                continue

            leaders: dict[str, str | None] = {}
            for cat, col in (
                ("scorer",    "points"),
                ("rebounder", "rebounds"),
                ("assister",  "assists"),
            ):
                c.execute(f"""
                    SELECT player_name, SUM({col}) AS total
                    FROM player_game_stats
                    WHERE espn_game_id = ANY(%s)
                      AND UPPER(team_abbr) = ANY(%s)
                    GROUP BY player_name
                    ORDER BY total DESC NULLS LAST
                    LIMIT 1
                """, (event_ids, abbrs))
                row = c.fetchone()
                leaders[cat] = row[0] if row else None

            if not any(leaders.values()):
                continue

            c.execute("""
                UPDATE series
                SET actual_leading_scorer    = %s,
                    actual_leading_rebounder = %s,
                    actual_leading_assister  = %s
                WHERE id = %s
            """, (leaders["scorer"], leaders["rebounder"],
                  leaders["assister"], series_id))
            result["series_updated"] += 1

        conn.commit()
        _log(f"sync_series_provisional_leaders: "
             f"checked={result['series_checked']} updated={result['series_updated']}")

    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        _log(f"sync_series_provisional_leaders error: {err}")
        result["errors"].append(err)
        if conn:
            try: conn.rollback()
            except Exception: pass
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

    return result
