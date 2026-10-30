# Replacing a Remix mesh: what the real runtime does (laptop, 2026-10-30)

**Result.** In the real Remix runtime (laptop `spaghetti`, RTX Spark N1X, Toolkit x64 runtime), a mesh cannot be
updated under the hash it already has:

| `REPROBE_REPLACE` | What the probe does every frame | Frame 14 | Verdict |
|---|---|---|---|
| unset (control) | nothing | centroid x 262.4 | baseline |
| `1` | `CreateMesh` with the **same live hash**, no destroy (the live path's rule until today) | 262.7 / 264.2 (two runs) | **old geometry kept** |
| `2` | `DestroyMesh`, then `CreateMesh` with the same hash | none: process exit `0xC0000005` after 7 frames | **crash** |
| `3` | `CreateMesh` with a **new hash**, then `DestroyMesh` of the old handle | 295.6 (+33 px; +35 expected) | **works** |

The probe moves the captured mesh +0.1 units in x per frame (about 25 px per unit at this camera), so frame 14 should
sit about 35 px right of the control. Image: `media/2026-10-30/laptop-mesh-replace-modes.png`
(control, mode 1, mode 1 again, mode 3). Receipts: `analysis/runtime/remix-probe/windows-{control-f14,replace-f14,
replace1-f14b,replace2-f14,replace3-f14}-20261030T08*.json`; probe `remix-mesh.exe` built by
`build.py --mesh runtime/remix-probe/mesh-body/captured_mesh.h` (sha256 prefix `53e1e0aa4b7fd471`), run with
`run_remote.py <label> --mesh --shot-frame 14 --env REPROBE_REPLACE=<mode>`.

**What that meant for the live path.** `live_scene::build_mesh` passed the capture key as the hash and, since the
"replacement deleted itself" fix, never destroyed a handle equal to the new one. So every rebuild under an existing key
showed the **old** geometry: a rewritten buffer kept its old shape, and a mesh first built without its texture never
showed the texture after the late-material repair (possibly part of the white/clay look; not checked live). The fake
runtime accepted same-hash replacement, so no mock gate could see it.

**Fix.** `live_scene::build_mesh` now gives every build a new hash (capture key in the high 32 bits, a 32-bit session-wide build
serial in the low bits) and destroys the previous handle after the new one exists: mode 3. The fake runtime now
behaves like the real one (handle == hash; `VIOLATION` on creating a live hash or re-creating a destroyed one) and logs
`key=` (hash >> 32), which the gates use as the geometry identity.

**Confirmed in runtime source** (`analysis/REMIX_API_PRIOR_ART.md`, researcher subagent, 2026-10-30):
`AssetReplacer::registerExternalMesh` returns early with "Ignoring repeated mesh registration" when the hash is live
(mode 1). Garry's Mod RTX Remixed's `MeshManager::UpdateMesh` uses create-new-then-destroy-old (mode 3). The mode 2
crash has no identified line; the likely cause is per-hash scene state (BLAS / draw tracking) outliving the destroy.

**Lights are different and need no change:** `LightManager::addExternalLight` overwrites a live hash in place and keeps
its stable identity, and RemixSDK.md documents Destroy + Create with the same hash as the way to update a light.
