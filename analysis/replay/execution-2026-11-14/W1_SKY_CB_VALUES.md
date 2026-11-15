# W1.2 — per-layer sky constant-buffer values from real captures (offline, 2026-11-15)

Reads the sky draws of three packed captures out of their own `scene.cbs` blob, using the names, offsets and bind
slots in the shader's DXBC `RDEF` chunk. No game run, no GPU, no deployment; nothing outside this repository is
written (the camp capture's shader directory under `/mnt/second/...` is only read).

Tool: `analysis/checks/sky_cb_dump.py` (SHA-256 `75c26f0e…`). Gate: `analysis/checks/test_sky_cb_dump.py`
(SHA-256 `1090c949…`, frozen v4). Evidence: `analysis/runtime/sky-cb-dump-gate/{camp,desert,pond}.{json,txt}`.

## How the numbers are known to be the right ones

- Draws are selected by **content**, not by the game's shader id: `FNV-1a 64(ps blob) == 0x33856d1d3ba64bb3`, the code
  the live proxy prints (the id differs per capture: `550292875656` on the laptop captures, `1842243472` on the
  desktop camp). The gate checks the blob that matched.
- The sky PS declares **`PSParamBuffer1` twice** — 64 bytes at bind 1 and 128 bytes at bind 2 — while captures bind
  112 bytes at slot 1 and 128 at slot 2. The tool assigns exact size matches first (128 → slot 2), then the remaining
  declaration only if exactly one unclaimed bind can hold it (64 → slot 1), and refuses two equal claims instead of
  guessing. On the desktop camp capture, a *non-sky* draw binds exactly 128 bytes at pcb1, which is what makes a
  capture-wide "widest binding" rule wrong; the gate reproduces that case (`camp-trap.manifest`).
- The register indices the gate pins (`g_IntensityParam` b1[1], `g_FogParam` b2[2], `g_SpParam` b2[4],
  `g_FogColor` b2[7], `g_UvOffset` b3[1], `g_ShadowParam` b3[2], `g_MeshColor` b4[0], `g_CameraVec` b13[1]) are the
  ones the 2026-11-15 disassembly of the same shader uses.
- `check_raw_bytes` recomputes `g_FogColor` and `g_IntensityParam.y` from the blob with `struct` alone, so the tool
  is not its own oracle.
- Mutations that the gate turns red: slot by table order, value read without the draw's blob offset, LUT always
  reported as a cube, no default shader code, silent unbound member, ambiguous resolution guessed.

## Per-layer values (one frame per area)

`t0` is the layer's own texture, `t12` the fog LUT, `int` = `g_IntensityParam.y`, `alb` = `g_AlbedoParam.rgb`
(replaces `t0` when `.w > 0`), `bb.w` = `g_BaseBoolParam.w` (1 = fog skipped), state = the capture's draw state
(blend enable, src blend, …, depth func).

| area | viewport | sky draws | layer (draw) | indices | state | bb.w | alb | int | t0 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pond `frame_67078468` | 2880x1800 | 4 / 1176 | 812 | 900 | opaque, no depth write, EQUAL | 1 | `(0,0,0)` | 1 | 256² BC1, 9 mips |
| | | | 857 | 690 | same | 0 | `(0.5,0.5,0.5)` | 6 | 2048² BC1, 12 mips |
| | | | 887 | 690 | same | 0 | `(0.5,0.5,0.5)` | 6 | 2048² BC1, 12 mips |
| | | | 1133 | 1044 | blended, depth write, LESS_EQUAL | 0 | `(0.5,0.5,0.5)` | 1 | 512² BC1, 10 mips |
| desert `frame_67279062` | 2880x1800 | 4 / 923 | 750 | 900 | opaque, EQUAL | 1 | `(0,0,0)` | 1 | 256² BC1, 9 mips |
| | | | 811 | 690 | same | 0 | `(0.5,0.5,0.5)` | 6 | 2048² BC1, 12 mips |
| | | | 827 | 690 | same | 0 | `(0.5,0.5,0.5)` | 6 | 2048² BC1, 12 mips |
| | | | 901 | 1044 | blended, depth write | 0 | `(0.5,0.5,0.5)` | 1 | 512² BC1, 10 mips |
| camp `frame_30632051` | 2580x1080 | 22 / 3382 | 2335 | 900 | opaque, EQUAL | 1 | `(0,0,0)` | 1 | 256² BC1, 1 mip |
| | | | 2446, 2513 | 690 | same | 0 | `(0.5,0.5,0.5)` | 6 | 2048² BC2, 1 mip |
| | | | 2661–2665 | 1080/144/432/288/144 | same | 0 | `(1.0,0.713,0.55)` | 5 | 256² BC1 (tint carried in albedo) |
| | | | 2666, 2667, 2699 | 441/165/471 | same | 0 | `(0.5,0.5,0.5)` | 10 | 2048² BC2 |
| | | | 2933 | 507 | same | 1 | `(0,0,0)` | 1 | 256² BC1 |
| | | | 3321–3330 | 216…1044 | blended, depth write | 0 | `(0.5,0.5,0.5)` | 1 | 512² / 2048² BC2 |

Per area, shared by every sky layer (all four/twenty-two agree):

| area | `g_FogColor.rgb` | `g_FogParam` (x, y, z, w) | `g_SpParam` | `g_lightColor` | `g_lightVec` | `g_MeshColor` | `g_UvOffset` | t12 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pond | 5.75294 grey | (0, 0.00192264, 1.47122, 5.75294) | (1,0,0,1) | (10, 9, 7, 10) | (-0.429, 0.839, -0.335) | (1,1,1) | (0,0,0,0) | tex_37 32² DXGI 87 |
| desert | 2.93726 grey | (0, 0.00117108, 0.882826, 2.93726) | (1,0,0,1) | (8, 7.2, 4.8, 8) | (0.150, 0.5, -0.853) | (1,1,1) | (0,0,0,0) | tex_37 32² DXGI 87 |
| camp | 6.2078 grey | (0, 4.78393e-05, 0.723137, 6.2078) | (1,0,0,1) | (6, 5.1, 4.8, 6) | (-0.429, 0.839, -0.335) | (1,1,1) | (0,0,0,0) | tex_94 32² DXGI 87 |

**Supersedes `PLAN_2026-11-13.md` L9** ("`PSParamBuffer1` … identical in every capture that has it: sun
(6.0, 5.1, 4.8), fog colour white 6.208, fog params (0, 0, 0.723, 6.208)"). Those are the *camp* values printed to
three significant digits (the real camp `g_FogParam.y` is 4.78393e-05, not 0). Desert and pond differ in fog colour,
fog scale, exponent and sun colour, so that note must not be used as a constant. The earlier "sky illumination is a
constant" reading is withdrawn; the plan item is recorded here rather than rewritten, as earlier plans are evidence.

## What the shader does with those numbers (from `runtime/w1-disasm/sky_ps.asm`)

```
base  = (g_AlbedoParam.w > 0 ? g_AlbedoParam.rgb : t0(uv + g_UvOffset)) * g_IntensityParam.y
base *= saturate(t17(screen uv) + g_ShadowParam.z)                 // AO / shadow mask
base *= g_MeshColor.rgb                                            // = 1 here, no tint
if g_BaseBoolParam.w == 0:                                         // layer 0 skips fog
    dir  = normalize(g_CameraVec.xyz - worldPos);  dist = |…|
    f    = exp(log(saturate((dist - g_FogParam.x) * g_FogParam.y)) * g_FogParam.z)
    fog  = lerp(t19(-dir), t12(-dir), g_SpParam.w) * g_FogColor.rgb   // SpParam.w = 1 everywhere
    out  = lerp(base, fog, f * fog.alpha)
out.a = t0.alpha                                                   // unchanged by albedo/intensity/AO
```

With the numbers above: `1 / g_FogParam.y` is 520 world units at the pond and 854 in the desert, so any dome vertex
(extent 8.3k–19k per the W1.1 census) saturates `f` to 1 — those skies are **entirely** the fog LUT colour and their
2048² cloud textures do not reach the screen. Camp is the exception: `1 / g_FogParam.y` = 20,900 units, so a dome of
radius ≈ 9,000 gives `f ≈ 0.53` — about half the visible sky is the dome texture times its per-layer intensity there.

## Two capture blind spots this dump exposed (both bounded, both offline to fix)

1. **Cube textures are stored as one face.** The sky shader declares `g_FogLUT` (t12) and `g_BeforeFogLUT` (t19) as
   `texturecube`, and 4348 shaders sample the fog LUT. `checks/texture_capture.h::write_dds` writes
   `TEXTURE2D`/`arraySize 1` unconditionally, and **none of the 373 textures in the pond capture has `arraySize > 1`
   or the cube flag**. The stored 32×32 DXGI-87 face is a smooth ramp (grey 50→138 with alpha 208→247 at the pond,
   warm 138→78 in the desert, dark 61→139 at camp), but the +Y face the sky actually samples is not in our data. So
   the sky's *angular* colour cannot be reconstructed from today's captures, and a baked radiance would bake this
   blind spot in.
2. **PS resource slots 16–127 are never captured.** `checks/texture_capture.h::capture` enumerates
   `PSGetShaderResources(0, 16, views)`; `t17` (`g_AO_Texture`) and `t19` (`g_BeforeFogLUT`) are outside that range.
   Every manifest therefore says "not bound" for slot 17/19 whether or not the game binds them, which is why this
   dump reports them as absent and why the AO term cannot be evaluated. The `g_ShadowParam.z = 0` in all three areas
   means the AO mask is the only thing that can keep the base term alive; with the mask unknown, the base term is
   unknown for pond/desert and known-looking only by the f≈0.53 arithmetic at camp.

Independent check that the sky is *not* cloudy where it dominates: stills from the laptop desert recording
(`runtime/sky-cb-dump-gate/video/frame-30.jpg`, `frame-55.jpg`) show a smooth dark-to-hazy gradient, no cloud detail —
consistent with pond/desert being the LUT colour, and consistent with cloud layers not reaching the screen there.

## Decision for W1.3 (smallest supported path)

1. **Do not bake a lat-long radiance now.** The projection is mesh UV + `g_UvOffset`, not a lat-long map, and the two
   multiplicative inputs that decide the residual (AO mask, before-fog LUT) are not in our captures, nor is the cube
   face the fog LUT is sampled from. A bake would encode the blind spot as the answer.
2. **Make the inputs visible first** — two small, switchable changes, each with its own gate, both needing one fresh
   F9 capture (a live run: user approval) to show the new data:
   - `texture_capture.h::capture`: enumerate the slots the shaders actually use (0–31) instead of 0–15; keep the byte
     budget and the dynamic/RTV filter, and measure the added per-frame cost before enabling by default.
   - `write_dds`: write a cube SRV as 6 faces with `resourceDimension = TEXTURECUBE`, `arraySize = 6` and the cube flag, instead of forcing `TEXTURE2D`/1; `read_dds`/`pack_capture` need the matching read-back.
3. **Meanwhile, the measurable W1.3 step is the camp-like case, not the fog case:** submit the existing SKY dome
   layers with the per-layer pieces we do have — `g_IntensityParam.y` folded into the material's base-colour factor,
   the `g_AlbedoParam` override as a constant colour when `.w > 0`, and `g_MeshColor` (identity here) — and gate it at
   W1.4 as "sky not flat, no regression at camp/desert/pond crops", not as an absolute colour match. Pond and desert
   show that the fog colour dominates there, so a Remix sky that reproduces the dome texture but not the game's fog
   will look wrong in exactly those two areas; that is a known, measured limitation to state with the artefacts.

## Acceptance / limits

- Offline only. No live run, no DLL install, no package or system change; the desktop game folder was read only.
- One frame per area; the camp capture has 22 sky-PS draws against 4 on the laptop captures, and the W1.1 census
  counted 7 *builds* over a 60-frame replay. The layer roles above are per-frame values, not a claim that the set is
  identical across frames of an area.
- Float members only: every name dumped is a `float4` in this shader (the disassembly does all of its arithmetic on
  them). Integer or array members are not decoded and would need a type-aware reader.
- Exact per-vertex distances need the vertex shader (absent from captures); the fog factors above use the census
  extents as the dome diameter, so `f` is a range, not a measurement.
- Camp's shader directory lives outside the repository (`/mnt/second/...`); the gate therefore uses only the two
  laptop captures, and camp numbers here are evidence, not a gate.

## Status block
```
Status: done (W1.2 offline; W1.3 not started — its first two steps need a fresh live F9 capture)
Owner: lead session; changed files: checks/sky_cb_dump.py (new), checks/test_sky_cb_dump.py (new),
  replay/execution-2026-11-14/W1_SKY_CB_VALUES.md (new), PLAN_2026-11-14.md (W1 row + Handoff)
Gate: python3 checks/test_sky_cb_dump.py, frozen v4 sha256 1090c949f1975ca402f38d02f2a43e881f76652ced99b5d1db99168c2bb7b05d;
  v1 0c6a8362 (red: "sky_cb_dump.py missing"), v2 2c2d5805/ea024e8f (red: fog LUT assumed to be a cube),
  v3 072e35c7 (red: "draw 0: g_FogColor at 112+16 outside pcb1" — the camp ambiguity), v4 extended for the reviewer's
  P1/P2 items and red on manifest strictness ("IndexError" instead of a message) before the fix; green after.
  Mutations (runtime/sky-cb-dump-gate/mutation-tool.py.orig is the unmutated copy, hash-verified restored): slot by
  table order, no blob offset, always-cube, no default code, silent unbound member, guessed ambiguity — all red.
Review: reviewer anthropic/claude-haiku-5-5, read-only, verdict BLOCK; P1-1 (camp-trap/resolve) fixed with a
  two-pass resolution, a direct resolve() test and an ambiguity refusal; P1-2 (claim wording) fixed — the receipt now
  separates measured per-layer inputs from the AO/before-fog terms the capture does not hold; P1-3 (PLAN_2026-11-13
  "identical in every capture") fixed by recording the supersession above. P2s taken: strict manifest parsing
  (fields, duplicate slots, lines after end), clear messages without tracebacks, member-outside-buffer and
  "slot not bound" errors, independent raw-byte oracle, second capture, texture/header distinctions, and a missing-file vs
  unreadable-header distinction. P3s not taken and why: register component suffixes (the disassembly notation is b<slot>[<reg>] and the
  gate pins that), integer/array member decoding (no such member among the dumped names; noted as a limit),
  absolute fixture paths (the suite runs from analysis/ on this checkout).
Validation: suite s91 128/128 (runtime/suite-w12-s1, -j 14, 271.7 s, test_live_visibility and test_live_normal_map
  passed in-lane this run). Captures: runtime/a1-intake-20261114/frame_67078468 (pond) and frame_67279062 (desert),
  manifests pinned by their own sha256 in the JSON evidence; camp read from runtime/replay/w1-sky-census-camp and
  /mnt/second/.../NIER_CAPTURE (read-only, outside the repo). No GPU was used; nothing was installed.
Measurements: per-layer values in the tables above; no fps/visual numbers claimed (offline dump only).
Limitations: one frame per area; cube faces and slots 16-127 absent from every capture; per-vertex distances not
  computed (fog factors are bounds from the census extents); camp not gated (its shader dir is outside the repo).
Next ready substep: W1.3 step 1 (dome layers with intensity/albedo folded in, gated by crops) — offline-capable;
  the capture fixes it depends on need one fresh live F9 capture and are listed under Handoff "Waiting on the user".
```
