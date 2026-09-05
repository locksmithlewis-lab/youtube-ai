const crypto = require('crypto');

const SUPABASE_URL = process.env.SUPABASE_URL || 'https://uqmnpeovwfzizajheuig.supabase.co';
const SUPABASE_PUBLISHABLE_KEY = process.env.SUPABASE_PUBLISHABLE_KEY || 'sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap';

function base64url(input) {
  return Buffer.from(input).toString('base64url');
}

function sign(payload, secret) {
  return crypto.createHmac('sha256', secret).update(payload).digest('base64url');
}

function looksLikeGoogleWebClientId(value) {
  return /^\d+-[a-z0-9_-]+\.apps\.googleusercontent\.com$/i.test(String(value || '').trim());
}

function requestOrigin(req) {
  const host = String(req.headers['x-forwarded-host'] || req.headers.host || '').split(',')[0].trim();
  if (!host) return '';
  const proto = String(req.headers['x-forwarded-proto'] || 'https').split(',')[0].trim();
  return `${proto}://${host}`.replace(/\/$/, '');
}

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const clientId = String(process.env.GOOGLE_CLIENT_ID || '').trim();
  const stateSecret = process.env.YOUTUBE_OAUTH_STATE_SECRET;
  const appUrl = requestOrigin(req) || String(process.env.APP_URL || '').replace(/\/$/, '');
  if (!clientId || !stateSecret || !appUrl) {
    return res.status(503).json({ error: 'YouTube OAuth is not configured yet.' });
  }
  if (!looksLikeGoogleWebClientId(clientId)) {
    return res.status(503).json({ error: 'GOOGLE_CLIENT_ID is invalid. In Vercel, use the Web application OAuth Client ID ending in .apps.googleusercontent.com — not the client secret, API key, or Supabase client ID.' });
  }

  const auth = req.headers.authorization || '';
  const accessToken = auth.startsWith('Bearer ') ? auth.slice(7) : '';
  if (!accessToken) return res.status(401).json({ error: 'Sign in first.' });

  const userResp = await fetch(`${SUPABASE_URL}/auth/v1/user`, {
    headers: {
      apikey: SUPABASE_PUBLISHABLE_KEY,
      Authorization: `Bearer ${accessToken}`,
    },
  });
  if (!userResp.ok) return res.status(401).json({ error: 'Invalid app session.' });
  const user = await userResp.json();

  const stateData = {
    uid: user.id,
    nonce: crypto.randomBytes(18).toString('base64url'),
    exp: Date.now() + 10 * 60 * 1000,
  };
  const encoded = base64url(JSON.stringify(stateData));
  const state = `${encoded}.${sign(encoded, stateSecret)}`;

  const redirectUri = `${appUrl}/api/youtube-callback`;
  const params = new URLSearchParams({
    client_id: clientId,
    redirect_uri: redirectUri,
    response_type: 'code',
    access_type: 'offline',
    prompt: 'consent',
    include_granted_scopes: 'true',
    scope: [
      'https://www.googleapis.com/auth/youtube.readonly',
      'https://www.googleapis.com/auth/youtube.upload',
      'https://www.googleapis.com/auth/yt-analytics.readonly',
    ].join(' '),
    state,
  });

  return res.status(200).json({ url: `https://accounts.google.com/o/oauth2/v2/auth?${params}` });
};
