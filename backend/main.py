from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import uvicorn
from datetime import datetime, timedelta
import asyncio
import time
import threading
import os
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import re
import psycopg2
import psycopg2.extras
from scoring import (
    calculate_play_in_points,
    calculate_series_points,
    calculate_series_leader_points,
    calculate_futures_points,
    calculate_leaders_points,
    FUTURES_BASE_POINTS,
    LEADERS_POINTS,
    SERIES_LEADER_BONUS,
)

_standings_cache = {"data": None, "expires": None, "fetched_at": None}

# Sync runs every 6 h until end-of-day April 20 2026 (last regular-season day).
# After this the app enters Static Mode: DB snapshot is served forever, no API calls.
_STANDINGS_SYNC_CUTOFF = datetime(2026, 4, 21, 0, 0, 0)   # exclusive — stops ON April 21

# Tracks sync health across requests — readable by /api/standings and admin endpoints
_sync_status = {
    "source":               "hardcoded",   # "nba_api" | "database" | "hardcoded"
    "last_attempt_at":      None,          # datetime (UTC)
    "last_success_at":      None,          # datetime (UTC)
    "last_error":           None,          # str | None
    "consecutive_failures": 0,
}

# OneSignal push notification credentials
_ONESIGNAL_APP_ID  = os.getenv("ONESIGNAL_APP_ID",  "c69b4c3e-79d1-48a4-8815-3ceabc1eae70")
_ONESIGNAL_API_KEY = os.getenv("ONESIGNAL_API_KEY",  "")

# Resend email credentials
_RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
_RESEND_FROM    = os.getenv("RESEND_FROM",    "NBA Picks <noreply@nba-playoffs-2026.vercel.app>")

# APScheduler instance — created in startup(), referenced in shutdown()
_scheduler = None

# ── RapidAPI — multi-source data strategy ──────────────────────────────────
# PRIMARY:   api-basketball-nba.p.rapidapi.com  (1,500 calls/day)
#            Endpoints: /nbastandings  /nbascoreboard  /nbabox
# SECONDARY: nba-api-free-data.p.rapidapi.com  (fallback, monthly quota)
#            Endpoints: /nba-league-standings  /nba-scoreboard-by-date
# Set RAPIDAPI_KEY in Railway environment variables (shared by both hosts).
_RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")

# Primary host (api-basketball-nba) — overridable via env var
_RAPIDAPI_HOST_PRIMARY   = os.getenv("RAPIDAPI_HOST_PRIMARY",
                                      "api-basketball-nba.p.rapidapi.com")
# Secondary host (legacy nba-api-free-data)
_RAPIDAPI_HOST_SECONDARY = "nba-api-free-data.p.rapidapi.com"
# Backward-compat alias used by older call sites
_RAPIDAPI_HOST = _RAPIDAPI_HOST_SECONDARY

# Primary API endpoints
_RAPIDAPI_PRIMARY_STANDINGS_URL   = (
    f"https://{_RAPIDAPI_HOST_PRIMARY}/nbastandings"
)
_RAPIDAPI_PRIMARY_SCOREBOARD_URL  = (
    f"https://{_RAPIDAPI_HOST_PRIMARY}/nbascoreboard"
)
_RAPIDAPI_PRIMARY_BOXSCORE_URL    = (
    f"https://{_RAPIDAPI_HOST_PRIMARY}/nbabox"
)

# Secondary API endpoints (legacy)
_RAPIDAPI_URL  = "https://nba-api-free-data.p.rapidapi.com/nba-league-standings?year=2026"
_RAPIDAPI_SCOREBOARD_BY_DATE_URL = "https://nba-api-free-data.p.rapidapi.com/nba-scoreboard-by-date"

# ESPN public summary API — no key needed, returns full boxscore (kept as tertiary)
_ESPN_BOXSCORE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"

# ── Fallback: direct stats.nba.com request (used when RAPIDAPI_KEY not set) ──
_NBA_STANDINGS_URL = (
    'https://stats.nba.com/stats/leaguestandingsv3'
    '?LeagueID=00&Season=2025-26&SeasonType=Regular%20Season'
)

# Rotate User-Agents so repeated Railway requests look less like a bot
_USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1',
]

# Base headers — User-Agent is overridden per-request with a random UA above.
# Accept-Encoding: identity → tells server "no compression" so we always get
# plain JSON (compressed responses cause JSONDecodeError on Railway).
_NBA_HEADERS = {
    'Host': 'stats.nba.com',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Encoding': 'identity',
    'Accept-Language': 'en-US,en;q=0.9',
    'Origin': 'https://www.nba.com',
    'Referer': 'https://www.nba.com/',
    'Connection': 'keep-alive',
    'x-nba-stats-origin': 'stats',
    'x-nba-stats-token': 'true',
}
_NBA_TIMEOUT = 30  # seconds — increased for Railway→NBA API latency

# Hardcoded standings (2025-26 season, as of 2026-03-26).
# Used instantly on startup so users never wait for the NBA API.
_HARDCODED_STANDINGS = [
    # Eastern Conference
    {'team_id': 1610612765, 'team_name': 'Detroit Pistons',        'conference': 'East', 'wins': 52, 'losses': 20, 'win_pct': 0.722, 'conf_rank': 1,  'playoff_rank': 1},
    {'team_id': 1610612738, 'team_name': 'Boston Celtics',         'conference': 'East', 'wins': 47, 'losses': 24, 'win_pct': 0.662, 'conf_rank': 2,  'playoff_rank': 2},
    {'team_id': 1610612752, 'team_name': 'New York Knicks',        'conference': 'East', 'wins': 47, 'losses': 25, 'win_pct': 0.653, 'conf_rank': 3,  'playoff_rank': 3},
    {'team_id': 1610612739, 'team_name': 'Cleveland Cavaliers',    'conference': 'East', 'wins': 44, 'losses': 27, 'win_pct': 0.620, 'conf_rank': 4,  'playoff_rank': 4},
    {'team_id': 1610612761, 'team_name': 'Toronto Raptors',        'conference': 'East', 'wins': 40, 'losses': 31, 'win_pct': 0.563, 'conf_rank': 5,  'playoff_rank': 5},
    {'team_id': 1610612737, 'team_name': 'Atlanta Hawks',          'conference': 'East', 'wins': 40, 'losses': 32, 'win_pct': 0.556, 'conf_rank': 6,  'playoff_rank': 6},
    {'team_id': 1610612755, 'team_name': 'Philadelphia 76ers',     'conference': 'East', 'wins': 39, 'losses': 33, 'win_pct': 0.542, 'conf_rank': 7,  'playoff_rank': 7},
    {'team_id': 1610612753, 'team_name': 'Orlando Magic',          'conference': 'East', 'wins': 38, 'losses': 33, 'win_pct': 0.535, 'conf_rank': 8,  'playoff_rank': 8},
    {'team_id': 1610612748, 'team_name': 'Miami Heat',             'conference': 'East', 'wins': 38, 'losses': 34, 'win_pct': 0.528, 'conf_rank': 9,  'playoff_rank': 9},
    {'team_id': 1610612766, 'team_name': 'Charlotte Hornets',      'conference': 'East', 'wins': 37, 'losses': 34, 'win_pct': 0.521, 'conf_rank': 10, 'playoff_rank': 10},
    # Western Conference
    {'team_id': 1610612760, 'team_name': 'Oklahoma City Thunder',  'conference': 'West', 'wins': 57, 'losses': 15, 'win_pct': 0.792, 'conf_rank': 1,  'playoff_rank': 1},
    {'team_id': 1610612759, 'team_name': 'San Antonio Spurs',      'conference': 'West', 'wins': 54, 'losses': 18, 'win_pct': 0.750, 'conf_rank': 2,  'playoff_rank': 2},
    {'team_id': 1610612747, 'team_name': 'Los Angeles Lakers',     'conference': 'West', 'wins': 46, 'losses': 26, 'win_pct': 0.639, 'conf_rank': 3,  'playoff_rank': 3},
    {'team_id': 1610612743, 'team_name': 'Denver Nuggets',         'conference': 'West', 'wins': 44, 'losses': 28, 'win_pct': 0.611, 'conf_rank': 4,  'playoff_rank': 4},
    {'team_id': 1610612750, 'team_name': 'Minnesota Timberwolves', 'conference': 'West', 'wins': 44, 'losses': 28, 'win_pct': 0.611, 'conf_rank': 5,  'playoff_rank': 5},
    {'team_id': 1610612745, 'team_name': 'Houston Rockets',        'conference': 'West', 'wins': 43, 'losses': 28, 'win_pct': 0.606, 'conf_rank': 6,  'playoff_rank': 6},
    {'team_id': 1610612756, 'team_name': 'Phoenix Suns',           'conference': 'West', 'wins': 40, 'losses': 32, 'win_pct': 0.556, 'conf_rank': 7,  'playoff_rank': 7},
    {'team_id': 1610612746, 'team_name': 'LA Clippers',            'conference': 'West', 'wins': 36, 'losses': 36, 'win_pct': 0.500, 'conf_rank': 8,  'playoff_rank': 8},
    {'team_id': 1610612757, 'team_name': 'Portland Trail Blazers', 'conference': 'West', 'wins': 36, 'losses': 37, 'win_pct': 0.493, 'conf_rank': 9,  'playoff_rank': 9},
    {'team_id': 1610612744, 'team_name': 'Golden State Warriors',  'conference': 'West', 'wins': 34, 'losses': 38, 'win_pct': 0.472, 'conf_rank': 10, 'playoff_rank': 10},
]

try:
    from nba_api.stats.static import teams as nba_teams_api
    from nba_api.stats.endpoints import leaguestandingsv3
    NBA_API_AVAILABLE = True
except Exception:
    NBA_API_AVAILABLE = False

app = FastAPI(title="NBA Predictor API")

_FRONTEND_ORIGIN = os.environ.get("FRONTEND_URL", "")
_allowed_origins = [
    "http://localhost:5173",
    "http://localhost:3000",
    "https://nba-playoffs-2026.vercel.app",   # production — always allowed
]
if _FRONTEND_ORIGIN and _FRONTEND_ORIGIN not in _allowed_origins:
    _allowed_origins.append(_FRONTEND_ORIGIN)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db_conn():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(url)

class User(BaseModel):
    username: str
    email: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class PasswordReset(BaseModel):
    username: str
    new_password: str

class Prediction(BaseModel):
    series_id: int
    predicted_winner_id: int
    predicted_games: Optional[int] = None
    leading_scorer: Optional[str] = None
    leading_rebounder: Optional[str] = None
    leading_assister: Optional[str] = None

class TeamOddsUpdate(BaseModel):
    team_id: int
    odds_championship: float = 1.0
    odds_conference: float = 1.0


def init_db():
    conn = get_db_conn()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT DEFAULT 'user',
        points INTEGER DEFAULT 0,
        avatar_url TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    # Migrate existing tables that predate these columns
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url TEXT DEFAULT ''")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")

    c.execute('''CREATE TABLE IF NOT EXISTS teams (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        abbreviation TEXT NOT NULL,
        city TEXT NOT NULL,
        conference TEXT NOT NULL,
        division TEXT,
        logo_url TEXT
    )''')
    # NOTE: odds columns are migrated separately in _apply_odds_migration()
    # with autocommit=True so they are never inside an abortable transaction.

    c.execute('''CREATE TABLE IF NOT EXISTS series (
        id SERIAL PRIMARY KEY,
        season TEXT NOT NULL,
        round TEXT NOT NULL,
        conference TEXT NOT NULL,
        home_team_id INTEGER NOT NULL,
        away_team_id INTEGER NOT NULL,
        home_seed INTEGER,
        away_seed INTEGER,
        home_wins INTEGER DEFAULT 0,
        away_wins INTEGER DEFAULT 0,
        winner_team_id INTEGER,
        status TEXT DEFAULT 'active'
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS predictions (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        series_id INTEGER NOT NULL,
        predicted_winner_id INTEGER NOT NULL,
        predicted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_correct INTEGER,
        points_earned INTEGER DEFAULT 0,
        predicted_games INTEGER,
        UNIQUE(user_id, series_id)
    )''')
    # Add predicted_games column if it doesn't exist (for existing DBs)
    # Use savepoints so a failure doesn't abort the whole transaction.
    c.execute('SAVEPOINT sp_pred_games')
    try:
        c.execute('ALTER TABLE predictions ADD COLUMN IF NOT EXISTS predicted_games INTEGER')
        c.execute('RELEASE SAVEPOINT sp_pred_games')
    except Exception as e:
        print(f"init_db: predictions.predicted_games migration: {e}")
        c.execute('ROLLBACK TO SAVEPOINT sp_pred_games')
    # Add leading stat columns for series leader predictions
    for _col in ('leading_scorer', 'leading_rebounder', 'leading_assister'):
        c.execute(f'SAVEPOINT sp_{_col}')
        try:
            c.execute(f'ALTER TABLE predictions ADD COLUMN IF NOT EXISTS {_col} TEXT')
            c.execute(f'RELEASE SAVEPOINT sp_{_col}')
        except Exception as e:
            print(f"init_db: predictions.{_col} migration: {e}")
            c.execute(f'ROLLBACK TO SAVEPOINT sp_{_col}')
    # Add actual_games column to series if it doesn't exist
    c.execute('SAVEPOINT sp_series_games')
    try:
        c.execute('ALTER TABLE series ADD COLUMN IF NOT EXISTS actual_games INTEGER')
        c.execute('RELEASE SAVEPOINT sp_series_games')
    except Exception as e:
        print(f"init_db: series.actual_games migration: {e}")
        c.execute('ROLLBACK TO SAVEPOINT sp_series_games')
    # Add actual series-leader columns for scoring
    for _col in ('actual_leading_scorer', 'actual_leading_rebounder', 'actual_leading_assister'):
        c.execute(f'SAVEPOINT sp_{_col}')
        try:
            c.execute(f'ALTER TABLE series ADD COLUMN IF NOT EXISTS {_col} TEXT')
            c.execute(f'RELEASE SAVEPOINT sp_{_col}')
        except Exception as e:
            print(f"init_db: series.{_col} migration: {e}")
            c.execute(f'ROLLBACK TO SAVEPOINT sp_{_col}')

    c.execute('''CREATE TABLE IF NOT EXISTS playin_games (
        id SERIAL PRIMARY KEY,
        season TEXT NOT NULL,
        conference TEXT NOT NULL,
        game_type TEXT NOT NULL,
        team1_id INTEGER NOT NULL,
        team1_seed INTEGER,
        team2_id INTEGER NOT NULL,
        team2_seed INTEGER,
        winner_id INTEGER,
        status TEXT DEFAULT 'active'
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS playin_predictions (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        game_id INTEGER NOT NULL,
        predicted_winner_id INTEGER NOT NULL,
        predicted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_correct INTEGER,
        points_earned INTEGER DEFAULT 0,
        UNIQUE(user_id, game_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS cached_standings (
        id           SERIAL PRIMARY KEY,
        team_id      INTEGER NOT NULL,
        team_name    TEXT    NOT NULL,
        abbreviation TEXT    NOT NULL,
        conference   TEXT    NOT NULL,
        wins         INTEGER NOT NULL,
        losses       INTEGER NOT NULL,
        win_pct      REAL    NOT NULL,
        conf_rank    INTEGER NOT NULL,
        season       TEXT    DEFAULT '2026',
        updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(abbreviation, season)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS site_settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS futures_predictions (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        season TEXT DEFAULT '2026',
        champion_team_id INTEGER,
        west_champ_team_id INTEGER,
        east_champ_team_id INTEGER,
        finals_mvp TEXT,
        west_finals_mvp TEXT,
        east_finals_mvp TEXT,
        locked BOOLEAN DEFAULT FALSE,
        predicted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_correct_champion INTEGER,
        is_correct_west INTEGER,
        is_correct_east INTEGER,
        points_earned INTEGER DEFAULT 0,
        UNIQUE(user_id, season)
    )''')

    # Playoff leaders predictions (stat values as integers)
    c.execute('''CREATE TABLE IF NOT EXISTS leaders_predictions (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        season TEXT DEFAULT '2026',
        top_scorer INTEGER,
        top_assists INTEGER,
        top_rebounds INTEGER,
        top_threes INTEGER,
        top_steals INTEGER,
        top_blocks INTEGER,
        predicted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_correct_scorer INTEGER,
        is_correct_assists INTEGER,
        is_correct_rebounds INTEGER,
        is_correct_threes INTEGER,
        is_correct_steals INTEGER,
        is_correct_blocks INTEGER,
        points_earned INTEGER DEFAULT 0,
        UNIQUE(user_id, season)
    )''')

    # Migration: convert leaders TEXT columns to INTEGER if they still are TEXT.
    # Each ALTER uses its own savepoint so a failure on one column doesn't
    # abort the transaction and block the remaining columns / tables.
    for col in ('top_scorer', 'top_assists', 'top_rebounds', 'top_threes', 'top_steals', 'top_blocks'):
        sp = f'sp_leaders_{col}'
        c.execute(f'SAVEPOINT {sp}')
        try:
            c.execute(f'''ALTER TABLE leaders_predictions
                          ALTER COLUMN {col} TYPE INTEGER
                          USING NULLIF(regexp_replace({col}::TEXT, '[^0-9]', '', 'g'), '')::INTEGER''')
            c.execute(f'RELEASE SAVEPOINT {sp}')
            print(f"init_db: leaders_predictions.{col} ensured INTEGER")
        except Exception as e:
            print(f"init_db: leaders_predictions.{col} migration skipped ({e})")
            c.execute(f'ROLLBACK TO SAVEPOINT {sp}')

    # Add bracket_group to series for progressive bracket unlocking
    c.execute("ALTER TABLE series ADD COLUMN IF NOT EXISTS bracket_group TEXT DEFAULT 'A'")

    conn.commit()
    conn.close()
    print("Database initialized")

def sync_teams():
    if not NBA_API_AVAILABLE:
        return
    teams = nba_teams_api.get_teams()
    conn = get_db_conn()
    c = conn.cursor()

    eastern = ['ATL','BOS','BKN','CHA','CHI','CLE','DET','IND','MIA','MIL','NYK','ORL','PHI','TOR','WAS']

    for team in teams:
        conf = 'Eastern' if team['abbreviation'] in eastern else 'Western'
        c.execute('''INSERT INTO teams (id, name, abbreviation, city, conference, division, logo_url)
                     VALUES (%s, %s, %s, %s, %s, %s, %s)
                     ON CONFLICT (id) DO UPDATE SET
                       name = EXCLUDED.name,
                       abbreviation = EXCLUDED.abbreviation,
                       city = EXCLUDED.city,
                       conference = EXCLUDED.conference,
                       logo_url = EXCLUDED.logo_url''',
                  (team['id'], team['full_name'], team['abbreviation'], team['city'],
                   conf, '', f"https://cdn.nba.com/logos/nba/{team['id']}/primary/L/logo.svg"))

    conn.commit()
    conn.close()
    print(f"Synced {len(teams)} teams")

_ALLSTAR_KEYWORDS = ('all-star', 'all star', 'team lebron', 'team stephen',
                     'team durant', 'team giannis', 'team curry')

# Map API-NBA team names → canonical NBA team IDs (from nba_api / our teams table).
# API-NBA uses full city+name strings like "Golden State Warriors".
_APINBA_NAME_TO_ID = {
    "Atlanta Hawks":           1610612737,
    "Boston Celtics":          1610612738,
    "Brooklyn Nets":           1610612751,
    "Charlotte Hornets":       1610612766,
    "Chicago Bulls":           1610612741,
    "Cleveland Cavaliers":     1610612739,
    "Dallas Mavericks":        1610612742,
    "Denver Nuggets":          1610612743,
    "Detroit Pistons":         1610612765,
    "Golden State Warriors":   1610612744,
    "Houston Rockets":         1610612745,
    "Indiana Pacers":          1610612754,
    "LA Clippers":             1610612746,
    "Los Angeles Lakers":      1610612747,
    "Memphis Grizzlies":       1610612763,
    "Miami Heat":              1610612748,
    "Milwaukee Bucks":         1610612749,
    "Minnesota Timberwolves":  1610612750,
    "New Orleans Pelicans":    1610612740,
    "New York Knicks":         1610612752,
    "Oklahoma City Thunder":   1610612760,
    "Orlando Magic":           1610612753,
    "Philadelphia 76ers":      1610612755,
    "Phoenix Suns":            1610612756,
    "Portland Trail Blazers":  1610612757,
    "Sacramento Kings":        1610612758,
    "San Antonio Spurs":       1610612759,
    "Toronto Raptors":         1610612761,
    "Utah Jazz":               1610612762,
    "Washington Wizards":      1610612764,
}

# Conference lookup — used when the API returns a flat list with no conference field
_NBA_TEAM_CONFERENCE = {
    # Eastern Conference
    "Atlanta Hawks": "East", "Boston Celtics": "East", "Brooklyn Nets": "East",
    "Charlotte Hornets": "East", "Chicago Bulls": "East", "Cleveland Cavaliers": "East",
    "Detroit Pistons": "East", "Indiana Pacers": "East", "Miami Heat": "East",
    "Milwaukee Bucks": "East", "New York Knicks": "East", "Orlando Magic": "East",
    "Philadelphia 76ers": "East", "Toronto Raptors": "East", "Washington Wizards": "East",
    # Western Conference
    "Dallas Mavericks": "West", "Denver Nuggets": "West", "Golden State Warriors": "West",
    "Houston Rockets": "West", "LA Clippers": "West", "Los Angeles Lakers": "West",
    "Memphis Grizzlies": "West", "Minnesota Timberwolves": "West",
    "New Orleans Pelicans": "West", "Oklahoma City Thunder": "West",
    "Phoenix Suns": "West", "Portland Trail Blazers": "West",
    "Sacramento Kings": "West", "San Antonio Spurs": "West", "Utah Jazz": "West",
}


def _parse_rapidapi_row(row: dict) -> dict | None:
    """
    Try multiple known response shapes from different RapidAPI NBA providers.
    Returns a normalised standings dict or None if the row can't be mapped.

    Supported shapes:
      Shape A (nba-api-free-data / Smart API):
        { "TeamID": "...", "TeamCity": "...", "TeamName": "...",
          "Conference": "East", "ConferenceRecord": "...",
          "WINS": 45, "LOSSES": 20, "WinPCT": 0.692,
          "ConferenceRank": 1, "GamesBehind": 0.0 }
      Shape B (flat with teamName / conference keys):
        { "teamName": "...", "conference": "East", "conferenceRank": 1,
          "wins": 45, "losses": 20, "pct": "0.692", "gamesBehind": "0" }
      Shape C (nested team+conference — old api-nba-v1 style):
        { "team": {"name": "..."}, "conference": {"name": "east", "rank": 1},
          "win": {"total": 45, "percentage": "0.692"}, "loss": {"total": 20},
          "gamesBehind": "0" }
    """
    def _safe_float(v, default=0.0):
        try: return float(v or default)
        except (TypeError, ValueError): return default

    def _safe_int(v, default=0):
        try: return int(v or default)
        except (TypeError, ValueError): return default

    # ── Shape A: flat UPPERCASE keys (nba-api-free-data) ──
    if "TeamName" in row or "WINS" in row:
        city      = row.get("TeamCity", "") or ""
        name      = row.get("TeamName", "") or ""
        team_name = f"{city} {name}".strip() if city else name
        conf      = (row.get("Conference") or "").capitalize()
        conf_rank = _safe_int(row.get("ConferenceRank") or row.get("PlayoffRank"), 99)
        wins      = _safe_int(row.get("WINS") or row.get("wins"))
        losses    = _safe_int(row.get("LOSSES") or row.get("losses"))
        win_pct   = _safe_float(row.get("WinPCT") or row.get("pct"))
        gb        = _safe_float(row.get("GamesBehind") or row.get("gamesBehind"))
        team_id   = _safe_int(row.get("TeamID")) or _APINBA_NAME_TO_ID.get(team_name)
        if not conf or conf.lower() not in ("east", "west"):
            return None
        return dict(team_id=team_id, team_name=team_name, conference=conf,
                    wins=wins, losses=losses, win_pct=win_pct,
                    conf_rank=conf_rank, playoff_rank=conf_rank, games_back=gb)

    # ── Shape B: flat camelCase ──
    if "teamName" in row:
        team_name = row.get("teamName", "")
        conf      = (row.get("conference") or "").capitalize()
        conf_rank = _safe_int(row.get("conferenceRank") or row.get("rank"), 99)
        wins      = _safe_int(row.get("wins") or row.get("win"))
        losses    = _safe_int(row.get("losses") or row.get("loss"))
        win_pct   = _safe_float(row.get("pct") or row.get("winPct") or row.get("percentage"))
        gb        = _safe_float(row.get("gamesBehind") or row.get("gb"))
        team_id   = _safe_int(row.get("teamId")) or _APINBA_NAME_TO_ID.get(team_name)
        if not conf or conf.lower() not in ("east", "west"):
            return None
        return dict(team_id=team_id, team_name=team_name, conference=conf,
                    wins=wins, losses=losses, win_pct=win_pct,
                    conf_rank=conf_rank, playoff_rank=conf_rank, games_back=gb)

    # ── Shape C: nested objects (old api-nba-v1) ──
    if "team" in row and isinstance(row["team"], dict) and "stats" not in row:
        team_name = row["team"].get("name", "")
        conf_obj  = row.get("conference", {}) or {}
        conf      = (conf_obj.get("name") or "").capitalize()
        conf_rank = _safe_int(conf_obj.get("rank"), 99)
        win_obj   = row.get("win", {}) or {}
        loss_obj  = row.get("loss", {}) or {}
        wins      = _safe_int(win_obj.get("total"))
        losses    = _safe_int(loss_obj.get("total"))
        win_pct   = _safe_float(win_obj.get("percentage"))
        gb        = _safe_float(row.get("gamesBehind"))
        team_id   = _APINBA_NAME_TO_ID.get(team_name)
        if not conf or conf.lower() not in ("east", "west"):
            return None
        return dict(team_id=team_id, team_name=team_name, conference=conf,
                    wins=wins, losses=losses, win_pct=win_pct,
                    conf_rank=conf_rank, playoff_rank=conf_rank, games_back=gb)

    # ── Shape D: ESPN-style entries (nba-api-free-data CONFIRMED structure) ──
    # Exact path: data['response']['standings']['entries'][i]
    # Each entry: { "team": {"displayName": "Boston Celtics", "id": "2"},
    #               "stats": [{"name": "wins", "value": 48},
    #                          {"name": "losses", "value": 20},
    #                          {"name": "playoffSeed", "value": 1}, ...] }
    if "team" in row and isinstance(row["team"], dict) and "stats" in row:
        team_obj  = row["team"]
        team_name = (team_obj.get("displayName") or team_obj.get("name") or
                     team_obj.get("fullName") or "")

        # Build name→value lookup from stats list (keys lowercased for safe matching)
        stats_map = {}
        for s in (row.get("stats") or []):
            key = (s.get("name") or s.get("shortDisplayName") or "").lower()
            if key:
                stats_map[key] = s.get("value")

        wins    = _safe_int(stats_map.get("wins") or stats_map.get("w"))
        losses  = _safe_int(stats_map.get("losses") or stats_map.get("l"))
        win_pct = _safe_float(
            stats_map.get("winpercent") or stats_map.get("winpercentage") or
            stats_map.get("pct") or stats_map.get("winspercentage") or
            stats_map.get("wpct") or stats_map.get("win%")
        )
        gb = _safe_float(
            stats_map.get("gamesbehind") or stats_map.get("gb") or
            stats_map.get("games behind") or stats_map.get("gamesback")
        )
        conf_rank = _safe_int(
            stats_map.get("playoffseed") or stats_map.get("seed") or
            stats_map.get("conferencerank") or stats_map.get("confrank") or
            stats_map.get("rank") or row.get("seed"),
            99
        )

        # Compute win_pct from wins/losses if not in stats
        if win_pct == 0.0 and (wins + losses) > 0:
            win_pct = round(wins / (wins + losses), 3)

        # Conference: flat list → look up by team name
        conf_raw = (row.get("conference") or row.get("group") or "")
        if isinstance(conf_raw, dict):
            conf_raw = conf_raw.get("name") or conf_raw.get("abbreviation") or ""
        conf_lower = str(conf_raw).lower().strip()
        if "east" in conf_lower or conf_lower == "e":
            conf = "East"
        elif "west" in conf_lower or conf_lower == "w":
            conf = "West"
        else:
            # No conference in row — use hardcoded lookup
            conf = _NBA_TEAM_CONFERENCE.get(team_name, "")

        team_id = _APINBA_NAME_TO_ID.get(team_name)

        if not conf or conf.lower() not in ("east", "west"):
            print(f"[RapidAPI] ⚠ Shape D: unknown conference for '{team_name}' — skipping")
            return None
        return dict(team_id=team_id, team_name=team_name, conference=conf,
                    wins=wins, losses=losses, win_pct=win_pct,
                    conf_rank=conf_rank, playoff_rank=conf_rank, games_back=gb)

    return None


def _fetch_standings_from_rapidapi() -> list:
    """
    Fetch 2025-26 NBA standings from RapidAPI (nba-api-free-data.p.rapidapi.com).
    Provider: 'NBA API Free Data' by Smart API.

    Logs the FULL raw response on every call so structure issues are visible
    in Railway logs. Tries multiple response-shape parsers for robustness.
    """
    import requests as _http

    if not _RAPIDAPI_KEY:
        raise RuntimeError("RAPIDAPI_KEY environment variable not set")

    headers = {
        "x-rapidapi-key":  _RAPIDAPI_KEY,
        "x-rapidapi-host": _RAPIDAPI_HOST,
    }

    print(f"[RapidAPI] GET {_RAPIDAPI_URL}")
    resp = _http.get(_RAPIDAPI_URL, headers=headers, timeout=10)
    print(f"[RapidAPI] HTTP {resp.status_code}  content-type: {resp.headers.get('content-type','?')}")

    # ── Log full response for debugging ─────────────────────────────────
    raw_text = resp.text
    print(f"[RapidAPI] Raw response ({len(raw_text)} chars):\n{raw_text[:2000]}")
    if len(raw_text) > 2000:
        print(f"[RapidAPI] ... (truncated, full length={len(raw_text)})")

    resp.raise_for_status()

    data = resp.json()
    print(f"[RapidAPI] Top-level keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")

    # ── Locate the rows array ─────────────────────────────────────────────
    # Confirmed path: data['response']['standings']
    # Fallback: any other common nesting just in case structure changes.
    rows = None

    if isinstance(data, list):
        rows = data
        print(f"[RapidAPI] Response is a bare list — {len(rows)} items")
    elif isinstance(data, dict):
        resp_val = data.get("response")

        # Confirmed path: response is a dict containing 'standings'
        if isinstance(resp_val, dict):
            print(f"[RapidAPI] response sub-keys: {list(resp_val.keys())}")
            standings_val = resp_val.get("standings", [])
            print(f"[RapidAPI] standings type: {type(standings_val).__name__}  "
                  f"len/keys: {len(standings_val) if isinstance(standings_val, (list,dict)) else '?'}")

            if isinstance(standings_val, list):
                rows = standings_val
                print(f"[RapidAPI] ✓ response.standings is a list — {len(rows)} items")
            elif isinstance(standings_val, dict):
                print(f"[RapidAPI] response.standings is a dict — sub-keys: {list(standings_val.keys())}")
                # Confirmed path: response.standings.entries
                for k in ("entries", "teams", "rows", "data", "results", "response"):
                    if isinstance(standings_val.get(k), list) and standings_val[k]:
                        rows = standings_val[k]
                        print(f"[RapidAPI] ✓ Found rows at response.standings.{k} — {len(rows)} items")
                        break
                if not rows:
                    print(f"DEBUG STANDINGS CONTENT: {str(standings_val)[:1000]}")

        # Fallback: response is already a list
        elif isinstance(resp_val, list) and resp_val:
            rows = resp_val
            print(f"[RapidAPI] response is a direct list — {len(rows)} items")

        # Broader fallback: search all top-level keys
        if not rows:
            for key in ("standings", "data", "body", "result", "results"):
                val = data.get(key)
                if isinstance(val, list) and val:
                    rows = val
                    print(f"[RapidAPI] Fallback: found rows under '{key}' — {len(rows)} items")
                    break

    if not rows:
        print(f"DEBUG STANDINGS CONTENT: {str(data.get('response', data))[:500]}")
        raise ValueError(
            f"Could not find standings list. "
            f"Top-level keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}. "
            f"response type: {type(data.get('response')).__name__ if isinstance(data, dict) else 'N/A'}. "
            f"Full response logged above."
        )

    # Log first row so field names are visible in Railway logs
    if isinstance(rows[0], dict):
        print(f"[RapidAPI] First row keys: {list(rows[0].keys())}")
        team_obj = rows[0].get("team")
        if isinstance(team_obj, dict):
            print(f"[RapidAPI] First row team keys: {list(team_obj.keys())}")
            print(f"[RapidAPI] First team displayName: {team_obj.get('displayName')}")
        stats_list = rows[0].get("stats")
        if isinstance(stats_list, list) and stats_list:
            # Print ALL stat names so we can verify the exact keys
            stat_names = [s.get("name") for s in stats_list]
            print(f"[RapidAPI] All stat names in first row: {stat_names}")
            print(f"[RapidAPI] stats sample: { {s['name']: s.get('value') for s in stats_list[:6]} }")
    print(f"[RapidAPI] First row sample: {str(rows[0])[:600]}")

    # ── Parse rows with multi-shape parser ──────────────────────────────
    standings = []
    skipped   = []
    for i, row in enumerate(rows):
        parsed = _parse_rapidapi_row(row)
        if parsed is None:
            print(f"[RapidAPI] ⚠ Row {i} — no parser matched: {str(row)[:200]}")
            continue
        if not parsed.get("team_id"):
            skipped.append(parsed.get("team_name", f"row_{i}"))
            print(f"[RapidAPI] ⚠ No NBA team_id for '{parsed.get('team_name')}' — skipping")
            continue
        standings.append(parsed)

    if skipped:
        print(f"[RapidAPI] ⚠ Skipped {len(skipped)} unmapped teams: {skipped}")

    # ── Validate ──────────────────────────────────────────────────────────
    bad = [t for t in standings
           if t["conference"].lower() not in ("east", "west")
           or any(kw in t["team_name"].lower() for kw in _ALLSTAR_KEYWORDS)]
    if bad:
        raise ValueError(f"Response contains bad data (All-Star?): '{bad[0]['team_name']}'")
    if len(standings) < 20:
        # Hard failure — fewer than 20 teams is clearly corrupted data
        raise ValueError(
            f"Only {len(standings)} teams parsed (skipped: {skipped}). "
            f"Check logs for 'Row N — no parser matched' to diagnose field names."
        )
    if len(standings) < 28:
        # Soft warning — partial data is still usable; log and continue
        print(f"[RapidAPI] ⚠ Only {len(standings)} teams parsed (expected 30) — "
              f"skipped: {skipped}. Proceeding with partial data.")

    # Log #1 East and #1 West so we can visually confirm data is current
    e1 = next((t for t in standings if t["conference"] == "East" and t["conf_rank"] == 1), None)
    w1 = next((t for t in standings if t["conference"] == "West" and t["conf_rank"] == 1), None)
    print(f"[RapidAPI] ✓ {len(standings)} teams parsed successfully")
    print(f"[RapidAPI] #1 East: {e1['team_name']} ({e1['wins']}-{e1['losses']}) wins={e1['wins']}" if e1 else "[RapidAPI] #1 East: not found")
    print(f"[RapidAPI] #1 West: {w1['team_name']} ({w1['wins']}-{w1['losses']}) wins={w1['wins']}" if w1 else "[RapidAPI] #1 West: not found")
    return standings


def _fetch_standings_from_primary_api() -> list:
    """
    Fetch 2025-26 NBA standings from PRIMARY API (api-basketball-nba.p.rapidapi.com).
    Endpoint: GET /nbastandings?year=2026&group=conference
    Response shape: ESPN-format with children[conference].standings.entries[]
      Each entry: { team: {id, abbreviation, displayName},
                    stats: [{name, value}, ...] }
    Stat names used: wins, losses, winPercent, gamesBehind, playoffSeed
    """
    import requests as _http

    if not _RAPIDAPI_KEY:
        raise RuntimeError("RAPIDAPI_KEY not set")

    headers = {
        "x-rapidapi-key":  _RAPIDAPI_KEY,
        "x-rapidapi-host": _RAPIDAPI_HOST_PRIMARY,
    }
    url = _RAPIDAPI_PRIMARY_STANDINGS_URL
    print(f"[Primary] GET {url}?year=2026&group=conference")
    resp = _http.get(url, headers=headers, params={"year": "2026", "group": "conference"},
                     timeout=12)
    print(f"[Primary] HTTP {resp.status_code}")
    resp.raise_for_status()
    data = resp.json()

    def _safe_int(v, d=0):
        try: return int(v or d)
        except: return d

    def _safe_float(v, d=0.0):
        try: return float(v or d)
        except: return d

    standings = []
    for conf_block in data.get("children", []):
        conf_abbr = conf_block.get("abbreviation", "")  # "East" or "West"
        if "east" in conf_abbr.lower():
            conf = "East"
        elif "west" in conf_abbr.lower():
            conf = "West"
        else:
            continue

        entries = conf_block.get("standings", {}).get("entries", [])
        for entry in entries:
            team_obj = entry.get("team", {})
            team_name = (team_obj.get("displayName") or
                         f"{team_obj.get('location','')} {team_obj.get('name','')}".strip())
            abbr      = team_obj.get("abbreviation", "")
            espn_tid  = team_obj.get("id", "")

            stats_map = {
                s["name"].lower(): s.get("value")
                for s in entry.get("stats", [])
                if s.get("name")
            }

            wins      = _safe_int(stats_map.get("wins"))
            losses    = _safe_int(stats_map.get("losses"))
            win_pct   = _safe_float(stats_map.get("winpercent"))
            gb_raw    = stats_map.get("gamesbehind", "0")
            gb        = 0.0 if str(gb_raw) in ("-", "", "None") else _safe_float(gb_raw)
            seed      = _safe_int(stats_map.get("playoffseed") or
                                  stats_map.get("seed") or
                                  stats_map.get("conferencerank"), 99)

            if win_pct == 0.0 and (wins + losses) > 0:
                win_pct = round(wins / (wins + losses), 3)

            # Map ESPN team ID → NBA team ID via abbreviation lookup
            team_id = _APINBA_NAME_TO_ID.get(team_name) or _APINBA_NAME_TO_ID.get(abbr, 0)

            standings.append({
                "team_id":      team_id,
                "team_name":    team_name,
                "conference":   conf,
                "wins":         wins,
                "losses":       losses,
                "win_pct":      win_pct,
                "conf_rank":    seed,
                "playoff_rank": seed,
                "games_back":   gb,
            })

    # Validate
    bad = [t for t in standings if any(kw in t["team_name"].lower()
                                       for kw in _ALLSTAR_KEYWORDS)]
    if bad:
        raise ValueError(f"Primary API returned bad data: '{bad[0]['team_name']}'")
    if len(standings) < 20:
        raise ValueError(f"Primary API: only {len(standings)} teams parsed (expected 30)")

    e1 = next((t for t in standings if t["conference"] == "East" and t["conf_rank"] == 1), None)
    w1 = next((t for t in standings if t["conference"] == "West" and t["conf_rank"] == 1), None)
    print(f"[Primary] ✓ {len(standings)} teams — "
          f"#1 East: {e1['team_name'] if e1 else '?'}  "
          f"#1 West: {w1['team_name'] if w1 else '?'}")
    return standings


def _fetch_scoreboard_primary(date_str: str) -> list:
    """
    Fetch game list from PRIMARY API: GET /nbascoreboard?year=YYYY&month=MM&day=DD
    Returns a list of event dicts compatible with the existing scoreboard pipeline:
      [ { id, completed, status, clock, period, home, away, broadcast }, ... ]
    """
    import requests as _http

    if not _RAPIDAPI_KEY:
        return []

    target = datetime.strptime(date_str, "%Y-%m-%d") if "-" in date_str \
             else datetime.strptime(date_str, "%Y%m%d")

    headers = {
        "x-rapidapi-key":  _RAPIDAPI_KEY,
        "x-rapidapi-host": _RAPIDAPI_HOST_PRIMARY,
    }
    params = {
        "year":  target.strftime("%Y"),
        "month": target.strftime("%m"),
        "day":   target.strftime("%d"),
    }
    print(f"[Primary] GET /nbascoreboard {date_str}")
    resp = _http.get(_RAPIDAPI_PRIMARY_SCOREBOARD_URL, headers=headers,
                     params=params, timeout=12)
    resp.raise_for_status()
    data = resp.json()

    events = data.get("events", [])
    result = []
    for ev in events:
        comps  = ev.get("competitions") or [{}]
        comp   = comps[0]
        teams  = comp.get("competitors") or []
        home_c = next((c for c in teams if c.get("homeAway") == "home"), {})
        away_c = next((c for c in teams if c.get("homeAway") == "away"), {})

        def _tm(c):
            t = c.get("team") or {}
            return {
                "id":     t.get("id"),
                "abbr":   t.get("abbreviation"),
                "name":   t.get("displayName") or t.get("name"),
                "score":  c.get("score"),
                "winner": bool(c.get("winner")),
            }

        stype = (ev.get("status") or {}).get("type") or {}
        result.append({
            "id":        str(ev.get("id", "")),
            "name":      ev.get("name") or ev.get("shortName"),
            "date":      ev.get("date"),
            "completed": bool(stype.get("completed")),
            "status":    stype.get("description") or stype.get("name"),
            "clock":     (ev.get("status") or {}).get("displayClock"),
            "period":    (ev.get("status") or {}).get("period"),
            "home":      _tm(home_c),
            "away":      _tm(away_c),
            "broadcast": comp.get("broadcast") or "",
            "venue":     ((comp.get("venue") or {}).get("fullName") or ""),
        })

    print(f"[Primary] /nbascoreboard {date_str}: {len(result)} games, "
          f"{sum(1 for e in result if e['completed'])} completed")
    return result


def _fetch_boxscore_primary(espn_game_id: str) -> list:
    """
    Fetch per-player boxscore from PRIMARY API: GET /nbabox?id={espn_game_id}
    Stat labels: ['MIN','PTS','FG','3PT','FT','REB','AST','TO','STL','BLK',
                  'OREB','DREB','PF','+/-']
    Compound stats (FG/3PT/FT) are in "made-attempted" format, e.g. "7-21".

    Returns list of player dicts matching our player_game_stats schema:
      [ { espn_pid, player_name, team_abbr, espn_team_id,
          points, rebounds, assists, steals, blocks, turnovers,
          minutes, fgm, fga, fg3m, fg3a, ftm, fta, oreb, dreb,
          fouls, plus_minus }, ... ]
    """
    import requests as _http

    if not _RAPIDAPI_KEY:
        return []

    headers = {
        "x-rapidapi-key":  _RAPIDAPI_KEY,
        "x-rapidapi-host": _RAPIDAPI_HOST_PRIMARY,
    }
    resp = _http.get(_RAPIDAPI_PRIMARY_BOXSCORE_URL, headers=headers,
                     params={"id": espn_game_id}, timeout=12)
    resp.raise_for_status()
    data = resp.json()

    # Log top-level keys to help diagnose response structure changes
    top_keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
    print(f"[Primary /nbabox] game={espn_game_id} top-level keys: {top_keys}")

    def _split_compound(val: str):
        """Parse 'made-attempted' string → (int made, int attempted)."""
        try:
            parts = str(val or "0-0").split("-")
            return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            return 0, 0

    def _safe_int(v, d=0):
        try: return int(v or d)
        except: return d

    def _safe_float(v, d=0.0):
        try: return float(str(v or d).replace(":", "").strip() or d)
        except: return d

    # Handle both flat {"players": [...]} and nested {"boxscore": {"players": [...]}}
    # Try every known path; log which one resolved so structure changes are visible.
    _flat    = data.get("players")          or []
    _nested  = (data.get("boxscore") or {}).get("players") or []
    raw_player_groups = _flat or _nested

    if raw_player_groups:
        _src = "data['players']" if _flat else "data['boxscore']['players']"
        print(f"[Primary /nbabox] game={espn_game_id} "
              f"player_groups={len(raw_player_groups)} via {_src}")
    else:
        print(f"[Primary /nbabox] ⚠ WARNING game={espn_game_id}: "
              f"0 player groups found — checked data['players'] and "
              f"data['boxscore']['players']. "
              f"Actual top-level keys: {top_keys}. "
              f"ESPN fallback will be attempted.")

    players = []
    for team_group in raw_player_groups:
        team_obj    = team_group.get("team", {})
        team_abbr   = (team_obj.get("abbreviation") or "").upper()
        espn_team_id = str(team_obj.get("id", ""))

        for stat_block in team_group.get("statistics", []):
            labels   = stat_block.get("labels", [])
            label_idx = {lbl.upper(): i for i, lbl in enumerate(labels)}
            athletes = stat_block.get("athletes", [])

            for ath in athletes:
                athlete   = ath.get("athlete") or {}
                espn_pid  = str(athlete.get("id", ""))
                pname     = athlete.get("displayName") or athlete.get("fullName") or ""
                stats_arr = ath.get("stats") or []

                if not espn_pid or not pname or not stats_arr:
                    continue

                def _get(label, default="0"):
                    idx = label_idx.get(label.upper())
                    if idx is not None and idx < len(stats_arr):
                        v = stats_arr[idx]
                        return str(v) if v is not None else default
                    return default

                # Parse minutes — may be "31" or "31:23"
                min_raw = _get("MIN", "0")
                try:
                    if ":" in min_raw:
                        parts = min_raw.split(":")
                        minutes = float(parts[0]) + float(parts[1]) / 60
                    else:
                        minutes = float(min_raw or 0)
                except (ValueError, AttributeError):
                    minutes = 0.0

                # Parse plus-minus (+14 or -5 string)
                pm_raw = _get("+/-", "0")
                try:
                    plus_minus = int(str(pm_raw).replace("+", "") or 0)
                except ValueError:
                    plus_minus = 0

                fgm,  fga  = _split_compound(_get("FG",  "0-0"))
                fg3m, fg3a = _split_compound(_get("3PT", "0-0"))
                ftm,  fta  = _split_compound(_get("FT",  "0-0"))

                players.append({
                    "espn_pid":     espn_pid,
                    "player_name":  pname,
                    "team_abbr":    team_abbr,
                    "espn_team_id": espn_team_id,
                    "points":       _safe_int(_get("PTS")),
                    "rebounds":     _safe_int(_get("REB")),
                    "assists":      _safe_int(_get("AST")),
                    "steals":       _safe_int(_get("STL")),
                    "blocks":       _safe_int(_get("BLK")),
                    "turnovers":    _safe_int(_get("TO")),
                    "minutes":      round(minutes, 2),
                    "fgm": fgm, "fga": fga,
                    "fg3m": fg3m, "fg3a": fg3a,
                    "ftm": ftm, "fta": fta,
                    "oreb":       _safe_int(_get("OREB")),
                    "dreb":       _safe_int(_get("DREB")),
                    "fouls":      _safe_int(_get("PF")),
                    "plus_minus": plus_minus,
                })

    return players


def _parse_standings_result_sets(result_sets: list) -> list:
    """
    Parse raw NBA API resultSets into our internal standings list.
    Validates for All-Star contamination and minimum team count.
    Raises ValueError on bad data.  Shared by server fetch and browser-push.
    """
    result_set  = result_sets[0]
    col_headers = result_set['headers']
    rows        = result_set['rowSet']

    def col(row, name):
        return row[col_headers.index(name)]

    standings = []
    for row in rows:
        try:
            games_back = float(col(row, 'ConferenceGamesBack') or 0)
        except (ValueError, KeyError, IndexError):
            games_back = 0.0
        standings.append({
            'team_id':      col(row, 'TeamID'),
            'team_name':    f"{col(row, 'TeamCity')} {col(row, 'TeamName')}",
            'conference':   col(row, 'Conference'),   # 'East' or 'West'
            'wins':         int(col(row, 'WINS')),
            'losses':       int(col(row, 'LOSSES')),
            'win_pct':      float(col(row, 'WinPCT')),
            'conf_rank':    99,
            'playoff_rank': 99,
            'games_back':   games_back,
        })

    # ── All-Star / bad-data guard ────────────────────────────────────────────
    bad_teams = [
        t for t in standings
        if t['conference'].lower().strip() not in ('east', 'west')
        or any(kw in t['team_name'].lower() for kw in _ALLSTAR_KEYWORDS)
    ]
    if bad_teams:
        sample = bad_teams[0]['team_name']
        raise ValueError(
            f"API returned All-Star data instead of Regular Season — "
            f"first suspicious team: '{sample}'. "
            f"Skipping save to prevent corrupting standings."
        )
    if len(standings) < 28:
        raise ValueError(
            f"API returned only {len(standings)} teams (expected 30) — "
            f"data appears incomplete or non-regular-season."
        )

    # Recompute conf_rank by win_pct, ties broken by wins
    for conf in ['East', 'West']:
        conf_teams = sorted(
            [t for t in standings if t['conference'] == conf],
            key=lambda x: (-x['win_pct'], -x['wins'])
        )
        for idx, team in enumerate(conf_teams, 1):
            team['conf_rank']    = idx
            team['playoff_rank'] = idx

    return standings


def _fetch_standings_from_api():
    """
    Fetch standings from stats.nba.com using requests directly (not nba_api
    wrapper).  3 attempts with exponential backoff (2 s, 4 s).  Raises last
    exception if all attempts fail.

    Key changes vs old nba_api approach:
    - Uses requests.get() — full control over headers, no hidden Accept-Encoding
    - Accept-Encoding: identity forces plain-text JSON (no gzip decode issues)
    - Rotates User-Agent each attempt to reduce IP-based rate-limiting
    """
    import random
    import requests as _http

    last_err = None
    for attempt in range(1, 4):
        ua = random.choice(_USER_AGENTS)
        headers = {**_NBA_HEADERS, 'User-Agent': ua}
        try:
            print(f"[Standings] Direct HTTP fetch attempt {attempt}/3 "
                  f"(UA: {ua[8:50]}…, timeout={_NBA_TIMEOUT}s)")
            http_resp = _http.get(
                _NBA_STANDINGS_URL,
                headers=headers,
                timeout=_NBA_TIMEOUT,
                allow_redirects=True,
            )
            print(f"[Standings] HTTP status: {http_resp.status_code} "
                  f"encoding: {http_resp.encoding} "
                  f"content-type: {http_resp.headers.get('content-type','?')}")
            http_resp.raise_for_status()
            raw = http_resp.json()
            print(f"[Standings] ✓ NBA API responded on attempt {attempt}")
            break
        except Exception as e:
            last_err = e
            status_code = getattr(getattr(e, 'response', None), 'status_code', None)
            if status_code:
                body = ''
                try: body = e.response.text[:600]
                except Exception: pass
                print(f"[Standings] ✗ Attempt {attempt} — HTTP {status_code}: {body}")
            else:
                print(f"[Standings] ✗ Attempt {attempt} — {type(e).__name__}: {e}")
            if attempt < 3:
                backoff = 2 ** attempt
                print(f"[Standings] Retrying in {backoff}s…")
                time.sleep(backoff)
    else:
        raise last_err  # all 3 attempts failed

    return _parse_standings_result_sets(raw['resultSets'])


def _compute_team_status(conf_rank: int) -> str:
    """Map conference rank to human-readable playoff status."""
    if conf_rank <= 6:  return 'Playoff'
    if conf_rank <= 10: return 'Play-In'
    return 'Eliminated'


def _send_onesignal_notification(title: str, body: str, url: str = "https://nba-playoffs-2026.vercel.app") -> bool:
    """
    Send a push notification to all subscribed users via OneSignal REST API.
    Returns True on success, False on failure.  Never raises.
    """
    if not _ONESIGNAL_API_KEY:
        print("[OneSignal] ONESIGNAL_API_KEY not set — skipping push notification")
        return False
    import urllib.request, json as _json
    payload = _json.dumps({
        "app_id":            _ONESIGNAL_APP_ID,
        "included_segments": ["All"],
        "headings":          {"en": title},
        "contents":          {"en": body},
        "url":               url,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://onesignal.com/api/v1/notifications",
        data=payload,
        headers={
            "Content-Type":  "application/json; charset=utf-8",
            "Authorization": f"Key {_ONESIGNAL_API_KEY}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = _json.loads(resp.read())
            print(f"[OneSignal] Notification sent — recipients: {result.get('recipients', '?')}")
            return True
    except Exception as e:
        print(f"[OneSignal] Notification error: {e}")
        return False


def _send_email_reminders(user_rows: list) -> None:
    """
    Send missing-picks email reminders via Resend to a list of (user_id, email) pairs.
    Silently no-ops if RESEND_API_KEY is not configured.
    """
    if not _RESEND_API_KEY or not user_rows:
        return
    try:
        import resend as _resend
        _resend.api_key = _RESEND_API_KEY
        emails_sent = 0
        for _uid, email in user_rows:
            if not email:
                continue
            try:
                _resend.Emails.send({
                    "from":    _RESEND_FROM,
                    "to":      [email],
                    "subject": "\U0001f3c0 \u05d0\u05dc \u05ea\u05e9\u05db\u05d7 \u05d0\u05ea \u05d4\u05e0\u05d9\u05d7\u05d5\u05e9\u05d9\u05dd \u05e9\u05dc\u05da \u05dc-NBA!",
                    "html": (
                        "<div dir='rtl' style='font-family:sans-serif;max-width:480px;"
                        "     margin:auto;padding:24px;text-align:right;'>"
                        "<h2 style='color:#f97316;margin-bottom:8px;'>"
                        "\u05d9\u05e9 \u05dc\u05da \u05e0\u05d9\u05d7\u05d5\u05e9\u05d9\u05dd \u05e4\u05ea\u05d5\u05d7\u05d9\u05dd!"
                        "</h2>"
                        "<p style='color:#334155;'>"
                        "\u05d9\u05e9 \u05e1\u05d3\u05e8\u05d5\u05ea \u05e4\u05dc\u05d9\u05d9\u05d0\u05d5\u05e3 \u05e4\u05e2\u05d9\u05dc\u05d5\u05ea"
                        " \u05e9\u05de\u05d7\u05db\u05d5\u05ea \u05dc\u05ea\u05d7\u05d6\u05d9\u05d5\u05ea \u05e9\u05dc\u05da."
                        "</p>"
                        "<p style='color:#334155;'>"
                        "\u05d0\u05dc \u05ea\u05e4\u05e1\u05e4\u05e1 \u05d0\u05ea \u05d4\u05d4\u05d6\u05d3\u05de\u05e0\u05d5\u05ea"
                        " \u05dc\u05e6\u05d1\u05d5\u05e8 \u05e0\u05e7\u05d5\u05d3\u05d5\u05ea"
                        " \u2013 \u05db\u05dc \u05e0\u05d9\u05d7\u05d5\u05e9 \u05e0\u05db\u05d5\u05df \u05e7\u05d5\u05d1\u05e2!"
                        "</p>"
                        "<a href='https://nba-playoffs-2026.vercel.app'"
                        "   style='display:inline-block;margin-top:16px;padding:12px 24px;"
                        "          background:#f97316;color:#fff;border-radius:8px;"
                        "          text-decoration:none;font-weight:bold;'>"
                        "\u05dc\u05de\u05d9\u05dc\u05d5\u05d9 \u05d4\u05e0\u05d9\u05d7\u05d5\u05e9\u05d9\u05dd \u05e9\u05dc\u05d9 \u2190"
                        "</a>"
                        "<p style='color:#94a3b8;font-size:12px;margin-top:24px;'>"
                        "\u05d4\u05de\u05d9\u05d9\u05dc \u05e0\u05e9\u05dc\u05d7 \u05d0\u05dc\u05d9\u05da \u05db\u05d9"
                        " \u05d9\u05e9 \u05dc\u05da \u05d7\u05e9\u05d1\u05d5\u05df"
                        " \u05d1-NBA Playoff Predictor 2026."
                        "</p>"
                        "</div>"
                    ),
                })
                emails_sent += 1
            except Exception as e:
                print(f"[Email] Failed to send to {email}: {e}")
        print(f"[Email] Resend reminders sent: {emails_sent}/{len(user_rows)}")
    except ImportError:
        print("[Email] resend package not installed — skipping email reminders")
    except Exception as e:
        print(f"[Email] Resend error: {e}")


def _send_missing_picks_alert() -> None:
    """
    Twice-daily cron (06:00 UTC = 09:00 IDT, 18:00 UTC = 21:00 IDT):
    find users who have at least one active/unlocked series with no prediction,
    then send them a targeted OneSignal push AND a Resend email reminder.
    Runs until _STANDINGS_SYNC_CUTOFF; skips silently if no credentials are set.
    """
    if datetime.utcnow() >= _STANDINGS_SYNC_CUTOFF:
        return

    has_push  = bool(_ONESIGNAL_API_KEY)
    has_email = bool(_RESEND_API_KEY)
    if not has_push and not has_email:
        print("[Alert] Neither ONESIGNAL_API_KEY nor RESEND_API_KEY set — skipping alert")
        return

    conn = None
    try:
        conn = get_db_conn()
        c    = conn.cursor()

        # Are there any active (unlocked) series right now?
        c.execute("SELECT COUNT(*) FROM series WHERE season = '2026' AND status = 'active'")
        if not c.fetchone()[0]:
            print("[Alert] No active series — skipping missing-picks alert")
            return

        # Users (id + email) who are missing at least one active-series prediction
        c.execute("""
            SELECT DISTINCT u.id::text, u.email
            FROM users u
            WHERE EXISTS (
                SELECT 1 FROM series s
                WHERE s.season = '2026' AND s.status = 'active'
                AND NOT EXISTS (
                    SELECT 1 FROM predictions p
                    WHERE p.user_id = u.id AND p.series_id = s.id
                )
            )
        """)
        rows = c.fetchall()          # list of (str_id, email)
        conn.close()
        conn = None

        if not rows:
            print("[Alert] All users have completed their picks — no alert needed")
            return

        user_ids   = [r[0] for r in rows]
        print(f"[Alert] Notifying {len(rows)} user(s) with missing picks")

        # ── OneSignal push ────────────────────────────────────────────────
        if has_push:
            import urllib.request, json as _json
            payload = _json.dumps({
                "app_id":          _ONESIGNAL_APP_ID,
                "include_aliases": {"external_id": user_ids},
                "target_channel":  "push",
                "headings":        {"en": "🏀 Don't forget your picks!"},
                "contents":        {"en": "You have open NBA playoff series waiting. Lock them in before it's too late!"},
                "url":             "https://nba-playoffs-2026.vercel.app",
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://onesignal.com/api/v1/notifications",
                data=payload,
                headers={
                    "Content-Type":  "application/json; charset=utf-8",
                    "Authorization": f"Key {_ONESIGNAL_API_KEY}",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    result = _json.loads(resp.read())
                    print(f"[Alert] Push sent — recipients: {result.get('recipients', '?')}")
            except Exception as e:
                print(f"[Alert] OneSignal push error: {e}")

        # ── Resend email ──────────────────────────────────────────────────
        if has_email:
            threading.Thread(target=_send_email_reminders, args=(rows,), daemon=True).start()

    except Exception as e:
        print(f"[Alert] Missing-picks alert error: {e}")
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def _persist_standings_to_db(standings: list) -> dict:
    """
    Upsert standings rows to cached_standings using (team_id, season) as the
    unique key.  Looks up team abbreviations from the teams table.
    Returns {'rows': int, 'synced_at': datetime|None}.
    """
    conn = None
    try:
        conn = get_db_conn()
        c    = conn.cursor()

        # Build abbreviation lookup from the teams table (populated by sync_teams)
        c.execute("SELECT id, abbreviation FROM teams")
        abbr_map = {r[0]: r[1] for r in c.fetchall()}

        # Snapshot existing statuses to detect significant rank changes after upsert
        c.execute("SELECT team_id, status, team_name FROM cached_standings WHERE season = '2026'")
        prev_status = {r[0]: {'status': r[1], 'name': r[2]} for r in c.fetchall()}

        # Delete stale rows that are NOT in the fresh batch — removes any
        # previously-saved All-Star or orphaned team rows from cached_standings.
        fresh_team_ids = tuple(t['team_id'] for t in standings)
        if fresh_team_ids:
            placeholders = ','.join(['%s'] * len(fresh_team_ids))
            c.execute(
                f"DELETE FROM cached_standings WHERE season = '2026' AND team_id NOT IN ({placeholders})",
                fresh_team_ids
            )
            deleted = c.rowcount
            if deleted:
                print(f"[Standings] Removed {deleted} stale row(s) from cached_standings (season=2026)")

        synced_at = datetime.utcnow()
        for t in standings:
            team_id   = t['team_id']
            abbr      = abbr_map.get(team_id, t['team_name'].split()[-1][:3].upper())
            status    = _compute_team_status(t.get('conf_rank', 99))
            games_back = float(t.get('games_back', 0.0) or 0.0)
            c.execute('''
                INSERT INTO cached_standings
                    (team_id, team_name, abbreviation, conference,
                     wins, losses, win_pct, conf_rank,
                     games_back, status, season, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '2026', %s)
                ON CONFLICT (team_id, season) DO UPDATE SET
                    team_name   = EXCLUDED.team_name,
                    wins        = EXCLUDED.wins,
                    losses      = EXCLUDED.losses,
                    win_pct     = EXCLUDED.win_pct,
                    conf_rank   = EXCLUDED.conf_rank,
                    games_back  = EXCLUDED.games_back,
                    status      = EXCLUDED.status,
                    updated_at  = EXCLUDED.updated_at
            ''', (team_id, t['team_name'], abbr, t['conference'],
                  t['wins'], t['losses'], t['win_pct'], t['conf_rank'],
                  games_back, status, synced_at))

        conn.commit()

        # Detect teams that crossed a playoff/play-in boundary
        rank_changes = []
        for t in standings:
            tid = t['team_id']
            new_status = _compute_team_status(t.get('conf_rank', 99))
            old_status = prev_status.get(tid, {}).get('status')
            if old_status and old_status != new_status:
                rank_changes.append({
                    'team':   t['team_name'],
                    'from':   old_status,
                    'to':     new_status,
                })

        print(f"[Standings] Persisted {len(standings)} rows to DB at {synced_at.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        if rank_changes:
            print(f"[Standings] {len(rank_changes)} status change(s) detected: {rank_changes}")
        return {'rows': len(standings), 'synced_at': synced_at, 'rank_changes': rank_changes}

    except Exception as e:
        print(f"[Standings] DB persist error: {e}")
        if conn:
            try: conn.rollback()
            except Exception: pass
        return {'rows': 0, 'synced_at': None}
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def _standings_sync_job():
    """
    Master cron job — called by APScheduler (0 */6 * * * UTC) and by the
    force-refresh endpoint.  Runs standings + player-stats sync in sequence.
    Returns True if standings sync succeeded.
    """
    now = datetime.utcnow()
    _sync_status["last_attempt_at"] = now

    if now >= _STANDINGS_SYNC_CUTOFF:
        msg = f"Regular season ended on {_STANDINGS_SYNC_CUTOFF.date()} — all syncs disabled"
        print(f"[Sync] {msg}")
        _sync_status["last_error"] = msg
        return False

    # Standings now use requests directly — no nba_api needed.
    # Player stats still needs nba_api; that check is inside _sync_player_stats_job.
    print(f"[Sync] Starting full data sync at {now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    standings_ok = False

    # ── 1. Standings ────────────────────────────────────────────────────
    # Try RapidAPI first; if it fails (any exception including ValueError from
    # a bad/unexpected response shape) fall through to stats.nba.com.
    fresh       = None
    used_source = None

    if _RAPIDAPI_KEY:
        # ── Source 1: Primary API (api-basketball-nba) ──
        try:
            print(f"[Standings] Trying Primary API ({_RAPIDAPI_HOST_PRIMARY})")
            fresh       = _fetch_standings_from_primary_api()
            used_source = "primary_api"
            print(f"[Standings] ✓ Source: Primary API")
        except Exception as _primary_err:
            print(f"[Standings] Primary API failed ({type(_primary_err).__name__}: "
                  f"{str(_primary_err)[:200]}) — trying Secondary API")

        # ── Source 2: Secondary API (nba-api-free-data) ──
        if fresh is None:
            try:
                print(f"[Standings] Trying Secondary API ({_RAPIDAPI_HOST_SECONDARY})")
                fresh       = _fetch_standings_from_rapidapi()
                used_source = "rapidapi"
                print(f"[Standings] ✓ Source: Secondary API")
            except Exception as _rapid_err:
                import traceback as _tb
                print(f"[Standings] Secondary API failed ({type(_rapid_err).__name__}: "
                      f"{str(_rapid_err)[:200]}) — falling back to stats.nba.com")
                print(f"[Standings] Secondary traceback:\n{_tb.format_exc()}")

    if fresh is None:
        try:
            print(f"[Standings] Trying stats.nba.com direct request")
            fresh       = _fetch_standings_from_api()
            used_source = "nba_api"
        except Exception as _nba_err:
            print(f"[Standings] stats.nba.com also failed: {type(_nba_err).__name__}: {_nba_err}")

    try:
        if fresh is None:
            raise RuntimeError("All standings sources failed — no data to persist")

        result = _persist_standings_to_db(fresh)
        if result['synced_at']:
            _standings_cache["data"]       = fresh
            _standings_cache["fetched_at"] = result['synced_at']
            _standings_cache["expires"]    = result['synced_at'] + timedelta(hours=6)
            next_at = (result['synced_at'] + timedelta(hours=6)).strftime('%H:%M UTC')
            # Sanity log: show #1 East and #1 West
            e1 = next((t for t in fresh if t['conference']=='East' and t['conf_rank']==1), None)
            w1 = next((t for t in fresh if t['conference']=='West' and t['conf_rank']==1), None)
            print(f"[Standings] ✓ {result['rows']} teams synced via {used_source} — "
                  f"#1 East: {e1 and e1['team_name']}  #1 West: {w1 and w1['team_name']}  "
                  f"next run ~{next_at}")
            standings_ok = True
            _sync_status["source"]               = used_source
            _sync_status["last_success_at"]      = result['synced_at']
            _sync_status["last_error"]           = None
            _sync_status["consecutive_failures"] = 0
            # Keep play-in matchups in sync with the latest seeds 7-10
            try:
                refresh_playin_matchups('2026')
            except Exception as _rpe:
                print(f"[Standings] refresh_playin_matchups failed (non-fatal): {_rpe}")
            # Push notification when teams cross playoff/play-in boundaries
            changes = result.get('rank_changes', [])
            if changes:
                parts = []
                for c in changes[:3]:
                    emoji = '✅' if c['to'] == 'Playoff' else ('⚠️' if c['to'] == 'Play-In' else '❌')
                    parts.append(f"{emoji} {c['team']}: {c['from']} → {c['to']}")
                body = '\n'.join(parts)
                if len(changes) > 3:
                    body += f'\n+{len(changes) - 3} more'
                threading.Thread(
                    target=_send_onesignal_notification,
                    args=("🏀 NBA Standings Update", body),
                    daemon=True,
                ).start()
        else:
            msg = "DB persist returned no synced_at — check DB logs"
            _sync_status["last_error"] = msg
            _sync_status["consecutive_failures"] = _sync_status.get("consecutive_failures", 0) + 1
    except Exception as e:
        import traceback
        full_err = traceback.format_exc()
        short_err = f"{type(e).__name__}: {str(e)[:300]}"
        print(f"[Standings] ✗ Sync error: {short_err}")
        print(f"[Standings] Full traceback:\n{full_err}")
        _sync_status["last_error"]           = short_err
        _sync_status["consecutive_failures"] = _sync_status.get("consecutive_failures", 0) + 1

    if not standings_ok:
        print(f"[Standings] ✗ Sync failed (consecutive failures: {_sync_status['consecutive_failures']})")
        # Best-effort: if the in-memory cache is empty, try to warm it from DB
        # so at least the most recent persisted snapshot is served instead of hardcoded
        if not _standings_cache.get("data"):
            db_rows = _load_standings_from_db()
            if db_rows:
                now = datetime.now()
                _standings_cache["data"]       = db_rows
                _standings_cache["fetched_at"] = now
                _standings_cache["expires"]    = now + timedelta(hours=1)
                _sync_status["source"]         = "database"
                print(f"[Standings] Warmed cache from DB ({len(db_rows)} rows) after API failure")

    # ── 2. Player stats (independent — standings failure doesn't block this) ──
    _sync_player_stats_job()

    return standings_ok


def _apply_standings_migration():
    """
    Idempotent DDL: add games_back / status columns and the (team_id, season)
    unique constraint needed for ON CONFLICT upserts.
    Runs with autocommit on its own connection (safe against PgBouncer pooler).
    """
    try:
        conn = get_db_conn()
        conn.autocommit = True
        c = conn.cursor()
        c.execute("SET search_path TO public")

        for col, defn in [("games_back", "REAL    DEFAULT 0.0"),
                          ("status",     "TEXT    DEFAULT 'Unknown'")]:
            try:
                c.execute(f"ALTER TABLE cached_standings ADD COLUMN IF NOT EXISTS {col} {defn}")
                print(f"[Migration] cached_standings.{col} ensured")
            except Exception as e:
                print(f"[Migration] cached_standings.{col}: {e}")

        # Add UNIQUE(team_id, season) if it doesn't already exist — required
        # by the ON CONFLICT clause in _persist_standings_to_db.
        try:
            c.execute("""
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                         WHERE conrelid = 'cached_standings'::regclass
                           AND conname  = 'cached_standings_team_season_key'
                    ) THEN
                        ALTER TABLE cached_standings
                            ADD CONSTRAINT cached_standings_team_season_key
                            UNIQUE (team_id, season);
                    END IF;
                END $$;
            """)
            print("[Migration] cached_standings(team_id, season) unique constraint ensured")
        except Exception as e:
            print(f"[Migration] cached_standings unique constraint: {e}")

        conn.close()
    except Exception as e:
        print(f"[Migration] Standings migration connection error (non-fatal): {e}")


def _load_standings_from_db():
    """Read standings from cached_standings, including games_back and status."""
    try:
        conn = get_db_conn()
        c = conn.cursor()
        c.execute('''SELECT team_id, team_name, conference, wins, losses, win_pct,
                            conf_rank,
                            COALESCE(games_back, 0.0),
                            COALESCE(status, 'Unknown'),
                            updated_at
                     FROM cached_standings
                     WHERE season = '2026'
                     ORDER BY conference, conf_rank''')
        rows = c.fetchall()
        conn.close()
        if not rows:
            return []
        return [
            {'team_id': r[0], 'team_name': r[1], 'conference': r[2],
             'wins': r[3], 'losses': r[4], 'win_pct': r[5],
             'conf_rank': r[6], 'playoff_rank': r[6],
             'games_back': float(r[7]), 'status': r[8]}
            for r in rows
        ]
    except Exception as e:
        print(f"DB standings load error: {e}")
        return []


def get_standings():
    """
    Returns standings instantly from memory cache → DB → hardcoded fallback.
    Never blocks on the NBA API.  For a live refresh use _standings_sync_job().
    """
    if _standings_cache["data"]:
        return _standings_cache["data"]

    db_data = _load_standings_from_db()
    if db_data:
        print("Using DB-seeded standings")
        now = datetime.now()
        _standings_cache["data"]       = db_data
        _standings_cache["fetched_at"] = now
        _standings_cache["expires"]    = now + timedelta(hours=1)
        if _sync_status["source"] not in ("nba_api",):
            _sync_status["source"] = "database"
        return db_data

    print("Using hardcoded standings fallback")
    if _sync_status["source"] not in ("nba_api", "database"):
        _sync_status["source"] = "hardcoded"
    return _HARDCODED_STANDINGS


def _apply_player_stats_migration():
    """
    Idempotent DDL:
      - Create player_stats if it doesn't exist; add new columns.
      - Create player_game_stats (per-game boxscore table) if it doesn't exist.
    Uses autocommit so each DDL statement is independent.
    """
    try:
        conn = get_db_conn()
        conn.autocommit = True
        c = conn.cursor()
        c.execute("SET search_path TO public")

        # ── Base player_stats table ──────────────────────────────────────
        c.execute('''CREATE TABLE IF NOT EXISTS player_stats (
            id                SERIAL PRIMARY KEY,
            player_id         INTEGER NOT NULL,
            player_name       TEXT    NOT NULL,
            team_abbreviation TEXT,
            season            TEXT    DEFAULT '2026',
            games_played      INTEGER DEFAULT 0,
            pts_per_game      REAL    DEFAULT 0,
            ast_per_game      REAL    DEFAULT 0,
            reb_per_game      REAL    DEFAULT 0,
            stl_per_game      REAL    DEFAULT 0,
            blk_per_game      REAL    DEFAULT 0,
            fg3m_per_game     REAL    DEFAULT 0,
            updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(player_id, season)
        )''')

        # ── New columns on player_stats (idempotent) ─────────────────────
        new_ps_cols = [
            ("espn_player_id", "INTEGER"),
            ("fgm_per_game",   "REAL DEFAULT 0"),
            ("fga_per_game",   "REAL DEFAULT 0"),
            ("ftm_per_game",   "REAL DEFAULT 0"),
            ("tov_per_game",   "REAL DEFAULT 0"),
            ("min_per_game",   "REAL DEFAULT 0"),
            ("oreb_per_game",  "REAL DEFAULT 0"),
            ("dreb_per_game",  "REAL DEFAULT 0"),
        ]
        for col_name, col_type in new_ps_cols:
            try:
                c.execute(
                    f"ALTER TABLE player_stats "
                    f"ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
                )
            except Exception as col_err:
                print(f"[Migration] player_stats.{col_name}: {col_err}")

        # ── Per-game boxscore table ───────────────────────────────────────
        c.execute('''CREATE TABLE IF NOT EXISTS player_game_stats (
            id             SERIAL PRIMARY KEY,
            espn_game_id   TEXT    NOT NULL,
            game_date      DATE    NOT NULL,
            espn_player_id TEXT    NOT NULL,
            player_name    TEXT    NOT NULL,
            espn_team_id   TEXT    NOT NULL,
            team_abbr      TEXT    DEFAULT '',
            season         TEXT    DEFAULT '2026',
            minutes        REAL    DEFAULT 0,
            points         INTEGER DEFAULT 0,
            rebounds       INTEGER DEFAULT 0,
            assists        INTEGER DEFAULT 0,
            steals         INTEGER DEFAULT 0,
            blocks         INTEGER DEFAULT 0,
            turnovers      INTEGER DEFAULT 0,
            fgm            INTEGER DEFAULT 0,
            fga            INTEGER DEFAULT 0,
            fg3m           INTEGER DEFAULT 0,
            fg3a           INTEGER DEFAULT 0,
            ftm            INTEGER DEFAULT 0,
            fta            INTEGER DEFAULT 0,
            oreb           INTEGER DEFAULT 0,
            dreb           INTEGER DEFAULT 0,
            fouls          INTEGER DEFAULT 0,
            plus_minus     INTEGER DEFAULT 0,
            UNIQUE(espn_game_id, espn_player_id)
        )''')

        # Add team_abbr to player_game_stats if it doesn't exist yet
        try:
            c.execute(
                "ALTER TABLE player_game_stats "
                "ADD COLUMN IF NOT EXISTS team_abbr TEXT DEFAULT ''"
            )
        except Exception:
            pass

        # Index for fast player name search (supports ILIKE prefix queries)
        try:
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_player_stats_name "
                "ON player_stats (player_name text_pattern_ops)"
            )
        except Exception:
            pass

        print("[Migration] player_stats + player_game_stats tables ensured")
        conn.close()
    except Exception as e:
        print(f"[Migration] player_stats: {e}")


def _sync_player_stats_job():
    """
    Fetch ALL active players' per-game stats from LeagueDashPlayerStats and upsert
    into player_stats.  Uses LeagueDashPlayerStats (returns every player who played
    at least 1 game this season) instead of LeagueLeaders top-150, so the full
    playoff roster including lower-usage players is available for MVP/leader search.
    Returns True on success.
    """
    if datetime.utcnow() >= _STANDINGS_SYNC_CUTOFF:
        print("[Players] Cutoff reached — skipping player stats sync")
        return False
    if not NBA_API_AVAILABLE:
        print("[Players] NBA API module not available — skipping")
        return False

    try:
        from nba_api.stats.endpoints import leaguedashplayerstats
        print("[Players] Fetching all player stats (LeagueDashPlayerStats)…")
        lp = leaguedashplayerstats.LeagueDashPlayerStats(
            season='2025-26',
            season_type_all_star='Regular Season',
            per_mode_simple='PerGame',
            league_id_nullable='00',
            headers=_NBA_HEADERS,
            timeout=_NBA_TIMEOUT,
        )
        raw = lp.get_dict()

        result_set  = raw.get('resultSets', [{}])[0]
        col_headers = result_set['headers']
        rows        = result_set['rowSet']

        def col(row, name, default=0):
            try:
                return row[col_headers.index(name)]
            except (ValueError, IndexError):
                return default

        conn      = get_db_conn()
        c         = conn.cursor()
        synced_at = datetime.utcnow()
        count     = 0

        for row in rows:  # ALL players — no limit
            pid  = col(row, 'PLAYER_ID')
            name = col(row, 'PLAYER_NAME', '')
            team = col(row, 'TEAM_ABBREVIATION', '')
            gp   = int(col(row, 'GP') or 0)
            pts  = float(col(row, 'PTS') or 0)
            ast  = float(col(row, 'AST') or 0)
            reb  = float(col(row, 'REB') or 0)
            stl  = float(col(row, 'STL') or 0)
            blk  = float(col(row, 'BLK') or 0)
            fg3m = float(col(row, 'FG3M') or 0)
            if not pid or not name:
                continue
            c.execute('''
                INSERT INTO player_stats
                    (player_id, player_name, team_abbreviation, season,
                     games_played, pts_per_game, ast_per_game, reb_per_game,
                     stl_per_game, blk_per_game, fg3m_per_game, updated_at)
                VALUES (%s, %s, %s, '2026', %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (player_id, season) DO UPDATE SET
                    player_name       = EXCLUDED.player_name,
                    team_abbreviation = EXCLUDED.team_abbreviation,
                    games_played      = EXCLUDED.games_played,
                    pts_per_game      = EXCLUDED.pts_per_game,
                    ast_per_game      = EXCLUDED.ast_per_game,
                    reb_per_game      = EXCLUDED.reb_per_game,
                    stl_per_game      = EXCLUDED.stl_per_game,
                    blk_per_game      = EXCLUDED.blk_per_game,
                    fg3m_per_game     = EXCLUDED.fg3m_per_game,
                    updated_at        = EXCLUDED.updated_at
            ''', (pid, name, team, gp, pts, ast, reb, stl, blk, fg3m, synced_at))
            count += 1

        conn.commit()
        conn.close()
        print(f"[Players] ✓ {count} player stats upserted at {synced_at.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        return True
    except Exception as e:
        import traceback
        print(f"[Players] LeagueDashPlayerStats error: {e}\n{traceback.format_exc()}")
        # Fallback to LeagueLeaders top-150 if LeagueDashPlayerStats fails
        try:
            from nba_api.stats.endpoints import leagueleaders
            print("[Players] Falling back to LeagueLeaders top-300…")
            ll = leagueleaders.LeagueLeaders(
                league_id='00',
                per_mode48='PerGame',
                scope='S',
                season='2025-26',
                season_type_all_star='Regular Season',
                stat_category_abbreviation='PTS',
                headers=_NBA_HEADERS,
                timeout=_NBA_TIMEOUT,
            )
            raw2        = ll.get_dict()
            rs2         = raw2.get('resultSet') or raw2.get('resultSets', [{}])[0]
            col_h2      = rs2['headers']
            rows2       = rs2['rowSet']
            def col2(row, name, default=0):
                try: return row[col_h2.index(name)]
                except (ValueError, IndexError): return default
            conn2     = get_db_conn()
            c2        = conn2.cursor()
            synced2   = datetime.utcnow()
            count2    = 0
            for row in rows2[:300]:
                pid  = col2(row, 'PLAYER_ID')
                name = col2(row, 'PLAYER', '')
                team = col2(row, 'TEAM', '')
                if not pid or not name: continue
                c2.execute('''
                    INSERT INTO player_stats
                        (player_id, player_name, team_abbreviation, season,
                         games_played, pts_per_game, ast_per_game, reb_per_game,
                         stl_per_game, blk_per_game, fg3m_per_game, updated_at)
                    VALUES (%s,%s,%s,'2026',%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (player_id, season) DO UPDATE SET
                        player_name=EXCLUDED.player_name,team_abbreviation=EXCLUDED.team_abbreviation,
                        games_played=EXCLUDED.games_played,pts_per_game=EXCLUDED.pts_per_game,
                        ast_per_game=EXCLUDED.ast_per_game,reb_per_game=EXCLUDED.reb_per_game,
                        stl_per_game=EXCLUDED.stl_per_game,blk_per_game=EXCLUDED.blk_per_game,
                        fg3m_per_game=EXCLUDED.fg3m_per_game,updated_at=EXCLUDED.updated_at
                ''', (pid, name, team,
                      int(col2(row,'GP') or 0), float(col2(row,'PTS') or 0),
                      float(col2(row,'AST') or 0), float(col2(row,'REB') or 0),
                      float(col2(row,'STL') or 0), float(col2(row,'BLK') or 0),
                      float(col2(row,'FG3M') or 0), synced2))
                count2 += 1
            conn2.commit()
            conn2.close()
            print(f"[Players] ✓ Fallback: {count2} players upserted")
            return True
        except Exception as e2:
            print(f"[Players] Fallback also failed: {e2}")
            return False


def _initial_standings_sync():
    """
    One-shot background thread at startup: waits for a random jitter then
    runs the first standings sync so the DB is fresh within ~40s of boot.
    APScheduler takes over every 6 h after that.
    """
    import random
    delay = random.uniform(15, 45)
    print(f"[Standings] Initial sync starts in {delay:.0f}s")
    time.sleep(delay)
    _standings_sync_job()

def sync_daily_boxscores(date_str: str | None = None, season: str = '2026') -> dict:
    """
    Fetch completed NBA games for a given date, pull full player boxscores
    from the ESPN public summary API, and upsert into player_game_stats.

    Also back-fills espn_player_id on existing player_stats rows via name match.

    Args:
        date_str: 'YYYY-MM-DD' or 'YYYYMMDD'.  Defaults to yesterday UTC.
        season:   Season tag stored on every row (default '2026').

    Returns a summary dict:
      { date, games_found, games_processed, players_upserted, espn_id_updates, errors }
    """
    import requests as _http
    from datetime import date as _date, timedelta as _td

    # ── Helpers ────────────────────────────────────────────────────────────
    def _safe_int(v, default=0):
        try: return int(str(v).strip())
        except: return default

    def _safe_float_min(v, default=0.0):
        """Parse "MM:SS" or plain integer minutes to a float."""
        try:
            s = str(v).strip()
            if ':' in s:
                mm, ss = s.split(':', 1)
                return round(int(mm) + int(ss) / 60, 2)
            return round(float(s), 2)
        except:
            return default

    def _split_compound(v, default=0):
        """
        Split 'FGM-FGA' compound strings like "6-14" → (6, 14).
        Handles negatives (plusMinus "-5") and plain integers safely.
        """
        s = str(v).strip()
        # Find a '-' that is NOT the first character (not a leading minus)
        idx = s.find('-', 1)
        if idx > 0:
            try:
                return int(s[:idx]), int(s[idx + 1:])
            except:
                return default, default
        try:
            val = int(s)
            return val, val   # single value — both sides the same
        except:
            return default, default

    def _pm(v, default=0):
        """Parse plus-minus: '+18' or '-5' → int."""
        try:
            return int(str(v).strip().lstrip('+'))
        except:
            return default

    # ── Resolve date ───────────────────────────────────────────────────────
    if date_str is None:
        target = (datetime.utcnow() - _td(days=1)).date()
    else:
        ds = date_str.replace('-', '')
        target = _date(int(ds[:4]), int(ds[4:6]), int(ds[6:8]))

    date_fmt = target.strftime('%Y%m%d')   # YYYYMMDD for RapidAPI
    date_iso = target.isoformat()           # YYYY-MM-DD for DB

    summary = {
        'date': date_iso, 'games_found': 0, 'games_processed': 0,
        'players_upserted': 0, 'espn_id_updates': 0, 'errors': [],
    }

    if not _RAPIDAPI_KEY:
        summary['errors'].append("RAPIDAPI_KEY not set")
        return summary

    # ── Step 1: Scoreboard — Primary API first, Secondary fallback ─────────
    normalized_events = []   # list of dicts from _fetch_scoreboard_primary()
    scoreboard_source = "none"

    try:
        print(f"[Boxscore] Step 1: scoreboard via Primary API ({date_iso})")
        normalized_events = _fetch_scoreboard_primary(date_iso)
        scoreboard_source = "primary_api"
    except Exception as _sb_primary_err:
        print(f"[Boxscore] Primary scoreboard failed: {_sb_primary_err} — trying Secondary")

    if not normalized_events:
        try:
            print(f"[Boxscore] Step 1b: scoreboard via Secondary API ({date_fmt})")
            resp = _http.get(
                _RAPIDAPI_SCOREBOARD_BY_DATE_URL,
                headers={"x-rapidapi-key": _RAPIDAPI_KEY, "x-rapidapi-host": _RAPIDAPI_HOST_SECONDARY},
                params={"date": date_fmt},
                timeout=12,
            )
            resp.raise_for_status()
            data     = resp.json()
            resp_obj = data.get("response", data)
            raw_events = (
                resp_obj.get("Events") or resp_obj.get("events") or []
                if isinstance(resp_obj, dict) else
                (resp_obj if isinstance(resp_obj, list) else [])
            )
            # Normalize secondary events into same shape as primary
            for ev in raw_events:
                stype = (ev.get("status") or {}).get("type") or {}
                comps = ev.get("competitions") or [{}]
                comp  = comps[0]
                teams = comp.get("competitors") or []
                home_c = next((c for c in teams if c.get("homeAway") == "home"), {})
                away_c = next((c for c in teams if c.get("homeAway") == "away"), {})
                def _tm2(c):
                    t = c.get("team") or {}
                    return {"id": t.get("id"), "abbr": t.get("abbreviation"),
                            "name": t.get("displayName") or t.get("name"),
                            "score": c.get("score"), "winner": bool(c.get("winner"))}
                normalized_events.append({
                    "id":        str(ev.get("id", "")),
                    "completed": bool(stype.get("completed")),
                    "status":    stype.get("description") or stype.get("name"),
                    "clock":     (ev.get("status") or {}).get("displayClock"),
                    "period":    (ev.get("status") or {}).get("period"),
                    "home":      _tm2(home_c),
                    "away":      _tm2(away_c),
                    "broadcast": comp.get("broadcast") or "",
                })
            scoreboard_source = "secondary_api"
        except Exception as e:
            summary['errors'].append(f"Scoreboard fetch failed (both APIs): {e}")
            return summary

    _FINAL_STATUSES = {"final", "status_final", "game over", "f/ot", "f/2ot"}

    def _is_finished(ev: dict) -> bool:
        """
        Accept a game as finished if EITHER:
          • status.type.completed == true  (ESPN boolean)
          • status description text contains 'final' (Primary API may omit boolean)
        """
        if ev.get("completed"):
            return True
        st = (ev.get("status") or "").lower().strip()
        return st in _FINAL_STATUSES or st.startswith("final")

    completed_events = [ev for ev in normalized_events if _is_finished(ev)]
    summary['games_found'] = len(normalized_events)

    # Log each game's status to surface timezone/completion issues
    for _ev in normalized_events:
        print(f"[Boxscore]   game={_ev.get('id')} completed={_ev.get('completed')} "
              f"status={_ev.get('status')!r} finished={_is_finished(_ev)} "
              f"{(_ev.get('away') or {}).get('abbr','?')} @ "
              f"{(_ev.get('home') or {}).get('abbr','?')}")

    print(f"[Boxscore] {len(normalized_events)} games on {date_iso} via {scoreboard_source}, "
          f"{len(completed_events)} finished (completed flag OR Final status)")

    if not completed_events:
        print(f"[Boxscore] No finished games on {date_iso} — skipping boxscore fetch")
        return summary

    conn = get_db_conn()
    c    = conn.cursor()

    for ev in completed_events:
        event_id = str(ev.get("id", ""))
        if not event_id:
            continue

        # ── Step 2: Boxscore — Primary API first, ESPN direct fallback ───────
        parsed_players = []
        boxscore_source = "none"

        # 2a: Try Primary API (/nbabox)
        try:
            parsed_players  = _fetch_boxscore_primary(event_id)
            boxscore_source = "primary_api"
            if parsed_players:
                print(f"[Boxscore] Primary OK: game {event_id} — "
                      f"{len(parsed_players)} players parsed")
            else:
                print(f"[Boxscore] ⚠ Primary returned 0 players for game {event_id} "
                      f"— trying ESPN direct fallback")
        except Exception as _bx_primary_err:
            print(f"[Boxscore] ⚠ Primary /nbabox FAILED (game {event_id}): "
                  f"{type(_bx_primary_err).__name__}: {_bx_primary_err} "
                  f"— trying ESPN direct fallback")

        # 2b: Fallback — ESPN public API (no key needed)
        if not parsed_players:
            try:
                bs = _http.get(_ESPN_BOXSCORE_URL, params={"event": event_id}, timeout=12)
                bs.raise_for_status()
                bs_data = bs.json()
                players_section = (
                    (bs_data.get("boxscore") or {}).get("players")
                    or bs_data.get("players") or []
                )
                for team_entry in players_section:
                    team_obj      = team_entry.get("team") or {}
                    espn_tid_raw  = str(team_obj.get("id", ""))
                    abbr_raw      = (team_obj.get("abbreviation") or "").upper()
                    statistics    = team_entry.get("statistics") or []
                    if not statistics:
                        continue
                    sb     = statistics[0]
                    keys   = sb.get("keys") or sb.get("labels") or []
                    ki     = {k.lower(): i for i, k in enumerate(keys)}

                    def _espn_stat(key, default="0", _arr=None):
                        idx = ki.get(key.lower())
                        if idx is not None and idx < len(_arr or []):
                            v = (_arr or [])[idx]
                            return str(v) if v is not None else default
                        return default

                    for ath in (sb.get("athletes") or []):
                        athlete   = ath.get("athlete") or {}
                        pid_raw   = str(athlete.get("id", ""))
                        pname_raw = athlete.get("displayName") or athlete.get("fullName") or ""
                        sarr      = ath.get("stats") or []
                        if not pid_raw or not pname_raw or not sarr:
                            continue
                        def _s(k, d="0"): return _espn_stat(k, d, sarr)
                        fgm_e,  fga_e  = _split_compound(_s("fieldGoalsMade-fieldGoalsAttempted","0-0"))
                        fg3m_e, fg3a_e = _split_compound(_s("threePointFieldGoalsMade-threePointFieldGoalsAttempted","0-0"))
                        ftm_e,  fta_e  = _split_compound(_s("freeThrowsMade-freeThrowsAttempted","0-0"))
                        parsed_players.append({
                            "espn_pid":     pid_raw,
                            "player_name":  pname_raw,
                            "team_abbr":    abbr_raw,
                            "espn_team_id": espn_tid_raw,
                            "points":       _safe_int(_s("points")),
                            "rebounds":     _safe_int(_s("rebounds")),
                            "assists":      _safe_int(_s("assists")),
                            "steals":       _safe_int(_s("steals")),
                            "blocks":       _safe_int(_s("blocks")),
                            "turnovers":    _safe_int(_s("turnovers")),
                            "minutes":      _safe_float_min(_s("minutes")),
                            "fgm": fgm_e,   "fga": fga_e,
                            "fg3m": fg3m_e, "fg3a": fg3a_e,
                            "ftm": ftm_e,   "fta": fta_e,
                            "oreb":       _safe_int(_s("offensiveRebounds")),
                            "dreb":       _safe_int(_s("defensiveRebounds")),
                            "fouls":      _safe_int(_s("fouls")),
                            "plus_minus": _pm(_s("plusMinus", "0")),
                        })
                if parsed_players:
                    boxscore_source = "espn_direct"
                    print(f"[Boxscore] ESPN fallback OK: game {event_id} — "
                          f"{len(parsed_players)} players parsed")
                else:
                    msg = (f"ESPN fallback returned 0 players for game {event_id} "
                           f"(HTTP 200 but empty athletes array)")
                    print(f"[Boxscore] ⚠ {msg}")
                    summary['errors'].append(msg)
            except Exception as e:
                msg = (f"Both sources failed for game {event_id}: "
                       f"{type(e).__name__}: {e}")
                print(f"[Boxscore] ⚠ {msg}")
                summary['errors'].append(msg)
                continue

        if not parsed_players:
            print(f"[Boxscore] ✗ SKIPPED game {event_id}: "
                  f"0 players from Primary API + ESPN fallback — "
                  f"no rows written to DB for this game")
            continue

        # ── Step 3: Upsert parsed players into DB ─────────────────────────
        game_count = 0
        for p in parsed_players:
                espn_pid      = p["espn_pid"]
                pname         = p["player_name"]
                espn_team_id  = p["espn_team_id"]
                team_abbr_val = p["team_abbr"]
                minutes       = p["minutes"]
                points        = p["points"]
                rebounds      = p["rebounds"]
                assists       = p["assists"]
                steals        = p["steals"]
                blocks        = p["blocks"]
                turnovers     = p["turnovers"]
                fgm, fga      = p["fgm"], p["fga"]
                fg3m, fg3a    = p["fg3m"], p["fg3a"]
                ftm, fta      = p["ftm"], p["fta"]
                oreb, dreb    = p["oreb"], p["dreb"]
                fouls         = p["fouls"]
                plus_minus    = p["plus_minus"]

                c.execute('''
                    INSERT INTO player_game_stats
                        (espn_game_id, game_date, espn_player_id, player_name,
                         espn_team_id, team_abbr, season, minutes, points,
                         rebounds, assists, steals, blocks, turnovers,
                         fgm, fga, fg3m, fg3a, ftm, fta, oreb, dreb, fouls, plus_minus)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (espn_game_id, espn_player_id) DO UPDATE SET
                        team_abbr  = EXCLUDED.team_abbr,
                        points     = EXCLUDED.points,
                        rebounds   = EXCLUDED.rebounds,
                        assists    = EXCLUDED.assists,
                        steals     = EXCLUDED.steals,
                        blocks     = EXCLUDED.blocks,
                        turnovers  = EXCLUDED.turnovers,
                        minutes    = EXCLUDED.minutes,
                        fgm=EXCLUDED.fgm, fga=EXCLUDED.fga,
                        fg3m=EXCLUDED.fg3m, fg3a=EXCLUDED.fg3a,
                        ftm=EXCLUDED.ftm, fta=EXCLUDED.fta,
                        oreb=EXCLUDED.oreb, dreb=EXCLUDED.dreb,
                        fouls=EXCLUDED.fouls,
                        plus_minus=EXCLUDED.plus_minus
                ''', (event_id, date_iso, espn_pid, pname, espn_team_id,
                      team_abbr_val, season, minutes, points, rebounds, assists,
                      steals, blocks, turnovers, fgm, fga, fg3m, fg3a,
                      ftm, fta, oreb, dreb, fouls, plus_minus))
                game_count += 1
                summary['players_upserted'] += 1

                # ── Step 4: Ensure player exists in player_stats ──────────
                # Needed so the MVP autocomplete can find every player seen in
                # a boxscore, even players not in LeagueLeaders top-150.
                try:
                    espn_pid_int = int(espn_pid)

                    # 4a: try to update by name (existing NBA-API row)
                    c.execute('''
                        UPDATE player_stats
                        SET espn_player_id = %s
                        WHERE LOWER(player_name) = LOWER(%s)
                          AND (espn_player_id IS NULL
                               OR espn_player_id != %s)
                    ''', (espn_pid_int, pname, espn_pid_int))
                    name_matched = c.rowcount

                    # 4b: also try to update by existing espn_player_id (rename)
                    if name_matched == 0:
                        c.execute('''
                            UPDATE player_stats
                            SET player_name = %s, team_abbreviation = %s
                            WHERE espn_player_id = %s AND season = %s
                        ''', (pname, team_abbr_val, espn_pid_int, season))
                        name_matched = c.rowcount

                    # 4c: player not found at all — insert a minimal row so
                    #     MVP search can find them.
                    #     player_id uses ESPN-ID-based synthetic key (offset by
                    #     10_000_000 to avoid collisions with real NBA API IDs).
                    if name_matched == 0:
                        synthetic_id = 10_000_000 + espn_pid_int
                        c.execute('''
                            INSERT INTO player_stats
                                (player_id, player_name, team_abbreviation,
                                 espn_player_id, season,
                                 pts_per_game, ast_per_game, reb_per_game,
                                 stl_per_game, blk_per_game, games_played)
                            VALUES (%s, %s, %s, %s, %s,
                                    %s, %s, %s, %s, %s, 1)
                            ON CONFLICT (player_id, season) DO UPDATE SET
                                player_name       = EXCLUDED.player_name,
                                team_abbreviation = EXCLUDED.team_abbreviation,
                                espn_player_id    = EXCLUDED.espn_player_id
                        ''', (synthetic_id, pname, team_abbr_val,
                              espn_pid_int, season,
                              float(points), float(assists), float(rebounds),
                              float(steals), float(blocks)))
                        summary['espn_id_updates'] += 1
                    else:
                        summary['espn_id_updates'] += name_matched
                except Exception:
                    pass  # espn_pid non-numeric or DB error — skip silently

        print(f"[Boxscore] ✓ game {event_id}: wrote {game_count} rows to DB "
              f"(source: {'Primary API' if boxscore_source == 'primary_api' else 'ESPN direct'}, "
              f"scoreboard: {scoreboard_source})")
        summary['games_processed'] += 1

    conn.commit()
    conn.close()
    print(f"[Boxscore] ✓ {date_iso} — {summary['games_processed']} games, "
          f"{summary['players_upserted']} players, "
          f"{summary['espn_id_updates']} ESPN ID updates")
    return summary


def refresh_playin_matchups(season: str = '2026') -> dict:
    """
    Re-align the playin_games table with the current standings for a season.

    For each conference:
      - Reads conf_rank 7 & 8 → updates the '7v8' game (if still active / not started)
      - Reads conf_rank 9 & 10 → updates the '9v10' game (if still active / not started)

    A game is considered "not started" when:
      status = 'active'  AND  winner_id IS NULL

    Teams that have a result (winner_id set) are never touched, so completed
    play-in games are always preserved.

    Returns a summary dict for logging / API responses.
    """
    summary = {'updated': [], 'skipped': [], 'errors': []}
    conn = None
    try:
        conn = get_db_conn()
        c = conn.cursor()

        for conf_short, conf_full in [('East', 'Eastern'), ('West', 'Western')]:
            # Fetch seeds 7-10 for this conference from latest cached standings
            c.execute(
                """SELECT team_id, team_name, conf_rank
                   FROM cached_standings
                   WHERE season = %s AND conference = %s
                     AND conf_rank BETWEEN 7 AND 10
                   ORDER BY conf_rank""",
                (season, conf_short)
            )
            rows = c.fetchall()
            seed_map = {r[2]: {'team_id': r[0], 'team_name': r[1]} for r in rows}

            if len(seed_map) < 4:
                msg = f"{conf_full}: only {len(seed_map)} seeds 7-10 in DB — skipping"
                print(f"[PlayinRefresh] {msg}")
                summary['errors'].append(msg)
                continue

            for game_type, s1, s2 in [('7v8', 7, 8), ('9v10', 9, 10)]:
                t1 = seed_map[s1]
                t2 = seed_map[s2]

                # Fetch the existing row for this conference + game_type
                c.execute(
                    """SELECT id, team1_id, team2_id, winner_id, status
                       FROM playin_games
                       WHERE season = %s AND conference = %s AND game_type = %s
                       LIMIT 1""",
                    (season, conf_full, game_type)
                )
                row = c.fetchone()

                if row is None:
                    # No row yet — insert it
                    c.execute(
                        """INSERT INTO playin_games
                               (season, conference, game_type,
                                team1_id, team1_seed, team2_id, team2_seed, status)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, 'active')""",
                        (season, conf_full, game_type,
                         t1['team_id'], s1, t2['team_id'], s2)
                    )
                    msg = f"{conf_full} {game_type}: inserted #{s1} {t1['team_name']} vs #{s2} {t2['team_name']}"
                    print(f"[PlayinRefresh] {msg}")
                    summary['updated'].append(msg)
                    continue

                row_id, db_t1, db_t2, winner_id, status = row

                # Skip games that have already been played
                if winner_id is not None or status != 'active':
                    msg = f"{conf_full} {game_type}: already played/completed — skipping"
                    print(f"[PlayinRefresh] {msg}")
                    summary['skipped'].append(msg)
                    continue

                # Check if anything actually changed
                new_t1, new_t2 = t1['team_id'], t2['team_id']
                if db_t1 == new_t1 and db_t2 == new_t2:
                    msg = f"{conf_full} {game_type}: unchanged ({t1['team_name']} vs {t2['team_name']})"
                    print(f"[PlayinRefresh] {msg}")
                    summary['skipped'].append(msg)
                    continue

                # Update teams
                c.execute(
                    """UPDATE playin_games
                       SET team1_id = %s, team1_seed = %s,
                           team2_id = %s, team2_seed = %s
                       WHERE id = %s""",
                    (new_t1, s1, new_t2, s2, row_id)
                )
                msg = (f"{conf_full} {game_type}: updated to "
                       f"#{s1} {t1['team_name']} vs #{s2} {t2['team_name']}")
                print(f"[PlayinRefresh] {msg}")
                summary['updated'].append(msg)

        conn.commit()
    except Exception as e:
        msg = f"refresh_playin_matchups error: {type(e).__name__}: {e}"
        print(f"[PlayinRefresh] {msg}")
        summary['errors'].append(msg)
        if conn:
            try: conn.rollback()
            except Exception: pass
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

    print(f"[PlayinRefresh] done — {len(summary['updated'])} updated, "
          f"{len(summary['skipped'])} skipped, {len(summary['errors'])} errors")
    return summary


def generate_matchups(force_conference=None):
    standings = get_standings()
    if not standings:
        print("No standings data, skipping matchup generation")
        return

    conn = get_db_conn()
    c = conn.cursor()

    for conf_short in ['East', 'West']:
        conf_full = 'Eastern' if conf_short == 'East' else 'Western'

        if force_conference and conf_full != force_conference:
            continue

        teams = sorted([t for t in standings if t['conference'] == conf_short],
                       key=lambda x: x['conf_rank'])[:10]

        if len(teams) < 6:
            print(f"Not enough {conf_full} teams ({len(teams)}), skipping")
            continue

        # Expected R1 matchups from current standings
        expected = {
            frozenset({teams[2]['team_id'], teams[5]['team_id']}),
            frozenset({teams[3]['team_id'], teams[4]['team_id']}),
        }

        c.execute('''SELECT home_team_id, away_team_id FROM series
                     WHERE season = %s AND conference = %s AND round = 'First Round' ''',
                  ('2026', conf_full))
        existing_r1 = {frozenset({r[0], r[1]}) for r in c.fetchall()}

        c.execute('SELECT COUNT(*) FROM playin_games WHERE season = %s AND conference = %s', ('2026', conf_full))
        playin_count = c.fetchone()[0]

        need_series = (existing_r1 != expected)
        need_playin = (playin_count < 2)

        # Safety: don't auto-regenerate if any First Round series is no longer active
        if need_series and not force_conference:
            c.execute('''SELECT COUNT(*) FROM series WHERE season = %s AND conference = %s
                         AND round = 'First Round' AND status != 'active' ''', ('2026', conf_full))
            if c.fetchone()[0] > 0:
                print(f"  -> {conf_full} has locked/completed R1 series — skipping auto-regeneration")
                need_series = False

        if not need_series and not need_playin and not force_conference:
            print(f"  -> {conf_full} already matches current standings, skipping")
            continue

        if need_series or force_conference:
            c.execute('DELETE FROM series WHERE season = %s AND conference = %s', ('2026', conf_full))
            matchups = [(teams[2], teams[5]), (teams[3], teams[4])]
            bracket_groups = ['B', 'A']  # 3v6 → Group B, 4v5 → Group A
            for (home, away), bg in zip(matchups, bracket_groups):
                c.execute('''INSERT INTO series (season, round, conference, home_team_id, away_team_id,
                            home_seed, away_seed, status, bracket_group) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                         ('2026', 'First Round', conf_full, home['team_id'], away['team_id'],
                          home['conf_rank'], away['conf_rank'], 'active', bg))
                print(f"  -> #{home['conf_rank']} {home['team_name']} vs #{away['conf_rank']} {away['team_name']}")
            print(f"  Created {conf_full} R1 series (3v6, 4v5)")

        if len(teams) >= 10 and (need_playin or force_conference):
            c.execute('DELETE FROM playin_games WHERE season = %s AND conference = %s', ('2026', conf_full))
            for game_type, idx1, idx2 in [('7v8', 6, 7), ('9v10', 8, 9)]:
                c.execute('''INSERT INTO playin_games (season, conference, game_type, team1_id, team1_seed,
                            team2_id, team2_seed, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
                         ('2026', conf_full, game_type,
                          teams[idx1]['team_id'], teams[idx1]['conf_rank'],
                          teams[idx2]['team_id'], teams[idx2]['conf_rank'], 'active'))
                print(f"  -> Play-In {game_type}: #{teams[idx1]['conf_rank']} {teams[idx1]['team_name']} vs #{teams[idx2]['conf_rank']} {teams[idx2]['team_name']}")
            print(f"  Created {conf_full} play-in games")

    conn.commit()
    conn.close()
    print("generate_matchups complete")

_ADMIN_EMAILS = {"agamital@gmail.com"}

def ensure_admin_users():
    """Promote known admin emails to role='admin' on every startup."""
    conn = get_db_conn()
    c = conn.cursor()
    for email in _ADMIN_EMAILS:
        c.execute("UPDATE users SET role='admin' WHERE email=%s AND role != 'admin'", (email,))
        if c.rowcount:
            print(f"Promoted {email} to admin")
    conn.commit()
    conn.close()

def _apply_odds_migration():
    """
    Ensure odds_championship / odds_conference exist on the teams table.
    Uses ADD COLUMN IF NOT EXISTS (idempotent) so no information_schema
    check is needed — works reliably on Supabase and PgBouncer poolers.
    Each column gets its own autocommit statement and its own try/except
    so one failure never blocks the other.
    """
    try:
        conn = get_db_conn()
        conn.autocommit = True
        c = conn.cursor()
        c.execute("SET search_path TO public")
        for col in ("odds_championship", "odds_conference"):
            try:
                c.execute(
                    f"ALTER TABLE teams ADD COLUMN IF NOT EXISTS {col} FLOAT DEFAULT 1.0"
                )
                print(f"Migration: ensured teams.{col} exists")
            except Exception as col_err:
                print(f"Migration: could not add teams.{col}: {col_err}")
        conn.close()
    except Exception as e:
        print(f"Odds migration connection error (non-fatal): {e}")


def _clean_allstar_data_from_db():
    """
    Remove any All-Star or suspicious rows from cached_standings.
    Runs once at startup to fix previously-corrupted data.
    """
    try:
        conn = get_db_conn()
        c = conn.cursor()
        like_clauses = " OR ".join(
            [f"LOWER(team_name) LIKE '%{kw}%'" for kw in _ALLSTAR_KEYWORDS]
        )
        c.execute(f"""
            DELETE FROM cached_standings
            WHERE {like_clauses}
               OR conference NOT IN ('East', 'West')
               OR team_name IS NULL
               OR team_name = ''
        """)
        deleted = c.rowcount
        conn.commit()
        conn.close()
        if deleted:
            print(f"[Startup] Removed {deleted} All-Star/null rows from cached_standings")
    except Exception as e:
        print(f"[Startup] cleanup cached_standings (non-fatal): {e}")


def _apply_series_migration():
    """Ensure manual_override column exists on the series table (idempotent)."""
    try:
        conn = get_db_conn()
        conn.autocommit = True
        c = conn.cursor()
        c.execute("SET search_path TO public")
        try:
            c.execute("ALTER TABLE series ADD COLUMN IF NOT EXISTS manual_override BOOLEAN DEFAULT FALSE")
            print("Migration: ensured series.manual_override exists")
        except Exception as col_err:
            print(f"Migration: could not add series.manual_override: {col_err}")
        conn.close()
    except Exception as e:
        print(f"Series migration connection error (non-fatal): {e}")


@app.on_event("startup")
async def startup():
    # Load hardcoded standings instantly — app responds to users immediately,
    # no waiting for NBA API or DB on a cold start.
    now = datetime.now()
    _standings_cache["data"]       = _HARDCODED_STANDINGS
    _standings_cache["fetched_at"] = now
    _standings_cache["expires"]    = now + timedelta(hours=1)
    print(f"Loaded {len(_HARDCODED_STANDINGS)} hardcoded standings into cache")

    _sync_status["source"] = "hardcoded"   # will be upgraded once DB/API data loads

    try:
        init_db()
        print("DB initialised")
    except Exception as e:
        print(f"ERROR init_db: {e}")

    # Apply odds columns separately with autocommit — must run even if init_db
    # had a partial failure, so these columns always exist before any request.
    _apply_odds_migration()

    try:
        ensure_admin_users()
    except Exception as e:
        print(f"ERROR ensure_admin_users: {e}")

    # Promote DB standings over hardcoded if available
    try:
        db_standings = _load_standings_from_db()
        if db_standings:
            now = datetime.now()
            _standings_cache["data"]       = db_standings
            _standings_cache["fetched_at"] = now
            _standings_cache["expires"]    = now + timedelta(hours=1)
            _sync_status["source"]         = "database"
            print(f"Upgraded to {len(db_standings)} DB standings")
    except Exception as e:
        print(f"ERROR loading DB standings: {e}")

    # Apply standings schema migration (games_back, status, unique constraint)
    _apply_standings_migration()

    # Remove any All-Star or null rows that may have been saved previously
    _clean_allstar_data_from_db()

    # Apply player stats schema migration (create player_stats table)
    _apply_player_stats_migration()

    # Apply series schema migration (manual_override column)
    _apply_series_migration()

    # Run heavyweight / network-dependent tasks in background threads so they
    # never block the server from binding to its port.
    def _background_init():
        try:
            sync_teams()
        except Exception as e:
            print(f"ERROR sync_teams: {e}")
        try:
            generate_matchups()
        except Exception as e:
            print(f"ERROR generate_matchups: {e}")

    threading.Thread(target=_background_init, daemon=True).start()

    # APScheduler cron jobs
    global _scheduler
    _scheduler = BackgroundScheduler(timezone='UTC', daemon=True)

    # ── 1) Full data sync chain ──────────────────────────────────────────
    # Hourly job; full chain (standings + players) fires only at 06:00 & 18:00 UTC
    # (09:00 & 21:00 IST) = 2 API calls/day. Boxscore runs every hour.
    # Chain: standings → refresh_playin_matchups → playin results → playoff results
    def _auto_sync_chain():
        from game_processor import sync_playin_results_from_api, sync_playoff_results_from_api

        utc_now  = datetime.utcnow()
        utc_hour = utc_now.hour
        # Full chain (standings + player stats) runs only at 06:00 and 18:00 UTC
        # (= 09:00 and 21:00 IST) to limit RapidAPI usage to 2 calls/day.
        # All other hours: boxscore-only (lightweight).
        is_chain_run = utc_hour in (6, 18)
        mode         = "Full-Chain" if is_chain_run else "BoxOnly"

        print(f"[Auto-Sync] ── Starting scheduled sync (Mode: {mode}, "
              f"{utc_now.strftime('%Y-%m-%d %H:%M')} UTC) ──")

        # ── Boxscore sync runs on EVERY call (day + night) ──────────────
        # Fetches both yesterday and today so recently-finished and
        # still-live games are captured regardless of time of day.
        for _bx_date in (None, datetime.utcnow().strftime('%Y-%m-%d')):
            _label = "yesterday" if _bx_date is None else "today"
            try:
                bx = sync_daily_boxscores(date_str=_bx_date, season='2026')
                print(f"[Auto-Sync] Boxscore ({_label}) — "
                      f"games={bx.get('games_processed',0)} "
                      f"players={bx.get('players_upserted',0)} "
                      f"errors={len(bx.get('errors',[]))}")
            except Exception as e:
                print(f"[Auto-Sync] Boxscore ({_label}) ERROR: {type(e).__name__}: {e}")

        if not is_chain_run:
            print(f"[Auto-Sync] ── {mode} — boxscore-only run complete "
                  f"({datetime.utcnow().strftime('%H:%M')} UTC) ──")
            return

        # ── Full chain — only at 06:00 and 18:00 UTC (2x/day) ───────────

        # Step 1 — Standings + player stats
        print("[Auto-Sync] Step 1/5 — Standings sync")
        try:
            standings_ok = _standings_sync_job()
            print(f"[Auto-Sync] Step 1/5 done — standings_ok={standings_ok}")
        except Exception as e:
            print(f"[Auto-Sync] Step 1/5 ERROR: {type(e).__name__}: {e}")
            standings_ok = False

        # Step 2 — Refresh play-in matchups from latest seeds
        print("[Auto-Sync] Step 2/5 — refresh_playin_matchups")
        try:
            pim = refresh_playin_matchups('2026')
            print(f"[Auto-Sync] Step 2/5 done — "
                  f"updated={len(pim.get('updated',[]))} skipped={len(pim.get('skipped',[]))}")
        except Exception as e:
            print(f"[Auto-Sync] Step 2/5 ERROR: {type(e).__name__}: {e}")

        # Step 3 — Sync finished Play-In games from RapidAPI scoreboard
        print("[Auto-Sync] Step 3/5 — sync_playin_results_from_api")
        try:
            pi = sync_playin_results_from_api('2026')
            print(f"[Auto-Sync] Step 3/5 done — "
                  f"processed={pi.get('processed',0)} promoted={pi.get('promoted',0)} "
                  f"errors={len(pi.get('errors',[]))}")
        except Exception as e:
            print(f"[Auto-Sync] Step 3/5 ERROR: {type(e).__name__}: {e}")

        # Step 4 — Sync finished Playoff games from RapidAPI scoreboard
        print("[Auto-Sync] Step 4/5 — sync_playoff_results_from_api")
        try:
            po = sync_playoff_results_from_api('2026')
            print(f"[Auto-Sync] Step 4/5 done — "
                  f"updated={po.get('updated',0)} completed={po.get('completed',0)} "
                  f"errors={len(po.get('errors',[]))}")
        except Exception as e:
            print(f"[Auto-Sync] Step 4/5 ERROR: {type(e).__name__}: {e}")

        print(f"[Auto-Sync] ── Full chain complete ({datetime.utcnow().strftime('%H:%M')} UTC) ──")

    _scheduler.add_job(
        _auto_sync_chain,
        # Fires every hour.  The function itself only runs the full standings+player
        # chain at 06:00 and 18:00 UTC (09:00 and 21:00 IST) to conserve RapidAPI
        # quota (2 full syncs/day).  All other hours: boxscore-only.
        CronTrigger.from_crontab('0 * * * *'),
        id='auto_sync_chain',
        replace_existing=True,
        misfire_grace_time=300,
        max_instances=1,
    )

    # ── 2) Game-hours boxscore — every 15 min during 20:00–04:00 UTC ────────
    # NBA tip-offs cluster 20:00–03:00 UTC (3pm–10pm ET).
    # Fires at :00, :15, :30, :45 of hours 20–23 and 0–4 UTC.
    def _game_hours_boxscore():
        utc_hour = datetime.utcnow().hour
        # Gate: 20:00–04:59 UTC only (avoids wasted calls mid-afternoon)
        if not (utc_hour >= 20 or utc_hour < 5):
            return
        for _bx_date in (None, datetime.utcnow().strftime('%Y-%m-%d')):
            _label = "yesterday" if _bx_date is None else "today"
            try:
                bx = sync_daily_boxscores(date_str=_bx_date, season='2026')
                print(f"[GameHours-Sync] Boxscore ({_label}) — "
                      f"games={bx.get('games_processed',0)} "
                      f"players={bx.get('players_upserted',0)}")
            except Exception as e:
                print(f"[GameHours-Sync] Boxscore ({_label}) ERROR: {type(e).__name__}: {e}")

    _scheduler.add_job(
        _game_hours_boxscore,
        CronTrigger.from_crontab('*/15 * * * *'),
        id='game_hours_boxscore',
        replace_existing=True,
        misfire_grace_time=120,
        max_instances=1,
    )

    # ── 3) Missing-picks morning alert — 06:00 UTC = 09:00 Jerusalem (IDT) ──
    _scheduler.add_job(
        _send_missing_picks_alert,
        CronTrigger.from_crontab('0 6 * * *'),
        id='missing_picks_morning',
        replace_existing=True,
        misfire_grace_time=1800,
        max_instances=1,
    )

    # ── 3) Missing-picks evening alert — 18:00 UTC = 21:00 Jerusalem (IDT) ──
    _scheduler.add_job(
        _send_missing_picks_alert,
        CronTrigger.from_crontab('0 18 * * *'),
        id='missing_picks_evening',
        replace_existing=True,
        misfire_grace_time=1800,
        max_instances=1,
    )

    _scheduler.start()
    print("[Scheduler] APScheduler started"
          " — auto_sync_chain: 0 * * * * (full-chain 2x/day at 06:00 & 18:00 UTC; boxscore every hour)"
          " — game_hours_boxscore: */15 * * * * (15-min boxscore during 20:00–04:59 UTC)"
          " — missing-picks: 0 6 * * * UTC (09:00 IL) + 0 18 * * * UTC (21:00 IL)"
          f" — active until {_STANDINGS_SYNC_CUTOFF.date()}")

    # Fire-and-forget initial sync so DB is populated shortly after boot
    threading.Thread(target=_initial_standings_sync, daemon=True).start()
    print("Server startup complete")


@app.on_event("shutdown")
async def shutdown_event():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        print("[Standings] APScheduler stopped")


@app.get("/")
async def root():
    return {"message": "NBA Predictor API", "version": "2.0", "nba_api": NBA_API_AVAILABLE}

@app.get("/api/standings")
async def api_standings(force_refresh: bool = False):
    sync_triggered = False
    if force_refresh:
        # Non-blocking background refresh (user-facing) — returns immediately
        threading.Thread(target=_standings_sync_job, daemon=True).start()
        sync_triggered = True

    standings = get_standings()
    eastern = sorted([t for t in standings if t['conference'] == 'East'], key=lambda x: x['conf_rank'])
    western = sorted([t for t in standings if t['conference'] == 'West'], key=lambda x: x['conf_rank'])

    # Pull last_synced_at from DB (most recent updated_at across all rows)
    last_synced_at = None
    try:
        conn = get_db_conn()
        c    = conn.cursor()
        c.execute("SELECT MAX(updated_at) FROM cached_standings WHERE season = '2026'")
        row = c.fetchone()
        conn.close()
        if row and row[0]:
            last_synced_at = row[0].isoformat()
    except Exception:
        pass

    fetched_at        = _standings_cache.get("fetched_at")
    cache_age_minutes = None
    if fetched_at:
        cache_age_minutes = round((datetime.now() - fetched_at).total_seconds() / 60, 1)

    is_static_mode = datetime.utcnow() >= _STANDINGS_SYNC_CUTOFF

    return {
        "eastern":           eastern,
        "western":           western,
        "last_updated":      fetched_at.isoformat() if fetched_at else None,
        "last_synced_at":    last_synced_at,
        "cache_age_minutes": cache_age_minutes,
        "cache_expires":     _standings_cache["expires"].isoformat() if _standings_cache.get("expires") else None,
        "sync_triggered":    sync_triggered,
        "sync_cutoff":       _STANDINGS_SYNC_CUTOFF.strftime('%Y-%m-%d'),
        "static_mode":       is_static_mode,
        "data_source":       _sync_status.get("source", "unknown"),
        "consecutive_failures": _sync_status.get("consecutive_failures", 0),
        "last_sync_error":   _sync_status.get("last_error"),
    }


@app.post("/api/admin/standings/sync")
async def admin_standings_sync():
    """
    Synchronous standings sync for the Admin Panel.
    Blocks until the NBA API fetch + DB write completes (or all retries fail).
    Returns detailed success/failure info so admins can diagnose issues.
    """
    import concurrent.futures
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        success = await loop.run_in_executor(pool, _standings_sync_job)

    last_success = _sync_status.get("last_success_at")
    last_attempt = _sync_status.get("last_attempt_at")

    # Run play-in refresh independently of standings success so the admin
    # always gets up-to-date matchup data after pressing the sync button.
    playin_refresh = refresh_playin_matchups('2026') if success else None

    return {
        "success":              success,
        "data_source":          _sync_status.get("source", "unknown"),
        "last_error":           _sync_status.get("last_error"),
        "consecutive_failures": _sync_status.get("consecutive_failures", 0),
        "last_success_at":      last_success.isoformat() if last_success else None,
        "last_attempt_at":      last_attempt.isoformat() if last_attempt else None,
        "nba_api_available":    NBA_API_AVAILABLE,
        "static_mode":          datetime.utcnow() >= _STANDINGS_SYNC_CUTOFF,
        "playin_refreshed":     playin_refresh,
    }

@app.post("/api/admin/player-stats/sync")
async def admin_player_stats_sync():
    """
    Force-sync player stats from NBA API (nba_api LeagueLeaders).
    Bypasses the regular-season cutoff so admins can always refresh.
    """
    if not NBA_API_AVAILABLE:
        return {"success": False, "error": "nba_api module not installed on server"}

    import concurrent.futures

    def _force_sync():
        try:
            from nba_api.stats.endpoints import leagueleaders
            ll = leagueleaders.LeagueLeaders(
                league_id='00',
                per_mode48='PerGame',
                scope='S',
                season='2025-26',
                season_type='Regular Season',
                stat_category='PTS',
                headers=_NBA_HEADERS,
                timeout=_NBA_TIMEOUT,
            )
            raw = ll.get_dict()
            result_set  = raw.get('resultSet') or raw.get('resultSets', [{}])[0]
            col_headers = result_set['headers']
            rows        = result_set['rowSet']

            def col(row, name, default=0):
                try:
                    return row[col_headers.index(name)]
                except (ValueError, IndexError):
                    return default

            conn      = get_db_conn()
            c         = conn.cursor()
            synced_at = datetime.utcnow()
            count     = 0
            for row in rows[:150]:
                pid  = col(row, 'PLAYER_ID')
                name = col(row, 'PLAYER', '')
                team = col(row, 'TEAM', '')
                gp   = int(col(row, 'GP') or 0)
                pts  = float(col(row, 'PTS') or 0)
                ast  = float(col(row, 'AST') or 0)
                reb  = float(col(row, 'REB') or 0)
                stl  = float(col(row, 'STL') or 0)
                blk  = float(col(row, 'BLK') or 0)
                fg3m = float(col(row, 'FG3M') or 0)
                if not pid or not name:
                    continue
                c.execute('''
                    INSERT INTO player_stats
                        (player_id, player_name, team_abbreviation, season,
                         games_played, pts_per_game, ast_per_game, reb_per_game,
                         stl_per_game, blk_per_game, fg3m_per_game, updated_at)
                    VALUES (%s, %s, %s, '2026', %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (player_id, season) DO UPDATE SET
                        player_name       = EXCLUDED.player_name,
                        team_abbreviation = EXCLUDED.team_abbreviation,
                        games_played      = EXCLUDED.games_played,
                        pts_per_game      = EXCLUDED.pts_per_game,
                        ast_per_game      = EXCLUDED.ast_per_game,
                        reb_per_game      = EXCLUDED.reb_per_game,
                        stl_per_game      = EXCLUDED.stl_per_game,
                        blk_per_game      = EXCLUDED.blk_per_game,
                        fg3m_per_game     = EXCLUDED.fg3m_per_game,
                        updated_at        = EXCLUDED.updated_at
                ''', (pid, name, team, gp, pts, ast, reb, stl, blk, fg3m, synced_at))
                count += 1
            conn.commit()
            conn.close()
            return {"success": True, "rows_synced": count, "synced_at": synced_at.isoformat()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        result = await loop.run_in_executor(pool, _force_sync)
    return result


@app.post("/api/admin/standings/push")
async def admin_push_standings(payload: dict):
    """
    Accept raw NBA API resultSets fetched by the admin's browser and save to DB.
    Bypasses the server-side IP block entirely — the browser makes the request,
    then POSTs the result here.

    Expected body: { "resultSets": [...] }  (exact NBA API shape)
    """
    result_sets = payload.get("resultSets")
    if not result_sets:
        raise HTTPException(status_code=400, detail="Missing 'resultSets' in payload")
    try:
        standings = _parse_standings_result_sets(result_sets)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    result = _persist_standings_to_db(standings)
    if not result['synced_at']:
        raise HTTPException(status_code=500, detail="DB persist failed — check server logs")

    # Update in-memory cache
    _standings_cache["data"]       = standings
    _standings_cache["fetched_at"] = result['synced_at']
    _standings_cache["expires"]    = result['synced_at'] + timedelta(hours=6)
    _sync_status["source"]               = "browser_push"
    _sync_status["last_success_at"]      = result['synced_at']
    _sync_status["last_error"]           = None
    _sync_status["consecutive_failures"] = 0

    east_no1 = next(
        (t for t in sorted(standings, key=lambda x: x['conf_rank'])
         if t['conference'] == 'East'), None
    )
    print(f"[Standings] ✓ Browser-pushed {result['rows']} teams. #1 East: {east_no1 and east_no1['team_name']}")

    playin_refresh = refresh_playin_matchups('2026')

    return {
        "success":          True,
        "rows_saved":       result['rows'],
        "east_no1":         east_no1['team_name'] if east_no1 else None,
        "synced_at":        result['synced_at'].isoformat(),
        "playin_refreshed": playin_refresh,
    }


@app.get("/api/admin/standings/test")
async def admin_test_standings():
    """
    Quick connection test — tries RapidAPI first (if key set), then stats.nba.com.
    Returns #1 East/West team so you can visually confirm correct data.
    """
    import concurrent.futures

    loop = asyncio.get_event_loop()

    # ── Try RapidAPI ────────────────────────────────────────────────────
    if _RAPIDAPI_KEY:
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                standings = await loop.run_in_executor(pool, _fetch_standings_from_rapidapi)
            east = sorted([t for t in standings if t['conference'] == 'East'], key=lambda x: x['conf_rank'])
            west = sorted([t for t in standings if t['conference'] == 'West'], key=lambda x: x['conf_rank'])
            return {
                "success":      True,
                "source":       "rapidapi",
                "east_no1":     east[0]['team_name'] if east else None,
                "west_no1":     west[0]['team_name'] if west else None,
                "east_top3":    [f"{t['team_name']} ({t['wins']}-{t['losses']})" for t in east[:3]],
                "west_top3":    [f"{t['team_name']} ({t['wins']}-{t['losses']})" for t in west[:3]],
                "total_teams":  len(standings),
            }
        except Exception as rapidapi_err:
            rapidapi_error = f"{type(rapidapi_err).__name__}: {str(rapidapi_err)[:300]}"
            print(f"[Test] RapidAPI failed: {rapidapi_error}")
    else:
        rapidapi_error = "RAPIDAPI_KEY not set in environment"

    # ── Try stats.nba.com fallback ──────────────────────────────────────
    import random, requests as _http
    def _do_nba_test():
        ua = random.choice(_USER_AGENTS)
        headers = {**_NBA_HEADERS, 'User-Agent': ua}
        http_resp = _http.get(_NBA_STANDINGS_URL, headers=headers, timeout=15, allow_redirects=True)
        http_resp.raise_for_status()
        return http_resp.json()

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            raw = await loop.run_in_executor(pool, _do_nba_test)
        standings = _parse_standings_result_sets(raw['resultSets'])
        east = sorted([t for t in standings if t['conference'] == 'East'], key=lambda x: x['conf_rank'])
        west = sorted([t for t in standings if t['conference'] == 'West'], key=lambda x: x['conf_rank'])
        return {
            "success":        True,
            "source":         "stats.nba.com",
            "rapidapi_error": rapidapi_error,
            "east_no1":       east[0]['team_name'] if east else None,
            "west_no1":       west[0]['team_name'] if west else None,
            "east_top3":      [f"{t['team_name']} ({t['wins']}-{t['losses']})" for t in east[:3]],
            "west_top3":      [f"{t['team_name']} ({t['wins']}-{t['losses']})" for t in west[:3]],
            "total_teams":    len(standings),
        }
    except Exception as nba_err:
        return {
            "success":        False,
            "rapidapi_error": rapidapi_error,
            "error":          f"{type(nba_err).__name__}: {str(nba_err)[:400]}",
            "hint":           "Set RAPIDAPI_KEY in Railway env vars to use RapidAPI (not IP-blocked). Or use 'Fetch via Browser'.",
        }


@app.get("/api/health")
async def health_check():
    try:
        conn = get_db_conn()
        conn.cursor().execute("SELECT 1")
        conn.close()
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        raise HTTPException(status_code=503, detail={"status": "error", "db": str(e)})

@app.get("/api/teams")
async def api_teams(conference: Optional[str] = None, playoff_only: bool = False):
    conn = get_db_conn()
    c = conn.cursor()
    teams = []

    # Try with odds columns (added by _apply_odds_migration on startup)
    try:
        q = '''SELECT id, name, abbreviation, city, conference, division, logo_url,
                      COALESCE(odds_championship, 1.0), COALESCE(odds_conference, 1.0)
               FROM teams'''
        if conference:
            c.execute(q + ' WHERE conference = %s', (conference,))
        else:
            c.execute(q)
        for row in c.fetchall():
            teams.append({'id': row[0], 'name': row[1], 'abbreviation': row[2],
                         'city': row[3], 'conference': row[4], 'division': row[5], 'logo_url': row[6],
                         'odds_championship': float(row[7]), 'odds_conference': float(row[8])})
    except Exception:
        # Columns not yet migrated — fall back and return default odds of 1.0
        conn.rollback()
        q = 'SELECT id, name, abbreviation, city, conference, division, logo_url FROM teams'
        if conference:
            c.execute(q + ' WHERE conference = %s', (conference,))
        else:
            c.execute(q)
        for row in c.fetchall():
            teams.append({'id': row[0], 'name': row[1], 'abbreviation': row[2],
                         'city': row[3], 'conference': row[4], 'division': row[5], 'logo_url': row[6],
                         'odds_championship': 1.0, 'odds_conference': 1.0})

    conn.close()

    if playoff_only:
        # Filter to top-10 per conference using standings (ranks 1-10 = playoff + play-in)
        standings = get_standings()
        rank_map = {t['team_id']: t['conf_rank'] for t in standings}
        eligible_ids = {t['team_id'] for t in standings if t.get('conf_rank', 99) <= 10}
        teams = [t for t in teams if t['id'] in eligible_ids]
        for t in teams:
            t['conf_rank'] = rank_map.get(t['id'], 99)
        teams.sort(key=lambda t: (t['conference'], t.get('conf_rank', 99)))

    return teams

@app.post("/api/auth/register")
async def register(user: User):
    conn = get_db_conn()
    c = conn.cursor()
    try:
        role = 'admin' if user.email in _ADMIN_EMAILS else 'user'
        c.execute('INSERT INTO users (username, email, password, role) VALUES (%s, %s, %s, %s) RETURNING id',
                  (user.username, user.email, user.password, role))
        conn.commit()
        user_id = c.fetchone()[0]
        conn.close()
        return {"user_id": user_id, "username": user.username, "email": user.email, "role": role, "points": 0}
    except Exception:
        conn.close()
        raise HTTPException(400, "User exists")

@app.get("/api/auth/me")
async def get_me(user_id: int):
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE id = %s', (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "User not found")
    return {"user_id": row[0], "username": row[1], "email": row[2], "role": row[4], "points": row[5]}

@app.post("/api/auth/reset-password")
async def reset_password(data: PasswordReset):
    if len(data.new_password) < 4:
        raise HTTPException(400, "Password must be at least 4 characters")
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('UPDATE users SET password = %s WHERE username = %s', (data.new_password, data.username))
    if c.rowcount == 0:
        conn.close()
        raise HTTPException(404, "User not found")
    conn.commit()
    conn.close()
    return {"message": "Password updated"}

# Secret-key protected bootstrap: sets role and/or password by email.
# Usage: POST /api/admin/bootstrap?secret=XXX&email=YYY&new_password=ZZZ&role=admin
@app.post("/api/admin/bootstrap")
async def bootstrap_admin(secret: str, email: str, new_password: Optional[str] = None, role: Optional[str] = None):
    expected = os.environ.get("ADMIN_SECRET", "")
    if not expected or secret != expected:
        raise HTTPException(403, "Invalid secret")
    conn = get_db_conn()
    c = conn.cursor()
    if role:
        c.execute('UPDATE users SET role = %s WHERE email = %s', (role, email))
    if new_password:
        c.execute('UPDATE users SET password = %s WHERE email = %s', (new_password, email))
    if c.rowcount == 0:
        conn.close()
        raise HTTPException(404, "User not found")
    conn.commit()
    conn.close()
    return {"message": f"User {email} updated"}

@app.post("/api/auth/login")
async def login(creds: UserLogin):
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE username = %s AND password = %s', (creds.username, creds.password))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(401, "Invalid credentials")
    role = 'admin' if row[2] in _ADMIN_EMAILS else row[4]
    if role == 'admin' and row[4] != 'admin':
        c.execute("UPDATE users SET role='admin' WHERE id=%s", (row[0],))
        conn.commit()
    conn.close()
    return {"user_id": row[0], "username": row[1], "email": row[2], "role": role, "points": row[5]}

@app.post("/api/auth/google")
async def google_auth(email: str, name: str = "", avatar_url: str = ""):
    """Find or create a user after Google OAuth (Supabase already verified the identity)."""
    if not email:
        raise HTTPException(400, "Email is required")

    # Derive a clean base username:
    # 1. Try the display name — but only if it contains at least one letter
    #    (rejects pure-numeric Google/Supabase UIDs like "7194")
    # 2. Fall back to the part of the email address before @
    _cleaned_name = re.sub(r'[^a-z0-9_]', '', (name or '').lower().replace(' ', '_'))
    if _cleaned_name and re.search(r'[a-z]', _cleaned_name):
        base_username = _cleaned_name
    else:
        base_username = re.sub(r'[^a-z0-9_]', '', email.split('@')[0].lower()) or 'user'

    conn = get_db_conn()
    c = conn.cursor()

    # Existing user?
    c.execute("SELECT id, username, email, password, role, points, avatar_url FROM users WHERE email = %s", (email,))
    row = c.fetchone()

    if row:
        role = 'admin' if email in _ADMIN_EMAILS else row[4]
        updates = []
        params = []
        if role == 'admin' and row[4] != 'admin':
            updates.append("role='admin'")
        if avatar_url and row[6] != avatar_url:
            updates.append("avatar_url=%s")
            params.append(avatar_url)
        if updates:
            params.append(row[0])
            c.execute(f"UPDATE users SET {', '.join(updates)} WHERE id=%s", params)
            conn.commit()
        conn.close()
        return {"user_id": row[0], "username": row[1], "email": row[2], "role": role,
                "points": row[5], "avatar_url": avatar_url or row[6] or ""}

    # New user — ensure username is unique by appending an incrementing suffix
    role = 'admin' if email in _ADMIN_EMAILS else 'user'
    username = base_username
    c.execute("SELECT id FROM users WHERE username = %s", (username,))
    if c.fetchone():
        suffix = 2
        while True:
            candidate = f"{base_username}{suffix}"
            c.execute("SELECT id FROM users WHERE username = %s", (candidate,))
            if not c.fetchone():
                username = candidate
                break
            suffix += 1

    c.execute(
        "INSERT INTO users (username, email, password, role, avatar_url) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (username, email, "", role, avatar_url)
    )
    conn.commit()
    user_id = c.fetchone()[0]
    conn.close()
    return {"user_id": user_id, "username": username, "email": email, "role": role, "points": 0, "avatar_url": avatar_url}


@app.get("/api/series")
async def api_series(season: str = "2026"):
    conn = get_db_conn()
    c = conn.cursor()

    # CRITICAL: Column order must match team table structure!
    c.execute('''SELECT
                 s.id, s.season, s.round, s.conference,
                 s.home_team_id, s.home_seed, s.home_wins,
                 s.away_team_id, s.away_seed, s.away_wins,
                 s.winner_team_id, s.status, s.actual_games,
                 ht.name, ht.abbreviation, ht.logo_url,
                 at.name, at.abbreviation, at.logo_url
                 FROM series s
                 JOIN teams ht ON s.home_team_id = ht.id
                 JOIN teams at ON s.away_team_id = at.id
                 WHERE s.season = %s''', (season,))

    series = []
    for row in c.fetchall():
        series.append({
            'id': row[0],
            'season': row[1],
            'round': row[2],
            'conference': row[3],
            'home_team': {
                'id': row[4],
                'seed': row[5],
                'name': row[13],
                'abbreviation': row[14],
                'logo_url': row[15]
            },
            'away_team': {
                'id': row[7],
                'seed': row[8],
                'name': row[16],
                'abbreviation': row[17],
                'logo_url': row[18]
            },
            'home_wins': row[6],
            'away_wins': row[9],
            'winner_team_id': row[10],
            'status': row[11],
            'actual_games': row[12],
        })

    conn.close()
    return series

@app.get("/api/playin-games")
async def api_playin(season: str = "2026"):
    conn = get_db_conn()
    c = conn.cursor()

    c.execute('''SELECT p.*, t1.name, t1.abbreviation, t1.logo_url,
                 t2.name, t2.abbreviation, t2.logo_url FROM playin_games p
                 JOIN teams t1 ON p.team1_id = t1.id
                 JOIN teams t2 ON p.team2_id = t2.id WHERE p.season = %s''', (season,))

    games = []
    for row in c.fetchall():
        games.append({
            'id': row[0],
            'season': row[1],
            'conference': row[2],
            'game_type': row[3],
            'team1': {
                'id': row[4],
                'seed': row[5],
                'name': row[10],
                'abbreviation': row[11],
                'logo_url': row[12]
            },
            'team2': {
                'id': row[6],
                'seed': row[7],
                'name': row[13],
                'abbreviation': row[14],
                'logo_url': row[15]
            },
            'winner_id': row[8],
            'status': row[9]
        })

    conn.close()
    return games

@app.post("/api/predictions")
async def make_pred(prediction: Prediction, user_id: int):
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('''INSERT INTO predictions
                     (user_id, series_id, predicted_winner_id, predicted_games,
                      leading_scorer, leading_rebounder, leading_assister)
                 VALUES (%s, %s, %s, %s, %s, %s, %s)
                 ON CONFLICT(user_id, series_id) DO UPDATE SET
                     predicted_winner_id = EXCLUDED.predicted_winner_id,
                     predicted_games     = EXCLUDED.predicted_games,
                     leading_scorer      = EXCLUDED.leading_scorer,
                     leading_rebounder   = EXCLUDED.leading_rebounder,
                     leading_assister    = EXCLUDED.leading_assister''',
              (user_id, prediction.series_id, prediction.predicted_winner_id, prediction.predicted_games,
               prediction.leading_scorer, prediction.leading_rebounder, prediction.leading_assister))
    conn.commit()
    conn.close()
    return {"message": "Saved"}

@app.post("/api/playin-predictions")
async def playin_pred(game_id: int, predicted_winner_id: int, user_id: int):
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('''INSERT INTO playin_predictions (user_id, game_id, predicted_winner_id)
                 VALUES (%s, %s, %s) ON CONFLICT(user_id, game_id)
                 DO UPDATE SET predicted_winner_id = %s''',
              (user_id, game_id, predicted_winner_id, predicted_winner_id))
    conn.commit()
    conn.close()
    return {"message": "Saved"}

@app.get("/api/leaderboard")
async def leaderboard(season: str = "2026"):
    conn = None
    try:
        conn = get_db_conn()
        c = conn.cursor()
        # Tiebreaker: 1) total_points  2) bullseyes_count (series winner+games exact,
        # plus leaders categories with is_correct_* = 2)
        c.execute('''
            SELECT
                u.id, u.username, u.points,
                COUNT(p.id)                                              AS total_preds,
                SUM(CASE WHEN p.is_correct = 1 THEN 1 ELSE 0 END)       AS correct_preds,
                -- Series bullseyes: winner correct AND games exact
                COALESCE((
                    SELECT COUNT(*) FROM predictions p2
                    JOIN series s ON s.id = p2.series_id
                    WHERE p2.user_id = u.id
                      AND p2.is_correct = 1
                      AND p2.predicted_games = s.actual_games
                ), 0) +
                -- Leaders bullseyes: each category with is_correct_* = 2
                COALESCE((
                    SELECT SUM(
                        CASE WHEN lp.is_correct_scorer   = 2 THEN 1 ELSE 0 END +
                        CASE WHEN lp.is_correct_assists  = 2 THEN 1 ELSE 0 END +
                        CASE WHEN lp.is_correct_rebounds = 2 THEN 1 ELSE 0 END +
                        CASE WHEN lp.is_correct_threes   = 2 THEN 1 ELSE 0 END +
                        CASE WHEN lp.is_correct_steals   = 2 THEN 1 ELSE 0 END +
                        CASE WHEN lp.is_correct_blocks   = 2 THEN 1 ELSE 0 END
                    ) FROM leaders_predictions lp WHERE lp.user_id = u.id
                ), 0)                                                    AS bullseyes_count
            FROM users u LEFT JOIN predictions p ON u.id = p.user_id
            GROUP BY u.id
            ORDER BY u.points DESC, bullseyes_count DESC
            LIMIT 100
        ''')
        board = []
        for idx, row in enumerate(c.fetchall(), 1):
            total, correct, bullseyes = row[3] or 0, row[4] or 0, row[5] or 0
            board.append({'rank': idx, 'user_id': row[0], 'username': row[1], 'points': row[2],
                         'total_predictions': total, 'correct_predictions': correct,
                         'accuracy': round((correct/total*100) if total > 0 else 0, 1),
                         'bullseyes_count': bullseyes})
        return board
    except Exception as e:
        print(f"leaderboard error: {e}")
        return []
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@app.get("/api/stats/global")
async def global_stats(season: str = "2026"):
    """Aggregate community prediction stats for the Global Stats tab."""
    _EMPTY = {'series': [], 'futures': {'top_champions': [], 'top_west_champs': [], 'top_east_champs': []}, 'total_users': 0}
    conn = None
    try:
        conn = get_db_conn()
        c = conn.cursor()

        # Per-series vote breakdown — only safe columns; no odds columns touched here.
        # home_seed / away_seed exist on series since original schema (init_db creates them).
        try:
            c.execute("""
                SELECT s.id, s.round, s.conference,
                       s.home_team_id, ht.name, ht.abbreviation, ht.logo_url,
                       COALESCE(s.home_seed, 0),
                       s.away_team_id, at.name, at.abbreviation, at.logo_url,
                       COALESCE(s.away_seed, 0),
                       s.status,
                       COALESCE(SUM(CASE WHEN p.predicted_winner_id = s.home_team_id THEN 1 ELSE 0 END), 0),
                       COALESCE(SUM(CASE WHEN p.predicted_winner_id = s.away_team_id THEN 1 ELSE 0 END), 0),
                       COUNT(p.id)
                FROM series s
                JOIN teams ht ON s.home_team_id = ht.id
                JOIN teams at ON s.away_team_id = at.id
                LEFT JOIN predictions p ON p.series_id = s.id
                WHERE s.season = %s
                GROUP BY s.id, s.round, s.conference,
                         s.home_team_id, ht.name, ht.abbreviation, ht.logo_url, s.home_seed,
                         s.away_team_id, at.name, at.abbreviation, at.logo_url, s.away_seed,
                         s.status
                ORDER BY s.conference, s.round
            """, (season,))
            series_stats = []
            for row in c.fetchall():
                home_v = int(row[14]) if row[14] else 0
                away_v = int(row[15]) if row[15] else 0
                total  = int(row[16]) if row[16] else 0
                series_stats.append({
                    'series_id':  row[0],
                    'round':      row[1],
                    'conference': row[2],
                    'home_team':  {'id': row[3], 'name': row[4],  'abbreviation': row[5],  'logo_url': row[6],  'seed': row[7]},
                    'away_team':  {'id': row[8], 'name': row[9],  'abbreviation': row[10], 'logo_url': row[11], 'seed': row[12]},
                    'status':      row[13],
                    'home_votes':  home_v,
                    'away_votes':  away_v,
                    'total_votes': total,
                    'home_pct':    round(home_v / total * 100) if total > 0 else 50,
                    'away_pct':    round(away_v / total * 100) if total > 0 else 50,
                })
        except Exception as e:
            print(f"global_stats series query error: {e}")
            conn.rollback()
            series_stats = []

        def top_futures(col):
            try:
                c.execute(f"""
                    SELECT fp.{col}, t.name, t.abbreviation, t.logo_url, COUNT(*) AS cnt
                    FROM futures_predictions fp
                    JOIN teams t ON fp.{col} = t.id
                    WHERE fp.season = %s AND fp.{col} IS NOT NULL
                    GROUP BY fp.{col}, t.name, t.abbreviation, t.logo_url
                    ORDER BY cnt DESC LIMIT 3
                """, (season,))
                return [{'team': {'id': r[0], 'name': r[1], 'abbreviation': r[2], 'logo_url': r[3]}, 'count': r[4]}
                        for r in c.fetchall()]
            except Exception as e:
                print(f"global_stats top_futures({col}) error: {e}")
                conn.rollback()
                return []

        try:
            c.execute("""SELECT COUNT(DISTINCT p.user_id) FROM predictions p
                         JOIN series s ON p.series_id = s.id WHERE s.season = %s""", (season,))
            total_users = c.fetchone()[0] or 0
        except Exception as e:
            print(f"global_stats total_users error: {e}")
            conn.rollback()
            total_users = 0

        return {
            'series':      series_stats,
            'futures':     {
                'top_champions':   top_futures('champion_team_id'),
                'top_west_champs': top_futures('west_champ_team_id'),
                'top_east_champs': top_futures('east_champ_team_id'),
            },
            'total_users': total_users,
        }
    except Exception as e:
        print(f"global_stats fatal error: {e}")
        return _EMPTY
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@app.get("/api/series/{series_id}/picks")
async def series_picks(series_id: int):
    """All predictions for a single series — vote counts + per-user picks."""
    conn = get_db_conn()
    c = conn.cursor()

    c.execute("""SELECT s.home_team_id, s.away_team_id,
                        ht.abbreviation, ht.logo_url,
                        at.abbreviation, at.logo_url
                 FROM series s
                 JOIN teams ht ON s.home_team_id = ht.id
                 JOIN teams at ON s.away_team_id = at.id
                 WHERE s.id = %s""", (series_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Series not found")
    home_id, away_id = row[0], row[1]

    c.execute("""SELECT u.username, p.predicted_winner_id, p.predicted_games,
                        t.abbreviation, t.logo_url
                 FROM predictions p
                 JOIN users u ON p.user_id = u.id
                 JOIN teams t ON p.predicted_winner_id = t.id
                 WHERE p.series_id = %s
                 ORDER BY u.username""", (series_id,))

    picks = []
    home_votes = away_votes = 0
    for r in c.fetchall():
        picks.append({'username': r[0], 'team_id': r[1], 'predicted_games': r[2],
                      'team_abbreviation': r[3], 'team_logo_url': r[4]})
        if r[1] == home_id:   home_votes += 1
        elif r[1] == away_id: away_votes += 1

    total = len(picks)
    conn.close()
    return {
        'series_id':  series_id,
        'picks':      picks,
        'home_votes': home_votes,
        'away_votes': away_votes,
        'total_votes': total,
        'home_pct':   round(home_votes / total * 100) if total else 50,
        'away_pct':   round(away_votes / total * 100) if total else 50,
    }

@app.get("/api/playin/{game_id}/picks")
async def playin_picks(game_id: int):
    """All predictions for a single play-in game — vote counts + per-user picks."""
    conn = get_db_conn()
    c = conn.cursor()

    c.execute("SELECT team1_id, team2_id FROM playin_games WHERE id = %s", (game_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Game not found")
    team1_id, team2_id = row

    c.execute("""SELECT u.username, pp.predicted_winner_id, t.abbreviation, t.logo_url
                 FROM playin_predictions pp
                 JOIN users u ON pp.user_id = u.id
                 JOIN teams t ON pp.predicted_winner_id = t.id
                 WHERE pp.game_id = %s
                 ORDER BY u.username""", (game_id,))

    picks = []
    t1_votes = t2_votes = 0
    for r in c.fetchall():
        picks.append({'username': r[0], 'team_id': r[1],
                      'team_abbreviation': r[2], 'team_logo_url': r[3]})
        if r[1] == team1_id:   t1_votes += 1
        elif r[1] == team2_id: t2_votes += 1

    total = len(picks)
    conn.close()
    return {
        'game_id':    game_id,
        'picks':      picks,
        'team1_votes': t1_votes,
        'team2_votes': t2_votes,
        'total_votes': total,
        'team1_pct':  round(t1_votes / total * 100) if total else 50,
        'team2_pct':  round(t2_votes / total * 100) if total else 50,
    }

@app.get("/api/dashboard")
async def dashboard(user_id: int, season: str = "2026"):
    """Lightweight dashboard counts — avoids fetching full prediction/series data."""
    conn = get_db_conn()
    c = conn.cursor()
    c.execute(
        '''SELECT
             (SELECT COUNT(*) FROM predictions p
              JOIN series s ON p.series_id = s.id
              WHERE p.user_id = %s AND s.season = %s) AS series_predicted,
             (SELECT COUNT(*) FROM series WHERE season = %s) AS total_series,
             (SELECT COUNT(*) FROM futures_predictions WHERE user_id = %s AND season = %s) AS futures_done,
             (SELECT COUNT(*) FROM leaders_predictions WHERE user_id = %s AND season = %s) AS leaders_done''',
        (user_id, season, season, user_id, season, user_id, season)
    )
    row = c.fetchone()
    conn.close()
    return {
        'series_predicted': row[0] or 0,
        'total_series':     row[1] or 0,
        'futures_done':     (row[2] or 0) > 0,
        'leaders_done':     (row[3] or 0) > 0,
    }

@app.get("/api/notifications/summary")
async def notifications_summary(user_id: int, season: str = "2026"):
    """
    Single-call summary of everything a user still needs to predict.
    Used by the frontend notification bell to build the badge count and popover list.
    Returns missing series, missing futures categories, and missing leaders categories.
    """
    conn = None
    try:
        conn = get_db_conn()
        c    = conn.cursor()

        # ── 1. Active series with no prediction ─────────────────────────────
        c.execute("""
            SELECT s.id, s.round, s.conference,
                   ht.abbreviation, at.abbreviation
            FROM series s
            JOIN teams ht ON s.home_team_id = ht.id
            JOIN teams at ON s.away_team_id = at.id
            WHERE s.season = %s AND s.status = 'active'
            AND NOT EXISTS (
                SELECT 1 FROM predictions p
                WHERE p.user_id = %s AND p.series_id = s.id
            )
            ORDER BY s.conference, s.round
        """, (season, user_id))

        _ROUND_LABELS = {
            'first_round': 'R1', 'second_round': 'R2',
            'conf_finals': 'CF', 'finals': 'Finals',
        }
        missing_series = []
        for row in c.fetchall():
            sid, rnd, conf, h_abbr, a_abbr = row
            conf_prefix = 'EC' if conf and conf.lower().startswith('e') else 'WC'
            round_short  = _ROUND_LABELS.get((rnd or '').lower().replace(' ', '_'), rnd or '')
            missing_series.append({
                'id':       sid,
                'label':    f"{h_abbr} vs {a_abbr}",
                'sublabel': f"{conf_prefix} · {round_short}",
            })

        # ── 2. Missing futures categories ───────────────────────────────────
        _FUTURES_CATS = [
            ('champion_team_id',  '🏆 NBA Champion'),
            ('west_champ_team_id','🌎 West Champion'),
            ('east_champ_team_id','🌏 East Champion'),
            ('finals_mvp',        '⭐ Finals MVP'),
            ('west_finals_mvp',   '⭐ West Finals MVP'),
            ('east_finals_mvp',   '⭐ East Finals MVP'),
        ]
        c.execute("""
            SELECT champion_team_id, west_champ_team_id, east_champ_team_id,
                   finals_mvp, west_finals_mvp, east_finals_mvp, locked
            FROM futures_predictions WHERE user_id = %s AND season = %s
        """, (user_id, season))
        fut = c.fetchone()
        futures_locked = bool(fut[6]) if fut else False

        missing_futures = []
        if not futures_locked:
            vals = list(fut[:6]) if fut else [None] * 6
            for i, (key, label) in enumerate(_FUTURES_CATS):
                if not vals[i]:
                    missing_futures.append({'key': key, 'label': label})

        # Check global lock
        if _get_futures_lock():
            missing_futures = []
            futures_locked  = True

        # ── 3. Missing leaders categories ───────────────────────────────────
        _LEADERS_CATS = [
            ('top_scorer',   '🏀 Most Points'),
            ('top_assists',  '🎯 Most Assists'),
            ('top_rebounds', '💪 Most Rebounds'),
            ('top_threes',   '3️⃣ Most 3-Pointers'),
            ('top_steals',   '🤚 Most Steals'),
            ('top_blocks',   '🛡️ Most Blocks'),
        ]
        c.execute("""
            SELECT top_scorer, top_assists, top_rebounds,
                   top_threes, top_steals, top_blocks
            FROM leaders_predictions WHERE user_id = %s AND season = %s
        """, (user_id, season))
        ldr = c.fetchone()

        missing_leaders = []
        if futures_locked:
            missing_leaders = []   # leaders lock with futures
        else:
            vals = list(ldr) if ldr else [None] * 6
            for i, (key, label) in enumerate(_LEADERS_CATS):
                if not vals[i]:
                    missing_leaders.append({'key': key, 'label': label})

        total = len(missing_series) + len(missing_futures) + len(missing_leaders)
        return {
            'missing_series':  missing_series,
            'missing_futures': missing_futures,
            'missing_leaders': missing_leaders,
            'futures_locked':  futures_locked,
            'total':           total,
        }

    except Exception as e:
        print(f"notifications_summary error: {e}")
        return {'missing_series': [], 'missing_futures': [], 'missing_leaders': [],
                'futures_locked': False, 'total': 0}
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@app.get("/api/my-predictions")
async def my_predictions(user_id: int, season: str = "2026"):
    """Get all predictions for a user"""
    conn = get_db_conn()
    c = conn.cursor()

    # Get playoff predictions
    c.execute('''
        SELECT p.id, p.user_id, p.series_id, p.predicted_winner_id,
               p.predicted_at, p.is_correct, p.points_earned, p.predicted_games,
               p.leading_scorer, p.leading_rebounder, p.leading_assister,
               s.round, s.conference,
               ht.name, ht.abbreviation, ht.logo_url,
               at.name, at.abbreviation, at.logo_url,
               wt.name, wt.abbreviation, wt.logo_url
        FROM predictions p
        JOIN series s ON p.series_id = s.id
        JOIN teams ht ON s.home_team_id = ht.id
        JOIN teams at ON s.away_team_id = at.id
        LEFT JOIN teams wt ON p.predicted_winner_id = wt.id
        WHERE p.user_id = %s AND s.season = %s
    ''', (user_id, season))

    playoff_preds = []
    for row in c.fetchall():
        playoff_preds.append({
            'id': row[0],
            'series_id': row[2],
            'predicted_games': row[7],
            'leading_scorer': row[8],
            'leading_rebounder': row[9],
            'leading_assister': row[10],
            'round': row[11],
            'conference': row[12],
            'home_team': {'name': row[13], 'abbreviation': row[14], 'logo_url': row[15]},
            'away_team': {'name': row[16], 'abbreviation': row[17], 'logo_url': row[18]},
            'predicted_winner': {'name': row[19], 'abbreviation': row[20], 'logo_url': row[21]},
            'predicted_at': row[4],
            'is_correct': row[5],
            'points_earned': row[6]
        })

    # Get play-in predictions
    c.execute('''
        SELECT pp.*, pg.game_type, pg.conference,
               t1.name, t1.abbreviation, t1.logo_url,
               t2.name, t2.abbreviation, t2.logo_url,
               wt.name, wt.abbreviation, wt.logo_url
        FROM playin_predictions pp
        JOIN playin_games pg ON pp.game_id = pg.id
        JOIN teams t1 ON pg.team1_id = t1.id
        JOIN teams t2 ON pg.team2_id = t2.id
        LEFT JOIN teams wt ON pp.predicted_winner_id = wt.id
        WHERE pp.user_id = %s AND pg.season = %s
    ''', (user_id, season))

    playin_preds = []
    for row in c.fetchall():
        playin_preds.append({
            'id': row[0],
            'game_id': row[2],
            'game_type': row[7],
            'conference': row[8],
            'team1': {'name': row[9], 'abbreviation': row[10], 'logo_url': row[11]},
            'team2': {'name': row[12], 'abbreviation': row[13], 'logo_url': row[14]},
            'predicted_winner': {'name': row[15], 'abbreviation': row[16], 'logo_url': row[17]},
            'predicted_at': row[4]
        })

    # Get futures prediction
    c.execute('''
        SELECT f.*,
               tc.name, tc.abbreviation, tc.logo_url,
               tw.name, tw.abbreviation, tw.logo_url,
               te.name, te.abbreviation, te.logo_url
        FROM futures_predictions f
        LEFT JOIN teams tc ON f.champion_team_id = tc.id
        LEFT JOIN teams tw ON f.west_champ_team_id = tw.id
        LEFT JOIN teams te ON f.east_champ_team_id = te.id
        WHERE f.user_id = %s AND f.season = %s
    ''', (user_id, season))
    frow = c.fetchone()
    futures_pred = None
    if frow:
        futures_pred = {
            'champion_team':   {'name': frow[15], 'abbreviation': frow[16], 'logo_url': frow[17]} if frow[15] else None,
            'west_champ_team': {'name': frow[18], 'abbreviation': frow[19], 'logo_url': frow[20]} if frow[18] else None,
            'east_champ_team': {'name': frow[21], 'abbreviation': frow[22], 'logo_url': frow[23]} if frow[21] else None,
            'finals_mvp':      frow[6],
            'west_finals_mvp': frow[7],
            'east_finals_mvp': frow[8],
            'locked':          bool(frow[9]),
            'predicted_at':    frow[10],
            'is_correct_champion': frow[11],
            'is_correct_west':     frow[12],
            'is_correct_east':     frow[13],
            'points_earned':       frow[14] or 0,
        }

    conn.close()

    return {
        'playoff_predictions': playoff_preds,
        'playin_predictions': playin_preds,
        'futures_prediction': futures_pred,
        'total_predictions': len(playoff_preds) + len(playin_preds)
    }

@app.post("/api/admin/regenerate-matchups")
async def admin_regenerate_matchups(conference: str = None, season: str = '2026'):
    """Force regenerate matchups for one or both conferences"""
    generate_matchups(force_conference=conference)
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM series WHERE season = %s', (season,))
    series = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM playin_games WHERE season = %s', (season,))
    playin = c.fetchone()[0]
    conn.close()
    return {"message": "Done", "series_count": series, "playin_count": playin}

@app.get("/api/admin/series")
async def admin_get_series(season: str = "2026"):
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('''SELECT s.id, s.round, s.conference, s.status, s.winner_team_id, s.actual_games,
                 ht.id, ht.name, ht.abbreviation, ht.logo_url,
                 at.id, at.name, at.abbreviation, at.logo_url,
                 wt.name, wt.abbreviation,
                 COUNT(p.id),
                 COALESCE(s.manual_override, FALSE),
                 CASE
                   WHEN s.round = 'First Round' THEN
                     EXISTS(SELECT 1 FROM series ns WHERE ns.season = s.season
                            AND ns.round = 'Conference Semifinals'
                            AND ns.conference = s.conference AND ns.bracket_group = s.bracket_group)
                   WHEN s.round = 'Conference Semifinals' THEN
                     EXISTS(SELECT 1 FROM series ns WHERE ns.season = s.season
                            AND ns.round = 'Conference Finals'
                            AND ns.conference = s.conference AND ns.bracket_group = s.bracket_group)
                   WHEN s.round = 'Conference Finals' THEN
                     EXISTS(SELECT 1 FROM series ns WHERE ns.season = s.season
                            AND ns.round = 'NBA Finals')
                   ELSE FALSE
                 END
                 FROM series s
                 JOIN teams ht ON s.home_team_id = ht.id
                 JOIN teams at ON s.away_team_id = at.id
                 LEFT JOIN teams wt ON s.winner_team_id = wt.id
                 LEFT JOIN predictions p ON s.id = p.series_id
                 WHERE s.season = %s GROUP BY s.id, ht.id, ht.name, ht.abbreviation, ht.logo_url,
                 at.id, at.name, at.abbreviation, at.logo_url, wt.name, wt.abbreviation''', (season,))
    result = []
    for row in c.fetchall():
        result.append({
            'id': row[0], 'round': row[1], 'conference': row[2],
            'status': row[3], 'winner_team_id': row[4], 'actual_games': row[5],
            'home_team': {'id': row[6], 'name': row[7], 'abbreviation': row[8], 'logo_url': row[9]},
            'away_team': {'id': row[10], 'name': row[11], 'abbreviation': row[12], 'logo_url': row[13]},
            'winner_name': row[14], 'winner_abbreviation': row[15],
            'prediction_count': row[16],
            'manual_override': row[17],
            'is_advanced': row[18],
        })
    conn.close()
    return result

def _recalculate_all_points(c):
    """Recalculate all user points from all prediction sources."""
    c.execute('''UPDATE users SET points = COALESCE((
        SELECT SUM(p.points_earned) FROM predictions p WHERE p.user_id = users.id
    ), 0) + COALESCE((
        SELECT SUM(pp.points_earned) FROM playin_predictions pp WHERE pp.user_id = users.id
    ), 0) + COALESCE((
        SELECT SUM(fp.points_earned) FROM futures_predictions fp WHERE fp.user_id = users.id
    ), 0) + COALESCE((
        SELECT SUM(lp.points_earned) FROM leaders_predictions lp WHERE lp.user_id = users.id
    ), 0)''')


def _try_advance_bracket(c, completed_series_id, season, round_name, conf, bracket_group, winner_team_id):
    """After a series completes, auto-create the next-round matchup if both bracket partners are done."""
    round_progression = {
        'First Round': 'Conference Semifinals',
        'Conference Semifinals': 'Conference Finals',
        'Conference Finals': 'NBA Finals',
    }
    next_round = round_progression.get(round_name)
    if not next_round:
        return

    if next_round == 'NBA Finals':
        c.execute('''SELECT winner_team_id FROM series
                     WHERE season = %s AND round = 'Conference Finals' AND status = 'completed'
                     ORDER BY conference''', (season,))
        cf_winners = c.fetchall()
        if len(cf_winners) == 2:
            c.execute("SELECT id FROM series WHERE season = %s AND round = 'NBA Finals'", (season,))
            if not c.fetchone():
                t1, t2 = cf_winners[0][0], cf_winners[1][0]
                c.execute('''INSERT INTO series (season, round, conference, home_team_id, away_team_id,
                             status, bracket_group)
                             VALUES (%s, 'NBA Finals', 'Finals', %s, %s, 'active', 'A')''',
                          (season, t1, t2))
        return

    # Find the partner series in the same bracket_group
    c.execute('''SELECT id, winner_team_id FROM series
                 WHERE season = %s AND round = %s AND conference = %s
                 AND bracket_group = %s AND status = 'completed' AND id != %s''',
              (season, round_name, conf, bracket_group, completed_series_id))
    partner = c.fetchone()

    if partner:
        partner_winner_id = partner[1]
        c.execute('''SELECT id FROM series WHERE season = %s AND round = %s
                     AND conference = %s AND bracket_group = %s''',
                  (season, next_round, conf, bracket_group))
        if not c.fetchone():
            c.execute('''INSERT INTO series (season, round, conference, home_team_id, away_team_id,
                         status, bracket_group)
                         VALUES (%s, %s, %s, %s, %s, 'active', %s)''',
                      (season, next_round, conf, winner_team_id, partner_winner_id, bracket_group))


@app.post("/api/admin/series/{series_id}/result")
async def set_series_result(
    series_id: int,
    winner_team_id: int,
    actual_games: int,
    manual_override: bool = False,
    actual_leading_scorer: str | None = None,
    actual_leading_rebounder: str | None = None,
    actual_leading_assister: str | None = None,
):
    conn = get_db_conn()
    c = conn.cursor()

    c.execute('''SELECT round, conference, season, bracket_group,
                 home_team_id, away_team_id, home_seed, away_seed, status
                 FROM series WHERE id = %s''', (series_id,))
    series_row = c.fetchone()
    if not series_row:
        conn.close()
        raise HTTPException(404, "Series not found")
    round_name, conf, season, bracket_group = series_row[:4]
    home_team_id, away_team_id = series_row[4], series_row[5]
    home_seed, away_seed = series_row[6], series_row[7]
    current_status = series_row[8]

    # If already completed, zero out old prediction scores before re-scoring
    if current_status == 'completed':
        c.execute('UPDATE predictions SET is_correct = 0, points_earned = 0 WHERE series_id = %s', (series_id,))

    # Mark series completed with manual_override flag and actual leaders
    c.execute('''UPDATE series SET winner_team_id = %s, actual_games = %s, status = %s,
                 manual_override = %s,
                 actual_leading_scorer = %s,
                 actual_leading_rebounder = %s,
                 actual_leading_assister = %s
                 WHERE id = %s''',
              (winner_team_id, actual_games, 'completed', manual_override,
               actual_leading_scorer, actual_leading_rebounder, actual_leading_assister,
               series_id))

    # Score each prediction individually so underdog multipliers apply per pick
    c.execute('''SELECT id, predicted_winner_id, predicted_games,
                        leading_scorer, leading_rebounder, leading_assister
                 FROM predictions WHERE series_id = %s''', (series_id,))
    for pred_id, pred_winner_id, pred_games, pred_scorer, pred_rebounder, pred_assister in c.fetchall():
        winner_correct = (pred_winner_id == winner_team_id)
        games_correct  = (pred_games == actual_games)
        games_diff     = abs(pred_games - actual_games) if pred_games is not None else None

        if pred_winner_id == home_team_id:
            pred_seed = home_seed
        elif pred_winner_id == away_team_id:
            pred_seed = away_seed
        else:
            pred_seed = None

        pts = calculate_series_points(
            round_name, home_seed, away_seed, pred_seed,
            winner_correct=winner_correct, games_correct=games_correct,
            games_diff=games_diff,
        )
        # Add series leader bonus
        pts += calculate_series_leader_points(
            {"scorer": pred_scorer, "rebounder": pred_rebounder, "assister": pred_assister},
            {"scorer": actual_leading_scorer, "rebounder": actual_leading_rebounder, "assister": actual_leading_assister},
        )
        is_correct = 1 if winner_correct else 0
        c.execute('UPDATE predictions SET is_correct = %s, points_earned = %s WHERE id = %s',
                  (is_correct, pts, pred_id))

    _recalculate_all_points(c)
    _try_advance_bracket(c, series_id, season, round_name, conf, bracket_group, winner_team_id)

    conn.commit()
    conn.close()
    return {"message": "Result set and scores updated", "manual_override": manual_override}


@app.delete("/api/admin/series/{series_id}/result")
async def reset_series_result(series_id: int):
    """Reset a completed series back to active — zeros out prediction scores and recalculates all points."""
    conn = get_db_conn()
    c = conn.cursor()

    c.execute("SELECT status FROM series WHERE id = %s", (series_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Series not found")

    # Zero out prediction scores for this series
    c.execute('UPDATE predictions SET is_correct = 0, points_earned = 0 WHERE series_id = %s', (series_id,))

    # Reset series to active
    c.execute('''UPDATE series SET winner_team_id = NULL, actual_games = NULL,
                 actual_leading_scorer = NULL, actual_leading_rebounder = NULL,
                 actual_leading_assister = NULL,
                 status = 'active', manual_override = FALSE WHERE id = %s''', (series_id,))

    _recalculate_all_points(c)
    conn.commit()
    conn.close()
    return {"message": "Series result reset — scores recalculated"}


@app.post("/api/admin/sync-and-advance")
async def sync_and_advance(season: str = "2026"):
    """Re-run bracket advancement for all completed series and recalculate all points."""
    conn = get_db_conn()
    c = conn.cursor()

    c.execute('''SELECT id, round, conference, bracket_group, winner_team_id
                 FROM series WHERE season = %s AND status = 'completed' ''', (season,))
    completed = c.fetchall()

    for series_id, round_name, conf, bracket_group, winner_team_id in completed:
        try:
            _try_advance_bracket(c, series_id, season, round_name, conf, bracket_group, winner_team_id)
        except Exception as e:
            print(f"sync_and_advance: failed to advance series {series_id}: {e}")

    _recalculate_all_points(c)
    conn.commit()
    conn.close()
    return {"message": f"Synced {len(completed)} completed series — points recalculated", "completed_count": len(completed)}

@app.get("/api/admin/playin")
async def admin_get_playin(season: str = "2026"):
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('''SELECT p.id, p.conference, p.game_type, p.winner_id, p.status,
                 t1.id, t1.name, t1.abbreviation, t1.logo_url,
                 t2.id, t2.name, t2.abbreviation, t2.logo_url,
                 wt.name, wt.abbreviation,
                 COUNT(pp.id)
                 FROM playin_games p
                 JOIN teams t1 ON p.team1_id = t1.id
                 JOIN teams t2 ON p.team2_id = t2.id
                 LEFT JOIN teams wt ON p.winner_id = wt.id
                 LEFT JOIN playin_predictions pp ON p.id = pp.game_id
                 WHERE p.season = %s GROUP BY p.id, t1.id, t1.name, t1.abbreviation, t1.logo_url,
                 t2.id, t2.name, t2.abbreviation, t2.logo_url, wt.name, wt.abbreviation''', (season,))
    rows = c.fetchall()

    # Compute is_advanced per game type / conference
    c.execute('''SELECT conference, bracket_group FROM series WHERE season=%s AND round='First Round' ''', (season,))
    r1_keys = {(r[0], r[1]) for r in c.fetchall()}   # (conf, bracket_group)

    c.execute('''SELECT conference FROM playin_games WHERE season=%s AND game_type='elimination' ''', (season,))
    elim_confs = {r[0] for r in c.fetchall()}

    type_labels = {
        '7v8':         'Game 1 — 7 vs 8',
        '9v10':        'Game 2 — 9 vs 10',
        'elimination': 'Game 3 — Elimination',
    }
    # What happens next for each game type (shown in admin)
    next_steps = {
        '7v8':         'Winner → #7 Seed (R1 vs #2)  ·  Loser → Game 3',
        '9v10':        'Winner → Game 3  ·  Loser eliminated',
        'elimination': 'Winner → #8 Seed (R1 vs #1)  ·  Loser eliminated',
    }

    result = []
    for row in rows:
        conf, game_type = row[1], row[2]
        if game_type == '7v8':
            is_advanced = (conf, 'B') in r1_keys
        elif game_type == '9v10':
            is_advanced = conf in elim_confs
        elif game_type == 'elimination':
            is_advanced = (conf, 'A') in r1_keys
        else:
            is_advanced = False

        result.append({
            'id': row[0], 'conference': conf, 'game_type': game_type,
            'winner_id': row[3], 'status': row[4],
            'team1': {'id': row[5], 'name': row[6], 'abbreviation': row[7], 'logo_url': row[8]},
            'team2': {'id': row[9], 'name': row[10], 'abbreviation': row[11], 'logo_url': row[12]},
            'winner_name': row[13], 'winner_abbreviation': row[14],
            'prediction_count': row[15],
            'is_advanced': is_advanced,
            'type_label': type_labels.get(game_type, game_type),
            'next_step': next_steps.get(game_type, ''),
        })
    conn.close()
    return result

def _try_create_playin_game3(c, season):
    """After BOTH 7v8 AND 9v10 complete, auto-create the elimination game per conference.
    Game 3 = loser of 7v8 vs winner of 9v10.  Idempotent — skips if already exists."""
    c.execute('SELECT DISTINCT conference FROM playin_games WHERE season = %s', (season,))
    for (conf,) in c.fetchall():
        # Need 7v8 completed
        c.execute('''SELECT winner_id, team1_id, team2_id, team1_seed, team2_seed
                     FROM playin_games
                     WHERE season=%s AND conference=%s AND game_type='7v8' AND status='completed' ''',
                  (season, conf))
        g7 = c.fetchone()
        if not g7:
            continue

        # Need 9v10 completed
        c.execute('''SELECT winner_id, team1_id, team2_id, team1_seed, team2_seed
                     FROM playin_games
                     WHERE season=%s AND conference=%s AND game_type='9v10' AND status='completed' ''',
                  (season, conf))
        g9 = c.fetchone()
        if not g9:
            continue

        # Skip if elimination game already exists
        c.execute('''SELECT id FROM playin_games
                     WHERE season=%s AND conference=%s AND game_type='elimination' ''',
                  (season, conf))
        if c.fetchone():
            continue

        # Loser of 7v8
        g7_winner, g7_t1, g7_t2, g7_t1_seed, g7_t2_seed = g7
        if g7_winner == g7_t1:
            loser_id, loser_seed = g7_t2, g7_t2_seed
        else:
            loser_id, loser_seed = g7_t1, g7_t1_seed

        # Winner of 9v10
        g9_winner, _, _, g9_t1_seed, g9_t2_seed = g9
        g9_t1 = g9[1]
        winner_9_seed = g9_t1_seed if g9_winner == g9_t1 else g9_t2_seed

        c.execute('''INSERT INTO playin_games
                     (season, conference, game_type, team1_id, team1_seed, team2_id, team2_seed, status)
                     VALUES (%s, %s, 'elimination', %s, %s, %s, %s, 'active')''',
                  (season, conf, loser_id, loser_seed, g9_winner, winner_9_seed))
        print(f'  -> Created {conf} Play-In Game 3: loser of 7v8 vs winner of 9v10')


def _try_create_r1_from_playin(c, game_id, winner_id, season):
    """After a play-in game, try to auto-create the R1 series vs the 1 or 2 seed."""
    c.execute('SELECT conference, game_type FROM playin_games WHERE id = %s', (game_id,))
    row = c.fetchone()
    if not row:
        return
    conf, game_type = row  # conf = 'Eastern' or 'Western'
    conf_short = 'East' if 'Eastern' in conf else 'West'

    standings = get_standings()
    conf_teams = sorted([t for t in standings if t['conference'] == conf_short], key=lambda x: x['conf_rank'])
    if len(conf_teams) < 2:
        return

    seed1_nba_id = conf_teams[0]['team_id']
    seed2_nba_id = conf_teams[1]['team_id']

    # Verify teams exist in our DB
    c.execute('SELECT id FROM teams WHERE id = %s', (seed1_nba_id,))
    s1 = c.fetchone()
    c.execute('SELECT id FROM teams WHERE id = %s', (seed2_nba_id,))
    s2 = c.fetchone()
    if not s1 or not s2:
        return

    seed1_id, seed2_id = s1[0], s2[0]

    if game_type == '7v8':
        # Winner is the 7-seed → plays 2-seed in R1 Group B
        c.execute('SELECT id FROM series WHERE season = %s AND conference = %s AND round = %s AND bracket_group = %s',
                  (season, conf, 'First Round', 'B'))
        if not c.fetchone():
            c.execute('''INSERT INTO series (season, round, conference, home_team_id, away_team_id,
                         home_seed, away_seed, status, bracket_group)
                         VALUES (%s, 'First Round', %s, %s, %s, 2, 7, 'active', 'B')''',
                      (season, conf, seed2_id, winner_id))
    elif game_type == 'elimination':
        # Winner is the 8-seed → plays 1-seed in R1 Group A
        c.execute('SELECT id FROM series WHERE season = %s AND conference = %s AND round = %s AND bracket_group = %s',
                  (season, conf, 'First Round', 'A'))
        if not c.fetchone():
            c.execute('''INSERT INTO series (season, round, conference, home_team_id, away_team_id,
                         home_seed, away_seed, status, bracket_group)
                         VALUES (%s, 'First Round', %s, %s, %s, 1, 8, 'active', 'A')''',
                      (season, conf, seed1_id, winner_id))


@app.post("/api/admin/playin/{game_id}/result")
async def set_playin_result(game_id: int, winner_id: int):
    conn = get_db_conn()
    c = conn.cursor()

    c.execute('SELECT team1_id, team1_seed, team2_id, team2_seed, season, status FROM playin_games WHERE id = %s', (game_id,))
    game_row = c.fetchone()
    if not game_row:
        conn.close()
        raise HTTPException(404, "Play-in game not found")

    t1_id, t1_seed, t2_id, t2_seed, season, current_status = game_row

    # If already completed, zero out old scores before re-scoring
    if current_status == 'completed':
        c.execute('UPDATE playin_predictions SET is_correct = 0, points_earned = 0 WHERE game_id = %s', (game_id,))

    winner_seed = t1_seed if winner_id == t1_id else (t2_seed if winner_id == t2_id else None)
    other_seed  = t2_seed if winner_id == t1_id else (t1_seed if winner_id == t2_id else None)
    is_underdog = bool(winner_seed and other_seed and winner_seed > other_seed)

    correct_pts = calculate_play_in_points(True, is_underdog=is_underdog)

    c.execute('UPDATE playin_games SET winner_id = %s, status = %s WHERE id = %s',
              (winner_id, 'completed', game_id))
    c.execute('''UPDATE playin_predictions SET
                 is_correct = CASE WHEN predicted_winner_id = %s THEN 1 ELSE 0 END,
                 points_earned = CASE WHEN predicted_winner_id = %s THEN %s ELSE 0 END
                 WHERE game_id = %s''',
              (winner_id, winner_id, correct_pts, game_id))

    _recalculate_all_points(c)
    # Advance bracket: 7v8 winner → R1 Group B; elimination winner → R1 Group A
    _try_create_r1_from_playin(c, game_id, winner_id, season)
    # Auto-create Game 3 once both 7v8 and 9v10 are done
    _try_create_playin_game3(c, season)

    conn.commit()
    conn.close()
    return {"message": "Play-in result set", "underdog_win": is_underdog, "points_awarded": correct_pts}


@app.delete("/api/admin/playin/{game_id}/result")
async def reset_playin_result(game_id: int):
    """Reset a completed play-in game — zeros prediction scores and recalculates all points."""
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT status FROM playin_games WHERE id = %s", (game_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Play-in game not found")

    c.execute('UPDATE playin_predictions SET is_correct = 0, points_earned = 0 WHERE game_id = %s', (game_id,))
    c.execute("UPDATE playin_games SET winner_id = NULL, status = 'active' WHERE id = %s", (game_id,))
    _recalculate_all_points(c)
    conn.commit()
    conn.close()
    return {"message": "Play-in result reset — scores recalculated"}


@app.post("/api/admin/playin/sync")
async def sync_playin(season: str = "2026"):
    """Manually trigger all play-in bracket progressions for the season (idempotent)."""
    conn = get_db_conn()
    c = conn.cursor()

    c.execute('''SELECT id, winner_id FROM playin_games
                 WHERE season = %s AND status = 'completed' ''', (season,))
    completed = c.fetchall()
    for gid, wid in completed:
        try:
            _try_create_r1_from_playin(c, gid, wid, season)
        except Exception as e:
            print(f"sync_playin: failed R1 creation for game {gid}: {e}")

    _try_create_playin_game3(c, season)
    _recalculate_all_points(c)
    conn.commit()
    conn.close()
    return {"message": f"Play-in sync complete — {len(completed)} completed games processed"}

@app.post("/api/admin/playin/sync-from-api")
async def admin_sync_playin_from_api(season: str = "2026"):
    """
    Fetch finished Play-In results from RapidAPI scoreboard and auto-promote
    winners in the bracket.  Requires RAPIDAPI_KEY env var to be set.
    """
    import concurrent.futures
    from game_processor import sync_playin_results_from_api
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        result = await loop.run_in_executor(pool, sync_playin_results_from_api, season)
    return result


@app.post("/api/admin/playoffs/sync-from-api")
async def admin_sync_playoffs_from_api(season: str = "2026"):
    """
    Fetch finished Playoff game results from RapidAPI scoreboard, update
    series win counts, score predictions, and advance the bracket when a
    team reaches 4 wins.  Requires RAPIDAPI_KEY env var to be set.
    """
    import concurrent.futures
    from game_processor import sync_playoff_results_from_api
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        result = await loop.run_in_executor(pool, sync_playoff_results_from_api, season)
    return result


@app.post("/api/admin/boxscore/sync")
async def admin_sync_boxscores(date: str | None = None, season: str = "2026"):
    """
    Fetch and store per-game player boxscores for a given date.
    date: 'YYYY-MM-DD' or 'YYYYMMDD'.  Defaults to yesterday UTC.
    """
    import concurrent.futures
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        result = await loop.run_in_executor(
            pool, sync_daily_boxscores, date, season
        )
    return result


@app.get("/api/admin/debug/game-stats")
async def debug_game_stats(date: str | None = None, season: str = "2026"):
    """
    Diagnostic: show what's in player_game_stats for a date (or recent 7 days).
    Returns row counts per date, unique game IDs, and sample players.
    """
    conn = get_db_conn()
    c    = conn.cursor()

    # Dates with data in the last 14 days
    c.execute('''
        SELECT game_date, COUNT(*) AS rows, COUNT(DISTINCT espn_game_id) AS games
        FROM player_game_stats
        WHERE season = %s
          AND game_date >= CURRENT_DATE - INTERVAL '14 days'
        GROUP BY game_date
        ORDER BY game_date DESC
    ''', (season,))
    recent = [{"date": str(r[0]), "rows": r[1], "games": r[2]} for r in c.fetchall()]

    # If a specific date requested, show game IDs and top players for that date
    detail = []
    if date:
        if len(date) == 8 and '-' not in date:
            date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
        c.execute('''
            SELECT espn_game_id, team_abbr, player_name, points
            FROM player_game_stats
            WHERE game_date = %s AND season = %s
            ORDER BY points DESC
            LIMIT 20
        ''', (date, season))
        detail = [{"game": r[0], "team": r[1], "player": r[2], "pts": r[3]}
                  for r in c.fetchall()]

    conn.close()
    return {"recent_dates": recent, "date_detail": detail, "queried_date": date}


@app.get("/api/players/top-performers")
async def get_top_performers(date: str | None = None, limit: int = 5,
                             season: str = "2026"):
    """
    Return the top N players by points from player_game_stats for a given date.
    date: 'YYYY-MM-DD'.  Defaults to yesterday UTC.
    """
    if date is None:
        date = (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        # Normalise YYYYMMDD → YYYY-MM-DD
        if len(date) == 8 and '-' not in date:
            date = f"{date[:4]}-{date[4:6]}-{date[6:]}"

    conn = get_db_conn()
    c    = conn.cursor()
    c.execute('''
        SELECT pgs.espn_player_id, pgs.player_name,
               COALESCE(NULLIF(pgs.team_abbr,''), pgs.espn_team_id) AS espn_team_id,
               pgs.points, pgs.rebounds, pgs.assists, pgs.steals, pgs.blocks,
               pgs.fgm, pgs.fga, pgs.fg3m, pgs.fg3a, pgs.ftm, pgs.fta,
               pgs.minutes, pgs.turnovers, pgs.plus_minus,
               COALESCE(NULLIF(pgs.team_abbr,''), pgs.espn_team_id) AS team_abbr,
               t.id AS nba_team_id
        FROM player_game_stats pgs
        LEFT JOIN teams t ON UPPER(t.abbreviation) = UPPER(pgs.team_abbr)
        WHERE pgs.game_date = %s
          AND pgs.season    = %s
        ORDER BY pgs.points DESC, pgs.rebounds DESC
        LIMIT %s
    ''', (date, season, limit))
    rows = c.fetchall()
    cols = [d[0] for d in c.description]

    conn.close()

    players = []
    for row in rows:
        r = dict(zip(cols, row))
        fga = r['fga'] or 0
        fgm = r['fgm'] or 0
        fg_pct = round(fgm / fga * 100, 1) if fga > 0 else 0.0
        players.append({
            'espn_player_id': r['espn_player_id'],
            'player_name':    r['player_name'],
            'team_abbr':      r['team_abbr'] or r['espn_team_id'],
            'nba_team_id':    r['nba_team_id'],
            'points':         r['points'],
            'rebounds':       r['rebounds'],
            'assists':        r['assists'],
            'steals':         r['steals'],
            'blocks':         r['blocks'],
            'minutes':        round(r['minutes'] or 0, 1),
            'fgm':            fgm,
            'fga':            fga,
            'fg_pct':         fg_pct,
            'fg3m':           r['fg3m'],
            'fg3a':           r['fg3a'],
            'plus_minus':     r['plus_minus'],
        })

    return {'date': date, 'players': players, 'count': len(players)}


@app.get("/api/players/games-with-performers")
async def get_games_with_performers(date: str | None = None, season: str = "2026"):
    """
    Returns each game for a date with the top-2 performers per team (from
    player_game_stats), merged with live scores from RapidAPI.
    """
    import requests as _http
    from collections import defaultdict

    if date is None:
        date = (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        if len(date) == 8 and '-' not in date:
            date = f"{date[:4]}-{date[4:6]}-{date[6:]}"

    # ── 1. Top performer per team + team totals from DB (one connection) ──
    conn = get_db_conn()
    c    = conn.cursor()

    # Top-1 performer per team per game
    c.execute('''
        WITH ranked AS (
            SELECT espn_game_id, team_abbr, player_name, espn_player_id,
                   points, rebounds, assists, steals, blocks, fg3m,
                   turnovers, minutes,
                   ROW_NUMBER() OVER (
                       PARTITION BY espn_game_id, team_abbr
                       ORDER BY points DESC, rebounds DESC
                   ) AS rn
            FROM player_game_stats
            WHERE game_date = %s AND season = %s
        )
        SELECT espn_game_id, team_abbr, player_name, espn_player_id,
               points, rebounds, assists, steals, blocks, fg3m,
               turnovers, minutes, rn
        FROM ranked WHERE rn <= 1
        ORDER BY espn_game_id, team_abbr, rn
    ''', (date, season))
    rows = c.fetchall()
    cols = [d[0] for d in c.description]

    # Team totals (sum of all player points per team per game)
    c.execute('''
        SELECT espn_game_id, team_abbr, SUM(points) AS team_total
        FROM player_game_stats
        WHERE game_date = %s AND season = %s
        GROUP BY espn_game_id, team_abbr
    ''', (date, season))
    totals_by_game: dict = defaultdict(dict)
    for gid, abbr, total in c.fetchall():
        totals_by_game[gid][abbr] = int(total or 0)

    conn.close()

    performers_by_game = defaultdict(list)
    for row in rows:
        r = dict(zip(cols, row))
        performers_by_game[r['espn_game_id']].append({
            'team_abbr':      r['team_abbr'],
            'player_name':    r['player_name'],
            'espn_player_id': r['espn_player_id'],
            'points':         r['points'],
            'rebounds':       r['rebounds'],
            'assists':        r['assists'],
            'steals':         r['steals'],
            'blocks':         r['blocks'],
            'fg3m':           r['fg3m'],
            'turnovers':      r['turnovers'],
            'minutes':        round(r['minutes'] or 0, 1),
        })

    # ── 2. Game scores — Primary API first, Secondary fallback ──────────
    api_games: dict = {}
    if _RAPIDAPI_KEY:
        # Try primary API
        try:
            norm_events = _fetch_scoreboard_primary(date)
            for ev in norm_events:
                api_games[ev["id"]] = ev
        except Exception as _primary_sb_err:
            print(f"[GamesWithPerformers] Primary scoreboard error: {_primary_sb_err} — trying secondary")
            # Fallback: secondary API
            try:
                date_fmt = date.replace('-', '')
                resp = _http.get(
                    _RAPIDAPI_SCOREBOARD_BY_DATE_URL,
                    headers={"x-rapidapi-key": _RAPIDAPI_KEY,
                             "x-rapidapi-host": _RAPIDAPI_HOST_SECONDARY},
                    params={"date": date_fmt},
                    timeout=10,
                )
                resp.raise_for_status()
                raw    = resp.json()
                obj    = raw.get("response", raw)
                events = (obj.get("Events") or obj.get("events") or []) \
                         if isinstance(obj, dict) else \
                         (obj if isinstance(obj, list) else [])
                for ev in events:
                    st     = ev.get("status") or {}
                    stype  = st.get("type") or {}
                    comps  = ev.get("competitions") or [{}]
                    comps0 = comps[0]
                    ctms   = comps0.get("competitors") or []
                    home_c = next((c for c in ctms if c.get("homeAway") == "home"), {})
                    away_c = next((c for c in ctms if c.get("homeAway") == "away"), {})
                    def _tm(c):
                        t = c.get("team") or {}
                        return {"id": t.get("id"), "abbr": t.get("abbreviation"),
                                "name": t.get("displayName") or t.get("name"),
                                "score": c.get("score"), "winner": bool(c.get("winner"))}
                    gid = str(ev.get("id", ""))
                    api_games[gid] = {
                        "id": gid, "completed": bool(stype.get("completed")),
                        "status": stype.get("description") or stype.get("name"),
                        "clock": st.get("displayClock"), "period": st.get("period"),
                        "home": _tm(home_c), "away": _tm(away_c),
                        "broadcast": comps0.get("broadcast") or "",
                    }
            except Exception as e:
                print(f"[GamesWithPerformers] Both scoreboards failed: {e}")

    # ── 3. Merge by game_id ─────────────────────────────────────────────
    result = []
    for gid in sorted(performers_by_game.keys()):
        info = dict(api_games.get(gid) or {"id": gid, "completed": True,
                                           "status": "Final", "clock": None,
                                           "period": 0, "broadcast": ""})

        # Derive home/away stubs from performers when API data is absent
        if not (info.get("home") or {}).get("abbr"):
            teams = list(dict.fromkeys(p['team_abbr'] for p in performers_by_game[gid]))
            info["away"] = {"abbr": teams[0] if teams else "", "score": None, "winner": False}
            info["home"] = {"abbr": teams[1] if len(teams) > 1 else "", "score": None, "winner": False}

        # Overlay boxscore-derived team totals (authoritative for completed games)
        totals = totals_by_game.get(gid, {})
        if totals:
            home_abbr = (info.get("home") or {}).get("abbr", "")
            away_abbr = (info.get("away") or {}).get("abbr", "")
            home_total = totals.get(home_abbr) or totals.get(home_abbr.upper())
            away_total = totals.get(away_abbr) or totals.get(away_abbr.upper())
            if home_total is not None:
                info["home"] = {**info.get("home", {}),
                                "score": home_total,
                                "winner": bool(home_total > (away_total or 0))}
            if away_total is not None:
                info["away"] = {**info.get("away", {}),
                                "score": away_total,
                                "winner": bool(away_total > (home_total or 0))}

        result.append({**info, "performers": performers_by_game[gid]})

    return {"date": date, "games": result, "count": len(result)}


@app.get("/api/players/game-boxscore")
async def get_game_boxscore(espn_game_id: str, season: str = "2026"):
    """Full per-player boxscore for a specific game from player_game_stats."""
    from collections import defaultdict

    conn = get_db_conn()
    c    = conn.cursor()
    c.execute('''
        SELECT team_abbr, player_name, minutes, points, rebounds, assists,
               steals, blocks, fg3m, turnovers, fgm, fga, plus_minus
        FROM player_game_stats
        WHERE espn_game_id = %s AND season = %s
        ORDER BY team_abbr, points DESC
    ''', (espn_game_id, season))
    rows = c.fetchall()
    cols = [d[0] for d in c.description]
    conn.close()

    if not rows:
        raise HTTPException(404, "No boxscore data found for this game")

    by_team: dict = defaultdict(list)
    for row in rows:
        r = dict(zip(cols, row))
        by_team[r['team_abbr']].append({
            'player_name': r['player_name'],
            'minutes':     round(r['minutes'] or 0, 1),
            'points':      r['points'],
            'rebounds':    r['rebounds'],
            'assists':     r['assists'],
            'steals':      r['steals'],
            'blocks':      r['blocks'],
            'fg3m':        r['fg3m'],
            'turnovers':   r['turnovers'],
            'fgm':         r['fgm'],
            'fga':         r['fga'],
            'plus_minus':  r['plus_minus'],
        })

    return {
        "espn_game_id": espn_game_id,
        "teams": [{"team_abbr": abbr, "players": players}
                  for abbr, players in by_team.items()],
    }


@app.get("/api/players/today-games")
async def get_today_games(date: str | None = None):
    """
    Fetch today's (or any date's) NBA scoreboard.
    Primary: api-basketball-nba Primary API (/nbascoreboard)
    Fallback: nba-api-free-data Secondary API (/nba-scoreboard-by-date)
    date: 'YYYY-MM-DD'.  Defaults to today UTC.
    """
    import requests as _http

    if date is None:
        date = datetime.utcnow().strftime('%Y-%m-%d')

    if not _RAPIDAPI_KEY:
        raise HTTPException(503, "RAPIDAPI_KEY not configured")

    # ── Source 1: Primary API (/nbascoreboard) ────────────────────────────
    source = "primary"
    games = []
    try:
        events = _fetch_scoreboard_primary(date)
        # _fetch_scoreboard_primary returns already-normalized dicts
        for ev in events:
            games.append({
                "id":        ev.get("id", ""),
                "name":      ev.get("name"),
                "date":      ev.get("date"),
                "status":    ev.get("status"),
                "completed": ev.get("completed", False),
                "clock":     ev.get("clock"),
                "period":    ev.get("period"),
                "broadcast": ev.get("broadcast", ""),
                "venue":     ev.get("venue", ""),
                "home":      ev.get("home", {}),
                "away":      ev.get("away", {}),
            })
    except Exception as primary_err:
        print(f"[today-games] Primary API failed: {primary_err}; trying secondary")
        source = "secondary"

    # ── Source 2: Secondary API (nba-api-free-data) ───────────────────────
    if not games and source == "secondary":
        date_fmt = date.replace('-', '')   # YYYYMMDD
        try:
            resp = _http.get(
                _RAPIDAPI_SCOREBOARD_BY_DATE_URL,
                headers={"x-rapidapi-key": _RAPIDAPI_KEY, "x-rapidapi-host": _RAPIDAPI_HOST},
                params={"date": date_fmt},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            resp_obj = data.get("response", data)
            if isinstance(resp_obj, dict):
                events = resp_obj.get("Events") or resp_obj.get("events") or []
            elif isinstance(resp_obj, list):
                events = resp_obj
            else:
                events = []

            for ev in events:
                status_obj  = (ev.get("status") or {})
                status_type = status_obj.get("type") or {}
                comps       = ev.get("competitions") or [{}]
                competitors = comps[0].get("competitors") or []
                home = next((c for c in competitors if c.get("homeAway") == "home"), {})
                away = next((c for c in competitors if c.get("homeAway") == "away"), {})

                def _team(c):
                    t = c.get("team") or {}
                    return {
                        "id":     t.get("id"),
                        "name":   t.get("displayName") or t.get("name"),
                        "abbr":   t.get("abbreviation"),
                        "score":  c.get("score"),
                        "winner": bool(c.get("winner")),
                    }

                games.append({
                    "id":        str(ev.get("id", "")),
                    "name":      ev.get("name") or ev.get("shortName"),
                    "date":      ev.get("date"),
                    "status":    status_type.get("description") or status_type.get("name"),
                    "completed": bool(status_type.get("completed")),
                    "clock":     status_obj.get("displayClock"),
                    "period":    status_obj.get("period"),
                    "broadcast": (comps[0].get("broadcast") or ""),
                    "venue":     ((comps[0].get("venue") or {}).get("fullName") or ""),
                    "home":      _team(home),
                    "away":      _team(away),
                })
        except Exception as sec_err:
            raise HTTPException(502, f"All scoreboard sources failed: {sec_err}")

    return {"date": date, "games": games, "count": len(games), "source": source}


def _get_futures_lock() -> bool:
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM site_settings WHERE key = 'futures_locked'")
    row = c.fetchone()
    conn.close()
    return row is not None and row[0] == '1'


@app.get("/api/futures/lock-status")
async def futures_lock_status():
    return {"locked": _get_futures_lock()}


@app.post("/api/admin/futures/lock")
async def admin_futures_lock(locked: bool):
    conn = get_db_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO site_settings (key, value) VALUES ('futures_locked', %s) "
        "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
        ('1' if locked else '0',)
    )
    conn.commit()
    conn.close()
    return {"locked": locked, "message": f"Futures {'locked' if locked else 'unlocked'}"}


@app.get("/api/futures")
async def get_futures(user_id: int, season: str = "2026"):
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('''SELECT f.*,
                 tc.name, tc.abbreviation, tc.logo_url,
                 tw.name, tw.abbreviation, tw.logo_url,
                 te.name, te.abbreviation, te.logo_url
                 FROM futures_predictions f
                 LEFT JOIN teams tc ON f.champion_team_id = tc.id
                 LEFT JOIN teams tw ON f.west_champ_team_id = tw.id
                 LEFT JOIN teams te ON f.east_champ_team_id = te.id
                 WHERE f.user_id = %s AND f.season = %s''', (user_id, season))
    row = c.fetchone()
    conn.close()
    if not row:
        return {"has_prediction": False}
    return {
        "has_prediction": True,
        "champion_team_id": row[2],
        "west_champ_team_id": row[3],
        "east_champ_team_id": row[4],
        "finals_mvp": row[5],
        "west_finals_mvp": row[6],
        "east_finals_mvp": row[7],
        "locked": bool(row[8]),
        "points_earned": row[14],
        "champion_team": {"name": row[15], "abbreviation": row[16], "logo_url": row[17]} if row[15] else None,
        "west_champ_team": {"name": row[18], "abbreviation": row[19], "logo_url": row[20]} if row[18] else None,
        "east_champ_team": {"name": row[21], "abbreviation": row[22], "logo_url": row[23]} if row[21] else None,
    }

@app.post("/api/futures")
async def save_futures(user_id: int, season: str = "2026",
                       champion_team_id: int = None, west_champ_team_id: int = None,
                       east_champ_team_id: int = None, finals_mvp: str = None,
                       west_finals_mvp: str = None, east_finals_mvp: str = None):
    conn = get_db_conn()
    c = conn.cursor()
    # Check global lock first
    if _get_futures_lock():
        conn.close()
        raise HTTPException(status_code=400, detail="Futures predictions are locked by admin")
    # Check per-user lock
    c.execute('SELECT locked FROM futures_predictions WHERE user_id = %s AND season = %s', (user_id, season))
    existing = c.fetchone()
    if existing and existing[0]:
        conn.close()
        raise HTTPException(status_code=400, detail="Predictions are locked")
    # Validate team IDs are playoff-eligible (top 10 per conference)
    standings = get_standings()
    west_ids = {t['team_id'] for t in standings if t['conference'] == 'West' and t.get('conf_rank', 99) <= 10}
    east_ids = {t['team_id'] for t in standings if t['conference'] == 'East' and t.get('conf_rank', 99) <= 10}
    all_playoff_ids = west_ids | east_ids
    if champion_team_id and champion_team_id not in all_playoff_ids:
        conn.close()
        raise HTTPException(status_code=400, detail="Selected champion is not a playoff-eligible team")
    if west_champ_team_id and west_champ_team_id not in west_ids:
        conn.close()
        raise HTTPException(status_code=400, detail="Selected West champion is not in the top 10 West teams")
    if east_champ_team_id and east_champ_team_id not in east_ids:
        conn.close()
        raise HTTPException(status_code=400, detail="Selected East champion is not in the top 10 East teams")
    c.execute('''INSERT INTO futures_predictions
                 (user_id, season, champion_team_id, west_champ_team_id, east_champ_team_id,
                  finals_mvp, west_finals_mvp, east_finals_mvp, predicted_at)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                 ON CONFLICT(user_id, season) DO UPDATE SET
                 champion_team_id = EXCLUDED.champion_team_id,
                 west_champ_team_id = EXCLUDED.west_champ_team_id,
                 east_champ_team_id = EXCLUDED.east_champ_team_id,
                 finals_mvp = EXCLUDED.finals_mvp,
                 west_finals_mvp = EXCLUDED.west_finals_mvp,
                 east_finals_mvp = EXCLUDED.east_finals_mvp,
                 predicted_at = CURRENT_TIMESTAMP''',
              (user_id, season, champion_team_id, west_champ_team_id, east_champ_team_id,
               finals_mvp, west_finals_mvp, east_finals_mvp))
    conn.commit()
    conn.close()
    return {"message": "Saved"}

@app.get("/api/futures/leaderboard")
async def futures_leaderboard(season: str = "2026"):
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('''SELECT u.username, f.points_earned,
                 f.is_correct_champion, f.is_correct_west, f.is_correct_east,
                 tc.name, tc.logo_url, tw.name, tw.logo_url, te.name, te.logo_url
                 FROM futures_predictions f
                 JOIN users u ON f.user_id = u.id
                 LEFT JOIN teams tc ON f.champion_team_id = tc.id
                 LEFT JOIN teams tw ON f.west_champ_team_id = tw.id
                 LEFT JOIN teams te ON f.east_champ_team_id = te.id
                 WHERE f.season = %s
                 ORDER BY f.points_earned DESC''', (season,))
    results = []
    for row in c.fetchall():
        results.append({
            "username": row[0],
            "points_earned": row[1] or 0,
            "correct_champion": row[2],
            "correct_west": row[3],
            "correct_east": row[4],
            "champion": {"name": row[5], "logo_url": row[6]} if row[5] else None,
            "west_champ": {"name": row[7], "logo_url": row[8]} if row[7] else None,
            "east_champ": {"name": row[9], "logo_url": row[10]} if row[9] else None,
        })
    conn.close()
    return results

@app.get("/api/futures/all")
async def futures_all(season: str = "2026"):
    """All users' futures picks with aggregate stats per category."""
    conn = get_db_conn()
    c = conn.cursor()

    c.execute('''
        SELECT u.username,
               f.finals_mvp, f.west_finals_mvp, f.east_finals_mvp,
               f.is_correct_champion, f.is_correct_west, f.is_correct_east, f.points_earned,
               tc.name, tc.abbreviation, tc.logo_url,
               tw.name, tw.abbreviation, tw.logo_url,
               te.name, te.abbreviation, te.logo_url
        FROM futures_predictions f
        JOIN users u ON f.user_id = u.id
        LEFT JOIN teams tc ON f.champion_team_id = tc.id
        LEFT JOIN teams tw ON f.west_champ_team_id = tw.id
        LEFT JOIN teams te ON f.east_champ_team_id = te.id
        WHERE f.season = %s
        ORDER BY f.predicted_at DESC
    ''', (season,))

    rows = c.fetchall()
    conn.close()

    entries = []
    champ_counts, west_counts, east_counts = {}, {}, {}
    mvp_counts, west_mvp_counts, east_mvp_counts = {}, {}, {}

    for row in rows:
        username     = row[0]
        finals_mvp   = row[1]
        west_mvp     = row[2]
        east_mvp     = row[3]
        champ  = {'name': row[8],  'abbreviation': row[9],  'logo_url': row[10]}  if row[8]  else None
        west_t = {'name': row[11], 'abbreviation': row[12], 'logo_url': row[13]}  if row[11] else None
        east_t = {'name': row[14], 'abbreviation': row[15], 'logo_url': row[16]}  if row[14] else None

        entries.append({
            'username':          username,
            'champion_team':     champ,
            'west_champ_team':   west_t,
            'east_champ_team':   east_t,
            'finals_mvp':        finals_mvp,
            'west_finals_mvp':   west_mvp,
            'east_finals_mvp':   east_mvp,
            'is_correct_champion': row[4],
            'is_correct_west':     row[5],
            'is_correct_east':     row[6],
            'points_earned':       row[7] or 0,
        })

        # Tally team picks
        if champ:
            k = champ['abbreviation']
            champ_counts[k] = champ_counts.get(k, {'team': champ, 'count': 0})
            champ_counts[k]['count'] += 1
        if west_t:
            k = west_t['abbreviation']
            west_counts[k] = west_counts.get(k, {'team': west_t, 'count': 0})
            west_counts[k]['count'] += 1
        if east_t:
            k = east_t['abbreviation']
            east_counts[k] = east_counts.get(k, {'team': east_t, 'count': 0})
            east_counts[k]['count'] += 1
        # Tally MVP picks
        for name, bucket in [(finals_mvp, mvp_counts), (west_mvp, west_mvp_counts), (east_mvp, east_mvp_counts)]:
            if name:
                bucket[name] = bucket.get(name, {'name': name, 'count': 0})
                bucket[name]['count'] += 1

    total = len(entries)

    def pct(count): return round(count / total * 100, 1) if total else 0

    def rank_teams(d):
        lst = sorted(d.values(), key=lambda x: -x['count'])
        for item in lst:
            item['pct'] = pct(item['count'])
        return lst

    def rank_players(d):
        lst = sorted(d.values(), key=lambda x: -x['count'])
        for item in lst:
            item['pct'] = pct(item['count'])
        return lst

    return {
        'total_entries': total,
        'champion':       rank_teams(champ_counts),
        'west_champ':     rank_teams(west_counts),
        'east_champ':     rank_teams(east_counts),
        'finals_mvp':     rank_players(mvp_counts),
        'west_finals_mvp': rank_players(west_mvp_counts),
        'east_finals_mvp': rank_players(east_mvp_counts),
        'entries':        entries,
    }


@app.get("/api/teams/{team_id}/roster")
async def get_team_roster(team_id: int):
    """Get team roster from nba_api with caching.
    team_id in our DB equals the NBA API team ID, so no DB lookup needed."""
    import time
    cache_key = f"roster_{team_id}"
    if not hasattr(get_team_roster, '_cache'):
        get_team_roster._cache = {}
    cached = get_team_roster._cache.get(cache_key)
    if cached and time.time() - cached['ts'] < 3600:
        return cached['data']

    if not NBA_API_AVAILABLE:
        return {"players": [], "error": "NBA API not available on this server"}

    try:
        from nba_api.stats.endpoints import commonteamroster

        # Our DB team_id IS the NBA API team_id — no DB lookup needed
        roster_df = None
        for season_try in ['2025-26', '2024-25']:
            try:
                roster_data = commonteamroster.CommonTeamRoster(team_id=team_id, season=season_try)
                roster_df = roster_data.get_data_frames()[0]
                if not roster_df.empty:
                    break
            except Exception:
                continue

        if roster_df is None or roster_df.empty:
            return {"players": [], "error": "Roster not available from NBA API"}

        players = []
        for _, p in roster_df.iterrows():
            players.append({
                "id": int(p['PLAYER_ID']),
                "name": str(p['PLAYER']),
                "number": str(p.get('NUM', '')),
                "position": str(p.get('POSITION', '')),
                "height": str(p.get('HEIGHT', '')),
                "weight": str(p.get('WEIGHT', '')),
                "age": str(p.get('AGE', '')),
                "photo_url": f"https://cdn.nba.com/headshots/nba/latest/1040x760/{int(p['PLAYER_ID'])}.png"
            })
        result = {"players": players}
        get_team_roster._cache[cache_key] = {'data': result, 'ts': time.time()}
        return result
    except Exception as e:
        print(f"Roster error for team {team_id}: {e}")
        return {"players": [], "error": "Roster temporarily unavailable"}


@app.get("/api/players/leaders")
async def player_leaders_endpoint(season: str = "2026", limit: int = 10, playoff_only: bool = True):
    """
    Current statistical leaders from the synced player_stats table.
    When playoff_only=True (default), only includes players from top-10 teams per conference.
    Includes team logo_url via JOIN with teams table.
    """
    conn = None
    try:
        conn = get_db_conn()
        c    = conn.cursor()

        # Resolve playoff-eligible team abbreviations
        playoff_abbrevs: list | None = None
        if playoff_only:
            standings = get_standings()
            playoff_ids = [t['team_id'] for t in standings if t.get('conf_rank', 99) <= 10]
            if playoff_ids:
                c.execute("SELECT abbreviation FROM teams WHERE id = ANY(%s)", (playoff_ids,))
                playoff_abbrevs = [row[0] for row in c.fetchall()]

        def top_n(order_col):
            if playoff_abbrevs:
                c.execute(f'''
                    SELECT ps.player_id, ps.player_name, ps.team_abbreviation,
                           t.logo_url,
                           ps.games_played, ps.pts_per_game, ps.ast_per_game, ps.reb_per_game,
                           ps.stl_per_game, ps.blk_per_game, ps.fg3m_per_game, ps.updated_at
                    FROM player_stats ps
                    LEFT JOIN teams t ON t.abbreviation = ps.team_abbreviation
                    WHERE ps.season = %s AND ps.team_abbreviation = ANY(%s)
                    ORDER BY ps.{order_col} DESC NULLS LAST, ps.pts_per_game DESC NULLS LAST
                    LIMIT %s
                ''', (season, playoff_abbrevs, limit))
            else:
                c.execute(f'''
                    SELECT ps.player_id, ps.player_name, ps.team_abbreviation,
                           t.logo_url,
                           ps.games_played, ps.pts_per_game, ps.ast_per_game, ps.reb_per_game,
                           ps.stl_per_game, ps.blk_per_game, ps.fg3m_per_game, ps.updated_at
                    FROM player_stats ps
                    LEFT JOIN teams t ON t.abbreviation = ps.team_abbreviation
                    WHERE ps.season = %s
                    ORDER BY ps.{order_col} DESC NULLS LAST, ps.pts_per_game DESC NULLS LAST
                    LIMIT %s
                ''', (season, limit))
            return [
                {'player_id': r[0], 'name': r[1], 'team': r[2], 'logo_url': r[3],
                 'gp': r[4], 'ppg': r[5], 'apg': r[6], 'rpg': r[7],
                 'spg': r[8], 'bpg': r[9], 'fg3m': r[10],
                 'updated_at': r[11].isoformat() if r[11] else None}
                for r in c.fetchall()
            ]

        c.execute("SELECT MAX(updated_at) FROM player_stats WHERE season = %s", (season,))
        last_row    = c.fetchone()
        last_synced = last_row[0].isoformat() if last_row and last_row[0] else None

        return {
            'top_scorers':    top_n('pts_per_game'),
            'top_assists':    top_n('ast_per_game'),
            'top_rebounds':   top_n('reb_per_game'),
            'top_steals':     top_n('stl_per_game'),
            'top_blocks':     top_n('blk_per_game'),
            'top_threes':     top_n('fg3m_per_game'),
            'last_synced_at': last_synced,
            'sync_cutoff':    _STANDINGS_SYNC_CUTOFF.strftime('%Y-%m-%d'),
        }
    except Exception as e:
        print(f"player_leaders error: {e}")
        return {'top_scorers': [], 'top_assists': [], 'top_rebounds': [],
                'top_steals': [], 'top_blocks': [], 'top_threes': [],
                'last_synced_at': None}
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@app.get("/api/players/playoff-eligible")
async def players_playoff_eligible(season: str = "2026"):
    """All players from top-10 teams per conference, sorted by PPG descending.
    Used to populate MVP autocomplete suggestions in the frontend."""
    conn = None
    try:
        conn = get_db_conn()
        c    = conn.cursor()
        standings = get_standings()
        playoff_ids = [t['team_id'] for t in standings if t.get('conf_rank', 99) <= 10]
        if not playoff_ids:
            return []
        c.execute("SELECT abbreviation FROM teams WHERE id = ANY(%s)", (playoff_ids,))
        playoff_abbrevs = [row[0] for row in c.fetchall()]
        if not playoff_abbrevs:
            return []
        c.execute('''
            SELECT ps.player_id, ps.player_name, ps.team_abbreviation,
                   t.logo_url, ps.pts_per_game
            FROM player_stats ps
            LEFT JOIN teams t ON t.abbreviation = ps.team_abbreviation
            WHERE ps.season = %s AND ps.team_abbreviation = ANY(%s)
            ORDER BY ps.pts_per_game DESC NULLS LAST
        ''', (season, playoff_abbrevs))
        return [
            {'player_id': r[0], 'name': r[1], 'team': r[2],
             'logo_url': r[3], 'ppg': r[4]}
            for r in c.fetchall()
        ]
    except Exception as e:
        print(f"players_playoff_eligible error: {e}")
        return []
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@app.get("/api/series/{series_id}/players")
async def get_series_players(series_id: int, season: str = "2026"):
    """
    Return all players from both teams in a series, sorted by PPG.
    Used to populate Leading Scorer / Rebounder / Assister dropdowns.
    """
    conn = None
    try:
        conn = get_db_conn()
        c    = conn.cursor()
        # Get home/away team abbreviations for this series
        c.execute("""
            SELECT ht.abbreviation, at.abbreviation
            FROM series s
            JOIN teams ht ON ht.id = s.home_team_id
            JOIN teams at ON at.id = s.away_team_id
            WHERE s.id = %s
        """, (series_id,))
        row = c.fetchone()
        if not row:
            return []
        abbrevs = [row[0].upper(), row[1].upper()]
        c.execute("""
            SELECT ps.player_id, ps.player_name, ps.team_abbreviation,
                   COALESCE(ps.pts_per_game, 0) AS ppg,
                   COALESCE(ps.reb_per_game, 0) AS rpg,
                   COALESCE(ps.ast_per_game, 0) AS apg,
                   t.logo_url
            FROM player_stats ps
            LEFT JOIN teams t ON UPPER(t.abbreviation) = UPPER(ps.team_abbreviation)
            WHERE ps.season = %s AND UPPER(ps.team_abbreviation) = ANY(%s)
            ORDER BY ps.pts_per_game DESC NULLS LAST
        """, (season, abbrevs))
        return [
            {'player_id': r[0], 'name': r[1], 'team': r[2],
             'ppg': round(float(r[3] or 0), 1),
             'rpg': round(float(r[4] or 0), 1),
             'apg': round(float(r[5] or 0), 1),
             'logo_url': r[6]}
            for r in c.fetchall()
        ]
    except Exception as e:
        print(f"get_series_players error: {e}")
        return []
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@app.get("/api/futures/page-data")
async def get_futures_page_data(season: str = "2026"):
    """
    Single combined endpoint for FuturesPage static data:
    playoff-eligible teams (all / west / east), MVP odds multipliers, lock status.
    Uses ONE DB connection, no get_standings() call — reads cached_standings directly.
    """
    conn = get_db_conn()
    c    = conn.cursor()

    # ── Teams: join cached_standings (top-10 per conf) with teams table ─────
    c.execute('''
        SELECT cs.team_id, cs.conference, cs.conf_rank,
               t.name, t.abbreviation, t.logo_url,
               COALESCE(t.odds_championship, 1.0) AS odds_championship,
               COALESCE(t.odds_conference,   1.0) AS odds_conference
        FROM cached_standings cs
        JOIN teams t ON t.id = cs.team_id
        WHERE cs.conf_rank <= 10
        ORDER BY cs.conference, cs.conf_rank
    ''')
    rows = c.fetchall()
    cols = [d[0] for d in c.description]
    all_teams, west_teams, east_teams = [], [], []
    for row in rows:
        r = dict(zip(cols, row))
        obj = {
            'id':              r['team_id'],
            'name':            r['name'],
            'abbreviation':    r['abbreviation'],
            'logo_url':        r['logo_url'],
            'conference':      r['conference'],
            'conf_rank':       r['conf_rank'],
            'odds_championship': float(r['odds_championship']),
            'odds_conference':   float(r['odds_conference']),
        }
        all_teams.append(obj)
        if r['conference'] in ('West', 'Western'):
            west_teams.append(obj)
        elif r['conference'] in ('East', 'Eastern'):
            east_teams.append(obj)

    # ── MVP odds multipliers from site_settings ──────────────────────────────
    c.execute(
        "SELECT key, value FROM site_settings "
        "WHERE key LIKE 'odds_%'"
    )
    odds = {row[0].replace('odds_', ''): float(row[1])
            for row in c.fetchall() if row[1]}

    # ── Lock status ───────────────────────────────────────────────────────────
    c.execute("SELECT value FROM site_settings WHERE key = 'futures_locked'")
    lock_row = c.fetchone()
    locked   = bool(lock_row and lock_row[0] == '1')

    conn.close()
    return {
        'teams':      all_teams,
        'west_teams': west_teams,
        'east_teams': east_teams,
        'odds':       odds,
        'locked':     locked,
    }


@app.get("/api/players/search")
async def search_players(q: str = "", conference: str = "All",
                         limit: int = 7, season: str = "2026"):
    """
    Debounced player search for MVP autocomplete.
    Returns players sorted by PPG (star power), optionally filtered by conference.
    Requires q >= 2 characters.
    """
    if len(q) < 2:
        return {"players": [], "total": 0}

    conn = get_db_conn()
    c    = conn.cursor()

    conf_filter = ""
    params: list = [season, f"%{q}%"]
    if conference and conference not in ("All", ""):
        conf_filter = "AND t.conference = %s"
        params.append(conference)

    c.execute(f'''
        SELECT ps.player_id, ps.player_name, ps.team_abbreviation,
               COALESCE(ps.pts_per_game, 0) AS ppg,
               t.logo_url, t.conference
        FROM player_stats ps
        LEFT JOIN teams t ON UPPER(t.abbreviation) = UPPER(ps.team_abbreviation)
        WHERE ps.season = %s
          AND ps.player_name ILIKE %s
          {conf_filter}
        ORDER BY ps.pts_per_game DESC NULLS LAST
        LIMIT %s
    ''', params + [limit])
    rows = c.fetchall()
    conn.close()

    return {
        "players": [
            {
                "player_id":  r[0],
                "name":       r[1],
                "team":       r[2],
                "ppg":        round(float(r[3]), 1),
                "logo_url":   r[4],
                "conference": r[5],
            }
            for r in rows
        ],
        "total": len(rows),
    }


@app.get("/api/players/{player_id}/stats")
async def get_player_stats(player_id: int):
    """Get player stats from nba_api with caching"""
    import time
    cache_key = f"stats_{player_id}"
    if not hasattr(get_player_stats, '_cache'):
        get_player_stats._cache = {}
    cached = get_player_stats._cache.get(cache_key)
    if cached and time.time() - cached['ts'] < 3600:
        return cached['data']

    try:
        from nba_api.stats.endpoints import playercareerstats, commonplayerinfo

        career = playercareerstats.PlayerCareerStats(player_id=player_id)
        career_df = career.get_data_frames()[0]

        info = commonplayerinfo.CommonPlayerInfo(player_id=player_id)
        info_df = info.get_data_frames()[0]

        # Get most recent season stats
        if career_df.empty:
            return {"error": "No stats found"}

        # Try to get 2024-25 season first, fallback to latest
        season_df = career_df[career_df['SEASON_ID'] == '2024-25']
        if season_df.empty:
            season_df = career_df.tail(1)
        row = season_df.iloc[-1]

        player_info = info_df.iloc[0]

        gp = int(row.get('GP', 0)) or 1
        result = {
            "name": str(player_info.get('DISPLAY_FIRST_LAST', '')),
            "position": str(player_info.get('POSITION', '')),
            "team": str(player_info.get('TEAM_ABBREVIATION', '')),
            "jersey": str(player_info.get('JERSEY', '')),
            "height": str(player_info.get('HEIGHT', '')),
            "weight": str(player_info.get('WEIGHT', '')),
            "country": str(player_info.get('COUNTRY', '')),
            "season": str(row.get('SEASON_ID', '')),
            "gp": int(row.get('GP', 0)),
            "ppg": round(float(row.get('PTS', 0)) / gp, 1),
            "rpg": round(float(row.get('REB', 0)) / gp, 1),
            "apg": round(float(row.get('AST', 0)) / gp, 1),
            "spg": round(float(row.get('STL', 0)) / gp, 1),
            "bpg": round(float(row.get('BLK', 0)) / gp, 1),
            "fg_pct": round(float(row.get('FG_PCT', 0)) * 100, 1),
            "fg3_pct": round(float(row.get('FG3_PCT', 0)) * 100, 1),
            "ft_pct": round(float(row.get('FT_PCT', 0)) * 100, 1),
            "photo_url": f"https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png"
        }
        get_player_stats._cache[cache_key] = {'data': result, 'ts': time.time()}
        return result
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/debug/standings-raw")
async def debug_standings_raw():
    """Returns raw column headers + top 6 rows directly from the NBA API via requests."""
    import random, requests as _http
    try:
        ua = random.choice(_USER_AGENTS)
        headers = {**_NBA_HEADERS, 'User-Agent': ua}
        http_resp = _http.get(_NBA_STANDINGS_URL, headers=headers, timeout=20, allow_redirects=True)
        http_resp.raise_for_status()
        raw = http_resp.json()
        result_set = raw['resultSets'][0]
        col_headers = result_set['headers']
        rows = result_set['rowSet']
        sample = [dict(zip(col_headers, row)) for row in rows[:6]]
        return {
            "fetched_at":   datetime.now().isoformat(),
            "total_rows":   len(rows),
            "headers":      col_headers,
            "sample_rows":  sample,
            "http_status":  http_resp.status_code,
            "cache_info": {
                "fetched_at": _standings_cache.get("fetched_at") and _standings_cache["fetched_at"].isoformat(),
                "expires":    _standings_cache.get("expires")    and _standings_cache["expires"].isoformat(),
            }
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)}"}


@app.get("/api/users/{username}")
async def get_user_profile(username: str):
    """Public profile: username, points, rank, avatar."""
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT id, username, points, avatar_url FROM users WHERE username = %s", (username,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "User not found")
    c.execute("SELECT COUNT(*) + 1 FROM users WHERE points > %s", (row[2],))
    rank = c.fetchone()[0]
    conn.close()
    return {"user_id": row[0], "username": row[1], "points": row[2], "avatar_url": row[3] or "", "rank": rank}


@app.get("/api/account")
async def get_account(user_id: int):
    """Private account info for the logged-in user."""
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT id, username, email, role, points, avatar_url, created_at, password FROM users WHERE id = %s", (user_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "User not found")
    c.execute("SELECT COUNT(*) + 1 FROM users WHERE points > %s", (row[4],))
    rank = c.fetchone()[0]
    conn.close()
    return {
        "user_id": row[0],
        "username": row[1],
        "email": row[2],
        "role": row[3],
        "points": row[4],
        "avatar_url": row[5] or "",
        "member_since": row[6].isoformat() if row[6] else None,
        "rank": rank,
        "login_method": "google" if not row[7] else "password",
    }


@app.patch("/api/account/username")
async def change_username(user_id: int, new_username: str):
    if len(new_username) < 3:
        raise HTTPException(400, "Username must be at least 3 characters")
    if not re.match(r'^[a-zA-Z0-9_]+$', new_username):
        raise HTTPException(400, "Username can only contain letters, numbers and underscores")
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE username = %s AND id != %s", (new_username, user_id))
    if c.fetchone():
        conn.close()
        raise HTTPException(400, "Username already taken")
    c.execute("UPDATE users SET username = %s WHERE id = %s", (new_username, user_id))
    conn.commit()
    conn.close()
    return {"message": "Username updated", "username": new_username}


@app.patch("/api/account/password")
async def change_account_password(user_id: int, current_password: str, new_password: str):
    if len(new_password) < 4:
        raise HTTPException(400, "Password must be at least 4 characters")
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT password FROM users WHERE id = %s", (user_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "User not found")
    if row[0] != current_password:
        conn.close()
        raise HTTPException(400, "Current password is incorrect")
    c.execute("UPDATE users SET password = %s WHERE id = %s", (new_password, user_id))
    conn.commit()
    conn.close()
    return {"message": "Password updated"}


@app.delete("/api/account")
async def delete_account(user_id: int):
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("DELETE FROM predictions WHERE user_id = %s", (user_id,))
    c.execute("DELETE FROM playin_predictions WHERE user_id = %s", (user_id,))
    c.execute("DELETE FROM futures_predictions WHERE user_id = %s", (user_id,))
    c.execute("DELETE FROM users WHERE id = %s", (user_id,))
    conn.commit()
    conn.close()
    return {"message": "Account deleted"}


# ── Admin: User Management ────────────────────────────────────────────────────

def _verify_admin(c, admin_user_id: int):
    """Raise 403 if admin_user_id is not an admin. Cursor must be open."""
    c.execute("SELECT role FROM users WHERE id = %s", (admin_user_id,))
    row = c.fetchone()
    if not row or row[0] != 'admin':
        raise HTTPException(403, "Admin access required")


@app.get("/api/admin/users")
async def admin_list_users(admin_user_id: int):
    """Return all users with stats. Admin only."""
    conn = get_db_conn()
    c = conn.cursor()
    try:
        _verify_admin(c, admin_user_id)
        c.execute("""
            SELECT u.id, u.username, u.email, u.role, u.points, u.created_at,
                   COUNT(DISTINCT p.id)  AS series_preds,
                   COUNT(DISTINCT pp.id) AS playin_preds
            FROM users u
            LEFT JOIN predictions p        ON p.user_id  = u.id
            LEFT JOIN playin_predictions pp ON pp.user_id = u.id
            GROUP BY u.id
            ORDER BY u.points DESC, u.username ASC
        """)
        return [
            {
                "id":               row[0],
                "username":         row[1],
                "email":            row[2],
                "role":             row[3],
                "points":           row[4] or 0,
                "created_at":       row[5].isoformat() if row[5] else None,
                "prediction_count": (row[6] or 0) + (row[7] or 0),
            }
            for row in c.fetchall()
        ]
    finally:
        conn.close()


@app.patch("/api/admin/users/{user_id}")
async def admin_update_user(
    user_id: int,
    admin_user_id: int,
    username: Optional[str] = None,
    points: Optional[int]   = None,
):
    """Edit a user's username and/or points. Admin only."""
    conn = get_db_conn()
    c = conn.cursor()
    try:
        _verify_admin(c, admin_user_id)
        updates, values = [], []
        if username is not None:
            updates.append("username = %s")
            values.append(username.strip())
        if points is not None:
            updates.append("points = %s")
            values.append(points)
        if not updates:
            raise HTTPException(400, "Nothing to update")
        values.append(user_id)
        c.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = %s RETURNING id", values)
        if not c.fetchone():
            raise HTTPException(404, "User not found")
        conn.commit()
        return {"message": "User updated"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        conn.close()


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: int, admin_user_id: int):
    """Delete a user and ALL their predictions. Admin only. Cannot self-delete."""
    if user_id == admin_user_id:
        raise HTTPException(400, "Cannot delete your own account via the admin panel")
    conn = get_db_conn()
    c = conn.cursor()
    try:
        _verify_admin(c, admin_user_id)
        c.execute("SELECT username FROM users WHERE id = %s", (user_id,))
        row = c.fetchone()
        if not row:
            raise HTTPException(404, "User not found")
        username = row[0]
        # Cascade — remove all prediction data before removing the user row
        for tbl in ("predictions", "playin_predictions", "futures_predictions", "leaders_predictions"):
            c.execute(f"DELETE FROM {tbl} WHERE user_id = %s", (user_id,))
        c.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        return {"message": f"User '{username}' and all their data deleted"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        conn.close()


# ── Series lock/unlock ────────────────────────────────────────────────────────

@app.post("/api/admin/series/{series_id}/lock")
async def lock_series_predictions(series_id: int, locked: bool):
    conn = get_db_conn()
    c = conn.cursor()
    new_status = 'locked' if locked else 'active'
    c.execute("UPDATE series SET status = %s WHERE id = %s AND status != 'completed'",
              (new_status, series_id))
    conn.commit()
    conn.close()
    return {"message": f"Series {'locked' if locked else 'unlocked'}"}


# ── Odds multipliers ──────────────────────────────────────────────────────────

@app.get("/api/admin/odds")
async def get_odds():
    conn = get_db_conn()
    c = conn.cursor()
    odds = {}
    for cat in FUTURES_BASE_POINTS:
        c.execute("SELECT value FROM site_settings WHERE key = %s", (f'odds_{cat}',))
        row = c.fetchone()
        odds[cat] = float(row[0]) if row else 1.0
    conn.close()
    return odds


@app.post("/api/admin/odds")
async def set_odds(champion: float = 1.0, west_champ: float = 1.0, east_champ: float = 1.0,
                   finals_mvp: float = 1.0, west_finals_mvp: float = 1.0, east_finals_mvp: float = 1.0):
    conn = get_db_conn()
    c = conn.cursor()
    settings = {
        'odds_champion': champion, 'odds_west_champ': west_champ, 'odds_east_champ': east_champ,
        'odds_finals_mvp': finals_mvp, 'odds_west_finals_mvp': west_finals_mvp,
        'odds_east_finals_mvp': east_finals_mvp,
    }
    for key, value in settings.items():
        c.execute("INSERT INTO site_settings (key, value) VALUES (%s, %s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
                  (key, str(value)))
    conn.commit()
    conn.close()
    return {"message": "Odds updated", **{k: v for k, v in settings.items()}}


# ── One-shot migration endpoint (safe to call multiple times) ─────────────────

@app.post("/api/admin/apply-migrations")
async def apply_migrations():
    """
    Manually trigger DB migrations.  Idempotent — safe to call repeatedly.
    Returns a detailed report so you can see exactly what happened.
    """
    results = []
    try:
        conn = get_db_conn()
        conn.autocommit = True
        c = conn.cursor()

        # Check which columns already exist
        c.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'teams'
              AND column_name IN ('odds_championship','odds_conference')
        """)
        existing = {row[0] for row in c.fetchall()}
        results.append(f"Existing odds columns before migration: {existing or 'none'}")

        for col in ("odds_championship", "odds_conference"):
            if col not in existing:
                c.execute(f"ALTER TABLE teams ADD COLUMN {col} FLOAT DEFAULT 1.0")
                results.append(f"Added column: {col}")
            else:
                results.append(f"Column already present: {col}")

        # Verify final state
        c.execute("""
            SELECT column_name, data_type, column_default
            FROM information_schema.columns
            WHERE table_name = 'teams'
              AND column_name IN ('odds_championship','odds_conference')
            ORDER BY column_name
        """)
        final = c.fetchall()
        results.append(f"Final column state: {final}")
        conn.close()
        return {"status": "ok", "steps": results}
    except Exception as e:
        return {"status": "error", "error": str(e), "steps": results}


# ── Per-team championship / conference odds ───────────────────────────────────

@app.get("/api/admin/team-odds")
async def get_team_odds():
    conn = get_db_conn()
    c = conn.cursor()
    teams = []
    try:
        c.execute('''SELECT id, name, abbreviation, conference, logo_url,
                            COALESCE(odds_championship, 1.0), COALESCE(odds_conference, 1.0)
                     FROM teams ORDER BY conference, name''')
        for row in c.fetchall():
            teams.append({
                'team_id': row[0], 'name': row[1], 'abbreviation': row[2],
                'conference': row[3], 'logo_url': row[4],
                'odds_championship': float(row[5]), 'odds_conference': float(row[6]),
            })
    except Exception:
        # Columns not migrated yet — trigger migration now then return defaults
        conn.rollback()
        _apply_odds_migration()
        c.execute('SELECT id, name, abbreviation, conference, logo_url FROM teams ORDER BY conference, name')
        for row in c.fetchall():
            teams.append({
                'team_id': row[0], 'name': row[1], 'abbreviation': row[2],
                'conference': row[3], 'logo_url': row[4],
                'odds_championship': 1.0, 'odds_conference': 1.0,
            })
    conn.close()
    return teams


@app.post("/api/admin/team-odds")
async def set_team_odds(updates: List[TeamOddsUpdate]):
    conn = get_db_conn()
    c = conn.cursor()
    for u in updates:
        c.execute(
            "UPDATE teams SET odds_championship = %s, odds_conference = %s WHERE id = %s",
            (u.odds_championship, u.odds_conference, u.team_id)
        )
    conn.commit()
    conn.close()
    return {"message": f"Updated odds for {len(updates)} teams"}


@app.post("/api/admin/update-odds")
async def update_single_team_odds(
    team_id: int,
    odds_championship: float = 1.0,
    odds_conference: float = 1.0,
):
    """Update championship and conference odds for a single team."""
    if odds_championship <= 0 or odds_conference <= 0:
        raise HTTPException(400, "Odds must be greater than 0")
    conn = get_db_conn()
    c = conn.cursor()
    c.execute(
        "UPDATE teams SET odds_championship = %s, odds_conference = %s WHERE id = %s",
        (odds_championship, odds_conference, team_id)
    )
    if c.rowcount == 0:
        conn.close()
        raise HTTPException(404, f"Team {team_id} not found")
    conn.commit()
    # Return the updated values for confirmation
    c.execute("SELECT name, abbreviation, odds_championship, odds_conference FROM teams WHERE id = %s", (team_id,))
    row = c.fetchone()
    conn.close()
    return {
        "team_id": team_id,
        "name": row[0],
        "abbreviation": row[1],
        "odds_championship": float(row[2]),
        "odds_conference": float(row[3]),
    }


# ── Futures actual results ────────────────────────────────────────────────────

@app.get("/api/admin/futures/results")
async def get_futures_results(season: str = "2026"):
    conn = get_db_conn()
    c = conn.cursor()
    results = {}
    for cat in FUTURES_BASE_POINTS:
        c.execute("SELECT value FROM site_settings WHERE key = %s", (f'actual_{cat}_{season}',))
        row = c.fetchone()
        results[cat] = row[0] if row else ''
    conn.close()
    return results


@app.post("/api/admin/futures/results")
async def set_futures_results(season: str = "2026",
                               actual_champion_id: Optional[int] = None,
                               actual_west_champ_id: Optional[int] = None,
                               actual_east_champ_id: Optional[int] = None,
                               actual_finals_mvp: Optional[str] = None,
                               actual_west_finals_mvp: Optional[str] = None,
                               actual_east_finals_mvp: Optional[str] = None):
    conn = get_db_conn()
    c = conn.cursor()

    # Store results
    settings = {
        f'actual_champion_{season}': str(actual_champion_id) if actual_champion_id else '',
        f'actual_west_champ_{season}': str(actual_west_champ_id) if actual_west_champ_id else '',
        f'actual_east_champ_{season}': str(actual_east_champ_id) if actual_east_champ_id else '',
        f'actual_finals_mvp_{season}': actual_finals_mvp or '',
        f'actual_west_finals_mvp_{season}': actual_west_finals_mvp or '',
        f'actual_east_finals_mvp_{season}': actual_east_finals_mvp or '',
    }
    for key, value in settings.items():
        c.execute("INSERT INTO site_settings (key, value) VALUES (%s, %s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
                  (key, value))

    # Load MVP category odds from site_settings (team-category odds come from teams table)
    mvp_cats = ['finals_mvp', 'west_finals_mvp', 'east_finals_mvp']
    base_odds = {}
    for cat in mvp_cats:
        c.execute("SELECT value FROM site_settings WHERE key = %s", (f'odds_{cat}',))
        row = c.fetchone()
        base_odds[cat] = float(row[0]) if row else 1.0

    # Load per-team odds so each user's pick uses that team's specific multiplier
    c.execute("SELECT id, COALESCE(odds_championship,1.0), COALESCE(odds_conference,1.0) FROM teams")
    team_odds_map = {row[0]: {'championship': float(row[1]), 'conference': float(row[2])}
                     for row in c.fetchall()}

    # Score all futures predictions
    c.execute('''SELECT id, champion_team_id, west_champ_team_id, east_champ_team_id,
                 finals_mvp, west_finals_mvp, east_finals_mvp
                 FROM futures_predictions WHERE season = %s''', (season,))
    fps = c.fetchall()

    for fp in fps:
        fp_id = fp[0]
        preds = {
            'champion':        fp[1],
            'west_champ':      fp[2],
            'east_champ':      fp[3],
            'finals_mvp':      fp[4],
            'west_finals_mvp': fp[5],
            'east_finals_mvp': fp[6],
        }
        actuals = {
            'champion':        actual_champion_id,
            'west_champ':      actual_west_champ_id,
            'east_champ':      actual_east_champ_id,
            'finals_mvp':      actual_finals_mvp,
            'west_finals_mvp': actual_west_finals_mvp,
            'east_finals_mvp': actual_east_finals_mvp,
        }
        # Build per-prediction odds: team picks use the predicted team's own multiplier
        odds = dict(base_odds)
        odds['champion']   = team_odds_map.get(fp[1], {}).get('championship', 1.0)
        odds['west_champ'] = team_odds_map.get(fp[2], {}).get('conference',   1.0)
        odds['east_champ'] = team_odds_map.get(fp[3], {}).get('conference',   1.0)
        pts, correct = calculate_futures_points(preds, actuals, odds)

        c.execute('''UPDATE futures_predictions SET
                     is_correct_champion = %s, is_correct_west = %s, is_correct_east = %s,
                     points_earned = %s WHERE id = %s''',
                  (correct.get('champion'), correct.get('west_champ'), correct.get('east_champ'),
                   pts, fp_id))

    _recalculate_all_points(c)
    conn.commit()
    conn.close()
    return {"message": "Futures results set and scores recalculated"}


# ── Playoff Leaders ───────────────────────────────────────────────────────────

@app.get("/api/leaders")
async def get_leaders(user_id: int, season: str = "2026"):
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM leaders_predictions WHERE user_id = %s AND season = %s', (user_id, season))
    row = c.fetchone()
    conn.close()
    if not row:
        return {"has_prediction": False}
    return {
        "has_prediction": True,
        "top_scorer":   row[3], "top_assists":  row[4],
        "top_rebounds": row[5], "top_threes":   row[6],
        "top_steals":   row[7], "top_blocks":   row[8],
        "is_correct_scorer":   row[10], "is_correct_assists":  row[11],
        "is_correct_rebounds": row[12], "is_correct_threes":   row[13],
        "is_correct_steals":   row[14], "is_correct_blocks":   row[15],
        "points_earned": row[16] or 0,
    }


@app.post("/api/leaders")
async def save_leaders(user_id: int, season: str = "2026",
                       top_scorer: Optional[int] = None, top_assists: Optional[int] = None,
                       top_rebounds: Optional[int] = None, top_threes: Optional[int] = None,
                       top_steals: Optional[int] = None, top_blocks: Optional[int] = None):
    if _get_futures_lock():
        raise HTTPException(400, "Predictions are locked")
    # Validate: all provided values must be positive integers
    for val in (top_scorer, top_assists, top_rebounds, top_threes, top_steals, top_blocks):
        if val is not None and val <= 0:
            raise HTTPException(400, "Stat values must be positive integers")
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('''INSERT INTO leaders_predictions
                 (user_id, season, top_scorer, top_assists, top_rebounds, top_threes, top_steals, top_blocks)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                 ON CONFLICT(user_id, season) DO UPDATE SET
                 top_scorer = EXCLUDED.top_scorer, top_assists = EXCLUDED.top_assists,
                 top_rebounds = EXCLUDED.top_rebounds, top_threes = EXCLUDED.top_threes,
                 top_steals = EXCLUDED.top_steals, top_blocks = EXCLUDED.top_blocks,
                 predicted_at = CURRENT_TIMESTAMP''',
              (user_id, season, top_scorer, top_assists, top_rebounds, top_threes, top_steals, top_blocks))
    conn.commit()
    conn.close()
    return {"message": "Saved"}


@app.get("/api/admin/leaders/results")
async def get_leaders_results(season: str = "2026"):
    conn = get_db_conn()
    c = conn.cursor()
    results = {}
    for cat in LEADERS_POINTS:
        c.execute("SELECT value FROM site_settings WHERE key = %s", (f'leaders_{cat}_{season}',))
        row = c.fetchone()
        raw = row[0] if row else None
        # Return as integer when available, else None
        try:
            results[cat] = int(raw) if raw and raw.strip() else None
        except (ValueError, TypeError):
            results[cat] = None
    conn.close()
    return results


@app.post("/api/admin/leaders/results")
async def set_leaders_results(season: str = "2026",
                               top_scorer: Optional[int] = None, top_assists: Optional[int] = None,
                               top_rebounds: Optional[int] = None, top_threes: Optional[int] = None,
                               top_steals: Optional[int] = None, top_blocks: Optional[int] = None):
    conn = get_db_conn()
    c = conn.cursor()
    # Store as string in site_settings (value column is TEXT); 0 or None means not set
    actual = {
        'scorer':   top_scorer   if top_scorer   and top_scorer   > 0 else None,
        'assists':  top_assists  if top_assists  and top_assists  > 0 else None,
        'rebounds': top_rebounds if top_rebounds and top_rebounds > 0 else None,
        'threes':   top_threes   if top_threes   and top_threes   > 0 else None,
        'steals':   top_steals   if top_steals   and top_steals   > 0 else None,
        'blocks':   top_blocks   if top_blocks   and top_blocks   > 0 else None,
    }
    for cat, val in actual.items():
        c.execute("INSERT INTO site_settings (key, value) VALUES (%s, %s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
                  (f'leaders_{cat}_{season}', str(val) if val is not None else ''))

    c.execute('''SELECT id, top_scorer, top_assists, top_rebounds, top_threes, top_steals, top_blocks
                 FROM leaders_predictions WHERE season = %s''', (season,))
    lps = c.fetchall()
    for lp in lps:
        lp_id = lp[0]
        preds = {
            'scorer':   lp[1], 'assists':   lp[2],
            'rebounds': lp[3], 'threes':    lp[4],
            'steals':   lp[5], 'blocks':    lp[6],
        }
        # actual values are already int | None from the dict above
        pts, correct = calculate_leaders_points(preds, actual)
        c.execute('''UPDATE leaders_predictions SET
                     is_correct_scorer = %s, is_correct_assists = %s,
                     is_correct_rebounds = %s, is_correct_threes = %s,
                     is_correct_steals = %s, is_correct_blocks = %s,
                     points_earned = %s WHERE id = %s''',
                  (correct.get('scorer'), correct.get('assists'), correct.get('rebounds'),
                   correct.get('threes'), correct.get('steals'), correct.get('blocks'), pts, lp_id))

    _recalculate_all_points(c)
    conn.commit()
    conn.close()
    return {"message": "Leaders results set", "results": actual}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
