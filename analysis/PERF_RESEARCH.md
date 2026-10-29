# CPU bottleneck: quick research (2026-10-29 night)

Live numbers (media/2026-10-29): 3.6 fps, readback 152 ms + other 125 ms per frame, GPU mostly idle; mesh cache
built 22223 / evicted 19717 against a 512 MB budget.

## What our code does today (checked in source)

- `live_capture.h::read_into`: creates a **new staging buffer per read**, `CopyResource`, then immediately
  `Map(D3D11_MAP_READ)`. Every read waits for the GPU to finish everything queued: a full CPU/GPU sync per buffer.
- No `CreateBuffer` hook: static/immutable vertex and index buffers created with initial data are later read back from
  the GPU instead of being captured from `pInitialData` at creation.
- Large non-constant buffers written with Map/UpdateSubresource are not mirrored (`max_shadow_write`), so they are
  re-read when drawn. The live log confirms "large buffer writes not mirrored on the CPU (re-read when drawn)".

## What the sources say

- Microsoft (copying and accessing resource data): mapping a staging resource before the GPU has finished the copy
  stalls the pipeline; "performance can grind to a halt" if mapped at the wrong time.
  https://learn.microsoft.com/en-us/windows/uwp/graphics-concepts/copying-and-accessing-resource-data
- Standard remedy (StackOverflow 40808759, NVIDIA/AMD guidance cited there): a ring of 2–3 staging resources, copy in
  frame N, map in frame N+2; accept latency for throughput. `D3D11_MAP_FLAG_DO_NOT_WAIT` returns
  `DXGI_ERROR_WAS_STILL_DRAWING` instead of blocking. https://stackoverflow.com/questions/40808759
- DXVK developer guidelines: prefer a separate `D3D11_USAGE_STAGING` resource for readback (we do); consider one
  `Flush` after issuing staging copies for consistent readback latency, but no more than 2–3 per frame. Never read a
  resource without `CPU_ACCESS_READ` directly. https://github.com/doitsujin/dxvk/wiki/Developer-guidelines
- DXVK option `d3d11.cachedDynamicResources` (values v/i/c/r/a): allocates dynamic resources in cached system memory
  "to allow fast readback from the CPU"; may reduce GPU-bound performance. Only helps if we read dynamic buffers
  directly; we copy to staging, so its benefit for us is unverified. https://github.com/doitsujin/dxvk/blob/master/dxvk.conf
- DXVK 1.10 release notes: reduced worker-thread synchronization around readbacks gave large CPU-bound gains in
  readback-heavy games: the cost we see is a known class, not specific to NieR.

## Candidate fixes, cheapest first (none implemented or measured)

1. **Capture static buffers at creation** (hook `CreateBuffer`, copy `pInitialData`): removes their readback entirely.
2. **Stop the mesh-cache thrash** (pose-specific skinned keys vs 512 MB): fewer rebuilds means fewer reads.
3. **Batch and defer readbacks**: issue all copies for the frame into a reusable staging ring, `Flush` once, map them
   1–2 frames later (geometry one frame late; transforms/camera stay current).
4. Laptop run (native Windows D3D11, no DXVK) to separate Proton/DXVK cost from our design.
