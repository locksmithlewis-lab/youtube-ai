const crypto = require('crypto');

const SUPABASE_URL = process.env.SUPABASE_URL || 'https://uqmnpeovwfzizajheuig.supabase.co';
const SUPABASE_PUBLISHABLE_KEY = process.env.SUPABASE_PUBLISHABLE_KEY || process.env.SUPABASE_ANON_KEY || 'sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap';

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
  return [iv.toString('base64url'), cipher.getAuthTag().toString('base64url'), ciphertext.toString('base64url')].join('.');
}

async function sb(path, options, serviceKey) {
  const response = await fetch(`${SUPABASE_URL}/rest/v1/${path}`, {
    ...(options || {}),
    headers: {
      apikey: serviceKey,
      Authorization: `Bearer ${serviceKey}`,
      'Content-Type': 'application/json',
      ...(options?.headers || {}),
    },
  });
  if (!response.ok) throw new Error(`Supabase request failed (${response.status})`);
  const text = await response.text();
  return text ? JSON.parse(text) : null;
}

async function getConnection(userId, serviceKey) {
  const rows = await sb(`youtube_connections?user_id=eq.${encodeURIComponent(userId)}&select=*`, {}, serviceKey) || [];
  return rows[0] || null;
}

async function markConnectionStatus(userId, status, serviceKey) {
  const current = await getConnection(userId, serviceKey);
  if (!current || current.status === status) return current;
  const now = new Date().toISOString();
  const rows = await sb(`youtube_connections?user_id=eq.${encodeURIComponent(userId)}`, {
    method: 'PATCH',
    headers: { Prefer: 'return=representation' },
    body: JSON.stringify({ status, updated_at: now }),
  }, serviceKey) || [];
  return rows[0] || { ...current, status, updated_at: now };
}

async function tokenHealth(user, res, clientId) {
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  const tokenSecret = process.env.YOUTUBE_TOKEN_ENCRYPTION_KEY;
  const clientSecret = process.env.GOOGLE_CLIENT_SECRET;
  if (!serviceKey || !tokenSecret || !clientId || !clientSecret) {
    return res.status(503).json({ error: 'YouTube token monitoring is not fully configured.' });
  }

  const rows = await sb(`youtube_oauth_tokens?user_id=eq.${encodeURIComponent(user.id)}&select=*`, {}, serviceKey) || [];
  const row = rows[0];
  const conn = await getConnection(user.id, serviceKey);
  if (!row) {
    return res.status(200).json({ ok: true, connected: false, reconnectRequired: false, status: conn?.status || 'not_connected' });
  }

  const needsRefresh = !row.access_token_ciphertext || !row.expires_at || Date.parse(row.expires_at) < Date.now() + 5 * 60 * 1000;
  if (!needsRefresh) {
    if (conn?.status === 'reconnect_required') await markConnectionStatus(user.id, 'connected', serviceKey);
    return res.status(200).json({ ok: true, connected: true, reconnectRequired: false, refreshed: false, expiresAt: row.expires_at });
  }

  let refreshToken;
  try {
    refreshToken = decrypt(row.refresh_token_ciphertext, tokenSecret);
  } catch {
    const marked = await markConnectionStatus(user.id, 'reconnect_required', serviceKey);
    return res.status(409).json({
      ok: false,
      reconnectRequired: true,
      reason: 'stored_refresh_token_invalid',
      incidentAt: marked?.updated_at || new Date().toISOString(),
      message: 'YouTube needs to be reconnected before publishing can continue.',
    });
  }

  const tokenResp = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: clientId,
      client_secret: clientSecret,
      refresh_token: refreshToken,
      grant_type: 'refresh_token',
    }),
  });

  if (!tokenResp.ok) {
    let googleError = {};
    try { googleError = await tokenResp.json(); } catch {}
    const marked = await markConnectionStatus(user.id, 'reconnect_required', serviceKey);
    console.error('YouTube refresh rejected', {
      status: tokenResp.status,
      error: googleError.error || 'refresh_failed',
      description: googleError.error_description || null,
      user_id: user.id,
    });
    return res.status(409).json({
      ok: false,
      reconnectRequired: true,
      reason: googleError.error || 'refresh_failed',
      incidentAt: marked?.updated_at || new Date().toISOString(),
      message: 'YouTube authorization expired or was revoked. Reconnect YouTube to resume publishing.',
    });
  }

  const tokens = await tokenResp.json();
  if (!tokens.access_token) {
    const marked = await markConnectionStatus(user.id, 'reconnect_required', serviceKey);
    return res.status(409).json({
      ok: false,
      reconnectRequired: true,
      reason: 'missing_access_token',
      incidentAt: marked?.updated_at || new Date().toISOString(),
      message: 'Google did not return a usable YouTube access token. Reconnect YouTube.',
    });
  }

  const expiresAt = new Date(Date.now() + Number(tokens.expires_in || 3600) * 1000).toISOString();
  await sb(`youtube_oauth_tokens?user_id=eq.${encodeURIComponent(user.id)}`, {
    method: 'PATCH',
    body: JSON.stringify({
      access_token_ciphertext: encrypt(tokens.access_token, tokenSecret),
      expires_at: expiresAt,
      updated_at: new Date().toISOString(),
    }),
  }, serviceKey);
  await markConnectionStatus(user.id, 'connected', serviceKey);
  return res.status(200).json({ ok: true, connected: true, reconnectRequired: false, refreshed: true, expiresAt });
}

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const clientId = String(process.env.GOOGLE_CLIENT_ID || '').trim();
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

  if (String(req.body?.action || '').toLowerCase() === 'health') {
    return tokenHealth(user, res, clientId);
  }

  const stateSecret = process.env.YOUTUBE_OAUTH_STATE_SECRET;
  const appUrl = requestOrigin(req) || String(process.env.APP_URL || '').replace(/\/$/, '');
  if (!clientId || !stateSecret || !appUrl) {
    return res.status(503).json({ error: 'YouTube OAuth is not configured yet.' });
  }
  if (!looksLikeGoogleWebClientId(clientId)) {
    return res.status(503).json({ error: 'GOOGLE_CLIENT_ID is invalid. In Vercel, use the Web application OAuth Client ID ending in .apps.googleusercontent.com — not the client secret, API key, or Supabase client ID.' });
  }

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
      'https://www.googleapis.com/auth/youtube.force-ssl',
      'https://www.googleapis.com/auth/yt-analytics.readonly',
    ].join(' '),
    state,
  });

  return res.status(200).json({ url: `https://accounts.google.com/o/oauth2/v2/auth?${params}` });
};
