// Never cache authenticated requests, API responses, profile data, or measurements.
const CACHE='betterme-shell-574f679b64c4';
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(['/logo.svg','/icon-192.png']))));
self.addEventListener('message',event=>{if(event.data==='SKIP_WAITING')self.skipWaiting()});
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key!==CACHE).map(key=>caches.delete(key)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{
 const url=new URL(event.request.url);
 if(event.request.method!=='GET'||url.origin!==self.location.origin||url.pathname.startsWith('/api/')||url.pathname.startsWith('/admin/'))return;
 if(event.request.mode==='navigate')event.respondWith(fetch(event.request).catch(()=>new Response('<h1>BetterMe is offline</h1><p>Reconnect to securely view your account or log an activity.</p>',{headers:{'Content-Type':'text/html'}})));
 else if(['/logo.svg','/icon-192.png'].includes(url.pathname))event.respondWith(caches.match(event.request).then(cached=>cached||fetch(event.request)));
});
