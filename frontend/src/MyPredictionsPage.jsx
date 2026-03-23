import React, { useState, useEffect } from 'react';
import { Trophy, CheckCircle, XCircle, Clock, Star, Users, BarChart2, ChevronDown, ChevronUp } from 'lucide-react';
import * as api from './services/api';

const Card = ({ children, className }) => (
  <div className={`bg-slate-900/50 border border-slate-800 rounded-lg backdrop-blur-sm ${className}`}>
    {children}
  </div>
);

// ── Futures section ────────────────────────────────────────────────────────────

const FuturesPick = ({ label, color, team, mvp, isCorrect }) => {
  const borderColor =
    isCorrect === 1 ? 'border-green-500/40 bg-green-500/5' :
    isCorrect === 0 ? 'border-red-500/40 bg-red-500/5' :
    'border-slate-700/60';

  return (
    <div className={`rounded-xl border p-3 flex items-center gap-3 ${borderColor}`}>
      <div className="flex-1 min-w-0">
        <p className={`text-[10px] font-black uppercase tracking-wider mb-1 ${color}`}>{label}</p>
        {team ? (
          <div className="flex items-center gap-2">
            <img src={team.logo_url} alt="" className="w-8 h-8 shrink-0" onError={e => e.target.style.display = 'none'} />
            <span className="text-sm font-black text-white truncate">{team.name}</span>
          </div>
        ) : mvp ? (
          <p className="text-sm font-bold text-white truncate">{mvp}</p>
        ) : (
          <p className="text-xs text-slate-600 italic">Not picked</p>
        )}
      </div>
      {isCorrect === 1 && <CheckCircle className="w-5 h-5 text-green-400 shrink-0" />}
      {isCorrect === 0 && <XCircle className="w-5 h-5 text-red-400 shrink-0" />}
    </div>
  );
};

// ── Community picks section ────────────────────────────────────────────────────

const PickBar = ({ label, color, items, icon: Icon }) => {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? items : items.slice(0, 3);
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5 mb-2">
        {Icon && <Icon className={`w-3 h-3 ${color}`} />}
        <p className={`text-[10px] font-black uppercase tracking-wider ${color}`}>{label}</p>
      </div>
      {shown.map((item, i) => (
        <div key={i} className="flex items-center gap-2">
          {item.team ? (
            <>
              <img src={item.team.logo_url} alt="" className="w-5 h-5 shrink-0" onError={e => e.target.style.display = 'none'} />
              <span className="text-xs text-slate-300 font-bold w-8">{item.team.abbreviation}</span>
            </>
          ) : (
            <span className="text-xs text-slate-300 font-bold flex-shrink-0 max-w-[80px] truncate">{item.name}</span>
          )}
          <div className="flex-1 h-2 bg-slate-800 rounded-full overflow-hidden">
            <div className="h-full bg-orange-500/70 rounded-full" style={{ width: `${item.pct}%` }} />
          </div>
          <span className="text-[10px] text-slate-500 font-bold w-10 text-right">{item.pct}%</span>
          <span className="text-[10px] text-slate-600 w-6 text-right">{item.count}</span>
        </div>
      ))}
      {items.length > 3 && (
        <button onClick={() => setExpanded(v => !v)} className="text-[10px] text-slate-500 hover:text-slate-300 flex items-center gap-1 mt-1">
          {expanded ? <><ChevronUp className="w-3 h-3" />Show less</> : <><ChevronDown className="w-3 h-3" />+{items.length - 3} more</>}
        </button>
      )}
    </div>
  );
};

// ── Main page ──────────────────────────────────────────────────────────────────

const MyPredictionsPage = ({ currentUser }) => {
  const [predictions, setPredictions] = useState({ playoff_predictions: [], playin_predictions: [], futures_prediction: null, total_predictions: 0 });
  const [community, setCommunity] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showCommunity, setShowCommunity] = useState(false);

  useEffect(() => {
    if (currentUser) {
      loadPredictions();
    }
  }, [currentUser]);

  const loadPredictions = async () => {
    setLoading(true);
    try {
      const [data, comm] = await Promise.all([
        api.getMyPredictions(currentUser.user_id, '2026'),
        api.getFuturesAll('2026'),
      ]);
      setPredictions(data);
      setCommunity(comm);
    } catch (err) {
      console.error('Error loading predictions:', err);
    } finally {
      setLoading(false);
    }
  };

  if (!currentUser) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-12 text-center">
        <h2 className="text-3xl font-bold text-white mb-4">Please Login</h2>
        <p className="text-slate-400">You need to be logged in to view your predictions</p>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <div className="mb-8">
        <h1 className="text-2xl md:text-4xl font-black text-white mb-2">My Predictions</h1>
        <p className="text-slate-400 text-sm">Track all your playoff picks</p>
      </div>

      {loading ? (
        <div className="text-center py-12">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-4 border-orange-500 border-t-transparent"></div>
        </div>
      ) : (
        <>
          {/* Stats row */}
          <div className="grid grid-cols-3 gap-3 md:gap-6 mb-8">
            <Card className="p-4 md:p-6 text-center">
              <div className="text-3xl md:text-4xl font-black text-orange-400 mb-1 md:mb-2">{predictions.total_predictions}</div>
              <div className="text-slate-400 text-xs md:text-sm">Total Predictions</div>
            </Card>
            <Card className="p-4 md:p-6 text-center">
              <div className="text-3xl md:text-4xl font-black text-green-400 mb-1 md:mb-2">
                {predictions.playoff_predictions.filter(p => p.is_correct === 1).length}
              </div>
              <div className="text-slate-400 text-xs md:text-sm">Correct</div>
            </Card>
            <Card className="p-4 md:p-6 text-center">
              <div className="text-3xl md:text-4xl font-black text-blue-400 mb-1 md:mb-2">
                {predictions.playoff_predictions.reduce((sum, p) => sum + (p.points_earned || 0), 0)}
              </div>
              <div className="text-slate-400 text-xs md:text-sm">Points Earned</div>
            </Card>
          </div>

          {/* ── Futures Prediction ── */}
          <div className="mb-8">
            <h2 className="text-xl md:text-2xl font-bold text-white mb-4 flex items-center gap-2">
              <Star className="w-5 h-5 text-yellow-400" />
              Futures Picks
              {predictions.futures_prediction?.points_earned > 0 && (
                <span className="ml-auto px-3 py-1 rounded-full bg-green-500/20 border border-green-500/30 text-green-400 text-sm font-black">
                  +{predictions.futures_prediction.points_earned} pts
                </span>
              )}
            </h2>
            {predictions.futures_prediction ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Card className="p-4 space-y-3">
                  <p className="text-xs font-black text-slate-500 uppercase tracking-wider">Champions</p>
                  <FuturesPick label="NBA Champion" color="text-yellow-400"
                    team={predictions.futures_prediction.champion_team}
                    isCorrect={predictions.futures_prediction.is_correct_champion} />
                  <FuturesPick label="Western Champion" color="text-red-400"
                    team={predictions.futures_prediction.west_champ_team}
                    isCorrect={predictions.futures_prediction.is_correct_west} />
                  <FuturesPick label="Eastern Champion" color="text-blue-400"
                    team={predictions.futures_prediction.east_champ_team}
                    isCorrect={predictions.futures_prediction.is_correct_east} />
                </Card>
                <Card className="p-4 space-y-3">
                  <p className="text-xs font-black text-slate-500 uppercase tracking-wider">MVPs</p>
                  <FuturesPick label="Finals MVP" color="text-yellow-400"
                    mvp={predictions.futures_prediction.finals_mvp} />
                  <FuturesPick label="West Finals MVP" color="text-red-400"
                    mvp={predictions.futures_prediction.west_finals_mvp} />
                  <FuturesPick label="East Finals MVP" color="text-blue-400"
                    mvp={predictions.futures_prediction.east_finals_mvp} />
                </Card>
              </div>
            ) : (
              <Card className="p-6 text-center">
                <Star className="w-10 h-10 text-slate-700 mx-auto mb-3" />
                <p className="text-slate-400 font-bold mb-1">No futures picks yet</p>
                <p className="text-slate-600 text-sm">Go to the Home page to predict the NBA Champion, Conference Winners and Finals MVPs.</p>
              </Card>
            )}
          </div>

          {/* ── Community Picks ── */}
          {community && community.total_entries > 0 && (
            <div className="mb-8">
              <button
                onClick={() => setShowCommunity(v => !v)}
                className="w-full flex items-center justify-between px-5 py-4 rounded-2xl bg-slate-900/60 border border-slate-800 hover:border-slate-700 transition-all mb-3"
              >
                <div className="flex items-center gap-2">
                  <Users className="w-5 h-5 text-purple-400" />
                  <span className="text-lg font-black text-white">Community Futures Picks</span>
                  <span className="px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-400 text-xs font-black">{community.total_entries} users</span>
                </div>
                {showCommunity ? <ChevronUp className="w-5 h-5 text-slate-400" /> : <ChevronDown className="w-5 h-5 text-slate-400" />}
              </button>

              {showCommunity && (
                <div className="space-y-4">
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <Card className="p-4">
                      <PickBar label="NBA Champion" color="text-yellow-400" icon={Trophy} items={community.champion} />
                    </Card>
                    <Card className="p-4">
                      <PickBar label="Western Champion" color="text-red-400" icon={Trophy} items={community.west_champ} />
                    </Card>
                    <Card className="p-4">
                      <PickBar label="Eastern Champion" color="text-blue-400" icon={Trophy} items={community.east_champ} />
                    </Card>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <Card className="p-4">
                      <PickBar label="Finals MVP" color="text-yellow-400" icon={Star} items={community.finals_mvp} />
                    </Card>
                    <Card className="p-4">
                      <PickBar label="West Finals MVP" color="text-red-400" icon={Star} items={community.west_finals_mvp} />
                    </Card>
                    <Card className="p-4">
                      <PickBar label="East Finals MVP" color="text-blue-400" icon={Star} items={community.east_finals_mvp} />
                    </Card>
                  </div>

                  {/* All user entries table */}
                  <Card className="overflow-hidden">
                    <div className="px-5 py-3 border-b border-slate-800 flex items-center gap-2">
                      <BarChart2 className="w-4 h-4 text-slate-400" />
                      <p className="text-sm font-black text-white">All Picks</p>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead className="bg-slate-800/50">
                          <tr>
                            <th className="px-4 py-2 text-left text-[10px] font-bold text-slate-400 uppercase">User</th>
                            <th className="px-3 py-2 text-center text-[10px] font-bold text-slate-400 uppercase">Champion</th>
                            <th className="px-3 py-2 text-center text-[10px] font-bold text-slate-400 uppercase">West</th>
                            <th className="px-3 py-2 text-center text-[10px] font-bold text-slate-400 uppercase">East</th>
                            <th className="px-3 py-2 text-center text-[10px] font-bold text-slate-400 uppercase">Finals MVP</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800/60">
                          {community.entries.map((entry, i) => (
                            <tr key={i} className={`hover:bg-slate-800/30 transition-colors ${entry.username === currentUser.username ? 'bg-orange-500/5' : ''}`}>
                              <td className="px-4 py-2.5">
                                <span className={`font-bold ${entry.username === currentUser.username ? 'text-orange-400' : 'text-white'}`}>
                                  {entry.username === currentUser.username ? 'You' : entry.username}
                                </span>
                              </td>
                              <td className="px-3 py-2.5 text-center">
                                {entry.champion_team ? (
                                  <div className="flex items-center justify-center gap-1">
                                    <img src={entry.champion_team.logo_url} alt="" className="w-5 h-5" onError={e => e.target.style.display = 'none'} />
                                    <span className="text-slate-300 font-bold">{entry.champion_team.abbreviation}</span>
                                  </div>
                                ) : <span className="text-slate-600">—</span>}
                              </td>
                              <td className="px-3 py-2.5 text-center">
                                {entry.west_champ_team ? (
                                  <div className="flex items-center justify-center gap-1">
                                    <img src={entry.west_champ_team.logo_url} alt="" className="w-5 h-5" onError={e => e.target.style.display = 'none'} />
                                    <span className="text-slate-300 font-bold">{entry.west_champ_team.abbreviation}</span>
                                  </div>
                                ) : <span className="text-slate-600">—</span>}
                              </td>
                              <td className="px-3 py-2.5 text-center">
                                {entry.east_champ_team ? (
                                  <div className="flex items-center justify-center gap-1">
                                    <img src={entry.east_champ_team.logo_url} alt="" className="w-5 h-5" onError={e => e.target.style.display = 'none'} />
                                    <span className="text-slate-300 font-bold">{entry.east_champ_team.abbreviation}</span>
                                  </div>
                                ) : <span className="text-slate-600">—</span>}
                              </td>
                              <td className="px-3 py-2.5 text-center text-slate-400">
                                {entry.finals_mvp || <span className="text-slate-600">—</span>}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </Card>
                </div>
              )}
            </div>
          )}

          {/* ── Play-In Predictions ── */}
          {predictions.playin_predictions.length > 0 && (
            <div className="mb-8">
              <h2 className="text-xl md:text-2xl font-bold text-white mb-4 flex items-center">
                <Trophy className="w-6 h-6 mr-2 text-purple-400" />
                Play-In Predictions
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {predictions.playin_predictions.map(pred => (
                  <Card key={pred.id} className="p-4">
                    <div className="flex items-center justify-between">
                      <div className="flex-1">
                        <p className="text-xs text-slate-400 mb-1">{pred.conference} • {pred.game_type}</p>
                        <p className="text-sm text-white">
                          {pred.team1.name} vs {pred.team2.name}
                        </p>
                      </div>
                      <div className="text-right">
                        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-orange-500/20 border border-orange-500/30">
                          <img src={pred.predicted_winner.logo_url} alt="" className="w-6 h-6" onError={(e) => e.target.style.display='none'} />
                          <span className="text-orange-400 text-sm font-bold">{pred.predicted_winner.abbreviation}</span>
                        </div>
                        <p className="text-xs text-slate-500 mt-1">
                          {new Date(pred.predicted_at).toLocaleDateString()}
                        </p>
                      </div>
                    </div>
                  </Card>
                ))}
              </div>
            </div>
          )}

          {/* ── Playoff Predictions ── */}
          {predictions.playoff_predictions.length > 0 && (
            <div>
              <h2 className="text-xl md:text-2xl font-bold text-white mb-4 flex items-center">
                <Trophy className="w-6 h-6 mr-2 text-orange-400" />
                Playoff Predictions
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {predictions.playoff_predictions.map(pred => (
                  <Card key={pred.id} className="p-4">
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex-1">
                        <p className="text-xs text-slate-400 mb-2">{pred.conference} • {pred.round}</p>
                        <div className="flex items-center gap-2">
                          <img src={pred.home_team.logo_url} alt="" className="w-7 h-7" onError={(e) => e.target.style.display='none'} />
                          <span className="text-xs text-slate-300 font-bold">{pred.home_team.abbreviation}</span>
                          <span className="text-slate-600 text-xs">vs</span>
                          <img src={pred.away_team.logo_url} alt="" className="w-7 h-7" onError={(e) => e.target.style.display='none'} />
                          <span className="text-xs text-slate-300 font-bold">{pred.away_team.abbreviation}</span>
                        </div>
                      </div>
                      {pred.is_correct !== null && (
                        pred.is_correct === 1 ? (
                          <CheckCircle className="w-6 h-6 text-green-400" />
                        ) : (
                          <XCircle className="w-6 h-6 text-red-400" />
                        )
                      )}
                    </div>
                    <div className="flex items-center justify-between flex-wrap gap-2 mt-3 pt-3 border-t border-slate-800">
                      <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-orange-500/20 border border-orange-500/30">
                        <img src={pred.predicted_winner.logo_url} alt="" className="w-6 h-6" onError={(e) => e.target.style.display='none'} />
                        <span className="text-orange-400 text-sm font-bold">{pred.predicted_winner.name}</span>
                      </div>
                      {pred.predicted_games && (
                        <div className="flex items-center gap-1 px-3 py-2 rounded-lg bg-blue-500/20 border border-blue-500/30">
                          <span className="text-blue-400 text-sm font-bold">in {pred.predicted_games} games</span>
                        </div>
                      )}
                      {pred.points_earned > 0 && (
                        <div className="px-3 py-2 rounded-lg bg-green-500/20 border border-green-500/30 text-green-400 text-sm font-bold">
                          +{pred.points_earned} pts
                        </div>
                      )}
                    </div>
                    <p className="text-xs text-slate-500 mt-2">
                      {new Date(pred.predicted_at).toLocaleDateString()}
                    </p>
                  </Card>
                ))}
              </div>
            </div>
          )}

          {predictions.total_predictions === 0 && !predictions.futures_prediction && (
            <Card className="p-12 text-center">
              <Clock className="w-16 h-16 text-slate-600 mx-auto mb-4" />
              <p className="text-xl text-slate-400 mb-2">No predictions yet!</p>
              <p className="text-slate-500">Make your first prediction in the Play-In or Playoffs pages</p>
            </Card>
          )}
        </>
      )}
    </div>
  );
};

export default MyPredictionsPage;
