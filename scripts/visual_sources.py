import hashlib, html, json, os, re, urllib.error, urllib.parse, urllib.request
from pathlib import Path

PEXELS_API_KEY=os.environ.get('PEXELS_API_KEY','').strip()
CACHE=Path(os.environ.get('ROLIXA_VISUAL_CACHE','.rolixa-cache')); CACHE.mkdir(exist_ok=True)
SEARCH_CACHE=CACHE/'search.json'
try: _cache=json.loads(SEARCH_CACHE.read_text()) if SEARCH_CACHE.exists() else {}
except Exception: _cache={}
UA='RolixaVisualRouter/2.0 (free licensed media matching)'
STOP={'this','that','with','from','have','will','your','they','them','then','into','about','while','where','when','what','people','video','right','really','just','every','inside','thing','things','there','their','would','could','should','scene','chapter'}

def words(s): return [x.lower() for x in re.findall(r"[A-Za-z0-9']+",s or '') if len(x)>2 and x.lower() not in STOP]
def uniq(xs):
 out=[];seen=set()
 for x in xs:
  k=str(x).lower()
  if k not in seen:seen.add(k);out.append(x)
 return out

def fetch_json(url,headers=None,timeout=25):
 req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'application/json',**(headers or {})})
 with urllib.request.urlopen(req,timeout=timeout) as r:return json.loads(r.read().decode())

def strip_html(v): return re.sub(r'<[^>]+>','',html.unescape(str(v or ''))).strip()
def cache_get(k): return _cache.get(k)
def cache_put(k,v):
 _cache[k]=v
 try:SEARCH_CACHE.write_text(json.dumps(_cache)[-1500000:],encoding='utf-8')
 except Exception:pass

def classify(text,project=None):
 low=(' '.join([text or '',(project or {}).get('topic') or '',(project or {}).get('title') or '',(project or {}).get('style') or ''])).lower()
 if any(x in low for x in ['chapter','mermaid','neon harbor','fiction','animated','animation','cyberpunk','fantasy','mystery story']):return 'fiction'
 if any(x in low for x in ['history','historic','war','president','king','queen','ancient','archive','museum']):return 'history'
 if any(x in low for x in ['animal','wildlife','ocean','forest','bird','wolf','lion','nature','reef','whale','shark']):return 'nature'
 if any(x in low for x in ['science','space','planet','cell','physics','engine','diagram','technology']):return 'science'
 return 'general'

def plan_scene(text,project=None,shot_type='environment'):
 keys=uniq(words(text)[:7]+words((project or {}).get('topic') or (project or {}).get('title') or '')[:4])
 domain=classify(text,project); query=' '.join(keys[:8]) or 'cinematic environment'
 # Search terms stay literal; provider ranking handles style rather than contaminating queries with vague stock-photo words.
 return {'text':text,'domain':domain,'query':query,'keywords':keys[:8],'shot_type':shot_type}

def relevance(plan,item):
 q=set(plan.get('keywords') or []); hay=set(words(' '.join([str(item.get('title') or ''),str(item.get('tags') or ''),str(item.get('description') or ''),str(item.get('credit') or '')])))
 overlap=len(q & hay)/max(1,len(q)); provider=item.get('provider')
 bonus={'wikimedia':.10,'openverse':.08,'pexels':.06,'local-graphic':.03}.get(provider,0)
 if plan.get('domain')=='history' and provider=='wikimedia':bonus+=.16
 if plan.get('domain')=='nature' and provider in ('pexels','openverse','wikimedia'):bonus+=.10
 if plan.get('domain')=='fiction' and provider=='local-graphic':bonus+=.18
 if plan.get('domain')=='science' and provider in ('wikimedia','openverse','local-graphic'):bonus+=.11
 return min(1.0,.25+overlap*.65+bonus)

def pexels(q):
 if not PEXELS_API_KEY:return []
 k='pexels:'+q
 if cache_get(k) is not None:return cache_get(k)
 try:data=fetch_json('https://api.pexels.com/v1/videos/search?'+urllib.parse.urlencode({'query':q,'per_page':12,'size':'medium'}),{'Authorization':PEXELS_API_KEY})
 except Exception:return []
 out=[]
 for v in data.get('videos') or []:
  fs=sorted(v.get('video_files') or [],key=lambda x:(x.get('width') or 0)*(x.get('height') or 0),reverse=True)
  f=next((x for x in fs if x.get('link') and (x.get('height') or 0)>=720),None)
  if f:out.append({'provider':'pexels','media_type':'video','id':f"pexels:{v.get('id')}",'url':f['link'],'page':v.get('url'),'credit':(v.get('user') or {}).get('name'),'license':'Pexels License','title':q,'tags':q})
 cache_put(k,out);return out

def openverse(q):
 k='openverse:'+q
 if cache_get(k) is not None:return cache_get(k)
 try:data=fetch_json('https://api.openverse.org/v1/images/?'+urllib.parse.urlencode({'q':q,'page_size':15,'mature':'false'}))
 except Exception:return []
 out=[]
 for x in data.get('results') or []:
  url=x.get('url') or x.get('thumbnail')
  if not url:continue
  lic=' '.join(filter(None,[x.get('license'),x.get('license_version')])).strip() or 'Open license'
  out.append({'provider':'openverse','media_type':'image','id':'openverse:'+str(x.get('id')),'url':url,'page':x.get('foreign_landing_url') or x.get('detail_url'),'credit':x.get('creator'),'license':lic,'title':x.get('title'),'tags':' '.join(t.get('name','') if isinstance(t,dict) else str(t) for t in (x.get('tags') or [])[:12]),'description':x.get('title')})
 cache_put(k,out);return out

def wikimedia(q):
 k='wikimedia:'+q
 if cache_get(k) is not None:return cache_get(k)
 params={'action':'query','format':'json','generator':'search','gsrsearch':q+' filetype:bitmap','gsrnamespace':6,'gsrlimit':12,'prop':'imageinfo','iiprop':'url|extmetadata','iiurlwidth':1400,'origin':'*'}
 try:data=fetch_json('https://commons.wikimedia.org/w/api.php?'+urllib.parse.urlencode(params))
 except Exception:return []
 out=[]
 for p in (data.get('query') or {}).get('pages',{}).values():
  ii=((p.get('imageinfo') or [{}])[0]); meta=ii.get('extmetadata') or {}; url=ii.get('thumburl') or ii.get('url')
  if not url:continue
  license_name=strip_html((meta.get('LicenseShortName') or {}).get('value')) or 'Wikimedia Commons license'
  credit=strip_html((meta.get('Artist') or {}).get('value')) or strip_html((meta.get('Credit') or {}).get('value'))
  desc=strip_html((meta.get('ImageDescription') or {}).get('value'))
  out.append({'provider':'wikimedia','media_type':'image','id':'wikimedia:'+str(p.get('pageid')),'url':url,'page':'https://commons.wikimedia.org/wiki/'+urllib.parse.quote(str(p.get('title') or '').replace(' ','_')),'credit':credit,'license':license_name,'title':p.get('title'),'description':desc,'tags':q})
 cache_put(k,out);return out

def candidates(plan):
 q=plan['query'];domain=plan['domain']
 providers={'pexels':lambda:pexels(q),'wikimedia':lambda:wikimedia(q),'openverse':lambda:openverse(q)}
 order={'history':['wikimedia','openverse','pexels'],'nature':['pexels','openverse','wikimedia'],'science':['wikimedia','openverse','pexels'],'fiction':['openverse','wikimedia','pexels'],'general':['pexels','openverse','wikimedia']}[domain]
 out=[]
 for name in order:
  for x in providers[name]():
   x=dict(x);x['relevance_score']=round(relevance(plan,x),3);out.append(x)
 return sorted(out,key=lambda x:x['relevance_score'],reverse=True)

def choose(plan,used=None,min_score=.42):
 used=used or set()
 for x in candidates(plan):
  if x.get('id') not in used and x.get('relevance_score',0)>=min_score:return x
 return None

def local_graphic_asset(plan,index):
 title=' '.join((plan.get('keywords') or [])[:5]) or 'Story beat'
 return {'provider':'local-graphic','media_type':'graphic','id':f"graphic:{index}:{hashlib.sha1(title.encode()).hexdigest()[:10]}",'url':None,'page':None,'credit':'Generated locally by Rolixa','license':'Original Rolixa graphic','title':title,'tags':' '.join(plan.get('keywords') or []),'relevance_score':round(relevance(plan,{'provider':'local-graphic','title':title,'tags':title}),3)}
