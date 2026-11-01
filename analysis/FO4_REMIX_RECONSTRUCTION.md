# FO4-Remix: complete integration map and transfer assessment

Research date: 2026-10-31. Scope: offline reconstruction of the plugin's rendering integration, all first-party modules, its public release boundaries, and the custom Remix API it requires. **No game, DLL, installer, or hook was executed or installed.**

This is a static architecture/data-flow reconstruction, not a claim that every function in the shipped DLL or its 239 MB runtime has been decompiled, or that their behavior has been reproduced in Fallout 4. Important binary checks and remaining uncertainties are separated below.

## 1. Findings that change our approach

1. **This is not a generic D3D11-to-Remix translator.** Engine events and CPU-side engine objects provide a persistent scene. D3D11 draws supply missing precombined geometry, visibility evidence, and HUD pixels.
2. **Cached mesh and present scene instance are different lifetimes.** A successfully submitted object remains in FO4's drawable map and is considered for `DrawInstance` on subsequent Remix frames, even without a new engine capture event. Our bridge instead draws only `frame.items` from the current capture (`analysis/checks/live_scene.h:300–325`). Zero mesh evictions therefore does not imply a persistent world.
3. **View-dependent captures must not replace a complete static assembly.** FO4 accumulates observed precombined chunks across frames. Its draw-capture code specifically documents holes when replacing the chunk set with the current visible subset (`draw_capture.cpp:266–269`). Retention still needs reload/reset and ownership rules; this is not permission to keep every NieR draw forever.
4. **A near-camera keep sphere and hysteresis protect visibility.** Beyond that sphere, FO4 combines conservative frustum tests with an age-delayed engine draw-recency signal. A never-observed visibility key is exempt rather than presumed invisible (`remix_renderer.cpp:2795–2864`).
5. **FO4 presents Remix directly in a visible second window.** It does not copy the path-traced frame back through the CPU into the game's swapchain. The image crossing the CPU boundary is principally the game's HUD in the opposite direction. This is a major architectural difference from our current full-frame PT readback, not a ready-made shared-texture implementation.
6. **The integration depends on a private ABI.** Its API is `0.1000.0`, not the stock `0.6.x` line. Upload-from-memory, batched creates, geometry refresh, and screen overlays cannot be copied into our upstream 1.6.1 bridge by changing function names.
7. **Our per-actor skinning fix is independently corroborated.** FO4 explicitly keys skinned mesh handles by drawable because the runtime skins the mesh's shared BLAS. Per-instance bone arrays alone do not make mesh sharing safe (`remix_renderer.cpp:1478–1486`).
8. **Its source is explicitly all-rights-reserved.** Read and reconstruct the design, but do not transplant implementation code without permission. The fork runtime has its own license; that does not license the plugin.

None of these findings proves which stage currently removes NieR's floor/wall.

## 2. Exact versions: source, release, and runtime are not interchangeable

| Artifact | Identity / result |
|---|---|
| Plugin default source | `Kim2091/FO4-Remix` at `cb23b9e44a69896f4fa5e6143d83a798e7efd402` |
| Public release | `v0.0.5`, published 2026-07-23 |
| Release tag source | `901e211af75ac618e62d23601201de0da71591d2` |
| Relationship | Default source is **19 commits ahead** of the release tag; release behavior must not be inferred wholesale from default source |
| Release archive | `Fallout_4_RTX_v0.0.5.7z`, 187,331,627 bytes; SHA-256 `e5911fcf70fd7efbc3cadf8c8d55cf60f83ab8a384c434e85c6b50aa5736f2b3` |
| Released plugin DLL | 808,448 bytes; SHA-256 `bc2ac3460882661b20f4577d4913a6c010f32c9b1ece6d8a3299b84028a1f707` |
| Default source's cached API header | SHA-256 `7d2c6c323ec1a4a8d359028db537a2b2aa5471819b460a7fb904a5c7c5a49d0c` |
| Matching public fork header | `Kim2091/dxvk-remix`, `fo4-numos3-main`, commit `05c52a14a312fc3e0b0d088e7297ed75be14bd46`: **byte-identical header** |
| Release tag's cached API header | SHA-256 `82675bedff87e09e80b6cac0fa6dc6ada49a4e8b6b32d3c66ce0c7c4eefab978` |
| Matching release-line fork header | `Kim2091/dxvk-remix`, `fo4-workstream`, commit `aff568efd933858154ce14faa82911f32ecccdea`: **byte-identical header** |

Matching headers establish an ABI/source relationship, **not** reproducible-build equivalence to the bundled runtime DLL. **Both pinned fork headers declare `0.1000.0`, yet `VIEW_MODEL` moves from bit 25 in the release header to bit 26 in the newer header, bit 25 becomes `HAIR_CARDS`, and `StartupInfo` gains `combineGuiInFinalColor`.** A version-number check alone therefore does not establish compatibility between these two source lines. Keep exact headers, category values, structs and runtime builds paired.

The archive contains a different INI from the release-tag source sample; the selected shipped INI is retained separately. Source defaults, sample settings, and deployed release settings are distinct evidence.

The official NVIDIA `remix-1.6.1` source tag declares API **0.6.5**. Our project's vendored probe header declares **0.6.6**. Earlier notes calling both 0.6.6 were imprecise. Both remain the stock minor-6 line, unlike this fork's reserved minor 1000.

Pinned sources, trees, released binary, INI, release metadata, and raw REA dossiers live under:

`analysis/runtime/prior-art-deep-20261031/fo4/`

Reviewable hashes, complete module inventory, source/header relationships, release artifact identities, and REA evidence IDs are retained in [the evidence manifest](evidence/fo4-remix/2026-10-31/manifest.json). Runtime downloads are gitignored; no third-party implementation has been copied into our bridge.

### Binary corroboration, not source-only inference

REA 6.4.0 / Ghidra 12.1.2 analyzed the actual released plugin, without loading it into a target process:

| Shipped entry | Result | Evidence ID |
|---|---|---|
| `F4SEPlugin_Load`, `0x180002ae0` | Config/environment setup; messaging-interface gate before irreversible installs; exception handler, semantic hook installation, F4SE message listener | `ev_c5826ec7ef1e3a7f02ad30eb70691395b319cb6f896470912659507428fedfc6` |
| Message callback, `0x1800026b0` | PreLoad/NewGame reset paths, PostLoad gate release, input/game readiness event handling | `ev_0c9a11625d55d52f571a728c691262c926cc49dfb8ec0ad73d70e7b1280b1a58` |
| Semantic installer, `0x180043f90` | Config gate, `Fallout4.exe` lookup, detour setup and diagnostic paths | `ev_bde9bc6a0dc894d3a2cda371cb45db05f2c87ae92c6e4b8da19050dee95c164c` |

Decompiler-generated C types are not authoritative ABI declarations: for example it misidentifies the F4SE interface as a CRT `FILE` pointer and introduces apparent extra parameters. Use the source ABI and actual call instructions, not that guessed signature. These three dossiers do not verify the entire release's renderer or reproduce gameplay.

## 3. Build and startup contract

`CMakeLists.txt`, `build.bat`, `main.cpp:20–179`, `f4se_compat.h`, `remix_api.cpp:20–181`.

- Windows/MSVC x64 F4SE plugin; CMake links the minimal F4SE support, MinHook, zlib, D3D11/DXGI, D3D9 and Win32 support. A sibling F4SE SDK is required. This is not a standalone D3D11 proxy DLL.
- Source advertises runtime layouts/version families including 1.10.163, 1.10.980, and 1.11.191. The public release specifically targets Steam Fallout 4 **1.11.191**. Advertised compatibility is not proof every hook works on every listed build.
- CMake can replace the cached API header with a sibling checkout. It explicitly checks for fork features (`VIEW_MODEL` category and geometry-refresh extension) before accepting that header (`CMakeLists.txt:45–85`). A reproducible build must pin which header was actually used.
- F4SE load obtains the messaging interface **before** installing process-global callbacks. Returning failure after installing callbacks would let F4SE unload the DLL while callbacks still point into it.
- `GetRenderPasses` hooks can be installed early. The DXGI Present hook is retried on appropriate F4SE messages and the Remix worker is started lazily at the first game Present.
- `GameDataReady` uses the message's **data value**, not merely receipt of the message. A false readiness dispatch closes the extraction gate.
- `RemixAPI::Initialize` loads local `d3d9.dll`, creates a visible Remix HWND, prefers `dxvk_CreateD3D9` + `CreateDeviceEx` + `dxvk_RegisterD3D9Device`, with a `Startup` fallback.
- `D3DCREATE_MULTITHREADED` is deliberately set. Its exact protective effect depends on that fork's D3D9 device locks; do not assume a DLL built with another runtime has the same synchronization.

### Thread ownership

```text
Engine / game render thread
  shader-property GetRenderPasses -> observe objects / live transforms
  D3D11 draw hooks                -> merge slices / visibility recency
  DXGI Present                   -> camera, resolve work, readback polling,
                                    texture/mesh staging, HUD capture
                                      | mutex/owned queues/atomics
                                      v
Texture + geometry workers       -> CPU decode / archive reads / conversions
                                      | owned results
                                      v
Dedicated Remix thread           -> window messages, camera setup,
                                    live poses, visibility, DrawInstance,
                                    light draws, HUD overlay, Remix Present
```

Unlike our worker-only API design, some FO4 resource creates originate from the game thread. Its batched-create API and destruction deferral address hazards specific to that threading arrangement. We should preserve our existing API ownership rather than introduce its cross-thread calls just to copy its fixes.

## 4. Object identity and lifecycle

`semantic_capture.cpp:49–80, 1370–1545, 2266–2587, 2679+`; `semantic_capture.h`; `remix_renderer.cpp:350–630, 1000–1660`.

1. An engine shader-property event observes `(geometry pointer, property pointer, material pointer)` and hashes that tuple to `PassKey`.
2. The map stores raw engine object pointers, parents/flags, transform and recency, resolver state, material/geometry identities, and refresh requirements. This is a **semantic object map**, not simply this frame's draw list.
3. Game Present's `SemanticCapture::Tick` checks readiness/load/memory gates and resolves pending entries within configured budgets. Pending data is retryable; a successful submission is not repeated as ordinary first-sight work every frame.
4. Geometry/material/texture extraction produces owned data. Renderer submission creates or reuses resources, then installs a persistent `DrawableInstance`.
5. Every Remix `OnFrame` revisits that instance map. Updated transforms, skeletons and visibility determine whether it is submitted that frame.
6. Retry/backoff, pressure parking, long-age eviction, and explicit world resets are separate transitions. An object's existence in a cache does not mean it was drawn.
7. A refresh may resolve replacement geometry/material resources while retaining the old instance until a successful swap. Do not tear down a usable object just because its replacement is pending.

### Keys must represent the correct lifetime

- Static geometry can share a content/material-keyed mesh handle with identical instances.
- Material hash includes texture references, relevant constants/alpha/water/two-sided variants. Mesh identity incorporates material identity because surfaces bind materials.
- Skinned mesh identity is **per drawable**, not shared solely by NIF/content hash (`remix_renderer.cpp:1478–1486`). This is the same underlying BLAS-state issue already fixed in our bridge.
- Pointer-based identity requires validation/reset. Long TTL is not protection against recycled engine addresses.
- Deferred destroys are cancellable. If a hash-valued handle is recreated before its parked destroy drains, the stale destroy must be removed or it can destroy the new registration.

## 5. Geometry reconstruction, including the difficult cases

### Ordinary shapes, terrain and dynamic vertices

`bs_extraction.cpp:3340–3897, 4081–4245`; `lighting_static.cpp:1711–2300`.

- Ordinary geometry comes from supported `BSTriShape` engine representations and CPU-side VB/IB data, not a universal GPU buffer interception scheme.
- Snapshot engine-owned bytes before worker-side decoding. Validate descriptor/stride/attribute offsets, vertex and index bounds, finite data, and supported object/format kinds.
- Dynamic FaceGen geometry needs its dynamic position stream rather than assuming the static buffer has the same record layout. The detailed `scripts/dynamic_trishape_desc.md` documents the reverse-engineering history; current parser branches, not that history alone, determine behavior.
- Terrain observation walks loaded LAND quadrant nodes. Terrain materials remain an approximation: choosing a representative layer is not equivalent to Bethesda's multi-layer terrain shader.
- Bethesda-to-Remix coordinate conversion reflects the X/Y convention. The parser swaps triangle corners to compensate winding (`bs_extraction.cpp:3647–3678`). Copying the transform without the winding adjustment can remove single-sided shells.
- **Correction to an initial worker report:** `TryResolveStatic` also supports skinned shapes when `Skinning.Enabled` is true (`lighting_static.cpp:1740–1783, 2211+`). Its historical name does not imply static-only behavior. Water's separate resolver does reject skinned geometry.
- Unsupported non-triangle/effect geometry does not become supported merely because it passes through a lighting property. Full particles, grass/effects, shader deformation and all material permutations are not established by this integration.

### Precombined buildings and merged instances

`draw_capture.h`, `draw_capture.cpp`; `lighting_static.cpp:30–320, 640–800, 1900–2150, 3450+`.

This subsystem is particularly relevant to understanding disappearing structural geometry:

- Engine-side merge descriptors were not a reliable complete source. FO4 supplements semantic objects with the **actual IA draw parameters** and structured instance data used by the game.
- It handles instanced and CPU-expanded/pre-baked indexed forms, validates VB/IB/SRV associations and range counts, and reads bounded buffer slices asynchronously from the source buffer's own device.
- Merge record transforms use Bethesda's convention; apply the coordinate conversion once. Double conversion or using a cluster-center transform for already expanded geometry creates displaced/rotated duplicates.
- A single camera frame contains only some visible chunks. The captured chunk set is accumulated across frames, and resolution can re-arm when it grows. Replacing it each frame discards previously learned parts.
- Async slice cache keys contain buffer identity, offset and size. Out-of-range copies must fail before issuing a D3D copy; otherwise an ignored copy can masquerade as valid staging data.
- World reloads repack shared geometry pools. `DrawCapture::ResetAll` and slice/async reset must discard old offsets and watches together.

This is an engine-specific repair for precombined geometry, not evidence that NieR uses Bethesda-style 80-byte records or identical merge tables.

### Blanket LOD filters were tried and reverted

`lighting_static.cpp:1785–1820` explicitly records rejected approaches: filtering every `kFlagIsMeshLOD` or `TopFadeNode` object removed wanted walls, floors and buildings. The current blanket LOD-return block is commented out. Those comments are author-reported investigation history; the disabled branch is directly source-verifiable.

Takeaway: a flag's name is not enough to infer that a whole drawable is disposable low detail. Do not introduce a comparable broad NieR filter without observing real objects and both sides of a transition.

## 6. Visibility: separate a retained object from a visible draw

`draw_capture.h:124–170`; `draw_capture.cpp:684–725`; `remix_renderer.cpp:2470–3005`; `hzb_occlusion.*`.

FO4 does **not** simply make the persistent map permanently visible:

- Static bounds feed expanded frustum tests with hysteresis. The near keep radius bypasses distant view-culling decisions, using bounds-aware distance rather than blindly trusting the object's origin.
- Engine draw visibility is tracked by IB identity/IA offset. A previously seen key becomes stale only after an age threshold; a freshly drawn key immediately recovers.
- A key **absent** from the visibility map is exempt. This is deliberate fail-open behavior: a hook/key-convention mismatch may under-cull but must not erase the world.
- A minimum scene-draw count disables that signal during low-information/menu/loading periods. Without it, a quiet game draw stream could age the entire retained world out.
- Optional software HZB builds a low-resolution conservative depth hierarchy from selected static occluders. It uses max reduction, depth bias, near-plane/projectability checks, keep radii and delayed verdicts. Uncertain projections return not-occluded. `hzb_occlusion.cpp` contains a `SelfTest`; it was inspected, not executed here.
- First-person/view-model and skinned geometry have different bounds/visibility rules. Bind-pose static bounds cannot safely cull an animated character.
- LOD chunks, hidden/removed actors, pressure-parked entries, unresolved objects and first-pose holds have separate gates.

Actual default-source sample settings include frustum and engine-recency culling on, HZB off. Sample `FrustumKeepRadius=4096` differs from code fallback `8192`; the INI controls behavior when present. These values are Fallout units and not calibrated NieR settings.

**Remaining risks:** long-retained objects can ghost after engine removal; pointer reuse can appear plausible; stale visibility and parking can delay return; aggressive occluders can over-cull if their bounds/projection are wrong. Persistence needs lifecycle evidence, not just a bigger cache.

## 7. Skinning, facial morphs and UV animation

`skinned_meshes.cpp:26–40, 282–310, 350–410, 550–733`; `lighting_static.cpp:2211–2300`; `remix_renderer.cpp:2270–2440, 2735, 3170–3285`.

- Parse bind-space geometry, widen four blend indices/weights, register inverse-bind data and the live bone transform sources. The captured skin object uses private Bethesda layouts; e.g. bone-data records have a `0x50` stride.
- Compose inverse-bind and live bone-world transforms using the correct row-vector/transposition convention. The instance transform supplies the remaining Bethesda-to-Remix conversion; do not also apply a normal static-object world transform.
- The game-side tick collects current bones; an owned queue transfers them to the renderer. Before the first valid bone set, a skinned instance is deliberately held back instead of drawing bind pose at the origin.
- Handles are per-drawable so simultaneous actors cannot fight over one skinned BLAS. Pose changes do not mint a new content identity every frame.
- FaceGen dynamic positions are fingerprinted/refreshed rather than treated as immutable forever. Newer default source adds stronger stable geometry refresh support; **do not attribute every newer morph fix to v0.0.5**.
- `MeshInfoRefreshGeometryEXT` asks the fork to retain hash/topology identity while replacing mutable positions. That is important for motion vectors/denoiser history, not merely upload speed.
- Eye UV changes are baked into a private refreshed mesh. This does not establish a general material UV-transform API.
- FO4 submits its own four-weight/index layout to its matching fork. It is not a reason to replace our separately tested stock-1.6.1 padded three-slot layout. API input packing, shader strides and compiled runtime behavior must still be matched together.

## 8. Textures: source selection, mips, ownership, conversion

`ba2_texture_source.*`; `bs_extraction.cpp:345–935, 988–1732, 1920–2770, 2796–3214`; `bs_extraction.h`.

### Selection and asynchronous work

- With authored-source mode enabled, ordinary 2D textures first try a readable authored DDS path through the resource stream, then indexed DX10 BA2 data. Failure/unsupported authored data falls back to the live GPU texture.
- The BA2 reader normalizes names, indexes archives, checks format families/dimensions, reads/inflates chunks and preserves usable mip chains. Its archive ranking is not a universal mod-load-order resolver.
- Live render targets are excluded from authored lookup. A generation/source salt prevents stale live-screen textures from reusing an immutable source result.
- GPU fallback stages relevant mips, then polls with `DO_NOT_WAIT`; `WAS_STILL_DRAWING` remains pending. Queue/ring bounds, retry state and cache TTLs control memory/work.
- CPU decode/conversion jobs own bytes; completed textures are shared immutable payloads, not pointers into a temporary map/unmapped resource. CPU cache eviction must not invalidate an in-flight upload.
- Texture identity includes the transformations and source mode: tint, palette, postprocess, luminance adjustments and other variants cannot share one undifferentiated texture hash.
- CPU, converted-on-disk, and Remix GPU caches are separate. A texture-name/hash cache hit cannot count as a usable GPU upload after world reset unless bytes or a valid GPU registration still exist.

### Formats and normal conversion

- BC1/2/3/4/5 paths and the vendored BC7 decoder cover selected supported cases. Formats needing conversion become RGBA8; ordinary supported compressed data can remain compressed.
- The normal converter (`bs_extraction.cpp:1535+`) reconstructs/normalizes a hemisphere vector and writes Remix's unsigned octahedral encoding. In normalized form it computes `s=|x|+|y|+|z|`, then stores channels corresponding to `(x/s+y/s)/2+0.5` and `(x/s-y/s)/2+0.5`. Negative Z is folded to the positive hemisphere; BC5 reconstructs Z upstream of this conversion.
- This is a useful encoding reference, **not** proof of NieR's source channel order, tangent convention, normal strength, or signed/unsigned format. Confirm those from captured textures/shaders before applying equivalent math.
- Albedo sRGB handling is intentionally adjusted for this fork's shader linearization. Only diffuse is forced through its UNORM mapping; the same blanket conversion for normals, roughness or emission would be wrong. Do not import that policy into stock Remix without checking the exact shader path.

## 9. Materials, terrain approximations and alpha

`bs_extraction.cpp:1374–1732, 3216–3338, 3899–3967`; `lighting_static.cpp`; `remix_renderer.cpp:1115–1470`.

- Material extraction is semantic: texture slots, emissive color/intensity, palette/tint, alpha flags, two-sidedness and optional metallic/roughness approximation come from Bethesda material objects.
- Submit validates uploaded texture references. Required diffuse failure leaves the drawable retryable rather than creating a material with dangling texture references; absent optional maps are cleared.
- The fork uploads in-memory textures with `CreateTexture`; material references use hash strings such as `0x...`, resolved by the fork. They are not ordinary DDS filenames for stock Remix.
- Opaque material constants and alpha test use the public opaque extension. Blend-enabled draws use `InstanceInfoBlendEXT` with the appropriate source/destination factors and test state.
- `MaterialInfoTranslucentEXT` models water using extracted deep-color transmittance, IOR 1.33 and a measurement distance. **The translucent material extension itself is also present upstream**; the private texture upload/reference mechanism is the portability boundary.
- Palette/tint and optional albedo lifting are conversion policies, not faithful emulation of every original shader. Source retains smoothness-to-roughness machinery that is not proof every resolver currently supplies such a map.
- Landscape layer selection loses Bethesda's full layered blend. There is no demonstrated general-purpose shader translation or universal per-material UV transform.
- Missing texture/mip/normal data explains appearance defects; it must not be conflated with absent structural instances.

## 10. Presentation, HUD and input: why its D3D11 support works

`remix_api.cpp`; `present_hook.cpp:608–820, 990–1290, 1375–1482`; `window_manager.cpp`; `remix_renderer.cpp:3630–3732`.

1. A dedicated worker owns the Remix window, message pump, rendering and pacing. It consumes camera/HUD state published from game Present.
2. The window is visible, borderless/nonactivating in overlay mode, and follows the game's client rect. Minimize/focus rules prevent a permanently topmost window from covering unrelated applications.
3. Raw mouse/keyboard registrations are rebound to the game window. Opening the Remix menu temporarily changes focus policy; closing restores game input.
4. Game D3D11 HUD/Scaleform render targets are identified through render-target/clear/draw activity. Staging/polling/compositing produces an owned CPU RGBA overlay.
5. The worker calls fork `DrawScreenOverlay`, then directly presents the path-traced frame. The original game Present still runs.
6. `RemixMaxFPS` pacing uses the remainder of the target interval, not a fixed sleep added after every render. Shared state is protected by mutexes/atomics; this does not by itself guarantee no back-pressure.
7. Optional raster suppression retains UI/query-sensitive work rather than indiscriminately dropping every game draw. It is disabled in the default sample and needs target-specific validation.

**Important negative finding:** `dxvk_GetSharedD3D11TextureHandle` and output-copy APIs are exposed in the fork header, but this plugin does not call them for full-frame transport. It is not an example of a working Vulkan/D3D11 shared-image import path into the original game swapchain.

A visible Remix presenter could avoid our PT CPU round trip in principle. Reusing that architecture still requires panel/focus/resize/menu/HUD acceptance tests and cannot be advertised as a proven frame-generation fix. No such change was made here. Full device-loss/resize recovery is not established by the inspected paths.

## 11. Lights, camera, weather and diagnostics

- `camera.cpp`: reads `PlayerCamera`/live `NiCamera`, converts the Bethesda axes, validates frustum/FOV, and publishes projection/view data. Private offsets are Fallout-version contracts, not NieR offsets. Newer source can submit a separate view-model camera.
- `bs_extraction.cpp:4360+` and renderer light paths: gather loaded-cell engine lights, convert color/radius/intensity, create/cache handles, and draw light instances. `UpdateLightDefinition` can update a stable handle on a supporting fork; otherwise recreation is a fallback.
- `weather_bridge.cpp`: maps game-hour movement into sun settings via queued config updates. It is not a complete storm/fog/weather renderer.
- `fo4_diagnostics.*`, `fo4_tracy.h`: counters/frame profiling, not correctness proofs.
- `startup_diag.*`: executable/plugin/OS/module-owner/overlay information to identify version or hook interference.
- `crash_diag.*`, `watchdog_main.cpp`: local first-chance/exit/terminate diagnostics and a separate debugger/minidump process. These explain otherwise silent failures; they do not repair them. Watchdog is designed not to kill the game when it exits.
- SEH guards sit at risky runtime calls so a hardware exception does not unwind past a held C++ lock and strand it. Comments about past crash root causes are author reports, not crashes reproduced here. Matching MinGW/ARM64EC exception semantics cannot be assumed.

## 12. Memory, cleanup and why longer TTL alone is insufficient

- Default map TTL is 18,000 game frames; sweeps run less often than every frame. Cached static events may not re-fire, hence the long lifetime.
- Resolve budget, upload budget, texture pending count, CPU conversion worker count and CPU cache budget bound **different** resources.
- GPU pressure can defer risky first creates, park behind-camera entries, or remove old entries. Semantic state and resource residency are deliberately separable.
- Draws stamp last-use on mesh/material/texture ownership paths. Material references can keep texture VRAM alive; freeing an outer drawable record is not immediate memory reclamation.
- Destruction is parked/queued and drained at controlled points; sample `DeferHandleDestroyToLoad=1` avoids mixing large create/destroy waves during play. This trades transient memory for safety and is not automatically correct for our runtime.
- PreLoadGame closes the resolve gate **before** clearing objects, captures and pool offsets, then requests a destruction drain. PostLoad lifts the gate even on an aborted load. NewGame needs its own reset because it does not receive the same load-message pair (`main.cpp:60–103`; corroborated in the shipped callback).
- Engine pointers held for minutes require guarded access and lifecycle invalidation. SEH guards cannot prove a recycled pointer still refers to the same object.

## 13. Exact portability matrix for our upstream ARM64EC target

| Mechanism | Transfer status |
|---|---|
| Separate semantic object/instance/resource lifetimes | Portable design; NieR identity/removal discovery required |
| Partial static capture union, retryable pending state | Portable design with explicit world reset and ownership; not indiscriminate stale draw replay |
| Conservative visibility, never-seen exemption, keep radius/hysteresis | Portable policy after calibration; Fallout units/keys are not portable |
| Per-actor skinned handles | Same requirement already implemented in our bridge |
| Normal re-encoding / ownership / mip preservation | Reimplement after verifying NieR source conventions; no direct source copying |
| CPU scene-graph extraction / F4SE / BA2 layouts | Bethesda-specific, not portable addresses or structures |
| `CreateTexture`, hash-string in-memory texture references | Fork-only; stock bridge currently uses DDS paths |
| `CreateMeshBatched` | Fork-only. Our worker ownership is the first line of defense; do not add unsupported calls |
| `MeshInfoRefreshGeometryEXT` | Fork-only; stable mutable-geometry identity needs runtime support or a different stock strategy |
| `DrawScreenOverlay` | Fork-only; visible-window/HUD architecture needs an alternative or a separately ported runtime |
| `GetVramStats`, `UpdateLightDefinition` | Fork-only API entries; use supported OS/runtime alternatives where appropriate |
| `InstanceInfoBoneTransformsEXT`, `InstanceInfoBlendEXT`, opaque/translucent material extensions | Also present in stock; verify layouts and exact behavior, not merely names |
| Shared D3D11 handle export | Fork-declared but unused by this plugin; not demonstrated interop |
| `VIEW_MODEL` category/camera additions | Version/header-sensitive fork behavior; not a stock-1.6.1 assumption |
| Visible direct Remix presentation | Conceptually avoids PT readback; ARM64EC/input/panel/FG behavior untested |

The fork header adds 18 PFN names relative to the official stock-1.6.1 header, including several not used by this plugin. The manifest records that exact symbol-set difference; **exposed** is not synonymous with **called**.

## 14. Module coverage and boundaries

All 21 C++ translation units and 22 source headers were inventoried by path, hash and line count; the vendored BC7 decoder is distinguished from original plugin work. This is a module/data-flow map, not an exhaustive correctness audit of every line.

| Module | Responsibility / investigation coverage |
|---|---|
| `main`, `f4se_compat` | F4SE entry, readiness, version declarations, load/new-game resets; selected release code decompiled |
| `remix_api` | Loader, D3D9 registration/startup, window/device teardown, raw-input rebinding |
| `present_hook` | DXGI hook installation, game tick, camera/overlay handoff, worker loop, HUD staging |
| `window_manager` | Overlay placement, foreground/minimize/menu focus policy |
| `raster_suppress` | Optional scene-raster suppression retaining UI/query-sensitive behavior |
| `semantic_capture` | Event observation, PassKey map, retries, live poses, refresh, parking/TTL/load gates |
| `resolvers/lighting_static` | Static/terrain/merged/skinned resolution, material policies, async merge decode, live refresh |
| `resolvers/water` | Separate water material/geometry resolution and pending handling |
| `draw_capture` | Merge draw partition/chunk capture, engine visibility recency, reset/watch lifecycle |
| `bs_extraction` | Snapshot/parse/convert geometry; textures/readbacks/workers; loaded cells, terrain, lights |
| `ba2_texture_source` | Archive indexing, lookup, validated chunk reads/decompression |
| `bcdec_bc7.h` | Vendored BC7 decoding; separate license from plugin |
| `skinned_meshes` | Bone sources/inverse binds, live transform composition, queueing and diagnostics |
| `remix_renderer` | Resource caches/refcounts, persistent instances, culling, skin/morph refresh, lights/HUD/Present |
| `hzb_occlusion` | Conservative software occluder raster, mip hierarchy, AABB query, embedded self-test |
| `camera`, `weather_bridge` | Live camera/projection conversion; limited time-of-day sun bridge |
| `config` + sample/shipped INIs | Parsed fallback defaults versus sample/release values and feature gates |
| `startup_diag`, `fo4_diagnostics`, `fo4_tracy` | Environment/version ownership and frame/counter diagnostics |
| `crash_diag`, `watchdog_main` | Exception/exit breadcrumbs and separate debugger/minidump utility |
| CMake/build/README/KB/scripts | Build inputs, header replacement, research history, stated limitations and licensing |
| Cached Remix ABI + matching fork source | Header compatibility, actual batched-owned-copy implementation, stock/fork distinctions; not all runtime internals |

Review rejected several worker errors: wrong repository permalinks, confusing this repository's HEAD with the archived FO4 commit, claiming the lighting resolver rejects all skinning, implying shared actor BLAS is safe with per-instance bones, and classifying stock translucent materials as fork-only. The curated report uses pinned archive identities and actual code branches instead.

## 15. What to do with this in NieR—without guessing a fix

**First, establish one object's identity and disappearance stage.** Extend observation, not visibility policy, so one known floor/wall can be followed through:

```text
engine visibility/model decision
  -> indexed draw issued
  -> hook observed + pass/filter decision
  -> geometry key + occurrence + transform/palette
  -> completed capture frame contains instance
  -> worker resolves live handle and calls DrawInstance
  -> runtime accepts instance / applies its own culling
```

Log explicit reason codes for exclusions, and compare a visible/missing/returned sequence. A retained mesh handle without a current instance must be distinguishable from no engine draw, rejected capture, pending resource, and failed runtime submission. That test also needs deterministic offline gates before any instrumented live run.

Only after locating the boundary:

- Engine stops drawing a legitimate static object: investigate NieR semantic identity/cull hooks and narrowly controlled retention, with removal/LOD/world-reset rules.
- Hook sees the draw but filtering drops it: correct that filter; do not hide it with an eternal scene cache.
- Capture has the instance but worker skips it: fix resource/queue/identity readiness once in the shared submission path.
- DrawInstance is issued with valid data but runtime hides it: inspect runtime category, bounds/winding, transform and culling behavior.

Then address normal encoding and materials independently. A later presentation redesign can borrow FO4's visible-presenter topology while preserving the laptop panel, other monitors, focus and menu usability. No live changes, cache-policy changes, culling patches or performance claims result from this research alone.

## Sources

Unless marked release or fork, line references above refer to:

- [Pinned FO4 plugin source](https://github.com/Kim2091/FO4-Remix/tree/cb23b9e44a69896f4fa5e6143d83a798e7efd402)
- [Release tag source](https://github.com/Kim2091/FO4-Remix/tree/901e211af75ac618e62d23601201de0da71591d2)
- [Released v0.0.5 package and author requirements](https://github.com/Kim2091/FO4-Remix/releases/tag/v0.0.5)
- [Semantic lifecycle/keying](https://github.com/Kim2091/FO4-Remix/blob/cb23b9e44a69896f4fa5e6143d83a798e7efd402/src/semantic_capture.cpp#L49-L80)
- [Persistent renderer, skinned handle identity and batched create](https://github.com/Kim2091/FO4-Remix/blob/cb23b9e44a69896f4fa5e6143d83a798e7efd402/src/remix_renderer.cpp#L1470-L1573)
- [Lighting resolver, actual skin gate and disabled blanket LOD filter](https://github.com/Kim2091/FO4-Remix/blob/cb23b9e44a69896f4fa5e6143d83a798e7efd402/src/resolvers/lighting_static.cpp#L1711-L1820)
- [Normal conversion](https://github.com/Kim2091/FO4-Remix/blob/cb23b9e44a69896f4fa5e6143d83a798e7efd402/src/bs_extraction.cpp#L1535-L1580)
- [Fork API header and ABI version](https://github.com/Kim2091/FO4-Remix/blob/cb23b9e44a69896f4fa5e6143d83a798e7efd402/extern/remix/remix_c.h#L59-L67)
- [Matching default-source runtime header/implementation tree](https://github.com/Kim2091/dxvk-remix/tree/05c52a14a312fc3e0b0d088e7297ed75be14bd46)
- [Matching release-line runtime header/implementation tree](https://github.com/Kim2091/dxvk-remix/tree/aff568efd933858154ce14faa82911f32ecccdea)
- [Official stock remix-1.6.1 API header](https://github.com/NVIDIAGameWorks/dxvk-remix/blob/remix-1.6.1/public/include/remix/remix_c.h)
- [Plugin licensing statement](https://github.com/Kim2091/FO4-Remix/blob/cb23b9e44a69896f4fa5e6143d83a798e7efd402/README.md#L77-L80)

Verification: **115 hash/identity/header assertions passed**, covering archived default/release source files, selected shipped artifacts and their REA evidence identities, and both exact fork-header matches/category values. Every non-vendored first-party tree entry is retained. Local report links and `git diff --check` passed. No implementation files changed; the game's full test suite and live runtime were not run for this documentation-only task. REA's previously open game session was closed; CLI analyses retained snapshots/dossiers and exited.

Unverified: live Fallout behavior, every release/source binary equivalence, the bundled runtime's exact build commit, complete shader/effect coverage, stock ARM64EC implementations of private fork APIs, full device-loss recovery, frame generation, and the actual cause of NieR's disappearing structures.
