import React, { useState, useCallback, useEffect } from 'react';
import { RefreshCw, Trophy, WifiOff, AlertTriangle, Database, Wifi, Star, Clock, X } from 'lucide-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import * as api from './services/api';

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

// ── Recent Games components ─────────────────────────────────────────────────

const GameStatusPill = ({ completed, status, clock, period }) => {
  if (completed)
    return <span className="px-2 py-0.5 rounded-full bg-slate-700/60 text-slate-400 text-[10px] font-bold">Final</span>;
  if (period > 0)
    return (
      <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-orange-500/20 text-orange-400 text-[10px] font-bold">
        <span className="w-1.5 h-1.5 rounded-full bg-orange-400 animate-ping inline-block" />
        Q{period} {clock}
      </span>
    );
  return <span className="px-2 py-0.5 rounded-full bg-slate-700/40 text-slate-500 text-[10px] font-bold">{status || 'Upcoming'}</span>;
};

// Compact game card used for today's schedule (no performers)
const GameCard = ({ game, onClick }) => {
  const { home, away, completed, status, clock, period, broadcast } = game;
  const hasScore = home?.score != null && away?.score != null;
  return (
    <div
      className="bg-slate-900/50 border border-slate-800 rounded-xl p-3 flex flex-col gap-2 cursor-pointer hover:border-orange-500/40 hover:bg-slate-900/80 transition-all"
      onClick={() => onClick && onClick(game)}
    >
      <div className="flex items-center justify-between gap-2">
        <GameStatusPill completed={completed} status={status} clock={clock} period={period} />
        {broadcast && <span className="text-[10px] text-slate-500 font-bold">{broadcast}</span>}
      </div>
      {[away, home].map((team, i) => (
        <div key={i} className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-[10px] text-slate-500 w-7 shrink-0">{i === 0 ? 'AWY' : 'HME'}</span>
            <span className={`text-sm font-bold truncate ${team?.winner ? 'text-white' : 'text-slate-300'}`}>
              {team?.abbr || team?.name || '—'}
            </span>
          </div>
          {hasScore && (
            <span className={`text-sm tabular-nums shrink-0 ${team?.winner ? 'text-white font-black' : 'text-slate-400 font-bold'}`}>
              {team?.score}
            </span>
          )}
        </div>
      ))}
    </div>
  );
};

// Game card with top-2 performers per team — clickable for full boxscore
const GameWithPerformersCard = ({ game, onClick }) => {
  const { home, away, completed, status, clock, period, performers = [] } = game;
  const hasScore = home?.score != null && away?.score != null;
  const awayAbbr = away?.abbr || '';
  const homeAbbr = home?.abbr || '';

  return (
    <div
      className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden cursor-pointer hover:border-orange-500/40 hover:bg-slate-900/80 transition-all group"
      onClick={() => onClick(game)}
    >
      {/* Score header */}
      <div className="px-4 py-2.5 border-b border-slate-800/80 flex items-center gap-3">
        {/* Away */}
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <span className={`text-sm font-black truncate ${away?.winner ? 'text-white' : 'text-slate-400'}`}>
            {awayAbbr || '—'}
          </span>
          {hasScore && (
            <span className={`text-base font-black tabular-nums ${away?.winner ? 'text-orange-400' : 'text-slate-500'}`}>
              {away?.score}
            </span>
          )}
        </div>

        {/* Centre: status + hint */}
        <div className="flex flex-col items-center gap-0.5 shrink-0">
          <GameStatusPill completed={completed} status={status} clock={clock} period={period} />
          <span className="text-[9px] text-slate-700 group-hover:text-orange-500/50 transition-colors">boxscore ↗</span>
        </div>

        {/* Home */}
        <div className="flex items-center gap-2 flex-1 min-w-0 justify-end">
          {hasScore && (
            <span className={`text-base font-black tabular-nums ${home?.winner ? 'text-orange-400' : 'text-slate-500'}`}>
              {home?.score}
            </span>
          )}
          <span className={`text-sm font-black truncate ${home?.winner ? 'text-white' : 'text-slate-400'}`}>
            {homeAbbr || '—'}
          </span>
        </div>
      </div>

      {/* Top-2 performers per team */}
      {performers.length > 0 && (
        <div className="divide-y divide-slate-800/40">
          {performers.map((p, i) => {
            const isAway = p.team_abbr === awayAbbr;
            return (
              <div key={i} className="flex items-center gap-2 px-3 py-2">
                <span className={`text-[10px] font-black w-8 shrink-0 ${isAway ? 'text-blue-400' : 'text-red-400'}`}>
                  {p.team_abbr}
                </span>
                <span className="flex-1 text-xs font-semibold text-slate-200 truncate">{p.player_name}</span>
                <div className="flex items-center gap-2 text-[11px] tabular-nums shrink-0">
                  <span className="font-black text-orange-400 w-5 text-right">{p.points}</span>
                  <span className="text-slate-500 w-5 text-right">{p.rebounds}r</span>
                  <span className="text-slate-500 w-5 text-right">{p.assists}a</span>
                  <span className="text-slate-600 w-5 text-right hidden sm:block">{p.fg3m}3</span>
                  <span className="text-slate-600 w-5 text-right hidden sm:block">{p.steals}s</span>
                  <span className="text-slate-600 w-5 text-right hidden sm:block">{p.blocks}b</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

// Full boxscore modal
const BoxscoreModal = ({ game, onClose }) => {
  const homeAbbr = game.home?.abbr || '';
  const awayAbbr = game.away?.abbr || '';
  const hasScore = game.home?.score != null && game.away?.score != null;

  const { data, isLoading } = useQuery({
    queryKey: ['gameBoxscore', game.id],
    queryFn:  () => api.getGameBoxscore(game.id),
    enabled:  !!game.id,
    staleTime: 30 * 60 * 1000,
  });

  // Close on Escape
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-16" onClick={onClose}>
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" />
      <div
        className="relative bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-2xl max-h-[80vh] overflow-hidden flex flex-col shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        {/* Modal header */}
        <div className="bg-gradient-to-r from-slate-800 to-slate-900 px-5 py-4 flex items-start justify-between border-b border-slate-700 shrink-0">
          <div>
            <h2 className="text-lg font-black text-white">
              {awayAbbr && homeAbbr ? `${awayAbbr} @ ${homeAbbr}` : 'Boxscore'}
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
              {hasScore
                ? `${awayAbbr} ${game.away?.score}  —  ${homeAbbr} ${game.home?.score}`
                : (game.status || 'Full Game Stats')}
            </p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white transition-colors p-1 ml-4 shrink-0">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal body */}
        <div className="overflow-y-auto flex-1">
          {isLoading ? (
            <div className="p-10 text-center text-slate-400 text-sm animate-pulse">Loading boxscore…</div>
          ) : data?.teams?.length ? (
            data.teams.map(team => (
              <div key={team.team_abbr} className="border-b border-slate-800 last:border-b-0">
                {/* Team header */}
                <div className="px-5 py-2 bg-slate-800/50 sticky top-0">
                  <span className="text-xs font-black text-orange-400 tracking-widest uppercase">{team.team_abbr}</span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="bg-slate-800/20">
                        <th className="px-4 py-2 text-left text-[10px] font-bold text-slate-500 uppercase">Player</th>
                        <th className="px-2 py-2 text-center text-[10px] font-bold text-slate-500 uppercase w-10">Min</th>
                        <th className="px-2 py-2 text-center text-[10px] font-bold text-slate-500 uppercase w-10">Pts</th>
                        <th className="px-2 py-2 text-center text-[10px] font-bold text-slate-500 uppercase w-10">Reb</th>
                        <th className="px-2 py-2 text-center text-[10px] font-bold text-slate-500 uppercase w-10">Ast</th>
                        <th className="px-2 py-2 text-center text-[10px] font-bold text-slate-500 uppercase w-10">3PM</th>
                        <th className="px-2 py-2 text-center text-[10px] font-bold text-slate-500 uppercase w-10">Stl</th>
                        <th className="px-2 py-2 text-center text-[10px] font-bold text-slate-500 uppercase w-10">Blk</th>
                        <th className="px-2 py-2 text-center text-[10px] font-bold text-slate-500 uppercase w-10">Tov</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/30">
                      {team.players.map((p, i) => (
                        <tr key={i} className="hover:bg-slate-800/20 transition-colors">
                          <td className="px-4 py-2.5 font-semibold text-white truncate max-w-[150px]">{p.player_name}</td>
                          <td className="px-2 py-2.5 text-center text-slate-500">{p.minutes}</td>
                          <td className="px-2 py-2.5 text-center font-black text-orange-400">{p.points}</td>
                          <td className="px-2 py-2.5 text-center text-slate-300">{p.rebounds}</td>
                          <td className="px-2 py-2.5 text-center text-slate-300">{p.assists}</td>
                          <td className="px-2 py-2.5 text-center text-slate-300">{p.fg3m}</td>
                          <td className="px-2 py-2.5 text-center text-slate-300">{p.steals}</td>
                          <td className="px-2 py-2.5 text-center text-slate-300">{p.blocks}</td>
                          <td className="px-2 py-2.5 text-center text-slate-400">{p.turnovers}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))
          ) : (
            <div className="p-10 text-center text-slate-500 text-sm">
              No boxscore data synced for this game yet.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

const RecentGamesSection = () => {
  const yesterday = new Date(Date.now() - 86400000).toISOString().split('T')[0];
  const today     = new Date().toISOString().split('T')[0];
  const [selectedGame, setSelectedGame] = useState(null);

  const { data: gwpData, isLoading: gwpLoading } = useQuery({
    queryKey: ['gamesWithPerformers', yesterday],
    queryFn:  () => api.getGamesWithPerformers(yesterday),
    staleTime: 30 * 60 * 1000,
  });

  const { data: todayData, isLoading: todayLoading } = useQuery({
    queryKey: ['todayGames', today],
    queryFn:  () => api.getTodayGames(today),
    staleTime: 5 * 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
  });

  const yesterdayGames = gwpData?.games  ?? [];
  const todayGames     = todayData?.games ?? [];
  const hasYesterday   = yesterdayGames.length > 0;
  const hasTodayGames  = todayGames.length > 0;
  const showTodayPanel = hasTodayGames || todayLoading;

  if (!hasYesterday && !hasTodayGames && !gwpLoading && !todayLoading) return null;

  const fmtDate = (d) => {
    try { return new Date(d + 'T12:00:00').toLocaleDateString([], { month: 'short', day: 'numeric' }); }
    catch { return d; }
  };

  return (
    <>
      {selectedGame && (
        <BoxscoreModal game={selectedGame} onClose={() => setSelectedGame(null)} />
      )}

      <div className="mb-8">
        <h2 className="text-xl font-black text-white mb-4 flex items-center gap-2">
          <Star className="w-5 h-5 text-orange-400" />
          Recent Games
        </h2>

        <div className={`grid grid-cols-1 ${showTodayPanel ? 'lg:grid-cols-[2fr_1fr]' : ''} gap-6`}>

          {/* Yesterday's games — top-2 per team per game */}
          <div className="bg-slate-900/50 border border-slate-800 rounded-xl overflow-hidden">
            <div className="bg-gradient-to-r from-orange-600/80 to-orange-800/80 px-5 py-3 flex items-center justify-between">
              <h3 className="text-sm font-black text-white flex items-center gap-2">
                <Trophy className="w-4 h-4" />
                {fmtDate(yesterday)} — Top Performers
              </h3>
              {gwpLoading && <RefreshCw className="w-3.5 h-3.5 text-white/60 animate-spin" />}
            </div>

            {gwpLoading ? (
              <div className="p-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="bg-slate-800/30 rounded-xl p-3 space-y-2 animate-pulse">
                    <div className="h-4 bg-slate-800 rounded w-28" />
                    {[1, 2, 3, 4].map(j => (
                      <div key={j} className="h-3 bg-slate-800/60 rounded" />
                    ))}
                  </div>
                ))}
              </div>
            ) : hasYesterday ? (
              <div className="p-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
                {yesterdayGames.map(g => (
                  <GameWithPerformersCard key={g.id} game={g} onClick={setSelectedGame} />
                ))}
              </div>
            ) : (
              <div className="px-5 py-8 text-center text-slate-500 text-sm">
                No game data for {fmtDate(yesterday)}
              </div>
            )}
          </div>

          {/* Today's games — hidden completely when empty */}
          {showTodayPanel && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <Clock className="w-4 h-4 text-slate-400" />
                <h3 className="text-sm font-black text-white">
                  Today's Games — {fmtDate(today)}
                </h3>
                {todayLoading && <RefreshCw className="w-3.5 h-3.5 text-slate-400 animate-spin" />}
              </div>

              {todayLoading ? (
                <div className="space-y-3">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <div key={i} className="bg-slate-900/50 border border-slate-800 rounded-xl p-4 space-y-3 animate-pulse">
                      <div className="h-3 bg-slate-800 rounded w-16" />
                      <div className="h-3 bg-slate-800 rounded w-full" />
                      <div className="h-3 bg-slate-800 rounded w-full" />
                    </div>
                  ))}
                </div>
              ) : (
                <div className="space-y-3">
                  {todayGames.map(g => (
                    <GameCard key={g.id} game={g} onClick={setSelectedGame} />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
};

// ── Main StandingsPage ──────────────────────────────────────────────────────

const StandingsPage = () => {
  const qc = useQueryClient();
  const [syncBanner, setSyncBanner] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const {
    data,
    isLoading: loading,
    error: queryError,
  } = useQuery({
    queryKey: ['standings'],
    queryFn: () => api.getStandings(),
    staleTime: 5 * 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
  });

  const standings          = data || { eastern: [], western: [] };
  const lastUpdated        = data?.last_updated ?? null;
  const lastSynced         = data?.last_synced_at ?? null;
  const staticMode         = data?.static_mode ?? false;
  const dataSource         = data?.data_source ?? null;
  const consecutiveFails   = data?.consecutive_failures ?? 0;
  const lastSyncError      = data?.last_sync_error ?? null;
  const error              = queryError ? 'Could not reach server. Showing last known data.' : null;

  const timeSince   = useTimeSince(lastUpdated);
  const syncedSince = useTimeSince(lastSynced);

  const loadStandings = useCallback(async (force = false) => {
    if (!force) { qc.invalidateQueries({ queryKey: ['standings'] }); return; }
    setRefreshing(true);
    try {
      await api.getStandings(true);
      await new Promise(r => setTimeout(r, 3500));
      const updated = await api.getStandings(false);
      qc.setQueryData(['standings'], updated);
      setSyncBanner(true);
      setTimeout(() => setSyncBanner(false), 5000);
    } catch {
      // stale data shown from cache
    } finally {
      setRefreshing(false);
    }
  }, [qc]);

  const isLive = lastUpdated && (Date.now() - new Date(lastUpdated)) < 6 * 60 * 1000;

  const StatusBadge = ({ status, rank }) => {
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
                      {team.win_pct != null ? (team.win_pct * 100).toFixed(1) + '%' : '—'}
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
      {staticMode && (
        <div className="mb-4 px-4 py-3 bg-slate-700/40 border border-slate-600/40 rounded-xl text-xs text-slate-300 font-bold flex items-center gap-2">
          <Trophy className="w-3 h-3 text-orange-400 shrink-0" />
          Final regular-season standings — regular season has ended. These results are locked.
        </div>
      )}

      {syncBanner && (
        <div className="mb-4 px-4 py-3 bg-blue-500/10 border border-blue-500/20 rounded-xl text-xs text-blue-400 font-bold flex items-center gap-2">
          <RefreshCw className="w-3 h-3 animate-spin" />
          Live sync triggered — standings will update in ~30 seconds. Refresh the page to see latest data.
        </div>
      )}

      {consecutiveFails > 0 && !staticMode && (
        <div className="mb-4 px-4 py-3 bg-amber-500/10 border border-amber-500/30 rounded-xl text-xs text-amber-400 font-bold flex items-start gap-2">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <div>
            <span>NBA API sync failing ({consecutiveFails} consecutive failure{consecutiveFails > 1 ? 's' : ''}) — showing {dataSource === 'database' ? 'last cached DB data' : 'hardcoded fallback data'}.</span>
            {lastSyncError && (
              <span className="block mt-1 font-normal text-amber-400/70 break-all">{lastSyncError}</span>
            )}
          </div>
        </div>
      )}

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl md:text-4xl font-black text-white mb-1">NBA Standings</h1>
          <div className="flex items-center gap-3 flex-wrap">
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

            {dataSource && (
              <span className={`flex items-center gap-1 text-xs font-bold px-2 py-0.5 rounded-full ${
                dataSource === 'rapidapi'     ? 'bg-green-500/15 text-green-400' :
                dataSource === 'nba_api'      ? 'bg-green-500/15 text-green-400' :
                dataSource === 'browser_push' ? 'bg-green-500/15 text-green-400' :
                dataSource === 'database'     ? 'bg-blue-500/15 text-blue-400' :
                                                'bg-amber-500/15 text-amber-400'
              }`}>
                {['rapidapi','nba_api','browser_push'].includes(dataSource) ? <Wifi className="w-3 h-3" /> :
                 dataSource === 'database' ? <Database className="w-3 h-3" /> :
                                             <AlertTriangle className="w-3 h-3" />}
                {dataSource === 'rapidapi'     ? 'RapidAPI' :
                 dataSource === 'nba_api'      ? 'Live NBA API' :
                 dataSource === 'browser_push' ? 'Browser Push' :
                 dataSource === 'database'     ? 'Database Cache' : 'Hardcoded Fallback'}
              </span>
            )}

            {lastSynced && (
              <span className="text-xs text-slate-400" title={lastSynced}>
                Last sync: {syncedSince} ({new Date(lastSynced).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })})
              </span>
            )}
            {lastUpdated && !lastSynced && (
              <span className="text-xs text-slate-400">Cache: {timeSince}</span>
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

      {/* Recent Games — top performers + today's schedule */}
      <RecentGamesSection />

      {/* Conference standings tables */}
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
