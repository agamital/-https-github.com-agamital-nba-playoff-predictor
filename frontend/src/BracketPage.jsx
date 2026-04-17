import React, { useState, useMemo, useEffect, useRef } from 'react';
import { Trophy, ChevronRight, ChevronDown, ChevronUp, AlertTriangle, RefreshCw, Info, Clock, Lock, CheckCircle, XCircle, Edit2 } from 'lucide-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import * as api from './services/api';
import { calcSeriesPts, getUnderdogMult, getRoundMult, PLAYIN_PTS, PLAYIN_UNDERDOG_PTS } from './scoringConstants';
import CommunityInsights from './components/CommunityInsights';

// ── Play-In countdown timers (Israel/Jerusalem time, UTC+3) ───────────────────
const PLAYIN_START_TIMES = {
  'Eastern_7v8':         '2026-04-15T23:30:00Z',  // Tue 7:30 PM ET → Wed 02:30 IDT
  'Western_7v8':         '2026-04-16T02:00:00Z',  // Tue 10:00 PM ET → Wed 05:00 IDT
  'Eastern_9v10':        '2026-04-16T23:30:00Z',  // Wed 7:30 PM ET → Thu 02:30 IDT
  'Western_9v10':        '2026-04-17T02:00:00Z',  // Wed 10:00 PM ET → Thu 05:00 IDT
  'Eastern_elimination': '2026-04-18T23:30:00Z',  // Fri 7:30 PM ET → Sat 02:30 IDT
  'Western_elimination': '2026-04-19T02:00:00Z',  // Fri 10:00 PM ET → Sat 05:00 IDT
};

function getPlayInStartZ(game) {
  if (!game) return null;
  if (game.start_time) return game.start_time.endsWith('Z') ? game.start_time : game.start_time + 'Z';
  return PLAYIN_START_TIMES[`${game.conference}_${game.game_type}`] || null;
}

function usePlayInCountdown(startZ) {
  const calc = () => startZ ? Math.floor((new Date(startZ) - Date.now()) / 1000) : null;
  const [secs, setSecs] = useState(calc);
  useEffect(() => {
    if (!startZ) return;
    const id = setInterval(() => setSecs(calc()), 1000);
    return () => clearInterval(id);
  }, [startZ]);
  return secs;
}

function PlayInTimeLabel({ startZ }) {
  if (!startZ) return null;
  const label = new Date(startZ).toLocaleString('en-IL', {
    timeZone: 'Asia/Jerusalem', weekday: 'short', month: 'short',
    day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  });
  return <span className="text-[10px] text-slate-500">🕐 {label} IL</span>;
}

function PlayInCountdown({ startZ }) {
  const secs = usePlayInCountdown(startZ);
  if (secs === null) return null;
  if (secs <= 0) return (
    <span className="flex items-center gap-1 text-[10px] font-bold text-rose-400">
      <Lock className="w-2.5 h-2.5" /> Bets closed
    </span>
  );
  const pad = n => String(n).padStart(2, '0');
  const d  = Math.floor(secs / 86400);
  const h  = Math.floor((secs % 86400) / 3600);
  const m  = Math.floor((secs % 3600) / 60);
  const s  = secs % 60;
  const urgent = secs < 7200;
  return (
    <span className={`flex items-center gap-1 text-[10px] font-mono font-bold ${urgent ? 'text-amber-400' : 'text-cyan-400'}`}>
      <Clock className="w-2.5 h-2.5 shrink-0" />
      {d > 1 ? `${d}d ` : ''}{d > 1 ? pad(h) : h}:{pad(m)}:{pad(s)}
    </span>
  );
}

// ── First Round Game 1 schedule (frontend fallback when backend field is null) ─
// Keys: `${conference}_${Math.min(s1,s2)}_${Math.max(s1,s2)}`
const _FR_SCHEDULE = {};
const _FR_SCHEDULE_DATA = [
  ['Eastern_4_5', '2026-04-18T17:00:00Z'],   // CLE vs TOR  · Sat 20:00 IDT
  ['Western_3_6', '2026-04-18T19:30:00Z'],   // DEN vs MIN  · Sat 22:30 IDT
  ['Eastern_3_6', '2026-04-18T22:00:00Z'],   // NYK vs ATL  · Sun 01:00 IDT
  ['Western_4_5', '2026-04-19T00:30:00Z'],   // LAL vs HOU  · Sun 03:30 IDT
  ['Eastern_2_7', '2026-04-19T17:00:00Z'],   // BOS vs #7   · Sun 20:00 IDT
  ['Western_1_8', '2026-04-19T19:30:00Z'],   // OKC vs #8   · Sun 22:30 IDT
  ['Eastern_1_8', '2026-04-19T22:30:00Z'],   // DET vs #8   · Mon 01:30 IDT
  ['Western_2_7', '2026-04-20T01:00:00Z'],   // SAS vs #7   · Mon 04:00 IDT
];
_FR_SCHEDULE_DATA.forEach(([k, v]) => { _FR_SCHEDULE[k] = v; });

function getSeriesGame1Z(series) {
  if (series.game1_start_time) return series.game1_start_time;
  if (series.round !== 'First Round') return null;
  // Try every combination of conf+seeds — backend may COALESCE NULL seeds to 0
  const conf = series.conference; // 'Eastern' | 'Western'
  const hs   = series.home_seed  != null ? +series.home_seed  : +(series.home_team?.seed  ?? 0);
  const as_  = series.away_seed  != null ? +series.away_seed  : +(series.away_team?.seed  ?? 0);
  if (conf && hs > 0 && as_ > 0) {
    const lo = Math.min(hs, as_), hi = Math.max(hs, as_);
    const t = _FR_SCHEDULE[`${conf}_${lo}_${hi}`];
    if (t) return t;
  }
  // Last resort: match by team IDs known from standings if seeds aren't reliable
  // Just return the earliest lock time so the card always shows something
  if (series.round === 'First Round') {
    // Return the per-conference earliest game if we can't determine matchup
    const earliestByConf = { Eastern: '2026-04-18T17:00:00Z', Western: '2026-04-18T19:30:00Z' };
    return earliestByConf[conf] || null;
  }
  return null;
}

// ── Desktop bracket compact timer ────────────────────────────────────────────
function DesktopSeriesTimer({ game1StartZ, picksLocked }) {
  const calc = () => game1StartZ ? Math.floor((new Date(game1StartZ) - Date.now()) / 1000) : null;
  const [secs, setSecs] = useState(calc);
  useEffect(() => {
    if (!game1StartZ) return;
    const id = setInterval(() => setSecs(calc()), 1000);
    return () => clearInterval(id);
  }, [game1StartZ]);

  if (!game1StartZ) return null;
  const d = new Date(game1StartZ);
  const idt = new Date(d.getTime() + 3 * 60 * 60 * 1000);
  const hh = String(idt.getUTCHours()).padStart(2, '0');
  const mm = String(idt.getUTCMinutes()).padStart(2, '0');
  const days = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
  const tipLabel = `${days[idt.getUTCDay()]} ${hh}:${mm}`;

  if (secs === null || secs <= 0 || picksLocked) {
    return (
      <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-red-500/20 border border-red-500/30 text-[9px] font-black text-red-400">
        <Lock className="w-2.5 h-2.5" /> Locked
      </span>
    );
  }
  const dv = Math.floor(secs / 86400);
  const hv = Math.floor((secs % 86400) / 3600);
  const mv = Math.floor((secs % 3600) / 60);
  const sv = secs % 60;
  const pad = n => String(n).padStart(2, '0');
  const urgent = secs < 3600;
  const soon   = secs < 86400;
  return (
    <span className={`flex items-center gap-1 px-2 py-0.5 rounded-full border text-[9px] font-black font-mono
      ${urgent ? 'bg-red-500/20 border-red-500/30 text-red-400' : soon ? 'bg-amber-500/15 border-amber-500/30 text-amber-400' : 'bg-slate-800 border-slate-700 text-cyan-400'}`}>
      <Clock className="w-2.5 h-2.5 shrink-0" />
      {dv > 0 ? `${dv}d ` : ''}{pad(hv)}:{pad(mv)}:{pad(sv)}
      <span className={`font-normal ${urgent ? 'text-red-400/60' : 'text-slate-600'}`}>· {tipLabel}</span>
    </span>
  );
}

// ── Per-series Game 1 countdown ───────────────────────────────────────────────
function useSeriesCountdown(game1StartZ) {
  const calc = () => game1StartZ ? Math.floor((new Date(game1StartZ) - Date.now()) / 1000) : null;
  const [secs, setSecs] = useState(calc);
  useEffect(() => {
    if (!game1StartZ) return;
    const id = setInterval(() => setSecs(calc()), 1000);
    return () => clearInterval(id);
  }, [game1StartZ]);
  return secs;
}

function SeriesGame1Countdown({ game1StartZ, picksLocked }) {
  const secs = useSeriesCountdown(game1StartZ);
  if (!game1StartZ) return null;

  // Format tip-off time in Jerusalem (IDT = UTC+3)
  const d = new Date(game1StartZ);
  const idt = new Date(d.getTime() + 3 * 60 * 60 * 1000);
  const days   = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const hh = String(idt.getUTCHours()).padStart(2, '0');
  const mm = String(idt.getUTCMinutes()).padStart(2, '0');
  const tipLabel = `${days[idt.getUTCDay()]} ${months[idt.getUTCMonth()]} ${idt.getUTCDate()} · ${hh}:${mm} IDT`;

  if (secs === null || secs <= 0 || picksLocked) {
    return (
      <div className="flex items-center justify-between px-3 py-2 rounded-xl bg-red-500/8 border border-red-500/20 text-[10px] font-bold">
        <span className="flex items-center gap-1.5 text-red-400">
          <Lock className="w-3 h-3" /> Bets Locked · Game 1 Started
        </span>
        <span className="text-slate-600">{tipLabel}</span>
      </div>
    );
  }

  const days_  = Math.floor(secs / 86400);
  const hours  = Math.floor((secs % 86400) / 3600);
  const mins   = Math.floor((secs % 3600) / 60);
  const secs_  = secs % 60;
  const pad    = n => String(n).padStart(2, '0');
  const urgent = secs < 3600;
  const soon   = secs < 86400;

  return (
    <div className={`px-3 py-2 rounded-xl border text-[10px] font-bold
      ${urgent ? 'bg-red-500/8 border-red-500/20' : soon ? 'bg-amber-500/8 border-amber-500/20' : 'bg-slate-800/50 border-slate-700/50'}`}>
      <div className="flex items-center justify-between">
        <span className={`flex items-center gap-1 ${urgent ? 'text-red-400' : soon ? 'text-amber-400' : 'text-slate-400'}`}>
          <Clock className="w-3 h-3 shrink-0" />
          Bets lock in:
        </span>
        <span className={`font-mono font-black tabular-nums ${urgent ? 'text-red-400' : soon ? 'text-amber-400' : 'text-cyan-400'}`}>
          {days_ > 1 ? `${days_}d ` : ''}{days_ > 1 ? pad(hours) : hours}:{pad(mins)}:{pad(secs_)}
        </span>
      </div>
      <p className="text-slate-600 mt-0.5 text-[9px]">Game 1 tipoff · {tipLabel}</p>
    </div>
  );
}

// Strip diacritics/accents for dedup — matches backend _normalize_name().
// 'Luka Dončić' → 'luka doncic'
const normalizeName = (n) =>
  (n || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();

// ── Layout constants ──────────────────────────────────────────────────────────
const BH = 640;   // bracket total height
const CH = 104;   // card height
const PI_SLOTS = 3; // play-in rows per conference

// ── Connector lines ───────────────────────────────────────────────────────────

const Connector = ({ height, dir = 'right' }) => {
  const half = height / 2;
  const side = dir === 'right' ? 'borderRight' : 'borderLeft';
  const bR   = dir === 'right' ? 10 : 0;
  const bL   = dir === 'left'  ? 10 : 0;
  const base = { [side]: '2px solid #1e3a5f', width: 24, flexShrink: 0 };
  return (
    <div style={{ height, width: 24, flexShrink: 0 }}>
      <div style={{ ...base, height: half, borderBottom: '2px solid #1e3a5f', borderBottomRightRadius: bR, borderBottomLeftRadius: bL }} />
      <div style={{ ...base, height: half, borderTop:    '2px solid #1e3a5f', borderTopRightRadius:    bR, borderTopLeftRadius:    bL }} />
    </div>
  );
};

const ConnectorCol = ({ count, dir }) => (
  <div style={{ display: 'flex', flexDirection: 'column', height: BH + 28, flexShrink: 0 }}>
    {Array.from({ length: count }).map((_, i) => (
      <Connector key={i} height={(BH + 28) / count} dir={dir} />
    ))}
  </div>
);

const HLine = ({ width = 28 }) => (
  <div style={{ height: BH + 28, width, flexShrink: 0, display: 'flex', alignItems: 'center' }}>
    <div style={{ width: '100%', height: 2, background: '#1e3a5f' }} />
  </div>
);

// ── Player dropdown for series leader picks ───────────────────────────────────

// statKey: 'ppg' | 'rpg' | 'apg' — controls sort order and stat label shown in dropdown
const STAT_LABELS = { ppg: 'PPG', rpg: 'RPG', apg: 'APG' };

const PlayerDropdown = ({ label, value, onChange, players, disabled, statKey = 'ppg' }) => {
  const [open, setOpen]   = useState(false);
  const [query, setQuery] = useState(value || '');
  const ref               = useRef(null);

  useEffect(() => {
    if (value !== query) setQuery(value || '');
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // Dedup by both player_id AND accent-normalized name (handles "Doncic" ↔ "Dončić"
  // cross-source splits), then sort by the relevant stat descending.
  const sorted = React.useMemo(() => {
    const seenIds   = new Set();
    const seenNames = new Set();
    const unique = players.filter(p => {
      const normName = normalizeName(p.name);
      if (seenIds.has(p.player_id) || seenNames.has(normName)) return false;
      seenIds.add(p.player_id);
      seenNames.add(normName);
      return true;
    });
    return unique.sort((a, b) => (b[statKey] ?? 0) - (a[statKey] ?? 0));
  }, [players, statKey]);

  const filtered = query.length >= 2
    ? sorted.filter(p => normalizeName(p.name).includes(normalizeName(query))).slice(0, 8)
    : sorted.slice(0, 8);

  const statLabel = STAT_LABELS[statKey] || statKey.toUpperCase();

  return (
    <div ref={ref} className="relative w-full">
      <p className="text-[9px] text-slate-500 uppercase font-bold tracking-widest mb-0.5">{label}</p>
      <div className="relative">
        <input
          type="text"
          value={query}
          disabled={disabled}
          onChange={e => { setQuery(e.target.value); onChange(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          placeholder="Search player…"
          className="w-full px-2 py-1 text-[10px] bg-slate-900 border border-slate-700 rounded-lg text-white placeholder-slate-600 focus:outline-none focus:border-orange-500/60 disabled:opacity-40"
        />
        {value && (
          <button onClick={() => { setQuery(''); onChange(''); }} className="absolute right-1.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white text-[10px]">✕</button>
        )}
      </div>
      {open && filtered.length > 0 && (
        <div className="absolute left-0 right-0 top-full mt-0.5 z-50 bg-slate-900 border border-slate-700 rounded-lg shadow-xl max-h-40 overflow-y-auto">
          {filtered.map(p => (
            <button key={p.player_id} onMouseDown={() => { setQuery(p.name); onChange(p.name); setOpen(false); }}
              className="w-full flex items-center gap-2 px-2 py-1.5 hover:bg-slate-800 transition-colors text-left">
              {p.logo_url && <img src={p.logo_url} alt="" className="w-4 h-4 shrink-0 object-contain" loading="lazy" onError={e => e.target.style.display='none'} />}
              <span className="text-[10px] text-white font-bold truncate flex-1">{p.name}</span>
              <span className="text-[9px] text-orange-400 font-black shrink-0">{(p[statKey] ?? 0).toFixed(1)} {statLabel}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

// ── TBD / Finals cards ────────────────────────────────────────────────────────

const TBDCard = ({ width = 'w-44' }) => (
  <div style={{ height: CH }} className={`${width} bg-slate-900/40 border border-slate-800 rounded-xl flex flex-col overflow-hidden`}>
    <div className="flex-1 flex items-center gap-3 px-4 border-b border-slate-800">
      <div className="w-7 h-7 rounded-full bg-slate-800/80" />
      <span className="text-sm text-slate-600 font-medium">TBD</span>
    </div>
    <div className="flex-1 flex items-center gap-3 px-4">
      <div className="w-7 h-7 rounded-full bg-slate-800/80" />
      <span className="text-sm text-slate-600 font-medium">TBD</span>
    </div>
  </div>
);

const FinalsCard = () => (
  <div style={{ height: BH + 28, flexShrink: 0, width: 220 }} className="flex flex-col items-center justify-center gap-3 px-3">
    <div className="text-center mb-1">
      <Trophy className="w-7 h-7 text-yellow-400 mx-auto mb-1" />
      <p className="text-xs text-yellow-400 uppercase font-black tracking-widest">NBA Finals</p>
    </div>
    <TBDCard />
  </div>
);

// ── Playoff match card ────────────────────────────────────────────────────────

const MatchCard = ({ series, pick, onTeamClick, hasBet }) => {
  const { home_team: h, away_team: a, status, winner_team_id, actual_games } = series;
  const isCompleted = status === 'completed';
  const isLocked    = status === 'locked' || series.picks_locked;
  const hp   = pick?.teamId === h.id;
  const ap   = pick?.teamId === a.id;
  const hWon = winner_team_id === h.id;
  const aWon = winner_team_id === a.id;

  // Inline timer inside the card divider
  const g1z      = status === 'active' ? getSeriesGame1Z(series) : null;
  const timerSecs = useSeriesCountdown(g1z);

  // ── Team row ─────────────────────────────────────────────────────────────────
  const teamRow = (team, picked, won, onClick) => {
    const dimmed = hasBet && !picked && !isCompleted; // fade unchosen when bet is saved
    return (
      <button
        onClick={isCompleted || isLocked ? undefined : onClick}
        className={`relative flex-1 flex items-center gap-2 px-3 w-full transition-all ${
          won                        ? 'bg-green-500/20' :
          isCompleted && !won        ? 'opacity-30' :
          !isCompleted && !isLocked && !picked ? 'hover:bg-slate-800/60' : ''
        } ${dimmed ? 'opacity-50' : ''}`}
        style={{
          cursor: isCompleted || isLocked ? 'default' : 'pointer',
          background: picked && !isCompleted && hasBet
            ? 'linear-gradient(90deg,rgba(234,179,8,0.38) 0%,rgba(234,179,8,0.12) 65%,transparent 100%)'
            : undefined,
        }}
      >
        {/* Gold left accent stripe — only when bet is saved */}
        {picked && !isCompleted && hasBet && (
          <div className="absolute left-0 top-0 bottom-0 w-[3px] bg-yellow-400 rounded-l" />
        )}
        <img src={team.logo_url} alt="" className="w-8 h-8 shrink-0"
          onError={e => e.target.style.display = 'none'} />
        <span className={`text-sm font-black truncate flex-1 ${
          won                              ? 'text-green-300' :
          picked && !isCompleted && hasBet ? 'text-yellow-300' :
          dimmed                           ? 'text-slate-500' :
                                             'text-white'
        }`}>{team.abbreviation}</span>
        {/* Gold star for saved pick, seed number otherwise */}
        {picked && !isCompleted && hasBet
          ? <span className="text-yellow-400 text-sm shrink-0">★</span>
          : <span className={`text-[10px] shrink-0 ${won ? 'text-green-400/60' : 'text-slate-600'}`}>{team.seed}</span>
        }
        {won && actual_games && (
          <span className="text-[9px] text-green-400 font-black shrink-0 ml-0.5">in {actual_games}</span>
        )}
      </button>
    );
  };

  // ── Middle divider — timer or live score ─────────────────────────────────────
  const hasScore = !isCompleted && (series.home_wins > 0 || series.away_wins > 0);
  const showTimer = !isCompleted && !hasScore && g1z && timerSecs !== null;
  const dividerTall = hasScore || showTimer;

  const dividerContent = hasScore ? (
    <span className="text-[9px] font-black tabular-nums px-1.5 bg-slate-950 border border-blue-500/30 text-blue-400 rounded leading-none">
      {series.home_wins}–{series.away_wins}
    </span>
  ) : showTimer ? (() => {
    const pad = n => String(n).padStart(2, '0');
    if (timerSecs <= 0 || series.picks_locked) {
      return <span className="text-[8px] font-black text-red-400/80 flex items-center gap-0.5"><Lock className="w-2 h-2" />Locked</span>;
    }
    const dv = Math.floor(timerSecs / 86400);
    const hv = Math.floor((timerSecs % 86400) / 3600);
    const mv = Math.floor((timerSecs % 3600) / 60);
    const sv = timerSecs % 60;
    const urgent = timerSecs < 3600;
    return (
      <span className={`text-[8px] font-black font-mono flex items-center gap-0.5 ${urgent ? 'text-red-400' : 'text-cyan-400/80'}`}>
        <Clock className="w-2 h-2 shrink-0" />
        {dv > 0 ? `${dv}d ` : ''}{pad(hv)}:{pad(mv)}:{pad(sv)}
      </span>
    );
  })() : null;

  const cardStyle = hasBet
    ? { height: CH, boxShadow: '0 0 0 2px rgba(234,179,8,0.85), 0 0 22px rgba(234,179,8,0.35)' }
    : { height: CH };

  return (
    <div style={cardStyle}
      className={`w-44 border-2 relative rounded-xl flex flex-col overflow-hidden transition-all ${
        isCompleted ? 'border-green-500/50 shadow-sm shadow-green-500/10' :
        hasBet      ? 'border-yellow-400 cursor-pointer' :
        isLocked    ? 'border-slate-600/40 opacity-60' :
        'border-slate-700/50 cursor-pointer hover:border-slate-600/80'
      } bg-slate-900/90`}>
      {teamRow(h, hp, hWon, () => onTeamClick(series, h.id))}
      <div
        className={`relative shrink-0 flex items-center justify-center bg-slate-950 border-y border-slate-800/70 ${dividerTall ? 'h-[14px]' : 'h-px'}`}
      >
        {dividerContent}
      </div>
      {teamRow(a, ap, aWon, () => onTeamClick(series, a.id))}
    </div>
  );
};

// ── Play-In match card ────────────────────────────────────────────────────────

const PlayInCard = ({ game, pick, onTeamClick, hasBet }) => {
  if (!game) return <TBDCard width="w-40" />;
  const { team1, team2 } = game;
  const p1 = pick?.teamId === team1?.id;
  const p2 = pick?.teamId === team2?.id;
  const underdogId = (team1?.seed ?? 0) > (team2?.seed ?? 0) ? team1?.id : team2?.id;
  const startZ = getPlayInStartZ(game);
  const piSecs = usePlayInCountdown(startZ);
  const betsClosed = game.status === 'completed' || (piSecs !== null && piSecs <= 0);
  const winner = game.status === 'completed' && game.winner_id
    ? (game.winner_id === team1?.id ? team1 : team2) : null;

  const teamRow = (team, picked, onClick) => {
    const isWinner = winner?.id === team?.id;
    // When hasBet: fade only the unchosen team (regardless of betsClosed)
    // When no bet and betsClosed: fade non-winners (or both if no winner yet)
    const isGameCompleted = game.status === 'completed';
    const dimmed = hasBet ? (!picked && !isGameCompleted) : (betsClosed && !isWinner);
    const showGold = picked && hasBet && !isGameCompleted;
    return (
      <button onClick={betsClosed ? undefined : onClick}
        className={`relative flex-1 flex items-center gap-2 px-2 w-full transition-all ${
          isWinner             ? 'bg-green-500/20' :
          !picked && !hasBet && !betsClosed ? 'hover:bg-slate-800/60' : ''
        } ${dimmed ? 'opacity-50' : ''}`}
        style={{
          cursor: betsClosed ? 'default' : 'pointer',
          background: showGold
            ? 'linear-gradient(90deg,rgba(234,179,8,0.38) 0%,rgba(234,179,8,0.12) 65%,transparent 100%)'
            : undefined,
        }}>
        {showGold && (
          <div className="absolute left-0 top-0 bottom-0 w-[3px] bg-yellow-400 rounded-l" />
        )}
        <img src={team?.logo_url} alt="" className="w-6 h-6 shrink-0" onError={e => e.target.style.display = 'none'} />
        <span className={`text-xs font-black truncate flex-1 ${
          isWinner   ? 'text-green-300' :
          showGold   ? 'text-yellow-300' :
          dimmed     ? 'text-slate-500' :
                       'text-white'
        }`}>{team?.abbreviation}</span>
        {showGold
          ? <span className="text-yellow-400 text-sm shrink-0">★</span>
          : <span className={`text-[10px] shrink-0 ${isWinner ? 'text-green-400/60' : 'text-slate-600'}`}>{team?.seed}</span>
        }
        {isWinner && <span className="text-[9px] font-black text-green-400 shrink-0">✓</span>}
      </button>
    );
  };

  // Countdown inside divider
  const dividerContent = (() => {
    if (betsClosed || !startZ || piSecs === null) return null;
    const pad = n => String(n).padStart(2, '0');
    const dv = Math.floor(piSecs / 86400);
    const hv = Math.floor((piSecs % 86400) / 3600);
    const mv = Math.floor((piSecs % 3600) / 60);
    const sv = piSecs % 60;
    const urgent = piSecs < 3600;
    return (
      <span className={`text-[8px] font-black font-mono flex items-center gap-0.5 ${urgent ? 'text-red-400' : 'text-cyan-400/80'}`}>
        <Clock className="w-2 h-2 shrink-0" />
        {dv > 0 ? `${dv}d ` : ''}{pad(hv)}:{pad(mv)}:{pad(sv)}
      </span>
    );
  })();

  const cardStyle = hasBet
    ? { height: CH, boxShadow: '0 0 0 2px rgba(234,179,8,0.85), 0 0 22px rgba(234,179,8,0.35)' }
    : { height: CH };

  return (
    <div style={cardStyle}
      className={`w-40 border-2 relative rounded-xl flex flex-col overflow-hidden transition-all bg-slate-900/90 ${
        game.status === 'completed' ? 'border-green-500/40 shadow-sm shadow-green-500/10' :
        hasBet                      ? 'border-yellow-400 cursor-pointer' :
        betsClosed                  ? 'border-slate-600/40 opacity-60' :
        'border-slate-700/50 cursor-pointer hover:border-slate-600/80'
      }`}>
      {teamRow(team1, p1, () => onTeamClick(game, team1?.id))}
      <div className={`relative shrink-0 flex items-center justify-center bg-slate-950 border-y border-slate-800/70 ${dividerContent ? 'h-[14px]' : 'h-px'}`}>
        {dividerContent}
      </div>
      {teamRow(team2, p2, () => onTeamClick(game, team2?.id))}
    </div>
  );
};

// ── Inline pickers ────────────────────────────────────────────────────────────

const InlinePicker = ({ seriesId, series, pick, onGamesSelect, onLeaderSelect, onSave, saved }) => {
  const homeSeed   = series?.home_seed   ?? series?.home_team?.seed   ?? null;
  const awaySeed   = series?.away_seed   ?? series?.away_team?.seed   ?? null;
  const roundName  = series?.round ?? 'First Round';
  const pickedTeamId = pick?.teamId;
  const pickedSeed = pickedTeamId === series?.home_team?.id ? homeSeed
                   : pickedTeamId === series?.away_team?.id ? awaySeed
                   : null;
  const { winnerPts, gamesPts, totalPts } = calcSeriesPts(roundName, homeSeed, awaySeed, pickedSeed);
  const roundMult    = getRoundMult(roundName);
  const underdogMult = getUnderdogMult(roundName, homeSeed, awaySeed, pickedSeed);
  const isUnderdog   = underdogMult > 1.0;
  // Compute bonus above favourite's max pts for the bonus-pop label
  const favSeed      = pickedSeed === homeSeed ? awaySeed : homeSeed;
  const { totalPts: favTotalPts } = calcSeriesPts(roundName, homeSeed, awaySeed, favSeed);
  const bonusAboveFav = totalPts - favTotalPts;

  const { data: seriesPlayers = [] } = useQuery({
    queryKey: ['seriesPlayers', seriesId],
    queryFn:  () => api.getSeriesPlayers(seriesId),
    staleTime: 30 * 60 * 1000,
    enabled: !!seriesId,
  });

  return (
    <div className={`w-44 rounded-xl px-3 py-2 space-y-1.5 shadow-lg transition-all ${
      isUnderdog
        ? 'bg-slate-950/90 border border-amber-500/30 shadow-amber-500/10 underdog-glow'
        : 'bg-slate-950/80 border border-orange-500/20 shadow-orange-500/5'
    }`}>
      {/* Risk / Reward header */}
      <div className="flex items-center justify-between gap-1">
        <span className={`text-[9px] font-black px-1.5 py-0.5 rounded border ${
          isUnderdog
            ? 'text-amber-400 bg-amber-500/15 border-amber-500/30'
            : 'text-slate-400 bg-slate-800 border-slate-700'
        }`}>
          {isUnderdog ? '🔥 RISKY' : '🛡️ SAFE'}
        </span>
        <div className="flex items-center gap-1">
          {/* Live series score */}
          {(series?.home_wins > 0 || series?.away_wins > 0) && (
            <span className="text-[9px] font-black text-blue-400 bg-blue-500/10 border border-blue-500/25 rounded px-1.5 py-0.5 tabular-nums">
              {series.home_wins}–{series.away_wins}
            </span>
          )}
          {isUnderdog && (
            <span className="text-[9px] font-black text-amber-400 bg-amber-500/10 border border-amber-500/25 rounded px-1.5 py-0.5">
              ×{underdogMult}ud
            </span>
          )}
          {roundMult > 1 && (
            <span className="text-[9px] font-black text-slate-500 bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5">
              ×{roundMult}rd
            </span>
          )}
        </div>
      </div>

      {/* Bonus pop for underdog */}
      {isUnderdog && (
        <p key={pickedSeed} className="bonus-pop text-[9px] font-black text-amber-400 text-center bg-amber-500/10 rounded py-0.5">
          +{bonusAboveFav} bonus vs fav pick
        </p>
      )}

      <p className="text-[9px] text-slate-600 font-bold text-center">
        +{winnerPts} winner / +{gamesPts} games
      </p>
      <p className="text-[10px] text-slate-500 uppercase font-bold tracking-widest text-center">Series length</p>
      <div className="grid grid-cols-4 gap-1">
        {[4, 5, 6, 7].map(g => (
          <button key={g} onClick={() => onGamesSelect(seriesId, g)}
            className={`py-1.5 rounded-lg text-sm font-black transition-all border ${
              pick?.games === g
                ? (isUnderdog ? 'border-amber-500 bg-amber-500/25 text-amber-400' : 'border-orange-500 bg-orange-500/25 text-orange-400')
                : 'border-slate-800 bg-slate-900 text-slate-400 hover:border-orange-500/40 hover:text-white'
            }`}>{g}</button>
        ))}
      </div>

      {/* Series leader picks */}
      <div className="pt-1 border-t border-slate-800/60 space-y-1.5">
        <PlayerDropdown label="Leading Scorer" value={pick?.scorer || ''}
          onChange={v => onLeaderSelect(seriesId, 'scorer', v)}
          players={seriesPlayers} statKey="ppg" />
        <PlayerDropdown label="Leading Rebounder" value={pick?.rebounder || ''}
          onChange={v => onLeaderSelect(seriesId, 'rebounder', v)}
          players={seriesPlayers} statKey="rpg" />
        <PlayerDropdown label="Leading Assister" value={pick?.assister || ''}
          onChange={v => onLeaderSelect(seriesId, 'assister', v)}
          players={seriesPlayers} statKey="apg" />
      </div>

      {/* Provisional series leaders */}
      {(series?.leading_scorer || series?.leading_rebounder || series?.leading_assister) && (
        <div className="border-t border-slate-800/60 pt-1.5 space-y-0.5">
          <p className="text-[8px] text-cyan-400/50 font-black uppercase tracking-widest mb-0.5">
            {series?.status === 'active' ? '📊 Provisional Leaders' : '📊 Series Leaders'}
          </p>
          {[
            { abbr: 'PTS', val: series?.leading_scorer },
            { abbr: 'REB', val: series?.leading_rebounder },
            { abbr: 'AST', val: series?.leading_assister },
          ].filter(l => l.val).map(l => (
            <p key={l.abbr} className="text-[8px] text-slate-500 truncate leading-tight">
              <span className="text-slate-600 font-black">{l.abbr}:</span>{' '}
              <span className="text-slate-400">{l.val.split(' ').slice(-1)[0]}</span>
            </p>
          ))}
        </div>
      )}

      <button onClick={() => onSave(seriesId)} disabled={!pick?.games}
        className={`w-full py-1.5 rounded-lg text-[10px] font-black tracking-wide transition-all ${
          saved ? 'bg-green-500/20 border border-green-500/40 text-green-400' :
          !pick?.games ? 'bg-slate-900 border border-slate-800 text-slate-600 cursor-not-allowed' :
          isUnderdog ? 'bg-gradient-to-r from-amber-500 to-orange-500 text-white shadow-md shadow-amber-500/30' :
          'bg-gradient-to-r from-orange-500 to-orange-600 text-white shadow-md shadow-orange-500/30'
        }`}>
        {saved ? '✓ Saved!' : `Save Pick • ${totalPts} pts max`}
      </button>
    </div>
  );
};

const PlayInPicker = ({ game, pick, onSave, saved }) => {
  const underdogId = (game?.team1?.seed ?? 0) > (game?.team2?.seed ?? 0) ? game?.team1?.id : game?.team2?.id;
  const isUnderdogPick = pick?.teamId != null && pick.teamId === underdogId;
  const pts = isUnderdogPick ? PLAYIN_UNDERDOG_PTS : PLAYIN_PTS;
  const startZ = getPlayInStartZ(game);
  const piSecs = usePlayInCountdown(startZ);
  const betsClosed = !game || game.status === 'completed' || (piSecs !== null && piSecs <= 0);

  return (
    <div className={`w-40 rounded-xl px-2 py-2 space-y-1.5 shadow-lg ${
      betsClosed ? 'bg-slate-950/80 border border-red-500/15' :
      isUnderdogPick
        ? 'bg-slate-950/90 border border-amber-500/30 shadow-amber-500/10'
        : 'bg-slate-950/80 border border-orange-500/20'
    }`}>
      {!betsClosed && (isUnderdogPick ? (
        <div className="text-center">
          <p className="text-[9px] font-black text-amber-400">🔥 Underdog Bonus!</p>
          <p className="text-[8px] text-amber-400/60 font-bold">+{pts} pts if correct</p>
        </div>
      ) : (
        <p className="text-[9px] text-cyan-400/80 font-black text-center">+{pts} pts if correct</p>
      ))}
      <button onClick={betsClosed ? undefined : () => onSave(game?.id)}
        disabled={betsClosed || !pick?.teamId}
        className={`w-full py-1.5 rounded-lg text-xs font-black tracking-wide transition-all flex items-center justify-center gap-1 ${
          betsClosed ? 'bg-red-500/15 border border-red-500/25 text-red-400 cursor-not-allowed' :
          saved ? 'bg-green-500/20 border border-green-500/40 text-green-400' :
          !pick?.teamId ? 'bg-slate-900 border border-slate-800 text-slate-600 cursor-not-allowed' :
          isUnderdogPick ? 'bg-gradient-to-r from-amber-500 to-orange-500 text-white shadow-md shadow-amber-500/30' :
          'bg-gradient-to-r from-orange-500 to-orange-600 text-white shadow-md shadow-orange-500/30'
        }`}>
        {betsClosed ? <><Lock className="w-3 h-3 shrink-0" /> Bets Closed</> :
         saved ? '✓ Saved!' : `Save Pick • +${pts} pts`}
      </button>
    </div>
  );
};

// ── Desktop columns ───────────────────────────────────────────────────────────

const PLAYIN_ORDER = [
  { type: 'elimination', label: 'Elimination',  sublabel: 'Winner → vs 1 seed' },
  { type: '9v10',        label: '9 vs 10',      sublabel: 'Winner plays loser of 7v8' },
  { type: '7v8',         label: '7 vs 8',       sublabel: 'Winner → vs 2 seed' },
];

const SeedBadge = ({ team, seed }) => (
  <div className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-slate-800/80 border border-slate-700/60">
    {team?.logo_url
      ? <img src={team.logo_url} alt="" className="w-5 h-5" onError={e => e.target.style.display = 'none'} />
      : <div className="w-5 h-5 rounded-full bg-slate-700 flex items-center justify-center text-[9px] font-black text-slate-400">{seed}</div>
    }
    <span className="text-[10px] font-black text-slate-300">{team?.abbreviation || `#${seed} Seed`}</span>
    <span className="text-[9px] text-slate-500 font-bold">waiting</span>
  </div>
);

const PlayInCol = ({ label, games, picks, onTeamClick, onSave, saved, seed1Team, seed2Team, confirmed, predMap }) => {
  const slotH = (BH + 28) / PI_SLOTS;
  const seedBySlot = { elimination: seed1Team, '7v8': seed2Team };
  return (
    <div style={{ flexShrink: 0 }}>
      <p className="text-xs text-slate-500 uppercase font-bold mb-3 text-center tracking-wider">{label}</p>
      <div style={{ height: BH + 28, display: 'flex', flexDirection: 'column' }}>
        {PLAYIN_ORDER.map(({ type, label: gLabel, sublabel }) => {
          const game = games.find(g => g.game_type === type);
          // Effective pick: local state (real-time) OR DB prediction (page load)
          const dbPred  = game ? predMap?.[game.id] : null;
          const localPick = game ? picks[game.id] : null;
          const pick = localPick || (dbPred ? { teamId: +dbPred.predicted_winner_id } : null);
          // hasBet: use only confirmed local state (hydration populates it from DB on load).
          const hasBet = !!(game && confirmed?.[game.id]);
          const seedTeam = seedBySlot[type];
          const gameStartZ = game ? getPlayInStartZ(game) : null;
          return (
            <div key={type} style={{ height: slotH, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 3 }}>
              <p className="text-[10px] text-slate-400 font-black uppercase tracking-wide">{gLabel}</p>
              <p className="text-[9px] text-slate-600 font-bold uppercase tracking-wider">{sublabel}</p>
              {gameStartZ && game?.status !== 'completed' && <PlayInCountdown startZ={gameStartZ} />}
              {seedTeam && <SeedBadge team={seedTeam} seed={type === 'elimination' ? 1 : 2} />}
              <div style={{ position: 'relative', display: 'inline-flex', flexDirection: 'column', alignItems: 'center' }}>
                <PlayInCard game={game} pick={pick} onTeamClick={onTeamClick} hasBet={hasBet} />
                {game && pick?.teamId && (
                  <div style={{ position: 'absolute', top: CH + 6, left: '50%', transform: 'translateX(-50%)', zIndex: 30 }}>
                    <PlayInPicker game={game} pick={pick} onSave={onSave} saved={saved[game.id]} />
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

// Shown in R1 for seeds 1 & 2 — real team on top, play-in winner TBD on bottom
const SeedWaitingCard = ({ team }) => (
  <div style={{ height: CH }} className="w-44 border-2 border-slate-700/60 rounded-xl flex flex-col overflow-hidden bg-slate-900/80">
    {/* Top row: real seed */}
    <div className="flex-1 flex items-center gap-2 px-3 border-b border-slate-800 hover:bg-slate-800/40 transition-colors">
      <span className="text-xs text-orange-400 w-4 shrink-0 font-black">{team.seed}</span>
      <img src={team.logo_url} alt="" className="w-8 h-8 shrink-0" onError={e => e.target.style.display = 'none'} />
      <span className="text-sm font-black text-white">{team.abbreviation}</span>
    </div>
    {/* Bottom row: TBD play-in winner */}
    <div className="flex-1 flex items-center gap-2 px-3 hover:bg-slate-800/40 transition-colors">
      <span className="text-xs text-slate-600 w-4 shrink-0 font-black">?</span>
      <div className="w-8 h-8 shrink-0 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center">
        <span className="text-[9px] text-slate-500 font-black">TBD</span>
      </div>
      <span className="text-xs text-slate-500 font-bold italic">Play-In Winner</span>
    </div>
  </div>
);

// slot index → which seed team "owns" that slot (no series yet)
const SEED_SLOT = { 0: 1, 3: 2 }; // slot 0 = 1-seed, slot 3 = 2-seed

const R1Col = ({ label, slots, picks, onTeamClick, onGamesSelect, onLeaderSelect, onSave, saved, seedTeams, confirmed, onEdit, predMap }) => (
  <div style={{ flexShrink: 0 }}>
    <p className="text-xs text-slate-500 uppercase font-bold mb-3 text-center tracking-wider">{label}</p>
    <div style={{ height: BH + 28, display: 'flex', flexDirection: 'column' }}>
      {slots.map((s, i) => {
        const waitingTeam = !s && seedTeams?.[SEED_SLOT[i]];
        return (
          <div key={i} style={{ height: (BH + 28) / 4, display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'relative' }}>
            {s ? (() => {
              // DB prediction (always reflects saved DB state on page load)
              const dbPred = predMap?.[s.id];
              // Effective pick: local state takes priority (real-time edits),
              // fall back to DB prediction so the tree is populated on page load
              const effectivePick = picks[s.id] || (dbPred ? {
                teamId:    +dbPred.predicted_winner_id,   // coerce: API may return string
                games:     dbPred.predicted_games,
                scorer:    dbPred.leading_scorer    || '',
                rebounder: dbPred.leading_rebounder || '',
                assister:  dbPred.leading_assister  || '',
              } : null);
              // hasBet: use only confirmed local state (hydration populates it from DB on load).
              // Do NOT check dbPred here — handleEdit resets confirmed[s.id]=false so the
              // InlinePicker can show; if we also checked dbPred it would stay true forever.
              const hasBet = !!confirmed[s.id];
              return (
              <div style={{ position: 'relative', display: 'inline-flex', flexDirection: 'column', alignItems: 'center' }}>
                <MatchCard series={s} pick={effectivePick} onTeamClick={onTeamClick} hasBet={hasBet} />
                {effectivePick?.teamId && s.status === 'active' && (
                  <div style={{ position: 'absolute', top: CH + 6, left: '50%', transform: 'translateX(-50%)', zIndex: 30 }}>
                    {s.picks_locked ? (
                      <button disabled className="w-44 py-1.5 rounded-lg text-[10px] font-black bg-red-500/15 border border-red-500/25 text-red-400 cursor-not-allowed flex items-center justify-center gap-1.5 whitespace-nowrap">
                        <Lock className="w-3 h-3 shrink-0" /> Bets Locked
                      </button>
                    ) : hasBet ? (
                      <button
                        onClick={() => onEdit(s.id)}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 hover:border-orange-500/50 hover:text-orange-400 text-[10px] font-bold transition-all whitespace-nowrap"
                      >
                        ✏ Edit pick
                      </button>
                    ) : (
                      <InlinePicker seriesId={s.id} series={s} pick={effectivePick} onGamesSelect={onGamesSelect} onLeaderSelect={onLeaderSelect} onSave={onSave} saved={saved[s.id]} />
                    )}
                  </div>
                )}
              </div>
            );
            })() : waitingTeam ? (
              <SeedWaitingCard team={waitingTeam} />
            ) : (
              <TBDCard />
            )}
          </div>
        );
      })}
    </div>
  </div>
);

const SemisCol = ({ label }) => {
  const pt = (BH + 28) / 8 - CH / 2;
  return (
    <div style={{ flexShrink: 0 }}>
      <p className="text-xs text-slate-500 uppercase font-bold mb-3 text-center tracking-wider">{label}</p>
      <div style={{ height: BH + 28, paddingTop: Math.max(pt, 0), paddingBottom: Math.max(pt, 0), display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
        <TBDCard /><TBDCard />
      </div>
    </div>
  );
};

const CFCol = ({ label }) => (
  <div style={{ flexShrink: 0 }}>
    <p className="text-xs text-slate-500 uppercase font-bold mb-3 text-center tracking-wider">{label}</p>
    <div style={{ height: BH + 28, display: 'flex', alignItems: 'center' }}>
      <TBDCard />
    </div>
  </div>
);

// ── Mobile cards ──────────────────────────────────────────────────────────────

const MobilePlayInCard = ({ game, pick, onTeamClick, onSave, saved, communityStats, predData, highlighted, confirmed }) => {
  if (!game) return null;
  const { team1, team2 } = game;
  const p1 = pick?.teamId === team1?.id;
  const p2 = pick?.teamId === team2?.id;
  const underdogId = (team1?.seed ?? 0) > (team2?.seed ?? 0) ? team1?.id : team2?.id;
  const pickedIsUnderdog = (p1 && team1?.id === underdogId) || (p2 && team2?.id === underdogId);
  const pickedPts = pickedIsUnderdog ? PLAYIN_UNDERDOG_PTS : PLAYIN_PTS;
  // confirmed = user already saved a pick (from piConfirmed state in parent)
  // betChanged = user selected a DIFFERENT team than what they previously saved
  const savedTeamId = predData?.predicted_winner_id;
  const betChanged = confirmed && (pick?.teamId != null) && (pick.teamId !== savedTeamId);

  const teamBtn = (team, picked, onClick) => {
    const isUnderdog = team?.id === underdogId;
    const pts = isUnderdog ? PLAYIN_UNDERDOG_PTS : PLAYIN_PTS;
    return (
      <button onClick={onClick}
        className={`flex items-center gap-3 p-3 rounded-xl border-2 transition-all w-full ${
          picked && confirmed ? 'border-yellow-500/70 bg-yellow-500/10' :
          picked && isUnderdog ? 'border-amber-500 bg-amber-500/15' :
          picked ? 'border-orange-500 bg-orange-500/15' :
          isUnderdog ? 'border-amber-500/25 bg-amber-500/5 hover:border-amber-400/50' :
          'border-slate-700 bg-slate-900/60 hover:border-slate-600'
        }`}>
        <span className={`text-xs font-black w-5 ${picked && confirmed ? 'text-yellow-400' : picked && isUnderdog ? 'text-amber-400' : picked ? 'text-orange-400' : 'text-slate-500'}`}>{team?.seed}</span>
        <img src={team?.logo_url} alt="" className="w-9 h-9 shrink-0" onError={e => e.target.style.display = 'none'} />
        <p className={`font-black text-sm flex-1 text-left ${picked && confirmed ? 'text-yellow-400' : picked && isUnderdog ? 'text-amber-400' : picked ? 'text-orange-400' : 'text-white'}`}>{team?.name}</p>
        {picked && confirmed
          ? <span className="text-[8px] font-black px-1.5 py-0.5 rounded shrink-0 bg-yellow-500/20 border border-yellow-500/30 text-yellow-400">MY BET</span>
          : <span className={`text-[10px] font-black px-2 py-0.5 rounded border shrink-0 ${
              isUnderdog ? 'text-amber-400 bg-amber-500/10 border-amber-500/25' : 'text-slate-500 bg-slate-800 border-slate-700'
            }`}>+{pts}</span>
        }
        {picked && confirmed && <div className="w-5 h-5 rounded-full bg-yellow-500 flex items-center justify-center shrink-0"><span className="text-white text-[10px] font-black">✓</span></div>}
        {picked && !confirmed && <div className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 ${isUnderdog ? 'bg-amber-500' : 'bg-orange-500'}`}><span className="text-white text-[10px] font-black">✓</span></div>}
      </button>
    );
  };

  const startZ = getPlayInStartZ(game);
  const piSecs = usePlayInCountdown(startZ);
  const betsClosed = game.status === 'completed' || (piSecs !== null && piSecs <= 0);

  return (
    <div id={`playin-${game.id}`} className={`border rounded-2xl p-4 space-y-2 transition-all duration-500 ${
      highlighted
        ? 'bg-orange-500/8 border-orange-500/60 shadow-lg shadow-orange-500/20 ring-2 ring-orange-500/30'
        : confirmed && !betsClosed && game.status !== 'completed'
        ? 'bg-yellow-500/5 border-yellow-500/30 shadow-sm shadow-yellow-500/10'
        : 'bg-slate-900/60 border-slate-800'
    }`}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] text-slate-600 font-bold uppercase tracking-wider">Play-In</span>
        {game.status === 'completed' && predData
          ? predData.is_correct === 1
            ? <span className="text-[10px] font-bold text-green-400 flex items-center gap-1"><CheckCircle className="w-3 h-3" /> Correct</span>
            : predData.is_correct === 0
            ? <span className="text-[10px] font-bold text-red-400 flex items-center gap-1"><XCircle className="w-3 h-3" /> Wrong</span>
            : <span className="text-[10px] font-bold text-slate-500">Pending</span>
          : predData && !betsClosed
          ? <span className="text-[10px] font-bold text-orange-400">✓ Predicted</span>
          : !predData && !betsClosed
          ? <span className="text-[10px] font-bold text-blue-400">Tap to predict</span>
          : <span className="text-[10px] font-bold text-slate-500">Fav <span className="text-slate-400 font-black">+{PLAYIN_PTS}</span> · Dog <span className="text-amber-400 font-black">+{PLAYIN_UNDERDOG_PTS}</span></span>
        }
      </div>
      {game.status !== 'completed' && startZ && (
        <div className="flex items-center justify-between px-1">
          <PlayInTimeLabel startZ={startZ} />
          <PlayInCountdown startZ={startZ} />
        </div>
      )}
      {teamBtn(team1, p1, betsClosed ? undefined : () => onTeamClick(game, team1?.id))}
      <div className="text-center text-xs text-slate-600 font-bold">VS</div>
      {teamBtn(team2, p2, betsClosed ? undefined : () => onTeamClick(game, team2?.id))}
      <button
        onClick={betsClosed ? undefined : () => onSave(game.id)}
        disabled={betsClosed || !(p1 || p2)}
        className={`w-full py-3 rounded-xl font-black text-sm transition-all mt-1 flex items-center justify-center gap-2 ${
          betsClosed        ? 'bg-red-500/15 border border-red-500/25 text-red-400 cursor-not-allowed' :
          saved             ? 'bg-green-500 text-white' :
          confirmed && !betChanged ? 'bg-green-500/15 border border-green-500/30 text-green-400' :
          betChanged        ? (pickedIsUnderdog ? 'bg-gradient-to-r from-amber-500 to-orange-500 text-white' : 'bg-gradient-to-r from-orange-500 to-red-500 text-white') :
          !(p1 || p2)       ? 'bg-slate-800 border border-slate-700 text-slate-600 cursor-not-allowed' :
          pickedIsUnderdog  ? 'bg-gradient-to-r from-amber-500 to-orange-500 text-white shadow-lg shadow-amber-500/25' :
                              'bg-gradient-to-r from-orange-500 to-red-500 text-white'
        }`}>
        {betsClosed         ? <><Lock className="w-4 h-4 shrink-0" /> Bets Closed</> :
         saved              ? '✓ Saved!' :
         confirmed && !betChanged ? <><CheckCircle className="w-4 h-4 shrink-0" /> Bet Saved</> :
         betChanged         ? <><Edit2 className="w-4 h-4 shrink-0" /> Update Pick</> :
         !(p1 || p2)        ? 'Pick a team first' :
         `Save Pick • +${pickedPts} pts`}
      </button>

      {/* ── Your Bet summary ── */}
      {predData && (
        <div className={`rounded-xl p-3 border ${
          game.status === 'completed' && predData.is_correct === 1 ? 'bg-green-500/10 border-green-500/30' :
          game.status === 'completed' && predData.is_correct === 0 ? 'bg-red-500/10 border-red-500/30' :
          game.status === 'completed' ? 'bg-slate-800/40 border-slate-700/30' :
          betsClosed ? 'bg-amber-500/5 border-amber-500/20' :
          'bg-orange-500/5 border-orange-500/15'
        }`}>
          <div className="flex items-center gap-3">
            {game.status === 'completed' && predData.is_correct === 1 && <CheckCircle className="w-5 h-5 text-green-400 shrink-0" />}
            {game.status === 'completed' && predData.is_correct === 0 && <XCircle className="w-5 h-5 text-red-400 shrink-0" />}
            {game.status !== 'completed' && (
              <div className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 text-white text-[9px] font-black ${betsClosed ? 'bg-amber-500/60' : 'bg-orange-500'}`}>✓</div>
            )}
            <div className="flex-1 min-w-0">
              <p className={`text-[9px] font-black uppercase tracking-wider mb-1 ${
                game.status === 'completed' && predData.is_correct === 1 ? 'text-green-400' :
                game.status === 'completed' && predData.is_correct === 0 ? 'text-red-400' :
                betsClosed ? 'text-amber-400/70' : 'text-orange-400/70'
              }`}>
                {game.status === 'completed'
                  ? predData.is_correct === 1 ? 'Correct Pick!'
                  : predData.is_correct === 0 ? 'Wrong Pick'
                  : 'Result Pending'
                  : betsClosed ? '🔒 Your Locked Bet' : 'Your Bet'}
              </p>
              <div className="flex items-center gap-1.5">
                <img src={predData.predicted_winner?.logo_url} alt=""
                  className="w-6 h-6 shrink-0" onError={e => e.target.style.display='none'} />
                <span className="text-sm font-black text-white">{predData.predicted_winner?.abbreviation}</span>
              </div>
            </div>
            {predData.points_earned > 0 && (
              <div className="text-right shrink-0">
                <p className="text-xl font-black text-green-400 leading-none">+{predData.points_earned}</p>
                <p className="text-[9px] text-green-400/50 font-bold">pts</p>
              </div>
            )}
          </div>
        </div>
      )}

      <CommunityInsights
        gameId={game.id}
        homeTeam={team1}
        awayTeam={team2}
        initialStats={communityStats ?? null}
        status={game.status}
        startZ={startZ}
      />
    </div>
  );
};

const MobileMatchCard = ({ series, pick, onTeamClick, onGamesSelect, onLeaderSelect, onSave, saved, communityStats, confirmed, onEdit, predData, highlighted }) => {
  const { home_team: h, away_team: a } = series;
  const hp = pick?.teamId === h.id;
  const ap = pick?.teamId === a.id;
  const picked = hp ? h : ap ? a : null;
  const isCompleted = series.status === 'completed';
  const isLocked = series.status === 'locked' || series.picks_locked;
  const hWon = series.winner_team_id === h.id;
  const aWon = series.winner_team_id === a.id;

  const homeSeed   = series.home_seed   ?? h.seed ?? null;
  const awaySeed   = series.away_seed   ?? a.seed ?? null;
  const underdogSeed2 = (homeSeed != null && awaySeed != null) ? Math.max(homeSeed, awaySeed) : null;
  const hIsUnderdog2 = underdogSeed2 != null && homeSeed === underdogSeed2;
  const aIsUnderdog2 = underdogSeed2 != null && awaySeed === underdogSeed2;

  const teamBtn = (team, isPicked, isWon, isTeamUnderdog, onClick) => (
    <button onClick={isCompleted || isLocked ? undefined : onClick}
      className={`flex items-center gap-3 p-4 rounded-xl border-2 transition-all w-full ${
        isWon ? 'border-green-500 bg-green-500/15' :
        isPicked && !isCompleted && confirmed ? 'border-yellow-500/70 bg-yellow-500/10' :
        isPicked && !isCompleted && isTeamUnderdog ? 'border-amber-500 bg-amber-500/15 underdog-glow' :
        isPicked && !isCompleted ? 'border-orange-500 bg-orange-500/15' :
        isCompleted && !isWon ? 'border-slate-700 bg-slate-900/60 opacity-40' :
        !isWon && !isPicked && !isCompleted && isTeamUnderdog ? 'border-amber-500/20 bg-amber-500/5 hover:border-amber-400/40' :
        'border-slate-700 bg-slate-900/60 hover:border-slate-600'
      }`}>
      <span className={`text-xs font-black w-5 shrink-0 ${isWon ? 'text-green-400' : isPicked && !isCompleted && confirmed ? 'text-yellow-400' : isPicked && !isCompleted && isTeamUnderdog ? 'text-amber-400' : isPicked && !isCompleted ? 'text-orange-400' : 'text-slate-500'}`}>{team.seed}</span>
      <img src={team.logo_url} alt="" className="w-10 h-10 shrink-0" onError={e => e.target.style.display = 'none'} />
      <div className="text-left flex-1 min-w-0">
        <p className={`font-black text-base leading-tight truncate ${isWon ? 'text-green-400' : isPicked && !isCompleted && confirmed ? 'text-yellow-400' : isPicked && !isCompleted && isTeamUnderdog ? 'text-amber-400' : isPicked && !isCompleted ? 'text-orange-400' : 'text-white'}`}>{team.name}</p>
        <p className="text-xs text-slate-500">{isWon && series.actual_games ? `Won in ${series.actual_games}` : isTeamUnderdog && !isCompleted ? '🔥 Underdog — higher reward' : `Seed #${team.seed}`}</p>
      </div>
      {!isCompleted && !isLocked && !isPicked && (() => {
        const previewPts = team.id === h.id ? hMaxPts : aMaxPts;
        return (
          <span className={`text-[9px] font-black shrink-0 px-1.5 py-0.5 rounded border ${
            isTeamUnderdog ? 'text-amber-400 bg-amber-500/10 border-amber-500/25' : 'text-slate-500 bg-slate-800 border-slate-700'
          }`}>{previewPts != null ? `+${previewPts}` : isTeamUnderdog ? 'RISKY' : 'SAFE'}</span>
        );
      })()}
      {isPicked && !isCompleted && confirmed && (
        <span className="text-[8px] font-black shrink-0 px-1.5 py-0.5 rounded bg-yellow-500/20 border border-yellow-500/30 text-yellow-400">MY BET</span>
      )}
      {isWon && <div className="w-6 h-6 rounded-full bg-green-500 flex items-center justify-center shrink-0"><span className="text-white text-xs font-black">✓</span></div>}
      {isPicked && !isCompleted && !isWon && !confirmed && <div className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 ${isTeamUnderdog ? 'bg-amber-500' : 'bg-orange-500'}`}><span className="text-white text-xs font-black">✓</span></div>}
      {isPicked && !isCompleted && !isWon && confirmed && <div className="w-6 h-6 rounded-full bg-yellow-500 flex items-center justify-center shrink-0"><span className="text-white text-xs font-black">✓</span></div>}
    </button>
  );

  const roundMult  = getRoundMult(series.round);
  const pickedSeed = hp ? homeSeed : ap ? awaySeed : null;
  const underdogMult = getUnderdogMult(series.round, homeSeed, awaySeed, pickedSeed);
  const { winnerPts, gamesPts, totalPts } = calcSeriesPts(series.round, homeSeed, awaySeed, pickedSeed);
  const isHUnderdog = hp && getUnderdogMult(series.round, homeSeed, awaySeed, homeSeed) > 1.0;
  const isAUnderdog = ap && getUnderdogMult(series.round, homeSeed, awaySeed, awaySeed) > 1.0;
  // Pre-compute per-team max pts for pts preview badges
  const hMaxPts = homeSeed != null ? calcSeriesPts(series.round, homeSeed, awaySeed, homeSeed).totalPts : null;
  const aMaxPts = awaySeed != null ? calcSeriesPts(series.round, homeSeed, awaySeed, awaySeed).totalPts : null;
  const hIsUnderdogTeam = hIsUnderdog2;
  const aIsUnderdogTeam = aIsUnderdog2;

  const { data: seriesPlayers = [] } = useQuery({
    queryKey: ['seriesPlayers', series.id],
    queryFn:  () => api.getSeriesPlayers(series.id),
    staleTime: 30 * 60 * 1000,
    enabled: !!(picked && !isCompleted && !isLocked),
  });

  return (
    <div id={`series-${series.id}`} className={`border rounded-2xl p-4 space-y-3 transition-all duration-500 ${
      highlighted
        ? 'bg-orange-500/8 border-orange-500/60 shadow-lg shadow-orange-500/20 ring-2 ring-orange-500/30'
        : confirmed && !isCompleted
        ? 'bg-yellow-500/5 border-yellow-500/30 shadow-sm shadow-yellow-500/10'
        : 'bg-slate-900/60 border-slate-800'
    }`}>
      <div className="flex items-center justify-between">
        <div>
          <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">{series.round}</span>
          {series.status === 'active' && (() => {
            const favPts    = Math.min(hMaxPts ?? 999, aMaxPts ?? 999);
            const udPts     = Math.max(hMaxPts ?? 0,   aMaxPts ?? 0);
            const showRange = udPts > favPts && favPts > 0;
            const hasScore  = (series.home_wins > 0 || series.away_wins > 0);
            return (
              <div className="flex items-center gap-1.5 flex-wrap">
                {hasScore && (
                  <span className="px-1.5 py-0.5 rounded bg-blue-500/10 border border-blue-500/25 text-blue-400 text-[10px] font-black tabular-nums">
                    {series.home_wins}–{series.away_wins}
                  </span>
                )}
                <span className="text-[10px] font-black text-slate-500">
                  {roundMult > 1 && <span>×{roundMult} · </span>}
                  Up to{' '}
                  {showRange ? (
                    <><span className="text-green-400">{favPts}</span>–<span className="text-amber-400">{udPts} pts</span></>
                  ) : (
                    <span className="text-green-400">{favPts} pts</span>
                  )}
                </span>
              </div>
            );
          })()}
        </div>
        {series.status === 'completed' && (
          predData
            ? predData.is_correct === 1
              ? <span className="text-xs font-bold text-green-400 flex items-center gap-1"><CheckCircle className="w-3.5 h-3.5" /> Correct</span>
              : predData.is_correct === 0
              ? <span className="text-xs font-bold text-red-400 flex items-center gap-1"><XCircle className="w-3.5 h-3.5" /> Wrong</span>
              : <span className="text-xs font-bold text-slate-400">✓ Complete</span>
            : <span className="text-xs font-bold text-slate-400">✓ Complete</span>
        )}
        {series.status === 'locked' && <span className="text-xs font-bold text-yellow-400 flex items-center gap-1">🔒 Locked</span>}
        {series.status === 'active' && (
          predData
            ? <span className="text-xs font-bold text-orange-400 flex items-center gap-1">✓ Predicted</span>
            : <span className="text-xs font-bold text-blue-400">Tap to predict</span>
        )}
      </div>
      {/* Game 1 countdown — First Round series (uses backend field or frontend fallback) */}
      {(() => {
        const g1z = getSeriesGame1Z(series);
        if (!g1z) return null;
        return <SeriesGame1Countdown game1StartZ={g1z} picksLocked={series.picks_locked} />;
      })()}
      <div className="space-y-2">
        {teamBtn(h, hp, hWon, hIsUnderdog2, () => onTeamClick(series, h.id))}
        <div className="text-center text-xs text-slate-600 font-bold">VS</div>
        {teamBtn(a, ap, aWon, aIsUnderdog2, () => onTeamClick(series, a.id))}
      </div>
      {/* Underdog bonus callout */}
      {(isHUnderdog || isAUnderdog) && !isCompleted && !isLocked && (
        <div className="bonus-pop flex items-center justify-between gap-2 px-3 py-1.5 rounded-xl bg-amber-500/10 border border-amber-500/20">
          <div className="flex items-center gap-1.5">
            <span className="text-amber-400 text-xs font-black">🔥 Underdog Bonus</span>
            <span className="text-[10px] font-black text-amber-400 bg-amber-500/20 border border-amber-500/30 rounded px-1.5 py-0.5">×{underdogMult}</span>
          </div>
          <span className="text-amber-400 text-xs font-black">{totalPts} pts max</span>
        </div>
      )}
      {/* Provisional / final series leaders */}
      {(series.leading_scorer || series.leading_rebounder || series.leading_assister) && (
        <div className={`px-3 py-2 rounded-xl border text-xs ${
          series.status === 'active'
            ? 'bg-cyan-500/5 border-cyan-500/15'
            : 'bg-slate-800/40 border-slate-700/30'
        }`}>
          <p className={`text-[9px] font-black uppercase tracking-widest mb-1.5 ${
            series.status === 'active' ? 'text-cyan-400/60' : 'text-slate-500'
          }`}>
            {series.status === 'active' ? '📊 Provisional Leaders' : '📊 Series Leaders'}
          </p>
          <div className="grid grid-cols-3 gap-1">
            {[
              { label: 'PTS', val: series.leading_scorer },
              { label: 'REB', val: series.leading_rebounder },
              { label: 'AST', val: series.leading_assister },
            ].map(l => l.val && (
              <div key={l.label} className="text-center">
                <p className="text-[8px] text-slate-600 font-bold">{l.label}</p>
                <p className="text-[10px] text-slate-300 font-bold truncate">{l.val.split(' ').slice(-1)[0]}</p>
              </div>
            ))}
          </div>
        </div>
      )}
      {/* Bets Locked / Edit — only shown when there's no predData panel (predData panel embeds these) */}
      {picked && !isCompleted && isLocked && !predData && (
        <button disabled className="w-full py-2.5 rounded-xl font-black text-sm bg-red-500/15 border border-red-500/25 text-red-400 cursor-not-allowed flex items-center justify-center gap-2">
          <Lock className="w-4 h-4 shrink-0" /> Bets Locked
        </button>
      )}
      {picked && !isCompleted && !isLocked && confirmed && !predData && (
        <button
          onClick={onEdit}
          className="w-full py-2.5 rounded-xl font-bold text-sm border border-slate-700 bg-slate-800/60 text-slate-300 hover:border-orange-500/50 hover:text-orange-400 transition-all flex items-center justify-center gap-2"
        >
          ✏ Edit prediction
        </button>
      )}
      {picked && !isCompleted && !isLocked && !confirmed && (
        <div className="pt-2 border-t border-slate-800 space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-xs text-slate-400 uppercase font-bold tracking-wider">Series Length</p>
            <p className="text-[10px] text-slate-500 font-bold">+{winnerPts} winner / +{gamesPts} games</p>
          </div>
          <div className="grid grid-cols-4 gap-2">
            {[4, 5, 6, 7].map(g => (
              <button key={g} onClick={() => onGamesSelect(series.id, g)}
                className={`py-3 rounded-xl font-black text-sm transition-all border-2 ${
                  pick?.games === g
                    ? (isHUnderdog || isAUnderdog ? 'border-amber-500 bg-amber-500/20 text-amber-400' : 'border-orange-500 bg-orange-500/20 text-white')
                    : 'border-slate-700 bg-slate-800/60 text-slate-400'
                }`}>{g}</button>
            ))}
          </div>
          {/* Series leader predictions */}
          <div className="space-y-2 pt-1 border-t border-slate-800/60">
            <p className="text-[10px] text-slate-500 uppercase font-bold tracking-widest">Series Leaders</p>
            <PlayerDropdown label="Leading Scorer" value={pick?.scorer || ''}
              onChange={v => onLeaderSelect(series.id, 'scorer', v)}
              players={seriesPlayers} statKey="ppg" />
            <PlayerDropdown label="Leading Rebounder" value={pick?.rebounder || ''}
              onChange={v => onLeaderSelect(series.id, 'rebounder', v)}
              players={seriesPlayers} statKey="rpg" />
            <PlayerDropdown label="Leading Assister" value={pick?.assister || ''}
              onChange={v => onLeaderSelect(series.id, 'assister', v)}
              players={seriesPlayers} statKey="apg" />
          </div>

          <button onClick={() => onSave(series.id)} disabled={!pick?.games}
            className={`w-full py-3.5 rounded-xl font-black text-sm transition-all ${
              saved ? 'bg-green-500 text-white' :
              !pick?.games ? 'bg-slate-800 text-slate-600 cursor-not-allowed' :
              (isHUnderdog || isAUnderdog) ? 'bg-gradient-to-r from-amber-500 to-orange-500 text-white shadow-lg shadow-amber-500/25' :
              'bg-gradient-to-r from-orange-500 to-red-500 text-white shadow-lg shadow-orange-500/25'
            }`}>
            {saved ? '✓ Saved!' : `Save Prediction • ${totalPts} pts max`}
          </button>
        </div>
      )}
      {/* ── Your Bet summary ── shown when user has a confirmed prediction.
           Uses predData (from API) when available, falls back to local pick
           state immediately after saving (before the query refetches). ── */}
      {(predData || (confirmed && picked)) && (() => {
        // Authoritative data (from DB) takes priority; local state is the fallback
        const dispWinner  = predData?.predicted_winner  || picked;
        const dispGames   = predData?.predicted_games   ?? pick?.games;
        const dispScorer  = predData?.leading_scorer    || pick?.scorer;
        const dispReb     = predData?.leading_rebounder || pick?.rebounder;
        const dispAst     = predData?.leading_assister  || pick?.assister;
        const isCorrect   = predData?.is_correct ?? null;
        const ptsEarned   = predData?.points_earned ?? 0;
        return (
          <div className={`rounded-xl p-3 border ${
            isCompleted && isCorrect === 1 ? 'bg-green-500/10 border-green-500/30' :
            isCompleted && isCorrect === 0 ? 'bg-red-500/10 border-red-500/30' :
            isCompleted ? 'bg-slate-800/40 border-slate-700/30' :
            isLocked    ? 'bg-amber-500/5 border-amber-500/20' :
                          'bg-orange-500/5 border-orange-500/15'
          }`}>
            <div className="flex items-center gap-3">
              {isCompleted && isCorrect === 1 && <CheckCircle className="w-5 h-5 text-green-400 shrink-0" />}
              {isCompleted && isCorrect === 0 && <XCircle className="w-5 h-5 text-red-400 shrink-0" />}
              {!isCompleted && (
                <div className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 text-white text-[9px] font-black ${isLocked ? 'bg-amber-500/60' : 'bg-orange-500'}`}>✓</div>
              )}
              <div className="flex-1 min-w-0">
                <p className={`text-[9px] font-black uppercase tracking-wider mb-1 ${
                  isCompleted && isCorrect === 1 ? 'text-green-400' :
                  isCompleted && isCorrect === 0 ? 'text-red-400' :
                  isLocked ? 'text-amber-400/70' : 'text-orange-400/70'
                }`}>
                  {isCompleted
                    ? isCorrect === 1 ? 'Correct Prediction!'
                    : isCorrect === 0 ? 'Wrong Prediction'
                    : 'Result Pending'
                    : isLocked ? '🔒 Your Locked Bet' : 'Your Bet'}
                </p>
                <div className="flex items-center gap-2 flex-wrap">
                  <div className="flex items-center gap-1.5">
                    <img src={dispWinner?.logo_url} alt=""
                      className="w-5 h-5 shrink-0" onError={e => e.target.style.display='none'} />
                    <span className="text-sm font-black text-white">{dispWinner?.name || dispWinner?.abbreviation}</span>
                  </div>
                  {dispGames && (
                    <span className="text-[10px] text-slate-500 font-bold">in {dispGames} games</span>
                  )}
                </div>
                {/* Leaders */}
                {(dispScorer || dispReb || dispAst) && (
                  <div className="flex gap-3 mt-1.5 flex-wrap">
                    {dispScorer && <span className="text-[9px] text-slate-500">PTS: <span className="text-slate-400 font-bold">{dispScorer.split(' ').slice(-1)[0]}</span></span>}
                    {dispReb    && <span className="text-[9px] text-slate-500">REB: <span className="text-slate-400 font-bold">{dispReb.split(' ').slice(-1)[0]}</span></span>}
                    {dispAst    && <span className="text-[9px] text-slate-500">AST: <span className="text-slate-400 font-bold">{dispAst.split(' ').slice(-1)[0]}</span></span>}
                  </div>
                )}
              </div>
              {ptsEarned > 0 && (
                <div className="text-right shrink-0">
                  <p className="text-xl font-black text-green-400 leading-none">+{ptsEarned}</p>
                  <p className="text-[9px] text-green-400/50 font-bold">pts</p>
                </div>
              )}
            </div>
            {/* Edit button — only for active/unlocked games */}
            {!isCompleted && !isLocked && (
              <button
                onClick={onEdit}
                className="w-full mt-2 pt-2 border-t border-slate-800/50 flex items-center justify-center gap-1.5 text-[10px] text-slate-500 hover:text-orange-400 transition-colors font-bold"
              >
                <Edit2 className="w-3 h-3" /> Edit prediction
              </button>
            )}
          </div>
        );
      })()}

      <CommunityInsights
        seriesId={series.id}
        homeTeam={h}
        awayTeam={a}
        initialStats={communityStats ?? null}
        status={series.status}
        startZ={getSeriesGame1Z(series)}
      />
    </div>
  );
};

// ── Main Page ─────────────────────────────────────────────────────────────────

const BracketPage = ({ currentUser, onNavigate, scrollTo }) => {
  const qc = useQueryClient();
  const [picks, setPicks]             = useState({});
  const [saved, setSaved]             = useState({});
  const [confirmed, setConfirmed]     = useState({});
  const [piPicks, setPiPicks]         = useState({});
  const [piSaved, setPiSaved]         = useState({});
  const [piConfirmed, setPiConfirmed] = useState({});
  const [showFull, setShowFull]       = useState(() => {
    try { return localStorage.getItem('bracketShowFull') === 'true'; } catch { return false; }
  });
  const [saveError, setSaveError]     = useState('');
  // Deep-link highlight — set when navigating from a notification
  const [highlightedId, setHighlightedId] = useState(null);

  // ── Deep-link scroll — when navigating from a notification, scroll to and
  //    briefly highlight the specific series or play-in card.  Retries every
  //    200ms for up to 2s so the element is guaranteed to exist in the DOM.
  useEffect(() => {
    if (!scrollTo) return;
    const key = `${scrollTo.type}-${scrollTo.id}`;
    let attempts = 0;
    const tryScroll = () => {
      attempts++;
      const el = document.getElementById(key);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        setHighlightedId(key);
        setTimeout(() => setHighlightedId(null), 2500);
      } else if (attempts < 10) {
        setTimeout(tryScroll, 200);
      }
    };
    const t = setTimeout(tryScroll, 300);
    return () => clearTimeout(t);
  }, [scrollTo?.type, scrollTo?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Cached data queries ──────────────────────────────────────────────────────
  const { data: series = [],    isLoading: l1, isError: e1, refetch: r1 } = useQuery({ queryKey: ['series', '2026'],    queryFn: () => api.getSeries('2026'),      staleTime: 60 * 1000, refetchOnWindowFocus: true, refetchInterval: 3 * 60 * 1000 });
  const { data: playInGames = [], isLoading: l2, isError: e2, refetch: r2 } = useQuery({ queryKey: ['playin', '2026'],  queryFn: () => api.getPlayInGames('2026'), staleTime: 60 * 1000, refetchOnWindowFocus: true, refetchInterval: 3 * 60 * 1000 });
  const { data: allTeams = [],  isLoading: l3, isError: e3, refetch: r3 } = useQuery({ queryKey: ['teams'],             queryFn: () => api.getTeams() });
  const { data: standingsRaw,   isLoading: l4, isError: e4, refetch: r4 } = useQuery({ queryKey: ['standings'],         queryFn: () => api.getStandings(),         staleTime: 2 * 60 * 1000, refetchInterval: 5 * 60 * 1000 });
  const { data: globalStats }                   = useQuery({ queryKey: ['globalStats'],         queryFn: () => api.getGlobalStats('2026'), staleTime: 2 * 60 * 1000, refetchInterval: 3 * 60 * 1000 });

  // Load the current user's saved predictions so picks are pre-populated on page load
  const { data: myPredictions } = useQuery({
    queryKey: ['myPredictions', currentUser?.user_id],
    // Pass viewer_id = own user_id so the backend returns ALL of this user's
    // predictions including ones for series that haven't started yet.
    // Without viewer_id the backend sets show_all=false and hides unlocked picks.
    queryFn:  () => api.getMyPredictions(currentUser.user_id, '2026', currentUser.user_id),
    staleTime: 30 * 1000,
    enabled:  !!currentUser,
  });

  // One-shot hydration: populate local pick/confirmed state from API data on first load.
  // Using a ref ensures we don't reset state mid-edit when myPredictions re-fetches.
  const didHydrate = useRef(false);
  useEffect(() => {
    if (!myPredictions || didHydrate.current) return;
    didHydrate.current = true;

    const newPicks = {};
    const newConfirmed = {};
    (myPredictions.playoff_predictions || []).forEach(pred => {
      newPicks[pred.series_id] = {
        teamId:    +pred.predicted_winner_id,   // coerce: API returns string, team IDs are numbers
        games:     pred.predicted_games,
        scorer:    pred.leading_scorer    || '',
        rebounder: pred.leading_rebounder || '',
        assister:  pred.leading_assister  || '',
      };
      newConfirmed[pred.series_id] = true;
    });
    setPicks(newPicks);
    setConfirmed(newConfirmed);

    const newPiPicks = {};
    const newPiConfirmed = {};
    (myPredictions.playin_predictions || []).forEach(pred => {
      newPiPicks[pred.game_id]     = { teamId: +pred.predicted_winner_id };  // coerce
      newPiConfirmed[pred.game_id] = true;
    });
    setPiPicks(newPiPicks);
    setPiConfirmed(newPiConfirmed);
  }, [myPredictions]);

  // Prediction detail maps — keyed by series_id / game_id — used for "Your Bet" panels
  const myPredMap = useMemo(() => {
    const map = {};
    (myPredictions?.playoff_predictions || []).forEach(pred => { map[pred.series_id] = pred; });
    return map;
  }, [myPredictions]);

  const myPiPredMap = useMemo(() => {
    const map = {};
    (myPredictions?.playin_predictions || []).forEach(pred => { map[pred.game_id] = pred; });
    return map;
  }, [myPredictions]);

  const standings = standingsRaw || { eastern: [], western: [] };
  const loading   = l1 || l2 || l3 || l4;
  const hasError  = e1 || e2 || e3 || e4;
  const refetchAll = () => { r1(); r2(); r3(); r4(); };

  const communityMap = useMemo(() => {
    const map = {};
    (globalStats?.series || []).forEach(entry => {
      map[entry.series_id] = { total_votes: entry.total_votes, home_pct: entry.home_pct, away_pct: entry.away_pct };
    });
    return map;
  }, [globalStats]);

  const toggleShowFull = () => {
    setShowFull(v => {
      const next = !v;
      try { localStorage.setItem('bracketShowFull', String(next)); } catch {}
      return next;
    });
  };

  const { westSlots, eastSlots, westSeries, eastSeries, westPI, eastPI, westSeed1, westSeed2, eastSeed1, eastSeed2, westSeedTeams, eastSeedTeams } = useMemo(() => {
    const minSeed = s => Math.min(
      s.home_seed ?? s.home_team?.seed ?? 99,
      s.away_seed ?? s.away_team?.seed ?? 99
    );
    const seedTeam = (s, n) => {
      if (!s) return null;
      if ((s.home_seed ?? s.home_team?.seed) === n) return s.home_team;
      if ((s.away_seed ?? s.away_team?.seed) === n) return s.away_team;
      return null;
    };
    const west = series.filter(s => s.conference === 'Western');
    const east = series.filter(s => s.conference === 'Eastern');
    const order = [1, 4, 3, 2];
    const wSlots = order.map(seed => west.find(s => minSeed(s) === seed) || null);
    const eSlots = order.map(seed => east.find(s => minSeed(s) === seed) || null);

    // Build seed→team maps from standings (conf_rank is the seed; conference uses 'West'/'East')
    // standings.western has conf_rank, team_id; standings.eastern similarly
    const buildSeedMap = (standingsArr) => {
      const map = {};
      (standingsArr || []).forEach(st => {
        const team = allTeams.find(t => t.id === st.team_id);
        if (team) map[st.conf_rank] = { ...team, seed: st.conf_rank };
      });
      return map;
    };
    const wSeedMap = buildSeedMap(standings.western);
    const eSeedMap = buildSeedMap(standings.eastern);

    const ws1 = seedTeam(wSlots[0], 1) || wSeedMap[1] || null;
    const ws2 = seedTeam(wSlots[3], 2) || wSeedMap[2] || null;
    const es1 = seedTeam(eSlots[0], 1) || eSeedMap[1] || null;
    const es2 = seedTeam(eSlots[3], 2) || eSeedMap[2] || null;

    return {
      westSlots: wSlots,
      eastSlots: eSlots,
      westSeries: west,
      eastSeries: east,
      westPI: playInGames.filter(g => g.conference === 'Western'),
      eastPI: playInGames.filter(g => g.conference === 'Eastern'),
      westSeed1: ws1, westSeed2: ws2,
      eastSeed1: es1, eastSeed2: es2,
      westSeedTeams: { 1: ws1, 2: ws2 },
      eastSeedTeams: { 1: es1, 2: es2 },
    };
  }, [series, playInGames, allTeams, standings]);

  // Playoff handlers
  const handleTeamClick = (seriesObj, teamId) => {
    if (!currentUser) return;
    setPicks(p => ({ ...p, [seriesObj.id]: { ...p[seriesObj.id], teamId } }));
  };
  const handleGamesSelect = (seriesId, games) => {
    setPicks(p => ({ ...p, [seriesId]: { ...p[seriesId], games } }));
  };
  const handleLeaderSelect = (seriesId, field, value) => {
    setPicks(p => ({ ...p, [seriesId]: { ...p[seriesId], [field]: value } }));
  };
  const handleSave = async (seriesId) => {
    if (!currentUser) return;
    const pick = picks[seriesId];
    if (!pick?.teamId || !pick?.games) return;
    // Optimistic: show saved instantly
    setSaved(p => ({ ...p, [seriesId]: true }));
    try {
      await api.makePrediction(
        currentUser.user_id, seriesId, pick.teamId, pick.games,
        { scorer: pick.scorer, rebounder: pick.rebounder, assister: pick.assister }
      );
      setConfirmed(p => ({ ...p, [seriesId]: true }));
      setTimeout(() => setSaved(p => ({ ...p, [seriesId]: false })), 2000);
      qc.invalidateQueries({ queryKey: ['myPredictions', currentUser.user_id] });
      qc.invalidateQueries({ queryKey: ['notifications', currentUser.user_id] });
      qc.invalidateQueries({ queryKey: ['globalStats'] });
      qc.invalidateQueries({ queryKey: ['leaderboard'] });
    } catch (err) {
      setSaved(p => ({ ...p, [seriesId]: false })); // revert
      setSaveError(err.response?.data?.detail || 'Failed to save prediction. Try again.');
    }
  };
  const handleEdit = (seriesId) => setConfirmed(p => ({ ...p, [seriesId]: false }));

  // Play-In handlers
  const handlePITeamClick = (game, teamId) => {
    if (!currentUser) return;
    setPiPicks(p => ({ ...p, [game.id]: { ...p[game.id], teamId } }));
  };
  const handlePISave = async (gameId) => {
    if (!currentUser) return;
    const pick = piPicks[gameId];
    if (!pick?.teamId) return;
    // Optimistic
    setPiSaved(p => ({ ...p, [gameId]: true }));
    try {
      await api.makePlayInPrediction(currentUser.user_id, gameId, pick.teamId);
      setPiConfirmed(p => ({ ...p, [gameId]: true }));
      setTimeout(() => setPiSaved(p => ({ ...p, [gameId]: false })), 2000);
      qc.invalidateQueries({ queryKey: ['myPredictions', currentUser.user_id] });
      qc.invalidateQueries({ queryKey: ['notifications', currentUser.user_id] });
      qc.invalidateQueries({ queryKey: ['globalStats'] });
      qc.invalidateQueries({ queryKey: ['leaderboard'] });
    } catch (err) {
      setPiSaved(p => ({ ...p, [gameId]: false })); // revert
      setSaveError(err.response?.data?.detail || 'Failed to save prediction. Try again.');
    }
  };

  if (!currentUser) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-16 text-center">
        <Trophy className="w-16 h-16 text-orange-400 mx-auto mb-4 opacity-60" />
        <h2 className="text-3xl font-black text-white mb-3">Login to Make Picks</h2>
        <p className="text-slate-400">Sign in to predict the 2026 NBA Playoffs</p>
      </div>
    );
  }

  if (hasError) {
    return (
      <div className="flex flex-col items-center justify-center py-24 gap-4">
        <p className="text-slate-400 text-lg">Failed to load bracket data.</p>
        <button
          onClick={refetchAll}
          className="px-6 py-2.5 bg-orange-500 hover:bg-orange-600 text-white font-bold rounded-xl transition-colors">
          Try Again
        </button>
      </div>
    );
  }

  if (loading) {
    const SkeletonCard = () => (
      <div className="bg-slate-900/50 border border-slate-800 rounded-xl overflow-hidden animate-pulse shrink-0 w-44" style={{ height: CH }}>
        <div className="h-1/2 flex items-center gap-3 px-4 border-b border-slate-800/60">
          <div className="w-7 h-7 rounded-full bg-slate-800 shrink-0" />
          <div className="h-2.5 flex-1 bg-slate-800 rounded" />
        </div>
        <div className="h-1/2 flex items-center gap-3 px-4">
          <div className="w-7 h-7 rounded-full bg-slate-800 shrink-0" />
          <div className="h-2.5 flex-1 bg-slate-800 rounded" />
        </div>
      </div>
    );
    return (
      <div className="px-4 py-8">
        {/* Header skeleton */}
        <div className="flex items-center gap-3 mb-6 justify-center">
          <div className="w-9 h-9 rounded-full bg-slate-800 animate-pulse" />
          <div className="space-y-2">
            <div className="h-7 w-56 bg-slate-800 rounded animate-pulse" />
            <div className="h-3 w-40 bg-slate-800/60 rounded animate-pulse" />
          </div>
        </div>
        {/* Conference skeletons */}
        {['West', 'East'].map(conf => (
          <div key={conf} className="mb-8">
            <div className="h-3.5 w-28 bg-slate-800 rounded animate-pulse mb-3" />
            <div className="flex gap-3 overflow-hidden">
              {[1, 2, 3, 4].map(i => <SkeletonCard key={i} />)}
            </div>
          </div>
        ))}
      </div>
    );
  }

  const missingWest = westSeries.length < 2;
  const missingEast = eastSeries.length < 2;
  const missingAny  = missingWest || missingEast;

  return (
    <div className="px-4 py-8">
      {/* Header */}
      <div className="flex items-center gap-3 mb-4 justify-center">
        <Trophy className="w-9 h-9 text-orange-400" />
        <div>
          <h1 className="text-2xl md:text-5xl font-black text-white leading-none">2026 NBA Playoffs</h1>
          <p className="text-slate-400 text-sm mt-1">Click any matchup to make your prediction</p>
        </div>
      </div>
      <div className="flex flex-col items-center gap-2 mb-5">
        {/* Strategy hint */}
        <div className="flex items-center gap-3 px-4 py-2 rounded-full bg-slate-800/60 border border-slate-700/60 text-xs font-bold text-slate-400">
          <span className="text-slate-300">🛡️ Safe = favorites</span>
          <span className="text-slate-600">·</span>
          <span className="text-amber-400">🔥 Risky = underdogs</span>
          <span className="text-slate-600">·</span>
          <span className="text-slate-500">Higher risk = higher reward</span>
        </div>
        <button
          onClick={() => onNavigate && onNavigate('scoring')}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-slate-800/80 border border-slate-700 text-slate-400 hover:text-orange-400 hover:border-orange-500/40 text-xs font-bold transition-all"
        >
          <Info className="w-3.5 h-3.5" /> How scoring works
        </button>
      </div>

      {/* Save error banner */}
      {saveError && (
        <div className="max-w-2xl mx-auto mb-4 flex items-center gap-3 px-4 py-3 rounded-xl bg-red-500/15 border border-red-500/30">
          <span className="text-red-400 text-sm font-bold flex-1">⚠ {saveError}</span>
          <button onClick={() => setSaveError('')} className="text-red-400/60 hover:text-red-400 font-bold text-lg leading-none transition-colors">×</button>
        </div>
      )}

      {/* Missing matchups banner */}
      {missingAny && (
        <div className="max-w-2xl mx-auto mb-6 flex items-start gap-3 px-4 py-3 rounded-xl bg-yellow-500/10 border border-yellow-500/30">
          <AlertTriangle className="w-5 h-5 text-yellow-400 shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <p className="text-yellow-400 font-bold text-sm">
              {missingWest && missingEast ? 'Both conferences are' : missingWest ? 'Western Conference is' : 'Eastern Conference is'} missing Round 1 matchups (seeds 3–6).
            </p>
            <p className="text-slate-400 text-xs mt-0.5">
              Go to <strong className="text-slate-300">Admin → Regenerate Matchups</strong> to generate them from live standings, then click Reload below.
            </p>
          </div>
          <button onClick={() => { qc.invalidateQueries({ queryKey: ['series'] }); qc.invalidateQueries({ queryKey: ['playin'] }); }} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-yellow-500/20 border border-yellow-500/40 text-yellow-400 hover:bg-yellow-500/30 text-xs font-bold transition-all shrink-0">
            <RefreshCw className="w-3 h-3" /> Reload
          </button>
        </div>
      )}

      {/* ── DESKTOP BRACKET ── */}
      <div className="hidden lg:block">
        {/* Pick progress bar */}
        {(() => {
          const r1All   = [...(westSlots || []), ...(eastSlots || [])].filter(Boolean);
          const piAll   = [...(westPI   || []), ...(eastPI   || [])].filter(g => g.status !== 'completed');
          const r1Saved = r1All.filter(s => myPredMap[s.id] || confirmed[s.id]).length;
          const piSaved = piAll.filter(g => myPiPredMap[g.id] || piConfirmed[g.id]).length;
          const total   = r1All.length + piAll.length;
          const done    = r1Saved + piSaved;
          const pct     = total > 0 ? Math.round((done / total) * 100) : 0;
          const allDone = done === total && total > 0;
          return (
            <div className="max-w-lg mx-auto mb-4 px-2">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[11px] font-black text-slate-400 uppercase tracking-widest">Your picks</span>
                <span className={`text-[11px] font-black ${allDone ? 'text-green-400' : done > 0 ? 'text-yellow-400' : 'text-cyan-400'}`}>
                  {done} / {total} saved{allDone ? ' 🎉' : ''}
                </span>
              </div>
              <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${allDone ? 'bg-green-500' : 'bg-gradient-to-r from-yellow-500 to-orange-500'}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              {/* Legend */}
              <div className="flex items-center gap-4 mt-2 justify-center flex-wrap">
                <span className="flex items-center gap-1.5 text-[10px] text-yellow-300/80 font-bold">
                  <span className="w-3 h-3 rounded border-2 border-yellow-400 bg-yellow-400/20 shrink-0" /> Pick saved
                </span>
                <span className="flex items-center gap-1.5 text-[10px] text-cyan-400/80 font-bold">
                  <span className="w-3 h-3 rounded border-2 border-cyan-500/60 shrink-0" /> Open — tap to pick
                </span>
                <span className="flex items-center gap-1.5 text-[10px] text-orange-400/80 font-bold">
                  <span className="w-3 h-3 rounded border-2 border-orange-500/60 shrink-0" /> Selected, not saved
                </span>
                <span className="flex items-center gap-1.5 text-[10px] text-green-400/80 font-bold">
                  <span className="w-3 h-3 rounded border-2 border-green-500/50 bg-green-500/15 shrink-0" /> Completed
                </span>
              </div>
            </div>
          );
        })()}

        <div className="flex items-center justify-between mb-2 px-1" style={{ width: 'fit-content', margin: '0 auto 8px' }}>
          <span className="text-sm font-black text-red-400 uppercase tracking-widest">Western Conference ▶</span>
          <span className="flex-1" />
          <span className="text-sm font-black text-blue-400 uppercase tracking-widest">◀ Eastern Conference</span>
        </div>

        <div className="overflow-x-auto pb-4">
          <div className="flex items-start gap-0" style={{ width: 'fit-content', margin: '0 auto' }}>

            {/* WEST Play-In */}
            <PlayInCol
              label="Play-In"
              games={westPI}
              picks={piPicks}
              onTeamClick={handlePITeamClick}
              onSave={handlePISave}
              saved={piSaved}
              seed1Team={westSeed1}
              seed2Team={westSeed2}
              confirmed={piConfirmed}
              predMap={myPiPredMap}
            />
            <HLine width={20} />

            {/* WEST R1 */}
            <R1Col label="Round 1" slots={westSlots} picks={picks} onTeamClick={handleTeamClick} onGamesSelect={handleGamesSelect} onLeaderSelect={handleLeaderSelect} onSave={handleSave} saved={saved} seedTeams={westSeedTeams} confirmed={confirmed} onEdit={handleEdit} predMap={myPredMap} />

            {/* WEST Semis → Finals (only if showFull) */}
            {showFull && (
              <>
                <ConnectorCol count={2} dir="right" />
                <SemisCol label="Conf Semis" />
                <ConnectorCol count={1} dir="right" />
                <CFCol label="Conf Finals" />
                <HLine />
                <FinalsCard />
                <HLine />
                <CFCol label="Conf Finals" />
                <ConnectorCol count={1} dir="left" />
                <SemisCol label="Conf Semis" />
                <ConnectorCol count={2} dir="left" />
              </>
            )}

            {/* EAST R1 */}
            <R1Col label="Round 1" slots={eastSlots} picks={picks} onTeamClick={handleTeamClick} onGamesSelect={handleGamesSelect} onLeaderSelect={handleLeaderSelect} onSave={handleSave} saved={saved} seedTeams={eastSeedTeams} confirmed={confirmed} onEdit={handleEdit} predMap={myPredMap} />

            {/* EAST Play-In */}
            <HLine width={20} />
            <PlayInCol
              label="Play-In"
              games={eastPI}
              picks={piPicks}
              onTeamClick={handlePITeamClick}
              onSave={handlePISave}
              saved={piSaved}
              seed1Team={eastSeed1}
              seed2Team={eastSeed2}
              confirmed={piConfirmed}
              predMap={myPiPredMap}
            />
          </div>
        </div>

        {/* Toggle button */}
        <div className="flex justify-center mt-4 mb-2">
          <button
            onClick={toggleShowFull}
            className="flex items-center gap-2 px-5 py-2.5 rounded-full border border-slate-700 bg-slate-900/80 text-slate-300 hover:border-orange-500/50 hover:text-orange-400 transition-all text-sm font-bold"
          >
            {showFull ? (
              <><ChevronUp className="w-4 h-4" /> Hide Conf Finals & Finals</>
            ) : (
              <><ChevronDown className="w-4 h-4" /> Show Full Bracket</>
            )}
          </button>
        </div>
      </div>

      {/* ── SERIES CARDS (all screen sizes) ── */}
      <div className="space-y-8">

        {/* Western Conference */}
        <div>
          <div className="flex items-center gap-2 mb-4">
            <div className="h-px flex-1 bg-red-500/20" />
            <h2 className="text-lg font-black text-red-400 uppercase tracking-widest px-3">Western Conference</h2>
            <div className="h-px flex-1 bg-red-500/20" />
          </div>

          {westPI.length > 0 && (
            <div className="mb-4">
              <p className="text-xs text-slate-500 uppercase font-bold tracking-wider mb-2 px-1">Play-In Tournament</p>
              <div className="space-y-2">
                {PLAYIN_ORDER.map(({ type, label }) => {
                  const game = westPI.find(g => g.game_type === type);
                  if (!game) return null;
                  return (
                    <div key={type}>
                      <p className="text-[11px] text-slate-500 font-bold uppercase tracking-wide px-1 mb-1">{label}</p>
                      <MobilePlayInCard game={game} pick={piPicks[game.id] || (myPiPredMap[game.id] ? { teamId: +myPiPredMap[game.id].predicted_winner_id } : undefined)} onTeamClick={handlePITeamClick} onSave={handlePISave} saved={piSaved[game.id]} communityStats={null} predData={myPiPredMap[game.id]} highlighted={highlightedId === `playin-${game.id}`} confirmed={!!(piConfirmed[game.id] || myPiPredMap[game.id])} />
                    </div>
                  );
                })}
              </div>
              <div className="flex items-center gap-2 my-4">
                <div className="h-px flex-1 bg-slate-800" />
                <span className="text-xs text-slate-600 font-bold uppercase tracking-wider">Round 1</span>
                <div className="h-px flex-1 bg-slate-800" />
              </div>
            </div>
          )}

          <div className="space-y-3">
            {westSlots.filter(Boolean).length > 0 ? westSlots.filter(Boolean).map(s => (
              <MobileMatchCard key={s.id} series={s} pick={picks[s.id] || (myPredMap[s.id] ? { teamId: +myPredMap[s.id].predicted_winner_id, games: myPredMap[s.id].predicted_games, scorer: myPredMap[s.id].leading_scorer || '', rebounder: myPredMap[s.id].leading_rebounder || '', assister: myPredMap[s.id].leading_assister || '' } : undefined)} onTeamClick={handleTeamClick} onGamesSelect={handleGamesSelect} onLeaderSelect={handleLeaderSelect} onSave={handleSave} saved={saved[s.id]} communityStats={communityMap[s.id] ?? null} confirmed={!!(confirmed[s.id] || myPredMap[s.id])} onEdit={() => handleEdit(s.id)} predData={myPredMap[s.id]} highlighted={highlightedId === `series-${s.id}`} />
            )) : (
              <div className="text-center py-6 text-slate-500">No matchups yet — check back soon</div>
            )}
          </div>
        </div>

        {/* Finals teaser */}
        <div className="bg-gradient-to-r from-yellow-500/10 to-orange-500/10 border border-yellow-500/20 rounded-2xl p-5 text-center">
          <Trophy className="w-10 h-10 text-yellow-400 mx-auto mb-2" />
          <p className="text-yellow-400 font-black text-lg">NBA Finals</p>
          <p className="text-slate-500 text-sm mt-1">To be determined</p>
        </div>

        {/* Eastern Conference */}
        <div>
          <div className="flex items-center gap-2 mb-4">
            <div className="h-px flex-1 bg-blue-500/20" />
            <h2 className="text-lg font-black text-blue-400 uppercase tracking-widest px-3">Eastern Conference</h2>
            <div className="h-px flex-1 bg-blue-500/20" />
          </div>

          {eastPI.length > 0 && (
            <div className="mb-4">
              <p className="text-xs text-slate-500 uppercase font-bold tracking-wider mb-2 px-1">Play-In Tournament</p>
              <div className="space-y-2">
                {PLAYIN_ORDER.map(({ type, label }) => {
                  const game = eastPI.find(g => g.game_type === type);
                  if (!game) return null;
                  return (
                    <div key={type}>
                      <p className="text-[11px] text-slate-500 font-bold uppercase tracking-wide px-1 mb-1">{label}</p>
                      <MobilePlayInCard game={game} pick={piPicks[game.id] || (myPiPredMap[game.id] ? { teamId: +myPiPredMap[game.id].predicted_winner_id } : undefined)} onTeamClick={handlePITeamClick} onSave={handlePISave} saved={piSaved[game.id]} communityStats={null} predData={myPiPredMap[game.id]} highlighted={highlightedId === `playin-${game.id}`} confirmed={!!(piConfirmed[game.id] || myPiPredMap[game.id])} />
                    </div>
                  );
                })}
              </div>
              <div className="flex items-center gap-2 my-4">
                <div className="h-px flex-1 bg-slate-800" />
                <span className="text-xs text-slate-600 font-bold uppercase tracking-wider">Round 1</span>
                <div className="h-px flex-1 bg-slate-800" />
              </div>
            </div>
          )}

          <div className="space-y-3">
            {eastSlots.filter(Boolean).length > 0 ? eastSlots.filter(Boolean).map(s => (
              <MobileMatchCard key={s.id} series={s} pick={picks[s.id] || (myPredMap[s.id] ? { teamId: +myPredMap[s.id].predicted_winner_id, games: myPredMap[s.id].predicted_games, scorer: myPredMap[s.id].leading_scorer || '', rebounder: myPredMap[s.id].leading_rebounder || '', assister: myPredMap[s.id].leading_assister || '' } : undefined)} onTeamClick={handleTeamClick} onGamesSelect={handleGamesSelect} onLeaderSelect={handleLeaderSelect} onSave={handleSave} saved={saved[s.id]} communityStats={communityMap[s.id] ?? null} confirmed={!!(confirmed[s.id] || myPredMap[s.id])} onEdit={() => handleEdit(s.id)} predData={myPredMap[s.id]} highlighted={highlightedId === `series-${s.id}`} />
            )) : (
              <div className="text-center py-6 text-slate-500">No matchups yet — check back soon</div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
};

export default BracketPage;
