"""
Run this script directly to fix the database WITHOUT needing to restart the server.

Usage:
  cd backend
  python fix_data.py

It will:
  1. Print raw NBA API standings to verify data is current
  2. Force-insert all missing playoff series and play-in games
  3. Print a final summary of what's in the DB
"""

import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "nba_predictor.db"


# ── 1. Fetch standings ─────────────────────────────────────────────────────────

print("=" * 60)
print("STEP 1: Fetching standings from NBA API...")
print("=" * 60)

NBA_HEADERS = {
    'Host': 'stats.nba.com',
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'x-nba-stats-origin': 'stats',
    'x-nba-stats-token': 'true',
    'Origin': 'https://www.nba.com',
    'Referer': 'https://www.nba.com/',
    'Connection': 'keep-alive',
}

try:
    from nba_api.stats.endpoints import leaguestandingsv3

    api = leaguestandingsv3.LeagueStandingsV3(season='2025-26', headers=NBA_HEADERS, timeout=60)
    raw = api.get_dict()
    result_set = raw['resultSets'][0]
    headers = result_set['headers']
    rows    = result_set['rowSet']

    def col(row, name):
        return row[headers.index(name)]

    standings = []
    for row in rows:
        conf = col(row, 'Conference')
        wins = int(col(row, 'WINS'))
        losses = int(col(row, 'LOSSES'))
        pct  = float(col(row, 'WinPCT'))
        standings.append({
            'team_id':   col(row, 'TeamID'),
            'team_name': f"{col(row, 'TeamCity')} {col(row, 'TeamName')}",
            'conference': conf,
            'wins': wins,
            'losses': losses,
            'win_pct': pct,
            'conf_rank': 99,
        })

    for conf in ['East', 'West']:
        conf_teams = sorted(
            [t for t in standings if t['conference'] == conf],
            key=lambda x: (-x['win_pct'], -x['wins'])
        )
        for idx, team in enumerate(conf_teams, 1):
            team['conf_rank'] = idx

    print(f"Fetched at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Total teams: {len(standings)}\n")

    for conf_label, conf_key in [("EASTERN", "East"), ("WESTERN", "West")]:
        print(f"  {conf_label} CONFERENCE (top 10):")
        conf_teams = sorted(
            [t for t in standings if t['conference'] == conf_key],
            key=lambda x: x['conf_rank']
        )[:10]
        for t in conf_teams:
            print(f"    #{t['conf_rank']:2d}  {t['team_name']:<30s}  {t['wins']}-{t['losses']}  ({t['win_pct']:.3f})")
        print()

except Exception as e:
    print(f"ERROR fetching standings: {e}")
    standings = []


# ── 2. Fix matchups in DB ──────────────────────────────────────────────────────

if not standings:
    print("Cannot generate matchups without standings. Exiting.")
    exit(1)

print("=" * 60)
print("STEP 2: Fixing playoff matchups in database...")
print("=" * 60)

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

for conf_short, conf_full in [('East', 'Eastern'), ('West', 'Western')]:
    teams = sorted(
        [t for t in standings if t['conference'] == conf_short],
        key=lambda x: x['conf_rank']
    )[:10]

    if len(teams) < 10:
        print(f"  WARN: Only {len(teams)} {conf_full} teams in standings, skipping")
        continue

    # Show seeds 1-10
    print(f"\n  {conf_full} seeds 1-10:")
    for t in teams:
        print(f"    #{t['conf_rank']}  {t['team_name']} ({t['wins']}-{t['losses']})")

    # Force-replace series (3v6, 4v5)
    c.execute('DELETE FROM series WHERE season = ? AND conference = ?', ('2026', conf_full))
    matchups = [
        (teams[2], teams[5]),   # 3 vs 6
        (teams[3], teams[4]),   # 4 vs 5
    ]
    for home, away in matchups:
        c.execute('''INSERT INTO series (season, round, conference, home_team_id, away_team_id,
                    home_seed, away_seed, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                 ('2026', 'First Round', conf_full,
                  home['team_id'], away['team_id'],
                  home['conf_rank'], away['conf_rank'], 'active'))
        print(f"  -> Created: #{home['conf_rank']} {home['team_name']} vs #{away['conf_rank']} {away['team_name']}")

    # Force-replace play-in games (7v8, 9v10)
    c.execute('DELETE FROM playin_games WHERE season = ? AND conference = ?', ('2026', conf_full))
    playin_pairs = [
        ('7v8',  teams[6], teams[7]),
        ('9v10', teams[8], teams[9]),
    ]
    for game_type, t1, t2 in playin_pairs:
        c.execute('''INSERT INTO playin_games (season, conference, game_type,
                    team1_id, team1_seed, team2_id, team2_seed, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                 ('2026', conf_full, game_type,
                  t1['team_id'], t1['conf_rank'],
                  t2['team_id'], t2['conf_rank'], 'active'))
        print(f"  -> Play-In {game_type}: #{t1['conf_rank']} {t1['team_name']} vs #{t2['conf_rank']} {t2['team_name']}")

conn.commit()


# ── 3. Summary ─────────────────────────────────────────────────────────────────

print("\n" + "=" * 60)
print("STEP 3: Database summary")
print("=" * 60)

c.execute('''SELECT s.id, s.conference, ht.name, s.home_seed, at.name, s.away_seed
             FROM series s
             JOIN teams ht ON s.home_team_id = ht.id
             JOIN teams at ON s.away_team_id = at.id
             WHERE s.season = '2026' ORDER BY s.conference, s.home_seed''')
series_rows = c.fetchall()
print(f"\n  Playoff series ({len(series_rows)} total):")
for row in series_rows:
    print(f"    [{row[0]}] {row[1]:8s}: #{row[3]} {row[2]} vs #{row[5]} {row[4]}")

c.execute('''SELECT p.id, p.conference, p.game_type, t1.name, t2.name
             FROM playin_games p
             JOIN teams t1 ON p.team1_id = t1.id
             JOIN teams t2 ON p.team2_id = t2.id
             WHERE p.season = '2026' ORDER BY p.conference, p.game_type''')
pi_rows = c.fetchall()
print(f"\n  Play-in games ({len(pi_rows)} total):")
for row in pi_rows:
    print(f"    [{row[0]}] {row[1]:8s}: {row[2]:4s}  {row[3]} vs {row[4]}")

conn.close()

print("\n" + "=" * 60)
print("DONE. Now RESTART the backend server, then reload the bracket.")
print("=" * 60)
