// ── Privacy lock ──────────────────────────────────────────────────────────────
// Community picks / vote distributions are hidden until the first Play-In game.
// 2026 NBA Play-In tip-off: April 15 @ 7:30 PM ET = 23:30 UTC
export const PICKS_REVEAL_DATE = new Date('2026-04-15T23:30:00Z');

/** Returns true when community picks may be shown to users. */
export const picksRevealed = () => Date.now() >= PICKS_REVEAL_DATE.getTime();

// ── Series base points ─────────────────────────────────────────────────────
export const BASE_WINNER_PTS   = 50;
export const BASE_GAMES_PTS    = 30;   // exact series length bonus (was 50)

// ── Play-In ────────────────────────────────────────────────────────────────
export const PLAYIN_PTS              = 5;    // correct favourite
export const PLAYIN_UNDERDOG_PTS     = 8;    // correct underdog (5+3)
export const PLAYIN_UNDERDOG_BONUS   = 3;    // bonus over favourite

// ── Round multipliers ──────────────────────────────────────────────────────
// NBA Finals winner uses FINALS_CHAMPION_MULT; all others use ROUND_MULTIPLIERS.
export const ROUND_MULTIPLIERS = {
  'First Round':            1.0,
  'Conference Semifinals':  1.5,
  'Conference Finals':      2.0,
  'NBA Finals':             2.5,   // used for exact-games pts in Finals
};
export const FINALS_CHAMPION_MULT = 2.5;  // applied to winner pts in NBA Finals

// ── R1 underdog multipliers ────────────────────────────────────────────────
const R1_UNDERDOG = { '1-8': 2.0, '2-7': 1.5, '3-6': 1.2, '4-5': 1.0 };

// ── Series statistical leader bonus ───────────────────────────────────────
export const SERIES_LEADER_BONUS = 10;  // pts per correct series leader (max 30)

// ── Futures / Global predictions ──────────────────────────────────────────
export const FUTURES_BASE_POINTS = {
  champion:        100,   // NBA Champion
  west_champ:       40,   // Western Conference Champion
  east_champ:       40,   // Eastern Conference Champion
  finals_mvp:       30,   // League / Finals MVP
  west_finals_mvp:  20,   // West Conference MVP
  east_finals_mvp:  20,   // East Conference MVP
};

// ── Variance-based leaders tiers ──────────────────────────────────────────
// Each tier: [maxDelta, points].  First matching delta wins.
export const LEADERS_TIERS = {
  scorer:   [[0, 80], [1, 40], [2, 20]],
  assists:  [[0, 80], [1, 40], [2, 20]],
  rebounds: [[0, 50], [1, 25]],
  threes:   [[0, 50], [1, 25]],
  steals:   [[0, 35]],
  blocks:   [[0, 35]],
};

// Exact-match (bullseye) point values — used for display in scoring guides.
export const LEADERS_POINTS = Object.fromEntries(
  Object.entries(LEADERS_TIERS).map(([k, tiers]) => [k, tiers[0][1]])
);

// ── Helper functions ───────────────────────────────────────────────────────

export function getRoundMult(roundName) {
  return ROUND_MULTIPLIERS[roundName] ?? 1;
}

export function getUnderdogMult(roundName, homeSeed, awaySeed, pickedSeed) {
  if (homeSeed == null || awaySeed == null || pickedSeed == null) return 1.0;
  const underdogSeed = Math.max(homeSeed, awaySeed);
  if (pickedSeed !== underdogSeed) return 1.0;
  if (roundName === 'First Round') {
    const key = `${Math.min(homeSeed, awaySeed)}-${Math.max(homeSeed, awaySeed)}`;
    return R1_UNDERDOG[key] ?? 1.0;
  }
  return 1.5; // late-round underdog flat bonus
}

/** Returns { winnerPts, gamesPts, totalPts } for a correct winner prediction.
 *  NBA Finals winner uses the champion multiplier (2.5×); games use 2.0×. */
export function calcSeriesPts(roundName, homeSeed, awaySeed, pickedSeed) {
  const rm  = getRoundMult(roundName);
  const um  = getUnderdogMult(roundName, homeSeed, awaySeed, pickedSeed);
  const wm  = roundName === 'NBA Finals' ? FINALS_CHAMPION_MULT : rm;
  const winnerPts = Math.floor(BASE_WINNER_PTS * wm * um);
  const gamesPts  = Math.floor(BASE_GAMES_PTS  * rm * um);
  return { winnerPts, gamesPts, totalPts: winnerPts + gamesPts };
}
