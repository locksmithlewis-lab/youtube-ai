const crypto = require('crypto');

const SUPABASE_URL = process.env.SUPABASE_URL || 'https://uqmnpeovwfzizajheuig.supabase.co';
const SUPABASE_PUBLISHABLE_KEY = process.env.SUPABASE_PUBLISHABLE_KEY || process.env.SUPABASE_ANON_KEY || 'sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap';
const REQUIRED_CHECKS = ['quality', 'copyright', 'visibility', 'approval'];

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

async function sb(path, options = {}, serviceKey) {
  const response = await fetch(`${SUPABASE_URL}/rest/v1/${path}`, {
    ...options,
    headers: {
      apikey: serviceKey,
      Authorization: `Bearer ${serviceKey}`,
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new Error(`Supabase request failed (${response.status})${text ? `: ${text.slice(0, 300)}` : ''}`);
  }
  const text = await response.text();
  return text ? JSON.parse(text) : null;
}

async function getUserFromBearer(bearer) {
  const response = await fetch(`${SUPABASE_URL}/auth/v1/user`, {
    headers: { apikey: SUPABASE_PUBLISHABLE_KEY, Authorization: `Bearer ${bearer}` },
  });
  if (!response.ok) return null;
  return response.json();
}

async function getAccessToken(userId, serviceKey, tokenSecret, clientId, clientSecret) {
  const rows = await sb(`youtube_oauth_tokens?user_id=eq.${userId}&select=*`, {}, serviceKey) || [];
  const row = rows[0];
  if (!row) throw new Error('Connect YouTube first.');
  const scopes = Array.isArray(row.scopes) ? row.scopes : [];
  if (!scopes.includes('https://www.googleapis.com/auth/youtube.upload')) {
    const err = new Error('Reconnect YouTube once to grant upload permission.');
    err.code = 'UPLOAD_SCOPE_MISSING';
    throw err;
  }

  let access = row.access_token_ciphertext ? decrypt(row.access_token_ciphertext, tokenSecret) : '';
  if (!access || !row.expires_at || Date.parse(row.expires_at) < Date.now() + 60000) {
    const refresh = decrypt(row.refresh_token_ciphertext, tokenSecret);
    if (!refresh) throw new Error('Reconnect YouTube to refresh access.');
    const tokenResponse = await fetch('https://oauth2.googleapis.com/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        client_id: clientId,
        client_secret: clientSecret,
        refresh_token: refresh,
        grant_type: 'refresh_token',
      }),
    });
    if (!tokenResponse.ok) throw new Error('Could not refresh YouTube access.');
    const tokenData = await tokenResponse.json();
    access = tokenData.access_token;
    if (!access) throw new Error('Google did not return a refreshed access token.');
    await sb(`youtube_oauth_tokens?user_id=eq.${userId}`, {
      method: 'PATCH',
      body: JSON.stringify({
        access_token_ciphertext: encrypt(access, tokenSecret),
        expires_at: new Date(Date.now() + Number(tokenData.expires_in || 3600) * 1000).toISOString(),
        updated_at: new Date().toISOString(),
      }),
    }, serviceKey);
  }
  return access;
}

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'POST only' });

  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  const tokenSecret = process.env.YOUTUBE_TOKEN_ENCRYPTION_KEY;
  const clientId = process.env.GOOGLE_CLIENT_ID;
  const clientSecret = process.env.GOOGLE_CLIENT_SECRET;
  if (!serviceKey || !tokenSecret || !clientId || !clientSecret) {
    return res.status(503).json({ error: 'YouTube publishing is not fully configured.' });
  }

  const bearer = String(req.headers.authorization || '').replace(/^Bearer\s+/i, '');
  if (!bearer) return res.status(401).json({ error: 'Sign in first.' });
  const user = await getUserFromBearer(bearer);
  if (!user) return res.status(401).json({ error: 'Invalid app session.' });

  const projectId = String(req.body?.projectId || '').trim();
  const privacyStatus = ['private', 'unlisted', 'public'].includes(req.body?.privacyStatus) ? req.body.privacyStatus : 'private';
  const description = String(req.body?.description || '').trim().slice(0, 5000);
  if (!projectId) return res.status(400).json({ error: 'projectId is required.' });

  try {
    const projects = await sb(`video_projects?id=eq.${encodeURIComponent(projectId)}&user_id=eq.${user.id}&select=*`, {}, serviceKey) || [];
    const project = projects[0];
    if (!project) return res.status(404).json({ error: 'Project not found.' });
    if (project.status === 'posted') return res.status(409).json({ error: 'This project is already marked posted.' });
    if (project.status !== 'ready') return res.status(409).json({ error: 'Project must pass the quality gate before publishing.' });
    if (!project.output_url) return res.status(409).json({ error: 'Project has no finished MP4.' });

    const checklist = await sb(`publish_checklist_items?project_id=eq.${projectId}&user_id=eq.${user.id}&select=item,checked`, {}, serviceKey) || [];
    const checked = new Set(checklist.filter(x => x.checked).map(x => x.item));
    const missing = REQUIRED_CHECKS.filter(item => !checked.has(item));
    if (missing.length) {
      return res.status(409).json({ error: `Complete these publishing approvals first: ${missing.join(', ')}.` });
    }

    const accessToken = await getAccessToken(user.id, serviceKey, tokenSecret, clientId, clientSecret);
    const objectPath = String(project.output_url).split('/').map(encodeURIComponent).join('/');
    const videoResponse = await fetch(`${SUPABASE_URL}/storage/v1/object/video-outputs/${objectPath}`, {
      headers: { apikey: serviceKey, Authorization: `Bearer ${serviceKey}` },
    });
    if (!videoResponse.ok) throw new Error(`Could not download rendered MP4 (${videoResponse.status}).`);
    const videoBuffer = Buffer.from(await videoResponse.arrayBuffer());
    if (!videoBuffer.length) throw new Error('Rendered MP4 is empty.');

    const title = String(project.title || 'Untitled video').trim().slice(0, 100);
    const fallbackDescription = String(project.topic || '').trim();
    const metadata = {
      snippet: {
        title,
        description: description || fallbackDescription,
        categoryId: '22',
      },
      status: {
        privacyStatus,
        selfDeclaredMadeForKids: false,
      },
    };

    const initResponse = await fetch('https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json; charset=UTF-8',
        'X-Upload-Content-Type': 'video/mp4',
        'X-Upload-Content-Length': String(videoBuffer.length),
      },
      body: JSON.stringify(metadata),
    });
    if (!initResponse.ok) {
      const text = await initResponse.text().catch(() => '');
      throw new Error(`YouTube upload could not start (${initResponse.status})${text ? `: ${text.slice(0, 400)}` : ''}`);
    }
    const uploadUrl = initResponse.headers.get('location');
    if (!uploadUrl) throw new Error('YouTube did not return an upload URL.');

    const uploadResponse = await fetch(uploadUrl, {
      method: 'PUT',
      headers: { 'Content-Type': 'video/mp4', 'Content-Length': String(videoBuffer.length) },
      body: videoBuffer,
    });
    if (!uploadResponse.ok) {
      const text = await uploadResponse.text().catch(() => '');
      throw new Error(`YouTube upload failed (${uploadResponse.status})${text ? `: ${text.slice(0, 400)}` : ''}`);
    }
    const uploaded = await uploadResponse.json();
    if (!uploaded?.id) throw new Error('YouTube upload completed without a video ID.');

    const now = new Date().toISOString();
    await sb(`video_projects?id=eq.${projectId}&user_id=eq.${user.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ status: 'posted', failure_reason: null, updated_at: now }),
    }, serviceKey);
    await sb(`project_pipeline_steps?project_id=eq.${projectId}&user_id=eq.${user.id}&step=eq.ready`, {
      method: 'PATCH',
      body: JSON.stringify({ status: 'passed', detail: `Published to YouTube as ${privacyStatus}.`, updated_at: now }),
    }, serviceKey);
    await sb('analytics_snapshots', {
      method: 'POST',
      headers: { Prefer: 'return=minimal' },
      body: JSON.stringify({
        user_id: user.id,
        project_id: projectId,
        youtube_video_id: uploaded.id,
        captured_at: now,
        raw_metrics: { source: 'youtube-publish', privacy_status: privacyStatus, title },
      }),
    }, serviceKey);
    await sb(`youtube_connections?user_id=eq.${user.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ last_sync_at: now, updated_at: now }),
    }, serviceKey);

    return res.status(200).json({
      ok: true,
      videoId: uploaded.id,
      privacyStatus,
      url: `https://www.youtube.com/watch?v=${uploaded.id}`,
    });
  } catch (error) {
    if (error?.code === 'UPLOAD_SCOPE_MISSING') return res.status(409).json({ error: error.message, reconnectRequired: true });
    console.error('youtube-publish', error);
    return res.status(500).json({ error: error?.message || 'YouTube publishing failed.' });
  }
};
