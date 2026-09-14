# BLACKSTAR S1E1 — Production Audit

Audit date: 2026-09-14

## Scope

This audit covers the Episode 1 story contract, continuity, Rolixa character cards, Blender orchestration, shared environment library, character identity continuity, dialogue parsing, audio mastering, final assembly, production registration, QC handoff, CTA, and publish handoff.

## Fixed

- Rolixa active BLACKSTAR page now loads the realistic portrait overlay after the legacy SVG UI and uses cache-busted module URLs for mobile browsers.
- BLACKSTAR and RED VECTOR operator portraits share one approved identity sprite so the UI and renderer can use the same face references.
- Episode 1 has a finished screenplay at `screenplay.md` in addition to the 20-segment machine-readable production manifest.
- Added strict preflight validation before expensive rendering: episode identity, 20 segments, duration, visual beats, continuity handoffs, valid dialogue speakers, operator-role readability, originality checks, persistent face/clothing rules, audio seam rules, screenplay presence, and Python compile checks.
- Corrected continuity wording at the 8→9 and 17→18 handoffs instead of weakening the validator.
- Blender source rendering is optimized for GitHub CPU runners at 1280×720/18fps and normalized to the required 1920×1080/24fps final master.
- Removed the previous expensive scene-wide volumetric cube and reduced unnecessary procedural geometry while preserving the shot/camera/continuity contract.
- Human BLACKSTAR operators now use visible heads, skin materials, layered outfit geometry, role accents, and approved portrait identity planes instead of opaque geometric helmet heads.
- Kestrel is represented as an electronic/holographic support presence rather than a physical squad body.
- Fixed dialogue parsing for multi-word speakers such as `VEYR COMMANDER` and `UNKNOWN RED VECTOR VOICE`.
- Added explicit voice mappings for the Veyr Commander and RED VECTOR final sting.
- Final assembler validates 20 segments, normalizes A/V, verifies 1920×1080 video plus audio, validates runtime, and adds the final six-second `LIKE + SUBSCRIBE • BLACKSTAR WILL RETURN` CTA.
- Production registration now uses real UTC ISO timestamps instead of literal `now()` strings in REST payloads.
- Production registration now uses the finished screenplay for creative QC when available.
- Corrected the normal publish-drain endpoint to the active Rolixa deployment domain.
- Hidden GitHub artifact paths are uploaded with `include-hidden-files: true`.
- The current workflow cancels obsolete BLACKSTAR episode runs when a newer render begins.

## Validation state

The strict preflight and Python compile checks passed after the continuity fixes. The shared common-library build also passed. A fresh 20-worker render was launched from the corrected manifest and optimized renderer.

The production database intentionally has no BLACKSTAR video project or series record yet. Registration occurs only after a real complete master is assembled; this prevents a placeholder or incomplete episode from appearing as production-ready.

## Required finish criteria

Episode 1 is not considered finished until all twenty segment artifacts exist, each segment contains audio and valid duration, the assembled master is approximately twenty minutes, the final file is 1920×1080 with video and audio streams, production registration succeeds, creative and final-video QC execute, and the `blackstar-s01e01-master` artifact exists.

No quality gate should be bypassed to obtain a green workflow.
