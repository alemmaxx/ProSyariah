// Pekerja servis ringkas: membolehkan "Pasang app". Sentiasa ambil dari rangkaian supaya data sentiasa terkini;
// guna salinan simpanan hanya jika tiada internet.
const C='prosyariah-v1';
self.addEventListener('install',e=>{self.skipWaiting();e.waitUntil(caches.open(C).then(c=>c.addAll(['./','./index.html','./icons/icon-192.png'])).catch(()=>{}));});
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('fetch',e=>{if(e.request.method!=='GET')return;
  e.respondWith(fetch(e.request).then(r=>{if(r.ok&&new URL(e.request.url).origin===location.origin){const cp=r.clone();caches.open(C).then(c=>c.put(e.request,cp));}return r;})
    .catch(()=>caches.match(e.request)));});
