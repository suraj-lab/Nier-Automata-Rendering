# NieR → RTX Remix: source-only feasibility spike

2026-10-25. **Verdict: plausible through a custom scene-submission plugin; not a drop-in DX11 wrapper.**
Proceed only to a small, isolated proof of concept—not a full remaster or a change to the working FSR/menu stack.
No game launch, laptop access, model load, runtime install or installed-game change was performed for the
initial source-only spike.

**Subsequent user-approved hardware test:** the standalone x64 probe now renders a reference triangle
through the Toolkit's x64 Remix runtime on Spaghetti's Windows ARM / RTX Spark N1X. This is confirmed
by the runtime's own captured image, not merely API success. Sixteen frames submit successfully and
scene resource deletion succeeds, but Shutdown hangs and required the 90-second watchdog. No probe
process remains; no game or language model was started. Original custom-scene capture was near-black;
reference scene changes were grouped, so its success does not isolate the original cause. Details:
`remix-probe/README.md`, image `remix-probe/screenshots/reference-triangle.png`, raw evidence
`runtime/remix-probe/render-evidence.json`. Clean shutdown and actual NieR scene extraction remain gates.

## What the sources establish

1. **D3D9 interception is not the only renderer entry point.** The upstream public header exposes
   `Startup`, `SetupCamera`, `CreateMesh`, `DrawInstance`, `DrawLightInstance` and `Present`.
   `StartupInfo.forceNoVkSwapchain` permits retrieving a raw Vulkan image for application-side
   presentation instead of letting Remix present to its own window. This is an integration route,
   not an automatic D3D11 scene extractor. SDK initialization alone is not a rendered scene. [S1–S2]
2. **Skinning is supported.** `MeshInfoSkinning` accepts per-vertex weights and bone indices;
   `InstanceInfoBoneTransformsEXT` supplies bone transforms. We do NOT necessarily have to read back
   every post-skinned vertex each frame. We still have to recover NieR's vertex formats, weights,
   bone palettes and transform conventions and validate the result. The public mesh format includes
   position, normal, UV and colour—not arbitrary original game vertex-shader code. [S2]
3. **Minecraft demonstrates an API integration, not automatic capture of another graphics API.** Its
   native bridge calls Remix Startup/Present; its interop path exports image-memory and semaphore
   handles for the OpenGL side. That is useful architectural evidence, but not a NieR/DX11 recipe.
   The vendored Minecraft header has fields/functions absent from the pinned upstream public header
   (e.g. StartupInfo.interopImage and dxvk_GetInteropInfo). Do not mix these structs/binaries: select
   a matching runtime/header pair and validate interface/version compatibility first. [S3–S4]
4. **Remix Plus is relevant, but evaluate the current fork.** The maintained RemixProjGroup repository
   advertises hardware-skinning improvements, capture fixes, SDK/plugin work and FSR/FG. The old
   Kim2091 main branch is a different revision; it must not be treated as the current Plus branch.
   Community interop helpers are leads to inspect, not proof they work with our DXVK/Proton chain. [S5]

These sources do not identify which integration was used in the specific DX11 videos the user saw.
They do establish a technically credible route beyond the built-in D3D9 capture frontend.

## What our existing NieR work actually gives us

| Requirement | Existing evidence | Still missing |
|---|---|---|
| Hook/host and frame boundary | Proxy DLL, Present/factory hooks and offline menu mock-game test | Remix initialization/coexistence in the actual mod stack |
| Camera | Existing camera reverse-engineering notes; main-camera tracking used by the AA mod | Stable full view/projection interface, handedness/jitter/unit validation for Remix |
| Meshes/instances | Recorded draws, shader hashes, resources and some constant-buffer contents | Vertex/index bytes and layouts, stable mesh IDs, object/world transforms and instance lifetimes |
| Animated characters | `MOTION_VECTOR_RESULTS.md:64–76` documents current/previous skinned/projected positions in the mod's motion shader | Original game mesh formats, weights/indices, bone palettes, shader variants and motion continuity |
| Materials | Recorded PS SRV bindings and texture metadata | Decode/export textures, map shader-specific channels and alpha modes into Remix materials |
| Lighting/world | Some frame state, not a reconstructed scene | Lights/intensity units, sky, offscreen occluders, transparency, particles and culling/lifetime policy |
| Final output/HUD | Existing post-AA routing analysis | Shared-image ownership/synchronization and composition with NieR's UI without double AA/upscaling |

Colour + depth + motion vectors do **not** provide the hidden geometry/materials needed for a
scene path tracer. Our current FSR bridge therefore cannot simply be connected to Remix in place
of its upscaler. A persistent scene cache or deeper engine integration is also needed: raster draw
hooks see the objects the game chose to draw, not necessarily the offscreen world needed for rays.

### What the old text captures can and cannot tell us

Recounted two already-saved files under `analysis/framedump-capture/`. Matching explicit
`Draw`, `DrawIndexed`, `DrawInstanced`, `DrawIndexedInstanced` event rows yields:

| Capture | Explicit draw rows | Sum of row `xN` repetitions |
|---|---:|---:|
| `NIER_DLAA_frame_20261019_224309_810.txt` | 3,080 | 4,308 |
| `NIER_DLAA_frame_20261019_224339_508.txt` | 2,240 | 3,476 |

These are precisely that text-query's counts, not unique meshes, triangle counts, a new capture,
or a complete workload/performance measurement. The logs explicitly collapse identical calls and
splice deferred-command-list records into submission order. They include multiple rendering passes.
Neither file contains vertex/index-buffer payload/layout records (`VB`, `IB`, `stride`, `POSITION`,
`NORMAL`, `BLEND`, `IASet` searches returned zero). We cannot extract a valid triangle/character mesh
from these text logs or estimate submission bandwidth from them. Existing higher-level frame-summary
counts use a different counting definition and are not used as a performance estimate here.

Capture SHA256:
- first: `75338d43572c95f0e38b2db0d7ed03d0f8928377ae4004d9b27de06dedb64a4b`
- second: `ae1f2a14d573190764ef1c8f8b67547db5755f31ee294daa12f9f371d2528894`

## Platform boundary

- NVIDIA's published Runtime/Toolkit requirements list Windows and an RTX GPU. The AMD desktop is
  **not our verified supported execution target**. This is not proof that every community runtime
  is incapable of running on AMD; Plus advertising FSR is not proof our AMD/Linux setup works either. [S6]
- Release 1.6 announces Windows-on-Arm runtime support. That does not establish x64 NieR + its x64
  plugin + a selected runtime binary on the laptop. Keep the in-process ABI compatible; native ARM64
  support alone is not permission to load an arbitrary ARM64 DLL into the x64 game process. [S7]
- Vulkan image handles are not D3D11 texture pointers. Windows external-memory/synchronization and
  DXVK/Proton interoperability are explicit experiments, not consequences of both renderers using Vulkan.
- At the source-only stage, laptop runtime/driver/memory had not been inspected. The later approved
  probe selected the Toolkit's x64 runtime and logged driver 617.69.0. It proves the captured synthetic
  triangle, not compatibility with NieR or a GPU peak-memory/performance budget. MCP availability by
  itself never established runtime compatibility.

## Smallest next proof, when hardware testing is authorized

1. **Standalone RTX-side smoke test, not injected into NieR:** matching x64 SDK/runtime in an isolated
   folder; initialize, submit one indexed triangle with a camera and light, render to its own output.
   Record API error codes, header/runtime revision, GPU and a captured image. No game DLL replacement.
2. **One static NieR object:** separately approved diagnostic capture of an original visible opaque
   indexed draw's layout/buffers, transform and base texture. Reconstruct it in the standalone sample.
   Pass = correct shape, orientation and camera response—not a screenshot textured onto a quad.
3. **One animated mesh:** feed weights/indices and bone transforms through the skinning extension;
   compare poses, normals and motion. This is where the existing motion/camera research may save work.
4. **D3D11 presentation/HUD test:** exchange the rendered image with a standalone D3D11 host using a
   tested memory/synchronization path. Do this before combining Remix with WAX, the AA mod or FSR.

Stop after the first failed gate and investigate; do not start broad material replacement or a whole
world converter before these pass. If geometry requires blocking GPU readback per draw, redesign and
measure it before expanding. Source/API inspection is a **GO** for this small prototype, not evidence
of full-game correctness, real-time performance or a defensible multi-month schedule.

## Where the MCP helps

After a usable Remix capture/project exists, the Toolkit MCP can inspect captured assets/layers and
replace textures/model references. It does not extract NieR geometry, implement the game plugin,
create arbitrary scene objects or solve renderer interop. No Toolkit project was opened or edited.

## Pinned sources

- **S1:** [Official SDK guide](https://github.com/NVIDIAGameWorks/dxvk-remix/blob/bbd74a1287c2fa887f4a2b0e46a1530177890b64/documentation/RemixSDK.md), initialization and per-frame submission sections.
- **S2:** [Official C API](https://github.com/NVIDIAGameWorks/dxvk-remix/blob/bbd74a1287c2fa887f4a2b0e46a1530177890b64/public/include/remix/remix_c.h): Startup L212–228; vertex/skinning L341–365; camera L413; bone transforms L437–442; instance L583; interface L790 onward.
- **S3:** [Minecraft native bridge](https://github.com/NVIDIAGameWorks/rtx-remix-minecraft/blob/f2c6fdaa763f45676f1576e63f8e054bf4ef16af/rtxremix-java/native/remixbridge.cpp), Startup L657–671, Present/interop L712–751.
- **S4:** [Minecraft OpenGL interop](https://github.com/NVIDIAGameWorks/rtx-remix-minecraft/blob/f2c6fdaa763f45676f1576e63f8e054bf4ef16af/src/main/java/com/nvidia/rtxremix/minecraft/gl/GlInterop.java).
- **S5:** [Maintained Remix Plus README](https://github.com/RemixProjGroup/dxvk-remix/blob/9aab34bd306f890933eb83dda84c7cd37bd8260f/README.md). Old Kim2091/main checked separately at `b7c1ef15d0e8c889902d26fa6df1122329b657b6`.
- **S6:** [Official technical requirements](https://docs.omniverse.nvidia.com/kit/docs/rtx_remix/latest/docs/introduction/intro-requirements.html), accessed 2026-10-25; unpinned documentation.
- **S7:** [Official release notes](https://github.com/NVIDIAGameWorks/rtx-remix/releases), 1.6 Windows-on-Arm announcement; accessed 2026-10-25.

The initial spike performed no runtime execution. The later approved x64-on-Windows-ARM reference
triangle test is recorded above; native ARM64 binaries and NieR/DXVK interoperability remain untested.
The installed menu build still awaits the user's separate live test; no game deployment or settings
were changed by the standalone probe.
