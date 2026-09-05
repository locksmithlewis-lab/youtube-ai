import hashlib, json, os, random, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

SUPABASE_URL=os.environ.get('SUPABASE_URL','').rstrip('/')
SERVICE_KEY=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')
if not SUPABASE_URL or not SERVICE_KEY: raise SystemExit('Supabase secrets required.')
HEADERS={'apikey':SERVICE_KEY,'Authorization':f'Bearer {SERVICE_KEY}','Content-Type':'application/json'}

def req(method,path,data=None,prefer=None):
    body=None if data is None else json.dumps(data).encode()
    h=dict(HEADERS)
    if prefer: h['Prefer']=prefer
    r=urllib.request.Request(SUPABASE_URL+path,data=body,headers=h,method=method)
    with urllib.request.urlopen(r,timeout=60) as res:
        raw=res.read(); return json.loads(raw.decode()) if raw else None

def seed_for(series_id,episode_number):
    return int(hashlib.sha256(f'{series_id}:{episode_number}'.encode()).hexdigest()[:16],16)

def choose(rng,items): return items[rng.randrange(len(items))]

def prior_episode(series_id):
    rows=req('GET',f"/rest/v1/series_episodes?series_id=eq.{series_id}&select=episode_number,chapter_title,synopsis,continuity&order=episode_number.desc&limit=1") or []
    return rows[0] if rows else None

def animated_story(series,episode_number):
    rng=random.Random(seed_for(series['id'],episode_number)); bible=series.get('story_bible') or {}; premise=series['premise']
    chars=bible.get('characters') or ['Mara','Jax','Niko','Vale']
    lead=chars[(episode_number-1)%len(chars)]; ally=chars[episode_number%len(chars)]
    goals=['protect a secret','recover what was stolen','prove everyone wrong','escape a dangerous bargain','find the missing clue','save someone before time runs out']
    obstacles=['a trusted friend changes sides','the obvious answer is a trap','a hidden rival arrives first','the plan works for the wrong reason','an old promise comes due','the truth creates a bigger problem']
    reveals=['the enemy already knew the plan','the missing object was never lost','the ally has been hiding part of the truth','the real threat is much closer than anyone thought','yesterday’s victory created today’s danger']
    places=['an abandoned transit station','a rain-soaked rooftop','a crowded night market','a forgotten underground lab','a quiet apartment with one light on','an empty stadium after midnight']
    goal,obstacle,reveal,place=choose(rng,goals),choose(rng,obstacles),choose(rng,reveals),choose(rng,places)
    previous=prior_episode(series['id']); carry=(previous or {}).get('continuity') or {}; open_loop=carry.get('open_loop')
    title=f'Chapter {episode_number}: {choose(rng,["The False Door","No Way Back","The Quiet Signal","Before Midnight","The Missing Piece","The Last Good Lie"])}'
    hook=f'{lead} had one rule: never go back to {place}. Tonight, there was no choice.'
    if open_loop: hook=f'{open_loop} {lead} finally got the answer — and it made everything worse.'
    beats=[
      hook,
      f'{premise} {lead} needed to {goal}, and {ally} was the only person willing to help.',
      f'At {place}, the first move looked easy. Then {obstacle}.',
      f'They pushed forward anyway, trading a safe exit for one more chance to finish the job.',
      f'That was when they discovered {reveal}.',
      f'{lead} had seconds to choose: protect the mission, or protect {ally}.',
      f'The choice worked — barely — but it exposed a new problem neither of them could ignore.',
      f'By sunrise, one thing was certain: the next chapter would cost more than the last.'
    ]
    script=' '.join(beats)
    continuity={'lead':lead,'ally':ally,'location':place,'reveal':reveal,'open_loop':f'The evidence from {place} points to someone inside their own circle.'}
    synopsis=f'{lead} and {ally} pursue a new objective tied to the series premise, hit a reversal at {place}, and uncover a reveal that opens the next chapter.'
    return title,synopsis,script,continuity

def documentary_story(series,episode_number):
    bible=series.get('story_bible') or {}; facts=bible.get('verified_facts') or []
    if not facts:
        raise RuntimeError('Documentary series needs story_bible.verified_facts before automatic factual episode generation.')
    rng=random.Random(seed_for(series['id'],episode_number)); premise=series['premise']
    fact=facts[(episode_number-1)%len(facts)]
    if isinstance(fact,dict):
        fact_text=str(fact.get('fact') or fact.get('claim') or '').strip(); source=str(fact.get('source') or '').strip()
    else: fact_text=str(fact).strip(); source=''
    if not fact_text: raise RuntimeError('Documentary verified fact is empty.')
    angles=['the detail most people miss','the turning point hidden in plain sight','the decision that changed what happened next','the consequence nobody expected','the small clue that explains the bigger story']
    angle=choose(rng,angles); title=f'Chapter {episode_number}: {angle.title()}'
    script=' '.join([
      f'One detail changes the way this story looks: {fact_text}',
      f'That matters because it connects directly to {premise}.',
      'Instead of treating it like trivia, follow the consequence. One decision creates pressure, that pressure creates a reaction, and the reaction changes what comes next.',
      'The interesting part is not just what happened. It is why this detail mattered at that exact moment.',
      f'That is the thread this chapter follows: {angle}.',
      'And once you see that connection, the larger story becomes much harder to ignore.'
    ])
    continuity={'fact':fact_text,'source':source,'open_loop':'The next verified fact should advance the chronology or deepen the causal chain.'}
    return title,f'An evidence-led documentary chapter built around one verified fact and its consequence.',script,continuity

def generate_one(series):
    ep=int(series['next_episode_number']); prior=prior_episode(series['id'])
    if prior and int(prior['episode_number'])>=ep: raise RuntimeError('Duplicate episode blocked.')
    if series['series_type']=='documentary': chapter,synopsis,script,continuity=documentary_story(series,ep)
    else: chapter,synopsis,script,continuity=animated_story(series,ep)
    # Create video project first, then episode link and render job.
    project=(req('POST','/rest/v1/video_projects',{
      'user_id':series['user_id'],'title':f"{series['title']} — {chapter}",'topic':series['premise'],'format':'Short' if int(series['episode_length_seconds'])<=180 else 'Story','style':'Documentary' if series['series_type']=='documentary' else 'Storytime','target_duration_seconds':series['episode_length_seconds'],'status':'generating','hook':script.split('. ')[0].strip(),'script':script
    },'return=representation') or [None])[0]
    if not project: raise RuntimeError('Could not create episode video project.')
    req('POST','/rest/v1/series_episodes',{'user_id':series['user_id'],'series_id':series['id'],'episode_number':ep,'chapter_title':chapter,'synopsis':synopsis,'script':script,'continuity':continuity,'video_project_id':project['id'],'status':'generating'},'return=minimal')
    steps=[]
    for step,status,detail in [
      ('research','running' if series['series_type']=='documentary' else 'passed','Series continuity loaded.'),('script','passed','Original chapter generated from series bible and prior continuity.'),('voice','running','Queued for neural narration.'),('visuals','running','Queued for animated character/graphics renderer.'),('edit','running','Queued for final edit.'),('quality_check','pending',None),('ready','pending',None)]:
      steps.append({'user_id':series['user_id'],'project_id':project['id'],'step':step,'status':status,'detail':detail})
    req('POST','/rest/v1/project_pipeline_steps',steps,'return=minimal')
    req('POST','/rest/v1/hook_variants',{'user_id':series['user_id'],'project_id':project['id'],'hook':project['hook'],'selected':True},'return=minimal')
    req('POST','/rest/v1/render_jobs',{'user_id':series['user_id'],'project_id':project['id'],'status':'queued'},'return=minimal')
    now=datetime.now(timezone.utc); nxt=now+timedelta(days=1)
    req('PATCH',f"/rest/v1/series_projects?id=eq.{series['id']}",{'next_episode_number':ep+1,'last_generated_at':now.isoformat(),'next_run_at':nxt.isoformat(),'story_bible':{**(series.get('story_bible') or {}),'last_continuity':continuity},'updated_at':now.isoformat()},'return=minimal')
    print(f"Queued {series['title']} episode {ep}: {chapter}")

now=urllib.parse.quote(datetime.now(timezone.utc).isoformat(),safe='')
series=req('GET',f'/rest/v1/series_projects?status=eq.active&cadence=eq.daily&or=(next_run_at.is.null,next_run_at.lte.{now})&select=*&order=created_at.asc') or []
if not series:
    print('No due series episodes.')
else:
    for item in series:
        try: generate_one(item)
        except Exception as exc: print(f"Series {item.get('id')} skipped: {exc}")
