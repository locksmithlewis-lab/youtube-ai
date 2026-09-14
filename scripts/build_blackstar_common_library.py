"""Build one immutable environment library shared by every BLACKSTAR segment worker.

The library deliberately combines complementary sources rather than regenerating
per worker: Poly Haven CC0 physical lighting/material assets, Runway original
exterior/interior plates, and Luma original depth/orbital plates. Every downloaded
file is hashed and the manifest is uploaded once as a GitHub Actions artifact, so
all 20 render workers consume byte-identical environment assets.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("BLACKSTAR_LIBRARY_DIR", ".blackstar-library"))
ROOT.mkdir(parents=True, exist_ok=True)
UA = "Rolixa-BLACKSTAR/1.0 (github.com/locksmithlewis-lab/youtube-ai)"


def get_json(url, headers=None):
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def post_json(url, payload, headers):
    h = {"User-Agent": UA, "Accept": "application/json", "Content-Type": "application/json"}
    h.update(headers)
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def download(url, path, max_bytes=120_000_000):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        n = int(r.headers.get("Content-Length") or 0)
        if n and n > max_bytes:
            raise RuntimeError(f"asset too large: {n} bytes")
        data = r.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise RuntimeError("asset exceeded download cap")
    path.write_bytes(data)
    return path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def flatten_files(node, prefix=""):
    out = []
    if isinstance(node, dict):
        if isinstance(node.get("url"), str):
            out.append((prefix, node))
        for k, v in node.items():
            out.extend(flatten_files(v, f"{prefix}/{k}"))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out.extend(flatten_files(v, f"{prefix}/{i}"))
    return out


def choose_asset(kind, words):
    assets = get_json(f"https://api.polyhaven.com/assets?t={kind}")
    scored = []
    for aid, meta in assets.items():
        tags = meta.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        hay = " ".join(
            [aid, str(meta.get("name", "")), str(meta.get("description", "")), str(meta.get("category", ""))]
            + [str(x) for x in tags]
        ).lower()
        score = sum(3 if w in hay else 0 for w in words)
        scored.append((score, aid, meta))
    scored.sort(key=lambda x: (-x[0], x[1]))
    if not scored:
        raise RuntimeError(f"Poly Haven returned no {kind}")
    return scored[0]


def polyhaven_file(kind, words, exts, filename):
    _, aid, meta = choose_asset(kind, words)
    files = get_json(f"https://api.polyhaven.com/files/{aid}")
    candidates = []
    for key, entry in flatten_files(files):
        url = entry.get("url", "")
        low = (key + " " + url).lower()
        if any(url.lower().split("?")[0].endswith(e) for e in exts):
            # Keep CI fast and deterministic: prefer 1K, then 2K, then smallest file.
            rank = (0 if "1k" in low else 1 if "2k" in low else 2, int(entry.get("size") or 0))
            candidates.append((rank, url, key))
    if not candidates:
        raise RuntimeError(f"No usable file for Poly Haven asset {aid}")
    candidates.sort(key=lambda x: x[0])
    path = download(candidates[0][1], ROOT / filename)
    return {
        "provider": "Poly Haven",
        "asset_id": aid,
        "asset_name": meta.get("name", aid),
        "file": path.name,
        "sha256": sha(path),
        "license": "CC0",
        "api_attribution": "Powered by Poly Haven",
    }


def runway_plate(name, prompt):
    from runwayml import RunwayML

    if not os.environ.get("RUNWAYML_API_SECRET"):
        raise RuntimeError("RUNWAYML_API_SECRET is required")
    client = RunwayML()
    # gen4_image supports text-only generation. Do not use the Turbo variant here:
    # Turbo is optimized around reference-image workflows and can reject text-only jobs.
    task = client.text_to_image.create(
        model="gen4_image",
        ratio="1920:1080",
        prompt_text=prompt,
    ).wait_for_task_output()
    if not task.output:
        raise RuntimeError("Runway returned no image")
    path = download(task.output[0], ROOT / name, max_bytes=20_000_000)
    return {
        "provider": "Runway",
        "model": "gen4_image",
        "task_id": str(task.id),
        "file": path.name,
        "sha256": sha(path),
        "prompt": prompt,
    }


def luma_plate(name, prompt):
    key = os.environ.get("LUMA_API_KEY")
    if not key:
        raise RuntimeError("LUMA_API_KEY is required")
    headers = {"Authorization": f"Bearer {key}"}
    g = post_json(
        "https://api.lumalabs.ai/dream-machine/v1/generations/image",
        {"prompt": prompt, "aspect_ratio": "16:9", "model": "photon-flash-1"},
        headers,
    )
    gid = g["id"]
    deadline = time.time() + 600
    while time.time() < deadline:
        g = get_json(f"https://api.lumalabs.ai/dream-machine/v1/generations/{gid}", headers)
        state = g.get("state")
        if state == "completed":
            break
        if state == "failed":
            raise RuntimeError(f"Luma generation failed: {g.get('failure_reason')}")
        time.sleep(5)
    else:
        raise RuntimeError("Luma generation timed out")
    url = (g.get("assets") or {}).get("image")
    if not url:
        raise RuntimeError("Luma returned no image")
    path = download(url, ROOT / name, max_bytes=20_000_000)
    return {
        "provider": "Luma AI",
        "model": "photon-flash-1",
        "generation_id": gid,
        "file": path.name,
        "sha256": sha(path),
        "prompt": prompt,
    }


def main():
    style = (
        "original BLACKSTAR universe, grounded cinematic military science fiction, "
        "graphite and steel-blue industrial architecture, restrained cyan technology, "
        "amber practical lights, realistic scale, realistic lens depth, no text, no logos, "
        "no copyrighted franchise designs, 16:9 background plate"
    )
    assets = [
        polyhaven_file("hdris", ["night", "industrial", "city"], (".hdr", ".exr"), "polyhaven-environment.hdr"),
        polyhaven_file("textures", ["metal", "concrete", "industrial"], (".jpg", ".jpeg", ".png"), "polyhaven-surface.jpg"),
        runway_plate(
            "runway-erebus.jpg",
            f"{style}. Empty frontier colony Erebus exterior, broad landing pad, modular habitat towers, distant storm haze, deep perspective, no people.",
        ),
        runway_plate(
            "runway-gateway.jpg",
            f"{style}. Vast underground reactor chamber containing an original geometric alien gateway, monumental machinery, volumetric haze, deep vanishing point, no people.",
        ),
        luma_plate(
            "luma-shaft.jpg",
            f"{style}. Vertical zero-gravity industrial maintenance shaft, cables, gantries, cold fog, dramatic depth, no people.",
        ),
        luma_plate(
            "luma-orbit.jpg",
            f"{style}. Dark hemisphere of an alien frontier planet from orbit, sparse city lights, debris field and hundreds of faint distant signal points, no spacecraft branding.",
        ),
    ]
    manifest = {
        "library_version": 2,
        "episode": "BLACKSTAR S01E01 First Contact",
        "shared_by_workers": 20,
        "immutable_for_run": True,
        "assets": assets,
    }
    (ROOT / "library.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"library": str(ROOT), "assets": [a["file"] for a in assets]}, indent=2))


if __name__ == "__main__":
    main()
