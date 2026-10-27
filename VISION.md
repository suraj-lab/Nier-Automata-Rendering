# Vision — a modern NieR:Automata, not a remaster

Written 2026-10-27, at the point where the live path stopped being a question of feasibility and became a build.
This file is the shared intent. [PROGRESS.md](PROGRESS.md) holds the evidence and the resume state;
[analysis/LIVE_TRANSFER.md](analysis/LIVE_TRANSFER.md) and [analysis/LIVE_IN_GAME_PLAN.md](analysis/LIVE_IN_GAME_PLAN.md)
hold the engineering.

## What we are building

Keep NieR:Automata exactly as it is — saves, gameplay, UI, content — and give it a **live modern rendering path**
layered on top:

- **RTX Remix path tracing, live, in the game window.** NieR's own geometry and textures, no asset replacement.
- **Ray tracing as the desktop default, path tracing as an option.** Full PT on an RX 9070 XT costs 21 fps at
  2580x1080 before upscaling; RT-only presets buy that back, and PT is the "look at this" mode.
- **Modern upscaling.** XeSS inside Remix (works on AMD, measured); FSR 4.1.1 at the game layer, already shipped.
- **Frame generation where the platform allows it** — see the per-platform split. `lsfg-vk` is explicitly excluded.
- **Lighting and LOD as quality goals**, not afterthoughts: they are what make the image look current.

The subjective test is simple: the game should look and run like a modern title, and an ordinary run with the
feature off should be byte-for-byte the game as it ships today.

## In scope

| Area | Intent |
|---|---|
| Geometry | Everything the game draws, live, from the game's own draw stream |
| Textures | The game's own, plus the installed WAX pack (already active) |
| Lighting | Sky/ambient solved within the C API's limits, emissive extraction from the game's shaders, sun + volumetrics |
| LOD | The installed LodMod is already in the pipeline; use it for LOD0 where it helps |
| Upscaling | XeSS in Remix, FSR4 at the game layer |
| Frame generation | Laptop: DL frame generation. Desktop: native FSR FG via a DX12 present takeover, or nothing |
| Presets | RT-only (default), path-traced (option), stock game (instant fallback) |

## Out of scope (deliberate)

- **Replacing assets.** No remaster art project, no retexturing, no new models. Materials stay "whatever the
  game's data gives us plus what we can extract" — secondary by decision, not by limitation.
- **UI and cutscenes.** The game's HUD stays the game's HUD. While a menu is open, present the game's own frame.
  Cutscenes and 2D segments are left alone.
- **Fixing NieR's design.** 60 fps cap stays; we are not re-tuning the game's logic, physics or AI.
- **A distributable mod, for now.** Everything here is local, hash-pinned and revertible. Redistribution of the
  closed proxy, the runtime or game content is a separate question with its own permission problems.

## The two builds, on purpose

### Desktop — "AMD optimised" (Arch, RX 9070 XT, RADV, GE-Proton)

The primary target, because it is the machine the game is installed and played on.

| | |
|---|---|
| Remix path | Copy-based transfer, in-process host, XeSS upscaling |
| Measured now | 21 fps native · 48 fps XeSS Quality · **60.65 fps XeSS Performance = NieR's own cap** (2580x1080) |
| Game layer | FSR 4.1.1, 2580x1080 → 3440x1440, already deployed and user-confirmed |
| Frame gen | Not lsfg-vk. Native FSR FG needs a DX12 swapchain; our proxy owns Present and already has colour/depth/motion vectors, so a DX12 present takeover is the route. Unbuilt. |
| Not available | DLSS, DLSS Ray Reconstruction (NGX is NVIDIA-only), FSR Ray Regeneration (needs ray-traced G-buffers Remix does not expose) |
| Noise | NRD initialises but has no effect for an API-only client; grain is handled by upscaling and, later, by better lighting/sampling |

### Laptop — "reference / best looking" (Windows on ARM, RTX Spark N1X)

Not the play target — x64 games run under emulation there — but the place where the maximum-quality stack exists
in one piece, and a native-NVIDIA control for anything we measure on the AMD box.

| | |
|---|---|
| Remix path | Same host design, native ARM64 runtime (1.6 added Windows-on-Arm artifacts) |
| Stack | DLSS + DLSS Ray Reconstruction + DL frame generation, all NGX |
| Role | Reference for the "best looking" variant, validation of the transfer against a second vendor, and the only host where frame gen is one integrated piece |
| Constraint | Fill it with facts first: `run_remote.py` already unloads local models so a render is not competing for unified memory |

## Next goals, in order

1. **In-game host, static scene.** `remix_live` module inside `d3d11.dll`, gated by `NIER_REMIX=1`: load the
   runtime, create the D3D9 device, register it *before* `Startup`, copy each frame, upload it, draw it as a
   fullscreen quad in the existing Present hook. Scene source is a converted F9 capture, camera static.
   *Acceptance:* the game window shows a path-traced NieR still instead of the game's frame, the game does not
   crash, and with `NIER_REMIX=0` behaviour is unchanged.
2. **Live draw stream.** Warm cache keyed by hash (mesh, material, texture), per-frame camera and per-instance
   transforms from the VS constant buffers we already capture. Submission is cheap (0.24 µs/draw measured), so this
   is bookkeeping, not performance work. *Acceptance:* the scene animates with the game, no cache thrash, no leaks
   over a 10-minute run.
3. **UI fallback.** Detect game menus and present the game's own frame while they are open. *Acceptance:* menus and
   the in-game menu mod both work, no flicker, no lost input.
4. **Quality pass, in parallel from now** (needs no game): sky and ambient within the C API's limits, emissive
   extraction from the game's pixel-shader constant buffers, `smoothNormalsTextures`, and the overdraw streaks that
   dominate the current stills.
5. **Desktop presets.** RT-only default, PT option, stock fallback — all through the existing settings machinery.
6. **Frame generation**, after 1–3: DX12 present takeover with the real FSR FG API, or consciously skip it on
   desktop and leave FG to the laptop.

## Success criteria

1. NieR runs with the game's own geometry and textures path-traced **live, in the game window**, at the 60 fps cap
   with upscaling at 1440p on the desktop.
2. The game's UI is intact, menus and cutscenes unaffected, input unchanged.
3. One flag switches back to stock rendering; rollback is one `cp` from the backup chain.
4. A 10-minute play session with no crash, no leak, no visual regression versus the stills we already accept.

## Risks we are accepting knowingly

- **Two Vulkan devices in the game's process.** Proven in a separate process (our bridge probe); unproven inside
  `NieRAutomata.exe`, where DXVK, LodMod, WAX and Remix all live. If it destabilises the game, the flag turns it off.
- **Per-frame CPU cost at real scale.** Measured at 180p and 1080p in isolation; three thousand draws inside the
  game with the engine's own cost on top is a different number.
- **The look.** Live rendering will inherit today's defects: no sky, no ambient, and streaks on thin geometry.
  Item 4 above is not optional polish — it is the difference between "modern" and "noisy".
- **Time.** Items 1–3 are days of work each, not hours; item 6 is the largest single piece.
