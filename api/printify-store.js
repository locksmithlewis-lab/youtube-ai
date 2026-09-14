const SUPABASE_URL=process.env.SUPABASE_URL||'https://uqmnpeovwfzizajheuig.supabase.co';
const PUB=process.env.SUPABASE_PUBLISHABLE_KEY||process.env.SUPABASE_ANON_KEY||'sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap';
const PRINTIFY_BASE='https://api.printify.com/v1';
const TARGET_SHOP='BigBng';

async function getUser(token){
  const r=await fetch(`${SUPABASE_URL}/auth/v1/user`,{headers:{apikey:PUB,Authorization:`Bearer ${token}`}});
  return r.ok?r.json():null;
}
async function pf(path,token,opt={}){
  const r=await fetch(`${PRINTIFY_BASE}${path}`,{
    ...opt,
    headers:{Authorization:`Bearer ${token}`,'User-Agent':'Rolixa-BLACKSTAR/1.0','Content-Type':'application/json;charset=utf-8',...(opt.headers||{})}
  });
  const text=await r.text();
  if(!r.ok)throw new Error(`Printify request failed (${r.status})${text?`: ${text.slice(0,240)}`:''}`);
  return text?JSON.parse(text):null;
}

module.exports=async function handler(req,res){
  if(req.method!=='GET')return res.status(405).json({error:'GET only'});
  const bearer=String(req.headers.authorization||'').replace(/^Bearer\s+/i,'');
  const user=bearer?await getUser(bearer):null;
  if(!user?.id)return res.status(401).json({error:'Sign in first.'});

  const token=process.env.PRINTIFY_API_TOKEN;
  if(!token)return res.status(503).json({
    connected:false,
    provider:'Printify',
    shopTitle:TARGET_SHOP,
    error:'PRINTIFY_API_TOKEN is not configured on the server.'
  });

  try{
    const shops=await pf('/shops.json',token) || [];
    const shop=shops.find(s=>String(s.title||'').trim().toLowerCase()===TARGET_SHOP.toLowerCase());
    if(!shop)return res.status(404).json({connected:false,provider:'Printify',shopTitle:TARGET_SHOP,error:`Printify account connected, but shop ${TARGET_SHOP} was not found.`,availableShops:shops.map(s=>({id:s.id,title:s.title,sales_channel:s.sales_channel}))});

    const products=await pf(`/shops/${encodeURIComponent(shop.id)}/products.json?limit=50`,token) || {};
    const rows=Array.isArray(products)?products:(products.data||[]);
    return res.status(200).json({
      connected:true,
      provider:'Printify',
      shop:{id:shop.id,title:shop.title,sales_channel:shop.sales_channel},
      products:rows.map(p=>({id:p.id,title:p.title,visible:p.visible,locked:p.is_locked,images:(p.images||[]).slice(0,1),variants:(p.variants||[]).length})),
      productCount:Number(products.total||rows.length||0)
    });
  }catch(e){
    return res.status(502).json({connected:false,provider:'Printify',shopTitle:TARGET_SHOP,error:e.message||'Printify connection failed.'});
  }
};
