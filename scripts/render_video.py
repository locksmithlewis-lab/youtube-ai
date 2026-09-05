import json, math, os, re, subprocess, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

SUPABASE_URL=os.environ.get('SUPABASE_URL','').rstrip('/')
SERVICE_KEY=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')
ENGINE='rolixa-story-renderer-v3-fast'
VOICE_MODEL=os.environ.get('PIPER_VOICE','en_US-lessac-medium')
VOICE_DIR=Path(os.environ.get('PIPER_VOICE_DIR','.piper-voices'))
if not SUPABASE_URL or not SERVICE_KEY: raise SystemExit('Supabase secrets required.')
HEADERS={'apikey':SERVICE_KEY,'Authorization':f'Bearer {SERVICE_KEY}','Content-Type':'application/json'}

def request(method,path,data=None,extra=None):
    body=None if data is None else json.dumps(data).encode(); h=dict(HEADERS); h.update(extra or {})
    req=urllib.request.Request(SUPABASE_URL+path,data=body,headers=h,method=method)
    with urllib.request.urlopen(req,timeout=60) as r:
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
    low=script.lower(); hits=[x for x in banned if x in low]
    if hits: raise RuntimeError('Script failed human-language gate: '+', '.join(hits))
    if len(script.split())<55: raise RuntimeError('Script is too thin for an engaging Short.')

def fonts():
    bold='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'; reg='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    return ImageFont.truetype(bold,72),ImageFont.truetype(bold,42),ImageFont.truetype(reg,30)

def wrap(draw,text,font,width,limit=4):
    out=[]; line=''
    for w in text.split():
        test=(line+' '+w).strip()
        if draw.textbbox((0,0),test,font=font)[2]<=width: line=test
        else:
            if line: out.append(line)
            line=w
            if len(out)>=limit-1: break
    if line and len(out)<limit: out.append(line)
    return out

def draw_person(draw,cx,cy,scale,accent,pose=0):
    skin=(218,168,128); dark=(24,26,35); shirt=accent
    r=int(92*scale); draw.ellipse((cx-r,cy-r,cx+r,cy+r),fill=skin)
    draw.pieslice((cx-r-4,cy-r-12,cx+r+4,cy+r-20),180,355,fill=dark)
    eye=int(8*scale)
    draw.ellipse((cx-int(34*scale)-eye,cy-int(8*scale)-eye,cx-int(34*scale)+eye,cy-int(8*scale)+eye),fill=dark)
    draw.ellipse((cx+int(34*scale)-eye,cy-int(8*scale)-eye,cx+int(34*scale)+eye,cy-int(8*scale)+eye),fill=dark)
    draw.arc((cx-int(35*scale),cy+int(10*scale),cx+int(35*scale),cy+int(55*scale)),0,180,fill=dark,width=max(3,int(5*scale)))
    top=cy+r-5; bodyw=int(210*scale); draw.rounded_rectangle((cx-bodyw,top,cx+bodyw,top+int(430*scale)),radius=int(70*scale),fill=shirt)
    hand_y=top+int((170 if pose%2==0 else 100)*scale); arm=int(260*scale)
    draw.line((cx-bodyw+20,top+90,cx-arm,hand_y),fill=skin,width=int(45*scale)); draw.ellipse((cx-arm-28,hand_y-28,cx-arm+28,hand_y+28),fill=skin)
    draw.line((cx+bodyw-20,top+90,cx+arm,hand_y-int(80*scale)),fill=skin,width=int(45*scale)); draw.ellipse((cx+arm-28,hand_y-int(80*scale)-28,cx+arm+28,hand_y-int(80*scale)+28),fill=skin)

def make_scene(args):
    path,text,index,total=args
    W,H=1080,1920; palettes=[((18,20,38),(113,78,220)),((10,34,45),(24,166,180)),((38,18,35),(218,74,133)),((34,29,12),(224,155,45)),((15,36,25),(50,180,110))]
    bg,accent=palettes[index%len(palettes)]; im=Image.new('RGB',(W,H),bg); d=ImageDraw.Draw(im); big,mid,small=fonts()
    for y in range(H):
        t=y/H; d.line((0,y,W,y),fill=tuple(int(bg[i]*(1-t*.25)+accent[i]*t*.22) for i in range(3)))
    for k in range(7):
        x=(index*173+k*211)%1250-100; y=220+k*215; rr=45+(k%3)*24; d.ellipse((x-rr,y-rr,x+rr,y+rr),outline=tuple(min(255,c+45) for c in accent),width=8)
    draw_person(d,540,720,1.05,accent,index)
    d.rounded_rectangle((70,80,290,145),28,fill=(7,8,15)); d.text((98,94),'ROLIXA',font=mid,fill='white')
    pts=[]
    for x in range(110,970,110):
        yy=1510-int((x-110)*.38)-((x//110+index)%3)*45; pts.append((x,yy))
    d.line(pts,fill=(245,245,250),width=13,joint='curve')
    for x,y in pts: d.ellipse((x-14,y-14,x+14,y+14),fill=accent,outline='white',width=4)
    lines=wrap(d,text,big,900,4); y=210
    for line in lines:
        box=d.textbbox((0,0),line,font=big); tw=box[2]; x=(W-tw)//2
        d.rounded_rectangle((x-20,y-8,x+tw+20,y+82),18,fill=(5,6,12)); d.text((x,y),line,font=big,fill='white'); y+=92
    d.text((80,1760),f'{index+1:02} / {total:02}',font=small,fill=(225,225,235)); d.rounded_rectangle((190,1773,990,1785),6,fill=(65,68,80)); d.rounded_rectangle((190,1773,190+int(800*(index+1)/total),1785),6,fill=accent)
    im.save(path,quality=92,optimize=False)
    return path

# Prefer Shorts so quick videos do not sit behind long-form renders.
queued=request('GET','/rest/v1/render_jobs?status=eq.queued&select=*&order=created_at.asc&limit=12') or []
if not queued: print('No queued render jobs.'); raise SystemExit(0)
job=None
for candidate in queued:
    rows=request('GET',f"/rest/v1/video_projects?id=eq.{candidate['project_id']}&select=id,format,target_duration_seconds") or []
    p=rows[0] if rows else {}
    if str(p.get('format') or '').lower()=='short' or int(p.get('target_duration_seconds') or 99999)<=90:
        job=candidate; break
job=job or queued[0]
patch('render_jobs',job['id'],{'status':'running','engine':ENGINE,'updated_at':'now()'})
try:
    project=(request('GET',f"/rest/v1/video_projects?id=eq.{job['project_id']}&select=*") or [None])[0]
    if not project: raise RuntimeError('Project not found.')
    script=(project.get('script') or '').strip(); human_check(script)
    pipe(project['id'],'voice','running','Generating and mastering neural narration.'); pipe(project['id'],'visuals','running','Building illustrated characters and story scenes in parallel.'); pipe(project['id'],'edit','running','Single-pass motion, captions, audio, and final encode.')
    work=Path('render-work'); work.mkdir(exist_ok=True); VOICE_DIR.mkdir(exist_ok=True)
    (work/'script.txt').write_text(script,encoding='utf-8'); model=VOICE_DIR/f'{VOICE_MODEL}.onnx'
    if not model.exists(): run(['python','-m','piper.download_voices','--download-dir',str(VOICE_DIR),VOICE_MODEL])
    raw=work/'raw.wav'
    with (work/'script.txt').open() as src: run(['piper','--model',str(model),'--output_file',str(raw),'--length-scale','0.91'],stdin=src)
    audio=work/'voice.wav'
    run(['ffmpeg','-y','-i',str(raw),'-af','highpass=f=75,lowpass=f=12500,acompressor=threshold=-19dB:ratio=2.2:attack=12:release=180,equalizer=f=180:t=q:w=1:g=1.5,equalizer=f=3200:t=q:w=1:g=1.2,loudnorm=I=-15:TP=-1.2:LRA=9','-ar','48000','-ac','2',str(audio)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    dur=duration(audio); ss=sentences(script); scene_count=max(8,min(12,math.ceil(dur/4.5)))
    scene_copy=[ss[min(len(ss)-1,math.floor(i*len(ss)/scene_count))] if ss else project.get('title','') for i in range(scene_count)]
    sd=work/'scenes'; sd.mkdir(exist_ok=True); paths=[sd/f's{i:02}.jpg' for i in range(scene_count)]
    workers=min(8,scene_count)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(make_scene,[(paths[i],scene_copy[i],i,scene_count) for i in range(scene_count)]))

    words=script.split(); chunks=[' '.join(words[i:i+5]) for i in range(0,len(words),5)]; weights=[max(1,len(re.sub(r'\W','',c))) for c in chunks]; total=sum(weights); cur=0; lines=[]
    for i,(c,w) in enumerate(zip(chunks,weights),1):
        start=cur; cur+=dur*w/total; lines += [str(i),f'{ts(start)} --> {ts(dur if i==len(chunks) else cur)}',c,'']
    cap=work/'captions.srt'; cap.write_text('\n'.join(lines),encoding='utf-8')

    # One FFmpeg process: animate all stills, concatenate, burn captions, add mastered audio, encode once.
    seg=dur/scene_count; ff=['ffmpeg','-y']
    for p in paths: ff += ['-loop','1','-t',f'{seg:.4f}','-i',str(p)]
    audio_index=scene_count; ff += ['-i',str(audio)]
    filters=[]; labels=[]
    frames=max(1,int(seg*30)+2)
    for i in range(scene_count):
        zoom="min(zoom+0.0012,1.10)" if i%2==0 else "if(lte(zoom,1.0),1.10,max(1.0,zoom-0.0012))"
        label=f'v{i}'; labels.append(f'[{label}]')
        filters.append(f"[{i}:v]scale=1200:2134,zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps=30,setsar=1[{label}]")
    filters.append(''.join(labels)+f'concat=n={scene_count}:v=1:a=0[story]')
    filters.append(f"[story]subtitles={cap}:force_style='FontName=DejaVu Sans,FontSize=30,Bold=1,PrimaryColour=&H00FFFFFF,BackColour=&HB0000000,BorderStyle=3,Outline=0,Alignment=2,MarginL=65,MarginR=65,MarginV=210'[vout]")
    out=work/'output.mp4'
    ff += ['-filter_complex',';'.join(filters),'-map','[vout]','-map',f'{audio_index}:a','-c:v','libx264','-preset','superfast','-crf','20','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart','-threads','0','-shortest',str(out)]
    run(ff,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    run(['ffmpeg','-v','error','-i',str(out),'-f','null','-'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    if out.stat().st_size<300000: raise RuntimeError('Output failed size validation.')
    obj=f"{job['user_id']}/{job['project_id']}/{job['id']}.mp4"; url=SUPABASE_URL+'/storage/v1/object/video-outputs/'+urllib.parse.quote(obj,safe='/')
    with out.open('rb') as f:
        req=urllib.request.Request(url,data=f.read(),headers={'apikey':SERVICE_KEY,'Authorization':f'Bearer {SERVICE_KEY}','Content-Type':'video/mp4','x-upsert':'true'},method='POST'); urllib.request.urlopen(req,timeout=180).read()
    patch('render_jobs',job['id'],{'status':'completed','engine':ENGINE,'output_url':obj,'error':None,'updated_at':'now()'}); patch('video_projects',project['id'],{'output_url':obj,'status':'quality_check','failure_reason':None,'updated_at':'now()'})
    pipe(project['id'],'voice','passed','Neural narration generated and mastered.'); pipe(project['id'],'visuals','passed',f'{scene_count} illustrated story scenes generated in parallel with continuous camera motion.'); pipe(project['id'],'edit','passed','Single-pass 1080x1920 H.264/AAC encode with burned captions decoded successfully.')
    print(f'Rendered {obj} ({dur:.1f}s, {scene_count} animated scenes, single-pass encode, {out.stat().st_size/1e6:.1f} MB)')
except Exception as exc:
    msg=str(exc)[:1000]; patch('render_jobs',job['id'],{'status':'failed','engine':ENGINE,'error':msg,'updated_at':'now()'}); patch('video_projects',job['project_id'],{'status':'failed','failure_reason':msg,'updated_at':'now()'})
    for s in ('voice','visuals','edit'):
        try: pipe(job['project_id'],s,'failed',msg)
        except Exception: pass
    raise
