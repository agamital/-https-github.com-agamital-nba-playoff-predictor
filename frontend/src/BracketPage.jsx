import React, { useState, useEffect, useMemo } from 'react';
import { Trophy } from 'lucide-react';
import * as api from './services/api';

const BH = 480;   // bracket total height px
const CH = 80;    // card height px
const SH = BH / 4; // slot height px = 120

// ── Connector lines ─────────────────────────────────────────────────────────

const Connector = ({ height, dir = 'right' }) => {
  const bR = dir === 'right' ? 8 : 0;
  const bL = dir === 'left'  ? 8 : 0;
  const half = height / 2;
  return (
    <div style={{ height, width: 20, flexShrink: 0 }}>
      <div style={{
        height: half,
        borderRight: dir === 'right' ? '2px solid #334155' : 'none',
        borderLeft:  dir === 'left'  ? '2px solid #334155' : 'none',
        borderBottom: '2px solid #334155',
        borderBottomRightRadius: dir === 'right' ? bR : 0,
        borderBottomLeftRadius:  dir === 'left'  ? bL : 0,
      }} />
      <div style={{
        height: half,
        borderRight: dir === 'right' ? '2px solid #334155' : 'none',
        borderLeft:  dir === 'left'  ? '2px solid #334155' : 'none',
        borderTop: '2px solid #334155',
        borderTopRightRadius: dir === 'right' ? bR : 0,
        borderTopLeftRadius:  dir === 'left'  ? bL : 0,
      }} />
    </div>
  );
};

// A bracket column made of stacked connectors (R1 → Semis uses 2 connectors)
const ConnectorColumn = ({ count, totalHeight, dir }) => {
  const h = totalHeight / count;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: totalHeight, flexShrink: 0 }}>
      {Array.from({ length: count }).map((_, i) => (
        <Connector key={i} height={h} dir={dir} />
      ))}
    </div>
  );
};

// Horizontal arrow line (CF → Finals)
const Arrow = ({ dir = 'right' }) => (
  <div style={{ height: BH, width: 24, flexShrink: 0, display: 'flex', alignItems: 'center' }}>
    <div style={{
      width: '100%',
      height: 2,
      background: '#334155',
    }} />
  </div>
);

// ── Matchup Cards ────────────────────────────────────────────────────────────

const TBDCard = ({ label = 'TBD' }) => (
  <div style={{ height: CH }} className="w-36 bg-slate-900/30 border border-slate-800 rounded-lg flex flex-col overflow-hidden opacity-50">
    <div className="flex-1 flex items-center gap-2 px-3 border-b border-slate-800">
      <div className="w-5 h-5 rounded bg-slate-800" />
      <span className="text-xs text-slate-600">{label}</span>
    </div>
    <div className="flex-1 flex items-center gap-2 px-3">
      <div className="w-5 h-5 rounded bg-slate-800" />
      <span className="text-xs text-slate-600">{label}</span>
    </div>
  </div>
);

const FinalsCard = () => (
  <div style={{ height: BH, flexShrink: 0 }} className="flex flex-col items-center justify-center px-2">
    <div className="mb-2">
      <Trophy className="w-5 h-5 text-yellow-400 mx-auto mb-1" />
      <p className="text-[10px] text-yellow-400 uppercase font-bold text-center">NBA Finals</p>
    </div>
    <TBDCard label="TBD" />
  </div>
);

const MatchCard = ({ series, pick, onTeamClick, isActive }) => {
  const home = series.home_team;
  const away = series.away_team;
  const homePicked = pick?.teamId === home.id;
  const awayPicked = pick?.teamId === away.id;

  return (
    <div
      style={{ height: CH }}
      className={`w-36 border rounded-lg flex flex-col overflow-hidden transition-all ${
        isActive ? 'border-orange-500 shadow-lg shadow-orange-500/20' :
        (homePicked || awayPicked) ? 'border-orange-500/50' : 'border-slate-700 hover:border-slate-600'
      } bg-slate-900/80`}
    >
      <button
        onClick={() => onTeamClick(series, home.id)}
        className={`flex-1 flex items-center gap-1.5 px-2 transition-all ${
          homePicked ? 'bg-orange-500/20' : 'hover:bg-slate-800/60'
        }`}
      >
        <span className="text-[10px] text-slate-500 w-3 shrink-0">{home.seed}</span>
        <img src={home.logo_url} alt="" className="w-5 h-5 shrink-0" onError={e => e.target.style.display = 'none'} />
        <span className={`text-xs font-bold truncate ${homePicked ? 'text-orange-400' : 'text-white'}`}>
          {home.abbreviation}
        </span>
        {homePicked && <span className="ml-auto text-orange-400 text-xs">✓</span>}
      </button>
      <div className="h-px bg-slate-800" />
      <button
        onClick={() => onTeamClick(series, away.id)}
        className={`flex-1 flex items-center gap-1.5 px-2 transition-all ${
          awayPicked ? 'bg-orange-500/20' : 'hover:bg-slate-800/60'
        }`}
      >
        <span className="text-[10px] text-slate-500 w-3 shrink-0">{away.seed}</span>
        <img src={away.logo_url} alt="" className="w-5 h-5 shrink-0" onError={e => e.target.style.display = 'none'} />
        <span className={`text-xs font-bold truncate ${awayPicked ? 'text-orange-400' : 'text-white'}`}>
          {away.abbreviation}
        </span>
        {awayPicked && <span className="ml-auto text-orange-400 text-xs">✓</span>}
      </button>
    </div>
  );
};

// ── Bracket Columns ──────────────────────────────────────────────────────────

const R1Column = ({ label, slots, picks, onTeamClick, activeId }) => (
  <div style={{ flexShrink: 0 }}>
    <p className="text-[10px] text-slate-500 uppercase font-bold mb-2 text-center">{label}</p>
    <div style={{ height: BH, display: 'flex', flexDirection: 'column' }}>
      {slots.map((s, i) => (
        <div key={i} style={{ height: SH, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          {s ? (
            <MatchCard
              series={s}
              pick={picks[s.id]}
              onTeamClick={onTeamClick}
              isActive={activeId === s.id}
            />
          ) : <TBDCard />}
        </div>
      ))}
    </div>
  </div>
);

const SemisColumn = ({ label }) => {
  const pt = SH - CH / 2; // 120 - 40 = 80px
  return (
    <div style={{ flexShrink: 0 }}>
      <p className="text-[10px] text-slate-500 uppercase font-bold mb-2 text-center">{label}</p>
      <div style={{ height: BH, paddingTop: pt, paddingBottom: pt, display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
        <TBDCard label="TBD" />
        <TBDCard label="TBD" />
      </div>
    </div>
  );
};

const CFColumn = ({ label }) => (
  <div style={{ flexShrink: 0 }}>
    <p className="text-[10px] text-slate-500 uppercase font-bold mb-2 text-center">{label}</p>
    <div style={{ height: BH, display: 'flex', alignItems: 'center' }}>
      <TBDCard label="TBD" />
    </div>
  </div>
);

// ── Pick Panel ───────────────────────────────────────────────────────────────

const PickPanel = ({ series, pick, onGamesSelect, onSave, saved, onClose }) => {
  if (!series) return null;
  const home = series.home_team;
  const away = series.away_team;
  const picked = pick?.teamId === home.id ? home : pick?.teamId === away.id ? away : null;

  return (
    <div className="mt-8 max-w-lg mx-auto bg-slate-900/90 border border-orange-500/30 rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <p className="text-xs text-slate-400 uppercase font-bold mb-1">{series.conference} • {series.round}</p>
          <h3 className="text-white font-bold">
            {home.abbreviation} vs {away.abbreviation}
          </h3>
        </div>
        <button onClick={onClose} className="text-slate-500 hover:text-white text-lg leading-none">×</button>
      </div>

      {picked ? (
        <div className="flex items-center gap-2 mb-4 px-3 py-2 rounded-lg bg-orange-500/20 border border-orange-500/30 w-fit">
          <img src={picked.logo_url} alt="" className="w-7 h-7" onError={e => e.target.style.display = 'none'} />
          <span className="text-orange-400 font-bold">{picked.name} to win</span>
        </div>
      ) : (
        <p className="text-slate-400 text-sm mb-4">Click a team above to pick a winner</p>
      )}

      <div className="mb-4">
        <p className="text-xs text-slate-400 uppercase font-bold mb-2">Series Length</p>
        <div className="flex gap-2">
          {[4, 5, 6, 7].map(g => (
            <button
              key={g}
              onClick={() => onGamesSelect(g)}
              className={`flex-1 py-2 rounded-lg font-bold text-sm transition-all border-2 ${
                pick?.games === g
                  ? 'border-orange-500 bg-orange-500/20 text-white'
                  : 'border-slate-700 bg-slate-800/50 text-slate-400 hover:border-slate-500'
              }`}
            >
              {g}
            </button>
          ))}
        </div>
      </div>

      <button
        onClick={onSave}
        disabled={!pick?.teamId || !pick?.games}
        className={`w-full py-2.5 rounded-lg font-bold transition-all ${
          saved
            ? 'bg-green-500 text-white'
            : !pick?.teamId || !pick?.games
            ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
            : 'bg-orange-500 hover:bg-orange-600 text-white'
        }`}
      >
        {saved ? 'Saved!' : 'Save Prediction'}
      </button>
    </div>
  );
};

// ── Main Component ───────────────────────────────────────────────────────────

const BracketPage = ({ currentUser }) => {
  const [series, setSeries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [picks, setPicks] = useState({});
  const [saved, setSaved] = useState({});
  const [activeSeries, setActiveSeries] = useState(null);

  useEffect(() => {
    api.getSeries('2026').then(setSeries).catch(console.error).finally(() => setLoading(false));
  }, []);

  const { westSlots, eastSlots } = useMemo(() => {
    const minSeed = s => Math.min(s.home_team.seed, s.away_team.seed);
    const west = series.filter(s => s.conference === 'Western');
    const east = series.filter(s => s.conference === 'Eastern');
    const order = [1, 4, 3, 2]; // bracket order top→bottom
    return {
      westSlots: order.map(seed => west.find(s => minSeed(s) === seed) || null),
      eastSlots: order.map(seed => east.find(s => minSeed(s) === seed) || null),
    };
  }, [series]);

  const handleTeamClick = (seriesObj, teamId) => {
    if (!currentUser) return;
    setPicks(p => ({ ...p, [seriesObj.id]: { ...p[seriesObj.id], teamId } }));
    setActiveSeries(seriesObj);
  };

  const handleGamesSelect = (games) => {
    if (!activeSeries) return;
    setPicks(p => ({ ...p, [activeSeries.id]: { ...p[activeSeries.id], games } }));
  };

  const handleSave = async () => {
    if (!activeSeries || !currentUser) return;
    const pick = picks[activeSeries.id];
    if (!pick?.teamId || !pick?.games) return;
    try {
      await api.makePrediction(currentUser.user_id, activeSeries.id, pick.teamId, pick.games);
      setSaved(p => ({ ...p, [activeSeries.id]: true }));
      setTimeout(() => setSaved(p => ({ ...p, [activeSeries.id]: false })), 2000);
    } catch (err) {
      alert('Error saving: ' + (err.response?.data?.detail || 'Unknown'));
    }
  };

  if (!currentUser) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-12 text-center">
        <h2 className="text-3xl font-bold text-white mb-4">Please Login</h2>
        <p className="text-slate-400">You need to be logged in to make predictions</p>
      </div>
    );
  }

  return (
    <div className="px-4 py-8">
      <div className="flex items-center gap-3 mb-8 justify-center">
        <Trophy className="w-8 h-8 text-orange-400" />
        <h1 className="text-4xl font-black text-white">2026 NBA Playoffs</h1>
      </div>

      {loading ? (
        <div className="text-center py-12">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-4 border-orange-500 border-t-transparent" />
        </div>
      ) : (
        <>
          {/* Conference labels */}
          <div className="flex justify-between max-w-5xl mx-auto mb-1 px-2">
            <span className="text-sm font-bold text-blue-400 uppercase tracking-wider">Western Conference</span>
            <span className="text-sm font-bold text-red-400 uppercase tracking-wider">Eastern Conference</span>
          </div>

          {/* Bracket */}
          <div className="overflow-x-auto pb-4">
            <div className="flex items-start justify-center" style={{ minWidth: 900 }}>

              {/* WEST: R1 → Semis → CF */}
              <R1Column
                label="Round 1"
                slots={westSlots}
                picks={picks}
                onTeamClick={handleTeamClick}
                activeId={activeSeries?.id}
              />
              <ConnectorColumn count={2} totalHeight={BH + 20} dir="right" />
              <SemisColumn label="Conf Semis" />
              <ConnectorColumn count={1} totalHeight={BH + 20} dir="right" />
              <CFColumn label="Conf Finals" />
              <Arrow />

              {/* NBA Finals center */}
              <FinalsCard />

              {/* EAST: CF → Semis → R1 (mirrored) */}
              <Arrow dir="left" />
              <CFColumn label="Conf Finals" />
              <ConnectorColumn count={1} totalHeight={BH + 20} dir="left" />
              <SemisColumn label="Conf Semis" />
              <ConnectorColumn count={2} totalHeight={BH + 20} dir="left" />
              <R1Column
                label="Round 1"
                slots={eastSlots}
                picks={picks}
                onTeamClick={handleTeamClick}
                activeId={activeSeries?.id}
              />
            </div>
          </div>

          {/* Click a matchup to pick */}
          {!activeSeries && (
            <p className="text-center text-slate-500 text-sm mt-4">Click on a team to make your prediction</p>
          )}

          <PickPanel
            series={activeSeries}
            pick={activeSeries ? picks[activeSeries.id] : null}
            onGamesSelect={handleGamesSelect}
            onSave={handleSave}
            saved={activeSeries ? saved[activeSeries.id] : false}
            onClose={() => setActiveSeries(null)}
          />
        </>
      )}
    </div>
  );
};

export default BracketPage;
