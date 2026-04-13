// API Service - Connects React frontend to Python FastAPI backend

import axios from 'axios';

// Dev: empty string so Vite proxy routes /api/* to localhost:8000
// Production: use VITE_API_URL from .env.production (Railway backend URL)
const API_BASE_URL = import.meta.env.DEV
  ? ''
  : (import.meta.env.VITE_API_URL || 'https://nba-playoff-predictor-production.up.railway.app');

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Separate instance for long-running admin calls (standings sync tries 4 sources
// sequentially — each can take up to 15 s — so we need a generous timeout).
const adminApi = axios.create({
  baseURL: API_BASE_URL,
  timeout: 60000,
  headers: { 'Content-Type': 'application/json' },
});

// Teams
export const getTeams = async (conference = null, playoffOnly = false) => {
  const params = {};
  if (conference) params.conference = conference;
  if (playoffOnly) params.playoff_only = true;
  const response = await api.get('/api/teams', { params });
  return response.data;
};

export const getTeam = async (teamId) => {
  const response = await api.get(`/api/teams/${teamId}`);
  return response.data;
};

// Live Scores
export const getLiveScores = async () => {
  const response = await api.get('/api/live-scores');
  return response.data;
};

// Auth
export const register = async (username, email, password) => {
  const response = await api.post('/api/auth/register', {
    username,
    email,
    password,
  });
  return response.data;
};

export const resetPassword = async (username, newPassword) => {
  const response = await api.post('/api/auth/reset-password', { username, new_password: newPassword });
  return response.data;
};

export const getMe = async (userId) => {
  const response = await api.get(`/api/auth/me?user_id=${userId}`);
  return response.data;
};

export const login = async (username, password) => {
  const response = await api.post('/api/auth/login', {
    username,
    password,
  });
  return response.data;
};

export const loginWithGoogle = async (email, name = '', avatarUrl = '') => {
  const response = await api.post('/api/auth/google', null, {
    params: { email, name, avatar_url: avatarUrl },
  });
  return response.data;
};

// User profiles
export const getUserProfile = async (username) => {
  const response = await api.get(`/api/users/${username}`);
  return response.data;
};

// Account management
export const getAccount = async (userId) => {
  const response = await api.get('/api/account', { params: { user_id: userId } });
  return response.data;
};

export const changeUsername = async (userId, newUsername) => {
  const response = await api.patch('/api/account/username', null, {
    params: { user_id: userId, new_username: newUsername },
  });
  return response.data;
};

export const changePassword = async (userId, currentPassword, newPassword) => {
  const response = await api.patch('/api/account/password', null, {
    params: { user_id: userId, current_password: currentPassword, new_password: newPassword },
  });
  return response.data;
};

export const deleteAccount = async (userId) => {
  const response = await api.delete('/api/account', { params: { user_id: userId } });
  return response.data;
};

export const uploadAvatar = async (userId, file) => {
  const formData = new FormData();
  formData.append('file', file);
  const response = await api.post(`/api/users/${userId}/avatar`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
};

// Series
export const getSeries = async (season = '2026', status = null) => {
  const params = { season };
  if (status) params.status = status;
  const response = await api.get('/api/series', { params });
  return response.data;
};

// Predictions
export const makePrediction = async (userId, seriesId, predictedWinnerId, predictedGames = null, leaders = {}) => {
  const response = await api.post(`/api/predictions?user_id=${userId}`, {
    series_id: seriesId,
    predicted_winner_id: predictedWinnerId,
    predicted_games: predictedGames,
    leading_scorer: leaders.scorer || null,
    leading_rebounder: leaders.rebounder || null,
    leading_assister: leaders.assister || null,
  });
  return response.data;
};

export const getSeriesPlayers = async (seriesId, season = '2026') => {
  const response = await api.get(`/api/series/${seriesId}/players`, { params: { season } });
  return response.data;
};

// Notification summary — missing predictions for the bell badge + popover
export const getNotificationsSummary = async (userId, season = '2026') => {
  const response = await api.get(`/api/notifications/summary?user_id=${userId}&season=${season}`);
  return response.data;
};

// Dashboard (lightweight counts for home page)
export const getDashboard = async (userId, season = '2026') => {
  const response = await api.get(`/api/dashboard?user_id=${userId}&season=${season}`);
  return response.data;
};

// Community picks per series / play-in game
export const getSeriesPicks = async (seriesId) => {
  const response = await api.get(`/api/series/${seriesId}/picks`);
  return response.data;
};

export const getPlayInPicks = async (gameId) => {
  const response = await api.get(`/api/playin/${gameId}/picks`);
  return response.data;
};

// Global community stats
export const getGlobalStats = async (season = '2026') => {
  const response = await api.get('/api/stats/global', { params: { season } });
  return response.data;
};

// Leaderboard
export const getLeaderboard = async (season = '2026', limit = 100) => {
  const response = await api.get('/api/leaderboard', {
    params: { season, limit },
  });
  return response.data;
};

// Standings
export const getStandings = async (forceRefresh = false) => {
  const response = await api.get('/api/standings', { params: forceRefresh ? { force_refresh: true } : {} });
  return response.data;
};

export const adminSyncStandings = async () => {
  const response = await adminApi.post('/api/admin/standings/sync');
  return response.data;
};

// Push browser-fetched NBA API data to the backend (bypasses server IP block)
export const pushStandingsFromBrowser = async (resultSets) => {
  const response = await adminApi.post('/api/admin/standings/push', { resultSets });
  return response.data;
};

// Quick server-side connection test — returns #1 East team name
export const testStandingsConnection = async () => {
  const response = await adminApi.get('/api/admin/standings/test');
  return response.data;
};

// Play-In Games
export const getPlayInGames = async (season = '2026', conference = null) => {
  const params = { season };
  if (conference) params.conference = conference;
  const response = await api.get('/api/playin-games', { params });
  return response.data;
};

export const makePlayInPrediction = async (userId, gameId, predictedWinnerId) => {
  const response = await api.post(
    `/api/playin-predictions?user_id=${userId}&game_id=${gameId}&predicted_winner_id=${predictedWinnerId}`
  );
  return response.data;
};

// Admin Functions
export const generateMatchups = async (season = '2026') => {
  const response = await api.post(`/api/admin/regenerate-matchups?season=${season}`);
  return response.data;
};

export const regenerateMatchups = async (conference = null, season = '2026') => {
  const params = new URLSearchParams({ season });
  if (conference) params.append('conference', conference);
  const response = await api.post(`/api/admin/regenerate-matchups?${params}`);
  return response.data;
};

export const generatePlayIn = async (season = '2026') => {
  const response = await api.post(`/api/admin/generate-playin?season=${season}`);
  return response.data;
};

export const syncSeeds = async (season = '2026') => {
  const response = await api.post(`/api/admin/sync-seeds?season=${season}`);
  return response.data;
};

// Get user's predictions
export const getMyPredictions = async (userId, season = '2026') => {
  const response = await api.get(`/api/my-predictions?user_id=${userId}&season=${season}`);
  return response.data;
};

// Admin
export const getAdminSeries = async (season = '2026') => {
  const response = await api.get('/api/admin/series', { params: { season } });
  return response.data;
};

export const setSeriesResult = async (seriesId, winnerTeamId, actualGames, manualOverride = false, leaders = {}) => {
  const params = { winner_team_id: winnerTeamId, actual_games: actualGames, manual_override: manualOverride };
  // Only include leader params if explicitly provided (undefined = keep existing, '' = clear)
  if (leaders.scorer   !== undefined) params.actual_leading_scorer    = leaders.scorer;
  if (leaders.rebounder !== undefined) params.actual_leading_rebounder = leaders.rebounder;
  if (leaders.assister  !== undefined) params.actual_leading_assister  = leaders.assister;
  const response = await api.post(`/api/admin/series/${seriesId}/result`, null, { params });
  return response.data;
};

export const resetSeriesResult = async (seriesId) => {
  const response = await api.delete(`/api/admin/series/${seriesId}/result`);
  return response.data;
};

export const syncAndAdvance = async (season = '2026') => {
  const response = await api.post(`/api/admin/sync-and-advance?season=${season}`);
  return response.data;
};

export const getAdminPlayin = async (season = '2026') => {
  const response = await api.get('/api/admin/playin', { params: { season } });
  return response.data;
};

export const setPlayinResult = async (gameId, winnerId) => {
  const response = await api.post(`/api/admin/playin/${gameId}/result`, null, {
    params: { winner_id: winnerId }
  });
  return response.data;
};

export const resetPlayinResult = async (gameId) => {
  const response = await api.delete(`/api/admin/playin/${gameId}/result`);
  return response.data;
};

export const syncPlayin = async (season = '2026') => {
  const response = await api.post(`/api/admin/playin/sync?season=${season}`);
  return response.data;
};

// Futures Predictions
export const getFutures = async (userId, season = '2026') => {
  const response = await api.get(`/api/futures?user_id=${userId}&season=${season}`);
  return response.data;
};

export const saveFutures = async (userId, data, season = '2026') => {
  const params = new URLSearchParams({ user_id: userId, season });
  if (data.champion_team_id) params.append('champion_team_id', data.champion_team_id);
  if (data.west_champ_team_id) params.append('west_champ_team_id', data.west_champ_team_id);
  if (data.east_champ_team_id) params.append('east_champ_team_id', data.east_champ_team_id);
  if (data.finals_mvp) params.append('finals_mvp', data.finals_mvp);
  if (data.west_finals_mvp) params.append('west_finals_mvp', data.west_finals_mvp);
  if (data.east_finals_mvp) params.append('east_finals_mvp', data.east_finals_mvp);
  const response = await api.post(`/api/futures?${params.toString()}`);
  return response.data;
};

export const getFuturesLockStatus = async () => {
  const response = await api.get('/api/futures/lock-status');
  return response.data;
};

export const setFuturesLock = async (locked) => {
  const response = await api.post('/api/admin/futures/lock', null, { params: { locked } });
  return response.data;
};

export const getLeadersLockStatus = async () => {
  const response = await api.get('/api/leaders/lock-status');
  return response.data;
};

export const setLeadersLock = async (locked) => {
  const response = await api.post('/api/admin/leaders/lock', null, { params: { locked } });
  return response.data;
};

export const getFuturesLeaderboard = async (season = '2026') => {
  const response = await api.get(`/api/futures/leaderboard?season=${season}`);
  return response.data;
};

export const getFuturesAll = async (season = '2026') => {
  const response = await api.get(`/api/futures/all?season=${season}`);
  return response.data;
};

// Playoff Leaders
export const getLeadersPrediction = async (userId, season = '2026') => {
  const response = await api.get(`/api/leaders?user_id=${userId}&season=${season}`);
  return response.data;
};

export const saveLeadersPrediction = async (userId, data, season = '2026') => {
  const params = new URLSearchParams({ user_id: userId, season });
  // Only append positive integer values
  const intVal = (v) => { const n = parseInt(v, 10); return Number.isFinite(n) && n > 0 ? n : null; };
  const ts = intVal(data.top_scorer);   if (ts)  params.append('top_scorer',   ts);
  const ta = intVal(data.top_assists);  if (ta)  params.append('top_assists',  ta);
  const tr = intVal(data.top_rebounds); if (tr)  params.append('top_rebounds', tr);
  const tt = intVal(data.top_threes);   if (tt)  params.append('top_threes',   tt);
  const tst = intVal(data.top_steals);  if (tst) params.append('top_steals',   tst);
  const tb = intVal(data.top_blocks);   if (tb)  params.append('top_blocks',   tb);
  const response = await api.post(`/api/leaders?${params.toString()}`);
  return response.data;
};

export const getAdminLeadersResults = async (season = '2026') => {
  const response = await api.get(`/api/admin/leaders/results?season=${season}`);
  return response.data;
};

export const setAdminLeadersResults = async (data, season = '2026') => {
  const params = new URLSearchParams({ season });
  const intVal = (v) => { const n = parseInt(v, 10); return Number.isFinite(n) && n > 0 ? n : null; };
  const ts = intVal(data.top_scorer);   if (ts)  params.append('top_scorer',   ts);
  const ta = intVal(data.top_assists);  if (ta)  params.append('top_assists',  ta);
  const tr = intVal(data.top_rebounds); if (tr)  params.append('top_rebounds', tr);
  const tt = intVal(data.top_threes);   if (tt)  params.append('top_threes',   tt);
  const tst = intVal(data.top_steals);  if (tst) params.append('top_steals',   tst);
  const tb = intVal(data.top_blocks);   if (tb)  params.append('top_blocks',   tb);
  const response = await api.post(`/api/admin/leaders/results?${params.toString()}`);
  return response.data;
};

export const getAdminOdds = async () => {
  const response = await api.get('/api/admin/odds');
  return response.data;
};

export const setAdminOdds = async (odds) => {
  const params = new URLSearchParams(Object.entries(odds).map(([k, v]) => [k, String(v)]));
  const response = await api.post(`/api/admin/odds?${params.toString()}`);
  return response.data;
};

export const getAdminTeamOdds = async () => {
  const response = await api.get('/api/admin/team-odds');
  return response.data;
};

export const setAdminTeamOdds = async (updates) => {
  const response = await api.post('/api/admin/team-odds', updates);
  return response.data;
};

export const updateTeamOdds = async (teamId, oddsChampionship, oddsConference) => {
  const params = new URLSearchParams({
    team_id: teamId,
    odds_championship: oddsChampionship,
    odds_conference: oddsConference,
  });
  const response = await api.post(`/api/admin/update-odds?${params.toString()}`);
  return response.data;
};

export const getAdminFuturesResults = async (season = '2026') => {
  const response = await api.get(`/api/admin/futures/results?season=${season}`);
  return response.data;
};

export const setAdminFuturesResults = async (data, season = '2026') => {
  const params = new URLSearchParams({ season });
  if (data.actual_champion_id)       params.append('actual_champion_id',       data.actual_champion_id);
  if (data.actual_west_champ_id)     params.append('actual_west_champ_id',     data.actual_west_champ_id);
  if (data.actual_east_champ_id)     params.append('actual_east_champ_id',     data.actual_east_champ_id);
  if (data.actual_finals_mvp)        params.append('actual_finals_mvp',        data.actual_finals_mvp);
  if (data.actual_west_finals_mvp)   params.append('actual_west_finals_mvp',   data.actual_west_finals_mvp);
  if (data.actual_east_finals_mvp)   params.append('actual_east_finals_mvp',   data.actual_east_finals_mvp);
  const response = await api.post(`/api/admin/futures/results?${params.toString()}`);
  return response.data;
};

export const lockSeries = async (seriesId, locked) => {
  const response = await api.post(`/api/admin/series/${seriesId}/lock?locked=${locked}`);
  return response.data;
};

export const getTeamRoster = async (teamId) => {
  const response = await api.get(`/api/teams/${teamId}/roster`);
  return response.data;
};

export const getPlayerStats = async (playerId) => {
  const response = await api.get(`/api/players/${playerId}/stats`);
  return response.data;
};

// Statistical leaders from the synced player_stats table (top 10 per category)
export const getPlayerLeaders = async (season = '2026', limit = 10, playoffOnly = true) => {
  const response = await api.get('/api/players/leaders', { params: { season, limit, playoff_only: playoffOnly } });
  return response.data;
};

export const getPlayoffEligiblePlayers = async (season = '2026') => {
  const response = await api.get('/api/players/playoff-eligible', { params: { season } });
  return response.data;
};

// Admin — User Management
export const getAdminUsers = async (adminUserId) => {
  const response = await api.get('/api/admin/users', { params: { admin_user_id: adminUserId } });
  return response.data;
};

export const updateAdminUser = async (adminUserId, userId, { username, points } = {}) => {
  const params = { admin_user_id: adminUserId };
  if (username !== undefined) params.username = username;
  if (points   !== undefined) params.points   = points;
  const response = await api.patch(`/api/admin/users/${userId}`, null, { params });
  return response.data;
};

export const deleteAdminUser = async (adminUserId, userId) => {
  const response = await api.delete(`/api/admin/users/${userId}`, { params: { admin_user_id: adminUserId } });
  return response.data;
};

export const syncPlayerStats = async () => {
  const response = await api.post('/api/admin/player-stats/sync');
  return response.data;
};

export const getFmvpProbability = async (season = '2026') => {
  const response = await api.get('/api/fmvp/probability', { params: { season } });
  return response.data;
};

export const toggleUserReminderOptOut = async (adminUserId, userId, optOut) => {
  const response = await api.patch(`/api/admin/users/${userId}`, null, {
    params: { admin_user_id: adminUserId, reminder_opt_out: optOut },
  });
  return response.data;
};

// Futures page — combined static data (teams + odds + lock)
export const getFuturesPageData = async (season = '2026') => {
  const response = await api.get('/api/futures/page-data', { params: { season } });
  return response.data;
};

// Player search — debounced, conference-filtered, sorted by PPG
export const searchPlayers = async (q, conference = 'All', limit = 15, season = '2026', mvp_type = '') => {
  const response = await api.get('/api/players/search', {
    params: { q, conference, limit, season, mvp_type },
  });
  return response.data;
};

// Admin — Play-In sync from API
export const syncPlayinFromApi = async (season = '2026') => {
  const response = await api.post('/api/admin/playin/sync-from-api', null, { params: { season } });
  return response.data;
};

// Admin — Playoff series sync from API
export const syncPlayoffsFromApi = async (season = '2026') => {
  const response = await api.post('/api/admin/playoffs/sync-from-api', null, { params: { season } });
  return response.data;
};

export const triggerReminderJob = async () => {
  const response = await api.post('/api/admin/trigger-reminder');
  return response.data;
};

export const sendTestEmail = async (to) => {
  const response = await api.post('/api/admin/send-test-email', null, { params: { to } });
  return response.data;
};

// Boxscore / player-game stats
export const syncBoxscores = async (date = null, season = '2026') => {
  const params = { season };
  if (date) params.date = date;
  const response = await adminApi.post('/api/admin/boxscore/sync', null, { params });
  return response.data;
};

export const getGamesWithPerformers = async (date = null, season = '2026') => {
  const params = { season };
  if (date) params.date = date;
  const response = await api.get('/api/players/games-with-performers', { params });
  return response.data;
};

export const getGameBoxscore = async (espnGameId, season = '2026') => {
  const response = await api.get('/api/players/game-boxscore', {
    params: { espn_game_id: espnGameId, season },
  });
  return response.data;
};

export const getTopPerformers = async (date = null, limit = 5, season = '2026') => {
  const params = { limit, season };
  if (date) params.date = date;
  const response = await api.get('/api/players/top-performers', { params });
  return response.data;
};

export const getTodayGames = async (date = null) => {
  const params = date ? { date } : {};
  const response = await api.get('/api/players/today-games', { params });
  return response.data;
};

export default api;
