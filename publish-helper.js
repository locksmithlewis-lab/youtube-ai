import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';

const supabaseUrl = 'https://uqmnpeovwfzizajheuig.supabase.co';
const supabaseKey = 'sb_publishable_W6N3YZeKf9iMSpQMt4Oukw_rmLfRTap';
const supabase = createClient(supabaseUrl, supabaseKey);

const workspace = document.getElementById('projectWorkspace');
let scheduled = false;
let rendering = false;

function selectedProjectId() {
  return document.querySelector('.project-button.selected')?.dataset.openProject || null;
}

function scheduleRefresh() {
  if (scheduled || rendering) return;
  scheduled = true;
  setTimeout(async () => {
    scheduled = false;
    try {
      await refreshPublishPanel();
    } catch (error) {
      console.error('publish-helper', error);
    }
  }, 80);
}

function makeStatus(text) {
  const p = document.createElement('p');
  p.className = 'status-line';
  p.textContent = text;
  return p;
}

function youtubeLink(videoId) {
  if (!/^[A-Za-z0-9_-]{6,32}$/.test(String(videoId || ''))) return null;
  return `https://www.youtube.com/watch?v=${videoId}`;
}

async function getLatestPublishedVideo(projectId) {
  const { data, error } = await supabase
    .from('analytics_snapshots')
    .select('youtube_video_id,captured_at')
    .eq('project_id', projectId)
    .not('youtube_video_id', 'is', null)
    .order('captured_at', { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) return null;
  return data?.youtube_video_id || null;
}

async function refreshPublishPanel() {
  if (!workspace) return;
  const projectId = selectedProjectId();
  if (!projectId) return;

  const existing = document.getElementById('youtubePublishPanel');
  if (existing?.dataset.projectId === projectId && existing.dataset.locked === 'true') return;

  rendering = true;
  try {
    const { data: project, error } = await supabase
      .from('video_projects')
      .select('id,title,status,output_url')
      .eq('id', projectId)
      .maybeSingle();
    if (error || !project) return;

    existing?.remove();

    const panel = document.createElement('section');
    panel.id = 'youtubePublishPanel';
    panel.dataset.projectId = projectId;
    panel.dataset.locked = 'true';
    panel.className = 'work-card wide-card';

    const eyebrow = document.createElement('div');
    eyebrow.className = 'eyebrow';
    eyebrow.textContent = 'YOUTUBE PUBLISH';
    panel.appendChild(eyebrow);

    const heading = document.createElement('h3');
    heading.textContent = 'Private upload test';
    panel.appendChild(heading);

    const copy = document.createElement('p');
    copy.className = 'muted small';
    copy.textContent = 'Uploads this finished Rolixa render to your connected YouTube channel as Private first. Nothing is made public by this test.';
    panel.appendChild(copy);

    if (project.status === 'posted') {
      const videoId = await getLatestPublishedVideo(projectId);
      const url = youtubeLink(videoId);
      if (url) {
        const link = document.createElement('a');
        link.className = 'primary compact';
        link.href = url;
        link.target = '_blank';
        link.rel = 'noopener';
        link.textContent = 'Open video on YouTube';
        panel.appendChild(link);
      } else {
        panel.appendChild(makeStatus('Posted successfully. The YouTube link is still syncing into Rolixa.'));
      }
    } else if (project.status === 'ready' && project.output_url) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'primary compact';
      button.textContent = 'Upload privately to YouTube';
      panel.appendChild(button);

      const status = makeStatus('Ready for the first real upload test.');
      panel.appendChild(status);

      button.addEventListener('click', async () => {
        button.disabled = true;
        status.textContent = 'Uploading finished MP4 to YouTube as Private…';
        try {
          const { data: { session } } = await supabase.auth.getSession();
          if (!session?.access_token) throw new Error('Your Rolixa session expired. Sign in again.');

          const response = await fetch('/api/youtube-publish', {
            method: 'POST',
            headers: {
              Authorization: `Bearer ${session.access_token}`,
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({
              projectId,
              privacyStatus: 'private',
              description: 'Created with Rolixa from a live YouTube trend signal. Original script, graphics, narration, and edit.',
            }),
          });
          const body = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(body.error || `YouTube upload failed (${response.status}).`);

          status.textContent = 'Upload confirmed by YouTube.';
          const url = youtubeLink(body.videoId) || body.url;
          if (url) {
            const link = document.createElement('a');
            link.className = 'ghost compact';
            link.href = url;
            link.target = '_blank';
            link.rel = 'noopener';
            link.textContent = 'Open private YouTube video';
            panel.appendChild(link);
          }
          button.remove();
          setTimeout(() => window.location.reload(), 1800);
        } catch (error) {
          status.textContent = error?.message || 'YouTube upload failed.';
          button.disabled = false;
        }
      });
    } else {
      panel.appendChild(makeStatus(`Project is ${project.status}. It must be Ready with a finished MP4 before YouTube upload.`));
    }

    const grid = workspace.querySelector('.work-grid');
    if (grid) grid.appendChild(panel);
    else workspace.appendChild(panel);

    const stale = [...workspace.querySelectorAll('p')].find(p => p.textContent.includes('Direct YouTube upload will remain separate until upload scope is added.'));
    if (stale) stale.textContent = 'Publishing approvals are stored per project. The first end-to-end test uploads as Private so the result can be inspected before any public release.';
  } finally {
    rendering = false;
  }
}

if (workspace) {
  const observer = new MutationObserver(scheduleRefresh);
  observer.observe(workspace, { childList: true, subtree: true });
  document.addEventListener('click', event => {
    if (event.target.closest('[data-open-project]')) scheduleRefresh();
  });
  scheduleRefresh();
}
