// Pekerja servis ProSyariah: "Pasang app", simpanan luar talian, notifikasi & semakan latar Robot Manual.
const C='prosyariah-v1';
self.addEventListener('install',e=>{self.skipWaiting();e.waitUntil(caches.open(C).then(c=>c.addAll(['./','./index.html','./icons/icon-192.png'])).catch(()=>{}));});
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('fetch',e=>{if(e.request.method!=='GET')return;
  e.respondWith(fetch(e.request).then(r=>{if(r.ok&&new URL(e.request.url).origin===location.origin){const cp=r.clone();caches.open(C).then(c=>c.put(e.request,cp));}return r;})
    .catch(()=>caches.match(e.request)));});

// Notifikasi push dari server (Firebase Cloud Messaging) — dihantar oleh robot GitHub
self.addEventListener('push',e=>{let d={};try{d=e.data?e.data.json():{};}catch(x){}
  const n=d.notification||{},x=d.data||{};const title=x.title||n.title||'ProSyariah';
  e.waitUntil(self.registration.showNotification(title,{body:x.body||n.body||'',tag:x.tag||undefined,icon:'icons/icon-192.png',badge:'icons/icon-192.png',data:{url:/^(man:|week:)/.test(x.tag||'')?'./#robot':'./'}}));});

// Tekan notifikasi → buka app di tab Robot
self.addEventListener('notificationclick',e=>{e.notification.close();
  e.waitUntil(self.clients.matchAll({type:'window',includeUncontrolled:true}).then(ws=>{
    const u=(e.notification.data&&e.notification.data.url)||'./';for(const w of ws){if('focus' in w){if(u.includes('#robot'))w.postMessage({go:'robot'});return w.focus();}}
    return self.clients.openWindow((e.notification.data&&e.notification.data.url)||'./');}));});

// Semakan latar (Chrome Android, app dipasang): semak harga terkini untuk Robot Manual
self.addEventListener('periodicsync',e=>{if(e.tag==='robot-check')e.waitUntil(robotCheck());});
async function robotCheck(){
  const c=await caches.open('prosyariah-state');const r=await c.match('./__robot.json');if(!r)return;
  const st=await r.json();if(!st.on||!st.open||!st.open.length)return;
  let M;try{M=await (await fetch('./data/market.json?t='+Date.now(),{cache:'no-store'})).json();}catch(e){return;}
  const asof=M.meta.asof,en=st.lang==='en',sent=st.sent||{};const f=x=>(+x).toFixed(3);
  for(const p of st.open){const v=M.stocks[p.code];if(!v||v.c==null)continue;const now=v.c;let id=null,t,b;
    const pl=((now/p.en-1-0.003)*p.stake).toFixed(2);
    if(now>=p.tg){id='man:'+p.id+':W';t=en?`${p.name}: reached upper level, time to close (sell)`:`${p.name}: sampai paras atas, masa tutup (jual)`;b=(en?'Price ':'Harga ')+f(now)+' ≥ '+f(p.tg)+` · RM ${pl}`;}
    else if(now<=p.sl){id='man:'+p.id+':L';t=en?`${p.name}: hit cut loss, force close`:`${p.name}: kena cut loss, force close`;b=(en?'Price ':'Harga ')+f(now)+' ≤ '+f(p.sl)+` · RM ${pl}`;}
    else if(asof>=p.last){id='man:'+p.id+':T';t=en?`${p.name}: closing date reached`:`${p.name}: tarikh tutup sudah sampai`;b=`RM ${pl}`;}
    else if(asof>=p.pre){id='man:'+p.id+':E';t=en?`${p.name}: closes tomorrow (latest closing date)`:`${p.name}: tutup esok (tarikh tutup paling lewat)`;b=`RM ${pl}`;}
    else if(p.mdEnd&&asof>=p.mdEnd){id='man:'+p.id+':D';t=en?`${p.name}: typical period has ended`:`${p.name}: tempoh biasa sudah tamat`;b=`RM ${pl}`;}
    if(id&&!sent[id]){await self.registration.showNotification(t,{body:b,tag:id,icon:'icons/icon-192.png',badge:'icons/icon-192.png',data:{url:'./#robot'}});sent[id]=1;}}
  st.sent=sent;await c.put('./__robot.json',new Response(JSON.stringify(st),{headers:{'Content-Type':'application/json'}}));
}
