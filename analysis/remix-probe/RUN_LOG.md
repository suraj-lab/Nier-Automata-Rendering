# Remix probe run log

`run-facts.csv` lists 82 runs (regenerated 2026-10-30 from the `windows-*.json` receipts).

## Runs

| label | timed_out | seconds | captures | exe_sha256 | first stdout line |
|---|---|---|---|---|---|
| 2b-body-20261025T215648Z | true | 91.5 | 1 | cd0a2c88 | `main thread 30136` |
| 2b-head-20261025T212955Z | true | 92.2 | 0 | 8b6a1200 | `main thread 10008` |
| 2b-head-final-20261025T214755Z | true | 91.6 | 1 | 17e5bfff | `main thread 19588` |
| 2b-head-flat-20261025T213457Z | true | 91.4 | 0 | 00bff6fc | `main thread 11248` |
| 2b-head-tri1-20261025T213735Z | true | 91.3 | 1 | 28700606 | `main thread 28104` |
| ab-cutout-20261029T185402Z | true | 92.1 | 1 | 35bc46ae | `main thread 48440` |
| ab-materials-20261029T190109Z | true | 95.9 | 1 | 71385306 | `main thread 14964` |
| ab-nocutout-20261029T185609Z | true | 90.8 | 1 | 35bc46ae | `main thread 24108` |
| accum-early-20261026T231432Z | true | 26.7 | 1 | 24ed9a4a | `main thread 31056` |
| accum-late-20261026T231534Z | true | 90.6 | 1 | 24ed9a4a | `main thread 21124` |
| accum2-20261026T233452Z | true | 60.6 | 2 | 24ed9a4a | `main thread 8204` |
| attempt-20261025T150646Z | true | 90.4 | 0 | n/a | `n/a` |
| attempt-summary | none | 0.0 | 0 | n/a | `n/a` |
| bands-30632051-20261029T201653Z | true | 91.1 | 1 | f4de6636 | `main thread 29912` |
| bisect-393-20261025T213931Z | true | 91.3 | 1 | 2074821e | `main thread 24524` |
| bisect-591-20261025T214116Z | true | 91.5 | 1 | c2aa2df4 | `main thread 32632` |
| bisect-690-20261025T214302Z | true | 91.4 | 1 | 1e65623e | `main thread 15188` |
| bisect-786-20261025T214449Z | true | 91.0 | 1 | 69c2a5dc | `main thread 5224` |
| blend-bisect-20261026T223205Z | true | 26.4 | 1 | 9b62a7e1 | `main thread 32212` |
| capture-20261025T151744Z | true | 90.8 | 1 | n/a | `[94440140] begin InitializeLibrary` |
| captured-sun-30632051-20261029T202310Z | true | 91.1 | 1 | 15911e71 | `main thread 50956` |
| control-f14-20261030T081741Z | true | 60.6 | 1 | 771dd782 | `main thread 13420` |
| control-triangle-20261025T213303Z | true | 91.3 | 1 | 99eabd78 | `main thread 22608` |
| dbgimg-20261026T233643Z | false | 14.2 | 0 | 24ed9a4a | `main thread 22316` |
| diagnostic-20261025T151136Z | true | 91.2 | 0 | n/a | `[94072781] begin InitializeLibrary` |
| fallback2-tex-20261026T222632Z | true | 30.6 | 1 | a67bb1b8 | `main thread 24524` |
| flip-normals-20261026T222759Z | true | 31.1 | 1 | 9c14b18e | `main thread 35336` |
| fps-180p-20261026T234213Z | true | 30.5 | 1 | 24ed9a4a | `main thread 25940` |
| fps-onedraw-20261026T234329Z | true | 25.3 | 1 | 24ed9a4a | `main thread 17320` |
| full-tex-v3-20261026T221100Z | true | 91.2 | 1 | 2e8ceac0 | `main thread 25564` |
| interop-20261026T234535Z | true | 12.9 | 1 | 53566513 | `main thread 34948` |
| lit-v1-20261026T221354Z | true | 61.1 | 1 | 26f6b5ac | `main thread 33540` |
| lit-v2-20261026T221548Z | true | 45.6 | 1 | 26f6b5ac | `main thread 14200` |
| lit-v3-20261026T221759Z | true | 30.4 | 1 | 26f6b5ac | `main thread 28932` |
| lit-v4-20261026T221919Z | true | 30.7 | 1 | 26f6b5ac | `main thread 34432` |
| lit-v5-opaque-20261026T222048Z | true | 31.3 | 1 | df4b857a | `main thread 28824` |
| lit-v6-notex-20261026T222202Z | true | 30.4 | 1 | df4b857a | `main thread 26116` |
| lit-v7-sun3-20261026T222340Z | true | 31.1 | 1 | a2af9fac | `main thread 27572` |
| main-stack-20261025T160523Z | true | 90.8 | 1 | d859f744 | `main thread 25492` |
| mat-none-20261026T222518Z | true | 31.0 | 1 | a67bb1b8 | `main thread 31048` |
| mat-triangle-20261026T223055Z | true | 25.9 | 1 | 69855565 | `main thread 10832` |
| modes-check-20261026T222922Z | true | 20.9 | 1 | d5640adc | `main thread 27344` |
| no-ngx-20261025T161508Z | true | 90.4 | 1 | d859f744 | `main thread 21084` |
| nrd-hist-20261026T232146Z | true | 91.1 | 1 | 24ed9a4a | `main thread 13848` |
| nrd-off-20261026T232405Z | true | 90.5 | 1 | 24ed9a4a | `main thread 29740` |
| nvidia-sample-20261025T155103Z | true | 90.8 | 0 | ee4d5b20 | `n/a` |
| nvidia-sample-rerun-20261025T160041Z | true | 90.4 | 0 | ee4d5b20 | `n/a` |
| one-draw-tex-20261026T220902Z | true | 91.1 | 1 | 2e8ceac0 | `main thread 33008` |
| optdump-20261026T233304Z | true | 40.7 | 1 | 24ed9a4a | `main thread 11224` |
| prepresent-20261026T233118Z | true | 60.8 | 1 | 24ed9a4a | `main thread 18784` |
| reference-20261025T152812Z | true | 90.9 | 1 | n/a | `[95068562] begin InitializeLibrary` |
| replace-f14-20261030T081633Z | true | 60.7 | 1 | 771dd782 | `main thread 46812` |
| replace-f4-20261030T081524Z | true | 61.6 | 0 | 771dd782 | `main thread 20616` |
| replace-f8-20261030T081857Z | true | 60.7 | 1 | 771dd782 | `main thread 13100` |
| replace1-f14b-20261030T082211Z | true | 60.7 | 1 | 53e1e0aa | `main thread 49232` |
| replace2-f14-20261030T082041Z | false | 16.1 | 0 | 53e1e0aa | `main thread 47936` |
| replace3-f14-20261030T082103Z | true | 60.6 | 1 | 53e1e0aa | `main thread 26512` |
| s416-live-20261030T094419Z | true | 94.1 | 1 | e23dedeb | `main thread 36212` |
| s416-noalb-20261030T094806Z | true | 90.5 | 1 | e23dedeb | `main thread 42000` |
| s416-sunq-20261030T094614Z | true | 90.5 | 1 | e23dedeb | `main thread 42396` |
| sample-control-20261025T164041Z | true | 90.3 | 1 | ee4d5b20 | `n/a` |
| sampler-20261025T160334Z | true | 90.8 | 1 | a1e7252f | `main thread 29588` |
| scene-full-20261025T223115Z | true | 90.8 | 1 | 1a175d7c | `main thread 516` |
| scene-full-nosky-20261025T223359Z | true | 91.7 | 1 | 437f1144 | `main thread 20364` |
| scene-hold-20261025T222059Z | true | 90.6 | 1 | 326bc36b | `main thread 8272` |
| scene-oracle-20261025T221530Z | true | 91.5 | 0 | 326bc36b | `main thread 28244` |
| scene-oracle2-20261025T221743Z | true | 90.6 | 0 | 326bc36b | `main thread 29540` |
| scene-v2-20261025T225509Z | true | 91.6 | 1 | e969d2ee | `main thread 28196` |
| skin2-cpu-20261030T095202Z | true | 60.9 | 1 | b9ff45dc | `main thread 41468` |
| skin2-gpu2-20261030T095306Z | true | 61.1 | 1 | b9ff45dc | `main thread 28616` |
| skin2-gpu4-20261030T095411Z | true | 60.4 | 1 | b9ff45dc | `main thread 52608` |
| sky-dds-fixed-20261029T213157Z | true | 91.2 | 1 | 2009269e | `main thread 46136` |
| sky-denoise-20261026T230032Z | true | 46.2 | 1 | 224de2a7 | `main thread 29588` |
| sky-denoise-v2-20261026T230226Z | true | 45.5 | 1 | 224de2a7 | `main thread 25696` |
| sky-fill2b-20261029T220243Z | true | 90.9 | 1 | 2009269e | `main thread 45244` |
| sky-hdr512-20261029T211735Z | false | 20.7 | 0 | 2009269e | `main thread 44360` |
| sky-v3-20261026T230349Z | false | 9.5 | 0 | 224de2a7 | `main thread 32124` |
| sky-v4-20261026T230555Z | false | 9.2 | 0 | 224de2a7 | `main thread 11836` |
| still-v1-20261026T223556Z | true | 76.3 | 2 | 05f48865 | `main thread 12528` |
| textured-blend1-20261026T223323Z | true | 31.3 | 1 | 8f1604a3 | `main thread 12556` |
| textured-blend2-20261026T223438Z | true | 30.5 | 1 | 8f1604a3 | `main thread 28932` |
| window-close-20261025T154814Z | true | 91.0 | 1 | e3361ad3 | `[96271203] begin InitializeLibrary` |

## Notes

- 76 of the 82 runs report `timed_out = true` (the `--hold` watchdog ends most runs; not a crash).
- `captures` counts Remix's own post-tonemapping DDS files.
- 2026-10-30 runs: `replace*`/`control-f14` = mesh replacement modes (analysis/MESH_REPLACEMENT.md); `s416-*` = frame_41686139 sun/albedo; `skin2-*` = 2-bone GPU skinning.
