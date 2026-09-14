import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';
const sb=createClient('https://uqmnpeovwfzizajheuig.supabase.co','sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap');
const workspace=document.getElementById('projectWorkspace');
const videosView=document.getElementById('videos');
const currentId=()=>document.querySelector('[data-open-project].selected')?.dataset.openProject||'';
const esc=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
async function session(){const {data}=await sb.auth.getSession();return data?.session||null;}
async function sendAction(action){
 const projectId=currentId(); if(!projectId)return;
 const warning=action==='delete'?'Permanently remove this project and its saved render?':'Stop this render?';
 if(!window.confirm(warning))return;
 const s=await session(); if(!s?.access_token){window.alert('Sign in first.');return;}
 const response=await fetch('/api/project-action',{method:'POST',headers:{Authorization:`Bearer ${s.access_token}`,'Content-Type':'application/json'},body:JSON.stringify({projectId,action})});
 const body=await response.json().catch(()=>({})); if(!response.ok){window.alert(body.error||'Action failed.');return;}
 window.alert(body.message||'Done.'); document.getElementById('refreshBtn')?.click();
}
async function clearFailed(){
 if(!window.confirm('Clear old failed projects from the dashboard? Only failed projects older than 24 hours, or failures that already exhausted automatic repair, will be removed. Posted, ready, scheduled, generating, and actively rendering projects are protected.'))return;
 const s=await session();if(!s?.access_token){window.alert('Sign in first.');return;}
 const btn=document.querySelector('[data-clear-failed]');if(btn)btn.disabled=true;
 try{const response=await fetch('/api/project-action',{method:'POST',headers:{Authorization:`Bearer ${s.access_token}`,'Content-Type':'application/json'},body:JSON.stringify({action:'delete_failed'})});const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body.error||'Cleanup failed.');window.alert(body.message||'Failed projects cleared.');document.getElementById('refreshBtn')?.click();}
 catch(e){window.alert(e.message||'Cleanup failed.');}
 finally{if(btn)btn.disabled=false;}
}
async function processNow(){
 const s=await session();if(!s?.access_token){window.alert('Sign in first.');return;}
 const btn=document.querySelector('[data-process-now]');if(btn)btn.disabled=true;
 try{const response=await fetch('/api/render-now',{method:'POST',headers:{Authorization:`Bearer ${s.access_token}`}});const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body.error||'Could not start render workers.');window.alert('Render workers requested. Existing queued/generating projects will move through QC; anything that reaches Ready is handled by the automatic publisher.');}
 catch(e){window.alert(e.message||'Could not start processing.');}
 finally{if(btn)btn.disabled=false;}
}
function addPageControls(){
 if(!videosView||videosView.querySelector('[data-dashboard-controls]'))return;
 const head=videosView.querySelector('.page-head');if(!head)return;
 const controls=document.createElement('div');controls.dataset.dashboardControls='true';controls.className='inline-actions';
 controls.innerHTML='<button type="button" class="primary compact" data-process-now>Process available now</button><button type="button" class="ghost compact" data-clear-failed>Clear old failed</button>';
 head.appendChild(controls);
}
function addControls(){
 if(!workspace||!currentId()||workspace.querySelector('[data-project-controls]'))return;
 const head=workspace.querySelector('.workspace-head'); if(!head)return;
 const controls=document.createElement('div'); controls.dataset.projectControls='true'; controls.className='inline-actions';
 controls.innerHTML='<button type="button" class="ghost compact" data-cancel-render>Cancel render</button><button type="button" class="ghost compact" data-remove-project>Delete permanently</button>';
 head.appendChild(controls);
}
function installMetricDrilldowns(){
 const pairs=[['postedCount','posted','Published videos'],['failedCount','failed','Failed videos']];
 for(const [id,status,label] of pairs){
  const count=document.getElementById(id);const card=count?.closest('.metric');if(!card||card.dataset.drilldownReady)return;
  card.dataset.drilldownReady='true';card.tabIndex=0;card.role='button';card.setAttribute('aria-label',`Open ${label.toLowerCase()}`);card.style.cursor='pointer';card.dataset.statusDrilldown=status;
 }
}
function ensureStatusDrawer(){
 let drawer=document.getElementById('statusDrilldownDrawer');if(drawer)return drawer;
 drawer=document.createElement('div');drawer.id='statusDrilldownDrawer';drawer.hidden=true;
 drawer.innerHTML='<div class="status-drilldown-backdrop" data-close-status-drawer></div><section class="status-drilldown-panel" role="dialog" aria-modal="true" aria-labelledby="statusDrilldownTitle"><div class="status-drilldown-head"><div><div class="eyebrow">VIDEO DETAILS</div><h2 id="statusDrilldownTitle">Videos</h2></div><button type="button" class="ghost compact" data-close-status-drawer>Close</button></div><div id="statusDrilldownList" class="status-drilldown-list"><div class="empty">Loading…</div></div></section>';
 const style=document.createElement('style');style.textContent=`#statusDrilldownDrawer{position:fixed;inset:0;z-index:1000}.status-drilldown-backdrop{position:absolute;inset:0;background:rgba(0,0,0,.68);backdrop-filter:blur(4px)}.status-drilldown-panel{position:absolute;right:0;top:0;height:100%;width:min(620px,96vw);overflow:auto;background:#0d1018;border-left:1px solid rgba(255,255,255,.12);padding:24px;box-shadow:-24px 0 70px rgba(0,0,0,.45)}.status-drilldown-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:22px}.status-drilldown-list{display:grid;gap:12px}.status-video-row{border:1px solid rgba(255,255,255,.11);border-radius:16px;padding:14px;background:rgba(255,255,255,.035)}.status-video-titlebox{width:100%;box-sizing:border-box;border:1px solid rgba(255,255,255,.13);border-radius:10px;background:#080a10;color:#fff;padding:12px 13px;font:inherit;font-weight:700;margin-bottom:10px}.status-video-meta{font-size:12px;opacity:.72;margin-bottom:10px}.status-video-error{font-size:12px;line-height:1.45;color:#ffb4b4;margin:8px 0 12px}.status-video-actions{display:flex;gap:8px;flex-wrap:wrap}`;document.head.appendChild(style);document.body.appendChild(drawer);return drawer;
}
async function openStatusDrawer(status){
 const drawer=ensureStatusDrawer();const title=document.getElementById('statusDrilldownTitle');const list=document.getElementById('statusDrilldownList');
 title.textContent=status==='posted'?'Published videos':'Failed videos';list.innerHTML='<div class="empty">Loading exact videos…</div>';drawer.hidden=false;
 const {data,error}=await sb.from('video_projects').select('id,title,topic,format,status,failure_reason,published_at,updated_at').eq('status',status).order(status==='posted'?'published_at':'updated_at',{ascending:false,nullsFirst:false}).limit(100);
 if(error){list.innerHTML=`<div class="empty">Could not load videos: ${esc(error.message)}</div>`;return;}
 if(!data?.length){list.innerHTML='<div class="empty">No videos in this status.</div>';return;}
 list.innerHTML=data.map(p=>`<article class="status-video-row"><input class="status-video-titlebox" type="text" readonly value="${esc(p.title||'Untitled video')}" aria-label="Exact video title"/><div class="status-video-meta">${esc(p.format||'Video')} · ${esc(p.status)}${p.published_at?` · ${new Date(p.published_at).toLocaleString()}`:''}</div>${p.failure_reason?`<div class="status-video-error">${esc(p.failure_reason)}</div>`:''}<div class="status-video-actions"><button type="button" class="primary compact" data-jump-project="${esc(p.id)}">Open video</button><button type="button" class="ghost compact" data-copy-title="${encodeURIComponent(p.title||'Untitled video')}">Copy title</button></div></article>`).join('');
}
function jumpToProject(id){
 document.querySelector('[data-close-status-drawer]')?.click();document.querySelector('.tab[data-view="videos"]')?.click();setTimeout(()=>document.querySelector(`[data-open-project="${CSS.escape(id)}"]`)?.click(),100);
}
document.addEventListener('click',event=>{
 if(event.target.closest('[data-cancel-render]'))sendAction('cancel');
 if(event.target.closest('[data-remove-project]'))sendAction('delete');
 if(event.target.closest('[data-clear-failed]'))clearFailed();
 if(event.target.closest('[data-process-now]'))processNow();
 const metric=event.target.closest('[data-status-drilldown]');if(metric)openStatusDrawer(metric.dataset.statusDrilldown);
 if(event.target.closest('[data-close-status-drawer]')){const drawer=document.getElementById('statusDrilldownDrawer');if(drawer)drawer.hidden=true;}
 const jump=event.target.closest('[data-jump-project]');if(jump)jumpToProject(jump.dataset.jumpProject);
 const copy=event.target.closest('[data-copy-title]');if(copy)navigator.clipboard?.writeText(decodeURIComponent(copy.dataset.copyTitle));
 setTimeout(addControls,50);
});
document.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){const metric=event.target.closest?.('[data-status-drilldown]');if(metric){event.preventDefault();openStatusDrawer(metric.dataset.statusDrilldown);}}if(event.key==='Escape'){const drawer=document.getElementById('statusDrilldownDrawer');if(drawer)drawer.hidden=true;}});
new MutationObserver(()=>{addControls();addPageControls();installMetricDrilldowns();}).observe(document.body,{childList:true,subtree:true});addControls();addPageControls();installMetricDrilldowns();
