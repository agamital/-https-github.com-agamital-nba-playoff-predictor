import React from 'react';
import { Trophy, Star, BarChart2, Zap, Info, CheckCircle } from 'lucide-react';
import {
  BASE_WINNER_PTS, BASE_GAMES_PTS, PLAYIN_PTS,
  ROUND_MULTIPLIERS, FUTURES_BASE_POINTS, LEADERS_POINTS,
} from './scoringConstants';

const Card = ({ children, className = '' }) => (
  <div className={`bg-slate-900/70 border border-slate-800 rounded-2xl p-5 ${className}`}>
    {children}
  </div>
);

const SectionHeader = ({ icon: Icon, title, color }) => (
  <div className={`flex items-center gap-2.5 mb-4 ${color}`}>
    <Icon className="w-5 h-5 shrink-0" />
    <h2 className="text-base font-black uppercase tracking-widest">{title}</h2>
  </div>
);

const Badge = ({ children, color = 'bg-orange-500/20 text-orange-400 border-orange-500/30' }) => (
  <span className={`inline-block px-2 py-0.5 rounded-full border text-[10px] font-black uppercase tracking-wider ${color}`}>
    {children}
  </span>
);

const ROUND_ROWS = [
  { round: 'First Round',          mult: 1, winner: BASE_WINNER_PTS * 1, games: BASE_GAMES_PTS * 1, total: (BASE_WINNER_PTS + BASE_GAMES_PTS) * 1 },
  { round: 'Conference Semifinals', mult: 2, winner: BASE_WINNER_PTS * 2, games: BASE_GAMES_PTS * 2, total: (BASE_WINNER_PTS + BASE_GAMES_PTS) * 2 },
  { round: 'Conference Finals',    mult: 3, winner: BASE_WINNER_PTS * 3, games: BASE_GAMES_PTS * 3, total: (BASE_WINNER_PTS + BASE_GAMES_PTS) * 3 },
  { round: 'NBA Finals',           mult: 4, winner: BASE_WINNER_PTS * 4, games: BASE_GAMES_PTS * 4, total: (BASE_WINNER_PTS + BASE_GAMES_PTS) * 4 },
];

const R1_UNDERDOG_ROWS = [
  { matchup: '1 vs 8', key: '1-8', mult: 2.5, winnerPts: Math.floor(BASE_WINNER_PTS * 2.5), gamesPts: Math.floor(BASE_GAMES_PTS * 2.5), totalPts: Math.floor((BASE_WINNER_PTS + BASE_GAMES_PTS) * 2.5) },
  { matchup: '2 vs 7', key: '2-7', mult: 2.0, winnerPts: Math.floor(BASE_WINNER_PTS * 2.0), gamesPts: Math.floor(BASE_GAMES_PTS * 2.0), totalPts: Math.floor((BASE_WINNER_PTS + BASE_GAMES_PTS) * 2.0) },
  { matchup: '3 vs 6', key: '3-6', mult: 1.5, winnerPts: Math.floor(BASE_WINNER_PTS * 1.5), gamesPts: Math.floor(BASE_GAMES_PTS * 1.5), totalPts: Math.floor((BASE_WINNER_PTS + BASE_GAMES_PTS) * 1.5) },
  { matchup: '4 vs 5', key: '4-5', mult: 1.0, winnerPts: Math.floor(BASE_WINNER_PTS * 1.0), gamesPts: Math.floor(BASE_GAMES_PTS * 1.0), totalPts: Math.floor((BASE_WINNER_PTS + BASE_GAMES_PTS) * 1.0) },
];

const LEADER_ROWS = [
  { label: 'Most Total Points',    key: 'scorer',  pts: LEADERS_POINTS.scorer,  color: 'text-yellow-400' },
  { label: 'Most Total Assists',   key: 'assists', pts: LEADERS_POINTS.assists, color: 'text-blue-400'   },
  { label: 'Most Total Rebounds',  key: 'rebounds',pts: LEADERS_POINTS.rebounds,color: 'text-green-400'  },
  { label: 'Most 3-Pointers Made', key: 'threes',  pts: LEADERS_POINTS.threes,  color: 'text-purple-400' },
  { label: 'Most Total Steals',    key: 'steals',  pts: LEADERS_POINTS.steals,  color: 'text-red-400'    },
  { label: 'Most Total Blocks',    key: 'blocks',  pts: LEADERS_POINTS.blocks,  color: 'text-orange-400' },
];

export default function ScoringGuide() {
  return (
    <div className="max-w-2xl mx-auto px-4 py-8 space-y-6">
      {/* Page title */}
      <div className="text-center mb-2">
        <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-orange-500/20 border border-orange-500/30 mb-4">
          <Info className="w-3.5 h-3.5 text-orange-400" />
          <span className="text-xs font-black text-orange-400 uppercase tracking-wider">Scoring System</span>
        </div>
        <h1 className="text-3xl font-black text-white">How Scoring Works</h1>
        <p className="text-slate-400 text-sm mt-2">Earn points by correctly predicting winners, series length, and more.</p>
      </div>

      {/* ── Play-In ── */}
      <Card>
        <SectionHeader icon={Zap} title="Play-In Tournament" color="text-cyan-400" />
        <div className="flex items-center justify-between bg-cyan-500/10 border border-cyan-500/20 rounded-xl px-4 py-3">
          <span className="text-slate-300 text-sm font-bold">Correct winner prediction</span>
          <span className="text-2xl font-black text-cyan-400">+{PLAYIN_PTS} pts</span>
        </div>
        <p className="text-slate-500 text-xs mt-3">Flat points per correct Play-In winner. No games prediction needed.</p>
      </Card>

      {/* ── Playoff Series ── */}
      <Card>
        <SectionHeader icon={Trophy} title="Playoff Series" color="text-orange-400" />

        {/* Base points by round */}
        <p className="text-xs text-slate-500 uppercase font-bold tracking-wider mb-3">Points by round (favourite pick)</p>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-500 text-[11px] font-bold uppercase tracking-wider">
                <th className="text-left pb-2">Round</th>
                <th className="text-center pb-2">Mult</th>
                <th className="text-right pb-2">Winner</th>
                <th className="text-right pb-2">+ Games</th>
                <th className="text-right pb-2">Max</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {ROUND_ROWS.map(r => (
                <tr key={r.round} className="text-white">
                  <td className="py-2.5 text-xs font-bold text-slate-300">{r.round}</td>
                  <td className="py-2.5 text-center">
                    <Badge color="bg-slate-800 text-slate-400 border-slate-700">{r.mult}x</Badge>
                  </td>
                  <td className="py-2.5 text-right font-black text-orange-400">+{r.winner}</td>
                  <td className="py-2.5 text-right font-black text-blue-400">+{r.games}</td>
                  <td className="py-2.5 text-right font-black text-green-400">{r.total}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-slate-600 text-[11px] mt-1">Games bonus only awarded when both winner AND games are correct.</p>

        {/* R1 underdog multipliers */}
        <div className="mt-5">
          <p className="text-xs text-slate-500 uppercase font-bold tracking-wider mb-3">First Round underdog multipliers</p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-500 text-[11px] font-bold uppercase tracking-wider">
                  <th className="text-left pb-2">Matchup</th>
                  <th className="text-center pb-2">Underdog mult</th>
                  <th className="text-right pb-2">Winner pts</th>
                  <th className="text-right pb-2">Max pts</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {R1_UNDERDOG_ROWS.map(r => (
                  <tr key={r.key} className="text-white">
                    <td className="py-2.5 text-xs font-bold text-slate-300">Seed {r.matchup}</td>
                    <td className="py-2.5 text-center">
                      <Badge color={r.mult > 1 ? 'bg-amber-500/20 text-amber-400 border-amber-500/30' : 'bg-slate-800 text-slate-400 border-slate-700'}>
                        {r.mult}x
                      </Badge>
                    </td>
                    <td className="py-2.5 text-right font-black text-orange-400">+{r.winnerPts}</td>
                    <td className="py-2.5 text-right font-black text-green-400">{r.totalPts}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-slate-500 text-[11px] mt-1">Underdog = higher seed number. Favourite picks always get x1.0.</p>
        </div>

        {/* Late rounds underdog */}
        <div className="mt-4 flex items-center gap-3 bg-amber-500/10 border border-amber-500/20 rounded-xl px-4 py-3">
          <Badge color="bg-amber-500/20 text-amber-400 border-amber-500/30">1.5x</Badge>
          <span className="text-slate-300 text-sm flex-1">
            <strong>Semis / Conf Finals / Finals underdog pick</strong> — any correct underdog = 1.5x multiplier
          </span>
        </div>

        {/* Worked examples */}
        <div className="mt-5 space-y-2">
          <p className="text-xs text-slate-500 uppercase font-bold tracking-wider mb-3">Examples</p>
          {[
            { label: 'R1 1v8 — pick underdog, correct winner only', pts: 50, note: '20 × 1 × 2.5' },
            { label: 'R1 1v8 — pick underdog, correct winner + games', pts: 150, note: '60 × 1 × 2.5' },
            { label: 'Conf Finals — pick underdog, correct winner + games', pts: 180, note: '60 × 3 × 1.5' },
            { label: 'NBA Finals — pick favourite, correct winner + games', pts: 240, note: '60 × 4 × 1.0' },
          ].map(ex => (
            <div key={ex.label} className="flex items-center justify-between gap-3 bg-slate-800/50 rounded-xl px-3 py-2.5">
              <span className="text-xs text-slate-400 flex-1">{ex.label}</span>
              <span className="text-xs text-slate-600 font-bold shrink-0 hidden sm:block">{ex.note}</span>
              <span className="text-sm font-black text-green-400 shrink-0">+{ex.pts} pts</span>
            </div>
          ))}
        </div>
      </Card>

      {/* ── Futures ── */}
      <Card>
        <SectionHeader icon={Star} title="Futures Predictions" color="text-yellow-400" />
        <p className="text-slate-500 text-xs mb-4">Base points shown below. Admin may apply an odds multiplier — final pts = base × multiplier.</p>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {[
            { label: 'NBA Champion',    pts: FUTURES_BASE_POINTS.champion,       color: 'text-yellow-400', border: 'border-yellow-500/30', bg: 'bg-yellow-500/10' },
            { label: 'West Champion',   pts: FUTURES_BASE_POINTS.west_champ,     color: 'text-red-400',    border: 'border-red-500/30',    bg: 'bg-red-500/10'    },
            { label: 'East Champion',   pts: FUTURES_BASE_POINTS.east_champ,     color: 'text-blue-400',   border: 'border-blue-500/30',   bg: 'bg-blue-500/10'   },
            { label: 'Finals MVP',      pts: FUTURES_BASE_POINTS.finals_mvp,     color: 'text-orange-400', border: 'border-orange-500/30', bg: 'bg-orange-500/10' },
            { label: 'West Finals MVP', pts: FUTURES_BASE_POINTS.west_finals_mvp,color: 'text-red-400',    border: 'border-red-500/30',    bg: 'bg-red-500/10'    },
            { label: 'East Finals MVP', pts: FUTURES_BASE_POINTS.east_finals_mvp,color: 'text-blue-400',   border: 'border-blue-500/30',   bg: 'bg-blue-500/10'   },
          ].map(f => (
            <div key={f.label} className={`rounded-xl border ${f.border} ${f.bg} p-3 text-center`}>
              <div className={`text-2xl font-black ${f.color}`}>{f.pts}</div>
              <div className="text-[11px] text-slate-400 font-bold mt-0.5">{f.label}</div>
              <div className="text-[10px] text-slate-600 mt-0.5">base pts</div>
            </div>
          ))}
        </div>
        <div className="mt-3 flex items-center gap-2 text-xs text-slate-500 bg-slate-800/40 rounded-xl px-3 py-2">
          <Info className="w-3.5 h-3.5 shrink-0 text-slate-600" />
          Picks lock before the playoffs begin and cannot be changed.
        </div>
      </Card>

      {/* ── Playoff Highs / Leaders ── */}
      <Card>
        <SectionHeader icon={BarChart2} title="Playoff Leaders (Highs)" color="text-cyan-400" />
        <p className="text-slate-500 text-xs mb-4">
          Predict which player leads the entire playoffs in each stat category.
          Points awarded only for an <strong className="text-slate-300">exact match</strong>.
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {LEADER_ROWS.map(l => (
            <div key={l.key} className="bg-slate-800/50 border border-slate-700/60 rounded-xl p-3 text-center">
              <div className={`text-2xl font-black ${l.color}`}>{l.pts}</div>
              <div className="text-[11px] text-slate-300 font-bold mt-0.5 leading-tight">{l.label}</div>
              <div className="mt-1.5">
                <Badge color="bg-slate-700/60 text-slate-400 border-slate-600/40">exact match</Badge>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-3 flex items-center gap-2 text-xs text-slate-500 bg-slate-800/40 rounded-xl px-3 py-2">
          <CheckCircle className="w-3.5 h-3.5 shrink-0 text-slate-600" />
          Picks lock with Futures. If two players tie, the pick is considered incorrect.
        </div>
      </Card>

      {/* ── Quick summary ── */}
      <div className="text-center text-slate-600 text-xs pb-4">
        Scoring is calculated automatically when results are entered by the admin.
      </div>
    </div>
  );
}
