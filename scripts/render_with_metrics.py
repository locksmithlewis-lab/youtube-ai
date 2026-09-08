import json
import os
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from production_guard import creative_preflight, final_video_qc, publication_priority
from longform_writer import needs_script as long_needs_script, write as write_longform
from shortform_writer import needs_script as short_needs_script, write as write_shortform

URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
H = {'apikey': KEY, 'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json'}


def req(method, path, data=None, prefer=None):
    headers = dict(H)
    if prefer:
        headers['Prefer'] = prefer
    request = urllib.request.Request(URL + path, data=None if data is None else json.dumps(data).encode(), headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=120) as response:
        raw = response.read()
        return json.loads(raw.decode()) if raw else None


def patch(table, item_id, data):
    return req('PATCH', f'/rest/v1/{table}?id=eq.{item_id}', data, 'return=minimal')


def step(project, name, status, detail):
    return req('POST', '/rest/v1/rpc/upsert_project_pipeline_step', {
        'p_user_id': project['user_id'], 'p_project_id': project['id'],
        'p_step': name, 'p_status': status, 'p_detail': detail,
    })


def report(project, job, stage, result):
    return req('POST', '/rest/v1/video_quality_reports', {
        'user_id': project['user_id'], 'project_id': project['id'],
        'render_job_id': job.get('id') if job else None, 'stage': stage,
        'passed': result['passed'], 'score': result['score'],
        'reasons': result.get('reasons') or [], 'metrics': result.get('metrics') or {},
    }, 'return=minimal')


def prepare_shortform(project):
    if not short_needs_script(project):
        return project
    step(project, 'script_writer', 'running', 'Researching the topic and writing final spoken Short narration from a public source.')
    try:
        made = write_shortform(project)
        source = made['source']
        existing = req('GET', f"/rest/v1/research_sources?project_id=eq.{project['id']}&select=id,url") or []
        if source.get('url') and not any(row.get('url') == source['url'] for row in existing):
            req('POST', '/rest/v1/research_sources', {
                'user_id': project['user_id'], 'project_id': project['id'],
                'title': source['title'], 'url': source['url'],
                'claim': 'Automatically retrieved public reference used to construct source-backed narration.',
                'verified': True,
            }, 'return=minimal')
        patch('video_projects', project['id'], {
            'script': made['script'], 'hook': made['hook'], 'title': made['title'], 'updated_at': 'now()',
        })
        project = dict(project, script=made['script'], hook=made['hook'], title=made['title'])
        step(project, 'script_writer', 'passed', f"Generated {made['word_count']} words of sourced spoken narration with {made['model']} from {source['title']}.")
        return project
    except Exception as exc:
        step(project, 'script_writer', 'failed', str(exc))
        raise


def prepare_longform(project):
    if not long_needs_script(project):
        return project
    sources = req('GET', f"/rest/v1/research_sources?project_id=eq.{project['id']}&select=title,url,claim,verified") or []
    step(project, 'script_writer', 'running', 'Writing final long-form spoken narration.')
    try:
        made = write_longform(project, sources)
        patch('video_projects', project['id'], {'script': made['script'], 'hook': made['hook'], 'updated_at': 'now()'})
        project = dict(project, script=made['script'], hook=made['hook'])
        step(project, 'script_writer', 'passed', f"Generated {made['word_count']} words of final narration with {made['model']}.")
        return project
    except Exception as exc:
        step(project, 'script_writer', 'failed', str(exc))
        raise


def preflight_queue():
    jobs = req('GET', '/rest/v1/render_jobs?status=eq.queued&select=id,project_id,user_id&order=created_at.asc&limit=12') or []
    for job in jobs:
        rows = req('GET', f"/rest/v1/video_projects?id=eq.{job['project_id']}&select=*") or []
        if not rows:
            continue
        project = rows[0]
        try:
            project = prepare_shortform(project)
            project = prepare_longform(project)
        except Exception as exc:
            reason = 'Automatic narration writer failed: ' + str(exc)
            patch('render_jobs', job['id'], {'status': 'failed', 'error': reason, 'completed_at': 'now()', 'updated_at': 'now()'})
            patch('video_projects', project['id'], {'status': 'failed', 'output_url': None, 'failure_reason': reason, 'updated_at': 'now()'})
            continue
        result = creative_preflight(project)
        report(project, job, 'creative_preflight', result)
        patch('video_projects', project['id'], {'creative_score': result['score'], 'updated_at': 'now()'})
        detail = f"Creative score {result['score']}/100. " + ('; '.join(result['reasons']) if result['reasons'] else 'Hook, spoken script, title, rhythm, originality and instruction-leak checks passed.')
        step(project, 'creative_preflight', 'passed' if result['passed'] else 'failed', detail)
        if not result['passed']:
            reason = 'Creative preflight failed: ' + ('; '.join(result['reasons']) or 'score below threshold')
            patch('render_jobs', job['id'], {'status': 'failed', 'error': reason, 'completed_at': 'now()', 'updated_at': 'now()'})
            patch('video_projects', project['id'], {'status': 'failed', 'output_url': None, 'failure_reason': reason, 'updated_at': 'now()'})


def download_output(obj, path):
    url = URL + '/storage/v1/object/video-outputs/' + urllib.parse.quote(obj, safe='/')
    request = urllib.request.Request(url, headers={'apikey': KEY, 'Authorization': f'Bearer {KEY}'})
    with urllib.request.urlopen(request, timeout=600) as response, open(path, 'wb') as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)


def upload(path, bucket, obj, mime):
    url = URL + f'/storage/v1/object/{bucket}/' + urllib.parse.quote(obj, safe='/')
    with open(path, 'rb') as handle:
        request = urllib.request.Request(url, data=handle.read(), headers={'apikey': KEY, 'Authorization': f'Bearer {KEY}', 'Content-Type': mime, 'x-upsert': 'true'}, method='POST')
        urllib.request.urlopen(request, timeout=600).read()


def media_duration(path):
    return float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', str(path)]).decode().strip())


def add_sound_design(src, dst, longform=False):
    dur = max(1.0, media_duration(src)); bed = .55 if longform else .75
    filt = f"[1:a]lowpass=f=420,highpass=f=45,volume=0.07,afade=t=in:st=0:d={bed},afade=t=out:st={max(0, dur-bed):.3f}:d={bed}[bed];[0:a][bed]amix=inputs=2:duration=first:weights='1 0.34',acompressor=threshold=-16dB:ratio=1.6:attack=8:release=180,loudnorm=I=-14:TP=-1:LRA=8[mix]"
    subprocess.run(['ffmpeg','-y','-i',str(src),'-f','lavfi','-i',f'anoisesrc=color=pink:amplitude=0.025:sample_rate=48000:d={dur:.3f}','-filter_complex',filt,'-map','0:v','-map','[mix]','-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart',str(dst)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


def make_thumbnail(video, title, path):
    dur = media_duration(video); timecode = max(1, min(dur*.28, dur-1)); text = path.with_suffix('.txt'); text.write_text(' '.join(str(title or 'Video').split()[:10]), encoding='utf-8'); font='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
    vf=f"scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,eq=contrast=1.08:saturation=1.12,drawbox=x=0:y=430:w=1280:h=290:color=black@0.48:t=fill,drawtext=fontfile={font}:textfile={text}:fontcolor=white:fontsize=58:line_spacing=10:x=70:y=470:box=0"
    subprocess.run(['ffmpeg','-y','-ss',f'{timecode:.2f}','-i',str(video),'-frames:v','1','-vf',vf,'-q:v','2',str(path)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


def fail_finished_qc(project, job, reason, result=None):
    if result is not None:
        report(project, job, 'final_video_qc', result)
    patch('video_projects', project['id'], {'status':'failed','output_url':None,'quality_score':(result or {}).get('score',0),'failure_reason':reason[:1000],'updated_at':'now()'})
    patch('render_jobs', job['id'], {'status':'failed','error':reason[:1000],'updated_at':'now()'})
    step(project, 'final_video_qc', 'failed', reason[:1000])


def post_render_qc(project_id, job_id, obj):
    project=(req('GET',f'/rest/v1/video_projects?id=eq.{project_id}&select=*') or [None])[0]; job=(req('GET',f'/rest/v1/render_jobs?id=eq.{job_id}&select=*') or [None])[0]
    if not project or not job:
        raise RuntimeError('Finished render record disappeared before final QC.')
    assets=req('GET',f'/rest/v1/visual_assets?render_job_id=eq.{job_id}&select=provider,media_type,relevance_score,scene_index') or []
    step(project,'final_video_qc','running','Inspecting the actual finished MP4 for semantic visual match, black frames, freezes, silence, duration and format.')
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            raw=Path(temp_dir)/'raw.mp4'; master=Path(temp_dir)/'master.mp4'; download_output(obj,raw)
            longform=int(project.get('target_duration_seconds') or 0)>120 or str(project.get('format') or '').lower() in ('long','longform','full','youtube','youtube video','full video','long form','long-form')
            add_sound_design(raw,master,longform); step(project,'sound_design','passed','Added a subtle locally generated ambience bed, narration-safe compression and final loudness mastering.')
            result=final_video_qc(master,project,assets); report(project,job,'final_video_qc',result)
            if not result['passed']:
                reason='Final video QC failed: '+'; '.join(result['reasons']); patch('video_projects',project['id'],{'quality_score':result['score'],'status':'failed','output_url':None,'failure_reason':reason,'updated_at':'now()'}); patch('render_jobs',job['id'],{'status':'failed','error':reason,'updated_at':'now()'}); step(project,'final_video_qc','failed',f"Finished-video score {result['score']}/100. "+'; '.join(result['reasons'])); raise RuntimeError(reason)
            upload(master,'video-outputs',obj,'video/mp4'); thumb_obj=None
            if longform:
                thumb=Path(temp_dir)/'thumbnail.jpg'; make_thumbnail(master,project.get('title'),thumb); thumb_obj=f"{project['user_id']}/{project['id']}/{job_id}.jpg"; upload(thumb,'video-thumbnails',thumb_obj,'image/jpeg'); step(project,'thumbnail','passed','Generated a custom 16:9 thumbnail from the finished video with concise title treatment.')
            creative=float(project.get('creative_score') or 0); priority=publication_priority(project,creative,result['score']); payload={'quality_score':result['score'],'publication_priority':priority,'status':'quality_check','failure_reason':None,'updated_at':'now()'}
            if thumb_obj: payload['thumbnail_url']=thumb_obj
            patch('video_projects',project['id'],payload); step(project,'final_video_qc','passed',f"Finished-video score {result['score']}/100. Actual MP4 passed semantic relevance, motion, freeze, black-frame, silence, duration, aspect-ratio and sound-master checks."); print(f'FINAL_QC_PASS project={project_id} score={result["score"]} priority={priority}')
    except Exception as exc:
        current=(req('GET',f'/rest/v1/video_projects?id=eq.{project_id}&select=status,failure_reason') or [{}])[0]
        if current.get('status')!='failed': fail_finished_qc(project,job,'Final video QC execution failed: '+str(exc))
        raise


preflight_queue()
render=subprocess.run(['python','scripts/render_video.py'],capture_output=True,text=True); text=(render.stdout or '')+(render.stderr or ''); print(text,end='')
if render.returncode: raise SystemExit(render.returncode)
matches=re.findall(r'Rendered\s+([^/\s]+/([^/\s]+)/([^/:\s]+)\.mp4):',text)
if not matches: raise SystemExit(0)
obj,project_id,job_id=matches[-1]; post_render_qc(project_id,job_id,obj)
