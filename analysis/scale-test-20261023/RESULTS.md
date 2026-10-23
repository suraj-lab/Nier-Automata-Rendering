# In-game render-scale test 1 — 2026-10-23 (over Moonlight, headless display)

Setter: `build/scale-setter/d3d11.dll` (`eb91ad72…`), scale 0.75. Backup and restore:
`backups/scale-test-20261023T113558Z/` (`restore.sh` run; d3d11.dll, NIER_DLAA.ini and
Graphic.ini hash-verified back; `d3d11_dlaa.dll` removed).

## What happened

- The setter applied at 12:51:02.458 (`screen=1600x900`), before the first
  Present (12:51:03.5). That does not establish whether it preceded all target
  creation. The dump below was taken after resolution changes; it cannot prove
  that the resolution detour was unnecessary.
- Swap chain went 1600×900 → 720×480 (12:51:04, the old monitor-name issue) → 1920×1080
  (user change, 12:53:50).
- User report: in-game image **black with a few sparkles**; menus fine. CAS sharpening
  was left **on** (not isolated).
- F10 dump: `NIER_DLAA_frame_20261023_125421_835.txt` (2899 entries, 0 unrecorded).

## Dump findings

- Scene colour targets scaled correctly: R11G11B10F / R32F / RGBA8 at **1440×810**
  (0.75 × 1920×1080); half/quarter chains 720×405, 360×202, …
- The command path reaches tone-map `2C76D68A` at 1440×810 → compute `F8E91DBD`
  (120×68 groups) targeting native 1920×1080 (likely engine CAS) → HUD `A1B77252`.
  Recorded commands do not establish correct sampling or output pixels.
- All **444 HDR scene draw entries** at 1440×810 report **DS=-**. No main
  scene-sized D24S8 appears in the resource table; one fixed 256×256 D24S8 does
  (`T1577`). The 19 Oct native capture references full-size scene depth, but is
  not the same scene/resolution.
- **Later static finding:** colour creation/resize uses the scale, whereas depth
  creation (`0x14024c340`) and resize (`0x140252210`) use native or half-native
  sizes. The engine can reject these mismatched pairs before D3D11 binding.
  This strongly explains the broken scene, but is not an isolated root-cause
  test: CAS was also enabled. See [DEPTH_SCALE_RESULTS.md](../DEPTH_SCALE_RESULTS.md).
- The AA mod skipped FSR4 (no FSR4 log activity), as expected.

## Next (offline)

1. Depth creation, resizing and engine validation are now mapped. The static
   verifier passes 34 checks; traces are in `../offline-depth/`. No fix is built.
2. Design a narrowly selected scene-depth fix that keeps allocation and engine
   metadata consistent on both creation and resize; validate refusal paths and
   odd-dimension rounding offline before installing anything.
3. Only after separate approval, re-test on the Dell at the desktop, CAS off,
   with screenshots and another F10 dump.

Save files `SlotData_0.dat` and `SystemData.dat` changed during the test (autosave /
settings). They were deliberately not restored; the originals are in the backup.
