import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';

const supabase = createClient('https://uqmnpeovwfzizajheuig.supabase.co','sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap');
const btn = document.getElementById('quickGenerateBtn');
const message = document.getElementById('quickGenerateMessage');

function cleanTitle(title){
  return String(title || 'Trending topic').replace(/[\r\n]+/g,' ').trim().slice(0,120);
}
function key(value){
  return cleanTitle(value).toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
}
function compactNumber(value){
  const n=Number(value||0); if(!n) return '';
  return new Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:1}).format(n);
}

function buildOriginalScript(trend){
  const topic=cleanTitle(trend.topic);
  const views=Number(trend.evidence?.views||0);
  const velocity=Number(trend.evidence?.views_per_hour||0);
  const channel=String(trend.evidence?.channel||'a creator').replace(/[\r\n]+/g,' ').trim();
  const hook=`Wait — ${topic} just exploded, and the numbers are wild.`;
  const proof=views
    ? `${channel} is already at about ${compactNumber(views)} views${velocity ? `, with roughly ${compactNumber(velocity)} more every hour` : ''}.`
    : `It just broke into YouTube's most-popular feed.`;
  const script=[
    hook,
    proof,
    `That kind of jump doesn't happen quietly. Thousands of people are clicking, watching, and sending this topic into more feeds right now.`,
    `The crazy part is how fast attention compounds: one strong moment pulls in the next viewer, then the next, until the algorithm has a reason to keep pushing it.`,
    `But viral speed can disappear just as fast as it arrives. The next few hours decide whether ${topic} keeps climbing or gets replaced by the next obsession.`,
    `So remember this name. If the momentum holds, you're watching the breakout happen in real time.`,
    `Would you keep watching — or scroll?`
  ].join(' ');
  return {hook,script,title:`${topic}: the breakout happening right now`.slice(0,140)};
}

async function chooseNeverUsedTrend(trends,userId){
  const [{data:projects,error:projectError},{data:sources,error:sourceError}] = await Promise.all([
    supabase.from('video_projects').select('id,topic,title').eq('user_id',userId),
    supabase.from('research_sources').select('project_id,url').eq('user_id',userId)
  ]);
  if(projectError) throw projectError;
  if(sourceError) throw sourceError;

  const usedTopics=new Set();
  for(const p of projects||[]){
    if(p.topic) usedTopics.add(key(p.topic));
    if(p.title) usedTopics.add(key(p.title));
  }
  const usedVideoIds=new Set();
  for(const s of sources||[]){
    const match=String(s.url||'').match(/[?&]v=([A-Za-z0-9_-]{6,32})/);
    if(match) usedVideoIds.add(match[1]);
  }

  return (trends||[]).find(t=>{
    const topicKey=key(t.topic);
    const videoId=String(t.evidence?.video_id||'');
    if(videoId && usedVideoIds.has(videoId)) return false;
    if(topicKey && usedTopics.has(topicKey)) return false;
    return true;
  }) || null;
}

btn?.addEventListener('click', async () => {
  btn.disabled=true; message.textContent='Finding a trend Rolixa has never used before…';
  try{
    const {data:{session}}=await supabase.auth.getSession();
    if(!session?.access_token) throw new Error('Sign in first.');
    const {data:{user}}=await supabase.auth.getUser();
    if(!user) throw new Error('Sign in first.');

    const trendResponse=await fetch('/api/trends',{method:'POST',headers:{Authorization:`Bearer ${session.access_token}`}});
    const trendBody=await trendResponse.json().catch(()=>({}));
    if(!trendResponse.ok) throw new Error(trendBody.error||'Could not read live trends.');

    const trend=await chooseNeverUsedTrend(trendBody.trends||[],user.id);
    if(!trend) throw new Error('No unused live trend is available right now. Rolixa will not repeat an old video automatically. Try again after the trend feed changes.');

    message.textContent='Writing a brand-new story and queuing the visual edit…';
    const generated=buildOriginalScript(trend);
    const {data:project,error:projectError}=await supabase.from('video_projects').insert({user_id:user.id,title:generated.title,topic:cleanTitle(trend.topic),format:'Short',style:'Hype',target_duration_seconds:45,status:'generating',hook:generated.hook,script:generated.script}).select().single();
    if(projectError) throw projectError;
    await supabase.from('project_pipeline_steps').insert([
      {user_id:user.id,project_id:project.id,step:'research',status:'running',detail:'Live YouTube trend evidence captured; source verification remains required before public publishing.'},
      {user_id:user.id,project_id:project.id,step:'script',status:'passed',detail:'Story-first narration created with hook, escalation, payoff, and viewer question.'},
      {user_id:user.id,project_id:project.id,step:'voice',status:'running',detail:'Queued for local neural narration.'},
      {user_id:user.id,project_id:project.id,step:'visuals',status:'running',detail:'Queued for scene-driven animated visual renderer.'},
      {user_id:user.id,project_id:project.id,step:'edit',status:'running',detail:'Queued for motion, captions, audio mastering, and final MP4.'},
      {user_id:user.id,project_id:project.id,step:'quality_check',status:'pending'},
      {user_id:user.id,project_id:project.id,step:'ready',status:'pending'}
    ]);
    await supabase.from('hook_variants').insert({user_id:user.id,project_id:project.id,hook:generated.hook,selected:true});
    if(trend.evidence?.video_id) await supabase.from('research_sources').insert({user_id:user.id,project_id:project.id,title:`Live YouTube trend reference: ${cleanTitle(trend.topic)}`,url:`https://www.youtube.com/watch?v=${encodeURIComponent(trend.evidence.video_id)}`,claim:`Observed in YouTube's most-popular feed with ${Number(trend.evidence.views||0).toLocaleString()} views at scan time.`,verified:false});
    const {error:renderError}=await supabase.from('render_jobs').insert({user_id:user.id,project_id:project.id,status:'queued'});
    if(renderError) throw renderError;
    message.textContent=`Queued NEW topic: “${generated.title}”. Rolixa skipped every previously used topic/video.`;
    setTimeout(()=>window.location.reload(),1800);
  }catch(error){message.textContent=error?.message||'Quick Generate failed.';}finally{btn.disabled=false;}
});
