# Porting NieR RTX to the laptop (Windows on ARM, RTX Spark N1X)

Written 2026-10-29 from facts read off the machine (`ssh spaghetti`), not assumptions. The goal is not a second
development machine: it is the fastest way to find out whether the 5 fps on the desktop is *our* copy path or Remix
itself, because the laptop has a working Remix stack (Portal RTX) and real Windows D3D9 readback instead of wined3d's.

## What the machine is

| | |
| --- | --- |
| OS | Windows 11 Home 10.0.28000, **ARM64** |
| CPU/SoC | ARM64-based PC, 23 GB RAM |
| GPU | **NVIDIA RTX Spark N1X** (6144-core Blackwell), driver 32.0.16.1769; Windows reports 4 GB for the adapter |
| Python | 3.14 **ARM64** (`...\Python314-arm64\python.exe`) |
| NieR | installed, `C:\Program Files (x86)\Steam\steamapps\common\NieRAutomata` |
| Remix proof | **Portal RTX installed** in the same Steam library — path tracing, DLSS and DL frame gen run here |
| Prior work | `C:\Users\suraj\Projects\Nier-Automata-Rendering-depth` (windows-vtable build, backups, quarantine) |
| Game dir today | `d3d11.dll` 452608 B (= the NIER_DLAA proxy renamed), `ec_hooks.dll`, `nvngx_dlss.dll`, `NIER_DLAA.ini/.log`; **no `.trex` runtime** next to the exe |

## The architecture constraint that decides everything

`NieRAutomata.exe` is x86-64. **A process can only load DLLs of its own architecture**, so on this machine every piece
has to be x64 and runs under Windows' x64 emulation (Prism): the game, our proxy, the Remix runtime's `d3d9.dll`, and
`nvngx_dlss.dll`. NVIDIA also ships an ARM64 Remix bundle (`.trex_arm64`), but that is for ARM64-native games and is
not usable here.

That is good news, not bad: Portal RTX is x64 and runs well on this machine, so *x64 emulation + Vulkan +
dxvk-remix + DLSS* is a proven combination on this hardware. Our work is not "port to ARM64", it is "run the same x64
binaries on Windows instead of Proton, and find out what behaves differently".

## What ports unchanged

- **Our proxy** is already a native Windows x86-64 DLL built with mingw-w64 (D3D11, DXGI, D3D9, Win32). Its hooks are
  on real `d3d11.dll` vtables, which exist under emulation too.
- **WAX** (`dxgi.dll`) and **LodMod** (`dinput8.dll`) are already Windows x64 binaries.
- **The gates** stay on the desktop: the laptop has no mingw, so tests are cross-compiled here and only *binaries* are
  deployed. Laptop work is runtime validation over ssh, not development.

## What changes

1. **No Proton, no DXVK, no vkd3d**: D3D11 comes from Windows. Our proxy keeps the same name (`d3d11.dll` beside the
   exe) and chain-loads the system one.
2. **No FSR4 chain.** The desktop's `d3d11_dlaa.dll` (AMD-only, RADIX/FSR4) does not exist here; the laptop's quality
   path is Remix's own DLSS, and DL frame generation — which is exactly what `VISION.md` already assigns to this build.
3. **Real `GetRenderTargetData`.** Our composite path currently costs 163 ms of a 190 ms frame *under wined3d*. On
   Windows it is the straight D3D9 runtime call. **This is the single most valuable measurement on this machine**: if
   the frame becomes Remix-bound, our 5 fps was our copy path; if it is still ~5 fps, it is Remix or submission.
4. **Memory.** Windows reports 4 GB for the adapter (unified-memory reporting is unreliable, but assume a tight
   budget): path tracing at 3440x1440 will not fit. Expect a lower `rtx.resolutionScale` plus DLSS.
5. **Paths and environment** become Windows paths and `set`/`$env:` variables instead of the Proton launch line.

## Staged plan, each stage with an acceptance and a rollback

**Stage 0 — desktop, offline.** Confirm the build is portable: x64, no Wine-only calls in the proxy, DLL hash recorded,
launch script written for Windows. Rollback: nothing installed.

**Stage 1 — proxy loads, Remix off.** Copy `d3d11.dll` + `NIER_RENDER.ini` to the game dir (replacing the DLAA proxy,
which is backed up first), `NIER_REMIX=0`. *Accept:* the game runs, menu works, no crash, `NIER_SCALE.log` shows the
proxy active. *Rollback:* restore the backed-up `d3d11.dll`.
This stage alone answers "does our hooking survive x64 emulation".

**Stage 2 — static scene, `NIER_REMIX=1`.** The F9 camp scene, no live capture. *Accept:* path-traced still in the game
window, and a `ms/frame` split with `readback` far below 163 ms. *Rollback:* `NIER_REMIX=0`.

**Stage 3 — live scene, `NIER_REMIX_LIVE=1`.** *Accept:* `analyze_live_run.py` on the laptop log shows a scene target
picked, `skipped_pass` around 1000, meshes following the draw stream, and playable frame rate at whatever
`resolutionScale` the 4 GB budget allows.

**Stage 4 — DLSS and frame generation** through Remix's own options, plus the in-game menu for the settings.

## Open questions to settle before Stage 1

- Does the game launch at all under x64 emulation with our `d3d11.dll` in place, or does the loader reject a
  mingw-built DLL? (It should not; but this is the first thing to see.)
- Which `d3d11.dll` does an emulated x64 process load, and can our proxy chain to it the same way it chains under Wine?
- Is the existing `Nier-Automata-Rendering-depth` project on the laptop current enough to reuse, or does it only hold
  the older "depth" work and should be left alone?
- Actual VRAM budget for path tracing at 1440p, and the DLSS/frame-gen cost on this SoC.

## Why this is worth doing now

The desktop's numbers cannot separate "our copy path" from "Remix" — both are on the same machine and the copy path is
the known outlier. The laptop separates them for free, because the same x64 binaries run against a different D3D9
implementation under a GPU that already runs Portal RTX well. One evening there is worth more than a week of guesses
here.

## Correction after looking at the actually-installed runtime (same day)

Portal RTX on this machine does **not** run the renderer in the game process — it uses the bridge, and the bridge server
is ARM64-native. Evidence from the installed game:

```
rtx-remix\logs\bridge64.log
  Native arch: arm64
  NVIDIA RTX Remix Bridge Server
  Version: remix-main+5a7eec84
  Running in x64 mode!
  Launched server with GUID cebda37e-...
rtx-remix\logs\remix-dxvk.log
  CPU: (NVIDIA) NVIDIA RTX Spark N1X (6144-core GPU, 20-core CPU)
  Skipping Emulated GPU adapter: Microsoft Direct3D12 (NVIDIA RTX Spark N1X ...)
  [GPU Profile] RTX Spark detected (... 47602 MiB device-local memory)
```

Three consequences that overturn parts of the plan above:

1. **Memory is not the constraint.** Device-local memory is reported as **47.6 GB** (unified LPC), not the 4 GB the
   Windows adapter property suggested. Path tracing at 1440p has room.
2. **There are two ways to host Remix, and they differ by an order of magnitude.** Portal RTX ships both
   `bin\.trex\NvRemixBridge.exe` (machine 0x8664) and `bin\.trex_arm64\NvRemixBridge.exe` (**0xAA64**) with an
   ARM64 `d3d9.dll` renderer (282 MB).
   * **In-process (what we do today):** our x64 proxy loads `.trex\d3d9.dll` — on the laptop that is the x64 renderer,
     so the entire path tracer runs under x64 emulation. Correct, but slow.
   * **Bridge:** x64 proxy → bridge client → IPC → **ARM64 `NvRemixBridge.exe` → native ARM64 renderer**. Only our
     proxy and the scene submission stay emulated.
3. **The bells and whistles are all there in `.trex_arm64`:** `nvngx_dlss.dll`, `nvngx_dlssd.dll` (ray
   reconstruction), `nvngx_dlssg.dll` (frame generation), `NRD.dll`, `NRC_Vulkan.dll`, and **`nvngx_dlssnr.dll`** —
   the DLSS 5 neural-rendering component that `VISION.md` records as parked because the DLL could not be obtained. On
   this machine it ships with the runtime. (Same distribution boundary as everything else in a game install: usable
   here, not redistributable.)

So the staged plan gains an ordering: get correctness with the **in-process x64 renderer** first (least new code, our
current architecture), then switch the same proxy to the **bridge** for the native ARM64 renderer. The bridge client is
the work: `NVIDIAGameWorks/bridge-remix` PR #12 ("BridgeApi") and xoxor4d's fork are the reference implementations, and
the bridge is already proven on this hardware by Portal RTX itself.

## First attempt, 2026-10-30 (unattended, logs only; `analysis/deploy/laptop_port.py install|run|restore`)

Build `b8ff96b8…` (the gated, not-yet-installed desktop build). Chain on the laptop: our `d3d11.dll` → the laptop's
NIER_DLAA proxy (DLSS build, `6ba266d6…`) renamed `d3d11_dlaa.dll` → system `d3d11.dll`. Launched directly with
`steam_appid.txt` so the `NIER_*` environment reaches the game. Receipts: `analysis/runtime/laptop-port/*.json`.
The game folder was restored exactly afterwards (hash-checked; everything the runs created removed).

- **Stage 0 passes.** The DLL imports only standard Windows libraries; Remix and d3dcompiler are loaded at runtime.
- **Stage 1 first crashed** (access violation inside our DLL at the first Present, during ImGui setup). Cause: the
  laptop DLAA loads `ec_hooks.dll`, a MinHook-API hook library for Windows on ARM that finds "the d3d11 module" and
  writes trampolines into its spare space ("slack"). Behind our proxy, the module named `d3d11.dll` is ours, so it
  wrote into our code. With `ec_hooks.dll` set aside for the run (`--no-ec-hooks`), **Stage 1 passes**: 90 s, no crash,
  menu ready at 1600x900; the user saw the game run. Behind our proxy the DLAA's hooks never initialize anyway
  (`MH_ERROR_NOT_INITIALIZED` on every hook), so nothing is lost by it. The mock game (`menu_overlay_mock_game.cpp`
  + stub chain DLL) also runs cleanly on the laptop: our hooks and ImGui work under x64 emulation.
- **Stage 2 crashed** 0.3 s after Remix created its 2880x1800 swapchain, before the first frame: Remix's crash
  handler caught a **stack overflow (0xC00000FD) in NVIDIA's D3D11 driver** (`nvwgf2umaxec.dll`, ARM64EC). The
  overflowing stack alternates driver → system `d3d11.dll` → Steam overlay (`gameoverlayrenderer64.dll`) → `dxgi.dll`;
  our proxy is not in the visible frames. Dump: `runtime/laptop-port/dumps/stage2.dmp` (`checks/read_minidump.py`).
  Not yet explained; next experiments: Steam overlay off for NieR, and a smaller Remix size than the monitor's.

Production fix for `ec_hooks` (not done): either ship without the laptop DLAA (Remix brings its own DLSS), or chain
through a copy that resolves the *system* d3d11. Two other notes for the bridge stage, from studying
Kamzik123/ac2-rtx: the Remix API through the bridge needs `exposeRemixApi = True` in `.trex/bridge.conf`, and their
game lights never worked that way.

### Same day, later: what kills stage 2
- Mock game + our proxy + the **real** in-process x64 Remix runtime on the laptop: Remix starts fine, at 1440x900 and
  (with `__COMPAT_LAYER=HighDpiAware`) at NieR's 2880x1800. So in-process Remix next to native D3D11 on the ARM
  driver works, and size is not the trigger.
- NieR with the Steam overlay switched off for the game: same crash. The dump shows the overlay **still loaded**
  (a direct launch with `steam_appid.txt` gets it from steam_api regardless of the per-game toggle) and a recursion
  `menu_overlay::present` (ours, `d3d11.dll+0xed90`) → `gameoverlayrenderer64.dll` → … → ours again, starting once
  Remix starts. Dump `runtime/laptop-port/dumps/stage2-overlay-off.dmp`.
- Next: launch through Steam (so the toggle applies) instead of directly. That needs the `NIER_*` settings from a
  file rather than the environment. Then, separately, make our Present hook safe against the overlay's re-entry.
- Launched **through Steam** with the overlay toggled off for NieR (settings via the new `NIER_ENV.ini`, build
  `233e5600…`): settings applied, same crash at Remix start. The dump shows `gameoverlayrenderer64.dll` **still
  loaded**: Steam injects it (screenshots, FPS counter) whatever the toggle says, so the overlay cannot be avoided by
  configuration. Both of our frames on the overflowing stack are the same return address (the call to the next
  Present), so the loop is hook-to-hook: ours → Steam's → ours, not our code presenting again. Working hypothesis
  (unverified): starting Remix makes something touch DXGI, Steam re-hooks Present and stores our hook as its single
  "original". Fix candidates: forward to DXGI's real Present instead of the vtable's previous entry, or wrap the swap
  chain instead of patching the shared vtable. Either needs a mock overlay that re-hooks, written first.
  Dump: `runtime/laptop-port/dumps/stage2-steam.dmp`. The desktop never showed this: under Proton the Steam overlay
  hooks Vulkan, not DXGI (INFERRED).

## SUCCESS — 2026-10-30 noon: stage 2 composites inside NieR, x64 and native ARM64EC

This supersedes the earlier startup-blocker notes. No desktop game launch/install was performed. Laptop runs were
bounded and restored the game's original files afterwards; no save was loaded and no desktop screenshots were taken.

### Hook fixes (source in `menu_overlay.cpp`)

1. Install Present in an **object-private copy** of the swapchain's vtable, leaving the shared DXGI class table alone.
   The mock overlay reproduces function rediscovery through a dummy swapchain: 51 looping frames before, 80 calls and
   zero loops after. This models the cycle in the dump; it is not a decompilation of Steam's hook implementation.
2. Preserve the interface floor promised by the factory (18 base, 29 v1), even if QI returns another interface pointer.
   SDK `sizeof` assertions cover 18/29/36/40/41 slots. If the shared downstream pointer changes between swapchains,
   leave the new one untouched instead of changing the saved chain for the old one.
3. Factory hooks are global, so they also see **driver/Remix DXGI swapchains**. With only fix 1, the game progressed
   beyond the stack overflow but crashed on the Remix worker while its driver created a swapchain; our adoption log
   fired for it. Device-identity filtering fixes that: bind at the first actual swapchain, then ignore other devices.
   Binding to the first proxy-created device was too early (temporary device enumeration): the reviewer found it,
   the new gate reproduced it, and binding was deferred. Session references/private tables are deliberately retained.

Gates: `test_present_overlay_rehook.py` (overlay rediscovery, changed downstream chain, proxy-first temporary device
plus a foreign-device swapchain), `test_present_interface_floor.py`; existing menu/camera/host/native-HUD regressions.
The fixture cannot establish every third-party COM implementation; real laptop runs below supply native evidence.

### ARM runtime: actually inspect and load it, do not trust the folder name

Installed `.trex/d3d9.dll` is x64 (Machine 8664). Installed `.trex_arm64/d3d9.dll` is classic ARM64 (AA64); an x64
process rejects it with `ERROR_BAD_EXE_FORMAT` (193). That is not an ARM64EC runtime.

The official **x64-game** 1.6.1 package contains a separate `d3d9_a64ec.dll`:
- URL: `https://github.com/NVIDIAGameWorks/rtx-remix/releases/download/remix-1.6.1/rtx-remix-for-x64-games-release-remix-1.6.1.zip`
- ZIP size 557087446; SHA256 `7dd1d44492a609050e44b0e3581cec31135d1ed88b4a91123b4faae91955716a`.
- EC DLL size 283582064; SHA256 `fff99d8f944514a6d7c576d9a7386b4b22d2388b58afe1d98ebba9f1fc2956df`.
  Matches the published `-crc.txt` entry. The archive SHA is locally computed; the DLL SHA matches upstream's manifest.
- PE Machine is 8664, **but CHPE metadata is nonzero** (load-config pointer `0x190c8a818`); do not identify this as
  ordinary x64 from Machine alone. The `runtime_loader_probe.cpp` x64 process loads it successfully and sees
  `remixapi_InitializeLibrary`; no device was created by the loader-only probe.
- Full package staged in `C:\Users\suraj\Downloads\NieR-Laptop-Port\upstream-1.6.1-x64`, never installed over Toolkit
  or Portal files. Licenses/dependencies retained. `NIER_REMIX_RUNTIME` points explicitly at `d3d9_a64ec.dll`.

### Runs and limits

Proxy `ffc0f3cc3b62456161b7dddf9af5272afdf17f819fd59caa6d753d8e763db517`:
- `stage2-private-game-device-20261030T115626Z.json`: x64 runtime, 90 seconds; first composited 2880x1800 frame,
  process alive at timeout, no dump; last 3 windows 19.8 / 23.2 / 23.0 fps.
- `stage2-private-game-device-ec-20261030T115811Z.json`: EC runtime, 90 seconds; first composited 2880x1800 frame,
  process alive at timeout, no dump; last 3 windows 19.5 / 24.1 / 23.9 fps.
- Final proxy after temporary-device ordering fix `cee4d891154b39ba84d7964ecd63cd212d6f94e7aa62f9bdbf47444308738a93`:
  `stage2-ec-final-owner-deferred-*.json`, 60 seconds, first composition at 2880x1800, alive/no crash, late 19.2/18.0 fps.

These are **static captured-camp** submissions over the game, not live draw-stream/gameplay tests. They are logs-only,
not visual acceptance of the displayed image. Sequential battery-powered runs, no controlled native-vs-emulated
performance conclusion. The initially-small game backbuffer transitioned to the monitor resolution on its own, so
no resolution override was required. First timing window includes a bad warmup bucket (`other` can be negative): use
later windows. Output readback still includes GPU completion, not only transfer time.

Restored original laptop `d3d11.dll` SHA256 `6ba266d64a8f67767700c535ee0c3c0596cf50280cf3e301e68518d8e3418b5a`;
`ec_hooks.dll` put back; task-created files removed. The runtime package and test receipts remain only in scratch.
Next stage: live capture in actual world gameplay, when the user can run it. The working EC path no longer needs a
bridge implementation to get native renderer code into the x64 game process.

### Launcher reliability fixes

- Send encoded PowerShell **over stdin** behind a fixed bootstrap to avoid cmd.exe's 8191-character command-line
  limit. Gate `test_laptop_port_transport.py` checks exact long Unicode round-trip without SSH.
- `AllowStartIfOnBatteries` / `DontStopIfGoingOnBatteries`, matching the existing render runner. The laptop was on
  battery, and the old default prevented task launch silently. No-PID/no-log attempts did not exercise the DLL.
- Task result is recorded. Rollback was executed in `finally` on the live attempts, and original hashes verified.

Final verification: **56/56 `analysis/checks/test_*.py` gates pass**, including the explicit header-path arguments
for camera/scene/scale tests. Runner recorded hashes of all checked source files before the run and confirmed they
were unchanged at completion (`runtime/present-overlay-rehook/full-suite.json`). Native EC evidence uses the same
final candidate `cee4d891…`; no global/runtime/Steam settings were changed by this final test round.
