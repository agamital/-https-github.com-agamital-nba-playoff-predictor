export const BASE_WINNER_PTS   = 50;
export const BASE_GAMES_PTS    = 50;
export const CLOSE_CALL_BONUS  = 15;
export const PLAYIN_PTS        = 20;
export const PLAYIN_UNDERDOG_BONUS = 10;

export const ROUND_MULTIPLIERS = {
  'First Round':            1.0,
  'Conference Semifinals':  1.5,
  'Conference Finals':      2.0,
  'NBA Finals':             3.0,
};

const R1_UNDERDOG = { '1-8': 2.5, '2-7': 2.0, '3-6': 1.5, '4-5': 1.0 };

export const FUTURES_BASE_POINTS = {
  champion: 200, west_champ: 100, east_champ: 100,
  finals_mvp: 150, west_finals_mvp: 50, east_finals_mvp: 50,
};

// Tiered proximity scoring for Leaders predictions.
// Each tier: [maxDelta, points].  First matching delta wins.
export const LEADERS_TIERS = {
  scorer:   [[0, 350], [2, 100], [4, 40]],
  assists:  [[0, 300], [1,  80], [2, 30]],
  rebounds: [[0, 300], [1,  80], [2, 30]],
  threes:   [[0, 250], [1,  50]],
  steals:   [[0, 200]],
  blocks:   [[0, 200]],
};

// Exact-match (bullseye) point values — used for display in scoring guides.
export const LEADERS_POINTS = Object.fromEntries(
  Object.entries(LEADERS_TIERS).map(([k, tiers]) => [k, tiers[0][1]])
);

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
  return 1.5;
}

/** Returns { winnerPts, gamesPts, closeCallPts, totalPts } for a correct winner.
 *  gamesPts = exact games bonus, closeCallPts = off-by-1 bonus. */
export function calcSeriesPts(roundName, homeSeed, awaySeed, pickedSeed) {
  const rm = getRoundMult(roundName);
  const um = getUnderdogMult(roundName, homeSeed, awaySeed, pickedSeed);
  const winnerPts    = Math.floor(BASE_WINNER_PTS  * rm * um);
  const gamesPts     = Math.floor(BASE_GAMES_PTS   * rm * um);
  const closeCallPts = Math.floor(CLOSE_CALL_BONUS * rm * um);
  return { winnerPts, gamesPts, closeCallPts, totalPts: winnerPts + gamesPts };
}
