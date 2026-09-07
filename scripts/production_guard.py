import json, math, re, subprocess
from pathlib import Path

OUTLINE_MARKERS=[r'(?im)^\s*(?:OPENING|ENDING|SCENE\s+\d+|CONTINUITY RULE)\s*[—:-]',r'(?i)queued for ',r'(?i)visual planner',r'(?i)production note']
WEAK_PHRASES=['looks ordinary until one detail changes the whole story','catch the wave before it moves on','this is the moment where a normal upload turns into','nobody knows what happens next']

def sentences(text):
    return [re.sub(r'\s+',' ',s).strip() for s in re.split(r'(?<=[.!?])\s+|\n+',str(text or '')) if len(s.strip().split())>2]

def words(text):
    return re.findall(r"[A-Za-z0-9']+",str(text or '').lower())

def _target_words(project):
    target=max(1,int(project.get('target_duration_seconds') or 60))
    fmt=str(project.get('format') or '').lower()
    if fmt in ('short','shorts','story') and target<=120:return max(55,int(target*1.7)),max(95,int(target*2.8))
    return max(500,int(target*1.55)),max(850,int(target*2.45))

def creative_preflight(project):
    script=str(project.get('script') or '').strip();hook=str(project.get('hook') or '').strip();ss=sentences(script);ws=words(script);reasons=[];score=100.0
    low,high=_target_words(project)
    if len(ws)<low:reasons.append(f'script too short ({len(ws)} words; target at least {low})');score-=30
    if len(ws)>high:reasons.append(f'script too dense ({len(ws)} words; target at most {high})');score-=12
    if len(ss)<6:reasons.append('not enough narrative beats');score-=20
    if not hook or len(words(hook))<5:reasons.append('opening hook is weak or missing');score-=18
    if len(words(hook))>24:reasons.append('opening hook is too long');score-=8
    if hook and hook[-1:] not in '.?!':score-=3
    for pat in OUTLINE_MARKERS:
        if re.search(pat,script):reasons.append('production directions leaked into spoken script');score-=45;break
    low_script=script.lower()
    if any(p in low_script for p in WEAK_PHRASES):reasons.append('known generic/template phrasing detected');score-=18
    normalized=[re.sub(r'\W+',' ',s.lower()).strip() for s in ss]
    dup=1-(len(set(normalized))/max(1,len(normalized)))
    if dup>.08:reasons.append(f'repeated sentence structure is too high ({dup:.0%})');score-=min(25,dup*80)
    starts=[s.split()[0].lower() for s in ss if s.split()]
    if starts and max(starts.count(x) for x in set(starts))/len(starts)>.35:reasons.append('too many sentences start the same way');score-=10
    lengths=[len(words(s)) for s in ss]
    if lengths and max(lengths)-min(lengths)<5:reasons.append('sentence rhythm is too uniform');score-=7
    if len(set(words(script)))<min(70,max(30,len(ws)//4)):reasons.append('vocabulary is too repetitive');score-=8
    score=max(0,round(score,1));return {'passed':score>=78 and not any('leaked' in r for r in reasons),'score':score,'reasons':reasons,'metrics':{'words':len(ws),'sentences':len(ss),'duplicate_sentence_ratio':round(dup,3),'target_word_range':[low,high]}}

def _ffprobe(path):
    raw=subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height,r_frame_rate:format=duration,size','-of','json',str(path)]).decode();return json.loads(raw)

def _detect(path):
    p=subprocess.run(['ffmpeg','-hide_banner','-nostats','-i',str(path),'-vf','blackdetect=d=0.35:pix_th=0.10,freezedetect=n=-45dB:d=1.0','-af','silencedetect=n=-48dB:d=2.5','-f','null','-'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
    text=p.stderr or ''
    black=[float(x) for x in re.findall(r'black_duration:([0-9.]+)',text)]
    freeze=[float(x) for x in re.findall(r'freeze_duration: ([0-9.]+)',text)]
    silence=[]
    starts=[float(x) for x in re.findall(r'silence_start: ([0-9.]+)',text)];ends=[float(x) for x in re.findall(r'silence_end: ([0-9.]+)',text)]
    for a,b in zip(starts,ends):silence.append(max(0,b-a))
    return {'max_black_seconds':max(black or [0]),'max_freeze_seconds':max(freeze or [0]),'max_silence_seconds':max(silence or [0])}

def final_video_qc(path,project,assets):
    path=Path(path);reasons=[];score=100.0;meta=_ffprobe(path);fmt=meta.get('format') or {};stream=(meta.get('streams') or [{}])[0];dur=float(fmt.get('duration') or 0);size=int(fmt.get('size') or 0);w=int(stream.get('width') or 0);h=int(stream.get('height') or 0);target=float(project.get('target_duration_seconds') or dur or 1);kind=str(project.get('format') or '').lower();longform=target>120 or kind in ('long','longform','full','youtube')
    motion=sum(1 for a in assets if a.get('media_type') in ('video','graphic'));images=sum(1 for a in assets if a.get('media_type')=='image');motion_ratio=motion/max(1,len(assets));image_ratio=images/max(1,len(assets));providers=len({a.get('provider') for a in assets if a.get('provider')});detect=_detect(path)
    if size<750000:reasons.append('file is too small to be a trustworthy final render');score-=35
    expected=(16/9 if longform else 9/16);ratio=w/max(1,h)
    if abs(ratio-expected)>.08:reasons.append(f'wrong aspect ratio {w}x{h}');score-=25
    min_motion=.70 if longform else .80
    if motion_ratio<min_motion:reasons.append(f'motion coverage only {motion_ratio:.0%}; need at least {min_motion:.0%}');score-=35
    if not longform and image_ratio>.20:reasons.append(f'still-image coverage {image_ratio:.0%} exceeds 20%');score-=25
    if len(assets)>=8 and providers<2:score-=5
    if dur<target*.65 or dur>target*1.45:reasons.append(f'finished duration {dur:.1f}s misses target {target:.0f}s');score-=18
    if detect['max_black_seconds']>.7:reasons.append(f'black frame run {detect["max_black_seconds"]:.1f}s');score-=20
    if detect['max_freeze_seconds']>1.8:reasons.append(f'frozen visual run {detect["max_freeze_seconds"]:.1f}s');score-=25
    if detect['max_silence_seconds']>4.0:reasons.append(f'unplanned silence {detect["max_silence_seconds"]:.1f}s');score-=15
    score=max(0,round(score,1));metrics={'duration_seconds':round(dur,2),'size_bytes':size,'width':w,'height':h,'motion_ratio':round(motion_ratio,3),'image_ratio':round(image_ratio,3),'provider_count':providers,**detect}
    return {'passed':score>=82 and not reasons,'score':score,'reasons':reasons,'metrics':metrics}

def publication_priority(project,creative_score,quality_score,analytics=None):
    a=analytics or {};retention=float(a.get('average_view_duration_seconds') or 0)/max(1,float(project.get('target_duration_seconds') or 60));engagement=(float(a.get('likes') or 0)+2*float(a.get('comments') or 0)+3*float(a.get('shares') or 0))/max(1,float(a.get('views') or 0));return round(float(creative_score)*.35+float(quality_score)*.50+min(15,retention*10+engagement*100),2)
