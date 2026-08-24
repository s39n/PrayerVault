// Service worker for the multi-church app: receives web-push messages and shows
// a notification. Registered by church.js with scope /church.
self.addEventListener("push", (event) => {
  let data = { title: "PrayerVault", body: "", url: "/church" };
  try { data = Object.assign(data, event.data ? event.data.json() : {}); }
  catch (e) { if (event.data) data.body = event.data.text(); }
  event.waitUntil(
    self.registration.showNotification(data.title || "PrayerVault", {
      body: data.body || "",
      icon: "/icon-192.png",
      badge: "/icon-192.png",
      data: { url: data.url || "/church" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/church";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      for (const w of wins) { if (w.url.includes("/church") && "focus" in w) return w.focus(); }
      return clients.openWindow(url);
    })
  );
});
