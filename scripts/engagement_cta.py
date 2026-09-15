"""Mandatory end-of-video Like + Subscribe CTA.

Adds a real spoken CTA and a dedicated visual end card to the finished render
before final QC. The step is intentionally fail-closed: if Piper or ffmpeg
cannot produce the CTA, the render must not proceed to publication.
"""
import json
import os
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

SUPABASE_URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
PIPER_VOICE = os.environ.get('PIPER_VOICE', 'en_US-lessac-medium')
PIPER_DATA_DIR = os.environ.get('PIPER_VOICE_DIR', '.piper-voices')
CTA_TEXT = os.environ.get(
    'ENGAGEMENT_CTA_TEXT',
    'If you enjoyed this video, hit like and subscribe for more. Thanks for watching.'
)
CTA_SECONDS = 6.5


def _headers():
    return {'apikey': KEY, 'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json'}


def _request(method, path, data=None, prefer=None):
    headers = _headers()
    if prefer:
        headers['Prefer'] = prefer
    request = urllib.request.Request(
        SUPABASE_URL + path,
        data=None if data is None else json.dumps(data).encode(),
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        raw = response.read()
        return json.loads(raw.decode()) if raw else None


def _download(obj, path):
    url = SUPABASE_URL + '/storage/v1/object/video-outputs/' + urllib.parse.quote(obj, safe='/')
    request = urllib.request.Request(url, headers={'apikey': KEY, 'Authorization': f'Bearer {KEY}'})
    with urllib.request.urlopen(request, timeout=600) as response, open(path, 'wb') as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)


def _upload(path, obj):
    url = SUPABASE_URL + '/storage/v1/object/video-outputs/' + urllib.parse.quote(obj, safe='/')
    headers = {
        'apikey': KEY,
        'Authorization': f'Bearer {KEY}',
        'Content-Type': 'video/mp4',
        'x-upsert': 'true',
    }
    with open(path, 'rb') as handle:
        request = urllib.request.Request(url, data=handle.read(), headers=headers, method='PUT')
        urllib.request.urlopen(request, timeout=600).read()


def _step(project, status, detail):
    return _request('POST', '/rest/v1/rpc/upsert_project_pipeline_step', {
        'p_user_id': project['user_id'],
        'p_project_id': project['id'],
        'p_step': 'engagement_cta',
        'p_status': status,
        'p_detail': detail,
    })


def _piper(wav_path):
    cmd = [
        'python', '-m', 'piper',
        '--model', PIPER_VOICE,
        '--data-dir', PIPER_DATA_DIR,
        '--output-file', str(wav_path),
    ]
    subprocess.run(cmd, input=CTA_TEXT.encode('utf-8'), check=True, timeout=180)


def _probe(path):
    out = subprocess.check_output([
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height', '-of', 'csv=p=0', str(path)
    ]).decode().strip().split(',')
    if len(out) != 2:
        raise RuntimeError('Could not determine source video dimensions.')
    return int(out[0]), int(out[1])


def _render_cta(src, dst, wav, width, height):
    font = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
    # Keep the final card visually unmistakable without relying on YouTube UI.
    filter_complex = (
        f"[0:v]format=yuv420p[v0];"
        f"color=c=0x101820:s={width}x{height}:r=30:d={CTA_SECONDS}[card0];"
        f"[card0]drawbox=x={int(width*.08)}:y={int(height*.34)}:w={int(width*.84)}:h={int(height*.32)}:"
        f"color=0xD71920@0.96:t=fill,"
        f"drawbox=x={int(width*.08)}:y={int(height*.34)}:w={int(width*.84)}:h={int(height*.32)}:"
        f"color=white@0.95:t=5,"
        f"drawtext=fontfile={font}:text='LIKE  +  SUBSCRIBE':fontcolor=white:"
        f"fontsize={max(38, int(width*.075))}:x=(w-text_w)/2:y={int(height*.405)},"
        f"drawtext=fontfile={font}:text='for more':fontcolor=white@0.92:"
        f"fontsize={max(28, int(width*.045))}:x=(w-text_w)/2:y={int(height*.535)}[v1];"
        f"[0:a]aresample=48000[a0];"
        f"[1:a]aresample=48000,apad=pad_dur={CTA_SECONDS},atrim=0:{CTA_SECONDS},loudnorm=I=-14:TP=-1:LRA=8[a1];"
        f"[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]"
    )
    subprocess.run([
        'ffmpeg', '-y', '-i', str(src), '-i', str(wav),
        '-filter_complex', filter_complex,
        '-map', '[v]', '-map', '[a]',
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '19',
        '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k',
        '-movflags', '+faststart', str(dst),
    ], check=True, timeout=600, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ensure_cta(obj, project_id, job_id):
    if not SUPABASE_URL or not KEY:
        raise RuntimeError('Supabase secrets required for engagement CTA.')
    project = (_request('GET', f'/rest/v1/video_projects?id=eq.{project_id}&select=*') or [None])[0]
    if not project:
        raise RuntimeError('Project disappeared before engagement CTA.')
    _step(project, 'running', 'Adding mandatory spoken Like + Subscribe CTA and visual end card.')
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            src = temp / 'source.mp4'
            wav = temp / 'cta.wav'
            dst = temp / 'cta.mp4'
            _download(obj, src)
            width, height = _probe(src)
            _piper(wav)
            _render_cta(src, dst, wav, width, height)
            _upload(dst, obj)
        _step(project, 'passed', f'Mandatory spoken CTA added: "{CTA_TEXT}" with a {CTA_SECONDS:.1f}s visual LIKE + SUBSCRIBE end card.')
        print(f'ENGAGEMENT_CTA_PASS project={project_id} job={job_id} seconds={CTA_SECONDS}')
    except Exception as exc:
        _step(project, 'failed', 'Engagement CTA failed: ' + str(exc)[:900])
        raise


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 4:
        raise SystemExit('Usage: engagement_cta.py <storage-object> <project-id> <job-id>')
    ensure_cta(sys.argv[1], sys.argv[2], sys.argv[3])
