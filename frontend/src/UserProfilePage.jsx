import React, { useState, useEffect } from 'react';
import { Trophy, CheckCircle, XCircle, Star, ArrowLeft, Medal } from 'lucide-react';
import * as api from './services/api';

const Card = ({ children, className = '' }) => (
  <div className={`bg-slate-900/50 border border-slate-800 rounded-lg backdrop-blur-sm ${className}`}>
    {children}
  </div>
);

export const Avatar = ({ username, avatarUrl, size = 'md' }) => {
  const sizes = {
    sm:  'w-8 h-8 text-sm',
    md:  'w-12 h-12 text-lg',
    lg:  'w-20 h-20 text-3xl',
    xl:  'w-28 h-28 text-4xl',
  };
  if (avatarUrl) {
    return (
      <img
        src={avatarUrl}
        alt={username}
        className={`${sizes[size]} rounded-full object-cover ring-2 ring-slate-700`}
        onError={(e) => { e.target.onerror = null; e.target.style.display = 'none'; }}
      />
    );
  }
  return (
    <div className={`${sizes[size]} bg-gradient-to-br from-blue-500 to-purple-600 rounded-full flex items-center justify-center text-white font-black shrink-0`}>
      {username?.[0]?.toUpperCase() || '?'}
    </div>
  );
};

const FuturesPick = ({ label, color, team, mvp, isCorrect }) => {
  const border =
    isCorrect === 1 ? 'border-green-500/40 bg-green-500/5' :
    isCorrect === 0 ? 'border-red-500/40 bg-red-500/5' :
    'border-slate-700/60';
  return (
    <div className={`rounded-xl border p-3 flex items-center gap-3 ${border}`}>
      <div className="flex-1 min-w-0">
        <p className={`text-[10px] font-black uppercase tracking-wider mb-1 ${color}`}>{label}</p>
        {team ? (
          <div className="flex items-center gap-2">
            <img src={team.logo_url} alt="" className="w-7 h-7 shrink-0" onError={e => e.target.style.display='none'} />
            <span className="text-sm font-black text-white truncate">{team.name}</span>
          </div>
        ) : mvp ? (
          <p className="text-sm font-bold text-white truncate">{mvp}</p>
        ) : (
          <p className="text-xs text-slate-600 italic">Not picked</p>
        )}
      </div>
      {isCorrect === 1 && <CheckCircle className="w-4 h-4 text-green-400 shrink-0" />}
      {isCorrect === 0 && <XCircle className="w-4 h-4 text-red-400 shrink-0" />}
    </div>
  );
};

const UserProfilePage = ({ username, currentUser, onNavigateToProfile }) => {
  const [profile, setProfile] = useState(null);
  const [predictions, setPredictions] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!username) return;
    setLoading(true);
    setError('');
    const load = async () => {
      try {
        const prof = await api.getUserProfile(username);
        setProfile(prof);
        const preds = await api.getMyPredictions(prof.user_id, '2026');
        setPredictions(preds);
      } catch (err) {
        setError(err.response?.status === 404 ? 'User not found.' : 'Failed to load profile.');
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [username]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-orange-500 border-t-transparent" />
      </div>
    );
  }

  if (error || !profile) {
    return (
      <div className="max-w-xl mx-auto px-4 py-16 text-center">
        <p className="text-slate-400 text-lg">{error || 'User not found.'}</p>
      </div>
    );
  }

  const isOwnProfile = currentUser?.username === profile.username;
  const playoff = predictions?.playoff_predictions || [];
  const playin  = predictions?.playin_predictions  || [];
  const futures = predictions?.futures_prediction;
  const correctCount = playoff.filter(p => p.is_correct === 1).length;

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">

      {/* ── Profile header ── */}
      <Card className="p-6 mb-8">
        <div className="flex items-center gap-5">
          <Avatar username={profile.username} avatarUrl={profile.avatar_url} size="xl" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-2xl md:text-3xl font-black text-white truncate">{profile.username}</h1>
              {isOwnProfile && (
                <span className="px-2 py-0.5 rounded-full bg-orange-500/20 border border-orange-500/30 text-orange-400 text-xs font-black">You</span>
              )}
            </div>
            <div className="flex items-center gap-4 mt-3 flex-wrap">
              <div className="flex items-center gap-1.5">
                <Medal className="w-4 h-4 text-yellow-400" />
                <span className="text-yellow-400 font-black text-lg">#{profile.rank}</span>
                <span className="text-slate-500 text-sm">rank</span>
              </div>
              <div className="flex items-center gap-1.5">
                <Trophy className="w-4 h-4 text-orange-400" />
                <span className="text-orange-400 font-black text-lg">{profile.points}</span>
                <span className="text-slate-500 text-sm">points</span>
              </div>
              {playoff.length > 0 && (
                <div className="flex items-center gap-1.5">
                  <CheckCircle className="w-4 h-4 text-green-400" />
                  <span className="text-green-400 font-black text-lg">{correctCount}/{playoff.length}</span>
                  <span className="text-slate-500 text-sm">correct</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </Card>

      {/* ── Futures Picks ── */}
      {futures && (
        <div className="mb-8">
          <h2 className="text-xl font-black text-white mb-4 flex items-center gap-2">
            <Star className="w-5 h-5 text-yellow-400" />
            Futures Picks
            {futures.points_earned > 0 && (
              <span className="ml-auto px-3 py-1 rounded-full bg-green-500/20 border border-green-500/30 text-green-400 text-sm font-black">
                +{futures.points_earned} pts
              </span>
            )}
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Card className="p-4 space-y-3">
              <p className="text-[10px] font-black text-slate-500 uppercase tracking-wider">Champions</p>
              <FuturesPick label="NBA Champion"      color="text-yellow-400" team={futures.champion_team}   isCorrect={futures.is_correct_champion} />
              <FuturesPick label="Western Champion"  color="text-red-400"    team={futures.west_champ_team} isCorrect={futures.is_correct_west} />
              <FuturesPick label="Eastern Champion"  color="text-blue-400"   team={futures.east_champ_team} isCorrect={futures.is_correct_east} />
            </Card>
            <Card className="p-4 space-y-3">
              <p className="text-[10px] font-black text-slate-500 uppercase tracking-wider">MVPs</p>
              <FuturesPick label="Finals MVP"        color="text-yellow-400" mvp={futures.finals_mvp} />
              <FuturesPick label="West Finals MVP"   color="text-red-400"    mvp={futures.west_finals_mvp} />
              <FuturesPick label="East Finals MVP"   color="text-blue-400"   mvp={futures.east_finals_mvp} />
            </Card>
          </div>
        </div>
      )}

      {/* ── Playoff Predictions ── */}
      {playoff.length > 0 && (
        <div className="mb-8">
          <h2 className="text-xl font-black text-white mb-4 flex items-center gap-2">
            <Trophy className="w-5 h-5 text-orange-400" /> Playoff Predictions
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {playoff.map(pred => (
              <Card key={pred.id} className="p-4">
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <p className="text-xs text-slate-400 mb-1.5">{pred.conference} · {pred.round}</p>
                    <div className="flex items-center gap-2">
                      <img src={pred.home_team.logo_url} alt="" className="w-6 h-6" onError={e=>e.target.style.display='none'} />
                      <span className="text-xs text-slate-300 font-bold">{pred.home_team.abbreviation}</span>
                      <span className="text-slate-600 text-xs">vs</span>
                      <img src={pred.away_team.logo_url} alt="" className="w-6 h-6" onError={e=>e.target.style.display='none'} />
                      <span className="text-xs text-slate-300 font-bold">{pred.away_team.abbreviation}</span>
                    </div>
                  </div>
                  {pred.is_correct === 1 && <CheckCircle className="w-5 h-5 text-green-400 shrink-0" />}
                  {pred.is_correct === 0 && <XCircle    className="w-5 h-5 text-red-400   shrink-0" />}
                </div>
                <div className="flex items-center gap-2 flex-wrap pt-3 border-t border-slate-800">
                  <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-orange-500/20 border border-orange-500/30">
                    <img src={pred.predicted_winner.logo_url} alt="" className="w-5 h-5" onError={e=>e.target.style.display='none'} />
                    <span className="text-orange-400 text-xs font-black">{pred.predicted_winner.name}</span>
                  </div>
                  {pred.predicted_games && (
                    <span className="px-3 py-1.5 rounded-lg bg-blue-500/20 border border-blue-500/30 text-blue-400 text-xs font-bold">
                      in {pred.predicted_games}G
                    </span>
                  )}
                  {pred.points_earned > 0 && (
                    <span className="ml-auto px-3 py-1.5 rounded-lg bg-green-500/20 border border-green-500/30 text-green-400 text-xs font-black">
                      +{pred.points_earned} pts
                    </span>
                  )}
                </div>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* ── Play-In Predictions ── */}
      {playin.length > 0 && (
        <div className="mb-8">
          <h2 className="text-xl font-black text-white mb-4 flex items-center gap-2">
            <Trophy className="w-5 h-5 text-purple-400" /> Play-In Predictions
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {playin.map(pred => (
              <Card key={pred.id} className="p-4">
                <p className="text-xs text-slate-400 mb-2">{pred.conference} · {pred.game_type}</p>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-300">{pred.team1.name} vs {pred.team2.name}</span>
                  <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-orange-500/20 border border-orange-500/30">
                    <img src={pred.predicted_winner.logo_url} alt="" className="w-5 h-5" onError={e=>e.target.style.display='none'} />
                    <span className="text-orange-400 text-xs font-black">{pred.predicted_winner.abbreviation}</span>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </div>
      )}

      {!futures && playoff.length === 0 && playin.length === 0 && (
        <Card className="p-12 text-center">
          <Trophy className="w-14 h-14 text-slate-700 mx-auto mb-4" />
          <p className="text-slate-400 font-bold">No predictions yet</p>
        </Card>
      )}
    </div>
  );
};

export default UserProfilePage;
