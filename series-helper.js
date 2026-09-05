import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';

const supabase=createClient('https://uqmnpeovwfzizajheuig.supabase.co','sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap');
const studio=document.getElementById('studio');
if(studio){
  const style=document.createElement('style');
  style.textContent=`.series-panel{margin-top:22px}.series-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.series-grid .wide{grid-column:1/-1}.series-list{display:grid;gap:10px;margin-top:16px}.series-row{display:grid;gap:5px;padding:14px;border:1px solid rgba(255,255,255,.09);border-radius:14px;background:rgba(255,255,255,.025)}@media(max-width:760px){.series-grid{grid-template-columns:1fr}.series-grid .wide{grid-column:auto}}`;
  document.head.appendChild(style);
  const panel=document.createElement('section'); panel.className='panel series-panel';
  panel.innerHTML=`<div class="section-head"><div><div class="eyebrow">SERIES ENGINE</div><h3>Documentaries, animated dramas & continuing series</h3><p class="muted small">Build a recurring cast of up to 50 characters. Rolixa keeps their names, roles, appearance, personality, relationships and continuity in the story bible instead of replacing them every episode.</p></div></div>
  <form id="seriesForm" class="series-grid">
    <label class="wide">Series title<input id="seriesTitle" required maxlength="120" placeholder="Example: Neon Harbor" /></label>
    <label>Type<select id="seriesType"><option value="animated_drama">Animated drama</option><option value="animated_series">Animated series</option><option value="documentary">Documentary series</option></select></label>
    <label>Episode length<input id="seriesLength" type="number" min="20" max="3600" value="60" /><span class="input-help">Seconds</span></label>
    <label class="wide">Premise / world<textarea id="seriesPremise" required maxlength="1200" placeholder="Who is this about? What world are we in? What conflict or subject keeps the series moving?"></textarea></label>
    <label class="wide">Characters — up to 50, one per line<textarea id="seriesCharacters" rows="10" maxlength="10000" placeholder="Mara | lead detective | 28, curly black hair, green coat | observant, dry humor | trusts Jax\nJax | pilot | 31, shaved head, flight jacket | bold, loyal | Mara's oldest friend"></textarea><span class="input-help">Format: Name | role | appearance | personality | relationships. Name-only lines also work.</span></label>
    <label class="wide" id="factsWrap" style="display:none">Verified documentary facts (one per line)<textarea id="seriesFacts" placeholder="Only facts you are comfortable treating as verified. Documentary auto-generation pauses if this is empty."></textarea></label>
    <label>Cadence<select id="seriesCadence"><option value="daily">New episode every day</option><option value="manual">Manual only</option></select></label>
    <div style="align-self:end"><button class="primary" type="submit">Create series</button></div>
  </form><p id="seriesMessage" class="status-line"></p><div id="seriesList" class="series-list"></div>`;
  studio.appendChild(panel);
  const type=document.getElementById('seriesType'),factsWrap=document.getElementById('factsWrap');
  type.addEventListener('change',()=>factsWrap.style.display=type.value==='documentary'?'block':'none');

  async function loadSeries(){
    const {data:{user}}=await supabase.auth.getUser(); if(!user)return;
    const {data,error}=await supabase.from('series_projects').select('*').order('created_at',{ascending:false});
    const box=document.getElementById('seriesList'); if(error){box.textContent='Could not load series.';return;}
    const rows=data||[]; if(!rows.length){box.innerHTML='<div class="empty compact-empty">No series yet.</div>';return;}
    box.innerHTML=rows.map(s=>{const count=Array.isArray(s.story_bible?.characters)?s.story_bible.characters.length:0;return `<div class="series-row"><strong>${escapeHtml(s.title)}</strong><span class="project-meta">${escapeHtml(s.series_type.replaceAll('_',' '))} · ${escapeHtml(s.status)} · ${count} characters · next episode ${s.next_episode_number} · ${escapeHtml(s.cadence)}</span><span class="muted small">${escapeHtml(s.premise)}</span><div class="inline-actions"><button class="ghost compact" data-series-toggle="${s.id}" data-next-status="${s.status==='active'?'paused':'active'}">${s.status==='active'?'Pause':'Resume'}</button></div></div>`}).join('');
    document.querySelectorAll('[data-series-toggle]').forEach(btn=>btn.addEventListener('click',async()=>{await supabase.from('series_projects').update({status:btn.dataset.nextStatus,updated_at:new Date().toISOString()}).eq('id',btn.dataset.seriesToggle);await loadSeries();}));
  }
  function escapeHtml(v){return String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}
  function parseCharacters(raw){
    const lines=String(raw||'').split(/\n|,(?=\s*[A-Z][A-Za-z0-9 _'-]{1,40}(?:\s*\||\s*,|$))/).map(x=>x.trim()).filter(Boolean).slice(0,50);
    return lines.map((line,index)=>{const p=line.split('|').map(x=>x.trim());return {id:`char_${index+1}`,name:p[0],role:p[1]||'',appearance:p[2]||'',personality:p[3]||'',relationships:p[4]||'',continuity:{introduced_episode:1,status:'active'}};});
  }
  document.getElementById('seriesForm').addEventListener('submit',async e=>{
    e.preventDefault(); const msg=document.getElementById('seriesMessage'); msg.textContent='Creating series…';
    const {data:{user}}=await supabase.auth.getUser(); if(!user){msg.textContent='Sign in first.';return;}
    const seriesType=type.value; const chars=parseCharacters(document.getElementById('seriesCharacters').value);
    if(chars.length>50){msg.textContent='Maximum 50 characters.';return;}
    const factLines=document.getElementById('seriesFacts').value.split('\n').map(x=>x.trim()).filter(Boolean);
    const story_bible={characters:chars,verified_facts:factLines.map(fact=>({fact})),cast_rules:{max_characters:50,preserve_identity:true,preserve_appearance:true,preserve_relationships:true,allow_character_growth:true},rules:{never_repeat_episode:true,continue_open_loops:true,original_chapters_only:true,maintain_character_continuity:true}};
    const cadence=document.getElementById('seriesCadence').value;
    const {error}=await supabase.from('series_projects').insert({user_id:user.id,title:document.getElementById('seriesTitle').value.trim(),series_type:seriesType,premise:document.getElementById('seriesPremise').value.trim(),style:seriesType==='documentary'?'Documentary':'Animated cinematic',episode_length_seconds:Number(document.getElementById('seriesLength').value)||60,cadence,status:'active',story_bible,next_run_at:cadence==='daily'?new Date().toISOString():null});
    if(error){msg.textContent=error.message;return;}
    msg.textContent=cadence==='daily'?`Series created with ${chars.length} recurring characters. Episode 1 will be generated at the next due-series check.`:`Series created with ${chars.length} recurring characters in manual mode.`;
    e.target.reset(); document.getElementById('seriesLength').value='60'; factsWrap.style.display='none'; await loadSeries();
  });
  supabase.auth.onAuthStateChange((_e,s)=>{if(s?.user)loadSeries();});
  const {data:{session}}=await supabase.auth.getSession(); if(session?.user)loadSeries();
}
