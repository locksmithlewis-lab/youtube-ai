import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';
const supabase=createClient('https://uqmnpeovwfzizajheuig.supabase.co','sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap');
const studio=document.getElementById('studio');
function toSeconds(v){const p=String(v||'').trim().split(':').map(Number);if(p.some(Number.isNaN))return NaN;if(p.length===1)return p[0];if(p.length===2)return p[0]*60+p[1];if(p.length===3)return p[0]*3600+p[1]*60+p[2];return NaN;}
function openClipStudio(){document.querySelector('[data-view="studio"]')?.click();setTimeout(()=>document.getElementById('clipStudioPanel')?.scrollIntoView({behavior:'smooth',block:'start'}),120);}
if(studio){
  const panel=document.createElement('section');panel.id='clipStudioPanel';panel.className='panel series-panel';panel.style.marginTop='22px';
  panel.innerHTML=`<div class="section-head"><div><div class="eyebrow">STREAM CLIPPER</div><h3>Clip long livestreams & gaming VODs</h3><p class="muted small">Make Shorts or standard clips from streams you own or have permission to reuse. Rolixa keeps the full source URL and cut points so the clip is reproducible.</p></div></div>
  <form id="clipForm" class="form-grid">
    <label class="wide">Stream / VOD URL<input id="clipUrl" type="url" required placeholder="YouTube, Twitch, or another supported stream/VOD URL" /></label>
    <label class="wide">Clip title<input id="clipTitle" required maxlength="140" placeholder="Best moment / clutch / reaction / highlight" /></label>
    <label>Start time<input id="clipStart" required placeholder="01:23:45 or 83" /></label>
    <label>End time<input id="clipEnd" required placeholder="01:24:30 or 128" /></label>
    <label>Output<select id="clipLayout"><option value="vertical">Vertical Short 9:16</option><option value="original">Original aspect</option></select></label>
    <label>Style<select id="clipStyle"><option>Gaming</option><option>Reaction</option><option>Podcast</option><option>Sports</option><option>Livestream</option></select></label>
    <label class="wide check-row"><input id="clipRights" type="checkbox" required /> I own this footage or have permission to reuse and monetize this clip.</label>
    <div class="form-action wide"><button class="primary" type="submit">Queue clip</button></div>
  </form><p id="clipMessage" class="status-line"></p>`;
  studio.appendChild(panel);
  document.getElementById('clipForm').addEventListener('submit',async e=>{
    e.preventDefault();const msg=document.getElementById('clipMessage');msg.textContent='Checking cut points…';
    const {data:{user}}=await supabase.auth.getUser();if(!user){msg.textContent='Sign in first.';return;}
    const start=toSeconds(document.getElementById('clipStart').value),end=toSeconds(document.getElementById('clipEnd').value);if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start){msg.textContent='Enter a valid start and end time.';return;}if(end-start>600){msg.textContent='One clip can be up to 10 minutes. Use multiple clips for a longer stream.';return;}
    const url=document.getElementById('clipUrl').value.trim(),title=document.getElementById('clipTitle').value.trim(),layout=document.getElementById('clipLayout').value,style=document.getElementById('clipStyle').value;msg.textContent='Creating clip job…';
    const {data:project,error:pe}=await supabase.from('video_projects').insert({user_id:user.id,title,topic:`Authorized clip from ${url}`,format:'Clip',style,target_duration_seconds:Math.round(end-start),status:'generating',hook:`Highlight clip: ${title}`,script:`Authorized source clip from ${start}s to ${end}s.`}).select().single();if(pe){msg.textContent=pe.message;return;}
    await supabase.from('project_pipeline_steps').insert([{user_id:user.id,project_id:project.id,step:'research',status:'passed',detail:'Source URL stored and reuse rights explicitly confirmed by the user.'},{user_id:user.id,project_id:project.id,step:'script',status:'passed',detail:'Clip uses the original authorized source segment; no generated narration required.'},{user_id:user.id,project_id:project.id,step:'voice',status:'passed',detail:'Original source audio retained.'},{user_id:user.id,project_id:project.id,step:'visuals',status:'running',detail:layout==='vertical'?'Preparing vertical gaming/livestream layout.':'Preserving original source aspect.'},{user_id:user.id,project_id:project.id,step:'edit',status:'running',detail:'Cutting the requested stream segment.'},{user_id:user.id,project_id:project.id,step:'quality_check',status:'pending'},{user_id:user.id,project_id:project.id,step:'ready',status:'pending'}]);
    await supabase.from('hook_variants').insert({user_id:user.id,project_id:project.id,hook:`Highlight clip: ${title}`,selected:true});
    await supabase.from('research_sources').insert({user_id:user.id,project_id:project.id,title:'Authorized stream/VOD source',url,claim:'User confirmed ownership or permission to reuse this source footage.',verified:true});
    const {error:ce}=await supabase.from('clip_jobs').insert({user_id:user.id,project_id:project.id,source_url:url,start_seconds:start,end_seconds:end,source_kind:layout,rights_confirmed:true,status:'queued'});if(ce){await supabase.from('video_projects').update({status:'failed',failure_reason:ce.message}).eq('id',project.id);msg.textContent=ce.message;return;}
    msg.textContent=`Queued ${Math.round(end-start)}s clip. Rolixa will learn its real processing time and use it to improve future clip ETAs.`;e.target.reset();
  });
  const addQuickClip=()=>{const body=document.getElementById('qgBody');if(!body||body.querySelector('[data-qg="clip"]'))return;const b=document.createElement('button');b.className='ghost';b.dataset.qg='clip';b.innerHTML='<strong>✂ Clip a stream</strong><br><span class="project-meta">Turn an authorized livestream or gaming VOD into a Short/highlight</span>';b.onclick=()=>{document.querySelector('[data-qg-close]')?.click();openClipStudio();};const manual=body.querySelector('[data-qg="manual"]');body.insertBefore(b,manual||null);};
  new MutationObserver(addQuickClip).observe(document.body,{childList:true,subtree:true});
}
