/**
 * constants.js — Single source of truth for all shared string constants.
 *
 * Mirror of backend/constants.py — keep both files in sync.
 * Import these instead of hardcoding strings in components or api.js.
 */

// ── Admin ─────────────────────────────────────────────────────────────────────
export const ADMIN_EMAIL = 'agamital@gmail.com';

// ── Season ────────────────────────────────────────────────────────────────────
export const CURRENT_SEASON = '2026';

// ── Series status ─────────────────────────────────────────────────────────────
export const SeriesStatus = {
  ACTIVE:    'active',
  COMPLETED: 'completed',
};

// ── Series round names (must match DB values exactly) ────────────────────────
export const Round = {
  FIRST_ROUND:  'First Round',
  CONF_SEMIS:   'Conference Semifinals',
  CONF_FINALS:  'Conference Finals',
  NBA_FINALS:   'NBA Finals',

  // Short display labels (do NOT send these to the API or store in DB)
  LABELS: {
    'First Round':             'R1',
    'Conference Semifinals':   'R2',
    'Conference Finals':       'CF',
    'NBA Finals':              'Finals',
  },
};

// ── Conference names (must match DB values exactly) ───────────────────────────
export const Conference = {
  EASTERN: 'Eastern',
  WESTERN: 'Western',
};

// ── Play-in game types (must match DB values exactly) ────────────────────────
export const PlayInType = {
  GAME_7V8:    '7v8',
  GAME_9V10:   '9v10',
  ELIMINATION: 'elimination',

  LABELS: {
    '7v8':         'Game 1 — 7 vs 8',
    '9v10':        'Game 2 — 9 vs 10',
    'elimination': 'Game 3 — Elimination',
  },
};

// ── Play-in / Series shared status ───────────────────────────────────────────
export const GameStatus = {
  ACTIVE:    'active',
  COMPLETED: 'completed',
};

// ── Futures prediction field keys (must match DB columns + API params) ────────
export const FuturesKey = {
  CHAMPION:   'champion_team_id',
  WEST_CHAMP: 'west_champ_team_id',
  EAST_CHAMP: 'east_champ_team_id',
  FINALS_MVP: 'finals_mvp',
  WEST_MVP:   'west_finals_mvp',
  EAST_MVP:   'east_finals_mvp',
};

// ── Leaders prediction field keys (must match DB columns + API params) ────────
export const LeadersKey = {
  SCORER:   'top_scorer',
  ASSISTS:  'top_assists',
  REBOUNDS: 'top_rebounds',
  THREES:   'top_threes',
  STEALS:   'top_steals',
  BLOCKS:   'top_blocks',
};
