"""
scoring.py — Centralized scoring rules for the NBA Playoff Predictor.

All point values and multipliers live here. Import from this module
anywhere scoring is needed so that rule changes require only one edit.
"""

from __future__ import annotations

# ── Play-In ────────────────────────────────────────────────────────────────────
PLAYIN_CORRECT_PTS: int = 5


# ── Playoff Series ─────────────────────────────────────────────────────────────
BASE_WINNER_PTS: int = 20
BASE_GAMES_PTS: int = 40

ROUND_MULTIPLIERS: dict[str, int] = {
    "First Round":            1,
    "Conference Semifinals":  2,
    "Conference Finals":      3,
    "NBA Finals":             4,
}

# First Round: applied only when correctly picking the *underdog* (higher seed).
# Key = frozenset of the two seed numbers in the matchup.
R1_UNDERDOG_MULTIPLIERS: dict[frozenset, float] = {
    frozenset({1, 8}): 2.5,
    frozenset({2, 7}): 2.0,
    frozenset({3, 6}): 1.5,
    frozenset({4, 5}): 1.0,
}

# Conference Semifinals and later: underdog picks earn this multiplier.
LATE_ROUND_UNDERDOG_MULT: float = 1.5


# ── Futures ────────────────────────────────────────────────────────────────────
FUTURES_BASE_POINTS: dict[str, int] = {
    "champion":        200,
    "west_champ":      100,
    "east_champ":      100,
    "finals_mvp":       80,
    "west_finals_mvp":  50,
    "east_finals_mvp":  50,
}


# ── Playoff Highs (Leaders) ────────────────────────────────────────────────────
LEADERS_POINTS: dict[str, int] = {
    "scorer":   100,
    "assists":   70,
    "rebounds":  70,
    "threes":    60,
    "steals":    40,
    "blocks":    40,
}


# ── Helper functions ───────────────────────────────────────────────────────────

def calculate_play_in_points(is_correct: bool) -> int:
    """Points for a correct play-in game prediction."""
    return PLAYIN_CORRECT_PTS if is_correct else 0


def get_round_multiplier(round_name: str) -> int:
    """Return the round multiplier for *round_name* (defaults to 1)."""
    return ROUND_MULTIPLIERS.get(round_name, 1)


def get_underdog_multiplier(
    round_name: str,
    home_seed: int | None,
    away_seed: int | None,
    predicted_winner_seed: int | None,
) -> float:
    """
    Return the underdog multiplier for a *correct* pick.

    Picking the favourite always returns 1.0.
    Picking the underdog (worse/higher seed):
      - First Round:  uses R1_UNDERDOG_MULTIPLIERS keyed by the seed pair.
      - Semis+:       always LATE_ROUND_UNDERDOG_MULT (1.5).

    If any seed is unknown, returns 1.0 (no bonus).
    """
    if home_seed is None or away_seed is None or predicted_winner_seed is None:
        return 1.0

    underdog_seed = max(home_seed, away_seed)
    if predicted_winner_seed != underdog_seed:
        return 1.0  # picked the favourite

    if round_name == "First Round":
        return R1_UNDERDOG_MULTIPLIERS.get(frozenset({home_seed, away_seed}), 1.0)

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
    Points earned for a single playoff-series prediction.

    Formula:
      winner_pts = BASE_WINNER_PTS × round_mult × underdog_mult
      games_pts  = BASE_GAMES_PTS  × round_mult × underdog_mult  (only when games correct too)
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
    Score a futures-prediction row.

    Args:
        predictions: {cat: team_id (int) or player name (str)}
        actuals:     {cat: team_id (int) or player name (str)}  — None/missing = result not set yet
        odds:        {cat: float}  — multipliers from site_settings

    Returns:
        (total_points, correctness_dict)
        correctness_dict values: 1 = correct, 0 = wrong, None = result not yet known
    """
    pts: int = 0
    correct: dict = {}

    for cat, base in FUTURES_BASE_POINTS.items():
        pred   = predictions.get(cat)
        actual = actuals.get(cat)

        if not actual:
            correct[cat] = None
            continue

        # Team categories compare by integer ID; player categories compare by string
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

    All categories are exact-match, case-insensitive string comparisons.

    Returns:
        (total_points, correctness_dict)
        correctness_dict values: 1 = correct, 0 = wrong, None = result not yet known
    """
    pts: int = 0
    correct: dict = {}

    for cat, base in LEADERS_POINTS.items():
        pred   = predictions.get(cat)
        actual = actuals.get(cat)

        if not actual:
            correct[cat] = None
            continue

        is_c = 1 if (pred and str(pred).strip().lower() == str(actual).strip().lower()) else 0
        correct[cat] = is_c
        if is_c:
            pts += base

    return pts, correct
