"""Build one immutable environment library shared by every BLACKSTAR segment worker.

Poly Haven provides CC0 lighting/material assets. Runway and Luma are used when
GitHub Actions secrets are available. If those optional provider secrets are not
present, deterministic local cinematic BMP plates are generated instead so the
render pipeline remains fully functional and every worker still receives the exact
same hashed environment library.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import time
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


def _write_bmp(path: Path, mode: str, width=1280, height=720):
    row_bytes = (width * 3 + 3) & ~3
    pixel_bytes = row_bytes * height
    header = bytearray(54)
    header[0:2] = b"BM"
    struct.pack_into("<I", header, 2, 54 + pixel_bytes)
    struct.pack_into("<I", header, 10, 54)
    struct.pack_into("<I", header, 14, 40)
    struct.pack_into("<i", header, 18, width)
    struct.pack_into("<i", header, 22, height)
    struct.pack_into("<H", header, 26, 1)
    struct.pack_into("<H", header, 28, 24)
    struct.pack_into("<I", header, 34, pixel_bytes)
    pad = b"\0" * (row_bytes - width * 3)
    with path.open("wb") as f:
        f.write(header)
        for y in range(height):
            yy = y / max(1, height - 1)
            row = bytearray()
            for x in range(width):
                xx = x / max(1, width - 1)
                if mode == "erebus":
                    horizon = 0.43
                    sky = max(0.0, min(1.0, (yy - horizon) / (1 - horizon)))
                    base = 18 + int(38 * sky)
                    r, g, b = base + 7, base + 16, base + 27
                    if yy < horizon:
                        r, g, b = 18, 22, 28
                    for cx, w, h in ((.18,.08,.18),(.37,.12,.25),(.62,.10,.20),(.82,.07,.15)):
                        if abs(xx-cx) < w and horizon-0.02 < yy < horizon+h:
                            r, g, b = 24, 37, 47
                    if abs(yy-horizon) < .006:
                        r, g, b = 190, 118, 46
                elif mode == "gateway":
                    d = math.hypot(xx-.5, yy-.5)
                    ring = max(0.0, 1.0 - abs(d-.23)*22)
                    r = int(10 + 18*(1-yy) + 25*ring)
                    g = int(13 + 22*(1-yy) + 110*ring)
                    b = int(20 + 30*(1-yy) + 150*ring)
                    if abs(xx-.5) < .015 or abs(yy-.5) < .012:
                        r, g, b = min(255,r+15), min(255,g+25), min(255,b+35)
                elif mode == "shaft":
                    edge = abs(xx-.5)
                    depth = max(0.0, 1.0-edge*1.7)
                    r = int(8 + 22*depth + 16*(1-yy))
                    g = int(15 + 42*depth + 20*(1-yy))
                    b = int(22 + 65*depth + 26*(1-yy))
                    if int(xx*18)%5==0 or int(yy*16)%7==0:
                        r, g, b = min(255,r+20), min(255,g+22), min(255,b+24)
                else:
                    d = math.hypot((xx-.53)*1.05, (yy-.48)*1.35)
                    planet = d < .34
                    r, g, b = (4,7,14)
                    if planet:
                        shade = max(0, int(46*(1-d/.34)))
                        r, g, b = 8+shade//5, 16+shade//2, 28+shade
                        signal = (int(xx*131)+int(yy*197)) % 43 == 0 and xx > .48
                        if signal:
                            r, g, b = 48, 200, 240
                row.extend((max(0,min(255,b)), max(0,min(255,g)), max(0,min(255,r))))
            f.write(row)
            f.write(pad)
    return path


def local_plate(name, prompt, mode, intended_provider):
    path = _write_bmp(ROOT / name, mode)
    return {
        "provider": "Local Procedural",
        "intended_provider": intended_provider,
        "source_mode": "deterministic credential-free fallback",
        "file": path.name,
        "sha256": sha(path),
        "prompt": prompt,
    }


def runway_plate(name, prompt, mode):
    if not os.environ.get("RUNWAYML_API_SECRET"):
        return local_plate(name.replace(".jpg", ".bmp"), prompt, mode, "Runway")
    try:
        from runwayml import RunwayML
        client = RunwayML()
        task = client.text_to_image.create(
            model="gen4_image", ratio="1920:1080", prompt_text=prompt,
        ).wait_for_task_output()
        if not task.output:
            raise RuntimeError("Runway returned no image")
        path = download(task.output[0], ROOT / name, max_bytes=20_000_000)
        return {"provider":"Runway","model":"gen4_image","task_id":str(task.id),"file":path.name,"sha256":sha(path),"prompt":prompt}
    except Exception as e:
        print(f"Runway unavailable, using local fallback: {e}")
        return local_plate(name.replace(".jpg", ".bmp"), prompt, mode, "Runway")


def luma_plate(name, prompt, mode):
    key = os.environ.get("LUMA_API_KEY")
    if not key:
        return local_plate(name.replace(".jpg", ".bmp"), prompt, mode, "Luma AI")
    try:
        headers = {"Authorization": f"Bearer {key}"}
        g = post_json(
            "https://api.lumalabs.ai/dream-machine/v1/generations/image",
            {"prompt": prompt, "aspect_ratio": "16:9", "model": "photon-flash-1"}, headers,
        )
        gid = g["id"]
        deadline = time.time() + 600
        while time.time() < deadline:
            g = get_json(f"https://api.lumalabs.ai/dream-machine/v1/generations/{gid}", headers)
            state = g.get("state")
            if state == "completed": break
            if state == "failed": raise RuntimeError(f"Luma generation failed: {g.get('failure_reason')}")
            time.sleep(5)
        else:
            raise RuntimeError("Luma generation timed out")
        url = (g.get("assets") or {}).get("image")
        if not url: raise RuntimeError("Luma returned no image")
        path = download(url, ROOT / name, max_bytes=20_000_000)
        return {"provider":"Luma AI","model":"photon-flash-1","generation_id":gid,"file":path.name,"sha256":sha(path),"prompt":prompt}
    except Exception as e:
        print(f"Luma unavailable, using local fallback: {e}")
        return local_plate(name.replace(".jpg", ".bmp"), prompt, mode, "Luma AI")


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
        runway_plate("runway-erebus.jpg", f"{style}. Empty frontier colony Erebus exterior, broad landing pad, modular habitat towers, distant storm haze, deep perspective, no people.", "erebus"),
        runway_plate("runway-gateway.jpg", f"{style}. Vast underground reactor chamber containing an original geometric alien gateway, monumental machinery, volumetric haze, deep vanishing point, no people.", "gateway"),
        luma_plate("luma-shaft.jpg", f"{style}. Vertical zero-gravity industrial maintenance shaft, cables, gantries, cold fog, dramatic depth, no people.", "shaft"),
        luma_plate("luma-orbit.jpg", f"{style}. Dark hemisphere of an alien frontier planet from orbit, sparse city lights, debris field and hundreds of faint distant signal points, no spacecraft branding.", "orbit"),
    ]
    manifest = {
        "library_version": 3,
        "episode": "BLACKSTAR S01E01 First Contact",
        "shared_by_workers": 20,
        "immutable_for_run": True,
        "assets": assets,
    }
    (ROOT / "library.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"library": str(ROOT), "providers": [a["provider"] for a in assets], "assets": [a["file"] for a in assets]}, indent=2))


if __name__ == "__main__":
    main()
