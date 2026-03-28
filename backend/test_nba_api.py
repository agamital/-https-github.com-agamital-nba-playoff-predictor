"""
Standalone test script — run directly on the Railway server (or locally) to
diagnose NBA API connectivity issues.

Usage:
    python test_nba_api.py
"""
from nba_api.stats.static import teams
from nba_api.stats.endpoints import leaguestandingsv3, leaguestandings

# Exact same headers used by main.py (Accept-Encoding intentionally omitted)
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

print("=" * 60)
print("NBA API connectivity test")
print(f"Season: {SEASON}  |  Timeout: {TIMEOUT}s")
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
print(f"\n[2] LeagueStandingsV3 — season={SEASON}")
try:
    api = leaguestandingsv3.LeagueStandingsV3(
        season=SEASON,
        season_type_all_star='Regular Season',
        headers=HEADERS,
        timeout=TIMEOUT,
        proxy=None,
    )
    data = api.get_dict()
    rs   = data['resultSets'][0]
    print(f"    ✓ Success — {len(rs['rowSet'])} teams returned")
    print(f"    Columns: {rs['headers']}")
    if rs['rowSet']:
        # Show first team as sanity-check
        row = rs['rowSet'][0]
        col = lambda name: row[rs['headers'].index(name)]
        print(f"    Sample: {col('TeamCity')} {col('TeamName')} "
              f"{col('WINS')}-{col('LOSSES')} (conf_rank will be recomputed)")
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
print(f"\n[3] LeagueStandings (fallback endpoint) — season={SEASON}")
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
    print(f"    ✓ Success — {len(rs2['rowSet'])} teams")
    print(f"    Columns: {rs2['headers']}")
except Exception as e:
    import traceback
    resp = getattr(e, 'response', None)
    if resp is not None:
        print(f"    ✗ HTTP {resp.status_code}: {resp.text[:400]}")
    else:
        print(f"    ✗ {type(e).__name__}: {e}")
    traceback.print_exc()

print("\n" + "=" * 60)
print("Done. If all tests show ✗, the server IP is likely blocked by stats.nba.com.")
print("Check Railway deployment logs for the full traceback from the scheduled sync.")
print("=" * 60)
