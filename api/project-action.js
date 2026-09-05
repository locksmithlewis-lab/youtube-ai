const SUPABASE_URL=process.env.SUPABASE_URL||'https://uqmnpeovwfzizajheuig.supabase.co';
const PUB=process.env.SUPABASE_PUBLISHABLE_KEY||process.env.SUPABASE_ANON_KEY||'sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap';

async function getUser(token){const r=await fetch(`${SUPABASE_URL}/auth/v1/user`,{headers:{apikey:PUB,Authorization:`Bearer ${token}`}});return r.ok?r.json():null;}
async function sb(path,opt={},key){const r=await fetch(`${SUPABASE_URL}/rest/v1/${path}`,{...opt,headers:{apikey:key,Authorization:`Bearer ${key}`,'Content-Type':'application/json',...(opt.headers||{})}});const text=await r.text();if(!r.ok)throw new Error(`Database request failed (${r.status})${text?`: ${text.slice(0,240)}`:''}`);return text?JSON.parse(text):null;}
async function removeObject(path,key){if(!path)return;const encoded=String(path).split('/').map(encodeURIComponent).join('/');const r=await fetch(`${SUPABASE_URL}/storage/v1/object/video-outputs/${encoded}`,{method:'DELETE',headers:{apikey:key,Authorization:`Bearer ${key}`}});if(!r.ok&&r.status!==404){const t=await r.text().catch(()=> '');throw new Error(`Could not delete rendered file (${r.status})${t?`: ${t.slice(0,180)}`:''}`);}}

module.exports=async function handler(req,res){
 if(req.method!=='POST')return res.status(405).json({error:'POST only'});
 const serviceKey=process.env.SUPABASE_SERVICE_ROLE_KEY;if(!serviceKey)return res.status(503).json({error:'Project controls are not configured.'});
 const bearer=String(req.headers.authorization||'').replace(/^Bearer\s+/i,'');const user=bearer?await getUser(bearer):null;if(!user?.id)return res.status(401).json({error:'Sign in first.'});
 const projectId=String(req.body?.projectId||'').trim(),action=String(req.body?.action||'').trim();if(!projectId||!['cancel','delete'].includes(action))return res.status(400).json({error:'Valid projectId and action are required.'});
 try{
  const rows=await sb(`video_projects?id=eq.${encodeURIComponent(projectId)}&user_id=eq.${encodeURIComponent(user.id)}&select=*`,{},serviceKey)||[];const project=rows[0];if(!project)return res.status(404).json({error:'Project not found.'});
  const jobs=await sb(`render_jobs?project_id=eq.${encodeURIComponent(projectId)}&user_id=eq.${encodeURIComponent(user.id)}&select=*&order=created_at.desc`,{},serviceKey)||[];
  if(action==='cancel'){
   const active=jobs.filter(j=>['queued','running'].includes(j.status));if(!active.length)return res.status(200).json({ok:true,message:'No active render to cancel.'});
   await sb(`render_jobs?project_id=eq.${encodeURIComponent(projectId)}&user_id=eq.${encodeURIComponent(user.id)}&status=in.(queued,running)`,{method:'PATCH',headers:{Prefer:'return=minimal'},body:JSON.stringify({status:'canceled',error:'Canceled by user.',completed_at:new Date().toISOString(),updated_at:new Date().toISOString()})},serviceKey);
   await sb(`video_projects?id=eq.${encodeURIComponent(projectId)}&user_id=eq.${encodeURIComponent(user.id)}`,{method:'PATCH',headers:{Prefer:'return=minimal'},body:JSON.stringify({status:'draft',failure_reason:null,updated_at:new Date().toISOString()})},serviceKey);
   return res.status(200).json({ok:true,message:'Render canceled.'});
  }
  if(jobs.some(j=>j.status==='running'))return res.status(409).json({error:'Cancel the active render first, then delete the project after it stops.'});
  const objects=new Set([project.output_url,...jobs.map(j=>j.output_url)].filter(Boolean));for(const path of objects)await removeObject(path,serviceKey);
  await sb(`video_projects?id=eq.${encodeURIComponent(projectId)}&user_id=eq.${encodeURIComponent(user.id)}`,{method:'DELETE',headers:{Prefer:'return=minimal'}},serviceKey);
  return res.status(200).json({ok:true,message:'Project and stored render deleted permanently.'});
 }catch(e){return res.status(500).json({error:e.message||'Project action failed.'});}
};
