import json, os, urllib.parse, urllib.request
from datetime import datetime, timezone

SUPABASE_URL=os.environ.get('SUPABASE_URL','').rstrip('/')
SERVICE_KEY=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')
if not SUPABASE_URL or not SERVICE_KEY: raise SystemExit('Supabase secrets required.')
HEADERS={'apikey':SERVICE_KEY,'Authorization':f'Bearer {SERVICE_KEY}','Content-Type':'application/json'}

def req(method,path,data=None,prefer=None):
    body=None if data is None else json.dumps(data).encode();h=dict(HEADERS)
    if prefer:h['Prefer']=prefer
    r=urllib.request.Request(SUPABASE_URL+path,data=body,headers=h,method=method)
    with urllib.request.urlopen(r,timeout=60) as res:
        raw=res.read();return json.loads(raw.decode()) if raw else None

def patch(table,row_id,payload):return req('PATCH',f'/rest/v1/{table}?id=eq.{row_id}',payload,'return=minimal')
def is_factual(p):
    style=str(p.get('style') or '').lower();fmt=str(p.get('format') or '').lower()
    return style in ('documentary','news','educational') or fmt=='explainer'

def passed_step(pid,name):
    q=urllib.parse.urlencode({'project_id':f'eq.{pid}','step':f'eq.{name}','status':'eq.passed','select':'id','limit':'1'})
    return bool(req('GET','/rest/v1/project_pipeline_steps?'+q) or [])

def verified_sources(pid):
    q=urllib.parse.urlencode({'project_id':f'eq.{pid}','verified':'eq.true','select':'id','limit':'1'})
    return bool(req('GET','/rest/v1/research_sources?'+q) or [])

def completed_render(pid):
    q=urllib.parse.urlencode({'project_id':f'eq.{pid}','status':'eq.completed','select':'id','limit':'1'})
    return bool(req('GET','/rest/v1/render_jobs?'+q) or [])

def set_step(p,step,status,detail):
    return req('POST','/rest/v1/rpc/upsert_project_pipeline_step',{'p_user_id':p['user_id'],'p_project_id':p['id'],'p_step':step,'p_status':status,'p_detail':detail})

rows=req('GET','/rest/v1/video_projects?status=eq.quality_check&output_url=not.is.null&select=*&order=updated_at.asc&limit=500') or []
ready=waiting=0
for p in rows:
    try:
        if str(p.get('format') or '').lower()=='clip':
            clips=req('GET',f"/rest/v1/clip_jobs?project_id=eq.{p['id']}&select=rights_confirmed,status,decision&order=created_at.desc&limit=1") or []
            c=clips[0] if clips else {}
            ok=bool(c.get('rights_confirmed') and c.get('status')=='completed' and c.get('decision')=='accepted')
            detail='Authorized clip passed automatic quality.' if ok else 'Clip is waiting for accepted rights-confirmed scoring.'
        else:
            rendered=bool(p.get('script') and p.get('output_url') and completed_render(p['id']))
            production=all(passed_step(p['id'],s) for s in ('voice','visuals','edit'))
            base=rendered and (production or bool(p.get('output_url')))
            if is_factual(p):
                ok=base and verified_sources(p['id'])
                detail='Factual quality passed with verified evidence and a completed render.' if ok else 'Factual video still needs verified evidence or a completed render.'
            else:
                ok=base
                detail='Rendered entertainment video passed fast automatic QC.' if ok else 'Entertainment video is waiting for a valid completed render.'
        if ok:
            now=datetime.now(timezone.utc).isoformat();patch('video_projects',p['id'],{'status':'ready','failure_reason':None,'updated_at':now});set_step(p,'quality_check','passed',detail);set_step(p,'ready','passed','Ready for publishing.');ready+=1;print('READY',p['id'],p.get('title'))
        else:
            waiting+=1;print('WAIT',p['id'],detail)
    except Exception as exc: waiting+=1;print('SKIP',p.get('id'),exc)
print(json.dumps({'checked':len(rows),'ready':ready,'waiting':waiting}))
