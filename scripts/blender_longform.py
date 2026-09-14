"""Blender-backed coordinated long-form renderer.

Each of 20 workers renders one continuity-locked segment from a shared episode
manifest and one immutable common environment library. Character identity plates
are extracted from the same approved BLACKSTAR portrait sprite used by Rolixa so
faces stay visually consistent between the dashboard and animation.
"""
import base64
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

WORKER = int(os.environ.get("ROLIXA_WORKER", "1"))
SEGMENTS = int(os.environ.get("ROLIXA_LONGFORM_SEGMENTS", "20"))
FPS = int(os.environ.get("ROLIXA_LONGFORM_FPS", "24"))
ROOT = Path(os.environ.get("ROLIXA_EPISODE_DIR", ".rolixa-episode"))
LIBRARY = Path(os.environ.get("BLACKSTAR_LIBRARY_DIR", ".blackstar-library"))
MANIFEST = ROOT / "episode.json"

PORTRAIT_IDS = [
    "MARA_VOSS", "JAX_MERCER", "IMANI_VALE", "ROOK", "KESTREL",
    "RV_KADE", "RV_NYX", "RV_BRIGGS", "RV_SABLE",
]


def load_manifest():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if len(data.get("segments", [])) != SEGMENTS:
        raise RuntimeError(f"episode manifest must contain exactly {SEGMENTS} segments")
    if not (LIBRARY / "library.json").exists():
        raise RuntimeError("BLACKSTAR shared environment library is required")
    return data


def validate_segment(seg):
    required = ("index", "duration", "shots", "continuity_in", "continuity_out", "dialogue")
    missing = [k for k in required if not seg.get(k)]
    if missing:
        raise RuntimeError("segment missing " + ", ".join(missing))
    if not 50 <= float(seg["duration"]) <= 70:
        raise RuntimeError("segment duration must stay near one minute")
    if len(seg["shots"]) < 4:
        raise RuntimeError("segment needs at least four visual beats")


def extract_portrait_references():
    """Decode the Rolixa portrait sprite and crop deterministic identity references."""
    overlay = Path("blackstar-portrait-overlay.js")
    if not overlay.exists():
        raise RuntimeError("approved BLACKSTAR portrait overlay is missing")
    text = overlay.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"BLACKSTAR_PORTRAIT_SPRITE=['\"]data:image/jpeg;base64,([^'\"]+)", text)
    if not m:
        raise RuntimeError("approved BLACKSTAR portrait sprite data was not found")

    payload = re.sub(r"\s+", "", m.group(1))
    # Preserve the approved sprite exactly. Recover only narrow JS-editing damage:
    # one stray base64 character, or at most three decoded bytes after a complete
    # JPEG EOI marker. Strict base64, SOI/EOI and ffmpeg crop decoding still gate
    # every render, so truncated/corrupt portrait data remains blocked.
    candidates = [payload]
    if len(payload.rstrip("=")) % 4 == 1:
        candidates.append(payload.rstrip("=")[:-1])

    raw = None
    last_error = None
    for candidate in candidates:
        padded = candidate + "=" * (-len(candidate) % 4)
        try:
            decoded = base64.b64decode(padded, validate=True)
        except Exception as exc:
            last_error = exc
            continue
        if len(decoded) < 1024 or not decoded.startswith(b"\xff\xd8"):
            continue
        clean = decoded.rstrip(b"\x00")
        if clean.endswith(b"\xff\xd9"):
            raw = clean
            break
        eoi = clean.rfind(b"\xff\xd9")
        if eoi >= 1022 and len(clean) - (eoi + 2) <= 3:
            raw = clean[:eoi + 2]
            print(f"recovered approved portrait sprite by trimming {len(clean) - (eoi + 2)} trailing byte(s)")
            break
    if raw is None:
        detail = f": {last_error}" if last_error else ""
        raise RuntimeError(f"approved portrait sprite is invalid or incomplete JPEG{detail}")

    portrait_dir = ROOT / "portraits"
    portrait_dir.mkdir(parents=True, exist_ok=True)
    sprite = portrait_dir / "sprite.jpg"
    sprite.write_bytes(raw)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to prepare operator portrait references")
    for i, cid in enumerate(PORTRAIT_IDS):
        out = portrait_dir / f"{cid}.jpg"
        vf = f"crop=iw/9:ih:{i}*iw/9:0,scale=360:540:force_original_aspect_ratio=increase,crop=360:540"
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(sprite), "-vf", vf, "-q:v", "2", str(out)], check=True)
        if not out.is_file() or out.stat().st_size < 512:
            raise RuntimeError(f"portrait crop failed for {cid}")
    print(f"prepared {len(PORTRAIT_IDS)} BLACKSTAR/RED VECTOR identity references")


def blender_render(manifest, seg):
    blender = shutil.which("blender")
    if not blender:
        raise RuntimeError("Blender is required but is not installed on this render worker")
    ROOT.mkdir(parents=True, exist_ok=True)
    extract_portrait_references()
    segfile = ROOT / f"segment-{WORKER:02}.json"
    segfile.write_text(
        json.dumps({"episode": manifest["episode"], "bible": manifest["bible"], "segment": seg}, indent=2),
        encoding="utf-8",
    )
    scripts = Path(__file__).parent
    bootstrap = scripts / "blender_common_library_bootstrap.py"
    driver = scripts / "blender_scene_driver.py"
    cmd = [
        blender, "--background", "--factory-startup",
        "--python", str(bootstrap), "--python", str(driver), "--",
        str(segfile), str(ROOT / f"segment-{WORKER:02}.mp4"),
    ]
    subprocess.run(cmd, check=True)


def main():
    manifest = load_manifest()
    if WORKER < 1 or WORKER > SEGMENTS:
        raise RuntimeError("worker index outside long-form segment range")
    seg = manifest["segments"][WORKER - 1]
    validate_segment(seg)
    blender_render(manifest, seg)


if __name__ == "__main__":
    main()
