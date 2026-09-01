import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';

const supabaseUrl = 'https://uqmnpeovwfzizajheuig.supabase.co';
const supabaseKey = 'sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap';
const supabase = createClient(supabaseUrl, supabaseKey);

const $ = (id) => document.getElementById(id);
const authPanel = $('authPanel');
const appContent = $('appContent');
const signOutBtn = $('signOutBtn');
const connectionBadge = $('connectionBadge');
let currentUser = null;

function setView(name){
  document.querySelectorAll('.view').forEach(v=>v.classList.remove('active-view'));
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.view===name));
  $(name)?.classList.add('active-view');
}

document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>setView(btn.dataset.view)));
document.querySelectorAll('[data-go]').forEach(btn=>btn.addEventListener('click',()=>setView(btn.dataset.go)));

async function refreshData(){
  if(!currentUser) return;
  connectionBadge.textContent='Supabase connected';

  const [{data:projects,error:projectError},{data:yt,error:ytError},{data:analytics,error:analyticsError}] = await Promise.all([
    supabase.from('video_projects').select('*').order('created_at',{ascending:false}),
    supabase.from('youtube_connections').select('*').maybeSingle(),
    supabase.from('analytics_snapshots').select('*').order('captured_at',{ascending:false}).limit(20)
  ]);

  if(projectError){ connectionBadge.textContent='Backend read error'; console.error(projectError); return; }

  const items = projects || [];
  $('projectCount').textContent=items.length;
  $('readyCount').textContent=items.filter(p=>p.status==='ready').length;
  $('postedCount').textContent=items.filter(p=>p.status==='posted').length;
  $('failedCount').textContent=items.filter(p=>p.status==='failed').length;

  const renderProject = p => `<div class="project-row"><div class="project-title">${escapeHtml(p.title)}</div><div class="project-meta">${escapeHtml(p.topic||'No topic yet')} · ${escapeHtml(p.format||'Unspecified')} · ${escapeHtml(p.style||'Unspecified')}</div><span class="status-pill">${escapeHtml(p.status)}</span>${p.failure_reason?`<div class="project-meta">Failure: ${escapeHtml(p.failure_reason)}</div>`:''}</div>`;
  $('recentProjects').innerHTML = items.length ? items.slice(0,4).map(renderProject).join('') : 'No projects yet.';
  $('projectList').innerHTML = items.length ? items.map(renderProject).join('') : 'No projects yet.';

  if(ytError){
    $('youtubeStatus').textContent='Could not read YouTube connection state.';
  } else if(!yt || yt.status!=='connected'){
    $('youtubeStatus').textContent='Not connected.';
    $('connectYouTubeBtn').textContent='Connect YouTube';
  } else {
    $('youtubeStatus').innerHTML=`Connected to <strong>${escapeHtml(yt.channel_title||yt.channel_id||'YouTube channel')}</strong>. Last sync: ${yt.last_sync_at?new Date(yt.last_sync_at).toLocaleString():'not synced yet'}.`;
    $('connectYouTubeBtn').textContent='Reconnect YouTube';
  }

  if(analyticsError){
    $('analyticsList').textContent='Could not read analytics snapshots.';
  } else if(!analytics?.length){
    $('analyticsList').textContent='No analytics snapshots yet.';
  } else {
    $('analyticsList').innerHTML=analytics.map(a=>`<div class="project-row"><div><div class="project-title">${escapeHtml(a.youtube_video_id||'Channel snapshot')}</div><div class="project-meta">Captured ${new Date(a.captured_at).toLocaleString()}</div></div><div>Views: ${a.views ?? '—'}</div><div>Avg duration: ${a.average_view_duration_seconds ?? '—'}s</div></div>`).join('');
  }
}

function escapeHtml(value){return String(value).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}

async function applySession(session){
  currentUser=session?.user||null;
  authPanel.classList.toggle('hidden',!!currentUser);
  appContent.classList.toggle('hidden',!currentUser);
  signOutBtn.classList.toggle('hidden',!currentUser);
  if(currentUser) await refreshData(); else connectionBadge.textContent='Supabase ready';
}

$('authForm').addEventListener('submit',async e=>{
  e.preventDefault();
  $('authMessage').textContent='Sending secure link…';
  const email=$('emailInput').value.trim();
  const {error}=await supabase.auth.signInWithOtp({email,options:{emailRedirectTo:window.location.origin}});
  $('authMessage').textContent=error?error.message:'Check your email for the sign-in link.';
});

$('connectYouTubeBtn').addEventListener('click', async ()=>{
  $('youtubeMessage').textContent='Starting secure YouTube connection…';
  const {data:{session}}=await supabase.auth.getSession();
  if(!session?.access_token){
    $('youtubeMessage').textContent='Sign in to the app first.';
    return;
  }
  try{
    const response=await fetch('/api/youtube-start',{
      method:'POST',
      headers:{Authorization:`Bearer ${session.access_token}`}
    });
    const body=await response.json().catch(()=>({}));
    if(!response.ok || !body.url){
      $('youtubeMessage').textContent=body.error||'YouTube OAuth is not configured yet.';
      return;
    }
    window.location.assign(body.url);
  }catch(error){
    $('youtubeMessage').textContent='Could not start YouTube connection.';
    console.error(error);
  }
});

signOutBtn.addEventListener('click',async()=>{await supabase.auth.signOut();});
$('refreshBtn').addEventListener('click',refreshData);

$('projectForm').addEventListener('submit',async e=>{
  e.preventDefault();
  if(!currentUser) return;
  $('projectMessage').textContent='Creating draft…';
  const duration=Number($('durationInput').value)||null;
  const payload={
    user_id:currentUser.id,
    title:$('titleInput').value.trim(),
    topic:$('topicInput').value.trim()||null,
    format:$('formatInput').value,
    style:$('styleInput').value,
    target_duration_seconds:duration,
    status:'draft'
  };
  const {error}=await supabase.from('video_projects').insert(payload);
  if(error){ $('projectMessage').textContent=`Could not create draft: ${error.message}`; return; }
  $('projectMessage').textContent='Draft created in Supabase.';
  e.target.reset();
  $('durationInput').value='45';
  await refreshData();
  setView('videos');
});

const params=new URLSearchParams(window.location.search);
if(params.get('youtube')==='connected'){
  $('youtubeMessage').textContent='YouTube connected successfully.';
  history.replaceState({},'',window.location.pathname);
}else if(params.get('youtube')==='denied'){
  $('youtubeMessage').textContent='YouTube connection was cancelled.';
  history.replaceState({},'',window.location.pathname);
}

supabase.auth.onAuthStateChange((_event,session)=>applySession(session));
const {data:{session}}=await supabase.auth.getSession();
await applySession(session);
