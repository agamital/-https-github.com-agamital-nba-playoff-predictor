import React, { useState, useEffect } from 'react';
import { Trophy, CheckCircle, XCircle, Clock } from 'lucide-react';
import * as api from './services/api';

const Card = ({ children, className }) => (
  <div className={`bg-slate-900/50 border border-slate-800 rounded-lg backdrop-blur-sm ${className}`}>
    {children}
  </div>
);

const MyPredictionsPage = ({ currentUser }) => {
  const [predictions, setPredictions] = useState({ playoff_predictions: [], playin_predictions: [], total_predictions: 0 });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (currentUser) {
      loadPredictions();
    }
  }, [currentUser]);

  const loadPredictions = async () => {
    setLoading(true);
    try {
      const data = await api.getMyPredictions(currentUser.user_id, '2026');
      setPredictions(data);
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
        <h1 className="text-4xl font-black text-white mb-2">My Predictions</h1>
        <p className="text-slate-400">Track all your playoff picks</p>
      </div>

      {loading ? (
        <div className="text-center py-12">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-4 border-orange-500 border-t-transparent"></div>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
            <Card className="p-6 text-center">
              <div className="text-4xl font-black text-orange-400 mb-2">{predictions.total_predictions}</div>
              <div className="text-slate-400">Total Predictions</div>
            </Card>
            <Card className="p-6 text-center">
              <div className="text-4xl font-black text-green-400 mb-2">
                {predictions.playoff_predictions.filter(p => p.is_correct === 1).length}
              </div>
              <div className="text-slate-400">Correct</div>
            </Card>
            <Card className="p-6 text-center">
              <div className="text-4xl font-black text-blue-400 mb-2">
                {predictions.playoff_predictions.reduce((sum, p) => sum + (p.points_earned || 0), 0)}
              </div>
              <div className="text-slate-400">Points Earned</div>
            </Card>
          </div>

          {predictions.playin_predictions.length > 0 && (
            <div className="mb-8">
              <h2 className="text-2xl font-bold text-white mb-4 flex items-center">
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

          {predictions.playoff_predictions.length > 0 && (
            <div>
              <h2 className="text-2xl font-bold text-white mb-4 flex items-center">
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

          {predictions.total_predictions === 0 && (
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