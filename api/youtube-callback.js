const crypto = require('crypto');

const SUPABASE_URL = process.env.SUPABASE_URL || 'https://uqmnpeovwfzizajheuig.supabase.co';

function sign(payload, secret) {
  return crypto.createHmac('sha256', secret).update(payload).digest('base64url');
}

function safeEqual(a, b) {
  try {
    return crypto.timingSafeEqual(Buffer.from(a), Buffer.from(b));
  } catch {
    return false;
  }
}

function encrypt(value, secret) {
  const key = crypto.createHash('sha256').update(secret).digest();
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', key, iv);
  const ciphertext = Buffer.concat([cipher.update(value, 'utf8'), cipher.final()]);
  const tag = cipher.getAuthTag();
  return [iv.toString('base64url'), tag.toString('base64url'), ciphertext.toString('base64url')].join('.');
}

async function supabaseRest(path, method, body, serviceKey, extraHeaders = {}) {
  const response = await fetch(`${SUPABASE_URL}/rest/v1/${path}`, {
    method,
    headers: {
      apikey: serviceKey,
      Authorization: `Bearer ${serviceKey}`,
      'Content-Type': 'application/json',
      Prefer: 'resolution=merge-duplicates,return=representation',
      ...extraHeaders,
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(`Supabase request failed (${response.status})`);
  const text = await response.text();
  return text ? JSON.parse(text) : null;
}

module.exports = async function handler(req, res) {
  const appUrl = process.env.APP_URL;
  const clientId = process.env.GOOGLE_CLIENT_ID;
  const clientSecret = process.env.GOOGLE_CLIENT_SECRET;
  const stateSecret = process.env.YOUTUBE_OAUTH_STATE_SECRET;
  const tokenSecret = process.env.YOUTUBE_TOKEN_ENCRYPTION_KEY;
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

  if (!appUrl || !clientId || !clientSecret || !stateSecret || !tokenSecret || !serviceKey) {
    return res.status(503).send('YouTube OAuth is not fully configured.');
  }

  const { code, state, error } = req.query || {};
  if (error) return res.redirect(`${appUrl}/?youtube=denied`);
  if (!code || !state || !String(state).includes('.')) return res.status(400).send('Missing OAuth response.');

  const [encoded, signature] = String(state).split('.');
  const expected = sign(encoded, stateSecret);
  if (!safeEqual(signature, expected)) return res.status(400).send('Invalid OAuth state.');

  let stateData;
  try {
    stateData = JSON.parse(Buffer.from(encoded, 'base64url').toString('utf8'));
  } catch {
    return res.status(400).send('Invalid OAuth state payload.');
  }
  if (!stateData.uid || !stateData.exp || Date.now() > stateData.exp) return res.status(400).send('OAuth state expired.');

  const redirectUri = `${appUrl.replace(/\/$/, '')}/api/youtube-callback`;
  const tokenResp = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      code: String(code),
      client_id: clientId,
      client_secret: clientSecret,
      redirect_uri: redirectUri,
      grant_type: 'authorization_code',
    }),
  });
  if (!tokenResp.ok) return res.status(502).send('Google token exchange failed.');
  const tokens = await tokenResp.json();
  if (!tokens.access_token) return res.status(502).send('Google did not return an access token.');

  const channelResp = await fetch('https://www.googleapis.com/youtube/v3/channels?part=id,snippet&mine=true', {
    headers: { Authorization: `Bearer ${tokens.access_token}` },
  });
  if (!channelResp.ok) return res.status(502).send('Could not read your YouTube channel.');
  const channelData = await channelResp.json();
  const channel = channelData.items?.[0];
  if (!channel) return res.status(400).send('No YouTube channel was found for this Google account.');

  const scopeList = String(tokens.scope || '').split(' ').filter(Boolean);
  const expiresAt = new Date(Date.now() + Number(tokens.expires_in || 3600) * 1000).toISOString();
  const existingRows = await supabaseRest(`youtube_oauth_tokens?user_id=eq.${stateData.uid}&select=refresh_token_ciphertext`, 'GET', null, serviceKey) || [];
  const refreshTokenCiphertext = tokens.refresh_token
    ? encrypt(tokens.refresh_token, tokenSecret)
    : existingRows[0]?.refresh_token_ciphertext;
  if (!refreshTokenCiphertext) {
    return res.status(502).send('Google did not return a refresh token. Reconnect YouTube and approve access again.');
  }

  const tokenRecord = {
    user_id: stateData.uid,
    refresh_token_ciphertext: refreshTokenCiphertext,
    access_token_ciphertext: encrypt(tokens.access_token, tokenSecret),
    expires_at: expiresAt,
    scopes: scopeList,
    updated_at: new Date().toISOString(),
  };

  await supabaseRest('youtube_oauth_tokens?on_conflict=user_id', 'POST', tokenRecord, serviceKey);
  await supabaseRest('youtube_connections?on_conflict=user_id', 'POST', {
    user_id: stateData.uid,
    channel_id: channel.id,
    channel_title: channel.snippet?.title || null,
    scopes: scopeList,
    credential_ref: `youtube_oauth_tokens:${stateData.uid}`,
    connected_at: new Date().toISOString(),
    status: 'connected',
    updated_at: new Date().toISOString(),
  }, serviceKey);

  return res.redirect(`${appUrl}/?youtube=connected`);
};
