"""Assemble 20 Blender segments into one mastered long-form BLACKSTAR episode."""
import os
import subprocess
from pathlib import Path

ROOT = Path(os.environ.get('ROLIXA_EPISODE_DIR', '.rolixa-episode'))
N = int(os.environ.get('ROLIXA_LONGFORM_SEGMENTS', '20'))
parts = [ROOT / f'segment-{i:02}.mp4' for i in range(1, N + 1)]
missing = [str(p) for p in parts if not p.exists()]
if missing:
    raise SystemExit('Missing Blender segments: ' + ', '.join(missing))

norm = []
for i, p in enumerate(parts, 1):
    q = ROOT / f'norm-{i:02}.mp4'
    norm.append(q)
    subprocess.run([
        'ffmpeg', '-y', '-loglevel', 'error', '-i', str(p),
        '-vf', 'fps=24,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2',
        '-movflags', '+faststart', str(q),
    ], check=True)

lst = ROOT / 'concat.txt'
lst.write_text('\n'.join("file '" + p.resolve().as_posix().replace("'", "'\\''") + "'" for p in norm), encoding='utf-8')
joined = ROOT / 'episode-joined.mp4'
subprocess.run([
    'ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', str(lst),
    '-c', 'copy', '-movflags', '+faststart', str(joined),
], check=True)

dur = float(subprocess.check_output([
    'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
    '-of', 'default=nw=1:nk=1', str(joined),
]).decode().strip())
if dur < 1000 or dur > 1400:
    raise SystemExit(f'Unexpected joined duration {dur:.1f}s')

# BLACKSTAR long-form CTA: one clean end-card overlay in the final six seconds.
# This dedicated pipeline did not previously inherit the normal short-form CTA hook.
out = ROOT / 'episode-master.mp4'
start = max(0.0, dur - 6.0)
font = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
text = 'LIKE + SUBSCRIBE  •  BLACKSTAR WILL RETURN'
filter_expr = (
    f"drawbox=x=0:y=ih-190:w=iw:h=190:color=black@0.58:t=fill:enable='gte(t,{start:.3f})',"
    f"drawtext=fontfile={font}:text='{text}':fontcolor=white:fontsize=48:"
    f"x=(iw-text_w)/2:y=ih-118:enable='gte(t,{start:.3f})'"
)
subprocess.run([
    'ffmpeg', '-y', '-loglevel', 'error', '-i', str(joined),
    '-vf', filter_expr,
    '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p',
    '-c:a', 'copy', '-movflags', '+faststart', str(out),
], check=True)

final_dur = float(subprocess.check_output([
    'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
    '-of', 'default=nw=1:nk=1', str(out),
]).decode().strip())
if abs(final_dur - dur) > 0.25:
    raise SystemExit(f'CTA pass changed duration unexpectedly: {dur:.2f}s -> {final_dur:.2f}s')
streams = subprocess.check_output([
    'ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', str(out)
]).decode().splitlines()
if 'video' not in streams or 'audio' not in streams:
    raise SystemExit('Master must contain both video and audio streams')
resolution = subprocess.check_output([
    'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height',
    '-of', 'csv=p=0:s=x', str(out)
]).decode().strip()
if resolution != '1920x1080':
    raise SystemExit(f'Unexpected master resolution {resolution}')
print(f'{out} duration={final_dur:.2f}s resolution={resolution} cta_start={start:.2f}s')
