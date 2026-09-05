import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';
const supabase=createClient('https://uqmnpeovwfzizajheuig.supabase.co','sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap');

function fmt(d){return new Date(d).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});}
function relative(ms){const m=Math.max(0,Math.round(ms/60000));if(m<1)return 'under 1 min';if(m<60)return `about ${m} min`;const h=Math.round(m/60);return `about ${h} hr${h===1?'':'s'}`;}
function etaText(project,job,queueIndex){
  if(project.status==='scheduled'&&project.scheduled_publish_at)return `Posts ${fmt(project.scheduled_publish_at)}`;
  if(project.status==='posted')return `Posted${project.published_at?` ${fmt(project.published_at)}`:''}`;
  if(project.status==='ready')return 'Ready to schedule/post';
  if(project.status==='quality_check')return 'Render finished · waiting for quality approval';
  if(project.status==='failed')return 'Stopped · needs attention';
  if(job?.status==='running')return `Render ETA ${relative(2*60000)}`;
  if(job?.status==='queued'){
    const wait=(queueIndex*2+5)*60000;return `Render ETA ${relative(wait)}`;
  }
  if(project.status==='generating')return 'Preparing render · ETA about 5–10 min';
  return 'ETA pending';
}

async function paint(){
  const {data:{user}}=await supabase.auth.getUser();if(!user)return;
  const [{data:projects},{data:jobs}]=await Promise.all([
    supabase.from('video_projects').select('id,status,scheduled_publish_at,published_at,created_at').order('created_at',{ascending:false}),
    supabase.from('render_jobs').select('project_id,status,created_at').in('status',['queued','running']).order('created_at',{ascending:true})
  ]);
  const queue=(jobs||[]).filter(j=>j.status==='queued');
  for(const p of projects||[]){
    const row=document.querySelector(`[data-open-project="${p.id}"]`);if(!row)continue;
    let tag=row.querySelector('.rolixa-eta');if(!tag){tag=document.createElement('div');tag.className='project-meta rolixa-eta';row.appendChild(tag);}
    const job=(jobs||[]).find(j=>j.project_id===p.id);const qi=Math.max(0,queue.findIndex(j=>j.project_id===p.id));tag.textContent=etaText(p,job,qi);
  }
  const selected=document.querySelector('.project-button.selected')?.dataset.openProject;if(selected){const p=(projects||[]).find(x=>x.id===selected);if(p){const head=document.querySelector('#projectWorkspace .workspace-head');if(head){let eta=head.querySelector('.rolixa-workspace-eta');if(!eta){eta=document.createElement('p');eta.className='status-line rolixa-workspace-eta';head.appendChild(eta);}const job=(jobs||[]).find(j=>j.project_id===p.id);const qi=Math.max(0,queue.findIndex(j=>j.project_id===p.id));eta.textContent=etaText(p,job,qi);}}}
}
setInterval(paint,30000);new MutationObserver(()=>setTimeout(paint,120)).observe(document.body,{childList:true,subtree:true});paint();
