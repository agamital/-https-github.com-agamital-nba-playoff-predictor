import React, { useState, useEffect, useRef, useCallback } from 'react';
import { RefreshCw, Trophy, WifiOff } from 'lucide-react';
import * as api from './services/api';

const AUTO_REFRESH_MS = 5 * 60 * 1000; // 5 minutes

function useTimeSince(isoString) {
  const [text, setText] = useState('');
  useEffect(() => {
    if (!isoString) return;
    const update = () => {
      const secs = Math.floor((Date.now() - new Date(isoString)) / 1000);
      if (secs < 60) setText(`${secs}s ago`);
      else if (secs < 3600) setText(`${Math.floor(secs / 60)}m ago`);
      else setText(`${Math.floor(secs / 3600)}h ago`);
    };
    update();
    const id = setInterval(update, 10000);
    return () => clearInterval(id);
  }, [isoString]);
  return text;
}

const StandingsPage = () => {
  const [standings, setStandings]     = useState({ eastern: [], western: [] });
  const [loading, setLoading]         = useState(true);
  const [refreshing, setRefreshing]   = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [lastSynced, setLastSynced]   = useState(null);
  const [syncBanner, setSyncBanner]   = useState(false);
  const [error, setError]             = useState(null);
  const intervalRef = useRef(null);
  const timeSince   = useTimeSince(lastUpdated);
  const syncedSince = useTimeSince(lastSynced);

  const loadStandings = useCallback(async (force = false) => {
    if (force) setRefreshing(true);
    else if (standings.eastern.length === 0) setLoading(true);
    setError(null);
    try {
      const data = await api.getStandings(force);
      setStandings(data);
      setLastUpdated(data.last_updated);
      if (data.last_synced_at) setLastSynced(data.last_synced_at);
      if (force && data.sync_triggered) {
        setSyncBanner(true);
        setTimeout(() => setSyncBanner(false), 5000);
      }
    } catch (err) {
      console.error('Error loading standings:', err);
      setError('Could not reach server. Showing last known data.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []); // eslint-disable-line

  // Auto-refresh every 5 min
  useEffect(() => {
    loadStandings();

    intervalRef.current = setInterval(() => loadStandings(), AUTO_REFRESH_MS);

    return () => {
      clearInterval(intervalRef.current);
    };
  }, [loadStandings]);

  const isLive = lastUpdated && (Date.now() - new Date(lastUpdated)) < 6 * 60 * 1000;

  const StatusBadge = ({ status, rank }) => {
    // Use backend status when available; fall back to rank-based derivation
    const s = status || (rank <= 6 ? 'Playoff' : rank <= 10 ? 'Play-In' : 'Eliminated');
    if (s === 'Playoff')
      return <span className="px-2 py-0.5 rounded-full bg-green-500/20 text-green-400 text-[10px] font-black">Playoff</span>;
    if (s === 'Play-In')
      return <span className="px-2 py-0.5 rounded-full bg-yellow-500/20 text-yellow-400 text-[10px] font-black">Play-In</span>;
    return null;
  };

  const StandingsTable = ({ teams, conference }) => {
    const color = conference === 'Eastern' ? 'from-blue-600 to-blue-800' : 'from-red-600 to-red-800';
    return (
      <div className="bg-slate-900/50 border border-slate-800 rounded-xl overflow-hidden">
        <div className={`bg-gradient-to-r ${color} px-5 py-4`}>
          <h2 className="text-xl font-black text-white flex items-center gap-2">
            <Trophy className="w-5 h-5" />
            {conference} Conference
          </h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-slate-800/50">
              <tr>
                <th className="px-4 py-3 text-left text-[11px] font-bold text-slate-400 uppercase w-10">#</th>
                <th className="px-4 py-3 text-left text-[11px] font-bold text-slate-400 uppercase">Team</th>
                <th className="px-3 py-3 text-center text-[11px] font-bold text-slate-400 uppercase">W</th>
                <th className="px-3 py-3 text-center text-[11px] font-bold text-slate-400 uppercase">L</th>
                <th className="px-3 py-3 text-center text-[11px] font-bold text-slate-400 uppercase">PCT</th>
                <th className="px-3 py-3 text-center text-[11px] font-bold text-slate-400 uppercase hidden sm:table-cell">GB</th>
                <th className="px-3 py-3 text-center text-[11px] font-bold text-slate-400 uppercase">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {teams.map((team) => {
                const rank      = team.conf_rank;
                const isPlayoff = rank <= 6;
                const isPlayIn  = rank >= 7 && rank <= 10;
                return (
                  <tr key={team.team_id}
                    className={`transition-colors hover:bg-slate-800/40 ${
                      isPlayoff ? 'bg-green-500/5' : isPlayIn ? 'bg-yellow-500/5' : ''
                    }`}>
                    <td className="px-4 py-3">
                      <span className={`text-sm font-black ${
                        isPlayoff ? 'text-green-400' : isPlayIn ? 'text-yellow-400' : 'text-slate-500'
                      }`}>{rank}</span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <img
                          src={`https://cdn.nba.com/logos/nba/${team.team_id}/primary/L/logo.svg`}
                          alt=""
                          className="w-9 h-9 shrink-0"
                          onError={e => e.target.style.display = 'none'}
                        />
                        <span className="font-bold text-white text-sm">{team.team_name}</span>
                      </div>
                    </td>
                    <td className="px-3 py-3 text-center font-black text-white text-sm">{team.wins}</td>
                    <td className="px-3 py-3 text-center font-bold text-slate-400 text-sm">{team.losses}</td>
                    <td className="px-3 py-3 text-center text-slate-300 text-sm">
                      {(team.win_pct * 100).toFixed(1)}%
                    </td>
                    <td className="px-3 py-3 text-center text-slate-500 text-sm hidden sm:table-cell">
                      {rank === 1 ? '—' : (team.games_back != null ? team.games_back.toFixed(1) : '—')}
                    </td>
                    <td className="px-3 py-3 text-center">
                      <StatusBadge status={team.status} rank={rank} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="px-5 py-3 bg-slate-800/30 border-t border-slate-800 flex items-center gap-4 text-[11px] text-slate-500">
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-green-500/60" />Playoff (1–6)</span>
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-yellow-500/60" />Play-In (7–10)</span>
        </div>
      </div>
    );
  };

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      {/* Sync-triggered banner */}
      {syncBanner && (
        <div className="mb-4 px-4 py-3 bg-blue-500/10 border border-blue-500/20 rounded-xl text-xs text-blue-400 font-bold flex items-center gap-2">
          <RefreshCw className="w-3 h-3 animate-spin" />
          Live sync triggered — standings will update in ~30 seconds. Refresh the page to see latest data.
        </div>
      )}

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl md:text-4xl font-black text-white mb-1">NBA Standings</h1>
          <div className="flex items-center gap-3 flex-wrap">
            {/* Live indicator */}
            <div className="flex items-center gap-1.5">
              {isLive ? (
                <>
                  <span className="relative flex h-2 w-2">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
                  </span>
                  <span className="text-xs text-green-400 font-bold">Live</span>
                </>
              ) : (
                <>
                  <WifiOff className="w-3 h-3 text-slate-500" />
                  <span className="text-xs text-slate-500 font-bold">Cached</span>
                </>
              )}
            </div>

            {lastUpdated && (
              <span className="text-xs text-slate-400">Cache: {timeSince}</span>
            )}
            {lastSynced && (
              <span className="text-xs text-slate-500">
                DB sync: {syncedSince}
              </span>
            )}
          </div>

          {error && (
            <p className="text-xs text-yellow-400 mt-1 flex items-center gap-1">
              <WifiOff className="w-3 h-3" /> {error}
            </p>
          )}
        </div>

        <button
          onClick={() => loadStandings(true)}
          disabled={loading || refreshing}
          className="flex items-center gap-2 px-4 py-2.5 min-h-[44px] rounded-xl border border-slate-700 bg-slate-900/60 text-slate-300 hover:border-orange-500/50 hover:text-orange-400 transition-all text-sm font-bold disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <RefreshCw className={`w-4 h-4 ${(loading || refreshing) ? 'animate-spin' : ''}`} />
          {refreshing ? 'Refreshing…' : 'Force Refresh'}
        </button>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {[{ conf: 'Eastern', color: 'from-blue-600 to-blue-800' }, { conf: 'Western', color: 'from-red-600 to-red-800' }].map(({ conf, color }) => (
            <div key={conf} className="bg-slate-900/50 border border-slate-800 rounded-xl overflow-hidden">
              <div className={`bg-gradient-to-r ${color} px-5 py-4`}>
                <div className="h-5 w-44 bg-white/20 rounded animate-pulse" />
              </div>
              <div className="divide-y divide-slate-800/60">
                {Array.from({ length: 10 }).map((_, i) => (
                  <div key={i} className="px-4 py-3 flex items-center gap-3 animate-pulse">
                    <div className="w-4 h-4 rounded bg-slate-800 shrink-0" />
                    <div className="w-9 h-9 rounded-full bg-slate-800 shrink-0" />
                    <div className="flex-1 h-3 bg-slate-800 rounded" />
                    <div className="w-6 h-3 bg-slate-800 rounded" />
                    <div className="w-6 h-3 bg-slate-800/60 rounded" />
                    <div className="w-10 h-3 bg-slate-800/60 rounded" />
                    <div className="w-14 h-4 bg-slate-800/30 rounded-full" />
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <StandingsTable teams={standings.eastern || []} conference="Eastern" />
          <StandingsTable teams={standings.western || []} conference="Western" />
        </div>
      )}
    </div>
  );
};

export default StandingsPage;
