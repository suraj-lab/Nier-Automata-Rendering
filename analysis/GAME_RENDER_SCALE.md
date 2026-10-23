# NieR:Automata's built-in internal render scale — 2026-10-19

## Summary

The game engine already supports rendering the scene at a reduced internal
resolution while post-processing and HUD stay native. On PC the scale is fixed at
1.0, so the feature is dormant. This removes most of the "scene-domain scaling"
work identified in `SCENE_DOMAIN_INVENTORY.md`.

Static analysis only. No game launch, no patch applied, no runtime test.

## Binary and unpacking

The game's code is encrypted on disk by SteamStub DRM (Variant 3.1 x64; `.text`
entropy 8.0, zero normal prologues, entry in `.bind`). With the user's approval it
was unpacked **offline, on a workspace copy only**, using Steamless v3.1.0.5 from
the official GitHub release (zip SHA-256
`e3e2d22e098ff3fb359b2876aa2bed9596f0501e6ff588cbffae90a76d2dc4f5`), run under
wine-mono in a new private Proton prefix (`offline-unpack/`). The unpacked file is
for analysis only: it is never run, installed or shared.

| File | SHA-256 |
| --- | --- |
| installed / copied exe (`input/NieRAutomata_win10.exe`) | `5171bed09e6fec7b21bf0ea479dbd2e1b228695c67d1f0b478549a9be2f5726a` |
| unpacked (`input/NieRAutomata_win10.unpacked.exe`) | `44ee2dc0e1f2fd939ddb39f028edb4238ecac4e9c80daad3ce925d50545a28c2` |

Unpacked `.text`: entropy 6.51, 15,989 standard prologues, original entry
`0x1409d5a24`. The game is ASLR-enabled (`DllCharacteristics 0x8160`).

## The mechanism

All named render targets are created in one function, **`0x140773cd0`**, through
helpers `0x140248170` and `0x140248060` (also `0x140248270`). No width or height
is passed. Each helper reads the global renderer object at **`[0x14177f1a0]`**:

```
width  = renderer->+0x3c        ; screen width
height = renderer->+0x40        ; screen height
if (scaleFlag)                  ; per-target byte argument
    width  = (int)(width  * renderer->+0x80)    ; float internal scale
    height = (int)(height * renderer->+0x80)
```

- **Only write:** the renderer initialiser stores `1.0f` at `0x1402497bf`
  (`c7 80 80 00 00 00 00 00 80 3f` = `mov dword [rax+0x80], 0x3f800000`).
  **Correction (2026-10-23):** a setter `0x14024d2b0` exists, but its only callers
  are a retail-unreachable debug hotkey that writes 1.0. See `VIEWPORT_RESULTS.md`.
- **Other readers of the scale:** `0x14024a150` loops over registered targets
  (`0x14177f600`, count `0x14177f608`) and applies the scaled size, which looks like
  re-creation on resize. `0x1402f3e60` computes the scaled size and uses it in
  float maths, which looks like viewport or screen-size constant setup.

## Which targets scale (from the creator's arguments)

Confirmed by Ghidra decompilation of the creator
(`offline-gameexe/rt-creator-function.json`, Evidence
`ev_c73715f51361503014a9def6bcc038ddc2381514347af86b95a5dba0780b4188`, decoded in
`rt-creator-function.decoded.c`). `FUN_140248170(obj, 0, fmt, 0, …, name, scaleFlag)`
takes the flag as its last argument. `FUN_140248060(obj, width, height, …, name,
flagA, flagB)` takes explicit sizes, which the creator computes from the engine's
size getters:

```
getWidth(scaled)  (0x14024cf90) = scaled ? (int)(renderer->w * scale) : renderer->w
getHeight(scaled) (0x14024cfc0) = scaled ? (int)(renderer->h * scale) : renderer->h
```

The creator calls both with `scaled = 1` (9 times each), so the half- and
quarter-resolution targets (velocity, Hi-Z, AO half, DOF, bloom, volumetric light,
event DOF) follow the scale as well.

**Scaled (flag set, 40):** `g_TargetTexture_Origin[0..2]` (scene), velocity
`[0..1]`, `g_ZMapTexture_Origin` (linear depth), `g_HiZMapTexture`, `g_SaoTexture`
and `_Half[0..1]` (AO), `g_SSSSS_Texture[0..2]` (subsurface), shadow receive,
`g_CapturedTexture_Full` (scene copy), `g_SignTexture`, volumetric light scatter
and blur, DOF and event DOF, most of `g_BloomTexture[0..11]`, SMAA result, edge
and weight, screenshot capture.

**Always native (flag clear, 28):** `g_TargetTextureBackBufferIntermediate0..6`,
`g_TargetTextureFidelityFXCASSharpenResult`, UI render textures, fixed-size render
textures (256²/512²/1024²), Enlighten lighting textures, half-shadow map, shadow
cast and shadow sign, bullet, fluid, communication-screen textures.

This matches the in-game dumps: scene, depth, AO, velocity, scene copy and bloom
are in the scaled set; the tone-map/HUD targets are back-buffer intermediates.
The native CAS result also suggests the engine already reconstructs from render
resolution to native, possibly using AMD CAS's upscaling mode. Not yet confirmed.

## Open question: passes, not just targets

Only the creator requests the scaled size through the getters. Elsewhere they are
called with the native flag (9 functions) or with a runtime flag this scan cannot
resolve (34 calls). Target creation is therefore fully scale-aware, but it is not
yet proven that every scene pass takes its viewport and screen-size constants from
the scaled size (or from the bound target's own size) rather than the screen size.
In the dumps every scene viewport equals its target's size, which is consistent
with the target-size case, but at scale 1.0 the two are indistinguishable.

## Viewport and sampling evidence (2026-10-19; resolved in `VIEWPORT_RESULTS.md`)

Resolved 2026-10-23: scene viewports follow the bound target's size, `0x1402f3e60`
is AMD CasSetup, and mode 2 is never assigned on PC.

- The engine's viewport wrapper is `0x140255c50`:
  `SetViewport(this, x, y, width, height, minDepth, maxDepth)` →
  `context->RSSetViewports(1, …)`. It is slot 14 (byte offset `0x70`) of the engine
  context-wrapper vtable at `0x140db1788`. It has no direct callers; its callers and
  the sizes they pass are not yet traced.
- `0x1402f3e60` (decompiled: `offline-gameexe/scaled-reader-1402f3e60.decoded.c`,
  Evidence `ev_eb46d0f85bf490cb6933ab9e314542861e46c7e5413ccdede4abc1f9110f15be`)
  computes the scaled size, then writes a 0x20-byte constant buffer containing
  `scaled / reference` UV ratios and half-pixel offsets. The reference is the native
  size when `renderer->+0x00 == 2`, otherwise the scaled size (ratio 1). This is
  what native-resolution passes need to sample scaled targets correctly, gated by
  an engine mode value. Static inference; the mode's meaning is not yet traced.
- `0x14024a150` is decompiled (`scaled-reader-14024a150.decoded.c`, Evidence
  `ev_bb228f15bd4c3272d8cc476ab539c2df45371c72ea2fd4b66d6011f75d8f9a8a`) but not yet read.

## What this means

1. **Scene-domain scaling:** setting `renderer->+0x80` (e.g. 0.75) before render
   targets are created, or before a resize re-creation, should make the engine
   create every scene target at render resolution by itself.
2. **The AA mod** then sees a scene smaller than the camera size (swap-chain size)
   and skips AA (its size gate). Making FSR4 upscale needs the mod patch described
   in `FRAMEDUMP_RESULTS.md`: unequal NGX create, native output, and either the SRV
   redirect or the engine's own reconstruction path.
3. **Runtime patch location:** `module base + 0x177f1a0` holds the renderer
   pointer; the scale is at `+0x80`. A patch must check the expected code bytes
   first, e.g. `4c 8b 15 20 70 53 01` at RVA `0x248179` and
   `f3 41 0f 59 82 80 00 00 00` at RVA `0x2481b8`, and do nothing on mismatch.

## Next

- Confirm the flag table and the two readers with the Ghidra decompile.
- Trace who consumes the scaled viewport/constants (`0x1402f3e60`), and whether
  the native CAS result is the engine's upscale step.
- Then, with approval, an in-game experiment: set the scale at runtime with AA
  toggled off, re-apply the resolution in settings to force re-creation, and
  check image correctness and HUD sharpness.
