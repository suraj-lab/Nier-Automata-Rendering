# Research C: laptop ops, unattended desktop runs, exit hang, terrain mips, play logs, D1 constraints

Task label: laptop_ops_recon. Phase: Research. Items: C1, C2, C3, D1 and the machinery around them.
Method: read-only. Files, source, logs and read-only system state (sysfs, `ps`, `lspci`, `sha256sum`, `lms ps`,
`git status --short`). No ssh, no build, no game or replay run, no writes outside this file.
Paths: `analysis/` is the project `analysis/` folder. `runtime/src/dxvk-remix/` is the Remix source in use.
Times in desktop file metadata are UTC. Laptop log times are laptop local time (no zone given).
UNVERIFIED marks anything I could not check from here.

---

## 0. Summary of what matters most

1. **The real desktop save changed after the last logged desktop run.** `GameData.dat` in the real Proton
   prefix has SHA-256 `b03f8782…`. The backup and every run summary say `7ad73ae8…`. Its mtime is
   2026-11-14 08:14:04 UTC, which is inside the laptop play session (08:13–08:19). The last desktop run ended
   07:53:11 UTC (`runtime/game-runs/ab-noterrain/summary.json`). No run log explains the change. Steam Cloud is a
   likely cause (`steam_autocloud.vdf` mtime 08:19). UNVERIFIED. The plan says "save never touched". See §3.5.
2. **`laptop_port.py install` does not set `ec_hooks.dll` aside.** Only `run --no-ec-hooks` does, and only for
   that run. The play setup was done by hand (PLAN_2026-11-13.md:2100-2101). C3 is still open.
3. **Two script hazards for C1.** `restore` deletes `NIER_SCALE.log` and `data\rtx-remix` unless someone copies
   them first. A plain `run` (no `--steam`) deletes `NIER_ENV.ini`. See §1.4.
4. **Terrain bakes are single-mip 512×512 files.** Remix warns on each one. The fix is a mip chain. The repo's
   own game-texture writer already does this, so it can be copied. Gate and size math in §5.
5. **Laptop play (08:13–08:19):** median 17.0 fps over 75 stats windows (nearest-rank p10 14.1, p90 19.8).
   Median readback is 50.6 ms of a 58.7 ms frame. The `qualityDLSS` value the run used is `1`, which is
   `MaxPerf` in the source enum, not "Performance". See §6.

---

## 1. (a) `analysis/deploy/laptop_port.py` and its files

### 1.1 Subcommands

| Command | What it does | Evidence |
| --- | --- | --- |
| `install` | Backs up the laptop's `d3d11.dll` (must start with `6ba266d64a8f6776`), moves it to `d3d11_dlaa.dll`, copies our proxy in as `d3d11.dll`, adds `nier_render_fonts`, `NIER_RENDER.ini` (`[Rendering] Preset=Native`), `steam_appid.txt` (`524220`), the scene files, and restores the Remix consent file if one was kept. Refuses if any `ADDED` name already exists in the game folder. | `laptop_port.py:95-124`; ADDED check `:106`; prefix check `:102` |
| `run <label> [flags]` | Stages the env, writes `launch-<label>.cmd`, registers and starts a scheduled task `NieRPort` (LogonType Interactive, RunLevel Limited), waits `--seconds` (default 90), kills only the PIDs it saw, copies logs back, writes a JSON receipt. | `:127-208`; task `:174-177`; start `:181`; kill `:185-190`; receipt `:197-199` |
| `restore` | Refuses while NieR runs. Checks the backup starts with `6ba266d64a8f6776`, copies it back, moves `KEEP` items to `WORK\kept\<stamp>`, deletes `ADDED`, renames `ec_hooks.dll.off` back, checks the hash. | `:211-228`; KEEP `:53`; ADDED `:46-47`; delete `:224`; ec `:225` |
| (no argument) | Prints the docstring and exits. | `:231-245` |

### 1.2 `run` flags

| Flag | Effect | Evidence |
| --- | --- | --- |
| `--remix` | `NIER_REMIX=1`; `RTX_HIDE_SPLASH_MESSAGE=1`; `NIER_REMIX_RUNTIME` (default the Toolkit x64 `.trex\d3d9.dll`, `RUNTIME` `:44`); `NIER_REMIX_SCENE=WORK\scene\scene.bin`. Without it `NIER_REMIX=0`. | `:132-140` |
| `--live` | Implies `--remix`. `NIER_REMIX_LIVE=1`, `NIER_REMIX_LIVE_TEX=WORK\live-textures`, `NIER_REMIX_LIVE_STATS_EVERY=60`. | `:130`, `:156-157` |
| `--steam` | Writes `NIER_ENV.ini` from the env dict and starts the game with `steam.exe -applaunch 524220`; waits 20 s. | `:158-162`, `:170-171`, `:184` |
| `--no-ec-hooks` | Renames `ec_hooks.dll` to `ec_hooks.dll.off` before the launch and back after it. | `:169`, `:191` |
| `--seconds N` | Run length, default 90. | `:238` |
| `--runtime <dll>` | Overrides `NIER_REMIX_RUNTIME`. Doc says pass the official `d3d9_a64ec.dll` for the ARM64EC renderer. | `:11-12`, `:140` |
| `--capture` | Needs `--live`. `NIER_REMIX_CAPTURE_COMPOSITE=WORK\composite.raw`. | `:153-155` |
| `--options-doc` | Needs remix. `DXVK_DOCUMENTATION_WRITE_RTX_OPTIONS_MD=1`. | `:150-152` |
| `--rtx-conf FILE` | Needs remix. Copies FILE to `WORK\rtx-<label>.conf` and sets `DXVK_RTX_CONFIG_FILE` to it. | `:145-149` |
| `--env KEY=VALUE` | Repeatable. Key must start with `NIER_`, value non-empty, no `"`. | `:141-144` |
| `--draw-probe` | `NIER_DRAW_PROBE=1`. Cannot combine with `--remix`/`--live`. | `:131`, `:133-134` |
| `--rehook` | `NIER_DRAW_PROBE_REHOOK=1`. Needs `--draw-probe`. | `:135-137` |
| `--steam` plus `--no-ec-hooks` | Both allowed. | `:169`, `:160` |

The label is `cmd[1]`, so it cannot be a flag (`:239`). Only one `--rtx-conf` and one `--runtime` are read
(`:241-242`).

### 1.3 What it copies, and where (laptop paths)

| Laptop path | Source | Set by | Evidence |
| --- | --- | --- | --- |
| `C:\Program Files (x86)\Steam\steamapps\common\NieRAutomata\` (`GAME`) | — | all | `:40` |
| `C:\Users\suraj\Downloads\NieR-Laptop-Port\` (`WORK`) | — | scratch, backup, staged scripts | `:42` |
| `WORK\backup\d3d11.dll` | game `d3d11.dll` (original) | install | `:103-105` |
| `WORK\d3d11.dll` | `runtime/menu-dll/d3d11.dll` (our proxy) | install, then moved into the game folder | `:37`, `:108`, `:116-117` |
| `WORK\nier_render_fonts\` | `runtime/menu-dll/nier_render_fonts` | install | `:38`, `:109`, `:118` |
| `WORK\scene\scene.bin`, `scene_sky.dds`, `nier_sky_hdr.dds`, `scene_textures\` | `runtime/remix-probe/textured-scene/` | install | `:39`, `:110-112` |
| game `d3d11_dlaa.dll` | the original DLAA proxy | install | `:116` |
| game `NIER_RENDER.ini` | written inline | install | `:119` |
| game `steam_appid.txt` | written inline (`524220`) | install | `:120` |
| game `data\rtx-remix\logs\.sentry-native\user-consent` | newest `WORK\kept\*\user-consent` | install | `:121-122` |
| game `NIER_ENV.ini` | written (with `--steam`) or deleted (without) | run | `:170-171` |
| `WORK\launch-<label>.cmd` | generated `set "K=V"` lines plus `start NieRAutomata.exe` (or the steam line) | run | `:160-163`, `:172-173` |
| `WORK\remix-dxvk-<label>.log` (copied back to `runtime/laptop-port/`) | game `data\rtx-remix\logs\remix-dxvk.log` | run | `:192-193`, `:200-202` |
| `runtime/laptop-port/<label>-<stamp>.json` | receipt: pids, task result, power state, the NIER_SCALE.log text appended during the run, crash dumps | run | `:164-199` |

The receipt holds only the NIER_SCALE.log lines written during the run (offset `:167`, read `:194`). It does not
record the DLL hash.

### 1.4 Hash pinning and transport

| Check | Value | Evidence |
| --- | --- | --- |
| Our proxy, full SHA-256 computed locally | `sha(DLL)` | `:96` |
| Game's original `d3d11.dll` (prefix match only, 16 hex chars) | `6ba266d64a8f6776` | `:45`, `:102`, `:216` |
| Backup copy equals the original | hash compare | `:104-105` |
| Transfer to laptop equals local | `transfer hash mismatch` | `:115` |
| Installed equals ours | `installed hash mismatch` | `:123` |
| Restore: backup is original | `backup is not the original` | `:216` |
| Restore: result equals the hash recorded at install | `restore hash mismatch` | `:226-227` |

Transport: every PowerShell job is written as a UTF-16 file with a BOM, copied with `scp` to
`WORK\nier-ps-<hash>.ps1` (`:61-67`), run with `ssh … powershell -NoProfile -NonInteractive -ExecutionPolicy
Bypass -File <path>` (`:70-71`), and deleted (`:74-75`). All ssh and scp calls use
`-o BatchMode=yes -o ConnectTimeout=10` (`:54`). Host: `NIER_LAPTOP_HOST`, default `spaghetti` (`:41`).
The comment at `:41` says the desktop reaches the laptop only by address (`suraj@100.114.109.95`).

Current state of the laptop (from the plan, not checked here): our build `9555829d…` is installed,
the DLAA proxy is at `d3d11_dlaa.dll`, `ec_hooks.dll.off` was set aside by hand (PLAN_2026-11-13.md:2093-2105).
UNVERIFIED: no ssh was used.

### 1.5 Hazards found by reading the script (not run)

| # | Hazard | Evidence | Effect |
| --- | --- | --- | --- |
| H1 | `run` without `--steam` deletes an existing game `NIER_ENV.ini`. | `:170-171` | Breaks a Steam play setup until it is re-placed. |
| H2 | `run --no-ec-hooks` renames `ec_hooks.dll` without a test. The script runs with `$ErrorActionPreference='Stop'`. If `ec_hooks.dll` is already gone (set aside by hand), the rename throws before launch. | `:165`, `:169` | UNVERIFIED by running. Read from the code. |
| H3 | `restore` deletes `NIER_SCALE.log`, `data\rtx-remix`, `RtxOptions.md`, `rtx.conf`. Only `run` copies `remix-dxvk.log` out first. A Steam play session has no copy step. | `:46-47`, `:224`; copy only `:192-193`, `:200-202` | A C1 play session loses its proxy and Remix logs at restore. Copy first. |
| H4 | `install()` never touches `ec_hooks.dll`. The only mentions are in `run` (`:168-169`, `:191`) and `restore` (`:225`). | grep of the file | C3's "install sets it aside" is not implemented. |
| H5 | No LM Studio unload in this script. | no `lms` string in the file | `run_remote.py` does it, `laptop_port.py` does not. See §2.4. |
| H6 | Default host `spaghetti` depends on name resolution. | `:41`; `~/.ssh/config` has `Host spaghetti` / `HostName spaghetti` | See §2.3. |
| H7 | The receipt does not record which DLL ran. | `:197` | Runs cannot be tied to a DLL hash after the fact. |

### 1.6 Other files in `analysis/deploy/`

| File | What it is | Evidence |
| --- | --- | --- |
| `deploy/README.md` | Documents `nier_upscale.sh` (the desktop FSR4 install), not `laptop_port.py`. Nothing in it covers the laptop. | `deploy/README.md:1-27` |
| `deploy/nier_upscale.sh`, `test_nier_upscale.sh`, `NIER_RENDER.ini.example` | Desktop FSR4 upscaler install and its test. Not laptop. | `deploy/README.md:3-19` |
| `deploy/laptop-NIER_ENV.ini` | Six settings for a Steam launch: `NIER_REMIX=1`, `NIER_REMIX_LIVE=1`, the Toolkit runtime, the scene, the live texture folder, stats every 60. Its header says it was "installed by deploy/laptop_port.py + this file". No code in `laptop_port.py` copies it. The laptop log says "NIER_ENV.ini: 6 settings applied" (`NIER_SCALE.log` line 1 of the play session). | `deploy/laptop-NIER_ENV.ini:1-9`; grep finds no copy step |
| `deploy/rtx/desktop-replay.conf` | Replay conf (`replay/run_replay.py:105` default). XeSS (`rtx.upscalerType = 4`), `dlssPreset = 2`, the replay GPUs are AMD. | `deploy/rtx/desktop-replay.conf:1-8`; `replay/run_replay.py:105` |
| `deploy/rtx/game.conf` | Desktop in-game conf. Installed as the game folder's `rtx.conf` (hash `2ae1ac7a…` matches). The proxy points Remix at the `rtx.conf` beside its DLL when `DXVK_RTX_CONFIG_FILE` is empty. | `deploy/rtx/game.conf:1-4`; `checks/remix_live.cpp:752-761` |
| `deploy/rtx/laptop-a-fg-off.conf` | Laptop run A: frame generation off. Its comment explains the NOLEGACY keyboard issue. | `:1-2`, `:4-9` |
| `deploy/rtx/laptop-b-dlss-perf.conf` | Laptop run B: run A plus `dlssPreset = 2`, DLSS fixed scaling. Has the enum table. | `:1-9` |
| `deploy/rtx/laptop-c-fast.conf` | Laptop run C: run B with the cheapest path-traced frame (`graphicsPreset` 4 Custom). | `:1-6` |
| `deploy/rtx/laptop-game.conf` | The laptop's play conf: B plus Ray Reconstruction plus the L1 grade. `qualityDLSS = 0` (UltraPerf) since the 08:29 edit. The play run read `qualityDLSS = 1`. | `laptop-game.conf:4-10`; `remix.log:26,62` |

The mtime of `laptop-game.conf` is 2026-11-14 08:29. The play session ran 08:13–08:19. So the play used `qualityDLSS = 1`
(§6.4). The edit to `0` came after the play.

---

## 2. (b) `LAPTOP_PORT.md`, the laptop facts, and `remix-probe/run_remote.py`

### 2.1 Laptop facts (`LAPTOP_PORT.md:9-18`, written 2026-10-29)

| Item | Value | Evidence |
| --- | --- | --- |
| OS | Windows 11 Home 10.0.28000, ARM64 | `LAPTOP_PORT.md:9` (table) |
| GPU | NVIDIA RTX Spark N1X, 6144-core Blackwell, driver 32.0.16.1769 | `:12` |
| Device memory seen by Remix | Heap 0 40,946 MiB; heap 1 11,644 MiB | `remix.log:117,121` |
| Python | 3.14 ARM64 | `:11` |
| NieR | `C:\Program Files (x86)\Steam\steamapps\common\NieRAutomata` | `:13` |
| Portal RTX | installed in the same Steam library | `:14` |
| Remix runtime paths | `.trex\d3d9.dll` (x64, Machine 8664); `.trex_arm64` (AA64, rejected by x64: error 193) | `:87-126` (correction), `:197-200` |
| Official x64 renderer | `upstream-1.6.1-x64\d3d9_a64ec.dll`, SHA-256 `fff99d8f…` | `:200-212` |

### 2.2 What can and cannot be done over ssh

| | Can | Cannot / limited | Evidence |
| --- | --- | --- | --- |
| Transfer | `scp` files, staged PowerShell with `-File` | `-EncodedCommand`/stdin hung three times with no side effects | `LAPTOP_PORT.md:283-292` |
| Game window | A scheduled task with LogonType Interactive started the game, and the user saw it | `start`, `schtasks /it`, `explorer <file>` produced no visible window (tested 2026-11-13). sshd runs in session 0. | `LAPTOP_PORT.md:139`; `PLAN_2026-11-13.md:1914-1917`; `laptop_port.py:174-181` |
| Remix logs | `remix-dxvk.log` copied back by `run` | `NIER_SCALE.log` and `remix.log` are not copied by `run` | `laptop_port.py:192-202` |
| Power | battery and plugged state recorded in the receipt | — | `:178-180` |

Reconcile: the Interactive scheduled task is not the same mechanism as the `schtasks /it` test in
`PLAN_2026-11-13.md:1914-1917`. LAPTOP_PORT.md:139 says the user saw the game run. UNVERIFIED which mechanism is
the working one today.

### 2.3 Name resolution

- `~/.ssh/config` has `Host spaghetti` with `HostName spaghetti` (the alias has no IP). Read: `~/.ssh/config:1-2`.
- `getent hosts spaghetti` returned nothing (checked 2026-11-14).
- `tailscale status` lists `100.114.109.95  spaghetti  …  active; direct 192.168.1.11:41641`.
- So `spaghetti` works only through Tailscale name resolution. UNVERIFIED now (no ssh used).
- `PLAN_2026-11-13.md:1912-1913` says the name did not resolve on 2026-11-13.

### 2.4 `analysis/remix-probe/run_remote.py`

- Purpose: run the built probe once on the laptop with a 90 s watchdog. Copies back stdout, stderr and Remix's own
  screenshot, never a desktop capture. (`run_remote.py:2-7`.)
- Modes: `--sample` (NVIDIA's RemixAPI_C control build, 16 frames), `--mesh`, `--scene` (`:37-41`, `:62-72`).
- Paths: laptop folder `C:\Users\suraj\Downloads\NieR-Remix-Probe-20261025T144235Z` (`:20`); runtime
  `…\RTX Remix\deps\remix_runtime\runtime\.trex\d3d9.dll` (`:21`); local output `runtime/remix-probe` (`:19`).
- Transport: `ssh spaghetti powershell -EncodedCommand …` (`:25-31`). The host is hard-coded `spaghetti`
  (`:27`), and `scp` targets `spaghetti:` as well.
- **LM Studio unload before GPU work:** `:121-127`. It runs `lms ps` on the laptop and, if any model is loaded,
  `lms unload --all` (`:126`). Skip it with `--no-unload` (`:56`). Reason in `remix-probe/README.md:28-29`: a
  loaded 35B model holds about 24 GB of unified memory and competes with the renderer.
- Watchdog: `--watchdog` default 90000 ms (`:57`); after it, the probe process is killed.

**Desktop equivalent:** nothing in `run_replay.py`, `game_run.py` or `laptop_port.py` unloads a local model.
The desktop has one loaded right now: `lms ps` shows `qwen/qwen3.8-27b`, status IDLE, 17.74 GB (read 2026-11-14).
The project rule is "Never run the game or GPU work while a desktop local agent runs; unload the desktop model
first" (`PROGRESS.md:1375`). So a D1 run needs a manual `lms unload` first. Do not run that command as part of
research.

### 2.5 The ARM64EC ec_hooks crash (`LAPTOP_PORT.md:135-149`)

- Stage 1 crash (135-141): our DLL crashed at the first Present. Cause: the laptop DLAA loads `ec_hooks.dll`, which
  writes trampolines into "the d3d11 module". Behind our proxy that module is ours. With `--no-ec-hooks`, stage 1
  passes (`:138-139`: "the user saw the game run"). The DLAA hooks never initialise behind our proxy anyway
  (`MH_ERROR_NOT_INITIALIZED`, `:140`).
- Stage 2 crash (142-146): Remix's crash handler caught a stack overflow (0xC00000FD) in `nvwgf2umaxec.dll`. The
  stack alternates driver → system `d3d11.dll` → Steam overlay → `dxgi.dll`. Later the same loop was shown to be
  hook-to-hook through Steam's overlay (`:211-220` region, "Steam injects it whatever the toggle says").
- Fix not done (148-149): ship without the DLAA, or chain through a copy that resolves the system `d3d11`.
- Status: `ec_hooks.dll` set aside by hand for play (`PLAN_2026-11-13.md:2100-2101`). `laptop_port.py install` still
  does not do it (§1.5 H4).

---

## 3. (c) Unattended game runs on the desktop (Track G)

### 3.1 What exists

| Piece | Where | Evidence |
| --- | --- | --- |
| Run wrapper | `runtime/game-runs/game_run.py` (168 lines). One process group, marker `NIER_RUN_LABEL` in `/proc/*/environ`, SIGKILL at the end. | `game_run.py:2-17`, `:102`, `:111-120`, `:148-151` |
| Save guard (in Python) | Hashes four files in the real save folder before and after the run. On change: restore from the verified backup, `save_ok: false`. | `game_run.py:25-26`, `:35`, `:38-41`, `:43-48`, `:107`, `:154-160` |
| Save guard (shell) | `runtime/game-runs/guard.sh` (19 lines). Hashes `*.dat` only, copies four files back from the backup on change. | `guard.sh:5-6`, `:8`, `:10`, `:16` |
| Old launch scripts | `g1-launch.sh`, `g1c-launch.sh`, `g2-drive.sh` (shell, superseded by game_run.py) | `runtime/game-runs/*.sh` |
| Installer | `checks/install_live_dll.py` (§3.6) | |

`game_run.py` launches `gamescope --backend headless -W 1920 -H 1080 -w 1920 -h 1080 -- <proton> run ./NieRAutomata.exe`
(`:108-110`) with `MESA_VK_DEVICE_SELECT=1002:73bf!` (the RX 6800 XT, `:70`) and a copied Proton prefix
(`STEAM_COMPAT_DATA_PATH=prefix-2026-11-13`, `:30`, `:69`). The real compatdata is never the run's prefix.

### 3.2 Exact procedure (what a run does, in order)

1. `game_run.py <label> [--shots …] [--shots-every N --shots-window a,b] [--menu-drive …] [--drive …] [--capture-at …] [--live] [--env K=V] [--limit S]` (`:44-62`).
2. Build env: strip `NIER_*`, `REPLAY_*`, `MOCK_*`, `STEAM_COMPAT*` from the inherited env, then set the Proton, Mesa and Steam app ID vars (`:69-72`).
3. Screenshots: `NIER_SCREENSHOT_DIR` and `NIER_SCREENSHOT_AT` (`:82-85`). The proxy writes `shot-N.raw` (12-byte header, rows) and the runs also save PNGs. Source: `checks/menu_overlay.cpp:401-414`, `poll_screenshots` `:478`, called every present `:649`.
4. Drive: `--drive` → `NIER_REMIX_LIVE_DRIVE` and `…_MIN_INSTANCES=8` (`:88-90`). `--menu-drive` → `NIER_REMIX_LIVE_MENU_DRIVE` (`:92`).
5. Live: `--live` → `NIER_REMIX=1`, `NIER_REMIX_LIVE=1`, `NIER_REMIX_LIVE_TEX` in the run folder, `NIER_REMIX_RUNTIME` = PortalRTX `.trex\d3d9.dll` (not the 1.6.1 shim, `:93-100`).
6. `save before` hash, then the launch, then a poll loop (every 0.5 s) until the game has been seen and is gone, or `--limit` (default 110 s) passes (`:107`, `:127`, `:131-149`).
7. Kill every process with the marker, `save after` hash, compare, restore on mismatch, write `summary.json` (`:148-160`).

### 3.3 Run inventory (41 summaries under `runtime/game-runs/*/summary.json`)

- **41 runs, all `save_ok: true`, zero restores.** 40 ended at their time limit (`exit: timeout`). `game-l1b` exited by itself at 20.3 s with no shots; UNVERIFIED why.
- Summaries record `menu_drive`, `live`, `extra_env`, `shots` (file names) and save hashes. They do **not** record `--drive`, the shot times, or `--capture-at`. A run cannot be rebuilt from its summary alone. Gap, see §8.

### 3.4 How the game's own frame (Remix off) is captured as a truth pair

- **Truth run:** `game-truth` (`live: false`, no `NIER_REMIX`). The game's own frame comes from the proxy's Present hook (`menu_overlay.cpp:478`). Output: `shots/shot-N.raw` and `shot-N.png` (three shots).
- **Our run:** `game-final` (`live: true`, `extra_env: NIER_REMIX_SIZE=640x350`). Same menu drive. Output: Remix frames, three shots.
- Both use the same save and the same menu script, and the camera is held still (`PLAN_2026-11-13.md:1462-1487`, the G4 rule). Repeatability was checked with two A runs (G4 step 2).
- The truth pair in the plan: `/tmp/g4-pair.jpg`. The numbers in `PLAN_2026-11-13.md:1497-1507`: game median luma 0.372, p95 0.569, saturation 0.180; ours 0.495, 0.859, 0.108. The `/tmp` file is not in the repo.
- The truth run's shot times are not recorded (§3.3). UNVERIFIED which times were used.

### 3.5 Save protection and the change found today

| Fact | Evidence |
| --- | --- |
| Real save folder: `…/compatdata/524220/pfx/drive_c/users/steamuser/Documents/My Games/NieR_Automata/` | `game_run.py:32-33`, `guard.sh:5` |
| Backup `save-backup-2026-11-13/`: `SlotData_0.dat` `1b76c94f…`, `GameData.dat` `7ad73ae8…`, `SystemData.dat` `e770db68…`, `Graphic.ini` `7d944856…`, plus `SHA256SUMS` | `runtime/game-runs/save-backup-2026-11-13/` |
| Real save today: `SlotData_0.dat` and `SystemData.dat` match the backup. `GameData.dat` is `b03f8782…`, which differs. | `sha256sum` (2026-11-14) |
| `GameData.dat` mtime 2026-11-14 08:14:04 UTC. Last desktop run ended 07:53:11 UTC (`ab-noterrain`, `save_after` = backup hash). | `stat`, `ab-noterrain/summary.json` |
| `steam_autocloud.vdf` mtime 08:19 UTC (the end of the laptop play). Its content is an account record. Not quoted here. | `stat` |
| The laptop played 08:13–08:19 on the same Steam account. | `runtime/laptop-play-20261114/remix.log` |
| `/tmp/save-before.sha` and `/tmp/save-after.sha` date from 2026-11-13. `guard.sh` has not run since. | `ls -la /tmp/save-*.sha` |

Reading: a Steam Cloud sync from the laptop is the most likely cause. UNVERIFIED. The desktop game was not running
(`ps`, no NieRAutomata process). The save guard only checks during a run, so it cannot see a change between runs.
Do not overwrite the file until the user decides. Restoring from the backup would discard whatever the laptop saved.

Also: `guard.sh` checks only `*.dat` (`:8`, `:10`). `Graphic.ini` is restored on change but never compared.

### 3.6 `checks/install_live_dll.py` (desktop proxy installer)

- Usage: `python3 analysis/checks/install_live_dll.py --expect <sha256>` is a dry run. Add `--install` to write.
  (`install_live_dll.py:1-9`, `:36-48`.)
- Candidate: `runtime/menu-dll/d3d11.dll` (`:20`). Target: the game folder's `d3d11.dll` (`:21`).
- Refuses unless the candidate's hash equals `--expect` (`:44`). Refuses while `NieRAutomata.exe` runs (`:29-34`, `:51`).
- Backs up the current file to `analysis/backups/live-scene-<stamp>/` with `receipt.json` and `RESTORE.md` (`:74-78`).
- Writes through `.new` and `os.replace` (atomic, `:66`). Restores the backup if the installed hash differs (`:68-72`).
- Today: `runtime/menu-dll/d3d11.dll` and the game folder's `d3d11.dll` both hash `9555829d…`. So the candidate is installed. The Track G rule (`PLAN_2026-11-13.md:1336-1338`) said to restore `065432e4…` at session end unless the user says otherwise. UNVERIFIED whether that was decided.

### 3.7 G items: done or not (from `PLAN_2026-11-13.md:1335-1339` and the sections below)

| Item | Status | Basis |
| --- | --- | --- |
| G1 start headless | Reaches rendering. Needs Steam running (DRM). Picture missing at the time. | `:1365-1383`. Later items supersede the picture problem. |
| G2 title to world, no person | **Done.** Dozens of cold starts to the camp. | `:1384-1448`; 41 summaries have `save_ok: true` |
| G3 capture without F9 | **Done** 2026-11-13: `frame_12935626`, 570 draws, 214 textures. Replays. | `:1450-1461`, `:1488-1496` |
| G4 game's own frame paired with ours | **Done** 2026-11-14 (`game-truth` vs `game-final`). Used for the L1 final pass. | `:1462-1487`, `:1497-1518` |
| G5 scripted motion runs | **Done** 2026-11-14 (12-min soak `s2-soak`, GPU-skinning A/B `s2-gpuskin`). Quit time is S1, not measured. | `:1520-1557`; `game_run.py` summaries |

Known limits recorded in the plan: the menu script is time based (`:1438-1448`). The game renders at the size its
display mode is set to, which these runs show as `640x350@60` (`game-runs/game-final/host.log`). The source of that
mode is UNVERIFIED (see §7.3). `NIER_REMIX_SIZE` must equal the game's size or Remix pauses (`:1545-1547`; source
`checks/remix_live.cpp:1372-1393`).

---

## 4. (d) The exit hang (S1 / C2)

### 4.1 What is measured (`PLAN_2026-11-13.md:1269-1298`)

| Run | Frames | Result |
| --- | --- | --- |
| `s1-clean-300` (`REPLAY_EXIT=clean`) | 300, all presented | No exit; timed out at 146 s |
| `s1-warm` (same dir, warm shader cache) | 300, all presented | No exit; timed out at 202 s |
| `s1-long` | 300, all presented | No exit after 422 s |
| `--mode off` with `REPLAY_EXIT=clean` (Remix not started), 120 frames | — | Exits in 4.1 s |

`REPLAY_EXIT=clean` makes `main` return instead of `TerminateProcess` (`replay/capture_replay.cpp:498-499`).
The old "230 to 322 s at 2,500 frames" figure was a timeout cut-off (`PLAN_2026-11-13.md:1291-1292`).

### 4.2 Source (scout, `replay/research-2026-11-13/remix_exit_path.md`, checked by the lead)

- `remixapi_Shutdown` releases the D3D9 device to refcount 0, then the interface, then `sentry::shutdown()` with a 4 s cap
  (`runtime/src/dxvk-remix/src/dxvk/rtx_render/rtx_remix_api.cpp:1671-1693`; cap in `util_sentry.cpp:82`).
- `RtxInitializer::onDestroy` (`rtx_initializer.cpp:49`) calls `waitForShaderPrewarm()` at `:57`. That is
  `while (isCompilingShaders()) Sleep(1);` with no timeout (`:201-209`). `isCompilingShaders()` is
  `m_workerBusy > 0` (`dxvk_state_cache.h:123-125`). The compiler stop flag is set later at `dxvk_device.cpp:167`.
- Other waits with no timeout on the exit path: `vkDeviceWaitIdle` (`dxvk_device.cpp:486`), a fence retry loop
  (`dxvk_cmdlist.cpp:173-177`), the submit and finish joins (`dxvk_queue.cpp:57-58`), `dxvk::thread::join` = `INFINITE`
  (`util/thread.cpp:38`).

I re-read `rtx_initializer.cpp:49-57`, `:201-209` and `dxvk_device.cpp:167` today. They match.

### 4.3 What is known and not

- **Known:** the hang is in Remix's destroy path, not in the replayer or the proxy (`--mode off` exits; Remix on does not).
- **Not known:** the thread that waits. No stack was taken. "Deadlock" (PLAN_2026-11-13.md:1290) is an inference from
  "did not exit in 422 s". UNVERIFIED.
- The warm-cache run hit the same wait, so the prewarm loop is not the whole story (`:1283-1286`).

### 4.4 The blocked step

- `cat /proc/sys/kernel/yama/ptrace_scope` returns **1** (read 2026-11-14). A process can attach only to its own
  descendants.
- `/usr/bin/gdb`, `/usr/bin/winedbg` and `/usr/bin/sudo` are installed.
- **Blocked step:** attach to the hung replay process (after `presented=300` with no exit) and run
  `thread apply all bt` (gdb) or `winedbg --command "bt all"`. Both need ptrace on a non-descendant.
- Options that need the user's decision: `sudo` for the attach, or `ptrace_scope=0` for one session (`PLAN_2026-11-13.md:1279-1281`).
- Option that may not need it (UNVERIFIED here): start the replay under `gdb` (`gdb -batch -ex run -ex "thread apply all bt" --args …`), so gdb is the parent. Yama's descendant rule should allow that at scope 1. Check the kernel's Yama documentation before relying on it.
- Option without ptrace: `s1-no-shutdown`. Same run with `Shutdown` skipped, recording the exit and the next run (`PLAN_2026-11-13.md:1297-1299`).

---

## 5. (e) Terrain bake mips

### 5.1 The current writer

- Bake: `checks/terrain_bake.h`. `bake()` box-filters to ≤512 (`shrink`, `:39-57`, `kMaxSize = 512` at `:19`). `dds_bytes(const Image&)` at `:106-120` writes **one mip**:
  - `h[2] = 0x1|0x2|0x4|0x1000|0x8` (no `DDSD_MIPMAPCOUNT` 0x20000, no `LINEARSIZE` 0x80000). `h[5]` = pitch `w*4`.
  - `h[7] = 1` (mip count), `h[27] = 0x1000` (no `DDSCAPS_MIPMAP`), `h[28] = 0`.
  - DX10 block `{29, 3, 0, 1, 0}` (R8G8B8A8_UNORM_SRGB, TEXTURE2D).
- File name: `bake_<t0>_<t1>_<level>_<sharpness×10000>.dds` (`checks/live_scene.h:282-300`, `:295-296`).
- Upload: `bake_file` writes it (`live_scene.h:297`). `baked_material_for` (`:306-334`) calls `nscn::detail::make_material_info(info, ext, path, hash, false)` (`:316`) and `api.CreateMaterial` (`:319`). `make_material_info` sets `info.albedoTexture = path` (`checks/nscn_scene.h:109-118`). **Remix loads the DDS from disk by path.** Our side uploads no GPU texture for a bake.

### 5.2 The warning in Remix

- Source: `runtime/src/dxvk-remix/src/dxvk/rtx_render/rtx_texture_manager.cpp:1484-1488`. It warns when
  `mipLevels == 1` **and** `width × height ≥ 512 × 512`.
- Laptop: `runtime/laptop-play-20261114/remix.log:289-299`. Ten warnings: eight for `bake_229_230_{0..7}_100.dds`
  (08:14:43.2–.6), two for `bake_1018_765_7_1000.dds` and `bake_1075_1076_7_1000.dds` (08:17:09–10). No other
  warning of this kind.
- Desktop, same runtime source: `runtime/game-runs/game-terrain/remix-dxvk.log` has eight such warnings (for
  `bake_230_231_{0..7}_100.dds`). `ab-defaults` has eight. The bake files are on disk: eight in `game-terrain/live-textures`.
- Desktop bake header, read today (`runtime/game-runs/game-terrain/live-textures/bake_230_231_0_100.dds`):
  512×512, `mips = 1`, `flags 0x100f`, `caps 0x1000`, DXGI 29, file size **1,048,724 B** (= 148 + 512·512·4).
- Desktop game texture for comparison (`live_343.dds`): 2048×2048, **12 mips**, `flags 0xa1007`, `caps 0x401000`,
  `caps2 0x400000`, DXGI 28. Game textures do not trigger the warning.

### 5.3 The model to copy

`checks/texture_capture.h:270-292` (`write_dds`, "carrying the game's whole mip chain") writes:
- `h[2] = … | 0x80000 | (levels>1 ? 0x20000 : 0)` (`:281`);
- `h[5] = mip0 linear size` (`:283`); `h[7] = levels` (`:284`);
- `h[27] = 0x1000 | (levels>1 ? 0x400000 : 0)` (`:288`); `h[28] = levels>1 ? 0x400000 : 0` (`:289`);
- mips 0..n written tightly packed in order (`:291-292`).

`remix_live.cpp:441` and `:464` use this writer for every game texture. Those textures load without the warning.

### 5.4 What a mip chain needs (concrete)

1. **`checks/terrain_bake.h`:** a `dds_bytes` that writes all levels from the baked image down to 1×1. Reuse the
   box filter in `shrink()` (`:39-57`) one level at a time. Encode each level as `dds_bytes` does today
   (`linear_to_srgb`, `mask_channels::to_byte`, `:110-118`). Header as in §5.3: `0x20000` and `0x80000` in `h[2]`,
   `h[7] = levels`, `h[27] = 0x1000|0x400000`, `h[28] = 0x400000`.
2. **Size for a 512² bake:** 9 levels (512 down to 1). Data = 4·(262144+65536+16384+4096+1024+256+64+16+4) =
   **1,398,096 B**, plus the 148-byte header = **1,398,244 B** (currently 1,048,724 B, +33%). Eight tiles per layer pair
   (`terrain_bake.h:18`) means about +2.7 MB per pair. UNVERIFIED how Remix holds the chain in GPU memory.
3. **Reader safety:** `read_dds` reads mip 0 from offset 148 (`terrain_bake.h:31-36`), and the RGBA path only needs
   `src_bytes ≥ w·h·4` (`checks/mask_channels.h:100`). Trailing mip bytes are therefore harmless to our reader.
   The bake input files are the game's own captured textures, which already have chains (§5.3), so this path was
   already in use.
4. **Gate:** `checks/test_terrain_bake.py` (167 lines; builds a g++ harness, `:149-160`). Its DDS checks are at
   `:82-83`, `:98-99`, `:116`. Add: `h[2] & 0x20000` set, `h[7]` = `floor(log2(max(w,h)))+1`, file size = 148 + Σ level bytes,
   the last level is 1×1, and `read_dds` still returns the same mip 0. Do not build it in research.
5. **Live check:** one desktop terrain run (`--env NIER_REMIX_LIVE_TERRAIN_LAYERS=1` is already the default,
   `checks/live_capture.h:570`). Then `grep -c suboptimal remix-dxvk.log` must print `0`. Then one laptop run with the
   same grep on `remix.log`.
6. **Cost:** a 512² bake grows by a third. Load time and memory are unmeasured.

---

## 6. (f) Laptop play session 2026-11-14, 08:13–08:19 (`runtime/laptop-play-20261114/`)

### 6.1 Files and scope

| File | What | Notes |
| --- | --- | --- |
| `NIER_SCALE.log` (4,455 lines, 1.3 MB) | Proxy log. Two PIDs: `27420` at 08:01 (crash, menu lines only, §6.6), `35692` at 08:13–08:19 (the session). | |
| `remix.log` (299 lines) | Remix's own log. Copied out by hand. | |
| `recording.mp4` (308 MB), `rec/f001–f007.png` | Screen recording, 2026-11-14 08:26–08:27. | Frames: `replay/research-2026-11-14/laptop-desert-*.jpg` |
| `frame_67078468/` (8.7 GB, 901 entries), `frame_67279062/` (5.5 GB, 929 entries) | Two capture folders (PLAN calls them F9 captures). `done-67279062` marker. | |
| `shaders/`, `shaders.zip` | Shader dumps. Not analysed. | |
| `scp.log` | Empty. | |

### 6.2 Frame time (stats windows, `remix: N fps over the last 60 frames (ms/frame: …)`)

75 windows (`NIER_SCALE.log` lines 199–4431). Method: the stats line's own `fps` value, percentiles nearest-rank.

| | min | p10 | median | p90 | max | mean |
| --- | --- | --- | --- | --- | --- | --- |
| fps | 3.7 | 14.1 | 17.0 | 19.8 | 24.8 | 16.9 |

Median ms per frame (75 windows) and maximum:

| Bucket | Median | Max |
| --- | --- | --- |
| update | 0.7 | 9.3 |
| submit | 1.0 | 2.8 |
| present | 0.4 | 2.4 |
| copy | 0.0 | 0.0 |
| **readback** | **50.6** | 77.2 |
| convert | 1.7 | 2.4 |
| publish | 0.0 | 0.0 |
| other | 3.2 | 220.2 |
| **sum of medians** | **58.7** | 274.0 (sum of maxima, not a real frame) |

The plan quotes "p10 13.3" (`PLAN_2026-11-13.md:2104-2106`). My nearest-rank p10 is 14.1. The method behind 13.3
is UNVERIFIED. The plan's "17.1 median" is 17.0 here.

### 6.3 Resolution and upscaler

| Line | Meaning |
| --- | --- |
| `NIER_SCALE.log:22` `remix: starting at 2880x1800 monitor (game backbuffer 1600x900 format=28)` | Remix sized to the monitor. The game's backbuffer was 1600x900 at the menu. |
| `:24` `menu: ready window=… backbuffer=1600x900 scale=1.0` | Proxy's view at start. |
| `:27` `remix: started 2880x1800 startup=5 surfaces=0 sky_skipped=0 untextured=0 live=1` | Remix started. |
| `:40` `remix: window … NieR:Automata_MainWindow … 2880x1800` | Window rect. |
| 76 `remix: live draws … scene=2880x1800` lines | Scene target is 2880×1800 for the whole session. |
| 90 `… scene=1` fragments | Not a size. These are `in_scene=1` in `remix: small ps=…` lines (`:…` e.g. 08:14:41.098). |
| No `paused` line | The live path ran; no `remix: paused` in this log. |

DLSS state (`remix.log:22-65`, the config is read twice):
- `rtx.upscalerType = 1` (DLSS) (`:30`). Enum `UpscalerType`: `None=0, DLSS=1, NIS, TAAU, XeSS` (`runtime/src/dxvk-remix/src/dxvk/rtx_render/rtx_options.h:70-77`).
- `rtx.dlssPreset = 2` (Custom) (`:27`, `:56`). `DlssPreset`: `Off=0, On, Custom` (`rtx_options.h:83-88`).
- `rtx.qualityDLSS = 1` (`:26`, `:62`). `DLSSProfile`: `UltraPerf=0, MaxPerf=1, Balanced=2, MaxQuality=3, Auto=4, FullResolution=5` (`rtx_dlss.h:35-43`). So **1 is MaxPerf**, not "Performance". The plan and `laptop-game.conf:8` say "Performance" (§7).
- `rtx.dlfg.enable = False` (`:22`, `:54`). `rtx.minPrimsInDynamicBLAS = 0` (`:25`, `:58`).
- Tonemap: `tonemappingMode = 0`, `colorGradingEnabled = True`, `saturation 1.6`, `contrast 0.90`, `exposureBias -0.85`, `colorBalance 1, 0.89, 0.7` (`:24-36`, `:53-65`).
- Heap 0 40,946 MiB, heap 1 11,644 MiB (`:117`, `:121`).

### 6.4 Warnings, errors and message types (unique types, counts)

**`remix.log` (299 lines):**

| Count | Message | Evidence |
| --- | --- | --- |
| 10 | `warn: A suboptimal replacement texture detected: …\live-textures\bake_*.dds! Please make sure all replacement textures have mip-maps.` | `:289-299`. §5 |
| 1 | `warn: [D3D9WindowProc] Swapchain handle is invalid, some of its values may not be correct.` | `:277` (08:13:43.093). Not explained. |
| 2 | `warn: Skipping Emulated GPU adapter …` / `Skipping CPU adapter …` | `:80-81`. Expected. |
| 1 | `info: OpenVR: Failed to locate module` | `:71`. Expected. |
| — | Config read from `…\NieRAutomata\rtx.conf` (`:18`), `DXVK_RTX_CONFIG_FILE` honoured. | `:16-19` |

Log-level check: `remix.log` has no `err:` lines.

**`NIER_SCALE.log` (after removing the noisy `presence` and `funnel` families):**

| Count | Message | Evidence |
| --- | --- | --- |
| 1136 | `remix: presence_why …` | One per window pair. Noise. |
| 1136 | `remix: presence seq=…` | Noise. |
| 28 | `remix: decode_failures vertex_out_of_range=N \| out_of_range stale=… dynamic=… small=…` | First at `:59` (N=1430). Later windows 64–100. |
| 4 | `remix: world gone (10 game frames without scene draws); showing the game's own frame` | `:29` 08:13:43.274; `:2351` 08:16:36.447; `:2533` 08:16:55.163; `:4455` 08:19:34.840 |
| 3 | `remix: world back; compositing Remix frame N (capture N)` | `:53` 08:14:41.067; `:2357` 08:16:38.099; `:2539` 08:17:07.977 |
| 1 | `remix: no live draws yet after 101 frames; showing the game's own image until they arrive` | `:30` 08:13:44.746 |
| 1 | `remix: first frame ready` | `:38` 08:14:41.035 |
| 1 | `remix: composited first frame 2880x1800` | `:54` 08:14:41.073 |
| 1 | `remix: focus -> … NieR:Automata_MainWindow own_process=1` | `:21` |
| 1 | `remix: native HUD handoff …` and `remix: started …` | early lines |
| 1 | `next-stage module=… exports_ready=1` | from `NIER_SCALE.log` |

No `error`, `crash`, `timeout` or `exception` text in `NIER_SCALE.log` after filtering.

Timeline of "world gone": the first at 08:13:43 is 10 frames after start. It is cleared at 08:14:41 (first live frame,
1 min later). The 2nd (08:16:36) clears in 2 s. The 3rd (08:16:55) clears in 12 s. The last (08:19:34) has no
"world back" line. What happened at the end is UNVERIFIED (a quit, a menu, a cutscene, or the session ending).

### 6.5 Effects (the effect shader table)

- Effect draws are dropped here: `checks/live_capture.h:1719-1725` (`if (pixel.effect && !keep_effects)`), tallied via
  `tally_shader(… effect=true, skipped=true)`. `keep_effects` default false (`:592`); `NIER_REMIX_LIVE_EFFECTS=1` sets it (`checks/remix_live.cpp:259`).
- `effect` is set when a pixel shader declares buffer `t27` or `t30` (`checks/live_capture.h:1414-1421`, `:1452`).
- Materials: 47 `remix: material ps=… effect=…` lines, 15 with `effect=1` (`NIER_SCALE.log`).
- **Shader table** (`remix: shader ps=… draws=… tris=… blend=… alpha=… effect=… rt=…`): the counts are cumulative
  (`tallies` never reset, `checks/live_capture.h:1342-1355`). 912 table lines over 76 windows. Only two shaders ever
  show effect draws:
  - `ps=801fc5c5c8`: 27,341 effect draws, `blend=off:0>0`, `rt=0`, first seen at line 4424 (`NIER_SCALE.log`).
  - `ps=80231fbe08`: 16,375 effect draws, `blend=off:0>0`, `rt=0`, first seen at line 2530.
- **Funnel** (`remix: funnel … effect=N`): per window (`funnel::take()` resets, `checks/remix_live.cpp:960-963`). 74
  windows parse. Effect drops per window: median 1,126, min 32, max 4,277, total 92,611. Median share 0.8% of funnel draws.
- Plan's question ("list every effect shader with blend state, target and count"): the two shaders above are the only
  ones that reach the table. The other effect drops appear only in the funnel total. Their identities are UNVERIFIED.

### 6.6 Session context

- 08:01:19 pid `27420`: menu hooks installed, then nothing from Remix. The first laptop launch crashed at 08:01 (PLAN_2026-11-13.md:2102-2104; dump `runtime/laptop-port/dumps/play-20261114.dmp`). The `ec_hooks` cause is §2.5.
- 08:13:35 pid `35692`: `NIER_ENV.ini: 6 settings applied`, Remix enabled, Remix started at 08:13:43.
- Stats windows run 08:14:44 to 08:19:34 (75 windows). The last window: 21.8 fps.
- `live draws` growth: `textures` 10 → 1,220 by 08:18:35; `meshes` 519 → 1,474; `built` 519 → 8,841. Built meshes rose by about 8,300 across the session. Mesh churn continues.

---

## 7. (g) Desktop hardware constraints for D1

### 7.1 GPUs (read 2026-11-14)

| Card | PCI | ID | VRAM total | VRAM used now | Role | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| card0 | 0000:47:00.0 | 1002:73bf (Navi 21, RX 6800/6800 XT) | 16,368 MiB | **10,751 MiB** | Replay and game runs (`MESA_VK_DEVICE_SELECT`). No monitor. | `lspci -nn`; sysfs; `PLAN_2026-11-13.md:1907-1910` |
| card1 | 0000:03:00.0 | 1002:7550 (Navi 48, RX 9070/9070 XT) | 16,304 MiB | **12,354 MiB** | Drives the monitors. Off limits for runs. | sysfs; `PLAN_2026-11-13.md:1908-1909`; `DUAL_GPU_PLAN.md:5` |
| card2 | 0000:5c:00.0 | 1002:164e (Radeon 610M, iGPU) | 512 MiB | 41 MiB | — | sysfs |

- No NieRAutomata process is running now. Steam has run for about 23 h (`ps`), so D6 (Steam may be started) is in effect.
- VRAM on card0 is used with no game running. Owner UNVERIFIED. The desktop LM Studio model is one candidate.

### 7.2 Desktop display and the D1 target

- D1 (`PLAN_2026-11-14.md`, table): "Desktop at its real resolution (3440x1440, 6800 XT: no DLSS, no frame generation)".
- The monitors and the 3440x1440 display are on the **9070 XT** (`PLAN_2026-11-13.md:1907-1910`). The 6800 XT has no monitor.
- The game's own video setting names the 9070 XT: `Graphic.ini` `VideoCard=AMD Radeon RX 9070 XT (RADV GFX1201)`, `Output=Default` (hex-encoded UTF-16, decoded today). The runs select the 6800 XT through Mesa only.
- No measurement at 3440×1440 on the 6800 XT exists in the cited tables (see §7.4). The only 3440x1440 numbers are on the 9070 XT (§7.4).
- "No DLSS" is right: the 6800 XT is AMD. `Remix`'s upscaler is XeSS on this box (`deploy/rtx/desktop-replay.conf:6-8`).

### 7.3 Resolution the runs use

- Every desktop game run in the logs shows the game's display mode `640x350@60` (`runtime/game-runs/game-final/host.log`,
  `Setting display mode: 640x350@60`; screenshots `menu: screenshot … written 640x350 format=28`, `game-final/NIER_SCALE.log`).
- The plan says this is set by the copied prefix's `Graphic.ini` (`PLAN_2026-11-13.md:1448`, `:1517`, `:1546-1547`).
  **That is not supported.** `Graphic.ini` (same hash in the real save, the backup and the copy, `7d944856…`) has only
  `VideoCard=` and `Output=` (`[Graphic]`, two lines). No width or height key. The source of 640x350 is UNVERIFIED.
- Headless gamescope is set to 1920×1080 (`game_run.py:108`). So the game does not take its size from gamescope.

### 7.4 What was measured before (not at 3440×1440 on the 6800 XT)

| Source | Card | Resolution | Result | Evidence |
| --- | --- | --- | --- | --- |
| `PLAN_2026-11-13.md` §11.2 table | 6800 XT | Replay: 2,500 frames, XeSS Performance; resolution not given per row except the two laptop rows at 2880×1800 | 29–53 fps across captures; laptop rows 28.2 / 26.4 fps; `minPrimsInDynamicBLAS 0` 29.3 fps vs 25.1 default on 30632051 | `:1696-1708`, `:1711-1721` |
| `PLAN_2026-11-13.md` §11.2 | 6800 XT | 2880×1800 laptop captures (replay) | 28.2 and 26.4 fps; readback 33.8 and 36.0 ms | `:1704-1705` |
| `DUAL_GPU_PLAN.md:5-6` | 9070 XT (monitors) | 3440×1440, game + Remix | Remix 7.3 fps, game 14 fps, 100% busy; Remix alone 38 fps | `DUAL_GPU_PLAN.md:5-6` (cites PROGRESS.md first checkpoint, not checked) |
| `PERF_RESEARCH.md` | 6800 XT (2026-10-29) | Not stated | 3.6 fps live; readback 152 ms; mesh cache 22,223 built / 19,717 evicted. Its readback reading is corrected at `:3-6`. | `PERF_RESEARCH.md:3-9` |
| `PLAN_2026-11-13.md` §11.2 "XeSS Performance at 2,500 frames" | 6800 XT | Camp captures, replay | camp 52.8–53.3 fps (21396979, 21565698) | `:1698-1701` |
| Laptop 2026-11-14 (N1X, DLSS MaxPerf) | RTX Spark N1X | 2880×1800 | median 17.0 fps, readback 50.6 ms | §6.2 |

- `PERF_RESEARCH.md` is about CPU readback design. It has no 3440×1440 numbers. Its "readback 152 ms" is the Remix worker's wait, per the correction at the top of that file.

### 7.5 What a D1 run needs (from the code, nothing run)

- A run at 3440×1440 on card0 needs three things:
  1. A way to make the game's display mode 3440×1440 (the source of 640x350 is not known, §7.3).
  2. A gamescope size other than 1920×1080 (`game_run.py:108`). Or the decision to use the monitor path.
  3. Nothing else on card0. Check `/sys/class/drm/card0/device/mem_info_vram_used` first (now 10.7 GB used).
- Desktop LM Studio: `qwen/qwen3.8-27b` is loaded. Unload it first (`PROGRESS.md:1375`). This is a manual step; no script does it on the desktop.
- Remix's own log gives the backbuffer and the presented size on every run (`remix: starting at …` line). Use it to prove the size.

---

## 8. Contradictions with `analysis/PLAN_2026-11-14.md` (and the plan it builds on)

| # | Plan says | Evidence says | Where |
| --- | --- | --- | --- |
| 1 | "save never touched" (rules carried over) | The real `GameData.dat` differs from the backup (`b03f8782…` vs `7ad73ae8…`), mtime 08:14:04 UTC, after the last logged desktop run (07:53:11 UTC). | §3.5; `PLAN_2026-11-14.md` header |
| 2 | C3: "`laptop_port.py install` sets `ec_hooks.dll` aside" (as a to-do) | `install()` has no `ec_hooks` code. Only `run --no-ec-hooks` and `restore` touch it. The set-aside was done by hand. | `laptop_port.py:95-124` vs `:168-169`, `:225`; PLAN_2026-11-13.md:2100-2101 |
| 3 | C3: "Install and Remix log clean" | `remix.log` has 10 "suboptimal replacement texture" warnings and one "Swapchain handle is invalid" warning. | `remix.log:277`, `:289-299` |
| 4 | C2: "deadlock in Remix teardown" | No thread stack. "Did not exit in 422 s" is the only evidence. | `PLAN_2026-11-13.md:1290-1292` |
| 5 | D1: "Desktop at its real resolution (3440x1440, 6800 XT)" | The 3440x1440 display is on the 9070 XT. The 6800 XT has no monitor and is the replay GPU. | `PLAN_2026-11-13.md:1907-1910`; `DUAL_GPU_PLAN.md:5` |
| 6 | Laptop play: DLSS "Performance" at `qualityDLSS = 1` (PLAN_2026-11-13.md:2112-2114, `laptop-game.conf:8`) | The enum value 1 is `MaxPerf` (`rtx_dlss.h:35-43`). | |
| 7 | "p10 13.3" fps (PLAN_2026-11-13.md:2104-2106) | Nearest-rank p10 = 14.1 over the same 75 windows. Median 17.0, not 17.1. Method UNVERIFIED. | §6.2 |
| 8 | "everything else < 3 ms" (same paragraph) | `other` median 3.2 ms (max 220 ms). | §6.2 |
| 9 | "The desktop's readback 7.9 ms" (same paragraph) | Source not found in the files read. UNVERIFIED. | |
| 10 | "the copied prefix's own `Graphic.ini` asks for 640x350" (PLAN_2026-11-13.md:1448, :1517, :1546-1547) | `Graphic.ini` has no size key. The source of 640x350 is unknown. | §7.3 |
| 11 | "ssh spaghetti … does not resolve" (PLAN_2026-11-13.md:1912-1913) and "laptop_port … (ssh spaghetti)" (LAPTOP_PORT.md:3) | Both were written as fact on different days. Today `spaghetti` is a Tailscale peer name; `getent` returns nothing. | §2.3 |
| 12 | "A scheduled task with `/it` … no visible window" (PLAN_2026-11-13.md:1914-1917) | `laptop_port.py` uses a scheduled task with LogonType Interactive, and the user saw the game (LAPTOP_PORT.md:139). Different mechanism. | §2.2 |
| 13 | `deploy/README.md` as the install doc | It documents `nier_upscale.sh`, not `laptop_port.py`. | §1.6 |
| 14 | `laptop-NIER_ENV.ini` "installed by deploy/laptop_port.py" | No code in `laptop_port.py` places this file. | §1.6 |

---

## Open questions

1. **Who changed the real `GameData.dat` at 08:14:04 UTC?** Determine: (a) Steam's cloud log for that minute (`~/.local/share/Steam/logs/`, path UNVERIFIED); (b) the laptop's own save file and its mtime (`C:\Users\suraj\Documents\My Games\NieR_Automata\`, UNVERIFIED path, needs ssh); (c) compare the new file's bytes with the laptop's save. Decision for the user: keep it, or restore the backup. Do not write either way until the user decides.
2. **Where does the 640x350 display mode come from?** Determine by a read-only check: the game's own save or registry values under the copied prefix (`runtime/game-runs/prefix-2026-11-13/pfx/system.reg`, `user.reg`; keys to find), and by comparing `SystemData.dat` (72 bytes) with a run at a different size. Needs a decision before D1.
3. **Does `ssh spaghetti` work today?** Determine: one `ssh -o BatchMode=yes -o ConnectTimeout=10 spaghetti echo ok` by the user or the lead. Not run here.
4. **Does a gdb-launched replay get a stack at `ptrace_scope = 1`?** Determine: on the desktop replay only, `gdb -batch -ex run -ex "thread apply all bt" --args <replay>` with `REPLAY_EXIT=clean`, 300 frames. Check the Yama rule in the kernel docs first (not checked here).
5. **What ends the laptop session at 08:19:34?** Determine: the user's account of the session, plus the laptop receipt for that run (none under `runtime/laptop-port/` for 20261114 at this time; UNVERIFIED).
6. **Why did `game-l1b` exit at 20.3 s?** Determine: `runtime/game-runs/game-l1b/host.log` and `NieRAutomata_d3d11.log`. Not read.
7. **Which GPU runs the desktop LM Studio model, and who uses card0 VRAM now?** Determine: `lms ps` device column (currently "Local") and `fuser /dev/dri/renderD*` by PID (read-only).
8. **How big is the mip-chain bake's effect on load time and memory?** Determine: one desktop terrain run with the chain (§5.4 step 5), frame-time windows compared to `game-terrain`.
9. **Does Remix's desktop build behave the same as the laptop's on the warnings?** Both use source `0ba9973f…`. The desktop shows the same warning (§5.2). The laptop run is the same binary family; UNVERIFIED hash of the laptop build.
10. **What is the laptop's installed `d3d11.dll` and `ec_hooks.dll` state right now?** Determine: `laptop_port.py` has no status command. A read-only ssh `Get-FileHash` by the user.
11. **Do the 41 desktop summaries reproduce?** The drive script, shot times and capture times are not in `summary.json` (§3.3). Determine: rerun one truth pair with an explicit command line stored in the run folder (not run here).
12. **Does `NIER_REMIX_LIVE_TERRAIN_LAYERS` change the bake count per run?** Not measured: `bake_*.dds` counts were read only for the two desktop runs.

---

## Recommended steps for the plan

Each step names the file, the change, and the check. Do the steps in order. Steps 1–4 can be done without the user at the laptop.

1. **Save first (safety, no code).** Ask the user about `GameData.dat` (§3.5, open question 1). Record the decision in
   the plan. Until then, do not run any desktop game run that restores the save. Check: `sha256sum` of the four real save
   files equals the decision.
2. **Make `guard.sh` check all four files.** Change `runtime/game-runs/guard.sh:8` and `:10` from `*.dat` to the four
   names in `game_run.py:35` (`SlotData_0.dat GameData.dat SystemData.dat Graphic.ini`). Check: `guard.sh before` then
   `guard.sh after` prints "real save unchanged" on an untouched save. Also add a `guard.sh check` that compares the real
   save with `save-backup-2026-11-13` and exits non-zero on a mismatch. It must not restore on its own.
3. **Record the full command line in every game run.** In `runtime/game-runs/game_run.py`, add `drive`, `shots`,
   `shots_every`, `capture_at` and `cmd` to the `summary` dict at `:154-158`. Check: one new run, then
   `python3 -c` reads the new keys from `summary.json`.
4. **Protect logs before `restore` (C1).** In `deploy/laptop_port.py`, add `NIER_SCALE.log`, `data\rtx-remix\logs` and
   `RtxOptions.md` to `KEEP` (`:53`) or copy them to `WORK\kept\<stamp>` before the delete at `:224`. Gate:
   extend `checks/test_laptop_port_transport.py` to assert the generated restore script contains the copy or keep line.
   Check: a restore after a play session leaves a copy of `NIER_SCALE.log`.
5. **Make `install` set `ec_hooks.dll` aside (C3).** In `deploy/laptop_port.py` `install()` (`:95-124`), add an
   idempotent rename: if `ec_hooks.dll` exists, rename it to `ec_hooks.dll.off`; if `.off` already exists, skip. Keep the
   existing `restore` rename at `:225`. Gate: `checks/test_laptop_port_transport.py` asserts the generated install text
   contains the rename, and `restore` puts it back. Check: one laptop install and one Steam launch (user at the laptop) with
   no crash at `ec_hooks` in the dump (`checks/read_minidump.py`).
6. **Fix two run hazards (C3).** In `deploy/laptop_port.py` `run()`: (a) line 169, test that `ec_hooks.dll` exists before
   the rename, or skip it; (b) lines 170-171, do not delete `NIER_ENV.ini` on a direct run. Gate: transport test on the
   script text. Check: `run` without `--steam` leaves `NIER_ENV.ini` in place.
7. **Mip chain for terrain bakes (C3, §5.4).** Edit `checks/terrain_bake.h` `dds_bytes` (`:106-120`) to write the full
   chain with the header of `checks/texture_capture.h:281-289`. Gate: extend `checks/test_terrain_bake.py` (`:82-83`
   area) with the header flags, `h[7]`, file size 148 + Σ levels (1,398,244 B for 512²), 1×1 last level, and unchanged
   `read_dds` mip 0. Check: one desktop terrain run; `grep -c suboptimal remix-dxvk.log` prints `0`; then one laptop run
   with the same grep on `remix.log`.
8. **Laptop play checks after step 5 and step 7 (C1).** Run the user's 20–30 minute session with these questions, each
   answered from logs: combat (look for `decode_failures`, `world gone` count, fps windows during combat), cutscene/video
   (`world gone` and `world back` pairs with timestamps), area change (`live draws` `meshes` and `built` jumps), menus
   (`menu:` lines), hacking (`world gone`), quit (last `fps over` line and the process end in the receipt). Copy the logs
   before restore (step 4). Record each failure with its log line numbers.
9. **Check the `qualityDLSS` value in the next laptop launch (C3/P1 context).** Expect `rtx.qualityDLSS = 0` in
   `remix.log` (the `laptop-game.conf:10` value). Compare its fps median with 17.0 (§6.2) over the same number of windows.
   Fix the plan text: `1` is MaxPerf, `0` is UltraPerf (`rtx_dlss.h:35-43`).
10. **Exit hang (C2).** Ask the user for one of: `sudo` for the attach, or `ptrace_scope=0` for one session. Or run the
    replay under `gdb` as the parent (§4.4), after checking the Yama rule. Named step: attach to the hung replay after
    `presented=300` and run `thread apply all bt`. Check: the stack names the wait. If the user says no, run
    `s1-no-shutdown` (`PLAN_2026-11-13.md:1297-1299`) instead. Record which one was done.
11. **D1 prerequisites.** (a) Find the 640x350 source (open question 2). (b) Choose the GPU and size explicitly (card0,
    6800 XT; 3440x1440). (c) Unload the desktop LM Studio model with `lms unload` (manual, `PROGRESS.md:1375`). (d) Check
    card0 VRAM is free (sysfs). Then one `game_run.py` run with the agreed size. Check: the Remix or proxy log line
    shows the backbuffer and presented size, and `fps over` lines exist.
12. **Put the laptop's `run` docs in `deploy/`.** Add `deploy/README-laptop.md` (or a section in `deploy/README.md`) with the
    subcommands, flags and hazards from §1.2 and §1.5. Check: the plan links it; `laptop_port.py` with no argument still
    prints the same text.
13. **Reduce log noise (optional, for C1 reading).** Either rate-limit the `remix: presence` and `remix: presence_why`
    lines (1,136 each in one session) or move them to a separate file. Check: one run, the file is smaller and the
    `fps over` and `world gone` lines are unchanged.
14. **Update the plan text (documentation).** Correct the items listed in §8 (rows 2, 3, 4, 5, 6, 7, 8, 10). Check: each
    corrected claim has a file:line next to it.
