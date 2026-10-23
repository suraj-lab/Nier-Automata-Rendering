# Native-output routing — offline results, 2026-10-19

## Summary

1. **Camera dimensions come from the swap chain.** The closed proxy reads
   `IDXGISwapChain::GetDesc().BufferDesc.Width/Height` on entry to its hooked
   `Present`, before forwarding Present. They follow swap-chain size, not scene
   texture size. A reduced internal render therefore leaves them at display size.
2. **A separate reduced → native → native-post route works in a small mock test**
   on Proton/DXVK (16×8 → 32×16, nearest neighbour, not FSR), including through the
   logger and the renamed patched AA proxy. Native Windows D3D11 was not tested.
3. **The logger can now trace that route.** It records resource identities,
   bindings, draw/dispatch snapshots, copies and command-list boundaries.

This does **not** establish the game's post/HUD consumers or a working closed-mod
upscale path. The proxy's final `CopyResource(scene, Output)` constraint remains.
No game launch, live capture, installed-file or source-binary change occurred.

## 1. Dimension source (static)

Evidence is in `offline-dimensions/` with its own snapshot. Target SHA-256:
`f1c77c58fdd265b25dfa262c8660d49a4463a05bb0ee88daf732727f15e717ce`.

- Factory hooks: `CreateSwapChain` (slot 10) and `CreateSwapChainForHwnd`
  (slot 15) pass each successfully returned swap chain to an installer
  (`ev_7290b085…`, `ev_0af18f68…`).
- Installer detours swap-chain **Present (slot 8)** to `0x1800054c0`; ResizeBuffers
  (slot 13) is detoured separately (`ev_0eb5108e…`).
- At `0x1800054f3–0x180005523`, the assembly keeps the incoming swap chain in RCX
  and calls **slot 12, GetDesc**. Width/height at descriptor offsets 0/4 go to
  the dimension setter. The decompiler's `(0, &desc)` receiver was misleading
  (`ev_4200af3a…`).
- Updates happen on each intercepted Present whose GetDesc succeeds, before the
  original Present. Failure leaves prior values. ResizeBuffers internals and
  multi-swap-chain behavior were not traced.

The SDK check now asserts Present/GetDesc/ResizeBuffers slots 8/12/13 and
`BufferDesc.Width/Height` offsets 0/4.

**Implication:** with the swap chain left at 3440×1440, camera W/H stay native.
The pre-dispatch gate compares scene-texture size with those dimensions, so a
smaller scene would currently skip AA. Projection jitter normalization also uses
these W/H. Scaling must reconcile camera dimensions, the gate, jitter and both
motion-vector grids together.

## 2. Logger resource tracing

Sources: `checks/d3d11_log_proxy.cpp`, `checks/d3d11_trace_abi.h`,
`checks/d3d11_abi_check.cpp`.

Added passive hooks on PS/CS SRVs, OM RTV/DSV/UAVs, CS UAVs, CopyResource,
CopySubresourceRegion, ResolveSubresource, four draw variants, Dispatch,
ClearState, ExecuteCommandList and FinishCommandList. The callback typedefs the
logger calls through are tied to SDK slots and types by static asserts. The hook
function definitions themselves are not compile-checked against those types; they
were compared by hand. The device-level typedefs (CreateTexture2D,
CreateDeferredContext, RSSetViewports) have slot-offset asserts only.

- Resources use canonical `IUnknown` identity plus 2D descriptor fields.
- Binding setters on immediate contexts log post-call **observed** state; on
  deferred contexts they log **requested** arguments, since deferred state is
  recorded rather than active. Draw/Dispatch snapshots and copy records are
  logged **before** forwarding, i.e. the state the call executes with.
- Draws open a thread-local group; snapshots record PS shader, PS slot 0 and
  render targets. Dispatch records CS slots 0–1 and UAVs 0–2.
- Every line has PID/TID, a serialized event number and its draw group, except
  the `CAPTURE_TRUNCATED` marker.
- A 100,000-event cap writes `CAPTURE_TRUNCATED`; such a trace is invalid.

Deliberate limits: base 8 UAV slots; no indirect draws/dispatches, newer context
interfaces, view-subresource descriptors, resource lifetime generations or frame
markers. Event order is CPU call order, not GPU execution order. Use a fresh
capture directory because the log appends across launches.

Known gaps (from review): devices created through the forwarded exports
(`D3D11CreateDeviceForD3D12`, `D3D11On12CreateDevice`, `D3D11Core*`) get no hooks
and no marker. `ResolveSubresource` and `ClearState` forwarding are correct by
inspection only, not exercised. Per-draw snapshots, a global log mutex with
`fflush` per line, and a locked registry lookup per call add measurable overhead;
re-evaluate before any in-game use.

## 3. Synthetic routing test

`checks/resource_route_probe.cpp` creates a 16×8 source, mock-reconstructs it
into a separate 32×16 UAV texture (nearest neighbour, **not FSR**), samples that
into a 32×16 post render target, then performs deferred full and region copies.

Ten checks. Seven are exact half-float bit comparisons over every pixel:

- each of Draw, DrawInstanced, DrawIndexed and DrawIndexedInstanced, cleared and
  verified separately (this assumes the clear takes effect; no zero readback is
  asserted after each clear);
- native post target, deferred full copy and offset region copy.

Three are binding identity/null checks, not pixel readbacks: SRV/RTV hazard
unbinding, immediate UAV KEEP retention, and RTV retention under render-target KEEP.

Results in `offline-routing/`:

| Run | Result |
| --- | --- |
| `baseline-checked` (no proxy) | 10 checks pass |
| `chain-checked` (logger → renamed patched AA proxy) | 10 checks pass; 141 trace events; no trace errors |

`checks/verify_resource_route.py` then checks the chained trace's semantics:
monotonic events, loader readiness, creation extents, view extents, the dispatch
source/UAV, each draw's native input and target, the observed hazard unbind,
KEEP observation of all 8 UAV slots, size/format compatibility of full
`CopyResource` calls (region copies: endpoints and arguments only, not bounds), and
deferred copy → Finish → Execute ordering with matching list identity. It does not
enforce that each route resource ID is created only once; in this trace they are.
Seven unit tests, including negative cases, pass in
`checks/test_verify_resource_route.py`.

The first review found an immediate UAV KEEP observation gap and two tests that
could pass despite missing forwarding. All three were fixed before the retained
`*-checked` runs; the earlier runs remain on disk.

**Review status:** the first follow-up re-review failed with a provider usage
limit (run `ac02365c-6231-44a9-a8b4-350af2fb370a`). A fresh re-review on Claude
Haiku 5.5 (run `ce8660d6-c6bc-4921-803f-48295e834ac6`) confirmed all three fixes
and returned **OK with notes** for offline use, with no P0/P1 findings. Its P2
notes are folded into this document (wording, known gaps above). The code-level P2
hardening items (hook-type static asserts, resolve and ClearState exercises, zero
readback after clears, route-ID uniqueness) are deferred while the logger is on
hold; see the next section.

## Built-in frame dump in the AA mod (supersedes in-game logger use)

The installed AA proxy already contains a frame render-graph dump, disabled by
default in `NIER_DLAA.ini` `[Debug] Enabled=0`. Static strings show it writes
`NIER_DLAA_frame_<date>_<time>_<ms>.txt` next to the DLL: one frame of GPU work in
submission order, deferred lists spliced in, with per-entry VS/PS/CS shaders,
constant buffers, SRVs, render targets, depth, viewport, blend/depth state,
dispatch groups, UAVs, copy source/destination, clears, and a resource table
(`tex2d WxH format mips array msaa bind`). It is triggered by F10 or
`DumpFrameAt`.

This answers the post/HUD consumer question for a real frame with an INI change
and no DLL swap. The passive logger is on hold unless the dump proves
insufficient.

Safety of enabling `[Debug]` was checked statically (evidence in
`offline-framedump/`): with `Enabled=1` and no key pressed, each foreground
Present only adds ~6 `GetAsyncKeyState` polls plus a `DumpFrameAt` compare — no
recording or state change. F10 is edge-triggered and requires game-window focus;
`DumpFrameAt=N` fires once without a key. The file writes synchronously two
Presents later (one blocking write, ~1-few MB, brief hitch). `DumpShaders` does
not gate the resource table. Avoid F11 (heavy readback), End (mip bias), PageUp
(jitter sign), F6 (debug view), F7 (object motion) and Home (DLSS toggle, not
debug-gated) during the dump.

## Next

1. Confirm statically that `[Debug] Enabled=1` with no key pressed changes
   nothing, and which debug keys alter rendering. Then, with approval, take one
   in-game frame dump (F10) during gameplay to identify the scene texture's actual
   downstream post/HUD consumers.
2. Design the native-output route: a native destination outside the proxy's
   equal-size copy-back, with coordinated camera dimensions, jitter and motion
   grids.
3. Only then prototype fixed-scale rendering; validate HUD, temporal quality and
   GPU headroom at the unchanged 60 FPS cap.
