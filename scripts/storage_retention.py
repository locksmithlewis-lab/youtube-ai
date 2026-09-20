import json, os, re
from datetime import datetime, timezone, timedelta
import urllib.error, urllib.parse, urllib.request

URL=os.environ.get("SUPABASE_URL","").rstrip("/")
KEY=os.environ.get("SUPABASE_SERVICE_ROLE_KEY","")
BUCKET=os.environ.get("ROLIXA_STORAGE_BUCKET","video-outputs")
RETENTION_DAYS=int(os.environ.get("ROLIXA_ARCHIVE_AFTER_DAYS","7"))
KEEP_VIEWS=int(os.environ.get("ROLIXA_KEEP_VIEWS","100"))
DRY_RUN=os.environ.get("ROLIXA_RETENTION_DRY_RUN","0")=="1"

if not URL or not KEY:
    raise SystemExit("Supabase secrets required.")

HEADERS={"apikey":KEY,"Authorization":f"Bearer {KEY}","Content-Type":"application/json"}

def get(path):
    req=urllib.request.Request(URL+path,headers=HEADERS,method="GET")
    with urllib.request.urlopen(req,timeout=90) as r:
        return json.loads(r.read().decode()) if r.readable() else []

def delete_objects(paths):
    if not paths:return
    body=json.dumps({"prefixes":paths}).encode()
    req=urllib.request.Request(f"{URL}/storage/v1/object/{BUCKET}",data=body,headers=HEADERS,method="DELETE")
    with urllib.request.urlopen(req,timeout=120) as r:
        return r.read().decode()

def dt(v):
    if not v:return None
    return datetime.fromisoformat(str(v).replace("Z","+00:00"))

def object_path(value):
    if not value:return None
    s=str(value)
    marker=f"/storage/v1/object/public/{BUCKET}/"
    if marker in s:return urllib.parse.unquote(s.split(marker,1)[1].split("?",1)[0])
    marker=f"/storage/v1/object/{BUCKET}/"
    if marker in s:return urllib.parse.unquote(s.split(marker,1)[1].split("?",1)[0])
    # The renderer stores object paths directly.
    if s.endswith(".mp4") and "/" in s and not s.startswith("http"):return s.split("?",1)[0]
    return None

cutoff=datetime.now(timezone.utc)-timedelta(days=RETENTION_DAYS)
projects=get("/rest/v1/video_projects?status=eq.posted&select=id,title,output_url,published_at,updated_at&limit=1000") or []
analytics=get("/rest/v1/analytics_snapshots?select=project_id,views,captured_at&order=captured_at.desc&limit=5000") or []
latest={}
for row in analytics:
    pid=row.get("project_id")
    if pid and pid not in latest: latest[pid]=row

candidates=[]
for p in projects:
    published=dt(p.get("published_at")) or dt(p.get("updated_at"))
    if not published or published>=cutoff: continue
    a=latest.get(p["id"])
    # Missing analytics is intentionally conservative: keep the archive.
    if not a or int(a.get("views") or 0)>=KEEP_VIEWS: continue
    path=object_path(p.get("output_url"))
    if not path or not path.lower().endswith(".mp4"): continue
    candidates.append({"project_id":p["id"],"title":p.get("title"),"views":int(a.get("views") or 0),"published_at":published.isoformat(),"path":path})

print(json.dumps({"mode":"dry-run" if DRY_RUN else "delete","cutoff":cutoff.isoformat(),"retention_days":RETENTION_DAYS,"keep_views":KEEP_VIEWS,"candidates":len(candidates),"items":candidates},indent=2))
if DRY_RUN or not candidates: raise SystemExit(0)

paths=[x["path"] for x in candidates]
for i in range(0,len(paths),1000):
    delete_objects(paths[i:i+1000])
print(json.dumps({"deleted_storage_objects":len(paths),"database_rows_changed":0,"youtube_uploads_changed":0}))
