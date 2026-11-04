// v2: network-first for everything (HTML + data), cache only as offline fallback. Never serve stale data when online.
const C='siw-v2';
self.addEventListener('install',e=>{self.skipWaiting()});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(k=>Promise.all(k.filter(x=>x!==C).map(x=>caches.delete(x)))).then(()=>self.clients.claim()))});
self.addEventListener('fetch',e=>{if(e.request.method!=='GET'||new URL(e.request.url).origin!==location.origin)return;
 e.respondWith(fetch(e.request,{cache:'no-store'}).then(r=>{const cl=r.clone();caches.open(C).then(c=>c.put(e.request.url.split('?')[0],cl));return r}).catch(()=>caches.match(e.request.url.split('?')[0])))});
