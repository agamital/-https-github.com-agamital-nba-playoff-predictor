import React, { useState, useEffect } from 'react';
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

const PlayInPage = ({ currentUser }) => {
  const [games, setGames]     = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => { loadGames(); }, []);

  const loadGames = async () => {
    setLoading(true);
    try {
      const data = await api.getPlayInGames('2026');
      setGames(data);
    } catch (err) {
      console.error('Error loading play-in games:', err);
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

  const GameCard = ({ game }) => {
    const meta   = GAME_META[game.game_type] || { label: game.game_type, accent: 'purple', next: '' };
    const accent = ACCENT_CLASSES[meta.accent] || ACCENT_CLASSES.purple;
    const isCompleted = game.status === 'completed';

    return (
      <Card className="p-6">
        {/* Header */}
        <div className="flex justify-between items-center mb-1">
          <span className="text-xs font-bold text-slate-400 uppercase">{game.conference}</span>
          <span className={`text-xs font-bold px-2.5 py-1 rounded-full border ${accent.badge}`}>
            {meta.label}
          </span>
        </div>

        {/* Next-step hint */}
        <p className="text-[10px] text-slate-600 mb-4">{meta.next}</p>

        {/* Teams */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3 flex-1">
            <img src={game.team1.logo_url} alt={game.team1.name} className="w-12 h-12"
              onError={e => e.target.style.display='none'} />
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
            <img src={game.team2.logo_url} alt={game.team2.name} className="w-12 h-12"
              onError={e => e.target.style.display='none'} />
          </div>
        </div>

        {/* Result banner */}
        {isCompleted && game.winner_id && (() => {
          const winner = game.winner_id === game.team1.id ? game.team1 : game.team2;
          return (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-green-500/10 border border-green-500/30 text-green-400 text-sm font-bold mb-4">
              <CheckCircle className="w-4 h-4 shrink-0" />
              {winner.name} advanced
            </div>
          );
        })()}

        {/* Prediction buttons */}
        {!isCompleted && (() => {
          // Higher seed = underdog
          const underdogId = game.team1.seed > game.team2.seed ? game.team1.id : game.team2.id;
          return currentUser ? (
            <div className="grid grid-cols-2 gap-3">
              {[game.team1, game.team2].map(team => {
                const isUnderdog = team.id === underdogId;
                const pts = isUnderdog ? PLAYIN_UNDERDOG_PTS : PLAYIN_PTS;
                return (
                  <button key={team.id}
                    onClick={() => handlePrediction(game.id, team.id)}
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

        <CommunityInsights
          gameId={game.id}
          homeTeam={game.team1}
          awayTeam={game.team2}
          initialStats={null}
        />
      </Card>
    );
  };

  // Per-conference status banner
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
      return null; // Phase 1 in progress — no banner needed
    }

    return (
      <div className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-xs font-bold mb-4 ${cls}`}>
        <Clock className="w-3.5 h-3.5 shrink-0" />
        {text}
      </div>
    );
  };

  // Game 3 pending placeholder card
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
        <Clock className="w-4 h-4" />
        Matchup determined after Games 1 & 2
      </div>
    </Card>
  );

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
                  {ordered.map(game => <GameCard key={game.id} game={game} />)}
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
