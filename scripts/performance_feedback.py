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
        '&select=views,estimated_minutes_watched,average_view_duration_seconds,likes,comments,shares,subscribers_gained,subscribers_lost,captured_at,raw_metrics'
        '&order=captured_at.desc&limit=1',
    ) or []
    return rows[0] if rows else None


def valid_snapshot(snapshot):
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


def parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None


def actual_duration(project, snapshot):
    raw = (snapshot or {}).get('raw_metrics') or {}
    details = raw.get('content_details') or {}
    measured = iso_duration_seconds(details.get('duration'))
    return max(1.0, measured or float(project.get('target_duration_seconds') or 60))


def analytics(snapshot):
    raw = (snapshot or {}).get('raw_metrics') or {}
    return raw.get('analytics') or {}


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def performance_score(project, snapshot):
    views = float(snapshot.get('views') or 0)
    duration = actual_duration(project, snapshot)
    retention = clamp(float(snapshot.get('average_view_duration_seconds') or 0) / duration, 0.0, 1.25)

    a = analytics(snapshot)
    impressions = float(a.get('impressions') or 0)
    ctr_raw = float(a.get('impressionsClickThroughRate') or 0)
    ctr = ctr_raw / 100.0 if ctr_raw > 1 else ctr_raw
    ctr = clamp(ctr, 0.0, 0.20)

    likes = float(snapshot.get('likes') or 0)
    comments = float(snapshot.get('comments') or 0)
    shares = float(snapshot.get('shares') or 0)
    subs_gained = float(snapshot.get('subscribers_gained') or 0)
    subs_lost = float(snapshot.get('subscribers_lost') or 0)
    net_subs = subs_gained - subs_lost

    engagement_rate = (likes + 2 * comments + 3 * shares) / max(1.0, views)
    subscriber_rate = max(-0.02, min(0.05, net_subs / max(1.0, views)))

    published = parse_time(project.get('published_at'))
    captured = parse_time(snapshot.get('captured_at')) or datetime.now(timezone.utc)
    age_hours = 24.0
    if published:
        age_hours = max(1.0, (captured - published).total_seconds() / 3600.0)
    views_per_hour = views / age_hours
    velocity_norm = clamp(math.log10(views_per_hour + 1.0) / 3.0)

    # Bayesian-style confidence: very small samples should not dominate ranking.
    view_confidence = views / (views + 250.0)
    impression_confidence = impressions / (impressions + 1000.0) if impressions > 0 else 0.0
    confidence = clamp(0.70 * view_confidence + 0.30 * impression_confidence)

    retention_score = 35.0 * clamp(retention / 0.75)
    ctr_score = 20.0 * clamp(ctr / 0.10) if impressions > 0 else 0.0
    engagement_score = 15.0 * clamp(engagement_rate / 0.08)
    subscriber_score = 10.0 * clamp((subscriber_rate + 0.005) / 0.025)
    velocity_score = 20.0 * velocity_norm

    observed = retention_score + ctr_score + engagement_score + subscriber_score + velocity_score
    neutral_prior = 50.0
    return clamp(neutral_prior * (1.0 - confidence) + observed * confidence, 0.0, 100.0)


posted = req(
    'GET',
    '/rest/v1/video_projects?status=eq.posted&select=id,style,format,target_duration_seconds,published_at&limit=500',
) or []

snapshots = {}
valid = {}
for project in posted:
    snapshot = latest_snapshot(project['id'])
    if snapshot:
        snapshots[project['id']] = snapshot
    if valid_snapshot(snapshot):
        valid[project['id']] = snapshot

profiles = {}
for project in posted:
    snapshot = valid.get(project['id'])
    if not snapshot:
        continue
    score = performance_score(project, snapshot)
    key = (str(project.get('style') or '').lower(), str(project.get('format') or '').lower())
    profiles.setdefault(key, []).append(score)

# Shrink small format/style profiles toward a neutral score so one lucky upload
# cannot massively reprioritize the future queue.
profile = {}
for key, values in profiles.items():
    n = len(values)
    mean = statistics.fmean(values)
    prior_weight = 4.0
    profile[key] = (mean * n + 50.0 * prior_weight) / (n + prior_weight)

future = req(
    'GET',
    '/rest/v1/video_projects?status=in.(generating,quality_check,ready,scheduled)'
    '&select=id,style,format,creative_score,quality_score,publication_priority&limit=1000',
) or []

updated = 0
now = datetime.now(timezone.utc).isoformat()
for project in future:
    base = float(project.get('creative_score') or 0) * 0.35 + float(project.get('quality_score') or 0) * 0.50
    key = (str(project.get('style') or '').lower(), str(project.get('format') or '').lower())
    learned = profile.get(key)
    bonus = 0.0 if learned is None else max(-7.5, min(15.0, (learned - 50.0) * 0.30))
    priority = round(max(0.0, min(100.0, base + bonus)), 2)
    if abs(priority - float(project.get('publication_priority') or 0)) > 0.05:
        patch(project['id'], {'publication_priority': priority, 'updated_at': now})
        updated += 1

print(json.dumps({
    'posted_with_any_snapshot': len(snapshots),
    'posted_with_valid_metrics': len(valid),
    'performance_profiles': len(profile),
    'future_projects_ranked': updated,
    'profiles': {f'{key[0]}|{key[1]}': round(value, 2) for key, value in profile.items()},
}))
