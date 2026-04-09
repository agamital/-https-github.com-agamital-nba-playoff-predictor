import React, { useState, useEffect } from 'react';
import { X, User, ChevronRight, Loader } from 'lucide-react';
import * as api from './services/api';

const StatBox = ({ label, value }) => (
  <div className="bg-slate-800/60 rounded-xl p-3 text-center">
    <div className="text-xl font-black text-white">{value ?? '—'}</div>
    <div className="text-[10px] text-slate-500 uppercase font-bold tracking-wide mt-0.5">{label}</div>
  </div>
);

const PlayerStatsModal = ({ player, onClose }) => {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getPlayerStats(player.id)
      .then(setStats)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [player.id]);

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-slate-900 border border-slate-700 rounded-2xl p-6 max-w-sm w-full shadow-2xl overflow-y-auto overscroll-contain" style={{ maxHeight: 'min(85dvh, 85vh)', WebkitOverflowScrolling: 'touch' }} onClick={e => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-3">
            <img
              src={`https://cdn.nba.com/headshots/nba/latest/1040x760/${player.id}.png`}
              alt={player.name}
              className="w-16 h-16 rounded-xl object-cover bg-slate-800"
              onError={e => { e.target.src = ''; e.target.style.display = 'none'; }}
            />
            <div>
              <h3 className="text-lg font-black text-white">{player.name}</h3>
              <p className="text-sm text-slate-400">{player.position} • #{player.number}</p>
            </div>
          </div>
          <button onClick={onClose} className="w-8 h-8 rounded-full bg-slate-800 text-slate-400 hover:text-white flex items-center justify-center transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader className="w-8 h-8 text-orange-400 animate-spin" />
            <span className="ml-2 text-slate-400 text-sm">Loading stats…</span>
          </div>
        ) : stats?.error ? (
          <p className="text-slate-500 text-center py-4 text-sm">{stats.error}</p>
        ) : stats ? (
          <>
            <p className="text-xs text-slate-500 uppercase font-bold tracking-wide mb-3">{stats.season} Season • {stats.gp} games</p>
            <div className="grid grid-cols-3 gap-2 mb-3">
              <StatBox label="PPG" value={stats.ppg} />
              <StatBox label="RPG" value={stats.rpg} />
              <StatBox label="APG" value={stats.apg} />
            </div>
            <div className="grid grid-cols-3 gap-2 mb-3">
              <StatBox label="SPG" value={stats.spg} />
              <StatBox label="BPG" value={stats.bpg} />
              <StatBox label="GP" value={stats.gp} />
            </div>
            <div className="grid grid-cols-3 gap-2">
              <StatBox label="FG%" value={stats.fg_pct} />
              <StatBox label="3P%" value={stats.fg3_pct} />
              <StatBox label="FT%" value={stats.ft_pct} />
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
};

const TeamDetailsModal = ({ team, onClose }) => {
  const [roster, setRoster] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedPlayer, setSelectedPlayer] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.getTeamRoster(team.id)
      .then(data => {
        if (data.error) setError(data.error);
        setRoster(data.players || []);
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [team.id]);

  return (
    <>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm" onClick={onClose}>
        <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-lg flex flex-col shadow-2xl" style={{ maxHeight: 'min(85dvh, 85vh)' }} onClick={e => e.stopPropagation()}>
          {/* Header */}
          <div className="flex items-center gap-4 p-5 border-b border-slate-800 shrink-0">
            <img src={team.logo_url} alt={team.name} className="w-14 h-14" onError={e => e.target.style.display = 'none'} />
            <div className="flex-1">
              <h2 className="text-xl font-black text-white">{team.name}</h2>
              <p className="text-sm text-slate-400">{team.conference} Conference{team.seed ? ` • Seed #${team.seed}` : ''}</p>
            </div>
            <button onClick={onClose} className="w-11 h-11 rounded-full bg-slate-800 text-slate-400 hover:text-white flex items-center justify-center transition-colors shrink-0">
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Roster */}
          <div className="flex-1 overflow-y-auto overscroll-contain p-4" style={{ WebkitOverflowScrolling: 'touch' }}>
            <p className="text-xs text-slate-500 uppercase font-bold tracking-wide mb-3">2024-25 Roster</p>
            {loading ? (
              <div className="flex items-center justify-center py-12">
                <Loader className="w-8 h-8 text-orange-400 animate-spin" />
                <span className="ml-2 text-slate-400">Loading roster…</span>
              </div>
            ) : error ? (
              <p className="text-slate-500 text-center py-8 text-sm">Could not load roster: {error}</p>
            ) : roster.length === 0 ? (
              <p className="text-slate-500 text-center py-8">No roster data available</p>
            ) : (
              <div className="space-y-1">
                {roster.map(player => (
                  <button key={player.id} onClick={() => setSelectedPlayer(player)}
                    className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl hover:bg-slate-800/60 transition-colors text-left group">
                    <img
                      src={player.photo_url}
                      alt={player.name}
                      className="w-9 h-9 rounded-lg object-cover bg-slate-800 shrink-0"
                      onError={e => { e.target.style.display = 'none'; }}
                    />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-bold text-white group-hover:text-orange-400 transition-colors truncate">{player.name}</p>
                      <p className="text-xs text-slate-500">{player.position}{player.number ? ` • #${player.number}` : ''}</p>
                    </div>
                    <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-orange-400 transition-colors shrink-0" />
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {selectedPlayer && (
        <PlayerStatsModal player={selectedPlayer} onClose={() => setSelectedPlayer(null)} />
      )}
    </>
  );
};

export default TeamDetailsModal;
