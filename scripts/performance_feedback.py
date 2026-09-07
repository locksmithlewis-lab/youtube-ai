import json, os, statistics, urllib.parse, urllib.request
URL=os.environ.get('SUPABASE_URL','').rstrip('/');KEY=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')
if not URL or not KEY:raise SystemExit('Supabase secrets required.')
H={'apikey':KEY,'Authorization':f'Bearer {KEY}','Content-Type':'application/json'}
def req(method,path,data=None,prefer=None):
 h=dict(H)
 if prefer:h['Prefer']=prefer
 r=urllib.request.Request(URL+path,data=None if data is None else json.dumps(data).encode(),headers=h,method=method)
 with urllib.request.urlopen(r,timeout=60) as x:raw=x.read();return json.loads(raw.decode()) if raw else None
def patch(id,payload):return req('PATCH',f'/rest/v1/video_projects?id=eq.{id}',payload,'return=minimal')
posted=req('GET','/rest/v1/video_projects?status=eq.posted&select=id,style,format,target_duration_seconds&limit=500') or []
latest={}
for p in posted:
 rows=req('GET',f"/rest/v1/analytics_snapshots?project_id=eq.{p['id']}&select=views,average_view_duration_seconds,likes,comments,shares,subscribers_gained,captured_at&order=captured_at.desc&limit=1") or []
 if rows:latest[p['id']]=rows[0]
profiles={}
for p in posted:
 a=latest.get(p['id']);views=float((a or {}).get('views') or 0)
 if not a or views<=0:continue
 dur=max(1,float(p.get('target_duration_seconds') or 60));ret=min(1.5,float(a.get('average_view_duration_seconds') or 0)/dur);eng=(float(a.get('likes') or 0)+2*float(a.get('comments') or 0)+3*float(a.get('shares') or 0)+4*float(a.get('subscribers_gained') or 0))/views;score=min(100,35*ret+min(35,eng*350)+min(30,statistics.fmean([1,views**0.25])*2));k=(str(p.get('style') or '').lower(),str(p.get('format') or '').lower());profiles.setdefault(k,[]).append(score)
profile={k:statistics.fmean(v) for k,v in profiles.items()}
future=req('GET','/rest/v1/video_projects?status=in.(generating,quality_check,ready,scheduled)&select=id,style,format,creative_score,quality_score,publication_priority&limit=1000') or []
updated=0
for p in future:
 base=float(p.get('creative_score') or 0)*.35+float(p.get('quality_score') or 0)*.50;k=(str(p.get('style') or '').lower(),str(p.get('format') or '').lower());learned=profile.get(k);bonus=0 if learned is None else min(15,learned*.15);priority=round(base+bonus,2)
 if abs(priority-float(p.get('publication_priority') or 0))>.05:patch(p['id'],{'publication_priority':priority,'updated_at':'now()'});updated+=1
print(json.dumps({'posted_with_metrics':len(latest),'performance_profiles':len(profile),'future_projects_ranked':updated,'profiles':{f'{k[0]}|{k[1]}':round(v,2) for k,v in profile.items()}}))
