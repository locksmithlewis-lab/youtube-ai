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

def status(job_id):
    rows=req('GET',f'/rest/v1/render_jobs?id=eq.{job_id}&select=status') or []
    return (rows[0] if rows else {}).get('status')

job,project=choose_job()
if not job:
    subprocess.run(['python','scripts/render_video.py'],check=True)
    raise SystemExit(0)
started=datetime.now(timezone.utc);tick=time.monotonic();patch(job['id'],{'started_at':started.isoformat()})
proc=subprocess.Popen(['python','scripts/render_video.py'])
try:
    while proc.poll() is None:
        time.sleep(1)
        if status(job['id'])=='canceled':
            print(f"Cancel requested for render {job['id']}; stopping renderer.")
            proc.terminate()
            try: proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill();proc.wait()
            break
    if proc.returncode not in (0,None,-15) and status(job['id'])!='canceled':
        raise subprocess.CalledProcessError(proc.returncode,['python','scripts/render_video.py'])
finally:
    done=datetime.now(timezone.utc);actual=max(.1,time.monotonic()-tick);state=status(job['id'])
    if state in ('completed','failed','canceled'):
        patch(job['id'],{'completed_at':done.isoformat(),'actual_render_seconds':actual,'media_duration_seconds':project.get('target_duration_seconds'),'updated_at':done.isoformat()})
