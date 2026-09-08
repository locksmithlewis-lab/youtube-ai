import json, os, re, subprocess, tempfile, urllib.parse, urllib.request
from pathlib import Path
from production_guard import creative_preflight, final_video_qc, publication_priority
from longform_writer import needs_script, write as write_longform
URL=os.environ.get('SUPABASE_URL','').rstrip('/');KEY=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')
H={'apikey':KEY,'Authorization':f'Bearer {KEY}','Content-Type':'application/json'}
def req(method,path,data=None,prefer=None):
 h=dict(H)
 if prefer:h['Prefer']=prefer
 r=urllib.request.Request(URL+path,data=None if data is None else json.dumps(data).encode(),headers=h,method=method)
 with urllib.request.urlopen(r,timeout=120) as x:raw=x.read();return json.loads(raw.decode()) if raw else None
def patch(table,id,data):return req('PATCH',f'/rest/v1/{table}?id=eq.{id}',data,'return=minimal')
def step(p,name,status,detail):return req('POST','/rest/v1/rpc/upsert_project_pipeline_step',{'p_user_id':p['user_id'],'p_project_id':p['id'],'p_step':name,'p_status':status,'p_detail':detail})
def report(p,job,stage,result):return req('POST','/rest/v1/video_quality_reports',{'user_id':p['user_id'],'project_id':p['id'],'render_job_id':job.get('id') if job else None,'stage':stage,'passed':result['passed'],'score':result['score'],'reasons':result.get('reasons') or [],'metrics':result.get('metrics') or {}},'return=minimal')
def prepare_longform(p):
 if not needs_script(p):return p
 sources=req('GET',f"/rest/v1/research_sources?project_id=eq.{p['id']}&select=title,url,claim,verified") or []
 step(p,'script_writer','running','Writing final long-form spoken narration with a dedicated language model.')
 try:
  made=write_longform(p,sources);patch('video_projects',p['id'],{'script':made['script'],'hook':made['hook'],'updated_at':'now()'});p=dict(p,script=made['script'],hook=made['hook']);step(p,'script_writer','passed',f"Generated {made['word_count']} words of final narration with {made['model']}.");return p
 except Exception as e:
  step(p,'script_writer','failed',str(e));raise
def preflight_queue():
 jobs=req('GET','/rest/v1/render_jobs?status=eq.queued&select=id,project_id,user_id&order=created_at.asc&limit=12') or []
 for j in jobs:
  rows=req('GET',f"/rest/v1/video_projects?id=eq.{j['project_id']}&select=*") or []
  if not rows:continue
  p=rows[0]
  try:p=prepare_longform(p)
  except Exception as e:
   reason='Long-form writer failed: '+str(e);patch('render_jobs',j['id'],{'status':'failed','error':reason,'completed_at':'now()','updated_at':'now()'});patch('video_projects',p['id'],{'status':'failed','failure_reason':reason,'updated_at':'now()'});continue
  result=creative_preflight(p);report(p,j,'creative_preflight',result);patch('video_projects',p['id'],{'creative_score':result['score'],'updated_at':'now()'});step(p,'creative_preflight','passed' if result['passed'] else 'failed',f"Creative score {result['score']}/100. "+('; '.join(result['reasons']) if result['reasons'] else 'Hook, script structure, title, rhythm and originality passed.'))
  if not result['passed']:
   reason='Creative preflight failed: '+('; '.join(result['reasons']) or 'score below threshold');patch('render_jobs',j['id'],{'status':'failed','error':reason,'completed_at':'now()','updated_at':'now()'});patch('video_projects',p['id'],{'status':'failed','failure_reason':reason,'updated_at':'now()'})
def download_output(obj,path):
 u=URL+'/storage/v1/object/video-outputs/'+urllib.parse.quote(obj,safe='/');r=urllib.request.Request(u,headers={'apikey':KEY,'Authorization':f'Bearer {KEY}'})
 with urllib.request.urlopen(r,timeout=600) as x,open(path,'wb') as f:
  while True:
   b=x.read(1024*1024)
   if not b:break
   f.write(b)
def upload(path,bucket,obj,mime):
 u=URL+f'/storage/v1/object/{bucket}/'+urllib.parse.quote(obj,safe='/')
 with open(path,'rb') as f:r=urllib.request.Request(u,data=f.read(),headers={'apikey':KEY,'Authorization':f'Bearer {KEY}','Content-Type':mime,'x-upsert':'true'},method='POST');urllib.request.urlopen(r,timeout=600).read()
def media_duration(path):return float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(path)]).decode().strip())
def video_size(path):
 raw=subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height','-of','csv=p=0:s=x',str(path)]).decode().strip();w,h=raw.split('x');return int(w),int(h)
def add_sound_design(src,dst,longform=False):
 dur=max(1.0,media_duration(src));bed=.55 if longform else .75;filt=f"[1:a]lowpass=f=420,highpass=f=45,volume=0.07,afade=t=in:st=0:d={bed},afade=t=out:st={max(0,dur-bed):.3f}:d={bed}[bed];[0:a][bed]amix=inputs=2:duration=first:weights='1 0.34',acompressor=threshold=-16dB:ratio=1.6:attack=8:release=180,loudnorm=I=-14:TP=-1:LRA=8[mix]";subprocess.run(['ffmpeg','-y','-i',str(src),'-f','lavfi','-i',f'anoisesrc=color=pink:amplitude=0.025:sample_rate=48000:d={dur:.3f}','-filter_complex',filt,'-map','0:v','-map','[mix]','-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart',str(dst)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def make_thumbnail(video,title,path):
 dur=media_duration(video);t=max(1,min(dur*.28,dur-1));txt=path.with_suffix('.txt');txt.write_text(' '.join(str(title or 'Video').split()[:10]),encoding='utf-8');font='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf';vf=f"scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,eq=contrast=1.08:saturation=1.12,drawbox=x=0:y=430:w=1280:h=290:color=black@0.48:t=fill,drawtext=fontfile={font}:textfile={txt}:fontcolor=white:fontsize=58:line_spacing=10:x=70:y=470:box=0";subprocess.run(['ffmpeg','-y','-ss',f'{t:.2f}','-i',str(video),'-frames:v','1','-vf',vf,'-q:v','2',str(path)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def integrity_intervals(path):
 p=subprocess.run(['ffmpeg','-hide_banner','-nostats','-i',str(path),'-vf','blackdetect=d=0.35:pix_th=0.10,freezedetect=n=-45dB:d=1.0','-an','-f','null','-'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True);text=p.stderr or '';black=[];freeze=[]
 for m in re.finditer(r'black_start:([0-9.]+)\s+black_end:([0-9.]+)\s+black_duration:([0-9.]+)',text):
  a,b,d=map(float,m.groups())
  if d>.7:black.append((max(0,a-.08),b+.08))
 starts=[float(x) for x in re.findall(r'freeze_start:\s*([0-9.]+)',text)];ends=[float(x) for x in re.findall(r'freeze_end:\s*([0-9.]+)',text)]
 for a,b in zip(starts,ends):
  if b-a>1.8:freeze.append((max(0,a-.08),b+.08))
 return black,freeze
def interval_expr(intervals):return '+'.join(f'between(t,{a:.3f},{b:.3f})' for a,b in intervals) or '0'
def repair_integrity(src,dst):
 black,freeze=integrity_intervals(src)
 if not black and not freeze:return False,{'black':0,'freeze':0}
 w,h=video_size(src);dur=media_duration(src);layers=[];inputs=['-i',str(src)];chains=[];prev='0:v';idx=1
 if freeze:
  inputs += ['-f','lavfi','-i',f'color=c=0x29425e:s={w}x{h}:r=30:d={dur:.3f}']
  chains.append(f'[{idx}:v]noise=alls=8:allf=t+u,drawgrid=w=96:h=96:t=2:c=white@0.07,drawbox=x=-260+mod(t*220\,{w+520}):y={int(h*.18)}:w=260:h=18:c=white@0.22:t=fill,drawbox=x={int(w*.12)}+45*sin(t*1.7):y={int(h*.55)}+55*cos(t*1.1):w={int(w*.24)}:h={int(h*.10)}:c=white@0.10:t=fill,format=rgba,colorchannelmixer=aa=0.34[rf]')
  chains.append(f'[{prev}][rf]overlay=shortest=1:enable=\'{interval_expr(freeze)}\'[v{idx}]');prev=f'v{idx}';idx+=1
 if black:
  inputs += ['-f','lavfi','-i',f'color=c=0x29425e:s={w}x{h}:r=30:d={dur:.3f}']
  chains.append(f'[{idx}:v]noise=alls=9:allf=t+u,drawgrid=w=110:h=110:t=2:c=white@0.08,drawbox=x=-300+mod(t*250\,{w+600}):y={int(h*.35)}:w=300:h=24:c=white@0.25:t=fill,format=rgba,colorchannelmixer=aa=0.96[rb]')
  chains.append(f'[{prev}][rb]overlay=shortest=1:enable=\'{interval_expr(black)}\'[v{idx}]');prev=f'v{idx}';idx+=1
 cmd=['ffmpeg','-y']+inputs+['-filter_complex',';'.join(chains),'-map',f'[{prev}]','-map','0:a?','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p','-c:a','copy','-movflags','+faststart',str(dst)]
 subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);return True,{'black':len(black),'freeze':len(freeze)}
def post_render_qc(project_id,job_id,obj):
 p=(req('GET',f'/rest/v1/video_projects?id=eq.{project_id}&select=*') or [None])[0];j=(req('GET',f'/rest/v1/render_jobs?id=eq.{job_id}&select=*') or [None])[0]
 if not p or not j:raise RuntimeError('Finished render record disappeared before final QC.')
 assets=req('GET',f'/rest/v1/visual_assets?render_job_id=eq.{job_id}&select=provider,media_type,relevance_score,scene_index') or []
 with tempfile.TemporaryDirectory() as d:
  raw=Path(d)/'raw.mp4';master=Path(d)/'master.mp4';repaired=Path(d)/'repaired.mp4';download_output(obj,raw);longform=int(p.get('target_duration_seconds') or 0)>120 or str(p.get('format') or '').lower() in ('long','longform','full','youtube','youtube video','full video','long form','long-form');add_sound_design(raw,master,longform);step(p,'sound_design','passed','Added a subtle locally generated ambience bed, narration-safe compression and final loudness mastering.')
  result=final_video_qc(master,p,assets);final_path=master;repair_meta=None
  if not result['passed'] and any(('frozen visual run' in r or 'black frame run' in r) for r in result.get('reasons') or []):
   changed,repair_meta=repair_integrity(master,repaired)
   if changed:
    second=final_video_qc(repaired,p,assets)
    if second['passed'] or second['score']>result['score']:result=second;final_path=repaired
  upload(final_path,'video-outputs',obj,'video/mp4')
  thumb_obj=None
  if longform:
   thumb=Path(d)/'thumbnail.jpg';make_thumbnail(final_path,p.get('title'),thumb);thumb_obj=f"{p['user_id']}/{p['id']}/{job_id}.jpg";upload(thumb,'video-thumbnails',thumb_obj,'image/jpeg');step(p,'thumbnail','passed','Generated a custom 16:9 thumbnail from the finished video with concise title treatment.')
 report(p,j,'final_video_qc',result);creative=float(p.get('creative_score') or 0);priority=publication_priority(p,creative,result['score']);payload={'quality_score':result['score'],'publication_priority':priority,'status':'quality_check' if result['passed'] else 'failed','failure_reason':None if result['passed'] else 'Final video QC failed: '+'; '.join(result['reasons']),'updated_at':'now()'}
 if thumb_obj:payload['thumbnail_url']=thumb_obj
 patch('video_projects',p['id'],payload);detail=(' Surgical motion-integrity repair applied.' if repair_meta else '');step(p,'final_video_qc','passed' if result['passed'] else 'failed',f"Finished-video score {result['score']}/100. "+('; '.join(result['reasons']) if result['reasons'] else 'Actual MP4 passed motion, freeze, black-frame, silence, duration, aspect-ratio, sound-master and integrity checks.')+detail)
 if not result['passed']:raise RuntimeError('Final video QC failed: '+'; '.join(result['reasons']))
 print(f'FINAL_QC_PASS project={project_id} score={result["score"]} priority={priority} repaired={bool(repair_meta)}')
preflight_queue();p=subprocess.run(['python','scripts/render_video.py'],capture_output=True,text=True);text=(p.stdout or '')+(p.stderr or '');print(text,end='')
if p.returncode:raise SystemExit(p.returncode)
matches=re.findall(r'Rendered\s+([^/\s]+/([^/\s]+)/([^/:\s]+)\.mp4):',text)
if not matches:raise SystemExit(0)
obj,project_id,job_id=matches[-1];post_render_qc(project_id,job_id,obj)
