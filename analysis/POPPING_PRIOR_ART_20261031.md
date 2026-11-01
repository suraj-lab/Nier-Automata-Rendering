# Geometry popping: measurement correction and public-source leads (2026-10-31)

Follow-up: [FO4-Remix integration reconstruction](FO4_REMIX_RECONSTRUCTION.md), with pinned source/release identities, selected shipped-plugin REA checks, and stock/fork portability boundaries. This remains research, not a diagnosed or installed geometry fix.

## What the 3 GiB test actually established

`live-budget3g`, unchanged DLL `2eaa2fa9d632c84f…`, `NIER_REMIX_LIVE_BUDGET=3072`, 150 s on laptop.
Original restored and hash-verified as `6ba266d6…` after exit.

- All sampled scene counters: **evicted=0**. Peak recorded mesh memory: **821.0 MiB**.
- Latest recording: `NieR Automata 2026.10.31 - 19.31.01.08.mp4`, 89.91 s, retained under
  `analysis/runtime/laptop-port/live-budget3g/recording/rec.mp4`.
- Sequential visual inspection at 0.5 s intervals across the full duration, then 0.1 s intervals around selected
  failures: camp floor missing ~0:03, ~0:14.4–14.9, ~0:16, ~0:32, ~1:28; wall surrounding the door absent ~0:43.2
  while the door and objects behind the wall remain. Returning floor/wall surfaces are already textured.
- This **disproves eviction as the sole explanation** for the disappearing geometry. Do not treat the higher
  budget as a fix or conflate absent geometry with a normal-map problem.

## 1. NieRAutomata-LodMod: strongest engine-specific lead

Source revision: `fc7316bd3309ab38eb2a4016a96f9282d285fb90`.
Repository: https://github.com/emoose/NieRAutomata-LodMod

- `LodMod.ini`, `DisableManualCulling`: author describes models disappearing/reappearing with camera position;
  specifically mentions the building outside the resistance camp and the mall interior.
- `Automata-LodMod/Rebug.cpp:20–21`: per-game-version tables for `Model_ShouldBeCulled` and its state global.
- `Rebug.cpp:118–205`, `Model_ShouldBeCulled_Hook`: restores debug manual-culling-disable behavior, and permits
  ordinary models while retaining exclusions for `low`, `lod`, `dummy`, `distant`, `far` and configured model filters.
- `Rebug.cpp:98–100`: special case for `g11420_dummybuild` when the resistance camp is loaded. Blindly disabling
  all culling can therefore expose duplicate/dummy geometry.
- `Automata-LodMod/SDK.h:201–224`, `DisableLODs`: clears distance LOD state and the `UseCullAABB` bit. Distinct
  mechanism from the manual-culling function; these must not be treated as one interchangeable switch.

Direct source:
https://github.com/emoose/NieRAutomata-LodMod/blob/fc7316bd3309ab38eb2a4016a96f9282d285fb90/Automata-LodMod/Rebug.cpp#L118-L205
https://github.com/emoose/NieRAutomata-LodMod/blob/fc7316bd3309ab38eb2a4016a96f9282d285fb90/Automata-LodMod/SDK.h#L201-L224

**Use:** identify the installed game's exact variant, verify candidate functions in REA against our binary, then
instrument culling decisions rather than copying addresses or loading the entire mod. Matching symptoms alone do
not establish that engine culling causes our current failure.

## 2. Special K / FAR: NieR D3D11 and LOD reference

Current plugin: https://github.com/SpecialKO/SpecialK/blob/main/src/plugins/nier.cpp

- `NA_Mesh`, `DisableLODs`, `sub_84CD60` / `sub_84D070`: explicit LOD fields and `UseCullAABB`; wraps mesh setup and
  disables LOD state before and after the original call.
- Explicit format-based identification of NieR render passes (bloom, AO, HDR paths) is useful for reviewing our
  own scene-target/pass filtering.
- Existing local `analysis/FAR_RESEARCH.md:119–125` already records static corroboration of `UseCullAABB` in the
  project binary. It explicitly does not claim a live fix.
- Original https://github.com/Kaldaien/FAR targets the 2017 game and warns it is incompatible with 2021 updates.
  Prefer current Special K and version-match every address.

## 3. FO4-Remix: actual D3D11-game to Remix integration

Repository: https://github.com/Kim2091/FO4-Remix
Reviewed public `master` source (not hash-pinned here; re-pin before implementing):
- `src/semantic_capture.cpp`: keeps a persistent engine-derived drawable map; uses `GetRenderPasses` hooks rather
  than equating a mesh cache with an active instance list.
- `src/remix_renderer.cpp`: nearby geometry is kept regardless of view direction; distant frustum culling uses
  expanded bounds; skipped objects retain handles, and re-entry only needs `DrawInstance`.
- `src/bs_extraction.cpp`, `ConvertNormalToOctahedral`: public normal-map conversion reference, after geometry
  stability is solved. BC decompression and Z reconstruction precede hemispherical octahedral conversion.

**Use:** distinguish mesh-resource lifetime from instance visibility. A mesh remaining cached does not make it
render unless it is submitted as an instance. This architecture is relevant to our D3D11 capture path.
**Limit:** it uses engine-specific Fallout hooks and a forked Remix API; not a drop-in bridge or proof for NieR.
Existing fuller comparison: `analysis/FO4_REMIX_NOTES.md`.

## 4. l4d2-rtx: targeted visibility overrides

https://github.com/xoxor4d/l4d2-rtx/blob/1c4586c0/src/components/modules/main_module.cpp

`r_cullnode_wrapper` overrides selected world-node visibility while keeping special sky/monitor views on the
original path; map settings support forced areas/leaves. Relevant method: targeted engine culling control, not
blind capture of all render passes. Source engine / D3D9, not a D3D11 translation layer.

## Next diagnostic boundary

For one disappearing floor/wall draw, determine in order:
1. Did the game issue the draw, and did our draw hook observe it?
2. Did our scene-target/pass filter accept it?
3. Did the completed frame contain its instance with a valid transform?
4. Did the worker actually call DrawInstance with its live mesh handle?
5. Only after these: did Remix cull or otherwise fail to render the submitted geometry?

The 3 GiB test answers none of these per-draw questions. Do not add a culling patch or persistent-world policy
until the loss is located. No runtime/mod was installed during this research.
