import json
import os
import subprocess
import urllib.request
from datetime import datetime, timezone, timedelta

URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
MAX_IDLE_HOURS = float(os.environ.get('ROLIXA_MAX_IDLE_HOURS', '24'))
MIN_READY_BACKLOG = int(os.environ.get('ROLIXA_MIN_READY_BACKLOG', '3'))
STUCK_HOURS = float(os.environ.get('ROLIXA_STUCK_GENERATING_HOURS', '1.5'))
MAX_STUCK_REQUEUES = int(os.environ.get('ROLIXA_MAX_STUCK_REQUEUES', '8'))
FAIL_ON_STALL = os.environ.get('ROLIXA_WATCHDOG_FAIL_ON_STALL', '0') == '1'
if not URL or not KEY:
    raise SystemExit('Supabase secrets required.')

H = {'apikey': KEY, 'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json'}
def req(method, path, data=None, prefer=None):
    headers=dict(H)
    if prefer: headers['Prefer']=prefer
    request=urllib.request.Request(URL+path,data=None if data is None else json.dumps(data).encode(),headers=headers,method=method)
    with urllib.request.urlopen(request,timeout=60) as response:
        raw=response.read();return json.loads(raw.decode()) if raw else []
def parse_time(value):
    if not value:return None
    try:return datetime.fromisoformat(str(value).replace('Z','+00:00'))
    except ValueError:return None
def count_status(status):
    return len(req('GET',f'/rest/v1/video_projects?status=eq.{status}&select=id&limit=1000') or [])
def job_count(status):
    return len(req('GET',f'/rest/v1/render_jobs?status=eq.{status}&select=id&limit=1000') or [])
def patch_project(pid,payload):
    req('PATCH',f'/rest/v1/video_projects?id=eq.{pid}',payload,'return=minimal')
def enqueue(user_id,project_id,engine='motion-first-v13-watchdog-recovery'):
    req('POST','/rest/v1/render_jobs',{'user_id':user_id,'project_id':project_id,'engine':engine,'status':'queued'},'return=minimal')

def recover_stuck_generating(now):
    cutoff=(now-timedelta(hours=STUCK_HOURS)).isoformat()
    rows=req('GET',f'/rest/v1/video_projects?status=eq.generating&updated_at=lt.{cutoff}&select=id,user_id,title,updated_at,failure_reason,qc_attempts&order=updated_at.asc&limit={MAX_STUCK_REQUEUES}') or []
    recovered=[];held=[]
    for p in rows:
        jobs=req('GET',f"/rest/v1/render_jobs?project_id=eq.{p['id']}&status=in.(queued,processing,running)&select=id,status&limit=1") or []
        if jobs:
            held.append({'project_id':p['id'],'reason':'active_render_job_exists'});continue
        attempts=int(p.get('qc_attempts') or 0)
        if attempts>=2:
            held.append({'project_id':p['id'],'reason':'repair_limit_reached'});continue
        enqueue(p['user_id'],p['id'])
        patch_project(p['id'],{'failure_reason':'Watchdog recovered stale generating project with no active render job.','updated_at':now.isoformat()})
        recovered.append(p['id'])
    return recovered,held

def run_repair_controller():
    try:
        proc=subprocess.run(['python','scripts/repair_failed.py'],capture_output=True,text=True,timeout=420)
        return {'returncode':proc.returncode,'stdout':(proc.stdout or '')[-2000:],'stderr':(proc.stderr or '')[-1000:]}
    except Exception as exc:
        return {'returncode':-1,'error':str(exc)}

now=datetime.now(timezone.utc)
posted=req('GET','/rest/v1/video_projects?status=eq.posted&select=id,published_at,updated_at,title&order=published_at.desc&limit=1') or []
latest=posted[0] if posted else None
published_at=parse_time((latest or {}).get('published_at')) or parse_time((latest or {}).get('updated_at'))
idle_hours=None if not published_at else max(0.0,(now-published_at).total_seconds()/3600.0)
statuses={s:count_status(s) for s in ('generating','quality_check','ready','scheduled','failed')}
render_jobs={s:job_count(s) for s in ('queued','processing','running','failed')}
ready_backlog=statuses['ready']+statuses['scheduled']
stalled=idle_hours is None or idle_hours>=MAX_IDLE_HOURS
blockers=[]
if stalled:
    if sum(statuses[s] for s in ('generating','quality_check','ready','scheduled'))==0:blockers.append('queue_starved')
    if statuses['failed']>0:blockers.append('failed_projects_present')
    if statuses['quality_check']>0 and statuses['ready']==0:blockers.append('qc_bottleneck')
    if statuses['ready']>0:blockers.append('publish_bottleneck')
if ready_backlog<MIN_READY_BACKLOG:blockers.append('ready_backlog_below_target')
if statuses['generating']>0 and render_jobs['queued']+render_jobs['processing']+render_jobs['running']==0:blockers.append('generating_without_active_render_jobs')

recovery={'stuck_requeued':[],'stuck_held':[],'repair_controller':None}
if blockers:
    recovery['repair_controller']=run_repair_controller()
    recovery['stuck_requeued'],recovery['stuck_held']=recover_stuck_generating(now)

# Re-read counts after recovery so the report describes the resulting state.
statuses_after={s:count_status(s) for s in ('generating','quality_check','ready','scheduled','failed')}
render_after={s:job_count(s) for s in ('queued','processing','running','failed')}
report={'ok':not stalled and (statuses_after['ready']+statuses_after['scheduled'])>=MIN_READY_BACKLOG,'checked_at':now.isoformat(),'latest_posted_project_id':(latest or {}).get('id'),'latest_posted_title':(latest or {}).get('title'),'published_at':published_at.isoformat() if published_at else None,'idle_hours':round(idle_hours,2) if idle_hours is not None else None,'max_idle_hours':MAX_IDLE_HOURS,'minimum_ready_backlog':MIN_READY_BACKLOG,'ready_backlog':statuses_after['ready']+statuses_after['scheduled'],'status_counts_before':statuses,'status_counts_after':statuses_after,'render_job_counts_before':render_jobs,'render_job_counts_after':render_after,'blockers':sorted(set(blockers)),'recovery':recovery}
print(json.dumps(report,indent=2))
if stalled and FAIL_ON_STALL:raise SystemExit(2)
