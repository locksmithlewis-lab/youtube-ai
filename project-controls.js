import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';
const sb=createClient('https://uqmnpeovwfzizajheuig.supabase.co','sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap');
const workspace=document.getElementById('projectWorkspace');
const currentId=()=>document.querySelector('[data-open-project].selected')?.dataset.openProject||'';
async function sendAction(action){
 const projectId=currentId(); if(!projectId)return;
 const warning=action==='delete'?'Permanently remove this project and its saved render?':'Stop this render?';
 if(!window.confirm(warning))return;
 const {data:{session}}=await sb.auth.getSession(); if(!session?.access_token){window.alert('Sign in first.');return;}
 const response=await fetch('/api/project-action',{method:'POST',headers:{Authorization:`Bearer ${session.access_token}`,'Content-Type':'application/json'},body:JSON.stringify({projectId,action})});
 const body=await response.json().catch(()=>({})); if(!response.ok){window.alert(body.error||'Action failed.');return;}
 window.alert(body.message||'Done.'); document.getElementById('refreshBtn')?.click();
}
function addControls(){
 if(!workspace||!currentId()||workspace.querySelector('[data-project-controls]'))return;
 const head=workspace.querySelector('.workspace-head'); if(!head)return;
 const controls=document.createElement('div'); controls.dataset.projectControls='true'; controls.className='inline-actions';
 controls.innerHTML='<button type="button" class="ghost compact" data-cancel-render>Cancel render</button><button type="button" class="ghost compact" data-remove-project>Delete permanently</button>';
 head.appendChild(controls);
}
document.addEventListener('click',event=>{if(event.target.closest('[data-cancel-render]'))sendAction('cancel');if(event.target.closest('[data-remove-project]'))sendAction('delete');setTimeout(addControls,50);});
new MutationObserver(addControls).observe(workspace,{childList:true,subtree:true}); addControls();
