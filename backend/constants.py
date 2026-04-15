"""
constants.py — Single source of truth for all shared string constants.

Import this module wherever a status, round name, game type, or conference
name is needed.  Never hardcode these strings elsewhere — reference the
constants below so a future rename is a one-line change.

The matching frontend file lives at:  frontend/src/constants.js
"""

# ── Admin ─────────────────────────────────────────────────────────────────────
ADMIN_EMAILS: set[str] = {"agamital@gmail.com"}

# ── Season ────────────────────────────────────────────────────────────────────
CURRENT_SEASON = "2026"

# ── Series status ─────────────────────────────────────────────────────────────
class SeriesStatus:
    ACTIVE    = "active"
    COMPLETED = "completed"

# ── Series round names (stored in DB) ─────────────────────────────────────────
class Round:
    FIRST_ROUND  = "First Round"
    CONF_SEMIS   = "Conference Semifinals"
    CONF_FINALS  = "Conference Finals"
    NBA_FINALS   = "NBA Finals"

    # Short display labels for UI  (do NOT store these in DB)
    LABELS = {
        FIRST_ROUND: "R1",
        CONF_SEMIS:  "R2",
        CONF_FINALS: "CF",
        NBA_FINALS:  "Finals",
    }

# ── Conference names (stored in DB and returned by API) ───────────────────────
class Conference:
    EASTERN  = "Eastern"
    WESTERN  = "Western"

    # Short abbreviations used in some internal helpers only
    EAST     = "East"
    WEST     = "West"

    # Map short → full (for generate_matchups and similar converters)
    FULL = {EAST: EASTERN, WEST: WESTERN}

# ── Play-in game types (stored in DB) ─────────────────────────────────────────
class PlayInType:
    GAME_7V8       = "7v8"
    GAME_9V10      = "9v10"
    ELIMINATION    = "elimination"

    LABELS = {
        GAME_7V8:    "7 vs 8 Seed",
        GAME_9V10:   "9 vs 10 Seed",
        ELIMINATION: "Elimination Game",
    }

# ── Play-in / Series shared status values ─────────────────────────────────────
class GameStatus:
    ACTIVE    = "active"
    COMPLETED = "completed"

# ── Futures prediction field keys (DB columns + API params) ───────────────────
class FuturesKey:
    CHAMPION    = "champion_team_id"
    WEST_CHAMP  = "west_champ_team_id"
    EAST_CHAMP  = "east_champ_team_id"
    FINALS_MVP  = "finals_mvp"
    WEST_MVP    = "west_finals_mvp"
    EAST_MVP    = "east_finals_mvp"

    ALL = [CHAMPION, WEST_CHAMP, EAST_CHAMP, FINALS_MVP, WEST_MVP, EAST_MVP]

# ── Leaders prediction field keys (DB columns + API params) ───────────────────
class LeadersKey:
    SCORER   = "top_scorer"
    ASSISTS  = "top_assists"
    REBOUNDS = "top_rebounds"
    THREES   = "top_threes"
    STEALS   = "top_steals"
    BLOCKS   = "top_blocks"

    ALL = [SCORER, ASSISTS, REBOUNDS, THREES, STEALS, BLOCKS]
