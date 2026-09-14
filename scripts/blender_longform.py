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
        print("portrait overlay not present; Blender will use procedural face fallback")
        return
    text = overlay.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"BLACKSTAR_PORTRAIT_SPRITE=['\"]data:image/jpeg;base64,([^'\"]+)", text)
    if not m:
        print("portrait sprite data not found; Blender will use procedural face fallback")
        return
    portrait_dir = ROOT / "portraits"
    portrait_dir.mkdir(parents=True, exist_ok=True)
    sprite = portrait_dir / "sprite.jpg"
    sprite.write_bytes(base64.b64decode(m.group(1)))
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg unavailable for portrait crops; procedural face fallback")
        return
    for i, cid in enumerate(PORTRAIT_IDS):
        out = portrait_dir / f"{cid}.jpg"
        # The approved sprite is nine equal vertical portrait panels.
        vf = f"crop=iw/9:ih:{i}*iw/9:0,scale=360:540:force_original_aspect_ratio=increase,crop=360:540"
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(sprite), "-vf", vf, "-q:v", "2", str(out)], check=True)
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
