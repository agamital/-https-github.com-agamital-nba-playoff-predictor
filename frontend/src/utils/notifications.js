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
 * Links an external user ID (our app's user_id) to this device's OneSignal
 * subscription.  Only fires when all of the following are true:
 *   1. SDK is loaded and ready
 *   2. Notification permission is 'granted'
 *   3. Device is opted in (subscribed)
 *   4. onesignalId is a permanent UUID — not a 'local-…' temp ID
 *
 * Any 400/403 or other error from OneSignal's backend is caught here and
 * logged as a warning — it must never reach the React render path.
 */
export function loginUser(externalId) {
  if (!externalId) return;
  try {
    const sdk = getOneSignal();
    if (!sdk) return;

    // Require 'granted' permission — without it the device isn't registered
    const permission = sdk.Notifications?.permission ?? Notification?.permission ?? 'default';
    if (permission !== 'granted') return;

    if (!isSDKReady()) {
      console.log('[OneSignal] loginUser: onesignalId not yet permanent — skipping');
      return;
    }

    const optedIn = sdk.User?.PushSubscription?.optedIn ?? false;
    if (!optedIn) return;

    try {
      Promise.resolve(sdk.login(String(externalId))).catch((err) => {
        console.warn('[OneSignal] login() rejected (non-fatal):', err?.message ?? err);
      });
    } catch (inner) {
      console.warn('[OneSignal] login() threw (non-fatal):', inner?.message ?? inner);
    }
  } catch (err) {
    console.warn('[OneSignal] loginUser error (non-fatal):', err?.message ?? err);
  }
}

/**
 * Clears all OneSignal operation-queue entries from both localStorage AND
 * IndexedDB so that a stuck "Op failed, pausing" retry loop doesn't survive
 * a page reload.  OneSignal v16 moved its OperationRepo to IndexedDB
 * ("ONE_SIGNAL_SDK_DB"), so localStorage-only cleanup is insufficient.
 *
 * Only nukes storage when the device is in a "local-…" stuck state (no
 * permanent onesignalId), so valid subscriptions are never disturbed.
 *
 * Safe to call even when OneSignal is disabled.
 */
export async function clearStaleOSOperations() {
  try {
    // localStorage cleanup (v15 compat + stale keys)
    const toRemove = Object.keys(localStorage).filter(k =>
      k.startsWith('onesignal-') || k.startsWith('ONE_SIGNAL')
    );
    toRemove.forEach(k => localStorage.removeItem(k));
    if (toRemove.length) console.log('[OneSignal] cleared stale localStorage keys:', toRemove);
  } catch { /* non-fatal */ }

  // IndexedDB cleanup — only when device is stuck in "local-…" state
  try {
    const sdk = getOneSignal();
    const oid = sdk?.User?.onesignalId ?? '';
    const isStuck = !oid || oid.startsWith('local-');
    if (isStuck && 'indexedDB' in window) {
      // Delete the whole OneSignal IDB — it will be recreated cleanly on next init
      await new Promise((resolve) => {
        const req = indexedDB.deleteDatabase('ONE_SIGNAL_SDK_DB');
        req.onsuccess = () => { console.log('[OneSignal] cleared stuck IndexedDB'); resolve(); };
        req.onerror   = () => resolve();  // non-fatal
        req.onblocked = () => resolve();
      });
    }
  } catch { /* non-fatal */ }
}
