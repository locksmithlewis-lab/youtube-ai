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

def has_hook(pid):
    q=urllib.parse.urlencode({'project_id':f'eq.{pid}','selected':'eq.true','select':'id','limit':'1'})
    return bool(req('GET','/rest/v1/hook_variants?'+q) or [])

def verified_sources(pid):
    q=urllib.parse.urlencode({'project_id':f'eq.{pid}','verified':'eq.true','select':'id'})
    return len(req('GET','/rest/v1/research_sources?'+q) or [])

def set_step(p,step,status,detail):
    req('POST','/rest/v1/project_pipeline_steps',{'user_id':p['user_id'],'project_id':p['id'],'step':step,'status':status,'detail':detail,'updated_at':datetime.now(timezone.utc).isoformat()},'resolution=merge-duplicates,return=minimal')

rows=req('GET','/rest/v1/video_projects?status=eq.quality_check&output_url=not.is.null&select=*&order=updated_at.asc&limit=50') or []
for p in rows:
    try:
        if str(p.get('format') or '').lower()=='clip':
            clips=req('GET',f"/rest/v1/clip_jobs?project_id=eq.{p['id']}&select=rights_confirmed,status,decision&order=created_at.desc&limit=1") or []
            c=clips[0] if clips else {}
            ok=bool(c.get('rights_confirmed') and c.get('status')=='completed' and c.get('decision')=='accepted')
            detail='Authorized clip passed automatic entertainment quality.' if ok else 'Clip is waiting for successful highlight scoring.'
        else:
            base=bool(p.get('script') and has_hook(p['id']) and all(passed_step(p['id'],s) for s in ('voice','visuals','edit')))
            if is_factual(p):
                ok=base and verified_sources(p['id'])>0
                detail='Factual quality passed with verified evidence.' if ok else 'Factual video still needs verified evidence and completed production steps.'
            else:
                ok=base
                detail='Entertainment quality passed automatically: hook, script, voice, visuals, edit, and render are complete.' if ok else 'Entertainment video is still missing a completed production requirement.'
        if ok:
            now=datetime.now(timezone.utc).isoformat();patch('video_projects',p['id'],{'status':'ready','failure_reason':None,'updated_at':now});set_step(p,'quality_check','passed',detail);set_step(p,'ready','passed','Ready for publishing.');print('READY',p['id'],p.get('title'))
        else:
            print('WAIT',p['id'],detail)
    except Exception as exc: print('SKIP',p.get('id'),exc)
