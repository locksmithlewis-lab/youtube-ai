"""Strict preflight audit for BLACKSTAR S1E1.

Fails fast on story, continuity, character, render-contract, or publishing-contract
regressions before expensive Blender workers start.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MANIFEST = Path(sys.argv[1] if len(sys.argv) > 1 else "episodes/blackstar-s01e01/episode.json")
SCREENPLAY = MANIFEST.with_name("screenplay.md")

ALLOWED_SPEAKERS = {
    "KESTREL", "VOSS", "JAX", "ROOK", "VALE", "VEYR COMMANDER",
    "UNKNOWN RED VECTOR VOICE",
}
FORBIDDEN_FRANCHISE_TERMS = {
    "master chief", "spartan", "covenant", "unsc", "rainbow six", "team rainbow",
}
REQUIRED_IDS = {"MARA_VOSS", "JAX_MERCER", "IMANI_VALE", "ROOK"}
REQUIRED_ROLE_BEATS = {
    "MARA_VOSS": ("aegis", "lane", "anti-entry"),
    "JAX_MERCER": ("breach", "manta", "open"),
    "IMANI_VALE": ("null loom", "deny", "uplink"),
    "ROOK": ("ghostline", "recon", "route"),
    "KESTREL": ("sensor", "extraction", "network"),
}


def fail(msg: str) -> None:
    raise SystemExit("BLACKSTAR AUDIT FAILED: " + msg)


def main() -> None:
    if not MANIFEST.is_file():
        fail(f"missing manifest: {MANIFEST}")
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    ep = data.get("episode") or {}
    bible = data.get("bible") or {}
    segments = data.get("segments") or []

    if ep.get("series") != "BLACKSTAR" or ep.get("season") != 1 or ep.get("episode") != 1:
        fail("wrong series/season/episode identity")
    if ep.get("aspect") != "16:9":
        fail("episode must remain 16:9")
    if len(segments) != 20:
        fail(f"expected 20 segments, found {len(segments)}")

    total = 0.0
    combined = []
    for i, seg in enumerate(segments, 1):
        if seg.get("index") != i:
            fail(f"segment index mismatch at position {i}")
        dur = float(seg.get("duration", 0))
        if not 50 <= dur <= 70:
            fail(f"segment {i} duration {dur} outside 50-70s")
        total += dur
        shots = seg.get("shots") or []
        if len(shots) < 4:
            fail(f"segment {i} needs at least four visual beats")
        if not seg.get("continuity_in") or not seg.get("continuity_out"):
            fail(f"segment {i} missing continuity contract")
        if i > 1:
            prev = str(segments[i-2].get("continuity_out", "")).strip().lower()
            cur = str(seg.get("continuity_in", "")).strip().lower()
            if not (prev in cur or cur in prev or set(prev.split()) & set(cur.split())):
                fail(f"continuity handoff {i-1}->{i} appears unrelated: {prev!r} vs {cur!r}")
        dialogue = str(seg.get("dialogue") or "").strip()
        if not dialogue:
            fail(f"segment {i} has no dialogue")
        speakers = re.findall(r"(?:^|\s)([A-Z][A-Z ]+):", dialogue)
        unknown = {s.strip() for s in speakers if s.strip() not in ALLOWED_SPEAKERS}
        if unknown:
            fail(f"segment {i} unknown speaker(s): {sorted(unknown)}")
        combined.extend(shots)
        combined.append(dialogue)

    if not 1140 <= total <= 1260:
        fail(f"total planned duration {total:.0f}s is not approximately 20 minutes")
    target = float(ep.get("target_duration_seconds", 0))
    if abs(total - target) > 60:
        fail(f"planned duration {total:.0f}s differs too much from target {target:.0f}s")

    ids = {c.get("id") for c in bible.get("characters", [])}
    if not REQUIRED_IDS.issubset(ids):
        fail(f"missing core character IDs: {sorted(REQUIRED_IDS - ids)}")
    ai = bible.get("ai_character") or {}
    if ai.get("id") != "KESTREL":
        fail("KESTREL AI character contract missing")

    all_text = " ".join(map(str, combined)).lower()
    for cid, terms in REQUIRED_ROLE_BEATS.items():
        if not any(t in all_text for t in terms):
            fail(f"role readability missing for {cid}")
    for term in FORBIDDEN_FRANCHISE_TERMS:
        if term in all_text:
            fail(f"forbidden copied-franchise term found: {term}")

    continuity_rules = bible.get("continuity_rules") or []
    if not any("faces" in str(x).lower() and "clothes" in str(x).lower() for x in continuity_rules):
        fail("persistent face/clothing continuity rule missing")
    if not any("music" in str(x).lower() and "crossfade" in str(x).lower() for x in continuity_rules):
        fail("audio seam continuity rule missing")

    if not SCREENPLAY.is_file() or SCREENPLAY.stat().st_size < 4000:
        fail("finished screenplay.md missing or too short")

    print("BLACKSTAR audit passed")
    print(f"segments={len(segments)} total_duration={total:.0f}s screenplay_bytes={SCREENPLAY.stat().st_size}")


if __name__ == "__main__":
    main()
