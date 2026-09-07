import json, os, time, urllib.request
RUNWAY=os.environ.get('RUNWAYML_API_SECRET','').strip();LUMA=os.environ.get('LUMA_API_KEY','').strip()
def available():return 'runway' if RUNWAY else ('luma' if LUMA else None)
def _json(method,url,key,body=None,headers=None,timeout=120):
 h={'Authorization':f'Bearer {key}','Content-Type':'application/json','Accept':'application/json'};h.update(headers or {});req=urllib.request.Request(url,data=None if body is None else json.dumps(body).encode(),headers=h,method=method)
 with urllib.request.urlopen(req,timeout=timeout) as r:return json.loads(r.read().decode())
def runway_url(image_url,prompt,vertical=False,duration=5):
 ratio='720:1280' if vertical else '1280:720';task=_json('POST','https://api.dev.runwayml.com/v1/image_to_video',RUNWAY,{'promptImage':image_url,'promptText':prompt[:1000],'model':'gen4.5','ratio':ratio,'duration':5 if duration<=5 else 10},{'X-Runway-Version':'2024-11-06'});tid=task['id'];deadline=time.time()+900
 while time.time()<deadline:
  time.sleep(8);s=_json('GET',f'https://api.dev.runwayml.com/v1/tasks/{tid}',RUNWAY,headers={'X-Runway-Version':'2024-11-06'});state=str(s.get('status') or '').upper()
  if state=='SUCCEEDED':
   out=s.get('output') or [];url=out[0] if isinstance(out,list) and out else (out.get('video') if isinstance(out,dict) else None)
   if not url:raise RuntimeError('Runway completed without a video URL.')
   return {'url':url,'provider':'runway-gen4.5','task_id':tid}
  if state in ('FAILED','CANCELLED'):raise RuntimeError('Runway generation failed: '+str(s.get('failure') or s.get('failureCode') or state))
 raise TimeoutError('Runway generation timed out.')
def luma_url(image_url,prompt,vertical=False,duration=5):
 body={'prompt':prompt[:6000],'model':'ray-2','aspect_ratio':'9:16' if vertical else '16:9','resolution':'720p','duration':'5s' if duration<=5 else '10s','keyframes':{'frame0':{'type':'image','url':image_url}}};task=_json('POST','https://api.lumalabs.ai/dream-machine/v1/generations/video',LUMA,body);tid=task['id'];deadline=time.time()+900
 while time.time()<deadline:
  time.sleep(8);s=_json('GET',f'https://api.lumalabs.ai/dream-machine/v1/generations/{tid}',LUMA);state=str(s.get('state') or '').lower()
  if state=='completed':
   url=(s.get('assets') or {}).get('video')
   if not url:raise RuntimeError('Luma completed without a video URL.')
   return {'url':url,'provider':'luma-ray-2','task_id':tid}
  if state=='failed':raise RuntimeError('Luma generation failed: '+str(s.get('failure_reason') or state))
 raise TimeoutError('Luma generation timed out.')
def generate_url(image_url,prompt,vertical=False,duration=5):
 if RUNWAY:return runway_url(image_url,prompt,vertical,duration)
 if LUMA:return luma_url(image_url,prompt,vertical,duration)
 return None
