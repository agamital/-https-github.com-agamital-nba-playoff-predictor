import React, { useState, useEffect } from 'react';
import { Trophy, Users, Target, BarChart3, Home as HomeIcon, LogOut, Menu, X, RefreshCw, Lock } from 'lucide-react';
import * as api from './services/api';
import StandingsPage from './StandingsPage';
import PlayInPage from './PlayInPage';
import './index.css';
import MyPredictionsPage from './MyPredictionsPage';

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

const Card = ({ children, className }) => (
  <div className={`bg-slate-900/50 border border-slate-800 rounded-lg backdrop-blur-sm ${className}`}>
    {children}
  </div>
);

const HomePage = ({ currentUser, onNavigate, onLogin }) => {
  const [loginMode, setLoginMode] = useState(true);
  const [formData, setFormData] = useState({ username: '', email: '', password: '' });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      if (loginMode) {
        const user = await api.login(formData.username, formData.password);
        onLogin(user);
      } else {
        const user = await api.register(formData.username, formData.email, formData.password);
        onLogin(user);
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  if (currentUser) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-12">
        <div className="text-center mb-16">
          <div className="inline-flex items-center px-4 py-2 rounded-full bg-orange-500/20 border border-orange-500/30 mb-6">
            <span className="text-sm font-bold text-orange-400">✨ 2026 PLAYOFFS</span>
          </div>
          <h1 className="text-6xl font-black text-white mb-6">
            NBA PLAYOFF<br />
            <span className="bg-gradient-to-r from-orange-400 to-red-500 bg-clip-text text-transparent">
              PREDICTOR
            </span>
          </h1>
          <p className="text-xl text-slate-300 mb-10">
            Welcome back, <strong>{currentUser.username}</strong>!
          </p>
          <div className="flex gap-4 justify-center">
            <Button onClick={() => onNavigate('betting')} className="px-8 py-4 text-lg">
              Make Predictions →
            </Button>
            <Button onClick={() => onNavigate('leaderboard')} variant="outline" className="px-8 py-4 text-lg">
              View Leaderboard
            </Button>
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <Card className="p-6 text-center">
            <div className="text-4xl font-black text-orange-400 mb-2">{currentUser.points || 0}</div>
            <div className="text-slate-400">Total Points</div>
          </Card>
          <Card className="p-6 text-center">
            <div className="text-4xl font-black text-blue-400 mb-2">0</div>
            <div className="text-slate-400">Predictions Made</div>
          </Card>
          <Card className="p-6 text-center">
            <div className="text-4xl font-black text-green-400 mb-2">0%</div>
            <div className="text-slate-400">Accuracy</div>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-md mx-auto px-4 py-12">
      <div className="text-center mb-8">
        <h1 className="text-4xl font-black text-white mb-2">
          {loginMode ? 'Welcome Back' : 'Join Now'}
        </h1>
        <p className="text-slate-400">
          {loginMode ? 'Login to your account' : 'Create your account'}
        </p>
      </div>
      <Card className="p-6">
        <form onSubmit={handleSubmit} className="space-y-4">
          <input
            type="text"
            placeholder="Username"
            value={formData.username}
            onChange={(e) => setFormData({ ...formData, username: e.target.value })}
            className="w-full px-4 py-3 bg-slate-800 border border-slate-700 rounded-lg text-white"
            required
          />
          {!loginMode && (
            <input
              type="email"
              placeholder="Email"
              value={formData.email}
              onChange={(e) => setFormData({ ...formData, email: e.target.value })}
              className="w-full px-4 py-3 bg-slate-800 border border-slate-700 rounded-lg text-white"
              required
            />
          )}
          <input
            type="password"
            placeholder="Password"
            value={formData.password}
            onChange={(e) => setFormData({ ...formData, password: e.target.value })}
            className="w-full px-4 py-3 bg-slate-800 border border-slate-700 rounded-lg text-white"
            required
          />
          {error && <p className="text-red-400 text-sm">{error}</p>}
          <Button type="submit" className="w-full py-3" disabled={loading}>
            {loading ? 'Loading...' : loginMode ? 'Login' : 'Sign Up'}
          </Button>
        </form>
        <div className="mt-4 text-center">
          <button
            onClick={() => setLoginMode(!loginMode)}
            className="text-orange-400 hover:text-orange-300 text-sm"
          >
            {loginMode ? "Don't have an account? Sign up" : 'Already have an account? Login'}
          </button>
        </div>
      </Card>
    </div>
  );
};

const TeamsPage = () => {
  const [teams, setTeams] = useState([]);
  const [filter, setFilter] = useState('all');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadTeams();
  }, [filter]);

  const loadTeams = async () => {
    setLoading(true);
    try {
      const data = await api.getTeams(filter === 'all' ? null : filter);
      setTeams(data);
    } catch (err) {
      console.error('Error loading teams:', err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <h1 className="text-4xl font-black text-white mb-6">NBA Teams</h1>
      <div className="flex gap-3 mb-6">
        <Button onClick={() => setFilter('all')} variant={filter === 'all' ? 'default' : 'outline'}>
          All Teams
        </Button>
        <Button onClick={() => setFilter('Eastern')} variant={filter === 'Eastern' ? 'default' : 'outline'}>
          Eastern
        </Button>
        <Button onClick={() => setFilter('Western')} variant={filter === 'Western' ? 'default' : 'outline'}>
          Western
        </Button>
      </div>
      {loading ? (
        <div className="text-center py-12">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-4 border-orange-500 border-t-transparent"></div>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {teams.map((team) => (
            <Card key={team.id} className="p-4 hover:bg-slate-800/50 transition-all cursor-pointer">
              <div className="flex items-center space-x-3">
                <img
                  src={team.logo_url}
                  alt={team.name}
                  className="w-12 h-12"
                  onError={(e) => e.target.src = 'https://via.placeholder.com/48?text=' + team.abbreviation}
                />
                <div className="flex-1 min-w-0">
                  <h3 className="font-bold text-white truncate">{team.name}</h3>
                  <p className="text-sm text-slate-400">{team.conference}</p>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
};

const BettingPage = ({ currentUser }) => {
  const [series, setSeries] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadSeries();
  }, []);

  const loadSeries = async () => {
    try {
      const data = await api.getSeries('2026');
      setSeries(data);
    } catch (err) {
      console.error('Error loading series:', err);
    } finally {
      setLoading(false);
    }
  };

  const handlePrediction = async (seriesId, teamId) => {
    if (!currentUser) {
      alert('Please login to make predictions');
      return;
    }
    try {
      await api.makePrediction(currentUser.user_id, seriesId, teamId);
      alert('Prediction saved!');
    } catch (err) {
      alert('Error: ' + (err.response?.data?.detail || 'Unknown error'));
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
    <div className="max-w-7xl mx-auto px-4 py-8">
      <h1 className="text-4xl font-black text-white mb-6">Make Predictions</h1>
      {loading ? (
        <div className="text-center py-12">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-4 border-orange-500 border-t-transparent"></div>
        </div>
      ) : series.length > 0 ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {series.map((s) => (
            <Card key={s.id} className="p-6">
              <div className="flex justify-between items-center mb-4">
                <span className="text-xs font-bold text-orange-400 uppercase">{s.conference} Conference</span>
                <span className="text-xs text-slate-400">{s.round}</span>
              </div>
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-3">
                    <img
                      src={s.home_team.logo_url}
                      alt={s.home_team.name}
                      className="w-10 h-10"
                      onError={(e) => e.target.src = `https://via.placeholder.com/40?text=${s.home_team.abbreviation}`}
                    />
                    <div>
                      <p className="font-bold text-white">{s.home_team.name}</p>
                      <p className="text-xs text-slate-400">Seed {s.home_team.seed} • Wins: {s.home_wins}</p>
                    </div>
                  </div>
                  <div className="text-slate-600 font-black text-xl">VS</div>
                  <div className="flex items-center space-x-3">
                    <div className="text-right">
                      <p className="font-bold text-white">{s.away_team.name}</p>
                      <p className="text-xs text-slate-400">Seed {s.away_team.seed} • Wins: {s.away_wins}</p>
                    </div>
                    <img
                      src={s.away_team.logo_url}
                      alt={s.away_team.name}
                      className="w-10 h-10"
                      onError={(e) => e.target.src = `https://via.placeholder.com/40?text=${s.away_team.abbreviation}`}
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <Button onClick={() => handlePrediction(s.id, s.home_team.id)}>
                    Pick {s.home_team.abbreviation}
                  </Button>
                  <Button onClick={() => handlePrediction(s.id, s.away_team.id)}>
                    Pick {s.away_team.abbreviation}
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <Card className="p-8 text-center">
          <p className="text-slate-400">No active series available. Check back when playoffs begin!</p>
        </Card>
      )}
    </div>
  );
};

const LeaderboardPage = () => {
  const [leaderboard, setLeaderboard] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadLeaderboard();
  }, []);

  const loadLeaderboard = async () => {
    try {
      const data = await api.getLeaderboard('2026');
      setLeaderboard(data);
    } catch (err) {
      console.error('Error loading leaderboard:', err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <h1 className="text-4xl font-black text-white mb-8">Leaderboard</h1>
      {loading ? (
        <div className="text-center py-12">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-4 border-orange-500 border-t-transparent"></div>
        </div>
      ) : (
        <div className="space-y-3">
          {leaderboard.map((user) => (
            <Card key={user.rank} className="p-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-4">
                  <div className="w-10 h-10 bg-gradient-to-br from-orange-500 to-red-600 rounded-full flex items-center justify-center text-white font-bold">
                    {user.rank}
                  </div>
                  <div>
                    <p className="font-bold text-white">{user.username}</p>
                    <p className="text-xs text-slate-400">
                      {user.correct_predictions}/{user.total_predictions} correct • {user.accuracy}% accuracy
                    </p>
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-2xl font-black text-orange-400">{user.points}</div>
                  <div className="text-xs text-slate-400">points</div>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
};

function App() {
  const [currentPage, setCurrentPage] = useState('home');
  const [currentUser, setCurrentUser] = useState(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem('nba_user');
    if (stored) setCurrentUser(JSON.parse(stored));
  }, []);

  const handleLogin = (user) => {
    setCurrentUser(user);
    localStorage.setItem('nba_user', JSON.stringify(user));
    setCurrentPage('home');
  };

  const handleLogout = () => {
    setCurrentUser(null);
    localStorage.removeItem('nba_user');
    setCurrentPage('home');
  };

  const navigate = (page) => {
    setCurrentPage(page);
    setMobileMenuOpen(false);
  };

  const navItems = [
    { id: 'home', label: 'Home', icon: HomeIcon },
    { id: 'standings', label: 'Standings', icon: BarChart3 },
    { id: 'playin', label: 'Play-In', icon: Trophy },
    { id: 'betting', label: 'Playoffs', icon: Target },
    { id: 'leaderboard', label: 'Leaderboard', icon: Users },
    { id: 'teams', label: 'Teams', icon: BarChart3 },
{ id: 'mypredictions', label: 'My Picks', icon: Target },
  ];

  const renderPage = () => {
    const props = { currentUser, onNavigate: navigate, onLogin: handleLogin };
    switch (currentPage) {
      case 'home': return <HomePage {...props} />;
      case 'standings': return <StandingsPage currentUser={currentUser} />;
      case 'playin': return <PlayInPage currentUser={currentUser} />;
      case 'teams': return <TeamsPage />;
      case 'betting': return <BettingPage currentUser={currentUser} />;
      case 'leaderboard': return <LeaderboardPage />;
      case 'mypredictions': return <MyPredictionsPage currentUser={currentUser} />;
      default: return <HomePage {...props} />;
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-blue-950 to-slate-900">
      <aside className="hidden md:fixed md:inset-y-0 md:flex md:w-64 md:flex-col">
        <div className="flex flex-col flex-grow pt-5 bg-slate-900/50 backdrop-blur-xl border-r border-blue-500/20">
          <div className="flex items-center px-4 mb-8">
            <div className="w-12 h-12 bg-gradient-to-br from-orange-500 to-red-600 rounded-xl flex items-center justify-center mr-3">
              <Trophy className="w-7 h-7 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-black text-white">NBA PLAYOFF</h1>
              <p className="text-xs font-bold text-orange-400">PREDICTOR 2026</p>
            </div>
          </div>
          <nav className="flex-1 px-2 space-y-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              return (
                <button key={item.id} onClick={() => navigate(item.id)}
                  className={`group flex items-center w-full px-3 py-3 text-sm font-semibold rounded-xl transition-all ${
                    currentPage === item.id ? 'bg-gradient-to-r from-orange-500 to-red-600 text-white shadow-lg' : 'text-slate-300 hover:bg-slate-800/50'
                  }`}>
                  <Icon className="mr-3 h-5 w-5" />
                  {item.label}
                </button>
              );
            })}
          </nav>
          {currentUser && (
            <div className="p-4 border-t border-blue-500/20">
              <div className="flex items-center mb-3 px-2">
                <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-600 rounded-full flex items-center justify-center text-white font-bold mr-3">
                  {currentUser.username[0].toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-white truncate">{currentUser.username}</p>
                  <p className="text-xs text-slate-400">{currentUser.points || 0} pts</p>
                </div>
              </div>
              <Button onClick={handleLogout} variant="outline" className="w-full">
                <LogOut className="w-4 h-4 mr-2" />
                Logout
              </Button>
            </div>
          )}
        </div>
      </aside>
      <div className="md:hidden sticky top-0 z-50 bg-slate-900/95 backdrop-blur-xl border-b border-blue-500/20">
        <div className="flex items-center justify-between px-4 py-3">
          <div className="flex items-center space-x-2">
            <div className="w-10 h-10 bg-gradient-to-br from-orange-500 to-red-600 rounded-lg flex items-center justify-center">
              <Trophy className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-black text-white">NBA PLAYOFF</h1>
              <p className="text-[10px] font-bold text-orange-400">PREDICTOR 2026</p>
            </div>
          </div>
          <button onClick={() => setMobileMenuOpen(!mobileMenuOpen)} className="p-2 rounded-lg bg-slate-800/50 text-white">
            {mobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
          </button>
        </div>
        {mobileMenuOpen && (
          <div className="bg-slate-900/98 border-b border-blue-500/20 p-2">
            <nav className="space-y-1">
              {navItems.map((item) => {
                const Icon = item.icon;
                return (
                  <button key={item.id} onClick={() => navigate(item.id)}
                    className={`flex items-center w-full px-3 py-3 rounded-xl ${
                      currentPage === item.id ? 'bg-gradient-to-r from-orange-500 to-red-600 text-white' : 'text-slate-300'
                    }`}>
                    <Icon className="mr-3 h-5 w-5" />
                    {item.label}
                  </button>
                );
              })}
              {currentUser && (
                <button onClick={handleLogout} className="flex items-center w-full px-3 py-3 text-red-400">
                  <LogOut className="mr-3 h-5 w-5" />
                  Logout
                </button>
              )}
            </nav>
          </div>
        )}
      </div>
      <main className="md:pl-64 min-h-screen">
        {renderPage()}
      </main>
    </div>
  );
}

export default App;