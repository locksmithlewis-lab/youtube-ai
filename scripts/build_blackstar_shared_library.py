"""Build one deterministic environment library shared by every BLACKSTAR segment.

Sources are deliberately complementary:
- Poly Haven: CC0 HDRI lighting/environment base via its public API.
- Runway: one original cinematic environment concept plate when configured.
- Luma: one original companion environment concept plate when configured.
- Blender: consumes the same downloaded library in every render worker.

Provider failures are recorded rather than silently replaced. Blender can still render
from the procedural bible if a paid generation provider is unavailable or out of credits.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(os.environ.get("ROLIXA_SHARED_LIBRARY", ".blackstar-library"))
EPISODE = Path(os.environ.get("EPISODE_MANIFEST", "episodes/blackstar-s01e01/episode.json"))
UA = "Rolixa-BLACKSTAR-Environment-Library/1.0"
TIMEOUT = 120


def download(url: str, dest: Path) -> str:
    r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return str(dest)


def poly_haven_hdri(dest: Path) -> dict:
    # Prefer an industrial HDRI appropriate for Erebus. Fall back deterministically
    # to the best industrial/urban result returned by the public asset catalogue.
    candidates = ["smelting_tower_02"]
    try:
        assets = requests.get(
            "https://api.polyhaven.com/assets",
            params={"type": "hdris"},
            headers={"User-Agent": UA}, timeout=TIMEOUT,
        ).json()
        ranked = []
        for asset_id, meta in assets.items():
            hay = " ".join([asset_id, meta.get("name", ""), meta.get("description", ""), *(meta.get("tags") or [])]).lower()
            score = sum(k in hay for k in ("industrial", "factory", "urban", "night", "dusk", "smelting"))
            if score:
                ranked.append((-score, asset_id))
        candidates.extend(a for _, a in sorted(ranked)[:20])
    except Exception:
        pass

    errors = []
    for asset_id in dict.fromkeys(candidates):
        try:
            files = requests.get(
                f"https://api.polyhaven.com/files/{asset_id}",
                headers={"User-Agent": UA}, timeout=TIMEOUT,
            )
            files.raise_for_status()
            data = files.json()
            hdri = data.get("hdri", {})
            choice = None
            for res in ("2k", "1k", "4k"):
                block = hdri.get(res, {})
                for ext in ("hdr", "exr"):
                    if isinstance(block.get(ext), dict) and block[ext].get("url"):
                        choice = block[ext]["url"]
                        break
                if choice:
                    break
            if not choice:
                continue
            suffix = Path(urlparse(choice).path).suffix or ".hdr"
            path = dest / f"polyhaven-{asset_id}{suffix}"
            download(choice, path)
            return {"provider": "Poly Haven", "asset_id": asset_id, "path": str(path), "license": "CC0"}
        except Exception as exc:
            errors.append(f"{asset_id}: {exc}")
    raise RuntimeError("Poly Haven HDRI unavailable: " + " | ".join(errors[-4:]))


def runway_plate(prompt: str, dest: Path) -> dict:
    if not os.environ.get("RUNWAYML_API_SECRET"):
        raise RuntimeError("RUNWAYML_API_SECRET is not configured")
    from runwayml import RunwayML
    client = RunwayML()
    task = client.text_to_image.create(
        model="gen4_image",
        ratio="1920:1080",
        prompt_text=prompt,
    ).wait_for_task_output()
    if not getattr(task, "output", None):
        raise RuntimeError("Runway returned no image output")
    path = dest / "runway-erebus-environment.jpg"
    download(task.output[0], path)
    return {"provider": "Runway", "path": str(path), "purpose": "shared distant environment plate"}


def luma_plate(prompt: str, dest: Path) -> dict:
    key = os.environ.get("LUMA_API_KEY")
    if not key:
        raise RuntimeError("LUMA_API_KEY is not configured")
    r = requests.post(
        "https://api.lumalabs.ai/dream-machine/v1/generations/image",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json"},
        json={"model": "photon-1", "prompt": prompt, "aspect_ratio": "16:9", "format": "jpg", "sync": True, "sync_timeout": 120},
        timeout=150,
    )
    r.raise_for_status()
    data = r.json()
    url = (data.get("assets") or {}).get("image")
    if not url:
        raise RuntimeError(f"Luma image not completed synchronously: state={data.get('state')}")
    path = dest / "luma-erebus-environment.jpg"
    download(url, path)
    return {"provider": "Luma", "path": str(path), "purpose": "shared companion environment plate"}


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    episode = json.loads(EPISODE.read_text(encoding="utf-8"))
    bible = episode["bible"]
    prompt = (
        "Original BLACKSTAR military science-fiction environment, abandoned Erebus frontier colony and underground industrial complex, "
        "graphite steel architecture, restrained cyan diagnostics, amber emergency practical lights, volumetric haze, enormous engineered spaces, "
        "grounded cinematic realism, believable human scale, no people, no text, no logos, no copyrighted franchise designs, 16:9 production background. "
        f"Visual bible: {bible['visual_style']}. Palette: {bible['palette']}."
    )
    manifest = {
        "version": 1,
        "episode": episode["episode"],
        "visual_style": bible["visual_style"],
        "palette": bible["palette"],
        "camera": bible["camera"],
        "procedural_seed": 2479,
        "assets": {},
        "errors": {},
        "credit": "Environment library uses Poly Haven live API assets where available; Poly Haven assets are CC0.",
    }
    for name, fn in (("poly_haven_hdri", poly_haven_hdri), ("runway_plate", lambda d: runway_plate(prompt, d)), ("luma_plate", lambda d: luma_plate(prompt, d))):
        try:
            manifest["assets"][name] = fn(ROOT)
            print(f"shared library: {name} ready")
        except Exception as exc:
            manifest["errors"][name] = str(exc)
            print(f"shared library warning: {name}: {exc}")
    # Poly Haven is free and deterministic, so require it. Paid AI plates are additive
    # and may be unavailable because of account credits/quota; that must not kill rendering.
    if "poly_haven_hdri" not in manifest["assets"]:
        raise RuntimeError(manifest["errors"].get("poly_haven_hdri", "shared HDRI missing"))
    (ROOT / "library.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"assets": list(manifest["assets"]), "errors": manifest["errors"]}, indent=2))


if __name__ == "__main__":
    main()
