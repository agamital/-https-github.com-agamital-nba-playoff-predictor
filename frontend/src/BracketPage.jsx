import React, { useState, useEffect, useMemo } from 'react';
import { Trophy, ChevronRight } from 'lucide-react';
import * as api from './services/api';

// ── Layout constants (desktop) ───────────────────────────────────────────────
const BH = 640;    // bracket total height
const CH = 104;    // card height
const SH = BH / 4; // slot height = 160

// ── Connector lines ──────────────────────────────────────────────────────────

const Connector = ({ height, dir = 'right' }) => {
  const half = height / 2;
  const side  = dir === 'right' ? 'borderRight' : 'borderLeft';
  const bR    = dir === 'right' ? 10 : 0;
  const bL    = dir === 'left'  ? 10 : 0;
  const base  = { [side]: '2px solid #1e3a5f', width: 24, flexShrink: 0 };
  return (
    <div style={{ height, width: 24, flexShrink: 0 }}>
      <div style={{ ...base, height: half, borderBottom: '2px solid #1e3a5f', borderBottomRightRadius: bR, borderBottomLeftRadius: bL }} />
      <div style={{ ...base, height: half, borderTop: '2px solid #1e3a5f', borderTopRightRadius: bR, borderTopLeftRadius: bL }} />
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

const HLine = () => (
  <div style={{ height: BH + 28, width: 28, flexShrink: 0, display: 'flex', alignItems: 'center' }}>
    <div style={{ width: '100%', height: 2, background: '#1e3a5f' }} />
  </div>
);

// ── TBD / Finals cards ───────────────────────────────────────────────────────

const TBDCard = () => (
  <div style={{ height: CH }} className="w-44 bg-slate-900/40 border border-slate-800 rounded-xl flex flex-col overflow-hidden">
    <div className="flex-1 flex items-center gap-3 px-4 border-b border-slate-800">
      <div className="w-8 h-8 rounded-full bg-slate-800/80" />
      <span className="text-sm text-slate-600 font-medium">TBD</span>
    </div>
    <div className="flex-1 flex items-center gap-3 px-4">
      <div className="w-8 h-8 rounded-full bg-slate-800/80" />
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

// ── Match card (desktop) ─────────────────────────────────────────────────────

const MatchCard = ({ series, pick, onTeamClick, isActive }) => {
  const { home_team: h, away_team: a } = series;
  const hp = pick?.teamId === h.id;
  const ap = pick?.teamId === a.id;

  const teamRow = (team, picked, onClick) => (
    <button
      onClick={onClick}
      className={`flex-1 flex items-center gap-2 px-3 w-full transition-all ${
        picked ? 'bg-orange-500/25' : 'hover:bg-slate-800/70'
      }`}
    >
      <span className="text-xs text-slate-500 w-4 shrink-0 font-bold">{team.seed}</span>
      <img src={team.logo_url} alt="" className="w-8 h-8 shrink-0"
        onError={e => e.target.style.display = 'none'} />
      <span className={`text-sm font-bold truncate ${picked ? 'text-orange-400' : 'text-white'}`}>
        {team.abbreviation}
      </span>
      {picked && <ChevronRight className="ml-auto w-4 h-4 text-orange-400 shrink-0" />}
    </button>
  );

  return (
    <div
      style={{ height: CH }}
      className={`w-44 border-2 rounded-xl flex flex-col overflow-hidden transition-all cursor-pointer ${
        isActive ? 'border-orange-500 shadow-xl shadow-orange-500/20' :
        (hp || ap) ? 'border-orange-500/40 shadow-md shadow-orange-500/10' :
        'border-slate-700/60 hover:border-slate-600'
      } bg-slate-900/80`}
    >
      {teamRow(h, hp, () => onTeamClick(series, h.id))}
      <div className="h-px bg-slate-800" />
      {teamRow(a, ap, () => onTeamClick(series, a.id))}
    </div>
  );
};

// ── Desktop bracket columns ──────────────────────────────────────────────────

const R1Col = ({ label, slots, picks, onTeamClick, activeId }) => (
  <div style={{ flexShrink: 0 }}>
    <p className="text-xs text-slate-500 uppercase font-bold mb-3 text-center tracking-wider">{label}</p>
    <div style={{ height: BH + 28, display: 'flex', flexDirection: 'column' }}>
      {slots.map((s, i) => (
        <div key={i} style={{ height: (BH + 28) / 4, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          {s ? <MatchCard series={s} pick={picks[s.id]} onTeamClick={onTeamClick} isActive={activeId === s.id} />
             : <TBDCard />}
        </div>
      ))}
    </div>
  </div>
);

const SemisCol = ({ label }) => {
  const pt = (BH + 28) / 8 - CH / 2;
  return (
    <div style={{ flexShrink: 0 }}>
      <p className="text-xs text-slate-500 uppercase font-bold mb-3 text-center tracking-wider">{label}</p>
      <div style={{ height: BH + 28, paddingTop: Math.max(pt, 0), paddingBottom: Math.max(pt, 0), display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
        <TBDCard />
        <TBDCard />
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

// ── Pick panel (shared desktop + mobile) ─────────────────────────────────────

const PickPanel = ({ series, pick, onGamesSelect, onSave, saved, onClose }) => {
  if (!series) return null;
  const { home_team: h, away_team: a } = series;
  const picked = pick?.teamId === h.id ? h : pick?.teamId === a.id ? a : null;

  return (
    <div className="mt-6 max-w-lg mx-auto bg-gradient-to-br from-slate-900 to-slate-900/80 border border-orange-500/30 rounded-2xl p-5 shadow-xl shadow-orange-500/5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <p className="text-xs text-slate-400 uppercase font-bold tracking-wider mb-0.5">
            {series.conference} • {series.round}
          </p>
          <h3 className="text-white font-black text-lg">{h.name} vs {a.name}</h3>
        </div>
        <button onClick={onClose} className="w-8 h-8 rounded-full bg-slate-800 text-slate-400 hover:text-white hover:bg-slate-700 flex items-center justify-center text-lg leading-none transition-all">×</button>
      </div>

      {picked ? (
        <div className="flex items-center gap-3 mb-5 px-4 py-3 rounded-xl bg-orange-500/15 border border-orange-500/30">
          <img src={picked.logo_url} alt="" className="w-10 h-10" onError={e => e.target.style.display = 'none'} />
          <div>
            <p className="text-xs text-orange-400/70 font-bold uppercase">Your Pick</p>
            <p className="text-orange-400 font-black">{picked.name}</p>
          </div>
        </div>
      ) : (
        <p className="text-slate-500 text-sm mb-5">Click a team to pick a winner</p>
      )}

      <div className="mb-5">
        <p className="text-xs text-slate-400 uppercase font-bold tracking-wider mb-2">Series Length</p>
        <div className="grid grid-cols-4 gap-2">
          {[4, 5, 6, 7].map(g => (
            <button key={g} onClick={() => onGamesSelect(g)}
              className={`py-3 rounded-xl font-black text-sm transition-all border-2 ${
                pick?.games === g
                  ? 'border-orange-500 bg-orange-500/20 text-white shadow-md shadow-orange-500/20'
                  : 'border-slate-700 bg-slate-800/50 text-slate-400 hover:border-slate-500 hover:text-white'
              }`}>
              {g}<span className="text-[10px] ml-0.5 opacity-70">G</span>
            </button>
          ))}
        </div>
      </div>

      <button onClick={onSave} disabled={!pick?.teamId || !pick?.games}
        className={`w-full py-3.5 rounded-xl font-black text-sm transition-all ${
          saved ? 'bg-green-500 text-white' :
          !pick?.teamId || !pick?.games ? 'bg-slate-800 text-slate-600 cursor-not-allowed' :
          'bg-gradient-to-r from-orange-500 to-red-500 hover:from-orange-600 hover:to-red-600 text-white shadow-lg shadow-orange-500/25'
        }`}>
        {saved ? '✓ Prediction Saved!' : 'Save Prediction'}
      </button>
    </div>
  );
};

// ── Mobile matchup card ──────────────────────────────────────────────────────

const MobileMatchCard = ({ series, pick, onTeamClick, onGamesSelect, onSave, saved }) => {
  const { home_team: h, away_team: a } = series;
  const hp = pick?.teamId === h.id;
  const ap = pick?.teamId === a.id;
  const picked = hp ? h : ap ? a : null;

  const teamBtn = (team, picked, onClick) => (
    <button onClick={onClick}
      className={`flex items-center gap-3 p-4 rounded-xl border-2 transition-all w-full ${
        picked ? 'border-orange-500 bg-orange-500/15' : 'border-slate-700 bg-slate-900/60 hover:border-slate-600 active:bg-slate-800'
      }`}>
      <span className={`text-xs font-black w-5 ${picked ? 'text-orange-400' : 'text-slate-500'}`}>{team.seed}</span>
      <img src={team.logo_url} alt="" className="w-10 h-10 shrink-0"
        onError={e => e.target.style.display = 'none'} />
      <div className="text-left flex-1">
        <p className={`font-black text-base leading-tight ${picked ? 'text-orange-400' : 'text-white'}`}>{team.name}</p>
        <p className="text-xs text-slate-500">Seed #{team.seed}</p>
      </div>
      {picked && <div className="w-6 h-6 rounded-full bg-orange-500 flex items-center justify-center shrink-0">
        <span className="text-white text-xs font-black">✓</span>
      </div>}
    </button>
  );

  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-4 space-y-3">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">{series.round}</span>
      </div>

      <div className="space-y-2">
        {teamBtn(h, hp, () => onTeamClick(series, h.id))}
        <div className="text-center text-xs text-slate-600 font-bold">VS</div>
        {teamBtn(a, ap, () => onTeamClick(series, a.id))}
      </div>

      {picked && (
        <div className="pt-2 border-t border-slate-800 space-y-3">
          <p className="text-xs text-slate-400 uppercase font-bold tracking-wider">Series Length</p>
          <div className="grid grid-cols-4 gap-2">
            {[4, 5, 6, 7].map(g => (
              <button key={g} onClick={() => onGamesSelect(series.id, g)}
                className={`py-3 rounded-xl font-black text-sm transition-all border-2 ${
                  pick?.games === g
                    ? 'border-orange-500 bg-orange-500/20 text-white'
                    : 'border-slate-700 bg-slate-800/60 text-slate-400'
                }`}>
                {g}G
              </button>
            ))}
          </div>
          <button onClick={() => onSave(series.id)} disabled={!pick?.games}
            className={`w-full py-3.5 rounded-xl font-black text-sm transition-all ${
              saved ? 'bg-green-500 text-white' :
              !pick?.games ? 'bg-slate-800 text-slate-600 cursor-not-allowed' :
              'bg-gradient-to-r from-orange-500 to-red-500 text-white shadow-lg shadow-orange-500/25'
            }`}>
            {saved ? '✓ Saved!' : 'Save Prediction'}
          </button>
        </div>
      )}
    </div>
  );
};

// ── Main Page ────────────────────────────────────────────────────────────────

const BracketPage = ({ currentUser }) => {
  const [series, setSeries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [picks, setPicks] = useState({});
  const [saved, setSaved] = useState({});
  const [activeSeries, setActiveSeries] = useState(null);

  useEffect(() => {
    api.getSeries('2026').then(setSeries).catch(console.error).finally(() => setLoading(false));
  }, []);

  const { westSlots, eastSlots, westSeries, eastSeries } = useMemo(() => {
    const minSeed = s => Math.min(s.home_team.seed, s.away_team.seed);
    const west = series.filter(s => s.conference === 'Western');
    const east = series.filter(s => s.conference === 'Eastern');
    const order = [1, 4, 3, 2];
    return {
      westSlots: order.map(seed => west.find(s => minSeed(s) === seed) || null),
      eastSlots: order.map(seed => east.find(s => minSeed(s) === seed) || null),
      westSeries: west,
      eastSeries: east,
    };
  }, [series]);

  const handleTeamClick = (seriesObj, teamId) => {
    if (!currentUser) return;
    setPicks(p => ({ ...p, [seriesObj.id]: { ...p[seriesObj.id], teamId } }));
    setActiveSeries(seriesObj);
  };

  const handleMobileGames = (seriesId, games) => {
    setPicks(p => ({ ...p, [seriesId]: { ...p[seriesId], games } }));
  };

  const handleSave = async (seriesId) => {
    if (!currentUser) return;
    const pick = picks[seriesId];
    if (!pick?.teamId || !pick?.games) return;
    try {
      await api.makePrediction(currentUser.user_id, seriesId, pick.teamId, pick.games);
      setSaved(p => ({ ...p, [seriesId]: true }));
      setTimeout(() => setSaved(p => ({ ...p, [seriesId]: false })), 2000);
    } catch (err) {
      alert('Error: ' + (err.response?.data?.detail || 'Unknown'));
    }
  };

  const handleDesktopGames = (games) => {
    if (!activeSeries) return;
    setPicks(p => ({ ...p, [activeSeries.id]: { ...p[activeSeries.id], games } }));
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
    return (
      <div className="flex items-center justify-center py-24">
        <div className="animate-spin rounded-full h-14 w-14 border-4 border-orange-500 border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="px-4 py-8">
      {/* Header */}
      <div className="flex items-center gap-3 mb-8 justify-center">
        <Trophy className="w-9 h-9 text-orange-400" />
        <div>
          <h1 className="text-4xl md:text-5xl font-black text-white leading-none">2026 NBA Playoffs</h1>
          <p className="text-slate-400 text-sm mt-1">Click a matchup to make your prediction</p>
        </div>
      </div>

      {/* ── DESKTOP BRACKET ── */}
      <div className="hidden lg:block">
        <div className="flex items-center justify-between max-w-5xl mx-auto mb-2 px-1">
          <span className="text-sm font-black text-blue-400 uppercase tracking-widest">◀ Western Conference</span>
          <span className="text-sm font-black text-red-400 uppercase tracking-widest">Eastern Conference ▶</span>
        </div>

        <div className="overflow-x-auto pb-6">
          <div className="flex items-start justify-center gap-0" style={{ minWidth: 1100 }}>
            {/* WEST */}
            <R1Col label="Round 1" slots={westSlots} picks={picks} onTeamClick={handleTeamClick} activeId={activeSeries?.id} />
            <ConnectorCol count={2} dir="right" />
            <SemisCol label="Conf Semis" />
            <ConnectorCol count={1} dir="right" />
            <CFCol label="Conf Finals" />
            <HLine />

            {/* Finals */}
            <FinalsCard />

            {/* EAST */}
            <HLine />
            <CFCol label="Conf Finals" />
            <ConnectorCol count={1} dir="left" />
            <SemisCol label="Conf Semis" />
            <ConnectorCol count={2} dir="left" />
            <R1Col label="Round 1" slots={eastSlots} picks={picks} onTeamClick={handleTeamClick} activeId={activeSeries?.id} />
          </div>
        </div>

        {!activeSeries && (
          <p className="text-center text-slate-600 text-sm mt-2">Select a matchup to pick a winner</p>
        )}

        <PickPanel
          series={activeSeries}
          pick={activeSeries ? picks[activeSeries.id] : null}
          onGamesSelect={handleDesktopGames}
          onSave={() => handleSave(activeSeries?.id)}
          saved={activeSeries ? saved[activeSeries.id] : false}
          onClose={() => setActiveSeries(null)}
        />
      </div>

      {/* ── MOBILE LAYOUT ── */}
      <div className="lg:hidden space-y-8">
        {/* Western Conference */}
        <div>
          <div className="flex items-center gap-2 mb-4">
            <div className="h-px flex-1 bg-blue-500/20" />
            <h2 className="text-lg font-black text-blue-400 uppercase tracking-widest px-3">Western Conference</h2>
            <div className="h-px flex-1 bg-blue-500/20" />
          </div>
          <div className="space-y-3">
            {westSeries.length > 0 ? westSeries.map(s => (
              <MobileMatchCard
                key={s.id}
                series={s}
                pick={picks[s.id]}
                onTeamClick={handleTeamClick}
                onGamesSelect={handleMobileGames}
                onSave={handleSave}
                saved={saved[s.id]}
              />
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
            <div className="h-px flex-1 bg-red-500/20" />
            <h2 className="text-lg font-black text-red-400 uppercase tracking-widest px-3">Eastern Conference</h2>
            <div className="h-px flex-1 bg-red-500/20" />
          </div>
          <div className="space-y-3">
            {eastSeries.length > 0 ? eastSeries.map(s => (
              <MobileMatchCard
                key={s.id}
                series={s}
                pick={picks[s.id]}
                onTeamClick={handleTeamClick}
                onGamesSelect={handleMobileGames}
                onSave={handleSave}
                saved={saved[s.id]}
              />
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
