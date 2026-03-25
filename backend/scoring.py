"""
scoring.py — Single source of truth for all NBA Playoff Predictor scoring rules.

Import from here everywhere points are calculated. Never hard-code point values
in endpoints — change a rule here and every flow (admin result entry, leaderboard
recalc, bracket advancement) picks it up automatically.

----------------------------------------------------------------------------
SCORING RULES SUMMARY
----------------------------------------------------------------------------

1. PLAY-IN  ------------------------------------------------------------------
   Correct winner: +5 pts (flat, no multipliers)

2. PLAYOFF SERIES  -----------------------------------------------------------
   Base points:
     Correct winner:         20 pts
     Correct games (bonus):  40 pts  (only awarded when winner is also correct)

   Round multipliers (applied to both winner pts and games pts):
     First Round              x1
     Conference Semifinals    x2
     Conference Finals        x3
     NBA Finals               x4

   Underdog multipliers (applied on top of round multiplier):
     The underdog is always the team with the HIGHER seed number.
     Picking the favourite -> underdog_mult = 1.0 (no bonus).
     Picking the underdog (correct):
       First Round  1 vs 8 -> x2.5
       First Round  2 vs 7 -> x2.0
       First Round  3 vs 6 -> x1.5
       First Round  4 vs 5 -> x1.0   (evenly seeded — no real underdog)
       Semis / CF / Finals  -> x1.5  (any underdog correct pick)

   Full formula:
     winner_pts = 20 x round_mult x underdog_mult
     games_pts  = 40 x round_mult x underdog_mult   (0 if games wrong)
     total      = winner_pts + games_pts

   Example calculations:
     R1 1v8, pick 8-seed correct, games correct:
       winner_pts = 20 x 1 x 2.5 = 50
       games_pts  = 40 x 1 x 2.5 = 100
       total      = 150 pts

     R1 2v7, pick 2-seed (fav) correct, games wrong:
       winner_pts = 20 x 1 x 1.0 = 20
       games_pts  = 0
       total      = 20 pts

     Conf Semis, pick higher seed (underdog) correct, games correct:
       winner_pts = 20 x 2 x 1.5 = 60
       games_pts  = 40 x 2 x 1.5 = 120
       total      = 180 pts

     NBA Finals, pick favourite correct, games correct:
       winner_pts = 20 x 4 x 1.0 = 80
       games_pts  = 40 x 4 x 1.0 = 160
       total      = 240 pts

3. FUTURES  ------------------------------------------------------------------
   Base points:
     NBA Champion          200 pts
     Western Conference     100 pts
     Eastern Conference     100 pts
     Finals MVP              80 pts
     West Finals MVP         50 pts
     East Finals MVP         50 pts

   Odds multiplier (admin-configurable per category, stored in site_settings):
     points = base x odds_multiplier
   Team categories matched by integer team_id.
   Player (MVP) categories matched by case-insensitive string.

4. PLAYOFF HIGHS (Leaders)  --------------------------------------------------
   Users predict the MAX stat value (integer), not the player name.
   Exact integer match only — no partial credit.
     Most Total Points      100 pts
     Most Total Assists      70 pts
     Most Total Rebounds     70 pts
     Most 3-Pointers Made    60 pts
     Most Total Steals       40 pts
     Most Total Blocks       40 pts

----------------------------------------------------------------------------
"""

from __future__ import annotations

# -- Play-In --------------------------------------------------------------------
PLAYIN_CORRECT_PTS: int = 5


# -- Playoff Series -------------------------------------------------------------
BASE_WINNER_PTS: int = 20
BASE_GAMES_PTS: int = 40

ROUND_MULTIPLIERS: dict[str, int] = {
    "First Round":            1,
    "Conference Semifinals":  2,
    "Conference Finals":      3,
    "NBA Finals":             4,
}

# First Round underdog multipliers.
# Applied only when the correctly predicted team is the UNDERDOG (higher seed).
# Key = frozenset of the two seed numbers in the matchup.
R1_UNDERDOG_MULTIPLIERS: dict[frozenset, float] = {
    frozenset({1, 8}): 2.5,
    frozenset({2, 7}): 2.0,
    frozenset({3, 6}): 1.5,
    frozenset({4, 5}): 1.0,  # effectively no bonus — seeds are nearly equal
}

# Conf Semis, Conf Finals, NBA Finals: any correct underdog pick gets this.
LATE_ROUND_UNDERDOG_MULT: float = 1.5


# -- Futures --------------------------------------------------------------------
FUTURES_BASE_POINTS: dict[str, int] = {
    "champion":        200,
    "west_champ":      100,
    "east_champ":      100,
    "finals_mvp":       80,
    "west_finals_mvp":  50,
    "east_finals_mvp":  50,
}


# -- Playoff Highs (Leaders) ----------------------------------------------------
LEADERS_POINTS: dict[str, int] = {
    "scorer":   100,
    "assists":   70,
    "rebounds":  70,
    "threes":    60,
    "steals":    40,
    "blocks":    40,
}


# -- Public API -----------------------------------------------------------------

def calculate_play_in_points(is_correct: bool) -> int:
    """5 pts for a correct play-in prediction; 0 otherwise."""
    return PLAYIN_CORRECT_PTS if is_correct else 0


def get_round_multiplier(round_name: str) -> int:
    """Round multiplier for *round_name*. Returns 1 for unknown rounds."""
    return ROUND_MULTIPLIERS.get(round_name, 1)


def get_underdog_multiplier(
    round_name: str,
    home_seed: int | None,
    away_seed: int | None,
    predicted_winner_seed: int | None,
) -> float:
    """
    Underdog multiplier for a single series prediction.

    Returns 1.0 when:
      - any seed is unknown (safe default)
      - the predicted winner is the favourite (lower seed number)

    Returns seed-based multiplier (R1) or LATE_ROUND_UNDERDOG_MULT (Semis+)
    when the predicted winner is the underdog (higher seed number).
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
) -> int:
    """
    Points earned for one playoff-series prediction.

    winner_pts = BASE_WINNER_PTS x round_mult x underdog_mult
    games_pts  = BASE_GAMES_PTS  x round_mult x underdog_mult  (0 if games wrong)
    total      = winner_pts + games_pts

    Both winner_pts and games_pts share the same multipliers, so an underdog
    bonus amplifies the games bonus equally.
    """
    if not winner_correct:
        return 0

    round_mult    = get_round_multiplier(round_name)
    underdog_mult = get_underdog_multiplier(round_name, home_seed, away_seed, predicted_winner_seed)

    winner_pts = int(BASE_WINNER_PTS * round_mult * underdog_mult)
    games_pts  = int(BASE_GAMES_PTS  * round_mult * underdog_mult) if games_correct else 0

    return winner_pts + games_pts


def calculate_futures_points(
    predictions: dict,
    actuals: dict,
    odds: dict,
) -> tuple[int, dict]:
    """
    Score a futures-prediction row against known results.

    Args:
        predictions  {cat: team_id (int) | player name (str)}
        actuals      {cat: team_id (int) | player name (str)}  — falsy = result unknown
        odds         {cat: float}  — per-category multipliers from site_settings

    Returns:
        (total_points, correctness)
        correctness values: 1 = correct, 0 = wrong, None = result not yet set
    """
    pts: int = 0
    correct: dict = {}

    for cat, base in FUTURES_BASE_POINTS.items():
        pred   = predictions.get(cat)
        actual = actuals.get(cat)

        if not actual:
            correct[cat] = None
            continue

        # Team categories: integer ID comparison.  Player categories: case-insensitive string.
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
    Score a playoff-highs (leaders) prediction row.

    Users predict the MAX stat value as a positive integer (e.g. 55 total points).
    Exact integer match only — no partial credit, no name matching.

    Args:
        predictions  {cat: int | None}   — user's predicted max stat value
        actuals      {cat: int | None}   — actual max stat value; falsy = result unknown

    Returns:
        (total_points, correctness)
        correctness values: 1 = correct, 0 = wrong, None = result not yet set
    """
    pts: int = 0
    correct: dict = {}

    for cat, base in LEADERS_POINTS.items():
        pred   = predictions.get(cat)
        actual = actuals.get(cat)

        # Result not yet set
        if actual is None or actual == '' or actual == 0:
            correct[cat] = None
            continue

        # Coerce both to int for comparison (handles strings coming from DB/API)
        try:
            actual_int = int(actual)
            pred_int   = int(pred) if pred is not None and pred != '' else None
        except (ValueError, TypeError):
            correct[cat] = None
            continue

        if actual_int <= 0:
            correct[cat] = None
            continue

        is_c = 1 if (pred_int is not None and pred_int == actual_int) else 0
        correct[cat] = is_c
        if is_c:
            pts += base

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
    check("correct pick",   calculate_play_in_points(True),  5)
    check("wrong pick",     calculate_play_in_points(False), 0)

    print("\n-- Series: First Round -------------------------------")
    # 1v8 — underdog (8-seed) correct, games correct
    # winner = 20x1x2.5 = 50, games = 40x1x2.5 = 100 -> 150
    check("R1 1v8 underdog+games", calculate_series_points("First Round", 1, 8, 8, True, True),  150)
    # 1v8 — underdog correct, games wrong -> 50
    check("R1 1v8 underdog only",  calculate_series_points("First Round", 1, 8, 8, True, False),  50)
    # 1v8 — favourite (1-seed) correct, games correct -> 20+40 = 60
    check("R1 1v8 fav+games",      calculate_series_points("First Round", 1, 8, 1, True, True),   60)
    # 2v7 — underdog correct, games correct -> (20+40)x1x2.0 = 120
    check("R1 2v7 underdog+games", calculate_series_points("First Round", 2, 7, 7, True, True),  120)
    # 3v6 — underdog correct, games correct -> (20+40)x1x1.5 = 90
    check("R1 3v6 underdog+games", calculate_series_points("First Round", 3, 6, 6, True, True),   90)
    # 4v5 — underdog correct, games correct -> (20+40)x1x1.0 = 60
    check("R1 4v5 underdog+games", calculate_series_points("First Round", 4, 5, 5, True, True),   60)
    # Wrong winner -> 0
    check("R1 wrong winner",       calculate_series_points("First Round", 1, 8, 8, False, False),  0)

    print("\n-- Series: Conference Semifinals ---------------------")
    # Semis, underdog correct, games correct -> (20+40)x2x1.5 = 180
    check("Semis underdog+games",  calculate_series_points("Conference Semifinals", 3, 6, 6, True, True),  180)
    # Semis, favourite correct, games wrong -> 20x2x1.0 = 40
    check("Semis fav only",        calculate_series_points("Conference Semifinals", 3, 6, 3, True, False),  40)

    print("\n-- Series: Conference Finals -------------------------")
    # CF, underdog correct+games -> (20+40)x3x1.5 = 270
    check("CF underdog+games",     calculate_series_points("Conference Finals", 4, 6, 6, True, True),  270)

    print("\n-- Series: NBA Finals --------------------------------")
    # Finals, favourite correct+games -> (20+40)x4x1.0 = 240
    check("Finals fav+games",      calculate_series_points("NBA Finals", 2, 5, 2, True, True),  240)
    # Finals, underdog correct+games -> (20+40)x4x1.5 = 360
    check("Finals underdog+games", calculate_series_points("NBA Finals", 2, 5, 5, True, True),  360)

    print("\n-- Series: unknown seeds -----------------------------")
    # Unknown seeds -> no underdog bonus -> (20+40)x2x1.0 = 120
    check("Semis unknown seeds",   calculate_series_points("Conference Semifinals", None, None, None, True, True), 120)

    print("\n-- Futures -------------------------------------------")
    preds   = {"champion": 1, "west_champ": 2, "east_champ": 3, "finals_mvp": "Shai", "west_finals_mvp": None, "east_finals_mvp": None}
    actuals = {"champion": 1, "west_champ": 9, "east_champ": 3, "finals_mvp": "shai gilgeous-alexander", "west_finals_mvp": None, "east_finals_mvp": None}
    odds    = {"champion": 1.5, "west_champ": 1.0, "east_champ": 1.0, "finals_mvp": 1.0, "west_finals_mvp": 1.0, "east_finals_mvp": 1.0}
    pts, correct = calculate_futures_points(preds, actuals, odds)
    check("futures champion correct (x1.5)",  correct["champion"],  1)
    check("futures west_champ wrong",         correct["west_champ"], 0)
    check("futures east_champ correct",       correct["east_champ"], 1)
    check("futures finals_mvp wrong (partial name)", correct["finals_mvp"], 0)
    check("futures total pts",                pts, int(200*1.5) + 100)  # 300 + 100 = 400

    print("\n-- Futures: result not yet set -----------------------")
    pts2, c2 = calculate_futures_points({"champion": 1}, {"champion": None}, {})
    check("futures result unknown -> None", c2["champion"], None)
    check("futures result unknown -> 0 pts", pts2, 0)

    print("\n-- Leaders / Playoff Highs (integer values) ----------")
    lp, lc = calculate_leaders_points(
        {"scorer": 550, "assists": 200, "rebounds": 300, "threes": None, "steals": 80, "blocks": None},
        {"scorer": 550, "assists": 210, "rebounds": 300, "threes": 120,  "steals": 80, "blocks": None},
    )
    check("leaders scorer exact int match",      lc["scorer"],   1)
    check("leaders assists wrong (200 vs 210)",  lc["assists"],  0)
    check("leaders rebounds exact match",        lc["rebounds"], 1)
    check("leaders threes not picked -> 0",      lc["threes"],   0)
    check("leaders steals exact match",          lc["steals"],   1)
    check("leaders blocks not set -> None",      lc["blocks"],   None)
    check("leaders total pts (100+70+40)",       lp, 210)

    print("\n-- Leaders: string-int coercion -----------------------")
    lp2, lc2 = calculate_leaders_points(
        {"scorer": "550", "assists": "200"},
        {"scorer": 550,   "assists": 200},
    )
    check("leaders str pred vs int actual",  lc2["scorer"],  1)
    check("leaders str pred vs int actual2", lc2["assists"], 1)

    print("\n-- Leaders: zero / missing actual -> None -------------")
    _, lc3 = calculate_leaders_points({"scorer": 550}, {"scorer": 0})
    check("leaders actual=0 -> None", lc3["scorer"], None)
    _, lc4 = calculate_leaders_points({"scorer": 550}, {"scorer": None})
    check("leaders actual=None -> None", lc4["scorer"], None)

    print()
    if errors:
        for e in errors:
            print(e)
        raise SystemExit(f"\n{len(errors)} test(s) failed")
    else:
        print(f"All tests passed")
