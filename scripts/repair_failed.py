import json, os, urllib.parse, urllib.request
from datetime import datetime, timezone

SUPABASE_URL=os.environ.get('SUPABASE_URL','').rstrip('/');KEY=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')
if not SUPABASE_URL or not KEY:raise SystemExit('Supabase secrets required.')
H={'apikey':KEY,'Authorization':f'Bearer {KEY}','Content-Type':'application/json'}
def req(method,path,data=None,prefer=None):
    h=dict(H)
    if prefer:h['Prefer']=prefer
    r=urllib.request.Request(SUPABASE_URL+path,data=None if data is None else json.dumps(data).encode(),headers=h,method=method)
    with urllib.request.urlopen(r,timeout=60) as x:
        raw=x.read();return json.loads(raw.decode()) if raw else None

def patch(table,id,payload):return req('PATCH',f'/rest/v1/{table}?id=eq.{id}',payload,'return=minimal')
def report(p,passed,score,reasons,metrics=None):
    return req('POST','/rest/v1/video_quality_reports',{'user_id':p['user_id'],'project_id':p['id'],'stage':'repair_controller','passed':passed,'score':score,'reasons':reasons,'metrics':metrics or {}},'return=minimal')

rows=req('GET','/rest/v1/video_projects?status=eq.failed&select=*&order=updated_at.asc&limit=100') or []
repairable=('visual','motion','image','provider','download','429','403','timeout','ffmpeg','decode','audio','silence','freeze','black frame','render','size validation')
script_faults=('script too','production directions','template phrasing','narrative beats','opening hook','factual','verified evidence')
requeued=discarded=waiting=0
for p in rows:
    reason=str(p.get('failure_reason') or '').lower();attempts=int(p.get('qc_attempts') or 0)
    if attempts>=2:
        report(p,False,0,['automatic repair limit reached'],{'previous_failure':reason,'attempts':attempts});discarded+=1;continue
    if any(x in reason for x in script_faults):
        report(p,False,20,['content problem requires rewrite before rerender'],{'previous_failure':reason,'attempts':attempts});waiting+=1;continue
    if not any(x in reason for x in repairable):
        report(p,False,30,['failure is not safely auto-repairable'],{'previous_failure':reason,'attempts':attempts});waiting+=1;continue
    now=datetime.now(timezone.utc).isoformat();patch('video_projects',p['id'],{'status':'generating','output_url':None,'scheduled_publish_at':None,'failure_reason':f'Automatic repair attempt {attempts+1}: rebuilding failed media/edit components.','qc_attempts':attempts+1,'updated_at':now});req('POST','/rest/v1/render_jobs',{'user_id':p['user_id'],'project_id':p['id'],'engine':'motion-first-repair','status':'queued'},'return=minimal');report(p,True,60,['repairable failure requeued'],{'previous_failure':reason,'attempt':attempts+1});requeued+=1
print(json.dumps({'failed_checked':len(rows),'requeued':requeued,'rewrite_needed':waiting,'repair_limit_reached':discarded}))
