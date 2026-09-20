import json, os, urllib.request, urllib.error
from datetime import datetime, timezone

URL=os.environ.get("SUPABASE_URL","").rstrip("/")
KEY=os.environ.get("SUPABASE_SERVICE_ROLE_KEY","")
if not URL or not KEY: raise SystemExit("Supabase secrets required.")
H={"apikey":KEY,"Authorization":f"Bearer {KEY}","Content-Type":"application/json"}

def get(path):
    req=urllib.request.Request(URL+path,headers=H,method="GET")
    try:
        with urllib.request.urlopen(req,timeout=60) as r:
            return json.loads(r.read().decode()) if r.readable() else []
    except urllib.error.HTTPError as e:
        body=e.read().decode(errors="replace")
        return {"_error":{"http":e.code,"body":body}}

def rows(table,select,limit=1000):
    r=get(f"/rest/v1/{table}?select={select}&limit={limit}")
    return r if isinstance(r,list) else r

def main():
    projects=rows("video_projects","id,status,created_at,updated_at,published_at,creative_score,quality_score",1000)
    jobs=rows("render_jobs","id,status,created_at,started_at,completed_at,error",1000)
    snaps=rows("analytics_snapshots","project_id,views,likes,comments,subscribers_gained,captured_at",5000)
    report={"generated_at":datetime.now(timezone.utc).isoformat()}
    if not isinstance(projects,list) or not isinstance(jobs,list):
        report["backend"]="blocked"
        report["projects"]=projects if not isinstance(projects,list) else {"count":len(projects)}
        report["jobs"]=jobs if not isinstance(jobs,list) else {"count":len(jobs)}
        print(json.dumps(report,indent=2)); return
    counts={}
    for p in projects: counts[p["status"]]=counts.get(p["status"],0)+1
    job_counts={}
    for j in jobs: job_counts[j["status"]]=job_counts.get(j["status"],0)+1
    latest={}
    if isinstance(snaps,list):
        for s in snaps:
            pid=s.get("project_id")
            if pid and pid not in latest: latest[pid]=s
    views=sum(int(x.get("views") or 0) for x in latest.values())
    report.update({"backend":"ok","projects_total":len(projects),"project_status":counts,"render_jobs_total":len(jobs),"render_job_status":job_counts,"latest_snapshot_projects":len(latest),"latest_total_views":views,"attention":[]})
    if counts.get("failed",0): report["attention"].append("failed_projects")
    if counts.get("generating",0) and not any(job_counts.get(x,0) for x in ("queued","processing","running")): report["attention"].append("generating_without_active_jobs")
    if counts.get("ready",0)+counts.get("scheduled",0)<3: report["attention"].append("ready_backlog_below_3")
    if job_counts.get("failed",0): report["attention"].append("failed_render_jobs")
    print(json.dumps(report,indent=2))
if __name__=="__main__": main()
