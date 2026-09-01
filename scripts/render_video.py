import json, math, os, subprocess, textwrap, urllib.parse, urllib.request
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

SUPABASE_URL=os.environ.get('SUPABASE_URL','').rstrip('/')
SERVICE_KEY=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')
if not SUPABASE_URL or not SERVICE_KEY:
    raise SystemExit('SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY repository secrets are required.')

HEADERS={'apikey':SERVICE_KEY,'Authorization':f'Bearer {SERVICE_KEY}','Content-Type':'application/json'}

def request(method,path,data=None,extra_headers=None):
    body=None if data is None else json.dumps(data).encode()
    headers=dict(HEADERS)
    if extra_headers: headers.update(extra_headers)
    req=urllib.request.Request(SUPABASE_URL+path,data=body,headers=headers,method=method)
    with urllib.request.urlopen(req,timeout=60) as r:
        raw=r.read()
        return json.loads(raw.decode()) if raw else None

def patch(table,row_id,payload):
    return request('PATCH',f'/rest/v1/{table}?id=eq.{row_id}',payload,{'Prefer':'return=minimal'})

jobs=request('GET','/rest/v1/render_jobs?status=eq.queued&select=*&order=created_at.asc&limit=1') or []
if not jobs:
    print('No queued render jobs.')
    raise SystemExit(0)
job=jobs[0]
patch('render_jobs',job['id'],{'status':'running','updated_at':'now()'})

try:
    projects=request('GET',f"/rest/v1/video_projects?id=eq.{job['project_id']}&select=*") or []
    if not projects: raise RuntimeError('Project not found.')
    project=projects[0]
    script=(project.get('script') or '').strip()
    title=(project.get('title') or 'Untitled video').strip()
    if not script: raise RuntimeError('Add a script before requesting a render.')

    work=Path('render-work'); work.mkdir(exist_ok=True)
    script_file=work/'script.txt'; script_file.write_text(script,encoding='utf-8')
    audio=work/'voice.wav'
    subprocess.run(['espeak-ng','-s','165','-w',str(audio),'-f',str(script_file)],check=True)
    duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(audio)]).decode().strip())

    W,H=1080,1920
    img=Image.new('RGB',(W,H),(10,12,18)); d=ImageDraw.Draw(img)
    for y in range(H):
        v=int(12 + 28*y/H)
        d.line([(0,y),(W,y)],fill=(v//2,v//2+3,v))
    font_path='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
    title_font=ImageFont.truetype(font_path,64)
    small_font=ImageFont.truetype(font_path,34)
    wrapped=textwrap.wrap(title,width=24)[:4]
    y=640
    for line in wrapped:
        box=d.textbbox((0,0),line,font=title_font); x=(W-(box[2]-box[0]))/2
        d.text((x,y),line,font=title_font,fill='white'); y+=82
    footer='YouTube AI · original render'
    box=d.textbbox((0,0),footer,font=small_font); d.text(((W-(box[2]-box[0]))/2,1660),footer,font=small_font,fill=(175,182,198))
    bg=work/'background.png'; img.save(bg)

    words=script.split(); chunk_size=8
    chunks=[' '.join(words[i:i+chunk_size]) for i in range(0,len(words),chunk_size)] or ['']
    srt=[]
    def ts(sec):
        ms=int(round(sec*1000)); h=ms//3600000; ms%=3600000; m=ms//60000; ms%=60000; s=ms//1000; ms%=1000
        return f'{h:02}:{m:02}:{s:02},{ms:03}'
    for i,c in enumerate(chunks):
        start=duration*i/len(chunks); end=duration*(i+1)/len(chunks)
        srt += [str(i+1),f'{ts(start)} --> {ts(end)}',c,'']
    captions=work/'captions.srt'; captions.write_text('\n'.join(srt),encoding='utf-8')

    output=work/'output.mp4'
    vf=f"subtitles={captions}:force_style='FontName=DejaVu Sans,FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=210'"
    subprocess.run(['ffmpeg','-y','-loop','1','-i',str(bg),'-i',str(audio),'-vf',vf,'-r','30','-c:v','libx264','-preset','veryfast','-pix_fmt','yuv420p','-c:a','aac','-b:a','128k','-shortest',str(output)],check=True)

    object_path=f"{job['user_id']}/{job['project_id']}/{job['id']}.mp4"
    upload_url=SUPABASE_URL+'/storage/v1/object/video-outputs/'+urllib.parse.quote(object_path,safe='/')
    with open(output,'rb') as f:
        req=urllib.request.Request(upload_url,data=f.read(),headers={'apikey':SERVICE_KEY,'Authorization':f'Bearer {SERVICE_KEY}','Content-Type':'video/mp4','x-upsert':'true'},method='POST')
        with urllib.request.urlopen(req,timeout=120) as r: r.read()

    patch('render_jobs',job['id'],{'status':'completed','output_url':object_path,'updated_at':'now()'})
    patch('video_projects',project['id'],{'output_url':object_path,'status':'quality_check','updated_at':'now()'})
    print('Rendered',object_path)
except Exception as exc:
    patch('render_jobs',job['id'],{'status':'failed','error':str(exc)[:1000],'updated_at':'now()'})
    patch('video_projects',job['project_id'],{'status':'failed','failure_reason':str(exc)[:1000],'updated_at':'now()'})
    raise
