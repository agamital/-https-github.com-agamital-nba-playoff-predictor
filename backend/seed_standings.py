"""
Manually seed NBA standings into the database and generate all playoff matchups.

Usage:
  cd backend
  python seed_standings.py

This is the fallback when the NBA API is unreachable.
After running this script, restart the backend — standings will be served from DB.
"""

import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "nba_predictor.db"

# ── Hardcoded standings (as of 2026-03-23) ────────────────────────────────────
# Format: (abbreviation, full_name, wins, losses, win_pct, conf_rank)

EASTERN = [
    ('DET', 'Detroit Pistons',        51, 19, 0.729, 1),
    ('BOS', 'Boston Celtics',         47, 24, 0.662, 2),
    ('NYK', 'New York Knicks',        47, 25, 0.653, 3),
    ('CLE', 'Cleveland Cavaliers',    44, 27, 0.620, 4),
    ('TOR', 'Toronto Raptors',        39, 31, 0.557, 5),
    ('ATL', 'Atlanta Hawks',          39, 32, 0.549, 6),
    ('PHI', 'Philadelphia 76ers',     39, 32, 0.549, 7),
    ('ORL', 'Orlando Magic',          38, 32, 0.543, 8),
    ('MIA', 'Miami Heat',             38, 33, 0.535, 9),
    ('CHA', 'Charlotte Hornets',      37, 34, 0.521, 10),
]

WESTERN = [
    ('OKC', 'Oklahoma City Thunder',  56, 15, 0.789, 1),
    ('SAS', 'San Antonio Spurs',      53, 18, 0.746, 2),
    ('LAL', 'Los Angeles Lakers',     46, 25, 0.648, 3),
    ('HOU', 'Houston Rockets',        43, 27, 0.614, 4),
    ('DEN', 'Denver Nuggets',         44, 28, 0.611, 5),
    ('MIN', 'Minnesota Timberwolves', 44, 28, 0.611, 6),
    ('PHX', 'Phoenix Suns',           40, 32, 0.556, 7),
    ('LAC', 'LA Clippers',            35, 36, 0.493, 8),
    ('POR', 'Portland Trail Blazers', 35, 37, 0.486, 9),
    ('GSW', 'Golden State Warriors',  33, 38, 0.465, 10),
]

# ── Connect ───────────────────────────────────────────────────────────────────

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Ensure cached_standings table exists (main.py will also create it on restart)
c.execute('''CREATE TABLE IF NOT EXISTS cached_standings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id     INTEGER NOT NULL,
    team_name   TEXT    NOT NULL,
    abbreviation TEXT   NOT NULL,
    conference  TEXT    NOT NULL,
    wins        INTEGER NOT NULL,
    losses      INTEGER NOT NULL,
    win_pct     REAL    NOT NULL,
    conf_rank   INTEGER NOT NULL,
    season      TEXT    DEFAULT '2026',
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(abbreviation, season)
)''')

# ── Step 1: Insert standings ──────────────────────────────────────────────────

print("=" * 60)
print("STEP 1: Inserting standings into cached_standings table")
print("=" * 60)

now = datetime.now().isoformat()

for conf_key, conf_label, rows in [('East', 'Eastern', EASTERN), ('West', 'Western', WESTERN)]:
    print(f"\n  {conf_label} Conference:")
    for abbr, name, wins, losses, pct, rank in rows:
        # Look up team_id from teams table
        c.execute('SELECT id FROM teams WHERE abbreviation = ?', (abbr,))
        row = c.fetchone()
        team_id = row[0] if row else 0
        if not team_id:
            print(f"    WARN: {abbr} not found in teams table — team_id will be 0")

        c.execute('''INSERT INTO cached_standings
                     (team_id, team_name, abbreviation, conference, wins, losses, win_pct, conf_rank, season, updated_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, '2026', ?)
                     ON CONFLICT(abbreviation, season) DO UPDATE SET
                       team_id=excluded.team_id, team_name=excluded.team_name,
                       wins=excluded.wins, losses=excluded.losses,
                       win_pct=excluded.win_pct, conf_rank=excluded.conf_rank,
                       updated_at=excluded.updated_at''',
                  (team_id, name, abbr, conf_key, wins, losses, pct, rank, now))
        print(f"    #{rank:2d}  {name:<30s}  {wins}-{losses}  ({pct:.3f})")

conn.commit()
print("\n  Standings saved.")

# ── Step 2: Generate matchups ─────────────────────────────────────────────────

print("\n" + "=" * 60)
print("STEP 2: Generating playoff series and play-in games")
print("=" * 60)

all_standings = []
for conf_key, conf_label, rows in [('East', 'Eastern', EASTERN), ('West', 'Western', WESTERN)]:
    for abbr, name, wins, losses, pct, rank in rows:
        c.execute('SELECT id FROM teams WHERE abbreviation = ?', (abbr,))
        row = c.fetchone()
        team_id = row[0] if row else 0
        all_standings.append({
            'team_id':    team_id,
            'team_name':  name,
            'abbreviation': abbr,
            'conference': conf_key,
            'wins':       wins,
            'losses':     losses,
            'win_pct':    pct,
            'conf_rank':  rank,
        })

for conf_short, conf_full in [('East', 'Eastern'), ('West', 'Western')]:
    teams = sorted(
        [t for t in all_standings if t['conference'] == conf_short],
        key=lambda x: x['conf_rank']
    )

    print(f"\n  {conf_full}:")

    # Delete existing data for this conference
    c.execute('DELETE FROM series WHERE season = ? AND conference = ?', ('2026', conf_full))
    c.execute('DELETE FROM playin_games WHERE season = ? AND conference = ?', ('2026', conf_full))

    # Insert R1 series: 3v6, 4v5
    matchups = [(teams[2], teams[5]), (teams[3], teams[4])]
    for home, away in matchups:
        c.execute('''INSERT INTO series (season, round, conference, home_team_id, away_team_id,
                    home_seed, away_seed, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                 ('2026', 'First Round', conf_full,
                  home['team_id'], away['team_id'],
                  home['conf_rank'], away['conf_rank'], 'active'))
        print(f"    Series: #{home['conf_rank']} {home['team_name']} vs #{away['conf_rank']} {away['team_name']}")

    # Insert play-in: 7v8, 9v10
    for game_type, i1, i2 in [('7v8', 6, 7), ('9v10', 8, 9)]:
        t1, t2 = teams[i1], teams[i2]
        c.execute('''INSERT INTO playin_games (season, conference, game_type,
                    team1_id, team1_seed, team2_id, team2_seed, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                 ('2026', conf_full, game_type,
                  t1['team_id'], t1['conf_rank'],
                  t2['team_id'], t2['conf_rank'], 'active'))
        print(f"    Play-In {game_type}: #{t1['conf_rank']} {t1['team_name']} vs #{t2['conf_rank']} {t2['team_name']}")

conn.commit()

# ── Step 3: Verify ────────────────────────────────────────────────────────────

print("\n" + "=" * 60)
print("STEP 3: Verification")
print("=" * 60)

c.execute('''SELECT s.id, s.conference, ht.name, s.home_seed, at.name, s.away_seed
             FROM series s
             JOIN teams ht ON s.home_team_id = ht.id
             JOIN teams at ON s.away_team_id = at.id
             WHERE s.season = '2026' ORDER BY s.conference, s.home_seed''')
series_rows = c.fetchall()
print(f"\n  Playoff series ({len(series_rows)}):")
for r in series_rows:
    print(f"    [{r[0]}] {r[1]:8s}: #{r[3]} {r[2]} vs #{r[5]} {r[4]}")

c.execute('''SELECT p.id, p.conference, p.game_type, t1.name, t2.name
             FROM playin_games p
             JOIN teams t1 ON p.team1_id = t1.id
             JOIN teams t2 ON p.team2_id = t2.id
             WHERE p.season = '2026' ORDER BY p.conference, p.game_type''')
pi_rows = c.fetchall()
print(f"\n  Play-in games ({len(pi_rows)}):")
for r in pi_rows:
    print(f"    [{r[0]}] {r[1]:8s}: {r[2]:4s}  {r[3]} vs {r[4]}")

conn.close()

print("\n" + "=" * 60)
print("DONE!")
print("Restart the backend server — standings will load from DB.")
print("=" * 60)
