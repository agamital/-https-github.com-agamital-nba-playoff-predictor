import React, { useState, useEffect, useRef, lazy, Suspense } from 'react';
import { createPortal } from 'react-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Trophy, Users, BarChart3, Home as HomeIcon, LogOut, Star, Shield, Download, X, Settings, Info, ChevronDown, ChevronRight, Share, Bell, Lock } from 'lucide-react';
import * as api from './services/api';

// ── OneSignal — CDN approach (OneSignalSDK.page.js loaded in index.html) ──────
// window.OneSignal is set by the CDN script; all calls must guard on it.
// _osPromise resolves when init() completes (or times out after 10 s) so every
// SDK call is race-free even if the CDN script loads slowly.
// initOneSignal() is called at module level so _osPromise is non-null before
// any child component's useEffect tries to read PushSubscription state.
let _osInitDone = false;
let _osPromise  = null;
const _osAppId  = import.meta.env.VITE_ONESIGNAL_APP_ID || 'c69b4c3e-79d1-48a4-8815-3ceabc1eae70';

function initOneSignal() {
  if (_osInitDone) return _osPromise;
  _osInitDone = true;

  _osPromise = new Promise((resolve) => {
    // 10-second failsafe: resolve even if the CDN script never loads so that
    // awaiting _osPromise never hangs indefinitely (toggle stays responsive).
    const timeout = setTimeout(resolve, 10_000);

    window.OneSignalDeferred = window.OneSignalDeferred || [];
    window.OneSignalDeferred.push(async (OneSignal) => {
      try {
        await OneSignal.init({
          appId:                        _osAppId,
          allowLocalhostAsSecureOrigin: true,
          // Disable every built-in OneSignal UI element.
          // The custom toggle in Account Settings is the sole subscription controller.
          notifyButton: { enable: false },
          slidedown:    { prompts: []   },
          customLink:   { enable: false },
          welcomeNotification: { disable: true },
        });
        // Belt-and-suspenders: remove any DOM nodes the SDK may have injected
        // despite the config flags (dashboard settings can override SDK config).
        [
          '#onesignal-bell-container',
          '#onesignal-slidedown-container',
          '#onesignal-popover-container',
        ].forEach(sel => document.querySelector(sel)?.remove());
      } catch { /* init error — SDK calls will silently no-op via window.OneSignal guard */ }
      clearTimeout(timeout);
      resolve();
    });
  });

  return _osPromise;
}

// Called at module load — guarantees _osPromise is non-null before any mount.
initOneSignal();

// Safe accessor: returns window.OneSignal only when it is the live SDK object
// (a plain array means the script hasn't executed yet).
const os = () => (window.OneSignal && !Array.isArray(window.OneSignal) ? window.OneSignal : null);

// Safe login/logout wrappers — wait for init, then guard on os()
const osLogin  = (id) => _osPromise.then(() => { try { os()?.login(String(id));  } catch {} });
const osLogout = ()   => _osPromise.then(() => { try { os()?.logout();            } catch {} });
import { supabase } from './lib/supabase';
import { picksRevealed, PICKS_REVEAL_DATE } from './scoringConstants';
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
  const [mode, setMode] = useState('login'); // 'login' | 'register' | 'reset'
  const [formData, setFormData] = useState({ username: '', email: '', password: '', confirmPassword: '', newPassword: '' });
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
      } else if (mode === 'register') {
        if (formData.password !== formData.confirmPassword) {
          setError('Passwords do not match.');
          return;
        }
        if (formData.password.length < 4) {
          setError('Password must be at least 4 characters.');
          return;
        }
        if (formData.username.length < 3 || !/^[a-zA-Z0-9_]+$/.test(formData.username)) {
          setError('Username must be 3+ characters (letters, numbers, underscores only).');
          return;
        }
        const user = await api.register(formData.username, formData.email, formData.password);
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

  const switchMode = (next) => {
    setMode(next);
    setError('');
    setSuccess('');
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

        {/* How Scoring Works */}
        <button
          onClick={() => onNavigate('scoring')}
          className="w-full flex items-center gap-3 p-4 mb-5 rounded-xl bg-blue-500/10 border border-blue-500/20 hover:bg-blue-500/15 transition-all text-left group active:scale-[0.99]"
        >
          <div className="w-9 h-9 rounded-lg bg-blue-500/20 flex items-center justify-center shrink-0">
            <Info className="w-4 h-4 text-blue-400" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-black text-white">How Scoring Works</p>
            <p className="text-[11px] text-slate-400 mt-0.5">Learn how points are earned for picks, upsets & futures</p>
          </div>
          <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-slate-400 transition-colors shrink-0" />
        </button>

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
        <div id="futures-section" className="flex items-center gap-3 mb-6">
          <div className="h-px flex-1 bg-slate-800" />
          <span className="text-[10px] text-slate-600 font-black uppercase tracking-widest">Futures & Leaders Picks</span>
          <div className="h-px flex-1 bg-slate-800" />
        </div>

        <FuturesPage currentUser={currentUser} onNavigate={onNavigate} />
      </div>
    );
  }

  // ── Auth page (login / register / reset) ──────────────────────────────────
  if (mode === 'register') {
    return (
      <div className="min-h-[calc(100dvh-7rem)] flex flex-col items-center justify-center px-4 py-8">
        <div className="w-full max-w-sm">
          <div className="text-center mb-7">
            <div className="w-14 h-14 bg-gradient-to-br from-orange-500 to-red-600 rounded-2xl flex items-center justify-center mx-auto mb-3 shadow-lg">
              <Trophy className="w-8 h-8 text-white" />
            </div>
            <h1 className="text-2xl font-black text-white">Create Account</h1>
            <p className="text-slate-400 text-sm mt-1">Join the 2026 Playoff Predictor</p>
          </div>
          <div className="bg-slate-900/70 border border-slate-700/60 rounded-2xl p-6 space-y-3">
            <input
              type="text"
              placeholder="Username (letters, numbers, _)"
              value={formData.username}
              onChange={e => setFormData({ ...formData, username: e.target.value })}
              className="w-full px-4 py-3.5 bg-slate-800/80 border border-slate-700 rounded-xl text-white text-base focus:outline-none focus:border-orange-500 transition-colors"
              autoCapitalize="none" autoCorrect="off"
              required
            />
            <input
              type="email"
              placeholder="Email address"
              value={formData.email}
              onChange={e => setFormData({ ...formData, email: e.target.value })}
              className="w-full px-4 py-3.5 bg-slate-800/80 border border-slate-700 rounded-xl text-white text-base focus:outline-none focus:border-orange-500 transition-colors"
              required
            />
            <input
              type="password"
              placeholder="Password (min 4 characters)"
              value={formData.password}
              onChange={e => setFormData({ ...formData, password: e.target.value })}
              className="w-full px-4 py-3.5 bg-slate-800/80 border border-slate-700 rounded-xl text-white text-base focus:outline-none focus:border-orange-500 transition-colors"
              required
            />
            <input
              type="password"
              placeholder="Confirm password"
              value={formData.confirmPassword}
              onChange={e => setFormData({ ...formData, confirmPassword: e.target.value })}
              className="w-full px-4 py-3.5 bg-slate-800/80 border border-slate-700 rounded-xl text-white text-base focus:outline-none focus:border-orange-500 transition-colors"
              required
            />
            {error   && <p className="text-red-400 text-sm">{error}</p>}
            {success && <p className="text-green-400 text-sm">{success}</p>}
            <button
              onClick={handleSubmit}
              disabled={loading}
              className="w-full py-3.5 rounded-xl bg-orange-500 hover:bg-orange-600 active:bg-orange-700 text-white font-black text-base transition-colors disabled:opacity-60"
              style={{ minHeight: 52 }}
            >
              {loading ? 'Creating account…' : 'Create Account'}
            </button>
          </div>
          <button
            onClick={() => switchMode('login')}
            className="w-full mt-4 py-3 text-slate-400 hover:text-slate-300 text-sm font-medium transition-colors"
            style={{ minHeight: 44 }}
          >
            Already have an account? Sign in
          </button>
        </div>
      </div>
    );
  }

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
            onClick={() => switchMode('login')}
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

        <div className="flex flex-col items-center mt-4 gap-1">
          <button
            onClick={() => switchMode('reset')}
            className="py-2 text-slate-400 hover:text-slate-300 text-sm font-medium transition-colors"
            style={{ minHeight: 40 }}
          >
            Forgot password?
          </button>
          <div className="flex items-center gap-1.5 text-sm">
            <span className="text-slate-500">New here?</span>
            <button
              onClick={() => switchMode('register')}
              className="text-orange-400 hover:text-orange-300 font-black transition-colors"
            >
              Create an account
            </button>
          </div>
        </div>
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

// ── Global Stats helpers ──────────────────────────────────────────────────────

const PicksLockedPlaceholder = () => (
  <div className="flex items-center gap-2 px-4 py-3 text-slate-600 text-[11px] font-bold">
    <Download className="w-3.5 h-3.5 shrink-0 opacity-50" />
    Predictions revealed when the tournament starts
    <span className="ml-auto text-[10px] text-slate-700">
      {PICKS_REVEAL_DATE.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
    </span>
  </div>
);

const SeriesVoteBar = ({ s, currentUser }) => {
  const [expanded, setExpanded]       = useState(false);
  const [picks, setPicks]             = useState(null);
  const [loadingPicks, setLoadingPicks] = useState(false);

  const total   = s.total_votes;
  const homePct = s.home_pct;
  const awayPct = s.away_pct;
  const noVotes = total === 0;

  const handleToggle = async () => {
    const next = !expanded;
    setExpanded(next);
    if (next && !picks) {
      setLoadingPicks(true);
      try {
        const data = await api.getSeriesPicks(s.series_id);
        setPicks(data.picks);
      } catch (e) {
        console.error('SeriesVoteBar picks fetch:', e);
        setPicks([]);
      } finally {
        setLoadingPicks(false);
      }
    }
  };

  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-2xl overflow-hidden">
      <div className="p-4">
        {/* Completed badge */}
        {s.status === 'completed' && (
          <div className="mb-3">
            <span className="text-[9px] font-black uppercase tracking-widest text-green-400 bg-green-500/10 border border-green-500/20 px-2 py-0.5 rounded-full">
              Completed
            </span>
          </div>
        )}

        {/* Teams row */}
        <div className="flex items-center gap-3 mb-3">
          {/* Home team */}
          <div className="flex-1 flex items-center gap-2 min-w-0">
            <img
              src={s.home_team.logo_url} alt={s.home_team.abbreviation}
              className="w-10 h-10 shrink-0"
              loading="lazy" decoding="async"
              onError={e => e.target.style.display = 'none'}
            />
            <div className="min-w-0">
              <p className="font-black text-white text-sm leading-tight truncate">
                {s.home_team.name || s.home_team.abbreviation}
              </p>
              <p className="text-[10px] text-slate-500 font-bold">Seed #{s.home_team.seed}</p>
            </div>
          </div>

          <div className="text-slate-700 font-black text-xs shrink-0">VS</div>

          {/* Away team */}
          <div className="flex-1 flex items-center gap-2 justify-end min-w-0">
            <div className="text-right min-w-0">
              <p className="font-black text-white text-sm leading-tight truncate">
                {s.away_team.name || s.away_team.abbreviation}
              </p>
              <p className="text-[10px] text-slate-500 font-bold">Seed #{s.away_team.seed}</p>
            </div>
            <img
              src={s.away_team.logo_url} alt={s.away_team.abbreviation}
              className="w-10 h-10 shrink-0"
              loading="lazy" decoding="async"
              onError={e => e.target.style.display = 'none'}
            />
          </div>
        </div>

        {/* Vote bar — always visible */}
        <div className="relative h-8 rounded-full overflow-hidden bg-slate-800 flex">
          <div
            className="h-full bg-blue-500/80 transition-all duration-700"
            style={{ width: noVotes ? '50%' : `${homePct}%` }}
          />
          <div className="h-full bg-orange-500/70 flex-1" />
          <div className="absolute inset-0 flex items-center justify-between px-3 pointer-events-none">
            <span className="text-xs font-black text-white drop-shadow-md">
              {noVotes ? '—' : `${homePct}%`}
            </span>
            <span className="text-xs font-black text-white drop-shadow-md">
              {noVotes ? '—' : `${awayPct}%`}
            </span>
          </div>
        </div>
        {/* Toggle row — individual picks only visible once series is no longer 'active' */}
        {(() => {
          const picksVisible = s.status !== 'active';
          return (
            <div className="flex items-center justify-between mt-2 px-1">
              <span className="text-[10px] text-blue-400 font-black">{s.home_team.abbreviation}</span>
              {picksVisible ? (
                <button
                  onClick={handleToggle}
                  className="flex items-center gap-1 text-[10px] text-slate-500 font-bold hover:text-slate-300 transition-colors"
                >
                  <Users className="w-3 h-3" />
                  {noVotes ? 'No picks yet' : `${total} ${total === 1 ? 'pick' : 'picks'}`}
                  <ChevronDown className={`w-3 h-3 transition-transform ${expanded ? 'rotate-180' : ''}`} />
                </button>
              ) : (
                <span className="flex items-center gap-1 text-[10px] text-slate-600 font-bold">
                  <Lock className="w-3 h-3" />
                  {noVotes ? 'No picks yet' : `${total} ${total === 1 ? 'pick' : 'picks'}`}
                </span>
              )}
              <span className="text-[10px] text-orange-400 font-black">{s.away_team.abbreviation}</span>
            </div>
          );
        })()}
      </div>

      {/* Expandable per-user picks — only once series is no longer 'active' */}
      {s.status !== 'active' && expanded && (
        <div className="border-t border-slate-800/80 bg-slate-950/40">
          {loadingPicks ? (
            <div className="flex justify-center py-5">
              <div className="w-5 h-5 border-2 border-orange-500 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : picks && picks.length > 0 ? (
            <div className="divide-y divide-slate-800/40 max-h-52 overflow-y-auto">
              {picks.map((p, i) => {
                const isMe = currentUser && p.username === currentUser.username;
                return (
                  <div key={i} className={`flex items-center gap-2.5 px-4 py-2.5 ${isMe ? 'bg-orange-500/10' : ''}`}>
                    {/* User avatar */}
                    {p.avatar_url ? (
                      <img
                        src={p.avatar_url} alt=""
                        className="w-6 h-6 rounded-full object-cover shrink-0"
                        onError={e => { e.target.style.display = 'none'; }}
                      />
                    ) : (
                      <div className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 ${isMe ? 'bg-orange-500/30' : 'bg-slate-700'}`}>
                        <span className={`text-[8px] font-black ${isMe ? 'text-orange-400' : 'text-slate-400'}`}>
                          {(p.username || '?')[0].toUpperCase()}
                        </span>
                      </div>
                    )}
                    {isMe && (
                      <span className="text-[8px] font-black text-orange-400 bg-orange-500/20 border border-orange-500/30 px-1.5 py-0.5 rounded-full shrink-0">
                        YOU
                      </span>
                    )}
                    <span className={`text-xs font-bold flex-1 truncate ${isMe ? 'text-orange-300' : 'text-slate-300'}`}>
                      {p.username}
                    </span>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <img
                        src={p.team_logo_url} alt=""
                        className="w-4 h-4"
                        onError={e => e.target.style.display = 'none'}
                      />
                      <span className={`text-[10px] font-black ${isMe ? 'text-orange-400' : 'text-slate-400'}`}>
                        {p.team_abbreviation}
                      </span>
                      {p.predicted_games && (
                        <span className="text-[10px] text-slate-600 font-bold">in {p.predicted_games}</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="text-xs text-slate-600 text-center py-4">No picks yet — be the first!</p>
          )}
        </div>
      )}
    </div>
  );
};

const _FUTURES_RANK_STYLE = [
  { badge: 'bg-amber-500/20 border-amber-500/40 text-amber-400',  bar: 'linear-gradient(90deg,#f59e0b,#fb923c)', label: '🥇' },
  { badge: 'bg-slate-500/20 border-slate-400/40 text-slate-300',  bar: 'linear-gradient(90deg,#94a3b8,#64748b)', label: '🥈' },
  { badge: 'bg-orange-700/20 border-orange-600/40 text-orange-400', bar: 'linear-gradient(90deg,#f97316,#ea580c)', label: '🥉' },
];

const FuturesPickBar = ({ item, rank, totalUsers }) => {
  const pct   = totalUsers > 0 ? Math.round(item.count / totalUsers * 100) : 0;
  const style = _FUTURES_RANK_STYLE[rank] ?? { badge: 'bg-slate-800 border-slate-700 text-slate-400', bar: '#475569', label: `#${rank + 1}` };

  return (
    <div className="flex items-center gap-3 py-2.5">
      {/* Rank badge */}
      <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-black border shrink-0 ${style.badge}`}>
        {style.label}
      </div>

      {/* Team logo */}
      <img
        src={item.team.logo_url} alt={item.team.abbreviation}
        className="w-9 h-9 shrink-0"
        loading="lazy" decoding="async"
        onError={e => e.target.style.display = 'none'}
      />

      {/* Bar + labels */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-sm font-black text-white truncate">{item.team.name}</span>
          <span className="text-xs font-bold text-slate-500 shrink-0 ml-2">
            {item.count} picks&nbsp;
            <span className="text-orange-400 font-black">({pct}%)</span>
          </span>
        </div>
        <div className="h-2.5 bg-slate-800 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-700"
            style={{ width: `${Math.max(pct, 4)}%`, background: style.bar }}
          />
        </div>
      </div>
    </div>
  );
};

const GlobalStatsTab = ({ currentUser }) => {
  const [stats, setStats]   = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getGlobalStats('2026').then(setStats).catch(console.error).finally(() => setLoading(false));
  }, []);

  if (loading) return (
    <div className="space-y-3">
      {[1, 2, 3, 4].map(i => (
        <div key={i} className="bg-slate-900/50 border border-slate-800 rounded-2xl p-4 animate-pulse h-24" />
      ))}
    </div>
  );
  if (!stats) return <p className="text-slate-500 text-center py-8">Could not load stats.</p>;

  const ROUND_ORDER = ['First Round', 'Conference Semifinals', 'Conference Finals', 'NBA Finals'];
  const byRound = {};
  stats.series.forEach(s => {
    if (!byRound[s.round]) byRound[s.round] = [];
    byRound[s.round].push(s);
  });
  const sortedRounds = ROUND_ORDER.filter(r => byRound[r]);

  const hasFutures = stats.futures.top_champions.length > 0
    || stats.futures.top_west_champs.length > 0
    || stats.futures.top_east_champs.length > 0;

  return (
    <div className="space-y-6">

      {/* ── Participation banner ── */}
      <div className="bg-gradient-to-r from-orange-500/10 to-amber-500/10 border border-orange-500/20 rounded-2xl p-5 flex items-center justify-center gap-4">
        <div className="text-center">
          <div className="text-4xl font-black text-orange-400 leading-none">{stats.total_users}</div>
          <div className="text-xs text-slate-400 font-bold mt-1 uppercase tracking-wide">Total Participants</div>
        </div>
        <div className="w-px h-10 bg-slate-700" />
        <div className="text-center">
          <div className="text-4xl font-black text-blue-400 leading-none">{stats.series.length}</div>
          <div className="text-xs text-slate-400 font-bold mt-1 uppercase tracking-wide">Active Series</div>
        </div>
      </div>

      {/* ── Series votes by round — aggregate bars always visible ── */}
      {sortedRounds.map(round => (
        <div key={round}>
          <div className="flex items-center gap-2 mb-3">
            <div className="h-px flex-1 bg-slate-800" />
            <h3 className="text-[10px] font-black uppercase tracking-widest text-slate-500 px-2">{round}</h3>
            <div className="h-px flex-1 bg-slate-800" />
          </div>
          <div className="space-y-3">
            {byRound[round].map(s => (
              <SeriesVoteBar key={s.series_id} s={s} currentUser={currentUser} />
            ))}
          </div>
        </div>
      ))}

      {/* ── Futures top picks — aggregate counts, always visible ── */}
      {hasFutures && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <div className="h-px flex-1 bg-slate-800" />
            <h3 className="text-[10px] font-black uppercase tracking-widest text-slate-500 px-2">Top Futures Picks</h3>
            <div className="h-px flex-1 bg-slate-800" />
          </div>

          {stats.futures.top_champions.length > 0 && (
            <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-4">
              <p className="text-xs font-black text-amber-400 mb-3 flex items-center gap-1.5">
                🏆 <span>NBA Champions</span>
              </p>
              <div className="divide-y divide-slate-800/50">
                {stats.futures.top_champions.map((item, i) => (
                  <FuturesPickBar key={i} item={item} rank={i} totalUsers={stats.total_users} />
                ))}
              </div>
            </div>
          )}

          {(stats.futures.top_west_champs.length > 0 || stats.futures.top_east_champs.length > 0) && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {stats.futures.top_west_champs.length > 0 && (
                <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-4">
                  <p className="text-xs font-black text-blue-400 mb-3">🌵 West Champs</p>
                  <div className="divide-y divide-slate-800/50">
                    {stats.futures.top_west_champs.map((item, i) => (
                      <FuturesPickBar key={i} item={item} rank={i} totalUsers={stats.total_users} />
                    ))}
                  </div>
                </div>
              )}
              {stats.futures.top_east_champs.length > 0 && (
                <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-4">
                  <p className="text-xs font-black text-green-400 mb-3">🗽 East Champs</p>
                  <div className="divide-y divide-slate-800/50">
                    {stats.futures.top_east_champs.map((item, i) => (
                      <FuturesPickBar key={i} item={item} rank={i} totalUsers={stats.total_users} />
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const LeaderboardPage = ({ onUserClick, currentUser }) => {
  const [leaderboard, setLeaderboard] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(null);
  const [tab, setTab] = useState('rankings'); // 'rankings' | 'global'

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
      <div className="flex items-center gap-3 mb-6">
        <Users className="w-7 h-7 text-orange-400" />
        <h1 className="text-4xl font-black text-white">Leaderboard</h1>
      </div>

      {/* Tab switcher */}
      <div className="flex gap-1 bg-slate-900/70 border border-slate-800 rounded-xl p-1 mb-6">
        {[{ id: 'rankings', label: '🏅 Rankings' }, { id: 'global', label: '🌍 Global Stats' }].map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex-1 py-2 px-4 rounded-lg text-sm font-bold transition-all ${
              tab === t.id
                ? 'bg-orange-500 text-white shadow'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'global' ? <GlobalStatsTab currentUser={currentUser} /> : loading ? (
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
                  {/* Rank / Avatar */}
                  <div className="relative shrink-0">
                    {user.avatar_url ? (
                      <img
                        src={user.avatar_url} alt={user.username}
                        className={`w-10 h-10 rounded-full object-cover border-2 ${
                          user.rank === 1 ? 'border-amber-500/60' :
                          user.rank === 2 ? 'border-slate-400/60' :
                          user.rank === 3 ? 'border-orange-600/60' :
                          'border-slate-700'
                        }`}
                        onError={e => { e.target.style.display = 'none'; e.target.nextSibling.style.display = 'flex'; }}
                      />
                    ) : null}
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center font-black text-sm ${user.avatar_url ? 'hidden' : ''} ${
                      user.rank === 1 ? 'bg-amber-500/20 text-amber-400 border border-amber-500/40' :
                      user.rank === 2 ? 'bg-slate-400/20 text-slate-300 border border-slate-400/40' :
                      user.rank === 3 ? 'bg-orange-700/20 text-orange-400 border border-orange-700/40' :
                      'bg-slate-800 text-slate-400'
                    }`}>
                      {user.rank <= 3 ? medals[user.rank - 1] : user.rank}
                    </div>
                    {user.rank <= 3 && user.avatar_url && (
                      <span className="absolute -bottom-1 -right-1 text-sm leading-none">{medals[user.rank - 1]}</span>
                    )}
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

// ── PWA Install Banner — iOS only ─────────────────────────────────────────────
// Android/Chrome install is handled via the sidebar "Install App" button which
// uses the beforeinstallprompt event lifted to App-level state.
const InstallBanner = () => {
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (localStorage.getItem('pwa_dismissed')) return;
    if (window.matchMedia('(display-mode: standalone)').matches) return;
    const ios = /iphone|ipad|ipod/i.test(navigator.userAgent) && !(window).MSStream;
    if (ios) setShow(true);
  }, []);

  if (!show) return null;

  return (
    <div className="fixed bottom-20 md:bottom-6 left-3 right-3 md:left-auto md:right-6 md:max-w-sm z-50 bg-slate-900 border border-orange-500/40 rounded-2xl shadow-2xl shadow-orange-500/10 p-4 flex items-start gap-3">
      <div className="w-10 h-10 bg-gradient-to-br from-orange-500 to-red-600 rounded-xl flex items-center justify-center shrink-0">
        <Trophy className="w-5 h-5 text-white" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-black text-white">Install NBA Picks</p>
        <div className="mt-1.5 space-y-1">
          <p className="text-xs text-slate-400 flex items-center gap-1 flex-wrap">
            1. Tap the
            <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700">
              <Share className="w-3 h-3 text-blue-400" />
              <span className="text-[10px] font-bold text-slate-300">Share</span>
            </span>
            icon in Safari
          </p>
          <p className="text-xs text-slate-400">
            2. Tap <span className="font-bold text-slate-200">"Add to Home Screen"</span>
          </p>
        </div>
      </div>
      <button
        onClick={() => { setShow(false); localStorage.setItem('pwa_dismissed', '1'); }}
        className="text-slate-500 hover:text-slate-300 shrink-0 transition-colors"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
};

// ── Notification Centre ──────────────────────────────────────────────────────
// Strip leading emoji from a label like "🏆 Champion" → "Champion"
const stripLeadingEmoji = (s) => s.replace(/^(\p{Emoji_Presentation}|\p{Emoji}\uFE0F)\s*/u, '').trim();
const leadingEmoji      = (s, fallback) => {
  const m = s.match(/^(\p{Emoji_Presentation}|\p{Emoji}\uFE0F)/u);
  return m ? m[0] : fallback;
};

const BellButton = ({ userId, onNavigate, className = '' }) => {
  const [open,       setOpen]       = useState(false);
  const [subscribed, setSubscribed] = useState(false);
  const [subLoading, setSubLoading] = useState(false);
  // popPos: { top, left? right? } — computed from button rect on open
  const [popPos,    setPopPos]      = useState(null);
  const buttonRef  = useRef(null);
  const panelRef   = useRef(null);

  // ── Cached notification summary ──────────────────────────────────────────
  const { data: summary } = useQuery({
    queryKey: ['notifications', userId],
    queryFn:  () => api.getNotificationsSummary(userId),
    enabled:  !!userId,
    staleTime: 2 * 60 * 1000,
    refetchOnWindowFocus: true,
  });

  // ── OneSignal subscription state ─────────────────────────────────────────
  useEffect(() => {
    let alive = true;

    // Read optedIn directly from the SDK.  OneSignal's optedIn already
    // combines the browser permission state with the user's opt-in choice,
    // so we don't need a separate permissionNative check.
    const readState = () => {
      if (!alive || !window.OneSignal) return;
      setSubscribed(window.OneSignal.User?.PushSubscription?.optedIn ?? false);
    };

    // Stable handler so addEventListener/removeEventListener pair correctly.
    const onChange = () => readState();

    _osPromise.then(() => {
      if (!alive) return;
      readState();
      try { window.OneSignal?.User?.PushSubscription?.addEventListener('change', onChange); } catch {}
    });

    return () => {
      alive = false;
      try { window.OneSignal?.User?.PushSubscription?.removeEventListener('change', onChange); } catch {}
    };
  }, [userId]);

  // ── Anchor panel to button via getBoundingClientRect — no magic numbers ──
  useEffect(() => {
    if (!open || !buttonRef.current) return;
    const r      = buttonRef.current.getBoundingClientRect();
    const W      = window.innerWidth;
    const H      = window.innerHeight;
    const PW     = 320;   // panel width  (w-80)
    const PH     = 520;   // safe panel height estimate for clamping
    const GAP    = 8;

    if (W - r.right >= PW + GAP) {
      // ── Sidebar bell: open to the RIGHT of the icon ─────────────────────
      // top aligns with button top, clamped so panel never goes below viewport
      const top = Math.max(GAP, Math.min(r.top, H - PH - GAP));
      // arrowOffset = distance from panel top to the vertical midpoint of the button
      const arrowOffset = (r.top + r.height / 2) - top;
      setPopPos({ placement: 'right', top, left: r.right + GAP, arrowOffset });
    } else {
      // ── Header bell: open BELOW the icon, right-edge aligned to button ──
      // left = button right edge minus panel width, clamped inside viewport
      const left = Math.max(GAP, Math.min(r.right - PW, W - PW - GAP));
      // arrowOffset = distance from panel left to the horizontal midpoint of the button
      const arrowOffset = (r.left + r.width / 2) - left;
      setPopPos({ placement: 'below', top: r.bottom + GAP, left, arrowOffset });
    }
  }, [open]);

  // ── Outside click / touch closes panel ───────────────────────────────────
  useEffect(() => {
    if (!open) return;
    const onDown = (e) => {
      if (panelRef.current?.contains(e.target))  return;
      if (buttonRef.current?.contains(e.target)) return;
      setOpen(false);
    };
    document.addEventListener('mousedown',  onDown);
    document.addEventListener('touchstart', onDown, { passive: true });
    return () => {
      document.removeEventListener('mousedown',  onDown);
      document.removeEventListener('touchstart', onDown);
    };
  }, [open]);

  const badgeCount = summary?.total ?? 0;
  const isCritical = badgeCount > 0;
  // Match Tailwind md: — sidebar is hidden below 768 px
  const isMobile   = window.innerWidth < 768;

  const handleSubscribeToggle = async () => {
    setSubLoading(true);
    try {
      await _osPromise;  // wait for SDK init (resolves in ≤10 s)

      // Guard: if the script never loaded, bail silently
      if (!window.OneSignal) { setSubLoading(false); return; }

      if (subscribed) {
        await window.OneSignal.User.PushSubscription.optOut();
        // Re-read actual state after the call settles
        setSubscribed(window.OneSignal.User?.PushSubscription?.optedIn ?? false);
      } else {
        // optIn() shows the browser permission prompt if not yet granted.
        // Works on desktop Chrome/Firefox, Android Chrome, and iOS 16.4+ PWA.
        await window.OneSignal.User.PushSubscription.optIn();
        // Re-read: if user denied the prompt, optedIn will still be false
        setSubscribed(window.OneSignal.User?.PushSubscription?.optedIn ?? false);
      }
    } catch { /* permission prompt dismissed or SDK error — leave state as-is */ }
    setSubLoading(false);
  };

  const goTo = (page) => { setOpen(false); onNavigate(page); };

  // Navigate to the home page then scroll to the futures/leaders section
  const goToFutures = () => {
    setOpen(false);
    onNavigate('home');
    setTimeout(() => {
      document.getElementById('futures-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 150);
  };

  // ── Item row ──────────────────────────────────────────────────────────────
  const Item = ({ emoji, label, sublabel, accent, onClick }) => (
    <button
      onClick={onClick}
      className="w-full flex items-center gap-3 px-4 py-3 hover:bg-white/5 active:bg-white/10 transition-colors text-left"
      style={{ minHeight: 60 }}
    >
      <div className={`w-10 h-10 rounded-xl ${accent} flex items-center justify-center shrink-0 text-lg`}>
        {emoji}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-[13px] font-bold text-white leading-snug truncate">{label}</p>
        {sublabel && <p className="text-[11px] text-slate-500 mt-0.5 truncate">{sublabel}</p>}
      </div>
      <div className="flex items-center gap-1 shrink-0 px-2 py-1 rounded-lg bg-orange-500/15 border border-orange-500/25">
        <span className="text-[11px] font-black text-orange-400">Pick</span>
        <ChevronRight className="w-3 h-3 text-orange-400" />
      </div>
    </button>
  );

  // ── Panel body ────────────────────────────────────────────────────────────
  const panelBody = (
    <div ref={panelRef} className="flex flex-col bg-slate-900 border border-slate-700/80 rounded-2xl shadow-2xl shadow-black/70 overflow-hidden" style={{ width: 320 }}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3.5 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-2.5">
          <Bell className="w-4 h-4 text-slate-400" />
          <span className="text-sm font-black text-white tracking-wide">Notifications</span>
          {badgeCount > 0 && (
            <span className="min-w-[20px] h-5 flex items-center justify-center px-1.5 rounded-full bg-red-500 text-white text-[10px] font-black">
              {badgeCount > 9 ? '9+' : badgeCount}
            </span>
          )}
        </div>
        <button
          onClick={() => setOpen(false)}
          className="w-7 h-7 flex items-center justify-center rounded-lg text-slate-500 hover:text-white hover:bg-slate-800 transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* List */}
      <div className="overflow-y-auto overscroll-contain" style={{ maxHeight: 380 }}>
        {!summary ? (
          <div className="px-4 py-4 space-y-3">
            {[1, 2, 3].map(i => (
              <div key={i} className="flex items-center gap-3 animate-pulse">
                <div className="w-10 h-10 rounded-xl bg-slate-800 shrink-0" />
                <div className="flex-1 space-y-2">
                  <div className="h-3 bg-slate-800 rounded-md w-3/4" />
                  <div className="h-2 bg-slate-800/60 rounded-md w-1/2" />
                </div>
              </div>
            ))}
          </div>
        ) : badgeCount === 0 ? (
          <div className="px-4 py-10 text-center">
            <p className="text-4xl mb-3">🍀</p>
            <p className="text-sm font-black text-white">All caught up!</p>
            <p className="text-xs text-slate-500 mt-1.5">Nothing missing — good luck 🏀</p>
          </div>
        ) : (
          <div className="py-1.5">
            {(summary.missing_series?.length > 0) && (
              <>
                <p className="px-4 pt-3 pb-1 text-[10px] font-black text-slate-500 uppercase tracking-widest">
                  Bracket Picks
                </p>
                {summary.missing_series.map(s => (
                  <Item key={s.id}
                    emoji="🏀"
                    label={s.label}
                    sublabel={s.sublabel}
                    accent="bg-orange-500/15 border border-orange-500/25"
                    onClick={() => goTo('betting')}
                  />
                ))}
              </>
            )}
            {(summary.missing_futures?.length > 0) && (
              <>
                <p className="px-4 pt-3 pb-1 text-[10px] font-black text-slate-500 uppercase tracking-widest">
                  Futures Picks
                </p>
                {summary.missing_futures.map(f => (
                  <Item key={f.key}
                    emoji={leadingEmoji(f.label, '🏆')}
                    label={stripLeadingEmoji(f.label)}
                    accent="bg-purple-500/15 border border-purple-500/25"
                    onClick={goToFutures}
                  />
                ))}
              </>
            )}
            {(summary.missing_leaders?.length > 0) && (
              <>
                <p className="px-4 pt-3 pb-1 text-[10px] font-black text-slate-500 uppercase tracking-widest">
                  Playoff Leaders
                </p>
                {summary.missing_leaders.map(l => (
                  <Item key={l.key}
                    emoji={leadingEmoji(l.label, '📊')}
                    label={stripLeadingEmoji(l.label)}
                    accent="bg-cyan-500/15 border border-cyan-500/25"
                    onClick={goToFutures}
                  />
                ))}
              </>
            )}
          </div>
        )}
      </div>

      {/* Footer — Push toggle */}
      <div className="px-4 py-3.5 border-t border-slate-800 flex items-center justify-between gap-4 shrink-0">
        <div className="min-w-0">
          <p className="text-xs font-bold text-white">Push notifications</p>
          <p className="text-[10px] text-slate-500 mt-0.5">
            {subscribed ? 'Enabled — alerts are on' : 'Off — tap to enable alerts'}
          </p>
        </div>
        <button
          onClick={handleSubscribeToggle}
          disabled={subLoading}
          aria-pressed={subscribed}
          title={subscribed ? 'Disable push notifications' : 'Enable push notifications'}
          className={`relative w-12 h-6 rounded-full transition-all duration-200 shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-500 disabled:opacity-50 ${
            subscribed ? 'bg-orange-500 shadow-md shadow-orange-500/40' : 'bg-slate-700'
          }`}
        >
          <span
            className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow-md transition-transform duration-200 ${
              subscribed ? 'translate-x-6' : 'translate-x-0'
            }`}
          />
        </button>
      </div>
    </div>
  );

  return (
    <>
      {/* ── Bell trigger ─────────────────────────────────────────────────── */}
      <div className={className}>
        <button
          ref={buttonRef}
          onClick={() => setOpen(o => !o)}
          title={isCritical ? `${badgeCount} action${badgeCount > 1 ? 's' : ''} needed` : 'Notifications'}
          className="relative p-2 rounded-xl hover:bg-slate-800/60 active:bg-slate-700/60 transition-colors"
          style={{ minWidth: 36, minHeight: 36 }}
        >
          <Bell className={`w-5 h-5 ${isCritical ? 'text-orange-400' : 'text-slate-400'} ${isCritical ? 'bell-shake' : ''}`} />
          {badgeCount > 0 && (
            <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] flex items-center justify-center px-1 rounded-full bg-red-500 text-white text-[10px] font-black leading-none ring-2 ring-slate-900 pointer-events-none">
              {badgeCount > 9 ? '9+' : badgeCount}
            </span>
          )}
        </button>
      </div>

      {/* ── Panel — always via portal so z-index / overflow never clips ───── */}
      {open && createPortal(
        isMobile ? (
          // ── Mobile: full bottom sheet ──────────────────────────────────
          <>
            <div className="fixed inset-0 bg-black/65 z-[998]" onClick={() => setOpen(false)} />
            <div
              ref={panelRef}
              className="fixed bottom-0 left-0 right-0 z-[999] flex flex-col bg-slate-900 border-t border-slate-700 rounded-t-2xl shadow-2xl pb-safe"
              style={{ maxHeight: '84vh' }}
            >
              {/* drag handle */}
              <div className="flex justify-center pt-3 pb-1.5 shrink-0">
                <div className="w-10 h-1 rounded-full bg-slate-700" />
              </div>
              {/* reuse panel body content — strip outer card shell for sheet */}
              <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800 shrink-0">
                <div className="flex items-center gap-2.5">
                  <Bell className="w-4 h-4 text-slate-400" />
                  <span className="text-sm font-black text-white">Notifications</span>
                  {badgeCount > 0 && (
                    <span className="min-w-[20px] h-5 flex items-center justify-center px-1.5 rounded-full bg-red-500 text-white text-[10px] font-black">
                      {badgeCount > 9 ? '9+' : badgeCount}
                    </span>
                  )}
                </div>
                <button onClick={() => setOpen(false)} className="w-7 h-7 flex items-center justify-center rounded-lg text-slate-500 hover:text-white hover:bg-slate-800 transition-colors">
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="overflow-y-auto overscroll-contain flex-1">
                {!summary ? (
                  <div className="px-4 py-4 space-y-3">
                    {[1, 2, 3].map(i => (
                      <div key={i} className="flex items-center gap-3 animate-pulse">
                        <div className="w-10 h-10 rounded-xl bg-slate-800 shrink-0" />
                        <div className="flex-1 space-y-2">
                          <div className="h-3 bg-slate-800 rounded-md w-3/4" />
                          <div className="h-2 bg-slate-800/60 rounded-md w-1/2" />
                        </div>
                      </div>
                    ))}
                  </div>
                ) : badgeCount === 0 ? (
                  <div className="px-4 py-12 text-center">
                    <p className="text-4xl mb-3">🍀</p>
                    <p className="text-sm font-black text-white">All caught up!</p>
                    <p className="text-xs text-slate-500 mt-1.5">Nothing missing — good luck 🏀</p>
                  </div>
                ) : (
                  <div className="py-1.5">
                    {(summary.missing_series?.length > 0) && (
                      <>
                        <p className="px-4 pt-3 pb-1 text-[10px] font-black text-slate-500 uppercase tracking-widest">Bracket Picks</p>
                        {summary.missing_series.map(s => (
                          <Item key={s.id} emoji="🏀" label={s.label} sublabel={s.sublabel} accent="bg-orange-500/15 border border-orange-500/25" onClick={() => goTo('betting')} />
                        ))}
                      </>
                    )}
                    {(summary.missing_futures?.length > 0) && (
                      <>
                        <p className="px-4 pt-3 pb-1 text-[10px] font-black text-slate-500 uppercase tracking-widest">Futures Picks</p>
                        {summary.missing_futures.map(f => (
                          <Item key={f.key} emoji={leadingEmoji(f.label, '🏆')} label={stripLeadingEmoji(f.label)} accent="bg-purple-500/15 border border-purple-500/25" onClick={goToFutures} />
                        ))}
                      </>
                    )}
                    {(summary.missing_leaders?.length > 0) && (
                      <>
                        <p className="px-4 pt-3 pb-1 text-[10px] font-black text-slate-500 uppercase tracking-widest">Playoff Leaders</p>
                        {summary.missing_leaders.map(l => (
                          <Item key={l.key} emoji={leadingEmoji(l.label, '📊')} label={stripLeadingEmoji(l.label)} accent="bg-cyan-500/15 border border-cyan-500/25" onClick={goToFutures} />
                        ))}
                      </>
                    )}
                  </div>
                )}
              </div>
              <div className="px-4 py-3.5 border-t border-slate-800 flex items-center justify-between gap-4 shrink-0">
                <div>
                  <p className="text-xs font-bold text-white">Push notifications</p>
                  <p className="text-[10px] text-slate-500 mt-0.5">
                    {subscribed ? 'Enabled — alerts are on' : 'Off — tap to enable alerts'}
                  </p>
                </div>
                <button
                  onClick={handleSubscribeToggle}
                  disabled={subLoading}
                  aria-pressed={subscribed}
                  className={`relative w-12 h-6 rounded-full transition-all duration-200 shrink-0 disabled:opacity-50 ${subscribed ? 'bg-orange-500 shadow-md shadow-orange-500/40' : 'bg-slate-700'}`}
                >
                  <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow-md transition-transform duration-200 ${subscribed ? 'translate-x-6' : 'translate-x-0'}`} />
                </button>
              </div>
            </div>
          </>
        ) : (
          // ── Desktop: anchored fixed panel ──────────────────────────────
          popPos && (
            <>
              {/* pointer-events-none: document mousedown handles outside-close; no onClick race */}
              <div className="fixed inset-0 z-[998] pointer-events-none" />
              <div
                className="fixed z-[999]"
                style={{ top: popPos.top, left: popPos.left, position: 'fixed' }}
              >
                {/* ── Arrow connector ── */}
                {popPos.placement === 'right' && (
                  // Left-pointing triangle: visually links panel to sidebar bell
                  <div style={{
                    position: 'absolute',
                    left: -7,
                    top: Math.max(12, popPos.arrowOffset - 7),
                    width: 0, height: 0,
                    borderTop:    '7px solid transparent',
                    borderBottom: '7px solid transparent',
                    borderRight:  '7px solid rgb(51 65 85 / 0.8)',  // slate-700 = panel border
                    zIndex: 1,
                  }} />
                )}
                {popPos.placement === 'below' && (
                  // Up-pointing triangle: visually links panel to header bell
                  <div style={{
                    position: 'absolute',
                    top: -7,
                    left: Math.max(12, popPos.arrowOffset - 7),
                    width: 0, height: 0,
                    borderLeft:   '7px solid transparent',
                    borderRight:  '7px solid transparent',
                    borderBottom: '7px solid rgb(51 65 85 / 0.8)',  // slate-700
                    zIndex: 1,
                  }} />
                )}
                {panelBody}
              </div>
            </>
          )
        ),
        document.body
      )}
    </>
  );
};

function App() {
  const [currentPage, setCurrentPage] = useState('home');
  const [currentUser, setCurrentUser] = useState(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState(null);
  const [profileUsername, setProfileUsername] = useState(null);
  // PWA install prompt — lifted here so sidebar + AccountPage can share it
  const [installPrompt, setInstallPrompt] = useState(null);
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches;

  // Notification badge count — same query key as BellButton → shared cache
  const { data: _navSummary } = useQuery({
    queryKey: ['notifications', currentUser?.user_id],
    queryFn:  () => api.getNotificationsSummary(currentUser.user_id),
    enabled:  !!currentUser?.user_id,
    staleTime: 2 * 60 * 1000,
    refetchOnWindowFocus: true,
  });
  const navBadgeCount = _navSummary?.total ?? 0;

  // Sync app-icon badge on the home screen.
  // 1. Call navigator.setAppBadge() directly from the page (works while app is open).
  // 2. postMessage the count to the service worker so it can set the badge from
  //    SW context — this is what makes the badge persist on the home-screen icon
  //    when the app is closed or backgrounded (the only time you see the icon).
  useEffect(() => {
    // Page context — immediate update while app is open
    if ('setAppBadge' in navigator) {
      if (navBadgeCount > 0) {
        navigator.setAppBadge(navBadgeCount).catch(() => {});
      } else {
        navigator.clearAppBadge().catch(() => {});
      }
    }
    // Service worker context — persists badge after app is closed
    navigator.serviceWorker?.controller?.postMessage({
      type: 'SET_BADGE',
      count: navBadgeCount,
    });
  }, [navBadgeCount]);

  // Capture beforeinstallprompt once so any button in the tree can use it
  useEffect(() => {
    if (isStandalone) return;
    const onPrompt = (e) => { e.preventDefault(); setInstallPrompt(e); };
    const onInstalled = () => setInstallPrompt(null);
    window.addEventListener('beforeinstallprompt', onPrompt);
    window.addEventListener('appinstalled', onInstalled);
    return () => {
      window.removeEventListener('beforeinstallprompt', onPrompt);
      window.removeEventListener('appinstalled', onInstalled);
    };
  }, [isStandalone]);

  const handleInstall = async () => {
    if (!installPrompt) return;
    installPrompt.prompt();
    const { outcome } = await installPrompt.userChoice;
    if (outcome === 'accepted') setInstallPrompt(null);
  };

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

  // Sync OneSignal external ID whenever user changes — waits for SDK ready
  useEffect(() => {
    if (!currentUser) { osLogout(); return; }
    osLogin(currentUser.user_id);
  }, [currentUser?.user_id]);

  const handleLogin = (user) => {
    setCurrentUser(user);
    localStorage.setItem('nba_user', JSON.stringify(user));
    setCurrentPage('home');
  };

  const handleLogout = () => {
    osLogout();
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
    setSelectedUser(user);
    setCurrentPage('user-predictions');
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
      case 'leaderboard':      return <LeaderboardPage onUserClick={handleUserClick} currentUser={currentUser} />;
      case 'mypredictions':    return <MyPredictionsPage currentUser={currentUser} />;
      case 'profile':          return <UserProfilePage username={profileUsername || currentUser?.username} currentUser={currentUser} />;
      case 'account':          return <AccountPage currentUser={currentUser} onLogout={handleLogout} onUserUpdate={handleUserUpdate} canInstall={!!installPrompt} onInstall={handleInstall} />;
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
              const badge = item.id === 'betting' && navBadgeCount > 0 ? navBadgeCount : 0;
              return (
                <button key={item.id} onClick={handleNav}
                  className={`group flex items-center w-full px-3 py-3 text-sm font-semibold rounded-xl transition-all ${
                    currentPage === item.id
                      ? 'bg-gradient-to-r from-orange-500 to-red-600 text-white shadow-lg'
                      : 'text-slate-300 hover:bg-slate-800/50'
                  }`}>
                  <div className="relative mr-3 shrink-0">
                    <Icon className="h-5 w-5" />
                    {badge > 0 && (
                      <span className="absolute -top-1.5 -right-1.5 min-w-[16px] h-4 flex items-center justify-center px-0.5 rounded-full bg-red-500 text-white text-[9px] font-black leading-none ring-1 ring-slate-900">
                        {badge > 9 ? '9+' : badge}
                      </span>
                    )}
                  </div>
                  {item.label}
                  {badge > 0 && (
                    <span className="ml-auto min-w-[20px] h-5 flex items-center justify-center px-1.5 rounded-full bg-red-500/20 text-red-400 text-[10px] font-black">
                      {badge > 9 ? '9+' : badge}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>
          {currentUser && (
            <div className="p-4 border-t border-blue-500/20 space-y-2">
              <div className="flex items-center gap-2">
                <button
                  onClick={() => navigate('account')}
                  className={`group flex items-center flex-1 px-3 py-2.5 text-sm font-semibold rounded-xl transition-all ${
                    currentPage === 'account'
                      ? 'bg-gradient-to-r from-orange-500 to-red-600 text-white shadow-lg'
                      : 'text-slate-300 hover:bg-slate-800/50'
                  }`}
                >
                  <Settings className="mr-3 h-4 w-4 shrink-0" />
                  Account Settings
                </button>
                <BellButton userId={currentUser?.user_id} onNavigate={navigate} />
              </div>
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
              {installPrompt && (
                <button
                  onClick={handleInstall}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 text-sm font-bold hover:bg-slate-700 hover:text-white transition-colors"
                >
                  <Download className="w-4 h-4 shrink-0" />
                  Install App
                </button>
              )}
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
            <div className="flex items-center gap-1">
              <BellButton userId={currentUser?.user_id} onNavigate={navigate} />
              <button
                onClick={() => navigate('account')}
                className="flex items-center gap-2 active:opacity-70 transition-opacity px-1"
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
            </div>
          )}
        </div>
      </div>

      {/* ── MAIN CONTENT ── */}
      {/* pb-20 on mobile to clear the bottom nav bar */}
      <main className="md:pl-64 min-h-screen pb-safe md:pb-0">
        <Suspense fallback={<PageSpinner />}>
          {renderPage()}
        </Suspense>
      </main>

      {/* ── PWA INSTALL BANNER ── */}
      <InstallBanner />

      {/* ── MOBILE BOTTOM NAV BAR ── */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 bg-slate-900/95 backdrop-blur-xl border-t border-slate-800 flex nav-safe-bottom">
        {bottomNavItems.map((item) => {
          const Icon = item.icon;
          const active = currentPage === item.id;
          const badge  = item.id === 'betting' && navBadgeCount > 0 ? navBadgeCount : 0;
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
              <div className="relative">
                <Icon className={`w-5 h-5 ${active ? 'text-orange-400' : 'text-slate-500'}`} />
                {badge > 0 && (
                  <span className="absolute -top-1 -right-2.5 min-w-[15px] h-[15px] flex items-center justify-center px-0.5 rounded-full bg-red-500 text-white text-[8px] font-black leading-none ring-1 ring-slate-900">
                    {badge > 9 ? '9+' : badge}
                  </span>
                )}
              </div>
              <span className={`text-[10px] font-bold leading-none ${active ? 'text-orange-400' : 'text-slate-500'}`}>
                {item.label}
              </span>
              {active && <div className="absolute bottom-0 h-0.5 w-8 bg-orange-400 rounded-full" />}
            </button>
          );
        })}
        {/* Install App tab — only shown on Android/Chrome when install is available */}
        {installPrompt && (
          <button
            onClick={handleInstall}
            className="flex-1 flex flex-col items-center justify-center py-2 gap-0.5 min-h-[56px] text-sky-400 active:bg-slate-800/60 transition-colors"
          >
            <Download className="w-5 h-5" />
            <span className="text-[10px] font-bold leading-none">Install</span>
          </button>
        )}
      </nav>
    </div>
  );
}

export default App;