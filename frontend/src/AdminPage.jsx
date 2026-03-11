import React, { useState, useEffect } from 'react';
import { Shield, CheckCircle, Trophy, RefreshCw } from 'lucide-react';
import * as api from './services/api';

const Card = ({ children, className }) => (
  <div className={`bg-slate-900/50 border border-slate-800 rounded-lg backdrop-blur-sm ${className}`}>
    {children}
  </div>
);

const TeamButton = ({ team, selected, onClick }) => (
  <button
    onClick={onClick}
    className={`flex items-center gap-2 px-4 py-3 rounded-lg border-2 font-bold transition-all ${
      selected
        ? 'border-orange-500 bg-orange-500/20 text-white'
        : 'border-slate-700 bg-slate-800/50 text-slate-300 hover:border-slate-500'
    }`}
  >
    <img
      src={team.logo_url}
      alt={team.name}
      className="w-8 h-8"
      onError={(e) => e.target.style.display = 'none'}
    />
    <span>{team.abbreviation}</span>
  </button>
);

const SeriesCard = ({ series, onSave }) => {
  const [winnerId, setWinnerId] = useState(series.winner_team_id || null);
  const [games, setGames] = useState(series.actual_games || null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const handleSave = async () => {
    if (!winnerId || !games) return;
    setSaving(true);
    try {
      await onSave(series.id, winnerId, games);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <span className="text-xs font-bold text-orange-400 uppercase">{series.conference}</span>
          <span className="text-xs text-slate-500 ml-2">{series.round}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">{series.prediction_count} picks</span>
          {series.status === 'completed' && (
            <span className="px-2 py-0.5 rounded bg-green-500/20 text-green-400 text-xs font-bold">Done</span>
          )}
        </div>
      </div>

      <div className="flex items-center gap-3 mb-4">
        <img src={series.home_team.logo_url} alt={series.home_team.name} className="w-10 h-10"
          onError={(e) => e.target.style.display = 'none'} />
        <div className="flex-1">
          <p className="font-bold text-white text-sm">{series.home_team.name}</p>
        </div>
        <span className="text-slate-600 font-black">VS</span>
        <div className="flex-1 text-right">
          <p className="font-bold text-white text-sm">{series.away_team.name}</p>
        </div>
        <img src={series.away_team.logo_url} alt={series.away_team.name} className="w-10 h-10"
          onError={(e) => e.target.style.display = 'none'} />
      </div>

      {series.winner_abbreviation && (
        <div className="mb-3 px-3 py-2 rounded bg-green-500/10 border border-green-500/30 text-green-400 text-sm font-bold flex items-center gap-2">
          <CheckCircle className="w-4 h-4" />
          Result: {series.winner_abbreviation} won in {series.actual_games} games
        </div>
      )}

      <div className="mb-3">
        <p className="text-xs text-slate-400 mb-2 uppercase font-bold">Set Winner</p>
        <div className="flex gap-2">
          <TeamButton team={series.home_team} selected={winnerId === series.home_team.id} onClick={() => setWinnerId(series.home_team.id)} />
          <TeamButton team={series.away_team} selected={winnerId === series.away_team.id} onClick={() => setWinnerId(series.away_team.id)} />
        </div>
      </div>

      <div className="mb-4">
        <p className="text-xs text-slate-400 mb-2 uppercase font-bold">Games Played</p>
        <div className="flex gap-2">
          {[4, 5, 6, 7].map(g => (
            <button
              key={g}
              onClick={() => setGames(g)}
              className={`px-4 py-2 rounded-lg border-2 font-bold text-sm transition-all ${
                games === g
                  ? 'border-orange-500 bg-orange-500/20 text-white'
                  : 'border-slate-700 bg-slate-800/50 text-slate-300 hover:border-slate-500'
              }`}
            >
              {g}
            </button>
          ))}
        </div>
      </div>

      <button
        onClick={handleSave}
        disabled={!winnerId || !games || saving}
        className={`w-full py-2 rounded-lg font-bold text-sm transition-all ${
          saved
            ? 'bg-green-500 text-white'
            : !winnerId || !games
            ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
            : 'bg-orange-500 hover:bg-orange-600 text-white'
        }`}
      >
        {saved ? 'Saved!' : saving ? 'Saving...' : 'Set Result'}
      </button>
    </Card>
  );
};

const PlayinCard = ({ game, onSave }) => {
  const [winnerId, setWinnerId] = useState(game.winner_id || null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const handleSave = async () => {
    if (!winnerId) return;
    setSaving(true);
    try {
      await onSave(game.id, winnerId);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <span className="text-xs font-bold text-purple-400 uppercase">{game.conference}</span>
          <span className="text-xs text-slate-500 ml-2">Play-In {game.game_type}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">{game.prediction_count} picks</span>
          {game.status === 'completed' && (
            <span className="px-2 py-0.5 rounded bg-green-500/20 text-green-400 text-xs font-bold">Done</span>
          )}
        </div>
      </div>

      <div className="flex items-center gap-3 mb-4">
        <img src={game.team1.logo_url} alt={game.team1.name} className="w-10 h-10"
          onError={(e) => e.target.style.display = 'none'} />
        <div className="flex-1">
          <p className="font-bold text-white text-sm">{game.team1.name}</p>
        </div>
        <span className="text-slate-600 font-black">VS</span>
        <div className="flex-1 text-right">
          <p className="font-bold text-white text-sm">{game.team2.name}</p>
        </div>
        <img src={game.team2.logo_url} alt={game.team2.name} className="w-10 h-10"
          onError={(e) => e.target.style.display = 'none'} />
      </div>

      {game.winner_abbreviation && (
        <div className="mb-3 px-3 py-2 rounded bg-green-500/10 border border-green-500/30 text-green-400 text-sm font-bold flex items-center gap-2">
          <CheckCircle className="w-4 h-4" />
          Result: {game.winner_abbreviation} won
        </div>
      )}

      <div className="mb-4">
        <p className="text-xs text-slate-400 mb-2 uppercase font-bold">Set Winner</p>
        <div className="flex gap-2">
          <TeamButton team={game.team1} selected={winnerId === game.team1.id} onClick={() => setWinnerId(game.team1.id)} />
          <TeamButton team={game.team2} selected={winnerId === game.team2.id} onClick={() => setWinnerId(game.team2.id)} />
        </div>
      </div>

      <button
        onClick={handleSave}
        disabled={!winnerId || saving}
        className={`w-full py-2 rounded-lg font-bold text-sm transition-all ${
          saved
            ? 'bg-green-500 text-white'
            : !winnerId
            ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
            : 'bg-purple-500 hover:bg-purple-600 text-white'
        }`}
      >
        {saved ? 'Saved!' : saving ? 'Saving...' : 'Set Result'}
      </button>
    </Card>
  );
};

const AdminPage = ({ currentUser }) => {
  const [series, setSeries] = useState([]);
  const [playin, setPlayin] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    load();
  }, []);

  const load = async () => {
    setLoading(true);
    try {
      const [s, p] = await Promise.all([api.getAdminSeries(), api.getAdminPlayin()]);
      setSeries(s);
      setPlayin(p);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleSeriesResult = async (seriesId, winnerTeamId, actualGames) => {
    await api.setSeriesResult(seriesId, winnerTeamId, actualGames);
    const updated = await api.getAdminSeries();
    setSeries(updated);
  };

  const handlePlayinResult = async (gameId, winnerId) => {
    await api.setPlayinResult(gameId, winnerId);
    const updated = await api.getAdminPlayin();
    setPlayin(updated);
  };

  if (!currentUser || currentUser.role !== 'admin') {
    return (
      <div className="max-w-4xl mx-auto px-4 py-12 text-center">
        <Shield className="w-16 h-16 text-slate-600 mx-auto mb-4" />
        <h2 className="text-3xl font-bold text-white mb-4">Admin Only</h2>
        <p className="text-slate-400">You don't have access to this page</p>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-4xl font-black text-white">Admin Panel</h1>
            <span className="px-3 py-1 rounded-full bg-orange-500/20 border border-orange-500/30 text-orange-400 text-xs font-bold uppercase">Admin</span>
          </div>
          <p className="text-slate-400">Set series results — scores update automatically</p>
        </div>
        <button onClick={load} className="flex items-center gap-2 px-4 py-2 rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800/50 transition-all">
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      {loading ? (
        <div className="text-center py-12">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-4 border-orange-500 border-t-transparent"></div>
        </div>
      ) : (
        <>
          {playin.length > 0 && (
            <div className="mb-10">
              <h2 className="text-2xl font-bold text-white mb-4 flex items-center gap-2">
                <Trophy className="w-6 h-6 text-purple-400" />
                Play-In Games
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {playin.map(game => (
                  <PlayinCard key={game.id} game={game} onSave={handlePlayinResult} />
                ))}
              </div>
            </div>
          )}

          <div>
            <h2 className="text-2xl font-bold text-white mb-4 flex items-center gap-2">
              <Trophy className="w-6 h-6 text-orange-400" />
              Playoff Series
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {series.map(s => (
                <SeriesCard key={s.id} series={s} onSave={handleSeriesResult} />
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
};

export default AdminPage;
