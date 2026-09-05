import json, os, subprocess, time, urllib.request
from datetime import datetime, timezone

SUPABASE_URL=os.environ.get('SUPABASE_URL','').rstrip('/')
SERVICE_KEY=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')
if not SUPABASE_URL or not SERVICE_KEY: raise SystemExit('Supabase secrets required.')
HEADERS={'apikey':SERVICE_KEY,'Authorization':f'Bearer {SERVICE_KEY}','Content-Type':'application/json'}

def req(method,path,data=None,extra=None):
    body=None if data is None else json.dumps(data).encode();h=dict(HEADERS);h.update(extra or {})
    r=urllib.request.Request(SUPABASE_URL+path,data=body,headers=h,method=method)
    with urllib.request.urlopen(r,timeout=60) as res:
        raw=res.read();return json.loads(raw.decode()) if raw else None

def patch(job_id,payload):req('PATCH',f'/rest/v1/render_jobs?id=eq.{job_id}',payload,{'Prefer':'return=minimal'})

def choose_job():
    queued=req('GET','/rest/v1/render_jobs?status=eq.queued&select=*&order=created_at.asc&limit=12') or []
    if not queued:return None,None
    for j in queued:
        rows=req('GET',f"/rest/v1/video_projects?id=eq.{j['project_id']}&select=id,format,target_duration_seconds") or []
        p=rows[0] if rows else {}
        if str(p.get('format') or '').lower()=='short' or int(p.get('target_duration_seconds') or 99999)<=90:return j,p
    j=queued[0];rows=req('GET',f"/rest/v1/video_projects?id=eq.{j['project_id']}&select=id,format,target_duration_seconds") or [];return j,(rows[0] if rows else {})

job,project=choose_job()
if not job:
    subprocess.run(['python','scripts/render_video.py'],check=True)
    raise SystemExit(0)
started=datetime.now(timezone.utc);tick=time.monotonic();patch(job['id'],{'started_at':started.isoformat()})
try:
    subprocess.run(['python','scripts/render_video.py'],check=True)
finally:
    done=datetime.now(timezone.utc);actual=max(.1,time.monotonic()-tick)
    rows=req('GET',f"/rest/v1/render_jobs?id=eq.{job['id']}&select=status") or []
    status=(rows[0] if rows else {}).get('status')
    if status in ('completed','failed'):
        patch(job['id'],{'completed_at':done.isoformat(),'actual_render_seconds':actual,'media_duration_seconds':project.get('target_duration_seconds'),'updated_at':done.isoformat()})
