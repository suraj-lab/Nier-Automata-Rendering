# Roadmap: finish the desktop build, then port to the laptop

Decided 2026-10-29. This is the order of work; `PLAYABILITY_PLAN.md` holds the *what* for each item and
`LAPTOP_PORT.md` holds the port detail.

## Standing rule: laptop first (user, 2026-10-29)

Every change that affects the rendered picture is proven on the laptop (RTX Spark, `remix-probe/run_remote.py`, same F9
capture, A/B against the previous render) **before** it goes into the live DLL or asks the user for a game run. The
probe and the live path share the conversion code (`nscn_scene.h` materials, `light_convert.h` lights), so what the
laptop shows is what the live path submits. A desktop game run is for what only the game can show (live capture,
timing, HUD), never for "does it look right".

## The rule

**Finish the desktop build first, then port.** Reason: porting now would mean debugging two unknowns at once — four
offline-verified changes nobody has seen run, and a platform where our DLL has never loaded. One short desktop session
separates "our change is wrong" from "the platform is different", and it means the laptop starts from a known-good DLL.

Division afterwards: **desktop** = AMD/FSR4 correctness and the gate harness; **laptop** = performance and visual
reference (native ARM64 renderer via the bridge, DLSS / RR / frame generation).

## Phase 1 — desktop: the picture (finish)

| # | Item | State | Gate / evidence | Blocked on |
| --- | --- | --- | --- | --- |
| 1.1 | A1 render-target filter | gated, not run in game | `test_live_scene_target` | live run |
| 1.2 | A2a alpha → cutout | gated, not run in game | `test_live_alpha_state` | live run |
| 1.3 | Late-material rebuild + `TEX_PER_FRAME` | gated, not run in game | `test_live_late_material` | live run |
| 1.4 | `untextured=` / `textures=` instrumentation | gated, not run in game | existing suite | live run |
| 1.5 | A3 lights from the tiled-forward arrays | **done, gated** (`2717a855`) | `test_live_lights` | live run |
| 1.6 | Validate 1.1–1.5 in one live session | not started | `analyze_live_run.py` verdicts | **user: install + launch** |
| 1.7 | White-surface cause | open again (my first explanation was wrong) | verdict line from 1.6 | 1.6 |
| 1.8 | A6 HUD capture + replay | **done, gated** (`20757e92`) | `test_live_hud_capture` (pixels) | live run |
| 1.9 | A4 sky category | **done, gated** | `test_live_geometry` (sky scenario) | live run |
| 1.9b | A5 `SMOOTH_NORMALS` / `HAIR_CARDS` | deferred: no evidence which draws | — | shader declarations per draw |
| 1.10 | A7 stability: 10-minute run, flat counters | instrumented | `analyze_live_run.py` | live run |

## Phase 1 test protocol — the gate that is not a test harness

Everything in phase 1 is green against software mocks. **None of it has run in NieR.** This is the procedure that turns
"gated" into "verified", and it is deliberately one session: nine changes, one log, one verdict list.

**0. Preconditions.** The reviewed build is the one in `analysis/PHASE1_REVIEW.md` ("Reviewed candidate"), built by
the suite into `analysis/runtime/menu-dll/d3d11.dll`. If the tree changes, re-run the suite and re-record the hash.
Record the Mesa version (`pacman -Q mesa`; below 25.1.3 is a known-bad RDNA4 baseline). No Special K / ReShade, Remix
frame generation and Reflex off.

**1. Install.** `python3 analysis/checks/install_live_dll.py --install --expect <reviewed sha256>`. It refuses any other
hash and refuses while NieR runs. It backs up the current DLL with a receipt and `RESTORE.md` to `<repo>/backups/live-scene-<stamp>/`,
then replaces the DLL atomically.

**2. Launch** with the usual line plus `NIER_REMIX=1 NIER_REMIX_LIVE=1 NIER_REMIX_LIVE_TEX=<absolute path>`, render
preset Custom75. Do **not** pass `NIER_REMIX_LIVE_SKIP_SMALL_VIEWPORT` (obsolete) or `NIER_REMIX_LIVE_ALL_TARGETS` (that
disables the filter).

**3a. Look (about 2 minutes):** the Resistance Camp (lamps, pods, foliage), a few steps of camera movement, one menu
opened and closed (the in-game settings panel too), one F10 round-trip into the original view and back. Do **not** use
the capture button in the Remix menu (rtx-remix #671 crashes on API meshes with no albedo).

**3b. Soak (at least 10 minutes, same launch):** walk around, change area once (a loading screen), and change the
display resolution once and back (exercises `paused`/`resumed` and the filter latch). Then quit normally.

**4. Read the log**, not the picture first: `python3 analysis/checks/analyze_live_run.py`. It reads only the last run in
the appended log and prints one PASS / FAIL / LOOK / SHORT line per row below (LOOK = the log is fine, now check the
screen). 1.10 needs at least 15 stats samples (SHORT otherwise). Save `journalctl -k -b > backups/<stamp>-kernel.log`
afterwards: a GPU hang shows there first.

### Acceptance, item by item

| # | Expected in the log / on screen | Fails if |
| --- | --- | --- |
| 1.1 | `scene=2580x1080`, `skipped_pass` in the high hundreds or thousands, `draws` around 1400 not 2900 | the log says `filter latched off` (3 consecutive empty frames), or `draws` still ~2900 |
| 1.2 | `blended=` in the hundreds | `blended=0`: NieR does not use straight alpha for foliage and the rule needs widening |
| 1.3 | no runaway `built=`, no `dropped=`, `meshes` stable | meshes climbing every sample, or the frame stuttering when textures stream in |
| 1.4 | `untextured=` small relative to `draws` | `untextured` high **and** `textures=` 0 → capture path; `textures=` growing but `untextured` high → material creation |
| 1.5 | lamps and pods light the scene; `lights=` nonzero; `light_creates=` grows with moving lights, not by thousands per sample | `lights=0` (array never read), still one sun, or lights flickering on and off |
| 1.8 | HUD visible over the path-traced image, `hud=` nonzero | HUD missing (`hud=0`), or the whole frame corrupt after Present (state not restored) |
| 1.9 | `sky=` nonzero; sky present where it used to be absent, not enclosing the camera | black band remains, or the world looks like it is inside a shell |
| 1.10 | counters flat across samples over 10 minutes | `meshes`/`mesh_bytes` growing, `dropped` climbing, watchdog reports |

### Recording the result

Fill this table in this file after the run (and copy the verdict to `PROGRESS.md`), so the next session starts from facts:

| item | expected | observed | verdict |
| --- | --- | --- | --- |
| 1.1 filter | | | |
| 1.2 cutout | | | |
| 1.3 late material | | | |
| 1.4 white surfaces | | | |
| 1.5 lights | | | |
| 1.8 HUD | | | |
| 1.9 sky | | | |
| 1.10 stability | | | |

### If it goes wrong

* **Any crash: read Remix's own minidump first.** The runtime's Sentry/crashpad handler writes
  `<game>/data/rtx-remix/logs/.sentry-native/reports/*.dmp` even when Proton logs nothing. Run
  `python3 analysis/checks/read_minidump.py <dmp> d3d11 d3d9` to get the exception, the module+RVA and the stack. Our DLL
  carries DWARF line info, so `x86_64-w64-mingw32-addr2line -e analysis/runtime/menu-dll/d3d11.dll <0x375xxxxxx>` maps a
  fault inside it to a source line (preferred base 0x3_7500_0000 + RVA). For a fault inside Remix, look for the
  debug-name string near the call site (2026-10-29: "Surface Material Buffer").
* **Crash on launch or on Present:** restore the backed-up `d3d11.dll`, relaunch with `NIER_REMIX=0` to confirm the proxy
  itself is fine, and re-run the matching gate. A GPU fault leaves a coredump at
  `/sys/class/drm/card1/device/devcoredump/data` and lines in `journalctl -k`.
* **HUD corrupting the frame or misplaced:** relaunch with `NIER_REMIX_LIVE_NO_HUD=1` (no HUD capture, no replay). If
  the frame is then clean, the cause is `hud_replay.h`. Misplaced sprites mean NieR's HUD vertex shader uses CB11
  differently from the world shaders: check the multiply in `hud_replay.h`'s VS.
* **Sky looks like a shell:** relaunch with `NIER_REMIX_LIVE_NO_SKY=1`, which drops the dome as before 1.9.
* **Picture empty or full of shadow-map copies:** the filter. `NIER_REMIX_LIVE_ALL_TARGETS=1` is the old behaviour.
* Every failure here is worth a gate: the point of the suite is that the same mistake cannot come back quietly.

## Phase 2 — desktop: the hardware (DEFERRED by decision 2026-10-29)

**Order changed by the user: Phase 1, then Phase 3.** Desktop performance work is deferred because the laptop is where
performance gets measured and where the renderer can run natively (Phase 3.4). Phase 2 only resumes if the laptop route
stalls, or if a desktop-only measurement is needed for the AMD/FSR4 build.

The items below stay in the roadmap, unordered, as the backlog for that case:


| # | Item | State | Notes |
| --- | --- | --- | --- |
| 2.1 | Readback (163 ms of a 190 ms frame) | measured, not fixed | route B1: `dxvk_CopyRenderingOutput` into an owned surface, pipelined publish, GPU-side conversion |
| 2.2 | Submission cost with the filter in place | unknown | ~1400 draws instead of 2900; upstream `drawcall2` instance preservation is the follow-up |
| 2.3 | Resolution / FSR4 inputs | knob exists | `SetConfigVariable("rtx.resolutionScale", …)` instead of a relaunch |
| 2.4 | Latency budget for a pipelined publish | unknown | decide against FSR FG |

## Phase 3 — the laptop

| # | Item | State | Accept |
| --- | --- | --- | --- |
| 3.1 | Stage 1: our DLL loads under x64 emulation, Remix off | not started | game runs, log shows the proxy |
| 3.2 | Stage 2: static scene with the in-process x64 renderer | not started | **real `GetRenderTargetData` cost**, path-traced still |
| 3.3 | Stage 3: live scene | not started | `analyze_live_run.py` verdicts on the laptop log |
| 3.4 | Bridge: x64 proxy → ARM64 `NvRemixBridge.exe` → native renderer | not started, biggest item | frame rate in the same class as Portal RTX |
| 3.5 | DLSS / ray reconstruction / frame generation | not started | the "bells and whistles" target |
| 3.6 | DLSS 5 NR (`nvngx_dlssnr.dll` ships in `.trex_arm64`) | parked since 2026-10 | revisit only after 3.5 |

## What "left" looks like in sessions

Focused working sessions, assuming nothing new breaks:

- **Phase 1: 3–4.** A3 finishing, one live validation session plus the fixes it uncovers, A6+1.9 in one sitting, A7
  folded into the validation run.
- **Phase 2: 3–4.** The readback fix is one session plus a validation; submission tuning is one; resolution/latency a
  shared half.
- **Phase 3: 4–6.** Stages 1–3 are 2 sessions. The bridge (3.4) is the risk: it needs a client built against
  `bridge-remix`'s BridgeApi and our proxy rewired to it — call it 2–3 sessions with real uncertainty. 3.5 is one.

So: **~10–14 sessions to "playable with the things an RTX game should have" on the desktop**, and **~4–6 more** for the
laptop to run the renderer natively. That excludes two unknowns that have historically cost a session each: whatever the
next live run exposes, and the doubling/washout artefacts that are still unexplained.

Cheapest real progress from here, in order: **one desktop live run** (validates four changes, answers the white-surface
question, costs minutes), then A6+1.9 (the last picture items), then straight to Phase 3 on the laptop.
