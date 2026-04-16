import React, { useState, useEffect, useRef, lazy, Suspense } from 'react';
import { createPortal } from 'react-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Trophy, Users, BarChart3, Home as HomeIcon, LogOut, Star, Shield, Download, X, Settings, Info, ChevronDown, ChevronRight, Share, Bell, Lock } from 'lucide-react';
import * as api from './services/api';
import * as ns from './utils/notifications';

// ── OneSignal v16 — fire-and-forget, isolated from app rendering ──────────────
//
// Architecture:
//   • _osPromise = Promise.resolve() — always resolved immediately.
//     Nothing in the render path awaits OneSignal; the app boots unconditionally.
//   • _bootOneSignal() polls for the CDN SDK, calls init(), then registers an
//     event-based subscription listener.  Any failure is caught and logged.
//   • ns.loginUser(id) links a confirmed user ID to their subscription ONLY when
//     the device already has a permanent onesignalId (not a "local-…" temp ID).
//     Calling login() before that causes the OperationRepo 400 race condition.
//
const _osAppId   = 'c69b4c3e-79d1-48a4-8815-3ceabc1eae70';
const _osPromise = Promise.resolve();  // always resolved — never blocks the app

// Safe accessor — null while CDN script is loading or if init fails.
const os = () => (window.OneSignal && !Array.isArray(window.OneSignal) ? window.OneSignal : null);

// Pending user ID — stored at module level so _bootOneSignal's subscription
// change listener can pick it up after init completes.
let _pendingLinkId = null;

async function _bootOneSignal() {
  try {
    // Poll until the CDN script replaces window.OneSignal with the live SDK.
    let waited = 0;
    while (!os() && waited < 10000) {
      await new Promise(r => setTimeout(r, 200));
      waited += 200;
    }
    if (!os()) { console.warn('[OneSignal] SDK not ready after 10 s — push disabled'); return; }

    await window.OneSignal.init({
      appId:               _osAppId,
      allowLocalhostAsSecureOrigin: true,
      notifyButton:        { enable: false },
      slidedown:           { prompts: []   },
      customLink:          { enable: false },
      welcomeNotification: { disable: true },
    });

    // Remove any injected UI nodes (dashboard settings can override SDK config).
    ['#onesignal-bell-container','#onesignal-slidedown-container','#onesignal-popover-container']
      .forEach(sel => document.querySelector(sel)?.remove());

    // Re-register sw.js so our badge-handling logic stays active.
    if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});

    // Event-based login: fires when SDK syncs a local- ID to a permanent UUID.
    // All guards (permission, optedIn, UUID check) live inside ns.loginUser().
    try {
      window.OneSignal.User.PushSubscription.addEventListener('change', (event) => {
        try {
          if ((event?.current?.optedIn ?? false) && _pendingLinkId) {
            ns.loginUser(_pendingLinkId);
          }
        } catch { /* swallow */ }
      });
    } catch { /* SDK version may not support addEventListener — skip */ }

    // Attempt immediately for returning visitors already subscribed.
    if (_pendingLinkId) ns.loginUser(_pendingLinkId);

  } catch (err) {
    console.warn('[OneSignal] init error (push disabled for this session):', err?.message ?? err);
  }
}

// Boot asynchronously — intentionally not awaited, never blocks rendering.
_bootOneSignal();

// ── Persistent badging ────────────────────────────────────────────────────────
// updateGlobalBadge(count) is the single source of truth for the home-screen
// app icon badge.  It works in two layers:
//   1. navigator.setAppBadge()  — page context, immediate while app is open.
//   2. SYNC_BADGE postMessage → sw.js — SW context, persists after app closes
//      and survives ColorOS/OPPO clearing the badge on notification dismissal
//      by restoring from IndexedDB on every SW activate.
function updateGlobalBadge(count) {
  const n = Number(count) || 0;

  // Layer 1: page context (works while the page is open)
  if ('setAppBadge' in navigator) {
    if (n > 0) {
      navigator.setAppBadge(n).catch(() => navigator.setAppBadge().catch(() => {}));
    } else {
      navigator.clearAppBadge().catch(() => {});
    }
  }

  // Layer 2: service worker context (persists + survives notification dismissal)
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.ready
      .then(reg => reg.active?.postMessage({ type: 'SYNC_BADGE', count: n }))
      .catch(() => {});
  }
}

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

// ── Futures + Playoff Leaders lock timer ─────────────────────────────────────
// Locks when CLE vs TOR tips off: Saturday April 18 17:00 UTC = 20:00 IDT
const FUTURES_LOCK_UTC = '2026-04-18T17:00:00Z';

function useBigCountdown(targetZ) {
  const calc = () => Math.floor((new Date(targetZ) - Date.now()) / 1000);
  const [secs, setSecs] = useState(calc);
  useEffect(() => {
    const id = setInterval(() => setSecs(calc()), 1000);
    return () => clearInterval(id);
  }, [targetZ]);
  return secs;
}

function FuturesLockTimer() {
  const secs = useBigCountdown(FUTURES_LOCK_UTC);
  const expired = secs <= 0;

  // Jerusalem time display
  const d = new Date(FUTURES_LOCK_UTC);
  const idt = new Date(d.getTime() + 3 * 60 * 60 * 1000);
  const hh = String(idt.getUTCHours()).padStart(2, '0');
  const mm = String(idt.getUTCMinutes()).padStart(2, '0');
  const days   = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
  const months = ['January','February','March','April','May','June','July','August','September','October','November','December'];
  const targetLabel = `${days[idt.getUTCDay()]} ${months[idt.getUTCMonth()]} ${idt.getUTCDate()} · ${hh}:${mm} IDT`;

  if (expired) {
    return (
      <div className="flex items-center justify-center gap-3 px-5 py-4 rounded-2xl bg-red-500/15 border border-red-500/30 mb-6">
        <Lock className="w-5 h-5 text-red-400 shrink-0" />
        <div className="text-center">
          <p className="text-red-400 font-black text-base">🔒 Futures & Leaders Bets are Locked</p>
          <p className="text-red-400/70 text-xs mt-0.5">First Round has started · {targetLabel}</p>
        </div>
      </div>
    );
  }

  const dv = Math.floor(secs / 86400);
  const hv = Math.floor((secs % 86400) / 3600);
  const mv = Math.floor((secs % 3600) / 60);
  const sv = secs % 60;
  const pad = n => String(n).padStart(2, '0');
  const urgent = secs < 3600;
  const soon   = secs < 86400;

  return (
    <div className={`px-5 py-4 rounded-2xl border text-center mb-6
      ${urgent ? 'bg-red-500/15 border-red-500/40' : soon ? 'bg-amber-500/10 border-amber-500/30' : 'bg-slate-800/60 border-slate-700/50'}`}>
      <p className={`text-xs font-bold uppercase tracking-widest mb-2 ${urgent ? 'text-red-400' : soon ? 'text-amber-400' : 'text-slate-400'}`}>
        ⏰ Futures & Playoff Leaders bets lock in
      </p>
      <div className={`flex items-center justify-center gap-3 font-black font-mono
        ${urgent ? 'text-red-400' : soon ? 'text-amber-400' : 'text-orange-400'}`}>
        {dv > 1 && (
          <>
            <div className="flex flex-col items-center">
              <span className="text-3xl sm:text-4xl leading-none">{dv}</span>
              <span className="text-[10px] text-slate-500 font-normal mt-0.5">DAYS</span>
            </div>
            <span className="text-2xl text-slate-600 mb-3">:</span>
          </>
        )}
        <div className="flex flex-col items-center">
          <span className="text-3xl sm:text-4xl leading-none">{pad(hv)}</span>
          <span className="text-[10px] text-slate-500 font-normal mt-0.5">HRS</span>
        </div>
        <span className="text-2xl text-slate-600 mb-3">:</span>
        <div className="flex flex-col items-center">
          <span className="text-3xl sm:text-4xl leading-none">{pad(mv)}</span>
          <span className="text-[10px] text-slate-500 font-normal mt-0.5">MIN</span>
        </div>
        <span className="text-2xl text-slate-600 mb-3">:</span>
        <div className="flex flex-col items-center">
          <span className="text-3xl sm:text-4xl leading-none">{pad(sv)}</span>
          <span className="text-[10px] text-slate-500 font-normal mt-0.5">SEC</span>
        </div>
      </div>
      <p className="text-slate-500 text-[11px] mt-2">
        {targetLabel}
      </p>
    </div>
  );
}

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
      const { data, error: oauthError } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: { redirectTo },
      });
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
        {/* Futures + Leaders lock countdown — top of page */}
        <FuturesLockTimer />

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

// Format an ISO UTC time to Jerusalem (IDT = UTC+3) display string, e.g. "Saturday April 18 · 20:00 IDT"
function _fmtIDT(isoZ) {
  if (!isoZ) return null;
  try {
    const d = new Date(isoZ);
    const idt = new Date(d.getTime() + 3 * 60 * 60 * 1000);
    const days   = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
    const months = ['January','February','March','April','May','June','July','August','September','October','November','December'];
    const hh = String(idt.getUTCHours()).padStart(2, '0');
    const mm = String(idt.getUTCMinutes()).padStart(2, '0');
    return `${days[idt.getUTCDay()]} ${months[idt.getUTCMonth()]} ${idt.getUTCDate()} · ${hh}:${mm} IDT`;
  } catch { return null; }
}

const SeriesVoteBar = ({ s, currentUser }) => {
  const [expanded, setExpanded]       = useState(false);
  const [picks, setPicks]             = useState(null);
  const [loadingPicks, setLoadingPicks] = useState(false);

  const total   = s.total_votes;
  const homePct = s.home_pct;
  const awayPct = s.away_pct;
  const noVotes = total === 0;

  const g1Ms = s.game1_start_time ? new Date(s.game1_start_time).getTime() : null;
  const _initVisible = s.picks_locked || s.status !== 'active' || (g1Ms != null && Date.now() >= g1Ms);
  const [picksVisible, setPicksVisible] = useState(_initVisible);

  useEffect(() => {
    if (picksVisible) return; // already unlocked
    if (!g1Ms) return;
    const ms = g1Ms - Date.now();
    if (ms <= 0) { setPicksVisible(true); return; }
    const t = setTimeout(() => setPicksVisible(true), ms);
    return () => clearTimeout(t);
  }, [g1Ms, picksVisible]);
  const g1Label   = _fmtIDT(s.game1_start_time);

  const handleToggle = async () => {
    if (!picksVisible) return;
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
        {/* Toggle row — individual picks revealed once game1_start_time passes */}
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
        {/* Lock hint — show game time until tipoff */}
        {!picksVisible && g1Label && (
          <p className="text-[9px] text-slate-700 font-bold text-center mt-1">
            Picks revealed at tipoff · {g1Label}
          </p>
        )}
      </div>

      {/* Expandable per-user picks — only once picks are revealed */}
      {picksVisible && expanded && (
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

// ── Play-in vote bar ────────────────────────────────────────────────────────
const PlayinVoteBar = ({ g, currentUser }) => {
  const [expanded, setExpanded]         = useState(false);
  const [picks, setPicks]               = useState(null);
  const [loadingPicks, setLoadingPicks] = useState(false);

  const total  = g.total_votes;
  const noVotes = total === 0;

  // Picks unlock once the backend confirms started OR start_time has passed
  // client-side — guards against sync worker failures (API quota exceeded etc.)
  // NOTE: picksRevealed() (global play-in start date) is intentionally NOT used
  // here because it would expose picks for future games once any game has started.
  const startMs = g.start_time ? new Date(g.start_time + (g.start_time.endsWith('Z') ? '' : 'Z')).getTime() : null;
  const timerPast    = startMs != null && Date.now() >= startMs;
  const picksVisible = Boolean(g.picks_visible) || timerPast;
  const gameStarted  = timerPast;

  // Schedule a one-shot re-render exactly at tipoff if the timer hasn't fired yet
  const [, forceUpdate] = useState(0);
  useEffect(() => {
    if (picksVisible || !startMs) return;
    const ms = startMs - Date.now();
    if (ms <= 0) return;
    const t = setTimeout(() => forceUpdate(n => n + 1), ms);
    return () => clearTimeout(t);
  }, [startMs, picksVisible]);

  const handleToggle = async () => {
    if (!picksVisible) return;   // guard: clicks before tipoff are no-ops
    const next = !expanded;
    setExpanded(next);
    if (next && !picks) {
      setLoadingPicks(true);
      try {
        const data = await api.getPlayInPicks(g.game_id);
        setPicks(data.picks);
      } catch (e) {
        console.error('PlayinVoteBar picks fetch:', e);
        setPicks([]);
      } finally {
        setLoadingPicks(false);
      }
    }
  };

  // Label the game type in human terms
  const gameLabel = g.game_type === 'top'
    ? `${g.conference} — 7 vs 8`
    : g.game_type === 'bottom'
    ? `${g.conference} — 9 vs 10`
    : `${g.conference} — Elimination`;

  const winnerKnown = !!g.winner_id;

  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-2xl overflow-hidden">
      <div className="p-4">
        {/* Header */}
        <div className="flex items-center justify-between mb-3">
          <span className="text-[10px] font-black uppercase tracking-widest text-purple-400">{gameLabel}</span>
          {g.status === 'completed' && (
            <span className="text-[9px] font-black uppercase tracking-widest text-green-400 bg-green-500/10 border border-green-500/20 px-2 py-0.5 rounded-full">Completed</span>
          )}
          {g.status === 'active' && g.start_time && !gameStarted && (
            <span className="text-[9px] font-black text-slate-500 flex items-center gap-1"><Lock className="w-2.5 h-2.5" />Picks locked after tip-off</span>
          )}
        </div>

        {/* Teams row */}
        <div className="flex items-center gap-3 mb-3">
          <div className="flex-1 flex items-center gap-2 min-w-0">
            <img src={g.team1.logo_url} alt={g.team1.abbreviation}
              className={`w-9 h-9 shrink-0 ${winnerKnown && g.winner_id !== g.team1.id ? 'opacity-40' : ''}`}
              loading="lazy" decoding="async" onError={e => e.target.style.display = 'none'} />
            <div className="min-w-0">
              <p className="font-black text-white text-sm leading-tight truncate">{g.team1.name || g.team1.abbreviation}</p>
              <p className="text-[10px] text-slate-500 font-bold">Seed #{g.team1.seed}</p>
            </div>
          </div>
          <div className="text-slate-700 font-black text-xs shrink-0">VS</div>
          <div className="flex-1 flex items-center gap-2 justify-end min-w-0">
            <div className="text-right min-w-0">
              <p className="font-black text-white text-sm leading-tight truncate">{g.team2.name || g.team2.abbreviation}</p>
              <p className="text-[10px] text-slate-500 font-bold">Seed #{g.team2.seed}</p>
            </div>
            <img src={g.team2.logo_url} alt={g.team2.abbreviation}
              className={`w-9 h-9 shrink-0 ${winnerKnown && g.winner_id !== g.team2.id ? 'opacity-40' : ''}`}
              loading="lazy" decoding="async" onError={e => e.target.style.display = 'none'} />
          </div>
        </div>

        {/* Vote bar */}
        <div className="relative h-8 rounded-full overflow-hidden bg-slate-800 flex">
          <div className="h-full bg-purple-500/70 transition-all duration-700"
            style={{ width: noVotes ? '50%' : `${g.team1_pct}%` }} />
          <div className="h-full bg-pink-500/60 flex-1" />
          <div className="absolute inset-0 flex items-center justify-between px-3 pointer-events-none">
            <span className="text-xs font-black text-white drop-shadow-md">{noVotes ? '—' : `${g.team1_pct}%`}</span>
            <span className="text-xs font-black text-white drop-shadow-md">{noVotes ? '—' : `${g.team2_pct}%`}</span>
          </div>
        </div>

        {/* Toggle row */}
        <div className="flex items-center justify-between mt-2 px-1">
          <span className="text-[10px] text-purple-400 font-black">{g.team1.abbreviation}</span>
          {picksVisible ? (
            <button onClick={handleToggle}
              className="flex items-center gap-1 text-[10px] text-slate-500 font-bold hover:text-slate-300 transition-colors">
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
          <span className="text-[10px] text-pink-400 font-black">{g.team2.abbreviation}</span>
        </div>
      </div>

      {/* Expandable per-user picks */}
      {picksVisible && expanded && (
        <div className="border-t border-slate-800/80 bg-slate-950/40">
          {loadingPicks ? (
            <div className="flex justify-center py-5">
              <div className="w-5 h-5 border-2 border-purple-500 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : picks && picks.length > 0 ? (
            <div className="divide-y divide-slate-800/40 max-h-52 overflow-y-auto">
              {picks.map((p, i) => {
                const isMe = currentUser && p.username === currentUser.username;
                return (
                  <div key={i} className={`flex items-center gap-2.5 px-4 py-2.5 ${isMe ? 'bg-purple-500/10' : ''}`}>
                    {p.avatar_url ? (
                      <img src={p.avatar_url} alt="" className="w-6 h-6 rounded-full object-cover shrink-0"
                        onError={e => { e.target.style.display = 'none'; }} />
                    ) : (
                      <div className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 ${isMe ? 'bg-purple-500/30' : 'bg-slate-700'}`}>
                        <span className={`text-[8px] font-black ${isMe ? 'text-purple-400' : 'text-slate-400'}`}>
                          {(p.username || '?')[0].toUpperCase()}
                        </span>
                      </div>
                    )}
                    {isMe && <span className="text-[8px] font-black text-purple-400 bg-purple-500/20 border border-purple-500/30 px-1.5 py-0.5 rounded-full shrink-0">YOU</span>}
                    <span className={`text-xs font-bold flex-1 truncate ${isMe ? 'text-purple-300' : 'text-slate-300'}`}>{p.username}</span>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <img src={p.team_logo_url} alt="" className="w-4 h-4"
                        onError={e => e.target.style.display = 'none'} />
                      <span className={`text-[10px] font-black ${isMe ? 'text-purple-400' : 'text-slate-400'}`}>{p.team_abbreviation}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="text-xs text-slate-600 text-center py-4">No picks yet</p>
          )}
        </div>
      )}
    </div>
  );
};

// ── Section divider ─────────────────────────────────────────────────────────
const SectionDivider = ({ label }) => (
  <div className="flex items-center gap-2">
    <div className="h-px flex-1 bg-slate-800" />
    <h3 className="text-[10px] font-black uppercase tracking-widest text-slate-500 px-2">{label}</h3>
    <div className="h-px flex-1 bg-slate-800" />
  </div>
);

// ── Player pick bar (MVP + leaders) — shows name + vote % bar, no user names ──
const _PB_STYLE = [
  { badge: 'bg-amber-500/20 border-amber-500/40 text-amber-400',   bar: 'bg-amber-500'  },
  { badge: 'bg-slate-500/20 border-slate-400/40 text-slate-300',   bar: 'bg-slate-400'  },
  { badge: 'bg-orange-700/20 border-orange-600/40 text-orange-400', bar: 'bg-orange-500' },
];
const PlayerPickBar = ({ item, rank }) => {
  const style = _PB_STYLE[rank] ?? { badge: 'bg-slate-800 border-slate-700 text-slate-400', bar: 'bg-slate-600' };
  const pct = item.pct ?? 0;
  return (
    <div className="flex items-center gap-2 py-1.5">
      <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-black border shrink-0 ${style.badge}`}>
        {rank < 3 ? ['🥇','🥈','🥉'][rank] : rank + 1}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs font-black text-white truncate">{item.name}</span>
          {item.team && <span className="text-[10px] text-slate-500 ml-1 shrink-0">{item.team}</span>}
          <span className="text-[10px] font-bold text-slate-400 shrink-0 ml-1">{item.count} <span className="text-orange-400">({pct}%)</span></span>
        </div>
        <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
          <div className={`h-full rounded-full transition-all duration-700 ${style.bar}`}
            style={{ width: `${Math.max(pct, 3)}%` }} />
        </div>
      </div>
    </div>
  );
};

const GlobalStatsTab = ({ currentUser }) => {
  const { data: stats, isLoading: loading } = useQuery({
    queryKey: ['globalStats'],
    queryFn:  () => api.getGlobalStats('2026'),
    staleTime: 2 * 60 * 1000,
    refetchOnWindowFocus: true,
    refetchInterval: 3 * 60 * 1000,
  });

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
  (stats.series || []).forEach(s => {
    if (!byRound[s.round]) byRound[s.round] = [];
    byRound[s.round].push(s);
  });
  const sortedRounds = ROUND_ORDER.filter(r => byRound[r]);

  // Play-in grouped by conference
  const playinByConf = {};
  (stats.playin || []).forEach(g => {
    if (!playinByConf[g.conference]) playinByConf[g.conference] = [];
    playinByConf[g.conference].push(g);
  });
  const hasPlayin = (stats.playin || []).length > 0;

  const hasFutures = (stats.futures?.top_champions?.length > 0)
    || (stats.futures?.top_west_champs?.length > 0)
    || (stats.futures?.top_east_champs?.length > 0);

  const totalBets = (stats.total_users || 0);

  return (
    <div className="space-y-6">

      {/* ── Participation banner ── */}
      <div className="bg-gradient-to-r from-orange-500/10 to-amber-500/10 border border-orange-500/20 rounded-2xl p-4">
        <div className="flex items-center justify-center gap-6">
          <div className="text-center">
            <div className="text-3xl font-black text-orange-400 leading-none">{totalBets}</div>
            <div className="text-[10px] text-slate-400 font-bold mt-1 uppercase tracking-wide">Participants</div>
          </div>
          <div className="w-px h-10 bg-slate-700" />
          <div className="text-center">
            <div className="text-3xl font-black text-blue-400 leading-none">{(stats.series || []).length}</div>
            <div className="text-[10px] text-slate-400 font-bold mt-1 uppercase tracking-wide">Series</div>
          </div>
          {hasPlayin && (
            <>
              <div className="w-px h-10 bg-slate-700" />
              <div className="text-center">
                <div className="text-3xl font-black text-purple-400 leading-none">{(stats.playin || []).length}</div>
                <div className="text-[10px] text-slate-400 font-bold mt-1 uppercase tracking-wide">Play-In</div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* ── Play-In games ── */}
      {hasPlayin && (
        <div className="space-y-3">
          <SectionDivider label="Play-In Tournament" />
          {Object.entries(playinByConf).map(([conf, games]) => (
            <div key={conf} className="space-y-3">
              <p className="text-xs font-black text-slate-400 px-1">{conf} Conference</p>
              {games.map(g => (
                <PlayinVoteBar key={g.game_id} g={g} currentUser={currentUser} />
              ))}
            </div>
          ))}
        </div>
      )}

      {/* ── Series votes by round ── */}
      {sortedRounds.map(round => (
        <div key={round} className="space-y-3">
          <SectionDivider label={round} />
          {byRound[round].map(s => (
            <SeriesVoteBar key={s.series_id} s={s} currentUser={currentUser} />
          ))}
        </div>
      ))}

      {/* ── Futures top picks ── */}
      {hasFutures && (
        <div className="space-y-4">
          <SectionDivider label="Top Futures Picks" />

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

          {/* ── MVP picks ── */}
          {(() => {
            const mvpSections = [
              { key: 'top_finals_mvp',      label: '🏆 Finals MVP',       cls: 'text-amber-400'  },
              { key: 'top_west_finals_mvp', label: '🌵 West Finals MVP',  cls: 'text-blue-400'   },
              { key: 'top_east_finals_mvp', label: '🗽 East Finals MVP',  cls: 'text-green-400'  },
            ].filter(s => (stats.futures?.[s.key] || []).length > 0);
            if (!mvpSections.length) return null;
            return (
              <div className="space-y-3">
                <SectionDivider label="MVP Picks" />
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  {mvpSections.map(({ key, label, cls }) => (
                    <div key={key} className="bg-slate-900/60 border border-slate-800 rounded-2xl p-4">
                      <p className={`text-xs font-black mb-3 ${cls}`}>{label}</p>
                      <div className="space-y-2">
                        {(stats.futures[key] || []).map((item, i) => (
                          <PlayerPickBar key={i} item={item} rank={i} />
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })()}
        </div>
      )}

      {/* ── Playoff Leaders max-stat picks ── */}
      {(() => {
        const ld = stats.leaders || {};
        const LEADER_META = [
          { key: 'top_scorer',   label: '🏀 Top Single-Game Score',   unit: 'pts', cls: 'text-orange-400', bar: 'bg-orange-500/70' },
          { key: 'top_assists',  label: '🎯 Top Single-Game Assists',  unit: 'ast', cls: 'text-blue-400',   bar: 'bg-blue-500/70'   },
          { key: 'top_rebounds', label: '💪 Top Single-Game Rebounds', unit: 'reb', cls: 'text-green-400',  bar: 'bg-green-500/70'  },
          { key: 'top_threes',   label: '🎳 Top Single-Game 3s Made', unit: '3pm', cls: 'text-purple-400', bar: 'bg-purple-500/70' },
          { key: 'top_steals',   label: '🤺 Top Single-Game Steals',  unit: 'stl', cls: 'text-cyan-400',   bar: 'bg-cyan-500/70'   },
          { key: 'top_blocks',   label: '🛡️ Top Single-Game Blocks',  unit: 'blk', cls: 'text-red-400',    bar: 'bg-red-500/70'    },
        ].filter(m => (ld[m.key]?.distribution?.length > 0));
        if (!LEADER_META.length) return null;
        return (
          <div className="space-y-3">
            <SectionDivider label="Playoff Leaders Picks — Max Single Game" />
            <p className="text-[10px] text-slate-600 text-center -mt-2">
              Each user predicted the highest single-game stat in the entire playoffs. Closer = more points.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {LEADER_META.map(({ key, label, unit, cls, bar }) => {
                const ld_entry = ld[key];
                const dist = ld_entry?.distribution || [];
                const maxCount = Math.max(...dist.map(d => d.count), 1);
                return (
                  <div key={key} className="bg-slate-900/60 border border-slate-800 rounded-2xl p-4">
                    <div className="flex items-center justify-between mb-3">
                      <p className={`text-xs font-black ${cls}`}>{label}</p>
                      {ld_entry?.avg_value != null && (
                        <span className="text-[10px] text-slate-500 font-bold">
                          avg pick: <span className={`font-black ${cls}`}>{ld_entry.avg_value}</span>
                        </span>
                      )}
                    </div>
                    <div className="space-y-1.5">
                      {dist.map((item, i) => (
                        <div key={i} className="flex items-center gap-2">
                          <span className={`text-xs font-black w-10 text-right shrink-0 ${i === 0 ? cls : 'text-slate-400'}`}>
                            {item.value}
                          </span>
                          <span className="text-[9px] text-slate-600 font-bold w-6 shrink-0">{unit}</span>
                          <div className="flex-1 h-2 bg-slate-800 rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full transition-all duration-500 ${i === 0 ? bar : 'bg-slate-600/50'}`}
                              style={{ width: `${Math.max(item.count / maxCount * 100, 8)}%` }}
                            />
                          </div>
                          <span className="text-[10px] text-slate-500 font-bold w-12 text-right shrink-0">
                            {item.count} {item.count === 1 ? 'pick' : 'picks'}
                          </span>
                        </div>
                      ))}
                    </div>
                    <p className="text-[9px] text-slate-700 mt-2 text-right">
                      {ld_entry?.total_picks} total picks
                    </p>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })()}
    </div>
  );
};

const LeaderboardPage = ({ onUserClick, currentUser }) => {
  const [expanded, setExpanded] = useState(null);
  const [tab, setTab] = useState('rankings');

  const { data: leaderboard = [], isLoading: loading } = useQuery({
    queryKey: ['leaderboard'],
    queryFn:  () => api.getLeaderboard('2026'),
    staleTime: 60 * 1000,
    refetchOnWindowFocus: true,
    refetchInterval: 3 * 60 * 1000,   // auto-refresh every 3 min after game results arrive
  });

  const medals = ['🥇', '🥈', '🥉'];
  const myRank = currentUser ? leaderboard.find(u => u.user_id === currentUser.user_id) : null;

  return (
    <div className="max-w-4xl mx-auto px-4 py-6 pb-24 md:pb-8">

      {/* ── Header ── */}
      <div className="flex items-center gap-3 mb-5">
        <Users className="w-6 h-6 text-orange-400" />
        <h1 className="text-3xl font-black text-white">Leaderboard</h1>
      </div>

      {/* ── Your rank banner (when logged in and ranked) ── */}
      {myRank && (
        <div className="mb-5 bg-gradient-to-r from-orange-500/10 to-amber-500/10 border border-orange-500/30 rounded-2xl p-4 flex items-center gap-4">
          <div className="text-3xl font-black text-orange-400 leading-none shrink-0">
            {myRank.rank <= 3 ? medals[myRank.rank - 1] : `#${myRank.rank}`}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-black text-white">Your ranking</p>
            <p className="text-xs text-slate-400 mt-0.5">
              {myRank.correct_predictions}/{myRank.total_predictions} correct · {myRank.accuracy}% accuracy
            </p>
          </div>
          <div className="text-right shrink-0">
            <div className="text-2xl font-black text-orange-400">{myRank.points}</div>
            <div className="text-[10px] text-slate-500 font-bold uppercase">pts</div>
          </div>
        </div>
      )}

      {/* ── Tab switcher ── */}
      <div className="flex gap-1 bg-slate-900/70 border border-slate-800 rounded-xl p-1 mb-5">
        {[{ id: 'rankings', label: '🏅 Rankings' }, { id: 'global', label: '🌍 Community Picks' }].map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`flex-1 py-2.5 px-3 rounded-lg text-sm font-bold transition-all ${
              tab === t.id ? 'bg-orange-500 text-white shadow' : 'text-slate-400 hover:text-white'
            }`}>
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
            const isMe       = currentUser && user.user_id === currentUser.user_id;
            const isExpanded = expanded === user.rank;
            const accuracy   = user.accuracy ?? 0;
            const seriesPts  = user.series_points;
            const playinPts  = user.playin_points;
            const futuresPts = user.futures_points;
            const leadersPts = user.leaders_points;
            const hasBreakdown = [seriesPts, playinPts, futuresPts, leadersPts].some(v => v != null && v > 0);
            const bullseyes  = user.bullseyes_count ?? 0;

            // Risk profile based on pts-per-correct
            const ppc = user.correct_predictions > 0 ? Math.round(user.points / user.correct_predictions) : 0;
            const riskProfile = ppc >= 100 ? { label: '🔥 Degen',    cls: 'text-amber-400 bg-amber-500/10 border-amber-500/30' }
                              : ppc >= 55  ? { label: '⚖️ Balanced', cls: 'text-blue-400  bg-blue-500/10  border-blue-500/30'  }
                              : ppc > 0    ? { label: '🛡️ Safe',     cls: 'text-green-400 bg-green-500/10 border-green-500/30' }
                              : null;

            const rankBorder = isMe
              ? 'border-orange-500/50 ring-1 ring-orange-500/20'
              : user.rank <= 3 ? 'border-amber-500/30' : 'border-slate-800';

            return (
              <div key={user.rank} className={`bg-slate-900/50 border rounded-xl transition-all overflow-hidden ${rankBorder} ${isMe ? 'bg-orange-500/5' : ''}`}>
                <div
                  className="p-3 sm:p-4 flex items-center gap-3 cursor-pointer hover:bg-slate-800/30 transition-colors"
                  onClick={() => setExpanded(isExpanded ? null : user.rank)}
                >
                  {/* Rank number (mobile: small) */}
                  <div className="text-xs font-black text-slate-600 w-5 text-center shrink-0 hidden sm:block">
                    {user.rank <= 3 ? medals[user.rank - 1] : `${user.rank}`}
                  </div>

                  {/* Avatar */}
                  <div className="relative shrink-0">
                    {user.avatar_url ? (
                      <img src={user.avatar_url} alt={user.username}
                        className={`w-9 h-9 sm:w-10 sm:h-10 rounded-full object-cover border-2 ${
                          isMe ? 'border-orange-500/60' :
                          user.rank === 1 ? 'border-amber-500/60' :
                          user.rank === 2 ? 'border-slate-400/60' :
                          user.rank === 3 ? 'border-orange-600/60' : 'border-slate-700'
                        }`}
                        onError={e => { e.target.style.display = 'none'; e.target.nextSibling.style.display = 'flex'; }} />
                    ) : null}
                    <div className={`w-9 h-9 sm:w-10 sm:h-10 rounded-full flex items-center justify-center font-black text-sm ${user.avatar_url ? 'hidden' : ''} ${
                      isMe ? 'bg-orange-500/20 text-orange-400 border border-orange-500/40' :
                      user.rank === 1 ? 'bg-amber-500/20 text-amber-400 border border-amber-500/40' :
                      user.rank === 2 ? 'bg-slate-400/20 text-slate-300 border border-slate-400/40' :
                      user.rank === 3 ? 'bg-orange-700/20 text-orange-400 border border-orange-700/40' :
                      'bg-slate-800 text-slate-400'
                    }`}>
                      {user.rank <= 3 ? medals[user.rank - 1] : user.rank}
                    </div>
                    {user.rank <= 3 && user.avatar_url && (
                      <span className="absolute -bottom-1 -right-1 text-xs leading-none">{medals[user.rank - 1]}</span>
                    )}
                  </div>

                  {/* Name + stats */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <button className={`font-black text-sm hover:text-orange-400 transition-colors text-left truncate ${isMe ? 'text-orange-300' : 'text-white'}`}
                        onClick={(e) => { e.stopPropagation(); onUserClick(user); }}>
                        {user.username}
                        {isMe && <span className="ml-1 text-[9px] text-orange-400 font-black align-middle">(you)</span>}
                      </button>
                      {riskProfile && (
                        <span className={`text-[9px] font-black px-1.5 py-0.5 rounded border hidden sm:inline ${riskProfile.cls}`}>
                          {riskProfile.label}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                      <span className="text-[11px] text-slate-500">
                        {user.correct_predictions ?? 0}/{user.total_predictions ?? 0} correct
                      </span>
                      <span className={`text-[11px] font-black ${
                        accuracy >= 70 ? 'text-green-400' : accuracy >= 50 ? 'text-yellow-400' : 'text-slate-500'
                      }`}>{accuracy}%</span>
                      {bullseyes > 0 && (
                        <span className="text-[10px] text-amber-400 font-black hidden sm:inline">🎯 {bullseyes}</span>
                      )}
                    </div>
                  </div>

                  {/* Points + chevron */}
                  <div className="flex items-center gap-2 shrink-0">
                    <div className="text-right">
                      <div className={`text-xl font-black ${isMe ? 'text-orange-400' : 'text-orange-400'}`}>{user.points}</div>
                      <div className="text-[10px] text-slate-500 font-bold">pts</div>
                    </div>
                    <ChevronDown className={`w-4 h-4 text-slate-600 transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
                  </div>
                </div>

                {/* Expanded breakdown */}
                {isExpanded && (
                  <div className="px-3 sm:px-4 pb-4 border-t border-slate-800 pt-3 space-y-3">
                    {/* Points breakdown grid */}
                    {hasBreakdown ? (
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                        {[
                          { label: 'Series',  val: seriesPts,  cls: 'text-orange-400' },
                          { label: 'Play-In', val: playinPts,  cls: 'text-purple-400' },
                          { label: 'Futures', val: futuresPts, cls: 'text-yellow-400' },
                          { label: 'Leaders', val: leadersPts, cls: 'text-cyan-400'   },
                        ].map(({ label, val, cls }) => (
                          <div key={label} className="text-center bg-slate-800/60 rounded-xl p-2.5">
                            <p className={`text-base font-black ${cls}`}>{val ?? 0}</p>
                            <p className="text-[10px] text-slate-500 font-bold uppercase">{label}</p>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="grid grid-cols-2 gap-2">
                        <div className="text-center bg-slate-800/60 rounded-xl p-2.5">
                          <p className="text-base font-black text-orange-400">{user.points}</p>
                          <p className="text-[10px] text-slate-500 font-bold uppercase">Total pts</p>
                        </div>
                        <div className="text-center bg-slate-800/60 rounded-xl p-2.5">
                          <p className="text-base font-black text-green-400">{accuracy}%</p>
                          <p className="text-[10px] text-slate-500 font-bold uppercase">Accuracy</p>
                        </div>
                      </div>
                    )}
                    {/* Extra stats row */}
                    <div className="flex items-center justify-between px-1 text-[11px] text-slate-500">
                      <span>{user.correct_predictions}/{user.total_predictions} correct picks</span>
                      {bullseyes > 0 && <span className="text-amber-400 font-bold">🎯 {bullseyes} bullseyes</span>}
                      <button className="text-slate-500 hover:text-orange-400 font-bold transition-colors"
                        onClick={(e) => { e.stopPropagation(); onUserClick(user); }}>
                        View profile →
                      </button>
                    </div>
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

// ── BellButton nav item row ── defined outside to prevent remount on every render
const _BellNavItem = ({ emoji, label, sublabel, accent, onClick }) => (
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

const BellButton = ({ userId, onNavigate, className = '' }) => {
  const [open,         setOpen]         = useState(false);
  const [isSDKReady,   setIsSDKReady]   = useState(false);
  // isSubscribed is seeded from localStorage for instant UI on mount.
  // The SDK state overwrites it once isSDKReady becomes true.
  const [isSubscribed, setIsSubscribed] = useState(
    () => ns.getOptedIn()
  );
  const [subLoading,   setSubLoading]   = useState(false);
  const [popPos,       setPopPos]       = useState(null);
  const buttonRef = useRef(null);
  const panelRef  = useRef(null);

  // ── Cached notification summary ──────────────────────────────────────────
  const { data: summary } = useQuery({
    queryKey: ['notifications', userId],
    queryFn:  () => api.getNotificationsSummary(userId),
    enabled:  !!userId,
    staleTime: 2 * 60 * 1000,
    refetchOnWindowFocus: true,
    refetchInterval: 3 * 60 * 1000,
  });

  // ── SDK readiness + subscription state ───────────────────────────────────
  // Poll for SDK readiness — resolves once the CDN script has loaded and
  // OneSignal.init() has replaced window.OneSignal with the live object.
  // If the SDK never loads (disabled, blocked, network error) isSDKReady
  // stays false and the toggle shows a graceful "Unavailable" state.
  useEffect(() => {
    let alive = true;
    let pollTimer = null;
    let retryTimer = null;

    const syncState = () => {
      if (!alive) return;
      try {
        const opted = ns.getOptedIn();
        setIsSubscribed(opted);
        localStorage.setItem('os_push_opted_in', String(opted));
      } catch { /* non-fatal */ }
    };

    const onchange = (event) => {
      if (!alive) return;
      try {
        const opted = event?.current?.optedIn ?? ns.getOptedIn();
        setIsSubscribed(opted);
        localStorage.setItem('os_push_opted_in', String(opted));
      } catch { /* non-fatal */ }
    };

    const checkReady = () => {
      if (!alive) return;
      if (ns.getOneSignal()) {
        setIsSDKReady(true);
        syncState();
        retryTimer = setTimeout(syncState, 1500); // re-read after server fetch
        ns.onSubscriptionChange(onchange);        // returns cleanup fn — stored below
      } else {
        pollTimer = setTimeout(checkReady, 500);  // retry until SDK loads or 10 s
      }
    };

    // Start polling after a short delay so it doesn't block initial render
    pollTimer = setTimeout(checkReady, 300);

    const onVisible = () => {
      if (document.visibilityState === 'visible' && ns.getOneSignal()) syncState();
    };
    document.addEventListener('visibilitychange', onVisible);

    return () => {
      alive = false;
      clearTimeout(pollTimer);
      clearTimeout(retryTimer);
      document.removeEventListener('visibilitychange', onVisible);
      // Remove subscription change listener via the wrapper
      try { ns.onSubscriptionChange(onchange); } catch {}
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
    if (subLoading || !isSDKReady) return;
    setSubLoading(true);
    try {
      const after = isSubscribed ? await ns.optOut() : await ns.optIn();
      setIsSubscribed(after);
      if (after && _pendingLinkId) ns.loginUser(_pendingLinkId);
    } catch (err) {
      console.warn('[PushToggle] unexpected error (non-fatal):', err?.message ?? err);
      setIsSubscribed(ns.getOptedIn());
    } finally {
      setSubLoading(false);
    }
  };

  const goTo = (page, opts = {}) => { setOpen(false); onNavigate(page, opts); };

  // Navigate to the home page then scroll to the futures/leaders section
  const goToFutures = () => {
    setOpen(false);
    onNavigate('home');
    setTimeout(() => {
      document.getElementById('futures-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 150);
  };

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
            {(summary.missing_playin?.length > 0) && (
              <>
                <p className="px-4 pt-3 pb-1 text-[10px] font-black text-slate-500 uppercase tracking-widest">
                  Play-In Picks
                </p>
                {summary.missing_playin.map(g => (
                  <_BellNavItem key={g.id}
                    emoji="⚡"
                    label={g.label}
                    sublabel={g.sublabel}
                    accent="bg-purple-500/15 border border-purple-500/25"
                    onClick={() => goTo('betting', { scrollTo: { type: 'playin', id: g.id } })}
                  />
                ))}
              </>
            )}
            {(summary.missing_series?.length > 0) && (
              <>
                <p className="px-4 pt-3 pb-1 text-[10px] font-black text-slate-500 uppercase tracking-widest">
                  Bracket Picks
                </p>
                {summary.missing_series.map(s => (
                  <_BellNavItem key={s.id}
                    emoji="🏀"
                    label={s.label}
                    sublabel={s.sublabel}
                    accent="bg-orange-500/15 border border-orange-500/25"
                    onClick={() => goTo('betting', { scrollTo: { type: 'series', id: s.id } })}
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
                  <_BellNavItem key={f.key}
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
                  <_BellNavItem key={l.key}
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
            {!isSDKReady ? 'Notifications unavailable' : isSubscribed ? 'Enabled — alerts are on' : 'Off — tap to enable alerts'}
          </p>
        </div>
        <button
          onClick={handleSubscribeToggle}
          disabled={subLoading || !isSDKReady}
          aria-pressed={isSubscribed}
          title={!isSDKReady ? 'Push notifications unavailable' : isSubscribed ? 'Disable push notifications' : 'Enable push notifications'}
          className={`relative w-12 h-6 rounded-full transition-all duration-200 shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-500 disabled:opacity-50 ${
            isSubscribed && isSDKReady ? 'bg-orange-500 shadow-md shadow-orange-500/40' : 'bg-slate-700'
          }`}
        >
          <span
            className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow-md transition-transform duration-200 ${
              isSubscribed && isSDKReady ? 'translate-x-6' : 'translate-x-0'
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
          className="relative flex items-center justify-center rounded-xl hover:bg-slate-800/60 active:bg-slate-700/60 transition-colors"
          style={{ minWidth: 44, minHeight: 44 }}
        >
          <Bell className={`w-5 h-5 ${isCritical ? 'text-orange-400' : 'text-slate-400'} ${isCritical ? 'bell-shake' : ''}`} />
          {badgeCount > 0 && (
            <span className="absolute top-1 right-1 min-w-[18px] h-[18px] flex items-center justify-center px-1 rounded-full bg-red-500 text-white text-[10px] font-black leading-none ring-2 ring-slate-900 pointer-events-none">
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
              style={{ maxHeight: 'min(84dvh, 84vh)' }}
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
                    {(summary.missing_playin?.length > 0) && (
                      <>
                        <p className="px-4 pt-3 pb-1 text-[10px] font-black text-slate-500 uppercase tracking-widest">Play-In Picks</p>
                        {summary.missing_playin.map(g => (
                          <_BellNavItem key={g.id} emoji="⚡" label={g.label} sublabel={g.sublabel} accent="bg-purple-500/15 border border-purple-500/25" onClick={() => goTo('betting', { scrollTo: { type: 'playin', id: g.id } })} />
                        ))}
                      </>
                    )}
                    {(summary.missing_series?.length > 0) && (
                      <>
                        <p className="px-4 pt-3 pb-1 text-[10px] font-black text-slate-500 uppercase tracking-widest">Bracket Picks</p>
                        {summary.missing_series.map(s => (
                          <_BellNavItem key={s.id} emoji="🏀" label={s.label} sublabel={s.sublabel} accent="bg-orange-500/15 border border-orange-500/25" onClick={() => goTo('betting', { scrollTo: { type: 'series', id: s.id } })} />
                        ))}
                      </>
                    )}
                    {(summary.missing_futures?.length > 0) && (
                      <>
                        <p className="px-4 pt-3 pb-1 text-[10px] font-black text-slate-500 uppercase tracking-widest">Futures Picks</p>
                        {summary.missing_futures.map(f => (
                          <_BellNavItem key={f.key} emoji={leadingEmoji(f.label, '🏆')} label={stripLeadingEmoji(f.label)} accent="bg-yellow-500/15 border border-yellow-500/25" onClick={goToFutures} />
                        ))}
                      </>
                    )}
                    {(summary.missing_leaders?.length > 0) && (
                      <>
                        <p className="px-4 pt-3 pb-1 text-[10px] font-black text-slate-500 uppercase tracking-widest">Playoff Leaders</p>
                        {summary.missing_leaders.map(l => (
                          <_BellNavItem key={l.key} emoji={leadingEmoji(l.label, '📊')} label={stripLeadingEmoji(l.label)} accent="bg-cyan-500/15 border border-cyan-500/25" onClick={goToFutures} />
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
                    {!isSDKReady ? 'Notifications unavailable' : isSubscribed ? 'Enabled — alerts are on' : 'Off — tap to enable alerts'}
                  </p>
                </div>
                <button
                  onClick={handleSubscribeToggle}
                  disabled={subLoading || !isSDKReady}
                  aria-pressed={isSubscribed}
                  className={`relative w-12 h-6 rounded-full transition-all duration-200 shrink-0 disabled:opacity-50 ${isSubscribed && isSDKReady ? 'bg-orange-500 shadow-md shadow-orange-500/40' : 'bg-slate-700'}`}
                >
                  <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow-md transition-transform duration-200 ${isSubscribed && isSDKReady ? 'translate-x-6' : 'translate-x-0'}`} />
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

// Pages that require extra state to render correctly — fall back to home on refresh
const _STATEFUL_PAGES = new Set(['user-predictions']);

function _pageFromHash() {
  const h = window.location.hash.slice(1);
  if (!h || _STATEFUL_PAGES.has(h)) return 'home';
  return h;
}

function App() {
  const [currentPage, setCurrentPage] = useState(_pageFromHash);
  const [currentUser, setCurrentUser] = useState(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState(null);
  const [profileUsername, setProfileUsername] = useState(null);
  // Deep-link scroll target for the bracket/betting page
  const [bracketTarget, setBracketTarget] = useState(null);
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
    refetchInterval: 3 * 60 * 1000,
  });
  const navBadgeCount = _navSummary?.total ?? 0;

  // Sync the home-screen app icon badge whenever the count changes.
  // 'subscribed' lives inside BellButton — read optedIn from localStorage here.
  useEffect(() => {
    const isSubscribed = localStorage.getItem('os_push_opted_in') === 'true';
    const count = isSubscribed ? navBadgeCount : 0;
    updateGlobalBadge(count);
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

  // Sync state when user hits browser back/forward or manually edits the hash
  useEffect(() => {
    const onHashChange = () => setCurrentPage(_pageFromHash());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  useEffect(() => {
    // Clear any stale OneSignal operation-queue entries that could cause a
    // 400-retry loop to restart on the next page load even with the SDK disabled.
    ns.clearStaleOSOperations();

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

  // Keep _pendingLinkId in sync with the logged-in user.
  // The 2 s delay gives the OneSignal SDK time to finalise the subscription
  // and replace any "local-…" onesignalId with a real permanent UUID before
  // osLinkUser() runs its guards — eliminating the login-user 400 race.
  useEffect(() => {
    _pendingLinkId = currentUser?.user_id ? String(currentUser.user_id) : null;
    if (!_pendingLinkId) return;
    const t = setTimeout(() => ns.loginUser(_pendingLinkId), 2000);
    return () => clearTimeout(t);
  }, [currentUser?.user_id]);

  const handleLogin = (user) => {
    setCurrentUser(user);
    localStorage.setItem('nba_user', JSON.stringify(user));
    setCurrentPage('home');
  };

  const handleLogout = () => {
    _pendingLinkId = null;
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
    if (opts.username) setProfileUsername(opts.username);
    // scrollTo: { type: 'series'|'playin', id: number } — deep-links into BracketPage
    if (opts.scrollTo) setBracketTarget(opts.scrollTo);
    else if (page !== 'betting') setBracketTarget(null); // clear when leaving bracket
    if (page !== 'user-predictions') setSelectedUser(null);
    // Persist current page in URL hash so refresh returns to same page
    window.location.hash = page === 'home' ? '' : page;
  };

  const handleUserClick = (user) => {
    navigate('profile', { username: user.username });
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
      case 'betting':          return <BracketPage currentUser={currentUser} onNavigate={navigate} scrollTo={bracketTarget} />;
      case 'leaderboard':      return <LeaderboardPage onUserClick={handleUserClick} currentUser={currentUser} />;
      case 'mypredictions':    return <MyPredictionsPage currentUser={currentUser} />;
      case 'profile':          return <UserProfilePage username={profileUsername || currentUser?.username} currentUser={currentUser} onBack={profileUsername && profileUsername !== currentUser?.username ? () => navigate('leaderboard') : undefined} />;
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
          <button onClick={() => navigate('home')} className="flex items-center px-4 mb-8 active:opacity-70 transition-opacity">
            <div className="w-12 h-12 bg-gradient-to-br from-orange-500 to-red-600 rounded-xl flex items-center justify-center mr-3 shrink-0">
              <Trophy className="w-7 h-7 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-black text-white">NBA PLAYOFF</h1>
              <p className="text-xs font-bold text-orange-400">PREDICTOR 2026</p>
            </div>
          </button>
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
      <div className="md:hidden sticky top-0 z-50 bg-slate-900/95 backdrop-blur-xl border-b border-blue-500/20 pt-safe">
        <div className="flex items-center justify-between px-4" style={{ minHeight: 56 }}>
          <button
            onClick={() => navigate('home')}
            className="flex items-center gap-2 active:opacity-70 transition-opacity"
          >
            <div className="w-9 h-9 bg-gradient-to-br from-orange-500 to-red-600 rounded-lg flex items-center justify-center shrink-0">
              <Trophy className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-base font-black text-white leading-none">NBA PLAYOFF</h1>
              <p className="text-[10px] font-bold text-orange-400">PREDICTOR 2026</p>
            </div>
          </button>
          {currentUser && (
            <div className="flex items-center gap-1">
              <BellButton userId={currentUser?.user_id} onNavigate={navigate} />
              {currentUser.role === 'admin' && (
                <button
                  onClick={() => navigate('admin')}
                  className={`flex items-center justify-center w-9 h-9 rounded-lg transition-colors active:opacity-70 ${
                    currentPage === 'admin'
                      ? 'bg-orange-500/20 text-orange-400'
                      : 'text-slate-400 hover:text-white'
                  }`}
                  title="Admin Panel"
                >
                  <Shield className="w-5 h-5" />
                </button>
              )}
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
              className={`flex-1 flex flex-col items-center justify-center py-2 gap-0.5 min-h-[60px] transition-colors active:bg-slate-800/60 ${
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