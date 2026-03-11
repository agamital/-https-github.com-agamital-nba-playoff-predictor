from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn
from datetime import datetime, timedelta
import sqlite3
from pathlib import Path

_standings_cache = {"data": None, "expires": None}

try:
    from nba_api.stats.static import teams as nba_teams_api
    from nba_api.stats.endpoints import leaguestandingsv3
    NBA_API_AVAILABLE = True
except ImportError:
    NBA_API_AVAILABLE = False

app = FastAPI(title="NBA Predictor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

def get_standings():
    if not NBA_API_AVAILABLE:
        return []

    now = datetime.now()
    if _standings_cache["data"] and _standings_cache["expires"] and now < _standings_cache["expires"]:
        return _standings_cache["data"]

    try:
        api = leaguestandingsv3.LeagueStandingsV3(season='2025-26')
        data = api.get_dict()
        
        standings = []
        rows = data['resultSets'][0]['rowSet']
        
        for row in rows:
            standings.append({
                'team_id': row[2],
                'team_name': f"{row[3]} {row[4]}",
                'conference': row[6],
                'wins': row[13],
                'losses': row[14],
                'win_pct': float(row[15]),
                'conf_rank': row[8] if row[8] else 99,
                'playoff_rank': row[8] if row[8] else 99
            })
        
        # Fix ranks
        for conf in ['East', 'West']:
            conf_teams = sorted([t for t in standings if t['conference'] == conf], 
                              key=lambda x: -x['win_pct'])
            for idx, team in enumerate(conf_teams, 1):
                team['conf_rank'] = idx
                team['playoff_rank'] = idx
        
        _standings_cache["data"] = standings
        _standings_cache["expires"] = now + timedelta(minutes=10)
        return standings
    except Exception as e:
        print(f"Error: {e}")
        return _standings_cache["data"] or []

def generate_matchups():
    standings = get_standings()
    if not standings:
        return
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # DELETE OLD PREDICTIONS WHEN REGENERATING
    c.execute('DELETE FROM predictions WHERE series_id IN (SELECT id FROM series WHERE season = ?)', ('2026',))
    c.execute('DELETE FROM playin_predictions WHERE game_id IN (SELECT id FROM playin_games WHERE season = ?)', ('2026',))
    
    c.execute('DELETE FROM series WHERE season = ?', ('2026',))
    c.execute('DELETE FROM playin_games WHERE season = ?', ('2026',))
    
    
    for conf_short in ['East', 'West']:
        conf_full = 'Eastern' if conf_short == 'East' else 'Western'
        teams = sorted([t for t in standings if t['conference'] == conf_short], 
                      key=lambda x: x['conf_rank'])[:10]
        
        if len(teams) >= 10:
            # Playoff matchups (3v6, 4v5)
            matchups = [
                (teams[2], teams[5]),
                (teams[3], teams[4])
            ]
            
            for home, away in matchups:
                c.execute('''INSERT INTO series (season, round, conference, home_team_id, away_team_id, 
                            home_seed, away_seed, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                         ('2026', 'First Round', conf_full, home['team_id'], away['team_id'],
                          home['conf_rank'], away['conf_rank'], 'active'))
            
            # Play-in
            c.execute('''INSERT INTO playin_games (season, conference, game_type, team1_id, team1_seed,
                        team2_id, team2_seed, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                     ('2026', conf_full, '7v8', teams[6]['team_id'], 7, teams[7]['team_id'], 8, 'active'))
            
            c.execute('''INSERT INTO playin_games (season, conference, game_type, team1_id, team1_seed,
                        team2_id, team2_seed, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                     ('2026', conf_full, '9v10', teams[8]['team_id'], 9, teams[9]['team_id'], 10, 'active'))
    
    conn.commit()
    conn.close()
    print("Generated matchups")

@app.on_event("startup")
async def startup():
    init_db()
    sync_teams()
    generate_matchups()

@app.get("/")
async def root():
    return {"message": "NBA Predictor API", "version": "2.0", "nba_api": NBA_API_AVAILABLE}

@app.get("/api/standings")
async def api_standings():
    standings = get_standings()
    eastern = [t for t in standings if t['conference'] == 'East']
    western = [t for t in standings if t['conference'] == 'West']
    return {"eastern": eastern, "western": western, "last_updated": datetime.now().isoformat()}

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
               wt.name, wt.abbreviation
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
            'predicted_winner': {'name': row[16], 'abbreviation': row[17]},
            'predicted_at': row[4],
            'is_correct': row[5],
            'points_earned': row[6]
        })
    
    # Get play-in predictions
    c.execute('''
        SELECT pp.*, pg.game_type, pg.conference,
               t1.name, t1.abbreviation, t1.logo_url,
               t2.name, t2.abbreviation, t2.logo_url,
               wt.name, wt.abbreviation
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
            'predicted_winner': {'name': row[15], 'abbreviation': row[16]},
            'predicted_at': row[4]
        })
    
    conn.close()
    
    return {
        'playoff_predictions': playoff_preds,
        'playin_predictions': playin_preds,
        'total_predictions': len(playoff_preds) + len(playin_preds)
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)