"""
Auto-Update Script - Runs every 10 minutes to update scores
"""

import sqlite3
import time
from datetime import datetime
from pathlib import Path

try:
    from nba_api.live.nba.endpoints import scoreboard
    NBA_API_AVAILABLE = True
except ImportError:
    NBA_API_AVAILABLE = False
    print("⚠️  NBA API not installed")

DB_PATH = Path(__file__).parent / "nba_predictor.db"

def update_live_scores():
    """Fetch and update live NBA scores"""
    if not NBA_API_AVAILABLE:
        print("❌ NBA API not available")
        return
    
    try:
        print(f"🔄 Updating scores at {datetime.now()}")
        
        # Get live scoreboard
        board = scoreboard.ScoreBoard()
        games = board.games.get_dict()
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        updated_count = 0
        for game in games:
            game_id = game.get('gameId')
            home_team_id = game.get('homeTeam', {}).get('teamId')
            away_team_id = game.get('awayTeam', {}).get('teamId')
            home_score = game.get('homeTeam', {}).get('score', 0)
            away_score = game.get('awayTeam', {}).get('score', 0)
            status = game.get('gameStatus')
            game_date = game.get('gameTimeUTC', '')[:10]
            
            # Update or insert game
            c.execute('''
                INSERT INTO games (id, game_date, home_team_id, away_team_id, home_score, away_score, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    home_score = ?,
                    away_score = ?,
                    status = ?,
                    updated_at = CURRENT_TIMESTAMP
            ''', (game_id, game_date, home_team_id, away_team_id, home_score, away_score, status,
                  home_score, away_score, status))
            
            updated_count += 1
            
            # If game is finished, update series if applicable
            if status == 3:  # Game finished
                winner_id = home_team_id if home_score > away_score else away_team_id
                
                # Find associated series
                c.execute('''
                    SELECT id, home_team_id, away_team_id, home_wins, away_wins
                    FROM series
                    WHERE (home_team_id = ? AND away_team_id = ?) OR (home_team_id = ? AND away_team_id = ?)
                    AND status = 'active'
                ''', (home_team_id, away_team_id, away_team_id, home_team_id))
                
                series = c.fetchone()
                if series:
                    series_id, s_home_id, s_away_id, home_wins, away_wins = series
                    
                    # Update series wins
                    if winner_id == s_home_id:
                        home_wins += 1
                    else:
                        away_wins += 1
                    
                    # Check if series is over (best of 7)
                    series_winner = None
                    series_status = 'active'
                    if home_wins >= 4:
                        series_winner = s_home_id
                        series_status = 'completed'
                    elif away_wins >= 4:
                        series_winner = s_away_id
                        series_status = 'completed'
                    
                    c.execute('''
                        UPDATE series
                        SET home_wins = ?, away_wins = ?, winner_team_id = ?, status = ?
                        WHERE id = ?
                    ''', (home_wins, away_wins, series_winner, series_status, series_id))
                    
                    # Calculate points for correct predictions
                    if series_winner:
                        calculate_prediction_points(c, series_id, series_winner)
        
        conn.commit()
        conn.close()
        
        print(f"✅ Updated {updated_count} games")
        
    except Exception as e:
        print(f"❌ Error updating scores: {e}")

def calculate_prediction_points(cursor, series_id, winner_team_id):
    """Calculate points for users who predicted correctly"""
    
    # Get round to determine points
    cursor.execute('SELECT round FROM series WHERE id = ?', (series_id,))
    round_name = cursor.fetchone()[0]
    
    points_map = {
        'First Round': 10,
        'Conference Semifinals': 20,
        'Conference Finals': 30,
        'NBA Finals': 50
    }
    points = points_map.get(round_name, 10)
    
    # Update predictions
    cursor.execute('''
        UPDATE predictions
        SET is_correct = 1, points_earned = ?
        WHERE series_id = ? AND predicted_winner_id = ?
    ''', (points, series_id, winner_team_id))
    
    # Update user points
    cursor.execute('''
        UPDATE users
        SET points = points + ?
        WHERE id IN (
            SELECT user_id FROM predictions
            WHERE series_id = ? AND predicted_winner_id = ?
        )
    ''', (points, series_id, winner_team_id))
    
    print(f"✅ Awarded {points} points to correct predictors for series {series_id}")

def run_continuous_updates(interval_minutes=10):
    """Run updates continuously"""
    print(f"🚀 Starting auto-update service (every {interval_minutes} minutes)")
    
    while True:
        update_live_scores()
        print(f"⏰ Next update in {interval_minutes} minutes...")
        time.sleep(interval_minutes * 60)

if __name__ == "__main__":
    # Run updates every 10 minutes
    run_continuous_updates(interval_minutes=10)
