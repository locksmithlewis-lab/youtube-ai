"""Add a compact Like + Subscribe overlay to the final captioned render."""
import subprocess

_BASE_RUN = subprocess.run
_INSTALLED = False


def _duration(path):
    try:
        return float(subprocess.check_output([
            'ffprobe','-v','error','-show_entries','format=duration',
            '-of','default=nw=1:nk=1',str(path)
        ]).decode().strip())
    except Exception:
        return 0.0


def install():
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    def wrapped(cmd, *args, **kwargs):
        try:
            if not isinstance(cmd, (list, tuple)) or not cmd:
                return _BASE_RUN(cmd, *args, **kwargs)
            if not str(cmd[0]).endswith('ffmpeg') or '-vf' not in cmd or not str(cmd[-1]).endswith('output.mp4'):
                return _BASE_RUN(cmd, *args, **kwargs)

            command = list(cmd)
            vf_index = command.index('-vf') + 1
            vf = str(command[vf_index])
            if 'subtitles=' not in vf or 'LIKE + SUBSCRIBE' in vf:
                return _BASE_RUN(cmd, *args, **kwargs)

            is_short = 'MarginV=330' in vf
            inputs = [str(command[i + 1]) for i, token in enumerate(command[:-1]) if token == '-i']
            media_dur = _duration(inputs[-1]) if inputs else 0.0
            if media_dur > 0:
                start = max(6.0, media_dur - (4.2 if is_short else 5.2))
                end = max(start + 0.8, media_dur - 0.45)
            else:
                start, end = ((8.0, 11.5) if is_short else (25.0, 29.0))

            if is_short:
                vf = vf.replace('FontSize=27', 'FontSize=30').replace('Outline=3', 'Outline=4')
                x, y, box_w, box_h, font = '(w-760)/2', 150, 760, 112, 48
            else:
                vf = vf.replace('FontSize=22', 'FontSize=24').replace('Outline=2', 'Outline=3')
                x, y, box_w, box_h, font = 'w-660', 70, 620, 82, 34

            enable = f"between(t,{start:.2f},{end:.2f})"
            vf += (
                f",drawbox=x='{x}':y={y}:w={box_w}:h={box_h}:color=0xD71920@0.94:t=fill:enable='{enable}'"
                f",drawbox=x='{x}':y={y}:w={box_w}:h={box_h}:color=white@0.88:t=3:enable='{enable}'"
                f",drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
                f"text='LIKE + SUBSCRIBE':fontcolor=white:fontsize={font}:"
                f"x=({x})+({box_w}-text_w)/2:y={y + 18}:enable='{enable}'"
            )
            command[vf_index] = vf
            return _BASE_RUN(command, *args, **kwargs)
        except Exception as exc:
            print('Engagement CTA overlay unavailable:', str(exc)[:240])
            return _BASE_RUN(cmd, *args, **kwargs)

    subprocess.run = wrapped
