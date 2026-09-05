import json, math, os, re, subprocess, urllib.parse, urllib.request
from pathlib import Path

SUPABASE_URL=os.environ.get('SUPABASE_URL','').rstrip('/')
SERVICE_KEY=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')
PEXELS_API_KEY=os.environ.get('PEXELS_API_KEY','')
ENGINE='rolixa-cinematic-renderer-v4'
VOICE_MODEL=os.environ.get('PIPER_VOICE','en_US-lessac-medium')
VOICE_DIR=Path(os.environ.get('PIPER_VOICE_DIR','.piper-voices'))
if not SUPABASE_URL or not SERVICE_KEY: raise SystemExit('Supabase secrets required.')
HEADERS={'apikey':SERVICE_KEY,'Authorization':f'Bearer {SERVICE_KEY}','Content-Type':'application/json'}

def request(method,path,data=None,extra=None):
    body=None if data is None else json.dumps(data).encode(); h=dict(HEADERS); h.update(extra or {})
    req=urllib.request.Request(SUPABASE_URL+path,data=body,headers=h,method=method)
    with urllib.request.urlopen(req,timeout=90) as r:
        raw=r.read(); return json.loads(raw.decode()) if raw else None

def patch(table,row_id,payload): return request('PATCH',f'/rest/v1/{table}?id=eq.{row_id}',payload,{'Prefer':'return=minimal'})
def pipe(pid,step,status,detail): return request('PATCH',f'/rest/v1/project_pipeline_steps?project_id=eq.{pid}&step=eq.{step}',{'status':status,'detail':detail,'updated_at':'now()'},{'Prefer':'return=minimal'})
def run(cmd,**kw): return subprocess.run(cmd,check=True,**kw)
def duration(path): return float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(path)]).decode().strip())
def ts(sec):
    ms=int(sec*1000); return f'{ms//3600000:02}:{(ms//60000)%60:02}:{(ms//1000)%60:02},{ms%1000:03}'
def sentences(script): return [re.sub(r'\s+',' ',x).strip() for x in re.split(r'(?<=[.!?])\s+',script) if x.strip()]
def human_check(script):
    banned=['this short takes','this video will','start with the','the key is speed','this version is built','faceless angle']
    hits=[x for x in banned if x in script.lower()]
    if hits: raise RuntimeError('Script failed human-language gate: '+', '.join(hits))
    if len(script.split())<55: raise RuntimeError('Script is too thin for a professional video.')

def search_terms(project,lines):
    base=re.sub(r'[^a-zA-Z0-9 ]',' ',(project.get('topic') or project.get('title') or 'people lifestyle'))
    stop={'the','and','that','this','with','from','into','right','now','official','video','trailer','why','about','just','more','than','your'}
    words=[w for w in base.split() if len(w)>3 and w.lower() not in stop][:5]
    primary=' '.join(words) or 'people cinematic'
    terms=[]
    for i,line in enumerate(lines):
        low=line.lower()
        if any(x in low for x in ['game','gaming','player','stream']): q='gaming player reaction'
        elif any(x in low for x in ['music','artist','song','concert']): q='music performer audience'
        elif any(x in low for x in ['money','business','market','company']): q='business people city'
        elif any(x in low for x in ['movie','film','actor','trailer']): q='cinematic people film'
        elif any(x in low for x in ['technology','phone','computer','ai']): q='technology people computer'
        else: q=primary+' people'
        terms.append(q)
    return terms

def pexels_video(query,orientation='portrait'):
    if not PEXELS_API_KEY: return None
    url='https://api.pexels.com/v1/videos/search?'+urllib.parse.urlencode({'query':query,'per_page':8,'orientation':orientation,'size':'medium'})
    req=urllib.request.Request(url,headers={'Authorization':PEXELS_API_KEY})
    with urllib.request.urlopen(req,timeout=30) as r: data=json.loads(r.read().decode())
    vids=data.get('videos') or []
    for v in vids:
        files=sorted(v.get('video_files') or [],key=lambda x:(x.get('width') or 0)*(x.get('height') or 0),reverse=True)
        for f in files:
            if f.get('link') and (f.get('height') or 0)>=720:
                return {'url':f['link'],'credit':v.get('user',{}).get('name'),'page':v.get('url')}
    return None

def download(url,path):
    req=urllib.request.Request(url,headers={'User-Agent':'Rolixa/1.0'})
    with urllib.request.urlopen(req,timeout=120) as r, open(path,'wb') as f:
        while True:
            b=r.read(1024*1024)
            if not b: break
            f.write(b)

def fallback_video(path,seconds,index):
    # Professional neutral fallback: moving cinematic gradient, never the old geometric/person-card template.
    run(['ffmpeg','-y','-f','lavfi','-i',f'color=c=0x10131b:s=1080x1920:r=30:d={seconds:.3f}','-vf',f"geq=r='18+22*X/W+8*sin(T+{index})':g='20+18*Y/H':b='32+28*X/W',noise=alls=4:allf=t+u",'-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

queued=request('GET','/rest/v1/render_jobs?status=eq.queued&select=*&order=created_at.asc&limit=12') or []
if not queued: print('No queued render jobs.'); raise SystemExit(0)
job=None
for c in queued:
    rows=request('GET',f"/rest/v1/video_projects?id=eq.{c['project_id']}&select=id,format,target_duration_seconds") or []; p=rows[0] if rows else {}
    if str(p.get('format') or '').lower()=='short' or int(p.get('target_duration_seconds') or 99999)<=90: job=c; break
job=job or queued[0]; patch('render_jobs',job['id'],{'status':'running','engine':ENGINE,'updated_at':'now()'})
try:
    project=(request('GET',f"/rest/v1/video_projects?id=eq.{job['project_id']}&select=*") or [None])[0]
    if not project: raise RuntimeError('Project not found.')
    script=(project.get('script') or '').strip(); human_check(script)
    pipe(project['id'],'voice','running','Generating and mastering narration.'); pipe(project['id'],'visuals','running','Finding cinematic human footage and scene-matched backgrounds.'); pipe(project['id'],'edit','running','Building professional camera movement, cuts, captions, and final grade.')
    work=Path('render-work'); work.mkdir(exist_ok=True); VOICE_DIR.mkdir(exist_ok=True); (work/'script.txt').write_text(script,encoding='utf-8')
    model=VOICE_DIR/f'{VOICE_MODEL}.onnx'
    if not model.exists(): run(['python','-m','piper.download_voices','--download-dir',str(VOICE_DIR),VOICE_MODEL])
    raw=work/'raw.wav'
    with (work/'script.txt').open() as src: run(['piper','--model',str(model),'--output_file',str(raw),'--length-scale','0.94'],stdin=src)
    audio=work/'voice.wav'; run(['ffmpeg','-y','-i',str(raw),'-af','highpass=f=70,lowpass=f=14000,acompressor=threshold=-18dB:ratio=2:attack=8:release=160,equalizer=f=3000:t=q:w=1:g=1.5,loudnorm=I=-14:TP=-1.0:LRA=8','-ar','48000','-ac','2',str(audio)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    dur=duration(audio); ss=sentences(script); scene_count=max(7,min(18,math.ceil(dur/3.2))); seg=dur/scene_count
    scene_copy=[ss[min(len(ss)-1,math.floor(i*len(ss)/scene_count))] if ss else project.get('title','') for i in range(scene_count)]
    terms=search_terms(project,scene_copy); clips=[]; credits=[]; used=set()
    for i,q in enumerate(terms):
        hit=None
        try: hit=pexels_video(q,'portrait') or pexels_video(q,'landscape')
        except Exception as e: print('Footage search:',e)
        src=work/f'source-{i:02}.mp4'
        if hit and hit['url'] not in used:
            download(hit['url'],src); used.add(hit['url']); credits.append(hit)
        else: fallback_video(src,max(seg+1,4),i)
        clip=work/f'clip-{i:02}.mp4'
        # Crop/scale plus alternating push-in, drift and pull-back gives every shot camera movement.
        z="min(zoom+0.0008,1.09)" if i%3==0 else ("min(zoom+0.00045,1.055)" if i%3==1 else "if(lte(zoom,1.0),1.07,max(1.0,zoom-0.00055))")
        frames=max(2,int(seg*30)+2)
        vf=f"scale=1200:2134:force_original_aspect_ratio=increase,crop=1200:2134,zoompan=z='{z}':x='iw/2-(iw/zoom/2)+sin(on/24)*5':y='ih/2-(ih/zoom/2)+cos(on/31)*4':d={frames}:s=1080x1920:fps=30,eq=contrast=1.05:saturation=1.06:brightness=-0.01,setsar=1"
        run(['ffmpeg','-y','-stream_loop','-1','-i',str(src),'-t',f'{seg:.3f}','-an','-vf',vf,'-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p',str(clip)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); clips.append(clip)
    words=script.split(); chunks=[' '.join(words[i:i+4]) for i in range(0,len(words),4)]; weights=[max(1,len(re.sub(r'\W','',c))) for c in chunks]; total=sum(weights); cur=0; lines=[]
    for i,(c,w) in enumerate(zip(chunks,weights),1):
        start=cur; cur+=dur*w/total; lines += [str(i),f'{ts(start)} --> {ts(dur if i==len(chunks) else cur)}',c,'']
    cap=work/'captions.srt'; cap.write_text('\n'.join(lines),encoding='utf-8')
    concat=work/'concat.txt'; concat.write_text('\n'.join("file '"+str(p.resolve()).replace("'","'\\''")+"'" for p in clips),encoding='utf-8')
    visual=work/'visual.mp4'; run(['ffmpeg','-y','-f','concat','-safe','0','-i',str(concat),'-c','copy',str(visual)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    out=work/'output.mp4'; style="FontName=DejaVu Sans,FontSize=32,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H90000000,BorderStyle=1,Outline=3,Shadow=1,Alignment=2,MarginL=70,MarginR=70,MarginV=220"
    run(['ffmpeg','-y','-i',str(visual),'-i',str(audio),'-vf',f"subtitles={cap}:force_style='{style}'",'-map','0:v','-map','1:a','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart','-shortest',str(out)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    run(['ffmpeg','-v','error','-i',str(out),'-f','null','-'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    if out.stat().st_size<500000: raise RuntimeError('Output failed size validation.')
    obj=f"{job['user_id']}/{job['project_id']}/{job['id']}.mp4"; url=SUPABASE_URL+'/storage/v1/object/video-outputs/'+urllib.parse.quote(obj,safe='/')
    with out.open('rb') as f:
        req=urllib.request.Request(url,data=f.read(),headers={'apikey':SERVICE_KEY,'Authorization':f'Bearer {SERVICE_KEY}','Content-Type':'video/mp4','x-upsert':'true'},method='POST'); urllib.request.urlopen(req,timeout=240).read()
    patch('render_jobs',job['id'],{'status':'completed','engine':ENGINE,'output_url':obj,'error':None,'updated_at':'now()'}); patch('video_projects',project['id'],{'output_url':obj,'status':'quality_check','failure_reason':None,'updated_at':'now()'})
    real=sum(1 for x in credits if x); pipe(project['id'],'voice','passed','Narration generated and mastered.'); pipe(project['id'],'visuals','passed',f'{scene_count} cinematic scenes with continuous camera movement; {real} licensed footage selections.'); pipe(project['id'],'edit','passed','Professional vertical edit, motion, grade, captions, H.264/AAC validation passed.')
    print(f'Rendered {obj}: {dur:.1f}s, {scene_count} cinematic shots, {real} licensed footage shots, engine={ENGINE}')
except Exception as exc:
    msg=str(exc)[:1000]; patch('render_jobs',job['id'],{'status':'failed','engine':ENGINE,'error':msg,'updated_at':'now()'}); patch('video_projects',job['project_id'],{'status':'failed','failure_reason':msg,'updated_at':'now()'})
    for s in ('voice','visuals','edit'):
        try: pipe(job['project_id'],s,'failed',msg)
        except Exception: pass
    raise
