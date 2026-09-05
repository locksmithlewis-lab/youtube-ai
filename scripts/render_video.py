import json, math, os, re, subprocess, textwrap, urllib.parse, urllib.request
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
ENGINE = "github-actions-ffmpeg-piper-v1"
VOICE_MODEL = os.environ.get("PIPER_VOICE", "en_US-lessac-medium")
VOICE_DIR = Path(os.environ.get("PIPER_VOICE_DIR", ".piper-voices"))

if not SUPABASE_URL or not SERVICE_KEY:
    raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY repository secrets are required.")

HEADERS = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
}

def request(method, path, data=None, extra_headers=None):
    body = None if data is None else json.dumps(data).encode()
    headers = dict(HEADERS)
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(SUPABASE_URL + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as response:
        raw = response.read()
        return json.loads(raw.decode()) if raw else None

def patch(table, row_id, payload):
    return request("PATCH", f"/rest/v1/{table}?id=eq.{row_id}", payload, {"Prefer": "return=minimal"})

def patch_pipeline(project_id, step, status, detail=None):
    payload = {"status": status, "updated_at": "now()"}
    if detail is not None:
        payload["detail"] = detail
    path = (
        f"/rest/v1/project_pipeline_steps?project_id=eq.{project_id}"
        f"&step=eq.{urllib.parse.quote(step)}"
    )
    return request("PATCH", path, payload, {"Prefer": "return=minimal"})

def run(cmd, **kwargs):
    return subprocess.run(cmd, check=True, **kwargs)

def probe_duration(path):
    return float(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ]
        )
        .decode()
        .strip()
    )

def timestamp(sec):
    ms = int(round(sec * 1000))
    hours = ms // 3600000
    ms %= 3600000
    minutes = ms // 60000
    ms %= 60000
    seconds = ms // 1000
    ms %= 1000
    return f"{hours:02}:{minutes:02}:{seconds:02},{ms:03}"

def fit_lines(draw, text, font, max_width, max_lines=5):
    words = text.split()
    lines = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        box = draw.textbbox((0, 0), trial, font=font)
        if box[2] - box[0] <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
            if len(lines) >= max_lines - 1:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    consumed = " ".join(lines)
    if len(consumed) < len(text.strip()) and lines:
        lines[-1] = lines[-1].rstrip(" .") + "…"
    return lines

def scene_texts(title, script, count=6):
    clean_sentences = [
        re.sub(r"\s+", " ", s).strip(" \n\t")
        for s in re.split(r"(?<=[.!?])\s+", script)
        if s.strip()
    ]
    picks = [title]
    if clean_sentences:
        step = max(1, math.ceil(len(clean_sentences) / max(1, count - 1)))
        for i in range(0, len(clean_sentences), step):
            picks.append(clean_sentences[i])
            if len(picks) >= count:
                break
    while len(picks) < count:
        picks.append(title)
    return picks[:count]

def make_scene(path, headline, index, total):
    width, height = 1080, 1920
    image = Image.new("RGB", (width, height), (8, 10, 20))
    draw = ImageDraw.Draw(image)

    accents = [
        (88, 74, 180),
        (46, 115, 173),
        (128, 70, 150),
        (32, 132, 132),
        (155, 88, 74),
        (75, 105, 185),
    ]
    accent = accents[index % len(accents)]

    for y in range(height):
        t = y / height
        base = int(12 + 18 * t)
        draw.line(
            [(0, y), (width, y)],
            fill=(base + accent[0] // 10, base + accent[1] // 12, base + accent[2] // 9),
        )

    draw.ellipse((-240, 180, 620, 1040), fill=tuple(min(255, c + 24) for c in accent))
    draw.ellipse((650, 900, 1370, 1620), fill=accent)
    draw.rectangle((0, 0, width, height), outline=(22, 25, 40), width=14)

    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    regular_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    brand_font = ImageFont.truetype(font_path, 36)
    headline_font = ImageFont.truetype(font_path, 62)
    small_font = ImageFont.truetype(regular_path, 30)

    draw.rounded_rectangle((70, 120, 320, 190), radius=30, fill=(8, 10, 20))
    draw.text((100, 137), "ROLIXA", font=brand_font, fill=(245, 245, 250))

    lines = fit_lines(draw, headline, headline_font, 900, max_lines=6)
    line_height = 80
    block_height = max(line_height, len(lines) * line_height)
    y = 700 - block_height // 2
    for line in lines:
        box = draw.textbbox((0, 0), line, font=headline_font)
        x = (width - (box[2] - box[0])) / 2
        draw.rounded_rectangle(
            (x - 24, y - 8, x + (box[2] - box[0]) + 24, y + 68),
            radius=18,
            fill=(8, 10, 20),
        )
        draw.text((x, y), line, font=headline_font, fill=(250, 250, 252))
        y += line_height

    progress_y = 1540
    draw.rounded_rectangle((90, progress_y, 990, progress_y + 12), radius=6, fill=(52, 56, 72))
    fill_width = int(900 * (index + 1) / total)
    draw.rounded_rectangle((90, progress_y, 90 + fill_width, progress_y + 12), radius=6, fill=(235, 235, 242))
    footer = f"Scene {index + 1}/{total}  ·  Original faceless render"
    box = draw.textbbox((0, 0), footer, font=small_font)
    draw.text(((width - (box[2] - box[0])) / 2, 1590), footer, font=small_font, fill=(220, 223, 232))

    image.save(path, quality=95)

jobs = request(
    "GET",
    "/rest/v1/render_jobs?status=eq.queued&select=*&order=created_at.asc&limit=1",
) or []
if not jobs:
    print("No queued render jobs.")
    raise SystemExit(0)

job = jobs[0]
patch("render_jobs", job["id"], {"status": "running", "engine": ENGINE, "updated_at": "now()"})

try:
    projects = request("GET", f"/rest/v1/video_projects?id=eq.{job['project_id']}&select=*") or []
    if not projects:
        raise RuntimeError("Project not found.")
    project = projects[0]
    script = (project.get("script") or "").strip()
    title = (project.get("title") or "Untitled video").strip()
    if not script:
        raise RuntimeError("Add a script before requesting a render.")

    patch_pipeline(project["id"], "voice", "running", "Generating local neural narration with Piper.")
    patch_pipeline(project["id"], "visuals", "running", "Building original vertical motion-card scenes.")
    patch_pipeline(project["id"], "edit", "running", "Rendering captions, mastered audio, and final MP4.")

    work = Path("render-work")
    work.mkdir(exist_ok=True)
    VOICE_DIR.mkdir(exist_ok=True)

    script_file = work / "script.txt"
    script_file.write_text(script, encoding="utf-8")

    raw_audio = work / "voice_raw.wav"
    model_path = VOICE_DIR / f"{VOICE_MODEL}.onnx"
    if not model_path.exists():
        run(
            [
                "python",
                "-m",
                "piper.download_voices",
                "--download-dir",
                str(VOICE_DIR),
                VOICE_MODEL,
            ]
        )

    with script_file.open("r", encoding="utf-8") as source:
        run(
            [
                "piper",
                "--model",
                str(model_path),
                "--output_file",
                str(raw_audio),
                "--length-scale",
                "0.96",
            ],
            stdin=source,
        )

    audio = work / "voice.wav"
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(raw_audio),
            "-af",
            "highpass=f=70,lowpass=f=12000,acompressor=threshold=-18dB:ratio=2.5:attack=20:release=250,loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar",
            "44100",
            "-ac",
            "2",
            str(audio),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    duration = probe_duration(audio)
    if duration < 3:
        raise RuntimeError(f"Narration is unexpectedly short ({duration:.2f}s).")

    scenes_dir = work / "scenes"
    scenes_dir.mkdir(exist_ok=True)
    scene_copy = scene_texts(title, script, count=6)
    scene_paths = []
    for index, copy in enumerate(scene_copy):
        scene_path = scenes_dir / f"scene_{index:02}.png"
        make_scene(scene_path, copy, index, len(scene_copy))
        scene_paths.append(scene_path)

    scene_duration = duration / len(scene_paths)
    concat_file = work / "scenes.txt"
    concat_lines = []
    for scene_path in scene_paths:
        concat_lines.append(f"file '{scene_path.resolve()}'")
        concat_lines.append(f"duration {scene_duration:.6f}")
    concat_lines.append(f"file '{scene_paths[-1].resolve()}'")
    concat_file.write_text("\n".join(concat_lines), encoding="utf-8")

    base_video = work / "visuals.mp4"
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-vf",
            "fps=30,scale=1080:1920:flags=lanczos",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-t",
            f"{duration:.3f}",
            str(base_video),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    words = script.split()
    chunk_size = 7
    chunks = [" ".join(words[i : i + chunk_size]) for i in range(0, len(words), chunk_size)] or [""]
    weights = [max(1, len(re.sub(r"\W", "", chunk))) for chunk in chunks]
    total_weight = sum(weights)
    cursor = 0.0
    srt = []
    for index, (chunk, weight) in enumerate(zip(chunks, weights), start=1):
        start = cursor
        cursor += duration * weight / total_weight
        end = duration if index == len(chunks) else cursor
        srt += [str(index), f"{timestamp(start)} --> {timestamp(end)}", chunk, ""]

    captions = work / "captions.srt"
    captions.write_text("\n".join(srt), encoding="utf-8")

    output = work / "output.mp4"
    subtitle_filter = (
        f"subtitles={captions}:force_style="
        "'FontName=DejaVu Sans,FontSize=28,Bold=1,PrimaryColour=&H00FFFFFF,"
        "BackColour=&H90000000,BorderStyle=3,Outline=0,Shadow=0,"
        "Alignment=2,MarginL=70,MarginR=70,MarginV=245'"
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(base_video),
            "-i",
            str(audio),
            "-vf",
            subtitle_filter,
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-shortest",
            str(output),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    run(
        ["ffmpeg", "-v", "error", "-i", str(output), "-f", "null", "-"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    probe = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(output),
            ]
        ).decode()
    )
    video_streams = [s for s in probe.get("streams", []) if s.get("codec_type") == "video"]
    audio_streams = [s for s in probe.get("streams", []) if s.get("codec_type") == "audio"]
    if not video_streams or not audio_streams:
        raise RuntimeError("Final MP4 is missing a video or audio stream.")
    video_stream = video_streams[0]
    if int(video_stream.get("width", 0)) != 1080 or int(video_stream.get("height", 0)) != 1920:
        raise RuntimeError("Final MP4 is not 1080x1920.")
    if output.stat().st_size < 250_000:
        raise RuntimeError("Final MP4 is unexpectedly small and failed technical validation.")

    object_path = f"{job['user_id']}/{job['project_id']}/{job['id']}.mp4"
    upload_url = (
        SUPABASE_URL
        + "/storage/v1/object/video-outputs/"
        + urllib.parse.quote(object_path, safe="/")
    )
    with output.open("rb") as file:
        req = urllib.request.Request(
            upload_url,
            data=file.read(),
            headers={
                "apikey": SERVICE_KEY,
                "Authorization": f"Bearer {SERVICE_KEY}",
                "Content-Type": "video/mp4",
                "x-upsert": "true",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=180) as response:
            response.read()

    patch(
        "render_jobs",
        job["id"],
        {
            "status": "completed",
            "engine": ENGINE,
            "output_url": object_path,
            "error": None,
            "updated_at": "now()",
        },
    )
    patch(
        "video_projects",
        project["id"],
        {
            "output_url": object_path,
            "status": "quality_check",
            "failure_reason": None,
            "updated_at": "now()",
        },
    )
    patch_pipeline(project["id"], "voice", "passed", "Piper neural narration generated and mastered successfully.")
    patch_pipeline(project["id"], "visuals", "passed", "Six original 1080x1920 scene cards generated successfully.")
    patch_pipeline(project["id"], "edit", "passed", "MP4 decoded successfully with H.264 video, AAC audio, and burned captions.")
    print(f"Rendered {object_path} ({duration:.1f}s, {output.stat().st_size / 1_000_000:.1f} MB)")

except Exception as exc:
    message = str(exc)[:1000]
    patch(
        "render_jobs",
        job["id"],
        {"status": "failed", "engine": ENGINE, "error": message, "updated_at": "now()"},
    )
    patch(
        "video_projects",
        job["project_id"],
        {"status": "failed", "failure_reason": message, "updated_at": "now()"},
    )
    for step in ("voice", "visuals", "edit"):
        try:
            patch_pipeline(job["project_id"], step, "failed", message)
        except Exception:
            pass
    raise
