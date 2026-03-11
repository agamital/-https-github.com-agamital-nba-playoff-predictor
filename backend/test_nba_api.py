from nba_api.stats.static import teams
from nba_api.stats.endpoints import leaguestandingsv3

print("Testing NBA API...")

# Test 1: Get teams
print("\n1. Testing teams.get_teams()...")
try:
    nba_teams = teams.get_teams()
    print(f"✅ Got {len(nba_teams)} teams")
    print(f"First team: {nba_teams[0]}")
except Exception as e:
    print(f"❌ Error: {e}")

# Test 2: Get standings
print("\n2. Testing LeagueStandingsV3...")
try:
    standings = leaguestandingsv3.LeagueStandingsV3(season='2024-25')
    data = standings.get_dict()
    print(f"✅ Got standings data")
    print(f"Keys: {data.keys()}")
    if 'resultSets' in data and len(data['resultSets']) > 0:
        print(f"Columns: {data['resultSets'][0]['headers']}")
        print(f"First team data: {data['resultSets'][0]['rowSet'][0]}")
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()

# Test 3: Try different endpoint
print("\n3. Testing alternative - leaguestandings...")
try:
    from nba_api.stats.endpoints import leaguestandings
    standings = leaguestandings.LeagueStandings(season='2024-25')
    data = standings.get_dict()
    print(f"✅ Got data with keys: {data.keys()}")
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()