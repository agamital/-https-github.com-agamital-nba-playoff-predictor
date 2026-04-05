// ── OneSignal safety wrapper ──────────────────────────────────────────────────
// All OneSignal access must go through this module.
// Every function is wrapped in try/catch — the rest of the app must never
// crash because of a push-notification failure.

/**
 * Returns the live OneSignal SDK object, or null if unavailable.
 * Guards against: server-side rendering, CDN not loaded, SDK still an array
 * (intermediate deferred state), or any init failure.
 */
export function getOneSignal() {
  try {
    if (typeof window === 'undefined') return null;
    const sdk = window.OneSignal;
    if (!sdk || Array.isArray(sdk)) return null;
    return sdk;
  } catch {
    return null;
  }
}

/**
 * Returns true only when the SDK is fully initialised and the device has
 * a permanent (non-temporary) onesignalId on OneSignal's servers.
 * A "local-…" prefix means the device hasn't registered yet; calling
 * login() at that point triggers the 400 race condition.
 */
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function isSDKReady() {
  try {
    const sdk = getOneSignal();
    if (!sdk) return false;
    const oid = sdk.User?.onesignalId ?? '';
    return UUID_V4.test(oid);
  } catch {
    return false;
  }
}

/**
 * Returns the current push subscription opted-in state.
 * Falls back to the localStorage persisted value so the UI shows the
 * correct toggle state immediately on mount, before the SDK responds.
 */
export function getOptedIn() {
  try {
    const sdk = getOneSignal();
    if (sdk) {
      return sdk.User?.PushSubscription?.optedIn ?? false;
    }
  } catch { /* fall through */ }
  // Fallback: last known state written by the toggle handler
  return localStorage.getItem('os_push_opted_in') === 'true';
}

/**
 * Opt the current device into push notifications.
 * Returns the final optedIn state (boolean).
 */
export async function optIn() {
  try {
    const sdk = getOneSignal();
    if (!sdk) return false;
    await sdk.User.PushSubscription.optIn();
    await new Promise(r => setTimeout(r, 300)); // let SDK settle
    const after = sdk.User?.PushSubscription?.optedIn ?? false;
    localStorage.setItem('os_push_opted_in', String(after));
    return after;
  } catch (err) {
    console.warn('[OneSignal] optIn() failed (non-fatal):', err?.message ?? err);
    return false;
  }
}

/**
 * Opt the current device out of push notifications.
 * Returns the final optedIn state (boolean — should be false).
 */
export async function optOut() {
  try {
    const sdk = getOneSignal();
    if (!sdk) return false;
    await sdk.User.PushSubscription.optOut();
    await new Promise(r => setTimeout(r, 300));
    const after = sdk.User?.PushSubscription?.optedIn ?? false;
    localStorage.setItem('os_push_opted_in', String(after));
    return after;
  } catch (err) {
    console.warn('[OneSignal] optOut() failed (non-fatal):', err?.message ?? err);
    return false;
  }
}

/**
 * Register a callback that fires whenever the subscription state changes.
 * Returns an unsubscribe function.
 */
export function onSubscriptionChange(callback) {
  try {
    const sdk = getOneSignal();
    if (!sdk) return () => {};
    sdk.User.PushSubscription.addEventListener('change', callback);
    return () => {
      try { sdk.User.PushSubscription.removeEventListener('change', callback); } catch {}
    };
  } catch {
    return () => {};
  }
}

/**
 * Clears all OneSignal operation-queue entries from localStorage so that
 * a stuck 400-retry loop doesn't survive a page reload.
 * Safe to call even when OneSignal is disabled.
 */
export function clearStaleOSOperations() {
  try {
    const toRemove = Object.keys(localStorage).filter(k =>
      k.startsWith('onesignal-') || k === 'ONE_SIGNAL_SDK_DB'
    );
    toRemove.forEach(k => localStorage.removeItem(k));
    if (toRemove.length) console.log('[OneSignal] cleared stale operation keys:', toRemove);
  } catch { /* non-fatal */ }
}
