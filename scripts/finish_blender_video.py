#!/usr/bin/env python3
"""Finish Blender batch videos with subtle animated topic hashtags and a short CTA end card."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

def main():
    if len(sys.argv) != 5:
        raise SystemExit("Usage: finish_blender_video.py input.mp4 title hashtags_json topic")
    src = Path(sys.argv[1]).resolve()
    title = sys.argv[2].strip()[:100] or "Rolixa"
    tags = json.loads(sys.argv[3])
    topic = sys.argv[4].strip()[:180]
    if not src.is_file() or src.stat().st_size < 100_000:
        raise SystemExit("Blender output is missing or too small to finish safely.")
    tags = [str(t) for t in tags if str(t).startswith("#")][:10]
    if not tags:
        tags = ["#AI", "#Technology", "#Gaming", "#Science", "#Rolixa"]
    with tempfile.TemporaryDirectory(prefix="rolixa-finish-") as td:
        root = Path(td)
        tag_file = root / "hashtags.txt"
        tag_text = "   ".join(tags[:8])
        tag_file.write_text(tag_text, encoding="utf-8")
        overlay = root / "overlay.mp4"
        outro = root / "outro.mp4"
        concat = root / "concat.txt"
        final = root / "final.mp4"
        vf = (
            f"drawtext=fontfile={FONT}:textfile={tag_file}:reload=0:"
            "fontcolor=white@0.30:fontsize=34:borderw=1:bordercolor=black@0.15:"
            "x=(w-text_w)/2+sin(t*0.55)*w*0.24:y=92+sin(t*0.7)*18,"
            f"drawtext=fontfile={FONT}:textfile={tag_file}:reload=0:"
            "fontcolor=white@0.20:fontsize=30:borderw=1:bordercolor=black@0.12:"
            "x=(w-text_w)/2-sin(t*0.43)*w*0.20:y=h-120+cos(t*0.6)*14"
        )
        run(["ffmpeg","-y","-i",str(src),"-vf",vf,"-c:v","libx264","-preset","veryfast","-crf","21",
             "-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-ar","48000","-ac","2","-movflags","+faststart",str(overlay)])
        outro_vf = (
            "drawbox=x=120:y=310:w=1680:h=460:color=0x10233D@0.96:t=fill,"
            "drawbox=x=120:y=310:w=1680:h=460:color=0x27C8F5@0.95:t=5,"
            f"drawtext=fontfile={FONT}:text='IF YOU ENJOYED THIS':fontcolor=white:"
            "fontsize=44:x=(w-text_w)/2:y=365,"
            f"drawtext=fontfile={FONT}:text='LIKE  +  SUBSCRIBE':fontcolor=white:"
            "fontsize=78+7*sin(t*4):x=(w-text_w)/2:y=465,"
            f"drawtext=fontfile={FONT}:text='MORE TECH, AI AND GAMING':fontcolor=0x7DE3FF:"
            "fontsize=32:x=(w-text_w)/2:y=590,"
            "fade=t=in:st=0:d=0.35,fade=t=out:st=3.65:d=0.35"
        )
        run(["ffmpeg","-y","-f","lavfi","-i","color=c=0x07111F:s=1920x1080:r=24:d=4",
             "-f","lavfi","-i","anullsrc=r=48000:cl=stereo","-t","4","-vf",outro_vf,
             "-c:v","libx264","-preset","veryfast","-crf","21","-pix_fmt","yuv420p",
             "-c:a","aac","-b:a","192k","-ar","48000","-ac","2","-shortest",str(outro)])
        concat.write_text("file '"+str(overlay).replace("'","'\\''")+" '\nfile '"+str(outro).replace("'","'\\''")+" '\n",encoding="utf-8")
        run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(concat),"-c","copy","-movflags","+faststart",str(final)])
        final.replace(src)
    print("BLENDER_FINISH_PASS: animated background hashtags and 4-second Like + Subscribe outro added.")

if __name__ == "__main__":
    main()
