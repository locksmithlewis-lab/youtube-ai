import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';

const supabase = createClient(
  'https://uqmnpeovwfzizajheuig.supabase.co',
  'sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap'
);

const ALERT_ID = 'youtubeTokenAlert';
const NOTIFIED_KEY = 'rolixa-youtube-token-incident';
let checking = false;
let timer = null;

function ensureBanner() {
  let banner = document.getElementById(ALERT_ID);
  if (banner) return banner;
  const app = document.getElementById('appContent');
  if (!app) return null;

  banner = document.createElement('section');
  banner.id = ALERT_ID;
  banner.setAttribute('role', 'alert');
  banner.style.cssText = [
    'display:none',
    'margin:0 0 16px',
    'padding:16px 18px',
    'border:1px solid rgba(255,104,117,.5)',
    'border-radius:16px',
    'background:linear-gradient(180deg,rgba(58,20,28,.96),rgba(31,14,20,.96))',
    'box-shadow:0 18px 50px rgba(0,0,0,.22)'
  ].join(';');
  banner.innerHTML = `
    <div style="display:flex;gap:14px;justify-content:space-between;align-items:center;flex-wrap:wrap">
      <div style="min-width:240px;flex:1">
        <div style="font-size:11px;font-weight:900;letter-spacing:.12em;color:#ff9da6">YOUTUBE NEEDS ATTENTION</div>
        <strong style="display:block;margin:5px 0 4px">Reconnect YouTube to resume publishing</strong>
        <span id="youtubeTokenAlertMessage" style="font-size:12px;line-height:1.5;color:#d5aeb3">The saved YouTube authorization can no longer refresh automatically.</span>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button id="enableYouTubeAlertsBtn" class="ghost compact" type="button" style="display:none">Enable browser alerts</button>
        <button id="reconnectYouTubeAlertBtn" class="primary compact" type="button">Reconnect YouTube</button>
      </div>
    </div>`;
  app.prepend(banner);

  banner.querySelector('#reconnectYouTubeAlertBtn')?.addEventListener('click', reconnectYouTube);
  banner.querySelector('#enableYouTubeAlertsBtn')?.addEventListener('click', async () => {
    if (!('Notification' in window)) return;
    const permission = await Notification.requestPermission();
    updatePermissionButton();
    if (permission === 'granted') notifyBrowser('manual-permission');
  });
  return banner;
}

function updatePermissionButton() {
  const button = document.getElementById('enableYouTubeAlertsBtn');
  if (!button) return;
  button.style.display = 'Notification' in window && Notification.permission === 'default' ? '' : 'none';
}

async function reconnectYouTube() {
  const { data: { session } } = await supabase.auth.getSession();
  if (!session?.access_token) return;
  const response = await fetch('/api/youtube-start', {
    method: 'POST',
    headers: { Authorization: `Bearer ${session.access_token}` },
  });
  const body = await response.json().catch(() => ({}));
  if (response.ok && body.url) window.location.assign(body.url);
}

function notifyBrowser(incidentId) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  const prior = localStorage.getItem(NOTIFIED_KEY);
  if (prior === incidentId) return;
  new Notification('Rolixa: YouTube needs reconnection', {
    body: 'Your YouTube authorization could not be refreshed. Reconnect YouTube to resume publishing.',
    tag: 'rolixa-youtube-token',
  });
  localStorage.setItem(NOTIFIED_KEY, incidentId);
}

function showReconnectAlert(body = {}) {
  const banner = ensureBanner();
  if (!banner) return;
  banner.style.display = '';
  const message = document.getElementById('youtubeTokenAlertMessage');
  if (message) message.textContent = body.message || 'The saved YouTube authorization can no longer refresh automatically.';
  updatePermissionButton();

  const incidentId = body.incidentAt || body.reason || 'youtube-reconnect-required';
  notifyBrowser(incidentId);

  const status = document.getElementById('youtubeStatus');
  if (status) status.textContent = 'YouTube authorization needs to be refreshed.';
  const connect = document.getElementById('connectYouTubeBtn');
  if (connect) connect.textContent = 'Reconnect YouTube';
  const badge = document.getElementById('connectionBadge');
  if (badge) badge.textContent = 'YouTube reconnect required';
}

function clearReconnectAlert() {
  const banner = document.getElementById(ALERT_ID);
  if (banner) banner.style.display = 'none';
  localStorage.removeItem(NOTIFIED_KEY);
}

async function checkTokenHealth() {
  if (checking) return;
  checking = true;
  try {
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) {
      clearReconnectAlert();
      return;
    }
    const response = await fetch('/api/youtube-token-health', {
      method: 'POST',
      headers: { Authorization: `Bearer ${session.access_token}` },
    });
    const body = await response.json().catch(() => ({}));
    if (body.reconnectRequired) showReconnectAlert(body);
    else if (response.ok) clearReconnectAlert();
  } catch (error) {
    console.error('youtube-token-health', error);
  } finally {
    checking = false;
  }
}

function startMonitoring() {
  ensureBanner();
  updatePermissionButton();
  checkTokenHealth();
  if (timer) clearInterval(timer);
  timer = setInterval(checkTokenHealth, 60 * 1000);
}

supabase.auth.onAuthStateChange((_event, session) => {
  if (session) startMonitoring();
  else clearReconnectAlert();
});

document.addEventListener('visibilitychange', () => {
  if (!document.hidden) checkTokenHealth();
});
window.addEventListener('focus', checkTokenHealth);

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', startMonitoring, { once: true });
else startMonitoring();
