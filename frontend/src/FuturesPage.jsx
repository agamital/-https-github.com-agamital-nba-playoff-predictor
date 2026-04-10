import React, { useState, useEffect, useRef } from 'react';
import { Trophy, Lock, CheckCircle, Star, BarChart2, Info, Search } from 'lucide-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import * as api from './services/api';
import { FUTURES_BASE_POINTS, LEADERS_POINTS, LEADERS_TIERS } from './scoringConstants';
import ScoringTooltip from './ScoringTooltip';

// ── useDebounce ────────────────────────────────────────────────────────────
function useDebounce(value, delay) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

// ── Numeric input for leader stat predictions ──────────────────────────────
const LeaderNumberInput = ({ value, onChange, locked, placeholder }) => {
  const handleChange = (e) => {
    const raw = e.target.value.replace(/[^0-9]/g, '');
    if (raw === '') { onChange(''); return; }
    const n = parseInt(raw, 10);
    if (Number.isFinite(n) && n > 0) onChange(n);
  };
  return (
    <div className="relative">
      <input
        type="text"
        inputMode="numeric"
        pattern="[0-9]*"
        value={value || ''}
        onChange={handleChange}
        disabled={locked}
        placeholder={placeholder || 'e.g. 550'}
        className="w-full px-4 py-3 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm placeholder-slate-500 focus:outline-none focus:border-cyan-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      />
      {value > 0 && (
        <p className="mt-1.5 text-xs text-cyan-400 font-bold flex items-center gap-1">✓ Predicted: {value}</p>
      )}
      <p className="mt-1 text-[10px] text-slate-600 font-bold">Closer = more points · Exact match earns full points</p>
    </div>
  );
};

// ── Smart MVP search input — shows top-PPG suggestions on focus ───────────
const MvpSearchInput = ({ value, onChange, locked, placeholder, conference, mvpType = '' }) => {
  const [query, setQuery] = useState(value || '');
  const [open, setOpen]   = useState(false);
  const containerRef      = useRef(null);
  const debouncedQ        = useDebounce(query, 280);

  // Keep local query in sync when external value changes (loading saved picks)
  useEffect(() => {
    if (value !== undefined && value !== query) setQuery(value || '');
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch top players on focus — Vegas-weighted when mvpType is set
  const { data: topData, isFetching: topFetching } = useQuery({
    queryKey: ['playerTopPPG', conference, mvpType],
    queryFn:  () => api.searchPlayers('', conference || 'All', 15, '2026', mvpType),
    staleTime: 10 * 60 * 1000,
  });

  // Fetch name-filtered results when user types
  const { data: searchData, isFetching: searchFetching } = useQuery({
    queryKey: ['playerSearch', debouncedQ, conference, mvpType],
    queryFn:  () => api.searchPlayers(debouncedQ, conference || 'All', 15, '2026', mvpType),
    enabled:  debouncedQ.length >= 1,
    staleTime: 5 * 60 * 1000,
    keepPreviousData: true,
  });

  const isFetching = query.length >= 1 ? searchFetching : topFetching;
  const players    = query.length >= 1
    ? (searchData?.players ?? [])
    : (topData?.players ?? []);

  // Close dropdown on outside click/touch
  useEffect(() => {
    const handler = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    document.addEventListener('touchstart', handler, { passive: true });
    return () => {
      document.removeEventListener('mousedown', handler);
      document.removeEventListener('touchstart', handler);
    };
  }, []);

  const handleSelect = (playerName) => {
    setQuery(playerName);
    onChange(playerName);
    setOpen(false);
  };

  const handleInput = (e) => {
    setQuery(e.target.value);
    onChange(e.target.value);
    setOpen(true);
  };

  const isSearchMode = query.length >= 1;
  const showDropdown = open && !locked;

  return (
    <div ref={containerRef} className="relative">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 pointer-events-none" />
        <input
          type="text"
          value={query}
          onChange={handleInput}
          onFocus={() => !locked && setOpen(true)}
          disabled={locked}
          placeholder={placeholder || 'Search or pick a player…'}
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="none"
          spellCheck={false}
          className="w-full pl-9 pr-4 py-3 bg-slate-800 border border-slate-700 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:border-orange-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        />
        {isFetching && (
          <div className="absolute right-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 border-2 border-orange-500 border-t-transparent rounded-full animate-spin" />
        )}
      </div>

      {/* Dropdown */}
      {showDropdown && (
        <div className="absolute top-full left-0 right-0 z-50 mt-1 bg-slate-800 border border-slate-700 rounded-xl shadow-2xl overflow-hidden"
          style={{ maxHeight: 320, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>

          {/* Header label */}
          <div className="px-4 py-2 bg-slate-900/70 border-b border-slate-700/50 flex items-center justify-between">
            <span className="text-[10px] font-black text-slate-500 uppercase tracking-wider">
              {isSearchMode ? 'Search results' : 'Top MVP candidates'}
              {conference && conference !== 'All' ? ` · ${conference} only` : ''}
            </span>
            {!isSearchMode && <span className="text-[10px] text-slate-600 font-bold">Tap to select</span>}
          </div>

          {isFetching && players.length === 0 ? (
            <div className="px-4 py-4 text-slate-500 text-sm animate-pulse">Loading…</div>
          ) : players.length === 0 ? (
            <div className="px-4 py-4 text-slate-500 text-sm">
              {isSearchMode ? `No players found for "${query}"` : 'No player data available yet'}
            </div>
          ) : (
            players.map((p, idx) => (
              <button
                key={p.player_id}
                onMouseDown={(e) => { e.preventDefault(); handleSelect(p.name); }}
                onTouchEnd={(e) => { e.preventDefault(); handleSelect(p.name); }}
                className="w-full flex items-center gap-2 px-4 py-2.5 hover:bg-slate-700/70 active:bg-slate-700 transition-colors text-left border-b border-slate-700/30 last:border-0"
              >
                {/* Rank badge */}
                {!isSearchMode && (
                  <span className={`w-5 h-5 shrink-0 flex items-center justify-center text-[10px] font-black rounded-full
                    ${idx === 0 ? 'bg-yellow-500/20 text-yellow-400' :
                      idx === 1 ? 'bg-slate-400/20 text-slate-300' :
                      idx === 2 ? 'bg-amber-700/20 text-amber-600' :
                      'text-slate-600'}`}>
                    {idx + 1}
                  </span>
                )}
                {p.logo_url ? (
                  <img src={p.logo_url} alt={p.team} className="w-5 h-5 shrink-0 object-contain" onError={e => e.target.style.display='none'} />
                ) : (
                  <span className="w-5 h-5 shrink-0 text-[9px] font-black text-slate-500 flex items-center justify-center">{p.team}</span>
                )}
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-semibold text-white truncate block">{p.name}</span>
                  <span className="text-[10px] text-slate-500 tabular-nums">
                    {p.ppg}pts · {p.rpg}reb · {p.apg}ast{p.spg > 0 ? ` · ${p.spg}stl` : ''}{p.bpg > 0 ? ` · ${p.bpg}blk` : ''}
                  </span>
                </div>
                <div className="shrink-0 text-right">
                  <span className="text-[10px] font-bold text-slate-500 block">{p.team}</span>
                  {p.mvp_score > 0 && (
                    <span className="text-[11px] font-black text-orange-400 tabular-nums">{p.mvp_score}⭐</span>
                  )}
                </div>
              </button>
            ))
          )}
        </div>
      )}

      {value && !open && (
        <p className="mt-1.5 text-xs text-orange-400 font-bold flex items-center gap-1">✓ {value}</p>
      )}
    </div>
  );
};

const LEADER_CATEGORIES = [
  { key: 'top_scorer',   statKey: 'scorer',   short: 'Most Total Points',    question: 'What will be the highest total points scored?',    color: 'text-yellow-400', pts: LEADERS_POINTS.scorer,   icon: '🏀', example: 'e.g. 550', refKey: 'top_scorers',  statField: 'ppg', statLabel: 'PPG' },
  { key: 'top_assists',  statKey: 'assists',  short: 'Most Total Assists',   question: 'What will be the highest total assists?',          color: 'text-blue-400',   pts: LEADERS_POINTS.assists,  icon: '🎯', example: 'e.g. 200', refKey: 'top_assists',  statField: 'apg', statLabel: 'APG' },
  { key: 'top_rebounds', statKey: 'rebounds', short: 'Most Total Rebounds',  question: 'What will be the highest total rebounds?',         color: 'text-green-400',  pts: LEADERS_POINTS.rebounds, icon: '💪', example: 'e.g. 250', refKey: 'top_rebounds', statField: 'rpg', statLabel: 'RPG' },
  { key: 'top_threes',   statKey: 'threes',   short: 'Most 3-Pointers Made', question: 'What will be the highest 3-pointers made?',        color: 'text-purple-400', pts: LEADERS_POINTS.threes,   icon: '3️⃣', example: 'e.g. 55',  refKey: 'top_threes',   statField: 'fg3m', statLabel: '3PM' },
  { key: 'top_steals',   statKey: 'steals',   short: 'Most Total Steals',    question: 'What will be the highest total steals?',           color: 'text-red-400',    pts: LEADERS_POINTS.steals,   icon: '🤚', example: 'e.g. 35',  refKey: 'top_steals',   statField: 'spg', statLabel: 'SPG' },
  { key: 'top_blocks',   statKey: 'blocks',   short: 'Most Total Blocks',    question: 'What will be the highest total blocks?',           color: 'text-orange-400', pts: LEADERS_POINTS.blocks,   icon: '🛡️', example: 'e.g. 40',  refKey: 'top_blocks',   statField: 'bpg', statLabel: 'BPG' },
];

const TeamGrid = ({ teams, selectedId, onSelect, locked, oddsField, cols = 5 }) => (
  <div className={`grid gap-3 ${cols === 5 ? 'grid-cols-4 sm:grid-cols-5' : 'grid-cols-3 sm:grid-cols-4 md:grid-cols-5'}`}>
    {teams.map(team => {
      const isSelected = selectedId === team.id;
      const odds = oddsField ? (team[oddsField] ?? 1.0) : null;
      const showOdds = odds !== null && odds !== 1.0;
      return (
        <button
          key={team.id}
          onClick={() => !locked && onSelect(team.id)}
          disabled={locked}
          className={`flex flex-col items-center gap-1 p-3 rounded-xl border-2 transition-all relative ${
            isSelected
              ? 'border-orange-500 bg-orange-500/15 shadow-lg shadow-orange-500/20'
              : locked
              ? 'border-slate-800 bg-slate-900/40 opacity-60 cursor-not-allowed'
              : 'border-slate-800 bg-slate-900/60 hover:border-slate-600 hover:bg-slate-800/60'
          }`}
        >
          <img src={team.logo_url} alt={team.abbreviation} className="w-10 h-10" onError={e => e.target.style.display = 'none'} />
          <span className={`text-[11px] font-black leading-tight text-center ${isSelected ? 'text-orange-400' : 'text-slate-300'}`}>
            {team.abbreviation}
          </span>
          {odds !== null && (
            <span className={`text-[9px] font-black ${showOdds ? 'text-amber-400' : 'text-slate-600'}`}>×{odds.toFixed(2)}</span>
          )}
          {isSelected && <CheckCircle className="w-3 h-3 text-orange-400" />}
        </button>
      );
    })}
  </div>
);

const Section = ({ title, icon, color, children, pts, oddsMult }) => {
  const finalPts = pts ? Math.floor(pts * (oddsMult || 1)) : null;
  const showMult = oddsMult && oddsMult !== 1 && pts;
  const isHighMult = oddsMult && oddsMult >= 1.5;
  return (
    <div className={`border rounded-2xl p-5 transition-all ${isHighMult ? 'bg-orange-500/5 border-orange-500/30 shadow-sm shadow-orange-500/10' : 'bg-slate-900/50 border-slate-800'}`}>
      <div className={`flex items-center gap-2 mb-1 ${color}`}>
        {icon}
        <h3 className="text-base font-black uppercase tracking-wider flex-1">{title}</h3>
        {finalPts != null && (
          <span className={`ml-auto text-xs font-black shrink-0 ${isHighMult ? 'text-amber-400' : 'text-green-400'}`}>
            {showMult ? `${pts} × ${oddsMult} = ${finalPts} pts` : `${finalPts} pts`}
          </span>
        )}
      </div>
      {isHighMult && <p className="text-[10px] text-amber-500/70 font-bold mb-3">Higher risk = more points</p>}
      {!isHighMult && <div className="mb-4" />}
      {children}
    </div>
  );
};


// ── Main FuturesPage ────────────────────────────────────────────────────────
const FuturesPage = ({ currentUser, onNavigate }) => {
  const qc = useQueryClient();

  // ── Prediction form state ────────────────────────────────────────────────
  const [champion,      setChampion]      = useState(null);
  const [westChamp,     setWestChamp]     = useState(null);
  const [eastChamp,     setEastChamp]     = useState(null);
  const [finalsMvp,     setFinalsMvp]     = useState('');
  const [westFinalsMvp, setWestFinalsMvp] = useState('');
  const [eastFinalsMvp, setEastFinalsMvp] = useState('');
  const [leaders, setLeaders] = useState({
    top_scorer: null, top_assists: null, top_rebounds: null,
    top_threes: null, top_steals: null, top_blocks: null,
  });

  const [saving,         setSaving]         = useState(false);
  const [saved,          setSaved]          = useState(false);
  const [leadersSaving,  setLeadersSaving]  = useState(false);
  const [leadersSaved,   setLeadersSaved]   = useState(false);
  const [saveError,      setSaveError]      = useState('');

  // ── React Query — static page data (teams/odds/lock) ────────────────────
  const { data: pageData, isLoading: pageLoading } = useQuery({
    queryKey: ['futuresPageData'],
    queryFn:  () => api.getFuturesPageData(),
    staleTime: 5 * 60 * 1000,
  });

  // ── React Query — regular-season leaders reference ───────────────────────
  const { data: playerLeaders } = useQuery({
    queryKey: ['playerLeaders', '2026'],
    queryFn:  () => api.getPlayerLeaders('2026', 5, true),
    staleTime: 30 * 60 * 1000,
  });

  // ── React Query — user's existing futures prediction ────────────────────
  const { data: futuresData } = useQuery({
    queryKey: ['userFutures', currentUser?.user_id],
    queryFn:  () => api.getFutures(currentUser.user_id),
    enabled:  !!currentUser,
    staleTime: 60 * 1000,
  });

  // ── React Query — user's existing leaders prediction ────────────────────
  const { data: leadersData } = useQuery({
    queryKey: ['userLeaders', currentUser?.user_id],
    queryFn:  () => api.getLeadersPrediction(currentUser.user_id),
    enabled:  !!currentUser,
    staleTime: 60 * 1000,
  });

  // Populate form when existing predictions load
  useEffect(() => {
    if (futuresData?.has_prediction) {
      setChampion(futuresData.champion_team_id ?? null);
      setWestChamp(futuresData.west_champ_team_id ?? null);
      setEastChamp(futuresData.east_champ_team_id ?? null);
      // Guard against numeric IDs accidentally stored — only set if it looks like a name
      const mvpVal = futuresData.finals_mvp;
      setFinalsMvp(mvpVal && isNaN(Number(mvpVal)) ? mvpVal : '');
      const wVal = futuresData.west_finals_mvp;
      setWestFinalsMvp(wVal && isNaN(Number(wVal)) ? wVal : '');
      const eVal = futuresData.east_finals_mvp;
      setEastFinalsMvp(eVal && isNaN(Number(eVal)) ? eVal : '');
    }
  }, [futuresData]);

  useEffect(() => {
    if (leadersData?.has_prediction) {
      setLeaders({
        top_scorer:   leadersData.top_scorer   ?? null,
        top_assists:  leadersData.top_assists  ?? null,
        top_rebounds: leadersData.top_rebounds ?? null,
        top_threes:   leadersData.top_threes   ?? null,
        top_steals:   leadersData.top_steals   ?? null,
        top_blocks:   leadersData.top_blocks   ?? null,
      });
    }
  }, [leadersData]);

  // Derived
  const teams      = pageData?.teams      ?? [];
  const westTeams  = pageData?.west_teams ?? [];
  const eastTeams  = pageData?.east_teams ?? [];
  const odds       = pageData?.odds       ?? {};
  const globalLocked = pageData?.locked   ?? false;
  const locked       = globalLocked || (futuresData?.locked || false);
  const loading      = pageLoading;

  const leadersLocked = pageData?.leaders_locked ?? false;
  const champOdds = teams.find(t => t.id === champion)?.odds_championship ?? null;
  const westOdds  = westTeams.find(t => t.id === westChamp)?.odds_conference ?? null;
  const eastOdds  = eastTeams.find(t => t.id === eastChamp)?.odds_conference ?? null;
  const hasAnyLeaderPick = Object.values(leaders).some(v => v);

  // ── Handlers ─────────────────────────────────────────────────────────────
  const handleSave = async () => {
    if (!currentUser || locked) return;
    setSaving(true);
    try {
      await api.saveFutures(currentUser.user_id, {
        champion_team_id: champion, west_champ_team_id: westChamp,
        east_champ_team_id: eastChamp, finals_mvp: finalsMvp,
        west_finals_mvp: westFinalsMvp, east_finals_mvp: eastFinalsMvp,
      });
      qc.invalidateQueries({ queryKey: ['userFutures', currentUser.user_id] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (err) {
      setSaveError(err.response?.data?.detail || 'Failed to save futures picks. Try again.');
    } finally {
      setSaving(false);
    }
  };

  const handleSaveLeaders = async () => {
    if (!currentUser || leadersLocked) return;
    setLeadersSaving(true);
    try {
      await api.saveLeadersPrediction(currentUser.user_id, leaders);
      qc.invalidateQueries({ queryKey: ['userLeaders', currentUser.user_id] });
      setLeadersSaved(true);
      setTimeout(() => setLeadersSaved(false), 2500);
    } catch (err) {
      setSaveError(err.response?.data?.detail || 'Failed to save leaders picks. Try again.');
    } finally {
      setLeadersSaving(false);
    }
  };

  if (!currentUser) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-16 text-center">
        <Star className="w-16 h-16 text-yellow-400 mx-auto mb-4 opacity-60" />
        <h2 className="text-3xl font-black text-white mb-3">Login to Make Futures Picks</h2>
        <p className="text-slate-400">Sign in to predict the 2026 NBA Playoffs champions</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="animate-spin rounded-full h-14 w-14 border-4 border-orange-500 border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 mt-2">
        <div className="flex items-center gap-2">
          <Star className="w-5 h-5 text-yellow-400" />
          <h2 className="text-xl font-black text-white uppercase tracking-wide">Futures Predictions</h2>
        </div>
        {locked && (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-red-500/10 border border-red-500/30">
            <Lock className="w-4 h-4 text-red-400" />
            <span className="text-red-400 text-sm font-bold">Picks Locked</span>
          </div>
        )}
        {!locked && futuresData?.has_prediction && (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-green-500/10 border border-green-500/30">
            <CheckCircle className="w-4 h-4 text-green-400" />
            <span className="text-green-400 text-sm font-bold">Picks Saved — Edit Anytime</span>
          </div>
        )}
      </div>

      {/* Scoring info */}
      <div className="flex justify-start mb-5">
        <button
          onClick={() => onNavigate && onNavigate('scoring')}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-slate-800/80 border border-slate-700 text-slate-400 hover:text-orange-400 hover:border-orange-500/40 text-xs font-bold transition-all"
        >
          <Info className="w-3.5 h-3.5" /> How scoring works
        </button>
      </div>

      {/* Current picks summary */}
      {futuresData?.has_prediction && (
        <div className="grid grid-cols-3 gap-3 mb-8">
          {[
            { label: 'Champion',   team: futuresData.champion_team,  correct: futuresData.is_correct_champion },
            { label: 'West Champ', team: futuresData.west_champ_team, correct: futuresData.is_correct_west },
            { label: 'East Champ', team: futuresData.east_champ_team, correct: futuresData.is_correct_east },
          ].map(({ label, team, correct }) => team && (
            <div key={label} className={`p-3 rounded-xl border text-center ${
              correct === 1 ? 'border-green-500/40 bg-green-500/10' :
              correct === 0 ? 'border-red-500/40 bg-red-500/10' :
              'border-orange-500/30 bg-orange-500/10'
            }`}>
              <img src={team.logo_url} alt="" className="w-10 h-10 mx-auto mb-1" onError={e => e.target.style.display='none'} />
              <p className="text-[10px] text-slate-500 uppercase font-bold">{label}</p>
              <p className="text-xs font-black text-white">{team.abbreviation}</p>
              {correct === 1 && <CheckCircle className="w-4 h-4 text-green-400 mx-auto mt-1" />}
            </div>
          ))}
        </div>
      )}

      <div className="space-y-6">
        {/* Champions divider */}
        <div className="flex items-center gap-2">
          <div className="h-px flex-1 bg-slate-800" />
          <span className="text-[10px] text-slate-500 font-black uppercase tracking-widest">Champions</span>
          <div className="h-px flex-1 bg-slate-800" />
        </div>

        <Section title="NBA Champion" color="text-yellow-400" icon={<Trophy className="w-5 h-5" />} pts={FUTURES_BASE_POINTS.champion} oddsMult={champOdds}>
          <p className="text-[10px] text-slate-600 font-bold mb-2 uppercase tracking-wider">Top 10 per conference · {teams.length} playoff-eligible teams</p>
          <TeamGrid teams={teams} selectedId={champion} onSelect={setChampion} locked={locked} oddsField="odds_championship" cols={5} />
        </Section>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Section title="West Champion" color="text-red-400" icon={<Trophy className="w-4 h-4" />} pts={FUTURES_BASE_POINTS.west_champ} oddsMult={westOdds}>
            <TeamGrid teams={westTeams} selectedId={westChamp} onSelect={setWestChamp} locked={locked} oddsField="odds_conference" cols={5} />
          </Section>
          <Section title="East Champion" color="text-blue-400" icon={<Trophy className="w-4 h-4" />} pts={FUTURES_BASE_POINTS.east_champ} oddsMult={eastOdds}>
            <TeamGrid teams={eastTeams} selectedId={eastChamp} onSelect={setEastChamp} locked={locked} oddsField="odds_conference" cols={5} />
          </Section>
        </div>

        {/* MVPs divider */}
        <div className="flex items-center gap-2">
          <div className="h-px flex-1 bg-slate-800" />
          <span className="text-[10px] text-slate-500 font-black uppercase tracking-widest">MVPs</span>
          <div className="h-px flex-1 bg-slate-800" />
        </div>

        <Section title="Finals MVP" color="text-orange-400" icon={<Star className="w-4 h-4" />} pts={FUTURES_BASE_POINTS.finals_mvp} oddsMult={odds.finals_mvp}>
          <MvpSearchInput value={finalsMvp} onChange={setFinalsMvp} locked={locked} placeholder="Search any playoff player…" conference="All" mvpType="finals" />
        </Section>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Section title="West Finals MVP" color="text-red-400" icon={<Star className="w-4 h-4" />} pts={FUTURES_BASE_POINTS.west_finals_mvp} oddsMult={odds.west_finals_mvp}>
            <MvpSearchInput value={westFinalsMvp} onChange={setWestFinalsMvp} locked={locked} placeholder="Search Western Conference players…" conference="West" mvpType="west" />
          </Section>
          <Section title="East Finals MVP" color="text-blue-400" icon={<Star className="w-4 h-4" />} pts={FUTURES_BASE_POINTS.east_finals_mvp} oddsMult={odds.east_finals_mvp}>
            <MvpSearchInput value={eastFinalsMvp} onChange={setEastFinalsMvp} locked={locked} placeholder="Search Eastern Conference players…" conference="East" mvpType="east" />
          </Section>
        </div>

        {/* Save Futures */}
        {!locked && (
          <button
            onClick={handleSave}
            disabled={saving || (!champion && !westChamp && !eastChamp && !finalsMvp)}
            className={`w-full py-4 rounded-2xl font-black text-lg tracking-wide transition-all ${
              saved ? 'bg-green-500 text-white shadow-lg shadow-green-500/25'
              : saving || (!champion && !westChamp && !eastChamp && !finalsMvp)
              ? 'bg-slate-800 text-slate-600 cursor-not-allowed'
              : 'bg-gradient-to-r from-orange-500 to-red-500 hover:from-orange-400 hover:to-red-400 text-white shadow-xl shadow-orange-500/30'
            }`}
          >
            {saved ? '✓ Futures Picks Saved!' : saving ? 'Saving...' : futuresData?.has_prediction ? 'Update Futures Picks' : 'Save Futures Picks'}
          </button>
        )}

        {/* ── Playoff Leaders ── */}
        <div className="mt-4">
          <div className="flex items-center gap-2 mb-2">
            <BarChart2 className="w-5 h-5 text-cyan-400" />
            <h2 className="text-xl font-black text-white uppercase tracking-wide">Playoff Leaders</h2>
            <ScoringTooltip content={
              <div className="space-y-2 text-xs">
                <p className="font-black text-white mb-1">Playoff Leaders — Elite Scoring</p>
                <p className="text-slate-500 text-[10px] mb-2">Tiered points — closer = more. Exact match earns full points.</p>
                {LEADER_CATEGORIES.map(c => {
                  const tiers = LEADERS_TIERS[c.statKey] || [];
                  return (
                    <div key={c.key} className="mb-1.5">
                      <p className={`font-black text-[11px] ${c.color} mb-0.5`}>{c.short}</p>
                      {tiers.map(([maxDelta, tierPts], i) => {
                        const prevDelta = i === 0 ? -1 : tiers[i-1][0];
                        const label = maxDelta === 0 ? '🎯 Exact' : prevDelta === 0 ? `✅ Off by 1${maxDelta > 1 ? `–${maxDelta}` : ''}` : `🟡 Off by ${prevDelta + 1}–${maxDelta}`;
                        return (
                          <div key={maxDelta} className="flex justify-between pl-2">
                            <span className="text-slate-400">{label}</span>
                            <span className="font-black text-white">{tierPts} pts</span>
                          </div>
                        );
                      })}
                    </div>
                  );
                })}
              </div>
            } />
            <span className="ml-2 px-2 py-0.5 rounded-full bg-cyan-500/20 border border-cyan-500/30 text-cyan-400 text-[10px] font-black uppercase tracking-wider">New</span>
          </div>
          <p className="text-slate-500 text-xs mb-5">Predict the highest total across the entire playoffs. <strong className="text-slate-400">Closer = more points.</strong> Picks lock with Futures.</p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {LEADER_CATEGORIES.map(cat => {
              const isCorrect  = leadersData?.[`is_correct_${cat.key.replace('top_', '')}`];
              const isBullseye = isCorrect === 2;
              const isClose    = isCorrect === 1;
              const isMiss     = isCorrect === 0;
              const tiers      = LEADERS_TIERS[cat.statKey] || [];
              return (
                <div key={cat.key} className={`bg-slate-900/50 border rounded-2xl p-4 ${
                  isBullseye ? 'border-green-500/50' : isClose ? 'border-yellow-500/40' : isMiss ? 'border-red-500/30' : 'border-slate-800'
                }`}>
                  <div className="flex items-center justify-between mb-2.5">
                    <span className={`text-sm font-black ${cat.color}`}>{cat.short}</span>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <span className="text-xs font-black text-slate-500 tabular-nums">{cat.pts} pts</span>
                      {isBullseye && <span className="text-base leading-none" title="Bullseye!">🎯</span>}
                      {isClose    && <span className="text-base leading-none" title="Close">🤏</span>}
                      {isMiss     && <span className="text-sm leading-none"   title="Miss">❌</span>}
                    </div>
                  </div>

                  <LeaderNumberInput
                    value={leaders[cat.key]}
                    onChange={v => setLeaders(prev => ({ ...prev, [cat.key]: v }))}
                    locked={leadersLocked}
                    placeholder={cat.example}
                  />

                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {tiers.map(([maxDelta, pts], i) => {
                      const prevDelta  = i === 0 ? -1 : tiers[i - 1][0];
                      const isExact    = maxDelta === 0;
                      const rangeLabel = isExact ? '🎯 Exact' : (prevDelta === 0 ? `🤏 ±${maxDelta}` : `🤏 ±${prevDelta + 1}–${maxDelta}`);
                      return (
                        <span key={maxDelta} className={`px-2 py-0.5 rounded border text-[10px] font-black tabular-nums ${
                          isExact ? 'bg-green-500/10 border-green-500/25 text-green-400' : 'bg-yellow-500/10 border-yellow-500/20 text-yellow-400'
                        }`}>{rangeLabel} = {pts}</span>
                      );
                    })}
                    <span className="px-2 py-0.5 rounded border text-[10px] font-black bg-slate-800 border-slate-700 text-slate-600">❌ = 0</span>
                  </div>

                  {playerLeaders && (playerLeaders[cat.refKey] || []).length > 0 && (
                    <div className="mt-3 pt-2.5 border-t border-slate-800/60">
                      <p className="text-[9px] font-black uppercase tracking-widest text-slate-600 mb-1.5">Reg. Season Leaders</p>
                      <div className="space-y-1">
                        {(playerLeaders[cat.refKey] || []).slice(0, 5).map((p, i) => (
                          <div key={p.player_id} className="flex items-center gap-2">
                            <span className="text-[10px] font-black text-slate-600 w-3">{i + 1}</span>
                            {p.logo_url ? (
                              <img src={p.logo_url} alt={p.team} className="w-4 h-4 shrink-0" onError={e => e.target.style.display = 'none'} />
                            ) : (
                              <span className="text-[9px] font-black text-slate-600 w-4 shrink-0">{p.team}</span>
                            )}
                            <span className="text-[11px] font-bold text-slate-400 flex-1 truncate">{p.name}</span>
                            <span className={`text-[11px] font-black tabular-nums ${cat.color}`}>{p[cat.statField]?.toFixed(1)}</span>
                            <span className="text-[9px] text-slate-600 font-bold">{cat.statLabel}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {!leadersLocked && (
            <button
              onClick={handleSaveLeaders}
              disabled={leadersSaving || !hasAnyLeaderPick}
              className={`w-full mt-4 py-4 rounded-2xl font-black text-lg tracking-wide transition-all ${
                leadersSaved ? 'bg-green-500 text-white shadow-lg shadow-green-500/25'
                : leadersSaving || !hasAnyLeaderPick ? 'bg-slate-800 text-slate-600 cursor-not-allowed'
                : 'bg-gradient-to-r from-cyan-500 to-blue-500 hover:from-cyan-400 hover:to-blue-400 text-white shadow-xl shadow-cyan-500/30'
              }`}
            >
              {leadersSaved ? '✓ Leaders Picks Saved!' : leadersSaving ? 'Saving...' : leadersData?.has_prediction ? 'Update Leaders Picks' : 'Save Leaders Picks'}
            </button>
          )}
        </div>
      </div>

      {saveError && (
        <div className="fixed bottom-20 md:bottom-6 left-3 right-3 md:left-auto md:right-6 md:max-w-sm z-50 flex items-center gap-3 px-4 py-3 rounded-2xl bg-red-950/95 border border-red-500/40 shadow-2xl backdrop-blur-sm">
          <span className="text-red-400 text-sm font-bold flex-1">⚠ {saveError}</span>
          <button onClick={() => setSaveError('')} className="text-red-400/60 hover:text-red-400 font-bold text-lg leading-none transition-colors shrink-0">×</button>
        </div>
      )}
    </div>
  );
};

export default FuturesPage;
