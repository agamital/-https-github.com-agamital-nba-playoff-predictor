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
 *   homeTeam      – { abbreviation, logo_url }  (team1 for play-in)
 *   awayTeam      – { abbreviation, logo_url }  (team2 for play-in)
 *   initialStats  – pre-fetched { total_votes, home_pct, away_pct } or null
 *                   When null the section lazy-loads on first expand.
 *   status        – series/game status string: 'active' | 'locked' | 'completed'
 *                   Individual picks are hidden while status === 'active'.
 *                   Falls back to global picksRevealed() when not provided.
 *   startZ        – ISO UTC string of game/series Game 1 tipoff time.
 *                   Picks unlock immediately when this time is reached,
 *                   without waiting for a status sync from the server.
 */
const CommunityInsights = ({ seriesId, gameId, homeTeam, awayTeam, initialStats = null, status, startZ }) => {
  const [open, setOpen]       = useState(false);
  const [picks, setPicks]     = useState(null);
  const [loading, setLoading] = useState(false);
  const [stats, setStats]     = useState(initialStats);

  // Determine whether individual pick names are revealed.
  // Priority order:
  //  1. startZ passed and time has passed → immediately revealed at tipoff
  //  2. status prop not 'active' (server confirmed game/series started)
  //  3. Global picksRevealed() fallback (first play-in game date)
  const startMs = startZ ? new Date(startZ).getTime() : null;
  const _timerPast = startMs != null && Date.now() >= startMs;
  const _initVisible = _timerPast || (status != null ? status !== 'active' : picksRevealed());
  const [picksVisible, setPicksVisible] = useState(_initVisible);

  // If the timer hasn't fired yet, schedule a one-shot to flip it exactly at tipoff
  useEffect(() => {
    if (picksVisible) return;
    if (!startMs) return;
    const ms = startMs - Date.now();
    if (ms <= 0) { setPicksVisible(true); return; }
    const t = setTimeout(() => setPicksVisible(true), ms);
    return () => clearTimeout(t);
  }, [startMs, picksVisible]);

  // With pre-fetched stats: hide component if nobody voted yet.
  // Without pre-fetched stats: always render (lazy-load button).
  if (initialStats !== null && (!stats || stats.total_votes === 0)) return null;

  const handleToggle = async () => {
    if (!picksVisible) return; // locked — ignore clicks
    const next = !open;
    setOpen(next);
    if (next && !picks) {
      setLoading(true);
      try {
        const data = seriesId
          ? await api.getSeriesPicks(seriesId)
          : await api.getPlayInPicks(gameId);
        setPicks(data.picks);
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

  return (
    <div className="pt-2 border-t border-slate-800/60 mt-1">
      {/* Toggle row — always rendered; expand is gated by picksVisible */}
      <button
        onClick={handleToggle}
        disabled={!picksVisible}
        className={`w-full flex items-center gap-2 py-1 ${picksVisible ? 'group' : 'cursor-default'}`}
      >
        <Users className="w-3 h-3 text-slate-500 shrink-0" />

        {stats ? (
          /* Vote bar — always visible when stats are available */
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

      {/* Pct labels — always visible when stats present */}
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

      {/* Lock hint when picks not yet revealed */}
      {!picksVisible && (
        <p className="text-[9px] text-slate-700 font-bold text-center mt-0.5">
          Names revealed when this game tips off
        </p>
      )}

      {/* Expanded picks list — only when picksVisible */}
      {open && picksVisible && (
        <div className="mt-2 max-h-48 overflow-y-auto rounded-xl bg-slate-900/60 border border-slate-800/80">
          {loading ? (
            <div className="flex items-center justify-center py-4">
              <div className="w-5 h-5 border-2 border-orange-500 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : picks && picks.length > 0 ? (
            <div className="divide-y divide-slate-800/60">
              {picks.map((p, i) => (
                <div key={i} className="flex items-center gap-2 px-3 py-2">
                  {/* User avatar */}
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
                </div>
              ))}
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
