"""Blender-backed coordinated long-form renderer.

Each of 20 workers renders one continuity-locked segment from a shared episode
manifest. The manifest is the contract for character IDs, voices, wardrobe,
locations, camera language, palette, dialogue, SFX cues, and transition handles.
This module intentionally uses fictional cinematic props only.
"""
import json, os, shutil, subprocess, sys
from pathlib import Path

WORKER = int(os.environ.get("ROLIXA_WORKER", "1"))
SEGMENTS = int(os.environ.get("ROLIXA_LONGFORM_SEGMENTS", "20"))
FPS = int(os.environ.get("ROLIXA_LONGFORM_FPS", "24"))
ROOT = Path(os.environ.get("ROLIXA_EPISODE_DIR", ".rolixa-episode"))
MANIFEST = ROOT / "episode.json"


def load_manifest():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if len(data.get("segments", [])) != SEGMENTS:
        raise RuntimeError(f"episode manifest must contain exactly {SEGMENTS} segments")
    return data


def validate_segment(seg):
    required = ("index", "duration", "shots", "continuity_in", "continuity_out")
    missing = [k for k in required if k not in seg]
    if missing:
        raise RuntimeError("segment missing " + ", ".join(missing))
    if not 50 <= float(seg["duration"]) <= 70:
        raise RuntimeError("segment duration must stay near one minute")
    if not seg["shots"]:
        raise RuntimeError("segment has no shots")


def blender_render(manifest, seg):
    blender = shutil.which("blender")
    if not blender:
        raise RuntimeError("Blender is required but is not installed on this render worker")
    ROOT.mkdir(parents=True, exist_ok=True)
    segfile = ROOT / f"segment-{WORKER:02}.json"
    segfile.write_text(json.dumps({"episode": manifest["episode"], "bible": manifest["bible"], "segment": seg}, indent=2), encoding="utf-8")
    driver = Path(__file__).with_name("blender_scene_driver.py")
    cmd = [blender, "--background", "--factory-startup", "--python", str(driver), "--", str(segfile), str(ROOT / f"segment-{WORKER:02}.mp4")]
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
