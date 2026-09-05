import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';
const supabase=createClient('https://uqmnpeovwfzizajheuig.supabase.co','sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap');

function selectedProjectId(){return document.querySelector('.project-button.selected')?.dataset.openProject||null;}
function profile(p){
  const format=String(p?.format||'').toLowerCase(),style=String(p?.style||'').toLowerCase();
  if(format==='clip')return 'clip';
  if(style==='documentary'||style==='news'||style==='educational'||format==='explainer')return 'factual';
  if(style.includes('story')||style.includes('animated')||format==='story')return 'story';
  return 'entertainment';
}
function copyFor(kind){
  if(kind==='factual')return 'Factual standard: verified source(s), a selected hook, a finished script, completed voice/visual/edit steps, and a finished render are required.';
  if(kind==='clip')return 'Clip standard: reuse rights must be confirmed, the clip job must finish successfully, and the rendered clip must exist. Factual research is not required.';
  if(kind==='story')return 'Story standard: continuity/script, hook, completed voice/visual/edit steps, and finished animation/render are required. Verified factual sources are not required for fiction.';
  return 'Entertainment standard: hook, finished script, completed voice/visual/edit steps, and finished render are required. Verified research is not required unless the video makes factual claims.';
}

async function runGate(projectId){
  const result=document.getElementById('qualityResult');if(result)result.textContent='Running the right quality standard for this video…';
  const [{data:{user}},{data:p},{data:sources},{data:hooks},{data:steps},{data:clips}]=await Promise.all([
    supabase.auth.getUser(),supabase.from('video_projects').select('*').eq('id',projectId).maybeSingle(),supabase.from('research_sources').select('*').eq('project_id',projectId),supabase.from('hook_variants').select('*').eq('project_id',projectId),supabase.from('project_pipeline_steps').select('*').eq('project_id',projectId),supabase.from('clip_jobs').select('*').eq('project_id',projectId).order('created_at',{ascending:false}).limit(1)
  ]);
  if(!user||!p){if(result)result.textContent='Could not load this project.';return;}
  const kind=profile(p),reasons=[],done=name=>(steps||[]).some(s=>s.step===name&&s.status==='passed');
  const hookSelected=(hooks||[]).some(h=>h.selected),scriptPresent=!!String(p.script||'').trim(),renderPresent=!!p.output_url,verified=(sources||[]).filter(s=>s.verified).length;
  if(kind==='factual'&&verified<1)reasons.push('Factual/documentary video needs at least one verified source.');
  if(kind==='clip'){
    const c=(clips||[])[0];if(!c?.rights_confirmed)reasons.push('Clip reuse rights are not confirmed.');if(c?.status!=='completed')reasons.push('Clip processing has not completed successfully.');
  }else{
    if(!hookSelected)reasons.push('No hook selected.');if(!scriptPresent)reasons.push('No finished script.');
    if(!done('voice'))reasons.push('Voice step has not passed.');if(!done('visuals'))reasons.push('Visuals step has not passed.');if(!done('edit'))reasons.push('Edit step has not passed.');
  }
  if(!renderPresent)reasons.push('No finished render.');
  const passed=!reasons.length,detail=passed?`${kind} quality standard passed.`:reasons.join(' ');
  await supabase.from('quality_checks').insert({user_id:user.id,project_id:projectId,score:null,passed,evidence:{quality_profile:kind,verified_sources:verified,selected_hook:hookSelected,script_present:scriptPresent,render_present:renderPresent,voice_passed:done('voice'),visuals_passed:done('visuals'),edit_passed:done('edit'),clip_rights_confirmed:!!(clips||[])[0]?.rights_confirmed,clip_completed:(clips||[])[0]?.status==='completed'},rejection_reasons:reasons,reviewer_version:'rolixa-profile-gate-v2'});
  await supabase.from('video_projects').update({status:passed?'ready':'quality_check',failure_reason:passed?null:detail,updated_at:new Date().toISOString()}).eq('id',projectId);
  await supabase.from('project_pipeline_steps').upsert([{user_id:user.id,project_id:projectId,step:'quality_check',status:passed?'passed':'failed',detail,updated_at:new Date().toISOString()},{user_id:user.id,project_id:projectId,step:'ready',status:passed?'passed':'blocked',detail:passed?'Ready for publishing approval.':'Content-specific quality gate did not pass.',updated_at:new Date().toISOString()}],{onConflict:'project_id,step'});
  if(result)result.textContent=passed?`Passed ${kind} standard. Project is Ready.`:`Blocked: ${detail}`;
  setTimeout(()=>document.getElementById('refreshBtn')?.click(),250);
}

document.addEventListener('click',e=>{const b=e.target.closest('#runQualityBtn');if(!b)return;e.preventDefault();e.stopImmediatePropagation();const id=selectedProjectId();if(id)runGate(id).catch(err=>{const r=document.getElementById('qualityResult');if(r)r.textContent=err?.message||'Quality check failed.';});},true);

async function paint(){const id=selectedProjectId();const card=document.getElementById('runQualityBtn')?.closest('.work-card');if(!id||!card)return;const {data:p}=await supabase.from('video_projects').select('format,style').eq('id',id).maybeSingle();if(!p)return;const note=card.querySelector('p.muted.small');if(note)note.textContent=copyFor(profile(p));}
new MutationObserver(()=>setTimeout(paint,80)).observe(document.body,{childList:true,subtree:true});paint();
