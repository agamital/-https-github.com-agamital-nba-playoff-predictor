import React, { useState, useEffect } from 'react';
import { Trophy, Lock } from 'lucide-react';
import * as api from './services/api';

const Card = ({ children, className }) => (
  <div className={`bg-slate-900/50 border border-slate-800 rounded-lg backdrop-blur-sm ${className}`}>
    {children}
  </div>
);

const Button = ({ children, onClick, className, variant = 'default', ...props }) => {
  const baseClass = 'px-4 py-2 rounded-lg font-semibold transition-all';
  const variants = {
    default: 'bg-orange-500 hover:bg-orange-600 text-white',
    outline: 'border-2 border-slate-700 bg-slate-800/50 text-white hover:bg-slate-700',
  };
  return (
    <button onClick={onClick} className={`${baseClass} ${variants[variant]} ${className}`} {...props}>
      {children}
    </button>
  );
};

const PlayInPage = ({ currentUser }) => {
  const [games, setGames] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadGames();
  }, []);

  const loadGames = async () => {
    setLoading(true);
    try {
      const data = await api.getPlayInGames('2026');
      setGames(data);
    } catch (err) {
      console.error('Error loading play-in games:', err);
    } finally {
      setLoading(false);
    }
  };

  const handlePrediction = async (gameId, teamId) => {
    if (!currentUser) {
      alert('Please login to make predictions');
      return;
    }

    try {
      await api.makePlayInPrediction(currentUser.user_id, gameId, teamId);
      alert('Prediction saved!');
      loadGames();
    } catch (err) {
      alert('Error: ' + (err.response?.data?.detail || 'Unknown error'));
    }
  };

  const GameCard = ({ game }) => (
    <Card className="p-6">
      <div className="flex justify-between items-center mb-4">
        <span className="text-xs font-bold text-orange-400 uppercase">{game.conference} Conference</span>
        <span className="text-xs font-semibold px-3 py-1 rounded-full bg-purple-500/20 text-purple-400 border border-purple-500/30">
          {game.game_type === '7v8' ? '7 vs 8 Game' : '9 vs 10 Game'}
        </span>
      </div>

      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3 flex-1">
            <img
              src={game.team1.logo_url}
              alt={game.team1.name}
              className="w-12 h-12"
              onError={(e) => e.target.src = `https://via.placeholder.com/48?text=${game.team1.abbreviation}`}
            />
            <div>
              <p className="font-bold text-white">{game.team1.name}</p>
              <p className="text-xs text-slate-400">Seed #{game.team1.seed}</p>
            </div>
          </div>

          <div className="text-slate-600 font-black text-2xl px-4">VS</div>

          <div className="flex items-center space-x-3 flex-1 justify-end">
            <div className="text-right">
              <p className="font-bold text-white">{game.team2.name}</p>
              <p className="text-xs text-slate-400">Seed #{game.team2.seed}</p>
            </div>
            <img
              src={game.team2.logo_url}
              alt={game.team2.name}
              className="w-12 h-12"
              onError={(e) => e.target.src = `https://via.placeholder.com/48?text=${game.team2.abbreviation}`}
            />
          </div>
        </div>

        {currentUser ? (
          <div className="grid grid-cols-2 gap-3 mt-4">
            <Button onClick={() => handlePrediction(game.id, game.team1.id)}>
              Pick {game.team1.abbreviation}
            </Button>
            <Button onClick={() => handlePrediction(game.id, game.team2.id)}>
              Pick {game.team2.abbreviation}
            </Button>
          </div>
        ) : (
          <div className="flex items-center justify-center py-3 bg-slate-800/50 rounded-lg text-slate-400 text-sm">
            <Lock className="w-4 h-4 mr-2" />
            Login to make predictions
          </div>
        )}
      </div>
    </Card>
  );

  const groupedGames = games.reduce((acc, game) => {
    if (!acc[game.conference]) acc[game.conference] = [];
    acc[game.conference].push(game);
    return acc;
  }, {});

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <div className="mb-8">
        <h1 className="text-4xl font-black text-white mb-2">Play-In Tournament</h1>
        <p className="text-slate-400 text-lg">Seeds 7-10 compete for playoff spots</p>
      </div>

      {loading ? (
        <div className="text-center py-12">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-4 border-orange-500 border-t-transparent"></div>
        </div>
      ) : games.length > 0 ? (
        <div className="space-y-8">
          {Object.entries(groupedGames).map(([conference, confGames]) => (
            <div key={conference}>
              <h2 className="text-2xl font-bold text-white mb-4 flex items-center">
                <Trophy className="w-6 h-6 mr-2 text-orange-400" />
                {conference} Conference
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {confGames.map(game => <GameCard key={game.id} game={game} />)}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <Card className="p-8 text-center">
          <p className="text-slate-400">No play-in games available yet. Admin needs to generate them from standings page.</p>
        </Card>
      )}
    </div>
  );
};

export default PlayInPage;