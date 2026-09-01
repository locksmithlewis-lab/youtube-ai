import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';

const supabase = createClient('https://uqmnpeovwfzizajheuig.supabase.co','sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap');
const btn = document.getElementById('quickGenerateBtn');
const message = document.getElementById('quickGenerateMessage');

function cleanTitle(title){
  return String(title || 'Trending topic').replace(/[\r\n]+/g,' ').trim().slice(0,120);
}

function buildOriginalScript(trend){
  const title = cleanTitle(trend.topic);
  const views = Number(trend.evidence?.views || 0);
  const velocity = Number(trend.evidence?.views_per_hour || 0);
  const channel = String(trend.evidence?.channel || 'a YouTube channel');
  const hook = `This topic is moving fast on YouTube right now — but here’s the part worth paying attention to.`;
  const stats = views ? `A current popular video about it from ${channel} has already reached about ${views.toLocaleString()} views${velocity ? `, moving at roughly ${velocity.toLocaleString()} views per hour` : ''}.` : `It is currently showing up in YouTube's most-popular feed.`;
  const script = `${hook}\n\nThe trend is: ${title}. ${stats}\n\nInstead of copying the viral video, this short takes a fresh faceless angle: what made this topic catch attention so quickly, what viewers are reacting to, and what happens next.\n\nThe key is speed plus a clear curiosity gap. Start with the strongest surprising detail, keep every sentence moving, and end by asking the viewer what they think happens next.\n\nThis version is built from the live trend signal, not copied wording, footage, or narration from the original video.`;
  return {hook,script,title:`Why ${title} is blowing up right now`.slice(0,140)};
}

btn?.addEventListener('click', async () => {
  btn.disabled = true;
  message.textContent = 'Finding the strongest live trend…';
  try {
    const {data:{session}} = await supabase.auth.getSession();
    if(!session?.access_token) throw new Error('Sign in first.');

    const trendResponse = await fetch('/api/trends', {method:'POST', headers:{Authorization:`Bearer ${session.access_token}`}});
    const trendBody = await trendResponse.json().catch(()=>({}));
    if(!trendResponse.ok) throw new Error(trendBody.error || 'Could not read live trends.');
    const trend = (trendBody.trends || [])[0];
    if(!trend) throw new Error('No live trend was available.');

    message.textContent = 'Creating an original faceless version…';
    const {data:{user}} = await supabase.auth.getUser();
    if(!user) throw new Error('Sign in first.');
    const generated = buildOriginalScript(trend);

    const {data:project,error:projectError} = await supabase.from('video_projects').insert({
      user_id:user.id,
      title:generated.title,
      topic:cleanTitle(trend.topic),
      format:'Short',
      style:'Hype',
      target_duration_seconds:45,
      status:'generating',
      hook:generated.hook,
      script:generated.script
    }).select().single();
    if(projectError) throw projectError;

    await supabase.from('project_pipeline_steps').insert([
      {user_id:user.id,project_id:project.id,step:'research',status:'running',detail:'Live YouTube trend evidence captured; additional source verification still recommended.'},
      {user_id:user.id,project_id:project.id,step:'script',status:'passed',detail:'Original trend-based starter script created.'},
      {user_id:user.id,project_id:project.id,step:'voice',status:'running',detail:'Queued for cloud renderer.'},
      {user_id:user.id,project_id:project.id,step:'visuals',status:'running',detail:'Queued for cloud renderer.'},
      {user_id:user.id,project_id:project.id,step:'edit',status:'running',detail:'Queued for cloud renderer.'},
      {user_id:user.id,project_id:project.id,step:'quality_check',status:'pending'},
      {user_id:user.id,project_id:project.id,step:'ready',status:'pending'}
    ]);

    await supabase.from('hook_variants').insert({user_id:user.id,project_id:project.id,hook:generated.hook,selected:true});
    if(trend.evidence?.video_id){
      await supabase.from('research_sources').insert({
        user_id:user.id,
        project_id:project.id,
        title:`Live YouTube trend reference: ${cleanTitle(trend.topic)}`,
        url:`https://www.youtube.com/watch?v=${encodeURIComponent(trend.evidence.video_id)}`,
        claim:`Observed in YouTube's most-popular feed with ${Number(trend.evidence.views||0).toLocaleString()} views at scan time.`,
        verified:false
      });
    }

    const {error:renderError} = await supabase.from('render_jobs').insert({user_id:user.id,project_id:project.id,status:'queued'});
    if(renderError) throw renderError;
    message.textContent = `Queued: “${generated.title}”. It uses the live viral topic as inspiration, but does not copy the original script or footage.`;
    setTimeout(()=>window.location.reload(),1800);
  } catch (error) {
    message.textContent = error?.message || 'Quick Generate failed.';
  } finally {
    btn.disabled = false;
  }
});
