import React, { useState, useEffect, useRef, lazy, Suspense } from 'react';
import { Trophy, Users, BarChart3, Home as HomeIcon, LogOut, Star, Shield, Download, X, Settings, Info, ChevronDown } from 'lucide-react';
import * as api from './services/api';
import { supabase } from './lib/supabase';
import './index.css';

// Eagerly-loaded small pages
import StandingsPage from './StandingsPage';
import ScoringGuide from './ScoringGuide';

// Lazy-loaded heavy pages (split into separate chunks)
const MyPredictionsPage  = lazy(() => import('./MyPredictionsPage'));
const UserPredictionsPage = lazy(() => import('./UserPredictionsPage'));
const AdminPage          = lazy(() => import('./AdminPage'));
const BracketPage        = lazy(() => import('./BracketPage'));
const FuturesPage        = lazy(() => import('./FuturesPage'));
const UserProfilePage    = lazy(() => import('./UserProfilePage'));
const AccountPage        = lazy(() => import('./AccountPage'));

const PageSpinner = () => (
  <div className="flex items-center justify-center py-24">
    <div className="animate-spin rounded-full h-10 w-10 border-4 border-orange-500 border-t-transparent" />
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

const Card = ({ children, className, onClick }) => (
  <div className={`bg-slate-900/50 border border-slate-800 rounded-lg backdrop-blur-sm ${className}`} onClick={onClick}>
    {children}
  </div>
);

// Google "G" logo SVG
const GoogleIcon = () => (
  <svg className="w-5 h-5" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
    <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
    <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
    <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
    <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
  </svg>
);

const HomePage = ({ currentUser, onNavigate, onLogin }) => {
  const [mode, setMode] = useState('login'); // 'login' | 'reset'
  const [formData, setFormData] = useState({ username: '', password: '', newPassword: '' });
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // Dashboard data when logged in
  const [dashLoading, setDashLoading] = useState(false);
  const [dashData, setDashData] = useState(null);

  useEffect(() => {
    if (!currentUser) return;
    setDashLoading(true);
    console.time('[dash] dashboard fetch');
    api.getDashboard(currentUser.user_id).then(data => {
      console.timeEnd('[dash] dashboard fetch');
      setDashData({
        seriesPredicted: data.series_predicted,
        totalSeries:     data.total_series,
        futuresDone:     data.futures_done,
        leadersDone:     data.leaders_done,
      });
    }).catch(console.error).finally(() => setDashLoading(false));
  }, [currentUser?.user_id]);

  const handleGoogleLogin = async () => {
    if (!supabase) {
      setError('Google login is not configured. Add VITE_SUPABASE_ANON_KEY in Vercel → Settings → Environment Variables.');
      return;
    }
    setGoogleLoading(true);
    setError('');
    try {
      const redirectTo = import.meta.env.VITE_APP_URL || window.location.origin;
      console.log('[Google OAuth] redirectTo:', redirectTo);
      const { data, error: oauthError } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: { redirectTo },
      });
      console.log('[Google OAuth] result:', { data, oauthError });
      if (oauthError) {
        throw new Error(oauthError.message || oauthError.toString() || 'OAuth error');
      }
      // Browser is now redirecting — loading stays true intentionally
    } catch (err) {
      console.error('[Google OAuth] error:', err);
      setError(err.message || 'Google sign-in failed. Check browser console for details.');
      setGoogleLoading(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    setSuccess('');
    try {
      if (mode === 'login') {
        const user = await api.login(formData.username, formData.password);
        onLogin(user);
      } else if (mode === 'reset') {
        await api.resetPassword(formData.username, formData.newPassword);
        setSuccess('Password updated! You can now log in.');
        setMode('login');
        setFormData(f => ({ ...f, password: '' }));
      }
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Could not reach server — check your connection');
    } finally {
      setLoading(false);
    }
  };

  if (currentUser) {
    const stepsComplete = dashData ? [
      dashData.seriesPredicted > 0,
      dashData.futuresDone,
      dashData.leadersDone,
    ].filter(Boolean).length : 0;

    const progressSteps = dashData ? [
      {
        num: 1,
        label: 'Playoffs',
        icon: '🏀',
        status: dashData.seriesPredicted > 0
          ? `${dashData.seriesPredicted}/${dashData.totalSeries} series predicted`
          : 'No picks yet — get started!',
        done: dashData.seriesPredicted > 0 && dashData.seriesPredicted >= dashData.totalSeries,
        partial: dashData.seriesPredicted > 0 && dashData.seriesPredicted < dashData.totalSeries,
        onClick: () => onNavigate('betting'),
        actionLabel: dashData.seriesPredicted === 0 ? 'Start →' : 'Continue →',
      },
      {
        num: 2,
        label: 'Futures',
        icon: '⭐',
        status: dashData.futuresDone ? 'Picks submitted' : 'Not completed — scroll down',
        done: !!dashData.futuresDone,
        partial: false,
        onClick: null,
        actionLabel: null,
      },
      {
        num: 3,
        label: 'Leaders',
        icon: '📊',
        status: dashData.leadersDone ? 'Picks submitted' : 'Not completed — scroll down',
        done: !!dashData.leadersDone,
        partial: false,
        onClick: null,
        actionLabel: null,
      },
    ] : null;

    return (
      <div className="max-w-2xl mx-auto px-4 py-8 md:py-10">
        {/* Hero */}
        <div className="text-center mb-6">
          <div className="inline-flex items-center px-3 py-1.5 rounded-full bg-orange-500/20 border border-orange-500/30 mb-4">
            <span className="text-xs font-bold text-orange-400">✨ 2026 PLAYOFFS</span>
          </div>
          <h1 className="text-3xl md:text-5xl font-black text-white mb-2 leading-tight">
            NBA PLAYOFF<br />
            <span className="bg-gradient-to-r from-orange-400 to-red-500 bg-clip-text text-transparent">PREDICTOR</span>
          </h1>
          <p className="text-slate-300 text-base mt-3">
            Welcome back, <strong className="text-white">{currentUser.username}</strong>!
          </p>
          <p className="text-slate-500 text-sm mt-1">
            Predict playoff results, earn points, and compete on the leaderboard.
          </p>
        </div>

        {/* CTA Buttons */}
        <div className="flex gap-3 justify-center mb-7">
          <button
            onClick={() => onNavigate('betting')}
            className="px-6 py-3.5 rounded-xl bg-gradient-to-r from-orange-500 to-red-500 hover:from-orange-400 hover:to-red-400 text-white font-black text-sm transition-all shadow-lg shadow-orange-500/25 active:scale-95"
          >
            🏀 Start Predicting
          </button>
          <button
            onClick={() => onNavigate('leaderboard')}
            className="px-6 py-3.5 rounded-xl bg-slate-800 border border-slate-700 hover:bg-slate-700 text-white font-bold text-sm transition-all active:scale-95"
          >
            View Leaderboard
          </button>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-3 gap-3 mb-6">
          <Card className="p-4 text-center">
            <div className="text-3xl font-black text-orange-400 mb-1">{currentUser.points || 0}</div>
            <div className="text-slate-500 text-[10px] font-black uppercase tracking-wider">Points</div>
          </Card>
          <Card className="p-4 text-center">
            <div className="text-3xl font-black text-blue-400 mb-1">
              {dashLoading ? <span className="text-slate-600 text-xl">—</span> : (dashData?.seriesPredicted ?? 0)}
            </div>
            <div className="text-slate-500 text-[10px] font-black uppercase tracking-wider">Picks Made</div>
          </Card>
          <Card className="p-4 text-center">
            <div className="text-3xl font-black text-green-400 mb-1">
              {dashLoading ? <span className="text-slate-600 text-xl">—</span> : `${stepsComplete}/3`}
            </div>
            <div className="text-slate-500 text-[10px] font-black uppercase tracking-wider">Steps Done</div>
          </Card>
        </div>

        {/* Prediction Progress */}
        {progressSteps && (
          <Card className="p-5 mb-8">
            <h3 className="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-4">Your Prediction Progress</h3>
            <div className="space-y-2.5">
              {progressSteps.map(step => (
                <div
                  key={step.num}
                  className={`flex items-center gap-3 p-3 rounded-xl border transition-all ${
                    step.done   ? 'bg-green-500/10 border-green-500/20' :
                    step.partial? 'bg-orange-500/10 border-orange-500/20' :
                                  'bg-slate-800/40 border-slate-700/50'
                  }`}
                >
                  <div className={`w-7 h-7 rounded-full flex items-center justify-center font-black text-xs shrink-0 ${
                    step.done   ? 'bg-green-500 text-white' :
                    step.partial? 'bg-orange-500 text-white' :
                                  'bg-slate-700 text-slate-400'
                  }`}>
                    {step.done ? '✓' : step.num}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className={`text-sm font-black ${
                      step.done ? 'text-green-400' : step.partial ? 'text-orange-400' : 'text-white'
                    }`}>
                      {step.icon} {step.label}
                    </p>
                    <p className={`text-xs ${
                      step.done ? 'text-green-500/70' : step.partial ? 'text-orange-500/70' : 'text-slate-500'
                    }`}>
                      {step.status}
                    </p>
                  </div>
                  {step.onClick && (
                    <button
                      onClick={step.onClick}
                      className={`text-xs font-black px-3 py-1.5 rounded-lg shrink-0 transition-all ${
                        step.done   ? 'text-green-400 bg-green-500/10 hover:bg-green-500/20' :
                        step.partial? 'text-orange-400 bg-orange-500/10 hover:bg-orange-500/20' :
                                      'text-white bg-orange-500 hover:bg-orange-600'
                      }`}
                    >
                      {step.actionLabel}
                    </button>
                  )}
                </div>
              ))}
            </div>
          </Card>
        )}

        {/* Loading skeleton for progress */}
        {dashLoading && (
          <Card className="p-5 mb-8">
            <div className="h-3 w-40 bg-slate-800 rounded mb-4 animate-pulse" />
            {[1, 2, 3].map(i => (
              <div key={i} className="flex items-center gap-3 p-3 rounded-xl bg-slate-800/40 border border-slate-700/50 mb-2.5 animate-pulse">
                <div className="w-7 h-7 rounded-full bg-slate-700 shrink-0" />
                <div className="flex-1 space-y-1.5">
                  <div className="h-3 w-20 bg-slate-700 rounded" />
                  <div className="h-2.5 w-32 bg-slate-800 rounded" />
                </div>
              </div>
            ))}
          </Card>
        )}

        {/* Divider before Futures/Leaders */}
        <div className="flex items-center gap-3 mb-6">
          <div className="h-px flex-1 bg-slate-800" />
          <span className="text-[10px] text-slate-600 font-black uppercase tracking-widest">Futures & Leaders Picks</span>
          <div className="h-px flex-1 bg-slate-800" />
        </div>

        <FuturesPage currentUser={currentUser} onNavigate={onNavigate} />
      </div>
    );
  }

  // ── Auth page (login / reset) ─────────────────────────────────────────────
  if (mode === 'reset') {
    return (
      <div className="min-h-[calc(100dvh-7rem)] flex flex-col items-center justify-center px-4 py-8">
        <div className="w-full max-w-sm">
          <div className="text-center mb-7">
            <h1 className="text-3xl font-black text-white mb-1">Reset Password</h1>
            <p className="text-slate-400 text-sm">Enter your username and a new password</p>
          </div>
          <div className="bg-slate-900/70 border border-slate-700/60 rounded-2xl p-6 space-y-3">
            <input
              type="text"
              placeholder="Username"
              value={formData.username}
              onChange={(e) => setFormData({ ...formData, username: e.target.value })}
              className="w-full px-4 py-3.5 bg-slate-800/80 border border-slate-700 rounded-xl text-white text-base focus:outline-none focus:border-orange-500 transition-colors"
              required
            />
            <input
              type="password"
              placeholder="New Password"
              value={formData.newPassword}
              onChange={(e) => setFormData({ ...formData, newPassword: e.target.value })}
              className="w-full px-4 py-3.5 bg-slate-800/80 border border-slate-700 rounded-xl text-white text-base focus:outline-none focus:border-orange-500 transition-colors"
              required
            />
            {error   && <p className="text-red-400 text-sm">{error}</p>}
            {success && <p className="text-green-400 text-sm">{success}</p>}
            <button
              onClick={handleSubmit}
              disabled={loading}
              className="w-full py-3.5 rounded-xl bg-orange-500 hover:bg-orange-600 active:bg-orange-700 text-white font-black text-base transition-colors disabled:opacity-60"
            >
              {loading ? 'Updating…' : 'Reset Password'}
            </button>
          </div>
          <button
            onClick={() => setMode('login')}
            className="w-full mt-4 py-3 text-orange-400 hover:text-orange-300 active:text-orange-200 text-sm font-semibold transition-colors"
          >
            ← Back to sign in
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-[calc(100dvh-7rem)] flex flex-col items-center justify-center px-4 py-8">
      {/* ── Brand header ── */}
      <div className="text-center mb-8">
        <div className="w-16 h-16 bg-gradient-to-br from-orange-500 to-red-600 rounded-2xl flex items-center justify-center mx-auto mb-4 shadow-lg shadow-orange-500/30">
          <Trophy className="w-9 h-9 text-white" />
        </div>
        <h1 className="text-2xl font-black text-white tracking-tight">NBA PLAYOFF</h1>
        <p className="text-orange-400 font-bold text-xs tracking-widest mt-0.5">PREDICTOR 2026</p>
        <p className="text-slate-400 text-sm mt-3 leading-relaxed">Login to save your predictions<br />and compete on the leaderboard.</p>
      </div>

      <div className="w-full max-w-sm">
        {/* ── Google button — primary CTA ── */}
        <button
          onClick={handleGoogleLogin}
          disabled={googleLoading}
          className="w-full flex items-center justify-center gap-3 py-4 px-6 bg-white hover:bg-gray-50 active:bg-gray-100 text-gray-800 font-bold rounded-2xl transition-all shadow-lg hover:shadow-xl text-base disabled:opacity-60 disabled:cursor-not-allowed"
          style={{ minHeight: 56 }}
        >
          {googleLoading ? (
            <>
              <div className="w-5 h-5 border-2 border-gray-300 border-t-blue-500 rounded-full animate-spin" />
              Redirecting to Google…
            </>
          ) : (
            <>
              <GoogleIcon />
              Continue with Google
            </>
          )}
        </button>

        {/* ── Divider ── */}
        <div className="flex items-center gap-3 my-6">
          <div className="flex-1 h-px bg-slate-700/70" />
          <span className="text-xs text-slate-500 font-medium uppercase tracking-wider">or</span>
          <div className="flex-1 h-px bg-slate-700/70" />
        </div>

        {/* ── Password login ── */}
        <div className="bg-slate-900/70 border border-slate-700/60 rounded-2xl p-5 space-y-3">
          <p className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-1">Sign in with password</p>
          <input
            type="text"
            placeholder="Username"
            value={formData.username}
            onChange={(e) => setFormData({ ...formData, username: e.target.value })}
            className="w-full px-4 py-3.5 bg-slate-800/80 border border-slate-700 rounded-xl text-white text-base focus:outline-none focus:border-orange-500 transition-colors"
            autoCapitalize="none"
            autoCorrect="off"
          />
          <input
            type="password"
            placeholder="Password"
            value={formData.password}
            onChange={(e) => setFormData({ ...formData, password: e.target.value })}
            className="w-full px-4 py-3.5 bg-slate-800/80 border border-slate-700 rounded-xl text-white text-base focus:outline-none focus:border-orange-500 transition-colors"
          />
          {error && <p className="text-red-400 text-sm">{error}</p>}
          <button
            onClick={handleSubmit}
            disabled={loading}
            className="w-full py-3.5 rounded-xl bg-slate-700 hover:bg-slate-600 active:bg-slate-500 text-white font-bold text-base transition-colors disabled:opacity-60"
            style={{ minHeight: 52 }}
          >
            {loading ? 'Signing in…' : 'Sign In'}
          </button>
        </div>

        <button
          onClick={() => setMode('reset')}
          className="w-full mt-4 py-3 text-slate-400 hover:text-slate-300 active:text-slate-200 text-sm font-medium transition-colors"
          style={{ minHeight: 44 }}
        >
          Forgot password?
        </button>
      </div>
    </div>
  );
};


const BettingPage = ({ currentUser }) => {
  const [series, setSeries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [picks, setPicks] = useState({}); // { [seriesId]: { teamId, games } }
  const [saved, setSaved] = useState({});

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

  const selectTeam = (seriesId, teamId) => {
    setPicks(prev => ({ ...prev, [seriesId]: { ...prev[seriesId], teamId } }));
  };

  const selectGames = (seriesId, games) => {
    setPicks(prev => ({ ...prev, [seriesId]: { ...prev[seriesId], games } }));
  };

  const handleSave = async (seriesId) => {
    if (!currentUser) { alert('Please login to make predictions'); return; }
    const pick = picks[seriesId];
    if (!pick?.teamId) { alert('Please pick a winner first'); return; }
    if (!pick?.games) { alert('Please pick number of games'); return; }
    try {
      await api.makePrediction(currentUser.user_id, seriesId, pick.teamId, pick.games);
      setSaved(prev => ({ ...prev, [seriesId]: true }));
      setTimeout(() => setSaved(prev => ({ ...prev, [seriesId]: false })), 2000);
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
          {series.map((s) => {
            const pick = picks[s.id] || {};
            return (
              <Card key={s.id} className="p-6">
                <div className="flex justify-between items-center mb-4">
                  <span className="text-xs font-bold text-orange-400 uppercase">{s.conference} Conference</span>
                  <span className="text-xs text-slate-400">{s.round}</span>
                </div>
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-3">
                      <img src={s.home_team.logo_url} alt={s.home_team.name} className="w-10 h-10"
                        onError={(e) => e.target.src = `https://via.placeholder.com/40?text=${s.home_team.abbreviation}`} />
                      <div>
                        <p className="font-bold text-white">{s.home_team.name}</p>
                        <p className="text-xs text-slate-400">Seed {s.home_team.seed}</p>
                      </div>
                    </div>
                    <div className="text-slate-600 font-black text-xl">VS</div>
                    <div className="flex items-center space-x-3">
                      <div className="text-right">
                        <p className="font-bold text-white">{s.away_team.name}</p>
                        <p className="text-xs text-slate-400">Seed {s.away_team.seed}</p>
                      </div>
                      <img src={s.away_team.logo_url} alt={s.away_team.name} className="w-10 h-10"
                        onError={(e) => e.target.src = `https://via.placeholder.com/40?text=${s.away_team.abbreviation}`} />
                    </div>
                  </div>

                  {/* Pick winner */}
                  <div>
                    <p className="text-xs text-slate-400 mb-2 uppercase font-bold">Pick Winner</p>
                    <div className="grid grid-cols-2 gap-3">
                      <Button
                        onClick={() => selectTeam(s.id, s.home_team.id)}
                        variant={pick.teamId === s.home_team.id ? 'default' : 'outline'}
                      >
                        {s.home_team.abbreviation}
                      </Button>
                      <Button
                        onClick={() => selectTeam(s.id, s.away_team.id)}
                        variant={pick.teamId === s.away_team.id ? 'default' : 'outline'}
                      >
                        {s.away_team.abbreviation}
                      </Button>
                    </div>
                  </div>

                  {/* Pick series length */}
                  <div>
                    <p className="text-xs text-slate-400 mb-2 uppercase font-bold">Series Length</p>
                    <div className="grid grid-cols-4 gap-2">
                      {[4, 5, 6, 7].map(g => (
                        <Button
                          key={g}
                          onClick={() => selectGames(s.id, g)}
                          variant={pick.games === g ? 'default' : 'outline'}
                          className="text-center"
                        >
                          {g} Games
                        </Button>
                      ))}
                    </div>
                  </div>

                  <Button
                    onClick={() => handleSave(s.id)}
                    className="w-full"
                    disabled={!pick.teamId || !pick.games}
                  >
                    {saved[s.id] ? 'Saved!' : 'Save Prediction'}
                  </Button>
                </div>
              </Card>
            );
          })}
        </div>
      ) : (
        <Card className="p-8 text-center">
          <p className="text-slate-400">No active series available. Check back when playoffs begin!</p>
        </Card>
      )}
    </div>
  );
};

const LeaderboardPage = ({ onUserClick }) => {
  const [leaderboard, setLeaderboard] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(null);

  useEffect(() => { loadLeaderboard(); }, []);

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

  const medals = ['🥇', '🥈', '🥉'];

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <div className="flex items-center gap-3 mb-8">
        <Users className="w-7 h-7 text-orange-400" />
        <h1 className="text-4xl font-black text-white">Leaderboard</h1>
      </div>
      {loading ? (
        <div className="space-y-2">
          {[1,2,3,4,5].map(i => (
            <div key={i} className="bg-slate-900/50 border border-slate-800 rounded-xl p-4 flex items-center gap-3 animate-pulse">
              <div className="w-10 h-10 rounded-full bg-slate-800 shrink-0" />
              <div className="flex-1 space-y-2">
                <div className="h-3.5 w-28 bg-slate-800 rounded" />
                <div className="h-2.5 w-20 bg-slate-800/60 rounded" />
              </div>
              <div className="w-12 h-8 bg-slate-800 rounded" />
            </div>
          ))}
        </div>
      ) : (
        <div className="space-y-2">
          {leaderboard.map((user) => {
            const isExpanded = expanded === user.rank;
            const accuracy = user.accuracy ?? (user.total_predictions > 0 ? Math.round((user.correct_predictions / user.total_predictions) * 100) : 0);
            const seriesPts  = user.series_points  ?? null;
            const futuresPts = user.futures_points ?? null;
            const leadersPts = user.leaders_points ?? null;
            const hasBreakdown = seriesPts != null || futuresPts != null || leadersPts != null;
            // Risk profile: pts-per-correct as proxy for boldness
            const ppc = user.correct_predictions > 0 ? Math.round(user.points / user.correct_predictions) : 0;
            const riskProfile = ppc >= 100 ? { label: '🔥 Degen',    cls: 'text-amber-400 bg-amber-500/10 border-amber-500/30' }
                              : ppc >= 55  ? { label: '⚖️ Balanced', cls: 'text-blue-400  bg-blue-500/10  border-blue-500/30'  }
                              : ppc > 0    ? { label: '🛡️ Safe',     cls: 'text-green-400 bg-green-500/10 border-green-500/30' }
                              : null;

            return (
              <div key={user.rank} className={`bg-slate-900/50 border rounded-xl transition-all overflow-hidden ${
                user.rank <= 3 ? 'border-amber-500/30' : 'border-slate-800'
              }`}>
                <div
                  className="p-4 flex items-center gap-3 cursor-pointer hover:bg-slate-800/30 transition-colors"
                  onClick={() => setExpanded(isExpanded ? null : user.rank)}
                >
                  {/* Rank */}
                  <div className={`w-10 h-10 rounded-full flex items-center justify-center font-black text-sm shrink-0 ${
                    user.rank === 1 ? 'bg-amber-500/20 text-amber-400 border border-amber-500/40' :
                    user.rank === 2 ? 'bg-slate-400/20 text-slate-300 border border-slate-400/40' :
                    user.rank === 3 ? 'bg-orange-700/20 text-orange-400 border border-orange-700/40' :
                    'bg-slate-800 text-slate-400'
                  }`}>
                    {user.rank <= 3 ? medals[user.rank - 1] : user.rank}
                  </div>

                  {/* Name + stats */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <button
                        className="font-black text-white hover:text-orange-400 transition-colors text-left"
                        onClick={(e) => { e.stopPropagation(); onUserClick(user); }}
                      >
                        {user.username}
                      </button>
                      {riskProfile && (
                        <span className={`text-[9px] font-black px-1.5 py-0.5 rounded border ${riskProfile.cls}`}>
                          {riskProfile.label}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 mt-0.5 flex-wrap">
                      <span className="text-xs text-slate-500">
                        {user.correct_predictions ?? 0}/{user.total_predictions ?? 0} correct
                      </span>
                      <span className={`text-xs font-black ${
                        accuracy >= 70 ? 'text-green-400' :
                        accuracy >= 50 ? 'text-yellow-400' :
                        'text-slate-500'
                      }`}>
                        {accuracy}% acc
                      </span>
                    </div>
                  </div>

                  {/* Points */}
                  <div className="text-right shrink-0">
                    <div className="text-2xl font-black text-orange-400">{user.points}</div>
                    <div className="text-[10px] text-slate-500 font-bold">pts</div>
                  </div>

                  {/* Expand chevron */}
                  <ChevronDown className={`w-4 h-4 text-slate-600 shrink-0 transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
                </div>

                {/* Expanded breakdown */}
                {isExpanded && (
                  <div className="px-4 pb-4 border-t border-slate-800 pt-3">
                    {hasBreakdown ? (
                      <div className="grid grid-cols-3 gap-3">
                        <div className="text-center bg-slate-800/60 rounded-xl p-3">
                          <p className="text-lg font-black text-orange-400">{seriesPts ?? '—'}</p>
                          <p className="text-[10px] text-slate-500 font-bold uppercase">Series</p>
                        </div>
                        <div className="text-center bg-slate-800/60 rounded-xl p-3">
                          <p className="text-lg font-black text-yellow-400">{futuresPts ?? '—'}</p>
                          <p className="text-[10px] text-slate-500 font-bold uppercase">Futures</p>
                        </div>
                        <div className="text-center bg-slate-800/60 rounded-xl p-3">
                          <p className="text-lg font-black text-cyan-400">{leadersPts ?? '—'}</p>
                          <p className="text-[10px] text-slate-500 font-bold uppercase">Leaders</p>
                        </div>
                      </div>
                    ) : (
                      <div className="grid grid-cols-2 gap-3">
                        <div className="text-center bg-slate-800/60 rounded-xl p-3">
                          <p className="text-xl font-black text-orange-400">{user.points}</p>
                          <p className="text-[10px] text-slate-500 font-bold uppercase">Total Points</p>
                        </div>
                        <div className="text-center bg-slate-800/60 rounded-xl p-3">
                          <p className="text-xl font-black text-green-400">{accuracy}%</p>
                          <p className="text-[10px] text-slate-500 font-bold uppercase">Accuracy</p>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

// ── PWA Install Prompt ────────────────────────────────────────────────────────
const InstallBanner = () => {
  const [show, setShow] = useState(false);
  const [isIOS, setIsIOS] = useState(false);
  const deferredPrompt = useRef(null);

  useEffect(() => {
    // Already installed or dismissed
    if (localStorage.getItem('pwa_dismissed')) return;
    // Already running as standalone
    if (window.matchMedia('(display-mode: standalone)').matches) return;

    const ios = /iphone|ipad|ipod/i.test(navigator.userAgent) && !window.MSStream;
    setIsIOS(ios);

    if (ios) {
      // On iOS show a manual guide
      setShow(true);
      return;
    }

    // Android/Chrome: capture beforeinstallprompt
    const handler = (e) => {
      e.preventDefault();
      deferredPrompt.current = e;
      setShow(true);
    };
    window.addEventListener('beforeinstallprompt', handler);
    return () => window.removeEventListener('beforeinstallprompt', handler);
  }, []);

  const handleInstall = async () => {
    if (deferredPrompt.current) {
      deferredPrompt.current.prompt();
      const { outcome } = await deferredPrompt.current.userChoice;
      deferredPrompt.current = null;
      if (outcome === 'accepted') setShow(false);
    }
  };

  const handleDismiss = () => {
    setShow(false);
    localStorage.setItem('pwa_dismissed', '1');
  };

  if (!show) return null;

  return (
    <div className="fixed bottom-20 md:bottom-6 left-3 right-3 md:left-auto md:right-6 md:max-w-sm z-50 bg-slate-900 border border-orange-500/40 rounded-2xl shadow-2xl shadow-orange-500/10 p-4 flex items-start gap-3">
      <div className="w-10 h-10 bg-gradient-to-br from-orange-500 to-red-600 rounded-xl flex items-center justify-center shrink-0">
        <Trophy className="w-5 h-5 text-white" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-black text-white">Install NBA Picks</p>
        {isIOS ? (
          <p className="text-xs text-slate-400 mt-0.5">
            Tap <span className="font-bold text-slate-300">Share</span> → <span className="font-bold text-slate-300">Add to Home Screen</span>
          </p>
        ) : (
          <p className="text-xs text-slate-400 mt-0.5">Add to home screen for a native app experience</p>
        )}
        {!isIOS && (
          <button onClick={handleInstall}
            className="mt-2 flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-orange-500 text-white text-xs font-black hover:bg-orange-400 transition-colors">
            <Download className="w-3 h-3" /> Install App
          </button>
        )}
      </div>
      <button onClick={handleDismiss} className="text-slate-500 hover:text-slate-300 shrink-0 transition-colors">
        <X className="w-4 h-4" />
      </button>
    </div>
  );
};

function App() {
  const [currentPage, setCurrentPage] = useState('home');
  const [currentUser, setCurrentUser] = useState(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState(null);
  const [profileUsername, setProfileUsername] = useState(null);

  useEffect(() => {
    const stored = localStorage.getItem('nba_user');
    if (stored) {
      const user = JSON.parse(stored);
      setCurrentUser(user);
      // Refresh user data from server to pick up role/points changes
      api.getMe(user.user_id).then(fresh => {
        const updated = { ...user, ...fresh };
        setCurrentUser(updated);
        localStorage.setItem('nba_user', JSON.stringify(updated));
      }).catch(() => {});
    }

    // Handle Google OAuth callback from Supabase
    if (!supabase) return;
    const { data: { subscription } } = supabase.auth.onAuthStateChange(async (event, session) => {
      if (event === 'SIGNED_IN' && session && !localStorage.getItem('nba_user')) {
        try {
          const email = session.user.email;
          const name = session.user.user_metadata?.full_name || session.user.user_metadata?.name || '';
          const avatarUrl = session.user.user_metadata?.avatar_url || session.user.user_metadata?.picture || '';
          console.log('[Google OAuth] syncing user:', email, name);
          const user = await api.loginWithGoogle(email, name, avatarUrl);
          setCurrentUser(user);
          localStorage.setItem('nba_user', JSON.stringify(user));
          // Sign out of Supabase session — we use our own auth from here on
          await supabase.auth.signOut();
        } catch (err) {
          console.error('Google login failed:', err);
        }
      }
    });
    return () => subscription.unsubscribe();
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

  const handleUserUpdate = (updatedUser) => {
    setCurrentUser(updatedUser);
    localStorage.setItem('nba_user', JSON.stringify(updatedUser));
  };

  const navigate = (page, opts = {}) => {
    setCurrentPage(page);
    setMobileMenuOpen(false);
    if (page === 'profile' && opts.username) setProfileUsername(opts.username);
    if (page !== 'user-predictions') setSelectedUser(null);
  };

  const handleUserClick = (user) => {
    setProfileUsername(user.username);
    setCurrentPage('profile');
    setMobileMenuOpen(false);
  };

  const navItems = [
    { id: 'home',        label: 'Home',             icon: HomeIcon  },
    { id: 'standings',   label: 'Standings',        icon: BarChart3 },
    { id: 'betting',     label: 'Playoffs',         icon: Trophy    },
    { id: 'leaderboard', label: 'Leaderboard',      icon: Users     },
    { id: 'profile',     label: 'My Profile',       icon: Star      },
    { id: 'scoring',     label: 'How Scoring Works',icon: Info      },
    ...(currentUser?.role === 'admin' ? [{ id: 'admin', label: 'Admin', icon: Shield }] : []),
  ];

  const renderPage = () => {
    const props = { currentUser, onNavigate: navigate, onLogin: handleLogin };
    switch (currentPage) {
      case 'home':             return <HomePage {...props} />;
      case 'standings':        return <StandingsPage currentUser={currentUser} />;
      case 'betting':          return <BracketPage currentUser={currentUser} onNavigate={navigate} />;
      case 'leaderboard':      return <LeaderboardPage onUserClick={handleUserClick} />;
      case 'mypredictions':    return <MyPredictionsPage currentUser={currentUser} />;
      case 'profile':          return <UserProfilePage username={profileUsername || currentUser?.username} currentUser={currentUser} />;
      case 'account':          return <AccountPage currentUser={currentUser} onLogout={handleLogout} onUserUpdate={handleUserUpdate} />;
      case 'user-predictions': return selectedUser ? <UserPredictionsPage userId={selectedUser.user_id} username={selectedUser.username} onBack={() => navigate('leaderboard')} /> : null;
      case 'admin':            return <AdminPage currentUser={currentUser} />;
      case 'scoring':          return <ScoringGuide />;
      default:                 return <HomePage {...props} />;
    }
  };

  // Bottom nav: core 5 items (no admin) + Account when logged in
  const coreNavItems = navItems.filter(i => i.id !== 'admin').slice(0, 5);
  const bottomNavItems = currentUser
    ? [...coreNavItems, { id: 'account', label: 'Account', icon: Settings }]
    : coreNavItems;

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-blue-950 to-slate-900">

      {/* ── DESKTOP SIDEBAR ── */}
      <aside className="hidden md:fixed md:inset-y-0 md:flex md:w-64 md:flex-col z-40">
        <div className="flex flex-col flex-grow pt-5 bg-slate-900/50 backdrop-blur-xl border-r border-blue-500/20">
          <div className="flex items-center px-4 mb-8">
            <div className="w-12 h-12 bg-gradient-to-br from-orange-500 to-red-600 rounded-xl flex items-center justify-center mr-3 shrink-0">
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
              const handleNav = () => {
                if (item.id === 'profile' && currentUser) {
                  setProfileUsername(currentUser.username);
                }
                navigate(item.id);
              };
              return (
                <button key={item.id} onClick={handleNav}
                  className={`group flex items-center w-full px-3 py-3 text-sm font-semibold rounded-xl transition-all ${
                    currentPage === item.id
                      ? 'bg-gradient-to-r from-orange-500 to-red-600 text-white shadow-lg'
                      : 'text-slate-300 hover:bg-slate-800/50'
                  }`}>
                  <Icon className="mr-3 h-5 w-5 shrink-0" />
                  {item.label}
                </button>
              );
            })}
          </nav>
          {currentUser && (
            <div className="p-4 border-t border-blue-500/20 space-y-2">
              <button
                onClick={() => navigate('account')}
                className={`group flex items-center w-full px-3 py-2.5 text-sm font-semibold rounded-xl transition-all ${
                  currentPage === 'account'
                    ? 'bg-gradient-to-r from-orange-500 to-red-600 text-white shadow-lg'
                    : 'text-slate-300 hover:bg-slate-800/50'
                }`}
              >
                <Settings className="mr-3 h-4 w-4 shrink-0" />
                Account Settings
              </button>
              <div className="flex items-center px-2 py-1">
                {currentUser.avatar_url ? (
                  <img src={currentUser.avatar_url} alt="" className="w-9 h-9 rounded-full object-cover mr-3 shrink-0" />
                ) : (
                  <div className="w-9 h-9 bg-gradient-to-br from-blue-500 to-purple-600 rounded-full flex items-center justify-center text-white font-bold mr-3 shrink-0">
                    {currentUser.username[0].toUpperCase()}
                  </div>
                )}
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

      {/* ── MOBILE TOP BAR (brand only, no hamburger) ── */}
      <div className="md:hidden sticky top-0 z-50 bg-slate-900/95 backdrop-blur-xl border-b border-blue-500/20">
        <div className="flex items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="w-9 h-9 bg-gradient-to-br from-orange-500 to-red-600 rounded-lg flex items-center justify-center shrink-0">
              <Trophy className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-base font-black text-white leading-none">NBA PLAYOFF</h1>
              <p className="text-[10px] font-bold text-orange-400">PREDICTOR 2026</p>
            </div>
          </div>
          {currentUser && (
            <button
              onClick={() => navigate('account')}
              className="flex items-center gap-2 active:opacity-70 transition-opacity"
              style={{ minHeight: 44 }}
            >
              {currentUser.avatar_url ? (
                <img src={currentUser.avatar_url} alt="" className="w-8 h-8 rounded-full object-cover shrink-0" />
              ) : (
                <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-purple-600 rounded-full flex items-center justify-center text-white text-sm font-black shrink-0">
                  {currentUser.username[0].toUpperCase()}
                </div>
              )}
              <span className="text-xs text-slate-400 font-bold">{currentUser.points || 0}pts</span>
            </button>
          )}
        </div>
      </div>

      {/* ── MAIN CONTENT ── */}
      {/* pb-20 on mobile to clear the bottom nav bar */}
      <main className="md:pl-64 min-h-screen pb-20 md:pb-0">
        <Suspense fallback={<PageSpinner />}>
          {renderPage()}
        </Suspense>
      </main>

      {/* ── PWA INSTALL BANNER ── */}
      <InstallBanner />

      {/* ── MOBILE BOTTOM NAV BAR ── */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 bg-slate-900/95 backdrop-blur-xl border-t border-slate-800 flex">
        {bottomNavItems.map((item) => {
          const Icon = item.icon;
          const active = currentPage === item.id;
          const handleBottomNav = () => {
            if (item.id === 'profile' && currentUser) setProfileUsername(currentUser.username);
            navigate(item.id);
          };
          return (
            <button
              key={item.id}
              onClick={handleBottomNav}
              className={`flex-1 flex flex-col items-center justify-center py-2 gap-0.5 min-h-[56px] transition-colors active:bg-slate-800/60 ${
                active ? 'text-orange-400' : 'text-slate-500'
              }`}
            >
              <Icon className={`w-5 h-5 ${active ? 'text-orange-400' : 'text-slate-500'}`} />
              <span className={`text-[10px] font-bold leading-none ${active ? 'text-orange-400' : 'text-slate-500'}`}>
                {item.label}
              </span>
              {active && <div className="absolute bottom-0 h-0.5 w-8 bg-orange-400 rounded-full" />}
            </button>
          );
        })}
      </nav>
    </div>
  );
}

export default App;