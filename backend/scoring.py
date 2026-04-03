"""
scoring.py — Single source of truth for all NBA Playoff Predictor scoring rules.

Import from here everywhere points are calculated. Never hard-code point values
in endpoints — change a rule here and every flow (admin result entry, leaderboard
recalc, bracket advancement) picks it up automatically.

----------------------------------------------------------------------------
SCORING RULES SUMMARY
----------------------------------------------------------------------------

1. PLAY-IN  -------------------------------------------------------------
   Correct winner (favourite):   5 pts
   Correct winner (underdog):    8 pts   (underdog = higher-seeded team)
   Wrong pick:                   0 pts

2. PLAYOFF SERIES  -------------------------------------------------------
   Base points:
     Correct winner:            50 pts
     Exact games (winner ✓):   +30 pts  ->80 pts combined

   Round multipliers (applied to all pts):
     First Round              ×1.0
     Conference Semifinals    ×1.0
     Conference Finals        ×1.5
     NBA Finals (winner)      ×2.5  ← "Correct Champion" bonus
     NBA Finals (games)       ×2.0

   First-Round underdog multipliers (applied on top of round mult):
     1 vs 8  ->×2.0
     2 vs 7  ->×1.5
     3 vs 6  ->×1.2
     4 vs 5  ->×1.0  (no bonus)

   Example: R1 1v8 underdog, winner + exact games:
     winner = 50×1.0×2.0 = 100 pts
     games  = 30×1.0×2.0 =  60 pts  ->160 pts

   Example: Conference Finals favourite, winner + games:
     winner = 50×1.5×1.0 = 75 pts
     games  = 30×1.5×1.0 = 45 pts  ->120 pts

   Example: NBA Finals correct champion + exact games:
     winner = 50×2.5×1.0 = 125 pts
     games  = 30×2.0×1.0 =  60 pts ->185 pts

   Series Statistical Leaders (per series, NEW):
     Correctly predicting the series leader in Points:   +10 pts
     Correctly predicting the series leader in Rebounds: +10 pts
     Correctly predicting the series leader in Assists:  +10 pts
     (case-insensitive name match)

3. FUTURES / GLOBAL PREDICTIONS  ----------------------------------------
   Base points:
     NBA Champion             100 pts
     Western Conference        40 pts
     Eastern Conference        40 pts
     League MVP (Finals MVP)   30 pts
     West Conference MVP       20 pts
     East Conference MVP       20 pts

   Odds multiplier:
     Team categories: per-team multiplier from teams.odds_championship /
                      teams.odds_conference  (default 1.0)
     Player categories: per-category from site_settings (default 1.0)

4. VARIANCE-BASED (Playoff Highs / Leaders)  ----------------------------
   Users predict the MAX cumulative stat across all playoffs.
   Tiered proximity scoring.

   Points / Assists:
     Exact  (Δ=0)  : 80 pts
     Off ±1 (Δ=1)  : 40 pts
     Off ±2 (Δ=2)  : 20 pts
     Off ±3+       :  0 pts

   Rebounds / Threes:
     Exact  (Δ=0)  : 50 pts
     Off ±1 (Δ=1)  : 25 pts
     Off ±2+       :  0 pts

   Steals / Blocks:
     Exact  (Δ=0)  : 35 pts
     Off ±1+       :  0 pts

   correctness return values:
     2 = "bullseye" — exact match (full points)
     1 = "close"    — proximity hit (partial points)
     0 = miss
     None = result not yet set

----------------------------------------------------------------------------
"""

from __future__ import annotations

# -- Play-In --------------------------------------------------------------------
PLAYIN_CORRECT_PTS: int    = 5
PLAYIN_UNDERDOG_BONUS: int = 3   # underdog total = 5+3 = 8 pts


# -- Playoff Series -------------------------------------------------------------
BASE_WINNER_PTS: int = 50
BASE_GAMES_PTS: int  = 30   # exact series length bonus

# Round multipliers — applied to both winner and games pts, except Finals winner.
ROUND_MULTIPLIERS: dict[str, float] = {
    "First Round":            1.0,
    "Conference Semifinals":  1.0,
    "Conference Finals":      1.5,
    "NBA Finals":             2.0,   # used for games pts in Finals
}

# The NBA Finals winner earns the "Correct Champion" multiplier (higher than 2.0×).
NBA_FINALS_CHAMPION_MULT: float = 2.5

# First Round underdog multipliers (applied when predicted winner = higher seed).
R1_UNDERDOG_MULTIPLIERS: dict[frozenset, float] = {
    frozenset({1, 8}): 2.0,
    frozenset({2, 7}): 1.5,
    frozenset({3, 6}): 1.2,
    frozenset({4, 5}): 1.0,
}

# Semis / CF / Finals: any correct underdog pick gets this flat bonus.
LATE_ROUND_UNDERDOG_MULT: float = 1.5

# Series statistical leader bonus (new — per series, per category)
SERIES_LEADER_BONUS: int = 10


# -- Futures --------------------------------------------------------------------
FUTURES_BASE_POINTS: dict[str, int] = {
    "champion":        100,   # NBA Champion
    "west_champ":       40,   # Western Conference Champion
    "east_champ":       40,   # Eastern Conference Champion
    "finals_mvp":       30,   # League / Finals MVP
    "west_finals_mvp":  20,   # West Conference MVP
    "east_finals_mvp":  20,   # East Conference MVP
}


# -- Playoff Highs (Leaders) — variance-based tiers ----------------------------
# Each tier: (max_delta_inclusive, points_awarded).
# Tiers checked in order — first matching delta wins.
LEADERS_TIERS: dict[str, list[tuple[int, int]]] = {
    "scorer":   [(0, 80), (1, 40), (2, 20)],  # exact=80, Δ1=40, Δ2=20
    "assists":  [(0, 80), (1, 40), (2, 20)],  # exact=80, Δ1=40, Δ2=20
    "rebounds": [(0, 50), (1, 25)],            # exact=50, Δ1=25
    "threes":   [(0, 50), (1, 25)],            # exact=50, Δ1=25
    "steals":   [(0, 35)],                     # exact only
    "blocks":   [(0, 35)],                     # exact only
}

# Convenience alias — exact-match values used by scoring guide / UI.
LEADERS_POINTS: dict[str, int] = {cat: tiers[0][1] for cat, tiers in LEADERS_TIERS.items()}


# -- Public API -----------------------------------------------------------------

def calculate_play_in_points(is_correct: bool, is_underdog: bool = False) -> int:
    """
    Play-in points.
    Correct pick (favourite):  PLAYIN_CORRECT_PTS  (5)
    Correct pick (underdog):   PLAYIN_CORRECT_PTS + PLAYIN_UNDERDOG_BONUS  (8)
    Wrong pick:                0
    """
    if not is_correct:
        return 0
    return PLAYIN_CORRECT_PTS + (PLAYIN_UNDERDOG_BONUS if is_underdog else 0)


def get_round_multiplier(round_name: str) -> float:
    """Games-pts round multiplier for *round_name*. Returns 1.0 for unknown rounds."""
    return ROUND_MULTIPLIERS.get(round_name, 1.0)


def get_underdog_multiplier(
    round_name: str,
    home_seed: int | None,
    away_seed: int | None,
    predicted_winner_seed: int | None,
) -> float:
    """
    Underdog multiplier for a single series prediction.

    Returns 1.0 when seeds are unknown or the predicted winner is the favourite.
    Returns seed-based multiplier (R1) or LATE_ROUND_UNDERDOG_MULT (Semis+)
    when the correctly predicted winner is the underdog (higher seed).
    """
    if home_seed is None or away_seed is None or predicted_winner_seed is None:
        return 1.0

    underdog_seed = max(home_seed, away_seed)
    if predicted_winner_seed != underdog_seed:
        return 1.0  # favourite pick — no underdog bonus

    if round_name == "First Round":
        return R1_UNDERDOG_MULTIPLIERS.get(frozenset({home_seed, away_seed}), 1.0)

    # Conference Semifinals, Conference Finals, NBA Finals
    return LATE_ROUND_UNDERDOG_MULT


def calculate_series_points(
    round_name: str,
    home_seed: int | None,
    away_seed: int | None,
    predicted_winner_seed: int | None,
    winner_correct: bool,
    games_correct: bool,
    games_diff: int | None = None,
) -> int:
    """
    Points earned for one playoff-series prediction.

    For the NBA Finals the winner uses the champion multiplier (2.5×) while
    the exact-games bonus still uses the standard round multiplier (2.0×).
    All other rounds: winner and games share the same multiplier.

    games_diff: abs(predicted_games - actual_games). Unused (kept for API compat).
    """
    if not winner_correct:
        return 0

    round_mult    = get_round_multiplier(round_name)
    underdog_mult = get_underdog_multiplier(round_name, home_seed, away_seed, predicted_winner_seed)

    # Finals winner uses the champion multiplier; games use the standard one.
    if round_name == "NBA Finals":
        winner_pts = int(BASE_WINNER_PTS * NBA_FINALS_CHAMPION_MULT * underdog_mult)
    else:
        winner_pts = int(BASE_WINNER_PTS * round_mult * underdog_mult)

    games_pts = int(BASE_GAMES_PTS * round_mult * underdog_mult) if games_correct else 0

    return winner_pts + games_pts


def calculate_series_leader_points(
    predicted: dict,
    actual: dict,
) -> int:
    """
    Score the three series-leader predictions (scorer, rebounder, assister).
    Each correct name match earns SERIES_LEADER_BONUS (10 pts).
    Comparison is case-insensitive; strips whitespace.

    Args:
        predicted  {'scorer': str|None, 'rebounder': str|None, 'assister': str|None}
        actual     {'scorer': str|None, 'rebounder': str|None, 'assister': str|None}
                   falsy value = result not yet set ->skip category.

    Returns total pts (0–30).
    """
    pts = 0
    for cat in ('scorer', 'rebounder', 'assister'):
        pred_val   = predicted.get(cat)
        actual_val = actual.get(cat)
        if not actual_val or not pred_val:
            continue
        if str(pred_val).strip().lower() == str(actual_val).strip().lower():
            pts += SERIES_LEADER_BONUS
    return pts


def calculate_futures_points(
    predictions: dict,
    actuals: dict,
    odds: dict,
) -> tuple[int, dict]:
    """
    Score a futures-prediction row against known results.

    Args:
        predictions  {cat: team_id (int) | player name (str)}
        actuals      {cat: team_id (int) | player name (str)}  — falsy = unknown
        odds         {cat: float}  — per-category multipliers (default 1.0).

    Returns (total_points, correctness).
    correctness values: 1 = correct, 0 = wrong, None = result not yet set.
    """
    pts: int = 0
    correct: dict = {}

    for cat, base in FUTURES_BASE_POINTS.items():
        pred   = predictions.get(cat)
        actual = actuals.get(cat)

        if not actual:
            correct[cat] = None
            continue

        if isinstance(actual, int):
            is_c = 1 if (pred is not None and int(pred) == actual) else 0
        else:
            is_c = 1 if (pred and str(pred).strip().lower() == str(actual).strip().lower()) else 0

        correct[cat] = is_c
        if is_c:
            pts += int(base * float(odds.get(cat, 1.0)))

    return pts, correct


def calculate_leaders_points(
    predictions: dict,
    actuals: dict,
) -> tuple[int, dict]:
    """
    Score a playoff-highs (leaders) prediction using tiered proximity scoring.
    Users predict the MAX cumulative stat value across the playoffs as an integer.

    Returns (total_points, correctness).
    correctness values: 2=bullseye, 1=close, 0=miss, None=not set.
    """
    pts: int = 0
    correct: dict = {}

    for cat, tiers in LEADERS_TIERS.items():
        pred   = predictions.get(cat)
        actual = actuals.get(cat)

        if actual is None or actual == '' or actual == 0:
            correct[cat] = None
            continue

        try:
            actual_int = int(actual)
            pred_int   = int(pred) if pred is not None and pred != '' else None
        except (ValueError, TypeError):
            correct[cat] = None
            continue

        if actual_int <= 0:
            correct[cat] = None
            continue

        if pred_int is None:
            correct[cat] = 0
            continue

        delta = abs(pred_int - actual_int)

        awarded = 0
        for max_delta, tier_pts in tiers:
            if delta <= max_delta:
                awarded = tier_pts
                break

        pts += awarded
        if awarded == 0:
            correct[cat] = 0
        elif delta == 0:
            correct[cat] = 2   # bullseye
        else:
            correct[cat] = 1   # close / proximity

    return pts, correct


# -- Self-test (run with: python scoring.py) ------------------------------------

if __name__ == "__main__":
    errors = []

    def check(label, got, expected):
        if got != expected:
            errors.append(f"FAIL  {label}: expected {expected}, got {got}")
        else:
            print(f"  OK  {label}: {got}")

    print("\n-- Play-In -------------------------------------------")
    check("correct pick favourite (5)",        calculate_play_in_points(True),               5)
    check("correct pick underdog (8)",         calculate_play_in_points(True, is_underdog=True), 8)
    check("wrong pick (0)",                    calculate_play_in_points(False),               0)

    print("\n-- Series: First Round (×1.0) ----------------------")
    # 1v8 underdog correct + games  ->50×1×2.0 + 30×1×2.0 = 100+60 = 160
    check("R1 1v8 underdog+games",   calculate_series_points("First Round", 1, 8, 8, True, True),  160)
    # 1v8 underdog correct only     ->100
    check("R1 1v8 underdog only",    calculate_series_points("First Round", 1, 8, 8, True, False), 100)
    # 1v8 favourite + games         ->50×1×1 + 30×1×1 = 80
    check("R1 1v8 fav+games",        calculate_series_points("First Round", 1, 8, 1, True, True),   80)
    # 2v7 underdog+games            ->(50+30)×1.5 = 120
    check("R1 2v7 underdog+games",   calculate_series_points("First Round", 2, 7, 7, True, True),  120)
    # 3v6 underdog+games            ->(50+30)×1.2 = 96
    check("R1 3v6 underdog+games",   calculate_series_points("First Round", 3, 6, 6, True, True),   96)
    # 4v5 underdog+games            ->(50+30)×1.0 = 80
    check("R1 4v5 underdog+games",   calculate_series_points("First Round", 4, 5, 5, True, True),   80)
    # wrong winner ->0
    check("R1 wrong winner",         calculate_series_points("First Round", 1, 8, 8, False, False),  0)

    print("\n-- Series: Conference Semifinals (×1.0) -------------")
    # Semis fav + games ->50×1×1 + 30×1×1 = 80
    check("Semis fav+games",         calculate_series_points("Conference Semifinals", 3, 6, 3, True, True),   80)
    # Semis underdog+games ->int(50×1×1.5)+int(30×1×1.5) = 75+45 = 120
    check("Semis underdog+games",    calculate_series_points("Conference Semifinals", 3, 6, 6, True, True),  120)

    print("\n-- Series: Conference Finals (×1.5) -----------------")
    # CF fav+games ->50×1.5 + 30×1.5 = 75+45 = 120
    check("CF fav+games",            calculate_series_points("Conference Finals", 3, 6, 3, True, True),  120)
    # CF underdog+games ->int(50×1.5×1.5)+int(30×1.5×1.5) = 112+67 = 179
    check("CF underdog+games",       calculate_series_points("Conference Finals", 3, 6, 6, True, True),  179)

    print("\n-- Series: NBA Finals (winner×2.5, games×2.0) -------")
    # Finals fav+games ->50×2.5 + 30×2.0 = 125+60 = 185
    check("Finals fav+games",        calculate_series_points("NBA Finals", 2, 5, 2, True, True),  185)
    # Finals fav only   ->125
    check("Finals fav only",         calculate_series_points("NBA Finals", 2, 5, 2, True, False), 125)
    # Finals underdog+games ->int(50×2.5×1.5)+int(30×2.0×1.5) = 187+90 = 277
    check("Finals underdog+games",   calculate_series_points("NBA Finals", 2, 5, 5, True, True),  277)

    print("\n-- Series Leaders ------------------------------------")
    check("all 3 correct -> 30 pts",
          calculate_series_leader_points(
              {"scorer": "LeBron James", "rebounder": "Anthony Davis", "assister": "Draymond Green"},
              {"scorer": "lebron james", "rebounder": "Anthony Davis", "assister": "draymond green"}
          ), 30)
    check("1 of 3 correct -> 10 pts",
          calculate_series_leader_points(
              {"scorer": "LeBron James", "rebounder": "Wrong Guy", "assister": None},
              {"scorer": "LeBron James", "rebounder": "Anthony Davis", "assister": None}
          ), 10)
    check("result not set -> 0 pts",
          calculate_series_leader_points({"scorer": "LeBron"}, {"scorer": None}), 0)

    print("\n-- Futures -------------------------------------------")
    preds   = {"champion": 1, "west_champ": 2, "east_champ": 3,
               "finals_mvp": "Shai", "west_finals_mvp": None, "east_finals_mvp": None}
    actuals = {"champion": 1, "west_champ": 9, "east_champ": 3,
               "finals_mvp": "shai gilgeous-alexander", "west_finals_mvp": None, "east_finals_mvp": None}
    odds    = {"champion": 1.5, "west_champ": 1.0, "east_champ": 1.0,
               "finals_mvp": 1.0, "west_finals_mvp": 1.0, "east_finals_mvp": 1.0}
    pts_f, correct_f = calculate_futures_points(preds, actuals, odds)
    check("champion correct (x1.5) -> 150",  correct_f["champion"],  1)
    check("west_champ wrong ->0",           correct_f["west_champ"], 0)
    check("east_champ correct ->40",        correct_f["east_champ"], 1)
    check("finals_mvp partial name wrong",  correct_f["finals_mvp"], 0)
    check("futures total pts",              pts_f, int(100*1.5) + 40)  # 150+40=190

    print("\n-- Leaders/Highs — exact matches ----------------------")
    lp, lc = calculate_leaders_points(
        {"scorer": 550, "assists": 200, "rebounds": 300, "threes": 55, "steals": 35, "blocks": 40},
        {"scorer": 550, "assists": 200, "rebounds": 300, "threes": 55, "steals": 35, "blocks": 40},
    )
    check("scorer exact ->2",   lc["scorer"],   2)
    check("assists exact ->2",  lc["assists"],  2)
    check("rebounds exact ->2", lc["rebounds"], 2)
    check("threes exact ->2",   lc["threes"],   2)
    check("steals exact ->2",   lc["steals"],   2)
    check("blocks exact ->2",   lc["blocks"],   2)
    check("all exact total (80+80+50+50+35+35=330)", lp, 330)

    print("\n-- Leaders — proximity tiers -------------------------")
    lp2, lc2 = calculate_leaders_points({"scorer": 549}, {"scorer": 550})
    check("scorer off 1 ->40",          lp2, 40)
    lp3, lc3 = calculate_leaders_points({"scorer": 548}, {"scorer": 550})
    check("scorer off 2 ->20",          lp3, 20)
    lp4, lc4 = calculate_leaders_points({"scorer": 546}, {"scorer": 550})
    check("scorer off 4 ->0",           lp4, 0)
    lp5, lc5 = calculate_leaders_points({"rebounds": 299}, {"rebounds": 300})
    check("rebounds off 1 ->25",        lp5, 25)
    lp6, lc6 = calculate_leaders_points({"rebounds": 298}, {"rebounds": 300})
    check("rebounds off 2 ->0",         lp6, 0)
    lp7, _   = calculate_leaders_points({"steals": 36}, {"steals": 35})
    check("steals off 1 ->0",           lp7, 0)

    print()
    if errors:
        for e in errors:
            print(e)
        raise SystemExit(f"\n{len(errors)} test(s) failed")
    else:
        print("All tests passed")
