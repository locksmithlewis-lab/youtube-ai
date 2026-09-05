import hashlib, json, os, random, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta
SUPABASE_URL=os.environ.get('SUPABASE_URL','').rstrip('/'); SERVICE_KEY=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')
if not SUPABASE_URL or not SERVICE_KEY: raise SystemExit('Supabase secrets required.')
HEADERS={'apikey':SERVICE_KEY,'Authorization':f'Bearer {SERVICE_KEY}','Content-Type':'application/json'}
def req(method,path,data=None,prefer=None):
 body=None if data is None else json.dumps(data).encode(); h=dict(HEADERS)
 if prefer:h['Prefer']=prefer
 r=urllib.request.Request(SUPABASE_URL+path,data=body,headers=h,method=method)
 with urllib.request.urlopen(r,timeout=60) as res: raw=res.read(); return json.loads(raw.decode()) if raw else None
def seed_for(series_id,episode_number): return int(hashlib.sha256(f'{series_id}:{episode_number}'.encode()).hexdigest()[:16],16)
def choose(rng,items): return items[rng.randrange(len(items))]
def prior_episode(series_id):
 rows=req('GET',f"/rest/v1/series_episodes?series_id=eq.{series_id}&select=episode_number,chapter_title,synopsis,continuity&order=episode_number.desc&limit=1") or []; return rows[0] if rows else None
def ensure_master(series):
 bible=series.get('story_bible') or {}; master=bible.get('master_story') or {}
 if not master:
  chars=bible.get('characters') or ['Mara','Jax','Niko','Vale']
  master={'logline':f"{series['premise']} One continuous escalating story follows {', '.join(chars[:5])} as every discovery changes the next choice.",'central_question':'What is really happening, who can be trusted, and what will the characters sacrifice to reach the truth?','acts':[{'name':'Act I — Discovery','range':[1,20]},{'name':'Act II — Escalation','range':[21,45]},{'name':'Act III — Fracture','range':[46,70]},{'name':'Act IV — Reckoning','range':[71,90]},{'name':'Act V — Resolution','range':[91,100]}],'open_threads':['the central mystery','the cost of the first discovery','a trust fracture inside the group'],'resolved_threads':[],'ending':'Resolve the central mystery and major character promises after the final act.'}
  bible['master_story']=master
 return bible,master
def act_for(master,n):
 for a in master.get('acts',[]):
  lo,hi=a.get('range',[1,100])
  if lo<=n<=hi:return a.get('name','Continuing arc')
 return 'Continuing arc'
def animated_story(series,episode_number):
 rng=random.Random(seed_for(series['id'],episode_number)); bible,master=ensure_master(series); chars=bible.get('characters') or ['Mara','Jax','Niko','Vale']; lead=chars[(episode_number-1)%len(chars)]; ally=chars[episode_number%len(chars)]; previous=prior_episode(series['id']); carry=(previous or {}).get('continuity') or bible.get('last_continuity') or {}; prior=carry.get('cliffhanger') or carry.get('open_loop') or 'the unanswered discovery from the previous chapter'; act=act_for(master,episode_number)
 places=['the flooded observation dome','the bioluminescent market','the old tide-control tunnels','the abandoned research pier','the deep-water transit lock','the storm-lit harbor wall','the sealed archive below the marina','the reef beyond the warning buoys']; place=choose(rng,places); thread=choose(rng,master.get('open_threads') or ['the central mystery']); turn=choose(rng,['uncovers evidence that contradicts the group’s safest assumption','realizes a trusted explanation cannot be true','finds a clue connected directly to an earlier chapter','is forced to choose between protecting an ally and following the evidence','discovers that an old warning was actually a map','learns that someone has been hiding part of the truth']); title=f'Chapter {episode_number}: {choose(rng,["The Signal Below","A Door That Should Not Open","The Missing Current","What the Lights Remember","The Name in the Archive","Pressure Line","The False Safe Harbor","The Last Quiet Warning"])}'; cliff=f'A final detail links {thread} to {ally}, forcing {lead} into a dangerous choice in Chapter {episode_number+1}.'
 beats=[f'OPENING — Continue immediately from this unresolved consequence: {prior}. Nothing resets.',f'SCENE 1 — At {place}, {lead} and {ally} pursue the same central question: {master.get("central_question")}',f'SCENE 2 — {lead} {turn}. The evidence advances the existing thread: {thread}.',f'SCENE 3 — The discovery creates conflict because {ally} wants the safer interpretation while {lead} realizes earlier chapters now mean something different.',f'SCENE 4 — They test the theory. The attempt produces a concrete consequence that cannot be undone next chapter.',f'SCENE 5 — A detail from the previous chapter pays off, one piece of the master mystery becomes clearer, and the stakes rise inside {act}.',f'ENDING — {cliff}']
 script=f"{series['title']} — {title}\n{act}\n\n"+'\n\n'.join(beats)+f"\n\nCONTINUITY RULE: This is Chapter {episode_number} of one long master story, not a standalone short story. Preserve knowledge, injuries, promises, relationships, clues and consequences. Every scene causes the next scene and this ending must cause Chapter {episode_number+1}."
 continuity={'chapter':episode_number,'act':act,'lead':lead,'ally':ally,'location':place,'advanced_thread':thread,'previous_cliffhanger':prior,'cliffhanger':cliff,'open_loop':cliff,'master_logline':master.get('logline')}; synopsis=f'{lead} follows the direct consequence of the previous chapter into {place}, where new evidence advances {thread}, changes the group’s understanding of the master mystery, and creates the decision that drives the next chapter.'; return title,synopsis,script,continuity,bible
def documentary_story(series,episode_number):
 bible,master=ensure_master(series); facts=bible.get('verified_facts') or []
 if not facts: raise RuntimeError('Documentary series needs story_bible.verified_facts before automatic factual episode generation.')
 rng=random.Random(seed_for(series['id'],episode_number)); fact=facts[(episode_number-1)%len(facts)]; fact_text=str((fact.get('fact') or fact.get('claim')) if isinstance(fact,dict) else fact).strip(); source=str(fact.get('source') or '') if isinstance(fact,dict) else ''; previous=prior_episode(series['id']); prior=((previous or {}).get('continuity') or {}).get('open_loop') or 'the consequence established in the previous chapter'; act=act_for(master,episode_number); title=f'Chapter {episode_number}: {choose(rng,["The Detail That Changes Everything","The Hidden Turning Point","The Consequence","What Happened Next"])}'; script=f"{series['title']} — {title}\n{act}\n\nContinue from {prior}. Verified fact: {fact_text}\n\nExplain how this fact changes the same central narrative, what caused it, what consequence followed, and why that consequence creates the next chapter. Do not reset the subject or present an unrelated fact.\n\nENDING: The next verified chapter follows the direct consequence of this event."; continuity={'fact':fact_text,'source':source,'act':act,'open_loop':'Follow the direct verified consequence in the next chapter.','master_logline':master.get('logline')}; return title,'A connected evidence-led chapter in the same long-form documentary narrative.',script,continuity,bible
def generate_one(series):
 ep=int(series['next_episode_number']); prior=prior_episode(series['id'])
 if prior and int(prior['episode_number'])>=ep: raise RuntimeError('Duplicate episode blocked.')
 if series['series_type']=='documentary': chapter,synopsis,script,continuity,bible=documentary_story(series,ep)
 else: chapter,synopsis,script,continuity,bible=animated_story(series,ep)
 project=(req('POST','/rest/v1/video_projects',{'user_id':series['user_id'],'title':f"{series['title']} — {chapter}",'topic':synopsis,'format':'Story','style':'Documentary' if series['series_type']=='documentary' else 'Storytime','target_duration_seconds':series['episode_length_seconds'],'status':'generating','hook':script.split('\n')[0].strip(),'script':script},'return=representation') or [None])[0]
 if not project: raise RuntimeError('Could not create episode video project.')
 req('POST','/rest/v1/series_episodes',{'user_id':series['user_id'],'series_id':series['id'],'episode_number':ep,'chapter_title':chapter,'synopsis':synopsis,'script':script,'continuity':continuity,'video_project_id':project['id'],'status':'generating'},'return=minimal')
 steps=[]
 for step,status,detail in [('research','running' if series['series_type']=='documentary' else 'passed','Master story and continuity loaded.'),('script','passed','Connected chapter advances the master story and ends in a causal handoff.'),('voice','running','Queued for natural narration.'),('visuals','running','Queued for story-matched safe-frame visuals.'),('edit','running','Queued for safe-area captions and final edit.'),('quality_check','pending',None),('ready','pending',None)]: steps.append({'user_id':series['user_id'],'project_id':project['id'],'step':step,'status':status,'detail':detail})
 req('POST','/rest/v1/project_pipeline_steps',steps,'resolution=merge-duplicates,return=minimal'); req('POST','/rest/v1/hook_variants',{'user_id':series['user_id'],'project_id':project['id'],'hook':project['hook'],'selected':True},'return=minimal'); req('POST','/rest/v1/render_jobs',{'user_id':series['user_id'],'project_id':project['id'],'status':'queued'},'return=minimal'); now=datetime.now(timezone.utc); bible['last_continuity']=continuity; req('PATCH',f"/rest/v1/series_projects?id=eq.{series['id']}",{'next_episode_number':ep+1,'last_generated_at':now.isoformat(),'next_run_at':(now+timedelta(days=1)).isoformat(),'story_bible':bible,'updated_at':now.isoformat()},'return=minimal'); print(f"Queued connected {series['title']} chapter {ep}: {chapter}")
now=urllib.parse.quote(datetime.now(timezone.utc).isoformat(),safe=''); series=req('GET',f'/rest/v1/series_projects?status=eq.active&cadence=eq.daily&or=(next_run_at.is.null,next_run_at.lte.{now})&select=*&order=created_at.asc') or []
if not series: print('No due series episodes.')
else:
 for item in series:
  try: generate_one(item)
  except Exception as exc: print(f"Series {item.get('id')} skipped: {exc}")
