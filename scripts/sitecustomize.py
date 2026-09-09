"""Production startup hook: hardens semantic visual scoring and optionally upgrades selected stills to generated video."""
import hashlib, os
try:
 import visual_sources as _v
 _base_relevance=_v.relevance
 def _semantic_relevance(plan,item):
  provider=str(item.get('provider') or '')
  # Pexels search itself is semantic, but its adapter historically copied the query into title/tags.
  # Give it a moderate search prior instead of allowing self-inserted query text to score as a perfect match.
  if provider=='pexels':
   score=.62
   if item.get('media_type')=='video':score+=.05
   if plan.get('domain')=='nature':score+=.04
   return round(min(.74,score),3)
  # For other providers, score only real source metadata; never the query copied into tags.
  q=set(_v.words(' '.join(plan.get('keywords') or [])))
  hay=set(_v.words(' '.join([str(item.get('title') or ''),str(item.get('description') or ''),str(item.get('credit') or '')])))
  overlap=len(q&hay)/max(1,len(q))
  score=.16+overlap*.72
  if item.get('media_type')=='video':score+=.07
  if provider=='local-motion':score+=.12
  if plan.get('domain')=='history' and provider.startswith('wikimedia'):score+=.08
  if plan.get('domain')=='science' and provider in ('wikimedia-video','wikimedia','local-motion'):score+=.06
  if plan.get('domain')=='nature' and provider in ('wikimedia-video','wikimedia'):score+=.05
  if overlap==0 and provider!='local-motion':score=min(score,.34)
  return round(min(1.0,score),3)
 _v.relevance=_semantic_relevance
except Exception as e:print('Semantic visual scoring hardening unavailable:',str(e)[:240])

if os.environ.get('GENERATIVE_VIDEO_ENABLED','1')!='0':
 try:
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

try:
 from storage_upload import install_legacy_urllib_transport as _install_storage_transport
 _install_storage_transport()
except Exception as e:print('Resumable storage transport unavailable:',str(e)[:240])
