import json
import math
import re
import subprocess
from pathlib import Path

from media_integrity import detect_intervals

OUTLINE_MARKERS = [
    r'(?im)^\s*(?:OPENING|ENDING|SCENE\s+\d+|CONTINUITY RULE)\s*[—:-]',
    r'(?i)queued for ', r'(?i)visual planner', r'(?i)production note'
]
INSTRUCTION_PATTERNS = [
    r'(?i)\bstart with\b', r'(?i)\bbuild (?:the )?(?:story|video|short|scene)\b', r'(?i)\bmove from the\b',
    r'(?i)\bhalfway through[, ]+introduce\b', r'(?i)\bkeep claims factual\b', r'(?i)\bavoid invented certainty\b',
    r'(?i)\bin the final (?:ten|\d+) seconds\b', r'(?i)\bpay off the opening\b', r'(?i)\bno filler\b',
    r'(?i)\bno generic motivational lines\b', r'(?i)\bno repeated scene\b', r'(?i)\bcreative treatment number\b',
    r'(?i)\bevery sentence must\b', r'(?i)\bthe viewer is seeing\b', r'(?i)\bshot rhythm\b', r'(?i)\bvisual identity\b',
    r'(?i)\btopic\s*:', r'(?i)\bscript instruction', r'(?i)\bnarration instruction', r'(?i)\bvisual instruction'
]
WEAK_PHRASES = [
    'looks ordinary until one detail changes the whole story',
    'catch the wave before it moves on',
    'this is the moment where a normal upload turns into',
    'nobody knows what happens next',
]


def sentences(text):
    return [
        re.sub(r'\s+', ' ', sentence).strip()
        for sentence in re.split(r'(?<=[.!?])\s+|\n+', str(text or ''))
        if len(sentence.strip().split()) > 2
    ]


def words(text):
    return re.findall(r"[A-Za-z0-9']+", str(text or '').lower())


def _target_words(project):
    target = max(1, int(project.get('target_duration_seconds') or 60))
    fmt = str(project.get('format') or '').lower()
    if fmt in ('short', 'shorts', 'story') and target <= 120:
        return max(55, int(target * 1.7)), max(95, int(target * 2.8))
    return max(500, int(target * 1.55)), max(850, int(target * 2.45))


def instruction_leaks(script):
    found = []
    for pattern in INSTRUCTION_PATTERNS:
        match = re.search(pattern, script or '')
        if match:
            found.append(match.group(0))
    return found


def creative_preflight(project):
    script = str(project.get('script') or '').strip()
    hook = str(project.get('hook') or '').strip()
    title = str(project.get('title') or '').strip()
    sentence_list = sentences(script)
    word_list = words(script)
    reasons = []
    score = 100.0
    low, high = _target_words(project)

    too_short = len(word_list) < low
    too_dense = len(word_list) > high
    if too_short:
        reasons.append(f'script too short ({len(word_list)} words; target at least {low})')
        score -= 30
    if too_dense:
        reasons.append(f'script too dense ({len(word_list)} words; target at most {high})')
        score -= 18
    if len(sentence_list) < 6:
        reasons.append('not enough narrative beats')
        score -= 20
    if not hook or len(words(hook)) < 5:
        reasons.append('opening hook is weak or missing')
        score -= 18
    if len(words(hook)) > 24:
        reasons.append('opening hook is too long')
        score -= 8
    if hook and hook[-1:] not in '.?!':
        score -= 3
    if len(words(title)) < 3:
        reasons.append('title is too vague')
        score -= 10
    if len(title) > 100:
        reasons.append('title is too long for YouTube packaging')
        score -= 7
    if re.search(r'(?i)^(?:showcase|signature)\s*\d+', title):
        reasons.append('generic batch title detected')
        score -= 22
    if re.search(r'(?i)\b(?:viral|must watch|you won.t believe|crazy)\b', title):
        score -= 4

    leaked = any(re.search(pattern, script) for pattern in OUTLINE_MARKERS)
    leaks = instruction_leaks(script)
    if leaked or leaks:
        sample = ', '.join(leaks[:3]) if leaks else 'outline/production marker'
        reasons.append(f'production directions leaked into spoken script ({sample})')
        score -= 60

    low_script = script.lower()
    if any(phrase in low_script for phrase in WEAK_PHRASES):
        reasons.append('known generic/template phrasing detected')
        score -= 18

    normalized = [re.sub(r'\W+', ' ', sentence.lower()).strip() for sentence in sentence_list]
    duplicate_ratio = 1 - (len(set(normalized)) / max(1, len(normalized)))
    if duplicate_ratio > .08:
        reasons.append(f'repeated sentence structure is too high ({duplicate_ratio:.0%})')
        score -= min(25, duplicate_ratio * 80)

    starts = [sentence.split()[0].lower() for sentence in sentence_list if sentence.split()]
    same_start = bool(starts) and max(starts.count(item) for item in set(starts)) / len(starts) > .35
    if same_start:
        reasons.append('too many sentences start the same way')
        score -= 10

    lengths = [len(words(sentence)) for sentence in sentence_list]
    if lengths and max(lengths) - min(lengths) < 5:
        reasons.append('sentence rhythm is too uniform')
        score -= 7
    if len(set(words(script))) < min(70, max(30, len(word_list) // 4)):
        reasons.append('vocabulary is too repetitive')
        score -= 8

    score = max(0, round(score, 1))
    hard_block = leaked or bool(leaks) or too_short or too_dense
    return {
        'passed': score >= 78 and not hard_block,
        'score': score,
        'reasons': reasons,
        'metrics': {
            'words': len(word_list), 'sentences': len(sentence_list),
            'title_words': len(words(title)), 'duplicate_sentence_ratio': round(duplicate_ratio, 3),
            'target_word_range': [low, high], 'instruction_leak_count': len(leaks),
            'hard_blocked_for_density': too_dense, 'hard_blocked_for_length': too_short,
        },
    }


def _ffprobe(path):
    raw = subprocess.check_output([
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,r_frame_rate:format=duration,size',
        '-of', 'json', str(path),
    ]).decode()
    return json.loads(raw)


def _detect(path):
    integrity = detect_intervals(path, black_limit=0.0, freeze_limit=0.0)
    proc = subprocess.run([
        'ffmpeg', '-hide_banner', '-nostats', '-i', str(path),
        '-af', 'silencedetect=n=-48dB:d=2.5', '-vn', '-f', 'null', '-'
    ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    text = proc.stderr or ''
    silence = []
    starts = [float(value) for value in re.findall(r'silence_start: ([0-9.]+)', text)]
    ends = [float(value) for value in re.findall(r'silence_end: ([0-9.]+)', text)]
    for start, end in zip(starts, ends):
        silence.append(max(0, end - start))
    return {
        'max_black_seconds': integrity['max_black_seconds'],
        'max_freeze_seconds': integrity['max_freeze_seconds'],
        'max_silence_seconds': max(silence or [0]),
    }


def final_video_qc(path, project, assets):
    path = Path(path)
    reasons = []
    score = 100.0
    meta = _ffprobe(path)
    fmt = meta.get('format') or {}
    stream = (meta.get('streams') or [{}])[0]
    dur = float(fmt.get('duration') or 0)
    size = int(fmt.get('size') or 0)
    width = int(stream.get('width') or 0)
    height = int(stream.get('height') or 0)
    target = float(project.get('target_duration_seconds') or dur or 1)
    kind = str(project.get('format') or '').lower()
    longform = target > 120 or kind in ('long', 'longform', 'full', 'youtube', 'youtube video', 'full video', 'long form', 'long-form')
    motion = sum(1 for asset in assets if asset.get('media_type') in ('video', 'graphic'))
    images = sum(1 for asset in assets if asset.get('media_type') == 'image')
    motion_ratio = motion / max(1, len(assets))
    image_ratio = images / max(1, len(assets))
    providers = len({asset.get('provider') for asset in assets if asset.get('provider')})
    detect = _detect(path)
    relevance = [float(asset.get('relevance_score') or 0) for asset in assets]
    avg_rel = sum(relevance) / max(1, len(relevance))
    low_rel = sum(1 for value in relevance if value < .46)
    low_rel_ratio = low_rel / max(1, len(relevance))

    if size < 750000:
        reasons.append('file is too small to be a trustworthy final render')
        score -= 35
    expected = 16 / 9 if longform else 9 / 16
    ratio = width / max(1, height)
    if abs(ratio - expected) > .08:
        reasons.append(f'wrong aspect ratio {width}x{height}')
        score -= 25
    min_motion = .70 if longform else .80
    if motion_ratio < min_motion:
        reasons.append(f'motion coverage only {motion_ratio:.0%}; need at least {min_motion:.0%}')
        score -= 35
    if not longform and image_ratio > .20:
        reasons.append(f'still-image coverage {image_ratio:.0%} exceeds 20%')
        score -= 25
    if avg_rel < .50:
        reasons.append(f'average semantic visual relevance only {avg_rel:.2f}; narration and visuals do not align closely enough')
        score -= 30
    if len(assets) >= 8 and low_rel_ratio > .25:
        reasons.append(f'{low_rel_ratio:.0%} of scenes are weak semantic matches')
        score -= 25
    if len(assets) >= 8 and providers < 2:
        score -= 5
    if dur < target * .65 or dur > target * 1.45:
        reasons.append(f'finished duration {dur:.1f}s misses target {target:.0f}s')
        score -= 18
    if detect['max_black_seconds'] > .7:
        reasons.append(f'black frame run {detect["max_black_seconds"]:.1f}s')
        score -= 20
    if detect['max_freeze_seconds'] > 1.8:
        reasons.append(f'frozen visual run {detect["max_freeze_seconds"]:.1f}s')
        score -= 25
    if detect['max_silence_seconds'] > 4.0:
        reasons.append(f'unplanned silence {detect["max_silence_seconds"]:.1f}s')
        score -= 15

    score = max(0, round(score, 1))
    metrics = {
        'duration_seconds': round(dur, 2), 'size_bytes': size,
        'width': width, 'height': height, 'motion_ratio': round(motion_ratio, 3),
        'image_ratio': round(image_ratio, 3), 'provider_count': providers,
        'average_semantic_relevance': round(avg_rel, 3),
        'weak_semantic_scene_ratio': round(low_rel_ratio, 3), **detect,
    }
    return {'passed': score >= 82 and not reasons, 'score': score, 'reasons': reasons, 'metrics': metrics}


def publication_priority(project, creative_score, quality_score, analytics=None):
    analytics = analytics or {}
    retention = float(analytics.get('average_view_duration_seconds') or 0) / max(1, float(project.get('target_duration_seconds') or 60))
    engagement = (
        float(analytics.get('likes') or 0) + 2 * float(analytics.get('comments') or 0) + 3 * float(analytics.get('shares') or 0)
    ) / max(1, float(analytics.get('views') or 0))
    return round(float(creative_score) * .35 + float(quality_score) * .50 + min(15, retention * 10 + engagement * 100), 2)
