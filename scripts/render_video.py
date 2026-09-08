import json
import math
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from media_integrity import is_healthy
from visual_sources import plan_scene, choose, local_graphic_asset

SUPABASE_URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
ENGINE = 'motion-first-renderer-v13-scene-qc'
VOICE_MODEL = os.environ.get('PIPER_VOICE', 'en_US-lessac-medium')
VOICE_DIR = Path(os.environ.get('PIPER_VOICE_DIR', '.piper-voices'))
if not SUPABASE_URL or not SERVICE_KEY:
    raise SystemExit('Supabase secrets required.')
HEADERS = {
    'apikey': SERVICE_KEY,
    'Authorization': f'Bearer {SERVICE_KEY}',
    'Content-Type': 'application/json',
}
W, H = 1080, 1920


def request(method, path, data=None, extra=None):
    body = None if data is None else json.dumps(data).encode()
    headers = dict(HEADERS)
    headers.update(extra or {})
    req = urllib.request.Request(SUPABASE_URL + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=90) as response:
        raw = response.read()
        return json.loads(raw.decode()) if raw else None


def patch(table, item_id, payload):
    return request('PATCH', f'/rest/v1/{table}?id=eq.{item_id}', payload, {'Prefer': 'return=minimal'})


def set_step(project, step, status, detail):
    return request('POST', '/rest/v1/rpc/upsert_project_pipeline_step', {
        'p_user_id': project['user_id'],
        'p_project_id': project['id'],
        'p_step': step,
        'p_status': status,
        'p_detail': detail,
    })


def run(cmd, **kwargs):
    return subprocess.run(cmd, check=True, **kwargs)


def duration(path):
    return float(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=nw=1:nk=1', str(path),
    ]).decode().strip())


def ts(sec):
    ms = int(sec * 1000)
    return f'{ms // 3600000:02}:{(ms // 60000) % 60:02}:{(ms // 1000) % 60:02},{ms % 1000:03}'


def sentences(text):
    return [
        re.sub(r'\s+', ' ', part).strip()
        for part in re.split(r'(?<=[.!?])\s+|\n+', text)
        if len(part.strip().split()) > 2
    ]


def is_longform(project):
    return (
        str(project.get('format') or '').lower() in ('full video', 'long form', 'long-form', 'youtube video')
        or int(project.get('target_duration_seconds') or 0) >= 180
    )


def human_check(script, longform=False):
    wc = len(script.split())
    beats = len(sentences(script))
    if longform:
        if wc < 850:
            raise RuntimeError('Long-form script is too short; minimum publish-grade target is about 850 words.')
        if beats < 18:
            raise RuntimeError('Long-form script needs more narrative sections and pacing changes.')
    else:
        if wc < 55:
            raise RuntimeError('Script is too thin for a professional Short.')
        if beats < 5:
            raise RuntimeError('Short needs more narrative beats for comprehension.')


def claim():
    rows = request('POST', '/rest/v1/rpc/claim_next_render_job', {}) or []
    return rows[0] if rows else None


def download(url, path):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'MotionVisualRouter/4.0', 'Accept': '*/*'})
            with urllib.request.urlopen(req, timeout=120) as response, open(path, 'wb') as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
            return True
        except urllib.error.HTTPError as exc:
            if exc.code not in (403, 408, 429, 500, 502, 503, 504):
                return False
            time.sleep(1.1 * (attempt + 1))
        except Exception:
            time.sleep(.7 * (attempt + 1))
    return False


def video_filter(index=0):
    sw = int(W * 1.06) // 2 * 2
    sh = int(H * 1.06) // 2 * 2
    return (
        f"scale={sw}:{sh}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H}:x='(in_w-out_w)/2+((in_w-out_w)/2)*sin(t*0.92+{index})':"
        f"y='(in_h-out_h)/2+((in_h-out_h)/2)*cos(t*0.77+{index})',"
        "fps=30,setpts=N/(30*TB),eq=contrast=1.035:saturation=1.05,setsar=1"
    )


def image_motion_filter(index, frames):
    zoom = "min(zoom+0.00135,1.16)" if index % 2 == 0 else "if(lte(zoom,1.0),1.15,max(1.0,zoom-0.0011))"
    x = "iw/2-(iw/zoom/2)+30*sin(on/15)"
    y = "ih/2-(ih/zoom/2)+24*cos(on/18)"
    return (
        f"scale={int(W * 1.20)}:{int(H * 1.20)}:force_original_aspect_ratio=increase,"
        f"crop={int(W * 1.20)}:{int(H * 1.20)},"
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps=30,"
        "eq=contrast=1.04:saturation=1.06,setsar=1"
    )


def final_motion_filter():
    sw = int(W * 1.03) // 2 * 2
    sh = int(H * 1.03) // 2 * 2
    return (
        f"scale={sw}:{sh},crop={W}:{H}:"
        "x='(in_w-out_w)/2+((in_w-out_w)/2)*sin(t*0.81)':"
        "y='(in_h-out_h)/2+((in_h-out_h)/2)*cos(t*0.67)',"
        "fps=30,lutrgb=r='max(val,24)':g='max(val,24)':b='max(val,24)',setsar=1"
    )


def make_graphic(path, seconds, index, plan):
    keys = (plan.get('keywords') or [])[:3]
    character = plan.get('character') or {}
    label = (
        f"{character.get('name', '')}  {character.get('accessory', '')}"
        if character else '  •  '.join(keys)
    )[:80] or ' '
    text_path = path.with_suffix('.txt')
    text_path.write_text(label, encoding='utf-8')
    font = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
    font_size = 44 if H > W else 38
    vf = (
        "eq=brightness='0.006*sin(2*PI*t*1.1)':eval=frame,"
        "drawgrid=width=96:height=96:thickness=2:color=white@0.08,"
        f"drawbox=x='-420+mod(t*260+{index * 70},{W + 720})':y='{int(H * .16)}':"
        f"w=420:h='{int(H * .12)}':color=white@0.24:t=fill,"
        f"drawbox=x='{int(W * .03)}+{int(W * .30)}*sin(t*1.7)':"
        f"y='{int(H * .34)}+{int(H * .10)}*cos(t*1.1)':w='{int(W * .42)}':h='{int(H * .22)}':"
        "color=white@0.16:t=fill,"
        f"drawbox=x='{int(W * .48)}+{int(W * .24)}*cos(t*1.35)':"
        f"y='{int(H * .58)}+{int(H * .12)}*sin(t*.95)':w='{int(W * .44)}':h='{int(H * .18)}':"
        "color=white@0.14:t=fill,"
        f"drawtext=fontfile={font}:textfile={text_path}:fontcolor=white@0.94:fontsize={font_size}:"
        "x=(w-text_w)/2:y=h*0.72:box=1:boxcolor=black@0.24:boxborderw=18,vignette=PI/5"
    )
    run([
        'ffmpeg', '-y', '-f', 'lavfi', '-i', f'color=c=0x26384f:s={W}x{H}:r=30:d={seconds:.3f}',
        '-vf', vf, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '19', '-pix_fmt', 'yuv420p', str(path),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def record_asset(job, project, index, plan, asset):
    request('POST', '/rest/v1/visual_assets', {
        'user_id': project['user_id'],
        'project_id': project['id'],
        'render_job_id': job['id'],
        'scene_index': index,
        'provider': asset['provider'],
        'media_type': asset['media_type'],
        'source_url': asset.get('url'),
        'source_page': asset.get('page'),
        'credit': asset.get('credit'),
        'license': asset.get('license'),
        'query': plan.get('query'),
        'relevance_score': asset.get('relevance_score'),
    }, {'Prefer': 'return=minimal'})


def visual_qc(assets, total, longform=False):
    scores = [float(asset.get('relevance_score') or 0) for asset in assets]
    avg = sum(scores) / max(1, len(scores))
    ids = {asset.get('id') for asset in assets}
    providers = {asset.get('provider') for asset in assets}
    images = sum(asset.get('media_type') == 'image' for asset in assets)
    graphics = sum(asset.get('media_type') == 'graphic' for asset in assets)
    videos = sum(asset.get('media_type') == 'video' for asset in assets)
    moving = videos + graphics
    reasons, warnings = [], []
    if len(ids) / max(1, total) < .78:
        reasons.append('visual repetition is too high')
    if avg < .50:
        reasons.append(f'average visual relevance is only {avg:.2f}')
    if images > math.ceil(total * .20):
        reasons.append(f'too many still-image scenes ({images}/{total}); slideshow-style edits are blocked')
    if moving / max(1, total) < .80:
        reasons.append(f'only {moving}/{total} scenes contain true motion')
    if graphics > math.ceil(total * (.40 if longform else .35)):
        reasons.append('motion-graphic fallback dominates instead of real footage')
    if total >= 8 and len(providers) < 2:
        warnings.append('single source provider used; relevance and motion still passed')
    return reasons, warnings, avg, providers, images, videos, graphics


def render_asset(asset, plan, index, seg, frames, work):
    src = work / f'source-{index:03}.mp4'
    clip = work / f'clip-{index:03}.mp4'
    if asset['media_type'] == 'graphic':
        make_graphic(src, max(seg + .3, 3.0), index, plan)
        run([
            'ffmpeg', '-y', '-i', str(src), '-t', f'{seg:.3f}', '-vf', 'fps=30,setpts=N/(30*TB)',
            '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '19', '-pix_fmt', 'yuv420p', str(clip),
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return clip, asset
    if asset['media_type'] == 'image':
        image = work / f'image-{index:03}.img'
        if not download(asset['url'], image):
            return render_asset(local_graphic_asset(plan, index), plan, index, seg, frames, work)
        try:
            run([
                'ffmpeg', '-y', '-loop', '1', '-i', str(image), '-t', f'{seg:.3f}',
                '-vf', image_motion_filter(index, frames), '-an', '-c:v', 'libx264', '-preset', 'veryfast',
                '-crf', '19', '-pix_fmt', 'yuv420p', str(clip),
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return clip, asset
        except Exception:
            return render_asset(local_graphic_asset(plan, index), plan, index, seg, frames, work)
    if not download(asset['url'], src):
        return render_asset(local_graphic_asset(plan, index), plan, index, seg, frames, work)
    try:
        run([
            'ffmpeg', '-y', '-stream_loop', '-1', '-ss', '1.0', '-i', str(src), '-t', f'{seg:.3f}',
            '-an', '-vf', video_filter(index), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '19',
            '-pix_fmt', 'yuv420p', str(clip),
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return clip, asset
    except Exception:
        return render_asset(local_graphic_asset(plan, index), plan, index, seg, frames, work)


def render_verified_scene(plan, initial_asset, index, seg, frames, work, used, used_providers):
    attempted = set()
    candidates = [initial_asset]
    for _ in range(2):
        candidate = choose(plan, used | attempted, .50, used_providers)
        if candidate:
            candidates.append(candidate)
            attempted.add(candidate.get('id'))
    candidates.append(local_graphic_asset(plan, index))

    failures = []
    seen = set()
    for candidate in candidates:
        if not candidate:
            continue
        candidate_id = candidate.get('id')
        if candidate_id in seen:
            continue
        seen.add(candidate_id)
        clip, actual = render_asset(candidate, plan, index, seg, frames, work)
        healthy, integrity = is_healthy(clip, black_limit=.45, freeze_limit=1.20)
        if healthy:
            return clip, actual, failures
        failures.append({
            'provider': actual.get('provider'),
            'id': actual.get('id'),
            'black': integrity['max_black_seconds'],
            'freeze': integrity['max_freeze_seconds'],
        })
        attempted.add(actual.get('id'))
    raise RuntimeError(f'Scene {index + 1} could not meet motion-integrity headroom after source replacement: {failures}')


def voice_pace(sentence, index, longform=False):
    base = [.96, 1.02, .99, 1.05, .94, 1.00][index % 6]
    if sentence.endswith('!'):
        base -= .04
    elif sentence.endswith('?'):
        base -= .02
    if len(sentence.split()) > 24:
        base += .04
    return max(.88, min(1.10, base))


def voice_pause(sentence, index, longform=False):
    base = ([.08, .14, .06, .18, .10, .12] if not longform else [.14, .22, .10, .28, .16, .20])[index % 6]
    if sentence.endswith('?'):
        base += .06
    if sentence.endswith('!'):
        base += .03
    return base


def expressive_voice(script, work, model, longform=False):
    sentence_list = sentences(script)
    parts = []
    for index, sentence in enumerate(sentence_list):
        text = work / f'voice-{index:03}.txt'
        wav = work / f'voice-{index:03}.wav'
        text.write_text(sentence, encoding='utf-8')
        with text.open() as source:
            run([
                'piper', '--model', str(model), '--output_file', str(wav),
                '--length-scale', str(voice_pace(sentence, index, longform)),
            ], stdin=source, stdout=subprocess.DEVNULL)
        parts.append(wav)
        if index < len(sentence_list) - 1:
            gap = work / f'pause-{index:03}.wav'
            run([
                'ffmpeg', '-y', '-f', 'lavfi', '-i', 'anullsrc=r=22050:cl=mono',
                '-t', str(voice_pause(sentence, index, longform)), '-c:a', 'pcm_s16le', str(gap),
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            parts.append(gap)
    concat = work / 'voice-concat.txt'
    concat.write_text('\n'.join("file '" + str(part.resolve()).replace("'", "'\\''") + "'" for part in parts), encoding='utf-8')
    raw = work / 'raw.wav'
    run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(concat), '-c:a', 'pcm_s16le', str(raw)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    audio = work / 'voice.wav'
    run([
        'ffmpeg', '-y', '-i', str(raw), '-af',
        'highpass=f=70,lowpass=f=14000,acompressor=threshold=-18dB:ratio=2:attack=8:release=160,'
        'equalizer=f=3000:t=q:w=1:g=1,loudnorm=I=-14:TP=-1:LRA=8',
        '-ar', '48000', '-ac', '2', str(audio),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return audio


def scene_lengths(total, count, longform=False):
    weights = []
    for index in range(count):
        if longform:
            weight = 1.0 + (.10 if index % 5 == 0 else -.08 if index % 4 == 0 else 0)
        else:
            weight = .72 if index < 3 else (.86 if index % 5 == 0 else 1.05 if index % 4 == 0 else .98)
        weights.append(weight)
    scale = total / sum(weights)
    return [weight * scale for weight in weights]


job = claim()
if not job:
    print('No queued render jobs.')
    raise SystemExit(0)
started = time.monotonic()
patch('render_jobs', job['id'], {'engine': ENGINE, 'updated_at': 'now()'})

try:
    project = (request('GET', f"/rest/v1/video_projects?id=eq.{job['project_id']}&select=*") or [None])[0]
    if not project:
        raise RuntimeError('Project not found.')
    longform = is_longform(project)
    if longform:
        W, H = 1920, 1080
    script = (project.get('script') or '').strip()
    human_check(script, longform)
    set_step(project, 'voice', 'running', f"Generating paced {'long-form' if longform else 'Short'} narration.")
    set_step(project, 'visuals', 'running', 'Selecting and encoding narration-matched scenes; every encoded scene must pass black/freeze integrity before assembly.')
    set_step(project, 'edit', 'running', 'Building retention-weighted timing, captions and scene-validated motion edit.')

    work = Path('render-work') / job['id']
    work.mkdir(parents=True, exist_ok=True)
    VOICE_DIR.mkdir(exist_ok=True)
    model = VOICE_DIR / f'{VOICE_MODEL}.onnx'
    if not model.exists():
        run(['python', '-m', 'piper.download_voices', '--download-dir', str(VOICE_DIR), VOICE_MODEL])

    audio = expressive_voice(script, work, model, longform)
    dur = duration(audio)
    sentence_list = sentences(script)
    scene_count = max(28, min(180, math.ceil(dur / 5.0))) if longform else max(10, min(24, math.ceil(dur / 2.8)))
    segs = scene_lengths(dur, scene_count, longform)
    copies = [sentence_list[min(len(sentence_list) - 1, math.floor(i * len(sentence_list) / scene_count))] for i in range(scene_count)]
    used, used_providers, clips, assets = set(), set(), [], []
    replaced_scenes = 0

    for index, (line, seg) in enumerate(zip(copies, segs)):
        kinds = ['establishing wide', 'tracking action', 'human medium', 'detail close up', 'environment movement', 'human reaction', 'macro detail', 'aerial motion']
        plan = plan_scene(line, project, kinds[index % len(kinds)])
        initial = local_graphic_asset(plan, index) if plan.get('domain') == 'fiction' and index % 3 == 0 else choose(plan, used, .50, used_providers)
        if not initial:
            initial = local_graphic_asset(plan, index)
        clip, asset, rejected = render_verified_scene(plan, initial, index, seg, max(2, int(seg * 30) + 2), work, used, used_providers)
        if rejected:
            replaced_scenes += 1
        used.add(asset['id'])
        used_providers.add(asset['provider'])
        record_asset(job, project, index, plan, asset)
        assets.append(asset)
        clips.append(clip)

    reasons, warnings, avg, providers, images, videos, graphics = visual_qc(assets, scene_count, longform)
    if reasons:
        raise RuntimeError('Publish-grade visual QC failed: ' + '; '.join(reasons) + '. Re-render required; video will not publish.')

    words = script.split()
    chunk_size = 5 if longform else 3
    chunks = [' '.join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]
    weights = [max(1, len(re.sub(r'\W', '', chunk))) for chunk in chunks]
    total = sum(weights)
    cur = 0
    lines = []
    for index, (chunk, weight) in enumerate(zip(chunks, weights), 1):
        start = cur
        cur += dur * weight / total
        lines += [str(index), f'{ts(start)} --> {ts(dur if index == len(chunks) else cur)}', chunk, '']
    captions = work / 'captions.srt'
    captions.write_text('\n'.join(lines), encoding='utf-8')

    concat = work / 'concat.txt'
    concat.write_text('\n'.join("file '" + str(clip.resolve()).replace("'", "'\\''") + "'" for clip in clips), encoding='utf-8')
    visual = work / 'visual.mp4'
    run([
        'ffmpeg', '-y', '-fflags', '+genpts', '-f', 'concat', '-safe', '0', '-i', str(concat),
        '-vf', 'fps=30,setpts=N/(30*TB)', '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '19',
        '-pix_fmt', 'yuv420p', str(visual),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    healthy, integrity = is_healthy(visual, black_limit=.55, freeze_limit=1.35)
    if not healthy:
        raise RuntimeError(
            f'Assembled visual failed integrity headroom before captions: black={integrity["max_black_seconds"]:.2f}s, '
            f'freeze={integrity["max_freeze_seconds"]:.2f}s.'
        )

    out = work / 'output.mp4'
    style = (
        "FontName=DejaVu Sans,FontSize=22,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&HC0000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginL=190,MarginR=190,MarginV=80"
        if longform else
        "FontName=DejaVu Sans,FontSize=27,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&HC0000000,BorderStyle=1,Outline=3,Shadow=1,Alignment=2,MarginL=130,MarginR=130,MarginV=330"
    )
    vf = final_motion_filter() + f",subtitles={captions}:force_style='{style}'"
    run([
        'ffmpeg', '-y', '-i', str(visual), '-i', str(audio), '-vf', vf,
        '-map', '0:v', '-map', '1:a', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '19',
        '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', '-shortest', str(out),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    run(['ffmpeg', '-v', 'error', '-i', str(out), '-f', 'null', '-'], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    if out.stat().st_size < (3000000 if longform else 500000):
        raise RuntimeError('Output failed file-size validation.')
    final_dur = duration(out)
    if final_dur < dur * .94:
        raise RuntimeError('Output duration validation failed; edit appears truncated.')
    healthy, integrity = is_healthy(out, black_limit=.55, freeze_limit=1.35)
    if not healthy:
        raise RuntimeError(
            f'Finished render missed pre-QC integrity headroom: black={integrity["max_black_seconds"]:.2f}s, '
            f'freeze={integrity["max_freeze_seconds"]:.2f}s.'
        )

    obj = f"{job['user_id']}/{job['project_id']}/{job['id']}.mp4"
    url = SUPABASE_URL + '/storage/v1/object/video-outputs/' + urllib.parse.quote(obj, safe='/')
    with out.open('rb') as handle:
        upload_request = urllib.request.Request(
            url, data=handle.read(),
            headers={'apikey': SERVICE_KEY, 'Authorization': f'Bearer {SERVICE_KEY}', 'Content-Type': 'video/mp4', 'x-upsert': 'true'},
            method='POST',
        )
        urllib.request.urlopen(upload_request, timeout=600 if longform else 240).read()

    elapsed = max(.1, time.monotonic() - started)
    patch('render_jobs', job['id'], {
        'status': 'completed', 'engine': ENGINE, 'output_url': obj, 'error': None,
        'completed_at': 'now()', 'actual_render_seconds': elapsed,
        'media_duration_seconds': final_dur, 'updated_at': 'now()',
    })
    patch('video_projects', project['id'], {
        'output_url': obj, 'voice': VOICE_MODEL, 'status': 'generating',
        'failure_reason': None, 'updated_at': 'now()',
    })
    warning_text = (' ' + '; '.join(warnings)) if warnings else ''
    set_step(project, 'voice', 'passed', f'Narration render passed with {VOICE_MODEL}.')
    set_step(project, 'visuals', 'passed', (
        f"Scene-level QC passed: {scene_count} scenes, {videos} stock-video, {graphics} motion-graphic, "
        f"{images} animated-image, avg relevance {avg:.2f}, providers {', '.join(sorted(providers))}, "
        f"{replaced_scenes} unhealthy source scenes replaced before assembly.{warning_text}"
    ))
    set_step(project, 'edit', 'passed', (
        f"{'16:9 long-form' if longform else '9:16 Short'} edit passed decode, duration, captions and "
        'pre-QC black/freeze headroom; finished-MP4 critic is next.'
    ))
    print(
        f'Rendered {obj}: mode={"longform" if longform else "short"}, motion={videos + graphics}/{scene_count}, '
        f'relevance={avg:.2f}, providers={providers}, scene_replacements={replaced_scenes}, engine={ENGINE}'
    )
except Exception as exc:
    message = str(exc)[:1000]
    patch('render_jobs', job['id'], {
        'status': 'failed', 'engine': ENGINE, 'error': message, 'completed_at': 'now()',
        'actual_render_seconds': max(.1, time.monotonic() - started), 'updated_at': 'now()',
    })
    patch('video_projects', job['project_id'], {'status': 'failed', 'output_url': None, 'failure_reason': message, 'updated_at': 'now()'})
    try:
        current_project = locals().get('project')
        if current_project:
            for stage in ('voice', 'visuals', 'edit'):
                set_step(current_project, stage, 'failed', message)
    except Exception:
        pass
    raise
