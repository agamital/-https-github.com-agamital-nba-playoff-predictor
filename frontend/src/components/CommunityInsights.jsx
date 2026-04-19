import React, { useState, useEffect } from 'react';
import { Users, ChevronDown, Lock } from 'lucide-react';
import * as api from '../services/api';
import { picksRevealed } from '../scoringConstants';

/**
 * Community vote bar + expandable picks list for a series or play-in game.
 *
 * Props:
 *   seriesId      – for playoff series (mutually exclusive with gameId)
 *   gameId        – for play-in games
 *   homeTeam      – { abbreviation, logo_url }
 *   awayTeam      – { abbreviation, logo_url }
 *   initialStats  – pre-fetched { total_votes, home_pct, away_pct } or null
 *   status        – series/game status: 'active' | 'locked' | 'completed'
 *   startZ        – ISO UTC string of game/series Game 1 tipoff time
 *   seriesActuals – { scorer, rebounder, assister } — actual leaders once complete
 *                   (already available on the series object from /api/series)
 */

/** Tiny badge shown on each leader pick after a series ends */
const LeaderCorrect = ({ picked, actual }) => {
  if (!picked) return null;
  const done   = actual != null;
  const correct = done && picked.trim().toLowerCase() === actual.trim().toLowerCase();
  if (!done) return (
    <span className="text-[8px] text-slate-600 font-bold italic">pending</span>
  );
  return correct
    ? <span className="text-[8px] font-black text-green-400">✓</span>
    : <span className="text-[8px] font-black text-red-500">✗</span>;
};

const CommunityInsights = ({
  seriesId, gameId,
  homeTeam, awayTeam,
  initialStats = null,
  status,
  startZ,
  seriesActuals,   // { scorer, rebounder, assister }
}) => {
  const [open, setOpen]       = useState(false);
  const [picks, setPicks]     = useState(null);
  const [loading, setLoading] = useState(false);
  const [stats, setStats]     = useState(initialStats);

  // Determine whether individual pick names are revealed.
  const startMs = startZ ? new Date(startZ).getTime() : null;
  const _timerPast  = startMs != null && Date.now() >= startMs;
  const _initVisible = _timerPast || (status != null ? status !== 'active' : picksRevealed());
  const [picksVisible, setPicksVisible] = useState(_initVisible);

  // One-shot timer to flip visibility at tipoff
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
        setPicks(data);           // store the whole response
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

  // Actuals: prefer prop (already on series obj) then fall back to fetched data
  const actuals = seriesActuals ?? (picks ? {
    scorer:    picks.actual_leading_scorer,
    rebounder: picks.actual_leading_rebounder,
    assister:  picks.actual_leading_assister,
  } : null);

  const isCompleted = status === 'completed';
  const userPicks   = picks?.picks ?? null;
  const hasLeaders  = userPicks?.some(p => p.leading_scorer || p.leading_rebounder || p.leading_assister);

  return (
    <div className="pt-2 border-t border-slate-800/60 mt-1">
      {/* Toggle row */}
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

      {/* Pct labels */}
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

      {/* Lock hint */}
      {!picksVisible && (
        <p className="text-[9px] text-slate-700 font-bold text-center mt-0.5">
          Names revealed when this game tips off
        </p>
      )}

      {/* Expanded picks list */}
      {open && picksVisible && (
        <div className="mt-2 max-h-72 overflow-y-auto rounded-xl bg-slate-900/60 border border-slate-800/80">
          {loading ? (
            <div className="flex items-center justify-center py-4">
              <div className="w-5 h-5 border-2 border-orange-500 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : userPicks && userPicks.length > 0 ? (
            <div className="divide-y divide-slate-800/60">
              {userPicks.map((p, i) => {
                /* Winner correctness badge */
                const isComplete = isCompleted || picks?.series_status === 'completed';
                const hasResult  = p.is_correct !== null && p.is_correct !== undefined;

                const hasLeaderPicks = p.leading_scorer || p.leading_rebounder || p.leading_assister;

                return (
                  <div key={i} className="px-3 py-2">
                    {/* ── Top row: avatar / name / winner pick / result ── */}
                    <div className="flex items-center gap-2">
                      {/* Avatar */}
                      {p.avatar_url ? (
                        <img
                          src={p.avatar_url}
                          alt=""
                          className="w-5 h-5 rounded-full object-cover shrink-0"
                          onError={e => { e.target.style.display = 'none'; }}
                        />
                      ) : (
                        <div className="w-5 h-5 rounded-full bg-slate-700 flex items-center justify-center shrink-0">
                          <span className="text-[7px] font-black text-slate-400">
                            {(p.username || '?')[0].toUpperCase()}
                          </span>
                        </div>
                      )}

                      <span className="text-xs font-bold text-slate-300 flex-1 truncate">
                        {p.username}
                      </span>

                      {/* Winner pick */}
                      <div className="flex items-center gap-1.5 shrink-0">
                        <img
                          src={p.team_logo_url}
                          alt=""
                          className="w-4 h-4"
                          onError={e => e.target.style.display = 'none'}
                        />
                        <span className="text-[10px] font-black text-orange-400">
                          {p.team_abbreviation}
                        </span>
                        {p.predicted_games && (
                          <span className="text-[10px] text-slate-500 font-bold">
                            in {p.predicted_games}
                          </span>
                        )}
                      </div>

                      {/* Winner result badge */}
                      {hasResult && isComplete && (
                        p.is_correct === 1 ? (
                          <span className="text-[8px] font-black text-green-400 bg-green-500/15 border border-green-500/30 px-1.5 py-0.5 rounded-full shrink-0 whitespace-nowrap">
                            ✓{p.points_earned > 0 ? ` +${p.points_earned}` : ''}
                          </span>
                        ) : (
                          <span className="text-[8px] font-black text-red-400 bg-red-500/15 border border-red-500/30 px-1.5 py-0.5 rounded-full shrink-0">
                            ✗
                          </span>
                        )
                      )}
                    </div>

                    {/* ── Leader picks sub-row ── */}
                    {hasLeaderPicks && (
                      <div className="mt-1.5 ml-7 flex flex-wrap gap-x-3 gap-y-0.5">
                        {p.leading_scorer && (
                          <span className="flex items-center gap-1 text-[9px] text-slate-500">
                            <span className="text-slate-600">🏀</span>
                            <span className="font-bold text-slate-400">{p.leading_scorer}</span>
                            <LeaderCorrect picked={p.leading_scorer} actual={actuals?.scorer ?? null} />
                          </span>
                        )}
                        {p.leading_rebounder && (
                          <span className="flex items-center gap-1 text-[9px] text-slate-500">
                            <span className="text-slate-600">💪</span>
                            <span className="font-bold text-slate-400">{p.leading_rebounder}</span>
                            <LeaderCorrect picked={p.leading_rebounder} actual={actuals?.rebounder ?? null} />
                          </span>
                        )}
                        {p.leading_assister && (
                          <span className="flex items-center gap-1 text-[9px] text-slate-500">
                            <span className="text-slate-600">🎯</span>
                            <span className="font-bold text-slate-400">{p.leading_assister}</span>
                            <LeaderCorrect picked={p.leading_assister} actual={actuals?.assister ?? null} />
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
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
