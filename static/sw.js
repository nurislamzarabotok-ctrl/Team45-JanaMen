'use strict';
const CACHE='janamen-v1-5-iphone';
const PUBLIC=['/offline.html','/offline.css','/manifest.webmanifest','/assets/apple-touch-icon.png','/assets/icon-192.png','/assets/icon-512.png','/assets/icon-maskable.png','/assets/jana-logo.svg'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(PUBLIC))));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('janamen-')&&k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('message',e=>{if(e.data?.type==='SKIP_WAITING')self.skipWaiting();});
self.addEventListener('fetch',e=>{
 const u=new URL(e.request.url);
 if(u.origin!==location.origin||e.request.method!=='GET'||u.pathname.startsWith('/api/'))return;
 if(e.request.mode==='navigate'){
  if(self.navigator.onLine===false){e.respondWith(caches.match('/offline.html'));return;}
  e.respondWith(fetch(e.request,{cache:'no-store'}).catch(()=>caches.match('/offline.html')));return;
 }
 if(PUBLIC.includes(u.pathname))e.respondWith(fetch(e.request,{cache:'no-store'}).catch(()=>caches.match(e.request)));
});
// No API responses, cookies, chat, account data or offline action queue are cached.
