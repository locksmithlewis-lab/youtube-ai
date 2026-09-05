import json, math, os, re, subprocess, urllib.error, urllib.parse, urllib.request
from pathlib import Path
SUPABASE_URL=os.environ.get('SUPABASE_URL','').rstrip('/'); SERVICE_KEY=os.environ.get('SUPABASE_SERVICE_ROLE_KEY',''); PEXELS_API_KEY=os.environ.get('PEXELS_API_KEY','').strip(); ENGINE='rolixa-cinematic-renderer-v6-safe-frame'; VOICE_MODEL=os.environ.get('PIPER_VOICE','en_US-lessac-medium'); VOICE_DIR=Path(os.environ.get('PIPER_VOICE_DIR','.piper-voices'))
if not SUPABASE_URL or not SERVICE_KEY: raise SystemExit('Supabase secrets required.')
HEADERS={'apikey':SERVICE_KEY,'Authorization':f'Bearer {SERVICE_KEY}','Content-Type':'application/json'}
def request(method,path,data=None,extra=None):
 body=None if data is None else json.dumps(data).encode(); h=dict(HEADERS); h.update(extra or {}); req=urllib.request.Request(SUPABASE_URL+path,data=body,headers=h,method=method)
 with urllib.request.urlopen(req,timeout=90) as r: raw=r.read(); return json.loads(raw.decode()) if raw else None
def patch(t,i,p): return request('PATCH',f'/rest/v1/{t}?id=eq.{i}',p,{'Prefer':'return=minimal'})
def pipe(pid,step,status,detail): return request('PATCH',f'/rest/v1/project_pipeline_steps?project_id=eq.{pid}&step=eq.{step}',{'status':status,'detail':detail,'updated_at':'now()'},{'Prefer':'return=minimal'})
def run(cmd,**kw): return subprocess.run(cmd,check=True,**kw)
def duration(p): return float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(p)]).decode().strip())
def ts(sec): ms=int(sec*1000); return f'{ms//3600000:02}:{(ms//60000)%60:02}:{(ms//1000)%60:02},{ms%1000:03}'
def sentences(s): return [re.sub(r'\s+',' ',x).strip() for x in re.split(r'(?<=[.!?])\s+',s) if x.strip()]
def human_check(s):
 low=s.lower(); hits=[x for x in ['this short takes','this video will','start with the','the key is speed','this version is built','faceless angle','in this video','today we are going'] if x in low]
 if hits: raise RuntimeError('Script failed human-language gate: '+', '.join(hits))
 if len(s.split())<55: raise RuntimeError('Script is too thin for a professional video.')
 ss=sentences(s)
 if len(ss)<5: raise RuntimeError('Story needs more narrative beats for comprehension.')
 if sum(1 for x in ss if len(x.split())>30)>max(1,len(ss)//3): raise RuntimeError('Story has too many long, synthetic-sounding sentences.')
def keywords(text,n=6):
 stop={'this','that','with','from','have','will','your','they','them','then','into','about','while','where','when','what','people','video','right','really','just','every','inside','thing','things','there','their','would','could','should'}
 words=[w for w in re.sub(r'[^a-zA-Z0-9 ]',' ',text).split() if len(w)>3 and w.lower() not in stop]
 out=[]
 for w in words:
  if w.lower() not in [x.lower() for x in out]: out.append(w)
 return out[:n]
def shot_plan(project,copy,count):
 base=' '.join(keywords((project.get('topic') or project.get('title') or ''),5)) or 'cinematic life'; plans=[]; types=['establishing wide','human medium','detail close up','action','environment','human reaction']
 for i,line in enumerate(copy):
  low=line.lower(); kind=types[i%len(types)]
  if any(x in low for x in ['city','tower','building','street','world','place','country']): kind='establishing wide'
  elif any(x in low for x in ['engineer','person','people','human','player','artist','woman','man','child','family']): kind='human medium'
  elif any(x in low for x in ['move','run','fight','push','wind','action','race','drive']): kind='action'
  elif any(x in low for x in ['small','detail','inside','weight','hand','eye','phone','screen']): kind='detail close up'
  line_keys=keywords(line,5); topic_keys=keywords(project.get('topic') or project.get('title') or '',3)
  q=' '.join((line_keys+topic_keys)[:6]) or base
  plans.append({'type':kind,'query':f'{q} {kind}','motion':['push-soft','drift-left','pull','drift-right','push-soft'][i%5]})
 return plans
def pexels_candidates(q,orientation='portrait'):
 if not PEXELS_API_KEY: raise RuntimeError('Pexels API key is missing from the render worker.')
 url='https://api.pexels.com/v1/videos/search?'+urllib.parse.urlencode({'query':q,'per_page':15,'orientation':orientation,'size':'medium'}); req=urllib.request.Request(url,headers={'Authorization':PEXELS_API_KEY,'Accept':'application/json','User-Agent':'Rolixa/1.0'})
 try:
  with urllib.request.urlopen(req,timeout=30) as r:data=json.loads(r.read().decode())
 except urllib.error.HTTPError as e:
  body=e.read().decode('utf-8','replace')[:300]; raise RuntimeError(f'Pexels API returned HTTP {e.code}: {body or e.reason}') from e
 out=[]
 for v in data.get('videos') or []:
  fs=sorted(v.get('video_files') or [],key=lambda x:(x.get('width') or 0)*(x.get('height') or 0),reverse=True)
  f=next((x for x in fs if x.get('link') and (x.get('height') or 0)>=720),None)
  if f:out.append({'id':v.get('id'),'url':f['link'],'credit':v.get('user',{}).get('name'),'page':v.get('url'),'width':f.get('width') or 0,'height':f.get('height') or 0})
 return out
def download(url,path):
 req=urllib.request.Request(url,headers={'User-Agent':'Rolixa/1.0'})
 with urllib.request.urlopen(req,timeout=120) as r,open(path,'wb') as f:
  while True:
   b=r.read(1024*1024)
   if not b:break
   f.write(b)
def fallback_video(path,seconds,index): run(['ffmpeg','-y','-f','lavfi','-i',f'color=c=0x10131b:s=1080x1920:r=30:d={seconds:.3f}','-vf',f"geq=r='18+22*X/W+8*sin(T+{index})':g='20+18*Y/H':b='32+28*X/W',noise=alls=4:allf=t+u",'-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def motion_filter(motion,frames):
 # Fit first, then place inside a 1080x1920 canvas. This prevents heads, faces, photos and landscape footage being chopped by a forced center crop.
 z={'push-soft':"min(zoom+0.00022,1.025)",'pull':"if(lte(zoom,1.0),1.025,max(1.0,zoom-0.00020))"}.get(motion,"min(zoom+0.00018,1.02)")
 dx="sin(on/30)*3" if motion=='drift-left' else ("0-sin(on/32)*3" if motion=='drift-right' else "sin(on/35)*2")
 return f"scale=1000:1760:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=0x090b10,zoompan=z='{z}':x='iw/2-(iw/zoom/2)+({dx})':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps=30,eq=contrast=1.04:saturation=1.05:brightness=-0.005,setsar=1"
def visual_qc(real,total,unique_ids,fallbacks):
 ratio=real/max(1,total); unique_ratio=len(unique_ids)/max(1,real); reasons=[]
 if real<max(4,math.ceil(total*.65)):reasons.append(f'only {real}/{total} scenes use licensed footage')
 if ratio<.65:reasons.append('fallback backgrounds dominate')
 if real and unique_ratio<.85:reasons.append('footage repetition too high')
 if fallbacks>max(2,math.floor(total*.35)):reasons.append('too many generic fallback scenes')
 return reasons
queued=request('GET','/rest/v1/render_jobs?status=eq.queued&select=*&order=created_at.asc&limit=12') or []
if not queued:print('No queued render jobs.');raise SystemExit(0)
job=queued[0];patch('render_jobs',job['id'],{'status':'running','engine':ENGINE,'updated_at':'now()'})
try:
 project=(request('GET',f"/rest/v1/video_projects?id=eq.{job['project_id']}&select=*") or [None])[0]
 if not project:raise RuntimeError('Project not found.')
 script=(project.get('script') or '').strip();human_check(script);pipe(project['id'],'voice','running','Generating natural narration.');pipe(project['id'],'visuals','running','Matching each narrative beat to safe-framed footage.');pipe(project['id'],'edit','running','Building readable captions and cinematic pacing.')
 work=Path('render-work');work.mkdir(exist_ok=True);VOICE_DIR.mkdir(exist_ok=True);(work/'script.txt').write_text(script,encoding='utf-8');model=VOICE_DIR/f'{VOICE_MODEL}.onnx'
 if not model.exists():run(['python','-m','piper.download_voices','--download-dir',str(VOICE_DIR),VOICE_MODEL])
 raw=work/'raw.wav'
 with (work/'script.txt').open() as src:run(['piper','--model',str(model),'--output_file',str(raw),'--length-scale','1.02'],stdin=src)
 audio=work/'voice.wav';run(['ffmpeg','-y','-i',str(raw),'-af','highpass=f=70,lowpass=f=14000,acompressor=threshold=-18dB:ratio=2:attack=8:release=160,equalizer=f=3000:t=q:w=1:g=1.0,loudnorm=I=-14:TP=-1.0:LRA=8','-ar','48000','-ac','2',str(audio)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);dur=duration(audio);ss=sentences(script);scene_count=max(7,min(18,math.ceil(dur/3.4)));seg=dur/scene_count;copy=[ss[min(len(ss)-1,math.floor(i*len(ss)/scene_count))] if ss else project.get('title','') for i in range(scene_count)];plans=shot_plan(project,copy,scene_count);clips=[];credits=[];used=set();fallbacks=0
 for i,p in enumerate(plans):
  try:choices=pexels_candidates(p['query'],'portrait') or pexels_candidates(p['query'],'landscape')
  except Exception as e: raise RuntimeError(f'Licensed footage search failed before scene {i+1}: {e}') from e
  hit=next((x for x in choices if x['url'] not in used),None);src=work/f'source-{i:02}.mp4'
  if hit:download(hit['url'],src);used.add(hit['url']);credits.append(hit)
  else:fallback_video(src,max(seg+1,4),i);fallbacks+=1
  clip=work/f'clip-{i:02}.mp4';frames=max(2,int(seg*30)+2);vf=motion_filter(p['motion'],frames);run(['ffmpeg','-y','-stream_loop','-1','-i',str(src),'-t',f'{seg:.3f}','-an','-vf',vf,'-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p',str(clip)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);clips.append(clip)
 reasons=visual_qc(len(credits),scene_count,{x.get('id') for x in credits},fallbacks)
 if reasons:raise RuntimeError('Visual professionalism gate failed: '+'; '.join(reasons)+'. Re-render required; video was not marked ready.')
 # Keep captions short, centered and well above Shorts/TikTok/Reels bottom UI. ASS margins protect both horizontal edges.
 words=script.split();chunks=[' '.join(words[i:i+3]) for i in range(0,len(words),3)];weights=[max(1,len(re.sub(r'\W','',c))) for c in chunks];total=sum(weights);cur=0;lines=[]
 for i,(c,w) in enumerate(zip(chunks,weights),1):start=cur;cur+=dur*w/total;lines += [str(i),f'{ts(start)} --> {ts(dur if i==len(chunks) else cur)}',c,'']
 cap=work/'captions.srt';cap.write_text('\n'.join(lines),encoding='utf-8');concat=work/'concat.txt';concat.write_text('\n'.join("file '"+str(p.resolve()).replace("'","'\\''")+"'" for p in clips),encoding='utf-8');visual=work/'visual.mp4';run(['ffmpeg','-y','-f','concat','-safe','0','-i',str(concat),'-c','copy',str(visual)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);out=work/'output.mp4';style="FontName=DejaVu Sans,FontSize=27,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&HC0000000,BorderStyle=1,Outline=3,Shadow=1,Alignment=2,MarginL=130,MarginR=130,MarginV=360";run(['ffmpeg','-y','-i',str(visual),'-i',str(audio),'-vf',f"subtitles={cap}:force_style='{style}'",'-map','0:v','-map','1:a','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart','-shortest',str(out)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);run(['ffmpeg','-v','error','-i',str(out),'-f','null','-'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
 if out.stat().st_size<500000:raise RuntimeError('Output failed size validation.')
 obj=f"{job['user_id']}/{job['project_id']}/{job['id']}.mp4";url=SUPABASE_URL+'/storage/v1/object/video-outputs/'+urllib.parse.quote(obj,safe='/')
 with out.open('rb') as f:req=urllib.request.Request(url,data=f.read(),headers={'apikey':SERVICE_KEY,'Authorization':f'Bearer {SERVICE_KEY}','Content-Type':'video/mp4','x-upsert':'true'},method='POST');urllib.request.urlopen(req,timeout=240).read()
 patch('render_jobs',job['id'],{'status':'completed','engine':ENGINE,'output_url':obj,'error':None,'updated_at':'now()'});patch('video_projects',project['id'],{'output_url':obj,'status':'quality_check','failure_reason':None,'updated_at':'now()'});pipe(project['id'],'voice','passed','Natural narration generated and mastered.');pipe(project['id'],'visuals','passed',f'Safe-frame QC passed: {scene_count} planned scenes, {len(credits)} unique licensed footage selections, {fallbacks} fallbacks.');pipe(project['id'],'edit','passed','Safe-area captions, restrained camera movement, pacing, grade and decode validation passed.');print(f'Rendered {obj}: {dur:.1f}s, {scene_count} shots, {len(credits)} licensed, {fallbacks} fallback, engine={ENGINE}')
except Exception as exc:
 msg=str(exc)[:1000];patch('render_jobs',job['id'],{'status':'failed','engine':ENGINE,'error':msg,'updated_at':'now()'});patch('video_projects',job['project_id'],{'status':'failed','failure_reason':msg,'updated_at':'now()'});
 for s in ('voice','visuals','edit'):
  try:pipe(job['project_id'],s,'failed',msg)
  except Exception:pass
 raise
