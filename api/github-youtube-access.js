const crypto = require('crypto');

const SUPABASE_URL = process.env.SUPABASE_URL || 'https://uqmnpeovwfzizajheuig.supabase.co';
const SUPABASE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;
const TOKEN_KEY = process.env.YOUTUBE_TOKEN_ENCRYPTION_KEY;
const GITHUB_REPO = 'locksmithlewis-lab/youtube-ai';

function decrypt(value) {
  const [iv, tag, data] = String(value).split('.');
  const key = crypto.createHash('sha256').update(TOKEN_KEY).digest();
  const decipher = crypto.createDecipheriv('aes-256-gcm', key, Buffer.from(iv, 'base64url'));
  decipher.setAuthTag(Buffer.from(tag, 'base64url'));
  return Buffer.concat([decipher.update(Buffer.from(data, 'base64url')), decipher.final()]).toString();
}

module.exports = async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });
  if (!SUPABASE_KEY || !TOKEN_KEY) return res.status(503).json({ error: 'YouTube credentials are not configured.' });

  const gh = req.headers.authorization || '';
  if (!gh.startsWith('Bearer ')) return res.status(401).json({ error: 'GitHub authorization required.' });

  const check = await fetch('https://api.github.com/repos/' + GITHUB_REPO, {
    headers: { Authorization: gh, Accept: 'application/vnd.github+json', 'User-Agent': 'rolixa-publisher' }
  });
  if (!check.ok) return res.status(401).json({ error: 'GitHub Actions authorization was rejected.' });

  const rowsResp = await fetch(
    SUPABASE_URL + '/rest/v1/youtube_oauth_tokens?select=refresh_token_ciphertext&order=updated_at.desc&limit=1',
    { headers: { apikey: SUPABASE_KEY, Authorization: 'Bearer ' + SUPABASE_KEY } }
  );
  if (!rowsResp.ok) return res.status(502).json({ error: 'Could not read the stored YouTube connection.' });
  const rows = await rowsResp.json();
  if (!rows[0]?.refresh_token_ciphertext) return res.status(404).json({ error: 'No connected YouTube channel found.' });

  let longLivedCredential;
  try { longLivedCredential = decrypt(rows[0].refresh_token_ciphertext); }
  catch { return res.status(500).json({ error: 'Stored YouTube credential could not be decrypted.' }); }

  const tokenResp = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: process.env.GOOGLE_CLIENT_ID,
      client_secret: process.env.GOOGLE_CLIENT_SECRET,
      grant_type: 'refresh_token',
      refresh_token: longLivedCredential
    })
  });
  const tokenBody = await tokenResp.json();
  if (!tokenResp.ok || !tokenBody.access_token) return res.status(502).json({ error: 'Google rejected the stored YouTube credential.' });

  return res.status(200).json({ access_token: tokenBody.access_token, expires_in: tokenBody.expires_in || 3600 });
};
