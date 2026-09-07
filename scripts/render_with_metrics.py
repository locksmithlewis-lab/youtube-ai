import json, os, re, subprocess, tempfile, urllib.parse, urllib.request
from pathlib import Path
from production_guard import creative_preflight, final_video_qc, publication_priority

URL=os.environ.get('SUPABASE_URL','').rstrip('/');KEY=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')
H={'apikey':KEY,'Authorization':f'Bearer {KEY}','Content-Type':'application/json'}
def req(method,path,data=None,prefer=None):
    h=dict(H)
    if prefer:h['Prefer']=prefer
    r=urllib.request.Request(URL+path,data=None if data is None else json.dumps(data).encode(),headers=h,method=method)
    with urllib.request.urlopen(r,timeout=120) as x:
        raw=x.read();return json.loads(raw.decode()) if raw else None

def patch(table,id,data):return req('PATCH',f'/rest/v1/{table}?id=eq.{id}',data,'return=minimal')
def step(p,name,status,detail):return req('POST','/rest/v1/rpc/upsert_project_pipeline_step',{'p_user_id':p['user_id'],'p_project_id':p['id'],'p_step':name,'p_status':status,'p_detail':detail})
def report(p,job,stage,result):return req('POST','/rest/v1/video_quality_reports',{'user_id':p['user_id'],'project_id':p['id'],'render_job_id':job.get('id') if job else None,'stage':stage,'passed':result['passed'],'score':result['score'],'reasons':result.get('reasons') or [],'metrics':result.get('metrics') or {}},'return=minimal')

def preflight_queue():
    jobs=req('GET','/rest/v1/render_jobs?status=eq.queued&select=id,project_id,user_id&order=created_at.asc&limit=12') or []
    for j in jobs:
        rows=req('GET',f"/rest/v1/video_projects?id=eq.{j['project_id']}&select=*") or []
        if not rows:continue
        p=rows[0];result=creative_preflight(p);report(p,j,'creative_preflight',result);patch('video_projects',p['id'],{'creative_score':result['score'],'updated_at':'now()'});step(p,'creative_preflight','passed' if result['passed'] else 'failed',f"Creative score {result['score']}/100. "+('; '.join(result['reasons']) if result['reasons'] else 'Hook, script structure, rhythm and originality passed.'))
        if not result['passed']:
            reason='Creative preflight failed: '+('; '.join(result['reasons']) or 'score below threshold');patch('render_jobs',j['id'],{'status':'failed','error':reason,'completed_at':'now()','updated_at':'now()'});patch('video_projects',p['id'],{'status':'failed','failure_reason':reason,'updated_at':'now()'})

def download_output(obj,path):
    u=URL+'/storage/v1/object/video-outputs/'+urllib.parse.quote(obj,safe='/');r=urllib.request.Request(u,headers={'apikey':KEY,'Authorization':f'Bearer {KEY}'})
    with urllib.request.urlopen(r,timeout=600) as x,open(path,'wb') as f:
        while True:
            b=x.read(1024*1024)
            if not b:break
            f.write(b)

def upload_output(obj,path):
    u=URL+'/storage/v1/object/video-outputs/'+urllib.parse.quote(obj,safe='/')
    with open(path,'rb') as f:
        r=urllib.request.Request(u,data=f.read(),headers={'apikey':KEY,'Authorization':f'Bearer {KEY}','Content-Type':'video/mp4','x-upsert':'true'},method='POST');urllib.request.urlopen(r,timeout=600).read()

def media_duration(path):return float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(path)]).decode().strip())
def add_sound_design(src,dst,longform=False):
    dur=max(1.0,media_duration(src));bed=.55 if longform else .75
    filt=f"[1:a]lowpass=f=420,highpass=f=45,volume=0.07,afade=t=in:st=0:d={bed},afade=t=out:st={max(0,dur-bed):.3f}:d={bed}[bed];[0:a][bed]amix=inputs=2:duration=first:weights='1 0.34',acompressor=threshold=-16dB:ratio=1.6:attack=8:release=180,loudnorm=I=-14:TP=-1:LRA=8[mix]"
    subprocess.run(['ffmpeg','-y','-i',str(src),'-f','lavfi','-i',f'anoisesrc=color=pink:amplitude=0.025:sample_rate=48000:d={dur:.3f}','-filter_complex',filt,'-map','0:v','-map','[mix]','-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart',str(dst)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def post_render_qc(project_id,job_id,obj):
    p=(req('GET',f'/rest/v1/video_projects?id=eq.{project_id}&select=*') or [None])[0];j=(req('GET',f'/rest/v1/render_jobs?id=eq.{job_id}&select=*') or [None])[0]
    if not p or not j:raise RuntimeError('Finished render record disappeared before final QC.')
    assets=req('GET',f'/rest/v1/visual_assets?render_job_id=eq.{job_id}&select=provider,media_type,relevance_score,scene_index') or []
    with tempfile.TemporaryDirectory() as d:
        raw=Path(d)/'raw.mp4';master=Path(d)/'master.mp4';download_output(obj,raw);longform=int(p.get('target_duration_seconds') or 0)>120 or str(p.get('format') or '').lower() in ('long','longform','full','youtube','youtube video','full video','long form','long-form');add_sound_design(raw,master,longform);upload_output(obj,master);step(p,'sound_design','passed','Added a subtle locally generated ambience bed, narration-safe compression and final loudness mastering.');result=final_video_qc(master,p,assets)
    report(p,j,'final_video_qc',result);creative=float(p.get('creative_score') or 0);priority=publication_priority(p,creative,result['score']);patch('video_projects',p['id'],{'quality_score':result['score'],'publication_priority':priority,'status':'quality_check' if result['passed'] else 'failed','failure_reason':None if result['passed'] else 'Final video QC failed: '+'; '.join(result['reasons']),'updated_at':'now()'});step(p,'final_video_qc','passed' if result['passed'] else 'failed',f"Finished-video score {result['score']}/100. "+('; '.join(result['reasons']) if result['reasons'] else 'Actual MP4 passed motion, freeze, black-frame, silence, duration, aspect-ratio, sound-master and integrity checks.'))
    if not result['passed']:raise RuntimeError('Final video QC failed: '+'; '.join(result['reasons']))
    print(f'FINAL_QC_PASS project={project_id} score={result["score"]} priority={priority}')

preflight_queue();p=subprocess.run(['python','scripts/render_video.py'],capture_output=True,text=True);text=(p.stdout or '')+(p.stderr or '');print(text,end='')
if p.returncode:raise SystemExit(p.returncode)
matches=re.findall(r'Rendered\s+([^/\s]+/([^/\s]+)/([^/:\s]+)\.mp4):',text)
if not matches:raise SystemExit(0)
obj,project_id,job_id=matches[-1];post_render_qc(project_id,job_id,obj)
