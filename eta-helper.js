import './clip-helper.js';
import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';
const supabase=createClient('https://uqmnpeovwfzizajheuig.supabase.co','sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap');
const median=a=>{const x=[...a].sort((p,q)=>p-q);return x.length?x[Math.floor(x.length/2)]:null;};
const between=(a,b)=>a&&b?Math.max(0,(new Date(b)-new Date(a))/1000):null;
function bucket(p){const f=String(p.format||'').toLowerCase(),d=Number(p.target_duration_seconds||0);if(f==='clip')return 'clip';if(f==='short'||d<=90)return 'short';if(d<=600)return 'standard';return 'long';}
function fmtSeconds(s){s=Math.max(0,Math.round(s||0));if(s<60)return `~${s}s`;const m=Math.round(s/60);if(m<60)return `~${m} min`;const h=Math.floor(m/60),r=m%60;return `~${h}h${r?` ${r}m`:''}`;}
function when(ts){return new Date(ts).toLocaleString([], {weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});}

let busy=false;
async function paint(){
  if(busy)return;busy=true;
  try{
    const {data:{user}}=await supabase.auth.getUser();if(!user)return;
    const [{data:projects},{data:renders},{data:clips}]=await Promise.all([
      supabase.from('video_projects').select('id,format,target_duration_seconds,status,render_eta_at,scheduled_publish_at,published_at,created_at,updated_at').eq('user_id',user.id),
      supabase.from('render_jobs').select('project_id,status,created_at,updated_at,started_at,completed_at,media_duration_seconds,actual_render_seconds').eq('user_id',user.id).order('created_at',{ascending:false}).limit(120),
      supabase.from('clip_jobs').select('project_id,status,created_at,started_at,completed_at,start_seconds,end_seconds').eq('user_id',user.id).order('created_at',{ascending:false}).limit(80)
    ]);
    const map=new Map((projects||[]).map(p=>[p.id,p])),ratios={short:[],standard:[],long:[],clip:[]},queue=[];
    for(const r of renders||[]){if(r.status!=='completed')continue;const p=map.get(r.project_id);if(!p)continue;const actual=Number(r.actual_render_seconds)||between(r.started_at,r.completed_at)||between(r.created_at,r.updated_at),media=Number(r.media_duration_seconds)||Number(p.target_duration_seconds)||0;if(actual>0&&media>0)ratios[bucket(p)].push(actual/media);const q=between(r.created_at,r.started_at);if(q!=null&&q<3600)queue.push(q);}
    for(const c of clips||[]){if(c.status!=='completed')continue;const actual=between(c.started_at,c.completed_at),media=Math.max(1,Number(c.end_seconds)-Number(c.start_seconds));if(actual>0)ratios.clip.push(actual/media);const q=between(c.created_at,c.started_at);if(q!=null&&q<3600)queue.push(q);}
    const queueWait=Math.max(5,median(queue)||25),fallback={short:1.6,standard:1.25,long:1.05,clip:.55};
    const latestRender=new Map(),latestClip=new Map();for(const r of renders||[])if(!latestRender.has(r.project_id))latestRender.set(r.project_id,r);for(const c of clips||[])if(!latestClip.has(c.project_id))latestClip.set(c.project_id,c);
    for(const p of projects||[]){
      const kind=bucket(p),hist=ratios[kind],rate=median(hist)||fallback[kind],duration=Math.max(15,Number(p.target_duration_seconds)||45),job=kind==='clip'?latestClip.get(p.id):latestRender.get(p.id);
      let text='ETA pending',etaIso=null;
      if(p.published_at) text=`Posted ${when(p.published_at)}`;
      else if(p.scheduled_publish_at) text=`Scheduled: posts ${when(p.scheduled_publish_at)}`;
      else if(p.status==='ready') text='Ready to schedule/post';
      else if(p.status==='quality_check') text='Render finished · quality check next';
      else if(p.status==='failed') text='Stopped · needs attention';
      else {
        let remain=queueWait+duration*rate;if(job?.status==='running'&&job.started_at)remain=Math.max(10,duration*rate-between(job.started_at,new Date().toISOString()));
        etaIso=new Date(Date.now()+remain*1000).toISOString();const learned=hist.length>=3?`learned from ${hist.length} ${kind} jobs`:`learning (${hist.length}/3 ${kind} samples)`;text=`ETA ${fmtSeconds(remain)} · ${learned}`;
      }
      const row=document.querySelector(`[data-open-project="${p.id}"]`);if(row){let tag=row.querySelector('.rolixa-eta');if(!tag){tag=document.createElement('div');tag.className='project-meta rolixa-eta';row.appendChild(tag);}tag.textContent=text;}
      const selected=document.querySelector('.project-button.selected')?.dataset.openProject;if(selected===p.id){const head=document.querySelector('#projectWorkspace .workspace-head');if(head){let tag=head.querySelector('.rolixa-workspace-eta');if(!tag){tag=document.createElement('p');tag.className='status-line rolixa-workspace-eta';head.appendChild(tag);}tag.textContent=text;}}
      if(etaIso&&p.render_eta_at!==etaIso) supabase.from('video_projects').update({render_eta_at:etaIso}).eq('id',p.id).then(()=>{});
    }
  }catch(e){console.warn('eta-helper',e);}finally{busy=false;}
}
setInterval(paint,15000);new MutationObserver(()=>setTimeout(paint,80)).observe(document.body,{childList:true,subtree:true});supabase.auth.onAuthStateChange((_e,s)=>{if(s?.user)setTimeout(paint,100)});paint();
