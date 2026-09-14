"""Assemble 20 Blender segments into one mastered long-form episode."""
import os, subprocess
from pathlib import Path

ROOT = Path(os.environ.get('ROLIXA_EPISODE_DIR', '.rolixa-episode'))
N = int(os.environ.get('ROLIXA_LONGFORM_SEGMENTS', '20'))
parts = [ROOT / f'segment-{i:02}.mp4' for i in range(1, N + 1)]
missing = [str(p) for p in parts if not p.exists()]
if missing:
    raise SystemExit('Missing Blender segments: ' + ', '.join(missing))

# Normalize every segment to identical A/V parameters so concatenation is safe.
norm = []
for i, p in enumerate(parts, 1):
    q = ROOT / f'norm-{i:02}.mp4'
    norm.append(q)
    subprocess.run([
        'ffmpeg', '-y', '-i', str(p),
        '-vf', 'fps=24,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2',
        '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2',
        '-movflags', '+faststart', str(q),
    ], check=True)

lst = ROOT / 'concat.txt'
lst.write_text('\n'.join("file '" + p.resolve().as_posix().replace("'", "'\\''") + "'" for p in norm), encoding='utf-8')
out = ROOT / 'episode-master.mp4'
subprocess.run([
    'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(lst),
    '-c', 'copy', '-movflags', '+faststart', str(out),
], check=True)

# Reject incomplete, silent, or malformed masters rather than publishing them.
dur = float(subprocess.check_output([
    'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
    '-of', 'default=nw=1:nk=1', str(out),
]).decode().strip())
if dur < 1000 or dur > 1400:
    raise SystemExit(f'Unexpected master duration {dur:.1f}s')
streams = subprocess.check_output([
    'ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', str(out)
]).decode().splitlines()
if 'video' not in streams or 'audio' not in streams:
    raise SystemExit('Master must contain both video and audio streams')
print(out)
