# Interop API: what the Portal RTX runtime actually implements

Static analysis, 2026-10-27. No GPU run, no game. Target:
`/mnt/second/SteamLibrary/steamapps/common/PortalRTX/bin/.trex/d3d9.dll`,
282 883 696 bytes, sha256 `ca71edf1d7d03d792a3e8d1d6b00c75d…`.

This answers the "live Remix in NieR" unknown (a) — *what can we get the rendered frame out
through* — without launching anything, and it corrects a false lead in the 2026-10-26/27 notes.

## 1. The export table is tiny, and the interface is the whole API

`analysis/tools/pe_info.py` (new, no third-party modules) reads the export table:

| export | RVA |
|---|---|
| `remixapi_InitializeLibrary` | `0x214d40` |
| `remixinternal_GetDlssNeuralRenderingStatus` | `0x2c2670` |
| `remixinternal_GetNrcStatus` | `0x30fea0` |
| `remixinternal_GetShaderCompilationCount` | `0x2923b0` |
| `writeAllMarkdownDocs` / `writeMarkdownDocumentation` | `0x472980` / `0x1ca5f0` |
| `writeAllOGNSchemas`, `writeRemixCategoriesSchemaUsda`, `QueryFeatureVersion` | `0x472990`, `0x521a10`, `0xf9990` |

Everything else (materials, meshes, lights, camera, the six `dxvk_*` calls) is reachable only
through the `remixapi_Interface` struct that `remixapi_InitializeLibrary` fills in. That is why
`strings` on the DLL shows no `dxvk_*` symbol names: they are struct member pointers, not exports.
`writeAllMarkdownDocs` explains the 1041-line `RtxOptions.md` the resume notes tell us to generate.

## 2. It fills exactly the 22 public members — and nothing else

`remixapi_InitializeLibrary` at `0x180214d40` is 0x160 bytes and, after validating its argument
struct, writes precisely 22 function pointers into the caller's interface:

```
+0x00 Shutdown                +0x58 dxvk_CreateD3D9
+0x08 CreateMaterial          +0x60 dxvk_RegisterD3D9Device
+0x10 DestroyMaterial         +0x68 dxvk_GetExternalSwapchain
+0x18 CreateMesh              +0x70 dxvk_GetVkImage
+0x20 DestroyMesh             +0x78 dxvk_CopyRenderingOutput
+0x28 SetupCamera             +0x80 dxvk_SetDefaultOutput
+0x30 DrawInstance            +0x88 pick_RequestObjectPicking
+0x38 CreateLight             +0x90 pick_HighlightObjects
+0x40 DestroyLight            +0x98 Startup
+0x48 DrawLightInstance       +0xa0 Present
+0x50 SetConfigVariable       +0xa8 SetCameraMediumMaterial
+0xb0  <-- never written
```

The 22 names are exactly the public header's 22 members in order (`vendor/remix_c.h`), which is
independent corroboration of the offset→name mapping.

## 3. `dxvk_GetInteropInfo` does not exist in this build

The Minecraft bridge (`rtxremix-java/native/remixbridge.cpp`, pinned `f2c6fdaa…`) calls
`g_remix.dxvk_GetInteropInfo(&info)` and sets `StartupInfo.interopImage`. Neither is in the public
header — not even on `main` — so both are runtime extensions of the Minecraft build (API 0.16.0).

In *our* runtime they cannot be present:

- The struct fill stops at `+0xa8`. An appended member 23 would be `+0xb0`, and no store to
  `[rdx+0xb0]` exists in the function.
- The version gate rejects such a client anyway: the function reads
  `InitializeLibraryInfo.version` from `[rcx+0x10]` and requires
  `(version & 0xffffffff0000) == 0x60000`, i.e. **API major 6** (0.6.x). The Minecraft runtime
  reports 0.16.0 (major 16) and would be refused here, just as a 0.6 client is refused there.
- The same function checks `[rcx] == 1`, confirming `InitializeLibraryInfo.sType == 1` and the
  field offsets `sType` 0, `pNext` 8, `version` 0x10.

So the 2026-10-26/27 note that the *"non-D3D9 host architecture is proven to exist, three unknowns
left"* is right about architecture but wrong about availability: **the interop-image path needs a
runtime we do not have.** The six `dxvk_*` members we probed as non-null are all in the 22, which is
why the earlier `Interop: … =1` line was true and still did not mean the Minecraft path was usable.

## 4. What the Minecraft host actually does (the reference implementation)

`dxvk_GetInteropInfo` returns `remixapi_dxvk_InteropInfo`, which the bridge marshals field by field:

```
dxvkDoneSemaphore_Handle   dxvkDoneSemaphore_ValueToWait   clientDoneSemaphore_Handle
imageMemory_Handle         allocationSize   width   height   interopImageFormat
depthImageMemory_Handle    depthAllocationSize   depthWidth   depthHeight   interopDepthImageFormat
```

`GlInterop.java` then imports those into OpenGL with
`glImportMemoryWin32HandleEXT(memoryObject, allocationSize, GL_HANDLE_TYPE_OPAQUE_WIN32_EXT, handle)`
and `glImportSemaphoreWin32HandleEXT`, and synchronises with **timeline** semaphores
(`GL_TIMELINE_SEMAPHORE_VALUE_NV`, `glWaitSemaphoreEXT`, `glSignalSemaphoreEXT`) plus a client-side
value counter that is incremented on every `signalDone()`.

Mechanism, in one line: Remix exports its colour **and depth** images as opaque Win32 shared
allocations and two timeline semaphores; the host imports them into its own graphics API and presents
them itself. Depth being exported too is what makes a path-traced depth buffer available for the
game's own post-processing.

## 5. Consequences for live Remix in NieR

Two routes exist, and only one is available with the installed runtime:

1. **Interop image (Minecraft route) — unavailable here.** Needs `dxvk_GetInteropInfo` (member 23)
   and `StartupInfo.interopImage` (field 8). Requires a newer runtime build: Remix Toolkit, or the
   runtime the Minecraft mod downloads. That is a download-and-run question, not a code question, and
   it does not need Minecraft itself.
2. **Public 0.6 surface — available now.** Two sub-routes, both already reachable through the pointers
   we verified non-null:
   - `Startup(forceNoVkSwapchain = 1)` then `dxvk_GetExternalSwapchain(&vkImage, &semRenderingDone,
     &semResume)`: the runtime renders into a `VkImage` **we** present. The header's own comment
     calls this the OpenGL-interop pattern. Caveat: a `VkImage` handle is device-specific, so this
     does not by itself cross into a second `VkDevice`; it suits a host that owns the same device.
   - `dxvk_CopyRenderingOutput(d3d9Surface, FINAL_COLOR)` after `dxvk_CreateD3D9`: a plain copy into
     a D3D9 surface belonging to Remix's own DXVK device, then `GetRenderTargetData` into system
     memory. No cross-device sharing at all — this is the route `interop_probe.h` implements, and it
     is the only one that is certain to work in-process regardless of how many `VkDevice`s exist.

The copy route's cost is a host-memory round trip: 3440×1440×4 ≈ 19.8 MB per frame, so at 60 fps
about 1.2 GB/s each way plus a D3D9 lock/unlock. That is plausible at 30–60 fps, and it is
measurable with the probe before anything is built on it.

**What to test next, in order:** the copy route end to end (already coded, one GPU run) → the size of
the frame actually produced (does it match the window, or the swapchain?) → then whether
`forceNoVkSwapchain` + `GetExternalSwapchain` yields a usable image, which is the cheap version if it
does. Only if both fail is a newer runtime worth obtaining.

## 6. Function-level decoding of the six `dxvk_*` members

The interface fill named every implementation, so each can be disassembled directly. All six are thin
wrappers over one dispatcher; what they check matters more than what they do.

| member | implementation |
|---|---|
| `dxvk_CreateD3D9` | `0x18020f240` — builds a stack command (`0x16`, editorModeEnabled) and dispatches |
| `dxvk_RegisterD3D9Device` | `0x18020f440` — null check, then dispatch |
| `dxvk_GetExternalSwapchain` | `0x18020f280` |
| `dxvk_GetVkImage` | `0x18020f400` |
| `dxvk_CopyRenderingOutput` | `0x18020eeb0` |
| `dxvk_SetDefaultOutput` | `0x18020f560` |

Error codes observed in the code itself: **0** success, **1** generic failure, **3** invalid argument,
**7** not initialized (returned whenever the global Remix instance at `0x190da14f8` is null, i.e.
before `Startup`).

### The trap: a successful external swapchain call can hand back a null image

`dxvk_GetExternalSwapchain(out_image, out_sem_render_done, out_sem_resume)`:

1. returns 3 if any out pointer is null, 7 if Remix is not started, 1 if its internal lookup fails;
2. walks a vector of swapchain images at `[rsi+0x688]..[rsi+0x690]`;
3. **if that vector is empty it returns 0 (success) and writes a null image**, with the semaphores
   still filled from `[rsi+0x768]`/`[rsi+0x760]` (+0x18);
4. the vector is empty unless `StartupInfo.forceNoVkSwapchain` was set — which is the header's own
   caveat, now confirmed in code.

So the probe must judge success by **the image handle being non-zero**, not by the return code. That is
why `interop_probe.h` already treats a zero handle as a finding rather than trusting the error code;
the same rule has to apply to this route.

### `dxvk_GetVkImage` returns the *surface's* image, not Remix's output

`0x18020f400` reads `surface->device->[+0x40]->[+0x90]` and writes that as the image handle. It is a
lookup of the VkImage backing the D3D9 surface it is handed — useful only to a host that shares the
same `VkDevice` (the OpenGL-interop shape the header describes). It cannot, by itself, hand a second
`VkDevice` Remix's final image.

### `dxvk_CopyRenderingOutput` validates more than the header says

`0x18020eeb0`:

- 7 when Remix is not initialized, 3 when the destination surface is null;
- pulls the DXVK device out of the destination surface (`[rcx+0x48] → [+0x40]`), so the surface **must
  be a DXVK D3D9 surface** — one created through the device `dxvk_CreateD3D9` returned;
- accepts types 0 (`FINAL_COLOR`), 1 (`DEPTH`), 2 (`NORMALS`), 4 (`GUI`); type 3
  (`OBJECT_PICKING`) is gated behind a one-shot flag at `0x190da15f8`;
- **refuses type 4 (`GUI`) with code 1 when `combineGuiInFinalColor` was set at Startup**, which is
  exactly what the header comment describes;
- anything else → 3;
- the copy itself is synchronous and takes an internal mutex before dispatching, and retries once by
  recreating the output object if the first dispatch fails.

For the probe this confirms the design: create the destination render target from Remix's own D3D9
device, call `CopyRenderingOutput(target, FINAL_COLOR)`, then `GetRenderTargetData` + `LockRect`.
`interop_probe.h` already requires exactly that ordering.

## Method note

This took one `pe_info.py` write, one export parse and one disassembly of a 0x160-byte function.
The 2026-10-26 session spent ~15 GPU runs and five research agents reaching a weaker conclusion,
because it read source before reading the shipped binary. The binary was the cheaper oracle.
