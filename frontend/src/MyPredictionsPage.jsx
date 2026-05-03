import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Trophy, CheckCircle, XCircle, Clock, Star, Users, BarChart2,
  ChevronDown, ChevronUp, RefreshCw, BarChart3, Minus,
} from 'lucide-react';
import * as api from './services/api';

// ── Helpers ────────────────────────────────────────────────────────────────────
const normName = (s) => s ? s.normalize('NFD').replace(/[̀-ͯ]/g, '').trim().toLowerCase() : '';
const namesMatch = (a, b) => {
  if (!a || !b) return false;
  const na = normName(a), nb = normName(b);
  if (na === nb) return true;
  const aL = na.split(/\s+/).pop() || '', bL = nb.split(/\s+/).pop() || '';
  return !!(aL && bL && aL === bL);
};
const lastName = (name) => {
  if (!name) return '';
  return name.trim().split(' ').pop();
};

const Card = ({ children, className = '' }) => (
  <div className={`bg-slate-900/50 border border-slate-800 rounded-xl ${className}`}>{children}</div>
);

// ── Round config ───────────────────────────────────────────────────────────────
const ROUNDS = [
  { key: 'playin',                  label: 'Play-In Tournament',      color: 'text-purple-400', accent: 'purple', dot: '⬡' },
  { key: 'First Round',             label: 'First Round',             color: 'text-orange-400', accent: 'orange', dot: '①' },
  { key: 'Conference Semifinals',   label: 'Conference Semifinals',   color: 'text-amber-400',  accent: 'amber',  dot: '②' },
  { key: 'Conference Finals',       label: 'Conference Finals',       color: 'text-red-400',    accent: 'red',    dot: '③' },
  { key: 'NBA Finals',              label: 'NBA Finals',              color: 'text-yellow-400', accent: 'yellow', dot: '🏆' },
];

const ACCENT_CLASSES = {
  purple: { border: 'border-purple-500/25', bg: 'bg-purple-500/8',  badge: 'bg-purple-500/20 text-purple-300 border-purple-500/30' },
  orange: { border: 'border-orange-500/25', bg: 'bg-orange-500/8',  badge: 'bg-orange-500/20 text-orange-300 border-orange-500/30' },
  amber:  { border: 'border-amber-500/25',  bg: 'bg-amber-500/8',   badge: 'bg-amber-500/20  text-amber-300  border-amber-500/30'  },
  red:    { border: 'border-red-500/25',     bg: 'bg-red-500/8',     badge: 'bg-red-500/20    text-red-300    border-red-500/30'    },
  yellow: { border: 'border-yellow-500/25', bg: 'bg-yellow-500/8',  badge: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30' },
};

// ── Play-In series card (compact) ──────────────────────────────────────────────
const PlayInCard = ({ pred }) => {
  const isCorrect = pred.is_correct;
  const borderCls = isCorrect === 1 ? 'border-green-500/30 bg-green-500/5'
                  : isCorrect === 0 ? 'border-red-500/30 bg-red-500/5'
                  : 'border-slate-800';
  return (
    <div className={`rounded-xl border p-3 flex items-center gap-3 ${borderCls}`}>
      <div className="flex-1 min-w-0">
        <p className="text-[10px] text-slate-500 font-bold uppercase mb-1.5">
          {pred.conference} · {pred.game_type?.replace(/_/g, ' ')}
        </p>
        <div className="flex items-center gap-2 mb-2">
          <img src={pred.team1?.logo_url} alt="" className="w-6 h-6 shrink-0" onError={e => e.target.style.display = 'none'} />
          <span className="text-xs font-black text-slate-300">{pred.team1?.abbreviation}</span>
          <span className="text-slate-600 text-xs">vs</span>
          <img src={pred.team2?.logo_url} alt="" className="w-6 h-6 shrink-0" onError={e => e.target.style.display = 'none'} />
          <span className="text-xs font-black text-slate-300">{pred.team2?.abbreviation}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-slate-500">My pick:</span>
          <img src={pred.predicted_winner?.logo_url} alt="" className="w-5 h-5 shrink-0" onError={e => e.target.style.display = 'none'} />
          <span className="text-xs font-black text-orange-400">{pred.predicted_winner?.abbreviation}</span>
        </div>
      </div>
      <div className="flex flex-col items-end gap-1.5 shrink-0">
        {isCorrect === 1 && <CheckCircle className="w-5 h-5 text-green-400" />}
        {isCorrect === 0 && <XCircle    className="w-5 h-5 text-red-400"   />}
        {isCorrect === null && <Minus   className="w-4 h-4 text-slate-600" />}
        {pred.points_earned > 0 && (
          <span className="text-[10px] font-black text-green-400 bg-green-500/10 border border-green-500/20 px-1.5 py-0.5 rounded">
            +{pred.points_earned}
          </span>
        )}
      </div>
    </div>
  );
};

// ── Playoff series card (compact) ──────────────────────────────────────────────
const SeriesCard = ({ pred }) => {
  const isCorrect = pred.is_correct;
  const borderCls = isCorrect === 1 ? 'border-green-500/30 bg-green-500/5'
                  : isCorrect === 0 ? 'border-red-500/30 bg-red-500/5'
                  : 'border-slate-800';
  return (
    <div className={`rounded-xl border p-3 ${borderCls}`}>
      {/* Matchup row */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <img src={pred.home_team?.logo_url} alt="" className="w-6 h-6 shrink-0" onError={e => e.target.style.display = 'none'} />
          <span className="text-xs font-black text-slate-300">{pred.home_team?.abbreviation}</span>
          <span className="text-slate-600 text-xs">vs</span>
          <img src={pred.away_team?.logo_url} alt="" className="w-6 h-6 shrink-0" onError={e => e.target.style.display = 'none'} />
          <span className="text-xs font-black text-slate-300">{pred.away_team?.abbreviation}</span>
          <span className="text-[10px] text-slate-600 ml-1">{pred.conference}</span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {isCorrect === 1 && <CheckCircle className="w-4 h-4 text-green-400" />}
          {isCorrect === 0 && <XCircle    className="w-4 h-4 text-red-400"   />}
          {pred.points_earned > 0 && (
            <span className="text-[10px] font-black text-green-400 bg-green-500/10 border border-green-500/20 px-1.5 py-0.5 rounded">
              +{pred.points_earned}
            </span>
          )}
        </div>
      </div>

      {/* My pick row */}
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] text-slate-500">My pick:</span>
        <img src={pred.predicted_winner?.logo_url} alt="" className="w-5 h-5 shrink-0" onError={e => e.target.style.display = 'none'} />
        <span className="text-xs font-black text-orange-400">{pred.predicted_winner?.name}</span>
        {pred.predicted_games && (
          <span className="text-[10px] text-slate-500">· in {pred.predicted_games}g</span>
        )}
      </div>

      {/* Leader picks — only if series finished */}
      {pred.series_finished && (pred.leading_scorer || pred.leading_rebounder || pred.leading_assister) && (
        <div className="flex flex-wrap gap-1 mt-2 pt-2 border-t border-slate-800/60">
          {[
            ['🏀', pred.leading_scorer,    pred.actual_leading_scorer,    'PTS'],
            ['💪', pred.leading_rebounder, pred.actual_leading_rebounder, 'REB'],
            ['🎯', pred.leading_assister,  pred.actual_leading_assister,  'AST'],
          ].map(([icon, picked, actual, cat]) => {
            if (!picked) return null;
            const ok = actual != null ? namesMatch(picked, actual) : null;
            return (
              <span key={cat} className={`inline-flex items-center gap-0.5 text-[10px] font-bold px-1.5 py-0.5 rounded ${
                ok === true  ? 'text-green-400 bg-green-500/10 border border-green-500/20' :
                ok === false ? 'text-red-400 bg-red-500/10 border border-red-500/20' :
                'text-slate-500 bg-slate-800/50 border border-slate-700/30'
              }`}>
                {icon} {lastName(picked)}{ok === true ? ' ✓' : ok === false ? ' ✗' : ''}
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
};

// ── Round section (collapsible) ────────────────────────────────────────────────
const RoundSection = ({ roundCfg, preds, defaultOpen = true }) => {
  const [open, setOpen] = useState(defaultOpen);
  const ac = ACCENT_CLASSES[roundCfg.accent];

  const correct = preds.filter(p => p.is_correct === 1).length;
  const total   = preds.length;
  const pts     = preds.reduce((s, p) => s + (p.points_earned || 0), 0);
  const allDone = preds.every(p => p.is_correct !== null);

  return (
    <div className={`rounded-2xl border ${ac.border} overflow-hidden`}>
      {/* Header */}
      <button
        onClick={() => setOpen(v => !v)}
        className={`w-full flex items-center justify-between px-4 py-3 ${ac.bg} hover:opacity-90 transition-opacity`}
      >
        <div className="flex items-center gap-2.5">
          <span className="text-base">{roundCfg.dot}</span>
          <span className={`text-sm font-black ${roundCfg.color}`}>{roundCfg.label}</span>
          <span className={`text-[10px] font-black px-2 py-0.5 rounded-full border ${ac.badge}`}>
            {total} pick{total !== 1 ? 's' : ''}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {/* Correct badge */}
          {allDone && total > 0 && (
            <span className={`text-[10px] font-black px-2 py-0.5 rounded-full border ${
              correct === total ? 'text-green-300 bg-green-500/20 border-green-500/30' :
              correct > 0      ? 'text-amber-300 bg-amber-500/20 border-amber-500/30' :
              'text-red-300 bg-red-500/20 border-red-500/30'
            }`}>
              {correct}/{total} ✓
            </span>
          )}
          {pts > 0 && (
            <span className="text-[10px] font-black text-green-400 bg-green-500/15 border border-green-500/25 px-2 py-0.5 rounded-full">
              +{pts} pts
            </span>
          )}
          {open ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
        </div>
      </button>

      {/* Cards grid */}
      {open && (
        <div className="p-3 grid grid-cols-1 md:grid-cols-2 gap-2.5 bg-slate-950/30">
          {preds.map(p => (
            roundCfg.key === 'playin'
              ? <PlayInCard key={p.id} pred={p} />
              : <SeriesCard key={p.id} pred={p} />
          ))}
        </div>
      )}
    </div>
  );
};

// ── Futures section ────────────────────────────────────────────────────────────
const FuturesPick = ({ label, color, team, mvp, isCorrect }) => {
  const borderCls =
    isCorrect === 1 ? 'border-green-500/40 bg-green-500/5' :
    isCorrect === 0 ? 'border-red-500/40 bg-red-500/5'   :
    'border-slate-700/60';
  return (
    <div className={`rounded-xl border p-3 flex items-center gap-3 ${borderCls}`}>
      <div className="flex-1 min-w-0">
        <p className={`text-[10px] font-black uppercase tracking-wider mb-1 ${color}`}>{label}</p>
        {team ? (
          <div className="flex items-center gap-2">
            <img src={team.logo_url} alt="" className="w-7 h-7 shrink-0" onError={e => e.target.style.display = 'none'} />
            <span className="text-sm font-black text-white truncate">{team.name}</span>
          </div>
        ) : mvp ? (
          <p className="text-sm font-bold text-white truncate">{mvp}</p>
        ) : (
          <p className="text-xs text-slate-600 italic">Not picked</p>
        )}
      </div>
      {isCorrect === 1 && <CheckCircle className="w-5 h-5 text-green-400 shrink-0" />}
      {isCorrect === 0 && <XCircle    className="w-5 h-5 text-red-400 shrink-0"   />}
    </div>
  );
};

// ── Community bar chart ────────────────────────────────────────────────────────
const PickBar = ({ label, color, items, icon: Icon }) => {
  const [exp, setExp] = useState(false);
  const shown = exp ? items : items.slice(0, 3);
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5 mb-2">
        {Icon && <Icon className={`w-3 h-3 ${color}`} />}
        <p className={`text-[10px] font-black uppercase tracking-wider ${color}`}>{label}</p>
      </div>
      {shown.map((item, i) => (
        <div key={i} className="flex items-center gap-2">
          {item.team ? (
            <>
              <img src={item.team.logo_url} alt="" className="w-5 h-5 shrink-0" onError={e => e.target.style.display = 'none'} />
              <span className="text-xs text-slate-300 font-bold w-8">{item.team.abbreviation}</span>
            </>
          ) : (
            <span className="text-xs text-slate-300 font-bold flex-shrink-0 max-w-[80px] truncate">{item.name}</span>
          )}
          <div className="flex-1 h-2 bg-slate-800 rounded-full overflow-hidden">
            <div className="h-full bg-orange-500/70 rounded-full" style={{ width: `${item.pct}%` }} />
          </div>
          <span className="text-[10px] text-slate-500 font-bold w-10 text-right">{item.pct}%</span>
          <span className="text-[10px] text-slate-600 w-6 text-right">{item.count}</span>
        </div>
      ))}
      {items.length > 3 && (
        <button onClick={() => setExp(v => !v)} className="text-[10px] text-slate-500 hover:text-slate-300 flex items-center gap-1 mt-1">
          {exp ? <><ChevronUp className="w-3 h-3" />Show less</> : <><ChevronDown className="w-3 h-3" />+{items.length - 3} more</>}
        </button>
      )}
    </div>
  );
};

// ── Collapsible wrapper ────────────────────────────────────────────────────────
const CollapsibleSection = ({ icon: Icon, iconColor, title, badge, rightBadge, defaultOpen = false, children }) => {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-2xl border border-slate-800 overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-4 py-3 bg-slate-900/60 hover:bg-slate-800/40 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Icon className={`w-4 h-4 ${iconColor}`} />
          <span className="text-sm font-black text-white">{title}</span>
          {badge && <span className="text-[10px] font-black px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700">{badge}</span>}
        </div>
        <div className="flex items-center gap-2">
          {rightBadge}
          {open ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
        </div>
      </button>
      {open && <div className="p-4 border-t border-slate-800">{children}</div>}
    </div>
  );
};

// ── Empty state ────────────────────────────────────────────────────────────────
const _EMPTY_PREDS = { playoff_predictions: [], playin_predictions: [], futures_prediction: null, leaders_prediction: null, total_predictions: 0 };

// ── Main page ──────────────────────────────────────────────────────────────────
const MyPredictionsPage = ({ currentUser }) => {
  const qc = useQueryClient();

  const { data: predictions = _EMPTY_PREDS, isLoading: loading, isFetching, refetch } = useQuery({
    queryKey: ['myPredictions', currentUser?.user_id],
    queryFn:  () => api.getMyPredictions(currentUser.user_id, '2026'),
    enabled:  !!currentUser?.user_id,
    staleTime: 3 * 60 * 1000,
    gcTime:   20 * 60 * 1000,
    retry: 1,
  });

  const { data: community } = useQuery({
    queryKey: ['futuresAll', '2026'],
    queryFn:  () => api.getFuturesAll('2026'),
    staleTime: 10 * 60 * 1000,
    gcTime:   30 * 60 * 1000,
    retry: 1,
  });

  if (!currentUser) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-12 text-center">
        <h2 className="text-3xl font-bold text-white mb-4">Please Login</h2>
        <p className="text-slate-400">You need to be logged in to view your predictions</p>
      </div>
    );
  }

  // Group by round
  const byRound = {};
  (predictions.playoff_predictions || []).forEach(p => {
    const r = p.round || 'Unknown';
    if (!byRound[r]) byRound[r] = [];
    byRound[r].push(p);
  });

  const totalPts    = (predictions.playoff_predictions || []).reduce((s, p) => s + (p.points_earned || 0), 0)
                    + (predictions.futures_prediction?.points_earned || 0)
                    + (predictions.leaders_prediction?.points_earned || 0);
  const totalPts_pi = (predictions.playin_predictions || []).reduce((s, p) => s + (p.points_earned || 0), 0);
  const grandTotal  = totalPts + totalPts_pi;

  const correctCount  = (predictions.playoff_predictions || []).filter(p => p.is_correct === 1).length;
  const totalSeriesDone = (predictions.playoff_predictions || []).filter(p => p.is_correct !== null).length;

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-black text-white mb-1">My Predictions</h1>
          <p className="text-slate-500 text-sm">All your 2026 playoff picks in one place</p>
        </div>
        <button onClick={() => refetch()} disabled={isFetching}
          className="flex items-center gap-2 px-3 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 text-xs font-bold rounded-xl transition-colors disabled:opacity-50 shrink-0">
          <RefreshCw className={`w-3.5 h-3.5 ${isFetching ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      {loading ? (
        <div className="space-y-3">
          {[1,2,3,4].map(i => <div key={i} className="h-14 bg-slate-900/50 border border-slate-800 rounded-2xl animate-pulse" />)}
        </div>
      ) : (
        <>
          {/* ── Stats row ── */}
          <div className="grid grid-cols-3 gap-3">
            <Card className="p-3 text-center">
              <div className="text-2xl md:text-3xl font-black text-orange-400">{predictions.total_predictions}</div>
              <div className="text-slate-500 text-[10px] md:text-xs mt-0.5">Picks Made</div>
            </Card>
            <Card className="p-3 text-center">
              <div className="text-2xl md:text-3xl font-black text-green-400">
                {totalSeriesDone > 0 ? `${correctCount}/${totalSeriesDone}` : '—'}
              </div>
              <div className="text-slate-500 text-[10px] md:text-xs mt-0.5">Correct</div>
            </Card>
            <Card className="p-3 text-center">
              <div className="text-2xl md:text-3xl font-black text-blue-400">{grandTotal}</div>
              <div className="text-slate-500 text-[10px] md:text-xs mt-0.5">Points</div>
            </Card>
          </div>

          {/* ── Round sections ── */}
          {ROUNDS.map(roundCfg => {
            const preds = roundCfg.key === 'playin'
              ? (predictions.playin_predictions || [])
              : (byRound[roundCfg.key] || []);
            if (preds.length === 0) return null;
            return (
              <RoundSection
                key={roundCfg.key}
                roundCfg={roundCfg}
                preds={preds}
                defaultOpen={true}
              />
            );
          })}

          {/* ── Futures Picks ── */}
          <CollapsibleSection
            icon={Star}
            iconColor="text-yellow-400"
            title="Futures Picks"
            defaultOpen={!!predictions.futures_prediction}
            rightBadge={
              predictions.futures_prediction?.points_earned > 0
                ? <span className="text-[10px] font-black text-green-400 bg-green-500/15 border border-green-500/25 px-2 py-0.5 rounded-full">+{predictions.futures_prediction.points_earned} pts</span>
                : null
            }
          >
            {predictions.futures_prediction ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2.5">
                  <p className="text-[10px] font-black text-slate-500 uppercase tracking-wider mb-2">Champions</p>
                  <FuturesPick label="NBA Champion"      color="text-yellow-400" team={predictions.futures_prediction.champion_team}   isCorrect={predictions.futures_prediction.is_correct_champion} />
                  <FuturesPick label="Western Champion"  color="text-red-400"    team={predictions.futures_prediction.west_champ_team}  isCorrect={predictions.futures_prediction.is_correct_west} />
                  <FuturesPick label="Eastern Champion"  color="text-blue-400"   team={predictions.futures_prediction.east_champ_team}  isCorrect={predictions.futures_prediction.is_correct_east} />
                </div>
                <div className="space-y-2.5">
                  <p className="text-[10px] font-black text-slate-500 uppercase tracking-wider mb-2">MVPs</p>
                  <FuturesPick label="Finals MVP"       color="text-yellow-400" mvp={predictions.futures_prediction.finals_mvp}       />
                  <FuturesPick label="West Finals MVP"  color="text-red-400"    mvp={predictions.futures_prediction.west_finals_mvp}  />
                  <FuturesPick label="East Finals MVP"  color="text-blue-400"   mvp={predictions.futures_prediction.east_finals_mvp}  />
                </div>
              </div>
            ) : (
              <div className="text-center py-6 text-slate-500 text-sm">
                <Star className="w-8 h-8 text-slate-700 mx-auto mb-2" />
                <p className="font-bold">No futures picks yet</p>
                <p className="text-xs text-slate-600 mt-1">Go to the Home page to predict the NBA Champion, Conference Winners and Finals MVPs.</p>
              </div>
            )}
          </CollapsibleSection>

          {/* ── Playoff Leaders Picks ── */}
          <CollapsibleSection
            icon={BarChart3}
            iconColor="text-cyan-400"
            title="Playoff Leaders Picks"
            defaultOpen={!!predictions.leaders_prediction}
            rightBadge={
              predictions.leaders_prediction?.points_earned > 0
                ? <span className="text-[10px] font-black text-green-400 bg-green-500/15 border border-green-500/25 px-2 py-0.5 rounded-full">+{predictions.leaders_prediction.points_earned} pts</span>
                : null
            }
          >
            {predictions.leaders_prediction ? (
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2.5">
                {[
                  { key: 'top_scorer',   label: 'Top Scorer (PPG)',   correct: predictions.leaders_prediction.is_correct_scorer   },
                  { key: 'top_assists',  label: 'Top Assists (APG)',  correct: predictions.leaders_prediction.is_correct_assists  },
                  { key: 'top_rebounds', label: 'Top Rebounds (RPG)', correct: predictions.leaders_prediction.is_correct_rebounds },
                  { key: 'top_threes',   label: 'Top 3-Pointers',     correct: predictions.leaders_prediction.is_correct_threes   },
                  { key: 'top_steals',   label: 'Top Steals (SPG)',   correct: predictions.leaders_prediction.is_correct_steals   },
                  { key: 'top_blocks',   label: 'Top Blocks (BPG)',   correct: predictions.leaders_prediction.is_correct_blocks   },
                ].map(({ key, label, correct }) => {
                  const val = predictions.leaders_prediction[key];
                  const cls = correct === 1 ? 'border-green-500/40 bg-green-500/5'
                            : correct === 0 ? 'border-red-500/40 bg-red-500/5'
                            : 'border-slate-700/60';
                  return (
                    <div key={key} className={`rounded-xl border p-3 ${cls}`}>
                      <p className="text-[10px] font-black uppercase tracking-wider text-slate-500 mb-1">{label}</p>
                      <div className="flex items-center justify-between">
                        <span className="text-base font-black text-white">
                          {val != null ? val : <span className="text-slate-600 text-xs italic">—</span>}
                        </span>
                        {correct === 1 && <CheckCircle className="w-4 h-4 text-green-400" />}
                        {correct === 0 && <XCircle    className="w-4 h-4 text-red-400"   />}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="text-center py-6 text-slate-500 text-sm">
                <BarChart3 className="w-8 h-8 text-slate-700 mx-auto mb-2" />
                <p className="font-bold">No leaders picks yet</p>
                <p className="text-xs text-slate-600 mt-1">Go to the Playoff page → Playoff Leaders section to enter your stat predictions.</p>
              </div>
            )}
          </CollapsibleSection>

          {/* ── Community Futures Picks ── */}
          {community && community.total_entries > 0 && (
            <CollapsibleSection
              icon={Users}
              iconColor="text-purple-400"
              title="Community Futures Picks"
              badge={`${community.total_entries} users`}
              defaultOpen={false}
            >
              <div className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <Card className="p-3"><PickBar label="NBA Champion"    color="text-yellow-400" icon={Trophy} items={community.champion}  /></Card>
                  <Card className="p-3"><PickBar label="West Champion"   color="text-red-400"    icon={Trophy} items={community.west_champ} /></Card>
                  <Card className="p-3"><PickBar label="East Champion"   color="text-blue-400"   icon={Trophy} items={community.east_champ} /></Card>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <Card className="p-3"><PickBar label="Finals MVP"      color="text-yellow-400" icon={Star}   items={community.finals_mvp}      /></Card>
                  <Card className="p-3"><PickBar label="West Finals MVP" color="text-red-400"    icon={Star}   items={community.west_finals_mvp}  /></Card>
                  <Card className="p-3"><PickBar label="East Finals MVP" color="text-blue-400"   icon={Star}   items={community.east_finals_mvp}  /></Card>
                </div>
                {/* All picks table */}
                <Card className="overflow-hidden">
                  <div className="px-4 py-3 border-b border-slate-800 flex items-center gap-2">
                    <BarChart2 className="w-4 h-4 text-slate-400" />
                    <p className="text-sm font-black text-white">All Picks</p>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead className="bg-slate-800/50">
                        <tr>
                          <th className="px-4 py-2 text-left text-[10px] font-bold text-slate-400 uppercase">User</th>
                          <th className="px-3 py-2 text-center text-[10px] font-bold text-slate-400 uppercase">Champion</th>
                          <th className="px-3 py-2 text-center text-[10px] font-bold text-slate-400 uppercase">West</th>
                          <th className="px-3 py-2 text-center text-[10px] font-bold text-slate-400 uppercase">East</th>
                          <th className="px-3 py-2 text-center text-[10px] font-bold text-slate-400 uppercase">Finals MVP</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/60">
                        {community.entries.map((entry, i) => (
                          <tr key={i} className={`hover:bg-slate-800/30 transition-colors ${entry.username === currentUser.username ? 'bg-orange-500/5' : ''}`}>
                            <td className="px-4 py-2.5 font-bold">
                              <span className={entry.username === currentUser.username ? 'text-orange-400' : 'text-white'}>
                                {entry.username === currentUser.username ? 'You' : entry.username}
                              </span>
                            </td>
                            <td className="px-3 py-2.5 text-center">
                              {entry.champion_team ? (
                                <div className="flex items-center justify-center gap-1">
                                  <img src={entry.champion_team.logo_url} alt="" className="w-5 h-5" onError={e => e.target.style.display = 'none'} />
                                  <span className="text-slate-300 font-bold">{entry.champion_team.abbreviation}</span>
                                </div>
                              ) : <span className="text-slate-600">—</span>}
                            </td>
                            <td className="px-3 py-2.5 text-center">
                              {entry.west_champ_team ? (
                                <div className="flex items-center justify-center gap-1">
                                  <img src={entry.west_champ_team.logo_url} alt="" className="w-5 h-5" onError={e => e.target.style.display = 'none'} />
                                  <span className="text-slate-300 font-bold">{entry.west_champ_team.abbreviation}</span>
                                </div>
                              ) : <span className="text-slate-600">—</span>}
                            </td>
                            <td className="px-3 py-2.5 text-center">
                              {entry.east_champ_team ? (
                                <div className="flex items-center justify-center gap-1">
                                  <img src={entry.east_champ_team.logo_url} alt="" className="w-5 h-5" onError={e => e.target.style.display = 'none'} />
                                  <span className="text-slate-300 font-bold">{entry.east_champ_team.abbreviation}</span>
                                </div>
                              ) : <span className="text-slate-600">—</span>}
                            </td>
                            <td className="px-3 py-2.5 text-center text-slate-400">
                              {entry.finals_mvp || <span className="text-slate-600">—</span>}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
              </div>
            </CollapsibleSection>
          )}

          {/* ── Empty state ── */}
          {predictions.total_predictions === 0 && !predictions.futures_prediction && (
            <Card className="p-12 text-center">
              <Clock className="w-14 h-14 text-slate-700 mx-auto mb-4" />
              <p className="text-lg text-slate-400 font-bold mb-1">No predictions yet</p>
              <p className="text-slate-600 text-sm">Make your first pick on the Playoff or Home page</p>
            </Card>
          )}
        </>
      )}
    </div>
  );
};

export default MyPredictionsPage;
