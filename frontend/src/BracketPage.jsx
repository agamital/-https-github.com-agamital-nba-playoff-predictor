import React, { useState, useMemo, useEffect, useRef } from 'react';
import { Trophy, ChevronRight, ChevronDown, ChevronUp, AlertTriangle, RefreshCw, Info } from 'lucide-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import * as api from './services/api';
import { calcSeriesPts, getUnderdogMult, getRoundMult, PLAYIN_PTS } from './scoringConstants';
import CommunityInsights from './components/CommunityInsights';

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

  // Dedup by both player_id AND normalised name (handles cross-source ID splits),
  // then sort by the relevant stat descending.
  const sorted = React.useMemo(() => {
    const seenIds   = new Set();
    const seenNames = new Set();
    const unique = players.filter(p => {
      const normName = p.name?.trim().toLowerCase();
      if (seenIds.has(p.player_id) || seenNames.has(normName)) return false;
      seenIds.add(p.player_id);
      seenNames.add(normName);
      return true;
    });
    return unique.sort((a, b) => (b[statKey] ?? 0) - (a[statKey] ?? 0));
  }, [players, statKey]);

  const filtered = query.length >= 2
    ? sorted.filter(p => p.name.toLowerCase().includes(query.toLowerCase())).slice(0, 8)
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

const MatchCard = ({ series, pick, onTeamClick }) => {
  const { home_team: h, away_team: a, status, winner_team_id, actual_games } = series;
  const isCompleted = status === 'completed';
  const isLocked = status === 'locked';
  const hp = pick?.teamId === h.id;
  const ap = pick?.teamId === a.id;
  const hWon = winner_team_id === h.id;
  const aWon = winner_team_id === a.id;

  const homeSeed = series.home_seed ?? h.seed ?? null;
  const awaySeed = series.away_seed ?? a.seed ?? null;
  const underdogSeed = (homeSeed != null && awaySeed != null) ? Math.max(homeSeed, awaySeed) : null;
  const hIsUnderdog = underdogSeed != null && homeSeed === underdogSeed;
  const aIsUnderdog = underdogSeed != null && awaySeed === underdogSeed;
  const pickedUnderdog = (hp && hIsUnderdog) || (ap && aIsUnderdog);

  const teamRow = (team, picked, won, isUnderdog, onClick) => (
    <button
      onClick={isCompleted || isLocked ? undefined : onClick}
      className={`flex-1 flex items-center gap-2 px-3 w-full transition-all ${
        won ? 'bg-green-500/20' :
        picked && !isCompleted ? (isUnderdog ? 'bg-amber-500/20' : 'bg-orange-500/25') :
        isCompleted && !won ? 'opacity-40' :
        isLocked ? '' :
        isUnderdog && !isCompleted ? 'hover:bg-amber-500/10' :
        'hover:bg-slate-800/70'
      }`}
      style={{ cursor: isCompleted || isLocked ? 'default' : 'pointer' }}
    >
      <span className="text-xs text-slate-500 w-4 shrink-0 font-bold">{team.seed}</span>
      {isUnderdog && !isCompleted && (
        <span className="text-[7px] font-black text-amber-400/60 shrink-0 uppercase tracking-tight">DOG</span>
      )}
      <img src={team.logo_url} alt="" className="w-8 h-8 shrink-0" onError={e => e.target.style.display = 'none'} />
      <span className={`text-sm font-bold truncate ${
        won ? 'text-green-400' :
        picked && !isCompleted ? (isUnderdog ? 'text-amber-400' : 'text-orange-400') :
        'text-white'
      }`}>
        {team.abbreviation}
      </span>
      {won && actual_games && <span className="ml-auto text-[10px] text-green-400 font-black shrink-0">in {actual_games}</span>}
      {picked && !isCompleted && !isLocked && (
        <span className={`ml-auto text-[7px] font-black shrink-0 px-1 py-0.5 rounded ${
          isUnderdog ? 'text-amber-400 bg-amber-500/15' : 'text-orange-400/70'
        }`}>
          {isUnderdog ? 'RISKY' : 'SAFE'}
        </span>
      )}
    </button>
  );

  return (
    <div style={{ height: CH }}
      className={`w-44 border-2 rounded-xl flex flex-col overflow-hidden transition-all ${
        isCompleted ? 'border-green-500/40 shadow-md shadow-green-500/10' :
        isLocked ? 'border-yellow-500/30 opacity-75' :
        pickedUnderdog && !isCompleted ? 'border-amber-400/60 underdog-glow' :
        (hp || ap) ? 'border-orange-500/40 shadow-md shadow-orange-500/10 cursor-pointer' :
        'border-slate-700/60 hover:border-slate-600 cursor-pointer'
      } bg-slate-900/80`}>
      {teamRow(h, hp, hWon, hIsUnderdog, () => onTeamClick(series, h.id))}
      <div className="h-px bg-slate-800" />
      {teamRow(a, ap, aWon, aIsUnderdog, () => onTeamClick(series, a.id))}
    </div>
  );
};

// ── Play-In match card ────────────────────────────────────────────────────────

const PlayInCard = ({ game, pick, onTeamClick }) => {
  if (!game) return <TBDCard width="w-40" />;
  const { team1, team2 } = game;
  const p1 = pick?.teamId === team1?.id;
  const p2 = pick?.teamId === team2?.id;

  const teamRow = (team, picked, onClick) => (
    <button onClick={onClick}
      className={`flex-1 flex items-center gap-2 px-3 w-full transition-all ${picked ? 'bg-orange-500/25' : 'hover:bg-slate-800/70'}`}>
      <span className="text-[11px] text-slate-500 w-4 shrink-0 font-bold">{team?.seed}</span>
      <img src={team?.logo_url} alt="" className="w-7 h-7 shrink-0" onError={e => e.target.style.display = 'none'} />
      <span className={`text-xs font-bold truncate ${picked ? 'text-orange-400' : 'text-white'}`}>{team?.abbreviation}</span>
      {picked && <ChevronRight className="ml-auto w-3 h-3 text-orange-400 shrink-0" />}
    </button>
  );

  return (
    <div style={{ height: CH }}
      className={`w-40 border-2 rounded-xl flex flex-col overflow-hidden transition-all cursor-pointer bg-slate-900/80 relative ${
        (p1 || p2) ? 'border-orange-500/40 shadow-md shadow-orange-500/10' : 'border-slate-700/60 hover:border-slate-600'
      }`}>
      <span className="absolute top-1 right-1.5 text-[9px] font-black text-cyan-400/70 z-10">+{PLAYIN_PTS}pts</span>
      {teamRow(team1, p1, () => onTeamClick(game, team1?.id))}
      <div className="h-px bg-slate-800" />
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
  const roundMult  = getRoundMult(roundName);
  const underdogMult = getUnderdogMult(roundName, homeSeed, awaySeed, pickedSeed);
  const isUnderdog = underdogMult > 1.0;

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
        {roundMult > 1 && (
          <span className="text-[9px] font-black text-slate-500 bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5">
            ×{roundMult}
          </span>
        )}
      </div>

      {/* Bonus pop for underdog */}
      {isUnderdog && (
        <p key={pickedSeed} className="bonus-pop text-[9px] font-black text-amber-400 text-center bg-amber-500/10 rounded py-0.5">
          +{totalPts - Math.floor(20 * roundMult) - Math.floor(40 * roundMult)} bonus pts vs fav
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

const PlayInPicker = ({ gameId, pick, onSave, saved }) => (
  <div className="w-40 bg-slate-950/80 border border-orange-500/20 rounded-xl px-2 py-2 space-y-1.5 shadow-lg">
    <p className="text-[9px] text-cyan-400/80 font-black text-center">+{PLAYIN_PTS} pts if correct</p>
    <button onClick={() => onSave(gameId)} disabled={!pick?.teamId}
      className={`w-full py-1.5 rounded-lg text-xs font-black tracking-wide transition-all ${
        saved ? 'bg-green-500/20 border border-green-500/40 text-green-400' :
        !pick?.teamId ? 'bg-slate-900 border border-slate-800 text-slate-600 cursor-not-allowed' :
        'bg-gradient-to-r from-orange-500 to-orange-600 text-white shadow-md shadow-orange-500/30'
      }`}>
      {saved ? '✓ Saved!' : 'Save Pick'}
    </button>
  </div>
);

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

const PlayInCol = ({ label, games, picks, onTeamClick, onSave, saved, seed1Team, seed2Team }) => {
  const slotH = (BH + 28) / PI_SLOTS;
  const seedBySlot = { elimination: seed1Team, '7v8': seed2Team };
  return (
    <div style={{ flexShrink: 0 }}>
      <p className="text-xs text-slate-500 uppercase font-bold mb-3 text-center tracking-wider">{label}</p>
      <div style={{ height: BH + 28, display: 'flex', flexDirection: 'column' }}>
        {PLAYIN_ORDER.map(({ type, label: gLabel, sublabel }) => {
          const game = games.find(g => g.game_type === type);
          const pick = game ? picks[game.id] : null;
          const seedTeam = seedBySlot[type];
          return (
            <div key={type} style={{ height: slotH, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 3 }}>
              <p className="text-[10px] text-slate-400 font-black uppercase tracking-wide">{gLabel}</p>
              <p className="text-[9px] text-slate-600 font-bold uppercase tracking-wider">{sublabel}</p>
              {seedTeam && <SeedBadge team={seedTeam} seed={type === 'elimination' ? 1 : 2} />}
              <div style={{ position: 'relative', display: 'inline-flex', flexDirection: 'column', alignItems: 'center' }}>
                <PlayInCard game={game} pick={pick} onTeamClick={onTeamClick} />
                {game && pick?.teamId && (
                  <div style={{ position: 'absolute', top: CH + 6, left: '50%', transform: 'translateX(-50%)', zIndex: 30 }}>
                    <PlayInPicker gameId={game.id} pick={pick} onSave={onSave} saved={saved[game.id]} />
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

const R1Col = ({ label, slots, picks, onTeamClick, onGamesSelect, onLeaderSelect, onSave, saved, seedTeams, confirmed, onEdit }) => (
  <div style={{ flexShrink: 0 }}>
    <p className="text-xs text-slate-500 uppercase font-bold mb-3 text-center tracking-wider">{label}</p>
    <div style={{ height: BH + 28, display: 'flex', flexDirection: 'column' }}>
      {slots.map((s, i) => {
        const waitingTeam = !s && seedTeams?.[SEED_SLOT[i]];
        return (
          <div key={i} style={{ height: (BH + 28) / 4, display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'relative' }}>
            {s ? (
              <div style={{ position: 'relative', display: 'inline-flex', flexDirection: 'column', alignItems: 'center' }}>
                <MatchCard series={s} pick={picks[s.id]} onTeamClick={onTeamClick} />
                {picks[s.id]?.teamId && s.status === 'active' && (
                  <div style={{ position: 'absolute', top: CH + 6, left: '50%', transform: 'translateX(-50%)', zIndex: 30 }}>
                    {confirmed[s.id] ? (
                      <button
                        onClick={() => onEdit(s.id)}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 hover:border-orange-500/50 hover:text-orange-400 text-[10px] font-bold transition-all whitespace-nowrap"
                      >
                        ✏ Edit pick
                      </button>
                    ) : (
                      <InlinePicker seriesId={s.id} series={s} pick={picks[s.id]} onGamesSelect={onGamesSelect} onLeaderSelect={onLeaderSelect} onSave={onSave} saved={saved[s.id]} />
                    )}
                  </div>
                )}
              </div>
            ) : waitingTeam ? (
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

const MobilePlayInCard = ({ game, pick, onTeamClick, onSave, saved, communityStats }) => {
  if (!game) return null;
  const { team1, team2 } = game;
  const p1 = pick?.teamId === team1?.id;
  const p2 = pick?.teamId === team2?.id;

  const teamBtn = (team, picked, onClick) => (
    <button onClick={onClick}
      className={`flex items-center gap-3 p-3 rounded-xl border-2 transition-all w-full ${
        picked ? 'border-orange-500 bg-orange-500/15' : 'border-slate-700 bg-slate-900/60 hover:border-slate-600'
      }`}>
      <span className={`text-xs font-black w-5 ${picked ? 'text-orange-400' : 'text-slate-500'}`}>{team?.seed}</span>
      <img src={team?.logo_url} alt="" className="w-9 h-9 shrink-0" onError={e => e.target.style.display = 'none'} />
      <p className={`font-black text-sm flex-1 text-left ${picked ? 'text-orange-400' : 'text-white'}`}>{team?.name}</p>
      {picked && <div className="w-5 h-5 rounded-full bg-orange-500 flex items-center justify-center shrink-0"><span className="text-white text-[10px] font-black">✓</span></div>}
    </button>
  );

  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-4 space-y-2">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] text-slate-600 font-bold uppercase tracking-wider">Play-In</span>
        <span className="text-[10px] font-black text-cyan-400/80">+{PLAYIN_PTS} pts if correct</span>
      </div>
      {teamBtn(team1, p1, () => onTeamClick(game, team1?.id))}
      <div className="text-center text-xs text-slate-600 font-bold">VS</div>
      {teamBtn(team2, p2, () => onTeamClick(game, team2?.id))}
      {(p1 || p2) && (
        <button onClick={() => onSave(game.id)}
          className={`w-full py-3 rounded-xl font-black text-sm transition-all mt-1 ${
            saved ? 'bg-green-500 text-white' : 'bg-gradient-to-r from-orange-500 to-red-500 text-white'
          }`}>
          {saved ? '✓ Saved!' : 'Save Pick'}
        </button>
      )}
      <CommunityInsights
        gameId={game.id}
        homeTeam={team1}
        awayTeam={team2}
        initialStats={communityStats ?? null}
        status={game.status}
      />
    </div>
  );
};

const MobileMatchCard = ({ series, pick, onTeamClick, onGamesSelect, onLeaderSelect, onSave, saved, communityStats, confirmed, onEdit }) => {
  const { home_team: h, away_team: a } = series;
  const hp = pick?.teamId === h.id;
  const ap = pick?.teamId === a.id;
  const picked = hp ? h : ap ? a : null;
  const isCompleted = series.status === 'completed';
  const isLocked = series.status === 'locked';
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
        isPicked && !isCompleted && isTeamUnderdog ? 'border-amber-500 bg-amber-500/15 underdog-glow' :
        isPicked && !isCompleted ? 'border-orange-500 bg-orange-500/15' :
        isCompleted && !isWon ? 'border-slate-700 bg-slate-900/60 opacity-40' :
        !isWon && !isPicked && !isCompleted && isTeamUnderdog ? 'border-amber-500/20 bg-amber-500/5 hover:border-amber-400/40' :
        'border-slate-700 bg-slate-900/60 hover:border-slate-600'
      }`}>
      <span className={`text-xs font-black w-5 shrink-0 ${isWon ? 'text-green-400' : isPicked && !isCompleted && isTeamUnderdog ? 'text-amber-400' : isPicked && !isCompleted ? 'text-orange-400' : 'text-slate-500'}`}>{team.seed}</span>
      <img src={team.logo_url} alt="" className="w-10 h-10 shrink-0" onError={e => e.target.style.display = 'none'} />
      <div className="text-left flex-1 min-w-0">
        <p className={`font-black text-base leading-tight truncate ${isWon ? 'text-green-400' : isPicked && !isCompleted && isTeamUnderdog ? 'text-amber-400' : isPicked && !isCompleted ? 'text-orange-400' : 'text-white'}`}>{team.name}</p>
        <p className="text-xs text-slate-500">{isWon && series.actual_games ? `Won in ${series.actual_games}` : isTeamUnderdog && !isCompleted ? '🔥 Underdog — higher reward' : `Seed #${team.seed}`}</p>
      </div>
      {!isCompleted && !isLocked && !isPicked && (
        <span className={`text-[8px] font-black shrink-0 px-1.5 py-0.5 rounded border ${
          isTeamUnderdog ? 'text-amber-400 bg-amber-500/10 border-amber-500/25' : 'text-slate-500 bg-slate-800 border-slate-700'
        }`}>{isTeamUnderdog ? 'RISKY' : 'SAFE'}</span>
      )}
      {isWon && <div className="w-6 h-6 rounded-full bg-green-500 flex items-center justify-center shrink-0"><span className="text-white text-xs font-black">✓</span></div>}
      {isPicked && !isCompleted && !isWon && <div className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 ${isTeamUnderdog ? 'bg-amber-500' : 'bg-orange-500'}`}><span className="text-white text-xs font-black">✓</span></div>}
    </button>
  );

  const roundMult  = getRoundMult(series.round);
  const pickedSeed = hp ? homeSeed : ap ? awaySeed : null;
  const underdogMult = getUnderdogMult(series.round, homeSeed, awaySeed, pickedSeed);
  const { winnerPts, gamesPts, totalPts } = calcSeriesPts(series.round, homeSeed, awaySeed, pickedSeed);
  const isHUnderdog = hp && getUnderdogMult(series.round, homeSeed, awaySeed, homeSeed) > 1.0;
  const isAUnderdog = ap && getUnderdogMult(series.round, homeSeed, awaySeed, awaySeed) > 1.0;

  const { data: seriesPlayers = [] } = useQuery({
    queryKey: ['seriesPlayers', series.id],
    queryFn:  () => api.getSeriesPlayers(series.id),
    staleTime: 30 * 60 * 1000,
    enabled: !!(picked && !isCompleted && !isLocked),
  });

  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">{series.round}</span>
          {series.status === 'active' && (
            <span className="ml-2 text-[10px] font-black text-slate-500">
              Round {roundMult}x | Up to <span className="text-green-400">{calcSeriesPts(series.round, homeSeed, awaySeed, null).totalPts}+ pts</span>
            </span>
          )}
        </div>
        {series.status === 'completed' && <span className="text-xs font-bold text-green-400 flex items-center gap-1">✓ Complete</span>}
        {series.status === 'locked' && <span className="text-xs font-bold text-yellow-400 flex items-center gap-1">🔒 Locked</span>}
        {series.status === 'active' && <span className="text-xs font-bold text-blue-400">Predictions Open</span>}
      </div>
      <div className="space-y-2">
        {teamBtn(h, hp, hWon, hIsUnderdog2, () => onTeamClick(series, h.id))}
        <div className="text-center text-xs text-slate-600 font-bold">VS</div>
        {teamBtn(a, ap, aWon, aIsUnderdog2, () => onTeamClick(series, a.id))}
      </div>
      {/* Underdog bonus callout */}
      {(isHUnderdog || isAUnderdog) && !isCompleted && !isLocked && (
        <div className="bonus-pop flex items-center gap-2 px-3 py-1.5 rounded-xl bg-amber-500/10 border border-amber-500/20">
          <span className="text-amber-400 text-xs font-black">🔥 Bold pick!</span>
          <span className="text-amber-400/70 text-xs font-bold">{totalPts} pts max · higher risk = higher reward</span>
        </div>
      )}
      {picked && !isCompleted && !isLocked && confirmed && (
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
      <CommunityInsights
        seriesId={series.id}
        homeTeam={h}
        awayTeam={a}
        initialStats={communityStats ?? null}
        status={series.status}
      />
    </div>
  );
};

// ── Main Page ─────────────────────────────────────────────────────────────────

const BracketPage = ({ currentUser, onNavigate }) => {
  const qc = useQueryClient();
  const [picks, setPicks]             = useState({});
  const [saved, setSaved]             = useState({});
  const [confirmed, setConfirmed]     = useState({});
  const [piPicks, setPiPicks]         = useState({});
  const [piSaved, setPiSaved]         = useState({});
  const [showFull, setShowFull]       = useState(() => {
    try { return localStorage.getItem('bracketShowFull') === 'true'; } catch { return false; }
  });
  const [saveError, setSaveError]     = useState('');

  // ── Cached data queries ──────────────────────────────────────────────────────
  const { data: series = [],    isLoading: l1 } = useQuery({ queryKey: ['series', '2026'],    queryFn: () => api.getSeries('2026') });
  const { data: playInGames = [], isLoading: l2 } = useQuery({ queryKey: ['playin', '2026'],  queryFn: () => api.getPlayInGames('2026') });
  const { data: allTeams = [],  isLoading: l3 } = useQuery({ queryKey: ['teams'],             queryFn: () => api.getTeams() });
  const { data: standingsRaw,   isLoading: l4 } = useQuery({ queryKey: ['standings'],         queryFn: () => api.getStandings() });
  const { data: globalStats }                   = useQuery({ queryKey: ['globalStats', '2026'], queryFn: () => api.getGlobalStats('2026'), staleTime: 10 * 60 * 1000 });

  const standings = standingsRaw || { eastern: [], western: [] };
  const loading   = l1 || l2 || l3 || l4;

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
      // Invalidate notification badge so it reflects this new pick
      qc.invalidateQueries({ queryKey: ['notifications', currentUser.user_id] });
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
      setTimeout(() => setPiSaved(p => ({ ...p, [gameId]: false })), 2000);
      qc.invalidateQueries({ queryKey: ['notifications', currentUser.user_id] });
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
            />
            <HLine width={20} />

            {/* WEST R1 */}
            <R1Col label="Round 1" slots={westSlots} picks={picks} onTeamClick={handleTeamClick} onGamesSelect={handleGamesSelect} onLeaderSelect={handleLeaderSelect} onSave={handleSave} saved={saved} seedTeams={westSeedTeams} confirmed={confirmed} onEdit={handleEdit} />

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
            <R1Col label="Round 1" slots={eastSlots} picks={picks} onTeamClick={handleTeamClick} onGamesSelect={handleGamesSelect} onLeaderSelect={handleLeaderSelect} onSave={handleSave} saved={saved} seedTeams={eastSeedTeams} confirmed={confirmed} onEdit={handleEdit} />

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

      {/* ── MOBILE LAYOUT ── */}
      <div className="lg:hidden space-y-8">

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
                      <MobilePlayInCard game={game} pick={piPicks[game.id]} onTeamClick={handlePITeamClick} onSave={handlePISave} saved={piSaved[game.id]} communityStats={null} />
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
            {westSeries.length > 0 ? westSeries.map(s => (
              <MobileMatchCard key={s.id} series={s} pick={picks[s.id]} onTeamClick={handleTeamClick} onGamesSelect={handleGamesSelect} onLeaderSelect={handleLeaderSelect} onSave={handleSave} saved={saved[s.id]} communityStats={communityMap[s.id] ?? null} confirmed={confirmed[s.id]} onEdit={() => handleEdit(s.id)} />
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
                      <MobilePlayInCard game={game} pick={piPicks[game.id]} onTeamClick={handlePITeamClick} onSave={handlePISave} saved={piSaved[game.id]} communityStats={null} />
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
            {eastSeries.length > 0 ? eastSeries.map(s => (
              <MobileMatchCard key={s.id} series={s} pick={picks[s.id]} onTeamClick={handleTeamClick} onGamesSelect={handleGamesSelect} onLeaderSelect={handleLeaderSelect} onSave={handleSave} saved={saved[s.id]} communityStats={communityMap[s.id] ?? null} confirmed={confirmed[s.id]} onEdit={() => handleEdit(s.id)} />
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
