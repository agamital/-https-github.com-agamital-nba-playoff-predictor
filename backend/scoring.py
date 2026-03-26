"""
scoring.py — Single source of truth for all NBA Playoff Predictor scoring rules.

Import from here everywhere points are calculated. Never hard-code point values
in endpoints — change a rule here and every flow (admin result entry, leaderboard
recalc, bracket advancement) picks it up automatically.

----------------------------------------------------------------------------
SCORING RULES SUMMARY
----------------------------------------------------------------------------

NBA EXPERT 50/25/22/3 SCORING MODEL
Weight allocation:  Series 50% | Leaders 25% | Futures 22% | Play-In 3%

1. PLAY-IN (3%)  -------------------------------------------------------------
   Correct winner:   20 pts (flat)
   Underdog bonus:  +10 pts  (the higher-seeded / away team wins)
   Maximum per game: 30 pts

2. PLAYOFF SERIES (50%)  ------------------------------------------------------
   Base points (before multipliers):
     Correct winner:              50 pts
     Exact games (winner also ✓): 50 pts  → 100 pts combined
     Close Call  (winner ✓, games off by 1): +15 pts  (instead of 50)

   Round multipliers (applied to all pts):
     First Round              x1.0
     Conference Semifinals    x1.5
     Conference Finals        x2.0
     NBA Finals               x3.0

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
     winner_pts   = 50  x round_mult x underdog_mult
     games_pts    = 50  x round_mult x underdog_mult   (exact games; 0 if wrong)
     close_bonus  = 15  x round_mult x underdog_mult   (off-by-1 games; 0 otherwise)
     total        = winner_pts + games_pts  (or winner_pts + close_bonus)

   Example calculations:
     R1 1v8, pick 8-seed correct, games correct:
       winner_pts = 50 x 1.0 x 2.5 = 125
       games_pts  = 50 x 1.0 x 2.5 = 125
       total      = 250 pts

     R1 2v7, pick 2-seed (fav) correct, games off by 1 (close call):
       winner_pts  = 50 x 1.0 x 1.0 = 50
       close_bonus = 15 x 1.0 x 1.0 = 15
       total       = 65 pts

     Conf Semis, pick underdog correct, games correct:
       winner_pts = 50 x 1.5 x 1.5 = 112
       games_pts  = 50 x 1.5 x 1.5 = 112
       total      = 224 pts   (truncated from 225 due to int())

     NBA Finals, pick favourite correct, games correct:
       winner_pts = 50 x 3.0 x 1.0 = 150
       games_pts  = 50 x 3.0 x 1.0 = 150
       total      = 300 pts

3. FUTURES (22%)  -------------------------------------------------------------
   Base points:
     NBA Champion          200 pts
     Western Conference     100 pts
     Eastern Conference     100 pts
     Finals MVP             150 pts  (elevated — hard single pick)
     West Finals MVP         50 pts
     East Finals MVP         50 pts

   Odds multiplier:
     Team categories (champion / west_champ / east_champ):
       Per-team multiplier stored in teams.odds_championship or teams.odds_conference.
       Default 1.0 — admin sets per-team odds in the Admin panel.
       points = base x team.odds_championship   (champion)
       points = base x team.odds_conference     (conf champs)
     Player categories (Finals MVP / West MVP / East MVP):
       Per-category multiplier stored in site_settings (odds_finals_mvp, etc.).
       points = base x odds_multiplier
   Team categories matched by integer team_id.
   Player (MVP) categories matched by case-insensitive string.

4. PLAYOFF HIGHS (Leaders)  --------------------------------------------------
   Users predict the MAX stat value (integer), not the player name.
   Tiered proximity scoring — closer guesses earn more.

   Points (scorer):
     Exact match (delta 0)   : 350 pts  🎯 Bullseye
     Off by 1–2  (delta 1-2) : 100 pts  ✅ Close
     Off by 3–4  (delta 3-4) :  40 pts  🟡 Near
     Off by 5+               :   0 pts  ❌ Miss

   Rebounds & Assists:
     Exact  (delta 0)        : 300 pts  🎯 Bullseye
     Off by 1  (delta 1)     :  80 pts  ✅ Close
     Off by 2  (delta 2)     :  30 pts  🟡 Near
     Off by 3+               :   0 pts  ❌ Miss

   Threes Made (3PM):
     Exact  (delta 0)        : 250 pts  🎯 Bullseye
     Off by 1  (delta 1)     :  50 pts  ✅ Close
     Off by 2+               :   0 pts  ❌ Miss

   Steals & Blocks (exact only):
     Exact  (delta 0)        : 200 pts  🎯 Bullseye
     Off by 1+               :   0 pts  ❌ Miss

   correctness return values:
     2 = "bullseye" — exact match
     1 = "close"    — proximity hit (partial points)
     0 = miss
     None = result not yet set

----------------------------------------------------------------------------
"""

from __future__ import annotations

# -- Play-In --------------------------------------------------------------------
PLAYIN_CORRECT_PTS: int   = 20
PLAYIN_UNDERDOG_BONUS: int = 10


# -- Playoff Series -------------------------------------------------------------
BASE_WINNER_PTS: int  = 50
BASE_GAMES_PTS: int   = 50
CLOSE_CALL_BONUS: int = 15   # winner correct + games off by exactly 1

ROUND_MULTIPLIERS: dict[str, float] = {
    "First Round":            1.0,
    "Conference Semifinals":  1.5,
    "Conference Finals":      2.0,
    "NBA Finals":             3.0,
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
    "finals_mvp":      150,
    "west_finals_mvp":  50,
    "east_finals_mvp":  50,
}


# -- Playoff Highs (Leaders) ----------------------------------------------------
# Each tier: (max_delta_inclusive, points_awarded).
# Tiers are checked in order — first matching delta wins.
# An empty tail means "exact only"; any delta beyond the last tier = 0 pts.
LEADERS_TIERS: dict[str, list[tuple[int, int]]] = {
    "scorer":   [(0, 350), (2, 100), (4, 40)],   # exact=350, Δ1-2=100, Δ3-4=40
    "assists":  [(0, 300), (1,  80), (2, 30)],   # exact=300, Δ1=80,   Δ2=30
    "rebounds": [(0, 300), (1,  80), (2, 30)],   # exact=300, Δ1=80,   Δ2=30
    "threes":   [(0, 250), (1,  50)],            # exact=250, Δ1=50
    "steals":   [(0, 200)],                      # exact only
    "blocks":   [(0, 200)],                      # exact only
}

# Convenience alias — exact-match point values used by the scoring guide / UI.
LEADERS_POINTS: dict[str, int] = {cat: tiers[0][1] for cat, tiers in LEADERS_TIERS.items()}


# -- Public API -----------------------------------------------------------------

def calculate_play_in_points(is_correct: bool, is_underdog: bool = False) -> int:
    """
    Play-in points.
    Correct pick:           PLAYIN_CORRECT_PTS (20)
    + Underdog bonus:      +PLAYIN_UNDERDOG_BONUS (10) when the higher-seeded team wins
    Wrong pick:             0
    """
    if not is_correct:
        return 0
    return PLAYIN_CORRECT_PTS + (PLAYIN_UNDERDOG_BONUS if is_underdog else 0)


def get_round_multiplier(round_name: str) -> float:
    """Round multiplier for *round_name*. Returns 1.0 for unknown rounds."""
    return ROUND_MULTIPLIERS.get(round_name, 1.0)


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
    games_diff: int | None = None,
) -> int:
    """
    Points earned for one playoff-series prediction.

    winner_pts   = BASE_WINNER_PTS x round_mult x underdog_mult
    games_pts    = BASE_GAMES_PTS  x round_mult x underdog_mult   (exact games)
    close_bonus  = CLOSE_CALL_BONUS x round_mult x underdog_mult  (games off by 1)
    total        = winner_pts + games_pts  (or winner_pts + close_bonus)

    games_diff: abs(predicted_games - actual_games). None → no close-call check.
    """
    if not winner_correct:
        return 0

    round_mult    = get_round_multiplier(round_name)
    underdog_mult = get_underdog_multiplier(round_name, home_seed, away_seed, predicted_winner_seed)

    winner_pts = int(BASE_WINNER_PTS * round_mult * underdog_mult)

    if games_correct:
        games_pts = int(BASE_GAMES_PTS * round_mult * underdog_mult)
    elif games_diff == 1:
        games_pts = int(CLOSE_CALL_BONUS * round_mult * underdog_mult)
    else:
        games_pts = 0

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
        odds         {cat: float}  — multipliers per category.
                     For team categories (champion/west_champ/east_champ), the caller
                     should supply the *predicted* team's specific odds from
                     teams.odds_championship / teams.odds_conference (default 1.0).
                     For player categories, these come from site_settings.

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
    Score a playoff-highs (leaders) prediction row using tiered proximity scoring.

    Users predict the MAX stat value as a positive integer (e.g. 550 total points).
    Points scale down as the prediction moves further from the actual value.

    Args:
        predictions  {cat: int | str | None}  — user's predicted max stat value
        actuals      {cat: int | str | None}  — actual max stat value; falsy = not set

    Returns:
        (total_points, correctness)
        correctness values:
            2    = bullseye (exact match — full points)
            1    = close    (proximity hit — partial points)
            0    = miss     (no points)
            None = result not yet set
    """
    pts: int = 0
    correct: dict = {}

    for cat, tiers in LEADERS_TIERS.items():
        pred   = predictions.get(cat)
        actual = actuals.get(cat)

        # Result not yet set
        if actual is None or actual == '' or actual == 0:
            correct[cat] = None
            continue

        # Coerce both to int (handles strings from DB/API)
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

        # Walk tiers — first tier whose max_delta >= delta wins
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
    check("correct pick, no underdog",    calculate_play_in_points(True),               20)
    check("correct pick, underdog bonus", calculate_play_in_points(True, is_underdog=True), 30)
    check("wrong pick",                   calculate_play_in_points(False),               0)

    print("\n-- Series: First Round (x1.0) ----------------------")
    # 1v8 underdog correct + games correct -> 50x1x2.5 + 50x1x2.5 = 125+125 = 250
    check("R1 1v8 underdog+games", calculate_series_points("First Round", 1, 8, 8, True, True),  250)
    # 1v8 underdog correct, games off by 1 (close call) -> 125 + 15x1x2.5 = 125+37 = 162
    check("R1 1v8 underdog close", calculate_series_points("First Round", 1, 8, 8, True, False, games_diff=1), 162)
    # 1v8 underdog correct, games wrong -> 125
    check("R1 1v8 underdog only",  calculate_series_points("First Round", 1, 8, 8, True, False), 125)
    # 1v8 favourite correct + games -> 50x1x1 + 50x1x1 = 100
    check("R1 1v8 fav+games",      calculate_series_points("First Round", 1, 8, 1, True, True),  100)
    # 1v8 favourite correct, close call -> 50 + 15 = 65
    check("R1 1v8 fav close call", calculate_series_points("First Round", 1, 8, 1, True, False, games_diff=1), 65)
    # 2v7 underdog+games -> (50+50)x1x2.0 = 200
    check("R1 2v7 underdog+games", calculate_series_points("First Round", 2, 7, 7, True, True),  200)
    # 3v6 underdog+games -> (50+50)x1x1.5 = 150
    check("R1 3v6 underdog+games", calculate_series_points("First Round", 3, 6, 6, True, True),  150)
    # 4v5 underdog+games -> (50+50)x1x1.0 = 100
    check("R1 4v5 underdog+games", calculate_series_points("First Round", 4, 5, 5, True, True),  100)
    # Wrong winner -> 0
    check("R1 wrong winner",       calculate_series_points("First Round", 1, 8, 8, False, False), 0)

    print("\n-- Series: Conference Semifinals (x1.5) -------------")
    # Semis underdog correct+games -> int(50x1.5x1.5)+int(50x1.5x1.5) = 112+112 = 224
    check("Semis underdog+games",  calculate_series_points("Conference Semifinals", 3, 6, 6, True, True),  224)
    # Semis favourite correct only -> 50x1.5x1.0 = 75
    check("Semis fav only",        calculate_series_points("Conference Semifinals", 3, 6, 3, True, False),  75)
    # Semis favourite close call -> 50x1.5 + 15x1.5 = 75+22 = 97
    check("Semis fav close call",  calculate_series_points("Conference Semifinals", 3, 6, 3, True, False, games_diff=1), 97)

    print("\n-- Series: Conference Finals (x2.0) -----------------")
    # CF underdog+games -> (50+50)x2.0x1.5 = 300
    check("CF underdog+games",     calculate_series_points("Conference Finals", 4, 6, 6, True, True),  300)

    print("\n-- Series: NBA Finals (x3.0) ------------------------")
    # Finals fav+games -> (50+50)x3.0x1.0 = 300
    check("Finals fav+games",      calculate_series_points("NBA Finals", 2, 5, 2, True, True),  300)
    # Finals underdog+games -> (50+50)x3.0x1.5 = 450
    check("Finals underdog+games", calculate_series_points("NBA Finals", 2, 5, 5, True, True),  450)

    print("\n-- Series: unknown seeds -----------------------------")
    # Unknown seeds → no underdog bonus → (50+50)x1.5x1.0 = 150
    check("Semis unknown seeds",   calculate_series_points("Conference Semifinals", None, None, None, True, True), 150)

    print("\n-- Futures -------------------------------------------")
    preds   = {"champion": 1, "west_champ": 2, "east_champ": 3, "finals_mvp": "Shai", "west_finals_mvp": None, "east_finals_mvp": None}
    actuals = {"champion": 1, "west_champ": 9, "east_champ": 3, "finals_mvp": "shai gilgeous-alexander", "west_finals_mvp": None, "east_finals_mvp": None}
    odds    = {"champion": 1.5, "west_champ": 1.0, "east_champ": 1.0, "finals_mvp": 1.0, "west_finals_mvp": 1.0, "east_finals_mvp": 1.0}
    pts, correct = calculate_futures_points(preds, actuals, odds)
    check("futures champion correct (x1.5)",  correct["champion"],  1)
    check("futures west_champ wrong",         correct["west_champ"], 0)
    check("futures east_champ correct",       correct["east_champ"], 1)
    check("futures finals_mvp wrong (partial name)", correct["finals_mvp"], 0)
    check("futures total pts",                pts, int(200*1.5) + 100)  # champion 300 + east_champ 100 = 400

    print("\n-- Futures: result not yet set -----------------------")
    pts2, c2 = calculate_futures_points({"champion": 1}, {"champion": None}, {})
    check("futures result unknown -> None", c2["champion"], None)
    check("futures result unknown -> 0 pts", pts2, 0)

    print("\n-- Leaders / Playoff Highs — exact matches ------------")
    lp, lc = calculate_leaders_points(
        {"scorer": 550, "assists": 200, "rebounds": 300, "threes": 55, "steals": 35, "blocks": 40},
        {"scorer": 550, "assists": 200, "rebounds": 300, "threes": 55, "steals": 35, "blocks": 40},
    )
    check("leaders scorer exact -> bullseye (2)",   lc["scorer"],   2)
    check("leaders assists exact -> bullseye (2)",  lc["assists"],  2)
    check("leaders rebounds exact -> bullseye (2)", lc["rebounds"], 2)
    check("leaders threes exact -> bullseye (2)",   lc["threes"],   2)
    check("leaders steals exact -> bullseye (2)",   lc["steals"],   2)
    check("leaders blocks exact -> bullseye (2)",   lc["blocks"],   2)
    check("leaders total pts all exact (350+300+300+250+200+200)", lp, 1600)

    print("\n-- Leaders — proximity tiers --------------------------")
    # scorer off by 2 -> 100 pts, close (1)
    lp2a, lc2a = calculate_leaders_points({"scorer": 548}, {"scorer": 550})
    check("scorer off 2 -> 100 pts",   lp2a, 100)
    check("scorer off 2 -> close (1)", lc2a["scorer"], 1)

    # scorer off by 4 -> 40 pts
    lp2b, lc2b = calculate_leaders_points({"scorer": 554}, {"scorer": 550})
    check("scorer off 4 -> 40 pts",    lp2b, 40)
    check("scorer off 4 -> close (1)", lc2b["scorer"], 1)

    # scorer off by 5 -> 0 pts
    lp2c, lc2c = calculate_leaders_points({"scorer": 545}, {"scorer": 550})
    check("scorer off 5 -> 0 pts",     lp2c, 0)
    check("scorer off 5 -> miss (0)",  lc2c["scorer"], 0)

    # assists off by 1 -> 80 pts
    lp3a, lc3a = calculate_leaders_points({"assists": 201}, {"assists": 200})
    check("assists off 1 -> 80 pts",   lp3a, 80)

    # assists off by 2 -> 30 pts
    lp3b, lc3b = calculate_leaders_points({"assists": 198}, {"assists": 200})
    check("assists off 2 -> 30 pts",   lp3b, 30)

    # assists off by 3 -> 0 pts
    lp3c, lc3c = calculate_leaders_points({"assists": 203}, {"assists": 200})
    check("assists off 3 -> 0 pts",    lp3c, 0)

    # threes off by 1 -> 50 pts
    lp4a, _ = calculate_leaders_points({"threes": 56}, {"threes": 55})
    check("threes off 1 -> 50 pts",    lp4a, 50)

    # threes off by 2 -> 0 pts (exact/off-1 only for threes)
    lp4b, _ = calculate_leaders_points({"threes": 57}, {"threes": 55})
    check("threes off 2 -> 0 pts",     lp4b, 0)

    # steals off by 1 -> 0 pts (exact only)
    lp5, lc5 = calculate_leaders_points({"steals": 36}, {"steals": 35})
    check("steals off 1 -> 0 pts (exact only)", lp5, 0)
    check("steals off 1 -> miss (0)",           lc5["steals"], 0)

    # blocks off by 1 -> 0 pts (exact only)
    lp6, lc6 = calculate_leaders_points({"blocks": 39}, {"blocks": 40})
    check("blocks off 1 -> 0 pts (exact only)", lp6, 0)

    print("\n-- Leaders — mixed result -------------------------")
    lpm, lcm = calculate_leaders_points(
        {"scorer": 550, "assists": 201, "rebounds": 303, "threes": None, "steals": 80, "blocks": None},
        {"scorer": 550, "assists": 200, "rebounds": 300, "threes": 55,   "steals": 80, "blocks": None},
    )
    check("mixed scorer exact (2)",     lcm["scorer"],   2)
    check("mixed assists off 1 (1)",    lcm["assists"],  1)
    check("mixed rebounds off 3 (0)",   lcm["rebounds"], 0)
    check("mixed threes not picked (0)",lcm["threes"],   0)
    check("mixed steals exact (2)",     lcm["steals"],   2)
    check("mixed blocks not set (None)",lcm["blocks"],   None)
    check("mixed total pts 350+80+200", lpm, 630)

    print("\n-- Leaders: string-int coercion -----------------------")
    lps, lcs = calculate_leaders_points(
        {"scorer": "550", "assists": "201"},
        {"scorer": 550,   "assists": 200},
    )
    check("str pred exact match -> 2", lcs["scorer"],  2)
    check("str pred off 1 -> 1",       lcs["assists"], 1)

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
