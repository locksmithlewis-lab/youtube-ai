import json, os, subprocess, urllib.parse, urllib.request
from datetime import datetime, timezone

SUPABASE_URL=os.environ.get('SUPABASE_URL','').rstrip('/')
SERVICE_KEY=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')
if not SUPABASE_URL or not SERVICE_KEY: raise SystemExit('Supabase secrets required.')
HEADERS={'apikey':SERVICE_KEY,'Authorization':f'Bearer {SERVICE_KEY}','Content-Type':'application/json'}

def req(method,path,data=None,prefer=None):
    body=None if data is None else json.dumps(data).encode(); h=dict(HEADERS)
    if prefer: h['Prefer']=prefer
    r=urllib.request.Request(SUPABASE_URL+path,data=body,headers=h,method=method)
    with urllib.request.urlopen(r,timeout=90) as res:
        raw=res.read(); return json.loads(raw.decode()) if raw else None

def probe(url):
    p=subprocess.run(['yt-dlp','--flat-playlist','--playlist-end','15','--dump-single-json','--skip-download',url],capture_output=True,text=True,timeout=90)
    if p.returncode!=0: return []
    try: data=json.loads(p.stdout)
    except Exception: return []
    entries=data.get('entries') if isinstance(data,dict) else None
    if not entries: entries=[data]
    out=[]
    for e in entries or []:
        if not isinstance(e,dict): continue
        live=e.get('is_live') is True or e.get('live_status')=='is_live'
        if not live: continue
        vid=str(e.get('id') or '').strip()
        webpage=str(e.get('webpage_url') or e.get('url') or '').strip()
        if webpage and not webpage.startswith('http') and vid:
            webpage=f'https://www.youtube.com/watch?v={vid}'
        if not webpage: continue
        out.append({'id':vid or webpage,'url':webpage,'title':str(e.get('title') or 'Live stream').strip()})
    return out

sources=req('GET','/rest/v1/stream_watch_sources?enabled=eq.true&rights_confirmed=eq.true&select=*&order=created_at.asc') or []
if not sources:
    print('No authorized stream watch sources.'); raise SystemExit(0)
now=datetime.now(timezone.utc)
for s in sources:
    try:
        live=probe(s['source_url'])
        if not live:
            print(f"No live stream: {s['label']}"); continue
        for item in live:
            every=max(5,int(s.get('clip_every_minutes') or 15))
            bucket=int(now.timestamp()//(every*60))
            window_key=f'{bucket}'
            qs=urllib.parse.urlencode({'watch_source_id':f"eq.{s['id']}",'stream_id':f"eq.{item['id']}",'window_key':f'eq.{window_key}','select':'id'})
            existing=req('GET','/rest/v1/stream_watch_events?'+qs) or []
            if existing: continue
            event=(req('POST','/rest/v1/stream_watch_events',{
                'user_id':s['user_id'],'watch_source_id':s['id'],'stream_id':item['id'],'stream_url':item['url'],'status':'live','window_key':window_key,'observed_at':now.isoformat(),'clip_queued':bool(s.get('auto_clip'))
            },'return=representation') or [None])[0]
            req('PATCH',f"/rest/v1/stream_watch_sources?id=eq.{s['id']}",{'last_seen_live_at':now.isoformat(),'last_stream_id':item['id'],'last_stream_url':item['url'],'updated_at':now.isoformat()},'return=minimal')
            if not s.get('auto_clip'): continue
            length=max(15,min(180,int(s.get('clip_length_seconds') or 60)))
            project=(req('POST','/rest/v1/video_projects',{
                'user_id':s['user_id'],'title':f"{s['label']} — live clip candidate {now.strftime('%H:%M UTC')}",'topic':f"Live highlight candidate from authorized source {s['label']}",'format':'Clip','style':'Gaming','target_duration_seconds':length,'status':'generating','hook':'Live highlight candidate','script':'Authorized live-source highlight candidate captured automatically.'
            },'return=representation') or [None])[0]
            if not project: continue
            steps=[
                {'user_id':s['user_id'],'project_id':project['id'],'step':'research','status':'passed','detail':'No factual research required for entertainment clip; source reuse rights confirmed.'},
                {'user_id':s['user_id'],'project_id':project['id'],'step':'script','status':'passed','detail':'Entertainment clip uses authorized source audio/video.'},
                {'user_id':s['user_id'],'project_id':project['id'],'step':'voice','status':'passed','detail':'Original live audio retained.'},
                {'user_id':s['user_id'],'project_id':project['id'],'step':'visuals','status':'running','detail':'Capturing current authorized live segment.'},
                {'user_id':s['user_id'],'project_id':project['id'],'step':'edit','status':'running','detail':'Formatting candidate highlight.'},
                {'user_id':s['user_id'],'project_id':project['id'],'step':'quality_check','status':'pending'},
                {'user_id':s['user_id'],'project_id':project['id'],'step':'ready','status':'pending'}]
            req('POST','/rest/v1/project_pipeline_steps',steps,'return=minimal')
            req('POST','/rest/v1/hook_variants',{'user_id':s['user_id'],'project_id':project['id'],'hook':'Live highlight candidate','selected':True},'return=minimal')
            req('POST','/rest/v1/clip_jobs',{'user_id':s['user_id'],'project_id':project['id'],'source_url':item['url'],'start_seconds':0,'end_seconds':length,'source_kind':'live-auto','rights_confirmed':True,'status':'queued'},'return=minimal')
            print(f"Queued live candidate from {s['label']}: {item['title']}")
    except Exception as exc:
        print(f"Watch source {s.get('id')} skipped: {exc}")
