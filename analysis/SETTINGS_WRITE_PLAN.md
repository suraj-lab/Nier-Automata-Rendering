# Real menu save/status continuation

Resumed by user request. Work remains offline; do not alter the installed candidate or game INI.
The preview remains a simulator until the real writer and observed-status boundary pass their gates.

## Accepted offline components

`checks/preset_rewrite.h` passed 437 assertions, native ASan/UBSan, two-TU linkage and MinGW
cross-build against the frozen contract/tests. A compiling no-op negative control failed before
implementation. Desktop worker `80a1a375` exceeded its time/fix boundary and entered ad-hoc diagnostic
loops; parent workflow `b1f8ef23-5660-4b58-a83c-3f5a459dacc9` was stopped before review. Its draft
was NOT imported. Frozen tests/production files were verified unchanged before lead edits; the
lead wrote the canonical implementation and the desktop model was unloaded.

`checks/startup_status.h` provides immutable terminal publication with release/acquire ordering.
32 concurrent stress rounds passed; actual extracted setter/bootstrap tests cover Native fallback,
patch/renderer failure, missing gate and thread-start failure. Source producers are connected, but
there is no UI consumer or observed backend/resource-dimension telemetry yet. A separate offline
DLL builds with 51 exports/49 forwarders, no D3D imports; it was not installed.

Luna review `456088bc-97f8-4bc7-9f4d-2771161a353b` found no issues and accepted ONLY those components.
Combined hashes, receipts and limitations: `runtime/settings-writer/checkpoint.json`. No real save
capability is implied.

The edit changes only Rendering/Preset and preserves unrelated bytes/comments and supported BOM/
newline formats. Duplicate/ambiguous structures and unsupported encodings fail without modifying
input or output. Invalid preset VALUES can be repaired; arbitrary malformed structures are not
silently reconstructed. Both input/output are capped at 64 KiB, without truncation.

## File-publish boundary: safety requirements to test next

Frozen boundary: `checks/SAVE_COMMIT_CONTRACT.md` and `checks/save_commit_cases.py` (13 scenarios).

**Writer implemented, accepted OFFLINE (Wine only):** `checks/settings_save.h`. Snapshot = presence,
bytes, volume serial + file index; refuses unreadable/directory/reparse/oversize. CREATE_NEW sibling
stage, write/flush/close checked, validated by the setter's real reader (`read_render_settings`, now
path-taking; startup behavior unchanged). Missing target: MoveFileExW without REPLACE_EXISTING;
existing: ReplaceFileW with a unique backup. After a failed publish the result is classified by
what is on disk, never by error code; final bytes are observed before reporting Committed.
`checks/test_settings_save.py` runs the real writer/reader under an isolated Wine prefix: 13 oracle
+ 6 extra cases pass, including a real ERROR_ALREADY_EXISTS creation race and a same-bytes file
swap. Five mutants (replace-on-create, no recheck, assume-untouched, ignore flush, bytes-only
identity) are each caught. Luna 92339044 blocked bytes-only rechecks; fixed; e9c37ee0 OK with notes.
Receipt: `runtime/settings-writer/save-io/validation.json`. Stage/backup names are unique but not
atomically reserved; owned backup deletion after success is best-effort. Not native Windows/NTFS ACL
evidence.

**Menu file state DONE (offline):** `checks/menu_state.h` adds FileState {Valid, Missing, Invalid,
Unreadable}, SaveOutcome {Committed, NotSaved, RecoveryRequired} and `complete_save(state, outcome,
observed file, observed next-launch mode)`: the caller re-reads the file after EVERY attempt, so a
stale failure never shows the old cached value. Invalid files can be repaired even when the edit equals
the Native fallback; Unreadable disables Save; RecoveryRequired is sticky for the session. Notice
priority: RecoveryRequired, ConfigUnreadable, SaveFailed, Unsaved, ConfigInvalid, RestartRequired.
Old constructor/`complete_save(bool)` are thin wrappers (existing preview unchanged). Desktop worker
100f6c5a implemented it against frozen `checks/menu_file_state_test.cpp` / `test_menu_file_state.py`
(passed first run; lead rerun 35M checks). Luna aeda98e0 accepted it and found that the LEAD's
contract let "Unsaved" hide an unreadable file; priority fixed, worker's original now fails the gate.
Preview still builds; 42 layout tests pass. The panel does not yet display the new notices.

**Step 4 (offline wiring) DONE:**
- `checks/menu_session.h` (desktop worker 994e30d0, frozen `menu_session_test.cpp`, 221 checks):
  startup snapshot -> session mode, Custom75 availability (off only after this build's patches
  failed) and exact reason text. Failed-session headline is "Not applied as configured".
- `checks/menu_settings_io.h` (lead): observe() = snapshot + real reader + codec dry run.
  Present-but-not-safely-editable is Unreadable. Snapshot/reader disagreement (file changed
  between them) re-observes once, then falls back to Unreadable. save() = writer + fresh observe.
  Wine: 13 oracle + 7 extra cases, each with a before/after menu-state table; deletion-race mutant
  caught.
- Panel: SaveReport callback; RecoveryRequired / ConfigUnreadable / ConfigInvalid notices; Repair
  label; failed save says "Next launch uses X" from the fresh read. Preview: 11 scenarios, F5 cycles
  simulated results; 66 native layout/click cases and 66 Wine D3D11 captures pass. Screenshots:
  `menu-preview/screenshots/file-states-sheet.png` and `*-file-100.png`, `recovery-100.png`.
- Luna 0f171a20 / 173314f5: OK with notes. Fixed: deleted file shown as Invalid (re-observe); notices
  hard-coding "Native" now show the observed next-launch mode. 66 layouts + 66 captures rerun pass.
- The preview's save is still simulated; the real writer is exercised only by the Wine harness.

**Next (step 5, needs user approval before any live test):** host the panel in the game DLL:
swapchain Present hook, window input, Insert toggle, construct State from the published startup
snapshot + observe(), real save via menu_settings_io. Develop/test offline first.

- Never call WritePrivateProfileString on the original file or truncate it in place. Capture an
  expected snapshot, stage/flush a complete sibling file, validate it with the actual reader, then
  publish. Missing-file creation must not replace a concurrently created file.
- Existing-file snapshots need identity/content checks; reject a detected external change instead
  of merging or overwriting it. A final path check is NOT an atomic compare-and-swap with an
  uncooperative external process. State this limitation rather than promising impossible locking.
- Preserve security/attributes, not only contents. In particular, CopyFile's documented copied
  security RESOURCE properties must not be mistaken for a blanket guarantee of DACL preservation.
  Reject reparse/directory/unreadable inputs rather than following an unexpected target.
- Microsoft documents ReplaceFile failure cases where the old file can move or disappear from its
  original name. Do not assume every false return means the original path is unchanged. The
  recovery/backup and post-commit error paths must be explicit/tested before connecting the UI.
  REPLACEFILE_WRITE_THROUGH is documented as unsupported; flushing the staged file is not a claim
  of universal power-loss durability or identical behavior on every filesystem.
- Save results must distinguish pre-commit failure, successful publish and recovery-required /
  post-commit uncertainty. The current bool-only simulated callback is not automatically sufficient
  for those outcomes. Never display an old cached enum as an observed on-disk saved value.
- Keep missing/invalid/unreadable metadata. Permit explicit repair of a readable invalid preset;
  never overwrite unreadable unknown contents, and don't disable repair just because the edit
  equals the Native fallback enum. These cases need UI-state gates as well as file tests.

Primary Win32 references inspected (indexed through context-mode):
- https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-replacefilew
- https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw
- https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-copyfilew
- https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers

## Observed startup status, separate from frame telemetry

The source now publishes the selected startup mode/validity and final observed patch/scale outcome,
not just a requested preset. Native bypass, failed setup, incomplete scale/gate application and
thread-start failure are distinct. Snapshot transport has release/acquire publication; the pending
UI integration must check readiness and metadata before constructing its session model. No patch
algorithm, AA mod or cap change was made. `NotApplied` means no reduced-scale write by this setter,
not a promise that every partially published instruction was rolled back or that another mod did
not alter rendering.

Do NOT report the setter's initial boot dimensions as actual render/output sizes. Backend/version,
GPU and real resource dimensions stay unknown until directly observed by a safe runtime seam.
Use the installed candidate's receipts only as historical evidence, not live menu telemetry.

Native Windows/ARM64 execution, real game attachment and live saving remain unverified/unimplemented.
