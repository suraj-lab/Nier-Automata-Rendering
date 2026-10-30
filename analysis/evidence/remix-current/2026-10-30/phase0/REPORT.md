# Phase 0 — reconcile repository, checkout, and deployed state

**Date:** 2026-10-30 (evening session)
**Objective:** establish one trustworthy starting point before any further renderer work: identify the current commit and
artifacts, prove the accepted candidate is reproducible from its source, run the full gate suite, verify the deployed
laptop and desktop state and the rollback paths, and mark stale planning documents.
**No game run, no install, no system change was made.** Desktop runs are unavailable by operator decision, so all
future runs are laptop runs.

Recommendation: **PROCEED** (to the laptop live-capture diagnostic), with two decisions requested at the end.

---

## 1. Repository state

| Item | Value |
| --- | --- |
| HEAD | `a7a3c0b6c02879d481ca7d36ecea078ae84b7ed8` (2026-10-30T13:03:26Z) |
| Branch | `main`, tracking `origin/main`, **1 commit ahead** (unpushed) |
| Dirty state at start | clean (`git status --porcelain` empty) |
| Submodules | none |
| Last pushed commit | `4f0a5f3` |

Commit `a7a3c0b` is the unaccepted CPU-only draw probe (`checks/draw_probe.h`, 4 Wine gates). It is deliberately
unpushed and is **not** the accepted candidate.

Changes made by this phase (documentation and tooling only, no compiled source):

- `README.md`, `VISION.md`, `analysis/ROADMAP.md`, `analysis/LIVE_IN_GAME_PLAN.md`: one dated staleness/supersession
  banner each; no historical text rewritten.
- `analysis/tools/pe_sections.py`: new, prints per-section SHA-256 of PE files (see §2).
- This report.

## 2. Candidate identity and reproducibility

### 2.1 Binary identities

| Artifact | SHA-256 |
| --- | --- |
| Tested/accepted live candidate, archived as `analysis/runtime/laptop-port/final-candidate/d3d11.dll` | `cee4d891154b39ba84d7964ecd63cd212d6f94e7aa62f9bdbf47444308738a93` |
| Rebuild of commit `4f0a5f3` (temp worktree) | `319ee42469682de3565779629edcd4249a59bee298c30a0099875e71cf637eb5` |
| Rebuild of commit `d22f3ea` (temp worktree) | `32e841300eec21baecf57d8be7cd11fe459692d19adb6caf265ff51d745c16c2` |
| Rebuild of the current tree `a7a3c0b` (in place, `analysis/runtime/menu-dll/d3d11.dll`) | `38cc1e7165db01a4e7df223859c6ddfe03a1713551e9fa7cdd8eae3a4bedafe7` |

`analysis/runtime/menu-dll/d3d11.dll` was already `38cc1e71` before this session and rebuilt to the same hash, so an
in-place rebuild *is* byte-reproducible.

### 2.2 Why the whole-file hash is not portable — and why the source is still reproducible

Rebuilding the same sources in a different directory produced a different whole-file hash. `.text` did not change:

```
file                         d3d11.dll(cee4d891)   d3d11.dll(4f0a5f3)   d3d11.dll(d22f3ea)   d3d11.dll(a7a3c0b)
sha256 (whole)   cee4d891154b39ba84d7  319ee42469682de35657  32e841300eec21baecf5  38cc1e7165db01a4e7df
.text             627d007f14286972f46e  627d007f14286972f46e  627d007f14286972f46e  837efce817a1405c759b  differs
```

`cee4d891` (the DLL that actually ran on the laptop) has the **same `.text`** as a rebuild of `4f0a5f3` and of
`d22f3ea`, whose compiled sources are identical (`git diff --stat d22f3ea 4f0a5f3` touches only
`analysis/deploy/laptop_port.py` and `analysis/checks/test_laptop_port_transport.py`). The current tree differs, as
expected, because it adds the draw probe.

Mechanism, measured rather than assumed:

1. Every build gets a different PE **image base**: `0x3755b1000` (repo tree), `0x2c8af1000` and `0x2b77a1000` (the two
   temp worktrees). The base tracks the output path, which is why in-place rebuilds match byte-for-byte.
2. All absolute pointers follow the base. Of 20,611 eight-byte words in `.rdata`, 2,988 differ between the two temp
   builds, and **every one of them differs by exactly the image-base delta `0x11350000`** (0 exceptions).
3. 10,939,580 of 15,537,852 bytes (70%) of the DLL are DWARF `.debug_*` sections contributed by the static
   libstdc++/libgcc objects, and those sections record the same absolute addresses, so they differ too.
4. No build path strings are embedded (`strings | grep -c` = 0 for the build directory in every artifact), and
   `.text` is identical, so no source difference is hidden in the mismatch.

Consequence for hash pinning: a whole-file hash proves "same source **and** same build directory". Source equality of
an arbitrary DLL must be judged on `.text`. `analysis/tools/pe_sections.py` prints exactly that table.

### 2.3 Gate receipts for `cee4d891`

Nine `analysis/runtime/*/validation.json` receipts reference `cee4d891…` and all report `passed: true`:
`remix-live`, `menu-overlay`, `live-camera`, `live-geometry`, `live-scene-target`, `live-alpha`, `live-late-material`,
`live-lights`, `live-hud`. The binary those receipts were produced from is still on disk at
`analysis/runtime/laptop-port/final-candidate/d3d11.dll`.

Note: those receipts were produced at 12:04–12:19, before `d22f3ea` was committed at 12:35, i.e. from a dirty tree
whose compiled sources are nevertheless identical to `d22f3ea`/`4f0a5f3` (proven by `.text` above). No unexplained
source difference exists.

## 3. Gate suite

Run with the repository's own runner (`full_suite_runner.py`, copied into
`analysis/runtime/phase0-reconcile-20261030/` so the previous receipt was not overwritten), including the explicit
header arguments for the camera/scene/scale tests.

- **57/57 pass**, 1,344 s of test time plus build time (~30 min wall), `passed: true`, `source_unchanged: true`
  (the runner hashes every `analysis/checks/*.{h,cpp,py}` before the run and re-checks after).
- 57, not 56, because `test_draw_probe.py` is new in `a7a3c0b`.
- Slowest: `test_live_geometry` 168 s, `test_live_camera` 124 s, `test_prepass_rule_captures` 99 s.
- Receipt: `analysis/runtime/phase0-reconcile-20261030/full-suite.json`; per-test logs `suite-*.log`.
- Limits: Wine/wined3d + Xvfb and mock games; no GPU, no Remix runtime, no NieR. Nothing here is a performance result.
- No mutation test was added or run in this phase; the suite's own gates were left untouched.

## 4. Deployed state

### 4.1 Laptop (`spaghetti`, Windows 11 on Arm, RTX Spark N1X)

| Item | Observed |
| --- | --- |
| Game folder | `C:\Program Files (x86)\Steam\steamapps\common\NieRAutomata` |
| `d3d11.dll` | `6ba266d64a8f67767700c535ee0c3c0596cf50280cf3e301e68518d8e3418b5a` — the original NIER_DLAA proxy ✔ |
| `ec_hooks.dll` | `c0abc71a9d529051773734cbc97e9ad9ff744eb5614581dcd8e5928f72486ca2` — present, not renamed ✔ |
| Files this project adds (`d3d11_dlaa.dll`, `NIER_RENDER.ini`, `steam_appid.txt`, `nier_render_fonts`, `NIER_ENV.ini`, `NIER_SCALE.log`, `NIER_CAPTURE`, `data\rtx-remix`) | all absent ✔ |
| Staged ARM64EC runtime `…\NieR-Laptop-Port\upstream-1.6.1-x64\d3d9_a64ec.dll` | `fff99d8f944514a6d7c576d9a7386b4b22d2388b58afe1d98ebba9f1fc2956df` — matches `LAPTOP_PORT.md` and the package's own crc manifest ✔ |
| Package zip | `7dd1d44492a609050e44b0e3581cec31135d1ed88b4a91123b4faae91955716a` — matches `LAPTOP_PORT.md` ✔ |
| Installed Toolkit runtime `.trex\d3d9.dll` / `.trex_arm64\d3d9.dll` | `ca71edf1…` / `460da8c4…` (ARM64 build, not loadable by the x64 game — as documented) |
| OS | 10.0.28000 (Windows 11) |
| GPU | NVIDIA RTX Spark N1X, driver 32.0.16.1769 |
| Power | **on battery** (`PowerOnline False`) — invalid for timing claims |
| Free space | 541.2 GB |

The laptop is in its original, restored state. No test deployment exists there.

### 4.2 Desktop (this machine)

| Item | Observed |
| --- | --- |
| Game install | `/mnt/second/SteamLibrary/steamapps/common/NieRAutomata` (a stale empty skeleton also exists under `~/.steam`) |
| Installed `d3d11.dll` | `065432e44e3b678d25bd8cbf3c8250b41142ce66d1590128c8c8af8dfdf8467e` — matches the newest install receipt |
| Chained `d3d11_dlaa.dll` | `3d628eb576b505180206653d72e4e4da6a4345334f19863256ab5b10e06b6915` |
| GPUs | Navi 48 (RX 9070 XT), Navi 21 (RX 6800 XT), Raphael iGPU — present; not used |
| Toolchain | `x86_64-w64-mingw32-g++` GCC 16.2.0, GNU ld 2.47.20260726 |

The desktop install is **not** stale; it is simply not usable for runs at the operator's direction. The desktop is
still the build and gate host.

## 5. Rollback paths

- `analysis/checks/install_live_dll.py` (desktop): dry run executed. It correctly **refuses** the current build —
  "candidate hash `38cc1e71…` is not the reviewed one" — because the staged DLL is the diagnostic draw-probe build.
  This is the intended behaviour and confirms the guard is live.
- `analysis/deploy/laptop_port.py restore`: read and verified — asserts the backup hash starts with `6ba266d6`, copies
  it back, removes only the `ADDED` names, undoes the `ec_hooks.dll` rename, and re-checks the restored hash. It was
  **not executed** today: the laptop folder is already original (§4.1), and executing a remote mutation to prove a
  no-op was judged unnecessary. The launcher transport path is covered by `test_laptop_port_transport.py` inside the
  57/57 suite.
- Desktop install receipt and restore material: `backups/live-scene-20261029T232758586690Z/{receipt.json,d3d11.dll,RESTORE.md}`,
  target `/mnt/second/…/d3d11.dll`, candidate `065432e4…`, previous `0e9b032b…`. Both binaries referenced by the
  receipt exist.

## 6. Documentation inconsistencies found

| Document | Claim | Reality (newest evidence) | Action |
| --- | --- | --- | --- |
| `README.md` | "Status refreshed 2026-10-28"; RTX Remix row "Not live in the game"; Remix-live row at 7.3 fps with no HUD/live stream | Live path-traced world with native HUD on 2026-10-29; laptop static composition on 2026-10-30 | Banner added, table left as-is |
| `analysis/ROADMAP.md` | "Finish the desktop build first, then port"; laptop renderer "via the bridge" | Port is at stage 2 (x64 and ARM64EC runtimes compose); no bridge needed; desktop runs paused | Banner added |
| `analysis/LIVE_IN_GAME_PLAN.md` | Presents the host as the build plan to execute | Host built and live-validated 2026-10-29 | Banner added, marked historical |
| `VISION.md` | Feasibility/risk language from 2026-10-27 | Superseded by live desktop and laptop evidence | Banner added |
| `PROGRESS.md` | Top checkpoint is correct and current | — | No change (it is the authority) |
| `analysis/PLAYABILITY_PLAN.md` | Ordering (picture before performance) still valid; no feasibility claim | — | No change |

Also noted: `PROGRESS.md` records the tested candidate as `cee4d891…` without saying that whole-file hashes are
directory-bound. Anyone rebuilding elsewhere gets a different hash and may wrongly conclude the source moved. §2 is
the answer to that; it belongs in `LAPTOP_PORT.md` when the next install is prepared.

## 7. Result

- One trustworthy starting point exists: HEAD `a7a3c0b`, clean, one unpushed commit, and the accepted candidate
  `cee4d891` is reproduced at source level from `4f0a5f3` (identical `.text`).
- 57/57 gates green on the current tree with source hashes unchanged during the run.
- Laptop and desktop deployments match their receipts; nothing was installed, launched, or altered.
- Stale documents are now marked rather than rewritten.
- Confounders: the gate suite is Wine/mock only; the laptop is on battery, so no timing statement from any run today
  or from the previous session is admissible; the draw-probe build in the current tree is a diagnostic and must not be
  installed as a candidate.
- **not** established: whether live capture can be reached in a real world on the laptop (Stage 3 still fails), and
  whether the draw probe explains why.

## 8. Decisions requested — item 1 DONE, item 2 open

1. **DONE 2026-10-30 evening — portable build hash.** `build_menu_dll.py` now links with
   `-Wl,--image-base,0x180000000 -Wl,--strip-debug`; the DLL is 4,242,383 bytes instead of 15,537,852 and rebuilds to
   the same whole-file SHA-256 in any directory. New gate `analysis/checks/test_build_reproducible.py` builds the same
   sources in two temp trees and compares the files. Two findings that belong in the record:
   - The image base was only half the story: **`objcopy`/`strip` rewrite the PE `TimeDateStamp` with the current
     time**, so the "strip and keep a `.debug` sidecar" route is non-deterministic by itself (`--no-insert-timestamp`
     is a linker option; objcopy has no equivalent). Stripping **via the linker** keeps the timestamp zero.
   - No `.debug` sidecar is shipped: the DWARF came from the static libstdc++/libgcc objects, nothing reads it
     (`read_minidump.py` resolves module+RVA), and it was 70% of the file. `.text` is unchanged by the strip (verified
     against an unstripped build of the same tree).
   - Consequence: the draw-probe diagnostic build is now `43bf86850ee56590c62f82cf68c59bea8731a0c3792f7bbc7bdbed865c54ba18`;
     the accepted live candidate stays `cee4d891…` (unstripped, built from `4f0a5f3`). Every earlier receipt refers to
     pre-change artifacts.
2. **OPEN — approve one short CPU-only diagnostic run on the laptop** (`NIER_DRAW_PROBE=1`, Remix forced off, ~90 s,
   you load a save and stand in the camp) to find out whether the draw hooks are reached at all. This is the cheapest
   discriminator for the Stage 3 failure and needs no GPU capture.

## 9. Commands run (all local or read-only remote)

```
git rev-parse HEAD; git branch -vv; git status --short; git log
python3 analysis/checks/build_menu_dll.py                          # in-tree, and in two temp worktrees (4f0a5f3, d22f3ea)
python3 analysis/tools/pe_sections.py <4 dlls>
python3 analysis/runtime/phase0-reconcile-20261030/full_suite_runner.py
python3 analysis/checks/install_live_dll.py                        # dry run only
sha256sum /mnt/second/…/NieRAutomata/d3d11.dll d3d11_dlaa.dll
ssh spaghetti … Get-FileHash (game folder, runtime, scratch); OS/GPU/driver/battery/disk inventory
```

Raw inventory output: `analysis/runtime/phase0-reconcile-20261030/` (suite logs + `full-suite.json`); the remote
inventory script is reproduced in §4 and was executed read-only.
