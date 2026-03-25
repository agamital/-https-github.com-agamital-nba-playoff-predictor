import React, { useState, useEffect } from 'react';
import { Shield, CheckCircle, Trophy, RefreshCw, Zap, Lock, Unlock, BarChart2, DollarSign, Target, ChevronDown, ChevronUp } from 'lucide-react';
import * as api from './services/api';

const Card = ({ children, className }) => (
  <div className={`bg-slate-900/50 border border-slate-800 rounded-lg backdrop-blur-sm ${className}`}>
    {children}
  </div>
);

const ConfirmModal = ({ message, onConfirm, onCancel }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
    <div className="bg-slate-900 border border-slate-700 rounded-2xl p-6 max-w-sm w-full mx-4 shadow-2xl">
      <p className="text-white font-black text-lg mb-2">Confirm Action</p>
      <p className="text-slate-400 text-sm mb-6">{message}</p>
      <div className="flex gap-3">
        <button onClick={onCancel}
          className="flex-1 py-2.5 rounded-xl border border-slate-700 text-slate-300 hover:bg-slate-800 font-bold text-sm transition-all">
          Cancel
        </button>
        <button onClick={onConfirm}
          className="flex-1 py-2.5 rounded-xl bg-orange-500 hover:bg-orange-600 text-white font-black text-sm transition-all">
          Confirm
        </button>
      </div>
    </div>
  </div>
);

const TeamButton = ({ team, selected, onClick }) => (
  <button
    onClick={onClick}
    className={`flex items-center gap-2 px-4 py-3 rounded-lg border-2 font-bold transition-all ${
      selected
        ? 'border-orange-500 bg-orange-500/20 text-white'
        : 'border-slate-700 bg-slate-800/50 text-slate-300 hover:border-slate-500'
    }`}
  >
    <img src={team.logo_url} alt={team.name} className="w-8 h-8" onError={(e) => e.target.style.display = 'none'} />
    <span>{team.abbreviation}</span>
  </button>
);

const SeriesCard = ({ series, onSave, onToggleLock }) => {
  const [winnerId, setWinnerId] = useState(series.winner_team_id || null);
  const [games, setGames] = useState(series.actual_games || null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [locking, setLocking] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const isCompleted = series.status === 'completed';
  const isLocked = series.status === 'locked';

  const handleSave = () => {
    if (!winnerId || !games) return;
    setConfirmOpen(true);
  };

  const doSave = async () => {
    setConfirmOpen(false);
    setSaving(true);
    try {
      await onSave(series.id, winnerId, games);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  };

  const handleToggleLock = async () => {
    setLocking(true);
    try {
      await onToggleLock(series.id, !isLocked);
    } finally {
      setLocking(false);
    }
  };

  const roundMult = { 'First Round': 1, 'Conference Semifinals': 2, 'Conference Finals': 3, 'NBA Finals': 4 };
  const mult = roundMult[series.round] || 1;

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <span className="text-xs font-bold text-orange-400 uppercase">{series.conference}</span>
          <span className="text-xs text-slate-500 ml-2">{series.round}</span>
          <span className="text-xs text-slate-600 ml-2">×{mult} multiplier</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">{series.prediction_count} picks</span>
          {isCompleted && <span className="px-2 py-0.5 rounded bg-green-500/20 text-green-400 text-xs font-bold">Done</span>}
          {isLocked && !isCompleted && <span className="px-2 py-0.5 rounded bg-yellow-500/20 text-yellow-400 text-xs font-bold">Locked</span>}
        </div>
      </div>

      <div className="flex items-center gap-3 mb-4">
        <img src={series.home_team.logo_url} alt={series.home_team.name} className="w-10 h-10" onError={(e) => e.target.style.display = 'none'} />
        <div className="flex-1"><p className="font-bold text-white text-sm">{series.home_team.name}</p></div>
        <span className="text-slate-600 font-black">VS</span>
        <div className="flex-1 text-right"><p className="font-bold text-white text-sm">{series.away_team.name}</p></div>
        <img src={series.away_team.logo_url} alt={series.away_team.name} className="w-10 h-10" onError={(e) => e.target.style.display = 'none'} />
      </div>

      {series.winner_abbreviation && (
        <div className="mb-3 px-3 py-2 rounded bg-green-500/10 border border-green-500/30 text-green-400 text-sm font-bold flex items-center gap-2">
          <CheckCircle className="w-4 h-4" />
          Result: {series.winner_abbreviation} won in {series.actual_games} games
        </div>
      )}

      <div className="mb-3">
        <p className="text-xs text-slate-400 mb-2 uppercase font-bold">Set Winner</p>
        <div className="flex gap-2">
          <TeamButton team={series.home_team} selected={winnerId === series.home_team.id} onClick={() => setWinnerId(series.home_team.id)} />
          <TeamButton team={series.away_team} selected={winnerId === series.away_team.id} onClick={() => setWinnerId(series.away_team.id)} />
        </div>
      </div>

      <div className="mb-4">
        <p className="text-xs text-slate-400 mb-2 uppercase font-bold">Games Played</p>
        <div className="flex gap-2">
          {[4, 5, 6, 7].map(g => (
            <button key={g} onClick={() => setGames(g)}
              className={`px-4 py-2 rounded-lg border-2 font-bold text-sm transition-all ${
                games === g ? 'border-orange-500 bg-orange-500/20 text-white' : 'border-slate-700 bg-slate-800/50 text-slate-300 hover:border-slate-500'
              }`}>{g}</button>
          ))}
        </div>
      </div>

      <div className="flex gap-2">
        <button onClick={handleSave} disabled={!winnerId || !games || saving}
          className={`flex-1 py-2 rounded-lg font-bold text-sm transition-all ${
            saved ? 'bg-green-500 text-white' :
            !winnerId || !games ? 'bg-slate-700 text-slate-500 cursor-not-allowed' :
            'bg-orange-500 hover:bg-orange-600 text-white'
          }`}>
          {saved ? 'Saved!' : saving ? 'Saving...' : 'Set Result'}
        </button>
        {!isCompleted && (
          <button onClick={handleToggleLock} disabled={locking}
            className={`px-3 py-2 rounded-lg font-bold text-sm transition-all disabled:opacity-50 ${
              isLocked
                ? 'bg-green-500/20 border border-green-500/40 text-green-400 hover:bg-green-500/30'
                : 'bg-yellow-500/20 border border-yellow-500/40 text-yellow-400 hover:bg-yellow-500/30'
            }`}>
            {locking ? '…' : isLocked ? <Unlock className="w-4 h-4" /> : <Lock className="w-4 h-4" />}
          </button>
        )}
      </div>
      {confirmOpen && (
        <ConfirmModal
          message={`Set result: ${winnerId === series.home_team.id ? series.home_team.name : series.away_team.name} wins in ${games} games. This will update all user scores.`}
          onConfirm={doSave}
          onCancel={() => setConfirmOpen(false)}
        />
      )}
    </Card>
  );
};

const PlayinCard = ({ game, onSave }) => {
  const [winnerId, setWinnerId] = useState(game.winner_id || null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const handleSave = async () => {
    if (!winnerId) return;
    setSaving(true);
    try {
      await onSave(game.id, winnerId);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <span className="text-xs font-bold text-purple-400 uppercase">{game.conference}</span>
          <span className="text-xs text-slate-500 ml-2">Play-In {game.game_type}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">{game.prediction_count} picks</span>
          {game.status === 'completed' && <span className="px-2 py-0.5 rounded bg-green-500/20 text-green-400 text-xs font-bold">Done</span>}
        </div>
      </div>

      <div className="flex items-center gap-3 mb-4">
        <img src={game.team1.logo_url} alt={game.team1.name} className="w-10 h-10" onError={(e) => e.target.style.display = 'none'} />
        <div className="flex-1"><p className="font-bold text-white text-sm">{game.team1.name}</p></div>
        <span className="text-slate-600 font-black">VS</span>
        <div className="flex-1 text-right"><p className="font-bold text-white text-sm">{game.team2.name}</p></div>
        <img src={game.team2.logo_url} alt={game.team2.name} className="w-10 h-10" onError={(e) => e.target.style.display = 'none'} />
      </div>

      {game.winner_abbreviation && (
        <div className="mb-3 px-3 py-2 rounded bg-green-500/10 border border-green-500/30 text-green-400 text-sm font-bold flex items-center gap-2">
          <CheckCircle className="w-4 h-4" /> Result: {game.winner_abbreviation} won
        </div>
      )}

      <div className="mb-4">
        <p className="text-xs text-slate-400 mb-2 uppercase font-bold">Set Winner</p>
        <div className="flex gap-2">
          <TeamButton team={game.team1} selected={winnerId === game.team1.id} onClick={() => setWinnerId(game.team1.id)} />
          <TeamButton team={game.team2} selected={winnerId === game.team2.id} onClick={() => setWinnerId(game.team2.id)} />
        </div>
      </div>

      <button onClick={handleSave} disabled={!winnerId || saving}
        className={`w-full py-2 rounded-lg font-bold text-sm transition-all ${
          saved ? 'bg-green-500 text-white' :
          !winnerId ? 'bg-slate-700 text-slate-500 cursor-not-allowed' :
          'bg-purple-500 hover:bg-purple-600 text-white'
        }`}>
        {saved ? 'Saved!' : saving ? 'Saving...' : 'Set Result'}
      </button>
    </Card>
  );
};

const FuturesLockCard = () => {
  const [locked, setLocked] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.getFuturesLockStatus().then(s => setLocked(s.locked)).catch(() => {});
  }, []);

  const toggle = async () => {
    setBusy(true);
    try {
      const res = await api.setFuturesLock(!locked);
      setLocked(res.locked);
    } catch (e) {
      alert('Error: ' + (e.response?.data?.detail || e.message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="p-5 mb-4">
      <div className="flex items-center gap-2 mb-3">
        {locked ? <Lock className="w-5 h-5 text-red-400" /> : <Unlock className="w-5 h-5 text-green-400" />}
        <h2 className="text-lg font-black text-white">Futures &amp; Leaders Lock</h2>
        {locked !== null && (
          <span className={`ml-auto px-2 py-0.5 rounded-full text-xs font-black ${locked ? 'bg-red-500/20 text-red-400' : 'bg-green-500/20 text-green-400'}`}>
            {locked ? 'LOCKED' : 'OPEN'}
          </span>
        )}
      </div>
      <p className="text-xs text-slate-400 mb-4">
        {locked ? 'Users cannot edit their futures or leaders picks.' : 'Users can still edit their futures and leaders picks.'}
      </p>
      <button onClick={toggle} disabled={busy || locked === null}
        className={`px-4 py-2 rounded-lg text-sm font-bold transition-all disabled:opacity-50 ${
          locked
            ? 'bg-green-500/20 border border-green-500/40 text-green-400 hover:bg-green-500/30'
            : 'bg-red-500/20 border border-red-500/40 text-red-400 hover:bg-red-500/30'
        }`}>
        {busy ? 'Updating…' : locked ? '🔓 Unlock Futures & Leaders' : '🔒 Lock Futures & Leaders'}
      </button>
    </Card>
  );
};

const OddsCard = () => {
  const [odds, setOdds] = useState({
    champion: 1.0, west_champ: 1.0, east_champ: 1.0,
    finals_mvp: 1.0, west_finals_mvp: 1.0, east_finals_mvp: 1.0,
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    api.getAdminOdds().then(setOdds).catch(() => {});
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.setAdminOdds(odds);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      alert('Error: ' + (e.response?.data?.detail || e.message));
    } finally {
      setSaving(false);
    }
  };

  const fields = [
    { key: 'champion',       label: 'NBA Champion',        base: 200 },
    { key: 'west_champ',     label: 'West Champion',       base: 100 },
    { key: 'east_champ',     label: 'East Champion',       base: 100 },
    { key: 'finals_mvp',     label: 'Finals MVP',          base: 80  },
    { key: 'west_finals_mvp',label: 'West Finals MVP',     base: 50  },
    { key: 'east_finals_mvp',label: 'East Finals MVP',     base: 50  },
  ];

  return (
    <Card className="p-5 mb-4">
      <button onClick={() => setExpanded(e => !e)} className="w-full flex items-center justify-between">
        <div className="flex items-center gap-2">
          <DollarSign className="w-5 h-5 text-yellow-400" />
          <h2 className="text-lg font-black text-white">Futures Odds Multipliers</h2>
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
      </button>
      {expanded && (
        <div className="mt-4">
          <p className="text-xs text-slate-400 mb-4">Base pts × multiplier = earned pts. Favorite=×1, Medium=×1.5, Underdog=×2-2.5</p>
          <div className="space-y-3">
            {fields.map(f => (
              <div key={f.key} className="flex items-center gap-3">
                <span className="text-sm text-slate-300 flex-1">{f.label}</span>
                <span className="text-xs text-slate-500">base {f.base}pts</span>
                <input
                  type="number"
                  min="0.5" max="5" step="0.5"
                  value={odds[f.key]}
                  onChange={e => setOdds(prev => ({ ...prev, [f.key]: parseFloat(e.target.value) || 1 }))}
                  className="w-20 px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm text-center focus:outline-none focus:border-orange-500"
                />
                <span className="text-xs text-orange-400 font-bold w-16 text-right">= {Math.round(f.base * odds[f.key])}pts</span>
              </div>
            ))}
          </div>
          <button onClick={handleSave} disabled={saving}
            className={`mt-4 w-full py-2 rounded-lg font-bold text-sm transition-all ${
              saved ? 'bg-green-500 text-white' : 'bg-orange-500 hover:bg-orange-600 text-white disabled:opacity-50'
            }`}>
            {saved ? '✓ Odds Saved!' : saving ? 'Saving...' : 'Save Odds Multipliers'}
          </button>
        </div>
      )}
    </Card>
  );
};

const FuturesResultsCard = ({ teams }) => {
  const [results, setResults] = useState({
    actual_champion_id: '', actual_west_champ_id: '', actual_east_champ_id: '',
    actual_finals_mvp: '', actual_west_finals_mvp: '', actual_east_finals_mvp: '',
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.setAdminFuturesResults(results);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      alert('Error: ' + (e.response?.data?.detail || e.message));
    } finally {
      setSaving(false);
    }
  };

  const teamSelect = (key, label) => (
    <div key={key} className="space-y-1">
      <label className="text-xs text-slate-400 font-bold uppercase">{label}</label>
      <select
        value={results[key] || ''}
        onChange={e => setResults(prev => ({ ...prev, [key]: e.target.value }))}
        className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm focus:outline-none focus:border-orange-500"
      >
        <option value="">— Not yet determined —</option>
        {teams.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
      </select>
    </div>
  );

  const playerInput = (key, label) => (
    <div key={key} className="space-y-1">
      <label className="text-xs text-slate-400 font-bold uppercase">{label}</label>
      <input
        type="text"
        value={results[key] || ''}
        onChange={e => setResults(prev => ({ ...prev, [key]: e.target.value }))}
        placeholder="Player name…"
        className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm focus:outline-none focus:border-orange-500"
      />
    </div>
  );

  return (
    <Card className="p-5 mb-4">
      <button onClick={() => setExpanded(e => !e)} className="w-full flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Target className="w-5 h-5 text-green-400" />
          <h2 className="text-lg font-black text-white">Set Futures Actual Results</h2>
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
      </button>
      {expanded && (
        <div className="mt-4 space-y-3">
          <p className="text-xs text-slate-400">Setting results will auto-calculate points for all users.</p>
          {teamSelect('actual_champion_id', 'NBA Champion')}
          {teamSelect('actual_west_champ_id', 'West Champion')}
          {teamSelect('actual_east_champ_id', 'East Champion')}
          {playerInput('actual_finals_mvp', 'Finals MVP')}
          {playerInput('actual_west_finals_mvp', 'West Finals MVP')}
          {playerInput('actual_east_finals_mvp', 'East Finals MVP')}
          <button onClick={handleSave} disabled={saving}
            className={`w-full py-2 rounded-lg font-bold text-sm transition-all ${
              saved ? 'bg-green-500 text-white' : 'bg-green-600 hover:bg-green-700 text-white disabled:opacity-50'
            }`}>
            {saved ? '✓ Results Saved & Scores Updated!' : saving ? 'Calculating...' : 'Save Results & Recalculate Scores'}
          </button>
        </div>
      )}
    </Card>
  );
};

const LeadersResultsCard = () => {
  const [results, setResults] = useState({
    top_scorer: null, top_assists: null, top_rebounds: null,
    top_threes: null, top_steals: null, top_blocks: null,
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    api.getAdminLeadersResults().then(data => {
      setResults({
        top_scorer:   data.scorer   || null,
        top_assists:  data.assists  || null,
        top_rebounds: data.rebounds || null,
        top_threes:   data.threes   || null,
        top_steals:   data.steals   || null,
        top_blocks:   data.blocks   || null,
      });
    }).catch(() => {});
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.setAdminLeadersResults(results);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      alert('Error: ' + (e.response?.data?.detail || e.message));
    } finally {
      setSaving(false);
    }
  };

  const fields = [
    { key: 'top_scorer',   label: 'Most Total Points',     pts: 100, example: 'e.g. 550' },
    { key: 'top_assists',  label: 'Most Total Assists',    pts: 70,  example: 'e.g. 200' },
    { key: 'top_rebounds', label: 'Most Total Rebounds',   pts: 70,  example: 'e.g. 250' },
    { key: 'top_threes',   label: 'Most 3-Pointers Made',  pts: 60,  example: 'e.g. 55'  },
    { key: 'top_steals',   label: 'Most Total Steals',     pts: 40,  example: 'e.g. 35'  },
    { key: 'top_blocks',   label: 'Most Total Blocks',     pts: 40,  example: 'e.g. 40'  },
  ];

  return (
    <Card className="p-5 mb-4">
      <button onClick={() => setExpanded(e => !e)} className="w-full flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BarChart2 className="w-5 h-5 text-cyan-400" />
          <h2 className="text-lg font-black text-white">Set Playoff Leaders Results</h2>
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
      </button>
      {expanded && (
        <div className="mt-4 space-y-3">
          <p className="text-xs text-slate-400">Enter the actual max stat value for each category. Scores update automatically.</p>
          {fields.map(f => (
            <div key={f.key} className="flex items-center gap-3">
              <div className="flex-1">
                <label className="text-xs text-slate-400 font-bold uppercase block mb-1">{f.label} ({f.pts}pts)</label>
                <input
                  type="number"
                  inputMode="numeric"
                  min="1"
                  step="1"
                  value={results[f.key] || ''}
                  onChange={e => {
                    const raw = e.target.value;
                    if (raw === '') { setResults(prev => ({ ...prev, [f.key]: null })); return; }
                    const n = parseInt(raw, 10);
                    if (Number.isFinite(n) && n > 0) setResults(prev => ({ ...prev, [f.key]: n }));
                  }}
                  placeholder={f.example}
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm focus:outline-none focus:border-cyan-500 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                />
              </div>
            </div>
          ))}
          <button onClick={handleSave} disabled={saving}
            className={`w-full py-2 rounded-lg font-bold text-sm transition-all ${
              saved ? 'bg-green-500 text-white' : 'bg-cyan-600 hover:bg-cyan-700 text-white disabled:opacity-50'
            }`}>
            {saved ? '✓ Leaders Saved & Scores Updated!' : saving ? 'Calculating...' : 'Save Leaders & Recalculate Scores'}
          </button>
        </div>
      )}
    </Card>
  );
};

const RegenerateMatchupsCard = ({ onDone }) => {
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const [confirmConf, setConfirmConf] = useState(null);

  const doRun = async (conference) => {
    setConfirmConf(null);
    setBusy(true);
    setStatus('Generating…');
    try {
      const res = await api.regenerateMatchups(conference === 'all' ? null : conference);
      setStatus(`Done! ${res.series_count} series, ${res.playin_count} play-in games`);
      onDone();
    } catch (e) {
      setStatus('Error: ' + (e.response?.data?.detail || e.message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="p-5 mb-8">
      <div className="flex items-center gap-2 mb-3">
        <Zap className="w-5 h-5 text-yellow-400" />
        <h2 className="text-lg font-black text-white">Regenerate Matchups</h2>
      </div>
      <p className="text-xs text-slate-400 mb-4">If seeds 3-6 are missing, use these buttons to create the missing playoff series and play-in games from live standings.</p>
      <div className="flex gap-2 flex-wrap">
        <button onClick={() => setConfirmConf('Western')} disabled={busy}
          className="px-4 py-2 rounded-lg bg-red-500/20 border border-red-500/40 text-red-400 hover:bg-red-500/30 text-sm font-bold transition-all disabled:opacity-50">
          Regenerate West
        </button>
        <button onClick={() => setConfirmConf('Eastern')} disabled={busy}
          className="px-4 py-2 rounded-lg bg-blue-500/20 border border-blue-500/40 text-blue-400 hover:bg-blue-500/30 text-sm font-bold transition-all disabled:opacity-50">
          Regenerate East
        </button>
        <button onClick={() => setConfirmConf('all')} disabled={busy}
          className="px-4 py-2 rounded-lg bg-orange-500/20 border border-orange-500/40 text-orange-400 hover:bg-orange-500/30 text-sm font-bold transition-all disabled:opacity-50">
          Regenerate All
        </button>
      </div>
      {status && <p className="mt-3 text-xs text-slate-300 font-bold">{status}</p>}
      {confirmConf !== null && (
        <ConfirmModal
          message={`Regenerate ${confirmConf === 'all' ? 'all' : confirmConf} matchups from live standings. This may overwrite existing matchups and will affect all users.`}
          onConfirm={() => doRun(confirmConf)}
          onCancel={() => setConfirmConf(null)}
        />
      )}
    </Card>
  );
};

const AdminPage = ({ currentUser }) => {
  const [series, setSeries] = useState([]);
  const [playin, setPlayin] = useState([]);
  const [allTeams, setAllTeams] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    load();
    api.getTeams().then(setAllTeams).catch(() => {});
  }, []);

  const load = async () => {
    setLoading(true);
    try {
      const [s, p] = await Promise.all([api.getAdminSeries(), api.getAdminPlayin()]);
      setSeries(s);
      setPlayin(p);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleSeriesResult = async (seriesId, winnerTeamId, actualGames) => {
    await api.setSeriesResult(seriesId, winnerTeamId, actualGames);
    const updated = await api.getAdminSeries();
    setSeries(updated);
  };

  const handleToggleLock = async (seriesId, locked) => {
    await api.lockSeries(seriesId, locked);
    const updated = await api.getAdminSeries();
    setSeries(updated);
  };

  const handlePlayinResult = async (gameId, winnerId) => {
    await api.setPlayinResult(gameId, winnerId);
    const [updatedPlayin, updatedSeries] = await Promise.all([api.getAdminPlayin(), api.getAdminSeries()]);
    setPlayin(updatedPlayin);
    setSeries(updatedSeries);
  };

  if (!currentUser || currentUser.role !== 'admin') {
    return (
      <div className="max-w-4xl mx-auto px-4 py-12 text-center">
        <Shield className="w-16 h-16 text-slate-600 mx-auto mb-4" />
        <h2 className="text-3xl font-bold text-white mb-4">Admin Only</h2>
        <p className="text-slate-400">You don't have access to this page</p>
      </div>
    );
  }

  // Group series by round
  const seriesByRound = series.reduce((acc, s) => {
    acc[s.round] = acc[s.round] || [];
    acc[s.round].push(s);
    return acc;
  }, {});
  const roundOrder = ['First Round', 'Conference Semifinals', 'Conference Finals', 'NBA Finals'];

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-4xl font-black text-white">Admin Panel</h1>
            <span className="px-3 py-1 rounded-full bg-orange-500/20 border border-orange-500/30 text-orange-400 text-xs font-bold uppercase">Admin</span>
          </div>
          <p className="text-slate-400">Set results — scores update automatically</p>
        </div>
        <button onClick={load} className="flex items-center gap-2 px-4 py-2 rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800/50 transition-all">
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      <FuturesLockCard />
      <OddsCard />
      <FuturesResultsCard teams={allTeams} />
      <LeadersResultsCard />
      <RegenerateMatchupsCard onDone={load} />

      {loading ? (
        <div className="text-center py-12">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-4 border-orange-500 border-t-transparent"></div>
        </div>
      ) : (
        <>
          {playin.length > 0 && (
            <div className="mb-10">
              <h2 className="text-2xl font-bold text-white mb-4 flex items-center gap-2">
                <Trophy className="w-6 h-6 text-purple-400" /> Play-In Games
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {playin.map(game => (
                  <PlayinCard key={game.id} game={game} onSave={handlePlayinResult} />
                ))}
              </div>
            </div>
          )}

          {roundOrder.map(round => {
            const roundSeries = seriesByRound[round];
            if (!roundSeries?.length) return null;
            return (
              <div key={round} className="mb-10">
                <h2 className="text-2xl font-bold text-white mb-4 flex items-center gap-2">
                  <Trophy className="w-6 h-6 text-orange-400" />
                  {round}
                  <span className="text-sm text-slate-500 font-normal ml-1">
                    (×{{'First Round':1,'Conference Semifinals':2,'Conference Finals':3,'NBA Finals':4}[round]} pts multiplier)
                  </span>
                </h2>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {roundSeries.map(s => (
                    <SeriesCard key={s.id} series={s} onSave={handleSeriesResult} onToggleLock={handleToggleLock} />
                  ))}
                </div>
              </div>
            );
          })}
        </>
      )}
    </div>
  );
};

export default AdminPage;
