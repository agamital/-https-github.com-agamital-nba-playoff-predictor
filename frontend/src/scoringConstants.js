export const BASE_WINNER_PTS = 20;
export const BASE_GAMES_PTS  = 40;
export const PLAYIN_PTS      = 5;

export const ROUND_MULTIPLIERS = {
  'First Round': 1,
  'Conference Semifinals': 2,
  'Conference Finals': 3,
  'NBA Finals': 4,
};

const R1_UNDERDOG = { '1-8': 2.5, '2-7': 2.0, '3-6': 1.5, '4-5': 1.0 };

export const FUTURES_BASE_POINTS = {
  champion: 200, west_champ: 100, east_champ: 100,
  finals_mvp: 80, west_finals_mvp: 50, east_finals_mvp: 50,
};

export const LEADERS_POINTS = {
  scorer: 100, assists: 70, rebounds: 70, threes: 60, steals: 40, blocks: 40,
};

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

/** Returns { winnerPts, gamesPts, totalPts } for a correct winner + correct games */
export function calcSeriesPts(roundName, homeSeed, awaySeed, pickedSeed) {
  const rm = getRoundMult(roundName);
  const um = getUnderdogMult(roundName, homeSeed, awaySeed, pickedSeed);
  const winnerPts = Math.floor(BASE_WINNER_PTS * rm * um);
  const gamesPts  = Math.floor(BASE_GAMES_PTS  * rm * um);
  return { winnerPts, gamesPts, totalPts: winnerPts + gamesPts };
}
