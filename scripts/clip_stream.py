import json, os, subprocess, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

SUPABASE_URL=os.environ.get('SUPABASE_URL','').rstrip('/')
SERVICE_KEY=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')
if not SUPABASE_URL or not SERVICE_KEY: raise SystemExit('Supabase secrets required.')
HEADERS={'apikey':SERVICE_KEY,'Authorization':f'Bearer {SERVICE_KEY}','Content-Type':'application/json'}

def req(method,path,data=None,extra=None):
    body=None if data is None else json.dumps(data).encode();h=dict(HEADERS);h.update(extra or {})
    r=urllib.request.Request(SUPABASE_URL+path,data=body,headers=h,method=method)
    with urllib.request.urlopen(r,timeout=90) as res:
        raw=res.read();return json.loads(raw.decode()) if raw else None

def patch(table,row_id,payload):return req('PATCH',f'/rest/v1/{table}?id=eq.{row_id}',payload,{'Prefer':'return=minimal'})
def pipe(pid,step,status,detail):return req('PATCH',f'/rest/v1/project_pipeline_steps?project_id=eq.{pid}&step=eq.{step}',{'status':status,'detail':detail,'updated_at':datetime.now(timezone.utc).isoformat()},{'Prefer':'return=minimal'})
def run(cmd):subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)

def upload(path,obj):
    url=SUPABASE_URL+'/storage/v1/object/video-outputs/'+urllib.parse.quote(obj,safe='/')
    with open(path,'rb') as f:
        r=urllib.request.Request(url,data=f.read(),headers={'apikey':SERVICE_KEY,'Authorization':f'Bearer {SERVICE_KEY}','Content-Type':'video/mp4','x-upsert':'true'},method='POST');urllib.request.urlopen(r,timeout=240).read()

jobs=req('GET','/rest/v1/clip_jobs?status=eq.queued&rights_confirmed=eq.true&select=*&order=created_at.asc&limit=1') or []
if not jobs: print('No queued clip jobs.');raise SystemExit(0)
job=jobs[0];started=datetime.now(timezone.utc);tick=time.monotonic();patch('clip_jobs',job['id'],{'status':'running','started_at':started.isoformat(),'updated_at':started.isoformat()})
try:
    project=(req('GET',f"/rest/v1/video_projects?id=eq.{job['project_id']}&select=*") or [None])[0]
    if not project: raise RuntimeError('Clip project not found.')
    if not job.get('rights_confirmed'): raise RuntimeError('Reuse rights were not confirmed.')
    start=float(job['start_seconds']);end=float(job['end_seconds']);length=end-start
    if length<=0 or length>600: raise RuntimeError('Clip length must be between 1 second and 10 minutes.')
    work=Path('clip-work');work.mkdir(exist_ok=True);source=work/'source.mp4';out=work/'clip.mp4'
    pipe(project['id'],'visuals','running','Capturing only the authorized source section needed for this clip.');pipe(project['id'],'edit','running','Cutting and formatting the selected highlight.')
    layout=str(job.get('source_kind') or 'vertical')
    if layout=='live-auto':
        # yt-dlp normally opens a live URL at the current live edge. Limit the downloader to a short rolling capture.
        run(['yt-dlp','--no-playlist','--downloader','ffmpeg','--downloader-args',f'ffmpeg_i:-t {length:.3f}','-f','b[height<=720]/best[height<=720]/best','--merge-output-format','mp4','-o',str(source),job['source_url']])
    else:
        section=f'*{start:.3f}-{end:.3f}'
        run(['yt-dlp','--no-playlist','--download-sections',section,'--force-keyframes-at-cuts','-f','bv*[height<=1080]+ba/b[height<=1080]/best','--merge-output-format','mp4','-o',str(source),job['source_url']])
    if not source.exists():
        candidates=list(work.glob('source.*'))
        if not candidates: raise RuntimeError('Source platform did not provide the requested clip section.')
        source=candidates[0]
    if layout in ('vertical','live-auto'):
        fc='[0:v]split=2[bg0][fg0];[bg0]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=24[bg];[fg0]scale=1020:1760:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[v]'
        run(['ffmpeg','-y','-i',str(source),'-filter_complex',fc,'-map','[v]','-map','0:a?','-c:v','libx264','-preset','veryfast','-crf','20','-c:a','aac','-b:a','192k','-movflags','+faststart','-shortest',str(out)])
    else:
        run(['ffmpeg','-y','-i',str(source),'-c:v','libx264','-preset','veryfast','-crf','20','-c:a','aac','-b:a','192k','-movflags','+faststart','-shortest',str(out)])
    run(['ffmpeg','-v','error','-i',str(out),'-f','null','-'])
    if out.stat().st_size<100000: raise RuntimeError('Clip output failed validation.')
    obj=f"{job['user_id']}/{job['project_id']}/clip-{job['id']}.mp4";upload(out,obj);done=datetime.now(timezone.utc);actual=max(.1,time.monotonic()-tick)
    patch('clip_jobs',job['id'],{'status':'completed','output_url':obj,'completed_at':done.isoformat(),'updated_at':done.isoformat(),'error':None})
    patch('video_projects',project['id'],{'output_url':obj,'status':'quality_check','failure_reason':None,'updated_at':done.isoformat()})
    req('POST','/rest/v1/render_jobs',{'user_id':job['user_id'],'project_id':project['id'],'engine':'rolixa-stream-clipper-v2','status':'completed','output_url':obj,'created_at':job['created_at'],'started_at':started.isoformat(),'completed_at':done.isoformat(),'media_duration_seconds':length,'actual_render_seconds':actual,'updated_at':done.isoformat()},{'Prefer':'return=minimal'})
    pipe(project['id'],'visuals','passed','Authorized source clip formatted successfully.');pipe(project['id'],'edit','passed',f'{length:.1f}s stream highlight rendered and decoded successfully.');print(f'Clipped {obj} in {actual:.1f}s')
except Exception as exc:
    msg=str(exc)[:1000];done=datetime.now(timezone.utc);patch('clip_jobs',job['id'],{'status':'failed','error':msg,'completed_at':done.isoformat(),'updated_at':done.isoformat()});patch('video_projects',job['project_id'],{'status':'failed','failure_reason':msg,'updated_at':done.isoformat()})
    for s in ('visuals','edit'):
        try:pipe(job['project_id'],s,'failed',msg)
        except Exception:pass
    raise
