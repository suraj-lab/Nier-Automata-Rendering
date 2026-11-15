# A1 resource validation — accepted substep, deduplication still open

Plan A1.1/A1.3/A1.4; no rendering defaults changed. `pack_capture.py` now refuses missing/truncated selected IB/VB/
VS-CB/PS-CB resources and missing declared positive texture IDs before writing outputs. Numeric/range/path checks
refuse invalid scalar metadata, unsafe output names, missing capture roots and output within immutable raw captures.
Texture id0 remains unbound even if a stray tex_0 file exists. Negative base_vertex is legal within signed32 range.
Selected-out draws do not require unused resources; index_count is validated before selection.

Delegated worker dfca5933, explicit openai-codex/gpt-6-luna: implementation in pack_capture.py only. Frozen gate
SHA256 `2aa1dfc153c6d65b64ae4d00f1705b4e22d1e1c6aa3046c1a87e9cfc146d732f` unchanged; lead red missing IB, worker green,
lead reran. Lead hidden negatives exposed missing-root/raw-output/type/name/texture0 cases, fixed after red.
Reviewer b760c1d3 identified validation before filtering; hidden red case fixed. Follow-up b25e4aeb correctly
confirmed scalar ordering, but its claimed failing draws==1 assertion is REJECTED: fixture has TWO draws and only
`draw_0000/capture.json` is changed to layout_found0; unchanged draw_0001 is packed. Gate actually passes. No test
was weakened to accommodate that false positive.

`runtime/a1-validation-mutations.json`: four rejected mutations (under-count IB bytes, ignore short VB, merge GPU
identities by equal bytes, allow writes into raw). All restored; both gates green. Full suite
`runtime/suite-s75-a1/full-suite.json`: **119/119**, source_unchanged=true,248.9s; extra replay-source identity checks
also unchanged (`a1-source-sha256.json`). Reviewer did not run tests; lead owns all run evidence.

## Valid-input compatibility and required replay checks

Before control: `runtime/a1-validation-control/receipt.json`. After control:
`runtime/a1-validation-candidate/receipt.json`. Both captures preserve the entire manifest except the new cbblob
output path and preserve CB blob bytes exactly. Buffer IDs and inode-based mappings are unchanged.

Exact commands and metric ordering in `runtime/a1-validation-replays/receipt.json`; both runs use software Wine
fake runtime, --isolated-prefix --frames400 --frame-ms16 --env REPLAY_EXIT=clean. Not GPU/game performance evidence.

| Capture | Meshes | Frame200 instances | Unique mesh triangles | Frame200 instance triangles | Textures | Lights | Final materials |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| desert67279062 |183|183|747517|747517|163|5|69|
| pond67078468 |347|745|638064|887306|320|7|117|

Both400/400presented,exit0,errors=[],forced_pids=[];36.7s/40.7s total (not benchmarks). All metrics match historical
controls, unlike the rejected content-dedup candidate. Baseline DLL hash remains f6c3b0ba0fd80c1719e8283ac119b6dba160613315eab3734644fe3c21d40cdc.

All51,743raw files rehashed after validation/replays:22,380files/5,813,513,277B desert and29,363files/14,317,920,437B
pond. Exact original local manifests match;4.889s/10.291s hash observations. Receipt:
`runtime/a1-validation-replays/raw-after-validation-replays.json`. No raw write/relink/normalization/retransfer.
Remote source hashes remain UNVERIFIED. Texture validation is existence only here, not a full DDS integrity parser.

## Remaining A1 dependency (do not call parent done)

Content canonical files112/170 are all distinct, and every draw snapshot matches one; frame.bytes equals canonical
buffer bytes + CB bytes, with0skipped and0link fallbacks. This recovers byte payload provenance locally, not permission
to merge the current replay's GPU logical identities. The replayer creates a GPU buffer per manifest ID and the
proxy's geometry key uses its pointers. Replacing copied snapshots2795/3537with112/170GPU objects already failed
required mesh/triangle accounting. Scout ef167215 Luna corroborated this identity/storage distinction; did not
provide an implementation that passes both requirements. No accepted dedup implementation is claimed.

A1.2/A1.3 dedup acceptance needs an authoritative per-draw source alias/identity map and a design proven to retain the
plan's accounting (or an explicitly approved disposition if those requirements conflict). Do not infer it from
bytes alone or quietly loosen the counts. Source-hash verification needs approved laptop access. Batch those into
session card rather than repeat the failed spike or change unrelated core keys. Shared-ledger sync pending; all
receipts retained locally.
