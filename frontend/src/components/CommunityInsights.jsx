import React, { useState, useEffect } from 'react';
import { Users, ChevronDown, Lock } from 'lucide-react';
import * as api from '../services/api';
import { picksRevealed } from '../scoringConstants';

/**
 * Community vote bar + expandable picks table for a series or play-in game.
 *
 * Props:
 *   seriesId      – for playoff series (mutually exclusive with gameId)
 *   gameId        – for play-in games
 *   homeTeam      – { abbreviation, logo_url }
 *   awayTeam      – { abbreviation, logo_url }
 *   initialStats  – pre-fetched { total_votes, home_pct, away_pct } or null
 *   status        – 'active' | 'locked' | 'completed'
 *   startZ        – ISO UTC string of Game 1 tipoff
 *   seriesActuals – { scorer, rebounder, assister } actual leaders (completed series)
 */

const lastName = (name) => {
  if (!name) return '—';
  const parts = name.trim().split(' ');
  return parts[parts.length - 1];
};

const leaderCorrect = (picked, actual) => {
  if (!picked || !actual) return null;
  return picked.trim().toLowerCase() === actual.trim().toLowerCase();
};

const CommunityInsights = ({
  seriesId, gameId,
  homeTeam, awayTeam,
  initialStats = null,
  status,
  startZ,
  seriesActuals,
}) => {
  const [open, setOpen]       = useState(false);
  const [picks, setPicks]     = useState(null);
  const [loading, setLoading] = useState(false);
  const [stats, setStats]     = useState(initialStats);

  const startMs = startZ ? new Date(startZ).getTime() : null;
  const _timerPast   = startMs != null && Date.now() >= startMs;
  const _initVisible = _timerPast || (status != null ? status !== 'active' : picksRevealed());
  const [picksVisible, setPicksVisible] = useState(_initVisible);

  useEffect(() => {
    if (picksVisible) return;
    if (!startMs) return;
    const ms = startMs - Date.now();
    if (ms <= 0) { setPicksVisible(true); return; }
    const t = setTimeout(() => setPicksVisible(true), ms);
    return () => clearTimeout(t);
  }, [startMs, picksVisible]);

  if (initialStats !== null && (!stats || stats.total_votes === 0)) return null;

  const handleToggle = async () => {
    if (!picksVisible) return;
    const next = !open;
    setOpen(next);
    if (next && !picks) {
      setLoading(true);
      try {
        const data = seriesId
          ? await api.getSeriesPicks(seriesId)
          : await api.getPlayInPicks(gameId);
        setPicks(data);
        setStats({
          total_votes: data.total_votes,
          home_pct: seriesId ? data.home_pct : data.team1_pct,
          away_pct: seriesId ? data.away_pct : data.team2_pct,
        });
      } catch (e) {
        console.error('CommunityInsights fetch error:', e);
      } finally {
        setLoading(false);
      }
    }
  };

  const totalVotes = stats?.total_votes ?? 0;
  const homePct    = stats?.home_pct   ?? 50;
  const awayPct    = stats?.away_pct   ?? 50;

  // Actual leaders: prefer prop then fall back to fetched data
  const actuals = seriesActuals ?? (picks ? {
    scorer:    picks.actual_leading_scorer    ?? null,
    rebounder: picks.actual_leading_rebounder ?? null,
    assister:  picks.actual_leading_assister  ?? null,
  } : null);

  const isCompleted = status === 'completed' || picks?.series_status === 'completed';
  const userPicks   = picks?.picks ?? null;
  const isSeries    = !!seriesId;

  return (
    <div className="pt-2 border-t border-slate-800/60 mt-1">
      {/* Toggle button */}
      <button
        onClick={handleToggle}
        disabled={!picksVisible}
        className={`w-full flex items-center gap-2 py-1 ${picksVisible ? 'group' : 'cursor-default'}`}
      >
        <Users className="w-3 h-3 text-slate-500 shrink-0" />

        {stats ? (
          <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden flex mx-0.5">
            <div
              className="h-full bg-blue-500/70 transition-all duration-500"
              style={{ width: `${homePct}%` }}
            />
            <div className="h-full bg-orange-500/60 flex-1" />
          </div>
        ) : (
          <span className="flex-1 text-[10px] text-slate-500 font-bold text-left">
            {picksVisible ? 'See community picks' : 'Community picks'}
          </span>
        )}

        <span className="text-[10px] text-slate-500 font-bold shrink-0 flex items-center gap-0.5">
          {totalVotes > 0 ? `${totalVotes} ${totalVotes === 1 ? 'pick' : 'picks'}` : ''}
          {picksVisible
            ? <ChevronDown className={`w-3 h-3 transition-transform ${open ? 'rotate-180' : ''}`} />
            : <Lock className="w-3 h-3 opacity-60" />
          }
        </span>
      </button>

      {/* Percentage labels */}
      {stats && totalVotes > 0 && (
        <div className="flex items-center justify-between px-5">
          <span className="text-[9px] font-black text-blue-400">
            {homeTeam?.abbreviation} {homePct}%
          </span>
          <span className="text-[9px] font-black text-orange-400">
            {awayPct}% {awayTeam?.abbreviation}
          </span>
        </div>
      )}

      {!picksVisible && (
        <p className="text-[9px] text-slate-700 font-bold text-center mt-0.5">
          Names revealed when this game tips off
        </p>
      )}

      {/* Expanded picks table */}
      {open && picksVisible && (
        <div className="mt-2 rounded-xl bg-slate-900/60 border border-slate-800/80 overflow-hidden">
          {loading ? (
            <div className="flex items-center justify-center py-4">
              <div className="w-5 h-5 border-2 border-orange-500 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : userPicks && userPicks.length > 0 ? (
            <div className="overflow-x-auto max-h-72">
              <table className="w-full" style={{ minWidth: isSeries ? 320 : 220 }}>
                {/* Column headers */}
                <thead className="sticky top-0 bg-slate-900/95 border-b border-slate-800">
                  <tr>
                    <th className="text-left px-3 py-1.5 text-[8px] font-black text-slate-500 uppercase tracking-wider">
                      User
                    </th>
                    <th className="text-center px-1 py-1.5 text-[8px] font-black text-slate-500 uppercase tracking-wider">
                      Pick
                    </th>
                    {isSeries && (
                      <>
                        <th className="text-center px-1 py-1.5 text-[8px] font-black text-slate-500 uppercase tracking-wider">
                          🏀 Scorer
                        </th>
                        <th className="text-center px-1 py-1.5 text-[8px] font-black text-slate-500 uppercase tracking-wider">
                          💪 Reb
                        </th>
                        <th className="text-center px-1 py-1.5 text-[8px] font-black text-slate-500 uppercase tracking-wider">
                          🎯 Ast
                        </th>
                      </>
                    )}
                    <th className="px-2 py-1.5 w-8" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/40">
                  {userPicks.filter(Boolean).map((p, i) => {
                    const hasResult = p.is_correct !== null && p.is_correct !== undefined;
                    const scorerOk    = leaderCorrect(p.leading_scorer,    actuals?.scorer);
                    const rebounderOk = leaderCorrect(p.leading_rebounder, actuals?.rebounder);
                    const assisterOk  = leaderCorrect(p.leading_assister,  actuals?.assister);

                    return (
                      <tr key={i} className="hover:bg-slate-800/20 transition-colors">
                        {/* User */}
                        <td className="px-3 py-2">
                          <div className="flex items-center gap-1.5">
                            {p.avatar_url ? (
                              <img
                                src={p.avatar_url}
                                alt=""
                                className="w-4 h-4 rounded-full object-cover shrink-0"
                                onError={e => { e.target.style.display = 'none'; }}
                              />
                            ) : (
                              <div className="w-4 h-4 rounded-full bg-slate-700 flex items-center justify-center shrink-0">
                                <span className="text-[6px] font-black text-slate-400">
                                  {(p.username || '?')[0].toUpperCase()}
                                </span>
                              </div>
                            )}
                            <span className="text-[10px] font-bold text-slate-300 truncate max-w-[70px]">
                              {p.username}
                            </span>
                          </div>
                        </td>

                        {/* Winner pick + games */}
                        <td className="px-1 py-2 text-center">
                          <div className="flex items-center justify-center gap-1">
                            <img
                              src={p.team_logo_url}
                              alt=""
                              className="w-4 h-4 shrink-0"
                              onError={e => e.target.style.display = 'none'}
                            />
                            <span className="text-[10px] font-black text-orange-400 whitespace-nowrap">
                              {p.team_abbreviation}
                              {p.predicted_games ? ` G${p.predicted_games}` : ''}
                            </span>
                          </div>
                        </td>

                        {/* Series leader picks */}
                        {isSeries && (
                          <>
                            {/* Scorer */}
                            <td className="px-1 py-2 text-center">
                              {p.leading_scorer ? (
                                <span className={`text-[10px] font-bold whitespace-nowrap ${
                                  scorerOk === true  ? 'text-green-400' :
                                  scorerOk === false ? 'text-red-400'   : 'text-slate-300'
                                }`}>
                                  {lastName(p.leading_scorer)}
                                  {scorerOk === true  && ' ✓'}
                                  {scorerOk === false && ' ✗'}
                                </span>
                              ) : (
                                <span className="text-[10px] text-slate-700">—</span>
                              )}
                            </td>
                            {/* Rebounder */}
                            <td className="px-1 py-2 text-center">
                              {p.leading_rebounder ? (
                                <span className={`text-[10px] font-bold whitespace-nowrap ${
                                  rebounderOk === true  ? 'text-green-400' :
                                  rebounderOk === false ? 'text-red-400'   : 'text-slate-300'
                                }`}>
                                  {lastName(p.leading_rebounder)}
                                  {rebounderOk === true  && ' ✓'}
                                  {rebounderOk === false && ' ✗'}
                                </span>
                              ) : (
                                <span className="text-[10px] text-slate-700">—</span>
                              )}
                            </td>
                            {/* Assister */}
                            <td className="px-1 py-2 text-center">
                              {p.leading_assister ? (
                                <span className={`text-[10px] font-bold whitespace-nowrap ${
                                  assisterOk === true  ? 'text-green-400' :
                                  assisterOk === false ? 'text-red-400'   : 'text-slate-300'
                                }`}>
                                  {lastName(p.leading_assister)}
                                  {assisterOk === true  && ' ✓'}
                                  {assisterOk === false && ' ✗'}
                                </span>
                              ) : (
                                <span className="text-[10px] text-slate-700">—</span>
                              )}
                            </td>
                          </>
                        )}

                        {/* Result badge */}
                        <td className="px-2 py-2 text-right">
                          {hasResult && isCompleted && (
                            p.is_correct === 1 ? (
                              <span className="text-[8px] font-black text-green-400 whitespace-nowrap">
                                ✓{p.points_earned > 0 ? ` +${p.points_earned}` : ''}
                              </span>
                            ) : (
                              <span className="text-[8px] font-black text-red-400">✗</span>
                            )
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-xs text-slate-600 text-center py-3">
              {totalVotes === 0 ? 'No picks yet — be the first!' : 'No picks data available'}
            </p>
          )}
        </div>
      )}
    </div>
  );
};

export default CommunityInsights;
