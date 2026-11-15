# C3b real-runtime terrain mip comparison — 2026-11-14

Executed the plan's fresh-assets warning/image comparison on headless RX6800XT (`1002:73bf`,PCI47:00.0), adapter
confirmed in BOTH host logs. No monitor-driving RX9070XT render or model unload. Inference model was resident
(~11.3GB allocated on the6800XT) but GPU busy samples were0%; all elapsed/FPS values are EXCLUDED as benchmarks.
No game-folder deployment, remote command, system/Steam setting or Toolkit/MCP action.

## Inputs and exact commands

`runtime/c3b-real-mip-comparison/off-on-runs.json` retains commands and asset inventories. Both runs use current
proxy SHA256f6c3b0ba0fd80c1719e8283ac119b6dba160613315eab3734644fe3c21d40cdc, Portal runtime
SHA256ca71edf1d7d03d792a3e8d1d6b00c75d122220e4b4f323ef93e6f71bb9392dc1, same config
SHA256abb85c8682eda423e7e22f7ce5b645f17f1654c0058ffe49f412e1d40abb858c, known control capture
`/mnt/second/SteamLibrary/steamapps/common/NieRAutomata/NIER_CAPTURE/frame_41686139`,1200frames,2580x1080,
shot1199,--mode real,--isolated-prefix,--env REPLAY_EXIT=clean,--timeout75. Candidate adds ONLY
`--env NIER_REMIX_LIVE_TERRAIN_MIPS=1`. Fresh run directories and live-texture assets on both sides.

| Result | Off | On |
| --- | ---: | ---: |
| Presented application frames |1200|1200|
| Fresh baked terrain DDS |24|24|
| DDS dimensions |512x512|512x512|
| Mip levels |1|10|
| DDS bytes per asset |1,048,724|1,398,248|
| Terrain-specific suboptimal warnings |24|0|
| Live draws / instances |554/680|554/680|
| Meshes / textures |549/358|549/358|

All24level-zero payloads match byte-for-byte; all24candidate names use `_mips1.dds`; native test's exact10-level
RGBA8+DX10 size confirmed in actual emitted assets. Asset hashes and comparisons:
`runtime/c3b-real-mip-comparison/asset-and-image-comparison.json`.

Native frame sources are `runtime/replay/c3b-real-mips-{off,on}-control/shot-1199.png` (both2580x1080). Encoded-RGB
mean absolute difference1.686/255,95th-percentile channel difference6. This includes stochastic rendering/history;
it is NOT a calibrated original/Remix pair, artistic approval, or proof of identical effective projection.
Labelled preview: [off/on](c3b-mip-off-on-preview.jpg). Smaller derived previews retained; native files untouched.
Agent visual image-reading was blocked by context-mode's per-read cap; numerical comparison and native assets are
recorded, but no claimed independent aesthetic approval/manual fine-detail inspection. No default flip.

## Limitations / rejected control

The initial `c3b-real-mips-off` run used frame30632051 at1720x720 and produced ZERO bakes; it is explicitly rejected
as a non-exercising fixture, not a zero-warning success. Its commands/logs/screenshots remain intact. Switched to
existing known frame41686139, which had already produced24bakes in earlier controls; no source/geometry workaround.

Both accepted comparison applications presented all1200frames, but launcher wait hit75.3s and required exact
private-prefix-owned cleanup (two remaining launcher/service PIDs each). Application wall~20s. `errors=[]`, and
post-cleanup ownership scan found no remaining tasks. This is NOT clean shutdown acceptance or a C2 fix.
Runtime/host Linux cache state was not standardized; timing/performance comparisons are invalid and excluded.

C3b's real mip-file/warning substep has evidence. C3 parent remains open: approved laptop install/restore cycle,
C3a PowerShell transition tests and laptop appearance/performance checks are not done. C3a cannot be accepted here:
no pwsh/powershell executable, original laptop DLL full-hash receipt not recovered from inspected local records
(local input and desktop chain are different hashes; never guess from them). No helper deployment attempted.
