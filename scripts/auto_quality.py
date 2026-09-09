import json, os, urllib.parse, urllib.request
from datetime import datetime, timezone
SUPABASE_URL=os.environ.get('SUPABASE_URL','').rstrip('/');SERVICE_KEY=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')
if not SUPABASE_URL or not SERVICE_KEY:raise SystemExit('Supabase secrets required.')
HEADERS={'apikey':SERVICE_KEY,'Authorization':f'Bearer {SERVICE_KEY}','Content-Type':'application/json'}
def req(method,path,data=None,prefer=None):
    h=dict(HEADERS)
    if prefer:h['Prefer']=prefer
    r=urllib.request.Request(SUPABASE_URL+path,data=None if data is None else json.dumps(data).encode(),headers=h,method=method)
    with urllib.request.urlopen(r,timeout=60) as res:
        raw=res.read();return json.loads(raw.decode()) if raw else None
def patch(table,row_id,payload):return req('PATCH',f'/rest/v1/{table}?id=eq.{row_id}',payload,'return=minimal')
def is_factual(p):return str(p.get('style') or '').lower() in ('documentary','news','educational','explainer') or str(p.get('format') or '').lower()=='explainer'
def passed_step(pid,name):
    q=urllib.parse.urlencode({'project_id':f'eq.{pid}','step':f'eq.{name}','status':'eq.passed','select':'id','limit':'1'});return bool(req('GET','/rest/v1/project_pipeline_steps?'+q) or [])
def verified_sources(pid):
    q=urllib.parse.urlencode({'project_id':f'eq.{pid}','verified':'eq.true','select':'id','limit':'1'});return bool(req('GET','/rest/v1/research_sources?'+q) or [])
def completed_render(pid):
    q=urllib.parse.urlencode({'project_id':f'eq.{pid}','status':'eq.completed','select':'id','limit':'1'});return bool(req('GET','/rest/v1/render_jobs?'+q) or [])
def set_step(p,step,status,detail):return req('POST','/rest/v1/rpc/upsert_project_pipeline_step',{'p_user_id':p['user_id'],'p_project_id':p['id'],'p_step':step,'p_status':status,'p_detail':detail})
def series_order_ready(pid):
    membership=req('GET',f'/rest/v1/series_episodes?video_project_id=eq.{pid}&select=series_id,episode_number&limit=1') or []
    if not membership:return True,None
    current=membership[0];series_id=current['series_id'];episode_number=int(current['episode_number'])
    priors=req('GET',f'/rest/v1/series_episodes?series_id=eq.{series_id}&episode_number=lt.{episode_number}&select=episode_number,video_project_id&order=episode_number.asc') or []
    for prior in priors:
        rows=req('GET',f"/rest/v1/video_projects?id=eq.{prior.get('video_project_id')}&select=status,title&limit=1") or []
        if not rows or rows[0].get('status')!='posted':
            return False,f"Series continuity hold: Chapter {prior.get('episode_number')} must publish before Chapter {episode_number}."
    return True,None
rows=req('GET','/rest/v1/video_projects?status=eq.quality_check&output_url=not.is.null&select=*&order=publication_priority.desc,updated_at.asc&limit=500') or []
ready=waiting=0
for p in rows:
    try:
        if str(p.get('format') or '').lower()=='clip':
            clips=req('GET',f"/rest/v1/clip_jobs?project_id=eq.{p['id']}&select=rights_confirmed,status,decision&order=created_at.desc&limit=1") or [];c=clips[0] if clips else {};ok=bool(c.get('rights_confirmed') and c.get('status')=='completed' and c.get('decision')=='accepted');detail='Authorized clip passed rights and quality checks.' if ok else 'Clip is waiting for accepted rights-confirmed scoring.'
        else:
            rendered=bool(p.get('script') and p.get('output_url') and completed_render(p['id']));production=all(passed_step(p['id'],s) for s in ('voice','visuals','edit','creative_preflight','final_video_qc'));score_ok=float(p.get('creative_score') or 0)>=78 and float(p.get('quality_score') or 0)>=82;base=rendered and production and score_ok
            if is_factual(p):ok=base and verified_sources(p['id']);detail='Factual video passed creative, production, finished-MP4 and verified-source gates.' if ok else 'Factual video still needs verified evidence or a complete publish-grade QC pass.'
            else:ok=base;detail='Video passed creative, production and finished-MP4 QC.' if ok else 'Video is waiting for publish-grade creative/final-video approval.'
        if ok:
            ordered,hold_detail=series_order_ready(p['id'])
            if not ordered:
                ok=False;detail=hold_detail
        if ok:
            now=datetime.now(timezone.utc).isoformat();patch('video_projects',p['id'],{'status':'ready','failure_reason':None,'updated_at':now});set_step(p,'quality_check','passed',detail);set_step(p,'ready','passed',f"Ready for publishing. creative={p.get('creative_score')} quality={p.get('quality_score')} priority={p.get('publication_priority')}");ready+=1;print('READY',p['id'],p.get('title'))
        else:
            waiting+=1
            if detail and detail.startswith('Series continuity hold:'):set_step(p,'quality_check','running',detail)
            print('WAIT',p['id'],detail)
    except Exception as exc:waiting+=1;print('SKIP',p.get('id'),exc)
print(json.dumps({'checked':len(rows),'ready':ready,'waiting':waiting}))
