import React, { useState, useEffect } from 'react';
import { RefreshCw, Trophy } from 'lucide-react';
import * as api from './services/api';

const Card = ({ children, className }) => (
  <div className={`bg-slate-900/50 border border-slate-800 rounded-lg backdrop-blur-sm ${className}`}>
    {children}
  </div>
);

const Button = ({ children, onClick, className, variant = 'default', disabled, ...props }) => {
  const baseClass = 'px-4 py-2 rounded-lg font-semibold transition-all';
  const variants = {
    default: 'bg-orange-500 hover:bg-orange-600 text-white',
    outline: 'border-2 border-slate-700 bg-slate-800/50 text-white hover:bg-slate-700',
  };
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`${baseClass} ${variants[variant]} ${className} ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
      {...props}
    >
      {children}
    </button>
  );
};

const StandingsPage = ({ currentUser }) => {
  const [standings, setStandings] = useState({ eastern: [], western: [] });
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(null);

  useEffect(() => {
    loadStandings();
  }, []);

  const loadStandings = async () => {
    setLoading(true);
    try {
      const data = await api.getStandings();
      setStandings(data);
      setLastUpdated(data.last_updated);
    } catch (err) {
      console.error('Error loading standings:', err);
    } finally {
      setLoading(false);
    }
  };

  const StandingsTable = ({ teams, conference }) => (
    <Card className="overflow-hidden">
      <div className="bg-gradient-to-r from-orange-500 to-red-600 px-6 py-4">
        <h2 className="text-2xl font-black text-white flex items-center">
          <Trophy className="w-6 h-6 mr-2" />
          {conference} Conference
        </h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-slate-800/50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-bold text-slate-400 uppercase">Rank</th>
              <th className="px-4 py-3 text-left text-xs font-bold text-slate-400 uppercase">Team</th>
              <th className="px-4 py-3 text-center text-xs font-bold text-slate-400 uppercase">W</th>
              <th className="px-4 py-3 text-center text-xs font-bold text-slate-400 uppercase">L</th>
              <th className="px-4 py-3 text-center text-xs font-bold text-slate-400 uppercase">Win%</th>
              <th className="px-4 py-3 text-center text-xs font-bold text-slate-400 uppercase">Seed</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {teams.map((team, idx) => {
              const isPlayoff = idx < 6;
              const isPlayIn = idx >= 6 && idx < 10;
              
              return (
                <tr
                  key={team.team_id}
                  className={`hover:bg-slate-800/30 transition-colors ${
                    isPlayoff ? 'bg-green-500/5' : isPlayIn ? 'bg-yellow-500/5' : ''
                  }`}
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center">
                      <span className={`font-bold ${isPlayoff ? 'text-green-400' : isPlayIn ? 'text-yellow-400' : 'text-slate-500'}`}>
                        {team.conf_rank}
                      </span>
                      {isPlayoff && <span className="ml-2 text-xs text-green-400">●</span>}
                      {isPlayIn && <span className="ml-2 text-xs text-yellow-400">●</span>}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center space-x-3">
                      <img
                        src={`https://cdn.nba.com/logos/nba/${team.team_id}/primary/L/logo.svg`}
                        alt={team.team_name}
                        className="w-10 h-10"
                        onError={(e) => e.target.style.display = 'none'}
                      />
                      <span className="font-semibold text-white">{team.team_name}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-center font-bold text-white">{team.wins}</td>
                  <td className="px-4 py-3 text-center font-bold text-slate-400">{team.losses}</td>
                  <td className="px-4 py-3 text-center text-slate-300">{(team.win_pct * 100).toFixed(1)}%</td>
                  <td className="px-4 py-3 text-center">
                    {isPlayoff && <span className="px-2 py-1 rounded bg-green-500/20 text-green-400 text-xs font-bold">{idx + 1}</span>}
                    {isPlayIn && <span className="px-2 py-1 rounded bg-yellow-500/20 text-yellow-400 text-xs font-bold">PI</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="px-6 py-4 bg-slate-800/30 border-t border-slate-800 text-xs text-slate-400">
        <div className="flex items-center space-x-4">
          <div className="flex items-center">
            <span className="w-3 h-3 rounded-full bg-green-500/30 mr-2"></span>
            <span>Playoff Bound (1-6)</span>
          </div>
          <div className="flex items-center">
            <span className="w-3 h-3 rounded-full bg-yellow-500/30 mr-2"></span>
            <span>Play-In (7-10)</span>
          </div>
        </div>
      </div>
    </Card>
  );

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-4xl font-black text-white mb-2">Live NBA Standings</h1>
          {lastUpdated && (
            <p className="text-sm text-slate-400">
              Last updated: {new Date(lastUpdated).toLocaleString()}
            </p>
          )}
        </div>
        <Button onClick={loadStandings} variant="outline" disabled={loading}>
          <RefreshCw className={`w-4 h-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {loading ? (
        <div className="text-center py-12">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-4 border-orange-500 border-t-transparent"></div>
          <p className="text-slate-400 mt-4">Loading standings...</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <StandingsTable teams={standings.eastern} conference="Eastern" />
          <StandingsTable teams={standings.western} conference="Western" />
        </div>
      )}
    </div>
  );
};

export default StandingsPage;