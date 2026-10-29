# Prior art: who has already solved parts of this

Researched 2026-10-29, offline (no game run, nothing installed). Read this before designing anything in
`analysis/LIVE_IN_GAME_PLAN.md` or `analysis/LIVE_SCENE_PLAN.md`.

Reference copies of the upstream documents and headers are in `analysis/reference/`; the API comparison we
generated from them is `analysis/reference/API_DIFF.md`.

## Sources

| Source | What it is | What we take |
| --- | --- | --- |
| [NVIDIAGameWorks/rtx-remix-minecraft](https://github.com/NVIDIAGameWorks/rtx-remix-minecraft) | NVIDIA's own Fabric mod: Minecraft 1.21.1 rendered by Remix. Captures terrain, entities, particles, sky and clouds and **submits them to the C API every frame** through a JNI bridge. | Same architecture as ours (non-D3D9 game, own geometry, live submission). Its docs are the missing ops manual: `docs/RENDERING_DIAGNOSTICS.md`, `tools/docs/BENCHMARKING.md`, `docs/TUNING.md`, `AGENTS.md`. |
| [xoxor4d/l4d2-rtx](https://github.com/xoxor4d/l4d2-rtx) | Left 4 Dead 2 made Remix-compatible. "How does a shader based game work with remix? By manually reimplementing fixed function rendering." | The closest *game* precedent (shader-based engine, no fixed function). Its known-issues list is our bug list: renderer forced single-threaded, alpha-tested foliage kills performance, CPU software skinning is a bottleneck, some effects wrong under fixed-function limits. |
| [xoxor4d/remix-comp-base](https://github.com/xoxor4d/remix-comp-base) | A starting codebase for RTX Remix compatibility mods: hooked D3D9 interface with every function detoured, drawcall-modification logic, ImGui debug menu. | Community conventions for tagging/culling draws and for a debug menu, if we need them. |
| [NVIDIAGameWorks/bridge-remix PR #12 "BridgeApi"](https://github.com/NVIDIAGameWorks/bridge-remix/pull/12) | x86 client/server wrapper so a 32-bit game can reach the 64-bit Remix API: the client forwards calls, the server assembles the real Remix API structs. | Our proxy-hosts-the-runtime architecture, already published and reviewed by NVIDIA. Nothing here is novel to us. |
| [Remix Plus](https://github.com/RemixProjGroup/dxvk-remix) — docs at [NightSightProductions/dxvk-remix-plus](https://github.com/NightSightProductions/dxvk-remix-plus/blob/main/docs/RemixApi.md) | Community fork of dxvk-remix with a written C API reference and API extensions. | The best C API documentation that exists, plus the extensions listed in `API_DIFF.md`. |
| [NVIDIA RTX Remix compatibility wiki](https://github.com/NVIDIAGameWorks/rtx-remix/wiki/Compatibility) | Official position: Remix targets DirectX 8/9 fixed-function games; "injecting the Remix runtime into other content is unlikely to work". | Confirms the proxy + C API route is *the* accepted workaround, not an untried hack. |
| [rtx-remix issue #814](https://github.com/NVIDIAGameWorks/rtx-remix/issues/814), [#1029](https://github.com/NVIDIAGameWorks/rtx-remix/issues/1029) | AMD driver timeouts and startup crashes with dxvk-remix. | The community's AMD baseline is worse than ours: we already run live on a 9070 XT under Proton. Treat AMD-specific crashes as expected class of failure, not as our bug alone. |

## Verified facts (from the files in `analysis/reference/`)

1. Our vendored `analysis/remix-probe/vendor/remix_c.h` is version **0.6.6**, the same version as upstream
   `dxvk-remix` `main` today. Nothing in the upstream API has moved since we vendored it.
2. Upstream 0.6.6 already has, and we already compile against:
   * `remixapi_StartupInfo.combineGuiInFinalColor` — false + `dxvk_CopyRenderingOutput(GUI)` separates **Remix's
     own dev GUI** (its settings overlay), not the game's HUD. Correction: it is not the HUD/menu-separation
     hook; the game's HUD is 58 sprite draws into the game's own 3440x1440 target and has to be composited by us
     (`analysis/PLAYABILITY_PLAN.md` A6).
   * `dxvk_CopyRenderingOutput(IDirect3DSurface9*, {FINAL_COLOR, DEPTH, NORMALS, OBJECT_PICKING, GUI})` — a
     GPU-side blit of the runtime's own outputs into a D3D9 surface we own. No CPU roundtrip.
   * `dxvk_GetExternalSwapchain(VkImage, semaphores)` with `forceNoVkSwapchain` — the documented way for a
     non-D3D9 host to present the Remix image without a readback (the Minecraft/OpenGL-interop path).
   * `SetConfigVariable(key, value)` — set any `rtx.*` option at runtime, no conf file edit and no relaunch.
   * `MaterialInfoOpaqueEXT`: `alphaTestType`, `alphaReferenceValue`, `useDrawCallAlphaState`,
     `blendType_value`, `invertedBlend`; `MaterialInfo.emissiveTexture`, `emissiveIntensity`,
     `emissiveColorConstant`; `MaterialInfoOpaqueSubsurfaceEXT` (foliage/skin single scattering);
     `InstanceInfoBlendEXT` (`alphaTestEnabled`, `alphaTestReferenceValue`, `alphaTestCompareOp`);
     `InstanceInfo.categoryFlags` (`InstanceCategoryBit`).
3. Remix Plus (same layout as its runtime, version 0.1000.0) **adds** `dxvk_GetSharedD3D11TextureHandle`
   (NT shared handle + dimensions of the final-colour target), `CreateTexture`/`DestroyTexture` from
   memory, `CreateMeshBatched`/`CreateLightBatched`, `AutoInstancePersistentLights`, `RegisterCallbacks`,
   `GetVramStats`/`RequestVramCompaction`, `DrawScreenOverlay`, `GetUIState`/`SetUIState`.
4. Remix Plus is a fork of an **older** upstream: its `MaterialInfoOpaqueEXT` lacks `enableDlssControlMask`
   and the texture-scroll fields, `StartupInfo` lacks `combineGuiInFinalColor`, `LightInfo` adds
   `isDynamic`/`ignoreViewModel`. So the two are not ABI-compatible in either direction: switching runtimes
   means switching headers and losing the newer upstream fields (notably `combineGuiInFinalColor`).
5. Minecraft's diagnostics doc records a failure signature we do not detect: `DrawInstance` "can return
   success while the runtime drops them for lack of a free surface slot"; draw counters report calls made,
   not surfaces accepted. Our `dropped=` counter only measures our own upload queue.
6. Upstream `dxvk-remix` merged "Implement preserving instances across frames for static draw calls"
   (branch `drawcall2`, 2026-06) — retained static instances on the runtime side.

## Adoption plan

### A. Offline, no runtime change (use the 0.6.6 API we already have)

1. **Materials from captured state instead of a guess.** Cutout per draw via the frozen DXBC-discard gate
   (`analysis/checks/test_dxbc_discard.py`) keyed on the pixel-shader hash, carried through
   `live_capture` → `Upload` → `make_material_info`. Today the live path passes `cutout=false` always, which
   is why foliage is solid.
2. **Emissive from the game's pixel-shader constant buffers** (`emissiveIntensity`, `emissiveColorConstant`)
   — VISION goal 4, needs no game.
3. **`MaterialInfoOpaqueSubsurfaceEXT` for foliage and skin**, with `rtx.subsurface.enableThinOpaque` set via
   `SetConfigVariable` (see `analysis/reference/remix-plus-FoliageSystem.md` for the parameters). Expect it
   to be expensive in Remix itself (L4D2's known issue says alpha-tested foliage kills performance).
4. **`InstanceCategoryBit` flags we never set** — `SKY`, `PARTICLE`, `DECAL_*`, `ALPHA_BLEND_TO_CUTOUT`,
   `SMOOTH_NORMALS`, `HAIR_CARDS`, `IGNORE_ALPHA_CHANNEL`, `VIEW_MODEL`: all present in 0.6.6, all unused. These
   are the cheapest correctness wins available (see `analysis/PLAYABILITY_PLAN.md`, stage A).
5. **Runtime knobs without relaunch**: move `rtx.resolutionScale`, `rtx.subsurface.enableThinOpaque` etc.
   from `rtx.conf` edits to `SetConfigVariable`.
6. **Add the surface-slot drop counter** (Minecraft's signature) next to our own `dropped=`, and read
   `log.txt` from the runtime for its own drop reports.

### B. The readback fix (163 ms of a 190 ms frame — see `PROGRESS.md`)

Two routes, mutually exclusive because of point 4 above:

* **B1, stay on upstream 0.6.6**: `dxvk_CopyRenderingOutput` into a D3D9 surface we own, then a pipelined
  publish (ring of two surfaces; publish frame N-1 while N renders) plus a GPU-side colour conversion instead
  of the per-pixel CPU swizzle. Small diff, keeps `combineGuiInFinalColor`, no runtime swap. Removes the
  `GetRenderTargetData` stall and the CPU cost, adds one frame of latency.
* **B2, Remix Plus**: `dxvk_GetSharedD3D11TextureHandle` → `OpenSharedResource1` on the game's D3D11 device →
  `CopyResource`. Zero CPU involvement, no extra latency. Costs: a runtime swap, an older API base (lose
  `combineGuiInFinalColor`, `enableDlssControlMask`, texture-scroll fields), and a community fork on AMD
  Linux, where the community itself reports crashes. Our FSR4 bridge already proves D3D11↔D3D12 shared NT
  handles work under GE-Proton, so the mechanism is known to this project.

Recommendation: **B1 first** (it is a strict subset of the work and validated by the existing fake-runtime
gate); evaluate B2 only if B1's pipelined publish still leaves the copy visible in `ms/frame`.

### C. Not adoptable offline

* Anything that needs the fork's runtime (B2, `CreateTexture` from memory, batched submission, persistent
  instances) needs an install and a live run.
* L4D2's lesson — one render thread, CPU skinning — is an architecture warning, not code to copy.
