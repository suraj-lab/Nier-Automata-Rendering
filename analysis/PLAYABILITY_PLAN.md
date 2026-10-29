# Playability first, performance second

Ordering decided 2026-10-29: make NieR *playable as an RTX game* — the picture and the interface right — and only
then optimise for the hardware. Performance work that makes a wrong picture smoother is wasted, and two of our
biggest "performance" mysteries (the 5 fps and the doubling) are picture bugs in disguise.

Everything below is ordered. Each item says what we need, whether it can be settled **offline** from data we
already have, and what "done" means. Offline-settled items have no dependency on the game launching.

Data source for the draw-mix numbers: the real captured frame `NIER_DLAA_frame_20261025_195822_205.txt`
(2436 draws with a viewport, recorded by the F9 capture). Counts are from that frame, not from a live run.

## What "an RTX game" means here (acceptance for stage A)

1. Geometry and transforms follow the game (already live).
2. Each pass is submitted once: no shadow-map or post pass drawn as world geometry.
3. Every surface has the right material: albedo rather than white, cutout for foliage/hair/grilles, emissive
   for lights/screens, translucent for glass and water.
4. Lighting comes from the game: sun, sky, **and the game's dynamic point/spot lights** (today: sun + sky only).
5. Sky renders as sky, not as geometry.
6. Characters look right: skinning (done), hair cards, smooth normals on low-poly surfaces.
7. The game's HUD and menus are visible and usable; the in-game settings menu still works.
8. Camera has no lag, no flicker, no double image, correct FOV/aspect after upscaling.
9. Stable over a 10-minute run: no leaks, no forgotten meshes, no GPU faults.
10. Then, and only then: frame rate, resolution scale, latency.

## The draw mix we are working with (one real frame)

| draws | pass | evidence |
| --- | --- | --- |
| 1375 | main view | viewport 2580x1080, RT 2580x1080, 48 distinct pixel shaders, all carry CB11 |
| 920 | **shadow atlas** | viewport 2048x2048, RT 4096x4096 |
| 58 | **HUD / UI sprites** | viewport 3440x1440 into the 3440x1440 target, 3 distinct PS, per-element constants |
| 58 | bloom chain | viewport 1290x540 (half of the main view) |
| 21 | misc small | 256x256, 322x134, 80x33, 1024x1, … |

Two consequences:

* 38% of submissions are shadow-atlas work. The `NIER_REMIX_LIVE_SKIP_SMALL_VIEWPORT=25` filter written before this
  measurement cannot see them (2048 > 25% of 3440); it is superseded by the render-target filter in A1
  (`NIER_REMIX_LIVE_ALL_TARGETS=1` restores the old submit-everything behaviour).
* The HUD is not a special layer: it is 58 sprite draws into the final 3440x1440 target. That is also the only
  cheap way to keep it — capture those draws and re-draw them over the Remix image, rather than trying to detect
  "menus are open".

## Stage A — the picture (playability)

### A1. Submit each pass once — DONE offline (2026-10-29, not installed)
* **Need:** during capture, record each draw's render target and viewport; treat a draw as world geometry only
  when it targets the main view.
* **Offline:** done. Rule: the scene target is the largest target strictly smaller than the final image with the
  final image's aspect ratio; a frame that the choice empties latches the filter off. Gate
  `analysis/checks/test_live_scene_target.py` (with a red test and a fallback test). Details in `PROGRESS.md`
  checkpoint 2026-10-29.
* **Done:** the live path submits ~1400 draws, not ~2900; nothing disappears from the picture.

### A2. Materials: albedo, cutout, emissive
* **Need:** per-draw material selection instead of "first PS texture is albedo".
  * **Cutout for alpha-blended draws — DONE offline (2026-10-29).** The live path reads the game's blend state per
    draw and marks straight-alpha draws `ALPHA_BLEND_TO_CUTOUT`; additive blending is excluded on purpose. Gate
    `analysis/checks/test_live_alpha_state.py`. One live run's `blended=` reports whether the rule matches the game.
  * **Cutout for opaque-path shaders — not yet wired.** The authority is the shader's `discard`:
    `analysis/checks/shader_capture.h` already stores each pixel shader's bytecode and `test_shader_capture.py` proves
    a captured blob disassembles and is recognised as a discard shader. Missing: call `D3DDisassemble` once per new
    shader inside the proxy, carry the flag to the material (`alphaTestType` + `alphaReferenceValue`).
  * `IGNORE_ALPHA_CHANNEL` (1<<21) remains unused for the case where alpha is not a mask at all.
  * **Albedo — confirmed by the shaders themselves.** `analysis/SHADER_DECLARATIONS.md`: slot 0 is
    `g_ColorTexture` (4985 shaders) or `g_Texture0` (3583), slot 4 `g_NormalTexture`, slot 2 `g_MaskTexture`,
    slot 11 `g_ShadowTexture`, slot 12 `g_FogLUT`, slot 13 `g_ZTexture`, slot 17 `g_AO_Texture`. Measured on the real
    frame: slot 0 is bound on 1375/1375
    main-view draws and always holds the largest colour texture (1024², 2048², 512², 256²), while slots 4-14 hold
    128²/64²/32² maps (masks, LUTs, dither). "First bound PS texture" already picks the albedo.
    **Correction (2026-10-29, during review of the delegated fix):** I first claimed the white surfaces came from a
    deferred texture leaving a geometry permanently untextured. That was wrong — the pre-fix code *skipped building*
    the mesh while its texture was deferred and built it with the material once the texture landed, so the symptom was a
    briefly invisible object, not a permanent white one. The deferred-material work is still worth having (it removes the
    invisibility and pins the rule in `test_live_late_material.py`), but **the cause of white surfaces is unknown again**
    and the next measurement is a `textures=`/`untextured=` counter in the live stats line: it distinguishes "texture
    never written" (disk budget, read failure, unsupported format) from "written but no material created".
  * Emissive: `MaterialInfo.emissiveTexture` / `emissiveIntensity` / `emissiveColorConstant` from the game's
    pixel-shader constants.
* **Offline:** cutout yes (gate exists); emissive needs the PS constant-buffer layout, which is analysis of
  shader code we already disassemble, not a game run.
* **Done:** foliage and grilles cut out instead of rendering as solid cards; lights and screens glow; surfaces
  are textured rather than white.

### A3. Dynamic lights from the game
* **Need:** the game's point/spot lights. We create one sun and one sky light and never update them
  (`!s.sun || !s.sky` in the live path). Remix wants `CreateLight` + `DrawLightInstance` per light, per frame.
* **Settled offline 2026-10-29** (`analysis/SHADER_DECLARATIONS.md`, generated from 10137 captured PS blobs): the
  renderer is **tiled forward** — point lights are a *structured buffer* at SRV slot 20 (48-byte elements), per-tile
  light indices at slot 21, spot lights at slot 22, with 2276/2191 shaders binding them. A constant-buffer scan for a
  light array finds nothing because lights are not in a constant buffer; that is a result, not a dead end.
* **Route:** capture the three structured buffers the same way vertex/index buffers are captured (staging read, one
  per frame, small), decode 48-byte point-light elements, and emit `CreateLight`/`DrawLightInstance`. Until that
  exists, emissive materials (A2) already give lamps a path-tracing light path: an emissive surface illuminates in
  Remix without any light API.
* **Done:** lamps, pods and explosions light the scene; the camp is not lit only by the sun.

### A4. Sky and atmosphere
* **Need:** tag the sky mesh with `REMIXAPI_INSTANCE_CATEGORY_BIT_SKY` (we never set any category flags), and set
  the runtime sky option rather than our hand-made sky light. Remix Plus's sky/weather system is richer, but
  upstream has the category bit today.
* **Offline:** yes — the capture already excludes some sky draws (`skipped_sky` counter exists).
* **Done:** no black band, no sky geometry as world, ambient matches the scene.

### A5. Characters
* **Need:** human body visibly correct — skinning is live; add `SMOOTH_NORMALS` (1<<24) and `HAIR_CARDS`
  (1<<25) categories for the relevant draws, and check bone space against Remix's expectation (open item).
* **Offline:** partly. `SMOOTH_NORMALS`/`HAIR_CARDS` are flag work; bone-space correctness needs the game.
* **Done:** no exploded or rubber-limbed characters.

### A6. HUD, menus, and the settings mod
* **Measured (2026-10-29, reference frame):** the whole HUD is **56 draws by a single pixel shader**
  (`A1B772527CEA5742`), 52 of them straight-alpha blended, and **all 58 draws into that target carry CB11** — i.e. the
  sprites are placed by a world matrix that maps to clip space, not by a separate screen-space path. The A1
  render-target filter therefore already keeps them out of the scene (correct), and they are absent from the picture.
* **Design:** replay those draws as a 2D overlay through the existing menu-overlay draw path (`menu_overlay.cpp` already
  draws textured quads into the game's backbuffer): decode the sprite geometry with the existing vertex decoder, use the
  captured CB11 as the transform with an identity view/projection, sample the already-captured texture, and composite the
  result over the Remix image at Present. One shader, one texture set, no new Remix feature.
* **Need:** the 58 sprite draws into the 3440x1440 target, re-drawn over the Remix image. Our proxy already owns
  Present and the game backbuffer, so this is a compositing decision, not a Remix feature:
  * option 1 — capture the UI pass as screen-space quads and draw them in D3D11 after the Remix blit;
  * option 2 — keep the game's UI draws and let them write into the presented texture last.
  Remix's `combineGuiInFinalColor` / `dxvk_CopyRenderingOutput(GUI)` is **Remix's own dev GUI**, not the game's
  HUD — do not confuse the two (I did, in `PRIOR_ART.md`, now corrected).
* **Offline:** the classification is offline; the compositing path is testable with the mock game
  (`analysis/checks/menu_overlay_mock_game.cpp`).
* **Done:** HUD visible in path-traced view, in-game menu mod opens and saves, no flicker on transition.

### A7. Stability
* **Need:** the one unexplained GPU fault (`gfx page fault in dxvk-submit`, ring timeout, wedged GPU) after the
  old F10 teardown; plus the bounded-run evidence Remix expects (10 minutes, no growth in meshes/bytes).
* **Offline:** no. Instrumentation only: the surface-slot drop counter (Minecraft's documented signature) and
  the per-stage `ms/frame` split we already print.
* **Done:** 10-minute run in the path-traced view with flat counters.

## Stage B — the hardware (optimisation), only after A

1. **The 163 ms readback** (`GetRenderTargetData` + `LockRect` + CPU swizzle) — measured as 86% of the frame.
   Route B1 in `PRIOR_ART.md`: `dxvk_CopyRenderingOutput` into an owned surface, pipelined publish, GPU
   conversion. Route B2 (fork shared handle) only if B1 still leaves the copy visible.
2. **Submission cost** — with A1 in place there are ~1400 draws, half of today's. Upstream's `drawcall2`
   instance preservation and the fork's `AutoInstancePersistentLights` are the follow-ups.
3. **Resolution / FSR4 inputs** — `SetConfigVariable("rtx.resolutionScale", …)` at runtime; the cheap-game and
   FSR4 paths already exist.
4. **Latency** — pipelined publish costs one frame; decide against FSR FG's own latency budget.

## Open questions to settle before coding A2/A4

* Which constant-buffer slot and layout holds the game's light array (CB12 in the reference frame is the
  candidate: 128 bytes with position/falloff-shaped values per 32-byte row).
* Whether `ALPHA_BLEND_TO_CUTOUT` alone fixes foliage, making shader-level discard detection unnecessary.
* Whether `SMOOTH_NORMALS` is enough on NieR's low-poly meshes, or we need `smoothNormalsTextures` too.
