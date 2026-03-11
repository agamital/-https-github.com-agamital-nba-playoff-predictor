// API Service - Connects React frontend to Python FastAPI backend

import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Teams
export const getTeams = async (conference = null) => {
  const params = conference ? { conference } : {};
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

export const login = async (username, password) => {
  const response = await api.post('/api/auth/login', {
    username,
    password,
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
export const makePrediction = async (userId, seriesId, predictedWinnerId, predictedGames = null) => {
  const response = await api.post(`/api/predictions?user_id=${userId}`, {
    series_id: seriesId,
    predicted_winner_id: predictedWinnerId,
    predicted_games: predictedGames,
  });
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
export const getStandings = async () => {
  const response = await api.get('/api/standings');
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
  const response = await api.post(`/api/playin-predictions?user_id=${userId}`, {
    game_id: gameId,
    predicted_winner_id: predictedWinnerId,
  });
  return response.data;
};

// Admin Functions
export const generateMatchups = async (season = '2026') => {
  const response = await api.post(`/api/admin/generate-matchups?season=${season}`);
  return response.data;
};

export const generatePlayIn = async (season = '2026') => {
  const response = await api.post(`/api/admin/generate-playin?season=${season}`);
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

export const setSeriesResult = async (seriesId, winnerTeamId, actualGames) => {
  const response = await api.post(`/api/admin/series/${seriesId}/result`, null, {
    params: { winner_team_id: winnerTeamId, actual_games: actualGames }
  });
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

export default api;
