import React, { useState, useEffect, useCallback } from 'react';
import { Shield, CheckCircle, Trophy, RefreshCw, Zap, Lock, Unlock, BarChart2, DollarSign, Target, ChevronDown, ChevronUp, X, Users, Search, Pencil, Trash2, Save, RotateCcw, Activity, AlertTriangle, Database, Wifi, Mail, MailX } from 'lucide-react';
import * as api from './services/api';

const Card = ({ children, className }) => (
  <div className={`bg-slate-900/50 border border-slate-800 rounded-lg backdrop-blur-sm ${className}`}>
    {children}
  </div>
);

// Simple toast — renders at top-right; auto-dismisses after 3 s
const Toast = ({ toasts, dismiss }) => (
  <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2 pointer-events-none">
    {toasts.map(t => (
      <div key={t.id}
        className={`flex items-center gap-3 px-4 py-3 rounded-xl shadow-2xl border text-sm font-bold pointer-events-auto
          ${t.type === 'success'
            ? 'bg-green-950/95 border-green-500/40 text-green-300'
            : 'bg-red-950/95 border-red-500/40 text-red-300'}`}>
        {t.type === 'success' ? <CheckCircle className="w-4 h-4 shrink-0" /> : <X className="w-4 h-4 shrink-0" />}
        <span className="flex-1">{t.message}</span>
        <button onClick={() => dismiss(t.id)} className="opacity-60 hover:opacity-100 transition-opacity ml-1">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    ))}
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

const SeriesStatusBadge = ({ series }) => {
  if (series.status !== 'completed') {
    if (series.status === 'locked') return <span className="px-2 py-0.5 rounded bg-yellow-500/20 text-yellow-400 text-xs font-bold">Locked</span>;
    return <span className="px-2 py-0.5 rounded bg-slate-700 text-slate-400 text-xs font-bold">Active</span>;
  }
  if (series.manual_override) return <span className="px-2 py-0.5 rounded bg-amber-500/20 text-amber-400 text-xs font-bold">Manual Override</span>;
  if (series.is_advanced) return <span className="px-2 py-0.5 rounded bg-green-500/20 text-green-400 text-xs font-bold">Finished · Advanced</span>;
  return <span className="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 text-xs font-bold">Finished</span>;
};

const SeriesCard = ({ series, onSave, onToggleLock, onReset }) => {
  const [winnerId, setWinnerId] = useState(series.winner_team_id || null);
  const [games, setGames] = useState(series.actual_games || null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [locking, setLocking] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);

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
      await onSave(series.id, winnerId, games, isCompleted /* manual_override if re-saving */);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  };

  const doReset = async () => {
    setConfirmReset(false);
    setResetting(true);
    try {
      await onReset(series.id);
      setWinnerId(null);
      setGames(null);
    } finally {
      setResetting(false);
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
          <span className="text-xs text-slate-600 ml-2">×{mult}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">{series.prediction_count} picks</span>
          <SeriesStatusBadge series={series} />
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
          {series.manual_override && <span className="ml-auto text-[10px] text-amber-400 font-black bg-amber-500/15 px-1.5 py-0.5 rounded">OVERRIDE</span>}
        </div>
      )}

      <div className="mb-3">
        <p className="text-xs text-slate-400 mb-2 uppercase font-bold">{isCompleted ? 'Override Winner' : 'Set Winner'}</p>
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
            isCompleted ? 'bg-amber-500 hover:bg-amber-600 text-white' :
            'bg-orange-500 hover:bg-orange-600 text-white'
          }`}>
          {saved ? 'Saved!' : saving ? 'Saving...' : isCompleted ? 'Force Update' : 'Set Result'}
        </button>
        {isCompleted ? (
          <button onClick={() => setConfirmReset(true)} disabled={resetting}
            className="px-3 py-2 rounded-lg font-bold text-sm transition-all disabled:opacity-50 bg-red-500/20 border border-red-500/40 text-red-400 hover:bg-red-500/30"
            title="Reset result — reverts user scores">
            {resetting ? '…' : <RotateCcw className="w-4 h-4" />}
          </button>
        ) : (
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
          message={isCompleted
            ? `Override result: ${winnerId === series.home_team.id ? series.home_team.name : series.away_team.name} wins in ${games} games. All user scores will be recalculated.`
            : `Set result: ${winnerId === series.home_team.id ? series.home_team.name : series.away_team.name} wins in ${games} games. This will update all user scores.`}
          onConfirm={doSave}
          onCancel={() => setConfirmOpen(false)}
        />
      )}
      {confirmReset && (
        <ConfirmModal
          message={`Reset this series result? All user scores for this series will be zeroed out and totals recalculated. The bracket advancement will NOT be reversed.`}
          onConfirm={doReset}
          onCancel={() => setConfirmReset(false)}
        />
      )}
    </Card>
  );
};

const PlayinStatusBadge = ({ game }) => {
  if (game.status !== 'completed') {
    return <span className="px-2 py-0.5 rounded bg-slate-700 text-slate-400 text-xs font-bold">Active</span>;
  }
  if (game.is_advanced) {
    return <span className="px-2 py-0.5 rounded bg-green-500/20 text-green-400 text-xs font-bold">Finished · Advanced</span>;
  }
  if (game.game_type === '7v8') {
    return <span className="px-2 py-0.5 rounded bg-amber-500/20 text-amber-400 text-xs font-bold">Finished · Waiting for 9v10</span>;
  }
  return <span className="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 text-xs font-bold">Finished</span>;
};

const PlayinCard = ({ game, onSave, onReset }) => {
  const [winnerId, setWinnerId] = useState(game.winner_id || null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);

  const isCompleted = game.status === 'completed';

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

  const doReset = async () => {
    setConfirmReset(false);
    setResetting(true);
    try {
      await onReset(game.id);
      setWinnerId(null);
    } finally {
      setResetting(false);
    }
  };

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between mb-3">
        <div>
          <span className={`text-xs font-black uppercase ${game.game_type === 'elimination' ? 'text-rose-400' : 'text-purple-400'}`}>
            {game.type_label || game.game_type}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">{game.prediction_count} picks</span>
          <PlayinStatusBadge game={game} />
        </div>
      </div>

      {/* Next-step hint */}
      {game.next_step && (
        <p className="text-[10px] text-slate-600 mb-3 leading-relaxed">{game.next_step}</p>
      )}

      <div className="flex items-center gap-3 mb-4">
        <img src={game.team1.logo_url} alt={game.team1.name} className="w-10 h-10" onError={(e) => e.target.style.display = 'none'} />
        <div className="flex-1"><p className="font-bold text-white text-sm">{game.team1.name}</p></div>
        <span className="text-slate-600 font-black">VS</span>
        <div className="flex-1 text-right"><p className="font-bold text-white text-sm">{game.team2.name}</p></div>
        <img src={game.team2.logo_url} alt={game.team2.name} className="w-10 h-10" onError={(e) => e.target.style.display = 'none'} />
      </div>

      {game.winner_abbreviation && (
        <div className="mb-3 px-3 py-2 rounded bg-green-500/10 border border-green-500/30 text-green-400 text-sm font-bold flex items-center gap-2">
          <CheckCircle className="w-4 h-4" />
          {game.winner_abbreviation} won
          {game.is_advanced && <span className="ml-auto text-[10px] text-green-300/60">→ R1 created</span>}
        </div>
      )}

      <div className="mb-4">
        <p className="text-xs text-slate-400 mb-2 uppercase font-bold">{isCompleted ? 'Override Winner' : 'Set Winner'}</p>
        <div className="flex gap-2">
          <TeamButton team={game.team1} selected={winnerId === game.team1.id} onClick={() => setWinnerId(game.team1.id)} />
          <TeamButton team={game.team2} selected={winnerId === game.team2.id} onClick={() => setWinnerId(game.team2.id)} />
        </div>
      </div>

      <div className="flex gap-2">
        <button onClick={handleSave} disabled={!winnerId || saving}
          className={`flex-1 py-2 rounded-lg font-bold text-sm transition-all ${
            saved ? 'bg-green-500 text-white' :
            !winnerId ? 'bg-slate-700 text-slate-500 cursor-not-allowed' :
            isCompleted ? 'bg-amber-500 hover:bg-amber-600 text-white' :
            'bg-purple-500 hover:bg-purple-600 text-white'
          }`}>
          {saved ? 'Saved!' : saving ? 'Saving...' : isCompleted ? 'Force Update' : 'Set Result'}
        </button>
        {isCompleted && (
          <button onClick={() => setConfirmReset(true)} disabled={resetting}
            className="px-3 py-2 rounded-lg font-bold text-sm transition-all disabled:opacity-50 bg-red-500/20 border border-red-500/40 text-red-400 hover:bg-red-500/30"
            title="Reset result — reverts user scores">
            {resetting ? '…' : <RotateCcw className="w-4 h-4" />}
          </button>
        )}
      </div>

      {confirmReset && (
        <ConfirmModal
          message={`Reset this play-in result? All user scores for this game will be zeroed and recalculated. Downstream bracket changes (R1 series, Game 3) will NOT be reversed.`}
          onConfirm={doReset}
          onCancel={() => setConfirmReset(false)}
        />
      )}
    </Card>
  );
};

// Per-conference status banner for the play-in section
const PlayinConferenceBanner = ({ confGames }) => {
  const g7   = confGames.find(g => g.game_type === '7v8');
  const g9   = confGames.find(g => g.game_type === '9v10');
  const gelim = confGames.find(g => g.game_type === 'elimination');

  let text, color;
  if (gelim?.is_advanced) {
    text = 'All games complete — both R1 seeds set'; color = 'green';
  } else if (gelim?.status === 'completed') {
    text = 'Game 3 complete — run Sync Play-In to advance #8 seed'; color = 'amber';
  } else if (gelim) {
    text = 'Game 3 open for predictions'; color = 'rose';
  } else if (g7?.status === 'completed' && g9?.status === 'completed') {
    text = 'Both games done — run Sync Play-In to create Game 3'; color = 'amber';
  } else if (g7?.status === 'completed') {
    text = 'Waiting for Game 2 (9v10) to finish'; color = 'slate';
  } else if (g9?.status === 'completed') {
    text = 'Waiting for Game 1 (7v8) to finish'; color = 'slate';
  } else {
    text = 'Phase 1: Games 1 & 2 in progress'; color = 'slate';
  }

  const colorMap = {
    green: 'bg-green-500/10 border-green-500/30 text-green-400',
    amber: 'bg-amber-500/10 border-amber-500/30 text-amber-400',
    rose:  'bg-rose-500/10  border-rose-500/30  text-rose-400',
    slate: 'bg-slate-800/60 border-slate-700    text-slate-400',
  };

  return (
    <div className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-xs font-bold mb-3 ${colorMap[color]}`}>
      <span>{text}</span>
    </div>
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
    <Card className="p-5 mb-2">
      <div className="flex items-center gap-2 mb-3">
        {locked ? <Lock className="w-5 h-5 text-red-400" /> : <Unlock className="w-5 h-5 text-green-400" />}
        <h2 className="text-lg font-black text-white">Futures Lock</h2>
        {locked !== null && (
          <span className={`ml-auto px-2 py-0.5 rounded-full text-xs font-black ${locked ? 'bg-red-500/20 text-red-400' : 'bg-green-500/20 text-green-400'}`}>
            {locked ? 'LOCKED' : 'OPEN'}
          </span>
        )}
      </div>
      <p className="text-xs text-slate-400 mb-4">
        {locked ? 'Users cannot edit champion, conference, and MVP picks.' : 'Users can edit champion, conference, and MVP picks.'}
      </p>
      <button onClick={toggle} disabled={busy || locked === null}
        className={`px-4 py-2 rounded-lg text-sm font-bold transition-all disabled:opacity-50 ${
          locked
            ? 'bg-green-500/20 border border-green-500/40 text-green-400 hover:bg-green-500/30'
            : 'bg-red-500/20 border border-red-500/40 text-red-400 hover:bg-red-500/30'
        }`}>
        {busy ? 'Updating…' : locked ? '🔓 Unlock Futures' : '🔒 Lock Futures'}
      </button>
    </Card>
  );
};

const LeadersLockCard = () => {
  const [locked, setLocked] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.getLeadersLockStatus().then(s => setLocked(s.locked)).catch(() => {});
  }, []);

  const toggle = async () => {
    setBusy(true);
    try {
      const res = await api.setLeadersLock(!locked);
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
        <h2 className="text-lg font-black text-white">Playoff Leaders Lock</h2>
        {locked !== null && (
          <span className={`ml-auto px-2 py-0.5 rounded-full text-xs font-black ${locked ? 'bg-red-500/20 text-red-400' : 'bg-green-500/20 text-green-400'}`}>
            {locked ? 'LOCKED' : 'OPEN'}
          </span>
        )}
      </div>
      <p className="text-xs text-slate-400 mb-4">
        {locked ? 'Users cannot edit Playoff Leaders picks (most pts/ast/reb etc).' : 'Users can edit Playoff Leaders picks.'}
      </p>
      <button onClick={toggle} disabled={busy || locked === null}
        className={`px-4 py-2 rounded-lg text-sm font-bold transition-all disabled:opacity-50 ${
          locked
            ? 'bg-green-500/20 border border-green-500/40 text-green-400 hover:bg-green-500/30'
            : 'bg-red-500/20 border border-red-500/40 text-red-400 hover:bg-red-500/30'
        }`}>
        {busy ? 'Updating…' : locked ? '🔓 Unlock Leaders' : '🔒 Lock Leaders'}
      </button>
    </Card>
  );
};

// MVP-only odds (category-level multipliers for Finals MVP picks)
const OddsCard = () => {
  const [odds, setOdds] = useState({
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
    { key: 'finals_mvp',     label: 'Finals MVP',      base: 80 },
    { key: 'west_finals_mvp',label: 'West Finals MVP', base: 50 },
    { key: 'east_finals_mvp',label: 'East Finals MVP', base: 50 },
  ];

  return (
    <Card className="p-5 mb-4">
      <button onClick={() => setExpanded(e => !e)} className="w-full flex items-center justify-between">
        <div className="flex items-center gap-2">
          <DollarSign className="w-5 h-5 text-yellow-400" />
          <h2 className="text-lg font-black text-white">MVP Odds Multipliers</h2>
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
      </button>
      {expanded && (
        <div className="mt-4">
          <p className="text-xs text-slate-400 mb-4">Base pts × multiplier = earned pts for MVP picks.</p>
          <div className="space-y-3">
            {fields.map(f => (
              <div key={f.key} className="flex items-center gap-3">
                <span className="text-sm text-slate-300 flex-1">{f.label}</span>
                <span className="text-xs text-slate-500">base {f.base}pts</span>
                <input
                  type="number"
                  min="0.5" max="5" step="0.25"
                  value={odds[f.key] ?? 1}
                  onChange={e => setOdds(prev => ({ ...prev, [f.key]: parseFloat(e.target.value) || 1 }))}
                  className="w-20 px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm text-center focus:outline-none focus:border-orange-500"
                />
                <span className="text-xs text-orange-400 font-bold w-16 text-right">= {Math.round(f.base * (odds[f.key] ?? 1))}pts</span>
              </div>
            ))}
          </div>
          <button onClick={handleSave} disabled={saving}
            className={`mt-4 w-full py-2 rounded-lg font-bold text-sm transition-all ${
              saved ? 'bg-green-500 text-white' : 'bg-orange-500 hover:bg-orange-600 text-white disabled:opacity-50'
            }`}>
            {saved ? '✓ MVP Odds Saved!' : saving ? 'Saving...' : 'Save MVP Odds'}
          </button>
        </div>
      )}
    </Card>
  );
};

// Per-team championship and conference odds
const TeamOddsCard = ({ addToast }) => {
  const [teams, setTeams]     = useState([]);
  // Store raw strings so user can type freely (e.g. "1.3" mid-entry)
  const [edits, setEdits]     = useState({}); // { team_id: { champ: string, conf: string } }
  const [savingId, setSavingId] = useState(null); // team_id currently being saved
  const [savedIds, setSavedIds] = useState(new Set());
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!expanded) return; // lazy-load only when opened
    api.getAdminTeamOdds().then(data => {
      setTeams(data);
      const init = {};
      data.forEach(t => {
        init[t.team_id] = {
          champ: String(t.odds_championship ?? 1.0),
          conf:  String(t.odds_conference   ?? 1.0),
        };
      });
      setEdits(init);
    }).catch(e => addToast('Failed to load team odds: ' + (e.message || e), 'error'));
  }, [expanded]);

  const handleChange = (teamId, field, value) => {
    setEdits(prev => ({ ...prev, [teamId]: { ...prev[teamId], [field]: value } }));
  };

  const handleSaveOne = async (teamId) => {
    const vals = edits[teamId];
    const champ = parseFloat(vals?.champ);
    const conf  = parseFloat(vals?.conf);
    if (isNaN(champ) || isNaN(conf) || champ <= 0 || conf <= 0) {
      addToast('Odds must be a positive number (e.g. 1.35)', 'error');
      return;
    }
    setSavingId(teamId);
    try {
      const result = await api.updateTeamOdds(teamId, champ, conf);
      // Sync back the confirmed values from the server
      setEdits(prev => ({
        ...prev,
        [teamId]: { champ: String(result.odds_championship), conf: String(result.odds_conference) },
      }));
      setSavedIds(prev => new Set([...prev, teamId]));
      setTimeout(() => setSavedIds(prev => { const n = new Set(prev); n.delete(teamId); return n; }), 2500);
      addToast(`✓ ${result.abbreviation} odds updated — Champ ×${result.odds_championship} · Conf ×${result.odds_conference}`, 'success');
    } catch (e) {
      addToast('Save failed: ' + (e.response?.data?.detail || e.message), 'error');
    } finally {
      setSavingId(null);
    }
  };

  const handleSaveAll = async () => {
    const updates = Object.entries(edits).map(([id, vals]) => ({
      team_id: parseInt(id),
      odds_championship: parseFloat(vals.champ) || 1.0,
      odds_conference:   parseFloat(vals.conf)  || 1.0,
    }));
    setSavingId('all');
    try {
      await api.setAdminTeamOdds(updates);
      addToast(`✓ All ${updates.length} teams saved successfully`, 'success');
    } catch (e) {
      addToast('Bulk save failed: ' + (e.response?.data?.detail || e.message), 'error');
    } finally {
      setSavingId(null);
    }
  };

  const preview = (raw, base) => {
    const n = parseFloat(raw);
    return isNaN(n) ? '—' : Math.round(base * n) + 'pt';
  };

  const conferences = ['Eastern', 'Western'];

  return (
    <Card className="p-5 mb-4">
      <button onClick={() => setExpanded(e => !e)} className="w-full flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Trophy className="w-5 h-5 text-amber-400" />
          <h2 className="text-lg font-black text-white">Team Championship Odds</h2>
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
      </button>
      {expanded && (
        <div className="mt-4">
          <p className="text-xs text-slate-400 mb-1">
            Decimal multiplier per team. <span className="text-amber-400">Champion base 200 pts · Conf base 100 pts.</span>
          </p>
          <p className="text-xs text-slate-500 mb-4">
            Example: OKC × 1.35 → 270 pts if they win championship. Hit <strong>Save</strong> per row or <strong>Save All</strong> at the bottom.
          </p>

          {/* Column headers */}
          <div className="hidden sm:grid grid-cols-[2rem_3rem_1fr_1fr_5rem] gap-2 mb-2 px-1">
            <span />
            <span />
            <span className="text-[10px] font-black text-amber-400/70 uppercase tracking-wider text-center">Champ ×200</span>
            <span className="text-[10px] font-black text-cyan-400/70 uppercase tracking-wider text-center">Conf ×100</span>
            <span />
          </div>

          {conferences.map(conf => {
            const confTeams = teams.filter(t => t.conference === conf);
            if (!confTeams.length) return null;
            return (
              <div key={conf} className="mb-5">
                <p className="text-xs font-black text-slate-400 uppercase tracking-wider mb-2 border-b border-slate-800 pb-1">{conf}</p>
                <div className="space-y-2">
                  {confTeams.map(t => {
                    const vals   = edits[t.team_id] || { champ: '1.0', conf: '1.0' };
                    const isSaving = savingId === t.team_id;
                    const wasSaved = savedIds.has(t.team_id);
                    return (
                      <div key={t.team_id} className={`flex items-center gap-2 p-1.5 rounded-lg transition-colors ${wasSaved ? 'bg-green-500/5 border border-green-500/20' : ''}`}>
                        {/* Logo */}
                        <img src={t.logo_url} alt={t.abbreviation} className="w-6 h-6 shrink-0"
                             onError={e => e.target.style.display='none'} />
                        {/* Abbrev */}
                        <span className="text-sm text-slate-300 w-10 font-bold shrink-0">{t.abbreviation}</span>

                        {/* Championship odds */}
                        <div className="flex items-center gap-1 flex-1">
                          <input
                            type="number" min="0.01" max="100" step="0.01"
                            value={vals.champ}
                            onChange={e => handleChange(t.team_id, 'champ', e.target.value)}
                            className="w-20 px-2 py-1.5 bg-slate-800 border border-slate-700 rounded text-white text-sm text-center focus:outline-none focus:border-amber-500 transition-colors"
                          />
                          <span className="text-[10px] text-amber-400 font-bold w-12 text-right shrink-0">
                            {preview(vals.champ, 200)}
                          </span>
                        </div>

                        {/* Conference odds */}
                        <div className="flex items-center gap-1 flex-1">
                          <input
                            type="number" min="0.01" max="100" step="0.01"
                            value={vals.conf}
                            onChange={e => handleChange(t.team_id, 'conf', e.target.value)}
                            className="w-20 px-2 py-1.5 bg-slate-800 border border-slate-700 rounded text-white text-sm text-center focus:outline-none focus:border-cyan-500 transition-colors"
                          />
                          <span className="text-[10px] text-cyan-400 font-bold w-12 text-right shrink-0">
                            {preview(vals.conf, 100)}
                          </span>
                        </div>

                        {/* Per-row save button */}
                        <button
                          onClick={() => handleSaveOne(t.team_id)}
                          disabled={isSaving || savingId === 'all'}
                          className={`shrink-0 px-3 py-1.5 rounded-lg text-xs font-black transition-all ${
                            wasSaved
                              ? 'bg-green-500/20 border border-green-500/40 text-green-400'
                              : isSaving
                              ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                              : 'bg-slate-800 hover:bg-amber-500 hover:text-white border border-slate-700 hover:border-amber-500 text-slate-300 transition-colors'
                          }`}
                        >
                          {wasSaved ? '✓' : isSaving ? '…' : 'Save'}
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}

          <button
            onClick={handleSaveAll}
            disabled={savingId !== null}
            className={`w-full py-2.5 rounded-lg font-bold text-sm transition-all mt-2 ${
              savingId === null
                ? 'bg-amber-500 hover:bg-amber-600 text-white'
                : 'bg-slate-700 text-slate-400 cursor-not-allowed'
            }`}
          >
            {savingId === 'all' ? 'Saving all teams…' : 'Save All Teams at Once'}
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

const UserManagementCard = ({ currentUser, addToast }) => {
  const [expanded, setExpanded]   = useState(false);
  const [users, setUsers]         = useState([]);
  const [loading, setLoading]     = useState(false);
  const [search, setSearch]       = useState('');
  const [editId, setEditId]       = useState(null);   // user id being edited
  const [editVals, setEditVals]   = useState({});     // { username, points }
  const [savingId, setSavingId]   = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null); // { id, username }

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getAdminUsers(currentUser.user_id);
      setUsers(data);
    } catch (e) {
      addToast('Failed to load users: ' + (e.response?.data?.detail || e.message), 'error');
    } finally {
      setLoading(false);
    }
  }, [currentUser.user_id]);

  useEffect(() => {
    if (expanded) load();
  }, [expanded]);

  const startEdit = (user) => {
    setEditId(user.id);
    setEditVals({ username: user.username, points: String(user.points) });
  };

  const cancelEdit = () => { setEditId(null); setEditVals({}); };

  const saveEdit = async (userId) => {
    const u = editVals;
    const pts = parseInt(u.points, 10);
    if (!u.username?.trim()) { addToast('Username cannot be empty', 'error'); return; }
    if (isNaN(pts) || pts < 0) { addToast('Points must be a non-negative integer', 'error'); return; }
    setSavingId(userId);
    try {
      await api.updateAdminUser(currentUser.user_id, userId, {
        username: u.username.trim(),
        points:   pts,
      });
      addToast('User updated', 'success');
      setEditId(null);
      await load();
    } catch (e) {
      addToast('Update failed: ' + (e.response?.data?.detail || e.message), 'error');
    } finally {
      setSavingId(null);
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    try {
      const res = await api.deleteAdminUser(currentUser.user_id, deleteTarget.id);
      addToast(res.message || 'User deleted', 'success');
      setDeleteTarget(null);
      await load();
    } catch (e) {
      addToast('Delete failed: ' + (e.response?.data?.detail || e.message), 'error');
      setDeleteTarget(null);
    }
  };

  const toggleReminderOptOut = async (userId, currentOptOut) => {
    try {
      await api.toggleUserReminderOptOut(currentUser.user_id, userId, !currentOptOut);
      addToast(!currentOptOut ? 'Email reminders disabled for user' : 'Email reminders enabled for user', 'success');
      setUsers(prev => prev.map(u => u.id === userId ? { ...u, reminder_opt_out: !currentOptOut } : u));
    } catch (e) {
      addToast('Failed: ' + (e.response?.data?.detail || e.message), 'error');
    }
  };

  const filtered = users.filter(u =>
    u.username.toLowerCase().includes(search.toLowerCase()) ||
    u.email.toLowerCase().includes(search.toLowerCase())
  );

  const fmt = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  };

  return (
    <Card className="p-5 mb-4">
      {/* Header / toggle */}
      <button onClick={() => setExpanded(e => !e)} className="w-full flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Users className="w-5 h-5 text-violet-400" />
          <h2 className="text-lg font-black text-white">User Management</h2>
          {users.length > 0 && (
            <span className="ml-1 px-2 py-0.5 rounded-full bg-violet-500/20 text-violet-400 text-[10px] font-black">
              {users.length}
            </span>
          )}
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
      </button>

      {expanded && (
        <div className="mt-4">
          {/* Search + refresh */}
          <div className="flex gap-2 mb-4">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
              <input
                type="text"
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Search by username or email…"
                className="w-full pl-9 pr-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm placeholder-slate-500 focus:outline-none focus:border-violet-500"
              />
            </div>
            <button
              onClick={load}
              disabled={loading}
              className="px-3 py-2 rounded-lg border border-slate-700 text-slate-400 hover:bg-slate-800 disabled:opacity-50 transition-all"
              title="Refresh"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>

          {loading && !users.length ? (
            <div className="text-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-2 border-violet-500 border-t-transparent mx-auto" />
            </div>
          ) : (
            <div className="overflow-x-auto rounded-xl border border-slate-800">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[10px] font-black uppercase tracking-wider text-slate-500 border-b border-slate-800 bg-slate-900/60">
                    <th className="text-left px-3 py-2.5">Username</th>
                    <th className="text-left px-3 py-2.5 hidden sm:table-cell">Email</th>
                    <th className="text-right px-3 py-2.5">Points</th>
                    <th className="text-center px-3 py-2.5 hidden md:table-cell">Picks</th>
                    <th className="text-center px-3 py-2.5 hidden lg:table-cell">Joined</th>
                    <th className="text-center px-3 py-2.5">Role</th>
                    <th className="text-center px-3 py-2.5" title="Email reminders">
                      <Mail className="w-3.5 h-3.5 inline-block" />
                    </th>
                    <th className="text-right px-3 py-2.5">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {filtered.length === 0 && (
                    <tr>
                      <td colSpan={8} className="text-center text-slate-600 py-6 text-sm">
                        {search ? 'No users match your search.' : 'No users found.'}
                      </td>
                    </tr>
                  )}
                  {filtered.map(user => {
                    const isEditing = editId === user.id;
                    const isSelf    = user.id === currentUser.user_id;
                    return (
                      <tr key={user.id} className={`transition-colors ${isEditing ? 'bg-violet-500/5' : 'hover:bg-slate-800/30'}`}>
                        {/* Username */}
                        <td className="px-3 py-2.5">
                          {isEditing ? (
                            <input
                              value={editVals.username}
                              onChange={e => setEditVals(p => ({ ...p, username: e.target.value }))}
                              className="w-full px-2 py-1 bg-slate-800 border border-violet-500/50 rounded text-white text-sm focus:outline-none focus:border-violet-400"
                            />
                          ) : (
                            <div className="flex items-center gap-1.5">
                              <span className="font-bold text-white">{user.username}</span>
                              {isSelf && <span className="text-[9px] text-violet-400 font-black bg-violet-500/15 px-1 rounded">you</span>}
                            </div>
                          )}
                        </td>
                        {/* Email */}
                        <td className="px-3 py-2.5 text-slate-500 text-xs hidden sm:table-cell truncate max-w-[160px]">
                          {user.email}
                        </td>
                        {/* Points */}
                        <td className="px-3 py-2.5 text-right">
                          {isEditing ? (
                            <input
                              type="number"
                              min="0"
                              value={editVals.points}
                              onChange={e => setEditVals(p => ({ ...p, points: e.target.value }))}
                              className="w-20 px-2 py-1 bg-slate-800 border border-violet-500/50 rounded text-white text-sm text-right focus:outline-none focus:border-violet-400 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                            />
                          ) : (
                            <span className="font-black text-orange-400 tabular-nums">{user.points.toLocaleString()}</span>
                          )}
                        </td>
                        {/* Picks */}
                        <td className="px-3 py-2.5 text-center text-slate-500 text-xs hidden md:table-cell">
                          {user.prediction_count}
                        </td>
                        {/* Joined */}
                        <td className="px-3 py-2.5 text-center text-slate-500 text-xs hidden lg:table-cell">
                          {fmt(user.created_at)}
                        </td>
                        {/* Role */}
                        <td className="px-3 py-2.5 text-center">
                          <span className={`text-[10px] font-black px-1.5 py-0.5 rounded ${
                            user.role === 'admin'
                              ? 'bg-orange-500/20 text-orange-400'
                              : 'bg-slate-700 text-slate-500'
                          }`}>
                            {user.role}
                          </span>
                        </td>
                        {/* Email reminders toggle */}
                        <td className="px-3 py-2.5 text-center">
                          <button
                            onClick={() => toggleReminderOptOut(user.id, user.reminder_opt_out)}
                            title={user.reminder_opt_out ? 'Reminders OFF — click to enable' : 'Reminders ON — click to disable'}
                            className={`p-1.5 rounded-lg border transition-colors ${
                              user.reminder_opt_out
                                ? 'bg-red-500/10 border-red-500/30 text-red-400 hover:bg-red-500/20'
                                : 'bg-green-500/10 border-green-500/30 text-green-400 hover:bg-green-500/20'
                            }`}
                          >
                            {user.reminder_opt_out
                              ? <MailX className="w-3.5 h-3.5" />
                              : <Mail className="w-3.5 h-3.5" />
                            }
                          </button>
                        </td>
                        {/* Actions */}
                        <td className="px-3 py-2.5">
                          <div className="flex items-center justify-end gap-1.5">
                            {isEditing ? (
                              <>
                                <button
                                  onClick={() => saveEdit(user.id)}
                                  disabled={savingId === user.id}
                                  className="p-1.5 rounded-lg bg-green-500/20 border border-green-500/30 text-green-400 hover:bg-green-500/30 transition-colors disabled:opacity-50"
                                  title="Save"
                                >
                                  <Save className="w-3.5 h-3.5" />
                                </button>
                                <button
                                  onClick={cancelEdit}
                                  className="p-1.5 rounded-lg bg-slate-700 border border-slate-600 text-slate-400 hover:bg-slate-600 transition-colors"
                                  title="Cancel"
                                >
                                  <X className="w-3.5 h-3.5" />
                                </button>
                              </>
                            ) : (
                              <>
                                <button
                                  onClick={() => startEdit(user)}
                                  className="p-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-400 hover:border-violet-500/50 hover:text-violet-400 transition-colors"
                                  title="Edit"
                                >
                                  <Pencil className="w-3.5 h-3.5" />
                                </button>
                                <button
                                  onClick={() => !isSelf && setDeleteTarget(user)}
                                  disabled={isSelf}
                                  className="p-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-400 hover:border-red-500/50 hover:text-red-400 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                                  title={isSelf ? "Can't delete yourself" : "Delete user"}
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {filtered.length > 0 && !loading && (
            <p className="text-[10px] text-slate-600 mt-2 text-right">
              {filtered.length} of {users.length} users shown
            </p>
          )}
        </div>
      )}

      {/* Delete confirmation modal */}
      {deleteTarget && (
        <ConfirmModal
          message={`Permanently delete "${deleteTarget.username}"? This removes their account, all series picks, play-in picks, futures, and leaders predictions. This cannot be undone.`}
          onConfirm={confirmDelete}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </Card>
  );
};

// NBA API URL + headers for browser-side fetch (bypasses Railway IP block)
const _NBA_BROWSER_URL = 'https://stats.nba.com/stats/leaguestandingsv3?LeagueID=00&Season=2025-26&SeasonType=Regular%20Season';
const _NBA_BROWSER_HEADERS = {
  'Accept': 'application/json, text/plain, */*',
  'Accept-Language': 'en-US,en;q=0.9',
  'Origin': 'https://www.nba.com',
  'Referer': 'https://www.nba.com/',
  'x-nba-stats-origin': 'stats',
  'x-nba-stats-token': 'true',
};

const PlayerStatsSyncCard = ({ addToast }) => {
  const [syncing, setSyncing] = useState(false);
  const [result, setResult]   = useState(null);

  const run = async () => {
    setSyncing(true);
    setResult(null);
    try {
      const res = await api.syncPlayerStats();
      setResult(res);
      addToast(res.success ? `Player stats synced ✓ (${res.count || 0} players)` : `Sync failed: ${res.error}`, res.success ? 'success' : 'error');
    } catch (e) {
      const msg = e.response?.data?.detail || e.message;
      setResult({ error: msg });
      addToast('Sync error: ' + msg, 'error');
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-700 rounded-xl p-5 mb-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <h3 className="text-white font-bold text-base">Player Stats Sync</h3>
          <p className="text-slate-400 text-xs mt-0.5">
            Syncs PPG / APG / RPG from NBA API into the player_stats table.
            Run this to fix MVP search ordering by PPG.
          </p>
        </div>
        <button
          onClick={run}
          disabled={syncing}
          className="shrink-0 px-4 py-2 rounded-lg text-sm font-bold bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white transition-colors"
        >
          {syncing ? 'Syncing…' : 'Sync Now'}
        </button>
      </div>
      {result && (
        <div className="mt-3 p-3 rounded-lg bg-slate-800 text-xs font-mono text-slate-300 break-all">
          {result.error
            ? <span className="text-red-400">{result.error}</span>
            : <span className="text-green-400">{JSON.stringify(result)}</span>}
        </div>
      )}
    </div>
  );
};

const ReminderCard = ({ addToast }) => {
  const [running, setRunning]     = useState(false);
  const [testing, setTesting]     = useState(false);
  const [testEmail, setTestEmail] = useState('');
  const [result, setResult]       = useState(null);

  const trigger = async () => {
    setRunning(true);
    setResult(null);
    try {
      const res = await api.triggerReminderJob();
      setResult(res);
      addToast('Reminder job queued ✓', 'success');
    } catch (e) {
      const msg = e.response?.data?.detail || e.message;
      setResult({ error: msg });
      addToast('Reminder job error: ' + msg, 'error');
    } finally {
      setRunning(false);
    }
  };

  const sendTest = async () => {
    const addr = testEmail.trim();
    if (!addr || !addr.includes('@')) {
      addToast('Enter a valid email address first', 'error');
      return;
    }
    setTesting(true);
    setResult(null);
    try {
      const res = await api.sendTestEmail(addr);
      setResult(res);
      addToast(`Test email sent to ${addr} ✓`, 'success');
    } catch (e) {
      const msg = e.response?.data?.detail || e.message;
      setResult({ error: msg });
      addToast('Test email error: ' + msg, 'error');
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-700 rounded-xl p-5 mb-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <h3 className="text-white font-bold text-base">Daily Email Reminders</h3>
          <p className="text-slate-400 text-xs mt-0.5">
            Sends Resend emails to users with missing picks for unstarted matchups.
            20-hour dedup per user. Vercel Cron fires daily at 10:00 AM IDT (07:00 UTC).
          </p>
        </div>
        <button
          onClick={trigger}
          disabled={running}
          className="shrink-0 px-4 py-2 rounded-lg text-sm font-bold bg-orange-600 hover:bg-orange-500 disabled:opacity-50 text-white transition-colors"
        >
          {running ? 'Running…' : 'Run Now'}
        </button>
      </div>

      {/* Test email row */}
      <div className="mt-4 flex gap-2 items-center">
        <input
          type="text"
          autoComplete="off"
          value={testEmail}
          onChange={e => setTestEmail(e.target.value)}
          placeholder="test@example.com"
          className="flex-1 bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-orange-500"
        />
        <button
          onClick={sendTest}
          disabled={testing}
          className="shrink-0 px-4 py-2 rounded-lg text-sm font-bold bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-white transition-colors"
        >
          {testing ? 'Sending…' : 'Send Test Email'}
        </button>
      </div>

      {result && (
        <div className="mt-3 p-3 rounded-lg bg-slate-800 text-xs font-mono text-slate-300 break-all">
          {result.error
            ? <span className="text-red-400">{result.error}</span>
            : <span className="text-green-400">{result.message || JSON.stringify(result)}</span>}
        </div>
      )}
    </div>
  );
};

const StandingsSyncCard = ({ addToast, onPlayinRefreshed }) => {
  const [expanded, setExpanded]         = useState(false);
  const [syncing, setSyncing]           = useState(false);
  const [browserFetching, setBrowserFetching] = useState(false);
  const [testing, setTesting]           = useState(false);
  const [syncingPlayers, setSyncingPlayers] = useState(false);
  const [playerSyncResult, setPlayerSyncResult] = useState(null);
  const [result, setResult]             = useState(null);
  const [testResult, setTestResult]     = useState(null);
  const [standing, setStanding]         = useState(null);

  useEffect(() => {
    if (!expanded) return;
    api.getStandings().then(d => setStanding(d)).catch(() => {});
  }, [expanded]);

  const runSync = async () => {
    setSyncing(true);
    setResult(null);
    try {
      const res = await api.adminSyncStandings();
      setResult(res);
      const [fresh, freshPlayin] = await Promise.all([
        api.getStandings(),
        api.getAdminPlayin(),
      ]);
      setStanding(fresh);
      if (onPlayinRefreshed) onPlayinRefreshed(freshPlayin);
      if (res.success) {
        const updated = res.playin_refreshed?.updated ?? [];
        const suffix  = updated.length ? ` · ${updated.length} play-in matchup(s) updated` : '';
        addToast(`Standings synced ✓${suffix}`, 'success');
      } else {
        addToast('Standings sync failed — see details below', 'error');
      }
    } catch (e) {
      const msg = e.response?.data?.detail || e.message;
      setResult({ success: false, last_error: msg });
      addToast('Sync error: ' + msg, 'error');
    } finally {
      setSyncing(false);
    }
  };

  const runBrowserFetch = async () => {
    setBrowserFetching(true);
    setResult(null);
    try {
      // Browser makes the request — bypasses Railway IP block
      const resp = await fetch(_NBA_BROWSER_URL, {
        method: 'GET',
        headers: _NBA_BROWSER_HEADERS,
        mode: 'cors',
        credentials: 'omit',
      });
      if (!resp.ok) throw new Error(`NBA API returned HTTP ${resp.status}`);
      const data = await resp.json();
      if (!data?.resultSets) throw new Error('Unexpected response shape — missing resultSets');

      // Push raw resultSets to our backend
      const pushRes = await api.pushStandingsFromBrowser(data.resultSets);
      setResult({ success: true, ...pushRes, last_success_at: pushRes.synced_at });
      const [fresh, freshPlayin] = await Promise.all([
        api.getStandings(),
        api.getAdminPlayin(),
      ]);
      setStanding(fresh);
      if (onPlayinRefreshed) onPlayinRefreshed(freshPlayin);
      const updated = pushRes.playin_refreshed?.updated ?? [];
      const suffix  = updated.length ? ` · ${updated.length} play-in matchup(s) updated` : '';
      addToast(`✓ Browser fetch saved ${pushRes.rows_saved} teams — #1 East: ${pushRes.east_no1}${suffix}`, 'success');
    } catch (e) {
      const isCors = e.message?.toLowerCase().includes('failed to fetch') || e.message?.toLowerCase().includes('cors');
      const msg = isCors
        ? 'CORS blocked — browser cannot fetch stats.nba.com directly. Use "Force Sync" (server) instead.'
        : (e.response?.data?.detail || e.message);
      setResult({ success: false, last_error: msg });
      addToast('Browser fetch failed: ' + msg, 'error');
    } finally {
      setBrowserFetching(false);
    }
  };

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await api.testStandingsConnection();
      setTestResult(res);
      if (res.success) addToast(`Connection OK — #1 East: ${res.east_no1}`, 'success');
      else addToast('Connection test failed — see details', 'error');
    } catch (e) {
      setTestResult({ success: false, error: e.response?.data?.detail || e.message });
    } finally {
      setTesting(false);
    }
  };

  const src = result?.data_source ?? standing?.data_source ?? null;
  const fails = result?.consecutive_failures ?? standing?.consecutive_failures ?? 0;

  const SourceBadge = ({ source }) => {
    if (!source) return null;
    const cfg = {
      rapidapi:      { label: 'RapidAPI ✓',           icon: Wifi,          cls: 'bg-green-500/20 text-green-400 border-green-500/30' },
      nba_api:       { label: 'stats.nba.com',         icon: Wifi,          cls: 'bg-green-500/20 text-green-400 border-green-500/30' },
      browser_push:  { label: 'Browser Push',          icon: Wifi,          cls: 'bg-green-500/20 text-green-400 border-green-500/30' },
      database:      { label: 'Database Cache',        icon: Database,      cls: 'bg-blue-500/20  text-blue-400  border-blue-500/30'  },
      hardcoded:     { label: 'Hardcoded Fallback ⚠',  icon: AlertTriangle, cls: 'bg-amber-500/20 text-amber-400 border-amber-500/30' },
    }[source] || { label: source, icon: Activity, cls: 'bg-slate-700 text-slate-400 border-slate-600' };
    const Icon = cfg.icon;
    return (
      <span className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-bold ${cfg.cls}`}>
        <Icon className="w-3 h-3" /> {cfg.label}
      </span>
    );
  };

  const fmt = (iso) => {
    if (!iso) return '—';
    return new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  };

  const runPlayerSync = async () => {
    setSyncingPlayers(true);
    setPlayerSyncResult(null);
    try {
      const res = await api.syncPlayerStats();
      setPlayerSyncResult(res);
      if (res.success) {
        addToast(`Player stats synced ✓ — ${res.rows_synced} players updated`, 'success');
      } else {
        addToast('Player stats sync failed: ' + (res.error || 'Unknown error'), 'error');
      }
    } catch (e) {
      const msg = e.response?.data?.detail || e.message;
      setPlayerSyncResult({ success: false, error: msg });
      addToast('Player sync error: ' + msg, 'error');
    } finally {
      setSyncingPlayers(false);
    }
  };

  const anyBusy = syncing || browserFetching || testing || syncingPlayers;

  return (
    <Card className="p-5 mb-4">
      <button onClick={() => setExpanded(e => !e)} className="w-full flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity className="w-5 h-5 text-blue-400" />
          <h2 className="text-lg font-black text-white">Standings Sync</h2>
          {fails > 0 && (
            <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400 text-[10px] font-black">
              <AlertTriangle className="w-3 h-3" /> {fails} failure{fails > 1 ? 's' : ''}
            </span>
          )}
          {src && <SourceBadge source={src} />}
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
      </button>

      {expanded && (
        <div className="mt-4 space-y-4">
          {/* Status grid */}
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="bg-slate-800/60 rounded-lg px-3 py-2">
              <p className="text-slate-500 font-bold uppercase mb-1">Data Source</p>
              <SourceBadge source={src} />
            </div>
            <div className="bg-slate-800/60 rounded-lg px-3 py-2">
              <p className="text-slate-500 font-bold uppercase mb-1">Consecutive Failures</p>
              <p className={`font-black text-lg ${fails > 0 ? 'text-amber-400' : 'text-green-400'}`}>{fails}</p>
            </div>
            <div className="bg-slate-800/60 rounded-lg px-3 py-2">
              <p className="text-slate-500 font-bold uppercase mb-1">Last DB Sync</p>
              <p className="text-white font-bold">{fmt(standing?.last_synced_at)}</p>
            </div>
            <div className="bg-slate-800/60 rounded-lg px-3 py-2">
              <p className="text-slate-500 font-bold uppercase mb-1">Season</p>
              <p className="text-white font-bold">2025-26 Regular Season</p>
            </div>
          </div>

          {/* All-Star data warning */}
          {(() => {
            const err = result?.last_error || standing?.last_sync_error || '';
            if (!err.toLowerCase().includes('all-star')) return null;
            return (
              <div className="bg-orange-950/50 border border-orange-500/50 rounded-lg px-3 py-2.5 flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 text-orange-400 shrink-0 mt-0.5" />
                <div>
                  <p className="text-orange-400 text-xs font-black uppercase mb-0.5">Error: API returned All-Star data instead of Regular Season</p>
                  <p className="text-orange-300/80 text-xs font-mono break-all">{err}</p>
                </div>
              </div>
            );
          })()}

          {/* General error */}
          {(result?.last_error || (fails > 0 && standing?.last_sync_error)) && (() => {
            const err = result?.last_error || standing?.last_sync_error || '';
            if (err.toLowerCase().includes('all-star')) return null;
            return (
              <div className="bg-red-950/40 border border-red-500/30 rounded-lg px-3 py-2">
                <p className="text-red-400 text-[10px] font-black uppercase mb-1">Last Error</p>
                <p className="text-red-300 text-xs font-mono break-all">{err}</p>
              </div>
            );
          })()}

          {/* Test connection result */}
          {testResult && (
            <div className={`px-3 py-2.5 rounded-lg border text-sm font-bold ${
              testResult.success
                ? 'bg-green-500/10 border-green-500/30 text-green-400'
                : 'bg-red-500/10  border-red-500/30  text-red-400'
            }`}>
              {testResult.success ? (
                <div>
                  <p className="flex items-center gap-1.5"><CheckCircle className="w-4 h-4" /> Connected via {testResult.source === 'rapidapi' ? 'RapidAPI ✓' : testResult.source ?? 'NBA API'}</p>
                  <p className="text-xs mt-1 font-normal">
                    #1 East: <span className="font-black">{testResult.east_no1}</span> &nbsp;|&nbsp;
                    #1 West: <span className="font-black">{testResult.west_no1}</span>
                  </p>
                  <p className="text-xs mt-0.5 font-normal text-green-300/70">
                    East: {testResult.east_top3?.join(' · ')}
                  </p>
                </div>
              ) : (
                <div>
                  <p className="flex items-center gap-1.5"><AlertTriangle className="w-4 h-4" /> Server cannot reach NBA API</p>
                  <p className="text-xs mt-1 font-mono font-normal break-all">{testResult.error}</p>
                  {testResult.hint && <p className="text-xs mt-1 text-amber-400 font-normal">{testResult.hint}</p>}
                </div>
              )}
            </div>
          )}

          {/* Sync result */}
          {result && !testResult && (
            <div className={`px-3 py-2 rounded-lg border text-sm font-bold flex items-center gap-2 ${
              result.success
                ? 'bg-green-500/10 border-green-500/30 text-green-400'
                : 'bg-red-500/10  border-red-500/30  text-red-400'
            }`}>
              {result.success ? <CheckCircle className="w-4 h-4" /> : <AlertTriangle className="w-4 h-4" />}
              {result.success
                ? `Sync succeeded — ${result.rows_saved ?? result.rows ?? ''} teams saved. #1 East: ${result.east_no1 ?? '—'} (${fmt(result.last_success_at)})`
                : 'Sync failed — check the error above'}
            </div>
          )}

          {/* Buttons */}
          <div className="grid grid-cols-1 gap-2">
            {/* Row 1: Test + Server sync */}
            <div className="flex gap-2">
              <button onClick={runTest} disabled={anyBusy}
                className={`flex-1 py-2.5 rounded-lg font-bold text-sm transition-all flex items-center justify-center gap-2 ${
                  anyBusy ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                          : 'bg-slate-700 hover:bg-slate-600 text-white border border-slate-600'
                }`}>
                {testing ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Wifi className="w-4 h-4" />}
                {testing ? 'Testing…' : 'Test Connection'}
              </button>
              <button onClick={runSync} disabled={anyBusy}
                className={`flex-1 py-2.5 rounded-lg font-bold text-sm transition-all flex items-center justify-center gap-2 ${
                  anyBusy ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                          : 'bg-blue-500 hover:bg-blue-600 text-white'
                }`}>
                <RefreshCw className={`w-4 h-4 ${syncing ? 'animate-spin' : ''}`} />
                {syncing ? 'Syncing via RapidAPI…' : 'Sync via RapidAPI'}
              </button>
            </div>

            {/* Row 2: Browser fetch (bypass) */}
            <button onClick={runBrowserFetch} disabled={anyBusy}
              className={`w-full py-2.5 rounded-lg font-bold text-sm transition-all flex items-center justify-center gap-2 ${
                anyBusy ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                        : 'bg-emerald-600 hover:bg-emerald-500 text-white'
              }`}>
              {browserFetching ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Wifi className="w-4 h-4" />}
              {browserFetching ? 'Browser fetching NBA data…' : 'Fetch via Browser (bypasses IP block)'}
            </button>

            {/* Row 3: Player stats sync */}
            <div className="border-t border-slate-700/60 pt-2 mt-1">
              <button onClick={runPlayerSync} disabled={anyBusy}
                className={`w-full py-2.5 rounded-lg font-bold text-sm transition-all flex items-center justify-center gap-2 ${
                  anyBusy ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                          : 'bg-purple-600 hover:bg-purple-500 text-white'
                }`}>
                <BarChart2 className={`w-4 h-4 ${syncingPlayers ? 'animate-pulse' : ''}`} />
                {syncingPlayers ? 'Syncing Player Stats…' : 'Sync Player Stats (MVP Search)'}
              </button>
              {playerSyncResult && (
                <div className={`mt-2 px-3 py-2 rounded-lg border text-xs font-bold flex items-center gap-2 ${
                  playerSyncResult.success
                    ? 'bg-green-500/10 border-green-500/30 text-green-400'
                    : 'bg-red-500/10  border-red-500/30  text-red-400'
                }`}>
                  {playerSyncResult.success
                    ? <><CheckCircle className="w-3.5 h-3.5 shrink-0" /> {playerSyncResult.rows_synced} players synced — MVP search is now ready</>
                    : <><AlertTriangle className="w-3.5 h-3.5 shrink-0" /> {playerSyncResult.error}</>}
                </div>
              )}
            </div>
          </div>

          <p className="text-[10px] text-slate-600 leading-relaxed">
            <strong className="text-slate-500">Test Connection</strong> — checks if the server can reach NBA API directly.<br />
            <strong className="text-slate-500">Sync via RapidAPI</strong> — server calls RapidAPI (not IP-blocked), saves to DB.<br />
            <strong className="text-slate-500">Fetch via Browser</strong> — YOUR browser fetches the data, then sends it to the server.
            Use this if the server is IP-blocked. Requires browser CORS access to stats.nba.com.<br />
            <strong className="text-slate-500">Sync Player Stats</strong> — populates the player_stats table used by MVP autocomplete search.
          </p>
        </div>
      )}
    </Card>
  );
};

const AdminPage = ({ currentUser }) => {
  const [series, setSeries] = useState([]);
  const [playin, setPlayin] = useState([]);
  const [allTeams, setAllTeams] = useState([]);
  const [loading, setLoading] = useState(true);
  const [toasts, setToasts] = useState([]);

  const addToast = useCallback((message, type = 'success') => {
    const id = Date.now();
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 3500);
  }, []);

  const dismissToast = useCallback((id) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

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

  const handleSeriesResult = async (seriesId, winnerTeamId, actualGames, manualOverride = false) => {
    await api.setSeriesResult(seriesId, winnerTeamId, actualGames, manualOverride);
    const updated = await api.getAdminSeries();
    setSeries(updated);
    addToast(manualOverride ? 'Result overridden — scores recalculated' : 'Result set — scores updated', 'success');
  };

  const handleResetSeriesResult = async (seriesId) => {
    try {
      await api.resetSeriesResult(seriesId);
      const updated = await api.getAdminSeries();
      setSeries(updated);
      addToast('Series reset — scores reverted', 'success');
    } catch (e) {
      addToast('Reset failed: ' + (e.response?.data?.detail || e.message), 'error');
    }
  };

  const handleSyncAndAdvance = async () => {
    try {
      const res = await api.syncAndAdvance();
      const updated = await api.getAdminSeries();
      setSeries(updated);
      addToast(res.message || 'Sync complete', 'success');
    } catch (e) {
      addToast('Sync failed: ' + (e.response?.data?.detail || e.message), 'error');
    }
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
    addToast('Play-in result set — bracket updated', 'success');
  };

  const handleResetPlayinResult = async (gameId) => {
    try {
      await api.resetPlayinResult(gameId);
      const updated = await api.getAdminPlayin();
      setPlayin(updated);
      addToast('Play-in result reset — scores reverted', 'success');
    } catch (e) {
      addToast('Reset failed: ' + (e.response?.data?.detail || e.message), 'error');
    }
  };

  const handleSyncPlayin = async () => {
    try {
      const res = await api.syncPlayin();
      const [updatedPlayin, updatedSeries] = await Promise.all([api.getAdminPlayin(), api.getAdminSeries()]);
      setPlayin(updatedPlayin);
      setSeries(updatedSeries);
      addToast(res.message || 'Play-in sync complete', 'success');
    } catch (e) {
      addToast('Sync failed: ' + (e.response?.data?.detail || e.message), 'error');
    }
  };

  const [syncingPlayoffsFromApi, setSyncingPlayoffsFromApi] = useState(false);
  const handleSyncPlayoffsFromApi = async () => {
    setSyncingPlayoffsFromApi(true);
    try {
      const res = await api.syncPlayoffsFromApi();
      const [updatedSeries] = await Promise.all([api.getAdminSeries()]);
      setSeries(updatedSeries);
      const updated   = res.updated   ?? 0;
      const completed = res.completed ?? 0;
      const errs      = res.errors?.length ?? 0;
      addToast(
        `Playoff sync done — ${updated} game(s) recorded, ${completed} series completed${errs > 0 ? `, ${errs} error(s)` : ''}`,
        errs === 0 ? 'success' : 'error'
      );
    } catch (e) {
      addToast('Playoff API sync failed: ' + (e.response?.data?.detail || e.message), 'error');
    } finally {
      setSyncingPlayoffsFromApi(false);
    }
  };

  const [syncingFromApi, setSyncingFromApi] = useState(false);
  const handleSyncPlayinFromApi = async () => {
    setSyncingFromApi(true);
    try {
      const res = await api.syncPlayinFromApi();
      const [updatedPlayin, updatedSeries] = await Promise.all([api.getAdminPlayin(), api.getAdminSeries()]);
      setPlayin(updatedPlayin);
      setSeries(updatedSeries);
      const promoted = res.promoted ?? 0;
      const processed = res.processed ?? 0;
      const errs = res.errors?.length ?? 0;
      addToast(
        `API sync done — ${processed} finished, ${promoted} promoted${errs > 0 ? `, ${errs} error(s)` : ''}`,
        promoted > 0 || errs === 0 ? 'success' : 'error'
      );
    } catch (e) {
      addToast('API sync failed: ' + (e.response?.data?.detail || e.message), 'error');
    } finally {
      setSyncingFromApi(false);
    }
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
      <Toast toasts={toasts} dismiss={dismissToast} />

      <div className="flex items-center justify-between mb-8">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-4xl font-black text-white">Admin Panel</h1>
            <span className="px-3 py-1 rounded-full bg-orange-500/20 border border-orange-500/30 text-orange-400 text-xs font-bold uppercase">Admin</span>
          </div>
          <p className="text-slate-400">Set results — scores update automatically</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={handleSyncAndAdvance}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-indigo-500/20 border border-indigo-500/40 text-indigo-300 hover:bg-indigo-500/30 font-bold text-sm transition-all"
            title="Re-run bracket advancement for all completed series and recalculate all points">
            <Zap className="w-4 h-4" />
            Sync &amp; Advance
          </button>
          <button onClick={load} className="flex items-center gap-2 px-4 py-2 rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800/50 transition-all">
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
        </div>
      </div>

      <UserManagementCard currentUser={currentUser} addToast={addToast} />
      <PlayerStatsSyncCard addToast={addToast} />
      <ReminderCard addToast={addToast} />
      <StandingsSyncCard addToast={addToast} onPlayinRefreshed={setPlayin} />
      <FuturesLockCard />
      <LeadersLockCard />
      <TeamOddsCard addToast={addToast} />
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
          {playin.length > 0 && (() => {
            const byConf = playin.reduce((acc, g) => {
              acc[g.conference] = acc[g.conference] || [];
              acc[g.conference].push(g);
              return acc;
            }, {});
            const gameOrder = { '7v8': 0, '9v10': 1, 'elimination': 2 };
            return (
              <div className="mb-10">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-2xl font-bold text-white flex items-center gap-2">
                    <Trophy className="w-6 h-6 text-purple-400" /> Play-In Games
                  </h2>
                  <div className="flex items-center gap-2">
                    <button onClick={handleSyncPlayinFromApi}
                      disabled={syncingFromApi}
                      className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-500/20 border border-blue-500/40 text-blue-300 hover:bg-blue-500/30 font-bold text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                      title="Fetch finished Play-In results from RapidAPI and auto-promote winners in the bracket">
                      {syncingFromApi
                        ? <RefreshCw className="w-4 h-4 animate-spin" />
                        : <Wifi className="w-4 h-4" />}
                      {syncingFromApi ? 'Syncing…' : 'Sync from API'}
                    </button>
                    <button onClick={handleSyncPlayin}
                      className="flex items-center gap-2 px-4 py-2 rounded-lg bg-purple-500/20 border border-purple-500/40 text-purple-300 hover:bg-purple-500/30 font-bold text-sm transition-all"
                      title="Re-run play-in progressions: create Game 3, advance R1 seeds, recalculate points">
                      <Zap className="w-4 h-4" />
                      Sync Play-In
                    </button>
                  </div>
                </div>

                {Object.entries(byConf).map(([conf, confGames]) => {
                  const ordered = [...confGames].sort((a, b) => (gameOrder[a.game_type] ?? 9) - (gameOrder[b.game_type] ?? 9));
                  return (
                    <div key={conf} className="mb-8">
                      <div className="flex items-center gap-2 mb-3">
                        <h3 className="text-lg font-black text-white">{conf} Conference</h3>
                        <span className="text-xs text-slate-500">Play-In</span>
                      </div>
                      <PlayinConferenceBanner confGames={confGames} />
                      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                        {ordered.map(game => (
                          <PlayinCard key={game.id} game={game} onSave={handlePlayinResult} onReset={handleResetPlayinResult} />
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            );
          })()}

          {/* Playoff Series header with API sync button — rendered once above all rounds */}
          {roundOrder.some(r => seriesByRound[r]?.length) && (
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-2xl font-bold text-white flex items-center gap-2">
                <Trophy className="w-6 h-6 text-orange-400" /> Playoff Series
              </h2>
              <button
                onClick={handleSyncPlayoffsFromApi}
                disabled={syncingPlayoffsFromApi}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-500/20 border border-blue-500/40 text-blue-300 hover:bg-blue-500/30 font-bold text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                title="Fetch finished Playoff game results from RapidAPI and update series scores">
                {syncingPlayoffsFromApi
                  ? <RefreshCw className="w-4 h-4 animate-spin" />
                  : <Wifi className="w-4 h-4" />}
                {syncingPlayoffsFromApi ? 'Syncing…' : 'Sync from API'}
              </button>
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
                    <SeriesCard key={s.id} series={s} onSave={handleSeriesResult} onToggleLock={handleToggleLock} onReset={handleResetSeriesResult} />
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
