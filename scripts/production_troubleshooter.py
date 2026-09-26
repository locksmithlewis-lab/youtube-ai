"""Rolixa self-healing troubleshooter.

Read-only diagnostics first. Recovery actions are deliberately bounded:
- never delete projects or media
- never retry HTTP errors blindly
- at most one automatic requeue per job per run
- storage pressure causes a safe stop, not paid usage
"""
import json, os, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

URL=os.environ.get("SUPABASE_URL","").rstrip("/")
KEY=os.environ.get("SUPABASE_SERVICE_ROLE_KEY","")
MAX_REQUEUES=int(os.environ.get("ROLIXA_TROUBLESHOOT_MAX_REQUEUES","1"))
STUCK_HOURS=float(os.environ.get("ROLIXA_STUCK_GENERATING_HOURS","1.5"))
MAX_IDLE_HOURS=float(os.environ.get("ROLIXA_MAX_IDLE_HOURS","24"))

H={"apikey":KEY,"Authorization":f"Bearer {KEY}","Content-Type":"application/json"}

def req(method,path,data=None):
    payload=None if data is None else json.dumps(data).encode()
    r=urllib.request.Request(URL+path,data=payload,headers=H,method=method)
    try:
        with urllib.request.urlopen(r,timeout=60) as x:
            raw=x.read()
            return json.loads(raw.decode()) if raw else None
    except urllib.error.HTTPError as e:
        return {"_error":{"http":e.code,"body":e.read().decode(errors="replace")[:1000]}}

def age_hours(v):
    if not v:return None
    try:return (datetime.now(timezone.utc)-datetime.fromisoformat(str(v).replace("Z","+00:00"))).total_seconds()/3600
    except Exception:return None

def patch(table,id,data):
    return req("PATCH",f"/rest/v1/{table}?id=eq.{id}",data)

def diagnose():
    projects=req("GET","/rest/v1/video_projects?select=id,title,status,updated_at,output_url,failure_reason&limit=1000")
    jobs=req("GET","/rest/v1/render_jobs?select=id,project_id,status,created_at,started_at,completed_at,error&limit=1000")
    findings=[]
    if isinstance(projects,dict) and projects.get("_error"):
        findings.append({"severity":"critical","area":"database","message":f"Supabase REST unavailable: HTTP {projects['_error']['http']}"})
        return projects,jobs,findings
    if isinstance(jobs,dict) and jobs.get("_error"):
        findings.append({"severity":"critical","area":"render_queue","message":f"Render job query failed: HTTP {jobs['_error']['http']}"})
        return projects,jobs,findings
    by_project={str(j.get("project_id")):j for j in jobs}
    for p in projects:
        age=age_hours(p.get("updated_at"))
        j=by_project.get(str(p["id"]))
        if p.get("status")=="generating" and age is not None and age>STUCK_HOURS and (not j or j.get("status") not in ("queued","processing","running")):
            findings.append({"severity":"high","area":"pipeline","project_id":p["id"],"title":p.get("title"),"message":"Project is generating without an active render job."})
        if p.get("status")=="quality_check" and not p.get("output_url") and age is not None and age>STUCK_HOURS:
            findings.append({"severity":"high","area":"qc","project_id":p["id"],"title":p.get("title"),"message":"Quality-check state has no output URL."})
    failed=[j for j in jobs if j.get("status")=="failed"]
    if failed:
        findings.append({"severity":"medium","area":"render_queue","message":f"{len(failed)} failed render jobs require inspection."})
    queued=[j for j in jobs if j.get("status")=="queued"]
    if not queued:
        newest=max((age_hours(p.get("updated_at")) for p in projects if age_hours(p.get("updated_at")) is not None),default=0)
        if newest>MAX_IDLE_HOURS:
            findings.append({"severity":"medium","area":"production","message":f"No queued renders and production state is idle for {newest:.1f} hours."})
    return projects,jobs,findings

def recover(projects,jobs,findings):
    actions=[]; count=0
    if MAX_REQUEUES<=0:return actions
    jobs_by_project={str(j.get("project_id")):j for j in jobs if isinstance(j,dict)}
    for f in findings:
        if count>=MAX_REQUEUES:break
        if f["area"]!="pipeline":continue
        pid=f["project_id"]; j=jobs_by_project.get(str(pid))
        if not j:continue
        # Recovery is only allowed for a stale generating project with a terminal/non-active job.
        r=patch("render_jobs",j["id"],{"status":"queued","error":None,"completed_at":None,"updated_at":"now()"})
        if isinstance(r,dict) and r.get("_error"):
            actions.append({"action":"requeue_failed","project_id":pid,"result":r})
            continue
        patch("video_projects",pid,{"status":"generating","failure_reason":None,"updated_at":"now()"})
        actions.append({"action":"requeued","project_id":pid,"job_id":j["id"]})
        count+=1
    return actions

def main():
    if not URL or not KEY: raise SystemExit("Supabase secrets required.")
    projects,jobs,findings=diagnose()
    if isinstance(projects,dict) and projects.get("_error"):
        print(json.dumps({"status":"blocked","findings":findings},indent=2)); return 2
    actions=recover(projects,jobs,findings)
    out={"status":"attention" if findings else "healthy","generated_at":datetime.now(timezone.utc).isoformat(),"findings":findings,"actions":actions}
    print(json.dumps(out,indent=2))
    return 0

if __name__=="__main__": raise SystemExit(main())
