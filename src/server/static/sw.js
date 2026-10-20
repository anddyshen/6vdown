// 6vdown 轻量 Service Worker 缓存壳
const CACHE_NAME = '6vdown-shell-v1';
const ASSETS = [
  '/',
  '/manifest.json'
];

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  // 对 API 请求全部放行走网络，页面壳优先网络
  if (event.request.url.includes('/api/')) {
    return;
  }
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});
