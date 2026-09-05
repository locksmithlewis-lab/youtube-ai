// Rolixa YouTube publish + scheduling bridge. Uses the signed-in browser session; no secrets client-side.
import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';
const supabase=createClient('https://uqmnpeovwfzizajheuig.supabase.co','sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap');
const workspace=document.getElementById('projectWorkspace'); let timer=null,rendering=false;
function selectedProjectId(){return document.querySelector('.project-button.selected')?.dataset.openProject||null;}
function fmt(value){if(!value)return '';return new Date(value).toLocaleString(undefined,{weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});}
function statusLine(text){const p=document.createElement('p');p.className='status-line';p.textContent=text;return p;}
function youtubeLink(id){return /^[A-Za-z0-9_-]{6,32}$/.test(String(id||''))?`https://www.youtube.com/watch?v=${id}`:null;}
async function latestVideo(projectId){const {data}=await supabase.from('analytics_snapshots').select('youtube_video_id').eq('project_id',projectId).not('youtube_video_id','is',null).order('captured_at',{ascending:false}).limit(1).maybeSingle();return data?.youtube_video_id||null;}
function refreshSoon(){clearTimeout(timer);timer=setTimeout(refreshPanel,100);}
async function sendPublish(projectId,publishAt,status,button){
  button.disabled=true; status.textContent=publishAt?'Uploading to YouTube and setting release time…':'Uploading finished MP4 to YouTube as Private…';
  try{
    const {data:{session}}=await supabase.auth.getSession(); if(!session?.access_token)throw new Error('Your Rolixa session expired. Sign in again.');
    const response=await fetch('/api/youtube-publish',{method:'POST',headers:{Authorization:`Bearer ${session.access_token}`,'Content-Type':'application/json'},body:JSON.stringify({projectId,privacyStatus:'private',publishAt:publishAt||null,description:'Created with Rolixa. Original script, graphics, narration, and edit.'})});
    const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body.error||`YouTube upload failed (${response.status}).`);
    status.textContent=body.publishAt?`Scheduled. YouTube will make it public ${fmt(body.publishAt)}.`:'Private upload confirmed by YouTube.';
    const url=youtubeLink(body.videoId)||body.url;if(url){const a=document.createElement('a');a.href=url;a.target='_blank';a.rel='noopener';a.className='ghost compact';a.textContent='Open on YouTube';status.parentElement.appendChild(a);} button.remove();setTimeout(()=>location.reload(),1600);
  }catch(e){status.textContent=e?.message||'YouTube upload failed.';button.disabled=false;}
}
async function refreshPanel(){
  if(!workspace||rendering)return;const projectId=selectedProjectId();if(!projectId)return;rendering=true;
  try{
    const {data:p}=await supabase.from('video_projects').select('id,title,status,output_url,scheduled_publish_at,published_at').eq('id',projectId).maybeSingle();if(!p)return;
    document.getElementById('youtubePublishPanel')?.remove();const panel=document.createElement('section');panel.id='youtubePublishPanel';panel.className='work-card wide-card';
    panel.innerHTML='<div class="eyebrow">YOUTUBE PUBLISH</div><h3>Release timing</h3>';
    if(p.status==='scheduled'&&p.scheduled_publish_at){panel.appendChild(statusLine(`Scheduled to post ${fmt(p.scheduled_publish_at)}. YouTube already has the video and will release it automatically.`));const id=await latestVideo(projectId),url=youtubeLink(id);if(url){const a=document.createElement('a');a.href=url;a.target='_blank';a.rel='noopener';a.className='ghost compact';a.textContent='Open scheduled video';panel.appendChild(a);}}
    else if(p.status==='posted'){panel.appendChild(statusLine(`Posted${p.published_at?` ${fmt(p.published_at)}`:''}.`));const id=await latestVideo(projectId),url=youtubeLink(id);if(url){const a=document.createElement('a');a.href=url;a.target='_blank';a.rel='noopener';a.className='primary compact';a.textContent='Open video on YouTube';panel.appendChild(a);}}
    else if(p.status==='ready'&&p.output_url){
      const copy=document.createElement('p');copy.className='muted small';copy.textContent='Upload privately now, or choose exactly when YouTube should make it public.';panel.appendChild(copy);
      const nowBtn=document.createElement('button');nowBtn.type='button';nowBtn.className='ghost compact';nowBtn.textContent='Upload privately now';panel.appendChild(nowBtn);
      const label=document.createElement('label');label.className='field-label';label.textContent='Schedule public release';const input=document.createElement('input');input.type='datetime-local';input.min=new Date(Date.now()+5*60000-new Date().getTimezoneOffset()*60000).toISOString().slice(0,16);label.appendChild(input);panel.appendChild(label);
      const scheduleBtn=document.createElement('button');scheduleBtn.type='button';scheduleBtn.className='primary compact';scheduleBtn.textContent='Schedule on YouTube';panel.appendChild(scheduleBtn);const st=statusLine('Ready to upload or schedule.');panel.appendChild(st);
      nowBtn.onclick=()=>sendPublish(projectId,null,st,nowBtn);scheduleBtn.onclick=()=>{if(!input.value){st.textContent='Choose a posting date and time first.';return;}const iso=new Date(input.value).toISOString();sendPublish(projectId,iso,st,scheduleBtn);};
    } else panel.appendChild(statusLine(`Project is ${p.status}. It must pass quality review before publishing can be scheduled.`));
    (workspace.querySelector('.work-grid')||workspace).appendChild(panel);
  }finally{rendering=false;}
}
if(workspace){new MutationObserver(refreshSoon).observe(workspace,{childList:true,subtree:true});document.addEventListener('click',e=>{if(e.target.closest('[data-open-project]'))refreshSoon();});refreshSoon();}
