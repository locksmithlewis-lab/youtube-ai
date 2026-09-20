import json, os, urllib.request
from datetime import datetime, timezone

URL=os.environ.get("SUPABASE_URL","").rstrip("/")
KEY=os.environ.get("SUPABASE_SERVICE_ROLE_KEY","")
if not URL or not KEY: raise SystemExit("Supabase secrets required.")
H={"apikey":KEY,"Authorization":f"Bearer {KEY}"}
req=urllib.request.Request(URL+"/rest/v1/video_projects?status=eq.posted&select=id,title,topic,format,output_url,thumbnail_url,published_at&order=published_at.desc&limit=20",headers=H)
with urllib.request.urlopen(req,timeout=60) as r: projects=json.loads(r.read().decode())
platforms=["youtube_shorts","tiktok","instagram_reels","facebook_reels","x_video"]
manifest=[]
for p in projects:
    manifest.append({"project_id":p["id"],"title":p.get("title"),"source_url":p.get("output_url"),"thumbnail_url":p.get("thumbnail_url"),"platforms":platforms,"status":"ready_for_platform_adapter","created_at":datetime.now(timezone.utc).isoformat()})
print(json.dumps({"generated_at":datetime.now(timezone.utc).isoformat(),"items":manifest},indent=2))
