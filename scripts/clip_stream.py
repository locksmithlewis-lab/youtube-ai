import json, os, re, subprocess, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

SUPABASE_URL=os.environ.get('SUPABASE_URL','').rstrip('/')
SERVICE_KEY=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')
ROLIXA_BASE_URL=os.environ.get('ROLIXA_BASE_URL','https://rolixa-bey56lewis-4041.vercel.app').rstrip('/')
if not SUPABASE_URL or not SERVICE_KEY: raise SystemExit('Supabase secrets required.')
HEADERS={'apikey':SERVICE_KEY,'Authorization':f'Bearer {SERVICE_KEY}','Content-Type':'application/json'}

GOOD_PHRASES={
 'oh my god':8,'omg':8,'no way':8,'lets go':9,"let's go":9,'clutch':10,'ace':9,'headshot':8,'victory':8,'winner':7,
 'win':6,'won':6,'insane':8,'crazy':6,'unbelievable':9,'what just happened':9,'did you see':8,'got him':7,'got them':7,
 'one shot':6,'last one':7,'final kill':9,'triple':8,'quad':9,'penta':10,'comeback':9,'record':8,'world record':10,
 'boss':5,'speedrun':6,'perfect':7,'amazing':6,'hilarious':7,'funny':5,'bro':3,'dude':3,'wow':5,'yes':3
}

def req(method,path,data=None,extra=None):
    body=None if data is None else json.dumps(data).encode();h=dict(HEADERS);h.update(extra or {})
    r=urllib.request.Request(SUPABASE_URL+path,data=body,headers=h,method=method)
    with urllib.request.urlopen(r,timeout=90) as res:
        raw=res.read();return json.loads(raw.decode()) if raw else None

def patch(table,row_id,payload):return req('PATCH',f'/rest/v1/{table}?id=eq.{row_id}',payload,{'Prefer':'return=minimal'})
def pipe(pid,step,status,detail):return req('PATCH',f'/rest/v1/project_pipeline_steps?project_id=eq.{pid}&step=eq.{step}',{'status':status,'detail':detail,'updated_at':datetime.now(timezone.utc).isoformat()},{'Prefer':'return=minimal'})
def run(cmd):return subprocess.run(cmd,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)

def upload(path,obj):
    url=SUPABASE_URL+'/storage/v1/object/video-outputs/'+urllib.parse.quote(obj,safe='/')
    with open(path,'rb') as f:
        r=urllib.request.Request(url,data=f.read(),headers={'apikey':SERVICE_KEY,'Authorization':f'Bearer {SERVICE_KEY}','Content-Type':'video/mp4','x-upsert':'true'},method='POST');urllib.request.urlopen(r,timeout=240).read()

def delete_object(obj):
    if not obj:return
    url=SUPABASE_URL+'/storage/v1/object/video-outputs/'+urllib.parse.quote(obj,safe='/')
    try: urllib.request.urlopen(urllib.request.Request(url,headers={'apikey':SERVICE_KEY,'Authorization':f'Bearer {SERVICE_KEY}'},method='DELETE'),timeout=90).read()
    except Exception as exc: print(f'Could not delete {obj}: {exc}')

def transcribe(path):
    try:
        from faster_whisper import WhisperModel
        model=WhisperModel('tiny.en',device='cpu',compute_type='int8',download_root=os.environ.get('HF_HOME','.whisper-cache'))
        segments,_=model.transcribe(str(path),beam_size=1,vad_filter=True,condition_on_previous_text=False)
        text=' '.join((s.text or '').strip() for s in segments if (s.text or '').strip()).strip()
        return re.sub(r'\s+',' ',text)[:5000]
    except Exception as exc:
        print(f'Speech recognition unavailable for this clip: {exc}')
        return ''

def semantic_signal(text):
    low=' '+re.sub(r'[^a-z0-9\' ]+',' ',text.lower())+' '
    points=0;hits=[]
    for phrase,value in GOOD_PHRASES.items():
        count=low.count(' '+phrase+' ')
        if count:
            points+=min(value*count,value*2);hits.append(phrase)
    exclamatory=len(re.findall(r'\b(oh|whoa|wow|yes|no|bro|dude|wait)\b',low))
    questions=len(re.findall(r'\b(what|how|why)\b',low))
    points+=min(12,exclamatory*2)+min(6,questions)
    return min(25.0,float(points)),hits[:8]

def score_clip(path,length):
    silence=run(['ffmpeg','-hide_banner','-i',str(path),'-af','silencedetect=n=-40dB:d=0.45','-f','null','-']).stderr
    silent=sum(float(x) for x in re.findall(r'silence_duration:\s*([0-9.]+)',silence));active_ratio=max(0.0,min(1.0,1.0-silent/max(length,.1)))
    vol=run(['ffmpeg','-hide_banner','-i',str(path),'-af','volumedetect','-f','null','-']).stderr
    mm=re.search(r'mean_volume:\s*(-?[0-9.]+) dB',vol);mx=re.search(r'max_volume:\s*(-?[0-9.]+) dB',vol)
    mean_db=float(mm.group(1)) if mm else -35.0;max_db=float(mx.group(1)) if mx else -10.0
    audio_presence=max(0.0,min(1.0,(mean_db+45)/30));dynamic=max(0.0,min(1.0,(max_db-mean_db)/24))
    scene=run(['ffmpeg','-hide_banner','-i',str(path),'-vf',"select='gt(scene,0.24)',showinfo",'-an','-f','null','-']).stderr
    changes=len(re.findall(r'showinfo.* n:\s*\d+',scene));motion=min(1.0,(changes/max(length/60,.1))/10.0)
    length_fit=1.0 if 20<=length<=90 else max(.35,1-abs(length-55)/220)
    transcript=transcribe(path);semantic,hits=semantic_signal(transcript)
    energy=round((audio_presence*.55+dynamic*.45)*25,2);activity=round(active_ratio*20,2);visual=round(motion*20,2);pacing=round(length_fit*10,2)
    score=round(min(100,energy+activity+visual+pacing+semantic),1)
    return score,{'audio_energy':energy,'active_audio':activity,'visual_change':visual,'length_fit':pacing,'semantic_signal':semantic,'recognized_moments':hits,'transcript_excerpt':transcript[:800],'mean_db':mean_db,'max_db':max_db,'scene_changes':changes,'active_ratio':round(active_ratio,3)}

def auto_publish(clip_job_id):
    data=json.dumps({'clipJobId':clip_job_id}).encode();r=urllib.request.Request(ROLIXA_BASE_URL+'/api/auto-publish-clip',data=data,headers={'Authorization':f'Bearer {SERVICE_KEY}','Content-Type':'application/json'},method='POST')
    try:
        with urllib.request.urlopen(r,timeout=300) as res:
            raw=res.read();return json.loads(raw.decode()) if raw else {'ok':True}
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'Auto-publish failed ({exc.code}): {exc.read().decode(errors="ignore")[:500]}')

def prune_stream(job,watch):
    if not job.get('watch_source_id') or not job.get('stream_id'):return
    keep=max(1,int((watch or {}).get('keep_best_per_stream') or 5))
    q=urllib.parse.urlencode({'watch_source_id':f"eq.{job['watch_source_id']}",'stream_id':f"eq.{job['stream_id']}",'decision':'eq.accepted','posted_at':'is.null','select':'id,project_id,output_url,highlight_score,created_at','order':'highlight_score.desc.nullslast,created_at.desc'})
    rows=req('GET','/rest/v1/clip_jobs?'+q) or []
    for old in rows[keep:]:
        delete_object(old.get('output_url'));now=datetime.now(timezone.utc).isoformat();patch('clip_jobs',old['id'],{'decision':'pruned','output_url':None,'auto_post_eligible':False,'updated_at':now});patch('video_projects',old['project_id'],{'status':'discarded','output_url':None,'failure_reason':'Lower-ranked clip pruned automatically.','updated_at':now})

jobs=req('GET','/rest/v1/clip_jobs?status=eq.queued&rights_confirmed=eq.true&select=*&order=created_at.asc&limit=1') or []
if not jobs: print('No queued clip jobs.');raise SystemExit(0)
job=jobs[0];started=datetime.now(timezone.utc);tick=time.monotonic();patch('clip_jobs',job['id'],{'status':'running','started_at':started.isoformat(),'updated_at':started.isoformat()})
try:
    project=(req('GET',f"/rest/v1/video_projects?id=eq.{job['project_id']}&select=*") or [None])[0]
    if not project: raise RuntimeError('Clip project not found.')
    if not job.get('rights_confirmed'): raise RuntimeError('Reuse rights were not confirmed.')
    watch=None
    if job.get('watch_source_id'):watch=(req('GET',f"/rest/v1/stream_watch_sources?id=eq.{job['watch_source_id']}&select=*") or [None])[0]
    start=float(job['start_seconds']);end=float(job['end_seconds']);length=end-start
    if length<=0 or length>600: raise RuntimeError('Clip length must be between 1 second and 10 minutes.')
    work=Path('clip-work');work.mkdir(exist_ok=True);source=work/'source.mp4';out=work/'clip.mp4'
    pipe(project['id'],'visuals','running','Capturing the authorized source section.');pipe(project['id'],'edit','running','Cutting, formatting, understanding, and scoring the highlight.')
    layout=str(job.get('source_kind') or 'vertical')
    if layout=='live-auto':run(['yt-dlp','--no-playlist','--downloader','ffmpeg','--downloader-args',f'ffmpeg_i:-t {length:.3f}','-f','b[height<=720]/best[height<=720]/best','--merge-output-format','mp4','-o',str(source),job['source_url']])
    else:
        section=f'*{start:.3f}-{end:.3f}';run(['yt-dlp','--no-playlist','--download-sections',section,'--force-keyframes-at-cuts','-f','bv*[height<=1080]+ba/b[height<=1080]/best','--merge-output-format','mp4','-o',str(source),job['source_url']])
    if not source.exists():
        candidates=list(work.glob('source.*'))
        if not candidates: raise RuntimeError('Source platform did not provide the requested clip section.')
        source=candidates[0]
    if layout in ('vertical','live-auto'):
        fc='[0:v]split=2[bg0][fg0];[bg0]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=24[bg];[fg0]scale=1020:1760:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[v]'
        run(['ffmpeg','-y','-i',str(source),'-filter_complex',fc,'-map','[v]','-map','0:a?','-c:v','libx264','-preset','veryfast','-crf','20','-c:a','aac','-b:a','192k','-movflags','+faststart','-shortest',str(out)])
    else:run(['ffmpeg','-y','-i',str(source),'-c:v','libx264','-preset','veryfast','-crf','20','-c:a','aac','-b:a','192k','-movflags','+faststart','-shortest',str(out)])
    run(['ffmpeg','-v','error','-i',str(out),'-f','null','-'])
    if out.stat().st_size<100000: raise RuntimeError('Clip output failed validation.')
    score,breakdown=score_clip(out,length);threshold=float((watch or {}).get('min_clip_score') or 70);accepted=score>=threshold
    done=datetime.now(timezone.utc);actual=max(.1,time.monotonic()-tick);obj=f"{job['user_id']}/{job['project_id']}/clip-{job['id']}.mp4"
    if accepted:upload(out,obj)
    decision='accepted' if accepted else 'rejected';eligible=bool(accepted and watch and watch.get('auto_post'))
    patch('clip_jobs',job['id'],{'status':'completed','output_url':obj if accepted else None,'completed_at':done.isoformat(),'updated_at':done.isoformat(),'error':None,'highlight_score':score,'score_breakdown':breakdown,'decision':decision,'auto_post_eligible':eligible})
    patch('video_projects',project['id'],{'output_url':obj if accepted else None,'status':'ready' if accepted else 'discarded','failure_reason':None if accepted else f'Clip score {score} below {threshold} threshold.','updated_at':done.isoformat()})
    req('POST','/rest/v1/render_jobs',{'user_id':job['user_id'],'project_id':project['id'],'engine':'rolixa-stream-clipper-v4-semantic','status':'completed','output_url':obj if accepted else None,'created_at':job['created_at'],'started_at':started.isoformat(),'completed_at':done.isoformat(),'media_duration_seconds':length,'actual_render_seconds':actual,'updated_at':done.isoformat()},{'Prefer':'return=minimal'})
    recognized=', '.join(breakdown.get('recognized_moments') or []) or 'audio/visual excitement signals'
    pipe(project['id'],'visuals','passed' if accepted else 'failed','Authorized clip formatted successfully.' if accepted else f'Clip discarded: highlight score {score}/{threshold}.');pipe(project['id'],'edit','passed' if accepted else 'failed',f'Highlight score {score}/100. Recognized: {recognized}. '+('Kept.' if accepted else 'Rejected and not stored.'));pipe(project['id'],'quality_check','passed' if accepted else 'failed',f'Entertainment clip score {score}/100; threshold {threshold}.');pipe(project['id'],'ready','passed' if accepted else 'blocked','Ready for posting.' if accepted else 'Weak clip automatically discarded.')
    if accepted:
        prune_stream(job,watch)
        if eligible:
            try:
                result=auto_publish(job['id']);vid=result.get('videoId');now2=datetime.now(timezone.utc).isoformat();patch('clip_jobs',job['id'],{'posted_at':now2,'youtube_video_id':vid,'updated_at':now2});patch('video_projects',project['id'],{'status':'posted','published_at':now2,'updated_at':now2});print(f'Auto-posted {vid or job["id"]} with score {score}')
            except Exception as pubexc:
                print(str(pubexc));patch('clip_jobs',job['id'],{'error':str(pubexc)[:1000],'updated_at':datetime.now(timezone.utc).isoformat()})
    print(f'Clip {decision}: score={score}, recognized={recognized}, render={actual:.1f}s')
except Exception as exc:
    msg=str(exc)[:1000];done=datetime.now(timezone.utc);patch('clip_jobs',job['id'],{'status':'failed','error':msg,'completed_at':done.isoformat(),'updated_at':done.isoformat()});patch('video_projects',job['project_id'],{'status':'failed','failure_reason':msg,'updated_at':done.isoformat()})
    for s in ('visuals','edit'):
        try:pipe(job['project_id'],s,'failed',msg)
        except Exception:pass
    raise
