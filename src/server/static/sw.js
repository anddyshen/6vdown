// 6vdown 轻量 Service Worker 缓存壳
self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  // 页面和 API 始终走最新网络
  event.respondWith(fetch(event.request));
});
