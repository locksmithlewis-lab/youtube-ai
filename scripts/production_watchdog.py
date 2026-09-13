import json
import os
import urllib.request
from datetime import datetime, timezone

URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
MAX_IDLE_HOURS = float(os.environ.get('ROLIXA_MAX_IDLE_HOURS', '24'))
MIN_READY_BACKLOG = int(os.environ.get('ROLIXA_MIN_READY_BACKLOG', '3'))
if not URL or not KEY:
    raise SystemExit('Supabase secrets required.')

H = {'apikey': KEY, 'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json'}

def req(path):
    request = urllib.request.Request(URL + path, headers=H, method='GET')
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read()
        return json.loads(raw.decode()) if raw else []

def parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None

def count_status(status):
    rows = req(f'/rest/v1/video_projects?status=eq.{status}&select=id&limit=1000') or []
    return len(rows)

now = datetime.now(timezone.utc)
posted = req('/rest/v1/video_projects?status=eq.posted&select=id,published_at,updated_at,title&order=published_at.desc&limit=1') or []
latest = posted[0] if posted else None
published_at = parse_time((latest or {}).get('published_at')) or parse_time((latest or {}).get('updated_at'))
idle_hours = None if not published_at else max(0.0, (now - published_at).total_seconds() / 3600.0)

statuses = {s: count_status(s) for s in ('generating','quality_check','ready','scheduled','failed')}
ready_backlog = statuses['ready'] + statuses['scheduled']
stalled = idle_hours is None or idle_hours >= MAX_IDLE_HOURS

blockers = []
if stalled:
    if sum(statuses[s] for s in ('generating','quality_check','ready','scheduled')) == 0:
        blockers.append('queue_starved')
    if statuses['failed'] > 0:
        blockers.append('failed_projects_present')
    if statuses['quality_check'] > 0 and statuses['ready'] == 0:
        blockers.append('qc_bottleneck')
    if statuses['ready'] > 0:
        blockers.append('publish_bottleneck')
if ready_backlog < MIN_READY_BACKLOG:
    blockers.append('ready_backlog_below_target')

report = {
    'ok': not stalled and ready_backlog >= MIN_READY_BACKLOG,
    'checked_at': now.isoformat(),
    'latest_posted_project_id': (latest or {}).get('id'),
    'latest_posted_title': (latest or {}).get('title'),
    'published_at': published_at.isoformat() if published_at else None,
    'idle_hours': round(idle_hours, 2) if idle_hours is not None else None,
    'max_idle_hours': MAX_IDLE_HOURS,
    'minimum_ready_backlog': MIN_READY_BACKLOG,
    'ready_backlog': ready_backlog,
    'status_counts': statuses,
    'blockers': sorted(set(blockers)),
}
print(json.dumps(report, indent=2))
if stalled:
    raise SystemExit(2)
