// Web Push service worker. Deliberately minimal: this app has no offline
// story and no cache strategy to own -- the sole job here is turning a push
// message into an OS-level notification, and turning a click on that
// notification into a focused/opened tab on the run it's about.

self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    // A malformed or empty payload still deserves *a* notification rather
    // than none -- the fallback title/body below cover this.
  }

  const title = data.title || 'Analysis update';
  const url = data.url || '/';

  event.waitUntil(
    self.registration.showNotification(title, {
      body: data.body || '',
      // data.url is read back in notificationclick below -- Notification
      // objects don't otherwise carry app-specific navigation state.
      data: { url },
      tag: url, // a second notification for the same run replaces the first
                // instead of stacking, since only the latest state matters.
    }),
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = event.notification.data && event.notification.data.url ? event.notification.data.url : '/';

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      // Reuse an already-open tab on this run rather than opening a
      // duplicate -- most likely to be the exact tab that requested the
      // subscription in the first place.
      for (const client of clients) {
        if (client.url.endsWith(url) && 'focus' in client) {
          return client.focus();
        }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow(url);
      }
    }),
  );
});
