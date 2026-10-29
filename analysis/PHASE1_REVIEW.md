# Phase 1 pre-test review (2026-10-29)

## Why the picture looked wrong: three causes, found from data (2026-10-29 evening)

Second live run (`df239034…`): Remix ran (scene filter worked, skipped_pass≈1300) but the picture was a beige haze with
streaks; `hud=0`, `lights=0`, 3-5 fps, then a crash with VRAM at 15.6/16 GB. An F9 capture (`frame_23275488`, 1894
draws) was analysed offline and A/B-rendered on the laptop (RTX Spark, same capture, `analysis/runtime/remix-probe/
before-after-materials.png`).

1. **Material defaults (the main one).** `make_material_info` (shared by live and captured paths) and the probe set
   `blendType_hasvalue=1` (= blending ON, type 2 reverse-alpha-emissive), `alphaTestType=0` (kNever) and left
   `filterMode`/`wrapModeU/V` at 0 (= nearest, clamp; MDL `tex::wrap_repeat` is 1). Result: every surface
   see-through by its texture alpha (2B rendered white and translucent), tiled textures smeared into streaks, blocky
   textures. Fixed to NVIDIA's `remix.h` defaults (no blend, kAlways, linear, repeat). Laptop render after the fix:
   solid geometry, 2B in her black dress, no streaks or haze; 52 fps at 1.22M triangles. Gate
   `test_material_defaults.py` (red on the old header).
2. **Depth pre-pass duplicates.** 38-42% of scene draws (4 captures, 2622/2622 with a full twin) are a POSITION-only
   pre-pass; the live path submitted them as a second untextured shell and doubled the mesh set (thrash, VRAM).
   Skipped by layout (`prepass=` in the stats). Gates `test_live_scene_target` (prepass), `test_prepass_rule_captures`.
3. **Alpha-tested foliage/decals** (22% of scene draws, 11 of 23 pixel shaders discard on `t0.a`): now an alpha-test
   material with the shader's own comparison and threshold, read once per shader via `D3DDisassemble`
   (`alpha_test.h`; gates `test_alpha_test_parse`, `test_live_alpha_state` alpha_test). Smaller effect than 1 in the
   A/B, but correct.

Still open: **lights** (`lights=0`; the render above is lit only by a generic sky, hence dark), **HUD** (NieR's HUD is
DrawIndexed into a separate 3440x1440 composite target `T5124` with its transform in CB0, not CB11; plan: feed the
Remix image into the game's own composite at the part3-redirect point so the game draws its own HUD, instead of
re-implementing it), **fps** (copy path, Phase 2). Rejected on evidence: vertex-shader-deformed geometry (the clay
render and the decode scan show correct geometry), wrong TEXCOORD choice, corrupt texture capture.

## First live run (2026-10-29 17:32 UTC, build `a4eaf86f…`): crashed at the title screen. Cause found and fixed

**What happened.** The first live frame was 6 title-screen draws. 74 ms later the game died. Proton logged nothing;
Remix's crashpad wrote a minidump (`read_minidump.py`):
`STATUS_INTEGER_DIVIDE_BY_ZERO` at `d3d9.dll+0x1d30cc`, `div r8` with `r8 = align(0, 64)`, inside DxvkBuffer's slice
computation. The caller is `updateSurfaceMaterials` → `createBuffer(…, "Surface Material Buffer")`. Upstream
`rtx_scene_manager.cpp:2376-2388` creates that buffer whenever the material cache is non-empty, sized by the frame's
ray-traced surface count, with no zero check. Remix hides SKY-category instances from ray tracing
(`rtx_instance_manager.cpp:1049`). The title screen's draws are sky-sized backdrop geometry, which item 1.9 now flags
SKY instead of dropping. The result was a frame with only SKY instances, zero surfaces and a crash. Older builds dropped
those draws, so they never submitted such a frame.

**Fix.** `live_scene::ready()` now requires a non-sky instance with a built mesh. A sky-only frame is held back and the
previous image stays up. **Gate:** the fake runtime now records a `VIOLATION` for a Present whose instances are all SKY
(the real runtime's crash condition). `test_live_geometry` "skyfirst" draws only the dome for 30 frames, then the world.
It was red on `a4eaf86f…` and is green after the fix. **Fixed build `df239034c71238aaf05348ef8cd437c244d0693556da7488d2c1741ac4a2e756` passes 38/38 and is installed**
(previous `a4eaf86f…` backed up by the installer).

**Unknown until the next run:** whether the 6 title draws really were all sky (they are not logged per draw). The
minidump proves the zero-surface condition. Sky-only is the only path to it in our submission that I can find.

## Fix status (same day): all R1–R10 fixed, gated, independently reviewed

**Reviewed candidate: `a4eaf86fe2bb011f9892fa2bbef46dc5b22f4ae41b132eac9935e88ee71b2f81`.** The full suite passes on it (38/38,
2026-10-29 17:28 UTC). **Installed** in the game the same minute, hash-verified; rollback in
`backups/live-scene-20261029T172859383059Z/` (previous `e313c177…`). Mesa 26.2.5. Awaiting the live run (ROADMAP
"Phase 1 test protocol").

| # | Fix | Gate that was red before, green after |
|---|---|---|
| R1 | analyzer accepts `key=v` and `key v` | `test_analyze_live_run.py` (new; lines rendered from the DLL's own format strings) |
| R2 | analyzer reads only the last run (`remix: enabled`) | same |
| R3 | stats line gains `lights=`, `light_creates=`, `sky=` (per draw); PASS/FAIL/LOOK/SHORT per row | same |
| R4 | installer requires `--expect <sha256>`, atomic replace, verified restore, refuses without `pgrep` | dry run checked by hand |
| R5 | real rollback switches `NIER_REMIX_LIVE_NO_HUD=1`, `NIER_REMIX_LIVE_NO_SKY=1`; ROADMAP text corrected | `test_live_hud_capture` (nohud), `test_live_geometry` (nosky) |
| R6 | latch needs 3 consecutive empty frames; latch is logged once | `test_live_scene_target` (flicker: every 10th frame empty) |
| R7 | light array read by the first draw that binds slot 20 | `test_live_lights` (slot 20 unbound on the first draw: old code found no lights at all) |
| R8 | changed light destroyed and recreated with the same hash | `test_live_lights` (light moves at frame 50) |
| R9 | HUD VS `mul(m, v)`: the translation must land in xyz, not w | `test_live_hud_capture` (CB11 translation of 0.6; red: drawn untranslated) |
| R10 | HUD save/restore of all 8 RTVs + DSV, blend factor + sample mask, GS/HS/DS cleared for the draw | `test_live_hud_capture` (`hud_state_lost=0` with DSV and blend factor bound across Present) |
| — | live-capture hooks installed only for a live session | `test_remix_live` off run: `ctx_map_in_proxy=0`; live: `1` |
| — | scene target == final image: blended scene draws stay world geometry | `test_live_scene_target` (full) |
| — | RTV size cache cleared per frame, honours MipSlice; light `FirstElement`; HUD decode pinned; `permitted` re-checked under the lock; F10 keeps mirroring writes and opens no frame | existing suite (no dedicated gate) |

Known limits left in the code:
* At native (100%) render scale, a blended HUD element of ≥128 indices is submitted as world geometry. The size of the
  render target cannot separate the scene from the HUD at that scale (marked `shortcut:` in `live_capture.h`). The protocol uses Custom75.
* Sky is still "world extent > 5000". It is the same rule as the captured-scene path, now with `NIER_REMIX_LIVE_NO_SKY` as the way back.
* Only RT slot 0 is classified. Non-capturable textures stay referenced for the session. The same-hash light recreate
  is unproven on the real runtime.
* Red not demonstrated for `hud_state_lost` alone, because the run failed earlier on the translation assertion. The
  old code restored a null DSV, which that check compares against.

Review of the Phase 1 tree **before** its first live run. Candidate `analysis/runtime/menu-dll/d3d11.dll`
`376e40e7d91e…` (rebuilt by the suite, same hash). Installed in the game: older `e313c177…`. The last
`NIER_SCALE.log` predates the A1 filter.

Method: the lead re-ran all 37 gates (all pass; 5 need their header argument: `test_camera_decode{,_hidden}.py
camera_decode.h`, `test_nscn_scene{,_hidden}.py nscn_scene.h`, `test_remix_scale.py render_settings.h`). The lead also
checked the context vtable slots against the mingw header (Map 14, Unmap 15, DrawIndexed 12, DrawIndexedInstanced 20,
Copy* 46/47/48: correct). Then three independent cloud reviewers (capture path; Remix submission + HUD; gates,
protocol and analyzer) and one online-research pass. "Confirmed" means the lead read the source line.

## Fix before the live test (would make the run unreadable or wrong)

| # | Finding | Where | Status |
|---|---|---|---|
| R1 | Analyzer cost split never prints: fps line is `present %.0f` (no `=`), regex wants `present=` | `remix_live.cpp:458`, `analyze_live_run.py` | confirmed |
| R2 | `NIER_SCALE.log` is opened in append mode, so the analyzer mixes every past run (old 5.6 s watchdog stall, old first frame). Slice from the last `remix: enabled` line | `d3d11_scale_setter.cpp:39` | confirmed |
| R3 | No verdict for 1.3, 1.5, 1.8, 1.9, 1.10: no `lights=` / sky key in the log; `hud=`, `dropped=`, `mesh_bytes=` are logged but not parsed; 1.10 needs first/max/last trends, not `stats[-1]` | analyzer + stats line | reviewer, keys spot-checked |
| R4 | Installer is not hash-pinned (ROADMAP says it is): it installs whatever is in `runtime/menu-dll/` | `install_live_dll.py` | confirmed |
| R5 | ROADMAP rollback names switches that do not exist: `NIER_REMIX_CAPTURE_COMPOSITE` only writes a debug `.raw`, there is no HUD-off or sky-off env | ROADMAP "If it goes wrong" | reviewer |
| R6 | Filter latch is cumulative: `scene_target_fallbacks` never resets, so 3 transient empty frames spread over a session (resize, loads) turn the filter off for good. The comment says "three strikes" but means consecutive | `live_capture.h:593-595` | confirmed |
| R7 | Light array read is spent on the first draw even if PS slot 20 is unbound there: `lights_read = true` before the SRV check → zero lights that frame | `live_capture.h:770-771` | confirmed |
| R8 | Lights never update: `if (s.lights[i]) continue;` keeps first-seen position/colour; index shifts when zero-position slots are compacted. 0.6.6 has no UpdateLight → Destroy+Create with the same hash on change (RemixSDK.md says exactly this) | `live_scene.h:195` | confirmed |
| R9 | HUD replay multiplies `mul(float4(pos,1), m)` with `m` = CB11 rows, but capture treats CB11 column 3 as translation, so translation lands in w. The gate's HUD CB11 is identity, so it cannot see this. Unverified against NieR's HUD shader | `hud_replay.h:47,231-235` | confirmed inconsistent |
| R10 | HUD state restore drops the game's DSV (`OMGetRenderTargets(1,&rtv,nullptr)` / restore with null DSV), doesn't save blend factor / sample mask, doesn't clear GS/HS/DS | `hud_replay.h:144,160` | confirmed (DSV) |

## Fix soon (wrong only off the protocol's settings, or slow leaks)

* **Unconditional capture hooks** (old P0 class): `menu_overlay.cpp:465` installs Map/Unmap/UpdateSubresource/Copy*
  hooks on every launch. They pass through behind one `permitted` atomic, so no readbacks happen. Still, "Remix off ⇒
  unchanged" now means "one extra indirect call", not "no hooks". Move the install under `live_enabled`. No gate checks
  hook installation.
* **Scene == final image** (Native / 100% scale): `choose_scene_target` rejects `size >= final` and falls back to the
  final size, then `ui_pass` routes *every blended world draw* to the HUD replay. Custom75 (the protocol's setting)
  is not affected. Gate uses 960x540 in 1920x1080 only.
* **RTV size cache keyed by raw pointer, no AddRef**: a released, reused RTV address keeps its old size until the
  4096-entry clear. It ignores MipSlice/ArraySlice. MRT reads slot 0 only.
* **Sky = any geometry whose extent is >5000 units** (first instance only). It matches the captured-scene rule that rendered
  correctly offline, so the risk is lower than the reviewer stated. Still no negative case in the gate.
* **HUD decode before `Pin`**: over the 256 MB shadow budget a trim can empty an earlier-returned buffer. Move `Pin`
  above the `ui_pass` block.
* F10 suspension clears `permitted`, so writes during F10 aren't mirrored and resume doesn't invalidate shadows.
* `permitted` checked before the mutex, not re-checked under it (teardown race).
* Non-capturable textures AddRef'd and never released; `waiting_materials` keyed by raw pointer; `unchanged` ignores
  a changed texture; refused lights retried every frame; HUD blend state created every frame.
* Light `Buffer.FirstElement` ignored (unverified that NieR uses non-zero).

## Rejected / already handled

* "Static path now uses the live camera when `NIER_REMIX_LIVE` is off": this is the live camera accepted on
  2026-10-28. It is intended.
* Bone cap: Remix clamps to `REMIXAPI_INSTANCE_INFO_MAX_BONES_COUNT` (256), and `live_capture.h:813` already clamps.
* Blend-state, SRV and slot-20 refcounts balance. Remix struct `sType`s and category bits match `remix_c.h`.
  Late-material rebuild fires once, and materials are cached per texture.

## Protocol changes

* 90 s cannot decide 1.10: `expire_frames` = 1800 (~90-190 s at 10-20 fps), and budgets are not reached. Add a
  separate ≥10-minute run with a walk and one area change.
* Add one resize / menu-resolution step (the `paused` path and R6 are untested live).
* Don't use the Remix menu's capture button (rtx-remix #671: crash on API meshes with no albedo).
* Record the Mesa version, keep frame generation / Reflex off, run without Special K / ReShade, and save `journalctl -k`
  afterwards (a GPU hang can freeze the desktop).

## Online (new since PRIOR_ART.md; source is dxvk-remix `main`, not 0.6.6)

* Destroy* calls are queued and return success immediately. Destroying a handle that the current frame still
  references is undocumented. Destroy after Present.
* A material texture path that fails to resolve gives an empty texture **with no log line**. This is a live lead for
  1.7 (white surfaces): stat the DDS before `CreateMaterial` and count misses.
* Lights: same `hash` on recreate for denoiser stability, and `DrawLightInstance` every frame (we already do).
* The SKY bit switches the instance to the sky camera unless VIEW_MODEL is also set.
* rtx-remix #874: light create/destroy crash fixed July 2025 (0.6.6 may predate it). #1101: Proton DLFG presenter
  deadlock (open). Mesa < 25.1.3 is a known-bad RDNA4 baseline. RDNA4 RT timeouts are still reported in 2026
  (vkd3d-proton #3036).
* No public precedent for D3D11 HUD compositing over Remix, or for render-target filtering. Expect 1.8 to be debugged
  from scratch.
