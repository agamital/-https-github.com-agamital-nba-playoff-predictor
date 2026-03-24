import React, { useState, useEffect, useRef } from 'react';
import { Trophy, Lock, CheckCircle, Star, User, X, BarChart2, Info } from 'lucide-react';
import * as api from './services/api';
import { FUTURES_BASE_POINTS, LEADERS_POINTS } from './scoringConstants';

// ── All known playoff-eligible players (search suggestions) ──────────────────
const ALL_PLAYERS = [
  'Nikola Jokic', 'LeBron James', 'Stephen Curry', 'Giannis Antetokounmpo',
  'Luka Doncic', 'Jayson Tatum', 'Kevin Durant', 'Shai Gilgeous-Alexander',
  'Anthony Davis', 'Joel Embiid', 'Tyrese Haliburton', 'Donovan Mitchell',
  'Jimmy Butler', 'Victor Wembanyama', 'Cade Cunningham', 'Jalen Brunson',
  'Darius Garland', 'Scottie Barnes', 'Evan Mobley', 'Paolo Banchero',
  'Franz Wagner', 'Alperen Sengun', 'Jaren Jackson Jr.', "De'Aaron Fox",
  'Ja Morant', 'Zion Williamson', 'Brandon Ingram', 'Devin Booker',
  'James Harden', 'Kawhi Leonard', 'Paul George', 'Klay Thompson',
  'Draymond Green', 'Jamal Murray', 'Michael Porter Jr.', 'Austin Reaves',
  'Anthony Edwards', 'Karl-Anthony Towns', 'Rudy Gobert',
];

const LEADER_CATEGORIES = [
  { key: 'top_scorer',   label: 'Most Total Points',     color: 'text-yellow-400', pts: 100, icon: '🏀' },
  { key: 'top_assists',  label: 'Most Total Assists',    color: 'text-blue-400',   pts: 70,  icon: '🎯' },
  { key: 'top_rebounds', label: 'Most Total Rebounds',   color: 'text-green-400',  pts: 70,  icon: '💪' },
  { key: 'top_threes',   label: 'Most 3-Pointers Made',  color: 'text-purple-400', pts: 60,  icon: '3️⃣' },
  { key: 'top_steals',   label: 'Most Total Steals',     color: 'text-red-400',    pts: 40,  icon: '🤚' },
  { key: 'top_blocks',   label: 'Most Total Blocks',     color: 'text-orange-400', pts: 40,  icon: '🛡️' },
];

// ── Search/autocomplete player picker ────────────────────────────────────────
const PlayerSearchPicker = ({ value, onChange, locked, placeholder }) => {
  const [query, setQuery] = useState(value || '');
  const [open, setOpen] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => { setQuery(value || ''); }, [value]);

  const filtered = query.trim().length > 0
    ? ALL_PLAYERS.filter(s => s.toLowerCase().includes(query.toLowerCase()))
    : ALL_PLAYERS.slice(0, 10);

  const handleInput = (e) => {
    const v = e.target.value;
    setQuery(v);
    onChange(v);
    setOpen(true);
  };

  const handleSelect = (name) => {
    setQuery(name);
    onChange(name);
    setOpen(false);
  };

  const handleClear = () => {
    setQuery('');
    onChange('');
    inputRef.current?.focus();
  };

  return (
    <div className="relative">
      <div className="relative flex items-center">
        <User className="absolute left-3 w-4 h-4 text-slate-500 pointer-events-none" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={handleInput}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          disabled={locked}
          placeholder={placeholder || 'Search player name…'}
          className="w-full pl-9 pr-8 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm placeholder-slate-500 focus:outline-none focus:border-orange-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        />
        {query && !locked && (
          <button
            onMouseDown={handleClear}
            className="absolute right-3 text-slate-500 hover:text-white transition-colors"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
      {open && !locked && filtered.length > 0 && (
        <div className="absolute z-20 w-full mt-1 bg-slate-800 border border-slate-700 rounded-xl overflow-hidden shadow-xl max-h-52 overflow-y-auto">
          {filtered.map(name => (
            <button
              key={name}
              onMouseDown={() => handleSelect(name)}
              className={`w-full text-left px-4 py-2 text-sm transition-colors flex items-center gap-2 hover:bg-slate-700 ${
                value === name ? 'text-orange-400 font-bold bg-orange-500/10' : 'text-slate-300'
              }`}
            >
              <User className="w-3.5 h-3.5 shrink-0 text-slate-500" />
              {name}
            </button>
          ))}
        </div>
      )}
      {value && (
        <p className="mt-1.5 text-xs text-orange-400 font-bold flex items-center gap-1">
          <CheckCircle className="w-3 h-3" />
          {value}
        </p>
      )}
    </div>
  );
};

const TeamGrid = ({ teams, selectedId, onSelect, locked }) => (
  <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2">
    {teams.map(team => {
      const isSelected = selectedId === team.id;
      return (
        <button
          key={team.id}
          onClick={() => !locked && onSelect(team.id)}
          disabled={locked}
          className={`flex flex-col items-center gap-1.5 p-3 rounded-xl border-2 transition-all ${
            isSelected
              ? 'border-orange-500 bg-orange-500/15 shadow-lg shadow-orange-500/20'
              : locked
              ? 'border-slate-800 bg-slate-900/40 opacity-60 cursor-not-allowed'
              : 'border-slate-800 bg-slate-900/60 hover:border-slate-600 hover:bg-slate-800/60'
          }`}
        >
          <img
            src={team.logo_url}
            alt={team.abbreviation}
            className="w-10 h-10"
            onError={e => e.target.style.display = 'none'}
          />
          <span className={`text-[11px] font-black leading-tight text-center ${isSelected ? 'text-orange-400' : 'text-slate-300'}`}>
            {team.abbreviation}
          </span>
          {isSelected && <CheckCircle className="w-3 h-3 text-orange-400" />}
        </button>
      );
    })}
  </div>
);

const Section = ({ title, icon, color, children, pts, oddsMult }) => {
  const finalPts = pts ? Math.floor(pts * (oddsMult || 1)) : null;
  const showMult = oddsMult && oddsMult !== 1 && pts;
  return (
    <div className="bg-slate-900/50 border border-slate-800 rounded-2xl p-5">
      <div className={`flex items-center gap-2 mb-4 ${color}`}>
        {icon}
        <h3 className="text-base font-black uppercase tracking-wider flex-1">{title}</h3>
        {finalPts != null && (
          <span className="ml-auto text-xs font-black text-green-400 shrink-0">
            {showMult ? `${pts} × ${oddsMult} = ${finalPts} pts` : `${finalPts} pts`}
          </span>
        )}
      </div>
      {children}
    </div>
  );
};

const FuturesPage = ({ currentUser, onNavigate }) => {
  const [teams, setTeams] = useState([]);
  const [westTeams, setWestTeams] = useState([]);
  const [eastTeams, setEastTeams] = useState([]);
  const [loading, setLoading] = useState(true);
  const [odds, setOdds] = useState({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [existing, setExisting] = useState(null);
  const [globalLocked, setGlobalLocked] = useState(false);

  const [champion, setChampion] = useState(null);
  const [westChamp, setWestChamp] = useState(null);
  const [eastChamp, setEastChamp] = useState(null);
  const [finalsMvp, setFinalsMvp] = useState('');
  const [westFinalsMvp, setWestFinalsMvp] = useState('');
  const [eastFinalsMvp, setEastFinalsMvp] = useState('');

  // Leaders state
  const [leaders, setLeaders] = useState({
    top_scorer: '', top_assists: '', top_rebounds: '',
    top_threes: '', top_steals: '', top_blocks: '',
  });
  const [leadersSaving, setLeadersSaving] = useState(false);
  const [leadersSaved, setLeadersSaved] = useState(false);
  const [existingLeaders, setExistingLeaders] = useState(null);

  const locked = globalLocked || (existing?.locked || false);

  useEffect(() => {
    const load = async () => {
      try {
        api.getAdminOdds().then(setOdds).catch(() => {});
        const [allTeams, west, east, lockStatus] = await Promise.all([
          api.getTeams(),
          api.getTeams('Western'),
          api.getTeams('Eastern'),
          api.getFuturesLockStatus(),
        ]);
        setTeams(allTeams);
        setWestTeams(west);
        setEastTeams(east);
        setGlobalLocked(lockStatus.locked);
        if (currentUser) {
          const [fut, leadPred] = await Promise.all([
            api.getFutures(currentUser.user_id),
            api.getLeadersPrediction(currentUser.user_id),
          ]);
          if (fut.has_prediction) {
            setExisting(fut);
            setChampion(fut.champion_team_id);
            setWestChamp(fut.west_champ_team_id);
            setEastChamp(fut.east_champ_team_id);
            setFinalsMvp(fut.finals_mvp || '');
            setWestFinalsMvp(fut.west_finals_mvp || '');
            setEastFinalsMvp(fut.east_finals_mvp || '');
          }
          if (leadPred.has_prediction) {
            setExistingLeaders(leadPred);
            setLeaders({
              top_scorer:   leadPred.top_scorer   || '',
              top_assists:  leadPred.top_assists  || '',
              top_rebounds: leadPred.top_rebounds || '',
              top_threes:   leadPred.top_threes   || '',
              top_steals:   leadPred.top_steals   || '',
              top_blocks:   leadPred.top_blocks   || '',
            });
          }
        }
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [currentUser]);

  const handleSave = async () => {
    if (!currentUser || locked) return;
    setSaving(true);
    try {
      await api.saveFutures(currentUser.user_id, {
        champion_team_id: champion,
        west_champ_team_id: westChamp,
        east_champ_team_id: eastChamp,
        finals_mvp: finalsMvp,
        west_finals_mvp: westFinalsMvp,
        east_finals_mvp: eastFinalsMvp,
      });
      const fut = await api.getFutures(currentUser.user_id);
      if (fut.has_prediction) setExisting(fut);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (err) {
      alert('Error: ' + (err.response?.data?.detail || 'Unknown error'));
    } finally {
      setSaving(false);
    }
  };

  const handleSaveLeaders = async () => {
    if (!currentUser || locked) return;
    setLeadersSaving(true);
    try {
      await api.saveLeadersPrediction(currentUser.user_id, leaders);
      const l = await api.getLeadersPrediction(currentUser.user_id);
      if (l.has_prediction) setExistingLeaders(l);
      setLeadersSaved(true);
      setTimeout(() => setLeadersSaved(false), 2500);
    } catch (err) {
      alert('Error: ' + (err.response?.data?.detail || 'Unknown error'));
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

  const hasAnyLeaderPick = Object.values(leaders).some(v => v);

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
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
        {!locked && existing?.has_prediction && (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-green-500/10 border border-green-500/30">
            <CheckCircle className="w-4 h-4 text-green-400" />
            <span className="text-green-400 text-sm font-bold">Picks Saved — Edit Anytime</span>
          </div>
        )}
      </div>

      {/* Scoring info button */}
      <div className="flex justify-start mb-5">
        <button
          onClick={() => onNavigate && onNavigate('scoring')}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-slate-800/80 border border-slate-700 text-slate-400 hover:text-orange-400 hover:border-orange-500/40 text-xs font-bold transition-all"
        >
          <Info className="w-3.5 h-3.5" /> How scoring works
        </button>
      </div>

      {/* Current picks summary */}
      {existing?.has_prediction && (
        <div className="grid grid-cols-3 gap-3 mb-8">
          {[
            { label: 'Champion', team: existing.champion_team, correct: existing.is_correct_champion },
            { label: 'West Champ', team: existing.west_champ_team, correct: existing.is_correct_west },
            { label: 'East Champ', team: existing.east_champ_team, correct: existing.is_correct_east },
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
        {/* NBA Champion */}
        <Section title="NBA Champion" color="text-yellow-400" icon={<Trophy className="w-5 h-5" />} pts={FUTURES_BASE_POINTS.champion} oddsMult={odds.champion}>
          <TeamGrid teams={teams} selectedId={champion} onSelect={setChampion} locked={locked} />
        </Section>

        {/* Conference Champions */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Section title="West Champion" color="text-red-400" icon={<Trophy className="w-4 h-4" />} pts={FUTURES_BASE_POINTS.west_champ} oddsMult={odds.west_champ}>
            <TeamGrid teams={westTeams} selectedId={westChamp} onSelect={setWestChamp} locked={locked} />
          </Section>
          <Section title="East Champion" color="text-blue-400" icon={<Trophy className="w-4 h-4" />} pts={FUTURES_BASE_POINTS.east_champ} oddsMult={odds.east_champ}>
            <TeamGrid teams={eastTeams} selectedId={eastChamp} onSelect={setEastChamp} locked={locked} />
          </Section>
        </div>

        {/* MVPs */}
        <Section title="Finals MVP" color="text-orange-400" icon={<Star className="w-4 h-4" />} pts={FUTURES_BASE_POINTS.finals_mvp} oddsMult={odds.finals_mvp}>
          <PlayerSearchPicker value={finalsMvp} onChange={setFinalsMvp} locked={locked} placeholder="Search any player…" />
        </Section>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Section title="West Finals MVP" color="text-red-400" icon={<Star className="w-4 h-4" />} pts={FUTURES_BASE_POINTS.west_finals_mvp} oddsMult={odds.west_finals_mvp}>
            <PlayerSearchPicker value={westFinalsMvp} onChange={setWestFinalsMvp} locked={locked} placeholder="Search any player…" />
          </Section>
          <Section title="East Finals MVP" color="text-blue-400" icon={<Star className="w-4 h-4" />} pts={FUTURES_BASE_POINTS.east_finals_mvp} oddsMult={odds.east_finals_mvp}>
            <PlayerSearchPicker value={eastFinalsMvp} onChange={setEastFinalsMvp} locked={locked} placeholder="Search any player…" />
          </Section>
        </div>

        {/* Save Futures button */}
        {!locked && (
          <button
            onClick={handleSave}
            disabled={saving || (!champion && !westChamp && !eastChamp && !finalsMvp)}
            className={`w-full py-4 rounded-2xl font-black text-lg tracking-wide transition-all ${
              saved
                ? 'bg-green-500 text-white shadow-lg shadow-green-500/25'
                : saving || (!champion && !westChamp && !eastChamp && !finalsMvp)
                ? 'bg-slate-800 text-slate-600 cursor-not-allowed'
                : 'bg-gradient-to-r from-orange-500 to-red-500 hover:from-orange-400 hover:to-red-400 text-white shadow-xl shadow-orange-500/30'
            }`}
          >
            {saved ? '✓ Futures Picks Saved!' : saving ? 'Saving...' : existing?.has_prediction ? 'Update Futures Picks' : 'Save Futures Picks'}
          </button>
        )}

        {/* ── Playoff Leaders Section ── */}
        <div className="mt-4">
          <div className="flex items-center gap-2 mb-2">
            <BarChart2 className="w-5 h-5 text-cyan-400" />
            <h2 className="text-xl font-black text-white uppercase tracking-wide">Playoff Leaders</h2>
            <span className="ml-2 px-2 py-0.5 rounded-full bg-cyan-500/20 border border-cyan-500/30 text-cyan-400 text-[10px] font-black uppercase tracking-wider">New</span>
          </div>
          <p className="text-slate-400 text-sm mb-1">
            Predict which player will lead the entire playoffs in each statistical category.
          </p>
          <p className="text-slate-500 text-xs mb-5 font-bold">Exact match required. Picks lock with Futures.</p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {LEADER_CATEGORIES.map(cat => {
              const isCorrect = existingLeaders?.[`is_correct_${cat.key.replace('top_', '')}`];
              return (
                <div key={cat.key}
                  className={`bg-slate-900/50 border rounded-2xl p-4 ${
                    isCorrect === 1 ? 'border-green-500/40' :
                    isCorrect === 0 ? 'border-red-500/40' :
                    'border-slate-800'
                  }`}>
                  <div className="flex items-center gap-3 mb-3">
                    <div className="flex-1 min-w-0">
                      <p className={`text-xs font-black uppercase tracking-wider ${cat.color}`}>{cat.label}</p>
                      <div className="flex items-center gap-1.5 mt-0.5">
                        <span className={`text-xl font-black ${cat.color}`}>{cat.pts}</span>
                        <span className="text-slate-500 text-xs font-bold">pts</span>
                        <span className="text-[9px] font-black text-slate-500 bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5">exact match</span>
                      </div>
                    </div>
                    {isCorrect === 1 && <CheckCircle className="w-5 h-5 text-green-400 shrink-0" />}
                  </div>
                  <PlayerSearchPicker
                    value={leaders[cat.key]}
                    onChange={v => setLeaders(prev => ({ ...prev, [cat.key]: v }))}
                    locked={locked}
                    placeholder={`Who leads in ${cat.label.toLowerCase()}?`}
                  />
                </div>
              );
            })}
          </div>

          {/* Save Leaders button */}
          {!locked && (
            <button
              onClick={handleSaveLeaders}
              disabled={leadersSaving || !hasAnyLeaderPick}
              className={`w-full mt-4 py-4 rounded-2xl font-black text-lg tracking-wide transition-all ${
                leadersSaved
                  ? 'bg-green-500 text-white shadow-lg shadow-green-500/25'
                  : leadersSaving || !hasAnyLeaderPick
                  ? 'bg-slate-800 text-slate-600 cursor-not-allowed'
                  : 'bg-gradient-to-r from-cyan-500 to-blue-500 hover:from-cyan-400 hover:to-blue-400 text-white shadow-xl shadow-cyan-500/30'
              }`}
            >
              {leadersSaved ? '✓ Leaders Picks Saved!' : leadersSaving ? 'Saving...' : existingLeaders ? 'Update Leaders Picks' : 'Save Leaders Picks'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default FuturesPage;
