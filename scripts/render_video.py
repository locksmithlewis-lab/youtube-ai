import json, math, os, re, subprocess, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from visual_sources import plan_scene, choose, local_graphic_asset

SUPABASE_URL=os.environ.get('SUPABASE_URL','').rstrip('/'); SERVICE_KEY=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')
ENGINE='rolixa-multisource-renderer-v7.1'; VOICE_MODEL=os.environ.get('PIPER_VOICE','en_US-lessac-medium'); VOICE_DIR=Path(os.environ.get('PIPER_VOICE_DIR','.piper-voices'))
if not SUPABASE_URL or not SERVICE_KEY: raise SystemExit('Supabase secrets required.')
HEADERS={'apikey':SERVICE_KEY,'Authorization':f'Bearer {SERVICE_KEY}','Content-Type':'application/json'}
def request(method,path,data=None,extra=None):
 body=None if data is None else json.dumps(data).encode();h=dict(HEADERS);h.update(extra or {});r=urllib.request.Request(SUPABASE_URL+path,data=body,headers=h,method=method)
 with urllib.request.urlopen(r,timeout=90) as x:raw=x.read();return json.loads(raw.decode()) if raw else None
def patch(t,i,p):return request('PATCH',f'/rest/v1/{t}?id=eq.{i}',p,{'Prefer':'return=minimal'})
def set_step(p,step,status,detail):return request('POST','/rest/v1/project_pipeline_steps',{'user_id':p['user_id'],'project_id':p['id'],'step':step,'status':status,'detail':detail,'updated_at':'now()'},{'Prefer':'resolution=merge-duplicates,return=minimal'})
def run(cmd,**kw):return subprocess.run(cmd,check=True,**kw)
def duration(p):return float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(p)]).decode().strip())
def ts(sec):ms=int(sec*1000);return f'{ms//3600000:02}:{(ms//60000)%60:02}:{(ms//1000)%60:02},{ms%1000:03}'
def sentences(s):return [re.sub(r'\s+',' ',x).strip() for x in re.split(r'(?<=[.!?])\s+|\n+',s) if len(x.strip().split())>2]
def human_check(s):
 if len(s.split())<55:raise RuntimeError('Script is too thin for a professional video.')
 if len(sentences(s))<5:raise RuntimeError('Story needs more narrative beats for comprehension.')
def claim():
 rows=request('POST','/rest/v1/rpc/claim_next_render_job',{}) or []
 return rows[0] if rows else None
def download(url,path):
 for attempt in range(3):
  try:
   req=urllib.request.Request(url,headers={'User-Agent':'RolixaVisualRouter/2.0','Accept':'*/*'})
   with urllib.request.urlopen(req,timeout=120) as r,open(path,'wb') as f:
    while True:
     b=r.read(1024*1024)
     if not b:break
     f.write(b)
   return True
  except urllib.error.HTTPError as e:
   if e.code not in (403,408,429,500,502,503,504):return False
   time.sleep(1.25*(attempt+1))
  except Exception:
   time.sleep(.75*(attempt+1))
 return False
def motion_filter(motion='push',frames=120):
 z="min(zoom+0.00020,1.025)" if motion!='pull' else "if(lte(zoom,1.0),1.025,max(1.0,zoom-0.00018))"
 return f"scale=1000:1760:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=0x090b10,zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps=30,eq=contrast=1.04:saturation=1.06,setsar=1"
def make_graphic(path,seconds,index,plan):
 txt=path.with_suffix('.txt');txt.write_text((' • '.join((plan.get('keywords') or [])[:5]) or plan.get('text',''))[:160],encoding='utf-8')
 vf=f"drawgrid=width=120:height=120:thickness=2:color=white@0.08,drawbox=x='80+20*sin(t)':y=330:w=920:h=560:color=white@0.06:t=fill,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:textfile={txt}:fontcolor=white:fontsize=54:line_spacing=18:x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.35:boxborderw=28"
 run(['ffmpeg','-y','-f','lavfi','-i',f'color=c=0x101827:s=1080x1920:r=30:d={seconds:.3f}','-vf',vf,'-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def record_asset(job,project,i,plan,a):
 request('POST','/rest/v1/visual_assets',{'user_id':project['user_id'],'project_id':project['id'],'render_job_id':job['id'],'scene_index':i,'provider':a['provider'],'media_type':a['media_type'],'source_url':a.get('url'),'source_page':a.get('page'),'credit':a.get('credit'),'license':a.get('license'),'query':plan.get('query'),'relevance_score':a.get('relevance_score')},{'Prefer':'return=minimal'})
def qc(assets,total):
 scores=[float(a.get('relevance_score') or 0) for a in assets];avg=sum(scores)/max(1,len(scores));ids={a.get('id') for a in assets};providers={a.get('provider') for a in assets};graphics=sum(a.get('media_type')=='graphic' for a in assets);reasons=[]
 if len(ids)/max(1,total)<.75:reasons.append('visual repetition is too high')
 if avg<.42:reasons.append(f'average visual relevance is only {avg:.2f}')
 if total>=8 and len(providers)<2:reasons.append('only one visual provider was used')
 if graphics>math.ceil(total*.55):reasons.append('generated graphics dominate the edit')
 return reasons,avg,providers

def render_asset(asset,plan,i,seg,frames,work):
 src=work/f'source-{i:02}.mp4';clip=work/f'clip-{i:02}.mp4'
 if asset['media_type']=='graphic':
  make_graphic(src,max(seg+.3,3.5),i,plan);run(['ffmpeg','-y','-stream_loop','-1','-i',str(src),'-t',f'{seg:.3f}','-an','-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p',str(clip)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);return clip,asset
 if asset['media_type']=='image':
  image=work/f'image-{i:02}.img'
  if not download(asset['url'],image):asset=local_graphic_asset(plan,i);return render_asset(asset,plan,i,seg,frames,work)
  try:run(['ffmpeg','-y','-loop','1','-i',str(image),'-t',f'{seg:.3f}','-vf',motion_filter('push' if i%2==0 else 'pull',frames),'-an','-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p',str(clip)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);return clip,asset
  except Exception:asset=local_graphic_asset(plan,i);return render_asset(asset,plan,i,seg,frames,work)
 if not download(asset['url'],src):asset=local_graphic_asset(plan,i);return render_asset(asset,plan,i,seg,frames,work)
 try:run(['ffmpeg','-y','-stream_loop','-1','-i',str(src),'-t',f'{seg:.3f}','-an','-vf',motion_filter('push' if i%2==0 else 'pull',frames),'-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p',str(clip)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);return clip,asset
 except Exception:asset=local_graphic_asset(plan,i);return render_asset(asset,plan,i,seg,frames,work)

job=claim()
if not job:print('No queued render jobs.');raise SystemExit(0)
started=time.monotonic();patch('render_jobs',job['id'],{'engine':ENGINE,'updated_at':'now()'})
try:
 project=(request('GET',f"/rest/v1/video_projects?id=eq.{job['project_id']}&select=*") or [None])[0]
 if not project:raise RuntimeError('Project not found.')
 script=(project.get('script') or '').strip();human_check(script)
 for s,d in [('voice','Generating natural narration.'),('visuals','Matching every narration beat across Pexels, Wikimedia Commons, Openverse and local graphics.'),('edit','Building safe captions and multi-source cinematic pacing.')]:set_step(project,s,'running',d)
 work=Path('render-work')/job['id'];work.mkdir(parents=True,exist_ok=True);VOICE_DIR.mkdir(exist_ok=True);(work/'script.txt').write_text(script,encoding='utf-8');model=VOICE_DIR/f'{VOICE_MODEL}.onnx'
 if not model.exists():run(['python','-m','piper.download_voices','--download-dir',str(VOICE_DIR),VOICE_MODEL])
 raw=work/'raw.wav'
 with (work/'script.txt').open() as src:run(['piper','--model',str(model),'--output_file',str(raw),'--length-scale','1.02'],stdin=src)
 audio=work/'voice.wav';run(['ffmpeg','-y','-i',str(raw),'-af','highpass=f=70,lowpass=f=14000,acompressor=threshold=-18dB:ratio=2:attack=8:release=160,equalizer=f=3000:t=q:w=1:g=1,loudnorm=I=-14:TP=-1:LRA=8','-ar','48000','-ac','2',str(audio)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 dur=duration(audio);ss=sentences(script);scene_count=max(8,min(22,math.ceil(dur/3.1)));seg=dur/scene_count;copies=[ss[min(len(ss)-1,math.floor(i*len(ss)/scene_count))] for i in range(scene_count)]
 used=set();clips=[];assets=[]
 for i,line in enumerate(copies):
  kinds=['establishing wide','human medium','detail close up','action','environment','human reaction'];plan=plan_scene(line,project,kinds[i%len(kinds)]);asset=None
  if plan['domain']=='fiction' and i%4==0:asset=local_graphic_asset(plan,i)
  if not asset:asset=choose(plan,used,.42)
  if not asset:asset=local_graphic_asset(plan,i)
  clip,asset=render_asset(asset,plan,i,seg,max(2,int(seg*30)+2),work);used.add(asset['id']);record_asset(job,project,i,plan,asset);assets.append(asset);clips.append(clip)
 reasons,avg,providers=qc(assets,scene_count)
 if reasons:raise RuntimeError('Visual relevance gate failed: '+'; '.join(reasons)+'.')
 words=script.split();chunks=[' '.join(words[i:i+3]) for i in range(0,len(words),3)];weights=[max(1,len(re.sub(r'\W','',c))) for c in chunks];total=sum(weights);cur=0;lines=[]
 for i,(c,w) in enumerate(zip(chunks,weights),1):start=cur;cur+=dur*w/total;lines += [str(i),f'{ts(start)} --> {ts(dur if i==len(chunks) else cur)}',c,'']
 cap=work/'captions.srt';cap.write_text('\n'.join(lines),encoding='utf-8');concat=work/'concat.txt';concat.write_text('\n'.join("file '"+str(p.resolve()).replace("'","'\\''")+"'" for p in clips),encoding='utf-8');visual=work/'visual.mp4';run(['ffmpeg','-y','-f','concat','-safe','0','-i',str(concat),'-c','copy',str(visual)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 out=work/'output.mp4';style="FontName=DejaVu Sans,FontSize=27,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&HC0000000,BorderStyle=1,Outline=3,Shadow=1,Alignment=2,MarginL=130,MarginR=130,MarginV=360";run(['ffmpeg','-y','-i',str(visual),'-i',str(audio),'-vf',f"subtitles={cap}:force_style='{style}'",'-map','0:v','-map','1:a','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart','-shortest',str(out)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);run(['ffmpeg','-v','error','-i',str(out),'-f','null','-'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
 if out.stat().st_size<500000:raise RuntimeError('Output failed size validation.')
 obj=f"{job['user_id']}/{job['project_id']}/{job['id']}.mp4";url=SUPABASE_URL+'/storage/v1/object/video-outputs/'+urllib.parse.quote(obj,safe='/')
 with out.open('rb') as f:r=urllib.request.Request(url,data=f.read(),headers={'apikey':SERVICE_KEY,'Authorization':f'Bearer {SERVICE_KEY}','Content-Type':'video/mp4','x-upsert':'true'},method='POST');urllib.request.urlopen(r,timeout=240).read()
 elapsed=max(.1,time.monotonic()-started);patch('render_jobs',job['id'],{'status':'completed','engine':ENGINE,'output_url':obj,'error':None,'completed_at':'now()','actual_render_seconds':elapsed,'media_duration_seconds':dur,'updated_at':'now()'});patch('video_projects',project['id'],{'output_url':obj,'status':'quality_check','failure_reason':None,'updated_at':'now()'})
 set_step(project,'voice','passed','Natural narration generated and mastered.');set_step(project,'visuals','passed',f"Multi-source relevance QC passed: {scene_count} scenes, avg relevance {avg:.2f}, providers {', '.join(sorted(providers))}.");set_step(project,'edit','passed','Safe-area captions, multi-source pacing and decode validation passed.');print(f'Rendered {obj}: {scene_count} scenes, relevance={avg:.2f}, providers={providers}, engine={ENGINE}')
except Exception as exc:
 msg=str(exc)[:1000];patch('render_jobs',job['id'],{'status':'failed','engine':ENGINE,'error':msg,'completed_at':'now()','actual_render_seconds':max(.1,time.monotonic()-started),'updated_at':'now()'});patch('video_projects',job['project_id'],{'status':'failed','failure_reason':msg,'updated_at':'now()'})
 try:
  project=locals().get('project')
  if project:
   for s in ('voice','visuals','edit'):set_step(project,s,'failed',msg)
 except Exception:pass
 raise
