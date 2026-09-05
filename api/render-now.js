const SUPABASE_URL=process.env.SUPABASE_URL||'https://uqmnpeovwfzizajheuig.supabase.co';
const SUPABASE_ANON_KEY=process.env.SUPABASE_ANON_KEY||'sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap';
const GH_TOKEN=process.env.GITHUB_ACTIONS_TOKEN;
const REPO='locksmithlewis-lab/youtube-ai';

async function getUser(token){
  const r=await fetch(`${SUPABASE_URL}/auth/v1/user`,{headers:{apikey:SUPABASE_ANON_KEY,Authorization:`Bearer ${token}`}});
  return r.ok?await r.json():null;
}
export default async function handler(req,res){
  if(req.method!=='POST')return res.status(405).json({error:'POST only'});
  const token=String(req.headers.authorization||'').replace(/^Bearer\s+/i,'');
  const user=token?await getUser(token):null;
  if(!user?.id)return res.status(401).json({error:'Sign in first.'});
  if(!GH_TOKEN)return res.status(503).json({error:'Instant renderer is not configured yet. The recovery queue will still pick up the job.'});
  const r=await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/render-video.yml/dispatches`,{method:'POST',headers:{Authorization:`Bearer ${GH_TOKEN}`,Accept:'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','Content-Type':'application/json'},body:JSON.stringify({ref:'main'})});
  if(!r.ok)return res.status(502).json({error:`Render dispatch failed (${r.status}). Recovery queue remains active.`});
  return res.status(202).json({ok:true,dispatched:true});
}
