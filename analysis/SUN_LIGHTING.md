# Captured sun and remaining live bands — 2026-10-29

## Verified evidence

F9 `frame_30632051` (original/F10 view is valid) contains 3,382 draws and BUFFEREX light views:
11 point elements at stride 48 and 17 spot elements at stride 80. The standalone probe decodes
26 contributing candidates, creates 24 runtime lights, and renders the scene successfully.
The normal 90-second `--hold` watchdog terminates the probe; this is not evidence of a render crash
or of clean runtime teardown.

Scene pixel shaders `ps_1840405040.asm:112-121` and `ps_1840405584.asm:106-115` identify:

- PS CB2 byte 0: directional-light RGB `(6.0, 5.1, 4.8)`.
- PS CB2 byte 16: unit surface-to-light vector `(-0.4291814, 0.8386706, -0.3353132)`.
- PS CB3 byte 12: per-material light multiplier, 1.0 in these captures.
- The normal dot product and view+light half-vector confirm the vector's meaning.
- Remix Distant.direction is the opposite (incoming ray travel).

Both captures (`frame_23275488`, `frame_30632051`) have identical verified sun bytes.
The latest has 1,068 full-attribute scene draws with that prefix; 182 other bindings contain
`[5,5,5,1],[1,1,1,1]`, which is not a valid unit-direction sun prefix.

## Probe-only change

`light_convert::parse_sun` reads the verified 32-byte PS CB2 prefix, checks finite nonnegative RGB,
unit direction and direction-row w=0, and returns incoming direction plus colour. This is not a
shader/layout detector. A caller must identify the correct scene shader and PS buffer first.

`triangle.cpp` optionally consumes `scene_sun.bin`, otherwise keeping its original placeholder sun.
`run_remote.py --sun-cb <verified_PS_CB2_file>` explicitly uploads that file; a stale diagnostic
sidecar in the scene directory is not automatically uploaded. The converter is unchanged.
Do not call this automatic capture-to-live sun recovery.

The diagnostic manually extracts `frame_30632051/draw_2404/ps_cb_2.bin` bytes 0..31.
Artifact metadata and SHA256: `analysis/runtime/remix-probe/bands-30632051/sun-extraction.json`.
To repeat the sun run, use `run_remote.py captured-sun --scene <scene.bin> --sun-cb <scene_sun.bin>
--hold --shot-frame 900 --no-unload` (only when laptop inference is already idle).

## Laptop result

- Baseline: `windows-bands-30632051-20261029T201653Z.json`.
- Captured sun: `windows-captured-sun-30632051-20261029T202310Z.json`.
- Display comparison: `analysis/runtime/remix-probe/bands-30632051/sun-before-after.png`.
- Same geometry/materials/local lights, no screenshot exposure lift. Captured sun is brighter/warmer.
- Sky remains dark; neither sky illumination nor radiometric intensity matching is solved.
- Sun RGB is copied directly as a diagnostic. No claim of equivalence between game intensity and
  Remix radiance; keep the existing 20-degree disc for this controlled comparison.
- The rendered executable preceded the extra w=0 validation; actual verified data has w=0.
  Current source was rebuilt and all focused gates rerun after that guard was added.

## DeepSeek review and vertex claim

DeepSeek completed an independent review and confirmed the sun offsets/sign. Its w=0 validation
suggestion has a red-then-green regression case. Its specific disc-intensity formula is not yet
verified against this Remix runtime, so it is not used to scale the light.

It also flagged live/offline decoder differences: incomplete/unsupported skinning layouts,
POSITION formats other than float3, and missing instance matrices. These are source-level risks,
not established causes of the user's long live bands.

Direct scan of main-viewport full-attribute draws:

| Capture | Scene surface draws | Unsupported element formats | Mismatched skinning layouts | POSITION not float3 |
|---|---:|---:|---:|---:|
| frame_23275488 | 553 | 0 | 0 | 3 |
| frame_30632051 | 1,250 | 0 | 0 | 7 |

The latest seven use format 10 and decode offline to 1–2-unit world extents. They are missing
from live, not proof of stretched live triangles. All 3,374 successfully decoded latest draws
have finite world positions and no bad bone references; finite wrong transforms/buffers remain possible.
The clean static render does NOT establish that the live bands are fixed. No live DLL was installed.

## Verification and review ledger

Passed: `test_sun_convert.py` (15 cases), `test_probe_sun_upload.py` (3 mocked upload cases,
no laptop contact), `test_light_convert.py`, `test_live_vertex_decode.py`, and
`remix-probe/build.py --scene` (native sanitizers/self-check and Windows cross-build).
The full Wine suite was not rerun; no live-path behaviour was changed.

Delegation outcomes are recorded in the repository-local
`analysis/runtime/delegation-outcomes-sun.jsonl`; the external Documents ledger was not modified.
Two OpenAI review launches failed (registry mismatch, then API model access); no review claims
are based on them. The user-requested DeepSeek review completed and was checked against real data.

## Live integration (2026-10-29, not yet verified in the running game)

- **Sky dome crash: root cause and fix.** The generated DX10 DDS lacked `DDPF_FOURCC` in its pixel format (and
  `DDSD_PITCH`/`DDSCAPS_COMPLEX`). Same texels with corrected header render on the laptop runtime
  (`windows-sky-dds-fixed-20261029T213157Z.json`); before, `0xc0000094`. Gate: `checks/test_sky_dds.py`.
  The symbolised `DdsFileParser::parse` frame came from an unmatched local binary, consistent but not proof.
- **Sky strength 2.0** chosen from `remix-probe/sky-dds-fixed/sky-fill-0.5-vs-2.png` (synthetic gradient sky,
  not the game's sky). Live: `nier_sky_hdr.dds` beside the scene file (sha256 e8746bd0...211f) or `NIER_REMIX_SKY_DDS`;
  `NIER_REMIX_SKY` overrides strength. Remove the file to drop the dome texture.
- **Live sun.** First non-sky scene draw per frame with a PS CB2 that passes `parse_sun` (dummy bindings fail it).
  Recreated only on change. Runtime light handle == hash, so the old handle is destroyed before re-creation
  (`test_live_scene.py` case 11, red under create-then-destroy).
- **Native HUD.** Before the first draw whose PS DXBC checksum is the shipped HUD sprite
  (`A1B772527CEA5742`, `hud_shader.h`) into a full-size R11G11B10F target, the Remix image is drawn into that target;
  the game then draws its own HUD sprites and final copy. Present skips its overwrite on those frames.
  Gate: `checks/test_native_hud.py` (shipped PS, synthetic VS; red when the hook is removed).
  Final target is plain RGBA8 (trace lists sRGB formats separately), so display-encoded bytes are sampled as UNORM.
- Live game uses PortalRTX's runtime, not the laptop's: dome texture behaviour there is unverified.
