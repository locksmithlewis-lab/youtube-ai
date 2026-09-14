import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';

const sb=createClient('https://uqmnpeovwfzizajheuig.supabase.co','sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap');
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function ensurePanel(){
  const merch=document.querySelector('[data-bs-panel="merch"]');
  if(!merch)return null;
  let panel=document.getElementById('blackstarPrintify');
  if(panel)return panel;
  panel=document.createElement('section');
  panel.id='blackstarPrintify';
  panel.className='bs-card';
  panel.style.marginBottom='16px';
  panel.innerHTML='<div class="bs-meta">Printify store</div><h3>BigBng</h3><p class="muted">Checking secure server connection…</p>';
  merch.prepend(panel);
  return panel;
}

async function load(){
  const panel=ensurePanel();
  if(!panel)return false;
  const {data:{session}}=await sb.auth.getSession();
  if(!session?.access_token){
    panel.innerHTML='<div class="bs-meta">Printify store</div><h3>BigBng</h3><div class="bs-status"><span class="bs-dot"></span><strong>Sign in to verify connection</strong></div><p class="muted small">The Printify credential stays server-side and is never exposed in this page.</p>';
    return true;
  }
  try{
    const r=await fetch('/api/printify-store',{headers:{Authorization:`Bearer ${session.access_token}`},cache:'no-store'});
    const b=await r.json().catch(()=>({}));
    if(!r.ok||!b.connected){
      panel.innerHTML=`<div class="bs-meta">Printify store</div><h3>BigBng</h3><div class="bs-status"><span class="bs-dot"></span><strong>Connection incomplete</strong></div><p>${esc(b.error||'Could not verify Printify.')}</p><p class="muted small">Expected server secret: PRINTIFY_API_TOKEN. Required scopes: shops.read, products.read; add catalog.read, products.write and uploads.write when BLACKSTAR begins creating merchandise automatically.</p><button class="ghost compact" id="retryPrintify">Retry</button>`;
      document.getElementById('retryPrintify')?.addEventListener('click',load,{once:true});
      return true;
    }
    const products=b.products||[];
    panel.innerHTML=`<div class="section-head"><div><div class="bs-meta">Printify store · connected</div><h3>${esc(b.shop.title)}</h3></div><div class="bs-status"><span class="bs-dot ok"></span><strong>Live</strong></div></div><p class="muted small">Shop ID ${esc(b.shop.id)} · ${esc(b.shop.sales_channel||'disconnected sales channel')} · ${Number(b.productCount||products.length)} products</p><div class="bs-grid">${products.slice(0,12).map(p=>`<article class="bs-card"><div class="bs-meta">Printify product</div><h4>${esc(p.title)}</h4><p class="muted small">${p.variants} variants · ${p.visible?'visible':'not visible'}${p.locked?' · locked':''}</p></article>`).join('')||'<div class="empty">BigBng is connected but currently has no products.</div>'}</div>`;
    return true;
  }catch(e){
    panel.innerHTML=`<div class="bs-meta">Printify store</div><h3>BigBng</h3><div class="bs-status"><span class="bs-dot"></span><strong>Connection error</strong></div><p>${esc(e.message)}</p>`;
    return true;
  }
}

const observer=new MutationObserver(()=>{if(ensurePanel()){observer.disconnect();load();}});
observer.observe(document.body,{childList:true,subtree:true});
load();
