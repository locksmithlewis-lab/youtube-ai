const crypto = require('crypto');
const SUPABASE_URL = process.env.SUPABASE_URL || 'https://uqmnpeovwfzizajheuig.supabase.co';
const SUPABASE_ANON_KEY = process.env.SUPABASE_ANON_KEY || 'sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap';

function decrypt(value, secret) {
  const [ivB64, tagB64, dataB64] = String(value || '').split('.');
  if (!ivB64 || !tagB64 || !dataB64) throw new Error('Invalid encrypted token.');
  const key = crypto.createHash('sha256').update(secret).digest();
  const decipher = crypto.createDecipheriv('aes-256-gcm', key, Buffer.from(ivB64, 'base64url'));
  decipher.setAuthTag(Buffer.from(tagB64, 'base64url'));
  return Buffer.concat([decipher.update(Buffer.from(dataB64, 'base64url')), decipher.final()]).toString('utf8');
}

function encrypt(value, secret) {
  const key = crypto.createHash('sha256').update(secret).digest();
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', key, iv);
  const ciphertext = Buffer.concat([cipher.update(value, 'utf8'), cipher.final()]);
  const tag = cipher.getAuthTag();
  return [iv.toString('base64url'), tag.toString('base64url'), ciphertext.toString('base64url')].join('.');
}

async function sb(path, options, serviceKey) {
  const r = await fetch(`${SUPABASE_URL}/rest/v1/${path}`, {
    ...options,
    headers: { apikey: serviceKey, Authorization: `Bearer ${serviceKey}`, 'Content-Type': 'application/json', ...(options?.headers || {}) },
  });
  if (!r.ok) throw new Error(`Supabase request failed (${r.status})`);
  const t = await r.text(); return t ? JSON.parse(t) : null;
}

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'POST only' });
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  const tokenSecret = process.env.YOUTUBE_TOKEN_ENCRYPTION_KEY;
  const clientId = process.env.GOOGLE_CLIENT_ID;
  const clientSecret = process.env.GOOGLE_CLIENT_SECRET;
  if (!serviceKey || !tokenSecret || !clientId || !clientSecret) return res.status(503).json({ error: 'Trend Radar is not fully configured.' });

  const bearer = String(req.headers.authorization || '').replace(/^Bearer\s+/i, '');
  if (!bearer) return res.status(401).json({ error: 'Sign in first.' });
  const userResp = await fetch(`${SUPABASE_URL}/auth/v1/user`, { headers: { apikey: SUPABASE_ANON_KEY, Authorization: `Bearer ${bearer}` } });
  if (!userResp.ok) return res.status(401).json({ error: 'Invalid session.' });
  const user = await userResp.json();

  const tokenRows = await sb(`youtube_oauth_tokens?user_id=eq.${user.id}&select=*`, {}, serviceKey) || [];
  const row = tokenRows[0];
  if (!row) return res.status(409).json({ error: 'Connect YouTube first.' });

  let access = decrypt(row.access_token_ciphertext, tokenSecret);
  if (!row.expires_at || Date.parse(row.expires_at) < Date.now() + 60000) {
    const refresh = decrypt(row.refresh_token_ciphertext, tokenSecret);
    if (!refresh) return res.status(409).json({ error: 'Reconnect YouTube to refresh access.' });
    const tr = await fetch('https://oauth2.googleapis.com/token', { method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({client_id:clientId,client_secret:clientSecret,refresh_token:refresh,grant_type:'refresh_token'}) });
    if (!tr.ok) return res.status(502).json({ error: 'Could not refresh YouTube access.' });
    const td = await tr.json(); access = td.access_token;
    await sb(`youtube_oauth_tokens?user_id=eq.${user.id}`, { method:'PATCH', body:JSON.stringify({access_token_ciphertext:encrypt(access,tokenSecret),expires_at:new Date(Date.now()+Number(td.expires_in||3600)*1000).toISOString(),updated_at:new Date().toISOString()}) }, serviceKey);
  }

  const yr = await fetch('https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics&chart=mostPopular&regionCode=US&maxResults=20', { headers:{Authorization:`Bearer ${access}`} });
  if (!yr.ok) return res.status(502).json({ error: 'YouTube trend request failed.' });
  const yd = await yr.json();
  const now = Date.now();
  const signals = (yd.items || []).map(v => {
    const ageHours = Math.max(1,(now-Date.parse(v.snippet.publishedAt))/3600000);
    const views = Number(v.statistics?.viewCount || 0);
    const velocity = views/ageHours;
    const freshness = Math.max(0,100-Math.min(100,ageHours/1.2));
    const momentum = Math.min(100,Math.log10(Math.max(10,velocity))*18);
    const score = Math.round(Math.max(0,Math.min(100,freshness*.45+momentum*.55)));
    return { user_id:user.id, source:'youtube_most_popular', topic:v.snippet.title, score, freshness:Math.round(freshness), competition:null, originality_fit:null, evidence:{video_id:v.id,channel:v.snippet.channelTitle,published_at:v.snippet.publishedAt,views,views_per_hour:Math.round(velocity),category_id:v.snippet.categoryId}, observed_at:new Date().toISOString() };
  }).sort((a,b)=>b.score-a.score).slice(0,12);

  await sb(`trend_signals?user_id=eq.${user.id}&source=eq.youtube_most_popular`, { method:'DELETE' }, serviceKey);
  if (signals.length) await sb('trend_signals', { method:'POST', headers:{Prefer:'return=representation'}, body:JSON.stringify(signals) }, serviceKey);
  res.status(200).json({ trends:signals });
};
