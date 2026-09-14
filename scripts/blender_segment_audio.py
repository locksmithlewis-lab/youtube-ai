"""Create dialogue, ambience and fictional cinematic SFX for one Blender segment.

Uses local Piper TTS voices and FFmpeg only. This intentionally creates fictional
cinematic sound design, not recordings or instructions for real weapons.
"""
import json
import os
import re
import subprocess
import tempfile
import wave
from pathlib import Path

ROOT = Path(os.environ.get('ROLIXA_EPISODE_DIR', '.rolixa-episode'))
WORKER = int(os.environ.get('ROLIXA_WORKER', '1'))
VOICE_DIR = Path(os.environ.get('PIPER_VOICE_DIR', '.piper-voices'))
MANIFEST = ROOT / 'episode.json'
VIDEO = ROOT / f'segment-{WORKER:02}.mp4'

VOICE_MAP = {
    'VOSS': 'en_US-amy-medium',
    'JAX': 'en_US-lessac-medium',
    'VALE': 'en_GB-alba-medium',
    'ROOK': 'en_US-lessac-medium',
    'KESTREL': 'en_GB-alba-medium',
    'VEYR COMMANDER': 'en_US-lessac-medium',
    'UNKNOWN RED VECTOR VOICE': 'en_US-amy-medium',
}


def run(cmd):
    subprocess.run(cmd, check=True)


def parse_dialogue(text):
    # Multi-word labels are required for VEYR COMMANDER and RED VECTOR's final sting.
    matches = list(re.finditer(r'(?:(?<=^)|(?<=\s))([A-Z][A-Z0-9_ ]{0,40}?):\s*', text or ''))
    out = []
    for i, match in enumerate(matches):
        speaker = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        line = re.sub(r'\s+', ' ', text[start:end]).strip(' .')
        if line:
            out.append((speaker, line + '.'))
    return out


def wav_seconds(path):
    with wave.open(str(path), 'rb') as w:
        return w.getnframes() / max(1, w.getframerate())


def synth_line(speaker, text, dst):
    model = VOICE_MAP.get(speaker, 'en_US-lessac-medium')
    raw = dst.with_suffix('.raw.wav')
    cmd = [
        'python', '-m', 'piper', '-m', model, '--data-dir', str(VOICE_DIR),
        '-f', str(raw), '--', text,
    ]
    run(cmd)
    run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(raw), '-ar', '48000', '-ac', '1', '-c:a', 'pcm_s16le', str(dst)])


def main():
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    seg = manifest['segments'][WORKER - 1]
    duration = float(seg['duration'])
    lines = parse_dialogue(seg.get('dialogue', ''))
    if not VIDEO.exists():
        raise SystemExit(f'missing visual segment {VIDEO}')
    if not lines:
        raise SystemExit(f'no parseable dialogue found for segment {WORKER}')

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        inputs = []
        delays = []
        cursor = 1.2
        for idx, (speaker, text) in enumerate(lines):
            wav = td / f'line-{idx:02}.wav'
            synth_line(speaker, text, wav)
            d = wav_seconds(wav)
            if cursor + d > duration - 2:
                break
            inputs.append(wav)
            delays.append(int(cursor * 1000))
            cursor += d + 0.55

        if not inputs:
            raise SystemExit(f'dialogue did not fit segment {WORKER}')

        filters = []
        maps = []
        ff = ['ffmpeg', '-y', '-loglevel', 'error', '-i', str(VIDEO)]
        for wav in inputs:
            ff += ['-i', str(wav)]
        ff += ['-f', 'lavfi', '-i', f'anoisesrc=color=pink:amplitude=0.012:sample_rate=48000:d={duration}']
        noise_idx = 1 + len(inputs)
        ff += ['-f', 'lavfi', '-i', f'sine=frequency=52:sample_rate=48000:duration={duration}']
        hum_idx = noise_idx + 1
        filters.append(f'[{noise_idx}:a]lowpass=f=650,highpass=f=35,volume=0.34[amb]')
        filters.append(f'[{hum_idx}:a]lowpass=f=120,volume=0.045[hum]')
        maps += ['[amb]', '[hum]']
        for i, delay in enumerate(delays, start=1):
            label = f'v{i}'
            filters.append(f'[{i}:a]adelay={delay}|{delay},volume=1.25[{label}]')
            maps.append(f'[{label}]')

        action = WORKER in {8, 10, 11, 12, 13, 16, 17, 18, 19}
        if action:
            ff += ['-f', 'lavfi', '-i', f'sine=frequency=82:sample_rate=48000:duration={duration}']
            fx_idx = hum_idx + 1
            filters.append(f'[{fx_idx}:a]tremolo=f=1.8:d=0.82,lowpass=f=180,volume=0.08[fx]')
            maps.append('[fx]')

        filters.append(
            f"{''.join(maps)}amix=inputs={len(maps)}:duration=longest:normalize=0,"
            'acompressor=threshold=-18dB:ratio=2.2:attack=8:release=180,'
            'loudnorm=I=-14:TP=-1.5:LRA=9[aout]'
        )
        mastered = td / 'mastered.mp4'
        ff += [
            '-filter_complex', ';'.join(filters), '-map', '0:v:0', '-map', '[aout]',
            '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-t', f'{duration:.3f}',
            '-movflags', '+faststart', str(mastered),
        ]
        run(ff)
        mastered.replace(VIDEO)
        print(f'AUDIO_MASTERED {VIDEO} voices={len(inputs)} speakers={[s for s,_ in lines]} action_fx={action}')


if __name__ == '__main__':
    main()
