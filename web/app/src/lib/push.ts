'use client';

import { getVapidPublicKey, subscribeRun } from '@/lib/api-client/client';

export function isPushSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window
  );
}

// PushManager.subscribe's applicationServerKey wants a raw Uint8Array, not
// the URL-safe base64 string the backend (and the rest of the Push API)
// otherwise agree on -- standard boilerplate conversion, no library needed
// for one string.
function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4);
  const base64Safe = (base64 + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = atob(base64Safe);
  const bytes = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; i += 1) {
    bytes[i] = rawData.charCodeAt(i);
  }
  return bytes;
}

export class PushUnsupportedError extends Error {}
export class PushPermissionDeniedError extends Error {}
// Chrome/Edge raise this specific AbortError ("Registration failed - push
// service error") when the browser itself cannot reach its push service
// (Google FCM) to register the subscription -- confirmed live: it fires
// identically for a freshly-generated, spec-valid key pair with nothing to
// do with this app's own VAPID key, so it is never caused by anything this
// app controls. Typically a network/firewall/VPN blocking Chrome's push
// channel (a separate connection from normal HTTPS browsing, so the rest of
// the site working is not evidence against this). Distinguished from a
// generic failure so the message can say so instead of "try again," which
// would not help -- there is nothing to retry until the network allows it.
export class PushServiceUnreachableError extends Error {}

/**
 * Requests notification permission (if not already decided), registers the
 * service worker, subscribes to push, and registers the subscription with
 * the backend for this specific run.
 *
 * Throws PushUnsupportedError / PushPermissionDeniedError for those two
 * specific, expected failure modes so the caller can show a precise
 * message; any other failure (network, a 404 because the run just
 * finished) propagates as-is.
 */
export async function subscribeToRunNotifications(runId: string): Promise<void> {
  if (!isPushSupported()) {
    throw new PushUnsupportedError('Push notifications are not supported in this browser.');
  }

  let permission = Notification.permission;
  if (permission === 'default') {
    permission = await Notification.requestPermission();
  }
  if (permission !== 'granted') {
    throw new PushPermissionDeniedError('Notification permission was not granted.');
  }

  const registration = await navigator.serviceWorker.register('/sw.js');
  const publicKey = await getVapidPublicKey();
  let subscription;
  try {
    subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      // TS's DOM lib types applicationServerKey as BufferSource, which
      // excludes a Uint8Array backed by the (also spec-valid) ArrayBufferLike
      // union our helper's return type infers to on this TS/lib version --
      // the value itself is a real Uint8Array, exactly what the spec and
      // every browser expect.
      applicationServerKey: urlBase64ToUint8Array(publicKey) as BufferSource,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new PushServiceUnreachableError(
        "Your browser could not reach its push service. This is usually a network, firewall, or VPN blocking the connection -- not something this app controls.",
      );
    }
    throw err;
  }

  const json = subscription.toJSON();
  if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) {
    throw new Error('Browser returned an incomplete push subscription.');
  }

  await subscribeRun(runId, {
    endpoint: json.endpoint,
    keys: { p256dh: json.keys.p256dh, auth: json.keys.auth },
  });
}
