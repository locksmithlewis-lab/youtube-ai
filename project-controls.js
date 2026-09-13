import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';
const sb=createClient('https://uqmnpeovwfzizajheuig.supabase.co','sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap');
const workspace=document.getElementById('projectWorkspace');
const videosView=document.getElementById('videos');
const currentId=()=>document.querySelector('[data-open-project].selected')?.dataset.openProject||'';
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
document.addEventListener('click',event=>{if(event.target.closest('[data-cancel-render]'))sendAction('cancel');if(event.target.closest('[data-remove-project]'))sendAction('delete');if(event.target.closest('[data-clear-failed]'))clearFailed();if(event.target.closest('[data-process-now]'))processNow();setTimeout(addControls,50);});
new MutationObserver(()=>{addControls();addPageControls();}).observe(document.body,{childList:true,subtree:true}); addControls();addPageControls();
