from pathlib import Path
import json,re,sys
ROOT=Path('.');EXT={'.py','.js','.yml','.yaml','.html','.css'};SKIP={'.git','node_modules','.piper-voices','.rolixa-cache','render-work'}
findings=[]
def add(level,path,n,rule,line):findings.append({'level':level,'file':str(path),'line':n,'rule':rule,'text':line.strip()[:220]})
for path in ROOT.rglob('*'):
 if not path.is_file() or path.suffix.lower() not in EXT or any(x in SKIP for x in path.parts):continue
 try:lines=path.read_text(encoding='utf-8').splitlines()
 except Exception:continue
 for n,line in enumerate(lines,1):
  low=line.lower()
  if re.search(r'\b(todo|fixme|mock|dummy|placeholder)\b',low) and 'placeholder=' not in low:add('warn',path,n,'unfinished_or_placeholder_code',line)
  if path.name in ('quick-generate.js','render_video.py','auto-publish-ready.js','youtube-publish.js') and re.search(r'(?i)rolixa',line):add('warn',path,n,'public_pipeline_brand_reference',line)
  if path.name=='render_video.py' and re.search(r"['\"]status['\"]\s*:\s*['\"]ready['\"]",line):add('critical',path,n,'renderer_bypasses_quality_check',line)
  if path.name not in ('auto_quality.py','auto-publish-ready.js') and re.search(r"status\s*[:=].*['\"]ready['\"]",line) and 'readystatus' not in low:add('warn',path,n,'direct_ready_state_write',line)
  if re.search(r'except Exception\s*:\s*pass',line):add('warn',path,n,'exception_swallowed',line)
  if 'while true' in low or re.search(r'while\s+True\s*:',line):add('warn',path,n,'unbounded_loop_review',line)
  if path.suffix=='.py' and 'urllib.request.urlopen(' in line and 'timeout=' not in line and 'with urllib.request.urlopen' in line:add('warn',path,n,'network_call_without_timeout',line)
  if path.suffix=='.js' and 'privacyStatus' in line and "'public'" in line and path.name not in ('auto-publish-ready.js','youtube-publish.js','auto-publish-clip.js'):add('warn',path,n,'unexpected_public_publish_path',line)
  if any(x in low for x in ['ai generated','#aigenerated','generatedbyai']) and path.name in ('quick-generate.js','hashtags.js','auto-publish-ready.js','youtube-publish.js'):add('warn',path,n,'ai_disclosure_branding_in_public_metadata',line)
  if path.name.endswith('.yml') and 'curl ' in low and '--max-time' not in low:add('warn',path,n,'curl_without_deadline',line)
critical=[x for x in findings if x['level']=='critical'];warn=[x for x in findings if x['level']=='warn']
print(json.dumps({'files_scanned':sum(1 for p in ROOT.rglob('*') if p.is_file() and p.suffix.lower() in EXT),'critical':len(critical),'warnings':len(warn),'findings':findings},indent=2))
sys.exit(1 if critical else 0)
