from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn
from datetime import datetime, timedelta
import sqlite3
import asyncio
import time
import threading
from pathlib import Path

_standings_cache = {"data": None, "expires": None, "fetched_at": None}

# Headers that NBA stats.nba.com requires to not block requests
_NBA_HEADERS = {
    'Host': 'stats.nba.com',
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'x-nba-stats-origin': 'stats',
    'x-nba-stats-token': 'true',
    'Origin': 'https://www.nba.com',
    'Referer': 'https://www.nba.com/',
    'Connection': 'keep-alive',
}
_NBA_TIMEOUT = 60  # seconds

try:
    from nba_api.stats.static import teams as nba_teams_api
    from nba_api.stats.endpoints import leaguestandingsv3
    NBA_API_AVAILABLE = True
except ImportError:
    NBA_API_AVAILABLE = False

app = FastAPI(title="NBA Predictor API")

import os
_FRONTEND_ORIGIN = os.environ.get("FRONTEND_URL", "")
_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "https://nba-playoff-predictor.vercel.app",
]
if _FRONTEND_ORIGIN and _FRONTEND_ORIGIN not in _ALLOWED_ORIGINS:
    _ALLOWED_ORIGINS.append(_FRONTEND_ORIGIN)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = Path(__file__).parent / "nba_predictor.db"

class User(BaseModel):
    username: str
    email: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class Prediction(BaseModel):
    series_id: int
    predicted_winner_id: int
    predicted_games: Optional[int] = None

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT DEFAULT 'user',
        points INTEGER DEFAULT 0
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS teams (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        abbreviation TEXT NOT NULL,
        city TEXT NOT NULL,
        conference TEXT NOT NULL,
        division TEXT,
        logo_url TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS series (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    try:
        c.execute('ALTER TABLE predictions ADD COLUMN predicted_games INTEGER')
    except:
        pass
    # Add actual_games column to series if it doesn't exist
    try:
        c.execute('ALTER TABLE series ADD COLUMN actual_games INTEGER')
    except:
        pass
    
    c.execute('''CREATE TABLE IF NOT EXISTS playin_games (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        game_id INTEGER NOT NULL,
        predicted_winner_id INTEGER NOT NULL,
        predicted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_correct INTEGER,
        points_earned INTEGER DEFAULT 0,
        UNIQUE(user_id, game_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS cached_standings (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
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
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        season TEXT DEFAULT '2026',
        champion_team_id INTEGER,
        west_champ_team_id INTEGER,
        east_champ_team_id INTEGER,
        finals_mvp TEXT,
        west_finals_mvp TEXT,
        east_finals_mvp TEXT,
        locked BOOLEAN DEFAULT 0,
        predicted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_correct_champion INTEGER,
        is_correct_west INTEGER,
        is_correct_east INTEGER,
        points_earned INTEGER DEFAULT 0,
        UNIQUE(user_id, season)
    )''')

    conn.commit()
    conn.close()
    print("Database initialized")

def sync_teams():
    if not NBA_API_AVAILABLE:
        return
    
    teams = nba_teams_api.get_teams()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    eastern = ['ATL','BOS','BKN','CHA','CHI','CLE','DET','IND','MIA','MIL','NYK','ORL','PHI','TOR','WAS']
    
    for team in teams:
        conf = 'Eastern' if team['abbreviation'] in eastern else 'Western'
        c.execute('''INSERT OR REPLACE INTO teams VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (team['id'], team['full_name'], team['abbreviation'], team['city'],
                   conf, '', f"https://cdn.nba.com/logos/nba/{team['id']}/primary/L/logo.svg"))
    
    conn.commit()
    conn.close()
    print(f"Synced {len(teams)} teams")

def _fetch_standings_from_api():
    """
    Single attempt to hit stats.nba.com with proper headers and timeout.
    Returns parsed standings list, or raises on failure.
    """
    standings_api = leaguestandingsv3.LeagueStandingsV3(
        season='2025-26',
        headers=_NBA_HEADERS,
        timeout=_NBA_TIMEOUT,
    )
    raw = standings_api.get_dict()

    result_set = raw['resultSets'][0]
    col_headers = result_set['headers']
    rows        = result_set['rowSet']

    def col(row, name):
        return row[col_headers.index(name)]

    standings = []
    for row in rows:
        standings.append({
            'team_id':    col(row, 'TeamID'),
            'team_name':  f"{col(row, 'TeamCity')} {col(row, 'TeamName')}",
            'conference': col(row, 'Conference'),   # 'East' or 'West'
            'wins':       int(col(row, 'WINS')),
            'losses':     int(col(row, 'LOSSES')),
            'win_pct':    float(col(row, 'WinPCT')),
            'conf_rank':  99,
            'playoff_rank': 99,
        })

    # Recompute ranks by win_pct, ties broken by wins
    for conf in ['East', 'West']:
        conf_teams = sorted(
            [t for t in standings if t['conference'] == conf],
            key=lambda x: (-x['win_pct'], -x['wins'])
        )
        for idx, team in enumerate(conf_teams, 1):
            team['conf_rank'] = idx
            team['playoff_rank'] = idx

    return standings


def _refresh_standings_cache(force=False):
    """
    Fetch fresh standings with up to 2 attempts (retry once after 5s delay).
    Updates _standings_cache on success; keeps old data on failure.
    """
    if not NBA_API_AVAILABLE:
        return

    now = datetime.now()
    cache_valid = (
        _standings_cache["data"] is not None and
        _standings_cache["expires"] is not None and
        now < _standings_cache["expires"]
    )
    if cache_valid and not force:
        return  # Still fresh, nothing to do

    last_error = None
    for attempt in range(1, 3):          # attempt 1, then retry (attempt 2)
        try:
            print(f"Standings fetch attempt {attempt}…")
            standings = _fetch_standings_from_api()
            now = datetime.now()
            _standings_cache["data"]       = standings
            _standings_cache["fetched_at"] = now
            _standings_cache["expires"]    = now + timedelta(minutes=5)
            print(f"Standings refreshed at {now.strftime('%H:%M:%S')} — {len(standings)} teams")
            return
        except Exception as e:
            last_error = e
            print(f"Standings attempt {attempt} failed: {e}")
            if attempt < 2:
                print("Retrying in 5 s…")
                time.sleep(5)

    # Both attempts failed — keep stale cache, just log
    print(f"Standings unavailable after 2 attempts. Keeping cached data. Last error: {last_error}")


def _load_standings_from_db():
    """Read manually-seeded standings from the cached_standings DB table."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''SELECT team_id, team_name, conference, wins, losses, win_pct, conf_rank
                     FROM cached_standings WHERE season = '2026' ORDER BY conference, conf_rank''')
        rows = c.fetchall()
        conn.close()
        if not rows:
            return []
        return [
            {'team_id': r[0], 'team_name': r[1], 'conference': r[2],
             'wins': r[3], 'losses': r[4], 'win_pct': r[5],
             'conf_rank': r[6], 'playoff_rank': r[6]}
            for r in rows
        ]
    except Exception as e:
        print(f"DB standings load error: {e}")
        return []


def get_standings(force_refresh=False):
    """
    Returns standings. Priority:
      1. In-memory cache (if still fresh and not forced)
      2. Live NBA API fetch (with retry)
      3. DB-stored manual standings (seed_standings.py fallback)
    """
    _refresh_standings_cache(force=force_refresh)

    if _standings_cache["data"]:
        return _standings_cache["data"]

    # API failed — fall back to DB-seeded standings
    db_data = _load_standings_from_db()
    if db_data:
        print("Using DB-seeded standings (NBA API unavailable)")
        # Populate cache so subsequent calls don't hit DB every time
        now = datetime.now()
        _standings_cache["data"]       = db_data
        _standings_cache["fetched_at"] = now
        _standings_cache["expires"]    = now + timedelta(hours=1)
    return db_data


def _background_standings_loop():
    """
    Background thread: tries to refresh standings from NBA API every 6 hours.
    Starts with a jitter delay so it doesn't block startup.
    Falls back to DB data if API is unavailable — the main cache already has DB data.
    """
    import random
    delay = random.uniform(10, 40)
    print(f"Background NBA API standings refresh starts in {delay:.0f}s")
    time.sleep(delay)

    while True:
        try:
            print("Background: attempting live standings fetch…")
            fresh = _fetch_standings_from_api()
            now = datetime.now()
            _standings_cache["data"]       = fresh
            _standings_cache["fetched_at"] = now
            _standings_cache["expires"]    = now + timedelta(minutes=5)
            print(f"Background: standings updated from NBA API — {len(fresh)} teams")
        except Exception as e:
            print(f"Background: NBA API unavailable ({e}), keeping current standings")
        time.sleep(6 * 60 * 60)

def generate_matchups(force_conference=None):
    standings = get_standings()
    if not standings:
        print("No standings data, skipping matchup generation")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    for conf_short in ['East', 'West']:
        conf_full = 'Eastern' if conf_short == 'East' else 'Western'

        # If forcing a specific conference, skip others
        if force_conference and conf_full != force_conference:
            continue

        # Check what already exists for this conference
        c.execute('SELECT COUNT(*) FROM series WHERE season = ? AND conference = ?', ('2026', conf_full))
        series_count = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM playin_games WHERE season = ? AND conference = ?', ('2026', conf_full))
        playin_count = c.fetchone()[0]

        print(f"{conf_full}: found {series_count} series, {playin_count} play-in games in DB")
        if series_count >= 2 and playin_count >= 2 and not force_conference:
            print(f"  -> {conf_full} already complete, skipping")
            continue

        teams = sorted([t for t in standings if t['conference'] == conf_short],
                       key=lambda x: x['conf_rank'])[:10]

        if len(teams) < 6:
            print(f"Not enough {conf_full} teams ({len(teams)}), skipping")
            continue

        # Create playoff series (3v6, 4v5) — replace if forcing
        if series_count < 2 or force_conference:
            c.execute('DELETE FROM series WHERE season = ? AND conference = ?', ('2026', conf_full))
            matchups = [(teams[2], teams[5]), (teams[3], teams[4])]
            for home, away in matchups:
                c.execute('''INSERT INTO series (season, round, conference, home_team_id, away_team_id,
                            home_seed, away_seed, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                         ('2026', 'First Round', conf_full, home['team_id'], away['team_id'],
                          home['conf_rank'], away['conf_rank'], 'active'))
                print(f"  -> #{home['conf_rank']} {home['team_name']} vs #{away['conf_rank']} {away['team_name']}")
            print(f"  Created {conf_full} R1 series (3v6, 4v5)")

        # Create play-in games (7v8, 9v10) — replace if forcing
        if len(teams) >= 10 and (playin_count < 2 or force_conference):
            c.execute('DELETE FROM playin_games WHERE season = ? AND conference = ?', ('2026', conf_full))
            for game_type, idx1, idx2 in [('7v8', 6, 7), ('9v10', 8, 9)]:
                c.execute('''INSERT INTO playin_games (season, conference, game_type, team1_id, team1_seed,
                            team2_id, team2_seed, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for email in _ADMIN_EMAILS:
        c.execute("UPDATE users SET role='admin' WHERE email=? AND role != 'admin'", (email,))
        if c.rowcount:
            print(f"Promoted {email} to admin")
    conn.commit()
    conn.close()

@app.on_event("startup")
async def startup():
    init_db()
    sync_teams()
    ensure_admin_users()

    # Step 1: immediately load DB-seeded standings into memory cache (instant, no API call)
    db_standings = _load_standings_from_db()
    if db_standings:
        now = datetime.now()
        _standings_cache["data"]       = db_standings
        _standings_cache["fetched_at"] = now
        _standings_cache["expires"]    = now + timedelta(hours=1)
        print(f"Pre-loaded {len(db_standings)} teams from DB standings cache")

    # Step 2: run matchup generation in background (uses DB standings if API is down)
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, generate_matchups)

    # Step 3: start background thread that tries live NBA API every 6 hours
    t = threading.Thread(target=_background_standings_loop, daemon=True)
    t.start()

@app.get("/")
async def root():
    return {"message": "NBA Predictor API", "version": "2.0", "nba_api": NBA_API_AVAILABLE}

@app.get("/api/standings")
async def api_standings(force_refresh: bool = False):
    standings = get_standings(force_refresh=force_refresh)
    eastern = sorted([t for t in standings if t['conference'] == 'East'], key=lambda x: x['conf_rank'])
    western = sorted([t for t in standings if t['conference'] == 'West'], key=lambda x: x['conf_rank'])
    fetched_at = _standings_cache.get("fetched_at")
    cache_age_minutes = None
    if fetched_at:
        cache_age_minutes = round((datetime.now() - fetched_at).total_seconds() / 60, 1)
    return {
        "eastern": eastern,
        "western": western,
        "last_updated": fetched_at.isoformat() if fetched_at else None,
        "cache_age_minutes": cache_age_minutes,
        "cache_expires": _standings_cache["expires"].isoformat() if _standings_cache.get("expires") else None,
    }

@app.get("/api/teams")
async def api_teams(conference: Optional[str] = None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    if conference:
        c.execute('SELECT * FROM teams WHERE conference = ?', (conference,))
    else:
        c.execute('SELECT * FROM teams')
    
    teams = []
    for row in c.fetchall():
        teams.append({'id': row[0], 'name': row[1], 'abbreviation': row[2],
                     'city': row[3], 'conference': row[4], 'division': row[5], 'logo_url': row[6]})
    
    conn.close()
    return teams

@app.post("/api/auth/register")
async def register(user: User):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute('INSERT INTO users (username, email, password) VALUES (?, ?, ?)',
                  (user.username, user.email, user.password))
        conn.commit()
        user_id = c.lastrowid
        conn.close()
        return {"user_id": user_id, "username": user.username}
    except:
        conn.close()
        raise HTTPException(400, "User exists")

@app.get("/api/auth/me")
async def get_me(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "User not found")
    return {"user_id": row[0], "username": row[1], "email": row[2], "role": row[4], "points": row[5]}

@app.post("/api/auth/login")
async def login(creds: UserLogin):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE username = ? AND password = ?', (creds.username, creds.password))
    row = c.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(401, "Invalid credentials")
    
    return {"user_id": row[0], "username": row[1], "email": row[2], "role": row[4], "points": row[5]}

@app.get("/api/series")
async def api_series(season: str = "2026"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # CRITICAL: Column order must match team table structure!
    c.execute('''SELECT 
                 s.id, s.season, s.round, s.conference,
                 s.home_team_id, s.home_seed, s.home_wins,
                 s.away_team_id, s.away_seed, s.away_wins,
                 s.winner_team_id, s.status,
                 ht.name, ht.abbreviation, ht.logo_url,
                 at.name, at.abbreviation, at.logo_url
                 FROM series s
                 JOIN teams ht ON s.home_team_id = ht.id
                 JOIN teams at ON s.away_team_id = at.id 
                 WHERE s.season = ?''', (season,))
    
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
                'name': row[12],
                'abbreviation': row[13],
                'logo_url': row[14]
            },
            'away_team': {
                'id': row[7],
                'seed': row[8],
                'name': row[15],
                'abbreviation': row[16],
                'logo_url': row[17]
            },
            'home_wins': row[6],
            'away_wins': row[9],
            'winner_team_id': row[10],
            'status': row[11]
        })
    
    conn.close()
    return series

@app.get("/api/playin-games")
async def api_playin(season: str = "2026"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''SELECT p.*, t1.name, t1.abbreviation, t1.logo_url,
                 t2.name, t2.abbreviation, t2.logo_url FROM playin_games p
                 JOIN teams t1 ON p.team1_id = t1.id
                 JOIN teams t2 ON p.team2_id = t2.id WHERE p.season = ?''', (season,))
    
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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO predictions (user_id, series_id, predicted_winner_id, predicted_games)
                 VALUES (?, ?, ?, ?) ON CONFLICT(user_id, series_id)
                 DO UPDATE SET predicted_winner_id = ?, predicted_games = ?''',
              (user_id, prediction.series_id, prediction.predicted_winner_id, prediction.predicted_games,
               prediction.predicted_winner_id, prediction.predicted_games))
    conn.commit()
    conn.close()
    return {"message": "Saved"}

@app.post("/api/playin-predictions")
async def playin_pred(game_id: int, predicted_winner_id: int, user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO playin_predictions (user_id, game_id, predicted_winner_id)
                 VALUES (?, ?, ?) ON CONFLICT(user_id, game_id) 
                 DO UPDATE SET predicted_winner_id = ?''',
              (user_id, game_id, predicted_winner_id, predicted_winner_id))
    conn.commit()
    conn.close()
    return {"message": "Saved"}

@app.get("/api/leaderboard")
async def leaderboard(season: str = "2026"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT u.id, u.username, u.points, COUNT(p.id),
                 SUM(CASE WHEN p.is_correct = 1 THEN 1 ELSE 0 END)
                 FROM users u LEFT JOIN predictions p ON u.id = p.user_id
                 GROUP BY u.id ORDER BY u.points DESC LIMIT 100''')
    
    board = []
    for idx, row in enumerate(c.fetchall(), 1):
        total, correct = row[3] or 0, row[4] or 0
        board.append({'rank': idx, 'user_id': row[0], 'username': row[1], 'points': row[2],
                     'total_predictions': total, 'correct_predictions': correct,
                     'accuracy': round((correct/total*100) if total > 0 else 0, 1)})
    
    conn.close()
    return board
@app.get("/api/my-predictions")
async def my_predictions(user_id: int, season: str = "2026"):
    """Get all predictions for a user"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Get playoff predictions
    c.execute('''
        SELECT p.*, s.round, s.conference,
               ht.name, ht.abbreviation, ht.logo_url,
               at.name, at.abbreviation, at.logo_url,
               wt.name, wt.abbreviation, wt.logo_url
        FROM predictions p
        JOIN series s ON p.series_id = s.id
        JOIN teams ht ON s.home_team_id = ht.id
        JOIN teams at ON s.away_team_id = at.id
        LEFT JOIN teams wt ON p.predicted_winner_id = wt.id
        WHERE p.user_id = ? AND s.season = ?
    ''', (user_id, season))
    
    playoff_preds = []
    for row in c.fetchall():
        playoff_preds.append({
            'id': row[0],
            'series_id': row[2],
            'predicted_games': row[7],
            'round': row[8],
            'conference': row[9],
            'home_team': {'name': row[10], 'abbreviation': row[11], 'logo_url': row[12]},
            'away_team': {'name': row[13], 'abbreviation': row[14], 'logo_url': row[15]},
            'predicted_winner': {'name': row[16], 'abbreviation': row[17], 'logo_url': row[18]},
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
        WHERE pp.user_id = ? AND pg.season = ?
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
        WHERE f.user_id = ? AND f.season = ?
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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM series WHERE season = ?', (season,))
    series = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM playin_games WHERE season = ?', (season,))
    playin = c.fetchone()[0]
    conn.close()
    return {"message": "Done", "series_count": series, "playin_count": playin}

@app.get("/api/admin/series")
async def admin_get_series(season: str = "2026"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT s.id, s.round, s.conference, s.status, s.winner_team_id, s.actual_games,
                 ht.id, ht.name, ht.abbreviation, ht.logo_url,
                 at.id, at.name, at.abbreviation, at.logo_url,
                 wt.name, wt.abbreviation,
                 COUNT(p.id)
                 FROM series s
                 JOIN teams ht ON s.home_team_id = ht.id
                 JOIN teams at ON s.away_team_id = at.id
                 LEFT JOIN teams wt ON s.winner_team_id = wt.id
                 LEFT JOIN predictions p ON s.id = p.series_id
                 WHERE s.season = ? GROUP BY s.id''', (season,))
    result = []
    for row in c.fetchall():
        result.append({
            'id': row[0], 'round': row[1], 'conference': row[2],
            'status': row[3], 'winner_team_id': row[4], 'actual_games': row[5],
            'home_team': {'id': row[6], 'name': row[7], 'abbreviation': row[8], 'logo_url': row[9]},
            'away_team': {'id': row[10], 'name': row[11], 'abbreviation': row[12], 'logo_url': row[13]},
            'winner_name': row[14], 'winner_abbreviation': row[15],
            'prediction_count': row[16]
        })
    conn.close()
    return result

@app.post("/api/admin/series/{series_id}/result")
async def set_series_result(series_id: int, winner_team_id: int, actual_games: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Update series
    c.execute('UPDATE series SET winner_team_id = ?, actual_games = ?, status = ? WHERE id = ?',
              (winner_team_id, actual_games, 'completed', series_id))
    # Score predictions: 2pts correct winner, +1 bonus for correct games
    c.execute('''UPDATE predictions SET
                 is_correct = CASE WHEN predicted_winner_id = ? THEN 1 ELSE 0 END,
                 points_earned = CASE
                     WHEN predicted_winner_id = ? AND predicted_games = ? THEN 3
                     WHEN predicted_winner_id = ? THEN 2
                     ELSE 0 END
                 WHERE series_id = ?''',
              (winner_team_id, winner_team_id, actual_games, winner_team_id, series_id))
    # Recalculate user points
    c.execute('''UPDATE users SET points = (
                 SELECT COALESCE(SUM(p.points_earned),0) FROM predictions p WHERE p.user_id = users.id
                 ) + (
                 SELECT COALESCE(SUM(pp.points_earned),0) FROM playin_predictions pp WHERE pp.user_id = users.id
                 )''')
    conn.commit()
    conn.close()
    return {"message": "Result set and scores updated"}

@app.get("/api/admin/playin")
async def admin_get_playin(season: str = "2026"):
    conn = sqlite3.connect(DB_PATH)
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
                 WHERE p.season = ? GROUP BY p.id''', (season,))
    result = []
    for row in c.fetchall():
        result.append({
            'id': row[0], 'conference': row[1], 'game_type': row[2],
            'winner_id': row[3], 'status': row[4],
            'team1': {'id': row[5], 'name': row[6], 'abbreviation': row[7], 'logo_url': row[8]},
            'team2': {'id': row[9], 'name': row[10], 'abbreviation': row[11], 'logo_url': row[12]},
            'winner_name': row[13], 'winner_abbreviation': row[14],
            'prediction_count': row[15]
        })
    conn.close()
    return result

@app.post("/api/admin/playin/{game_id}/result")
async def set_playin_result(game_id: int, winner_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE playin_games SET winner_id = ?, status = ? WHERE id = ?',
              (winner_id, 'completed', game_id))
    c.execute('''UPDATE playin_predictions SET
                 is_correct = CASE WHEN predicted_winner_id = ? THEN 1 ELSE 0 END,
                 points_earned = CASE WHEN predicted_winner_id = ? THEN 1 ELSE 0 END
                 WHERE game_id = ?''', (winner_id, winner_id, game_id))
    c.execute('''UPDATE users SET points = (
                 SELECT COALESCE(SUM(p.points_earned),0) FROM predictions p WHERE p.user_id = users.id
                 ) + (
                 SELECT COALESCE(SUM(pp.points_earned),0) FROM playin_predictions pp WHERE pp.user_id = users.id
                 )''')
    conn.commit()
    conn.close()
    return {"message": "Play-in result set"}

def _get_futures_lock() -> bool:
    conn = sqlite3.connect(DB_PATH)
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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO site_settings (key, value) VALUES ('futures_locked', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        ('1' if locked else '0',)
    )
    conn.commit()
    conn.close()
    return {"locked": locked, "message": f"Futures {'locked' if locked else 'unlocked'}"}


@app.get("/api/futures")
async def get_futures(user_id: int, season: str = "2026"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT f.*,
                 tc.name, tc.abbreviation, tc.logo_url,
                 tw.name, tw.abbreviation, tw.logo_url,
                 te.name, te.abbreviation, te.logo_url
                 FROM futures_predictions f
                 LEFT JOIN teams tc ON f.champion_team_id = tc.id
                 LEFT JOIN teams tw ON f.west_champ_team_id = tw.id
                 LEFT JOIN teams te ON f.east_champ_team_id = te.id
                 WHERE f.user_id = ? AND f.season = ?''', (user_id, season))
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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Check global lock first
    if _get_futures_lock():
        conn.close()
        raise HTTPException(status_code=400, detail="Futures predictions are locked by admin")
    # Check per-user lock
    c.execute('SELECT locked FROM futures_predictions WHERE user_id = ? AND season = ?', (user_id, season))
    existing = c.fetchone()
    if existing and existing[0]:
        conn.close()
        raise HTTPException(status_code=400, detail="Predictions are locked")
    c.execute('''INSERT INTO futures_predictions
                 (user_id, season, champion_team_id, west_champ_team_id, east_champ_team_id,
                  finals_mvp, west_finals_mvp, east_finals_mvp, predicted_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                 ON CONFLICT(user_id, season) DO UPDATE SET
                 champion_team_id = excluded.champion_team_id,
                 west_champ_team_id = excluded.west_champ_team_id,
                 east_champ_team_id = excluded.east_champ_team_id,
                 finals_mvp = excluded.finals_mvp,
                 west_finals_mvp = excluded.west_finals_mvp,
                 east_finals_mvp = excluded.east_finals_mvp,
                 predicted_at = CURRENT_TIMESTAMP''',
              (user_id, season, champion_team_id, west_champ_team_id, east_champ_team_id,
               finals_mvp, west_finals_mvp, east_finals_mvp))
    conn.commit()
    conn.close()
    return {"message": "Saved"}

@app.get("/api/futures/leaderboard")
async def futures_leaderboard(season: str = "2026"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT u.username, f.points_earned,
                 f.is_correct_champion, f.is_correct_west, f.is_correct_east,
                 tc.name, tc.logo_url, tw.name, tw.logo_url, te.name, te.logo_url
                 FROM futures_predictions f
                 JOIN users u ON f.user_id = u.id
                 LEFT JOIN teams tc ON f.champion_team_id = tc.id
                 LEFT JOIN teams tw ON f.west_champ_team_id = tw.id
                 LEFT JOIN teams te ON f.east_champ_team_id = te.id
                 WHERE f.season = ?
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
    conn = sqlite3.connect(DB_PATH)
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
        WHERE f.season = ?
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
    """Returns the raw column headers + top 6 rows from the NBA API.
    Use this to verify the API is returning current data and column names are correct."""
    if not NBA_API_AVAILABLE:
        return {"error": "nba_api not installed"}
    try:
        standings_api = leaguestandingsv3.LeagueStandingsV3(season='2025-26')
        raw = standings_api.get_dict()
        result_set = raw['resultSets'][0]
        headers = result_set['headers']
        rows = result_set['rowSet']

        # Return headers + a sample of rows as dicts for easy inspection
        sample = [dict(zip(headers, row)) for row in rows[:6]]
        return {
            "fetched_at": datetime.now().isoformat(),
            "total_rows": len(rows),
            "headers": headers,
            "sample_rows": sample,
            "cache_info": {
                "fetched_at": _standings_cache.get("fetched_at", None) and _standings_cache["fetched_at"].isoformat(),
                "expires": _standings_cache.get("expires", None) and _standings_cache["expires"].isoformat(),
            }
        }
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)