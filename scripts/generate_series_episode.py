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
def animated_story(series,episode_number):
 rng=random.Random(seed_for(series['id'],episode_number)); bible=series.get('story_bible') or {}; premise=series['premise']; chars=bible.get('characters') or ['Mara','Jax','Niko','Vale']; lead=chars[(episode_number-1)%len(chars)]; ally=chars[episode_number%len(chars)]
 goals=['get back the evidence before dawn','reach someone who has stopped answering','recover the one thing they cannot replace','find out who betrayed the group','stop a mistake before anyone notices','get out before the doors lock']; obstacles=['the person they trust most is already there','the obvious route is deliberately blocked','someone else knows exactly what they are looking for','their backup plan makes the situation worse','a promise from the past suddenly matters','the clue points at the last person they expected']; reveals=['the enemy has been listening the whole time','the missing object was planted as bait','their ally knew more than they admitted','the danger is coming from inside the group','their last victory caused this problem']; places=['an abandoned transit station','a rain-soaked rooftop','a crowded night market','a forgotten underground lab','a quiet apartment with one light on','an empty stadium after midnight']
 goal,obstacle,reveal,place=choose(rng,goals),choose(rng,obstacles),choose(rng,reveals),choose(rng,places); previous=prior_episode(series['id']); carry=(previous or {}).get('continuity') or {}; open_loop=carry.get('open_loop'); title=f'Chapter {episode_number}: {choose(rng,["The False Door","No Way Back","The Quiet Signal","Before Midnight","The Missing Piece","The Last Good Lie"])}'
 opening=f'{lead} promised never to return to {place}. Then {ally} sent one message: “I found it. Come alone.”'
 if open_loop: opening=f'{lead} had spent all night thinking about one ugly possibility: {open_loop} Then {ally} called with proof.'
 beats=[opening,f'That changed the plan. {lead} needed to {goal}, and waiting until morning was no longer an option.',f'{ally} met {lead} at {place}. For a moment, it looked like they had arrived first. They had not.',f'{obstacle.capitalize()}. Suddenly the job was not about getting in. It was about deciding who to trust.',f'{lead} wanted to leave. {ally} noticed one detail that made leaving impossible: {reveal}.',f'Now the choice was simple and terrible. Save the mission, or save {ally}. There was not enough time to do both.',f'{lead} chose {ally}. They escaped with seconds to spare, but the evidence they carried made the situation much bigger than either of them expected.',f'By sunrise, they finally understood the cost: someone close to them had been steering events from the beginning. And now that person knew they were onto them.']
 script=' '.join(beats); continuity={'lead':lead,'ally':ally,'location':place,'reveal':reveal,'open_loop':f'The evidence from {place} points to someone inside their own circle.'}; synopsis=f'{lead} and {ally} chase a concrete objective, face a trust-breaking reversal at {place}, make a costly choice, and uncover evidence that drives the next chapter.'; return title,synopsis,script,continuity
def documentary_story(series,episode_number):
 bible=series.get('story_bible') or {}; facts=bible.get('verified_facts') or []
 if not facts: raise RuntimeError('Documentary series needs story_bible.verified_facts before automatic factual episode generation.')
 rng=random.Random(seed_for(series['id'],episode_number)); premise=series['premise']; fact=facts[(episode_number-1)%len(facts)]
 if isinstance(fact,dict): fact_text=str(fact.get('fact') or fact.get('claim') or '').strip(); source=str(fact.get('source') or '').strip()
 else: fact_text=str(fact).strip(); source=''
 if not fact_text: raise RuntimeError('Documentary verified fact is empty.')
 angle=choose(rng,['the detail most people miss','the turning point hidden in plain sight','the decision that changed what happened next','the consequence nobody expected','the small clue that explains the bigger story']); title=f'Chapter {episode_number}: {angle.title()}'
 script=' '.join([f'Here is the detail that changes this story: {fact_text}',f'On its own, that can sound like trivia. It is not. It matters because it connects directly to {premise}.','Look at what happens next. One decision creates pressure. That pressure forces a reaction. And that reaction changes the direction of the story.','That cause-and-effect chain is the part worth remembering. It explains why this moment mattered when it did, not just what happened. ',f'This chapter is really about {angle}.','Once that connection is clear, the bigger story stops looking accidental. The next chapter follows the consequence.']); continuity={'fact':fact_text,'source':source,'open_loop':'The next verified fact should advance the chronology or deepen the causal chain.'}; return title,'An evidence-led documentary chapter organized around a clear cause, consequence and forward question.',script,continuity
def generate_one(series):
 ep=int(series['next_episode_number']); prior=prior_episode(series['id'])
 if prior and int(prior['episode_number'])>=ep: raise RuntimeError('Duplicate episode blocked.')
 if series['series_type']=='documentary': chapter,synopsis,script,continuity=documentary_story(series,ep)
 else: chapter,synopsis,script,continuity=animated_story(series,ep)
 project=(req('POST','/rest/v1/video_projects',{'user_id':series['user_id'],'title':f"{series['title']} — {chapter}",'topic':series['premise'],'format':'Short' if int(series['episode_length_seconds'])<=180 else 'Story','style':'Documentary' if series['series_type']=='documentary' else 'Storytime','target_duration_seconds':series['episode_length_seconds'],'status':'generating','hook':script.split('. ')[0].strip(),'script':script},'return=representation') or [None])[0]
 if not project: raise RuntimeError('Could not create episode video project.')
 req('POST','/rest/v1/series_episodes',{'user_id':series['user_id'],'series_id':series['id'],'episode_number':ep,'chapter_title':chapter,'synopsis':synopsis,'script':script,'continuity':continuity,'video_project_id':project['id'],'status':'generating'},'return=minimal'); steps=[]
 for step,status,detail in [('research','running' if series['series_type']=='documentary' else 'passed','Series continuity loaded.'),('script','passed','Human-paced chapter with hook, goal, reversal, choice, payoff and open loop.'),('voice','running','Queued for natural narration.'),('visuals','running','Queued for story-matched safe-frame visuals.'),('edit','running','Queued for safe-area captions and final edit.'),('quality_check','pending',None),('ready','pending',None)]: steps.append({'user_id':series['user_id'],'project_id':project['id'],'step':step,'status':status,'detail':detail})
 req('POST','/rest/v1/project_pipeline_steps',steps,'return=minimal'); req('POST','/rest/v1/hook_variants',{'user_id':series['user_id'],'project_id':project['id'],'hook':project['hook'],'selected':True},'return=minimal'); req('POST','/rest/v1/render_jobs',{'user_id':series['user_id'],'project_id':project['id'],'status':'queued'},'return=minimal'); now=datetime.now(timezone.utc); nxt=now+timedelta(days=1); req('PATCH',f"/rest/v1/series_projects?id=eq.{series['id']}",{'next_episode_number':ep+1,'last_generated_at':now.isoformat(),'next_run_at':nxt.isoformat(),'story_bible':{**(series.get('story_bible') or {}),'last_continuity':continuity},'updated_at':now.isoformat()},'return=minimal'); print(f"Queued {series['title']} episode {ep}: {chapter}")
now=urllib.parse.quote(datetime.now(timezone.utc).isoformat(),safe=''); series=req('GET',f'/rest/v1/series_projects?status=eq.active&cadence=eq.daily&or=(next_run_at.is.null,next_run_at.lte.{now})&select=*&order=created_at.asc') or []
if not series: print('No due series episodes.')
else:
 for item in series:
  try: generate_one(item)
  except Exception as exc: print(f"Series {item.get('id')} skipped: {exc}")
