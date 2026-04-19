import React, { useState, useEffect } from 'react';
import { Trophy, CheckCircle, XCircle, Star, ArrowLeft, Medal, BarChart2, Lock, Eye, EyeOff } from 'lucide-react';
import * as api from './services/api';
import { ADMIN_EMAIL } from './constants';

const Card = ({ children, className = '' }) => (
  <div className={`bg-slate-900/50 border border-slate-800 rounded-lg backdrop-blur-sm ${className}`}>
    {children}
  </div>
);

export const Avatar = ({ username, avatarUrl, size = 'md' }) => {
  const sizes = {
    sm:  'w-8 h-8 text-sm',
    md:  'w-12 h-12 text-lg',
    lg:  'w-20 h-20 text-3xl',
    xl:  'w-28 h-28 text-4xl',
  };
  if (avatarUrl) {
    return (
      <img
        src={avatarUrl}
        alt={username}
        className={`${sizes[size]} rounded-full object-cover ring-2 ring-slate-700`}
        loading="lazy"
        decoding="async"
        onError={(e) => { e.target.onerror = null; e.target.style.display = 'none'; }}
      />
    );
  }
  return (
    <div className={`${sizes[size]} bg-gradient-to-br from-blue-500 to-purple-600 rounded-full flex items-center justify-center text-white font-black shrink-0`}>
      {username?.[0]?.toUpperCase() || '?'}
    </div>
  );
};

const ResultBadge = ({ isCorrect, points }) => {
  if (isCorrect === 1) return (
    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-green-500/20 border border-green-500/30 text-green-400 text-xs font-black shrink-0">
      <CheckCircle className="w-3.5 h-3.5" />
      {points > 0 ? `+${points} pts` : 'Correct'}
    </div>
  );
  if (isCorrect === 0) return (
    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-red-500/20 border border-red-500/30 text-red-400 text-xs font-black shrink-0">
      <XCircle className="w-3.5 h-3.5" />
      Wrong
    </div>
  );
  return null;
};

const FuturesPick = ({ label, color, team, mvp, isCorrect }) => {
  const border =
    isCorrect === 1 ? 'border-green-500/40 bg-green-500/5' :
    isCorrect === 0 ? 'border-red-500/40 bg-red-500/5' :
    'border-slate-700/60';
  return (
    <div className={`rounded-xl border p-3 flex items-center gap-3 ${border}`}>
      <div className="flex-1 min-w-0">
        <p className={`text-[10px] font-black uppercase tracking-wider mb-1 ${color}`}>{label}</p>
        {team ? (
          <div className="flex items-center gap-2">
            <img src={team.logo_url} alt="" className="w-7 h-7 shrink-0" onError={e => e.target.style.display='none'} />
            <span className="text-sm font-black text-white truncate">{team.name}</span>
          </div>
        ) : mvp ? (
          <p className="text-sm font-bold text-white truncate">{mvp}</p>
        ) : (
          <p className="text-xs text-slate-600 italic">Not picked</p>
        )}
      </div>
      {isCorrect === 1 && <CheckCircle className="w-4 h-4 text-green-400 shrink-0" />}
      {isCorrect === 0 && <XCircle className="w-4 h-4 text-red-400 shrink-0" />}
    </div>
  );
};

// ── Small correctness pill for a single leader pick ──────────────────────────
const LeaderPickRow = ({ emoji, label, picked, actual, isFinished }) => {
  if (!picked) return null;
  const correct  = isFinished && actual != null
    ? picked.trim().toLowerCase() === actual.trim().toLowerCase()
    : null;
  const border =
    correct === true  ? 'border-green-500/30 bg-green-500/5'
    : correct === false ? 'border-red-500/30 bg-red-500/5'
    : 'border-slate-700/50';
  return (
    <div className={`flex items-center gap-1.5 px-2 py-1 rounded-lg border ${border}`}>
      <span className="text-[10px]">{emoji}</span>
      <div className="flex-1 min-w-0">
        <p className="text-[8px] font-black uppercase tracking-wider text-slate-600 leading-none">{label}</p>
        <p className="text-[10px] font-bold text-slate-300 truncate leading-tight mt-0.5">{picked}</p>
      </div>
      {correct === true  && <CheckCircle className="w-3 h-3 text-green-400 shrink-0" />}
      {correct === false && <XCircle    className="w-3 h-3 text-red-400   shrink-0" />}
    </div>
  );
};

// ── Playoff prediction card ───────────────────────────────────────────────────
const PlayoffPredCard = ({ pred }) => {
  const finished  = pred.series_finished;
  const correct   = pred.is_correct;
  const cardBorder =
    correct === 1 ? 'border-green-500/30 bg-green-500/5' :
    correct === 0 ? 'border-red-500/30   bg-red-500/5'   :
    'border-slate-800';

  const hasLeaders = pred.leading_scorer || pred.leading_rebounder || pred.leading_assister;

  return (
    <Card className={`p-4 ${cardBorder}`}>
      {/* Header */}
      <div className="flex items-start justify-between mb-3 gap-2">
        <div>
          <p className="text-[10px] text-slate-500 font-bold uppercase tracking-wider mb-1">
            {pred.conference} · {pred.round}
          </p>
          <div className="flex items-center gap-2 flex-wrap">
            <img src={pred.home_team?.logo_url} alt="" className="w-6 h-6" onError={e=>e.target.style.display='none'} />
            <span className="text-xs text-slate-300 font-bold">{pred.home_team?.abbreviation}</span>
            {finished && (
              <span className="text-[10px] font-black text-slate-500">
                {pred.home_wins}–{pred.away_wins}
              </span>
            )}
            <span className="text-slate-600 text-xs">vs</span>
            <img src={pred.away_team?.logo_url} alt="" className="w-6 h-6" onError={e=>e.target.style.display='none'} />
            <span className="text-xs text-slate-300 font-bold">{pred.away_team?.abbreviation}</span>
          </div>
        </div>
        <ResultBadge isCorrect={correct} points={pred.points_earned} />
      </div>

      {/* Winner pick */}
      <div className="flex items-center gap-2 flex-wrap pt-3 border-t border-slate-800/60">
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-orange-500/20 border border-orange-500/30">
          <img src={pred.predicted_winner?.logo_url} alt="" className="w-5 h-5" onError={e=>e.target.style.display='none'} />
          <span className="text-orange-400 text-xs font-black">{pred.predicted_winner?.name}</span>
        </div>
        {pred.predicted_games && (
          <span className="px-2.5 py-1.5 rounded-lg bg-blue-500/20 border border-blue-500/30 text-blue-400 text-xs font-bold">
            in {pred.predicted_games}G
          </span>
        )}
        {/* Pending series — show lock icon */}
        {!finished && pred.picks_locked && correct == null && (
          <span className="ml-auto flex items-center gap-1 text-slate-600 text-[10px]">
            <Lock className="w-3 h-3" /> Awaiting result
          </span>
        )}
      </div>

      {/* Leader picks section */}
      {hasLeaders && (
        <div className="mt-3 pt-2 border-t border-slate-800/50">
          <p className="text-[9px] font-black uppercase tracking-wider text-slate-600 mb-2">Series Leaders Picks</p>
          <div className="grid grid-cols-3 gap-1.5">
            <LeaderPickRow
              emoji="🏀" label="Top Scorer"
              picked={pred.leading_scorer}
              actual={pred.actual_leading_scorer}
              isFinished={finished}
            />
            <LeaderPickRow
              emoji="💪" label="Top Rebounder"
              picked={pred.leading_rebounder}
              actual={pred.actual_leading_rebounder}
              isFinished={finished}
            />
            <LeaderPickRow
              emoji="🎯" label="Top Assister"
              picked={pred.leading_assister}
              actual={pred.actual_leading_assister}
              isFinished={finished}
            />
          </div>
          {/* Show actual leaders when series is done */}
          {finished && (pred.actual_leading_scorer || pred.actual_leading_rebounder || pred.actual_leading_assister) && (
            <div className="mt-2 flex flex-wrap gap-2">
              {pred.actual_leading_scorer && (
                <span className="text-[9px] text-slate-500 font-bold">
                  Actual scorer: <span className="text-slate-300">{pred.actual_leading_scorer}</span>
                </span>
              )}
              {pred.actual_leading_rebounder && (
                <span className="text-[9px] text-slate-500 font-bold">
                  · Reb: <span className="text-slate-300">{pred.actual_leading_rebounder}</span>
                </span>
              )}
              {pred.actual_leading_assister && (
                <span className="text-[9px] text-slate-500 font-bold">
                  · Ast: <span className="text-slate-300">{pred.actual_leading_assister}</span>
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </Card>
  );
};

// ── Play-in prediction card ───────────────────────────────────────────────────
const PlayinPredCard = ({ pred }) => {
  const finished = pred.game_finished;
  const correct  = pred.is_correct;
  const cardBorder =
    correct === 1 ? 'border-green-500/30 bg-green-500/5' :
    correct === 0 ? 'border-red-500/30   bg-red-500/5'   :
    'border-slate-800';

  const GAME_LABELS = { '7v8': 'Game 1 — 7 vs 8', '9v10': 'Game 2 — 9 vs 10', 'elimination': 'Game 3 — Elimination' };

  return (
    <Card className={`p-4 ${cardBorder}`}>
      <div className="flex items-start justify-between mb-3 gap-2">
        <div>
          <p className="text-[10px] text-slate-500 font-bold uppercase tracking-wider mb-1">
            {pred.conference} · Play-In
          </p>
          <p className="text-xs text-slate-400">{GAME_LABELS[pred.game_type] || pred.game_type}</p>
          <p className="text-xs text-slate-500 mt-0.5">{pred.team1?.name} vs {pred.team2?.name}</p>
        </div>
        <ResultBadge isCorrect={correct} points={pred.points_earned} />
      </div>

      <div className="flex items-center gap-2 pt-3 border-t border-slate-800/60">
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-purple-500/20 border border-purple-500/30">
          <img src={pred.predicted_winner?.logo_url} alt="" className="w-5 h-5" onError={e=>e.target.style.display='none'} />
          <span className="text-purple-400 text-xs font-black">{pred.predicted_winner?.abbreviation}</span>
        </div>
        {!finished && pred.picks_locked && correct == null && (
          <span className="ml-auto flex items-center gap-1 text-slate-600 text-[10px]">
            <Lock className="w-3 h-3" /> Awaiting result
          </span>
        )}
      </div>
    </Card>
  );
};

// ── Main page ─────────────────────────────────────────────────────────────────
const UserProfilePage = ({ username, currentUser, onNavigateToProfile, onBack }) => {
  const [profile, setProfile]         = useState(null);
  const [predictions, setPredictions] = useState(null);
  const [loading, setLoading]         = useState(true);
  const [predsLoading, setPredsLoading] = useState(false);
  const [error, setError]             = useState('');

  const isAdmin = currentUser?.email === ADMIN_EMAIL;

  useEffect(() => {
    if (!username) return;
    setLoading(true);
    setError('');
    setPredictions(null);

    api.getUserProfile(username)
      .then(prof => {
        setProfile(prof);
        setLoading(false);
        setPredsLoading(true);
        return api.getMyPredictions(prof.user_id, '2026', currentUser?.user_id ?? null);
      })
      .then(preds => setPredictions(preds))
      .catch(err => {
        setError(err.response?.status === 404 ? 'User not found.' : 'Failed to load profile.');
        setLoading(false);
      })
      .finally(() => setPredsLoading(false));
  }, [username]);

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-8">
        <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-6 mb-8 animate-pulse">
          <div className="flex items-center gap-5">
            <div className="w-28 h-28 rounded-full bg-slate-800 shrink-0" />
            <div className="flex-1 space-y-3">
              <div className="h-7 w-40 bg-slate-800 rounded" />
              <div className="h-4 w-56 bg-slate-800 rounded" />
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (error || !profile) {
    return (
      <div className="max-w-xl mx-auto px-4 py-16 text-center">
        <p className="text-slate-400 text-lg">{error || 'User not found.'}</p>
      </div>
    );
  }

  const isOwnProfile = currentUser?.username === profile.username;
  const canSeeAll    = isAdmin || isOwnProfile;

  const playoff = predictions?.playoff_predictions || [];
  const playin  = predictions?.playin_predictions  || [];
  const futures = predictions?.futures_prediction;
  const leaders = predictions?.leaders_prediction  || null;
  const hasHiddenFutures = predictions?.has_hidden_futures ?? false;
  const hasHiddenLeaders = predictions?.has_hidden_leaders ?? false;

  // Only count series/play-in that have been scored for accuracy (not future rounds)
  const scoredPlayoff = playoff.filter(p => p.series_finished);
  const scoredPlayin  = playin.filter(p => p.game_finished);
  const scoredCount   = scoredPlayoff.length + scoredPlayin.filter(p => p.is_correct !== null && p.is_correct !== undefined).length;
  const correctCount  = playoff.filter(p => p.is_correct === 1).length
                      + playin.filter(p => p.is_correct === 1).length;
  const scoredDenom   = scoredPlayoff.length;  // for series-only accuracy card
  const pointsFromPicks = playoff.reduce((s, p) => s + (p.points_earned || 0), 0)
    + playin.reduce((s, p) => s + (p.points_earned || 0), 0);

  const underdogPicks = playoff.filter(p => {
    const hSeed = p.home_team?.seed ?? null;
    const aSeed = p.away_team?.seed ?? null;
    if (hSeed == null || aSeed == null) return false;
    const underdogId = hSeed > aSeed ? p.home_team?.id : p.away_team?.id;
    return p.predicted_winner?.id === underdogId;
  });
  const underdogPct = playoff.length > 0 ? Math.round((underdogPicks.length / playoff.length) * 100) : null;
  const boldWins = playoff.filter(p => p.is_correct === 1 && (p.points_earned ?? 0) > 60);
  const riskProfile = underdogPct == null ? null
    : underdogPct >= 40 ? { label: 'Aggressive 🔥', cls: 'text-amber-400 bg-amber-500/10 border-amber-500/30', desc: 'You love the long shot.' }
    : underdogPct >= 15 ? { label: 'Balanced ⚖️',   cls: 'text-blue-400  bg-blue-500/10  border-blue-500/30',  desc: 'Mix of safe and bold picks.' }
    :                     { label: 'Safe 🛡️',        cls: 'text-green-400 bg-green-500/10 border-green-500/30', desc: 'You play it safe with favorites.' };

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      {onBack && (
        <button onClick={onBack} className="flex items-center gap-1.5 text-slate-400 hover:text-white mb-4 transition-colors text-sm font-bold">
          <ArrowLeft className="w-4 h-4" /> Back to Leaderboard
        </button>
      )}

      {/* ── Profile header ── */}
      <Card className="p-6 mb-8">
        <div className="flex items-center gap-5">
          <Avatar username={profile.username} avatarUrl={profile.avatar_url} size="xl" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-2xl md:text-3xl font-black text-white truncate">{profile.username}</h1>
              {isOwnProfile && (
                <span className="px-2 py-0.5 rounded-full bg-orange-500/20 border border-orange-500/30 text-orange-400 text-xs font-black">You</span>
              )}
              {isAdmin && !isOwnProfile && (
                <span className="px-2 py-0.5 rounded-full bg-red-500/20 border border-red-500/30 text-red-400 text-xs font-black flex items-center gap-1">
                  <Eye className="w-3 h-3" /> Admin View
                </span>
              )}
              {riskProfile && (
                <span className={`px-2.5 py-0.5 rounded-full border text-xs font-black ${riskProfile.cls}`}>{riskProfile.label}</span>
              )}
            </div>
            <div className="flex items-center gap-4 mt-3 flex-wrap">
              <div className="flex items-center gap-1.5">
                <Medal className="w-4 h-4 text-yellow-400" />
                <span className="text-yellow-400 font-black text-lg">#{profile.rank}</span>
                <span className="text-slate-500 text-sm">rank</span>
              </div>
              <div className="flex items-center gap-1.5">
                <Trophy className="w-4 h-4 text-orange-400" />
                <span className="text-orange-400 font-black text-lg">{profile.points}</span>
                <span className="text-slate-500 text-sm">points</span>
              </div>
              {playoff.length > 0 && (
                <div className="flex items-center gap-1.5">
                  <CheckCircle className="w-4 h-4 text-green-400" />
                  <span className="text-green-400 font-black text-lg">{correctCount}/{playoff.length}</span>
                  <span className="text-slate-500 text-sm">correct</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </Card>

      {/* ── Hidden bets notice for other users ── */}
      {!canSeeAll && (
        <div className="flex items-center gap-2 px-4 py-3 rounded-lg bg-slate-800/60 border border-slate-700 text-slate-400 text-sm mb-6">
          <EyeOff className="w-4 h-4 shrink-0 text-slate-500" />
          Picks for games that haven't started yet are hidden until the game tips off.
        </div>
      )}

      {/* ── Stats Section ── */}
      {(profile.points > 0 || playoff.length > 0) && (
        <div className="mb-8">
          <h2 className="text-xl font-black text-white mb-4 flex items-center gap-2">
            <BarChart2 className="w-5 h-5 text-cyan-400" /> Stats
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Card className="p-4 text-center">
              <p className="text-3xl font-black text-orange-400">{profile.points}</p>
              <p className="text-xs text-slate-500 font-bold uppercase mt-1">Total Points</p>
            </Card>
            {scoredDenom > 0 && (
              <Card className="p-4 text-center">
                <p className="text-3xl font-black text-green-400">
                  {Math.round((playoff.filter(p => p.is_correct === 1).length / scoredDenom) * 100)}%
                </p>
                <p className="text-xs text-slate-500 font-bold uppercase mt-1">Accuracy</p>
                <p className="text-[9px] text-slate-600 mt-0.5">{scoredDenom} scored</p>
              </Card>
            )}
            {scoredDenom > 0 && (
              <Card className="p-4 text-center">
                <p className="text-3xl font-black text-blue-400">
                  {playoff.filter(p => p.is_correct === 1).length}/{scoredDenom}
                </p>
                <p className="text-xs text-slate-500 font-bold uppercase mt-1">Correct Picks</p>
              </Card>
            )}
            {(() => {
              const best = [...playoff, ...playin].filter(p => p.points_earned > 0).sort((a, b) => b.points_earned - a.points_earned)[0];
              return best ? (
                <Card className="p-4 text-center border-yellow-500/30 bg-yellow-500/5">
                  <p className="text-3xl font-black text-yellow-400">+{best.points_earned}</p>
                  <p className="text-xs text-yellow-500/80 font-bold uppercase mt-1">Best Pick</p>
                  <p className="text-[10px] text-slate-400 mt-0.5">
                    {best.predicted_winner?.abbreviation}
                    {best.round ? ` · ${best.round.replace('Conference ', 'Conf ')}` : ' · Play-In'}
                  </p>
                </Card>
              ) : null;
            })()}
          </div>

          {/* Risk profile row */}
          {playoff.length > 0 && (
            <div className="mt-3 grid grid-cols-2 md:grid-cols-3 gap-3">
              {underdogPct != null && (
                <Card className={`p-3 flex items-center gap-3 ${underdogPct >= 15 ? 'border-amber-500/20 bg-amber-500/5' : ''}`}>
                  <span className="text-2xl shrink-0">{underdogPct >= 40 ? '🔥' : underdogPct >= 15 ? '⚡' : '🛡️'}</span>
                  <div>
                    <p className={`text-lg font-black ${underdogPct >= 15 ? 'text-amber-400' : 'text-slate-300'}`}>{underdogPct}%</p>
                    <p className="text-[10px] text-slate-500 font-bold">Underdog Picks</p>
                  </div>
                </Card>
              )}
              {boldWins.length > 0 && (
                <Card className="p-3 flex items-center gap-3 border-amber-500/20 bg-amber-500/5">
                  <span className="text-2xl shrink-0">💎</span>
                  <div>
                    <p className="text-lg font-black text-amber-400">{boldWins.length}</p>
                    <p className="text-[10px] text-slate-500 font-bold">Bold Wins</p>
                  </div>
                </Card>
              )}
              {riskProfile && (
                <Card className={`p-3 flex items-center gap-3 border col-span-2 md:col-span-1 ${riskProfile.cls}`}>
                  <div>
                    <p className="text-sm font-black text-white">{riskProfile.label}</p>
                    <p className="text-[10px] text-slate-400 mt-0.5">{riskProfile.desc}</p>
                  </div>
                </Card>
              )}
            </div>
          )}

          {(futures?.points_earned > 0 || pointsFromPicks > 0) && (
            <div className="mt-3 grid grid-cols-2 gap-3">
              <Card className="p-3 flex items-center gap-3">
                <Trophy className="w-5 h-5 text-orange-400 shrink-0" />
                <div>
                  <p className="text-sm font-black text-white">{pointsFromPicks}</p>
                  <p className="text-[10px] text-slate-500 font-bold">Pick Points</p>
                </div>
              </Card>
              {futures?.points_earned > 0 && (
                <Card className="p-3 flex items-center gap-3">
                  <Star className="w-5 h-5 text-yellow-400 shrink-0" />
                  <div>
                    <p className="text-sm font-black text-white">{futures.points_earned}</p>
                    <p className="text-[10px] text-slate-500 font-bold">Futures Points</p>
                  </div>
                </Card>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Futures Picks ── */}
      {futures ? (
        <div className="mb-8">
          <h2 className="text-xl font-black text-white mb-4 flex items-center gap-2">
            <Star className="w-5 h-5 text-yellow-400" />
            Futures Picks
            {futures.points_earned > 0 && (
              <span className="ml-auto px-3 py-1 rounded-full bg-green-500/20 border border-green-500/30 text-green-400 text-sm font-black">
                +{futures.points_earned} pts
              </span>
            )}
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Card className="p-4 space-y-3">
              <p className="text-[10px] font-black text-slate-500 uppercase tracking-wider">Champions</p>
              <FuturesPick label="NBA Champion"     color="text-yellow-400" team={futures.champion_team}   isCorrect={futures.is_correct_champion} />
              <FuturesPick label="Western Champion" color="text-red-400"    team={futures.west_champ_team} isCorrect={futures.is_correct_west} />
              <FuturesPick label="Eastern Champion" color="text-blue-400"   team={futures.east_champ_team} isCorrect={futures.is_correct_east} />
            </Card>
            <Card className="p-4 space-y-3">
              <p className="text-[10px] font-black text-slate-500 uppercase tracking-wider">MVPs</p>
              <FuturesPick label="Finals MVP"       color="text-yellow-400" mvp={futures.finals_mvp} />
              <FuturesPick label="West Finals MVP"  color="text-red-400"    mvp={futures.west_finals_mvp} />
              <FuturesPick label="East Finals MVP"  color="text-blue-400"   mvp={futures.east_finals_mvp} />
            </Card>
          </div>
        </div>
      ) : hasHiddenFutures && (
        <div className="mb-8">
          <h2 className="text-xl font-black text-white mb-4 flex items-center gap-2">
            <Star className="w-5 h-5 text-yellow-400" />
            Futures Picks
          </h2>
          <Card className="p-6 flex items-center gap-3 text-slate-500">
            <Lock className="w-5 h-5 shrink-0" />
            <span className="text-sm">Hidden until this user locks their futures picks.</span>
          </Card>
        </div>
      )}

      {/* ── Play-In Predictions ── */}
      {playin.length > 0 && (
        <div className="mb-8">
          <h2 className="text-xl font-black text-white mb-4 flex items-center gap-2">
            <Trophy className="w-5 h-5 text-purple-400" />
            Play-In Predictions
            {playin.filter(p => p.is_correct === 1).length > 0 && (
              <span className="ml-auto px-3 py-1 rounded-full bg-green-500/20 border border-green-500/30 text-green-400 text-sm font-black">
                {playin.filter(p => p.is_correct === 1).length}/{playin.length} correct
              </span>
            )}
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {playin.map(pred => <PlayinPredCard key={pred.id} pred={pred} />)}
          </div>
        </div>
      )}

      {/* ── Playoff Predictions ── */}
      {playoff.length > 0 && (
        <div className="mb-8">
          <h2 className="text-xl font-black text-white mb-4 flex items-center gap-2">
            <Trophy className="w-5 h-5 text-orange-400" />
            Playoff Predictions
            {correctCount > 0 && (
              <span className="ml-auto px-3 py-1 rounded-full bg-green-500/20 border border-green-500/30 text-green-400 text-sm font-black">
                {playoff.filter(p => p.is_correct === 1).length}/{scoredDenom} correct
              </span>
            )}
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {playoff.map(pred => <PlayoffPredCard key={pred.id} pred={pred} />)}
          </div>
        </div>
      )}

      {/* ── Playoff Leaders Picks ── */}
      {leaders ? (
        <div className="mb-8">
          <h2 className="text-xl font-black text-white mb-4 flex items-center gap-2">
            <BarChart2 className="w-5 h-5 text-cyan-400" />
            Playoff Leaders Picks
            {leaders.points_earned > 0 && (
              <span className="ml-auto px-3 py-1 rounded-full bg-green-500/20 border border-green-500/30 text-green-400 text-sm font-black">
                +{leaders.points_earned} pts
              </span>
            )}
          </h2>
          <Card className="p-4">
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              {[
                { key: 'top_scorer',   label: 'Top Scorer (PPG)',   correct: leaders.is_correct_scorer },
                { key: 'top_assists',  label: 'Top Assists (APG)',  correct: leaders.is_correct_assists },
                { key: 'top_rebounds', label: 'Top Rebounds (RPG)', correct: leaders.is_correct_rebounds },
                { key: 'top_threes',   label: 'Top 3-Pointers',     correct: leaders.is_correct_threes },
                { key: 'top_steals',   label: 'Top Steals (SPG)',   correct: leaders.is_correct_steals },
                { key: 'top_blocks',   label: 'Top Blocks (BPG)',   correct: leaders.is_correct_blocks },
              ].map(({ key, label, correct }) => {
                const val = leaders[key];
                const border = correct === 1 ? 'border-green-500/40 bg-green-500/5'
                             : correct === 0 ? 'border-red-500/40 bg-red-500/5'
                             : 'border-slate-700/60';
                return (
                  <div key={key} className={`rounded-xl border p-3 ${border}`}>
                    <p className="text-[10px] font-black uppercase tracking-wider text-slate-500 mb-1">{label}</p>
                    <div className="flex items-center justify-between">
                      <span className="text-lg font-black text-white">
                        {val != null ? val : <span className="text-slate-600 text-sm italic">—</span>}
                      </span>
                      {correct === 1 && <CheckCircle className="w-4 h-4 text-green-400" />}
                      {correct === 0 && <XCircle    className="w-4 h-4 text-red-400" />}
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>
        </div>
      ) : hasHiddenLeaders && (
        <div className="mb-8">
          <h2 className="text-xl font-black text-white mb-4 flex items-center gap-2">
            <BarChart2 className="w-5 h-5 text-cyan-400" />
            Playoff Leaders Picks
          </h2>
          <Card className="p-6 flex items-center gap-3 text-slate-500">
            <Lock className="w-5 h-5 shrink-0" />
            <span className="text-sm">Hidden until this user locks their futures picks.</span>
          </Card>
        </div>
      )}

      {predsLoading && (
        <div className="space-y-3 mb-8">
          {[1, 2, 3, 4].map(i => (
            <div key={i} className="bg-slate-900/50 border border-slate-800 rounded-lg p-4 animate-pulse flex gap-4">
              <div className="w-8 h-8 rounded-full bg-slate-800 shrink-0" />
              <div className="flex-1 space-y-2">
                <div className="h-3 w-28 bg-slate-800 rounded" />
                <div className="h-3 w-40 bg-slate-800 rounded" />
              </div>
            </div>
          ))}
        </div>
      )}

      {!predsLoading && !futures && !leaders && !hasHiddenFutures && !hasHiddenLeaders && playoff.length === 0 && playin.length === 0 && predictions !== null && (
        <Card className="p-12 text-center">
          <Trophy className="w-14 h-14 text-slate-700 mx-auto mb-4" />
          <p className="text-slate-400 font-bold">
            {canSeeAll ? 'No predictions yet' : 'No predictions visible yet — check back after games tip off'}
          </p>
        </Card>
      )}
    </div>
  );
};

export default UserProfilePage;
