import json
import math
import os
import statistics
import urllib.request
from datetime import datetime, timezone

URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
if not URL or not KEY:
    raise SystemExit('Supabase secrets required.')
H = {'apikey': KEY, 'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json'}


def req(method, path, data=None, prefer=None):
    headers = dict(H)
    if prefer:
        headers['Prefer'] = prefer
    r = urllib.request.Request(
        URL + path,
        data=None if data is None else json.dumps(data).encode(),
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(r, timeout=60) as x:
        raw = x.read()
        return json.loads(raw.decode()) if raw else None


def patch(project_id, payload):
    return req('PATCH', f'/rest/v1/video_projects?id=eq.{project_id}', payload, 'return=minimal')


def latest_snapshot(project_id):
    rows = req(
        'GET',
        f'/rest/v1/analytics_snapshots?project_id=eq.{project_id}'
        '&select=views,estimated_minutes_watched,average_view_duration_seconds,likes,comments,shares,subscribers_gained,captured_at,raw_metrics'
        '&order=captured_at.desc&limit=1',
    ) or []
    return rows[0] if rows else None


def valid_retention(snapshot):
    if not snapshot:
        return False
    views = float(snapshot.get('views') or 0)
    avd = float(snapshot.get('average_view_duration_seconds') or 0)
    return views >= 3 and avd > 0


def iso_duration_seconds(value):
    text = str(value or '')
    if not text.startswith('PT'):
        return 0.0
    text = text[2:]
    hours = minutes = seconds = 0.0
    import re
    match = re.search(r'([0-9.]+)H', text)
    if match:
        hours = float(match.group(1))
    match = re.search(r'([0-9.]+)M', text)
    if match:
        minutes = float(match.group(1))
    match = re.search(r'([0-9.]+)S', text)
    if match:
        seconds = float(match.group(1))
    return hours * 3600 + minutes * 60 + seconds


def actual_duration(project, snapshot):
    raw = (snapshot or {}).get('raw_metrics') or {}
    details = raw.get('content_details') or {}
    measured = iso_duration_seconds(details.get('duration'))
    return max(1.0, measured or float(project.get('target_duration_seconds') or 60))


def performance_score(project, snapshot):
    views = float(snapshot.get('views') or 0)
    duration = actual_duration(project, snapshot)
    retention = min(1.5, float(snapshot.get('average_view_duration_seconds') or 0) / duration)
    engagement = (
        float(snapshot.get('likes') or 0)
        + 2 * float(snapshot.get('comments') or 0)
        + 3 * float(snapshot.get('shares') or 0)
        + 4 * float(snapshot.get('subscribers_gained') or 0)
    ) / max(1.0, views)
    reach = min(25.0, math.log10(max(1.0, views) + 1.0) * 9.0)
    return min(100.0, 50.0 * retention + min(25.0, engagement * 300.0) + reach)


posted = req(
    'GET',
    '/rest/v1/video_projects?status=eq.posted&select=id,style,format,target_duration_seconds&limit=500',
) or []

snapshots = {}
valid = {}
for project in posted:
    snapshot = latest_snapshot(project['id'])
    if snapshot:
        snapshots[project['id']] = snapshot
    if valid_retention(snapshot):
        valid[project['id']] = snapshot

profiles = {}
for project in posted:
    snapshot = valid.get(project['id'])
    if not snapshot:
        continue
    score = performance_score(project, snapshot)
    key = (str(project.get('style') or '').lower(), str(project.get('format') or '').lower())
    profiles.setdefault(key, []).append(score)

profile = {key: statistics.fmean(values) for key, values in profiles.items()}
future = req(
    'GET',
    '/rest/v1/video_projects?status=in.(generating,quality_check,ready,scheduled)'
    '&select=id,style,format,creative_score,quality_score,publication_priority&limit=1000',
) or []

updated = 0
now = datetime.now(timezone.utc).isoformat()
for project in future:
    base = float(project.get('creative_score') or 0) * .35 + float(project.get('quality_score') or 0) * .50
    key = (str(project.get('style') or '').lower(), str(project.get('format') or '').lower())
    learned = profile.get(key)
    bonus = 0.0 if learned is None else min(15.0, learned * .15)
    priority = round(base + bonus, 2)
    if abs(priority - float(project.get('publication_priority') or 0)) > .05:
        patch(project['id'], {'publication_priority': priority, 'updated_at': now})
        updated += 1

print(json.dumps({
    'posted_with_any_snapshot': len(snapshots),
    'posted_with_valid_retention': len(valid),
    'performance_profiles': len(profile),
    'future_projects_ranked': updated,
    'profiles': {f'{key[0]}|{key[1]}': round(value, 2) for key, value in profile.items()},
}))
