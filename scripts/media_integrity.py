import re
import subprocess
from pathlib import Path


def media_duration(path):
    return float(subprocess.check_output([
        'ffprobe','-v','error','-show_entries','format=duration',
        '-of','default=nw=1:nk=1',str(path)
    ]).decode().strip())


def _ffmpeg_scan(path):
    proc = subprocess.run([
        'ffmpeg','-hide_banner','-nostats','-i',str(path),
        '-vf','blackdetect=d=0.25:pix_th=0.10,freezedetect=n=-45dB:d=0.75',
        '-an','-f','null','-'
    ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    return proc.stderr or ''


def detect_intervals(path, black_limit=0.70, freeze_limit=1.80):
    """Return black/freeze intervals, including freezes that run to EOF.

    The same detector is shared by scene validation and final QC so the renderer
    cannot call a clip healthy using a different definition from the publisher.
    """
    path = Path(path)
    text = _ffmpeg_scan(path)
    total = max(0.0, media_duration(path))

    black = []
    for m in re.finditer(
        r'black_start:([0-9.]+)\s+black_end:([0-9.]+)\s+black_duration:([0-9.]+)',
        text,
    ):
        start, end, length = map(float, m.groups())
        if length > black_limit:
            black.append((start, end, length))

    freezes = []
    open_start = None
    pending_duration = None
    for line in text.splitlines():
        start_match = re.search(r'freeze_start:\s*([0-9.]+)', line)
        if start_match:
            # A new start should not normally occur before an end, but if it
            # does, close the prior interval conservatively at the new start.
            new_start = float(start_match.group(1))
            if open_start is not None:
                length = max(0.0, new_start - open_start)
                if length > freeze_limit:
                    freezes.append((open_start, new_start, length))
            open_start = new_start
            pending_duration = None
            continue

        duration_match = re.search(r'freeze_duration:\s*([0-9.]+)', line)
        if duration_match and open_start is not None:
            pending_duration = float(duration_match.group(1))
            continue

        end_match = re.search(r'freeze_end:\s*([0-9.]+)', line)
        if end_match and open_start is not None:
            end = float(end_match.group(1))
            length = pending_duration if pending_duration is not None else max(0.0, end - open_start)
            if length > freeze_limit:
                freezes.append((open_start, end, length))
            open_start = None
            pending_duration = None

    # FFmpeg emits freeze_start but no freeze_end/freeze_duration when a freeze
    # continues through the final frame. Older QC silently missed this case.
    if open_start is not None:
        end = total
        length = max(0.0, end - open_start)
        if length > freeze_limit:
            freezes.append((open_start, end, length))

    return {
        'black_intervals': black,
        'freeze_intervals': freezes,
        'max_black_seconds': max([x[2] for x in black] or [0.0]),
        'max_freeze_seconds': max([x[2] for x in freezes] or [0.0]),
        'duration_seconds': total,
    }


def is_healthy(path, black_limit=0.45, freeze_limit=1.20):
    result = detect_intervals(path, black_limit=black_limit, freeze_limit=freeze_limit)
    return not result['black_intervals'] and not result['freeze_intervals'], result
