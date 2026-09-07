"""Production startup hook: upgrades selected still assets to true generated video when a provider key exists."""
import hashlib, os
if os.environ.get('GENERATIVE_VIDEO_ENABLED','1')!='0':
 try:
  import visual_sources as _v
  from generative_video import available as _available, generate_url
  _original_choose=_v.choose
  def _generated_choose(plan,used=None,min_score=.42,used_providers=None):
   pool=_v.candidates(plan);images=[x for x in pool if x.get('media_type')=='image' and x.get('relevance_score',0)>=min_score]
   rate=max(0,min(100,int(os.environ.get('GENERATIVE_VIDEO_PERCENT','25'))));bucket=int(hashlib.sha256((plan.get('text') or plan.get('query') or '').encode()).hexdigest()[:8],16)%100
   if _available() and images and bucket<rate:
    seed=max(images,key=lambda x:x.get('relevance_score',0));prompt=(plan.get('text') or plan.get('query') or '')+' Cinematic natural motion, physically coherent movement, stable subjects, no text, no logos, no morphing.'
    try:
     g=generate_url(seed['url'],prompt,vertical=os.environ.get('ROLIXA_OUTPUT_VERTICAL','1')=='1',duration=5)
     if g:
      return {**seed,'provider':g['provider'],'media_type':'video','id':f"{g['provider']}:{g['task_id']}",'url':g['url'],'page':seed.get('page'),'credit':seed.get('credit'),'license':seed.get('license'),'relevance_score':min(1.0,float(seed.get('relevance_score') or .5)+.08),'generated_from':seed.get('id')}
    except Exception as e:print('Generative video fallback:',str(e)[:240])
   return _original_choose(plan,used,min_score,used_providers)
  _v.choose=_generated_choose
 except Exception as e:print('Generative video startup unavailable:',str(e)[:240])
