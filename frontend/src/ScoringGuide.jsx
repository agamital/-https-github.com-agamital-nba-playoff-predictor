import React from 'react';
import { Trophy, Star, BarChart2, Zap, Info, Target } from 'lucide-react';
import {
  BASE_WINNER_PTS, BASE_GAMES_PTS,
  PLAYIN_PTS, PLAYIN_UNDERDOG_PTS,
  FUTURES_BASE_POINTS, LEADERS_TIERS,
  SERIES_LEADER_BONUS, FINALS_CHAMPION_MULT, ROUND_MULTIPLIERS,
} from './scoringConstants';

// ── Shared primitives ──────────────────────────────────────────────────────────

const Card = ({ children, className = '' }) => (
  <div className={`bg-slate-900/70 border border-slate-800 rounded-2xl ${className}`}>
    {children}
  </div>
);

const WeightBadge = ({ label }) => (
  <span className="text-[10px] font-black px-2 py-0.5 rounded-full bg-slate-800 border border-slate-700 text-slate-500 tabular-nums">
    {label}
  </span>
);

const TierPill = ({ icon, label, variant }) => {
  const styles = {
    exact: 'bg-green-500/10 border-green-500/25 text-green-300',
    close: 'bg-yellow-500/10 border-yellow-500/25 text-yellow-300',
    miss:  'bg-red-500/5  border-red-500/15   text-red-400',
  };
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-[11px] font-bold ${styles[variant]}`}>
      <span>{icon}</span>
      <span>{label}</span>
    </span>
  );
};

// ── Pre-computed table data ────────────────────────────────────────────────────

const ROUND_ROWS = [
  { label: 'First Round',           abbr: 'R1',     winMult: ROUND_MULTIPLIERS['First Round'],           gmMult: ROUND_MULTIPLIERS['First Round']           },
  { label: 'Conference Semifinals', abbr: 'Semis',  winMult: ROUND_MULTIPLIERS['Conference Semifinals'], gmMult: ROUND_MULTIPLIERS['Conference Semifinals'] },
  { label: 'Conference Finals',     abbr: 'CF',     winMult: ROUND_MULTIPLIERS['Conference Finals'],     gmMult: ROUND_MULTIPLIERS['Conference Finals']     },
  { label: 'NBA Finals',            abbr: 'Finals', winMult: FINALS_CHAMPION_MULT,                       gmMult: ROUND_MULTIPLIERS['NBA Finals']            },
].map(r => ({
  ...r,
  winner: Math.floor(BASE_WINNER_PTS * r.winMult),
  exact:  Math.floor(BASE_GAMES_PTS  * r.gmMult),
  isChamp: r.abbr === 'Finals',
}));

const R1_UNDERDOG_ROWS = [
  { matchup: '1 vs 8', key: '1-8', udMult: 2.0 },
  { matchup: '2 vs 7', key: '2-7', udMult: 1.5 },
  { matchup: '3 vs 6', key: '3-6', udMult: 1.2 },
  { matchup: '4 vs 5', key: '4-5', udMult: 1.0 },
].map(r => ({
  ...r,
  winner: Math.floor(BASE_WINNER_PTS * r.udMult),
  total:  Math.floor((BASE_WINNER_PTS + BASE_GAMES_PTS) * r.udMult),
}));

const LEADER_ROWS = [
  { label: 'Most Points',   key: 'scorer',   color: 'text-yellow-400' },
  { label: 'Most Assists',  key: 'assists',  color: 'text-blue-400'   },
  { label: 'Most Rebounds', key: 'rebounds', color: 'text-green-400'  },
  { label: 'Most 3PM',      key: 'threes',   color: 'text-purple-400' },
  { label: 'Most Steals',   key: 'steals',   color: 'text-red-400'    },
  { label: 'Most Blocks',   key: 'blocks',   color: 'text-orange-400' },
];

// ── Component ──────────────────────────────────────────────────────────────────

export default function ScoringGuide() {
  return (
    <div className="max-w-2xl mx-auto px-4 py-8 space-y-8">

      {/* Page header */}
      <div className="text-center">
        <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-orange-500/20 border border-orange-500/30 mb-4">
          <Info className="w-3.5 h-3.5 text-orange-400" />
          <span className="text-xs font-black text-orange-400 uppercase tracking-wider">Scoring System</span>
        </div>
        <h1 className="text-3xl font-black text-white">How Scoring Works</h1>
        <p className="text-slate-500 text-sm mt-2">Predict series winners, length, leaders &amp; futures. More risk = more reward.</p>
      </div>

      {/* ══ PRIMARY — Playoff Series ══════════════════════════════════════════ */}
      <Card className="p-6 border-orange-500/20 bg-gradient-to-b from-orange-500/5 to-slate-900/70">
        <div className="flex items-center gap-2.5 mb-5">
          <Trophy className="w-6 h-6 text-orange-400 shrink-0" />
          <h2 className="text-lg font-black text-orange-400 uppercase tracking-widest flex-1">Playoff Series</h2>
          <WeightBadge label="50%" />
        </div>

        {/* Formula callout */}
        <div className="flex flex-wrap items-center gap-2 mb-5 text-sm font-black">
          <span className="px-3 py-1.5 rounded-lg bg-orange-500/20 border border-orange-500/30 text-orange-300">
            Winner +{BASE_WINNER_PTS}
          </span>
          <span className="text-slate-600">+</span>
          <span className="px-3 py-1.5 rounded-lg bg-blue-500/15 border border-blue-500/25 text-blue-300">
            Exact Games +{BASE_GAMES_PTS}
          </span>
          <span className="text-slate-600">=</span>
          <span className="px-3 py-1.5 rounded-lg bg-green-500/10 border border-green-500/25 text-green-300 text-base">
            {BASE_WINNER_PTS + BASE_GAMES_PTS} pts max
          </span>
        </div>

        {/* Round multiplier table */}
        <p className="text-[10px] text-slate-600 font-black uppercase tracking-widest mb-2">Points by round</p>
        <div className="overflow-x-auto rounded-xl border border-slate-800 mb-5">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[10px] text-slate-600 font-black uppercase tracking-wider border-b border-slate-800">
                <th className="text-left px-3 py-2">Round</th>
                <th className="text-center px-3 py-2">Winner ×</th>
                <th className="text-center px-3 py-2 text-orange-500/80">Winner pts</th>
                <th className="text-center px-3 py-2 text-blue-500/80">+ Exact</th>
                <th className="text-center px-3 py-2 text-green-500/70">Max</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {ROUND_ROWS.map((r) => (
                <tr key={r.label} className={r.isChamp ? 'bg-yellow-500/5' : ''}>
                  <td className="px-3 py-2.5 text-xs font-bold text-slate-300">
                    {r.label}
                    {r.isChamp && <span className="ml-1.5 text-[9px] font-black text-yellow-400 bg-yellow-500/15 px-1.5 py-0.5 rounded">Champion</span>}
                  </td>
                  <td className="px-3 py-2.5 text-center">
                    <span className="text-[11px] font-black text-slate-400 bg-slate-800 px-1.5 py-0.5 rounded">
                      {r.winMult}×
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-center font-black text-orange-400">+{r.winner}</td>
                  <td className="px-3 py-2.5 text-center font-black text-blue-400">+{r.exact}</td>
                  <td className="px-3 py-2.5 text-center font-black text-green-400">{r.winner + r.exact}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-[11px] text-slate-600 mb-5">
          NBA Finals winner = Correct Champion bonus: <strong className="text-yellow-400">×{FINALS_CHAMPION_MULT}</strong> on winner pts, ×2.0 on games pts.
        </p>

        {/* R1 Underdog table */}
        <p className="text-[10px] text-slate-600 font-black uppercase tracking-widest mb-2">
          First Round underdog multipliers
        </p>
        <div className="grid grid-cols-2 gap-2 mb-5">
          {R1_UNDERDOG_ROWS.map(r => (
            <div key={r.key}
              className={`flex items-center justify-between px-3 py-2 rounded-lg border text-xs font-bold ${
                r.udMult > 1
                  ? 'border-amber-500/25 bg-amber-500/10 text-amber-300'
                  : 'border-slate-700/50 bg-slate-800/40 text-slate-500'
              }`}>
              <span>Seed {r.matchup}</span>
              <span className="font-black">
                {r.udMult > 1 ? `×${r.udMult}` : '×1.0 (no bonus)'}
              </span>
            </div>
          ))}
        </div>
        <p className="text-[11px] text-slate-600 mb-5">
          Semis / CF / Finals underdog: flat <strong className="text-slate-400">×1.5</strong> on all points.
        </p>

        {/* Examples */}
        <p className="text-[10px] text-slate-600 font-black uppercase tracking-widest mb-2">Examples</p>
        <div className="space-y-1.5">
          {[
            { label: 'R1 1v8 — underdog winner only',             pts: 100 },
            { label: 'R1 1v8 — underdog winner + exact games',    pts: 160,  green: true },
            { label: 'R1 2v7 — underdog winner + exact games',    pts: 120,  green: true },
            { label: 'Conf Finals — favourite, winner + games',   pts: 160 },
            { label: 'Conf Finals — underdog, winner + games',    pts: 240,  green: true },
            { label: 'NBA Finals — correct champion + games',     pts: 200,  gold: true  },
          ].map(ex => (
            <div key={ex.label} className="flex items-center justify-between gap-2 bg-slate-800/50 rounded-lg px-3 py-2">
              <span className="text-xs text-slate-400 flex-1">{ex.label}</span>
              <span className={`text-sm font-black shrink-0 ${ex.gold ? 'text-yellow-400' : ex.green ? 'text-green-400' : 'text-orange-400'}`}>
                +{ex.pts}
              </span>
            </div>
          ))}
        </div>
      </Card>

      {/* ══ Series Statistical Leaders (NEW) ════════════════════════════════ */}
      <Card className="p-5 border-cyan-500/15">
        <div className="flex items-center gap-2.5 mb-3">
          <Target className="w-5 h-5 text-cyan-400 shrink-0" />
          <h2 className="text-base font-black text-cyan-400 uppercase tracking-widest flex-1">Series Leaders</h2>
          <span className="text-[10px] font-black px-2 py-0.5 rounded-full bg-cyan-500/10 border border-cyan-500/20 text-cyan-400">NEW</span>
        </div>
        <p className="text-slate-500 text-xs mb-4">
          For each series, predict the leading scorer, rebounder, and assister.
          <strong className="text-slate-300"> +{SERIES_LEADER_BONUS} pts</strong> per correct prediction — up to +30 pts per series.
        </p>
        <div className="grid grid-cols-3 gap-2">
          {[
            { label: 'Top Scorer',    color: 'text-yellow-400', ring: 'border-yellow-500/20 bg-yellow-500/5' },
            { label: 'Top Rebounder', color: 'text-green-400',  ring: 'border-green-500/20  bg-green-500/5'  },
            { label: 'Top Assister',  color: 'text-blue-400',   ring: 'border-blue-500/20   bg-blue-500/5'   },
          ].map(c => (
            <div key={c.label} className={`rounded-xl border ${c.ring} p-3 text-center`}>
              <div className={`text-2xl font-black ${c.color}`}>+{SERIES_LEADER_BONUS}</div>
              <div className="text-[10px] text-slate-500 font-bold mt-0.5">{c.label}</div>
            </div>
          ))}
        </div>
      </Card>

      {/* ══ Playoff Leaders / Highs ══════════════════════════════════════════ */}
      <Card className="p-5">
        <div className="flex items-center gap-2.5 mb-4">
          <BarChart2 className="w-5 h-5 text-purple-400 shrink-0" />
          <h2 className="text-base font-black text-purple-400 uppercase tracking-widest flex-1">Playoff Highs</h2>
          <WeightBadge label="25%" />
        </div>
        <p className="text-slate-500 text-xs mb-4">
          Predict the highest <strong className="text-slate-400">cumulative</strong> stat total across the entire playoffs (single player).
          Closer = more points.
        </p>

        <div className="flex gap-2 mb-4">
          <TierPill icon="🎯" label="Exact" variant="exact" />
          <TierPill icon="🤏" label="Close" variant="close" />
          <TierPill icon="❌" label="Miss"  variant="miss" />
        </div>

        <div className="space-y-2">
          {LEADER_ROWS.map(l => {
            const tiers = LEADERS_TIERS[l.key] || [];
            return (
              <div key={l.key} className="bg-slate-800/40 border border-slate-700/30 rounded-xl px-3 py-2.5">
                <div className="flex items-center justify-between mb-2">
                  <span className={`text-xs font-black ${l.color}`}>{l.label}</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {tiers.map(([maxDelta, pts], i) => {
                    const prevDelta  = i === 0 ? -1 : tiers[i - 1][0];
                    const isExact    = maxDelta === 0;
                    const rangeLabel = isExact
                      ? '🎯 Exact'
                      : prevDelta === 0
                        ? `🤏 ±${maxDelta}`
                        : `🤏 ±${prevDelta + 1}–${maxDelta}`;
                    return (
                      <span key={maxDelta}
                        className={`px-2 py-0.5 rounded border text-[11px] font-black tabular-nums ${
                          isExact
                            ? 'bg-green-500/10 border-green-500/25 text-green-300'
                            : 'bg-yellow-500/10 border-yellow-500/20 text-yellow-300'
                        }`}>
                        {rangeLabel} = +{pts}
                      </span>
                    );
                  })}
                  <span className="px-2 py-0.5 rounded border text-[11px] font-black bg-slate-800 border-slate-700 text-slate-600">
                    ❌ = 0
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      {/* ══ Futures / Global Predictions ════════════════════════════════════ */}
      <Card className="p-5">
        <div className="flex items-center gap-2.5 mb-4">
          <Star className="w-5 h-5 text-yellow-400 shrink-0" />
          <h2 className="text-base font-black text-yellow-400 uppercase tracking-widest flex-1">Global Predictions</h2>
          <WeightBadge label="22%" />
        </div>
        <p className="text-slate-600 text-xs mb-4">Base × Vegas multiplier. Higher-odds picks earn more.</p>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
          {[
            { label: 'NBA Champion',       pts: FUTURES_BASE_POINTS.champion,        color: 'text-yellow-400', ring: 'border-yellow-500/25 bg-yellow-500/8' },
            { label: 'West Champion',      pts: FUTURES_BASE_POINTS.west_champ,      color: 'text-red-400',    ring: 'border-red-500/20    bg-red-500/5'    },
            { label: 'East Champion',      pts: FUTURES_BASE_POINTS.east_champ,      color: 'text-blue-400',   ring: 'border-blue-500/20   bg-blue-500/5'   },
            { label: 'League MVP',         pts: FUTURES_BASE_POINTS.finals_mvp,      color: 'text-orange-400', ring: 'border-orange-500/25 bg-orange-500/8' },
            { label: 'West Conf MVP',      pts: FUTURES_BASE_POINTS.west_finals_mvp, color: 'text-red-400',    ring: 'border-red-500/20    bg-red-500/5'    },
            { label: 'East Conf MVP',      pts: FUTURES_BASE_POINTS.east_finals_mvp, color: 'text-blue-400',   ring: 'border-blue-500/20   bg-blue-500/5'   },
          ].map(f => (
            <div key={f.label} className={`rounded-xl border ${f.ring} p-3 flex items-center justify-between gap-2`}>
              <div>
                <div className="text-[10px] text-slate-500 font-bold uppercase tracking-wide">{f.label}</div>
                <div className="text-[10px] text-slate-700 font-bold mt-0.5">base pts</div>
              </div>
              <div className={`text-xl font-black tabular-nums ${f.color}`}>{f.pts}</div>
            </div>
          ))}
        </div>
        <div className="mt-3 text-[11px] text-slate-600 flex items-center gap-1.5">
          <Info className="w-3.5 h-3.5 shrink-0" />
          Picks lock before the playoffs begin.
        </div>
      </Card>

      {/* ══ Play-In ══════════════════════════════════════════════════════════ */}
      <Card className="p-4">
        <div className="flex items-center gap-2.5 mb-3">
          <Zap className="w-4 h-4 text-cyan-500/60 shrink-0" />
          <h2 className="text-sm font-black text-slate-400 uppercase tracking-widest flex-1">Play-In Games</h2>
          <WeightBadge label="3%" />
        </div>
        <div className="flex flex-wrap gap-2">
          <span className="px-3 py-1.5 rounded-lg bg-slate-800/60 border border-slate-700 text-xs font-bold text-slate-300">
            Correct favourite <span className="font-black text-cyan-400 ml-1">+{PLAYIN_PTS} pts</span>
          </span>
          <span className="px-3 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/20 text-xs font-bold text-slate-300">
            Correct underdog <span className="font-black text-amber-400 ml-1">+{PLAYIN_UNDERDOG_PTS} pts</span>
          </span>
        </div>
      </Card>

      {/* Footer note */}
      <p className="text-center text-slate-700 text-xs pb-4">
        Scoring updates automatically when admin enters results.
      </p>
    </div>
  );
}
