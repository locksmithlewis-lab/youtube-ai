import json, os, re, urllib.request
from datetime import datetime, timezone
from production_guard import creative_preflight, instruction_leaks

SUPABASE_URL=os.environ.get('SUPABASE_URL','').rstrip('/');KEY=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')
if not SUPABASE_URL or not KEY:raise SystemExit('Supabase secrets required.')
H={'apikey':KEY,'Authorization':f'Bearer {KEY}','Content-Type':'application/json'}
def req(method,path,data=None,prefer=None):
    h=dict(H)
    if prefer:h['Prefer']=prefer
    r=urllib.request.Request(SUPABASE_URL+path,data=None if data is None else json.dumps(data).encode(),headers=h,method=method)
    with urllib.request.urlopen(r,timeout=60) as x:
        raw=x.read();return json.loads(raw.decode()) if raw else None

def patch(table,id,payload):return req('PATCH',f'/rest/v1/{table}?id=eq.{id}',payload,'return=minimal')
def report(p,passed,score,reasons,metrics=None):
    return req('POST','/rest/v1/video_quality_reports',{'user_id':p['user_id'],'project_id':p['id'],'stage':'repair_controller','passed':passed,'score':score,'reasons':reasons,'metrics':metrics or {}},'return=minimal')
def clean_title(title):
    title=re.sub(r'(?i)^\s*(?:signature|showcase)\s*\d+\s*[—:\-]\s*','',str(title or '')).strip()
    return title or 'Untold Story'
def sentence_list(text):
    return [re.sub(r'\s+',' ',s).strip() for s in re.split(r'(?<=[.!?])\s+|\n+',text) if len(s.strip().split())>2]
def clean_script(script):
    s=str(script or '')
    s=re.sub(r'(?im)^\s*(?:OPENING|ENDING|SCENE\s+\d+|CONTINUITY RULE)\s*[—:-]\s*','',s)
    s=re.sub(r'(?im)^.*\b(?:production note|visual planner|queued for)\b.*$',' ',s)
    weak={
      'looks ordinary until one detail changes the whole story':'seems ordinary at first, but one detail changes the story',
      'catch the wave before it moves on':'follow what happens next',
      'this is the moment where a normal upload turns into':'this is where the story becomes',
      'nobody knows what happens next':'what happens next changes the stakes'
    }
    for old,new in weak.items():s=re.sub(re.escape(old),new,s,flags=re.I)
    return re.sub(r'\s+',' ',s).strip()
def diversify_starts(sentences):
    if not sentences:return sentences
    starts=[s.split()[0].lower() for s in sentences if s.split()]
    out=[];seen={};trans=['Meanwhile,','Then,','Soon,','But,','Across the scene,','A moment later,']
    for i,s in enumerate(sentences):
        first=s.split()[0].lower();seen[first]=seen.get(first,0)+1
        if starts.count(first)/max(1,len(starts))>.35 and seen[first]>1:
            s=f'{trans[(seen[first]-2)%len(trans)]} {s[0].lower()+s[1:] if len(s)>1 else s.lower()}'
        out.append(s)
    return out
def fit_short_budget(sentences,high):
    chosen=[];wc=0
    for s in sentences:
        n=len(re.findall(r"[A-Za-z0-9']+",s))
        if chosen and wc+n>high:break
        chosen.append(s);wc+=n
    while len(chosen)<6 and len(chosen)<len(sentences):
        s=sentences[len(chosen)];n=len(re.findall(r"[A-Za-z0-9']+",s))
        if wc+n>high:break
        chosen.append(s);wc+=n
    return chosen
def verified_sources(project_id):
    return req('GET',f'/rest/v1/research_sources?project_id=eq.{project_id}&verified=eq.true&select=title,url,claim&limit=20') or []
def repair_creative(p):
    original_script=str(p.get('script') or '')
    script=clean_script(original_script);title=clean_title(p.get('title'))
    ss=diversify_starts(sentence_list(script))
    probe=dict(p,title=title,script=' '.join(ss));first=creative_preflight(probe);low,high=first['metrics']['target_word_range']
    short=str(p.get('format') or '').lower() in ('short','shorts','story') and int(p.get('target_duration_seconds') or 60)<=120
    if short and len(re.findall(r"[A-Za-z0-9']+",' '.join(ss)))>high:ss=fit_short_budget(ss,high)
    script=' '.join(ss).strip();hook=str(p.get('hook') or '').strip()
    if len(re.findall(r"[A-Za-z0-9']+",hook))<5 and ss:hook=ss[0]
    if len(re.findall(r"[A-Za-z0-9']+",hook))>24:hook=' '.join(hook.split()[:22]).rstrip(',;:')+'.'
    candidate=dict(p,title=title,script=script,hook=hook);result=creative_preflight(candidate)
    return candidate,result

rows=req('GET','/rest/v1/video_projects?status=eq.failed&select=*&order=updated_at.asc&limit=100') or []
repairable=('visual','motion','image','provider','download','429','403','timeout','ffmpeg','decode','audio','silence','freeze','black frame','render','size validation')
creative_faults=('script too','production directions','template phrasing','narrative beats','opening hook','generic batch title','sentences start the same way','sentence rhythm','vocabulary is too repetitive')
nonmechanical=('factual','verified evidence')
requeued=rewritten=discarded=waiting=0
for p in rows:
    reason=str(p.get('failure_reason') or '').lower();attempts=int(p.get('qc_attempts') or 0)
    if attempts>=2:
        report(p,False,0,['automatic repair limit reached'],{'previous_failure':reason,'attempts':attempts});discarded+=1;continue
    now=datetime.now(timezone.utc).isoformat()
    leaks=instruction_leaks(str(p.get('script') or ''))
    if leaks:
        sources=verified_sources(p['id'])
        report(p,False,10,['instruction-script quarantined; automatic trimming is forbidden because it is not narration','verified research required before factual rewrite'],{'previous_failure':reason,'instruction_leaks':leaks[:8],'verified_source_count':len(sources)})
        waiting+=1;continue
    if any(x in reason for x in creative_faults) and not any(x in reason for x in nonmechanical):
        candidate,result=repair_creative(p)
        if result['passed']:
            patch('video_projects',p['id'],{'title':candidate['title'],'script':candidate['script'],'hook':candidate['hook'],'creative_score':result['score'],'status':'generating','output_url':None,'scheduled_publish_at':None,'failure_reason':f'Automatic creative repair passed at {result["score"]}/100; queued for clean rerender.','qc_attempts':attempts+1,'updated_at':now})
            req('POST','/rest/v1/render_jobs',{'user_id':p['user_id'],'project_id':p['id'],'engine':'motion-first-creative-repair','status':'queued'},'return=minimal')
            report(p,True,result['score'],['creative failure repaired and requeued'],{'previous_failure':reason,'attempt':attempts+1,'preflight':result});rewritten+=1;requeued+=1;continue
        report(p,False,result['score'],['automatic creative cleanup did not meet publish-grade threshold'],{'previous_failure':reason,'attempts':attempts,'preflight':result});waiting+=1;continue
    if any(x in reason for x in nonmechanical):
        report(p,False,20,['factual/evidence problem requires verified-source rewrite'],{'previous_failure':reason,'attempts':attempts});waiting+=1;continue
    if not any(x in reason for x in repairable):
        report(p,False,30,['failure is not safely auto-repairable'],{'previous_failure':reason,'attempts':attempts});waiting+=1;continue
    patch('video_projects',p['id'],{'status':'generating','output_url':None,'scheduled_publish_at':None,'failure_reason':f'Automatic repair attempt {attempts+1}: rebuilding failed media/edit components.','qc_attempts':attempts+1,'updated_at':now});req('POST','/rest/v1/render_jobs',{'user_id':p['user_id'],'project_id':p['id'],'engine':'motion-first-repair','status':'queued'},'return=minimal');report(p,True,60,['repairable failure requeued'],{'previous_failure':reason,'attempt':attempts+1});requeued+=1
print(json.dumps({'failed_checked':len(rows),'requeued':requeued,'creative_rewritten':rewritten,'rewrite_needed':waiting,'repair_limit_reached':discarded}))
