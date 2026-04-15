import React, { useState, useEffect, useRef } from 'react';
import { Trophy, Lock, CheckCircle, Clock } from 'lucide-react';
import * as api from './services/api';
import CommunityInsights from './components/CommunityInsights';
import { PLAYIN_PTS, PLAYIN_UNDERDOG_PTS } from './scoringConstants';

const Card = ({ children, className }) => (
  <div className={`bg-slate-900/50 border border-slate-800 rounded-lg backdrop-blur-sm ${className}`}>
    {children}
  </div>
);

// Labels + colours per game type
const GAME_META = {
  '7v8':         { label: 'Game 1 — 7 vs 8',       accent: 'purple', next: 'Winner → #7 Seed · Loser → Game 3' },
  '9v10':        { label: 'Game 2 — 9 vs 10',      accent: 'purple', next: 'Winner → Game 3 · Loser eliminated' },
  'elimination': { label: 'Game 3 — Elimination',   accent: 'rose',   next: 'Winner → #8 Seed · Loser eliminated' },
};
const ACCENT_CLASSES = {
  purple: { badge: 'bg-purple-500/20 text-purple-400 border-purple-500/30', pick: 'bg-purple-500 hover:bg-purple-600' },
  rose:   { badge: 'bg-rose-500/20  text-rose-400  border-rose-500/30',   pick: 'bg-rose-500   hover:bg-rose-600'   },
};

// ── Countdown timer displayed in Asia/Jerusalem timezone ──────────────────────
const JERUSALEM_TZ = 'Asia/Jerusalem';

// Fallback schedule (UTC) in case DB hasn't backfilled start_time yet.
// Key = `${conference}_${game_type}`
const FALLBACK_START_TIMES = {
  'Eastern_7v8':         '2026-04-15T23:30:00Z',
  'Western_7v8':         '2026-04-16T02:00:00Z',
  'Eastern_9v10':        '2026-04-16T23:30:00Z',
  'Western_9v10':        '2026-04-17T02:00:00Z',
  'Eastern_elimination': '2026-04-18T23:30:00Z',
  'Western_elimination': '2026-04-19T02:00:00Z',
};

function resolveStartTime(game) {
  if (game.start_time) {
    // Backend returns naive ISO (no Z) — force UTC
    return game.start_time.endsWith('Z') ? game.start_time : game.start_time + 'Z';
  }
  // Fall back to hardcoded schedule if DB column not set yet
  return FALLBACK_START_TIMES[`${game.conference}_${game.game_type}`] || null;
}

function formatJerusalemTime(isoUtcZ) {
  if (!isoUtcZ) return null;
  return new Date(isoUtcZ).toLocaleString('en-IL', {
    timeZone: JERUSALEM_TZ,
    weekday: 'short',
    month:   'short',
    day:     'numeric',
    hour:    '2-digit',
    minute:  '2-digit',
    hour12:  false,
  });
}

function useCountdown(isoUtcZ) {
  const getSecsLeft = () => {
    if (!isoUtcZ) return null;
    return Math.floor((new Date(isoUtcZ) - Date.now()) / 1000);
  };
  const [secs, setSecs] = useState(getSecsLeft);

  useEffect(() => {
    if (!isoUtcZ) return;
    const id = setInterval(() => setSecs(getSecsLeft()), 1000);
    return () => clearInterval(id);
  }, [isoUtcZ]);

  return secs; // negative means game already started
}

const Countdown = ({ startTime }) => {
  const secs = useCountdown(startTime);
  if (secs === null) return null;

  if (secs <= 0) {
    return (
      <div className="flex items-center gap-1.5 text-rose-400 text-xs font-bold">
        <Lock className="w-3 h-3" /> Bets closed — game started
      </div>
    );
  }

  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  const pad = n => String(n).padStart(2, '0');

  const urgent = secs < 3600; // < 1 hour
  return (
    <div className={`flex items-center gap-1.5 text-xs font-mono font-bold ${urgent ? 'text-amber-400' : 'text-cyan-400'}`}>
      <Clock className="w-3 h-3 shrink-0" />
      <span>Bets close in {h > 0 ? `${h}h ` : ''}{pad(m)}m {pad(s)}s</span>
    </div>
  );
};

// ── Module-level components (must NOT be defined inside PlayInPage) ───────────
// Defining them inside would create a new component type each render,
// which resets hook state (including countdown timers) on every re-render.

const GameCard = ({ game, currentUser, onPrediction }) => {
  const meta        = GAME_META[game.game_type] || { label: game.game_type, accent: 'purple', next: '' };
  const accent      = ACCENT_CLASSES[meta.accent] || ACCENT_CLASSES.purple;
  const isCompleted = game.status === 'completed';

  const startTimeZ = resolveStartTime(game);
  const secsLeft   = useCountdown(startTimeZ);
  const betsClosed = isCompleted || (secsLeft !== null && secsLeft <= 0);
  const startLabel = formatJerusalemTime(startTimeZ);

  return (
    <Card className="p-6">
      <div className="flex justify-between items-center mb-1">
        <span className="text-xs font-bold text-slate-400 uppercase">{game.conference}</span>
        <span className={`text-xs font-bold px-2.5 py-1 rounded-full border ${accent.badge}`}>
          {meta.label}
        </span>
      </div>
      <p className="text-[10px] text-slate-600 mb-2">{meta.next}</p>

      {!betsClosed && startTimeZ && (
        <div className="mb-3 space-y-1">
          {startLabel && <p className="text-[11px] text-slate-500">🕐 {startLabel} (Israel Time)</p>}
          <Countdown startTime={startTimeZ} />
        </div>
      )}

      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3 flex-1">
          <img src={game.team1.logo_url} alt={game.team1.name} className="w-12 h-12" onError={e => e.target.style.display='none'} />
          <div>
            <p className="font-bold text-white">{game.team1.name}</p>
            <p className="text-xs text-slate-400">Seed #{game.team1.seed}</p>
          </div>
        </div>
        <div className="text-slate-600 font-black text-2xl px-4">VS</div>
        <div className="flex items-center gap-3 flex-1 justify-end">
          <div className="text-right">
            <p className="font-bold text-white">{game.team2.name}</p>
            <p className="text-xs text-slate-400">Seed #{game.team2.seed}</p>
          </div>
          <img src={game.team2.logo_url} alt={game.team2.name} className="w-12 h-12" onError={e => e.target.style.display='none'} />
        </div>
      </div>

      {isCompleted && game.winner_id && (() => {
        const winner = game.winner_id === game.team1.id ? game.team1 : game.team2;
        return (
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-green-500/10 border border-green-500/30 text-green-400 text-sm font-bold mb-4">
            <CheckCircle className="w-4 h-4 shrink-0" /> {winner.name} advanced
          </div>
        );
      })()}

      {!isCompleted && (() => {
        if (betsClosed) {
          return (
            <div className="flex items-center justify-center py-3 bg-rose-900/20 border border-rose-500/30 rounded-lg text-rose-400 text-sm gap-2 mb-3">
              <Lock className="w-4 h-4" /> Bets are closed
            </div>
          );
        }
        const underdogId = game.team1.seed > game.team2.seed ? game.team1.id : game.team2.id;
        return currentUser ? (
          <div className="grid grid-cols-2 gap-3">
            {[game.team1, game.team2].map(team => {
              const isUnderdog = team.id === underdogId;
              const pts = isUnderdog ? PLAYIN_UNDERDOG_PTS : PLAYIN_PTS;
              return (
                <button key={team.id} onClick={() => onPrediction(game.id, team.id)}
                  className={`relative py-2.5 rounded-lg font-bold text-sm text-white transition-all ${accent.pick} ${isUnderdog ? 'ring-1 ring-amber-400/50' : ''}`}>
                  Pick {team.abbreviation}
                  <span className={`absolute -top-1.5 -right-1.5 text-[9px] font-black px-1.5 py-0.5 rounded-full ${
                    isUnderdog ? 'bg-amber-500 text-black' : 'bg-slate-700 text-slate-300'
                  }`}>+{pts}</span>
                </button>
              );
            })}
          </div>
        ) : (
          <div className="flex items-center justify-center py-3 bg-slate-800/50 rounded-lg text-slate-400 text-sm gap-2">
            <Lock className="w-4 h-4" /> Login to predict
          </div>
        );
      })()}

      <CommunityInsights gameId={game.id} homeTeam={game.team1} awayTeam={game.team2} initialStats={null} status={game.status} />
    </Card>
  );
};

const ConferenceBanner = ({ confGames }) => {
  const g7    = confGames.find(g => g.game_type === '7v8');
  const g9    = confGames.find(g => g.game_type === '9v10');
  const gelim = confGames.find(g => g.game_type === 'elimination');
  let text, cls;
  if (gelim?.status === 'completed') {
    text = 'All games complete'; cls = 'bg-green-500/10 border-green-500/30 text-green-400';
  } else if (gelim) {
    text = 'Game 3 is live — make your pick!'; cls = 'bg-rose-500/10 border-rose-500/30 text-rose-400';
  } else if (g7?.status === 'completed' && g9?.status === 'completed') {
    text = 'Both games finished — Game 3 matchup coming soon'; cls = 'bg-amber-500/10 border-amber-500/30 text-amber-400';
  } else if (g7?.status === 'completed') {
    text = 'Waiting for Game 2 (9v10) to finish'; cls = 'bg-slate-800 border-slate-700 text-slate-400';
  } else if (g9?.status === 'completed') {
    text = 'Waiting for Game 1 (7v8) to finish'; cls = 'bg-slate-800 border-slate-700 text-slate-400';
  } else {
    return null;
  }
  return (
    <div className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-xs font-bold mb-4 ${cls}`}>
      <Clock className="w-3.5 h-3.5 shrink-0" /> {text}
    </div>
  );
};

const Game3PendingCard = () => (
  <Card className="p-6 border-dashed border-slate-700 opacity-60">
    <div className="flex justify-between items-center mb-1">
      <span className="text-xs font-bold text-slate-500 uppercase">Coming Soon</span>
      <span className="text-xs font-bold px-2.5 py-1 rounded-full border bg-rose-500/10 text-rose-500/60 border-rose-500/20">
        Game 3 — Elimination
      </span>
    </div>
    <p className="text-[10px] text-slate-600 mb-4">Winner → #8 Seed · Loser eliminated</p>
    <div className="flex items-center justify-center py-8 text-slate-600 text-sm gap-2">
      <Clock className="w-4 h-4" /> Matchup determined after Games 1 & 2
    </div>
  </Card>
);

const PlayInPage = ({ currentUser }) => {
  const [games, setGames]     = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    loadGames();
    // Poll every 60 s so Game 3 appears automatically after Games 1 & 2 complete
    const interval = setInterval(loadGames, 60_000);
    return () => clearInterval(interval);
  }, []);

  const loadGames = async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const data = await api.getPlayInGames('2026');
      setGames(data);
    } catch (err) {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  };

  const handlePrediction = async (gameId, teamId) => {
    if (!currentUser) { alert('Please login to make predictions'); return; }
    try {
      await api.makePlayInPrediction(currentUser.user_id, gameId, teamId);
      await loadGames();
    } catch (err) {
      alert('Error: ' + (err.response?.data?.detail || 'Unknown error'));
    }
  };

  const groupedGames = games.reduce((acc, game) => {
    acc[game.conference] = acc[game.conference] || [];
    acc[game.conference].push(game);
    return acc;
  }, {});

  const gameOrder = { '7v8': 0, '9v10': 1, 'elimination': 2 };

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <div className="mb-8">
        <h1 className="text-4xl font-black text-white mb-2">Play-In Tournament</h1>
        <p className="text-slate-400">Seeds 7–10 compete for the final two playoff spots</p>
      </div>

      {loading ? (
        <div className="text-center py-12">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-4 border-orange-500 border-t-transparent" />
        </div>
      ) : loadError ? (
        <div className="flex flex-col items-center py-16 gap-4">
          <p className="text-slate-400">Failed to load play-in games.</p>
          <button onClick={loadGames} className="px-6 py-2.5 bg-orange-500 hover:bg-orange-600 text-white font-bold rounded-xl transition-colors">
            Try Again
          </button>
        </div>
      ) : games.length > 0 ? (
        <div className="space-y-10">
          {Object.entries(groupedGames).map(([conference, confGames]) => {
            const ordered = [...confGames].sort((a, b) => (gameOrder[a.game_type] ?? 9) - (gameOrder[b.game_type] ?? 9));
            const hasElim = confGames.some(g => g.game_type === 'elimination');
            const bothPhase1Done = confGames.find(g => g.game_type === '7v8')?.status === 'completed'
                                && confGames.find(g => g.game_type === '9v10')?.status === 'completed';
            return (
              <div key={conference}>
                <h2 className="text-2xl font-bold text-white mb-3 flex items-center gap-2">
                  <Trophy className="w-6 h-6 text-orange-400" />
                  {conference} Conference
                </h2>
                <ConferenceBanner confGames={confGames} />
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                  {ordered.map(game => <GameCard key={game.id} game={game} currentUser={currentUser} onPrediction={handlePrediction} />)}
                  {/* Placeholder when both phase 1 games done but Game 3 not yet created */}
                  {bothPhase1Done && !hasElim && <Game3PendingCard key="pending" />}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <Card className="p-8 text-center">
          <p className="text-slate-400">No play-in games available yet.</p>
        </Card>
      )}
    </div>
  );
};

export default PlayInPage;
