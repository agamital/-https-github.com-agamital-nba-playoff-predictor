import React, { useState, useEffect, useRef } from 'react';
import { User, Mail, Shield, Calendar, Trophy, Key, AlertTriangle, Check, X, Loader, Camera, ImageIcon } from 'lucide-react';
import * as api from './services/api';
import { Avatar } from './UserProfilePage';

// ── Default NBA-themed SVG avatars ────────────────────────────────────────────
const DEFAULT_AVATARS = [
  { id: 'orange', label: 'Orange', svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="48" fill="#f97316"/><circle cx="50" cy="50" r="48" fill="none" stroke="#c2410c" stroke-width="3"/><path d="M50 2 Q52 50 50 98" stroke="#c2410c" stroke-width="3" fill="none"/><path d="M2 50 Q50 52 98 50" stroke="#c2410c" stroke-width="3" fill="none"/><path d="M12 20 Q50 38 88 20" stroke="#c2410c" stroke-width="2.5" fill="none"/><path d="M12 80 Q50 62 88 80" stroke="#c2410c" stroke-width="2.5" fill="none"/></svg>` },
  { id: 'gold',   label: 'Gold',   svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="48" fill="#eab308"/><circle cx="50" cy="50" r="48" fill="none" stroke="#a16207" stroke-width="3"/><path d="M50 2 Q52 50 50 98" stroke="#a16207" stroke-width="3" fill="none"/><path d="M2 50 Q50 52 98 50" stroke="#a16207" stroke-width="3" fill="none"/><path d="M12 20 Q50 38 88 20" stroke="#a16207" stroke-width="2.5" fill="none"/><path d="M12 80 Q50 62 88 80" stroke="#a16207" stroke-width="2.5" fill="none"/></svg>` },
  { id: 'blue',   label: 'Blue',   svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="48" fill="#3b82f6"/><circle cx="50" cy="50" r="48" fill="none" stroke="#1d4ed8" stroke-width="3"/><path d="M50 2 Q52 50 50 98" stroke="#1d4ed8" stroke-width="3" fill="none"/><path d="M2 50 Q50 52 98 50" stroke="#1d4ed8" stroke-width="3" fill="none"/><path d="M12 20 Q50 38 88 20" stroke="#1d4ed8" stroke-width="2.5" fill="none"/><path d="M12 80 Q50 62 88 80" stroke="#1d4ed8" stroke-width="2.5" fill="none"/></svg>` },
  { id: 'red',    label: 'Red',    svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="48" fill="#ef4444"/><circle cx="50" cy="50" r="48" fill="none" stroke="#b91c1c" stroke-width="3"/><path d="M50 2 Q52 50 50 98" stroke="#b91c1c" stroke-width="3" fill="none"/><path d="M2 50 Q50 52 98 50" stroke="#b91c1c" stroke-width="3" fill="none"/><path d="M12 20 Q50 38 88 20" stroke="#b91c1c" stroke-width="2.5" fill="none"/><path d="M12 80 Q50 62 88 80" stroke="#b91c1c" stroke-width="2.5" fill="none"/></svg>` },
  { id: 'green',  label: 'Green',  svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="48" fill="#22c55e"/><circle cx="50" cy="50" r="48" fill="none" stroke="#15803d" stroke-width="3"/><path d="M50 2 Q52 50 50 98" stroke="#15803d" stroke-width="3" fill="none"/><path d="M2 50 Q50 52 98 50" stroke="#15803d" stroke-width="3" fill="none"/><path d="M12 20 Q50 38 88 20" stroke="#15803d" stroke-width="2.5" fill="none"/><path d="M12 80 Q50 62 88 80" stroke="#15803d" stroke-width="2.5" fill="none"/></svg>` },
  { id: 'purple', label: 'Purple', svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="48" fill="#a855f7"/><circle cx="50" cy="50" r="48" fill="none" stroke="#7e22ce" stroke-width="3"/><path d="M50 2 Q52 50 50 98" stroke="#7e22ce" stroke-width="3" fill="none"/><path d="M2 50 Q50 52 98 50" stroke="#7e22ce" stroke-width="3" fill="none"/><path d="M12 20 Q50 38 88 20" stroke="#7e22ce" stroke-width="2.5" fill="none"/><path d="M12 80 Q50 62 88 80" stroke="#7e22ce" stroke-width="2.5" fill="none"/></svg>` },
];

const svgToDataUrl = (svg) =>
  `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;

// ── AvatarUpload component ────────────────────────────────────────────────────
const AvatarUpload = ({ userId, currentAvatarUrl, onSaved }) => {
  const [preview, setPreview]     = useState(null); // data URL for preview
  const [previewFile, setPreviewFile] = useState(null); // actual File object
  const [uploading, setUploading] = useState(false);
  const [msg, setMsg]             = useState(null);
  const [showDefaults, setShowDefaults] = useState(false);
  const fileInputRef = useRef(null);

  const handleFileChange = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      setMsg({ type: 'error', text: 'Only JPEG, PNG, or WebP images are supported.' });
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setMsg({ type: 'error', text: 'Image must be under 5 MB.' });
      return;
    }
    setMsg(null);
    setPreviewFile(file);
    const reader = new FileReader();
    reader.onload = (ev) => setPreview(ev.target.result);
    reader.readAsDataURL(file);
  };

  const handleUpload = async () => {
    if (!previewFile) return;
    setUploading(true);
    setMsg(null);
    try {
      const data = await api.uploadAvatar(userId, previewFile);
      setPreview(null);
      setPreviewFile(null);
      setMsg({ type: 'ok', text: 'Avatar saved!' });
      onSaved(data.avatar_url);
    } catch (err) {
      setMsg({ type: 'error', text: err.response?.data?.detail || 'Upload failed — is storage configured?' });
    } finally {
      setUploading(false);
    }
  };

  const handleSelectDefault = async (avatarObj) => {
    setUploading(true);
    setMsg(null);
    setShowDefaults(false);
    try {
      // Convert SVG to a File blob and upload
      const blob = new Blob([avatarObj.svg], { type: 'image/svg+xml' });
      // Supabase doesn't accept SVG; convert via canvas to PNG
      const img = new window.Image();
      img.src = svgToDataUrl(avatarObj.svg);
      await new Promise((res, rej) => { img.onload = res; img.onerror = rej; });
      const canvas = document.createElement('canvas');
      canvas.width = 200; canvas.height = 200;
      canvas.getContext('2d').drawImage(img, 0, 0, 200, 200);
      const pngBlob = await new Promise(res => canvas.toBlob(res, 'image/png'));
      const file = new File([pngBlob], `avatar-${avatarObj.id}.png`, { type: 'image/png' });
      const data = await api.uploadAvatar(userId, file);
      setMsg({ type: 'ok', text: 'Avatar saved!' });
      onSaved(data.avatar_url);
    } catch (err) {
      setMsg({ type: 'error', text: err.response?.data?.detail || 'Upload failed — is storage configured?' });
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Current / preview */}
      <div className="flex items-end gap-4">
        <div className="relative">
          {preview ? (
            <img src={preview} alt="Preview" className="w-20 h-20 rounded-full object-cover ring-2 ring-orange-500" />
          ) : currentAvatarUrl ? (
            <img src={currentAvatarUrl} alt="Avatar" className="w-20 h-20 rounded-full object-cover ring-2 ring-slate-600" />
          ) : (
            <div className="w-20 h-20 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
              <Camera className="w-8 h-8 text-white/60" />
            </div>
          )}
          {preview && (
            <span className="absolute -bottom-1 -right-1 text-[9px] font-black bg-orange-500 text-white px-1.5 py-0.5 rounded-full">Preview</span>
          )}
        </div>

        <div className="flex flex-col gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={handleFileChange}
            className="hidden"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 text-xs font-bold hover:bg-slate-700 transition-colors"
          >
            <Camera className="w-3.5 h-3.5" /> Choose Photo
          </button>
          <button
            onClick={() => setShowDefaults(v => !v)}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 text-xs font-bold hover:bg-slate-700 transition-colors"
          >
            <ImageIcon className="w-3.5 h-3.5" /> Default Avatars
          </button>
        </div>
      </div>

      {/* Default avatar picker */}
      {showDefaults && (
        <div className="grid grid-cols-6 gap-2 p-3 bg-slate-800/60 rounded-xl border border-slate-700">
          {DEFAULT_AVATARS.map(av => (
            <button
              key={av.id}
              onClick={() => handleSelectDefault(av)}
              disabled={uploading}
              title={av.label}
              className="group relative rounded-full overflow-hidden ring-2 ring-transparent hover:ring-orange-500 transition-all focus:outline-none"
            >
              <img src={svgToDataUrl(av.svg)} alt={av.label} className="w-12 h-12" />
            </button>
          ))}
        </div>
      )}

      {/* Save button (only shown when a file is chosen via picker) */}
      {previewFile && (
        <button
          onClick={handleUpload}
          disabled={uploading}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-orange-500 hover:bg-orange-600 text-white font-bold text-sm disabled:opacity-50 transition-colors"
        >
          {uploading && <Loader className="w-4 h-4 animate-spin" />}
          {uploading ? 'Uploading…' : 'Save Avatar'}
        </button>
      )}
      {uploading && !previewFile && (
        <div className="flex items-center gap-2 text-sm text-slate-400">
          <Loader className="w-4 h-4 animate-spin" /> Saving…
        </div>
      )}

      <StatusMsg msg={msg} />
      <p className="text-[11px] text-slate-500">JPEG, PNG or WebP · max 5 MB</p>
    </div>
  );
};

const Card = ({ children, className = '' }) => (
  <div className={`bg-slate-900/50 border border-slate-800 rounded-xl backdrop-blur-sm ${className}`}>
    {children}
  </div>
);

const SectionTitle = ({ icon: Icon, label, color = 'text-orange-400' }) => (
  <div className="flex items-center gap-2 mb-4">
    <Icon className={`w-5 h-5 ${color}`} />
    <h2 className="text-lg font-black text-white">{label}</h2>
  </div>
);

const Field = ({ label, value, sub }) => (
  <div className="flex items-center justify-between py-3 border-b border-slate-800 last:border-0">
    <span className="text-sm text-slate-400">{label}</span>
    <div className="text-right">
      <span className="text-sm font-semibold text-white">{value}</span>
      {sub && <p className="text-xs text-slate-500">{sub}</p>}
    </div>
  </div>
);

const StatusMsg = ({ msg }) => {
  if (!msg) return null;
  const isError = msg.type === 'error';
  return (
    <div className={`flex items-center gap-2 text-sm rounded-lg px-3 py-2 mt-3 ${
      isError ? 'bg-red-500/10 border border-red-500/30 text-red-400'
               : 'bg-green-500/10 border border-green-500/30 text-green-400'
    }`}>
      {isError ? <X className="w-4 h-4 shrink-0" /> : <Check className="w-4 h-4 shrink-0" />}
      {msg.text}
    </div>
  );
};


const AccountPage = ({ currentUser, onLogout, onUserUpdate }) => {
  const [account, setAccount] = useState(null);
  const [loading, setLoading] = useState(true);

  // Avatar
  const handleAvatarSaved = (newUrl) => {
    setAccount(a => ({ ...a, avatar_url: newUrl }));
    onUserUpdate({ ...currentUser, avatar_url: newUrl });
  };

  // Change username
  const [newUsername, setNewUsername] = useState('');
  const [usernameLoading, setUsernameLoading] = useState(false);
  const [usernameMsg, setUsernameMsg] = useState(null);

  // Change password
  const [passwords, setPasswords] = useState({ current: '', next: '', confirm: '' });
  const [passwordLoading, setPasswordLoading] = useState(false);
  const [passwordMsg, setPasswordMsg] = useState(null);

  // Delete account
  const [deleteStep, setDeleteStep] = useState(0); // 0=hidden, 1=confirm, 2=deleting
  const [deleteConfirm, setDeleteConfirm] = useState('');

  useEffect(() => {
    api.getAccount(currentUser.user_id)
      .then(data => { setAccount(data); setNewUsername(data.username); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [currentUser.user_id]);

  const handleChangeUsername = async (e) => {
    e.preventDefault();
    if (newUsername === account.username) { setUsernameMsg({ type: 'error', text: 'That is already your username.' }); return; }
    setUsernameLoading(true);
    setUsernameMsg(null);
    try {
      const res = await api.changeUsername(currentUser.user_id, newUsername);
      setAccount(a => ({ ...a, username: res.username }));
      onUserUpdate({ ...currentUser, username: res.username });
      setUsernameMsg({ type: 'ok', text: 'Username updated!' });
    } catch (err) {
      setUsernameMsg({ type: 'error', text: err.response?.data?.detail || 'Could not update username.' });
    } finally {
      setUsernameLoading(false);
    }
  };

  const handleChangePassword = async (e) => {
    e.preventDefault();
    if (passwords.next !== passwords.confirm) { setPasswordMsg({ type: 'error', text: 'New passwords do not match.' }); return; }
    setPasswordLoading(true);
    setPasswordMsg(null);
    try {
      await api.changePassword(currentUser.user_id, passwords.current, passwords.next);
      setPasswords({ current: '', next: '', confirm: '' });
      setPasswordMsg({ type: 'ok', text: 'Password updated!' });
    } catch (err) {
      setPasswordMsg({ type: 'error', text: err.response?.data?.detail || 'Could not update password.' });
    } finally {
      setPasswordLoading(false);
    }
  };

  const handleDeleteAccount = async () => {
    if (deleteConfirm !== account.username) { return; }
    setDeleteStep(2);
    try {
      await api.deleteAccount(currentUser.user_id);
      onLogout();
    } catch {
      setDeleteStep(1);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-orange-500 border-t-transparent" />
      </div>
    );
  }
  if (!account) return null;

  const memberSince = account.member_since
    ? new Date(account.member_since).toLocaleDateString('en-US', { year: 'numeric', month: 'long' })
    : 'Unknown';

  return (
    <div className="max-w-2xl mx-auto px-4 py-8 space-y-6">
      <h1 className="text-3xl font-black text-white">Account Settings</h1>

      {/* ── Profile Info ── */}
      <Card className="p-6">
        <SectionTitle icon={User} label="Profile" />
        <div className="flex items-center gap-4 mb-5 pb-5 border-b border-slate-800">
          <Avatar username={account.username} avatarUrl={account.avatar_url} size="lg" />
          <div>
            <p className="text-xl font-black text-white">{account.username}</p>
            <div className="flex items-center gap-2 mt-1">
              {account.login_method === 'google' ? (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-blue-500/20 border border-blue-500/30 text-blue-300 text-xs font-bold">
                  <svg className="w-3 h-3" viewBox="0 0 24 24"><path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/><path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/><path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/><path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/></svg>
                  Google account
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-slate-700/50 border border-slate-600/50 text-slate-300 text-xs font-bold">
                  <Key className="w-3 h-3" /> Email / Password
                </span>
              )}
              {account.role === 'admin' && (
                <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-orange-500/20 border border-orange-500/30 text-orange-400 text-xs font-black">
                  <Shield className="w-3 h-3" /> Admin
                </span>
              )}
            </div>
          </div>
        </div>
        <Field label="Email" value={account.email} />
        <Field label="Member since" value={memberSince} />
        <Field label="Total points" value={`${account.points} pts`} sub={`Rank #${account.rank}`} />

        {/* ── Avatar Upload ── */}
        <div className="mt-5 pt-5 border-t border-slate-800">
          <p className="text-sm font-black text-white mb-3 flex items-center gap-2">
            <Camera className="w-4 h-4 text-orange-400" /> Profile Photo
          </p>
          <AvatarUpload
            userId={currentUser.user_id}
            currentAvatarUrl={account.avatar_url}
            onSaved={handleAvatarSaved}
          />
        </div>
      </Card>

      {/* ── Change Username ── */}
      <Card className="p-6">
        <SectionTitle icon={User} label="Change Username" />
        <form onSubmit={handleChangeUsername} className="space-y-3">
          <input
            type="text"
            value={newUsername}
            onChange={e => setNewUsername(e.target.value)}
            placeholder="New username"
            minLength={3}
            pattern="[a-zA-Z0-9_]+"
            title="Letters, numbers and underscores only"
            className="w-full px-4 py-3 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-orange-500"
            required
          />
          <StatusMsg msg={usernameMsg} />
          <button
            type="submit"
            disabled={usernameLoading || !newUsername || newUsername === account.username}
            className="px-6 py-2.5 rounded-lg bg-orange-500 hover:bg-orange-600 text-white font-bold text-sm disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
          >
            {usernameLoading && <Loader className="w-4 h-4 animate-spin" />}
            Save Username
          </button>
        </form>
      </Card>

      {/* ── Change Password (only for email/password accounts) ── */}
      {account.login_method === 'password' && (
        <Card className="p-6">
          <SectionTitle icon={Key} label="Change Password" />
          <form onSubmit={handleChangePassword} className="space-y-3">
            <input
              type="password"
              value={passwords.current}
              onChange={e => setPasswords(p => ({ ...p, current: e.target.value }))}
              placeholder="Current password"
              className="w-full px-4 py-3 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-orange-500"
              required
            />
            <input
              type="password"
              value={passwords.next}
              onChange={e => setPasswords(p => ({ ...p, next: e.target.value }))}
              placeholder="New password"
              minLength={4}
              className="w-full px-4 py-3 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-orange-500"
              required
            />
            <input
              type="password"
              value={passwords.confirm}
              onChange={e => setPasswords(p => ({ ...p, confirm: e.target.value }))}
              placeholder="Confirm new password"
              className="w-full px-4 py-3 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-orange-500"
              required
            />
            <StatusMsg msg={passwordMsg} />
            <button
              type="submit"
              disabled={passwordLoading}
              className="px-6 py-2.5 rounded-lg bg-orange-500 hover:bg-orange-600 text-white font-bold text-sm disabled:opacity-50 transition-colors flex items-center gap-2"
            >
              {passwordLoading && <Loader className="w-4 h-4 animate-spin" />}
              Update Password
            </button>
          </form>
        </Card>
      )}

      {account.login_method === 'google' && (
        <Card className="p-6">
          <SectionTitle icon={Key} label="Password" />
          <p className="text-slate-400 text-sm">
            Your account uses Google sign-in — no password to manage.
          </p>
        </Card>
      )}

      {/* ── Danger Zone ── */}
      <Card className="p-6 border-red-900/40">
        <SectionTitle icon={AlertTriangle} label="Danger Zone" color="text-red-400" />
        {deleteStep === 0 && (
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold text-white">Delete Account</p>
              <p className="text-xs text-slate-500 mt-0.5">Permanently delete your account and all predictions.</p>
            </div>
            <button
              onClick={() => setDeleteStep(1)}
              className="px-4 py-2 rounded-lg border border-red-700 text-red-400 text-sm font-bold hover:bg-red-900/30 transition-colors"
            >
              Delete
            </button>
          </div>
        )}

        {deleteStep === 1 && (
          <div className="space-y-3">
            <p className="text-sm text-red-300 font-semibold">
              This cannot be undone. Type your username <span className="font-black text-white">{account.username}</span> to confirm.
            </p>
            <input
              type="text"
              value={deleteConfirm}
              onChange={e => setDeleteConfirm(e.target.value)}
              placeholder={`Type "${account.username}" to confirm`}
              className="w-full px-4 py-3 bg-slate-800 border border-red-800/60 rounded-lg text-white focus:outline-none focus:border-red-500"
            />
            <div className="flex gap-3">
              <button
                onClick={handleDeleteAccount}
                disabled={deleteConfirm !== account.username}
                className="px-6 py-2.5 rounded-lg bg-red-600 hover:bg-red-700 text-white font-black text-sm disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Yes, delete my account
              </button>
              <button
                onClick={() => { setDeleteStep(0); setDeleteConfirm(''); }}
                className="px-6 py-2.5 rounded-lg border border-slate-700 text-slate-300 text-sm font-bold hover:bg-slate-800 transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {deleteStep === 2 && (
          <div className="flex items-center gap-3 text-slate-400">
            <Loader className="w-5 h-5 animate-spin" /> Deleting account…
          </div>
        )}
      </Card>
    </div>
  );
};

export default AccountPage;
