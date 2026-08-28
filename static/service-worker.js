const STATIC_CACHE = "raumradar-static-v2";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
    let data = {};
    try {
        data = event.data ? event.data.json() : {};
    } catch {
        data = { body: event.data?.text() || "Neue Nachricht von RaumRadar" };
    }

    event.waitUntil(
        self.registration.showNotification(data.title || "RaumRadar", {
            body: data.body || "Es gibt neue Informationen.",
            icon: "/static/icon.svg",
            badge: "/static/icon.svg",
            data: { url: data.url || "/" },
        })
    );
});

self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    const targetUrl = new URL(event.notification.data?.url || "/", self.location.origin).href;
    event.waitUntil(
        self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
            const existingClient = clients.find((client) => client.url === targetUrl);
            if (existingClient) {
                return existingClient.focus();
            }
            return self.clients.openWindow(targetUrl);
        })
    );
});

self.addEventListener("fetch", (event) => {
    if (event.request.method !== "GET") {
        return;
    }

    const requestUrl = new URL(event.request.url);
    if (requestUrl.origin !== self.location.origin || !requestUrl.pathname.startsWith("/static/")) {
        return;
    }

    event.respondWith(
        caches.open(STATIC_CACHE).then(async (cache) => {
            const cachedResponse = await cache.match(event.request);
            if (cachedResponse) {
                return cachedResponse;
            }

            const response = await fetch(event.request);
            if (response.ok) {
                await cache.put(event.request, response.clone());
            }
            return response;
        })
    );
});
