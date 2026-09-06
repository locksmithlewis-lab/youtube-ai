import json, math, os, re, subprocess, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from visual_sources import plan_scene, choose, local_graphic_asset

SUPABASE_URL=os.environ.get('SUPABASE_URL','').rstrip('/'); SERVICE_KEY=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')
ENGINE='motion-first-renderer-v9'; VOICE_MODEL=os.environ.get('PIPER_VOICE','en_US-lessac-medium'); VOICE_DIR=Path(os.environ.get('PIPER_VOICE_DIR','.piper-voices'))
if not SUPABASE_URL or not SERVICE_KEY: raise SystemExit('Supabase secrets required.')
HEADERS={'apikey':SERVICE_KEY,'Authorization':f'Bearer {SERVICE_KEY}','Content-Type':'application/json'}
W,H=1080,1920

def request(method,path,data=None,extra=None):
 body=None if data is None else json.dumps(data).encode();h=dict(HEADERS);h.update(extra or {});r=urllib.request.Request(SUPABASE_URL+path,data=body,headers=h,method=method)
 with urllib.request.urlopen(r,timeout=90) as x:raw=x.read();return json.loads(raw.decode()) if raw else None

def patch(t,i,p):return request('PATCH',f'/rest/v1/{t}?id=eq.{i}',p,{'Prefer':'return=minimal'})
def set_step(p,step,status,detail):return request('POST','/rest/v1/rpc/upsert_project_pipeline_step',{'p_user_id':p['user_id'],'p_project_id':p['id'],'p_step':step,'p_status':status,'p_detail':detail})
def run(cmd,**kw):return subprocess.run(cmd,check=True,**kw)
def duration(p):return float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(p)]).decode().strip())
def ts(sec):ms=int(sec*1000);return f'{ms//3600000:02}:{(ms//60000)%60:02}:{(ms//1000)%60:02},{ms%1000:03}'
def sentences(s):return [re.sub(r'\s+',' ',x).strip() for x in re.split(r'(?<=[.!?])\s+|\n+',s) if len(x.strip().split())>2]
def is_longform(p):return str(p.get('format') or '').lower() in ('full video','long form','long-form','youtube video') or int(p.get('target_duration_seconds') or 0)>=180

def human_check(s,longform=False):
 wc=len(s.split()); beats=len(sentences(s))
 if longform:
  if wc<850:raise RuntimeError('Long-form script is too short; minimum publish-grade target is about 850 words.')
  if beats<18:raise RuntimeError('Long-form script needs more narrative sections and pacing changes.')
 else:
  if wc<55:raise RuntimeError('Script is too thin for a professional Short.')
  if beats<5:raise RuntimeError('Short needs more narrative beats for comprehension.')

def claim():
 rows=request('POST','/rest/v1/rpc/claim_next_render_job',{}) or []
 return rows[0] if rows else None

def download(url,path):
 for attempt in range(3):
  try:
   req=urllib.request.Request(url,headers={'User-Agent':'MotionVisualRouter/3.0','Accept':'*/*'})
   with urllib.request.urlopen(req,timeout=120) as r,open(path,'wb') as f:
    while True:
     b=r.read(1024*1024)
     if not b:break
     f.write(b)
   return True
  except urllib.error.HTTPError as e:
   if e.code not in (403,408,429,500,502,503,504):return False
   time.sleep(1.1*(attempt+1))
  except Exception:time.sleep(.7*(attempt+1))
 return False

def video_filter(i=0):
 return f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},eq=contrast=1.035:saturation=1.05,setsar=1"

def image_motion_filter(i,frames):
 # Strong enough to read as a moving shot, not a static slideshow: continuous push/pull plus lateral drift.
 zoom="min(zoom+0.00075,1.11)" if i%2==0 else "if(lte(zoom,1.0),1.10,max(1.0,zoom-0.00065))"
 x="iw/2-(iw/zoom/2)+18*sin(on/20)"; y="ih/2-(ih/zoom/2)+12*cos(on/24)"
 return f"scale={int(W*1.16)}:{int(H*1.16)}:force_original_aspect_ratio=increase,crop={int(W*1.16)}:{int(H*1.16)},zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps=30,eq=contrast=1.04:saturation=1.06,setsar=1"

def make_graphic(path,seconds,index,plan):
 # Local fallback is an actual animated motion graphic, not a text slide.
 words=(plan.get('keywords') or [])[:3];txt=path.with_suffix('.txt');txt.write_text('  •  '.join(words)[:80] or ' ',encoding='utf-8')
 font='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf';fs=44 if H>W else 38
 vf=(f"drawgrid=width=120:height=120:thickness=2:color=white@0.055,"
     f"drawbox=x='-260+mod(t*170+{index*90},{W+420})':y='{int(H*.22)}':w=260:h=18:color=white@0.22:t=fill,"
     f"drawbox=x='{int(W*.08)}+40*sin(t*1.7)':y='{int(H*.38)}+70*cos(t*1.15)':w='{int(W*.28)}':h='{int(H*.17)}':color=white@0.055:t=fill,"
     f"drawbox=x='{int(W*.62)}+55*cos(t*1.3)':y='{int(H*.58)}+90*sin(t*.9)':w='{int(W*.22)}':h='{int(H*.12)}':color=white@0.045:t=fill,"
     f"drawtext=fontfile={font}:textfile={txt}:fontcolor=white@0.90:fontsize={fs}:x=(w-text_w)/2:y=h*0.72:box=1:boxcolor=black@0.18:boxborderw=18,"
     f"vignette=PI/5")
 run(['ffmpeg','-y','-f','lavfi','-i',f'color=c=0x0b1320:s={W}x{H}:r=30:d={seconds:.3f}','-vf',vf,'-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p',str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def record_asset(job,project,i,plan,a):
 request('POST','/rest/v1/visual_assets',{'user_id':project['user_id'],'project_id':project['id'],'render_job_id':job['id'],'scene_index':i,'provider':a['provider'],'media_type':a['media_type'],'source_url':a.get('url'),'source_page':a.get('page'),'credit':a.get('credit'),'license':a.get('license'),'query':plan.get('query'),'relevance_score':a.get('relevance_score')},{'Prefer':'return=minimal'})

def qc(assets,total,longform=False):
 scores=[float(a.get('relevance_score') or 0) for a in assets];avg=sum(scores)/max(1,len(scores));ids={a.get('id') for a in assets};providers={a.get('provider') for a in assets};images=sum(a.get('media_type')=='image' for a in assets);graphics=sum(a.get('media_type')=='graphic' for a in assets);videos=sum(a.get('media_type')=='video' for a in assets);moving=videos+graphics;reasons=[];warnings=[]
 if len(ids)/max(1,total)<.78:reasons.append('visual repetition is too high')
 if avg<.44:reasons.append(f'average visual relevance is only {avg:.2f}')
 if images>math.ceil(total*.20):reasons.append(f'too many still-image scenes ({images}/{total}); slideshow-style edits are blocked')
 if moving/max(1,total)<.80:reasons.append(f'only {moving}/{total} scenes contain true motion')
 if graphics>math.ceil(total*(.40 if longform else .35)):reasons.append('motion-graphic fallback dominates instead of real footage')
 if total>=8 and len(providers)<2:warnings.append('single source provider used; relevance and motion still passed')
 return reasons,warnings,avg,providers,images,videos,graphics

def render_asset(asset,plan,i,seg,frames,work):
 src=work/f'source-{i:03}.mp4';clip=work/f'clip-{i:03}.mp4'
 if asset['media_type']=='graphic':
  make_graphic(src,max(seg+.3,3.0),i,plan);run(['ffmpeg','-y','-i',str(src),'-t',f'{seg:.3f}','-an','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p',str(clip)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);return clip,asset
 if asset['media_type']=='image':
  image=work/f'image-{i:03}.img'
  if not download(asset['url'],image):return render_asset(local_graphic_asset(plan,i),plan,i,seg,frames,work)
  try:run(['ffmpeg','-y','-loop','1','-i',str(image),'-t',f'{seg:.3f}','-vf',image_motion_filter(i,frames),'-an','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p',str(clip)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);return clip,asset
  except Exception:return render_asset(local_graphic_asset(plan,i),plan,i,seg,frames,work)
 if not download(asset['url'],src):return render_asset(local_graphic_asset(plan,i),plan,i,seg,frames,work)
 try:run(['ffmpeg','-y','-stream_loop','-1','-i',str(src),'-t',f'{seg:.3f}','-an','-vf',video_filter(i),'-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p',str(clip)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);return clip,asset
 except Exception:return render_asset(local_graphic_asset(plan,i),plan,i,seg,frames,work)

def expressive_voice(script,work,model,longform=False):
 ss=sentences(script);parts=[];scales=[.94,1.04,.98,1.08,.92,1.00];pauses=[.08,.14,.06,.18,.10,.12] if not longform else [.14,.22,.10,.28,.16,.20]
 for i,s in enumerate(ss):
  text=work/f'voice-{i:03}.txt';wav=work/f'voice-{i:03}.wav';text.write_text(s,encoding='utf-8')
  with text.open() as src:run(['piper','--model',str(model),'--output_file',str(wav),'--length-scale',str(scales[i%len(scales)])],stdin=src,stdout=subprocess.DEVNULL)
  parts.append(wav)
  if i<len(ss)-1:
   gap=work/f'pause-{i:03}.wav';run(['ffmpeg','-y','-f','lavfi','-i','anullsrc=r=22050:cl=mono','-t',str(pauses[i%len(pauses)]),'-c:a','pcm_s16le',str(gap)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);parts.append(gap)
 concat=work/'voice-concat.txt';concat.write_text('\n'.join("file '"+str(p.resolve()).replace("'","'\\''")+"'" for p in parts),encoding='utf-8');raw=work/'raw.wav';run(['ffmpeg','-y','-f','concat','-safe','0','-i',str(concat),'-c:a','pcm_s16le',str(raw)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 audio=work/'voice.wav';run(['ffmpeg','-y','-i',str(raw),'-af','highpass=f=70,lowpass=f=14000,acompressor=threshold=-18dB:ratio=2:attack=8:release=160,equalizer=f=3000:t=q:w=1:g=1,loudnorm=I=-14:TP=-1:LRA=8','-ar','48000','-ac','2',str(audio)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);return audio

job=claim()
if not job:print('No queued render jobs.');raise SystemExit(0)
started=time.monotonic();patch('render_jobs',job['id'],{'engine':ENGINE,'updated_at':'now()'})
try:
 project=(request('GET',f"/rest/v1/video_projects?id=eq.{job['project_id']}&select=*") or [None])[0]
 if not project:raise RuntimeError('Project not found.')
 longform=is_longform(project)
 if longform:W,H=1920,1080
 script=(project.get('script') or '').strip();human_check(script,longform)
 set_step(project,'voice','running',f"Generating expressive {'long-form' if longform else 'Short'} narration with varied pacing.");set_step(project,'visuals','running','Motion-first visual search: stock video first, animated motion graphics fallback, still images tightly limited.');set_step(project,'edit','running','Building motion-first edit, captions, pacing and publish-grade QC.')
 work=Path('render-work')/job['id'];work.mkdir(parents=True,exist_ok=True);VOICE_DIR.mkdir(exist_ok=True);model=VOICE_DIR/f'{VOICE_MODEL}.onnx'
 if not model.exists():run(['python','-m','piper.download_voices','--download-dir',str(VOICE_DIR),VOICE_MODEL])
 audio=expressive_voice(script,work,model,longform);dur=duration(audio);ss=sentences(script)
 scene_count=(max(28,min(180,math.ceil(dur/5.0))) if longform else max(10,min(24,math.ceil(dur/2.8))));seg=dur/scene_count;copies=[ss[min(len(ss)-1,math.floor(i*len(ss)/scene_count))] for i in range(scene_count)]
 used=set();used_providers=set();clips=[];assets=[]
 for i,line in enumerate(copies):
  kinds=['establishing wide','tracking action','human medium','detail close up','environment movement','human reaction','macro detail','aerial motion'];plan=plan_scene(line,project,kinds[i%len(kinds)]);asset=choose(plan,used,.44,used_providers)
  if not asset:asset=local_graphic_asset(plan,i)
  clip,asset=render_asset(asset,plan,i,seg,max(2,int(seg*30)+2),work);used.add(asset['id']);used_providers.add(asset['provider']);record_asset(job,project,i,plan,asset);assets.append(asset);clips.append(clip)
 reasons,warnings,avg,providers,images,videos,graphics=qc(assets,scene_count,longform)
 if reasons:raise RuntimeError('Publish-grade visual QC failed: '+'; '.join(reasons)+'. Re-render required; video will not publish.')
 words=script.split();chunk_size=5 if longform else 3;chunks=[' '.join(words[i:i+chunk_size]) for i in range(0,len(words),chunk_size)];weights=[max(1,len(re.sub(r'\W','',c))) for c in chunks];total=sum(weights);cur=0;lines=[]
 for i,(c,w) in enumerate(zip(chunks,weights),1):start=cur;cur+=dur*w/total;lines += [str(i),f'{ts(start)} --> {ts(dur if i==len(chunks) else cur)}',c,'']
 cap=work/'captions.srt';cap.write_text('\n'.join(lines),encoding='utf-8');concat=work/'concat.txt';concat.write_text('\n'.join("file '"+str(p.resolve()).replace("'","'\\''")+"'" for p in clips),encoding='utf-8');visual=work/'visual.mp4';run(['ffmpeg','-y','-f','concat','-safe','0','-i',str(concat),'-c','copy',str(visual)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 out=work/'output.mp4';style=("FontName=DejaVu Sans,FontSize=22,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&HC0000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginL=190,MarginR=190,MarginV=80" if longform else "FontName=DejaVu Sans,FontSize=27,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&HC0000000,BorderStyle=1,Outline=3,Shadow=1,Alignment=2,MarginL=130,MarginR=130,MarginV=330")
 run(['ffmpeg','-y','-i',str(visual),'-i',str(audio),'-vf',f"subtitles={cap}:force_style='{style}'",'-map','0:v','-map','1:a','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart','-shortest',str(out)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);run(['ffmpeg','-v','error','-i',str(out),'-f','null','-'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
 if out.stat().st_size<(3000000 if longform else 500000):raise RuntimeError('Output failed file-size validation.')
 final_dur=duration(out)
 if final_dur<dur*.94:raise RuntimeError('Output duration validation failed; edit appears truncated.')
 obj=f"{job['user_id']}/{job['project_id']}/{job['id']}.mp4";url=SUPABASE_URL+'/storage/v1/object/video-outputs/'+urllib.parse.quote(obj,safe='/')
 with out.open('rb') as f:r=urllib.request.Request(url,data=f.read(),headers={'apikey':SERVICE_KEY,'Authorization':f'Bearer {SERVICE_KEY}','Content-Type':'video/mp4','x-upsert':'true'},method='POST');urllib.request.urlopen(r,timeout=600 if longform else 240).read()
 elapsed=max(.1,time.monotonic()-started);patch('render_jobs',job['id'],{'status':'completed','engine':ENGINE,'output_url':obj,'error':None,'completed_at':'now()','actual_render_seconds':elapsed,'media_duration_seconds':final_dur,'updated_at':'now()'});patch('video_projects',project['id'],{'output_url':obj,'voice':VOICE_MODEL,'status':'ready','failure_reason':None,'updated_at':'now()'})
 warn=(' '+ '; '.join(warnings)) if warnings else '';set_step(project,'voice','passed',f'Expressive narration passed with {VOICE_MODEL}.');set_step(project,'visuals','passed',f"Motion QC passed: {scene_count} scenes, {videos} stock-video, {graphics} motion-graphic, {images} animated-image, avg relevance {avg:.2f}, providers {', '.join(sorted(providers))}.{warn}");set_step(project,'edit','passed',f"{'16:9 long-form' if longform else '9:16 Short'} edit passed decode, duration, caption and motion checks.");print(f'Rendered {obj}: mode={"longform" if longform else "short"}, motion={videos+graphics}/{scene_count}, relevance={avg:.2f}, providers={providers}, engine={ENGINE}')
except Exception as exc:
 msg=str(exc)[:1000];patch('render_jobs',job['id'],{'status':'failed','engine':ENGINE,'error':msg,'completed_at':'now()','actual_render_seconds':max(.1,time.monotonic()-started),'updated_at':'now()'});patch('video_projects',job['project_id'],{'status':'failed','failure_reason':msg,'updated_at':'now()'})
 try:
  project=locals().get('project')
  if project:
   for s in ('voice','visuals','edit'):set_step(project,s,'failed',msg)
 except Exception:pass
 raise
