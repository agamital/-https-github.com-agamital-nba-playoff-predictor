from fastapi import FastAPI, HTTPException, Request, UploadFile, File, BackgroundTasks, Response
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
from apscheduler.triggers.date import DateTrigger
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
    LEADERS_TIERS,
    SERIES_LEADER_BONUS,
)

# ── Anthropic SDK (optional — chatbot feature) ────────────────────────────────
try:
    import anthropic as _anthropic_sdk
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _anthropic_sdk = None
    _ANTHROPIC_AVAILABLE = False
    print("[startup] WARNING: anthropic package not installed — /api/chat will return 503")

_standings_cache = {"data": None, "expires": None, "fetched_at": None}

# Sync runs once daily (04:00 UTC) until end-of-day April 20 2026 (last regular-season day).
# After this the app enters Static Mode: DB snapshot is served forever, no API calls.
_STANDINGS_SYNC_CUTOFF = datetime(2026, 4, 14, 0, 0, 0)   # extended — games on Apr 13; stops standings ON April 14
# Email / push reminders keep running through the playoffs (Finals end ~June 2026)
_EMAIL_REMINDER_CUTOFF = datetime(2026, 7, 1, 0, 0, 0)

# ── Player name normalization (accent / diacritic stripping) ─────────────────
import unicodedata as _ud

def _normalize_name(name: str) -> str:
    """
    Strip diacritics and lowercase a player name for dedup comparisons.
    'Luka Dončić' → 'luka doncic', 'Matisse Thybulle' → 'matisse thybulle'.
    Used in both backend search dedup and boxscore sync name-matching.
    """
    return ''.join(
        c for c in _ud.normalize('NFD', name or '')
        if _ud.category(c) != 'Mn'
    ).lower().strip()


# ── On-demand freshness TTLs (minutes) ────────────────────────────────────────
# Prevents redundant API calls when a user repeatedly triggers a refresh.
STANDINGS_TTL_MINUTES: int = 360   # 6 h — standings don't change mid-day
BOXSCORE_TTL_MINUTES:  int = 20    # 20 min — enough for live game windows

# Per-date boxscore sync timestamps (in-memory; resets on restart).
# Keyed by ISO date string ('YYYY-MM-DD') → last successful sync datetime (UTC).
_boxscore_last_sync: dict = {}

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

# Gmail API (OAuth2) credentials — set these in Railway env vars.
# Generate GMAIL_REFRESH_TOKEN once with the companion script
# tools/generate_gmail_token.py, then store the printed value here.
_GMAIL_CLIENT_ID     = os.getenv("GMAIL_CLIENT_ID",     "")
_GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET", "")
_GMAIL_REFRESH_TOKEN = os.getenv("GMAIL_REFRESH_TOKEN", "")
_GMAIL_SENDER        = os.getenv("GMAIL_SENDER",
                                  "nbaplayoffpredictor2000@gmail.com")
# CRON_SECRET — shared secret between Vercel cron and this backend to prevent
# unauthenticated calls to the trigger-reminder endpoint.
_CRON_SECRET    = os.getenv("CRON_SECRET", "")

# Supabase Storage — for user avatar uploads
# URL is the same project used for Google OAuth (already public in the frontend).
# Service role key must be set in Railway env vars (Settings → Variables).
_SUPABASE_URL = (
    os.getenv("SUPABASE_URL")
    or os.getenv("VITE_SUPABASE_URL")          # some deployments mirror the frontend var
    or "https://nvfmfbedpbulynqmbdqt.supabase.co"   # project-specific fallback
).rstrip("/")
_SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

# APScheduler instance — created in startup(), referenced in shutdown()
_scheduler = None

# ── On-demand live sync ────────────────────────────────────────────────────
# Triggered whenever a user fetches play-in or series data.
# Cooldown prevents hammering the API on every request.
import threading as _threading
_live_sync_lock   = _threading.Lock()
_live_sync_last   = 0.0          # epoch seconds of last completed sync
_LIVE_SYNC_COOLDOWN = 300        # seconds — only re-sync at most once per 5 min

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

# ESPN public APIs — no key needed
_ESPN_BOXSCORE_URL    = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
_ESPN_SCOREBOARD_URL2 = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
_ESPN_STANDINGS_URL   = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/standings"

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

# Hardcoded standings (2025-26 season, FINAL after April 13 2026).
# Used instantly on startup so users never wait for the NBA API.
_HARDCODED_STANDINGS = [
    # Eastern Conference
    {'team_id': 1610612765, 'team_name': 'Detroit Pistons',        'conference': 'East', 'wins': 60, 'losses': 22, 'win_pct': 0.732, 'conf_rank': 1,  'playoff_rank': 1},
    {'team_id': 1610612738, 'team_name': 'Boston Celtics',         'conference': 'East', 'wins': 56, 'losses': 26, 'win_pct': 0.683, 'conf_rank': 2,  'playoff_rank': 2},
    {'team_id': 1610612752, 'team_name': 'New York Knicks',        'conference': 'East', 'wins': 53, 'losses': 29, 'win_pct': 0.646, 'conf_rank': 3,  'playoff_rank': 3},
    {'team_id': 1610612739, 'team_name': 'Cleveland Cavaliers',    'conference': 'East', 'wins': 52, 'losses': 30, 'win_pct': 0.634, 'conf_rank': 4,  'playoff_rank': 4},
    {'team_id': 1610612761, 'team_name': 'Toronto Raptors',        'conference': 'East', 'wins': 46, 'losses': 36, 'win_pct': 0.561, 'conf_rank': 5,  'playoff_rank': 5},
    {'team_id': 1610612737, 'team_name': 'Atlanta Hawks',          'conference': 'East', 'wins': 46, 'losses': 36, 'win_pct': 0.561, 'conf_rank': 6,  'playoff_rank': 6},
    {'team_id': 1610612755, 'team_name': 'Philadelphia 76ers',     'conference': 'East', 'wins': 45, 'losses': 37, 'win_pct': 0.549, 'conf_rank': 7,  'playoff_rank': 7},
    {'team_id': 1610612753, 'team_name': 'Orlando Magic',          'conference': 'East', 'wins': 45, 'losses': 37, 'win_pct': 0.549, 'conf_rank': 8,  'playoff_rank': 8},
    {'team_id': 1610612766, 'team_name': 'Charlotte Hornets',      'conference': 'East', 'wins': 44, 'losses': 38, 'win_pct': 0.537, 'conf_rank': 9,  'playoff_rank': 9},
    {'team_id': 1610612748, 'team_name': 'Miami Heat',             'conference': 'East', 'wins': 43, 'losses': 39, 'win_pct': 0.524, 'conf_rank': 10, 'playoff_rank': 10},
    # Western Conference
    {'team_id': 1610612760, 'team_name': 'Oklahoma City Thunder',  'conference': 'West', 'wins': 64, 'losses': 18, 'win_pct': 0.780, 'conf_rank': 1,  'playoff_rank': 1},
    {'team_id': 1610612759, 'team_name': 'San Antonio Spurs',      'conference': 'West', 'wins': 62, 'losses': 20, 'win_pct': 0.756, 'conf_rank': 2,  'playoff_rank': 2},
    {'team_id': 1610612743, 'team_name': 'Denver Nuggets',         'conference': 'West', 'wins': 54, 'losses': 28, 'win_pct': 0.659, 'conf_rank': 3,  'playoff_rank': 3},
    {'team_id': 1610612747, 'team_name': 'Los Angeles Lakers',     'conference': 'West', 'wins': 53, 'losses': 29, 'win_pct': 0.646, 'conf_rank': 4,  'playoff_rank': 4},
    {'team_id': 1610612745, 'team_name': 'Houston Rockets',        'conference': 'West', 'wins': 52, 'losses': 30, 'win_pct': 0.634, 'conf_rank': 5,  'playoff_rank': 5},
    {'team_id': 1610612750, 'team_name': 'Minnesota Timberwolves', 'conference': 'West', 'wins': 49, 'losses': 33, 'win_pct': 0.598, 'conf_rank': 6,  'playoff_rank': 6},
    {'team_id': 1610612756, 'team_name': 'Phoenix Suns',           'conference': 'West', 'wins': 45, 'losses': 37, 'win_pct': 0.549, 'conf_rank': 7,  'playoff_rank': 7},
    {'team_id': 1610612757, 'team_name': 'Portland Trail Blazers', 'conference': 'West', 'wins': 42, 'losses': 40, 'win_pct': 0.512, 'conf_rank': 8,  'playoff_rank': 8},
    {'team_id': 1610612746, 'team_name': 'LA Clippers',            'conference': 'West', 'wins': 42, 'losses': 40, 'win_pct': 0.512, 'conf_rank': 9,  'playoff_rank': 9},
    {'team_id': 1610612744, 'team_name': 'Golden State Warriors',  'conference': 'West', 'wins': 37, 'losses': 45, 'win_pct': 0.451, 'conf_rank': 10, 'playoff_rank': 10},
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

# ── PostgreSQL connection pool ─────────────────────────────────────────────────
# Reuses connections across requests instead of opening a new TCP+SSL+auth
# handshake every time (~200–400 ms per cold connection on Railway).
# ThreadedConnectionPool is safe with FastAPI's default thread-pool executor.
import psycopg2.pool as _pg_pool

_db_pool: '_pg_pool.ThreadedConnectionPool | None' = None

def _init_db_pool() -> None:
    global _db_pool
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    # TCP keepalives keep Railway from dropping idle connections silently.
    # keepalives_idle=30 → probe after 30 s idle; 5 probes × 10 s apart.
    _db_pool = _pg_pool.ThreadedConnectionPool(
        minconn=1,
        maxconn=8,   # conservative — Railway free Postgres caps at ~25 total
        dsn=url,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5,
        connect_timeout=15,
    )
    print(f"[DB] Connection pool initialised (min=1 max=8, keepalives on)")


class _PooledConn:
    """
    Thin proxy around a psycopg2 connection from the pool.
    Redirects .close() to putconn() so the connection is reused, not terminated.
    All other attributes/methods are transparently delegated to the real conn.
    """
    __slots__ = ('_c', '_pool')

    def __init__(self, conn, pool):
        object.__setattr__(self, '_c',    conn)
        object.__setattr__(self, '_pool', pool)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, '_c'), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, '_c'), name, value)

    def close(self):
        c    = object.__getattribute__(self, '_c')
        pool = object.__getattribute__(self, '_pool')
        try:
            c.rollback()        # reset any uncommitted transaction
        except Exception:
            pass
        try:
            pool.putconn(c)     # return to pool ← the key change
        except Exception:
            try: c.close()      # last resort: actually close if pool is gone
            except Exception: pass

    # Support `with conn:` blocks (some endpoints use this pattern)
    def __enter__(self):
        return object.__getattribute__(self, '_c').__enter__()

    def __exit__(self, *args):
        return object.__getattribute__(self, '_c').__exit__(*args)


def _direct_conn():
    """Open a fresh connection with keepalives (used as fallback)."""
    url = os.environ.get("DATABASE_URL", "")
    return psycopg2.connect(
        url,
        keepalives=1, keepalives_idle=30,
        keepalives_interval=10, keepalives_count=5,
        connect_timeout=15,
    )


def get_db_conn() -> _PooledConn:
    """
    Return a pooled connection. Callers still call conn.close() as before —
    the wrapper silently returns the connection to the pool instead.

    Validates the connection is alive before returning; if Railway has
    dropped it, discards it and gets a fresh one (up to 3 attempts).
    """
    global _db_pool
    if _db_pool is None or _db_pool.closed:
        _init_db_pool()
    for _attempt in range(3):
        try:
            raw = _db_pool.getconn()
            # Quick liveness check — catches TCP connections dropped by Railway
            if raw.closed != 0:
                raise Exception("connection already closed")
            try:
                raw.cursor().execute("SELECT 1")
                raw.reset()          # clear any lingering state
            except Exception:
                # Dead connection — discard from pool, retry
                try: _db_pool.putconn(raw, close=True)
                except Exception: pass
                print(f"[DB] Stale pooled connection discarded (attempt {_attempt+1})")
                continue
            return _PooledConn(raw, _db_pool)
        except _pg_pool.PoolError:
            # Pool exhausted — fall back to a direct connection so the request
            # still succeeds (just without pooling benefit).
            print("[DB] Pool exhausted — opening direct connection (temporary)")
            return _direct_conn()  # type: ignore[return-value]
    # All retries used up — open a direct connection as last resort
    print("[DB] All pool retries failed — opening direct connection")
    return _direct_conn()  # type: ignore[return-value]

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

class ChatMessage(BaseModel):
    role: str        # "user" | "assistant"
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    user_id: Optional[int] = None
    season: str = "2026"


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
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS reminder_last_sent_at TIMESTAMP")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS reminder_opt_out BOOLEAN DEFAULT FALSE")

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
        status TEXT DEFAULT 'active',
        start_time TIMESTAMP
    )''')
    # Add start_time to existing tables
    c.execute('SAVEPOINT sp_playin_start_time')
    try:
        c.execute('ALTER TABLE playin_games ADD COLUMN IF NOT EXISTS start_time TIMESTAMP')
        c.execute('RELEASE SAVEPOINT sp_playin_start_time')
    except Exception as e:
        print(f"init_db: playin_games.start_time migration: {e}")
        c.execute('ROLLBACK TO SAVEPOINT sp_playin_start_time')

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

    # Performance indexes — idempotent, safe to run every startup
    c.execute("CREATE INDEX IF NOT EXISTS idx_series_season ON series(season)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_series_season_status ON series(season, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_predictions_series ON predictions(series_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_futures_user_season ON futures_predictions(user_id, season)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_leaders_user_season ON leaders_predictions(user_id, season)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_playin_season ON playin_games(season)")
    # users.points — makes rank query (COUNT WHERE points > ?) O(log n) instead of O(n)
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_points ON users(points)")
    # player_game_stats(season, game_date) — speeds up playoff-highs and provisional-pts scans
    c.execute("CREATE INDEX IF NOT EXISTS idx_pgs_season_date ON player_game_stats(season, game_date)")

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
        conf = 'East' if team['abbreviation'] in eastern else 'West'
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


def _fetch_standings_from_espn_direct() -> list:
    """
    Fetch NBA standings from ESPN's free public API — no API key required.
    Same response format as _fetch_standings_from_primary_api() (ESPN-backed).
    Returns list of team dicts; raises on failure.
    """
    import requests as _http

    print(f"[ESPN-Direct] GET {_ESPN_STANDINGS_URL}")
    resp = _http.get(_ESPN_STANDINGS_URL, timeout=15)
    print(f"[ESPN-Direct] HTTP {resp.status_code}")
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
        conf_abbr = conf_block.get("abbreviation", "")
        if "east" in conf_abbr.lower():
            conf = "East"
        elif "west" in conf_abbr.lower():
            conf = "West"
        else:
            continue

        entries = conf_block.get("standings", {}).get("entries", [])
        for entry in entries:
            team_obj  = entry.get("team", {})
            team_name = (team_obj.get("displayName") or
                         f"{team_obj.get('location','')} {team_obj.get('name','')}".strip())
            abbr      = team_obj.get("abbreviation", "")

            stats_map = {
                s["name"].lower(): s.get("value")
                for s in entry.get("stats", [])
                if s.get("name")
            }

            wins    = _safe_int(stats_map.get("wins"))
            losses  = _safe_int(stats_map.get("losses"))
            win_pct = _safe_float(stats_map.get("winpercent"))
            gb_raw  = stats_map.get("gamesbehind", "0")
            gb      = 0.0 if str(gb_raw) in ("-", "", "None") else _safe_float(gb_raw)
            seed    = _safe_int(stats_map.get("playoffseed") or
                                stats_map.get("seed") or
                                stats_map.get("conferencerank"), 99)

            if win_pct == 0.0 and (wins + losses) > 0:
                win_pct = round(wins / (wins + losses), 3)

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

    bad = [t for t in standings if any(kw in t["team_name"].lower() for kw in _ALLSTAR_KEYWORDS)]
    if bad:
        raise ValueError(f"ESPN direct returned bad data: '{bad[0]['team_name']}'")
    if len(standings) < 20:
        raise ValueError(f"ESPN direct: only {len(standings)} teams parsed (expected 30)")

    e1 = next((t for t in standings if t["conference"] == "East" and t["conf_rank"] == 1), None)
    w1 = next((t for t in standings if t["conference"] == "West" and t["conf_rank"] == 1), None)
    print(f"[ESPN-Direct] ✓ {len(standings)} teams — "
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
    params["limit"] = 20   # prevent default page-size of 5 from truncating heavy days
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
    Deprecated stub — email reminders are now handled exclusively by
    _send_daily_email_reminders() which queries the DB for each user's
    specific missing matchups and applies the 20-hour dedup.
    Kept so call-sites don't break; intentionally does nothing.
    """
    pass


def _send_missing_picks_alert() -> None:
    """
    Twice-daily cron (06:00 UTC = 09:00 IDT, 18:00 UTC = 21:00 IDT):
    find users who have at least one active/unlocked series OR open play-in game
    with no prediction, then send them a targeted OneSignal push AND a Gmail
    SMTP email reminder.
    Runs until _EMAIL_REMINDER_CUTOFF; skips silently if no credentials are set.
    """
    if datetime.utcnow() >= _EMAIL_REMINDER_CUTOFF:
        return

    has_push  = bool(_ONESIGNAL_API_KEY)
    has_email = bool(_GMAIL_CLIENT_ID and _GMAIL_CLIENT_SECRET and _GMAIL_REFRESH_TOKEN)
    if not has_push and not has_email:
        print("[Alert] Neither ONESIGNAL_API_KEY nor Gmail API credentials set — skipping alert")
        return

    conn = None
    try:
        conn = get_db_conn()
        c    = conn.cursor()

        # Are there any active (unlocked) series or open play-in games?
        c.execute("SELECT COUNT(*) FROM series WHERE season = '2026' AND status = 'active'")
        has_active_series = bool(c.fetchone()[0])

        c.execute("""
            SELECT COUNT(*) FROM playin_games
            WHERE season = '2026' AND status != 'completed'
            AND (start_time IS NULL OR start_time > NOW())
        """)
        has_active_playin = bool(c.fetchone()[0])

        if not has_active_series and not has_active_playin:
            print("[Alert] No active series or open play-in games — skipping missing-picks alert")
            return

        # Users (id + email) missing at least one active-series OR play-in prediction
        c.execute("""
            SELECT DISTINCT u.id::text, u.email
            FROM users u
            WHERE
                -- Missing at least one active-series prediction
                EXISTS (
                    SELECT 1 FROM series s
                    WHERE s.season = '2026' AND s.status = 'active'
                    AND NOT EXISTS (
                        SELECT 1 FROM predictions p
                        WHERE p.user_id = u.id AND p.series_id = s.id
                    )
                )
                OR
                -- Missing at least one open play-in prediction (bets not yet closed)
                EXISTS (
                    SELECT 1 FROM playin_games pg
                    WHERE pg.season = '2026' AND pg.status != 'completed'
                    AND (pg.start_time IS NULL OR pg.start_time > NOW())
                    AND NOT EXISTS (
                        SELECT 1 FROM playin_predictions pp
                        WHERE pp.user_id = u.id AND pp.game_id = pg.id
                    )
                )
        """)
        rows = c.fetchall()          # list of (str_id, email)
        conn.close()
        conn = None

        if not rows:
            print("[Alert] All users have completed their picks — no alert needed")
            return

        user_ids = [r[0] for r in rows]
        print(f"[Alert] Notifying {len(rows)} user(s) with missing picks")

        # ── OneSignal push ─────────────────────────────────────────────────────
        # Use include_aliases for targeted delivery (only linked subscribers).
        # Also send a broadcast fallback so subscribers who never linked still get it.
        if has_push:
            import urllib.request, json as _json

            def _os_post(body_dict):
                payload = _json.dumps(body_dict).encode("utf-8")
                req = urllib.request.Request(
                    "https://onesignal.com/api/v1/notifications",
                    data=payload,
                    headers={
                        "Content-Type":  "application/json; charset=utf-8",
                        "Authorization": f"Key {_ONESIGNAL_API_KEY}",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return _json.loads(resp.read())

            push_title = "🏀 Don't forget your picks!"
            push_body  = ("You have open NBA playoff picks waiting — "
                          "lock them in before the game starts!")

            # Targeted: users who linked their external_id
            try:
                res = _os_post({
                    "app_id":          _ONESIGNAL_APP_ID,
                    "include_aliases": {"external_id": user_ids},
                    "target_channel":  "push",
                    "headings":        {"en": push_title},
                    "contents":        {"en": push_body},
                    "url":             "https://nba-playoffs-2026.vercel.app",
                })
                print(f"[Alert] Targeted push sent — recipients: {res.get('recipients', '?')}")
            except Exception as e:
                print(f"[Alert] Targeted OneSignal push error: {e}")

            # Broadcast fallback: reaches all subscribed devices (including unlinked)
            try:
                res2 = _os_post({
                    "app_id":            _ONESIGNAL_APP_ID,
                    "included_segments": ["All"],
                    "headings":          {"en": push_title},
                    "contents":          {"en": push_body},
                    "url":               "https://nba-playoffs-2026.vercel.app",
                })
                print(f"[Alert] Broadcast push sent — recipients: {res2.get('recipients', '?')}")
            except Exception as e:
                print(f"[Alert] Broadcast OneSignal push error: {e}")

        # ── Gmail email — use the same full per-user path as daily reminders ──
        if has_email:
            threading.Thread(target=_send_daily_email_reminders, daemon=True).start()

    except Exception as e:
        print(f"[Alert] Missing-picks alert error: {e}")
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def _send_futures_bet_reminder(hours_before: int) -> None:
    """
    DateTrigger job — fires at 12h, 6h, 2h before FUTURES_LOCK_UTC.
    Finds users who have NOT submitted futures_predictions OR leaders_predictions
    for season 2026, then sends a targeted push + email to each.
    """
    label_map = {12: "12 hours", 6: "6 hours", 2: "2 hours", 3: "3 hours", 1: "1 hour"}
    time_label = label_map.get(hours_before, f"{hours_before} hours")

    conn = None
    try:
        conn = get_db_conn()
        c    = conn.cursor()

        # Find users missing futures OR leaders — fetch their email too
        c.execute("""
            SELECT DISTINCT u.id::text, u.email,
                (NOT EXISTS (SELECT 1 FROM futures_predictions fp WHERE fp.user_id = u.id AND fp.season = '2026')) AS missing_futures,
                (NOT EXISTS (SELECT 1 FROM leaders_predictions lp WHERE lp.user_id = u.id AND lp.season = '2026')) AS missing_leaders
            FROM users u
            WHERE
                NOT EXISTS (SELECT 1 FROM futures_predictions fp WHERE fp.user_id = u.id AND fp.season = '2026')
                OR NOT EXISTS (SELECT 1 FROM leaders_predictions lp WHERE lp.user_id = u.id AND lp.season = '2026')
        """)
        rows = c.fetchall()
        conn.close(); conn = None

        if not rows:
            print(f"[FuturesReminder {hours_before}h] All users have submitted — skipping")
            return

        user_ids = [r[0] for r in rows]
        print(f"[FuturesReminder {hours_before}h] Notifying {len(user_ids)} user(s) missing futures/leaders bets")

        push_title = f"⏰ {time_label} left to place your bets!"
        push_body  = (f"Futures & Playoff Leaders bets close in {time_label} — "
                      "lock in your predictions before it's too late!")

        # ── Push ──────────────────────────────────────────────────────────────
        if _ONESIGNAL_API_KEY:
            import urllib.request, json as _json
            def _os_post(bd):
                payload = _json.dumps(bd).encode("utf-8")
                req = urllib.request.Request(
                    "https://onesignal.com/api/v1/notifications", data=payload,
                    headers={"Content-Type": "application/json; charset=utf-8",
                             "Authorization": f"Key {_ONESIGNAL_API_KEY}"}, method="POST")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return _json.loads(resp.read())
            try:
                res = _os_post({"app_id": _ONESIGNAL_APP_ID,
                    "include_aliases": {"external_id": user_ids}, "target_channel": "push",
                    "headings": {"en": push_title}, "contents": {"en": push_body},
                    "url": "https://nba-playoffs-2026.vercel.app"})
                print(f"[FuturesReminder {hours_before}h] Push targeted — {res.get('recipients','?')}")
            except Exception as e:
                print(f"[FuturesReminder {hours_before}h] Push targeted error: {e}")
            try:
                res2 = _os_post({"app_id": _ONESIGNAL_APP_ID, "included_segments": ["All"],
                    "headings": {"en": push_title}, "contents": {"en": push_body},
                    "url": "https://nba-playoffs-2026.vercel.app"})
                print(f"[FuturesReminder {hours_before}h] Push broadcast — {res2.get('recipients','?')}")
            except Exception as e:
                print(f"[FuturesReminder {hours_before}h] Push broadcast error: {e}")

        # ── Email — per-user labels so each person sees what they're missing ──
        email_labels = []
        for uid, email, missing_futures, missing_leaders in rows:
            if not email:
                continue
            labels = []
            if missing_futures:
                labels.append(f"Futures Predictions (Champion, Conference winners, Finals MVPs) — bets close in {time_label}")
            if missing_leaders:
                labels.append(f"Playoff Leaders (Max single-game stats) — bets close in {time_label}")
            if labels:
                email_labels.append((email, labels))

        if email_labels:
            threading.Thread(
                target=_send_bulk_email_reminder,
                args=("Futures & Leaders", hours_before, email_labels),
                daemon=True,
            ).start()

    except Exception as e:
        print(f"[FuturesReminder {hours_before}h] Error: {type(e).__name__}: {e}")
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def _send_playin_game_reminder(conference: str, game_type: str, hours_before: int = 2) -> None:
    """
    Fire a targeted push + email before a play-in game tips off.
    Targets users who have NOT placed a playin_prediction for this game.
    Skips if the game no longer exists or is already completed.
    """
    _game_labels = {
        '7v8':         'Game 1 (7 vs 8)',
        '9v10':        'Game 2 (9 vs 10)',
        'elimination': 'Game 3 — Elimination',
    }
    game_label = _game_labels.get(game_type, game_type)
    label_map = {12: "12 hours", 6: "6 hours", 2: "2 hours", 3: "3 hours", 1: "1 hour"}
    time_label = label_map.get(hours_before, f"{hours_before} hours")
    context = f"{conference} Play-In {game_label}"

    conn = None
    try:
        conn = get_db_conn()
        c    = conn.cursor()

        c.execute(
            "SELECT id, status FROM playin_games WHERE season='2026' AND conference=%s AND game_type=%s",
            (conference, game_type),
        )
        row = c.fetchone()
        if not row:
            print(f"[PlayinReminder {hours_before}h] {context} — not found, skip")
            conn.close(); return
        if row[1] == 'completed':
            print(f"[PlayinReminder {hours_before}h] {context} — completed, skip")
            conn.close(); return

        game_id = row[0]

        # Users who haven't bet on this game (with email for email reminders)
        c.execute("""
            SELECT DISTINCT u.id::text, u.email
            FROM users u
            WHERE NOT EXISTS (
                SELECT 1 FROM playin_predictions pp
                WHERE pp.user_id = u.id AND pp.game_id = %s
            )
        """, (game_id,))
        rows = c.fetchall()
        conn.close(); conn = None

        user_ids = [r[0] for r in rows]
        if not user_ids:
            print(f"[PlayinReminder {hours_before}h] {context} — all users have bet, skip")
            return

        push_title = f"⏰ {conference} Play-In bets close in {time_label}!"
        push_body  = (f"{conference} {game_label} tips off in {time_label} — "
                      "lock in your pick before bets close!")

        # ── Push ──────────────────────────────────────────────────────────────
        if _ONESIGNAL_API_KEY:
            import urllib.request, json as _json
            def _os_post(bd):
                payload = _json.dumps(bd).encode("utf-8")
                req = urllib.request.Request(
                    "https://onesignal.com/api/v1/notifications", data=payload,
                    headers={"Content-Type": "application/json; charset=utf-8",
                             "Authorization": f"Key {_ONESIGNAL_API_KEY}"}, method="POST")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return _json.loads(resp.read())
            try:
                res = _os_post({"app_id": _ONESIGNAL_APP_ID,
                    "include_aliases": {"external_id": user_ids}, "target_channel": "push",
                    "headings": {"en": push_title}, "contents": {"en": push_body},
                    "url": "https://nba-playoffs-2026.vercel.app"})
                print(f"[PlayinReminder {hours_before}h] {context} push targeted — {res.get('recipients','?')}")
            except Exception as e:
                print(f"[PlayinReminder {hours_before}h] Push targeted error: {e}")
            try:
                res2 = _os_post({"app_id": _ONESIGNAL_APP_ID, "included_segments": ["All"],
                    "headings": {"en": push_title}, "contents": {"en": push_body},
                    "url": "https://nba-playoffs-2026.vercel.app"})
                print(f"[PlayinReminder {hours_before}h] {context} push broadcast — {res2.get('recipients','?')}")
            except Exception as e:
                print(f"[PlayinReminder {hours_before}h] Push broadcast error: {e}")

        # ── Email ──────────────────────────────────────────────────────────────
        email_label = f"{conference} Play-In {game_label} (tips off in {time_label})"
        email_labels = [(r[1], [email_label]) for r in rows if r[1]]
        if email_labels:
            threading.Thread(
                target=_send_bulk_email_reminder,
                args=(context, hours_before, email_labels),
                daemon=True,
            ).start()

    except Exception as e:
        print(f"[PlayinReminder {hours_before}h] Error ({conference} {game_type}): {type(e).__name__}: {e}")
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def _send_series_bet_reminder(conference: str, home_seed: int, away_seed: int, hours_before: int) -> None:
    """
    Fire a targeted push + email before a playoff series Game 1.
    Targets users who have NOT placed a prediction for this series.
    Skips if the series doesn't exist.
    """
    label_map = {12: "12 hours", 6: "6 hours", 2: "2 hours", 3: "3 hours", 1: "1 hour"}
    time_label = label_map.get(hours_before, f"{hours_before} hours")

    conn = None
    try:
        conn = get_db_conn()
        c    = conn.cursor()

        c.execute("""
            SELECT s.id, t1.abbreviation, t2.abbreviation
            FROM series s
            LEFT JOIN teams t1 ON t1.id = s.home_team_id
            LEFT JOIN teams t2 ON t2.id = s.away_team_id
            WHERE s.season = '2026' AND s.conference = %s
              AND s.home_seed = %s AND s.away_seed = %s
              AND s.round = 'First Round'
        """, (conference, home_seed, away_seed))
        row = c.fetchone()

        if not row:
            print(f"[SeriesReminder {hours_before}h] {conference} {home_seed}v{away_seed} — not found, skip")
            conn.close(); return

        series_id, home_abbr, away_abbr = row
        matchup = f"{home_abbr or f'#{home_seed}'} vs {away_abbr or f'#{away_seed}'}"

        # Users who haven't bet on this series (with email)
        c.execute("""
            SELECT DISTINCT u.id::text, u.email
            FROM users u
            WHERE NOT EXISTS (
                SELECT 1 FROM predictions p
                WHERE p.user_id = u.id AND p.series_id = %s
            )
        """, (series_id,))
        rows = c.fetchall()
        conn.close(); conn = None

        user_ids = [r[0] for r in rows]
        if not user_ids:
            print(f"[SeriesReminder {hours_before}h] {matchup} — all users have bet, skip")
            return

        push_title = f"⏰ {matchup} bets close in {time_label}!"
        push_body  = (f"{conference} First Round — {matchup} Game 1 tips off in {time_label}. "
                      "Lock in your series prediction before bets close!")

        # ── Push ──────────────────────────────────────────────────────────────
        if _ONESIGNAL_API_KEY:
            import urllib.request, json as _json
            def _os_post(bd):
                payload = _json.dumps(bd).encode("utf-8")
                req = urllib.request.Request(
                    "https://onesignal.com/api/v1/notifications", data=payload,
                    headers={"Content-Type": "application/json; charset=utf-8",
                             "Authorization": f"Key {_ONESIGNAL_API_KEY}"}, method="POST")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return _json.loads(resp.read())
            try:
                res = _os_post({"app_id": _ONESIGNAL_APP_ID,
                    "include_aliases": {"external_id": user_ids}, "target_channel": "push",
                    "headings": {"en": push_title}, "contents": {"en": push_body},
                    "url": "https://nba-playoffs-2026.vercel.app"})
                print(f"[SeriesReminder {hours_before}h] {matchup} push targeted — {res.get('recipients','?')}")
            except Exception as e:
                print(f"[SeriesReminder {hours_before}h] Push targeted error: {e}")
            try:
                res2 = _os_post({"app_id": _ONESIGNAL_APP_ID, "included_segments": ["All"],
                    "headings": {"en": push_title}, "contents": {"en": push_body},
                    "url": "https://nba-playoffs-2026.vercel.app"})
                print(f"[SeriesReminder {hours_before}h] {matchup} push broadcast — {res2.get('recipients','?')}")
            except Exception as e:
                print(f"[SeriesReminder {hours_before}h] Push broadcast error: {e}")

        # ── Email ──────────────────────────────────────────────────────────────
        email_label = f"{matchup} — {conference} First Round Game 1 (tips off in {time_label})"
        email_labels = [(r[1], [email_label]) for r in rows if r[1]]
        if email_labels:
            threading.Thread(
                target=_send_bulk_email_reminder,
                args=(matchup, hours_before, email_labels),
                daemon=True,
            ).start()

    except Exception as e:
        print(f"[SeriesReminder {hours_before}h] Error ({conference} {home_seed}v{away_seed}): "
              f"{type(e).__name__}: {e}")
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def _send_bulk_email_reminder(context_label: str, hours_before: int,
                              email_labels: list) -> int:
    """
    Send one email per recipient in email_labels.
    email_labels = [(email_address, [label_str, ...]), ...]
    Skips entries with empty label lists.  Returns count of emails sent.  Never raises.
    """
    if not _GMAIL_CLIENT_ID or not _GMAIL_CLIENT_SECRET or not _GMAIL_REFRESH_TOKEN:
        print(f"[BulkEmail {hours_before}h] Gmail credentials not set — skipping")
        return 0
    if not email_labels:
        return 0

    label_map = {12: "12 hours", 6: "6 hours", 2: "2 hours", 3: "3 hours", 1: "1 hour"}
    time_label = label_map.get(hours_before, f"{hours_before} hours")
    subject = f"⏰ {time_label} left — lock in your NBA playoff picks!"

    sent = 0
    for email, labels in email_labels:
        if not email or not labels:
            continue
        try:
            _gmail_send_email(email, subject, _build_reminder_html(labels))
            sent += 1
            print(f"[BulkEmail {hours_before}h] ✓ {email} ({len(labels)} bet(s))")
        except Exception as e:
            print(f"[BulkEmail {hours_before}h] ✗ {email}: {e}")

    print(f"[BulkEmail {hours_before}h] {context_label} — sent={sent}/{len(email_labels)}")
    return sent


def _build_reminder_html(missing_labels: list[str]) -> str:
    """Return the HTML body for a missing-picks reminder email."""
    items_html = "".join(
        f"<li style='padding:6px 0;color:#334155;font-size:14px;'>{lbl}</li>"
        for lbl in missing_labels
    )
    return (
        "<!DOCTYPE html>"
        "<html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "</head><body style='margin:0;padding:0;background:#f1f5f9;'>"
        "<div style='max-width:540px;margin:32px auto;background:#fff;"
        "     border-radius:12px;overflow:hidden;font-family:sans-serif;"
        "     box-shadow:0 4px 24px rgba(0,0,0,.08);'>"
        # Header
        "  <div style='background:#0f172a;padding:28px 32px;text-align:center;'>"
        "    <p style='margin:0;color:#f97316;font-size:28px;font-weight:900;"
        "       letter-spacing:-0.5px;'>🏀 NBA Playoff Predictor</p>"
        "  </div>"
        # Body
        "  <div style='padding:28px 32px;'>"
        "    <h2 style='margin:0 0 8px;color:#0f172a;font-size:20px;'>"
        "      Don't leave points on the table!"
        "    </h2>"
        "    <p style='color:#475569;margin:0 0 16px;font-size:14px;'>"
        "      You still have open matchups waiting for your picks — lock them in"
        "      before the games tip off and you lose your chance to score!"
        "    </p>"
        f"   <ul style='margin:0 0 20px;padding-left:20px;'>{items_html}</ul>"
        "    <a href='https://nba-playoffs-2026.vercel.app/playoffs'"
        "       style='display:inline-block;padding:13px 32px;"
        "              background:#f97316;color:#fff;border-radius:8px;"
        "              text-decoration:none;font-weight:700;font-size:15px;'>"
        "      Make My Picks &rarr;"
        "    </a>"
        "  </div>"
        # Footer
        "  <div style='background:#f8fafc;padding:16px 32px;border-top:1px solid #e2e8f0;'>"
        "    <p style='margin:0;color:#94a3b8;font-size:11px;'>"
        "      You're receiving this because you have an account on"
        "      <a href='https://nba-playoffs-2026.vercel.app'"
        "         style='color:#94a3b8;'>NBA Playoff Predictor 2026</a>."
        "    </p>"
        "  </div>"
        "</div>"
        "</body></html>"
    )


def _gmail_send_email(to: str, subject: str, html: str) -> None:
    """
    Send a single transactional email via the Gmail REST API using OAuth2.
    This bypasses SMTP entirely — the request goes over HTTPS (port 443)
    which Railway never blocks.

    Auth flow (service-account-free, no interactive browser needed):
      1. Build a google.oauth2.credentials.Credentials object from the stored
         client_id / client_secret / refresh_token.
      2. The google-auth library auto-exchanges the refresh_token for a short-
         lived access_token on the first API call.
      3. Build the Gmail API service and call users.messages.send().

    Required Railway env vars:
      GMAIL_CLIENT_ID      — OAuth2 client ID from Google Cloud Console
      GMAIL_CLIENT_SECRET  — OAuth2 client secret
      GMAIL_REFRESH_TOKEN  — long-lived refresh token (generate once with
                             tools/generate_gmail_token.py)
      GMAIL_SENDER         — sending address (default: nbaplayoffpredictor2000@gmail.com)
    """
    import base64
    from email.mime.multipart import MIMEMultipart
    from email.mime.text      import MIMEText

    from google.oauth2.credentials  import Credentials
    from googleapiclient.discovery  import build
    from googleapiclient.errors     import HttpError

    if not _GMAIL_CLIENT_ID or not _GMAIL_CLIENT_SECRET or not _GMAIL_REFRESH_TOKEN:
        raise RuntimeError(
            "Gmail API credentials not set — add GMAIL_CLIENT_ID, "
            "GMAIL_CLIENT_SECRET, and GMAIL_REFRESH_TOKEN to Railway env vars"
        )

    print(f"[Gmail] Sending to={to!r} from={_GMAIL_SENDER!r} "
          f"client_id_prefix={_GMAIL_CLIENT_ID[:12]}...")

    # ── Stage 1: build credentials + service ────────────────────────────────
    from google.auth.exceptions import RefreshError, TransportError
    try:
        creds = Credentials(
            token=None,                               # fetched automatically via refresh
            refresh_token=_GMAIL_REFRESH_TOKEN,
            client_id=_GMAIL_CLIENT_ID,
            client_secret=_GMAIL_CLIENT_SECRET,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=["https://www.googleapis.com/auth/gmail.send"],
        )
        service = build("gmail", "v1", credentials=creds)
        print("[Gmail] Stage 1 OK — credentials + service built")
    except RefreshError as exc:
        raise RuntimeError(
            f"[Gmail] Stage 1 FAILED — token refresh error. "
            f"The refresh token may have been revoked; re-run "
            f"tools/generate_gmail_token.py to generate a new one. "
            f"Detail: {exc}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            f"[Gmail] Stage 1 FAILED — could not build Gmail service: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    # ── Stage 2: compose message ─────────────────────────────────────────────
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"NBA Playoff Predictor <{_GMAIL_SENDER}>"
    msg["To"]      = to
    msg.attach(MIMEText(html, "html", "utf-8"))

    # Gmail API requires base64url encoding of the raw RFC-2822 bytes
    raw_b64 = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    print("[Gmail] Stage 2 OK — message encoded")

    # ── Stage 3: send via API ────────────────────────────────────────────────
    try:
        result = (
            service.users()
                   .messages()
                   .send(userId="me", body={"raw": raw_b64})
                   .execute()
        )
        print(f"[Gmail] ✓ email delivered — message id={result.get('id')} to={to!r}")
    except HttpError as exc:
        status = exc.resp.status
        # 429 = quota exceeded; 401/403 = auth/scope problem
        if status == 429:
            raise RuntimeError(
                f"[Gmail] Stage 3 FAILED — Gmail API quota exceeded (HTTP 429). "
                f"Wait a few minutes and retry. Detail: {exc.error_details}"
            ) from exc
        if status in (401, 403):
            raise RuntimeError(
                f"[Gmail] Stage 3 FAILED — authorization error (HTTP {status}). "
                f"Ensure the Gmail API is enabled in Google Cloud Console and "
                f"the OAuth scope includes 'gmail.send'. Detail: {exc.error_details}"
            ) from exc
        raise RuntimeError(
            f"[Gmail] Stage 3 FAILED — Gmail API HTTP {status}: {exc.error_details}"
        ) from exc
    except TransportError as exc:
        raise RuntimeError(
            f"[Gmail] Stage 3 FAILED — network error reaching Gmail API: {exc}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            f"[Gmail] Stage 3 FAILED — unexpected error: {type(exc).__name__}: {exc}"
        ) from exc


def _send_daily_email_reminders() -> dict:
    """
    Daily cron job (and admin-triggered): send per-user Gmail API email reminders
    to users with incomplete predictions for matchups that haven't started yet.

    • Only includes series with home_wins + away_wins = 0 (game not yet tipped off)
    • Only includes play-in games with winner_id IS NULL
    • Skips users alerted within the last 20 hours (reminder_last_sent_at dedup)
    • Updates reminder_last_sent_at per user after a successful send
    Returns a summary dict.
    """
    if datetime.utcnow() >= _EMAIL_REMINDER_CUTOFF:
        return {"skipped": "past cutoff"}

    if not _GMAIL_CLIENT_ID or not _GMAIL_CLIENT_SECRET or not _GMAIL_REFRESH_TOKEN:
        print("[EmailReminder] Gmail API credentials not set — skipping")
        return {"skipped": "no gmail credentials"}

    conn = None
    sent = 0
    skipped_no_picks = 0
    errors = []

    try:
        conn = get_db_conn()
        c = conn.cursor()

        # ── 1. Open series: active (unlocked) + not yet completed ────────
        # status = 'active' means picks are still open; no need to also
        # filter on home_wins + away_wins = 0 (that would skip series
        # where a game has been played but the series is still unlocked).
        c.execute("""
            SELECT s.id, ht.name, at.name, s.round
            FROM series s
            JOIN teams ht ON s.home_team_id = ht.id
            JOIN teams at ON s.away_team_id = at.id
            WHERE s.season = '2026'
              AND s.status = 'active'
        """)
        open_series = c.fetchall()   # (id, home_name, away_name, round)

        # ── 2. Open play-in games: not yet decided ────────────────────────
        c.execute("""
            SELECT pg.id, ht.name, at.name
            FROM playin_games pg
            JOIN teams ht ON ht.id = pg.team1_id
            JOIN teams at ON at.id = pg.team2_id
            WHERE pg.season = '2026'
              AND pg.winner_id IS NULL
              AND pg.status = 'active'
        """)
        open_playin = c.fetchall()   # (id, team1_name, team2_name)

        if not open_series and not open_playin:
            print("[EmailReminder] No open matchups — nothing to remind")
            conn.close()
            return {"sent": 0, "reason": "no open matchups"}

        open_series_ids = [r[0] for r in open_series]
        open_playin_ids = [r[0] for r in open_playin]
        series_label    = {r[0]: f"{r[1]} vs {r[2]} ({r[3]})" for r in open_series}
        playin_label    = {r[0]: f"{r[1]} vs {r[2]} (Play-In)" for r in open_playin}

        # ── 3. Eligible users: missing picks + 20-hour dedup ─────────────
        cutoff_20h = datetime.utcnow() - timedelta(hours=20)
        c.execute("""
            SELECT DISTINCT u.id, u.email
            FROM users u
            WHERE u.email IS NOT NULL
              AND u.email != ''
              AND (u.reminder_opt_out IS NULL OR u.reminder_opt_out = FALSE)
              AND (u.reminder_last_sent_at IS NULL OR u.reminder_last_sent_at < %s)
              AND (
                EXISTS (
                    SELECT 1 FROM series s
                    WHERE s.id = ANY(%s)
                      AND NOT EXISTS (
                          SELECT 1 FROM predictions p
                          WHERE p.user_id = u.id AND p.series_id = s.id
                      )
                )
                OR EXISTS (
                    SELECT 1 FROM playin_games pg
                    WHERE pg.id = ANY(%s)
                      AND NOT EXISTS (
                          SELECT 1 FROM playin_predictions pp
                          WHERE pp.user_id = u.id AND pp.game_id = pg.id
                      )
                )
              )
        """, (cutoff_20h, open_series_ids or [0], open_playin_ids or [0]))
        eligible_users = c.fetchall()

        if not eligible_users:
            print("[EmailReminder] All eligible users already reminded recently — skipping")
            conn.close()
            return {"sent": 0, "reason": "all deduped"}

        print(f"[EmailReminder] Sending to {len(eligible_users)} user(s) via Gmail API")

        subject = "Don't leave points on the table! 🏀 Your NBA Playoff predictions are incomplete."

        for user_id, email in eligible_users:
            # Per-user missing matchup lists
            c.execute("""
                SELECT id FROM series
                WHERE id = ANY(%s)
                  AND NOT EXISTS (
                      SELECT 1 FROM predictions p
                      WHERE p.user_id = %s AND p.series_id = series.id
                  )
            """, (open_series_ids or [0], user_id))
            missing_series_ids = [r[0] for r in c.fetchall()]

            c.execute("""
                SELECT id FROM playin_games
                WHERE id = ANY(%s)
                  AND NOT EXISTS (
                      SELECT 1 FROM playin_predictions pp
                      WHERE pp.user_id = %s AND pp.game_id = playin_games.id
                  )
            """, (open_playin_ids or [0], user_id))
            missing_playin_ids = [r[0] for r in c.fetchall()]

            missing_labels = (
                [series_label[sid] for sid in missing_series_ids if sid in series_label] +
                [playin_label[pid] for pid in missing_playin_ids if pid in playin_label]
            )

            if not missing_labels:
                skipped_no_picks += 1
                continue

            try:
                _gmail_send_email(email, subject, _build_reminder_html(missing_labels))
                c.execute(
                    "UPDATE users SET reminder_last_sent_at = %s WHERE id = %s",
                    (datetime.utcnow(), user_id),
                )
                conn.commit()
                sent += 1
                print(f"[EmailReminder] ✓ user {user_id} → {email} "
                      f"({len(missing_labels)} matchup(s))")
            except Exception as e:
                errors.append(f"user {user_id} ({email}): {e}")
                print(f"[EmailReminder] ✗ user {user_id}: {e}")

        print(f"[EmailReminder] Done — sent={sent} "
              f"skipped_no_picks={skipped_no_picks} errors={len(errors)}")
        return {"sent": sent, "skipped_no_picks": skipped_no_picks, "errors": errors}

    except Exception as e:
        print(f"[EmailReminder] Fatal error: {type(e).__name__}: {e}")
        return {"sent": sent, "error": str(e)}
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

    # ── Source 3: ESPN public API (no key, same format as Primary) ──
    if fresh is None:
        try:
            print("[Standings] Trying ESPN public API (no key required)")
            fresh       = _fetch_standings_from_espn_direct()
            used_source = "espn_direct"
            print("[Standings] ✓ Source: ESPN direct")
        except Exception as _espn_err:
            print(f"[Standings] ESPN direct failed ({type(_espn_err).__name__}: "
                  f"{str(_espn_err)[:200]}) — trying stats.nba.com")

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
            # Auto-generate/update First Round matchups from fresh standings
            # (safety guard inside generate_matchups skips if any series is not 'active')
            try:
                generate_matchups()
            except Exception as _gme:
                print(f"[Standings] generate_matchups failed (non-fatal): {_gme}")
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
            per_mode_detailed='PerGame',
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

def sync_daily_boxscores(date_str: str | None = None, season: str = '2026',
                         force: bool = False, triggered_by: str = 'auto') -> dict:
    """
    Fetch completed NBA games for a given date, pull full player boxscores
    from the ESPN public summary API, and upsert into player_game_stats.

    Also back-fills espn_player_id on existing player_stats rows via name match.

    Args:
        date_str:     'YYYY-MM-DD' or 'YYYYMMDD'.  Defaults to yesterday UTC.
        season:       Season tag stored on every row (default '2026').
        force:        If True, bypass the freshness TTL gate (used by admin/daily-sync).
        triggered_by: Label used in logs — 'daily_auto', 'user_refresh', 'admin', etc.

    Returns a summary dict:
      { date, games_found, games_processed, players_upserted, espn_id_updates,
        errors, skipped, skip_reason }
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
        'skipped': False, 'skip_reason': None, 'triggered_by': triggered_by,
    }

    # ── Freshness gate — skip if recently synced for this date ────────────────
    if not force:
        _last = _boxscore_last_sync.get(date_iso)
        if _last is not None:
            age_min = (datetime.utcnow() - _last).total_seconds() / 60
            if age_min < BOXSCORE_TTL_MINUTES:
                summary['skipped']     = True
                summary['skip_reason'] = f"fresh_cache ({age_min:.1f}m < {BOXSCORE_TTL_MINUTES}m TTL)"
                print(f"[Boxscore] [{triggered_by}] Skipping {date_iso} — "
                      f"synced {age_min:.1f}m ago (TTL={BOXSCORE_TTL_MINUTES}m)")
                return summary

    print(f"[Boxscore] [{triggered_by}] Starting sync for {date_iso}")

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
            print(f"[Boxscore] Secondary scoreboard failed: {e} — trying ESPN direct")
            # ── Step 1c: ESPN public scoreboard — no API key required ──────────
            try:
                print(f"[Boxscore] Step 1c: scoreboard via ESPN public API ({date_fmt})")
                resp_espn = _http.get(
                    _ESPN_SCOREBOARD_URL2,
                    params={"dates": date_fmt, "limit": 20},
                    timeout=12,
                )
                resp_espn.raise_for_status()
                espn_data   = resp_espn.json()
                espn_events = espn_data.get("events") or []
                for ev in espn_events:
                    comps  = ev.get("competitions") or [{}]
                    comp   = comps[0]
                    teams  = comp.get("competitors") or []
                    home_c = next((c for c in teams if c.get("homeAway") == "home"), {})
                    away_c = next((c for c in teams if c.get("homeAway") == "away"), {})
                    def _tm_espn(c):
                        t = c.get("team") or {}
                        return {"id": t.get("id"), "abbr": t.get("abbreviation"),
                                "name": t.get("displayName") or t.get("name"),
                                "score": c.get("score"), "winner": bool(c.get("winner"))}
                    stype_e = (ev.get("status") or {}).get("type") or {}
                    normalized_events.append({
                        "id":        str(ev.get("id", "")),
                        "completed": bool(stype_e.get("completed")),
                        "status":    stype_e.get("description") or stype_e.get("name"),
                        "clock":     (ev.get("status") or {}).get("displayClock"),
                        "period":    (ev.get("status") or {}).get("period"),
                        "home":      _tm_espn(home_c),
                        "away":      _tm_espn(away_c),
                        "broadcast": comp.get("broadcast") or "",
                    })
                scoreboard_source = "espn_direct"
                print(f"[Boxscore] ESPN direct: {len(espn_events)} events")
            except Exception as e2:
                summary['errors'].append(f"Scoreboard fetch failed (all 3 sources): {e2}")
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

    # Build accent-normalized name → player_id lookup so step-4a can match
    # "Luka Doncic" (ESPN) to "Luka Dončić" (nba_api) without creating duplicates.
    _norm_name_to_pid: dict = {}
    try:
        c.execute("SELECT player_id, player_name FROM player_stats WHERE season = %s", (season,))
        for _pid_r, _pname_r in c.fetchall():
            _key = _normalize_name(_pname_r)
            if _key and _key not in _norm_name_to_pid:
                _norm_name_to_pid[_key] = _pid_r
    except Exception as _norm_err:
        print(f"[Boxscore] Warn: could not build norm-name lookup: {_norm_err}")

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

                    # 4a: match by accent-normalized name (handles "Doncic" ↔ "Dončić")
                    _pname_norm = _normalize_name(pname)
                    existing_pid = _norm_name_to_pid.get(_pname_norm)
                    if existing_pid is not None:
                        c.execute('''
                            UPDATE player_stats
                            SET espn_player_id = %s
                            WHERE player_id = %s
                              AND (espn_player_id IS NULL OR espn_player_id != %s)
                        ''', (espn_pid_int, existing_pid, espn_pid_int))
                        name_matched = c.rowcount
                        if name_matched == 0:
                            name_matched = 1  # row exists, just espn_id already set
                    else:
                        name_matched = 0

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

    # ── Commit boxscore data NOW before Step 5 so a Step 5 failure can't
    # roll back the inserts we just did. ──────────────────────────────────────
    conn.commit()

    # ── Step 5: Recompute per-game averages from player_game_stats ──────────
    # Match by espn_player_id first; fall back to player name so rows that
    # came from _sync_player_stats_job() (NBA API, no espn_player_id) also
    # get their PPG updated.
    try:
        c.execute(f'''
            UPDATE player_stats ps
            SET pts_per_game  = sub.avg_pts,
                ast_per_game  = sub.avg_ast,
                reb_per_game  = sub.avg_reb,
                stl_per_game  = sub.avg_stl,
                blk_per_game  = sub.avg_blk,
                fg3m_per_game = sub.avg_fg3m,
                games_played  = sub.gp
            FROM (
                SELECT espn_player_id,
                       LOWER(player_name)                     AS lname,
                       COUNT(*)                               AS gp,
                       ROUND(AVG(points)::numeric,  1)        AS avg_pts,
                       ROUND(AVG(assists)::numeric, 1)        AS avg_ast,
                       ROUND(AVG(rebounds)::numeric,1)        AS avg_reb,
                       ROUND(AVG(steals)::numeric,  1)        AS avg_stl,
                       ROUND(AVG(blocks)::numeric,  1)        AS avg_blk,
                       ROUND(AVG(fg3m)::numeric,    1)        AS avg_fg3m
                FROM player_game_stats
                WHERE season = %s
                GROUP BY espn_player_id, LOWER(player_name)
            ) sub
            WHERE ps.season = %s
              AND (
                  ps.espn_player_id = sub.espn_player_id
                  OR LOWER(ps.player_name) = sub.lname
              )
        ''', (season, season))
        updated_rows = c.rowcount
        print(f"[Boxscore] ✓ Recomputed per-game averages for {updated_rows} players")
    except Exception as _avg_err:
        print(f"[Boxscore] ⚠ Average recompute failed (non-critical): {type(_avg_err).__name__}: {_avg_err}")
        try: conn.rollback()
        except Exception: pass

    try:
        conn.commit()  # commit the averages update (if it succeeded)
    except Exception:
        try: conn.rollback()
        except Exception: pass

    # ── Step 6: Auto-update series leaders from player_game_stats ────────────
    # For each active playoff series, recompute leading scorer / rebounder /
    # assister by summing stats from player_game_stats for both teams, starting
    # from game1_start_time so earlier-round games aren't double-counted.
    try:
        c.execute("""
            SELECT s.id,
                   ht.abbreviation AS home_abbr,
                   at.abbreviation AS away_abbr,
                   COALESCE(DATE(s.game1_start_time), %s::date) AS series_start
            FROM series s
            JOIN teams ht ON ht.id = s.home_team_id
            JOIN teams at ON at.id = s.away_team_id
            WHERE s.season = %s AND s.status = 'active'
        """, ('2026-04-18', season))
        active_series = c.fetchall()

        for sid, home_abbr, away_abbr, series_start in active_series:
            c.execute("""
                SELECT player_name,
                       SUM(points)   AS total_pts,
                       SUM(rebounds) AS total_reb,
                       SUM(assists)  AS total_ast
                FROM player_game_stats
                WHERE season = %s
                  AND game_date >= %s
                  AND team_abbr IN (%s, %s)
                GROUP BY player_name
                ORDER BY total_pts DESC  -- tiebreaker: higher scorer wins
            """, (season, series_start, home_abbr, away_abbr))
            rows = c.fetchall()
            if not rows:
                continue
            # stable max: ORDER BY pts DESC means ties go to the higher scorer
            scorer    = max(rows, key=lambda r: r[1] or 0)[0]
            rebounder = max(rows, key=lambda r: r[2] or 0)[0]
            assister  = max(rows, key=lambda r: r[3] or 0)[0]
            c.execute("""
                UPDATE series SET
                    actual_leading_scorer    = %s,
                    actual_leading_rebounder = %s,
                    actual_leading_assister  = %s
                WHERE id = %s
            """, (scorer, rebounder, assister, sid))

        conn.commit()
        print(f"[Boxscore] ✓ Updated leaders for {len(active_series)} active series")
    except Exception as _leaders_err:
        print(f"[Boxscore] ⚠ Series leaders update failed (non-critical): {type(_leaders_err).__name__}: {_leaders_err}")
        try: conn.rollback()
        except Exception: pass

    conn.close()
    # Record successful sync timestamp so TTL gate can skip redundant calls
    _boxscore_last_sync[date_iso] = datetime.utcnow()
    print(f"[Boxscore] [{triggered_by}] ✓ {date_iso} — "
          f"{summary['games_processed']} games, "
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
                    # No row yet — insert it (include start_time from schedule)
                    st = PLAYIN_SCHEDULE_UTC.get((conf_full, game_type))
                    c.execute(
                        """INSERT INTO playin_games
                               (season, conference, game_type,
                                team1_id, team1_seed, team2_id, team2_seed, status, start_time)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, 'active', %s)""",
                        (season, conf_full, game_type,
                         t1['team_id'], s1, t2['team_id'], s2, st)
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


def _should_live_sync(season: str = "2026") -> bool:
    """
    Return True if a live sync should fire now.
    Conditions:
      1. Cooldown has elapsed (>_LIVE_SYNC_COOLDOWN seconds since last sync).
      2. At least one play-in or playoff game is active AND its start_time is
         in the past (game may have finished but DB hasn't been updated yet).
    """
    import time as _time
    global _live_sync_last
    if _time.time() - _live_sync_last < _LIVE_SYNC_COOLDOWN:
        return False
    try:
        conn = get_db_conn()
        c = conn.cursor()
        now_utc = datetime.utcnow()
        # Any active play-in game whose start_time has passed?
        c.execute('''SELECT 1 FROM playin_games
                     WHERE season = %s AND status = 'active'
                       AND start_time IS NOT NULL AND start_time <= %s
                     LIMIT 1''', (season, now_utc))
        has_live_playin = c.fetchone() is not None
        # Any active playoff series (once R1 starts)?
        c.execute('''SELECT 1 FROM series
                     WHERE season = %s AND status = 'active'
                     LIMIT 1''', (season,))
        has_active_series = c.fetchone() is not None
        # Completed play-in game(s) whose 7-seed/8-seed R1 series hasn't been created yet?
        c.execute('''SELECT 1 FROM playin_games p
                     WHERE p.season = %s AND p.status = 'completed'
                       AND p.winner_id IS NOT NULL
                       AND NOT EXISTS (
                           SELECT 1 FROM series s
                           WHERE s.season = %s AND s.conference = p.conference
                             AND s.round = 'First Round'
                             AND (s.home_team_id = p.winner_id OR s.away_team_id = p.winner_id)
                       )
                     LIMIT 1''', (season, season))
        missing_r1_series = c.fetchone() is not None
        conn.close()
        return has_live_playin or has_active_series or missing_r1_series
    except Exception as e:
        print(f"[LiveSync] _should_live_sync check error: {e}")
        return False


def _run_live_sync_bg(season: str = "2026"):
    """
    Non-blocking full sync chain called as a background task.
    Acquires a lock so only one sync runs at a time.
    Updates _live_sync_last after completion.
    """
    import time as _time
    global _live_sync_last
    if not _live_sync_lock.acquire(blocking=False):
        return   # another sync already running — skip
    try:
        print(f"[LiveSync] Background sync triggered for season={season}")
        from game_processor import (
            sync_playin_results_from_api,
            sync_playoff_results_from_api,
            sync_series_provisional_leaders,
        )

        # Play-In results + bracket promotion
        try:
            pi = sync_playin_results_from_api(season)
            print(f"[LiveSync] Play-In — processed={pi.get('processed',0)} "
                  f"promoted={pi.get('promoted',0)} errors={len(pi.get('errors',[]))}")
        except Exception as e:
            print(f"[LiveSync] Play-In ERROR: {type(e).__name__}: {e}")

        # Bracket gap-filler: ensure all completed play-in games have R1 series
        try:
            conn = get_db_conn()
            c = conn.cursor()
            c.execute('''SELECT id, winner_id FROM playin_games
                         WHERE season = %s AND status = 'completed' AND winner_id IS NOT NULL''',
                      (season,))
            for gid, wid in c.fetchall():
                _try_create_r1_from_playin(c, gid, wid, season)
            _try_create_playin_game3(c, season)
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[LiveSync] Bracket gap-filler ERROR: {type(e).__name__}: {e}")

        # Playoff results + series advancement
        try:
            po = sync_playoff_results_from_api(season)
            print(f"[LiveSync] Playoff — updated={po.get('updated',0)} "
                  f"completed={po.get('completed',0)} errors={len(po.get('errors',[]))}")
        except Exception as e:
            print(f"[LiveSync] Playoff ERROR: {type(e).__name__}: {e}")

        # DB-driven backfill — scores any predictions the API steps may have missed
        try:
            pi_bf = _backfill_playin_scores(season)
            s_bf  = _backfill_series_scores(season)
            if pi_bf.get('rows_scored', 0) or s_bf.get('rows_scored', 0):
                print(f"[LiveSync] Backfill — "
                      f"playin_rows={pi_bf['rows_scored']} series_rows={s_bf['rows_scored']}")
        except Exception as e:
            print(f"[LiveSync] Backfill ERROR: {type(e).__name__}: {e}")

        _live_sync_last = _time.time()
        print(f"[LiveSync] Done — cooldown reset")
    finally:
        _live_sync_lock.release()


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

        # Only regenerate the middle-seed (3v6, 4v5) matchups.
        # Play-in winner series (1v8, 2v7) are created separately by
        # _try_create_r1_from_playin and must NOT be touched here.
        need_series = not expected.issubset(existing_r1)
        need_playin = (playin_count < 2)

        # Safety: don't auto-regenerate if any First Round series is no longer active
        if need_series and not force_conference:
            c.execute('''SELECT COUNT(*) FROM series WHERE season = %s AND conference = %s
                         AND round = 'First Round' AND status != 'active' ''', ('2026', conf_full))
            if c.fetchone()[0] > 0:
                print(f"  -> {conf_full} has locked/completed R1 series — skipping auto-regeneration")
                need_series = False

        # Safety: don't wipe series if ANY R1 series has user predictions
        # (covers 3v6/4v5 now AND 1v8/2v7 once play-in winners are picked)
        if need_series and not force_conference:
            c.execute('''SELECT COUNT(*) FROM predictions p
                         JOIN series s ON s.id = p.series_id
                         WHERE s.season = %s AND s.conference = %s AND s.round = 'First Round' ''',
                      ('2026', conf_full))
            if c.fetchone()[0] > 0:
                print(f"  -> {conf_full} R1 series have user predictions — skipping regeneration to protect picks")
                need_series = False

        if not need_series and not need_playin and not force_conference:
            print(f"  -> {conf_full} already matches current standings, skipping")
            continue

        if need_series or force_conference:
            # Only delete 3v6 and 4v5 series that have NO user predictions.
            # Series with picks are NEVER deleted, regardless of force flag —
            # this is the last line of defence so picks can never be lost.
            c.execute('''SELECT id FROM series
                         WHERE season = %s AND conference = %s AND round = 'First Round'
                           AND home_seed NOT IN (1, 2) AND away_seed NOT IN (7, 8)
                           AND id NOT IN (SELECT DISTINCT series_id FROM predictions)''',
                      ('2026', conf_full))
            old_ids = [r[0] for r in c.fetchall()]
            if old_ids:
                # Double-check: no predictions exist on these ids (belt-and-suspenders)
                c.execute("DELETE FROM predictions WHERE series_id = ANY(%s)", (old_ids,))
                c.execute('''DELETE FROM series WHERE id = ANY(%s)''', (old_ids,))
                print(f"  -> Deleted {len(old_ids)} empty R1 series for {conf_full}")
            # Log any series that were skipped because they had predictions
            c.execute('''SELECT id FROM series
                         WHERE season = %s AND conference = %s AND round = 'First Round'
                           AND home_seed NOT IN (1, 2) AND away_seed NOT IN (7, 8)
                           AND id IN (SELECT DISTINCT series_id FROM predictions)''',
                      ('2026', conf_full))
            protected = [r[0] for r in c.fetchall()]
            if protected:
                print(f"  -> Kept {len(protected)} R1 series with predictions (protected from deletion)")
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
                st = PLAYIN_SCHEDULE_UTC.get((conf_full, game_type))
                c.execute('''INSERT INTO playin_games (season, conference, game_type, team1_id, team1_seed,
                            team2_id, team2_seed, status, start_time) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                         ('2026', conf_full, game_type,
                          teams[idx1]['team_id'], teams[idx1]['conf_rank'],
                          teams[idx2]['team_id'], teams[idx2]['conf_rank'], 'active', st))
                print(f"  -> Play-In {game_type}: #{teams[idx1]['conf_rank']} {teams[idx1]['team_name']} vs #{teams[idx2]['conf_rank']} {teams[idx2]['team_name']}")
            print(f"  Created {conf_full} play-in games")

    conn.commit()
    conn.close()
    print("generate_matchups complete")
    _backfill_game1_start_times()

# Play-In game start times (UTC). Bets close when server time >= start_time.
# Schedule: Tue Apr 15 & Wed Apr 16 (phase 1), Fri Apr 18 (elimination).
# ET is UTC-4 (EDT); Jerusalem IDT is UTC+3 — display on frontend as +3.
PLAYIN_SCHEDULE_UTC = {
    ('Eastern', '7v8'):         '2026-04-15 23:30:00',  # Tue 7:30 PM ET
    ('Western', '7v8'):         '2026-04-16 02:00:00',  # Tue 10:00 PM ET
    ('Eastern', '9v10'):        '2026-04-16 23:30:00',  # Wed 7:30 PM ET
    ('Western', '9v10'):        '2026-04-17 02:00:00',  # Wed 10:00 PM ET
    ('Eastern', 'elimination'): '2026-04-18 23:30:00',  # Fri 7:30 PM ET
    ('Western', 'elimination'): '2026-04-19 02:00:00',  # Fri 10:00 PM ET
}

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

def _backfill_playin_start_times():
    """Set start_time on any existing play-in game rows that have it as NULL."""
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT id, conference, game_type FROM playin_games WHERE start_time IS NULL")
    rows = c.fetchall()
    for row_id, conf, game_type in rows:
        st = PLAYIN_SCHEDULE_UTC.get((conf, game_type))
        if st:
            c.execute("UPDATE playin_games SET start_time = %s WHERE id = %s", (st, row_id))
            print(f"  Backfilled start_time={st} for playin_game id={row_id} ({conf} {game_type})")
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
            ["LOWER(team_name) LIKE %s" for _ in _ALLSTAR_KEYWORDS]
        )
        like_params = tuple(f"%{kw}%" for kw in _ALLSTAR_KEYWORDS)
        c.execute(f"""
            DELETE FROM cached_standings
            WHERE {like_clauses}
               OR conference NOT IN ('East', 'West')
               OR team_name IS NULL
               OR team_name = ''
        """, like_params)
        deleted = c.rowcount
        conn.commit()
        conn.close()
        if deleted:
            print(f"[Startup] Removed {deleted} All-Star/null rows from cached_standings")
    except Exception as e:
        print(f"[Startup] cleanup cached_standings (non-fatal): {e}")


def _apply_series_migration():
    """Ensure manual_override + game1_start_time columns exist on series table (idempotent)."""
    try:
        conn = get_db_conn()
        conn.autocommit = True
        c = conn.cursor()
        c.execute("SET search_path TO public")
        for col, defn in [
            ("manual_override",   "BOOLEAN DEFAULT FALSE"),
            ("game1_start_time",  "TEXT"),
        ]:
            try:
                c.execute(f"ALTER TABLE series ADD COLUMN IF NOT EXISTS {col} {defn}")
                print(f"Migration: ensured series.{col} exists")
            except Exception as col_err:
                print(f"Migration: could not add series.{col}: {col_err}")
        conn.close()
    except Exception as e:
        print(f"Series migration connection error (non-fatal): {e}")


# Game 1 start times for First Round 2026 (UTC ISO strings).
# Key: (conference, home_seed, away_seed)  — home = better seed per generate_matchups()
_GAME1_SCHEDULE_UTC: dict[tuple, str] = {
    # Saturday April 18
    ('Eastern', 4, 5): '2026-04-18T17:00:00Z',   # CLE vs TOR   1:00 PM ET  → 20:00 IDT
    ('Western', 3, 6): '2026-04-18T19:30:00Z',   # DEN vs MIN   3:30 PM ET  → 22:30 IDT
    ('Eastern', 3, 6): '2026-04-18T22:00:00Z',   # NYK vs ATL   6:00 PM ET  → 01:00 IDT Apr 19
    ('Western', 4, 5): '2026-04-19T00:30:00Z',   # LAL vs HOU   8:30 PM ET  → 03:30 IDT Apr 19
    # Sunday April 19
    ('Eastern', 2, 7): '2026-04-19T17:00:00Z',   # BOS vs #7    1:00 PM ET  → 20:00 IDT
    ('Western', 1, 8): '2026-04-19T19:30:00Z',   # OKC vs #8    3:30 PM ET  → 22:30 IDT
    ('Eastern', 1, 8): '2026-04-19T22:30:00Z',   # DET vs #8    6:30 PM ET  → 01:30 IDT Apr 20
    ('Western', 2, 7): '2026-04-20T01:00:00Z',   # SAS vs #7    9:00 PM ET  → 04:00 IDT Apr 20
}

# Futures + leaders bets lock when the very first First Round game tips off
FUTURES_LOCK_UTC = '2026-04-18T17:00:00Z'   # CLE vs TOR — earliest Game 1


def _backfill_game1_start_times(season: str = '2026', force: bool = False):
    """Sync game1_start_time on First Round series from the canonical schedule.

    By default only fills NULL entries.  Pass force=True to overwrite any
    value that was NOT manually set (manual_override IS NOT TRUE) — this
    corrects wrong times that an admin accidentally entered.
    """
    try:
        conn = get_db_conn()
        c = conn.cursor()
        if force:
            c.execute("""SELECT id, conference, home_seed, away_seed
                         FROM series
                         WHERE season=%s AND round='First Round'
                           AND (manual_override IS NOT TRUE)""",
                      (season,))
        else:
            c.execute("""SELECT id, conference, home_seed, away_seed
                         FROM series
                         WHERE season=%s AND round='First Round'
                           AND game1_start_time IS NULL""",
                      (season,))
        updated = 0
        for sid, conf, hs, aws in c.fetchall():
            t = _GAME1_SCHEDULE_UTC.get((conf, hs, aws))
            if t:
                c.execute("UPDATE series SET game1_start_time=%s WHERE id=%s", (t, sid))
                updated += 1
        conn.commit()
        conn.close()
        print(f"[Schedule] game1_start_time synced on {updated} First Round series (force={force})")
        return updated
    except Exception as e:
        print(f"[Schedule] _backfill_game1_start_times error: {e}")
        return 0


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
        # Warm up the connection pool immediately so the first user request
        # does not pay the pool-creation + connection-handshake cost.
        _init_db_pool()
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

    # Backfill start_time for existing play-in games that don't have one yet
    try:
        _backfill_playin_start_times()
    except Exception as e:
        print(f"ERROR _backfill_playin_start_times: {e}")

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

    # Supabase Storage diagnostic — log key presence so upload failures are easy to diagnose
    if _SUPABASE_SERVICE_ROLE_KEY:
        print(f"[Supabase] Service role key configured ({len(_SUPABASE_SERVICE_ROLE_KEY)} chars) "
              f"— avatar uploads enabled (bucket: avatars at {_SUPABASE_URL})")
    else:
        print("[Supabase] WARNING: SUPABASE_SERVICE_ROLE_KEY is not set "
              "— avatar uploads will return 503. "
              "Add it in Railway → Settings → Variables.")

    # Apply series schema migration (manual_override + game1_start_time columns)
    _apply_series_migration()
    try:
        _backfill_game1_start_times(force=True)
    except Exception as e:
        print(f"ERROR _backfill_game1_start_times: {e}")

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
        # On every deploy: re-apply bracket promotions for already-completed play-in games.
        # Fixes any R1 series that were missed due to the bracket_group bug.
        try:
            conn = get_db_conn()
            c = conn.cursor()
            c.execute('''SELECT id, winner_id FROM playin_games
                         WHERE season = '2026' AND status = 'completed'
                           AND winner_id IS NOT NULL''')
            rows = c.fetchall()
            for gid, wid in rows:
                _try_create_r1_from_playin(c, gid, wid, '2026')
            _try_create_playin_game3(c, '2026')
            conn.commit()
            conn.close()
            if rows:
                print(f"[Startup] Bracket gap-filler: processed {len(rows)} completed play-in game(s)")
                # New series may have been created — remind users immediately
                threading.Thread(target=_send_daily_email_reminders, daemon=True).start()
        except Exception as e:
            print(f"[Startup] Bracket gap-filler ERROR: {e}")

        # Score any unscored predictions for completed play-in games + series.
        # Runs every restart so results processed before a deploy are never missed.
        try:
            pi_bf = _backfill_playin_scores('2026')
            if pi_bf.get('rows_scored', 0) > 0:
                print(f"[Startup] Backfill play-in: scored {pi_bf['rows_scored']} predictions "
                      f"across {pi_bf['games_checked']} games")
        except Exception as e:
            print(f"[Startup] Backfill play-in ERROR: {e}")
        try:
            s_bf = _backfill_series_scores('2026')
            if s_bf.get('rows_scored', 0) > 0:
                print(f"[Startup] Backfill series: scored {s_bf['rows_scored']} predictions "
                      f"across {s_bf['series_checked']} series")
        except Exception as e:
            print(f"[Startup] Backfill series ERROR: {e}")

    threading.Thread(target=_background_init, daemon=True).start()

    # APScheduler cron jobs
    global _scheduler
    _scheduler = BackgroundScheduler(timezone='UTC', daemon=True)

    # ── 1a) Standings-only syncs — 03:00, 06:00, 09:00 UTC (Jerusalem morning) ─
    # Extra syncs during play-in week so the leaderboard is fresh when users
    # wake up in Israel (06:00–12:00 IDT = 03:00–09:00 UTC).
    for _hr in (3, 6, 9):
        _scheduler.add_job(
            _standings_sync_job,
            CronTrigger.from_crontab(f'0 {_hr} * * *'),
            id=f'standings_sync_{_hr:02d}00',
            replace_existing=True,
            misfire_grace_time=600,
            max_instances=1,
        )
    print("[Scheduler] Added standings-only syncs at 03:00, 06:00, 09:00 UTC "
          "(06:00, 09:00, 12:00 IDT)")

    # ── 1) Full-chain sync — 04:00–09:00 UTC every hour (6x/day) ──────────────
    # Runs the complete sequence each hour during the post-game window so
    # play-in / playoff results, bracket advancements, and boxscores are
    # picked up within ~1 hour of a game finishing (games tip off ~23:30 UTC,
    # latest finishes ~05:00 UTC).  Idempotent — safe to run repeatedly.
    def _full_chain_sync():
        from game_processor import (
            sync_playin_results_from_api, sync_playoff_results_from_api,
            sync_series_provisional_leaders,
        )
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
                      f"players={bx.get('players_upserted',0)} "
                      f"errors={len(bx.get('errors',[]))}")
            except Exception as e:
                print(f"[Auto-Sync {label}] Boxscore ({_lbl}) ERROR: {type(e).__name__}: {e}")

        # Step 2 — Standings (also triggers generate_matchups + refresh_playin)
        try:
            standings_ok = _standings_sync_job()
            print(f"[Auto-Sync {label}] Standings — ok={standings_ok}")
        except Exception as e:
            print(f"[Auto-Sync {label}] Standings ERROR: {type(e).__name__}: {e}")

        # Step 3 — Aggregate series leaders from boxscores BEFORE processing results
        # so that when a series completes in step 4/5, _finalize_series() can
        # immediately score leader predictions (10 pts each) from the fresh data.
        try:
            pl = sync_series_provisional_leaders('2026')
            print(f"[Auto-Sync {label}] Leaders — updated={pl.get('series_updated',0)}")
        except Exception as e:
            print(f"[Auto-Sync {label}] Leaders ERROR: {type(e).__name__}: {e}")

        # Step 3b — Playoff Highs: auto-compute MAX single-game stat across all
        # playoff games and re-score leaders_predictions with proximity scoring.
        try:
            la = _auto_sync_leaders_actuals('2026')
            if la.get('skipped'):
                print(f"[Auto-Sync {label}] Playoff Highs — {la.get('reason','no data yet')}")
            else:
                print(f"[Auto-Sync {label}] Playoff Highs — "
                      f"pts={la.get('actual',{}).get('scorer')} "
                      f"reb={la.get('actual',{}).get('rebounds')} "
                      f"ast={la.get('actual',{}).get('assists')} "
                      f"scored={la.get('predictions_scored',0)}")
        except Exception as e:
            print(f"[Auto-Sync {label}] Playoff Highs ERROR: {type(e).__name__}: {e}")

        # Step 4 — Play-In results + bracket promotion
        try:
            pi = sync_playin_results_from_api('2026')
            print(f"[Auto-Sync {label}] Play-In — "
                  f"processed={pi.get('processed',0)} promoted={pi.get('promoted',0)} "
                  f"errors={len(pi.get('errors',[]))}")
        except Exception as e:
            print(f"[Auto-Sync {label}] Play-In ERROR: {type(e).__name__}: {e}")

        # Step 4b — Re-apply bracket promotions for all completed play-in games
        # (idempotent gap-filler in case sync missed a game earlier)
        try:
            conn = get_db_conn()
            c = conn.cursor()
            c.execute('''SELECT id, winner_id FROM playin_games
                         WHERE season = '2026' AND status = 'completed' AND winner_id IS NOT NULL''')
            completed_pi = c.fetchall()
            for gid, wid in completed_pi:
                _try_create_r1_from_playin(c, gid, wid, '2026')
            _try_create_playin_game3(c, '2026')
            conn.commit()
            conn.close()
            if completed_pi:
                print(f"[Auto-Sync {label}] Bracket re-sync — {len(completed_pi)} completed play-in game(s)")
        except Exception as e:
            print(f"[Auto-Sync {label}] Bracket re-sync ERROR: {type(e).__name__}: {e}")

        # Step 5 — Playoff results + bracket advancement + prediction scoring
        # Leaders are already computed (step 3), so _finalize_series() will
        # include leader points in the prediction scores automatically.
        try:
            po = sync_playoff_results_from_api('2026')
            print(f"[Auto-Sync {label}] Playoff — "
                  f"updated={po.get('updated',0)} completed={po.get('completed',0)} "
                  f"errors={len(po.get('errors',[]))}")
        except Exception as e:
            print(f"[Auto-Sync {label}] Playoff ERROR: {type(e).__name__}: {e}")

        # Step 6 — DB-driven backfill: score any predictions that the API-driven
        # steps missed (e.g. ESPN no longer showing old events, or prior deploy
        # lacked scoring logic).  Fast, DB-only, idempotent.
        try:
            pi_bf = _backfill_playin_scores('2026')
            s_bf  = _backfill_series_scores('2026')
            if pi_bf.get('rows_scored', 0) or s_bf.get('rows_scored', 0):
                print(f"[Auto-Sync {label}] Backfill — "
                      f"playin_rows={pi_bf['rows_scored']} series_rows={s_bf['rows_scored']}")
        except Exception as e:
            print(f"[Auto-Sync {label}] Backfill ERROR: {type(e).__name__}: {e}")

        print(f"[Auto-Sync {label}] ── complete ({datetime.utcnow().strftime('%H:%M')} UTC) ──")

    for _hr in range(4, 10):   # 04, 05, 06, 07, 08, 09 UTC
        _scheduler.add_job(
            _full_chain_sync,
            CronTrigger.from_crontab(f'0 {_hr} * * *'),
            id=f'full_chain_sync_{_hr:02d}00',
            replace_existing=True,
            misfire_grace_time=600,
            max_instances=1,
        )
    # Extra play-in / early-overnight syncs: 00:30 and 02:30 UTC
    for _hhmm, _jid in [('30 0', 'full_chain_sync_0030'), ('30 2', 'full_chain_sync_0230')]:
        _scheduler.add_job(
            _full_chain_sync,
            CronTrigger.from_crontab(f'{_hhmm} * * *'),
            id=_jid,
            replace_existing=True,
            misfire_grace_time=600,
            max_instances=1,
        )
    # Evening game-window syncs — NBA games tip off from ~17:00 UTC (1PM ET)
    # through midnight.  Fire hourly so results land within 1 hour of any game.
    # These close the previous 09:00–00:30 UTC gap (15.5 h with no cron).
    for _hr in (17, 18, 19, 20, 21, 22, 23):
        _scheduler.add_job(
            _full_chain_sync,
            CronTrigger.from_crontab(f'0 {_hr} * * *'),
            id=f'full_chain_sync_{_hr:02d}00',
            replace_existing=True,
            misfire_grace_time=600,
            max_instances=1,
        )
    print("[Scheduler] Added evening game-window syncs at "
          "17:00, 18:00, 19:00, 20:00, 21:00, 22:00, 23:00 UTC")
    print("[Scheduler] Full-chain sync scheduled at 04:00–09:00 UTC + 00:30 + 02:30 UTC (play-in window)")

    # ── 2c) Auto-lock futures + leaders at first First Round tip-off ─────────
    # Saturday April 18 17:00 UTC = CLE vs TOR 1 PM ET = 20:00 IDT
    _FUTURES_LOCK_DT = datetime(2026, 4, 18, 17, 0, 0)
    if datetime.utcnow() < _FUTURES_LOCK_DT:
        def _auto_lock_futures():
            try:
                conn = get_db_conn()
                c = conn.cursor()
                for key in ('futures_locked', 'leaders_locked'):
                    c.execute(
                        "INSERT INTO site_settings(key,value) VALUES(%s,'1') "
                        "ON CONFLICT(key) DO UPDATE SET value='1'", (key,)
                    )
                conn.commit()
                conn.close()
                print("[Scheduler] Futures + Leaders bets AUTO-LOCKED (first R1 game started)")
            except Exception as e:
                print(f"[Scheduler] auto_lock_futures error: {e}")

        _scheduler.add_job(
            _auto_lock_futures,
            DateTrigger(run_date=_FUTURES_LOCK_DT),
            id='auto_lock_futures',
            replace_existing=True,
        )
        print(f"[Scheduler] Auto-lock futures scheduled for {_FUTURES_LOCK_DT} UTC "
              f"(Apr 18 20:00 IDT)")

    # ── 2d) Futures + Leaders bet reminders — 12h, 6h, 2h before lock ──────────
    # Lock time: 2026-04-18 17:00 UTC (CLE vs TOR tipoff, IDT 20:00)
    # Each job sends push + email to users missing futures/leaders bets.
    _FUTURES_REMIND_OFFSETS = [
        (12, datetime(2026, 4, 18,  5, 0, 0)),   # 12h before → 08:00 IDT
        ( 6, datetime(2026, 4, 18, 11, 0, 0)),   #  6h before → 14:00 IDT
        ( 2, datetime(2026, 4, 18, 15, 0, 0)),   #  2h before → 18:00 IDT
    ]
    for _hrs, _remind_dt in _FUTURES_REMIND_OFFSETS:
        if _remind_dt <= datetime.utcnow():
            print(f"[Scheduler] Futures reminder {_hrs}h already past "
                  f"({_remind_dt.strftime('%Y-%m-%d %H:%M')} UTC) — skipping")
            continue
        _scheduler.add_job(
            _send_futures_bet_reminder,
            DateTrigger(run_date=_remind_dt, timezone='UTC'),
            args=[_hrs],
            id=f'futures_remind_{_hrs}h',
            replace_existing=True,
            misfire_grace_time=1800,
        )
        print(f"[Scheduler] Futures reminder {_hrs}h scheduled "
              f"@ {_remind_dt.strftime('%Y-%m-%d %H:%M')} UTC")

    # ── 3) Missing-picks push alert — 06:00 UTC = 09:00 Jerusalem (IDT) ──
    _scheduler.add_job(
        _send_missing_picks_alert,
        CronTrigger.from_crontab('0 6 * * *'),
        id='missing_picks_morning',
        replace_existing=True,
        misfire_grace_time=1800,
        max_instances=1,
    )

    # ── 4) Missing-picks push alert — 18:00 UTC = 21:00 Jerusalem (IDT) ──
    _scheduler.add_job(
        _send_missing_picks_alert,
        CronTrigger.from_crontab('0 18 * * *'),
        id='missing_picks_evening',
        replace_existing=True,
        misfire_grace_time=1800,
        max_instances=1,
    )

    # ── 5) Daily email reminders — 10:00 UTC (1 PM Israel) + 17:00 UTC (8 PM Israel) ──
    # 20-hour per-user dedup prevents double-sending within the same day.
    for _remind_hr, _remind_id in ((7, 'daily_email_reminders'), (17, 'daily_email_reminders_eve')):
        _scheduler.add_job(
            _send_daily_email_reminders,
            CronTrigger.from_crontab(f'0 {_remind_hr} * * *'),
            id=_remind_id,
            replace_existing=True,
            misfire_grace_time=1800,
            max_instances=1,
        )

    # ── 6) Play-In game reminders — 12h, 6h, 2h before each tipoff ─────────────
    # One-shot DateTrigger jobs per game × 3 intervals.
    # Targeted push + email to users missing that game's bet.
    _PLAYIN_REMIND_HOURS = [12, 6, 2]
    _now_utc = datetime.utcnow()
    for (_pi_conf, _pi_gtype), _pi_start_str in PLAYIN_SCHEDULE_UTC.items():
        _pi_start = datetime.strptime(_pi_start_str, "%Y-%m-%d %H:%M:%S")
        for _pi_hrs in _PLAYIN_REMIND_HOURS:
            _pi_remind = _pi_start - timedelta(hours=_pi_hrs)
            if _pi_remind <= _now_utc:
                print(f"[Scheduler] Play-In reminder {_pi_conf} {_pi_gtype} -{_pi_hrs}h already past "
                      f"({_pi_remind.strftime('%Y-%m-%d %H:%M')} UTC) — skipping")
                continue
            _pi_job_id = f"playin_remind_{_pi_conf.lower()}_{_pi_gtype}_{_pi_hrs}h"
            _scheduler.add_job(
                _send_playin_game_reminder,
                DateTrigger(run_date=_pi_remind, timezone='UTC'),
                args=[_pi_conf, _pi_gtype, _pi_hrs],
                id=_pi_job_id,
                replace_existing=True,
                misfire_grace_time=1800,
            )
            print(f"[Scheduler] Play-In reminder scheduled: {_pi_conf} {_pi_gtype} -{_pi_hrs}h "
                  f"@ {_pi_remind.strftime('%Y-%m-%d %H:%M')} UTC")

    # ── 7) First Round series reminders — 12h, 6h, 2h before each Game 1 ───────
    # Targeted push + email to users missing that series' prediction.
    _SERIES_REMIND_HOURS = [12, 6, 2]
    for (_sr_conf, _sr_hs, _sr_as), _sr_start_str in _GAME1_SCHEDULE_UTC.items():
        _sr_start = datetime.strptime(
            _sr_start_str.rstrip('Z').replace('T', ' '), "%Y-%m-%d %H:%M:%S"
        )
        for _sr_hrs in _SERIES_REMIND_HOURS:
            _sr_remind = _sr_start - timedelta(hours=_sr_hrs)
            if _sr_remind <= _now_utc:
                print(f"[Scheduler] Series reminder {_sr_conf} {_sr_hs}v{_sr_as} -{_sr_hrs}h already past "
                      f"({_sr_remind.strftime('%Y-%m-%d %H:%M')} UTC) — skipping")
                continue
            _sr_job_id = f"series_remind_{_sr_conf.lower()}_{_sr_hs}v{_sr_as}_{_sr_hrs}h"
            _scheduler.add_job(
                _send_series_bet_reminder,
                DateTrigger(run_date=_sr_remind, timezone='UTC'),
                args=[_sr_conf, _sr_hs, _sr_as, _sr_hrs],
                id=_sr_job_id,
                replace_existing=True,
                misfire_grace_time=1800,
            )
            print(f"[Scheduler] Series reminder scheduled: {_sr_conf} {_sr_hs}v{_sr_as} -{_sr_hrs}h "
                  f"@ {_sr_remind.strftime('%Y-%m-%d %H:%M')} UTC")

    # ── 8) Post-game syncs — fire 3h after each game tipoff to capture results ───
    # One-shot DateTrigger per game so results are picked up promptly even if
    # the game falls outside the 04:00–09:00 UTC cron window.
    _POST_GAME_DELAY = timedelta(hours=3)
    # Play-in games
    for (_pg_conf, _pg_gtype), _pg_start_str in PLAYIN_SCHEDULE_UTC.items():
        _pg_start = datetime.strptime(_pg_start_str, "%Y-%m-%d %H:%M:%S")
        _pg_sync = _pg_start + _POST_GAME_DELAY
        if _pg_sync > _now_utc:
            _pg_jid = f"post_game_sync_{_pg_conf.lower()}_{_pg_gtype.replace('v','v')}"
            _scheduler.add_job(
                _full_chain_sync,
                DateTrigger(run_date=_pg_sync, timezone='UTC'),
                id=_pg_jid,
                replace_existing=True,
                misfire_grace_time=1800,
                max_instances=1,
            )
            print(f"[Scheduler] Post-game sync: {_pg_conf} {_pg_gtype} @ "
                  f"{_pg_sync.strftime('%Y-%m-%d %H:%M')} UTC (+3h)")
        else:
            print(f"[Scheduler] Post-game sync {_pg_conf} {_pg_gtype} already past — skipping")
    # First Round Game 1 tipoffs
    for (_sr_conf, _sr_hs, _sr_as), _sr_start_str in _GAME1_SCHEDULE_UTC.items():
        _sr_start = datetime.strptime(
            _sr_start_str.rstrip('Z').replace('T', ' '), "%Y-%m-%d %H:%M:%S"
        )
        _sr_sync = _sr_start + _POST_GAME_DELAY
        if _sr_sync > _now_utc:
            _sr_jid = f"post_game_sync_{_sr_conf.lower()}_{_sr_hs}v{_sr_as}"
            _scheduler.add_job(
                _full_chain_sync,
                DateTrigger(run_date=_sr_sync, timezone='UTC'),
                id=_sr_jid,
                replace_existing=True,
                misfire_grace_time=1800,
                max_instances=1,
            )
            print(f"[Scheduler] Post-game sync: {_sr_conf} {_sr_hs}v{_sr_as} @ "
                  f"{_sr_sync.strftime('%Y-%m-%d %H:%M')} UTC (+3h after Game 1)")
        else:
            print(f"[Scheduler] Post-game sync {_sr_conf} {_sr_hs}v{_sr_as} already past — skipping")

    _scheduler.start()
    print("[Scheduler] APScheduler started"
          " — daily_auto_sync: 0 4 * * * UTC (04:00 UTC, 1x/day; full chain)"
          " — missing-picks push: 0 6 & 0 18 UTC"
          " — daily email reminders: 0 10 UTC (20h dedup)"
          f" — active until {_STANDINGS_SYNC_CUTOFF.date()}"
          f" — boxscore TTL={BOXSCORE_TTL_MINUTES}m, standings TTL={STANDINGS_TTL_MINUTES}m")

    # Fire-and-forget initial sync so DB is populated shortly after boot
    threading.Thread(target=_initial_standings_sync, daemon=True).start()

    # Backfill yesterday + today boxscores on every startup (force=True) so
    # a Railway redeploy always catches up on any missed games immediately.
    def _startup_boxscore_backfill():
        import time as _time
        _time.sleep(15)  # let DB connections settle
        for _date, _lbl in [
            ((datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d'), 'yesterday'),
            (datetime.utcnow().strftime('%Y-%m-%d'), 'today'),
        ]:
            try:
                bx = sync_daily_boxscores(date_str=_date, season='2026',
                                          force=True, triggered_by='startup_backfill')
                print(f"[Startup] Boxscore backfill ({_lbl}/{_date}): "
                      f"games={bx.get('games_processed',0)} players={bx.get('players_upserted',0)}")
            except Exception as _e:
                print(f"[Startup] Boxscore backfill ({_lbl}) ERROR: {_e}")

    threading.Thread(target=_startup_boxscore_backfill, daemon=True).start()
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
    skip_reason    = None
    if force_refresh:
        # Only trigger if cache is stale — avoids hammering the API on rapid reloads
        fetched_at = _standings_cache.get("fetched_at")
        if fetched_at:
            age_min = (datetime.utcnow() - fetched_at).total_seconds() / 60
            if age_min < STANDINGS_TTL_MINUTES:
                skip_reason = f"fresh_cache ({age_min:.1f}m < {STANDINGS_TTL_MINUTES}m TTL)"
                print(f"[Standings] [user_refresh] Skipping — {skip_reason}")
            else:
                print(f"[Standings] [user_refresh] Cache is {age_min:.1f}m old — triggering sync")
                threading.Thread(target=_standings_sync_job, daemon=True).start()
                sync_triggered = True
        else:
            # No cache at all — always sync
            print("[Standings] [user_refresh] No cache found — triggering sync")
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
        "sync_skipped":      skip_reason is not None,
        "sync_skip_reason":  skip_reason,
        "sync_cutoff":       _STANDINGS_SYNC_CUTOFF.strftime('%Y-%m-%d'),
        "static_mode":       is_static_mode,
        "data_source":       _sync_status.get("source", "unknown"),
        "consecutive_failures": _sync_status.get("consecutive_failures", 0),
        "last_sync_error":   _sync_status.get("last_error"),
    }


@app.post("/api/games/refresh")
async def refresh_today_games(date: str | None = None):
    """
    User-triggered on-demand boxscore refresh.
    Checks the BOXSCORE_TTL_MINUTES freshness gate before hitting any API.
    Returns immediately after spawning a background thread.

    Query param:
        date: 'YYYY-MM-DD' — defaults to yesterday UTC (most recent completed games).
    """
    target_date = date or (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')

    # Freshness check — don't trigger if recently synced
    _last = _boxscore_last_sync.get(target_date)
    if _last is not None:
        age_min = (datetime.utcnow() - _last).total_seconds() / 60
        if age_min < BOXSCORE_TTL_MINUTES:
            return {
                "triggered": False,
                "date": target_date,
                "reason": f"fresh_cache ({age_min:.1f}m < {BOXSCORE_TTL_MINUTES}m TTL)",
                "last_sync": _last.isoformat(),
            }

    def _run():
        sync_daily_boxscores(date_str=target_date, season='2026',
                             force=False, triggered_by='user_refresh')
        # Also refresh game results + provisional leaders in the same background pass
        try:
            from game_processor import sync_playoff_results_from_api, sync_series_provisional_leaders
            sync_playoff_results_from_api('2026')
            sync_series_provisional_leaders('2026')
        except Exception as _gp_err:
            print(f"[Boxscore] [user_refresh] game_processor sync error: {_gp_err}")

    threading.Thread(target=_run, daemon=True).start()
    print(f"[Boxscore] [user_refresh] Background sync triggered for {target_date}")
    return {
        "triggered": True,
        "date": target_date,
        "message": f"Boxscore sync started for {target_date}. Refresh in ~30s to see updated results.",
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
    Aggregate per-game averages directly from player_game_stats and upsert
    into player_stats. Pure SQL — no external API, no timeout risk.
    Players with < 5 games are excluded (insufficient sample).
    """
    conn = get_db_conn()
    c    = conn.cursor()
    try:
        c.execute('''
            INSERT INTO player_stats
                (player_id, player_name, team_abbreviation, season,
                 games_played, pts_per_game, ast_per_game, reb_per_game,
                 stl_per_game, blk_per_game, fg3m_per_game, updated_at)
            SELECT
                ps.player_id,
                agg.player_name,
                agg.team_abbr,
                '2026',
                agg.gp,
                agg.ppg,
                agg.apg,
                agg.rpg,
                agg.spg,
                agg.bpg,
                agg.fg3m,
                NOW()
            FROM (
                SELECT
                    player_name,
                    MAX(team_abbr)                                          AS team_abbr,
                    COUNT(DISTINCT espn_game_id)                            AS gp,
                    ROUND(AVG(points)::numeric,    1)                       AS ppg,
                    ROUND(AVG(assists)::numeric,   1)                       AS apg,
                    ROUND(AVG(rebounds)::numeric,  1)                       AS rpg,
                    ROUND(AVG(steals)::numeric,    1)                       AS spg,
                    ROUND(AVG(blocks)::numeric,    1)                       AS bpg,
                    ROUND(AVG(COALESCE(fg3m, 0))::numeric, 1)               AS fg3m
                FROM player_game_stats
                WHERE season = '2026'
                  AND (points > 0 OR assists > 0 OR rebounds > 0)
                GROUP BY player_name
                HAVING COUNT(DISTINCT espn_game_id) >= 5
            ) agg
            JOIN player_stats ps
                ON LOWER(ps.player_name) = LOWER(agg.player_name)
               AND ps.season = '2026'
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
        ''')
        updated = c.rowcount
        conn.commit()
        print(f"[PlayerSync] Aggregated from player_game_stats → {updated} rows updated")
        return {"success": True, "source": "player_game_stats", "count": updated,
                "synced_at": datetime.utcnow().isoformat()}
    except Exception as e:
        conn.rollback()
        print(f"[PlayerSync] ERROR: {e}")
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


@app.post("/api/admin/cleanup-duplicate-series")
async def cleanup_duplicate_series(season: str = "2026"):
    """
    One-time cleanup: remove duplicate First Round series rows that share the same
    (conference, home_seed, away_seed) slot. Keeps the row with the most predictions
    (or highest id if tied), deletes the rest. Safe to run multiple times.
    """
    conn = get_db_conn()
    c = conn.cursor()
    try:
        # Find duplicate slots: same conference + round + (home_seed, away_seed)
        c.execute('''
            SELECT conference, home_seed, away_seed, array_agg(id ORDER BY
                (SELECT COUNT(*) FROM predictions p WHERE p.series_id = s.id) DESC,
                id DESC
            ) AS ids
            FROM series s
            WHERE season = %s AND round = 'First Round'
            GROUP BY conference, home_seed, away_seed
            HAVING COUNT(*) > 1
        ''', (season,))
        rows = c.fetchall()
        deleted_total = 0
        for conf, hs, as_, ids in rows:
            keep_id   = ids[0]        # first = most predictions, then highest id
            drop_ids  = ids[1:]
            # Re-attach any predictions from drop rows to the kept row
            for drop_id in drop_ids:
                c.execute('''UPDATE predictions SET series_id = %s
                             WHERE series_id = %s
                             AND NOT EXISTS (
                                 SELECT 1 FROM predictions p2
                                 WHERE p2.series_id = %s AND p2.user_id = predictions.user_id
                             )''', (keep_id, drop_id, keep_id))
                c.execute('DELETE FROM predictions WHERE series_id = %s', (drop_id,))
                c.execute('DELETE FROM series WHERE id = %s', (drop_id,))
                deleted_total += 1
            print(f"[DeduplicateSeries] Kept {keep_id}, removed {drop_ids} ({conf} {hs}v{as_})")
        conn.commit()
        return {"deleted": deleted_total, "groups_fixed": len(rows)}
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        conn.close()


@app.post("/api/admin/cleanup-duplicate-players")
async def cleanup_duplicate_players(season: str = "2026"):
    """
    One-time cleanup: merge player_stats rows that are duplicates by accent-
    normalized name (e.g. 'Luka Dončić' and 'Luka Doncic').
    For each duplicate group, keeps the row with the most games_played and
    deletes the rest.  Returns a list of merged player names.
    """
    conn = get_db_conn()
    c    = conn.cursor()
    c.execute("SELECT player_id, player_name, games_played FROM player_stats WHERE season = %s",
              (season,))
    rows = c.fetchall()

    # Group by normalized name
    groups: dict[str, list] = {}
    for pid, pname, gp in rows:
        key = _normalize_name(pname)
        groups.setdefault(key, []).append((pid, pname, gp or 0))

    merged = []
    deleted_total = 0
    for norm_key, group in groups.items():
        if len(group) < 2:
            continue
        # Keep the row with the most games_played (best stats source)
        group.sort(key=lambda x: -x[2])
        keep_pid   = group[0][0]
        keep_name  = group[0][1]
        delete_pids = [g[0] for g in group[1:]]
        try:
            c.execute(
                "DELETE FROM player_stats WHERE player_id = ANY(%s) AND season = %s",
                (delete_pids, season)
            )
            deleted_total += c.rowcount
            merged.append({
                "kept":    f"{keep_name} (pid={keep_pid})",
                "removed": [f"{g[1]} (pid={g[0]})" for g in group[1:]],
            })
            print(f"[Cleanup] Merged duplicate '{keep_name}': kept pid={keep_pid}, "
                  f"removed {delete_pids}")
        except Exception as e:
            print(f"[Cleanup] Error merging '{norm_key}': {e}")

    conn.commit()
    conn.close()
    return {
        "season":        season,
        "groups_merged": len(merged),
        "rows_deleted":  deleted_total,
        "details":       merged,
    }


@app.post("/api/admin/backfill-player-ppg")
async def backfill_player_ppg(season: str = "2026"):
    """
    Recompute pts_per_game (and other per-game averages) for all players
    in player_stats using actual game data from player_game_stats.
    Run once after deploying the PPG fix.
    """
    conn = get_db_conn()
    c    = conn.cursor()
    c.execute('''
        UPDATE player_stats ps
        SET pts_per_game  = sub.avg_pts,
            ast_per_game  = sub.avg_ast,
            reb_per_game  = sub.avg_reb,
            stl_per_game  = sub.avg_stl,
            blk_per_game  = sub.avg_blk,
            fg3m_per_game = sub.avg_fg3m,
            games_played  = sub.gp
        FROM (
            SELECT espn_player_id,
                   COUNT(*)                               AS gp,
                   ROUND(AVG(points)::numeric,  1)        AS avg_pts,
                   ROUND(AVG(assists)::numeric, 1)        AS avg_ast,
                   ROUND(AVG(rebounds)::numeric,1)        AS avg_reb,
                   ROUND(AVG(steals)::numeric,  1)        AS avg_stl,
                   ROUND(AVG(blocks)::numeric,  1)        AS avg_blk,
                   ROUND(AVG(fg3m)::numeric,    1)        AS avg_fg3m
            FROM player_game_stats
            WHERE season = %s
            GROUP BY espn_player_id
        ) sub
        WHERE ps.espn_player_id = sub.espn_player_id
          AND ps.season = %s
    ''', (season, season))
    updated = c.rowcount
    conn.commit()
    conn.close()
    return {"players_updated": updated, "season": season}


@app.post("/api/admin/trigger-reminder")
async def admin_trigger_reminder(request: Request):
    """
    Trigger the daily email reminder job.  Accepts calls from:
    • Vercel Cron  — Authorization: Bearer <CRON_SECRET>
    • Admin UI     — authenticated admin session (no secret header needed)

    Runs _send_daily_email_reminders() in a background thread so the HTTP
    response returns immediately.
    """
    # Verify cron secret when the header is present (Vercel cron path)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
        if _CRON_SECRET and token != _CRON_SECRET:
            raise HTTPException(status_code=401, detail="Invalid cron secret")

    import threading as _threading
    _threading.Thread(target=_send_daily_email_reminders, daemon=True).start()
    return {"status": "queued", "message": "Daily email reminder job started in background"}


@app.post("/api/admin/send-test-email")
async def admin_send_test_email(request: Request, to: str):
    """
    Send a single test reminder email to the given address.
    Uses placeholder matchups so the Resend config can be verified end-to-end.
    Full error details are logged to Railway stdout on failure.
    """
    # Log the raw query string so any encoding/autofill artifact is visible
    print(f"[TestEmail] Raw URL: {request.url}")

    to = to.strip()   # defensive: remove any leading/trailing whitespace

    if not _GMAIL_CLIENT_ID or not _GMAIL_CLIENT_SECRET or not _GMAIL_REFRESH_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, or GMAIL_REFRESH_TOKEN not configured — add them to Railway env vars",
        )
    if not to or "@" not in to:
        raise HTTPException(status_code=400, detail="Invalid 'to' email address")

    sample_labels = [
        "Oklahoma City Thunder vs Memphis Grizzlies (First Round)",
        "Boston Celtics vs Miami Heat (Conference Semifinals)",
    ]
    subject = "[TEST] Don't leave points on the table! \U0001f3c0 Your NBA Playoff predictions are incomplete."
    print(f"[TestEmail] Triggered — to={to!r} from={_GMAIL_SENDER!r}")
    try:
        _gmail_send_email(to, subject, _build_reminder_html(sample_labels))
        return {"sent": True, "to": to, "gmail_sender": _GMAIL_SENDER}
    except RuntimeError as e:
        err_str = str(e)
        print(f"[TestEmail] FAILED — {err_str}")
        raise HTTPException(status_code=502, detail=err_str)
    except Exception as e:
        err_str = f"{type(e).__name__}: {e}"
        print(f"[TestEmail] FAILED (unexpected) — {err_str}")
        raise HTTPException(status_code=500, detail=err_str)


@app.post("/api/admin/run-reminder-now")
async def admin_run_reminder_now():
    """
    Synchronously run _send_daily_email_reminders() and return its result.
    Use this to diagnose why daily reminders aren't sending — the response
    shows how many users were eligible, how many emails were sent, and any
    errors, without waiting for the 10:00 UTC cron.
    """
    result = _send_daily_email_reminders()
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
    try:
        generate_matchups()
    except Exception as _gme:
        print(f"[Standings/push] generate_matchups failed (non-fatal): {_gme}")

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


# ── AI Chatbot ────────────────────────────────────────────────────────────────

_CHAT_SYSTEM_PROMPT = """You are an NBA Playoff Predictor assistant embedded in a pick-em game called "NBA Playoff Predictor 2026."
Help users make informed decisions about their picks and answer questions about the playoff bracket.

== LANGUAGE RULE (CRITICAL — always follow this first) ==
Detect the language of the user's latest message and reply ENTIRELY in that language.
- If the user writes in Hebrew (עברית) → respond fully in Hebrew, right-to-left naturally.
- If the user writes in English → respond in English.
- If mixed, match the dominant language.
- Team names and stat abbreviations (OKC, PPG, etc.) may stay in English regardless of reply language.
- Never translate or mix mid-response — pick one language and stay with it.

== YOUR ROLE ==
- Answer questions about picks, strategy, and scoring
- Suggest optimal picks backed by real data (standings, community votes, seedings)
- Tell users their ranking and pick accuracy when asked
- READ-ONLY — you cannot make or change picks for users

== SCORING RULES ==
PLAY-IN: Correct favourite=5pts | Correct underdog=8pts
SERIES: Correct winner=50pts base | Exact games=+30pts bonus
Round multipliers: R1x1.0 | Conf Semis x1.5 | Conf Finals x2.0 | NBA Finals x2.5
R1 underdog multipliers: 1v8 x2.0 | 2v7 x1.5 | 3v6 x1.2 | 4v5 x1.0
FUTURES: Champion=100pts | Conf Champ=40pts | Finals MVP=30pts | Conf MVPs=20pts each
PLAYOFF LEADERS (season-long): Top Scorer=50pts | Top Rebounder=30pts | Top Assister=30pts | Top 3s=30pts | Top Steals=30pts | Top Blocks=30pts

== HOW TO READ THE LIVE CONTEXT JSON ==
The context contains several sections — here is what each key means:

user_series_picks → the user's picks for each playoff series (who they picked to win, in how many games, whether it was correct, and points earned)
user_futures_picks → the user's season-long futures bets:
  • champion = team they picked to win the NBA title
  • west_champ / east_champ = conference champions they picked
  • finals_mvp / west_finals_mvp / east_finals_mvp = MVP picks
user_leaders_picks → the user's bets on which PLAYER will lead the ENTIRE playoffs in each stat category:
  • top_scorer = player they bet will score the most PPG across all playoff games
  • top_assists = player they bet will lead playoffs in assists
  • top_rebounds = player they bet will lead playoffs in rebounds
  • top_threes = player they bet will make the most 3-pointers per game in the playoffs
  • top_steals = player they bet will lead playoffs in steals
  • top_blocks = player they bet will lead playoffs in blocks (most BPG across all playoff games)
  • correct=1 means that bet was correct, correct=0 means wrong, correct=null means still pending
user_playin_picks → the user's play-in tournament picks

community_top_blocks_picks → how many users picked each player as the playoff blocks leader, with %
community_top_threes_picks → how many users picked each player as the 3-pointers leader, with %
community_champion_picks / community_west_champ_picks / community_east_champ_picks → futures picks from all users
community_finals_mvp_picks → Finals MVP picks across all users

stat_leaders_blocks → current per-game blocks leaders in the playoffs (actual live stats)
stat_leaders_scoring → current per-game scoring leaders
stat_leaders_threes → current per-game 3-pointers leaders
record_most_blocks_one_game → highest single-game block totals this postseason
record_most_points_one_game → highest single-game scoring performances
community_series_picks → for each series, how the community voted (% for each team)

== IMPORTANT RULES FOR ANSWERING ==
- "What is my [stat] bet?" or "Who did I bet on for [stat]?" → look in user_leaders_picks
- "Who leads in [stat]?" → look in stat_leaders_[stat]
- "What is the record for most [stat] in one game?" → look in record_most_[stat]_one_game
- "What does the community think about [X]?" → look in community_* sections
- "What are my futures picks?" → look in user_futures_picks
- If user_leaders_picks is missing → the user is not logged in or hasn't made leaders picks yet
- Never say you don't have access to data that IS present in the context JSON below

== STRATEGY TIPS ==
- Picking a 1-seed upset (8 beats 1) yields up to 160pts vs 80pts for the favourite — high risk, high reward
- Later rounds multiply all points — prioritise accuracy in Semis/Finals
- Exact game count doubles your payout for a correct winner pick
- Community % can signal where the smart money is, but fading the crowd can pay off in upsets

== TONE ==
- Confident, concise, basketball-smart
- Use concrete numbers from the context below
- Keep responses under 200 words unless the user asks for detailed analysis
- Never fabricate stats, scores, or standings not present in the context

== LIVE CONTEXT (current as of this request) ==
{context_json}

When a user asks who to pick, cite specific community vote percentages and seedings from the context above.
When they ask about their ranking, reference their exact rank and points from the context.
"""


def _build_chat_context(conn, user_id: Optional[int], season: str) -> str:
    """Build a comprehensive JSON context from all DB tables for the LLM."""
    import json as _json
    c = conn.cursor()
    ctx = {}

    # ── 1. All series (status, score, winner) ─────────────────────────────────
    c.execute("""
        SELECT s.round, s.conference,
               ht.name, ht.abbreviation, s.home_seed, s.home_wins,
               at.name, at.abbreviation, s.away_seed, s.away_wins,
               s.status, s.winner_team_id,
               ht.id, at.id, COALESCE(s.actual_games, 0)
        FROM series s
        JOIN teams ht ON s.home_team_id = ht.id
        JOIN teams at ON s.away_team_id = at.id
        WHERE s.season = %s
        ORDER BY s.round, s.conference
    """, (season,))
    ctx["series"] = []
    for r in c.fetchall():
        winner = r[3] if (r[11] and r[12] == r[11]) else (r[7] if r[11] else None)
        ctx["series"].append({
            "round": r[0], "conf": r[1],
            "home": r[3], "home_seed": r[4], "home_wins": r[5],
            "away": r[7], "away_seed": r[8], "away_wins": r[9],
            "status": r[10], "winner": winner, "total_games": r[14],
        })

    # ── 2. Community series picks (% per team, all series) ────────────────────
    c.execute("""
        WITH lp AS (
            SELECT DISTINCT ON (user_id, series_id) series_id, predicted_winner_id
            FROM predictions ORDER BY user_id, series_id, id DESC
        )
        SELECT s.round, s.conference, ht.abbreviation, at.abbreviation,
               COUNT(lp.predicted_winner_id)::int AS total,
               SUM(CASE WHEN lp.predicted_winner_id = s.home_team_id THEN 1 ELSE 0 END)::int,
               SUM(CASE WHEN lp.predicted_winner_id = s.away_team_id THEN 1 ELSE 0 END)::int
        FROM series s
        JOIN teams ht ON s.home_team_id = ht.id
        JOIN teams at ON s.away_team_id = at.id
        LEFT JOIN lp ON lp.series_id = s.id
        WHERE s.season = %s
        GROUP BY s.round, s.conference, ht.abbreviation, at.abbreviation
        ORDER BY s.round, s.conference
    """, (season,))
    ctx["community_series_picks"] = []
    for r in c.fetchall():
        total = r[4] or 0
        hv, av = r[5] or 0, r[6] or 0
        ctx["community_series_picks"].append({
            "round": r[0], "conf": r[1], "home": r[2], "away": r[3],
            "total_votes": total,
            "home_pct": round(hv / total * 100) if total else 50,
            "away_pct": round(av / total * 100) if total else 50,
        })

    # ── 3. Community futures picks (champion / west / east champ) ─────────────
    for col, label in [("champion_team_id", "champion"), ("west_champ_team_id", "west_champ"),
                       ("east_champ_team_id", "east_champ")]:
        c.execute(f"""
            SELECT t.name, t.abbreviation, COUNT(*)::int AS votes
            FROM futures_predictions fp
            JOIN teams t ON t.id = fp.{col}
            WHERE fp.season = %s AND fp.{col} IS NOT NULL
            GROUP BY t.name, t.abbreviation
            ORDER BY votes DESC
        """, (season,))
        rows = c.fetchall()
        total = sum(r[2] for r in rows)
        ctx[f"community_{label}_picks"] = [
            {"team": r[1], "votes": r[2], "pct": round(r[2] / total * 100) if total else 0}
            for r in rows
        ]

    # ── 4. Community Finals MVP picks ─────────────────────────────────────────
    for col, label in [("finals_mvp", "finals_mvp"), ("west_finals_mvp", "west_finals_mvp"),
                       ("east_finals_mvp", "east_finals_mvp")]:
        c.execute(f"""
            SELECT {col}, COUNT(*)::int AS votes
            FROM futures_predictions
            WHERE season = %s AND {col} IS NOT NULL AND {col} != ''
            GROUP BY {col} ORDER BY votes DESC LIMIT 10
        """, (season,))
        rows = c.fetchall()
        total = sum(r[1] for r in rows)
        ctx[f"community_{label}_picks"] = [
            {"player": r[0], "votes": r[1], "pct": round(r[1] / total * 100) if total else 0}
            for r in rows
        ]

    # ── 5. Community stat-leader picks (top_blocks, top_scorer, etc.) ─────────
    for col, label in [
        ("top_scorer",   "community_top_scorer_picks"),
        ("top_assists",  "community_top_assists_picks"),
        ("top_rebounds", "community_top_rebounds_picks"),
        ("top_threes",   "community_top_threes_picks"),
        ("top_steals",   "community_top_steals_picks"),
        ("top_blocks",   "community_top_blocks_picks"),
    ]:
        c.execute(f"""
            SELECT ps.player_name, COUNT(*)::int AS votes
            FROM leaders_predictions lp
            JOIN player_stats ps ON ps.player_id = lp.{col} AND ps.season = %s
            WHERE lp.season = %s AND lp.{col} IS NOT NULL
            GROUP BY ps.player_name ORDER BY votes DESC LIMIT 10
        """, (season, season))
        rows = c.fetchall()
        total = sum(r[1] for r in rows)
        ctx[label] = [
            {"player": r[0], "votes": r[1], "pct": round(r[1] / total * 100) if total else 0}
            for r in rows
        ]

    # ── 6. Leaderboard top 20 ─────────────────────────────────────────────────
    c.execute("""
        SELECT username, points,
               RANK() OVER (ORDER BY points DESC) AS rank
        FROM users ORDER BY points DESC LIMIT 20
    """)
    ctx["leaderboard_top20"] = [
        {"rank": int(r[2]), "username": r[0], "points": r[1] or 0}
        for r in c.fetchall()
    ]

    # ── 7. Playoff stat leaders — per-game averages ───────────────────────────
    for cat, col in [
        ("stat_leaders_scoring",   "pts_per_game"),
        ("stat_leaders_blocks",    "blk_per_game"),
        ("stat_leaders_rebounds",  "reb_per_game"),
        ("stat_leaders_assists",   "ast_per_game"),
        ("stat_leaders_steals",    "stl_per_game"),
        ("stat_leaders_threes",    "fg3m_per_game"),
    ]:
        c.execute(f"""
            SELECT player_name, team_abbreviation, games_played,
                   pts_per_game, ast_per_game, reb_per_game,
                   stl_per_game, blk_per_game, fg3m_per_game, {col}
            FROM player_stats
            WHERE season = %s AND {col} > 0
            ORDER BY {col} DESC NULLS LAST LIMIT 5
        """, (season,))
        ctx[cat] = [
            {
                "name": r[0], "team": r[1], "gp": r[2],
                "ppg": round(float(r[3] or 0), 1),
                "apg": round(float(r[4] or 0), 1),
                "rpg": round(float(r[5] or 0), 1),
                "spg": round(float(r[6] or 0), 1),
                "bpg": round(float(r[7] or 0), 1),
                "3pg": round(float(r[8] or 0), 1),
                "stat_value": round(float(r[9] or 0), 1),
            }
            for r in c.fetchall()
        ]

    # ── 8. Single-game records from game logs ─────────────────────────────────
    for stat_col, label in [
        ("blocks",   "record_most_blocks_one_game"),
        ("points",   "record_most_points_one_game"),
        ("rebounds", "record_most_rebounds_one_game"),
        ("assists",  "record_most_assists_one_game"),
        ("steals",   "record_most_steals_one_game"),
    ]:
        c.execute(f"""
            SELECT player_name, team_abbr, {stat_col}, game_date
            FROM player_game_stats
            WHERE season = %s AND {stat_col} > 0
            ORDER BY {stat_col} DESC NULLS LAST LIMIT 5
        """, (season,))
        ctx[label] = [
            {"name": r[0], "team": r[1], "value": r[2], "date": str(r[3])}
            for r in c.fetchall()
        ]

    # ── 9. User-specific data (if logged in) ──────────────────────────────────
    if user_id:
        # User info + rank
        c.execute("""
            SELECT username, points,
                   (SELECT COUNT(*)+1 FROM users u2 WHERE u2.points > u.points)
            FROM users u WHERE id = %s
        """, (user_id,))
        urow = c.fetchone()
        if urow:
            ctx["user_username"] = urow[0]
            ctx["user_points"] = urow[1] or 0
            ctx["user_rank"] = int(urow[2])

        # Series picks
        c.execute("""
            SELECT s.round, s.conference,
                   ht.abbreviation, at.abbreviation, wt.abbreviation,
                   p.predicted_games, p.is_correct, p.points_earned
            FROM predictions p
            JOIN series s ON p.series_id = s.id
            JOIN teams ht ON s.home_team_id = ht.id
            JOIN teams at ON s.away_team_id = at.id
            LEFT JOIN teams wt ON p.predicted_winner_id = wt.id
            WHERE p.user_id = %s AND s.season = %s
            ORDER BY s.round, s.conference
        """, (user_id, season))
        ctx["user_series_picks"] = [
            {"round": r[0], "conf": r[1], "home": r[2], "away": r[3],
             "picked": r[4], "games": r[5], "correct": r[6], "pts": r[7] or 0}
            for r in c.fetchall()
        ]

        # Futures picks (champion / MVP)
        c.execute("""
            SELECT tc.abbreviation, tw.abbreviation, te.abbreviation,
                   fp.finals_mvp, fp.west_finals_mvp, fp.east_finals_mvp,
                   fp.is_correct_champion, fp.is_correct_west, fp.is_correct_east,
                   fp.points_earned
            FROM futures_predictions fp
            LEFT JOIN teams tc ON tc.id = fp.champion_team_id
            LEFT JOIN teams tw ON tw.id = fp.west_champ_team_id
            LEFT JOIN teams te ON te.id = fp.east_champ_team_id
            WHERE fp.user_id = %s AND fp.season = %s
        """, (user_id, season))
        frow = c.fetchone()
        if frow:
            ctx["user_futures_picks"] = {
                "champion": frow[0], "west_champ": frow[1], "east_champ": frow[2],
                "finals_mvp": frow[3], "west_finals_mvp": frow[4], "east_finals_mvp": frow[5],
                "champion_correct": frow[6], "west_correct": frow[7], "east_correct": frow[8],
                "points_earned": frow[9] or 0,
            }

        # Leaders/stat picks — fetch raw player IDs first, then resolve names
        c.execute("""
            SELECT top_scorer, top_assists, top_rebounds,
                   top_threes, top_steals, top_blocks,
                   is_correct_scorer, is_correct_assists,
                   is_correct_rebounds, is_correct_threes,
                   is_correct_steals, is_correct_blocks,
                   points_earned
            FROM leaders_predictions
            WHERE user_id = %s AND season = %s
        """, (user_id, season))
        lrow = c.fetchone()
        if lrow:
            def _resolve_player(pid):
                if not pid:
                    return None
                c.execute("SELECT player_name FROM player_stats WHERE player_id = %s LIMIT 1", (pid,))
                r = c.fetchone()
                return r[0] if r else f"player_id:{pid}"
            ctx["user_leaders_picks"] = {
                "top_scorer":    {"player": _resolve_player(lrow[0]),  "correct": lrow[6]},
                "top_assists":   {"player": _resolve_player(lrow[1]),  "correct": lrow[7]},
                "top_rebounds":  {"player": _resolve_player(lrow[2]),  "correct": lrow[8]},
                "top_threes":    {"player": _resolve_player(lrow[3]),  "correct": lrow[9]},
                "top_steals":    {"player": _resolve_player(lrow[4]),  "correct": lrow[10]},
                "top_blocks":    {"player": _resolve_player(lrow[5]),  "correct": lrow[11]},
                "points_earned": lrow[12] or 0,
            }

        # Play-in picks
        c.execute("""
            SELECT g.home_team_id, g.away_team_id, g.conference, g.round,
                   wt.abbreviation, pp.is_correct, pp.points_earned
            FROM playin_predictions pp
            JOIN playin_games g ON pp.game_id = g.id
            LEFT JOIN teams wt ON wt.id = pp.predicted_winner_id
            WHERE pp.user_id = %s AND g.season = %s
        """, (user_id, season))
        ctx["user_playin_picks"] = [
            {"conf": r[2], "round": r[3], "picked": r[4],
             "correct": r[5], "pts": r[6] or 0}
            for r in c.fetchall()
        ]

    return _json.dumps(ctx, default=str)


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    """AI chatbot: builds live DB context, sends to Claude, returns reply."""
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not anthropic_key:
        raise HTTPException(status_code=503, detail="AI service not configured")

    # Build context from DB
    conn = None
    context_json = "{}"
    try:
        conn = get_db_conn()
        context_json = _build_chat_context(conn, req.user_id, req.season)
    except Exception as e:
        print(f"[chat] context build error: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    system = _CHAT_SYSTEM_PROMPT.replace("{context_json}", context_json)

    # Only send the last 10 messages to keep token budget bounded
    history = [{"role": m.role, "content": m.content} for m in req.messages[-10:]]

    try:
        if not _ANTHROPIC_AVAILABLE:
            raise HTTPException(status_code=503, detail="anthropic package not installed on server")
        client = _anthropic_sdk.Anthropic(api_key=anthropic_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=system,
            messages=history,
        )
        return {"reply": response.content[0].text}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[chat] Anthropic API error: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"AI error: {type(e).__name__}: {str(e)[:200]}")


@app.get("/api/chat/test")
async def chat_test():
    """Diagnostic endpoint — checks anthropic package, API key, and DB."""
    key = os.getenv("ANTHROPIC_API_KEY", "")
    result = {
        "anthropic_installed": _ANTHROPIC_AVAILABLE,
        "api_key_set": bool(key),
        "api_key_prefix": (key[:16] + "...") if key else None,
        "db": "unknown",
    }
    try:
        conn = get_db_conn()
        conn.cursor().execute("SELECT 1")
        conn.close()
        result["db"] = "connected"
    except Exception as e:
        result["db"] = f"error: {e}"
    return result


@app.get("/api/chat/ping")
async def chat_ping():
    """Diagnostic: actually calls Anthropic API with a tiny test message."""
    import anthropic as _anth_check
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        return {"ok": False, "error": "ANTHROPIC_API_KEY not set"}
    if not _ANTHROPIC_AVAILABLE:
        return {"ok": False, "error": "anthropic package not installed"}

    sdk_version = getattr(_anth_check, "__version__", "unknown")

    # Check for any env vars that might override the base URL
    base_url_env = os.getenv("ANTHROPIC_BASE_URL", None)
    key_len = len(key)
    key_stripped = key.strip()
    key_has_whitespace = (key != key_stripped)

    diag = {
        "sdk_version": sdk_version,
        "key_length": key_len,
        "key_has_whitespace": key_has_whitespace,
        "key_prefix": key_stripped[:20] + "...",
        "base_url_env": base_url_env,
    }

    # Use stripped key
    client = _anthropic_sdk.Anthropic(api_key=key_stripped)

    # First: list available models so we know what this account can use
    try:
        models_page = client.models.list()
        available_models = [m.id for m in models_page.data]
        diag["available_models"] = available_models
    except Exception as e:
        diag["models_list_error"] = str(e)[:200]
        available_models = []

    # Try to find a haiku/small model, fall back to first available
    preferred = ["claude-haiku-4-5", "claude-haiku-4-0", "claude-3-5-haiku-20241022",
                 "claude-3-haiku-20240307"]
    model_to_use = next((m for m in preferred if m in available_models), None)
    if not model_to_use and available_models:
        model_to_use = available_models[-1]  # cheapest (usually last)
    if not model_to_use:
        model_to_use = "claude-haiku-4-5"  # best guess

    try:
        resp = client.messages.create(
            model=model_to_use,
            max_tokens=10,
            messages=[{"role": "user", "content": "Say hi"}],
        )
        return {"ok": True, "reply": resp.content[0].text, "model": resp.model, **diag}
    except Exception as e:
        return {"ok": False, "error_type": type(e).__name__, "error": str(e)[:300],
                "tried_model": model_to_use, **diag}


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
async def api_teams(response: Response, conference: Optional[str] = None, playoff_only: bool = False):
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

    response.headers["Cache-Control"] = "public, max-age=300"  # teams rarely change
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
    return {"user_id": row[0], "username": row[1], "email": row[2], "role": row[4], "points": row[5], "avatar_url": row[6] or ""}

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
    return {"user_id": row[0], "username": row[1], "email": row[2], "role": role, "points": row[5], "avatar_url": row[6] or ""}

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
async def api_series(response: Response, season: str = "2026", background_tasks: BackgroundTasks = None):
    # Fire a live sync in the background if games are active and cooldown elapsed
    if background_tasks is not None and _should_live_sync(season):
        background_tasks.add_task(_run_live_sync_bg, season)
    conn = None
    try:
        conn = get_db_conn()
        c = conn.cursor()

        # CRITICAL: Column order must match team table structure!
        # ORDER: rows with existing bets first (pred_count DESC) so the
        # dedup step below keeps the row users actually placed bets on.
        c.execute('''SELECT
                     s.id, s.season, s.round, s.conference,
                     s.home_team_id, s.home_seed, s.home_wins,
                     s.away_team_id, s.away_seed, s.away_wins,
                     s.winner_team_id, s.status, s.actual_games,
                     ht.name, ht.abbreviation, ht.logo_url,
                     at.name, at.abbreviation, at.logo_url,
                     s.actual_leading_scorer, s.actual_leading_rebounder,
                     s.actual_leading_assister,
                     s.game1_start_time,
                     (SELECT COUNT(*) FROM predictions p WHERE p.series_id = s.id) AS pred_count,
                     COALESCE(s.bracket_group, \'A\')
                     FROM series s
                     JOIN teams ht ON s.home_team_id = ht.id
                     JOIN teams at ON s.away_team_id = at.id
                     WHERE s.season = %s
                     ORDER BY pred_count DESC, s.id ASC''', (season,))

        from datetime import timezone as _tz
        _now_utc = datetime.now(_tz.utc)

        series = []
        _seen_series_matchups = set()   # dedup: same two teams in same round+conf → keep first
        for row in c.fetchall():
            # row[23] = pred_count (used for ordering, not exposed in response)
            _mkey = (row[3], row[2], min(row[4], row[7]), max(row[4], row[7]))
            if _mkey in _seen_series_matchups:
                continue
            _seen_series_matchups.add(_mkey)

            g1_start = row[22]
            # row[23] = pred_count, row[24] = bracket_group
            bracket_group = row[24] if len(row) > 24 else 'A'
            # A series is picks_locked when game1_start_time has passed OR status != active
            if g1_start:
                g1_dt = datetime.fromisoformat(g1_start.replace('Z', '+00:00'))
                picks_locked = _now_utc >= g1_dt or row[11] != 'active'
            else:
                picks_locked = row[11] != 'active'
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
                'leading_scorer':    row[19],
                'leading_rebounder': row[20],
                'leading_assister':  row[21],
                'game1_start_time':  g1_start,
                'picks_locked':      picks_locked,
                'bracket_group':     bracket_group,
            })

        response.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=60"
        return series
    except Exception as e:
        print(f"api_series error: {e}")
        raise HTTPException(status_code=500, detail="Failed to load series")
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@app.get("/api/playin-games")
async def api_playin(season: str = "2026", background_tasks: BackgroundTasks = None):
    # Fire a live sync in the background if games are active and cooldown elapsed
    if background_tasks is not None and _should_live_sync(season):
        background_tasks.add_task(_run_live_sync_bg, season)
    conn = None
    try:
        conn = get_db_conn()
        c = conn.cursor()

        # ORDER: rows with existing bets first so dedup keeps the canonical row
        c.execute('''SELECT p.id, p.season, p.conference, p.game_type,
                     p.team1_id, p.team1_seed, p.team2_id, p.team2_seed,
                     p.winner_id, p.status, p.start_time,
                     t1.name, t1.abbreviation, t1.logo_url,
                     t2.name, t2.abbreviation, t2.logo_url,
                     (SELECT COUNT(*) FROM playin_predictions pp WHERE pp.game_id = p.id) AS pred_count
                     FROM playin_games p
                     JOIN teams t1 ON p.team1_id = t1.id
                     JOIN teams t2 ON p.team2_id = t2.id
                     WHERE p.season = %s
                     ORDER BY pred_count DESC, p.id ASC''', (season,))

        games = []
        _seen_playin = set()   # dedup: one row per (conference, game_type)
        for row in c.fetchall():
            _pgkey = (row[2], row[3])   # (conference, game_type)
            if _pgkey in _seen_playin:
                continue
            _seen_playin.add(_pgkey)

            start_time = row[10]
            games.append({
                'id': row[0],
                'season': row[1],
                'conference': row[2],
                'game_type': row[3],
                'team1': {
                    'id': row[4],
                    'seed': row[5],
                    'name': row[11],
                    'abbreviation': row[12],
                    'logo_url': row[13]
                },
                'team2': {
                    'id': row[6],
                    'seed': row[7],
                    'name': row[14],
                    'abbreviation': row[15],
                    'logo_url': row[16]
                },
                'winner_id': row[8],
                'status': row[9],
                'start_time': start_time.isoformat() if start_time else None,
            })

        return games
    except Exception as e:
        print(f"api_playin error: {e}")
        raise HTTPException(status_code=500, detail="Failed to load play-in games")
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@app.post("/api/predictions")
async def make_pred(prediction: Prediction, user_id: int):
    conn = None
    try:
        conn = get_db_conn()
        c = conn.cursor()
        # Reject predictions on locked, completed, or game-started series
        c.execute("SELECT status, game1_start_time FROM series WHERE id = %s", (prediction.series_id,))
        series_row = c.fetchone()
        if not series_row:
            raise HTTPException(status_code=404, detail="Series not found")
        if series_row[0] != 'active':
            raise HTTPException(status_code=400, detail="Predictions are closed for this series")
        game1_start = series_row[1]
        if game1_start:
            from datetime import timezone
            start_dt = datetime.fromisoformat(game1_start.replace('Z', '+00:00'))
            if datetime.now(timezone.utc) >= start_dt:
                raise HTTPException(status_code=400, detail="Game 1 has started — predictions are closed")
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
        return {"message": "Saved"}
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@app.post("/api/playin-predictions")
async def playin_pred(game_id: int, predicted_winner_id: int, user_id: int):
    from datetime import datetime, timezone
    conn = get_db_conn()
    c = conn.cursor()
    # Check if bets are closed (game started)
    c.execute("SELECT start_time, status FROM playin_games WHERE id = %s", (game_id,))
    game_row = c.fetchone()
    if game_row:
        start_time, status = game_row
        if status != 'active':
            conn.close()
            raise HTTPException(status_code=400, detail="Bets are closed — game is no longer active")
        if start_time:
            # Compare both as naive UTC datetimes (DB stores TIMESTAMP without tz)
            now_naive = datetime.utcnow()
            st_naive  = start_time if isinstance(start_time, datetime) else datetime.fromisoformat(str(start_time))
            if now_naive >= st_naive:
                conn.close()
                raise HTTPException(status_code=400, detail="Bets are closed — game has already started")
    c.execute('''INSERT INTO playin_predictions (user_id, game_id, predicted_winner_id)
                 VALUES (%s, %s, %s) ON CONFLICT(user_id, game_id)
                 DO UPDATE SET predicted_winner_id = %s''',
              (user_id, game_id, predicted_winner_id, predicted_winner_id))
    conn.commit()
    conn.close()
    return {"message": "Saved"}


@app.post("/api/admin/reset-game1-times")
async def admin_reset_game1_times(season: str = "2026"):
    """Force-reset all game1_start_time values to the canonical schedule
    (overwrites any admin-entered wrong dates, unless manual_override=true).
    """
    updated = _backfill_game1_start_times(season=season, force=True)
    return {"ok": True, "updated": updated, "schedule": {
        f"{conf} {hs}v{aws}": t
        for (conf, hs, aws), t in _GAME1_SCHEDULE_UTC.items()
    }}


@app.post("/api/admin/playin/{game_id}/start-time")
async def set_playin_start_time(game_id: int, start_time: str | None = None):
    """Set or clear the start_time for a play-in game. Format: 'YYYY-MM-DD HH:MM:SS' (UTC)."""
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("UPDATE playin_games SET start_time = %s WHERE id = %s", (start_time, game_id))
    if c.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Game not found")
    conn.commit()
    conn.close()
    return {"message": "Start time updated", "game_id": game_id, "start_time": start_time}

@app.get("/api/leaderboard")
async def leaderboard(response: Response, season: str = "2026"):
    conn = None
    try:
        conn = get_db_conn()
        c = conn.cursor()
        # Tiebreaker: 1) total_points  2) bullseyes_count (series winner+games exact,
        # plus leaders categories with is_correct_* = 2)
        c.execute('''
            SELECT
                u.id, u.username, u.points,
                -- Series predictions
                -- Only count predictions that have been scored (series completed)
                COUNT(CASE WHEN p.is_correct IS NOT NULL THEN 1 END)    AS total_preds,
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
                ), 0)                                                    AS bullseyes_count,
                u.avatar_url,
                -- Points per category
                COALESCE((SELECT SUM(p3.points_earned) FROM predictions p3 WHERE p3.user_id = u.id), 0)             AS series_pts,
                COALESCE((SELECT SUM(pp.points_earned) FROM playin_predictions pp WHERE pp.user_id = u.id), 0)       AS playin_pts,
                COALESCE((SELECT SUM(fp.points_earned) FROM futures_predictions fp WHERE fp.user_id = u.id), 0)      AS futures_pts,
                COALESCE((SELECT SUM(lp.points_earned) FROM leaders_predictions lp WHERE lp.user_id = u.id), 0)     AS leaders_pts,
                -- Play-in: only count scored predictions (is_correct IS NOT NULL)
                COALESCE((SELECT COUNT(*) FROM playin_predictions pp2 WHERE pp2.user_id = u.id AND pp2.is_correct IS NOT NULL), 0) AS playin_total,
                COALESCE((SELECT COUNT(*) FROM playin_predictions pp2 WHERE pp2.user_id = u.id AND pp2.is_correct = 1), 0)        AS playin_correct
            FROM users u LEFT JOIN predictions p ON u.id = p.user_id
            GROUP BY u.id
            ORDER BY u.points DESC, bullseyes_count DESC
            LIMIT 100
        ''')
        board = []
        for idx, row in enumerate(c.fetchall(), 1):
            total_series, correct_series, bullseyes = row[3] or 0, row[4] or 0, row[5] or 0
            series_pts  = int(row[7])  if row[7]  else None
            playin_pts  = int(row[8])  if row[8]  else None
            futures_pts = int(row[9])  if row[9]  else None
            leaders_pts = int(row[10]) if row[10] else None
            playin_total   = int(row[11]) if row[11] else 0
            playin_correct = int(row[12]) if row[12] else 0
            total_all   = total_series + playin_total
            correct_all = correct_series + playin_correct
            board.append({
                'rank': idx, 'user_id': row[0], 'username': row[1], 'points': row[2],
                'total_predictions': total_all, 'correct_predictions': correct_all,
                'accuracy': round((correct_all / total_all * 100) if total_all > 0 else 0, 1),
                'bullseyes_count': bullseyes, 'avatar_url': row[6] or '',
                'series_points':  series_pts,
                'playin_points':  playin_pts,
                'futures_points': futures_pts,
                'leaders_points': leaders_pts,
            })

        # ── Provisional leaders points (while playoffs are ongoing) ────────────
        # Compute based on current playoff record highs vs each user's prediction.
        # Only shown for categories not yet officially scored (is_correct_* IS NULL).
        try:
            PLAYOFF_START_LB = '2026-04-18'
            # Step A: current playoff highs (one query, one row)
            c.execute("""
                SELECT
                    MAX(points)   FILTER (WHERE points   > 0),
                    MAX(assists)  FILTER (WHERE assists   > 0),
                    MAX(rebounds) FILTER (WHERE rebounds  > 0),
                    MAX(fg3m)     FILTER (WHERE fg3m      > 0),
                    MAX(steals)   FILTER (WHERE steals    > 0),
                    MAX(blocks)   FILTER (WHERE blocks    > 0)
                FROM player_game_stats
                WHERE season = %s AND game_date >= %s
            """, (season, PLAYOFF_START_LB))
            highs_row = c.fetchone() or (None,)*6
            current_highs = {
                'scorer':   highs_row[0],
                'assists':  highs_row[1],
                'rebounds': highs_row[2],
                'threes':   highs_row[3],
                'steals':   highs_row[4],
                'blocks':   highs_row[5],
            }

            # Step B: all users' leaders_predictions in one batch
            user_ids = [entry['user_id'] for entry in board]
            lp_by_user = {}
            if user_ids:
                c.execute("""
                    SELECT user_id,
                           top_scorer, top_assists, top_rebounds,
                           top_threes, top_steals, top_blocks,
                           is_correct_scorer, is_correct_assists, is_correct_rebounds,
                           is_correct_threes, is_correct_steals, is_correct_blocks
                    FROM leaders_predictions
                    WHERE season = %s AND user_id = ANY(%s)
                """, (season, user_ids))
                for lp_row in c.fetchall():
                    lp_by_user[lp_row[0]] = lp_row

            # Step C: compute provisional pts per user per category
            cat_cols = ['scorer', 'assists', 'rebounds', 'threes', 'steals', 'blocks']
            for entry in board:
                lp = lp_by_user.get(entry['user_id'])
                if not lp:
                    entry['provisional_leaders_pts'] = 0
                    entry['provisional_breakdown'] = {}
                    continue

                # lp indices: 1-6 = predictions, 7-12 = is_correct_*
                preds       = {cat: lp[i+1] for i, cat in enumerate(cat_cols)}
                is_correct  = {cat: lp[i+7] for i, cat in enumerate(cat_cols)}

                breakdown = {}
                total_prov = 0
                for cat, tiers in LEADERS_TIERS.items():
                    if is_correct[cat] is not None:
                        # Already officially scored — no provisional needed
                        continue
                    high = current_highs.get(cat)
                    pred = preds.get(cat)
                    if high is None or pred is None:
                        continue
                    try:
                        delta = abs(int(pred) - int(high))
                    except (TypeError, ValueError):
                        continue
                    awarded = 0
                    for max_delta, tier_pts in tiers:
                        if delta <= max_delta:
                            awarded = tier_pts
                            break
                    if awarded > 0:
                        breakdown[cat] = {'pts': awarded, 'predicted': int(pred), 'record': int(high)}
                        total_prov += awarded

                entry['provisional_leaders_pts'] = total_prov
                entry['provisional_breakdown'] = breakdown
        except Exception as prov_err:
            print(f"[Leaderboard] provisional pts error (non-critical): {prov_err}")
            for entry in board:
                if 'provisional_leaders_pts' not in entry:
                    entry['provisional_leaders_pts'] = 0
                    entry['provisional_breakdown'] = {}

        response.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=60"
        return board
    except Exception as e:
        print(f"leaderboard error: {e}")
        return []
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@app.get("/api/stats/global")
async def global_stats(response: Response, season: str = "2026"):
    """Aggregate community prediction stats for the Global Stats tab."""
    _EMPTY = {'series': [], 'playin': [], 'futures': {'top_champions': [], 'top_west_champs': [], 'top_east_champs': []}, 'total_users': 0}
    conn = None
    try:
        conn = get_db_conn()
        c = conn.cursor()

        # Per-series vote breakdown — only safe columns; no odds columns touched here.
        # home_seed / away_seed exist on series since original schema (init_db creates them).
        # Dedup predictions: take the latest pick per (user_id, series_id) so users who
        # re-saved a pick don't inflate the vote count.
        try:
            c.execute("""
                WITH latest_preds AS (
                    SELECT DISTINCT ON (user_id, series_id)
                           id, series_id, user_id, predicted_winner_id
                    FROM predictions
                    ORDER BY user_id, series_id, id DESC
                )
                SELECT s.id, s.round, s.conference,
                       s.home_team_id, ht.name, ht.abbreviation, ht.logo_url,
                       COALESCE(s.home_seed, 0),
                       s.away_team_id, at.name, at.abbreviation, at.logo_url,
                       COALESCE(s.away_seed, 0),
                       s.status,
                       COALESCE(SUM(CASE WHEN p.predicted_winner_id = s.home_team_id THEN 1 ELSE 0 END), 0),
                       COALESCE(SUM(CASE WHEN p.predicted_winner_id = s.away_team_id THEN 1 ELSE 0 END), 0),
                       COUNT(p.id),
                       s.game1_start_time,
                       s.winner_team_id, s.actual_games,
                       s.actual_leading_scorer, s.actual_leading_rebounder, s.actual_leading_assister
                FROM series s
                JOIN teams ht ON s.home_team_id = ht.id
                JOIN teams at ON s.away_team_id = at.id
                LEFT JOIN latest_preds p ON p.series_id = s.id
                WHERE s.season = %s
                GROUP BY s.id, s.round, s.conference,
                         s.home_team_id, ht.name, ht.abbreviation, ht.logo_url, s.home_seed,
                         s.away_team_id, at.name, at.abbreviation, at.logo_url, s.away_seed,
                         s.status, s.game1_start_time,
                         s.winner_team_id, s.actual_games,
                         s.actual_leading_scorer, s.actual_leading_rebounder, s.actual_leading_assister
                ORDER BY COUNT(p.id) DESC, s.id ASC
            """, (season,))
            series_stats = []
            _seen_matchups = set()  # dedup guard for duplicate DB rows — keeps series with most picks
            _now_utc = datetime.utcnow().replace(tzinfo=__import__('datetime').timezone.utc)
            for row in c.fetchall():
                # Deduplicate: same two teams in same round+conference → keep first row only
                _matchup_key = (row[2], row[1], min(row[3], row[8]), max(row[3], row[8]))
                if _matchup_key in _seen_matchups:
                    continue
                _seen_matchups.add(_matchup_key)

                home_v    = int(row[14]) if row[14] else 0
                away_v    = int(row[15]) if row[15] else 0
                total     = int(row[16]) if row[16] else 0
                g1_start  = row[17]
                # picks_locked: true once game1_start_time has passed OR series is not active
                _picks_locked = row[13] != 'active'
                if not _picks_locked and g1_start:
                    try:
                        from datetime import timezone as _tz
                        _start_dt = datetime.fromisoformat(g1_start.replace('Z', '+00:00'))
                        _picks_locked = datetime.now(_tz.utc) >= _start_dt
                    except Exception:
                        pass
                winner_team_id_gs = row[18]
                actual_games_gs   = row[19]
                actual_scorer_gs  = row[20]
                actual_reb_gs     = row[21]
                actual_ast_gs     = row[22]
                # Derive winner team object from home/away
                if winner_team_id_gs == row[3]:
                    winner_team_gs = {'id': row[3], 'name': row[4], 'abbreviation': row[5], 'logo_url': row[6], 'seed': row[7]}
                elif winner_team_id_gs == row[8]:
                    winner_team_gs = {'id': row[8], 'name': row[9], 'abbreviation': row[10], 'logo_url': row[11], 'seed': row[12]}
                else:
                    winner_team_gs = None
                series_stats.append({
                    'series_id':    row[0],
                    'round':        row[1],
                    'conference':   row[2],
                    'home_team':    {'id': row[3], 'name': row[4],  'abbreviation': row[5],  'logo_url': row[6],  'seed': row[7]},
                    'away_team':    {'id': row[8], 'name': row[9],  'abbreviation': row[10], 'logo_url': row[11], 'seed': row[12]},
                    'status':       row[13],
                    'home_votes':   home_v,
                    'away_votes':   away_v,
                    'total_votes':  total,
                    'home_pct':     round(home_v / total * 100) if total > 0 else 50,
                    'away_pct':     round(away_v / total * 100) if total > 0 else 50,
                    'game1_start_time': g1_start,
                    'picks_locked': _picks_locked,
                    'winner_team_id':          winner_team_id_gs,
                    'winner_team':             winner_team_gs,
                    'actual_games':            actual_games_gs,
                    'actual_leading_scorer':   actual_scorer_gs,
                    'actual_leading_rebounder':actual_reb_gs,
                    'actual_leading_assister': actual_ast_gs,
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

        # Play-in game vote breakdown — deduplicate so each user counts once per game
        try:
            c.execute("""
                WITH latest_pi AS (
                    SELECT DISTINCT ON (user_id, game_id)
                           id, game_id, user_id, predicted_winner_id
                    FROM playin_predictions
                    ORDER BY user_id, game_id, id DESC
                )
                SELECT pg.id, pg.conference, pg.game_type, pg.status,
                       pg.start_time,
                       pg.team1_id, t1.name, t1.abbreviation, t1.logo_url, COALESCE(pg.team1_seed, 0),
                       pg.team2_id, t2.name, t2.abbreviation, t2.logo_url, COALESCE(pg.team2_seed, 0),
                       pg.winner_id,
                       COALESCE(SUM(CASE WHEN pp.predicted_winner_id = pg.team1_id THEN 1 ELSE 0 END), 0),
                       COALESCE(SUM(CASE WHEN pp.predicted_winner_id = pg.team2_id THEN 1 ELSE 0 END), 0),
                       COUNT(pp.id)
                FROM playin_games pg
                JOIN teams t1 ON pg.team1_id = t1.id
                JOIN teams t2 ON pg.team2_id = t2.id
                LEFT JOIN latest_pi pp ON pp.game_id = pg.id
                WHERE pg.season = %s
                GROUP BY pg.id, t1.name, t1.abbreviation, t1.logo_url,
                         t2.name, t2.abbreviation, t2.logo_url
                ORDER BY COUNT(pp.id) DESC, pg.id ASC
            """, (season,))
            playin_stats = []
            _seen_playin_gs = set()   # dedup guard: one row per (conference, game_type)
            for row in c.fetchall():
                _pgkey = (row[1], row[2])   # (conference, game_type)
                if _pgkey in _seen_playin_gs:
                    continue
                _seen_playin_gs.add(_pgkey)

                t1_v = int(row[16]) if row[16] else 0
                t2_v = int(row[17]) if row[17] else 0
                total = int(row[18]) if row[18] else 0
                start_time = row[4].isoformat() if row[4] else None
                # Picks unlock once status != 'active' OR start_time has passed.
                # Checking start_time client-side handles the case where the sync
                # worker can't mark the game completed (e.g. API quota exceeded).
                _st_row = row[4]
                if _st_row:
                    _st_dt = _st_row if hasattr(_st_row, 'hour') else datetime.fromisoformat(str(_st_row))
                    picks_visible = row[3] != 'active' or datetime.utcnow() >= _st_dt
                else:
                    picks_visible = row[3] != 'active'
                playin_stats.append({
                    'game_id':       row[0],
                    'conference':    row[1],
                    'game_type':     row[2],
                    'status':        row[3],
                    'start_time':    start_time,
                    'picks_visible': picks_visible,
                    'team1': {'id': row[5], 'name': row[6],  'abbreviation': row[7],  'logo_url': row[8],  'seed': row[9]},
                    'team2': {'id': row[10], 'name': row[11], 'abbreviation': row[12], 'logo_url': row[13], 'seed': row[14]},
                    'winner_id':   row[15],
                    'team1_votes': t1_v,
                    'team2_votes': t2_v,
                    'total_votes': total,
                    'team1_pct':   round(t1_v / total * 100) if total > 0 else 50,
                    'team2_pct':   round(t2_v / total * 100) if total > 0 else 50,
                })
        except Exception as e:
            print(f"global_stats playin query error: {e}")
            conn.rollback()
            playin_stats = []

        try:
            c.execute("""SELECT COUNT(DISTINCT p.user_id) FROM predictions p
                         JOIN series s ON p.series_id = s.id WHERE s.season = %s""", (season,))
            total_users = c.fetchone()[0] or 0
        except Exception as e:
            print(f"global_stats total_users error: {e}")
            conn.rollback()
            total_users = 0

        # MVP picks — aggregate by player name (TEXT field)
        def top_mvp(col):
            try:
                c.execute(f"""
                    SELECT fp.{col}, COUNT(*) AS cnt
                    FROM futures_predictions fp
                    WHERE fp.season = %s AND fp.{col} IS NOT NULL AND fp.{col} <> ''
                    GROUP BY fp.{col}
                    ORDER BY cnt DESC LIMIT 5
                """, (season,))
                total_mvp = sum(r[1] for r in c.fetchall()) or 1
                c.execute(f"""
                    SELECT fp.{col}, COUNT(*) AS cnt
                    FROM futures_predictions fp
                    WHERE fp.season = %s AND fp.{col} IS NOT NULL AND fp.{col} <> ''
                    GROUP BY fp.{col}
                    ORDER BY cnt DESC LIMIT 5
                """, (season,))
                return [{'name': r[0], 'count': r[1], 'pct': round(r[1] / total_mvp * 100)}
                        for r in c.fetchall()]
            except Exception as e:
                print(f"global_stats top_mvp({col}) error: {e}")
                conn.rollback()
                return []

        # Leaders picks — aggregate by predicted numeric value (max single-game stat)
        def top_leaders(col):
            try:
                c.execute(f"""
                    SELECT lp.{col}, COUNT(*) AS cnt
                    FROM leaders_predictions lp
                    WHERE lp.season = %s AND lp.{col} IS NOT NULL AND lp.{col} > 0
                    GROUP BY lp.{col}
                    ORDER BY cnt DESC, lp.{col} DESC
                    LIMIT 8
                """, (season,))
                rows = c.fetchall()
                total = sum(r[1] for r in rows) or 1
                all_vals = [r[0] for r in rows]
                avg_val  = round(sum(all_vals) / len(all_vals)) if all_vals else None
                return {
                    'distribution': [
                        {'value': r[0], 'count': r[1], 'pct': round(r[1] / total * 100)}
                        for r in rows
                    ],
                    'total_picks': int(total),
                    'avg_value':   avg_val,
                }
            except Exception as e:
                print(f"global_stats top_leaders({col}) error: {e}")
                conn.rollback()
                return {'distribution': [], 'total_picks': 0, 'avg_value': None}

        result = {
            'series':      series_stats,
            'playin':      playin_stats,
            'futures':     {
                'top_champions':      top_futures('champion_team_id'),
                'top_west_champs':    top_futures('west_champ_team_id'),
                'top_east_champs':    top_futures('east_champ_team_id'),
                'top_finals_mvp':     top_mvp('finals_mvp'),
                'top_west_finals_mvp': top_mvp('west_finals_mvp'),
                'top_east_finals_mvp': top_mvp('east_finals_mvp'),
            },
            'leaders':     {
                'top_scorer':   top_leaders('top_scorer'),
                'top_assists':  top_leaders('top_assists'),
                'top_rebounds': top_leaders('top_rebounds'),
                'top_threes':   top_leaders('top_threes'),
                'top_steals':   top_leaders('top_steals'),
                'top_blocks':   top_leaders('top_blocks'),
            },
            'total_users': total_users,
        }
        response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=120"
        return result
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
                        at.abbreviation, at.logo_url,
                        s.status, s.winner_team_id,
                        s.actual_leading_scorer, s.actual_leading_rebounder, s.actual_leading_assister
                 FROM series s
                 JOIN teams ht ON s.home_team_id = ht.id
                 JOIN teams at ON s.away_team_id = at.id
                 WHERE s.id = %s""", (series_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Series not found")
    home_id, away_id = row[0], row[1]
    series_status  = row[6]
    winner_team_id = row[7]
    actual_scorer    = row[8]
    actual_rebounder = row[9]
    actual_assister  = row[10]

    # Deduplicate: each user's most recent prediction for this series
    c.execute("""SELECT u.username, u.avatar_url, p.predicted_winner_id, p.predicted_games,
                        COALESCE(t.abbreviation, '?'), COALESCE(t.logo_url, ''),
                        p.is_correct, p.points_earned,
                        p.leading_scorer, p.leading_rebounder, p.leading_assister
                 FROM (
                     SELECT DISTINCT ON (user_id)
                            id, series_id, user_id, predicted_winner_id, predicted_games,
                            is_correct, points_earned,
                            leading_scorer, leading_rebounder, leading_assister
                     FROM predictions
                     WHERE series_id = %s
                     ORDER BY user_id, id DESC
                 ) p
                 JOIN users u ON p.user_id = u.id
                 LEFT JOIN teams t ON p.predicted_winner_id = t.id
                 ORDER BY u.username""", (series_id,))

    picks = []
    home_votes = away_votes = 0
    for r in c.fetchall():
        picks.append({
            'username': r[0], 'avatar_url': r[1] or '',
            'team_id': r[2], 'predicted_games': r[3],
            'team_abbreviation': r[4], 'team_logo_url': r[5],
            'is_correct': r[6], 'points_earned': r[7] or 0,
            'leading_scorer':    r[8],
            'leading_rebounder': r[9],
            'leading_assister':  r[10],
        })
        if r[2] == home_id:   home_votes += 1
        elif r[2] == away_id: away_votes += 1

    total = len(picks)
    conn.close()
    return {
        'series_id':     series_id,
        'series_status': series_status,
        'winner_team_id': winner_team_id,
        'actual_leading_scorer':    actual_scorer,
        'actual_leading_rebounder': actual_rebounder,
        'actual_leading_assister':  actual_assister,
        'picks':         picks,
        'home_votes':    home_votes,
        'away_votes':    away_votes,
        'total_votes':   total,
        'home_pct':      round(home_votes / total * 100) if total else 50,
        'away_pct':      round(away_votes / total * 100) if total else 50,
    }

@app.get("/api/playin/{game_id}/picks")
async def playin_picks(game_id: int):
    """All predictions for a single play-in game — vote counts + per-user picks."""
    conn = get_db_conn()
    c = conn.cursor()

    c.execute("""SELECT pg.team1_id, pg.team2_id, pg.status, pg.winner_id
                 FROM playin_games pg WHERE pg.id = %s""", (game_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Game not found")
    team1_id, team2_id, game_status, winner_id = row

    # Deduplicate: each user's most recent prediction for this game
    c.execute("""SELECT u.username, u.avatar_url, pp.predicted_winner_id,
                        COALESCE(t.abbreviation, '?'), COALESCE(t.logo_url, ''),
                        pp.is_correct, pp.points_earned
                 FROM (
                     SELECT DISTINCT ON (user_id)
                            id, game_id, user_id, predicted_winner_id,
                            is_correct, points_earned
                     FROM playin_predictions
                     WHERE game_id = %s
                     ORDER BY user_id, id DESC
                 ) pp
                 JOIN users u ON pp.user_id = u.id
                 LEFT JOIN teams t ON pp.predicted_winner_id = t.id
                 ORDER BY u.username""", (game_id,))

    picks = []
    t1_votes = t2_votes = 0
    for r in c.fetchall():
        picks.append({
            'username': r[0], 'avatar_url': r[1] or '', 'team_id': r[2],
            'team_abbreviation': r[3], 'team_logo_url': r[4],
            'is_correct': r[5], 'points_earned': r[6] or 0,
        })
        if r[2] == team1_id:   t1_votes += 1
        elif r[2] == team2_id: t2_votes += 1

    total = len(picks)
    conn.close()
    return {
        'game_id':     game_id,
        'game_status': game_status,
        'winner_id':   winner_id,
        'picks':       picks,
        'team1_votes': t1_votes,
        'team2_votes': t2_votes,
        'total_votes': total,
        'team1_pct':   round(t1_votes / total * 100) if total else 50,
        'team2_pct':   round(t2_votes / total * 100) if total else 50,
    }

@app.get("/api/dashboard")
async def dashboard(user_id: int, season: str = "2026"):
    """Lightweight dashboard counts — avoids fetching full prediction/series data."""
    conn = None
    try:
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
        return {
            'series_predicted': row[0] or 0,
            'total_series':     row[1] or 0,
            'futures_done':     (row[2] or 0) > 0,
            'leaders_done':     (row[3] or 0) > 0,
        }
    except Exception as e:
        print(f"dashboard error: {e}")
        raise HTTPException(status_code=500, detail="Failed to load dashboard")
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

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
        # Uses DISTINCT ON to deduplicate same-matchup duplicate DB rows, and
        # checks NOT EXISTS across ALL rows for the same matchup so a prediction
        # on any duplicate series counts as "covered" (prevents false alerts).
        c.execute("""
            SELECT DISTINCT ON (s.conference, s.round,
                                LEAST(s.home_team_id, s.away_team_id),
                                GREATEST(s.home_team_id, s.away_team_id))
                   s.id, s.round, s.conference,
                   ht.abbreviation, at.abbreviation
            FROM series s
            JOIN teams ht ON s.home_team_id = ht.id
            JOIN teams at ON s.away_team_id = at.id
            WHERE s.season = %s AND s.status = 'active'
            AND NOT EXISTS (
                SELECT 1 FROM predictions p
                JOIN series s2 ON p.series_id = s2.id
                WHERE p.user_id = %s
                  AND s2.season = s.season
                  AND s2.round = s.round
                  AND s2.conference = s.conference
                  AND LEAST(s2.home_team_id, s2.away_team_id)
                      = LEAST(s.home_team_id, s.away_team_id)
                  AND GREATEST(s2.home_team_id, s2.away_team_id)
                      = GREATEST(s.home_team_id, s.away_team_id)
            )
            ORDER BY s.conference, s.round,
                     LEAST(s.home_team_id, s.away_team_id),
                     GREATEST(s.home_team_id, s.away_team_id),
                     s.id ASC
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

        # ── 4. Active play-in games with no prediction ──────────────────────
        # DISTINCT ON (conference, game_type) deduplicates same-slot duplicate
        # rows.  NOT EXISTS checks across all rows for the same slot so a
        # prediction on any duplicate counts as "covered".
        c.execute("""
            SELECT DISTINCT ON (pg.conference, pg.game_type)
                   pg.id, t1.abbreviation, t2.abbreviation
            FROM playin_games pg
            JOIN teams t1 ON t1.id = pg.team1_id
            JOIN teams t2 ON t2.id = pg.team2_id
            WHERE pg.season = %s AND pg.status = 'active' AND pg.winner_id IS NULL
            AND NOT EXISTS (
                SELECT 1 FROM playin_predictions pp
                JOIN playin_games pg2 ON pp.game_id = pg2.id
                WHERE pp.user_id = %s
                  AND pg2.season = pg.season
                  AND pg2.conference = pg.conference
                  AND pg2.game_type = pg.game_type
            )
            ORDER BY pg.conference, pg.game_type, pg.id ASC
        """, (season, user_id))
        missing_playin = []
        for row in c.fetchall():
            gid, h_abbr, a_abbr = row
            missing_playin.append({
                'id':       gid,
                'label':    f"{h_abbr} vs {a_abbr}",
                'sublabel': 'Play-In',
            })

        total = len(missing_series) + len(missing_playin) + len(missing_futures) + len(missing_leaders)
        return {
            'missing_series':  missing_series,
            'missing_playin':  missing_playin,
            'missing_futures': missing_futures,
            'missing_leaders': missing_leaders,
            'futures_locked':  futures_locked,
            'total':           total,
        }

    except Exception as e:
        print(f"notifications_summary error: {e}")
        return {'missing_series': [], 'missing_playin': [], 'missing_futures': [], 'missing_leaders': [],
                'futures_locked': False, 'total': 0}
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@app.get("/api/my-predictions")
async def my_predictions(user_id: int, season: str = "2026", viewer_id: int = None):
    """Get predictions for a user.
    viewer_id controls privacy:
      - admin (user 1 / agamital@gmail.com) sees everything
      - user viewing own profile sees everything
      - anyone else only sees predictions for locked/completed games
    """
    conn = None
    try:
        conn = get_db_conn()
        c = conn.cursor()

        # Determine if viewer is admin or the profile owner
        is_admin = False
        if viewer_id:
            c.execute("SELECT email FROM users WHERE id = %s", (viewer_id,))
            vrow = c.fetchone()
            if vrow and vrow[0] in _ADMIN_EMAILS:
                is_admin = True
        is_self = (viewer_id == user_id)
        show_all = is_admin or is_self  # if False: only show locked/completed bets

        now_utc = datetime.utcnow()

        # Get playoff predictions — include game1_start_time + status for lock check
        c.execute('''
            SELECT p.id, p.user_id, p.series_id, p.predicted_winner_id,
                   p.predicted_at, p.is_correct, p.points_earned, p.predicted_games,
                   p.leading_scorer, p.leading_rebounder, p.leading_assister,
                   s.round, s.conference,
                   ht.id, ht.name, ht.abbreviation, ht.logo_url, s.home_seed,
                   at.id, at.name, at.abbreviation, at.logo_url, s.away_seed,
                   wt.name, wt.abbreviation, wt.logo_url,
                   s.status, s.game1_start_time,
                   s.home_wins, s.away_wins,
                   s.actual_leading_scorer, s.actual_leading_rebounder, s.actual_leading_assister
            FROM predictions p
            JOIN series s ON p.series_id = s.id
            JOIN teams ht ON s.home_team_id = ht.id
            JOIN teams at ON s.away_team_id = at.id
            LEFT JOIN teams wt ON p.predicted_winner_id = wt.id
            WHERE p.user_id = %s AND s.season = %s
        ''', (user_id, season))

        playoff_preds = []
        for row in c.fetchall():
            s_status  = row[26]
            g1_start  = row[27]
            home_wins = row[28] or 0
            away_wins = row[29] or 0
            actual_ls = row[30]
            actual_lr = row[31]
            actual_la = row[32]

            # Picks are locked once game1_start_time has passed or series is not active
            picks_locked = (s_status != 'active')
            if not picks_locked and g1_start:
                try:
                    _g1dt = g1_start if hasattr(g1_start, 'year') else datetime.fromisoformat(str(g1_start))
                    picks_locked = now_utc >= _g1dt
                except Exception:
                    pass

            if not show_all and not picks_locked:
                continue  # hide from other viewers until bet time is over

            playoff_preds.append({
                'id': row[0],
                'series_id': row[2],
                'predicted_winner_id': row[3],   # numeric team ID — needed by frontend to highlight pick
                'predicted_games': row[7],
                'leading_scorer': row[8],
                'leading_rebounder': row[9],
                'leading_assister': row[10],
                'actual_leading_scorer':    actual_ls,
                'actual_leading_rebounder': actual_lr,
                'actual_leading_assister':  actual_la,
                'round': row[11],
                'conference': row[12],
                'home_team': {'id': row[13], 'name': row[14], 'abbreviation': row[15], 'logo_url': row[16], 'seed': row[17]},
                'away_team': {'id': row[18], 'name': row[19], 'abbreviation': row[20], 'logo_url': row[21], 'seed': row[22]},
                'predicted_winner': {'name': row[23], 'abbreviation': row[24], 'logo_url': row[25]},
                'predicted_at': row[4],
                'is_correct': row[5],
                'points_earned': row[6] or 0,
                'picks_locked': picks_locked,
                'series_status': s_status,
                'series_finished': (s_status == 'completed'),
                'home_wins': home_wins,
                'away_wins': away_wins,
            })

        # Get play-in predictions — include start_time + winner_id for lock/result check
        c.execute('''
            SELECT pp.id, pp.user_id, pp.game_id, pp.predicted_winner_id,
                   pp.predicted_at, pp.is_correct, pp.points_earned,
                   pg.game_type, pg.conference, pg.winner_id, pg.start_time, pg.status,
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
            pg_winner_id = row[9]
            pg_start     = row[10]
            pg_status    = row[11]

            # Locked once start_time has passed or game is completed
            pi_locked = (pg_status == 'completed') or (pg_winner_id is not None)
            if not pi_locked and pg_start:
                try:
                    _pdt = pg_start if hasattr(pg_start, 'year') else datetime.fromisoformat(str(pg_start))
                    pi_locked = now_utc >= _pdt
                except Exception:
                    pass

            if not show_all and not pi_locked:
                continue

            playin_preds.append({
                'id': row[0],
                'game_id': row[2],
                'predicted_winner_id': row[3],   # numeric team ID — needed by frontend to highlight pick
                'game_type': row[7],
                'conference': row[8],
                'team1': {'name': row[12], 'abbreviation': row[13], 'logo_url': row[14]},
                'team2': {'name': row[15], 'abbreviation': row[16], 'logo_url': row[17]},
                'predicted_winner': {'name': row[18], 'abbreviation': row[19], 'logo_url': row[20]},
                'predicted_at': row[4],
                'is_correct': row[5],
                'points_earned': row[6] or 0,
                'picks_locked': pi_locked,
                'game_finished': pg_status == 'completed',
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
        futures_locked = bool(frow[9]) if frow else False

        # Privacy: futures picks are only visible to others after the user locks them
        futures_pred = None
        if frow and (show_all or futures_locked):
            futures_pred = {
                'champion_team':   {'name': frow[15], 'abbreviation': frow[16], 'logo_url': frow[17]} if frow[15] else None,
                'west_champ_team': {'name': frow[18], 'abbreviation': frow[19], 'logo_url': frow[20]} if frow[18] else None,
                'east_champ_team': {'name': frow[21], 'abbreviation': frow[22], 'logo_url': frow[23]} if frow[21] else None,
                'finals_mvp':      frow[6],
                'west_finals_mvp': frow[7],
                'east_finals_mvp': frow[8],
                'locked':          futures_locked,
                'predicted_at':    frow[10],
                'is_correct_champion': frow[11],
                'is_correct_west':     frow[12],
                'is_correct_east':     frow[13],
                'points_earned':       frow[14] or 0,
            }

        # Get leaders prediction
        c.execute('''SELECT top_scorer, top_assists, top_rebounds, top_threes, top_steals, top_blocks,
                     is_correct_scorer, is_correct_assists, is_correct_rebounds,
                     is_correct_threes, is_correct_steals, is_correct_blocks,
                     points_earned, predicted_at
                     FROM leaders_predictions WHERE user_id = %s AND season = %s''', (user_id, season))
        lrow = c.fetchone()

        # Privacy: leaders lock with futures — only visible to others once futures are locked
        leaders_pred = None
        if lrow and (show_all or futures_locked):
            leaders_pred = {
                'top_scorer':    lrow[0],
                'top_assists':   lrow[1],
                'top_rebounds':  lrow[2],
                'top_threes':    lrow[3],
                'top_steals':    lrow[4],
                'top_blocks':    lrow[5],
                'is_correct_scorer':   lrow[6],
                'is_correct_assists':  lrow[7],
                'is_correct_rebounds': lrow[8],
                'is_correct_threes':   lrow[9],
                'is_correct_steals':   lrow[10],
                'is_correct_blocks':   lrow[11],
                'points_earned': lrow[12] or 0,
                'predicted_at':  lrow[13],
            }

        # Tell the frontend whether futures/leaders exist but are hidden for this viewer
        has_hidden_futures = (not show_all and not futures_locked and frow is not None)
        has_hidden_leaders = (not show_all and not futures_locked and lrow is not None)

        return {
            'playoff_predictions': playoff_preds,
            'playin_predictions': playin_preds,
            'futures_prediction': futures_pred,
            'leaders_prediction': leaders_pred,
            'futures_locked': futures_locked,
            'has_hidden_futures': has_hidden_futures,
            'has_hidden_leaders': has_hidden_leaders,
            'total_predictions': len(playoff_preds) + len(playin_preds)
        }
    except Exception as e:
        print(f"my_predictions error: {e}")
        raise HTTPException(status_code=500, detail="Failed to load predictions")
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

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


@app.post("/api/admin/sync-seeds")
async def admin_sync_seeds(season: str = '2026'):
    """
    Update home_seed / away_seed on existing ACTIVE series and play-in games
    to match current standings — without deleting any series or bets.
    Also calls refresh_playin_matchups() to sync play-in team assignments.
    Use this when seedings shifted but the matchup teams are still correct.
    Use /regenerate-matchups when the actual teams in a matchup need to change.
    """
    conn = None
    updated_series = []
    flagged_series = []
    try:
        conn = get_db_conn()
        c = conn.cursor()

        standings = get_standings()
        if not standings:
            raise HTTPException(503, "No standings data available")

        # Build seed map: team_id -> current conf_rank
        seed_map = {t['team_id']: t['conf_rank'] for t in standings}

        # Update active series seeds
        c.execute("""SELECT id, home_team_id, away_team_id, home_seed, away_seed, conference, round
                     FROM series WHERE season = %s AND status = 'active'""", (season,))
        for row in c.fetchall():
            sid, ht, at, old_hs, old_as, conf, rnd = row
            new_hs = seed_map.get(ht)
            new_as = seed_map.get(at)
            if new_hs is None or new_as is None:
                flagged_series.append({'id': sid, 'reason': 'team not in current standings'})
                continue
            if new_hs != old_hs or new_as != old_as:
                c.execute("UPDATE series SET home_seed=%s, away_seed=%s WHERE id=%s",
                          (new_hs, new_as, sid))
                updated_series.append({'id': sid, 'round': rnd,
                                       'old': f'{old_hs}v{old_as}', 'new': f'{new_hs}v{new_as}'})

        # Update active play-in game seeds
        c.execute("""SELECT id, team1_id, team2_id, team1_seed, team2_seed, conference, game_type
                     FROM playin_games WHERE season = %s AND status = 'active' AND winner_id IS NULL""", (season,))
        updated_playin = []
        for row in c.fetchall():
            pid, t1, t2, old_s1, old_s2, conf, gtype = row
            new_s1 = seed_map.get(t1)
            new_s2 = seed_map.get(t2)
            if new_s1 and new_s2 and (new_s1 != old_s1 or new_s2 != old_s2):
                c.execute("UPDATE playin_games SET team1_seed=%s, team2_seed=%s WHERE id=%s",
                          (new_s1, new_s2, pid))
                updated_playin.append({'id': pid, 'conf': conf, 'game_type': gtype})

        conn.commit()

        # Also run full play-in refresh to catch team changes in 7-10 range
        try:
            playin_refresh = refresh_playin_matchups(season)
        except Exception as pe:
            playin_refresh = {'error': str(pe)}

        return {
            'updated_series': updated_series,
            'flagged_series': flagged_series,
            'updated_playin_seeds': updated_playin,
            'playin_refresh': playin_refresh,
            'message': f'Seeds synced: {len(updated_series)} series updated, {len(updated_playin)} play-in seeds updated'
        }
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            try: conn.rollback()
            except Exception: pass
        raise HTTPException(500, f"sync-seeds error: {e}")
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

@app.get("/api/admin/series")
async def admin_get_series(season: str = "2026"):
    conn = None
    try:
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
                     END,
                     s.actual_leading_scorer, s.actual_leading_rebounder, s.actual_leading_assister
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
                'leading_scorer':    row[19],
                'leading_rebounder': row[20],
                'leading_assister':  row[21],
            })
        return result
    except Exception as e:
        print(f"admin_get_series error: {e}")
        raise HTTPException(status_code=500, detail="Failed to load admin series")
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

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


def _score_playin_game(game_id: int, winner_id: int) -> bool:
    """
    Score playin_predictions for a completed play-in game and recalculate
    all user points.  Idempotent — safe to call multiple times.

    Returns True if scoring ran, False if the game row was not found.
    Called by game_processor.sync_playin_results_from_api so that the
    automated sync pipeline awards points without requiring an admin action.
    """
    conn = None
    try:
        conn = get_db_conn()
        c = conn.cursor()

        c.execute(
            'SELECT team1_id, team1_seed, team2_id, team2_seed FROM playin_games WHERE id = %s',
            (game_id,)
        )
        row = c.fetchone()
        if not row:
            return False

        t1_id, t1_seed, t2_id, t2_seed = row
        winner_seed = t1_seed if winner_id == t1_id else (t2_seed if winner_id == t2_id else None)
        other_seed  = t2_seed if winner_id == t1_id else (t1_seed if winner_id == t2_id else None)
        is_underdog = bool(winner_seed and other_seed and winner_seed > other_seed)

        correct_pts = calculate_play_in_points(True, is_underdog=is_underdog)

        c.execute(
            '''UPDATE playin_predictions
               SET is_correct   = CASE WHEN predicted_winner_id = %s THEN 1 ELSE 0 END,
                   points_earned = CASE WHEN predicted_winner_id = %s THEN %s ELSE 0 END
               WHERE game_id = %s
                 AND is_correct IS NULL''',
            (winner_id, winner_id, correct_pts, game_id)
        )
        _recalculate_all_points(c)
        conn.commit()
        return True
    except Exception as e:
        print(f"[_score_playin_game] error scoring game {game_id}: {e}")
        if conn:
            try: conn.rollback()
            except Exception: pass
        return False
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def _backfill_playin_scores(season: str = "2026") -> dict:
    """
    DB-driven backfill: scores any unscored playin_predictions for completed
    play-in games, then recalculates all user points.

    Does NOT need the ESPN API — reads winner_id directly from playin_games.
    Safe to call on every startup and every sync run (idempotent: only
    touches rows where is_correct IS NULL).

    Returns a summary dict with how many games and rows were processed.
    """
    conn = None
    summary = {"games_checked": 0, "rows_scored": 0, "points_recalculated": False}
    try:
        conn = get_db_conn()
        c = conn.cursor()

        # Find completed play-in games that still have unscored predictions
        c.execute("""
            SELECT pg.id, pg.winner_id, pg.team1_id, pg.team1_seed,
                   pg.team2_id, pg.team2_seed
            FROM playin_games pg
            WHERE pg.season = %s
              AND pg.status = 'completed'
              AND pg.winner_id IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM playin_predictions pp
                  WHERE pp.game_id = pg.id AND pp.is_correct IS NULL
              )
        """, (season,))
        games = c.fetchall()
        summary["games_checked"] = len(games)

        for game_id, winner_id, t1_id, t1_seed, t2_id, t2_seed in games:
            winner_seed = t1_seed if winner_id == t1_id else (t2_seed if winner_id == t2_id else None)
            other_seed  = t2_seed if winner_id == t1_id else (t1_seed if winner_id == t2_id else None)
            is_underdog = bool(winner_seed and other_seed and winner_seed > other_seed)
            correct_pts = calculate_play_in_points(True, is_underdog=is_underdog)

            c.execute(
                """UPDATE playin_predictions
                   SET is_correct    = CASE WHEN predicted_winner_id = %s THEN 1 ELSE 0 END,
                       points_earned = CASE WHEN predicted_winner_id = %s THEN %s ELSE 0 END
                   WHERE game_id = %s AND is_correct IS NULL""",
                (winner_id, winner_id, correct_pts, game_id)
            )
            summary["rows_scored"] += c.rowcount
            print(f"[BackfillPlayin] game {game_id}: scored {c.rowcount} predictions "
                  f"(winner={winner_id}, pts={correct_pts})")

        if summary["rows_scored"] > 0:
            _recalculate_all_points(c)
            summary["points_recalculated"] = True

        conn.commit()
        if summary["games_checked"]:
            print(f"[BackfillPlayin] season={season}: "
                  f"games={summary['games_checked']} rows={summary['rows_scored']}")
        return summary

    except Exception as e:
        print(f"[BackfillPlayin] error: {e}")
        if conn:
            try: conn.rollback()
            except Exception: pass
        return summary
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def _backfill_series_scores(season: str = "2026") -> dict:
    """
    DB-driven backfill: scores any unscored predictions for completed playoff
    series, then recalculates all user points.

    Uses the same scoring logic as game_processor._finalize_series so points
    are consistent. Reads winner_team_id / actual_games / actual leaders
    directly from the series table — no ESPN API needed.
    Idempotent: only touches rows where is_correct IS NULL.

    Returns a summary dict.
    """
    conn = None
    summary = {"series_checked": 0, "rows_scored": 0, "points_recalculated": False}
    try:
        conn = get_db_conn()
        c = conn.cursor()

        # Find completed series that still have unscored predictions
        c.execute("""
            SELECT s.id, s.round, s.conference,
                   s.winner_team_id, s.home_team_id, s.home_seed,
                   s.away_team_id, s.away_seed, s.actual_games,
                   s.actual_leading_scorer, s.actual_leading_rebounder,
                   s.actual_leading_assister
            FROM series s
            WHERE s.season = %s
              AND s.status = 'completed'
              AND s.winner_team_id IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM predictions p
                  WHERE p.series_id = s.id AND p.is_correct IS NULL
              )
        """, (season,))
        series_rows = c.fetchall()
        summary["series_checked"] = len(series_rows)

        for (series_id, round_name, conf,
             winner_id, home_id, home_seed, away_id, away_seed, actual_games,
             actual_scorer, actual_rebounder, actual_assister) in series_rows:

            games = actual_games or 4  # default if not recorded yet
            actual_leaders = {
                "scorer":    actual_scorer,
                "rebounder": actual_rebounder,
                "assister":  actual_assister,
            }

            # Fetch predictions that need scoring
            c.execute(
                """SELECT id, predicted_winner_id, predicted_games,
                          leading_scorer, leading_rebounder, leading_assister
                   FROM predictions
                   WHERE series_id = %s AND is_correct IS NULL""",
                (series_id,)
            )
            for pred_id, pw_id, pred_games, pred_scorer, pred_rebounder, pred_assister \
                    in c.fetchall():
                winner_correct = pw_id == winner_id
                games_correct  = pred_games == games
                games_diff     = abs(pred_games - games) if pred_games is not None else None
                pred_seed      = (home_seed if pw_id == home_id else
                                  away_seed if pw_id == away_id else None)

                pts = calculate_series_points(
                    round_name, home_seed, away_seed, pred_seed,
                    winner_correct=winner_correct,
                    games_correct=games_correct,
                    games_diff=games_diff,
                )
                pts += calculate_series_leader_points(
                    predicted={"scorer":    pred_scorer,
                               "rebounder": pred_rebounder,
                               "assister":  pred_assister},
                    actual=actual_leaders,
                )

                c.execute(
                    """UPDATE predictions
                       SET is_correct    = %s,
                           points_earned = %s
                       WHERE id = %s""",
                    (1 if winner_correct else 0, pts, pred_id)
                )
                summary["rows_scored"] += c.rowcount

            print(f"[BackfillSeries] series {series_id} ({round_name}): backfilled predictions "
                  f"(winner={winner_id}, games={games})")

        if summary["rows_scored"] > 0:
            _recalculate_all_points(c)
            summary["points_recalculated"] = True

        conn.commit()
        if summary["series_checked"]:
            print(f"[BackfillSeries] season={season}: "
                  f"series={summary['series_checked']} rows={summary['rows_scored']}")
        return summary

    except Exception as e:
        print(f"[BackfillSeries] error: {e}")
        if conn:
            try: conn.rollback()
            except Exception: pass
        return summary
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def _try_advance_bracket(c, completed_series_id, season, round_name, conf, bracket_group,
                         winner_team_id, winner_seed=None):
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
        c.execute('''SELECT winner_team_id, home_team_id, away_team_id, home_seed, away_seed
                     FROM series
                     WHERE season = %s AND round = 'Conference Finals' AND status = 'completed'
                     ORDER BY conference''', (season,))
        cf_winners = c.fetchall()
        if len(cf_winners) == 2:
            c.execute("SELECT id FROM series WHERE season = %s AND round = 'NBA Finals'", (season,))
            if not c.fetchone():
                t1, t1_seed = cf_winners[0][0], (cf_winners[0][3] if cf_winners[0][1] == cf_winners[0][0] else cf_winners[0][4])
                t2, t2_seed = cf_winners[1][0], (cf_winners[1][3] if cf_winners[1][1] == cf_winners[1][0] else cf_winners[1][4])
                c.execute('''INSERT INTO series (season, round, conference, home_team_id, away_team_id,
                             home_seed, away_seed, status, bracket_group)
                             VALUES (%s, 'NBA Finals', 'Finals', %s, %s, %s, %s, 'active', 'A')''',
                          (season, t1, t2, t1_seed, t2_seed))
        return

    # Find the partner series in the same bracket_group
    c.execute('''SELECT id, winner_team_id, home_team_id, away_team_id, home_seed, away_seed FROM series
                 WHERE season = %s AND round = %s AND conference = %s
                 AND bracket_group = %s AND status = 'completed' AND id != %s''',
              (season, round_name, conf, bracket_group, completed_series_id))
    partner = c.fetchone()

    if partner:
        partner_winner_id = partner[1]
        # Determine partner winner's seed
        partner_seed = partner[4] if partner[2] == partner_winner_id else partner[5]
        c.execute('''SELECT id FROM series WHERE season = %s AND round = %s
                     AND conference = %s AND bracket_group = %s''',
                  (season, next_round, conf, bracket_group))
        if not c.fetchone():
            c.execute('''INSERT INTO series (season, round, conference, home_team_id, away_team_id,
                         home_seed, away_seed, status, bracket_group)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, 'active', %s)''',
                      (season, next_round, conf, winner_team_id, partner_winner_id,
                       winner_seed, partner_seed, bracket_group))


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
    if actual_games < 4 or actual_games > 7:
        raise HTTPException(status_code=400, detail="actual_games must be between 4 and 7")

    conn = None
    try:
        conn = get_db_conn()
        c = conn.cursor()

        c.execute('''SELECT round, conference, season, bracket_group,
                     home_team_id, away_team_id, home_seed, away_seed, status,
                     actual_leading_scorer, actual_leading_rebounder, actual_leading_assister
                     FROM series WHERE id = %s''', (series_id,))
        series_row = c.fetchone()
        if not series_row:
            raise HTTPException(404, "Series not found")
        round_name, conf, season, bracket_group = series_row[:4]
        home_team_id, away_team_id = series_row[4], series_row[5]
        home_seed, away_seed = series_row[6], series_row[7]
        current_status = series_row[8]
        # Resolve effective leaders: use passed param if provided, else keep existing DB value
        eff_scorer    = actual_leading_scorer    if actual_leading_scorer    is not None else series_row[9]
        eff_rebounder = actual_leading_rebounder if actual_leading_rebounder is not None else series_row[10]
        eff_assister  = actual_leading_assister  if actual_leading_assister  is not None else series_row[11]
        # Treat empty-string as explicit clear
        if actual_leading_scorer    == '': eff_scorer    = None
        if actual_leading_rebounder == '': eff_rebounder = None
        if actual_leading_assister  == '': eff_assister  = None

        # If already completed, zero out old prediction scores before re-scoring
        if current_status == 'completed':
            c.execute('UPDATE predictions SET is_correct = 0, points_earned = 0 WHERE series_id = %s', (series_id,))

        # Mark series completed with manual_override flag and resolved actual leaders
        c.execute('''UPDATE series SET winner_team_id = %s, actual_games = %s, status = %s,
                     manual_override = %s,
                     actual_leading_scorer    = %s,
                     actual_leading_rebounder = %s,
                     actual_leading_assister  = %s
                     WHERE id = %s''',
                  (winner_team_id, actual_games, 'completed', manual_override,
                   eff_scorer, eff_rebounder, eff_assister, series_id))

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
            # Add series leader bonus — uses resolved effective leaders so existing names score correctly
            pts += calculate_series_leader_points(
                {"scorer": pred_scorer, "rebounder": pred_rebounder, "assister": pred_assister},
                {"scorer": eff_scorer, "rebounder": eff_rebounder, "assister": eff_assister},
            )
            is_correct = 1 if winner_correct else 0
            c.execute('UPDATE predictions SET is_correct = %s, points_earned = %s WHERE id = %s',
                      (is_correct, pts, pred_id))

        _recalculate_all_points(c)
        winner_seed = home_seed if winner_team_id == home_team_id else away_seed
        _try_advance_bracket(c, series_id, season, round_name, conf, bracket_group, winner_team_id, winner_seed)

        conn.commit()
        return {"message": "Result set and scores updated", "manual_override": manual_override}
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            try: conn.rollback()
            except Exception: pass
        print(f"set_series_result error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to set result: {e}")
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@app.delete("/api/admin/series/{series_id}/result")
async def reset_series_result(series_id: int):
    """Reset a completed series back to active — zeros out prediction scores and recalculates all points."""
    conn = None
    try:
        conn = get_db_conn()
        c = conn.cursor()

        c.execute("SELECT status FROM series WHERE id = %s", (series_id,))
        row = c.fetchone()
        if not row:
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
        return {"message": "Series result reset — scores recalculated"}
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            try: conn.rollback()
            except Exception: pass
        raise HTTPException(status_code=500, detail=f"Failed to reset series: {e}")
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@app.post("/api/admin/sync-and-advance")
async def sync_and_advance(season: str = "2026"):
    """Re-run bracket advancement for all completed series, score any unscored
    predictions, and recalculate all user points.  Use this as the admin backup
    trigger when the automatic system needs a nudge."""
    conn = None
    try:
        conn = get_db_conn()
        c = conn.cursor()

        c.execute('''SELECT id, round, conference, bracket_group, winner_team_id,
                     home_team_id, home_seed, away_seed
                     FROM series WHERE season = %s AND status = 'completed' ''', (season,))
        completed = c.fetchall()

        for series_id, round_name, conf, bracket_group, winner_team_id, home_team_id, home_seed, away_seed in completed:
            try:
                winner_seed = home_seed if winner_team_id == home_team_id else away_seed
                _try_advance_bracket(c, series_id, season, round_name, conf, bracket_group, winner_team_id, winner_seed)
            except Exception as e:
                print(f"sync_and_advance: failed to advance series {series_id}: {e}")

        _recalculate_all_points(c)
        conn.commit()
    except Exception as e:
        if conn:
            try: conn.rollback()
            except Exception: pass
        print(f"sync_and_advance error: {e}")
        raise HTTPException(status_code=500, detail=f"Sync failed: {e}")
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

    # Also run DB-driven score backfill for any unscored predictions
    pi_bf = _backfill_playin_scores(season)
    s_bf  = _backfill_series_scores(season)

    return {
        "message": f"Synced {len(completed)} completed series — points recalculated",
        "completed_count": len(completed),
        "playin_predictions_scored": pi_bf.get("rows_scored", 0),
        "series_predictions_scored": s_bf.get("rows_scored", 0),
    }


@app.post("/api/admin/backfill-scores")
async def admin_backfill_scores(season: str = "2026"):
    """
    Admin backup: score all unscored predictions for completed play-in games
    and series, then recalculate every user's total points.

    This is the manual safety net — use it when the automatic backfill
    (which runs on startup and every sync cycle) hasn't kicked in yet,
    or to verify that all predictions are correctly scored.
    Idempotent: re-running never double-awards points.
    """
    pi_bf = _backfill_playin_scores(season)
    s_bf  = _backfill_series_scores(season)
    return {
        "message": "Score backfill complete",
        "playin_games_checked":        pi_bf.get("games_checked", 0),
        "playin_predictions_scored":   pi_bf.get("rows_scored",   0),
        "series_checked":              s_bf.get("series_checked", 0),
        "series_predictions_scored":   s_bf.get("rows_scored",    0),
        "points_recalculated":         pi_bf.get("points_recalculated") or s_bf.get("points_recalculated"),
    }

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

        elim_st = PLAYIN_SCHEDULE_UTC.get((conf, 'elimination'))
        c.execute('''INSERT INTO playin_games
                     (season, conference, game_type, team1_id, team1_seed, team2_id, team2_seed, status, start_time)
                     VALUES (%s, %s, 'elimination', %s, %s, %s, %s, 'active', %s)''',
                  (season, conf, loser_id, loser_seed, g9_winner, winner_9_seed, elim_st))
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
        # Check by seed pair OR by team IDs to prevent duplicates
        c.execute('''SELECT id FROM series WHERE season = %s AND conference = %s
                     AND round = 'First Round'
                     AND (
                         (home_seed = 2 AND away_seed = 7)
                         OR (home_team_id = %s AND away_team_id = %s)
                     )''',
                  (season, conf, seed2_id, winner_id))
        existing = c.fetchone()
        _g1_time_7 = _GAME1_SCHEDULE_UTC.get((conf, 2, 7))
        if existing:
            # Series slot exists (possibly pre-created) — update the play-in winner + start time
            c.execute('''UPDATE series SET away_team_id = %s, home_seed = 2, away_seed = 7, status = 'active',
                         game1_start_time = COALESCE(game1_start_time, %s)
                         WHERE id = %s AND (away_team_id IS NULL OR away_team_id != %s)''',
                      (winner_id, _g1_time_7, existing[0], winner_id))
        else:
            c.execute('''INSERT INTO series (season, round, conference, home_team_id, away_team_id,
                         home_seed, away_seed, status, bracket_group, game1_start_time)
                         VALUES (%s, 'First Round', %s, %s, %s, 2, 7, 'active', 'B', %s)''',
                      (season, conf, seed2_id, winner_id, _g1_time_7))
    elif game_type == 'elimination':
        # Winner is the 8-seed → plays 1-seed in R1 Group A
        # Check by seed pair OR by team IDs to prevent duplicates
        c.execute('''SELECT id FROM series WHERE season = %s AND conference = %s
                     AND round = 'First Round'
                     AND (
                         (home_seed = 1 AND away_seed = 8)
                         OR (home_team_id = %s AND away_team_id = %s)
                     )''',
                  (season, conf, seed1_id, winner_id))
        existing = c.fetchone()
        _g1_time_8 = _GAME1_SCHEDULE_UTC.get((conf, 1, 8))
        if existing:
            # Series slot exists — update the play-in winner + start time
            c.execute('''UPDATE series SET away_team_id = %s, home_seed = 1, away_seed = 8, status = 'active',
                         game1_start_time = COALESCE(game1_start_time, %s)
                         WHERE id = %s AND (away_team_id IS NULL OR away_team_id != %s)''',
                      (winner_id, _g1_time_8, existing[0], winner_id))
        else:
            c.execute('''INSERT INTO series (season, round, conference, home_team_id, away_team_id,
                         home_seed, away_seed, status, bracket_group, game1_start_time)
                         VALUES (%s, 'First Round', %s, %s, %s, 1, 8, 'active', 'A', %s)''',
                      (season, conf, seed1_id, winner_id, _g1_time_8))


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

    c.execute('UPDATE playin_predictions SET is_correct = NULL, points_earned = 0 WHERE game_id = %s', (game_id,))
    c.execute("UPDATE playin_games SET winner_id = NULL, status = 'active' WHERE id = %s", (game_id,))
    _recalculate_all_points(c)
    conn.commit()
    conn.close()
    return {"message": "Play-in result reset — scores recalculated"}


@app.delete("/api/admin/playin/{game_id}")
async def delete_playin_game(game_id: int):
    """Delete a play-in game row (ONLY if it has zero user predictions).
    Used to remove incorrectly-auto-created elimination games so the system
    can recreate them correctly once the real results arrive."""
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT game_type, conference, status FROM playin_games WHERE id = %s", (game_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Play-in game not found")
    game_type, conference, status = row
    # Safety: refuse to delete if any user has placed predictions on this game
    c.execute("SELECT COUNT(*) FROM playin_predictions WHERE game_id = %s", (game_id,))
    pred_count = c.fetchone()[0]
    if pred_count > 0:
        conn.close()
        raise HTTPException(400, f"Cannot delete — {pred_count} user predictions exist on this game")
    c.execute("DELETE FROM playin_games WHERE id = %s", (game_id,))
    conn.commit()
    conn.close()
    return {"message": f"Deleted {conference} {game_type} play-in game (id={game_id})"}


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
    Fetch and store per-game player boxscores for a given date (admin, force-bypass TTL).
    date: 'YYYY-MM-DD' or 'YYYYMMDD'.  Defaults to yesterday UTC.
    """
    import concurrent.futures
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        result = await loop.run_in_executor(
            pool,
            lambda: sync_daily_boxscores(date_str=date, season=season,
                                         force=True, triggered_by='admin')
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


@app.get("/api/admin/series-leaders-debug")
async def series_leaders_debug(season: str = "2026"):
    """Return per-series cumulative player totals (pts/reb/ast) so leaders can be verified."""
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("""
        SELECT s.id, ht.abbreviation, at.abbreviation,
               s.home_wins, s.away_wins, s.round,
               s.actual_leading_scorer, s.actual_leading_rebounder, s.actual_leading_assister,
               COALESCE(DATE(s.game1_start_time), '2026-04-18'::date) AS series_start
        FROM series s
        JOIN teams ht ON ht.id = s.home_team_id
        JOIN teams at ON at.id = s.away_team_id
        WHERE s.season = %s AND s.status = 'active'
        ORDER BY s.id
    """, (season,))
    series_rows = c.fetchall()

    result = []
    for sid, home, away, hw, aw, rnd, cur_scorer, cur_reb, cur_ast, series_start in series_rows:
        c.execute("""
            SELECT player_name, team_abbr,
                   SUM(points)   AS tot_pts,
                   SUM(rebounds) AS tot_reb,
                   SUM(assists)  AS tot_ast,
                   COUNT(*)      AS games
            FROM player_game_stats
            WHERE season = %s AND game_date >= %s AND team_abbr IN (%s, %s)
            GROUP BY player_name, team_abbr
            ORDER BY tot_pts DESC
        """, (season, series_start, home, away))
        players = [{"name": r[0], "team": r[1], "pts": r[2], "reb": r[3], "ast": r[4], "gp": r[5]}
                   for r in c.fetchall()]

        top_scorer    = max(players, key=lambda p: p["pts"] or 0) if players else None
        top_rebounder = max(players, key=lambda p: p["reb"] or 0) if players else None
        top_assister  = max(players, key=lambda p: p["ast"] or 0) if players else None

        result.append({
            "series": f"{home} vs {away}",
            "record": f"{hw}-{aw}",
            "round": rnd,
            "db_scorer":    cur_scorer,
            "db_rebounder": cur_reb,
            "db_assister":  cur_ast,
            "computed_scorer":    {"name": top_scorer["name"],    "total": top_scorer["pts"],    "gp": top_scorer["gp"]}    if top_scorer    else None,
            "computed_rebounder": {"name": top_rebounder["name"], "total": top_rebounder["reb"], "gp": top_rebounder["gp"]} if top_rebounder else None,
            "computed_assister":  {"name": top_assister["name"],  "total": top_assister["ast"],  "gp": top_assister["gp"]}  if top_assister  else None,
            "top10_scorers": sorted(players, key=lambda p: p["pts"] or 0, reverse=True)[:5],
        })

    conn.close()
    return result


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
                    params={"date": date_fmt, "limit": 20},
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
    # Iterate over the UNION of DB games and API scoreboard games so that
    # games show up even when player_game_stats hasn't been synced yet.
    all_gids = sorted(set(performers_by_game.keys()) | set(api_games.keys()))
    result = []
    for gid in all_gids:
        info = dict(api_games.get(gid) or {"id": gid, "completed": True,
                                           "status": "Final", "clock": None,
                                           "period": 0, "broadcast": ""})

        # Derive home/away stubs from performers when API data is absent
        if not (info.get("home") or {}).get("abbr"):
            teams = list(dict.fromkeys(p['team_abbr'] for p in performers_by_game.get(gid, [])))
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

        result.append({**info, "performers": performers_by_game.get(gid, [])})

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
        # DB has no data — try live API fetch as fallback
        print(f"[Boxscore] No DB rows for game {espn_game_id} — trying live API fetch")
        try:
            api_players = _fetch_boxscore_primary(espn_game_id)
        except Exception as e:
            print(f"[Boxscore] Live API fetch failed for {espn_game_id}: {e}")
            api_players = []

        if not api_players:
            raise HTTPException(404, "No boxscore data found for this game")

        by_team: dict = defaultdict(list)
        for p in api_players:
            by_team[p['team_abbr']].append({
                'player_name': p.get('player_name', ''),
                'minutes':     round(float(p.get('minutes') or 0), 1),
                'points':      p.get('points', 0),
                'rebounds':    p.get('rebounds', 0),
                'assists':     p.get('assists', 0),
                'steals':      p.get('steals', 0),
                'blocks':      p.get('blocks', 0),
                'fg3m':        p.get('fg3m', 0),
                'turnovers':   p.get('turnovers', 0),
                'fgm':         p.get('fgm', 0),
                'fga':         p.get('fga', 0),
                'plus_minus':  p.get('plus_minus', 0),
            })

        return {
            "espn_game_id": espn_game_id,
            "teams": [{"team_abbr": abbr, "players": players}
                      for abbr, players in by_team.items()],
        }

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
            # ── Source 3: ESPN public scoreboard — no API key needed ──────────
            try:
                print(f"[today-games] Secondary failed ({sec_err}); trying ESPN direct")
                date_fmt2 = date.replace('-', '')
                resp_espn = _http.get(
                    _ESPN_SCOREBOARD_URL2,
                    params={"dates": date_fmt2, "limit": 20},
                    timeout=12,
                )
                resp_espn.raise_for_status()
                espn_data = resp_espn.json()
                source = "espn_direct"
                for ev in (espn_data.get("events") or []):
                    comps = ev.get("competitions") or [{}]
                    comp  = comps[0]
                    teams = comp.get("competitors") or []
                    home_c = next((c for c in teams if c.get("homeAway") == "home"), {})
                    away_c = next((c for c in teams if c.get("homeAway") == "away"), {})
                    stype = (ev.get("status") or {}).get("type") or {}
                    def _te(c):
                        t = c.get("team") or {}
                        return {"id": t.get("id"), "name": t.get("displayName") or t.get("name"),
                                "abbr": t.get("abbreviation"), "score": c.get("score"),
                                "winner": bool(c.get("winner"))}
                    games.append({
                        "id":        str(ev.get("id", "")),
                        "name":      ev.get("name") or ev.get("shortName"),
                        "date":      ev.get("date"),
                        "status":    stype.get("description") or stype.get("name"),
                        "completed": bool(stype.get("completed")),
                        "clock":     (ev.get("status") or {}).get("displayClock"),
                        "period":    (ev.get("status") or {}).get("period"),
                        "broadcast": comp.get("broadcast") or "",
                        "venue":     ((comp.get("venue") or {}).get("fullName") or ""),
                        "home":      _te(home_c),
                        "away":      _te(away_c),
                    })
            except Exception as espn_err:
                raise HTTPException(502, f"All scoreboard sources failed: {espn_err}")

    return {"date": date, "games": games, "count": len(games), "source": source}


def _get_futures_lock() -> bool:
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM site_settings WHERE key = 'futures_locked'")
    row = c.fetchone()
    conn.close()
    return row is not None and row[0] == '1'


def _get_leaders_lock() -> bool:
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM site_settings WHERE key = 'leaders_locked'")
    row = c.fetchone()
    conn.close()
    return row is not None and row[0] == '1'


@app.get("/api/futures/lock-status")
async def futures_lock_status():
    return {"locked": _get_futures_lock()}


@app.get("/api/leaders/lock-status")
async def leaders_lock_status():
    return {"locked": _get_leaders_lock()}


@app.post("/api/admin/leaders/lock")
async def admin_leaders_lock(locked: bool):
    conn = get_db_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO site_settings (key, value) VALUES ('leaders_locked', %s) "
        "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
        ('1' if locked else '0',)
    )
    conn.commit()
    conn.close()
    return {"locked": locked, "message": f"Leaders picks {'locked' if locked else 'unlocked'}"}


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
    # futures_predictions column order (SELECT f.*):
    # 0:id 1:user_id 2:season 3:champion_team_id 4:west_champ_team_id 5:east_champ_team_id
    # 6:finals_mvp 7:west_finals_mvp 8:east_finals_mvp 9:locked 10:predicted_at
    # 11:is_correct_champion 12:is_correct_west 13:is_correct_east 14:points_earned
    # Then joined: 15-17=champion_team, 18-20=west_champ_team, 21-23=east_champ_team
    return {
        "has_prediction": True,
        "champion_team_id": row[3],
        "west_champ_team_id": row[4],
        "east_champ_team_id": row[5],
        "finals_mvp": row[6],
        "west_finals_mvp": row[7],
        "east_finals_mvp": row[8],
        "locked": bool(row[9]),
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






@app.get("/api/players/playoff-highs")
async def get_playoff_highs(response: Response, season: str = "2026"):
    """
    Returns the current single-game playoff record holder for each stat category
    (points, assists, rebounds, 3-pointers, steals, blocks).

    IMPORTANT — only genuine playoff games are considered:
      • game_date >= PLAYOFF_START (day after play-in ends) — excludes regular season
        and play-in games whose stats would otherwise contaminate the max.
      • JOIN to series with an explicit round allowlist — only First Round,
        Conference Semifinals, Conference Finals, NBA Finals.
      • A team that played the play-in and then the playoffs would otherwise have
        its play-in game matched by the series JOIN; the date filter prevents that.

    The record is dynamic: whenever boxscores sync and someone beats the current
    best, the endpoint returns the new holder automatically.
    """
    # 2026 NBA Play-In ended April 18; First Round tip-off: April 19.
    # Any game before this date is regular-season or play-in — excluded.
    PLAYOFF_START = '2026-04-18'

    PLAYOFF_ROUNDS = (
        'First Round',
        'Conference Semifinals',
        'Conference Finals',
        'NBA Finals',
    )

    STATS = [
        ('scorer',   'points'),
        ('assists',  'assists'),
        ('rebounds', 'rebounds'),
        ('threes',   'fg3m'),
        ('steals',   'steals'),
        ('blocks',   'blocks'),
    ]
    conn = None
    try:
        conn = get_db_conn()
        c    = conn.cursor()
        highs = {}

        for cat, col in STATS:
            # ── Step 1: max value — simple date filter only ───────────────────
            # After play-in ends (Apr 18), all remaining games are genuine playoffs.
            # No series JOIN needed here; the date filter is the only gate required.
            c.execute(f"""
                SELECT MAX(pgs.{col})
                FROM player_game_stats pgs
                WHERE pgs.season = %s
                  AND pgs.game_date >= %s
                  AND pgs.{col} > 0
            """, (season, PLAYOFF_START))
            row = c.fetchone()
            if not row or row[0] is None:
                highs[cat] = None
                continue
            max_val = row[0]

            # ── Step 2: who set the record ─────────────────────────────────────
            # Simple fetch — no JOIN fan-out risk. Series context looked up per-row below.
            c.execute(f"""
                SELECT DISTINCT pgs.player_name, pgs.team_abbr, pgs.{col}, pgs.game_date, pgs.espn_game_id
                FROM player_game_stats pgs
                WHERE pgs.season = %s
                  AND pgs.game_date >= %s
                  AND pgs.{col} = %s
                ORDER BY pgs.game_date DESC, pgs.player_name
                LIMIT 10
            """, (season, PLAYOFF_START, max_val))

            rows = c.fetchall()
            if not rows:
                highs[cat] = None
                continue

            # Check for a tie (multiple distinct players with the same max)
            unique_names = list(dict.fromkeys(r[0] for r in rows))  # preserve order, dedupe
            most_recent  = rows[0]  # already ordered by game_date DESC
            team_abbr    = most_recent[1]
            game_date    = most_recent[3]
            espn_game_id = most_recent[4]

            # Look up which playoff round/conference this team is in
            c.execute("""
                SELECT s.round, s.conference,
                       (SELECT COUNT(DISTINCT g.espn_game_id)
                        FROM player_game_stats g
                        JOIN teams tt ON tt.abbreviation = g.team_abbr
                        WHERE g.season = %s AND g.game_date >= %s
                          AND (tt.id = s.home_team_id OR tt.id = s.away_team_id)
                          AND (g.game_date < %s OR
                               (g.game_date = %s AND g.espn_game_id <= %s))
                       ) AS game_number
                FROM series s
                JOIN teams t ON t.abbreviation = %s
                WHERE (s.home_team_id = t.id OR s.away_team_id = t.id)
                  AND s.season = %s
                  AND s.round = ANY(%s)
                ORDER BY s.id DESC
                LIMIT 1
            """, (season, PLAYOFF_START, game_date, game_date, espn_game_id,
                  team_abbr, season, list(PLAYOFF_ROUNDS)))
            series_row = c.fetchone()

            entry = {
                'player_name': most_recent[0],
                'team_abbr':   team_abbr,
                'value':       most_recent[2],
                'game_date':   game_date.isoformat() if game_date else None,
                'round':       series_row[0] if series_row else None,
                'conference':  series_row[1] if series_row else None,
                'game_number': series_row[2] if series_row else None,
            }
            if len(unique_names) > 1:
                entry['tied_players'] = unique_names[:5]
            highs[cat] = entry

        response.headers["Cache-Control"] = "public, max-age=120, stale-while-revalidate=300"
        return {'highs': highs, 'season': season}

    except Exception as e:
        print(f"get_playoff_highs error: {e}")
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
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
            SELECT DISTINCT ON (LOWER(ps.player_name))
                   ps.player_id, ps.player_name, ps.team_abbreviation,
                   COALESCE(ps.pts_per_game, 0) AS ppg,
                   COALESCE(ps.reb_per_game, 0) AS rpg,
                   COALESCE(ps.ast_per_game, 0) AS apg,
                   t.logo_url
            FROM player_stats ps
            LEFT JOIN teams t ON UPPER(t.abbreviation) = UPPER(ps.team_abbreviation)
            WHERE ps.season = %s AND UPPER(ps.team_abbreviation) = ANY(%s)
            ORDER BY LOWER(ps.player_name), ps.pts_per_game DESC NULLS LAST
        """, (season, abbrevs))
        # Extra Python-level dedup by accent-normalized name
        seen: set = set()
        result = []
        for r in c.fetchall():
            norm = _normalize_name(r[1])
            if norm in seen:
                continue
            seen.add(norm)
            result.append({'player_id': r[0], 'name': r[1], 'team': r[2],
                           'ppg': round(float(r[3] or 0), 1),
                           'rpg': round(float(r[4] or 0), 1),
                           'apg': round(float(r[5] or 0), 1),
                           'logo_url': r[6]})
        return result
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
    c.execute("SELECT key, value FROM site_settings WHERE key IN ('futures_locked', 'leaders_locked')")
    lock_rows = {row[0]: row[1] for row in c.fetchall()}
    locked         = lock_rows.get('futures_locked', '0') == '1'
    leaders_locked = lock_rows.get('leaders_locked', '0') == '1'

    conn.close()
    return {
        'teams':          all_teams,
        'west_teams':     west_teams,
        'east_teams':     east_teams,
        'odds':           odds,
        'locked':         locked,
        'leaders_locked': leaders_locked,
    }


# ── Vegas odds used as compass for MVP search ordering ───────────────────────
# American odds → implied probability (normalized, overround removed).
# Used to weight the stats-based mvp_score so that players on title-contending
# teams bubble up even when their raw stats are similar to peers on weaker teams.

def _vegas_team_weights(mvp_type: str) -> dict:
    """
    Return {TEAM_ABBR: weight} where weight = normalized implied probability.
    mvp_type: "finals" uses championship odds,
              "west"   uses West-team championship odds,
              "east"   uses East-team championship odds.
    All other values return an empty dict (no weighting applied).
    Source: Vegas / Polymarket consensus pre-playoffs 2026.
    """
    # American championship odds per team
    CHAMP_ODDS = {
        "OKC": 115,   # West  +115  46.5%
        "SAS": 550,   # West  +550  15.4%
        "BOS": 600,   # East  +600  14.3%
        "CLE": 950,   # East  +950   9.5%
        "DEN": 1100,  # West +1100   8.3%
        "DET": 1400,  # East +1400   6.7%
        "NYK": 1700,  # East +1700   5.6%
        "HOU": 4000,  # West +4000   2.4%
    }
    WEST_TEAMS = {"OKC", "SAS", "DEN", "HOU"}
    EAST_TEAMS = {"BOS", "CLE", "DET", "NYK"}

    if mvp_type == "west":
        pool = {k: v for k, v in CHAMP_ODDS.items() if k in WEST_TEAMS}
    elif mvp_type == "east":
        pool = {k: v for k, v in CHAMP_ODDS.items() if k in EAST_TEAMS}
    elif mvp_type == "finals":
        pool = CHAMP_ODDS
    else:
        return {}

    def impl(odds): return 100.0 / (odds + 100.0)
    raw   = {k: impl(v) for k, v in pool.items()}
    total = sum(raw.values()) or 1.0
    return {k: v / total for k, v in raw.items()}   # normalized [0,1]


@app.get("/api/players/search")
async def search_players(q: str = "", conference: str = "All",
                         limit: int = 15, season: str = "2026",
                         mvp_type: str = ""):
    """
    Player search for MVP autocomplete.
    Merges two sources: player_stats (ESPN full-season) + player_game_stats
    (synced boxscores). Uses GREATEST so full-season wins when available,
    falls back to recent game averages otherwise. Never returns empty results
    for a conference that has players in either source.

    mvp_type: "finals" | "west" | "east" — applies Vegas team-odds weight
              to the mvp_score so that players on title-contending teams
              rank higher when stats are otherwise equal.
    """
    conn = get_db_conn()
    c    = conn.cursor()

    name_filter     = ""
    conf_filter     = ""
    name_params:list = []
    conf_params:list = []

    if q.strip():
        name_filter = "AND LOWER(pname) LIKE LOWER(%s)"
        name_params.append(f"%{q.strip()}%")

    if conference and conference not in ("All", ""):
        conf_filter = """AND UPPER(team) IN (
            SELECT UPPER(abbreviation) FROM teams
            WHERE UPPER(conference) = UPPER(%s)
               OR UPPER(conference) LIKE UPPER(%s) || '%%'
        )"""
        conf_params.extend([conference, conference])

    # Merge full-season (player_stats) + recent boxscore (player_game_stats).
    # Group by lower(player_name) to deduplicate across both sources.
    # GREATEST picks whichever source has higher values.
    # MVP score: PTS*2.0 + REB*1.2 + AST*1.5 + STL*2.0 + BLK*2.0
    c.execute(f'''
        WITH season AS (
            -- full-season averages from ESPN sync
            -- Sanity cap: per-game stats > 60 means ESPN stored season totals,
            -- not per-game averages (bug in parsing). Treat those rows as 0.
            SELECT
                LOWER(player_name)                                        AS lname,
                MAX(player_id)                                            AS player_id,
                MAX(player_name)                                          AS player_name,
                MAX(team_abbreviation)                                    AS team_abbr,
                MAX(CASE WHEN pts_per_game <= 60 THEN pts_per_game ELSE 0 END) AS ppg,
                MAX(CASE WHEN ast_per_game <= 30 THEN ast_per_game ELSE 0 END) AS apg,
                MAX(CASE WHEN reb_per_game <= 30 THEN reb_per_game ELSE 0 END) AS rpg,
                MAX(CASE WHEN stl_per_game <= 10 THEN stl_per_game ELSE 0 END) AS spg,
                MAX(CASE WHEN blk_per_game <= 10 THEN blk_per_game ELSE 0 END) AS bpg
            FROM player_stats
            WHERE season = %s
            GROUP BY LOWER(player_name)
        ),
        recent AS (
            -- per-game averages from synced boxscores (any season games we have)
            SELECT
                LOWER(player_name)                           AS lname,
                MAX(player_name)                             AS player_name,
                MAX(team_abbr)                               AS team_abbr,
                ROUND(AVG(points)::numeric,   1)             AS ppg,
                ROUND(AVG(assists)::numeric,  1)             AS apg,
                ROUND(AVG(rebounds)::numeric, 1)             AS rpg,
                ROUND(AVG(steals)::numeric,   1)             AS spg,
                ROUND(AVG(blocks)::numeric,   1)             AS bpg
            FROM player_game_stats
            WHERE season = %s
              AND (points > 0 OR assists > 0 OR rebounds > 0)
            GROUP BY LOWER(player_name)
            HAVING COUNT(DISTINCT espn_game_id) >= 5
        ),
        merged AS (
            SELECT
                COALESCE(s.lname, r.lname)                           AS lname,
                COALESCE(s.player_name, r.player_name)               AS pname,
                COALESCE(s.team_abbr,   r.team_abbr)                 AS team,
                COALESCE(s.player_id, 0)                             AS player_id,
                GREATEST(COALESCE(s.ppg,0), COALESCE(r.ppg,0))      AS ppg,
                GREATEST(COALESCE(s.apg,0), COALESCE(r.apg,0))      AS apg,
                GREATEST(COALESCE(s.rpg,0), COALESCE(r.rpg,0))      AS rpg,
                GREATEST(COALESCE(s.spg,0), COALESCE(r.spg,0))      AS spg,
                GREATEST(COALESCE(s.bpg,0), COALESCE(r.bpg,0))      AS bpg
            FROM season s
            FULL OUTER JOIN recent r ON s.lname = r.lname
        )
        SELECT
            m.player_id,
            m.pname                                                   AS player_name,
            m.team,
            m.ppg, m.apg, m.rpg, m.spg, m.bpg,
            (m.ppg*2.0 + m.rpg*1.2 + m.apg*1.5 + m.spg*2.0 + m.bpg*2.0) AS mvp_score,
            t.logo_url,
            t.conference
        FROM merged m
        LEFT JOIN teams t ON UPPER(t.abbreviation) = UPPER(m.team)
        WHERE (m.ppg > 0 OR m.apg > 0 OR m.rpg > 0)
          {name_filter}
          {conf_filter}
        ORDER BY mvp_score DESC NULLS LAST, m.pname ASC
        LIMIT %s
    ''', [season, season] + name_params + conf_params + [500 if mvp_type else limit * 3])

    # Vegas team weights — compass for ordering, not raw probability display
    vegas_weights = _vegas_team_weights(mvp_type)

    seen_norm: set = set()
    raw_players = []
    for r in c.fetchall():
        norm = _normalize_name(r[1])
        if norm in seen_norm:
            continue
        seen_norm.add(norm)
        team        = (r[2] or "").upper()
        stats_score = float(r[8] or 0)

        if vegas_weights:
            # Weight = team's normalized implied championship probability.
            # Players on higher-odds teams float up even if stats are similar.
            # Teams not in the Vegas list (non-contenders) get a floor of 0.005.
            w = vegas_weights.get(team, 0.005)
            weighted_score = stats_score * w
        else:
            weighted_score = stats_score

        raw_players.append({
            "player_id":      r[0],
            "name":           r[1],
            "team":           team,
            "ppg":            round(float(r[3] or 0), 1),
            "apg":            round(float(r[4] or 0), 1),
            "rpg":            round(float(r[5] or 0), 1),
            "spg":            round(float(r[6] or 0), 1),
            "bpg":            round(float(r[7] or 0), 1),
            "mvp_score":      round(stats_score, 1),
            "weighted_score": weighted_score,
            "logo_url":       r[9],
            "conference":     r[10],
        })

    for p in raw_players:
        del p["weighted_score"]

    if vegas_weights:
        # Round-robin by team so every team's best player appears before
        # any team's 2nd player.
        # Step 1: group by team, each group sorted by mvp_score desc
        from collections import defaultdict
        team_buckets: dict = defaultdict(list)
        for p in raw_players:
            team_buckets[p["team"]].append(p)
        for bucket in team_buckets.values():
            bucket.sort(key=lambda x: x["mvp_score"], reverse=True)

        # Step 2: order teams by their Vegas weight (best odds first)
        team_order = sorted(team_buckets.keys(),
                            key=lambda t: vegas_weights.get(t, 0),
                            reverse=True)

        # Step 3: interleave — slot 0 of every team, then slot 1, then slot 2
        players = []
        slot = 0
        while len(players) < limit:
            added = False
            for t in team_order:
                bucket = team_buckets[t]
                if slot < len(bucket):
                    players.append(bucket[slot])
                    added = True
                    if len(players) >= limit:
                        break
            if not added:
                break
            slot += 1
    else:
        # No MVP type — pure stats order, no per-team cap
        players = raw_players[:limit]

    conn.close()
    return {"players": players, "total": len(players)}


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
async def get_account(user_id: int, response: Response):
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
    response.headers["Cache-Control"] = "private, max-age=60"
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


@app.post("/api/users/{user_id}/avatar")
async def upload_avatar(user_id: int, file: UploadFile = File(...)):
    """Upload a profile avatar to Supabase Storage and save the public URL."""
    _ALLOWED = {"image/jpeg", "image/png", "image/webp"}
    _EXT_MAP  = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
    if file.content_type not in _ALLOWED:
        raise HTTPException(400, "Only JPEG, PNG, and WebP images are supported")

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(400, "Image must be under 5 MB")

    if not _SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(503,
            "Avatar storage not configured: add SUPABASE_SERVICE_ROLE_KEY in Railway → Settings → Variables. "
            f"(SUPABASE_URL is {'set' if _SUPABASE_URL else 'missing'})"
        )

    ext = _EXT_MAP[file.content_type]
    object_path = f"{user_id}.{ext}"
    upload_url  = f"{_SUPABASE_URL}/storage/v1/object/avatars/{object_path}"

    import requests as _http
    _auth_header = {"Authorization": f"Bearer {_SUPABASE_SERVICE_ROLE_KEY}"}

    # Verify the avatars bucket exists before attempting upload
    bucket_resp = _http.get(
        f"{_SUPABASE_URL}/storage/v1/bucket/avatars",
        headers=_auth_header,
        timeout=8,
    )
    if bucket_resp.status_code == 404:
        print(f"[Supabase] ERROR: 'avatars' bucket not found at {_SUPABASE_URL}")
        raise HTTPException(503,
            "Avatar storage bucket 'avatars' does not exist. "
            "Create it in Supabase Dashboard → Storage → New bucket (name: avatars, public: true)."
        )
    if bucket_resp.status_code not in (200, 201):
        print(f"[Supabase] Bucket check failed ({bucket_resp.status_code}): {bucket_resp.text[:120]}")

    resp = _http.put(
        upload_url,
        data=content,
        headers={**_auth_header, "Content-Type": file.content_type, "x-upsert": "true"},
        timeout=20,
    )
    if resp.status_code not in (200, 201):
        print(f"[Supabase] Upload failed ({resp.status_code}): {resp.text[:200]}")
        raise HTTPException(502, f"Storage upload failed ({resp.status_code}): {resp.text[:200]}")

    public_url = f"{_SUPABASE_URL}/storage/v1/object/public/avatars/{object_path}"
    conn = get_db_conn()
    c    = conn.cursor()
    c.execute("UPDATE users SET avatar_url = %s WHERE id = %s", (public_url, user_id))
    conn.commit()
    conn.close()
    return {"avatar_url": public_url}


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
                   COUNT(DISTINCT pp.id) AS playin_preds,
                   u.reminder_opt_out
            FROM users u
            LEFT JOIN predictions p        ON p.user_id  = u.id
            LEFT JOIN playin_predictions pp ON pp.user_id = u.id
            GROUP BY u.id
            ORDER BY u.points DESC, u.username ASC
        """)
        return [
            {
                "id":                row[0],
                "username":          row[1],
                "email":             row[2],
                "role":              row[3],
                "points":            row[4] or 0,
                "created_at":        row[5].isoformat() if row[5] else None,
                "prediction_count":  (row[6] or 0) + (row[7] or 0),
                "reminder_opt_out":  bool(row[8]),
            }
            for row in c.fetchall()
        ]
    finally:
        conn.close()


@app.patch("/api/admin/users/{user_id}")
async def admin_update_user(
    user_id: int,
    admin_user_id: int,
    username: Optional[str]  = None,
    points: Optional[int]    = None,
    reminder_opt_out: Optional[bool] = None,
):
    """Edit a user's username, points, and/or reminder opt-out. Admin only."""
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
        if reminder_opt_out is not None:
            updates.append("reminder_opt_out = %s")
            values.append(reminder_opt_out)
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
    conn = None
    try:
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
        return {"message": "Futures results set and scores recalculated"}
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            try: conn.rollback()
            except Exception: pass
        print(f"set_futures_results error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to set futures results: {e}")
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


# ── Playoff Leaders ───────────────────────────────────────────────────────────

@app.get("/api/leaders/community-picks")
async def leaders_community_picks(season: str = "2026"):
    """Per-user leaders predictions for community picks display."""
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("""
        SELECT u.username, u.avatar_url,
               lp.top_scorer,   lp.top_assists,  lp.top_rebounds,
               lp.top_threes,   lp.top_steals,   lp.top_blocks,
               lp.is_correct_scorer,   lp.is_correct_assists,  lp.is_correct_rebounds,
               lp.is_correct_threes,   lp.is_correct_steals,   lp.is_correct_blocks,
               lp.points_earned
        FROM leaders_predictions lp
        JOIN users u ON lp.user_id = u.id
        WHERE lp.season = %s
        ORDER BY u.username
    """, (season,))
    rows = c.fetchall()
    conn.close()
    return {
        "picks": [
            {
                "username":           row[0],
                "avatar_url":         row[1],
                "top_scorer":         row[2],
                "top_assists":        row[3],
                "top_rebounds":       row[4],
                "top_threes":         row[5],
                "top_steals":         row[6],
                "top_blocks":         row[7],
                "is_correct_scorer":   row[8],
                "is_correct_assists":  row[9],
                "is_correct_rebounds": row[10],
                "is_correct_threes":   row[11],
                "is_correct_steals":   row[12],
                "is_correct_blocks":   row[13],
                "points_earned":       row[14] or 0,
            }
            for row in rows
        ]
    }


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
    if _get_leaders_lock():
        raise HTTPException(400, "Leaders predictions are locked")
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


def _auto_sync_leaders_actuals(season: str = '2026') -> dict:
    """
    Automatically compute the HIGHEST SINGLE-GAME stat by any player across all
    playoff games played so far, then store them as the provisional/final actuals
    and re-score every leaders_prediction row.

    Uses only games that are recorded in series_processed_events (type='playoff')
    so regular-season and play-in boxscores are excluded.

    Safe to call repeatedly — idempotent; only updates if a new max is found.
    """
    conn = None
    try:
        conn = get_db_conn()
        c = conn.cursor()

        # Max single-game stat across all tracked playoff game boxscores
        c.execute("""
            SELECT
                MAX(pgs.points)   AS max_pts,
                MAX(pgs.assists)  AS max_ast,
                MAX(pgs.rebounds) AS max_reb,
                MAX(pgs.threes)   AS max_3s,
                MAX(pgs.steals)   AS max_stl,
                MAX(pgs.blocks)   AS max_blk
            FROM player_game_stats pgs
            JOIN series_processed_events spe
              ON spe.event_id = pgs.espn_game_id
            WHERE spe.event_type = 'playoff'
        """)
        row = c.fetchone()
        conn.close()
        conn = None

        if not row or all(v is None for v in row):
            return {"skipped": True, "reason": "no playoff boxscores yet"}

        actual = {
            'scorer':   int(row[0]) if row[0] else None,
            'assists':  int(row[1]) if row[1] else None,
            'rebounds': int(row[2]) if row[2] else None,
            'threes':   int(row[3]) if row[3] else None,
            'steals':   int(row[4]) if row[4] else None,
            'blocks':   int(row[5]) if row[5] else None,
        }

        # Persist to site_settings and re-score predictions
        conn = get_db_conn()
        c = conn.cursor()
        for cat, val in actual.items():
            c.execute(
                "INSERT INTO site_settings (key, value) VALUES (%s, %s) "
                "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
                (f'leaders_{cat}_{season}', str(val) if val is not None else '')
            )

        c.execute(
            "SELECT id, top_scorer, top_assists, top_rebounds, top_threes, top_steals, top_blocks "
            "FROM leaders_predictions WHERE season = %s",
            (season,)
        )
        scored = 0
        for lp_id, p_sc, p_ast, p_reb, p_3s, p_stl, p_blk in c.fetchall():
            preds = {
                'scorer': p_sc, 'assists': p_ast, 'rebounds': p_reb,
                'threes': p_3s, 'steals': p_stl, 'blocks': p_blk,
            }
            pts, correct = calculate_leaders_points(preds, actual)
            c.execute(
                """UPDATE leaders_predictions SET
                   is_correct_scorer=%(sc)s, is_correct_assists=%(ast)s,
                   is_correct_rebounds=%(reb)s, is_correct_threes=%(3s)s,
                   is_correct_steals=%(stl)s, is_correct_blocks=%(blk)s,
                   points_earned=%(pts)s
                   WHERE id=%(id)s""",
                {"sc": correct.get("scorer"), "ast": correct.get("assists"),
                 "reb": correct.get("rebounds"), "3s": correct.get("threes"),
                 "stl": correct.get("steals"), "blk": correct.get("blocks"),
                 "pts": pts, "id": lp_id}
            )
            scored += 1

        _recalculate_all_points(c)
        conn.commit()
        print(f"[Leaders Auto-Sync] actual={actual} scored={scored} predictions")
        return {"actual": actual, "predictions_scored": scored}

    except Exception as e:
        print(f"[Leaders Auto-Sync] ERROR: {type(e).__name__}: {e}")
        if conn:
            try: conn.rollback()
            except Exception: pass
        return {"error": str(e)}
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@app.post("/api/admin/leaders/results")
async def set_leaders_results(season: str = "2026",
                               top_scorer: Optional[int] = None, top_assists: Optional[int] = None,
                               top_rebounds: Optional[int] = None, top_threes: Optional[int] = None,
                               top_steals: Optional[int] = None, top_blocks: Optional[int] = None):
    conn = None
    try:
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
        return {"message": "Leaders results set", "results": actual}
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            try: conn.rollback()
            except Exception: pass
        print(f"set_leaders_results error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to set leaders results: {e}")
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


@app.get("/api/fmvp/probability")
async def get_fmvp_probability(season: str = "2026"):
    """
    FMVP probability based on Vegas odds (American format).

    Primary source: hardcoded Vegas FMVP American odds (as of 2026 pre-playoffs).
    Implied probability = 100 / (odds + 100) for positive odds.
    Stats from player_stats + player_game_stats supplement each row with
    season averages and TS% for context.

    Returns top candidates with probability normalized to 100%.
    """
    # ── Vegas FMVP odds (American, positive = underdog) ──────────────────────
    # Source: Polymarket / Vegas consensus pre-playoffs 2026
    VEGAS_FMVP = [
        {"name": "Shai Gilgeous-Alexander", "team": "OKC", "odds": 145,
         "note": "Reigning FMVP; heavy favorite"},
        {"name": "Victor Wembanyama",        "team": "SAS", "odds": 600,
         "note": "Primary upset candidate"},
        {"name": "Nikola Jokic",             "team": "DEN", "odds": 900,
         "note": "Value pick if Denver finds 2023 form"},
        {"name": "Jaylen Brown",             "team": "BOS", "odds": 1200,
         "note": "2024 FMVP; voters trust him in June"},
        {"name": "Jayson Tatum",             "team": "BOS", "odds": 1400,
         "note": "Often moves in tandem with Brown"},
        {"name": "Donovan Mitchell",         "team": "CLE", "odds": 1600,
         "note": "Favorite if Cavs win the East"},
        {"name": "Cade Cunningham",          "team": "DET", "odds": 2500,
         "note": "Longshot despite Detroit's 58-win season"},
        {"name": "Luka Doncic",             "team": "LAL", "odds": 3300,
         "note": "Now with the Lakers"},
    ]

    # ── Vegas Championship odds → team implied Finals probability ─────────────
    VEGAS_CHAMP = {
        "OKC": 115,   # +115  → 46.5%
        "SAS": 550,   # +550  → 15.4%
        "BOS": 600,   # +600  → 14.3%
        "CLE": 950,   # +950  → 9.5%
        "DEN": 1100,  # +1100 → 8.3%
        "DET": 1400,  # +1400 → 6.7%
        "NYK": 1700,  # +1700 → 5.6%
        "HOU": 4000,  # +4000 → 2.4%
    }

    def american_to_implied(odds: int) -> float:
        """Convert positive American odds to implied probability (0–1)."""
        return 100.0 / (odds + 100.0)

    # Implied prob for each FMVP candidate (raw, before overround removal)
    for p in VEGAS_FMVP:
        p["implied_raw"] = american_to_implied(p["odds"])

    # Normalize FMVP implied probs to sum to 100% (remove bookmaker overround)
    total_implied = sum(p["implied_raw"] for p in VEGAS_FMVP)
    for p in VEGAS_FMVP:
        p["probability"] = round(p["implied_raw"] / total_implied * 100, 1)

    # ── Pull season stats from DB to enrich each candidate ───────────────────
    conn = get_db_conn()
    c    = conn.cursor()
    try:
        names_lower = [p["name"].lower() for p in VEGAS_FMVP]

        c.execute('''
            SELECT LOWER(player_name),
                   MAX(pts_per_game), MAX(reb_per_game),
                   MAX(ast_per_game), MAX(stl_per_game), MAX(blk_per_game)
            FROM player_stats
            WHERE season = %s
              AND LOWER(player_name) = ANY(%s)
            GROUP BY LOWER(player_name)
        ''', (season, names_lower))
        stat_rows = {row[0]: row[1:] for row in c.fetchall()}

        c.execute('''
            SELECT LOWER(player_name),
                   SUM(points), SUM(fga), SUM(fta), COUNT(DISTINCT espn_game_id)
            FROM player_game_stats
            WHERE season = %s
              AND (points > 0 OR assists > 0 OR rebounds > 0)
              AND LOWER(player_name) = ANY(%s)
            GROUP BY LOWER(player_name)
        ''', (season, names_lower))
        game_rows = {row[0]: row[1:] for row in c.fetchall()}

        # ── Team championship implied probabilities ────────────────────────────
        team_finals_prob = {}
        raw_total = sum(american_to_implied(v) for v in VEGAS_CHAMP.values())
        for abbr, odds in VEGAS_CHAMP.items():
            team_finals_prob[abbr] = round(
                american_to_implied(odds) / raw_total * 100, 1)

        result = []
        for p in VEGAS_FMVP:
            lname = p["name"].lower()
            sr    = stat_rows.get(lname)
            gr    = game_rows.get(lname)

            ppg = round(float(sr[0] or 0), 1) if sr else 0.0
            rpg = round(float(sr[1] or 0), 1) if sr else 0.0
            apg = round(float(sr[2] or 0), 1) if sr else 0.0
            spg = round(float(sr[3] or 0), 1) if sr else 0.0
            bpg = round(float(sr[4] or 0), 1) if sr else 0.0

            ts_pct = 0.0
            if gr and gr[1] and (float(gr[1]) + 0.44 * float(gr[2] or 0)) > 0:
                denom  = 2 * (float(gr[1]) + 0.44 * float(gr[2]))
                ts_pct = round(float(gr[0]) / denom * 100, 1)

            # Stats-based MVP impact score (context only, not used for prob)
            mvp_score = round(ppg * 2.0 + rpg * 0.5 + apg * 0.7, 1)

            result.append({
                "name":             p["name"],
                "team":             p["team"],
                "odds":             f"+{p['odds']}",
                "probability":      p["probability"],
                "note":             p["note"],
                "team_finals_prob": team_finals_prob.get(p["team"], 0.0),
                "ppg":              ppg,
                "rpg":              rpg,
                "apg":              apg,
                "spg":              spg,
                "bpg":              bpg,
                "ts_pct":           ts_pct,
                "mvp_score":        mvp_score,
            })

        return {
            "top": result,
            "source": "Vegas/Polymarket consensus odds — pre-playoffs 2026",
            "formula": "Implied prob = 100/(odds+100), normalized to remove overround",
        }

    finally:
        conn.close()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
