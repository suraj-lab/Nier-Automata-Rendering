# Filesystem save: next frozen boundary

**Specification/test skeleton only. No filesystem writer is implemented by these files.**
The accepted codec (`preset_rewrite.h`) changes bytes; it does not provide persistence guarantees.

## Outcomes

- `PreCommitFailure`: this attempt did not publish. Report the reason and keep the edited selection.
  A stale snapshot means the external file is preserved, NOT that the cached saved enum is still true.
- `Committed`: a complete supported file was published and observed at the target. Only this outcome
  may acknowledge a successful save to the menu. Active rendering is never changed.
- `RecoveryRequired`: publication/recovery state is uncertain or the old target moved. Do not report
  ordinary save failure with “old value still on disk”. Return surviving recovery paths, preserve
  their contents, and require re-observation/manual recovery before claiming a saved preset.

The eventual result includes target/backup observations and a diagnostic stage/code. This is not
compatible with blindly feeding every false Win32 return into the existing bool-only preview callback.

## Required sequence / invariants

1. Read a bounded regular-file snapshot (or positively observe missing). Reject unreadable, reparse
   or directory targets. Record identity and bytes; never treat a fallback mode as saved-file content.
2. Rewrite in memory with the accepted codec. Unsupported/ambiguous input fails without file changes.
3. Create an owned sibling stage without overwriting existing files, establish required security
   before putting original contents there, write the whole result, flush, close/check errors, and
   verify it with the actual startup reader. Never truncate the original.
4. Recheck expected identity/content/presence before publishing. Detected external edits fail closed.
   For a missing target, publication must atomically fail if another file now exists; no replace flag.
5. Existing-file replacement must have a deliberate original-data recovery path and preserve metadata/
   security. Inspect the documented partial-failure states; don't infer old-path preservation from
   `ReplaceFileW == FALSE`. Never overwrite a pre-existing foreign backup/stage/recovery file.
6. Clean up only positively owned, no-longer-needed artifacts. On uncertainty preserve recovery data.
   A failed flush, close, validation, security setup or publish must never produce a success notice.

## Frozen scenario oracle

`save_commit_cases.py` supplies fixture bytes, fault/external-change points and expected observations.
It is an oracle for a future Win32/fault-injection adapter, NOT a fake writer implementation. Its
self-check tests only the oracle's acceptance/rejection rules; it must report `writer_executed=false`.

The adapter must use fresh fixture directories below `analysis/runtime/settings-writer/`, never the
game directory or another Wine prefix. It must execute actual candidate save code, not fabricate the
expected dictionaries. Add real Win32/Wine cases alongside deterministic API-failure injection.

## Limits that must remain explicit

A final path/snapshot recheck is not a true compare-and-swap against uncooperative external writers.
Specify the supported single/cooperating-writer model and do not claim that all racing replacements
are prevented. Staging plus flush is not universal power-loss durability. DACL/security preservation,
partial replacement recovery and native Windows/ARM64 behavior require their own evidence. No game
attachment, live save or deployment is authorized by this contract.
