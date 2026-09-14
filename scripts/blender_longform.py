"""Blender-backed coordinated long-form renderer.

Each of 20 workers renders one continuity-locked segment from a shared episode
manifest and one immutable common environment library. This module intentionally
uses fictional cinematic props only.
"""
import json, os, shutil, subprocess
from pathlib import Path

WORKER = int(os.environ.get("ROLIXA_WORKER", "1"))
SEGMENTS = int(os.environ.get("ROLIXA_LONGFORM_SEGMENTS", "20"))
FPS = int(os.environ.get("ROLIXA_LONGFORM_FPS", "24"))
ROOT = Path(os.environ.get("ROLIXA_EPISODE_DIR", ".rolixa-episode"))
LIBRARY = Path(os.environ.get("BLACKSTAR_LIBRARY_DIR", ".blackstar-library"))
MANIFEST = ROOT / "episode.json"


def load_manifest():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if len(data.get("segments", [])) != SEGMENTS:
        raise RuntimeError(f"episode manifest must contain exactly {SEGMENTS} segments")
    if not (LIBRARY / "library.json").exists():
        raise RuntimeError("BLACKSTAR shared environment library is required")
    return data


def validate_segment(seg):
    required = ("index", "duration", "shots", "continuity_in", "continuity_out")
    missing = [k for k in required if k not in seg]
    if missing: raise RuntimeError("segment missing " + ", ".join(missing))
    if not 50 <= float(seg["duration"]) <= 70: raise RuntimeError("segment duration must stay near one minute")
    if not seg["shots"]: raise RuntimeError("segment has no shots")


def blender_render(manifest, seg):
    blender = shutil.which("blender")
    if not blender: raise RuntimeError("Blender is required but is not installed on this render worker")
    ROOT.mkdir(parents=True, exist_ok=True)
    segfile = ROOT / f"segment-{WORKER:02}.json"
    segfile.write_text(json.dumps({"episode": manifest["episode"], "bible": manifest["bible"], "segment": seg}, indent=2), encoding="utf-8")
    scripts = Path(__file__).parent
    bootstrap = scripts / "blender_common_library_bootstrap.py"
    driver = scripts / "blender_scene_driver.py"
    cmd = [blender, "--background", "--factory-startup", "--python", str(bootstrap), "--python", str(driver), "--", str(segfile), str(ROOT / f"segment-{WORKER:02}.mp4")]
    subprocess.run(cmd, check=True)


def main():
    manifest = load_manifest()
    if WORKER < 1 or WORKER > SEGMENTS: raise RuntimeError("worker index outside long-form segment range")
    seg = manifest["segments"][WORKER - 1]
    validate_segment(seg)
    blender_render(manifest, seg)

if __name__ == "__main__": main()
