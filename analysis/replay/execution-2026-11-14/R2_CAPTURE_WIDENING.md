# R2a/R2b — a capture that can see PS slots 16-31 and a cube's six faces (offline, 2026-11-15)

Scope: item 1 of the plan's handoff list, "R2a/R2b": (a) enumerate PS SRVs 0-31 instead of 0-15 in
`texture_capture.h::capture`, keeping the byte budget and the dynamic/RTV filter, behind a switch; (b) write a cube SRV
as all six faces under a DX10 cube header, plus the matching read-back in `terrain_bake::read_dds` /
`replay/pack_capture.py` / `replay/capture_replay.cpp`. Both are default-off; no game run, no DLL install, no deploy,
no package or system change. The desktop game folder was not touched.

The *new data* these changes would expose (slots 16-31 populated, real cube faces) still needs **one fresh live F9
capture**; this item proves the writer/reader/switch offline, not what the game binds at those slots.

## Correction: what a cube DDS header actually is

The plan's item 1(b) said "`resourceDimension = TEXTURECUBE`, `arraySize = 6`". That is not the DDS encoding, and the
first implementation followed it into an invalid file: writer, reader, packer and gate agreed with each other and
disagreed with every DDS consumer. The independent review caught it (P1). The verified encoding, from Microsoft's own
loader (`DirectXTex/DirectXTexDDS.cpp`, the `DDS_DIMENSION_TEXTURE2D` case, fetched 2026-11-15):

| field (DX10 header, offset from file start) | 2D texture | cube |
| --- | --- | --- |
| `dxgiFormat` (128) | format | format |
| `resourceDimension` (132) | 3 (TEXTURE2D) | **3** — there is no TEXTURECUBE dimension; 4 is TEXTURE3D |
| `miscFlag` (136) | 0 | **0x4** (`DDS_RESOURCE_MISC_TEXTURECUBE`) |
| `arraySize` (140) | 1 | **1** — it counts cubes, DirectXTex multiplies by 6 for faces |
| `miscFlags2` (144) | 0 | 0 |

DirectXTex source, verbatim: *"case DDS_DIMENSION_TEXTURE2D: if (d3d10ext->miscFlag & DDS_RESOURCE_MISC_TEXTURECUBE)
{ // DDS_HEADER_DXT10.arraySize is a count of cubemaps; TexMetadata stores their faces. ... metadata.arraySize *= 6; }"*
and the TEXTURE3D case refuses a file without `DDS_HEADER_FLAGS_VOLUME`. `DDSCAPS2` keeps the six face bits
(`0xFE00`) and `DDSCAPS_COMPLEX` (`0x8`), which the writer already set correctly.

## What changed

| file (SHA-256) | change |
| --- | --- |
| `checks/texture_capture.h` `990458e6…` | `Texture.faces` (1 = 2D, 6 = cube); `read_mips(…, faces)` copies subresource `CalcSubresource(mip, face, mips)` and lays the bytes out slice-major, the DDS order; `capture(…, slots = 16, cube_faces = false)` enumerates up to 32 PS SRVs, reads six faces only for a `TEXTURECUBE` **view** (`SRV::GetDesc`, not the resource's misc flag) of an `ArraySize == 6` resource, and charges the whole six-face read to the budget through `capture_bytes`; `write_dds` writes the cube encoding above when `faces > 1` and is byte-identical to before when it is not (pinned header bytes in the gate); `to_octahedral`/`to_channel` refuse a cube (a face chain is never converted as if it were a 2D chain) |
| `checks/draw_capture.h` `3862f1d0…` | `texture_slot_limit()` (`NIER_REMIX_LIVE_TEX_SLOTS`, clamped to 16-32), `texture_cube_faces()` (`NIER_REMIX_LIVE_TEX_CUBE`), `texture_budget()` (`NIER_REMIX_LIVE_TEX_BUDGET`, test switch) — each read once, defaults unchanged; the one call site passes them |
| `checks/terrain_bake.h` `52b39687…` | `read_dds` accepts `resourceDimension 3` only (a 2D texture and a cube's face 0 chain both start at 148) and refuses every other dimension instead of decoding it as a 2D tile |
| `replay/pack_capture.py` `6ad18e50…` | `cube_sized`: detects a cube by `resourceDimension 3` + `miscFlag & 0x4`, requires one cube and all six faces' whole mip chain (block-size table for every format `texture_capture.h` gives a size, typeless included), and raises `ValueError` otherwise; reads only the 148-byte header, then `stat()`; validated once per texture id, not once per draw; 2D files are not size-checked, as before |
| `replay/capture_replay.cpp` `8d8065cf…` | `load_texture` rejects a cube DDS (`miscFlag & 0x4`) instead of binding face 0's chain as a 2D texture; the frame counts it as `missing_textures`, a coverage gap rather than a wrong texture. Not gated by this item (the replay exe is not built here) — see limitations |
| `checks/menu_overlay_mock_game.cpp` `3adee902…` | `MOCK_TEX_SLOT16` (a static 8×8 RGBA at PS slot 16 beside a render target at slot 17), `MOCK_TEX_CUBE` (a 6-face, 2-level 4×4 cube at slot 3, every face and level a distinct pattern) and `MOCK_TEX_CUBE=face2d` (a `Texture2D` view of face 0 of that cube) — bound only in those modes, so every existing mock gate sees exactly the slots it saw before |

Default-off parity is exact: with none of the three variables set, `capture` reads the same 16 slots, takes the same
branch for every texture, and `write_dds` emits the same 148-byte header and payload — the gate now compares that
header byte for byte (`PLAIN_HEADER`), which the older gates only sampled (format, magic, payload).

`pack_capture.py` and `terrain_bake.h` also carry **earlier** uncommitted items (A1's packer preflight/refusals in
`pack()`, terrain-mips' `half()`/`dds_bytes(full_mips)`); they are judged by `test_pack_capture_validation*.py` and
`test_terrain_mips*.py`, not by this receipt.

## Frozen gate `checks/test_live_texture_wide.py` (SHA-256 `95d6239f…`)

Red before the implementation (the widened run captured nothing at slot 16), green after; and red again against the
wrong cube encoding (mutation row 5 below). What it pins, all in the Wine/llvmpipe mock with the real proxy DLL:

- **default**: with `MOCK_TEX_SLOT16` bound, both frames still hold exactly `[(0,1), (2,2)]`, `textures == 2`; the
  slot-16 static texture and the slot-17 render target stay invisible.
- **slots 32**: `[(0,1), (2,2), (16,3)]`, `tex_3.dds` is format 28/8×8 with the mock's exact bytes, and the slot-17
  render target is still skipped — the filter survived. The light-array buffers at t20/t22 never appear.
- **clamp**: `NIER_REMIX_LIVE_TEX_SLOTS=200` behaves exactly like 32.
- **budget**: `NIER_REMIX_LIVE_TEX_BUDGET=64` with 32 slots → only the 64-byte 4×4 texture is written
  (`textures == 1`, `texture_bytes == 64`); the BC1 and the 8×8 are recorded as seen with id 0, as before.
- **cube off**: a cube at slot 3 is written as today — plain TEXTURE2D, `miscFlag 0`, `arraySize 1`, 80 bytes = face
  0's two levels.
- **cube on**: `miscFlag 0x4`, `arraySize 1`, caps `COMPLEX`, `caps2` `0xFE00`, 480 bytes in slice-major order (all
  six faces, each with its own chain); the same frame's 2D DDS header is byte-identical to the pre-item one.
- **cube face view**: with `MOCK_TEX_CUBE=face2d` (a `Texture2D` view of face 0) the file stays one face, even with
  the switch on — a six-face file must not be written for a one-face sample.
- **cube budget**: the frame's two 2D textures take 96 bytes of a 400-byte budget; a cube charged as one 80-byte face
  would fit, the whole 480-byte read does not, and no `tex_3` is written.
- **read-back** (native, mingw, `-Wall -Wextra -Werror`): `read_dds` on that cube file returns a 4×4 image whose first
  texel is face 0's; dimensions 1/2/4 are refused; `to_channel`/`to_octahedral` refuse a cube and leave its bytes alone.
  The harness exits 4 if `read_dds` refuses the writer's own cube, so a refusal fails loudly instead of reading past a
  vector.
- **packer**: the six-face cube packs; a truncated cube, a header-only cube and a two-cube file raise `ValueError`; a
  real 2D DDS from the same run still packs, the DDS is not rewritten and the raw capture is not written.

## Mutations (18, all red, all restored byte-identically, receipts regenerated in one run)

`runtime/live-texture-wide/mutate.py` (re-runnable), receipt `runtime/live-texture-wide/mutations.json`:

| # | mutation | red because |
| --- | --- | --- |
| 1 | slot loop ignores the switch (`slot < 16`) | slot 16 missing in the widened run |
| 2 | cube never reads its six faces | the cube file stayed 2D |
| 3 | a 2D view of a cube face is read as six faces | the face-view case wrote a cube file |
| 4 | every face read as face 0 | the six faces are identical / payload wrong |
| 5 | **DDS written with the wrong cube encoding (dimension 4, arraySize 6)** | the gate names the required encoding; this is the P1 the review found |
| 6 | header drops the cube flag | `miscFlag` 0 on a cube |
| 7 | header drops the six face bits | `caps2` was `0x400000` |
| 8 | cube converted as a 2D chain (channel) | `cube_channel == 1`, bytes mangled |
| 9 | cube converted as a 2D chain (octahedral) | `cube_octa`/`cube_kept` |
| 10 | no dimension check in `read_dds` | `TEXTURE1D` decoded as a tile |
| 11 | `read_dds` refuses cubes too | harness exit 4 — the item's own claim |
| 12 | packer keys cube detection on the wrong field | truncated cube silently packed |
| 13 | packer does not size-check cubes | truncated cube silently packed |
| 14 | packer accepts a truncated cube | same |
| 15 | packer accepts an array of cubes | two cubes silently packed |
| 16 | byte budget ignored | the 64-byte cap captured three textures |
| 17 | a six-face read is charged as one face | the cube fit a budget it cannot fit |
| 18 | render targets captured again | the slot-1 / slot-17 targets entered the capture |

Each mutation was run once (`attempts: 1`), every red carries an `AssertionError` from the gate rather than a build
failure, and the runner re-verifies each file's SHA-256 after restoring. Two earlier rows that were red only because
they failed to compile were replaced with compile-clean equivalents.

## Suite

`runtime/suite-r2a-r2b-s2/full-suite.json`: **131/131 passed**, `-j 14`, 282.8 s, `source_unchanged: true` (130 gates
before this item + the new one). An earlier run of the pre-correction tree (`suite-r2a-r2b-s1`) was also 131/131; it is
superseded, not evidence for the corrected encoding.

## Independent review

`reviewer` (anthropic/claude-haiku-5-5, synchronous, read-only). Verdict: BLOCK for R2b, R2a OK — P1: the cube header
was invalid (see above), and the gate pinned it. Every finding and its disposition:

| finding | disposition |
| --- | --- |
| P1-1 cube header invalid, gate enshrines it | **fixed**: writer/reader/packer/gate now use TEXTURE2D + `miscFlag 0x4` + `arraySize 1`, verified against DirectXTex; mutation 5 keeps it dead |
| P2-a `cube_sized` read every file whole, per draw | **fixed**: 148-byte header read + `stat()`, once per texture id |
| P2-b bypass below 148 bytes, typeless formats missing | **fixed**: a DDS that cannot be a cube is left alone, but a header-only cube is refused (gate case), and the format table now carries the typeless formats |
| P2-c a cube could overshoot the budget 6×, allocation unguarded | **fixed**: the whole six-face read is charged before it happens (`capture_bytes`), gate case present |
| P2-d the SRV's view dimension was never consulted | **fixed**: `SRV::GetDesc` decides, gate case `MOCK_TEX_CUBE=face2d` |
| P2-e the harness read `im.rgba[0]` before checking `read_dds` | **fixed**: `if (!read) return 4;` |
| P2-f the "legacy 2D packs" case used a malformed file | **fixed**: the case now uses a real 2D DDS written in the same run |
| P2-g attribution: `pack_capture.py`/`terrain_bake.h` carry earlier items | **recorded** in this receipt and listed as such |
| P3-a the slot clamp was untested | **fixed**: the clamp case runs `=200` |
| P3-b `caps2` 0x400000 pre-existing | left as found: changing it would change every 2D header, which is a separate decision |
| P3-c `remix_live.cpp`'s `write_dds` has no `faces` guard | left as found: the live read path passes `faces = 1`, so no cube can reach it; recorded here |
| P3-d the mutation receipt held compile-only rows | **fixed**: receipt regenerated in one run, 18/18 behavioural |
| P3-e non-cube header bytes were not pinned | **fixed**: `PLAIN_HEADER` compares all 148 bytes |
| P3-f `run-*` work dirs accumulate | accepted: retention under `runtime/`, not a leak |

## Limitations (state them, do not paper over them)

- **Cost of the wider range is unmeasured.** `PSGetShaderResources(0, 32)` plus up to 16 more slot inspections and the
  six-face readbacks cost something per draw; the plan requires a measurement before any default change, so the
  default stays 16. Unmeasured, not zero.
- Nothing here proves Remix loads a cube replacement DDS (its loader is `gli`, whose cube path is untested here), nor
  that a cube replacement is what the sky wants. `capture_replay::load_texture` rejects a cube DDS, which is a truthful
  coverage gap rather than a wrong texture — but that rejection is **not gated** by this item.
- The mock's cube is 4×4 RGBA8 with two levels: BC formats, larger faces and non-square mips are untested, as is a real
  NieR cube (the fog LUT at t12/t19 and the environment cube).
- The gate's wide-slot texture is a synthetic static 8×8: it proves the enumeration and the filter at slots 16-17, not
  which slots NieR actually binds (that is what the live capture is for).
- `NIER_REMIX_LIVE_TEX_BUDGET` is a **test switch** added so the cap could be gated without a 1 MB frame; it is read
  once and its absence restores `max_texture_bytes` exactly.
