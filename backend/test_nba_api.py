"""
Standalone test script — run directly on the Railway server (or locally) to
diagnose NBA API connectivity issues.

Usage:
    python test_nba_api.py
"""
from nba_api.stats.static import teams
from nba_api.stats.endpoints import leaguestandingsv3, leaguestandings

# Exact same headers used by main.py (Accept-Encoding intentionally omitted —
# cloud servers receive gzip-compressed responses nba_api cannot decode)
HEADERS = {
    'Host': 'stats.nba.com',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Origin': 'https://www.nba.com',
    'Referer': 'https://www.nba.com/',
    'Connection': 'keep-alive',
    'x-nba-stats-origin': 'stats',
    'x-nba-stats-token': 'true',
}
TIMEOUT = 30
SEASON  = '2025-26'

# Known real NBA team names — used to detect All-Star data contamination
_REAL_TEAM_NAMES = {
    'Atlanta Hawks', 'Boston Celtics', 'Brooklyn Nets', 'Charlotte Hornets',
    'Chicago Bulls', 'Cleveland Cavaliers', 'Dallas Mavericks', 'Denver Nuggets',
    'Detroit Pistons', 'Golden State Warriors', 'Houston Rockets', 'Indiana Pacers',
    'LA Clippers', 'Los Angeles Lakers', 'Memphis Grizzlies', 'Miami Heat',
    'Milwaukee Bucks', 'Minnesota Timberwolves', 'New Orleans Pelicans', 'New York Knicks',
    'Oklahoma City Thunder', 'Orlando Magic', 'Philadelphia 76ers', 'Phoenix Suns',
    'Portland Trail Blazers', 'Sacramento Kings', 'San Antonio Spurs', 'Toronto Raptors',
    'Utah Jazz', 'Washington Wizards',
}
_ALLSTAR_KEYWORDS = ('all-star', 'all star', 'team lebron', 'team stephen',
                     'team durant', 'team giannis', 'team curry')

def _validate_regular_season(rows, headers):
    """Return a list of warning strings if the data looks like All-Star data."""
    warnings = []
    bad = []
    for row in rows:
        city = row[headers.index('TeamCity')]
        name = row[headers.index('TeamName')]
        conf = row[headers.index('Conference')]
        full = f"{city} {name}"
        if conf.lower().strip() not in ('east', 'west'):
            bad.append(f"'{full}' (conference='{conf}')")
        elif any(kw in full.lower() for kw in _ALLSTAR_KEYWORDS):
            bad.append(f"'{full}' (All-Star keyword detected)")
    if bad:
        warnings.append(f"ALLSTAR DATA DETECTED — {len(bad)} suspicious team(s): {bad[:3]}")
    if len(rows) < 28:
        warnings.append(f"Only {len(rows)} teams returned (expected 30) — likely incomplete or non-Regular-Season data")
    return warnings


print("=" * 60)
print("NBA API connectivity test")
print(f"Season: {SEASON}  |  Timeout: {TIMEOUT}s  |  proxy=None")
print("=" * 60)

# ── Test 1: Static teams list (no network call) ──────────────────────────────
print("\n[1] teams.get_teams() — static data, no network")
try:
    nba_teams = teams.get_teams()
    print(f"    ✓ {len(nba_teams)} teams loaded")
    print(f"    First team: {nba_teams[0]}")
except Exception as e:
    print(f"    ✗ {type(e).__name__}: {e}")

# ── Test 2: LeagueStandingsV3 (primary endpoint used by main.py) ─────────────
print(f"\n[2] LeagueStandingsV3 — season={SEASON}, season_type=Regular Season")
try:
    api = leaguestandingsv3.LeagueStandingsV3(
        season=SEASON,
        season_type='Regular Season',          # primary — prevents All-Star data
        season_type_all_star='Regular Season', # belt-and-suspenders
        headers=HEADERS,
        timeout=TIMEOUT,
        proxy=None,
    )
    data = api.get_dict()
    rs   = data['resultSets'][0]
    rows, hdrs = rs['rowSet'], rs['headers']
    print(f"    ✓ Success — {len(rows)} teams returned")

    if rows:
        col = lambda name: rows[0][hdrs.index(name)]
        first_team = f"{col('TeamCity')} {col('TeamName')}"
        print(f"    First team: {first_team} — {col('WINS')}-{col('LOSSES')} ({col('Conference')})")

        # All-Star guard
        warnings = _validate_regular_season(rows, hdrs)
        if warnings:
            for w in warnings:
                print(f"    ⚠ {w}")
        else:
            print(f"    ✓ Data looks like Regular Season (all conferences are East/West, no All-Star names)")

        # Quick sanity: show top-3 teams per conference
        east = sorted(
            [r for r in rows if r[hdrs.index('Conference')] == 'East'],
            key=lambda r: (-int(r[hdrs.index('WINS')]), int(r[hdrs.index('LOSSES')]))
        )[:3]
        west = sorted(
            [r for r in rows if r[hdrs.index('Conference')] == 'West'],
            key=lambda r: (-int(r[hdrs.index('WINS')]), int(r[hdrs.index('LOSSES')]))
        )[:3]
        print("    East top-3:", [f"{r[hdrs.index('TeamCity')]} {r[hdrs.index('TeamName')]} ({r[hdrs.index('WINS')]}-{r[hdrs.index('LOSSES')]})" for r in east])
        print("    West top-3:", [f"{r[hdrs.index('TeamCity')]} {r[hdrs.index('TeamName')]} ({r[hdrs.index('WINS')]}-{r[hdrs.index('LOSSES')]})" for r in west])

except Exception as e:
    import traceback
    resp = getattr(e, 'response', None)
    if resp is not None:
        print(f"    ✗ HTTP {resp.status_code}")
        print(f"    Response body (first 600 chars): {resp.text[:600]}")
    else:
        print(f"    ✗ {type(e).__name__}: {e}")
    traceback.print_exc()

# ── Test 3: LeagueStandings fallback endpoint ─────────────────────────────────
print(f"\n[3] LeagueStandings (fallback endpoint) — season={SEASON}, season_type=Regular Season")
try:
    api2 = leaguestandings.LeagueStandings(
        season=SEASON,
        season_type='Regular Season',
        headers=HEADERS,
        timeout=TIMEOUT,
        proxy=None,
    )
    data2 = api2.get_dict()
    rs2   = data2['resultSets'][0]
    rows2, hdrs2 = rs2['rowSet'], rs2['headers']
    print(f"    ✓ Success — {len(rows2)} teams")

    if rows2:
        warnings2 = _validate_regular_season(rows2, hdrs2)
        if warnings2:
            for w in warnings2:
                print(f"    ⚠ {w}")
        else:
            print(f"    ✓ Data looks like Regular Season")

except Exception as e:
    import traceback
    resp = getattr(e, 'response', None)
    if resp is not None:
        print(f"    ✗ HTTP {resp.status_code}: {resp.text[:400]}")
    else:
        print(f"    ✗ {type(e).__name__}: {e}")
    traceback.print_exc()

print("\n" + "=" * 60)
print("Done.")
print("  • All ✗ → server IP likely blocked by stats.nba.com")
print("  • ⚠ ALLSTAR DATA → season_type param not accepted by this API version")
print("  •   Fix: use LeagueStandings (Test 3) as primary, or update nba_api")
print("=" * 60)
