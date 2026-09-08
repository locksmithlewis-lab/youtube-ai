import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';
const supabase=createClient('https://uqmnpeovwfzizajheuig.supabase.co','sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap');
const esc=v=>String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
let busy=false;
function numeric(v){const n=Number(v);return Number.isFinite(n)?n:null;}
function validRetention(row){const d=numeric(row.average_view_duration_seconds);return d!=null&&d>0;}
async function paint(){
  if(busy)return;busy=true;
  try{
    const {data:{user}}=await supabase.auth.getUser();if(!user)return;
    const [{data:snapshots,error:aerr},{data:projects,error:perr}]=await Promise.all([
      supabase.from('analytics_snapshots').select('*').eq('user_id',user.id).order('captured_at',{ascending:false}).limit(80),
      supabase.from('video_projects').select('id,title,target_duration_seconds').eq('user_id',user.id)
    ]);
    if(aerr||perr)return;
    const analyticsList=document.getElementById('analyticsList');
    if(analyticsList){
      if(!snapshots?.length)analyticsList.textContent='No analytics snapshots yet.';
      else analyticsList.innerHTML=snapshots.map(a=>{
        const views=numeric(a.views),likes=numeric(a.likes),duration=validRetention(a)?numeric(a.average_view_duration_seconds):null;
        return `<div class="project-row"><div class="project-title">${esc(a.youtube_video_id||'Channel snapshot')}</div><div class="project-meta">Captured ${new Date(a.captured_at).toLocaleString()}</div><div class="analytics-mini"><span>Views ${views??'—'}</span><span>Avg duration ${duration==null?'—':`${duration}s`}</span><span>Likes ${likes??'—'}</span></div></div>`;
      }).join('');
    }
    const lessons=document.getElementById('lessonsList');if(!lessons)return;
    const projectMap=new Map((projects||[]).map(p=>[p.id,p]));
    const latest=new Map();for(const row of snapshots||[]){if(row.project_id&&!latest.has(row.project_id))latest.set(row.project_id,row);}
    const valid=[...latest.values()].filter(validRetention);
    if(!valid.length){
      lessons.className='lesson-list';
      lessons.innerHTML='<div class="lesson"><strong>Learning waiting for valid retention</strong><p>Views can be displayed now, but the app will not call a video a top performer or tune production from snapshots with missing or 0-second average view duration.</p></div><div class="lesson"><strong>Data standard</strong><p>Optimization starts only after YouTube returns real non-zero watch-duration data linked to a project.</p></div>';
      return;
    }
    valid.sort((a,b)=>{const av=(numeric(a.views)||0)*(numeric(a.average_view_duration_seconds)||0),bv=(numeric(b.views)||0)*(numeric(b.average_view_duration_seconds)||0);return bv-av;});
    const best=valid[0],project=projectMap.get(best.project_id),target=Math.max(1,numeric(project?.target_duration_seconds)||60),avg=numeric(best.average_view_duration_seconds)||0,retention=Math.min(100,Math.round(avg/target*100));
    lessons.className='lesson-list';
    lessons.innerHTML=`<div class="lesson"><strong>Best valid performance signal</strong><p>${esc(project?.title||best.youtube_video_id||'Video')} has ${Number(best.views||0).toLocaleString()} views and ${avg}s average view duration in its latest valid snapshot (about ${retention}% of the production target length).</p></div><div class="lesson"><strong>Data standard</strong><p>Only non-zero, project-linked retention snapshots influence production learning. Missing analytics remain unknown, not zero.</p></div>`;
  }catch(e){console.warn('stats-truth-helper',e);}finally{busy=false;}
}
setInterval(paint,20000);new MutationObserver(()=>setTimeout(paint,120)).observe(document.body,{childList:true,subtree:true});supabase.auth.onAuthStateChange((_e,s)=>{if(s?.user)setTimeout(paint,150)});paint();
