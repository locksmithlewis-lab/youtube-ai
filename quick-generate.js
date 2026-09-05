import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';

const supabase = createClient('https://uqmnpeovwfzizajheuig.supabase.co','sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap');
const btn = document.getElementById('quickGenerateBtn');
const message = document.getElementById('quickGenerateMessage');

function cleanTitle(title){return String(title||'Trending topic').replace(/[\r\n]+/g,' ').trim().slice(0,120);}
function key(value){return cleanTitle(value).toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();}
function compactNumber(value){const n=Number(value||0);return n?new Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:1}).format(n):'';}
function escapeHtml(v){return String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}

function buildShort(trend){
  const topic=cleanTitle(trend.topic),views=Number(trend.evidence?.views||0),velocity=Number(trend.evidence?.views_per_hour||0),channel=String(trend.evidence?.channel||'a creator').trim();
  const hook=`Wait — ${topic} just exploded, and the numbers are wild.`;
  const proof=views?`${channel} is already at about ${compactNumber(views)} views${velocity?`, with roughly ${compactNumber(velocity)} more every hour`:''}.`:`It just broke into YouTube's most-popular feed.`;
  const script=[hook,proof,`That kind of jump doesn't happen quietly. Thousands of people are clicking, watching, and pushing this topic into more feeds right now.`,`The wild part is how quickly attention compounds. One strong moment pulls in the next viewer, then the next, until momentum starts feeding itself.`,`But viral speed can disappear just as quickly. The next few hours decide whether ${topic} keeps climbing or gets replaced by the next obsession.`,`So remember this name. If the momentum holds, you're watching the breakout happen in real time.`,`Would you keep watching — or scroll?`].join(' ');
  return {hook,script,title:`${topic}: the breakout happening right now`.slice(0,140),format:'Short',style:'Hype',duration:45};
}

function buildDocumentary(trend){
  const topic=cleanTitle(trend.topic),views=Number(trend.evidence?.views||0),channel=String(trend.evidence?.channel||'the source channel').trim(),published=trend.evidence?.published_at?new Date(trend.evidence.published_at).toLocaleDateString():null;
  const hook=`Something unusual is happening around ${topic}.`;
  const evidence=views?`At the latest Rolixa scan, the video from ${channel} had about ${compactNumber(views)} views${published?` after being published on ${published}`:''}.`:`It appeared in YouTube's most-popular feed during Rolixa's live scan.`;
  const script=[hook,evidence,`That number alone does not explain why people care, but it does tell us where the attention is concentrating right now.`,`The useful question is what changed: timing, audience interest, the people involved, or a moment that suddenly made the subject impossible to ignore.`,`This documentary chapter stays with what can actually be verified. The live trend signal proves the attention spike; deeper claims still need source-backed research before they are added.`,`What we can say now is simple: ${topic} has crossed from ordinary release into a measurable attention event, and the next wave of evidence will show whether that interest lasts.`].join(' ');
  return {hook,script,title:`Documentary: ${topic}`.slice(0,140),format:'Explainer',style:'Documentary',duration:90};
}

async function chooseNeverUsedTrend(trends,userId){
  const [{data:projects,error:pe},{data:sources,error:se}]=await Promise.all([supabase.from('video_projects').select('id,topic,title').eq('user_id',userId),supabase.from('research_sources').select('project_id,url').eq('user_id',userId)]);
  if(pe)throw pe;if(se)throw se;const usedTopics=new Set(),usedIds=new Set();
  for(const p of projects||[]){if(p.topic)usedTopics.add(key(p.topic));if(p.title)usedTopics.add(key(p.title));}
  for(const s of sources||[]){const m=String(s.url||'').match(/[?&]v=([A-Za-z0-9_-]{6,32})/);if(m)usedIds.add(m[1]);}
  return (trends||[]).find(t=>{const id=String(t.evidence?.video_id||'');return !(id&&usedIds.has(id))&&!usedTopics.has(key(t.topic));})||null;
}

async function generateTrendVideo(kind){
  const {data:{session}}=await supabase.auth.getSession();if(!session?.access_token)throw new Error('Sign in first.');
  const {data:{user}}=await supabase.auth.getUser();if(!user)throw new Error('Sign in first.');
  message.textContent='Finding a topic Rolixa has never used before…';
  const r=await fetch('/api/trends',{method:'POST',headers:{Authorization:`Bearer ${session.access_token}`}});const body=await r.json().catch(()=>({}));if(!r.ok)throw new Error(body.error||'Could not read live trends.');
  const trend=await chooseNeverUsedTrend(body.trends||[],user.id);if(!trend)throw new Error('No unused live trend is available right now. Rolixa will not repeat an old video automatically.');
  const g=kind==='documentary'?buildDocumentary(trend):buildShort(trend);message.textContent='Writing it and queuing the render…';
  const {data:project,error}=await supabase.from('video_projects').insert({user_id:user.id,title:g.title,topic:cleanTitle(trend.topic),format:g.format,style:g.style,target_duration_seconds:g.duration,status:'generating',hook:g.hook,script:g.script}).select().single();if(error)throw error;
  await supabase.from('project_pipeline_steps').insert([
    {user_id:user.id,project_id:project.id,step:'research',status:'running',detail:'Live YouTube evidence captured; factual claims remain source-gated.'},
    {user_id:user.id,project_id:project.id,step:'script',status:'passed',detail:kind==='documentary'?'Evidence-first documentary narration created.':'Story-first narration created with hook, escalation, payoff, and viewer question.'},
    {user_id:user.id,project_id:project.id,step:'voice',status:'running',detail:'Queued for neural narration.'},{user_id:user.id,project_id:project.id,step:'visuals',status:'running',detail:'Queued for animated visual renderer.'},{user_id:user.id,project_id:project.id,step:'edit',status:'running',detail:'Queued for final edit.'},{user_id:user.id,project_id:project.id,step:'quality_check',status:'pending'},{user_id:user.id,project_id:project.id,step:'ready',status:'pending'}]);
  await supabase.from('hook_variants').insert({user_id:user.id,project_id:project.id,hook:g.hook,selected:true});
  if(trend.evidence?.video_id)await supabase.from('research_sources').insert({user_id:user.id,project_id:project.id,title:`Live YouTube trend reference: ${cleanTitle(trend.topic)}`,url:`https://www.youtube.com/watch?v=${encodeURIComponent(trend.evidence.video_id)}`,claim:`Observed in YouTube's most-popular feed with ${Number(trend.evidence.views||0).toLocaleString()} views at scan time.`,verified:false});
  const {error:re}=await supabase.from('render_jobs').insert({user_id:user.id,project_id:project.id,status:'queued'});if(re)throw re;
  message.textContent=`Queued: “${g.title}”.`;
  setTimeout(()=>window.location.reload(),1400);
}

async function showSeriesPicker(body){
  const {data,error}=await supabase.from('series_projects').select('id,title,series_type,status,next_episode_number').eq('status','active').order('created_at',{ascending:false});if(error)throw error;
  const rows=data||[];if(!rows.length){body.innerHTML='<p class="muted">You do not have an active series yet.</p><button class="ghost compact" data-qg-new-series>Create a new series</button>';return;}
  body.innerHTML=`<p class="muted small">Choose the series. Rolixa will make the next numbered chapter only — never a duplicate episode.</p><div style="display:grid;gap:10px">${rows.map(s=>`<button class="ghost" data-qg-series="${s.id}"><strong>${escapeHtml(s.title)}</strong><br><span class="project-meta">Next: Episode ${s.next_episode_number} · ${escapeHtml(s.series_type.replaceAll('_',' '))}</span></button>`).join('')}</div>`;
  body.querySelectorAll('[data-qg-series]').forEach(b=>b.onclick=async()=>{b.disabled=true;message.textContent='Moving the next episode to the front of the series queue…';const {error}=await supabase.from('series_projects').update({next_run_at:new Date().toISOString(),status:'active',updated_at:new Date().toISOString()}).eq('id',b.dataset.qgSeries);if(error){message.textContent=error.message;b.disabled=false;return;}closeChooser();message.textContent='Next episode requested. It will be generated at the next series-worker run, with the next unused episode number.';});
  body.querySelector('[data-qg-new-series]')?.addEventListener('click',()=>{});
}

let overlay=null;
function closeChooser(){overlay?.remove();overlay=null;}
function openChooser(){
  closeChooser();overlay=document.createElement('div');overlay.style.cssText='position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.72);display:flex;align-items:flex-end;justify-content:center;padding:16px';
  overlay.innerHTML=`<section style="width:min(680px,100%);max-height:88vh;overflow:auto;background:#11141d;border:1px solid rgba(255,255,255,.14);border-radius:22px;padding:20px;box-shadow:0 -20px 60px rgba(0,0,0,.45)"><div class="section-head"><div><div class="eyebrow">QUICK GENERATE</div><h2 style="margin:5px 0">What do you want to make?</h2></div><button class="ghost compact" data-qg-close>Close</button></div><div id="qgBody" style="display:grid;gap:10px;margin-top:16px"><button class="primary" data-qg="quick"><strong>⚡ Quick video</strong><br><span style="font-weight:400">A brand-new trending Short</span></button><button class="ghost" data-qg="documentary"><strong>🎬 Single documentary</strong><br><span class="project-meta">One evidence-first standalone documentary</span></button><button class="ghost" data-qg="episode"><strong>▶ Next episode</strong><br><span class="project-meta">Continue one of your existing series</span></button><button class="ghost" data-qg="series"><strong>🎭 Create a new series</strong><br><span class="project-meta">Animated drama, animated series, or documentary series</span></button><button class="ghost" data-qg="manual"><strong>✎ Custom video</strong><br><span class="project-meta">Open Studio and choose everything yourself</span></button></div></section>`;
  document.body.appendChild(overlay);overlay.onclick=e=>{if(e.target===overlay)closeChooser();};overlay.querySelector('[data-qg-close]').onclick=closeChooser;
  const body=overlay.querySelector('#qgBody');
  body.querySelector('[data-qg="quick"]').onclick=async()=>{closeChooser();await runChoice(()=>generateTrendVideo('quick'));};
  body.querySelector('[data-qg="documentary"]').onclick=async()=>{closeChooser();await runChoice(()=>generateTrendVideo('documentary'));};
  body.querySelector('[data-qg="episode"]').onclick=()=>showSeriesPicker(body).catch(e=>message.textContent=e.message);
  body.querySelector('[data-qg="series"]').onclick=()=>{closeChooser();document.querySelector('[data-view="studio"]')?.click();setTimeout(()=>document.getElementById('seriesForm')?.scrollIntoView({behavior:'smooth',block:'start'}),150);};
  body.querySelector('[data-qg="manual"]').onclick=()=>{closeChooser();document.querySelector('[data-view="studio"]')?.click();};
}
async function runChoice(fn){btn.disabled=true;try{await fn();}catch(e){message.textContent=e?.message||'Generation failed.';}finally{btn.disabled=false;}}

btn?.addEventListener('click',openChooser);
