import './project-controls.js';
import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';
const supabase=createClient('https://uqmnpeovwfzizajheuig.supabase.co','sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap');

function selectedProjectId(){return document.querySelector('.project-button.selected')?.dataset.openProject||null;}
function profile(p){const format=String(p?.format||'').toLowerCase(),style=String(p?.style||'').toLowerCase();if(format==='clip')return 'clip';if(style==='documentary'||style==='news'||style==='educational'||format==='explainer')return 'factual';if(style.includes('story')||style.includes('animated')||format==='story')return 'story';return 'entertainment';}
function copyFor(kind){
  if(kind==='factual')return 'Factual standard: verified evidence, creative preflight, voice/visual/edit completion, sound mastering and finished-MP4 QC must all pass. This button only requests a review; it cannot mark a video ready.';
  if(kind==='clip')return 'Clip standard: reuse rights, successful processing and server-side video quality checks are required. This button cannot bypass publishing QC.';
  if(kind==='story')return 'Story standard: continuity, finished narration, creative preflight, motion-first visuals and finished-MP4 QC are required.';
  return 'Entertainment standard: hook, finished narration, creative preflight, motion-first production and finished-MP4 QC are required.';
}
async function runGate(projectId){
  const result=document.getElementById('qualityResult');if(result)result.textContent='Checking current evidence. Server QC controls final approval…';
  const [{data:{user}},{data:p},{data:sources},{data:hooks},{data:steps},{data:clips}]=await Promise.all([supabase.auth.getUser(),supabase.from('video_projects').select('*').eq('id',projectId).maybeSingle(),supabase.from('research_sources').select('*').eq('project_id',projectId),supabase.from('hook_variants').select('*').eq('project_id',projectId),supabase.from('project_pipeline_steps').select('*').eq('project_id',projectId),supabase.from('clip_jobs').select('*').eq('project_id',projectId).order('created_at',{ascending:false}).limit(1)]);
  if(!user||!p){if(result)result.textContent='Could not load this project.';return;}
  const kind=profile(p),reasons=[],done=name=>(steps||[]).some(s=>s.step===name&&s.status==='passed'),hookSelected=(hooks||[]).some(h=>h.selected),scriptPresent=!!String(p.script||'').trim(),renderPresent=!!p.output_url,verified=(sources||[]).filter(s=>s.verified).length;
  if(kind==='factual'&&verified<1)reasons.push('Factual/documentary video needs at least one verified source.');
  if(kind==='clip'){const c=(clips||[])[0];if(!c?.rights_confirmed)reasons.push('Clip reuse rights are not confirmed.');if(c?.status!=='completed')reasons.push('Clip processing has not completed successfully.');}
  else{if(!hookSelected)reasons.push('No hook selected.');if(!scriptPresent)reasons.push('No finished script.');for(const name of ['creative_preflight','voice','visuals','edit','final_video_qc'])if(!done(name))reasons.push(`${name.replaceAll('_',' ')} has not passed.`);if(Number(p.creative_score||0)<78)reasons.push('Creative score is below 78.');if(Number(p.quality_score||0)<82)reasons.push('Finished-video score is below 82.');}
  if(!renderPresent)reasons.push('No finished render.');const passed=!reasons.length,detail=passed?'All visible requirements pass. Server quality worker will control Ready status.':reasons.join(' ');
  await supabase.from('quality_checks').insert({user_id:user.id,project_id:projectId,score:p.quality_score??null,passed,evidence:{quality_profile:kind,creative_score:p.creative_score,quality_score:p.quality_score,verified_sources:verified,selected_hook:hookSelected,script_present:scriptPresent,render_present:renderPresent,creative_preflight:done('creative_preflight'),voice_passed:done('voice'),visuals_passed:done('visuals'),edit_passed:done('edit'),final_video_qc:done('final_video_qc'),clip_rights_confirmed:!!(clips||[])[0]?.rights_confirmed,clip_completed:(clips||[])[0]?.status==='completed'},rejection_reasons:reasons,reviewer_version:'server-authoritative-profile-gate-v3'});
  if(result)result.textContent=passed?'All visible checks pass. Automatic server QC will approve publishing.':`Blocked: ${detail}`;
}
document.addEventListener('click',e=>{const b=e.target.closest('#runQualityBtn');if(!b)return;e.preventDefault();e.stopImmediatePropagation();const id=selectedProjectId();if(id)runGate(id).catch(err=>{const r=document.getElementById('qualityResult');if(r)r.textContent=err?.message||'Quality check failed.';});},true);
async function paint(){const id=selectedProjectId(),card=document.getElementById('runQualityBtn')?.closest('.work-card');if(!id||!card)return;const {data:p}=await supabase.from('video_projects').select('format,style').eq('id',id).maybeSingle();if(!p)return;const note=card.querySelector('p.muted.small');if(note)note.textContent=copyFor(profile(p));const b=document.getElementById('runQualityBtn');if(b)b.textContent='Review QC status';}
new MutationObserver(()=>setTimeout(paint,80)).observe(document.body,{childList:true,subtree:true});paint();
