# Web + desktop research, 2026-11-14: C2 diagnosis on Linux, frame-generation alternatives, Steam overlay, Windows-on-ARM

Read-only. Nothing built, run, installed or changed. Web pages fetched with `curl` to `/tmp` and stripped of markup;
desktop inspected with `cat /proc/...`, `sysctl`, `man`, `ls`, `pacman -Q`, `getcap`. Where a claim is my inference it
says so; where I could not check it says **UNVERIFIED**.

Contents: §1 C2 (teardown deadlock on Linux) · §2 frame generation · §3 Steam overlay with two swapchains ·
§4 Windows on ARM · §5 contradictions with `PLAN_2026-11-14.md` · §6 Open questions · §7 Recommended steps.

---

## 1. C2 — diagnosing the teardown deadlock on Linux

### 1.1 What the repo already establishes (no new work needed)

| Fact | Evidence |
| --- | --- |
| The hang is reproduced by `REPLAY_EXIT=clean` (return from `main` instead of `TerminateProcess`) | `analysis/replay/capture_replay.cpp:496-505` |
| With Remix off and the proxy loaded (`--mode off`) exit takes 4.1 s; with Remix on it never exits | `analysis/PLAN_2026-11-13.md:1296-1300` |
| Not proportional to frame count; warm shader cache does not help; 422 s with all 300 frames presented | `PLAN_2026-11-13.md:1272-1290` |
| The proxy never calls `remixapi_Shutdown` — the only assignment of `api->Shutdown` in `analysis/checks/` is the fake runtime | `analysis/checks/remix_live_fake_runtime.cpp:372`; `grep -rn 'remixapi_Shutdown' analysis/checks/*.cpp` → no hits |
| No `DllMain`, no `FreeLibrary`, no teardown function in our proxy | `grep -n 'FreeLibrary\|DllMain\|atexit' analysis/checks/remix_live.cpp` → only a comment at `:172` |
| The replayer's own comment says what hangs: "DLL detach waits on its worker threads forever" | `capture_replay.cpp:496-497` |
| `gdb -p` on the hung process: `ptrace: Operation not permitted` | `PLAN_2026-11-13.md:1283-1284` |

**Consequence that changes the diagnosis.** Since our code never calls `remixapi_Shutdown`, the wait cannot be the
`waitForShaderPrewarm` loop that `PLAN_2026-11-13.md:1248-1250` blames (that loop is reached from
`RtxInitializer::onDestroy`, i.e. only through the device destructor driven by `Shutdown`). What hangs instead is the
runtime's own C++ static destructors / CRT `DLL_PROCESS_DETACH` inside `ExitProcess`, which the earlier "skip
`Shutdown`" mitigation does not avoid — and does not need to, because it is already the case.

**A second consequence for any dump.** `ExitProcess` terminates all other threads *before* the loader runs the DLL
detaches. So a dump taken during the hang shows the **main thread's** stack (that is where the deadlock is) plus
already-terminated worker threads. One good stack is enough to name the wait; do not expect to see what the workers
were doing at that instant.

### 1.2 `kernel.yama.ptrace_scope` — what the values mean, and what this machine has

Primary source: <https://www.kernel.org/doc/html/latest/admin-guide/LSM/Yama.html> (fetched, quoted).

| Value | Meaning (kernel doc wording, abridged) |
| --- | --- |
| 0 | "classic ptrace permissions: a process can PTRACE_ATTACH to any other process running under the same uid, as long as it is dumpable" |
| 1 | "restricted ptrace: a process must have a predefined relationship with the inferior… by default… only its descendants… an inferior can call `prctl(PR_SET_PTRACER, debugger, …)` to declare an allowed debugger PID" |
| 2 | "admin-only attach: only processes with CAP_SYS_PTRACE may use ptrace" |
| 3 | "no attach: no processes may use ptrace with PTRACE_ATTACH nor via PTRACE_TRACEME. Once set, this sysctl value cannot be changed" |

**This desktop: `kernel.yama.ptrace_scope = 1`** (`cat /proc/sys/kernel/yama/ptrace_scope`, `sysctl
kernel.yama.ptrace_scope` → `kernel.yama.ptrace_scope = 1`). Kernel `7.3.3-1-cachyos` (`uname -r`).

Measured consequences on this machine (read-only probes against another same-uid process):

| Probe | Result | Reading |
| --- | --- | --- |
| `cat /proc/<pid>/wchan` (unrelated same-uid pid) | `do_epoll_wait` — readable | no ptrace check on `wchan` |
| `cat /proc/<pid>/task/<tid>/syscall` | `Operation not permitted` | ptrace access check applies (man `proc_pid_syscall`) |
| `cat /proc/<pid>/task/<tid>/stack` | `Permission denied` | needs `CAP_SYS_PTRACE`; also gives *kernel* stacks only, useless for a user-space deadlock |

Tooling present: `gdb 18.1-1.1`, `strace 7.3-1`, `elfutils 0.197-1` (`eu-stack`), `systemd 262.1-1`
(`coredumpctl`), system Wine `wine-11.21` (`/usr/bin/winedbg`). **Absent**: `lldb` (not in the repos:
`error: package 'lldb' was not found`), `pstack`, `procdump`. `getcap /usr/bin/gdb` → empty, i.e. gdb has no
`cap_sys_ptrace` today.

### 1.3 Scoping a permission change, cheapest first

| Route | What it costs | Scope | Notes |
| --- | --- | --- | --- |
| `prctl(PR_SET_PTRACER, PR_SET_PTRACER_ANY)` from **inside** the target | no root, no sysctl | that process only, until it exits | kernel doc: "If a process wishes to entirely disable these ptrace restrictions, it can call `prctl(PR_SET_PTRACER, PR_SET_PTRACER_ANY, …)`". Our proxy is a DLL in the target, so it *can* do this — but a Win32 DLL has no `prctl`; it would need a raw `syscall` (x86-64 `SYS_prctl` = 157, `PR_SET_PTRACER` = `0x59616d61`) or a Wine unixlib call. Hacky; **UNVERIFIED** that an inline syscall from a Win64 DLL under Wine is safe. |
| Launch the game **as a child of the debugger** | none | that session | Yama 1 allows ancestors. Simple for the *fake* mode (`winedbg <exe>`), awkward for `--mode real` because the chain is `gamescope → proton → pressure-vessel → wine → exe`. |
| `CAP_SYS_PTRACE` on the debugger | `sudo setcap cap_sys_ptrace+ep /usr/bin/gdb` — persistent, gdb becomes a privilege boundary | every process, permanently | Yama 2 semantics: "only processes with CAP_SYS_PTRACE may use ptrace, either with PTRACE_ATTACH or through children calling PTRACE_TRACEME". Kernel doc says the sysctl itself is "writable only with CAP_SYS_PTRACE". |
| `sudo sysctl -w kernel.yama.ptrace_scope=0` | one command, root | whole machine, until reboot (not persisted unless written to `/etc/sysctl.d/`) | the blunt instrument; `sudo sysctl -w kernel.yama.ptrace_scope=1` restores it |
| `sudo gdb -p <pid>` | root per command | that command | no config change at all; `sudo` carries CAP_SYS_PTRACE |

Note for `--mode real`: the replay runs `proton run` with `STEAM_COMPAT_DATA_PATH=<run>/proton-prefix` **inside
gamescope** (`analysis/replay/run_replay.py:158-165`), so the game process lives inside Proton's pressure-vessel
container while an outside shell does not share its PID view of the wineserver socket. Any outside tool must be started
with the same `STEAM_COMPAT_DATA_PATH` **and** inside the same container to reach that wineserver. **UNVERIFIED**
whether `pressure-vessel` is entered for a bare `proton run` (no `--` Steam client); test with `ps -o pid,cmd -C wine`.

### 1.4 The thing that makes most of this unnecessary: Wine declares its own ptracer

Wine sets, at first-thread init:

```
dlls/ntdll/unix/server.c:1666-1669
#if defined(__linux__) && defined(HAVE_PRCTL)
    /* work around Ubuntu's ptrace breakage */
    if (server_pid != -1) prctl( 0x59616d61 /* PR_SET_PTRACER */, server_pid );
#endif
```

Source: <https://gitlab.winehq.org/wine/wine/-/raw/master/dlls/ntdll/unix/server.c> (wine master `9f8c4ae4`,
"Release 11.22", fetched 2026-11-14; line number as of that commit). The kernel's own Yama document says the same in
prose: `prctl(PR_SET_PTRACER, pid, ...)` "is used by KDE, Chromium, and Firefox's crash handlers, **and by Wine for
allowing only Wine processes to ptrace each other**" (<https://www.kernel.org/doc/html/latest/admin-guide/LSM/Yama.html>).

So under `ptrace_scope=1` the **wineserver** is already an allowed tracer of every Wine process in that prefix. Wine's
cross-process thread/memory access is served by the wineserver, not by the tool: `suspend_for_ptrace()` does
`ptrace(PTRACE_ATTACH, …)` and `read_thread_long()` does `PTRACE_PEEKDATA`
(<https://gitlab.winehq.org/wine/wine/-/raw/master/server/ptrace.c>, `suspend_for_ptrace()` and `read_thread_long()`,
around `server/ptrace.c:284-316` in master). Therefore:

- a plain `gdb -p` from an unrelated process is blocked (observed, `PLAN_2026-11-13.md:1284`), **but**
- `winedbg` is a Wine process talking to the same wineserver, and the wineserver is the declared ptracer.

**This contradicts `PLAN_2026-11-13.md:1284-1286`**, which says `winedbg --command "bt all"` "goes through the same
ptrace" and is therefore blocked. It is a testable difference of one command, not a decision for the user.

Practical wrinkles, checked on this machine:

- The replay's Proton is `/usr/share/steam/compatibilitytools.d/proton-cachyos-slr` (`run_replay.py:31`),
  version `cachyos-11.0-20261015-slr` (`…/version`). It ships **no `winedbg` launcher** in `files/bin/`
  (only `msidb`, `wine`, `wineserver`) but does ship **`files/lib/wine/x86_64-windows/winedbg.exe`** and
  **`dbghelp.dll`** (no `dbgcore.dll`). So the Wine-native debugger is available *inside that Wine session*
  (`wine winedbg.exe …` with the prefix's own wine), just not as a Unix command.
- The system `/usr/bin/winedbg` belongs to `wine-11.21` and its wineserver is not the replay's, so it cannot attach to
  replay processes unless the whole replay is run with system wine (`--mode fake`).

### 1.5 Every way to get all-thread stacks without attaching from an unrelated process

| Route | Needs ptrace from an outsider? | Needs root / system change? | Gives | Verdict |
| --- | --- | --- | --- | --- |
| `winedbg --minidump out.mdmp <wpid>` (Wine's own dump) | no — goes through the prefix's wineserver, which Wine already authorised | no | all-thread minidump (see below) | **cheapest real route if winedbg can be started in that session** |
| `winedbg --command "bt all" <wpid>` / `attach <wpid>` then `bt all` | same as above | no | live text stacks | same; man page: `winedbg [options] [program\|wpid]`, `--command string`, `attach N`, `info proc` (`man winedbg`, local) |
| **In-process** `MiniDumpWriteDump` from our own DLL (watchdog/exit hook) | no | no | all-thread minidump written by the target itself | **recommended: no session plumbing at all**, and we control the trigger (§1.6) |
| `SetsUnhandledExceptionFilter` + `winedbg` as AeDebug | no (Wine spawns it) | no | dump on an exception | useless here — a deadlock raises no exception |
| `kill -ABRT <pid>` → `systemd-coredump` → `coredumpctl gdb` | no (a signal is not ptrace) | no | Linux core: **every Linux thread's stack**, ELF symbols only | works today, see below |
| `eu-stack -p <pid>` | **yes** (`PTRACE_SEIZE`) | no | all-thread stacks | blocked under scope 1 |
| `gdb -p` | **yes** | `sudo` or scope 0 | all-thread stacks | needs §1.3 |
| `/proc/<pid>/task/*/stack` | yes (capability check) | **root** | kernel stacks only | not useful |
| `WINEDEBUG=+seh,+tid` (+ `+relay`) | no | no | log lines, no stacks | see cost below |
| `PROTON_LOG=1` | no | no | Proton/wine stderr log (`~/steam-<appid>.log`); no stacks | cheap context only; **UNVERIFIED** exact path for `proton run` without the Steam client |

**`kill -ABRT` + coredumpctl is real on this machine.** `core_pattern` is
`|/usr/lib/systemd/systemd-coredump %P %u %g %s %t %c %h %d %F %I`, `systemd-coredump.socket` is `active`+
`enabled`, `ulimit -c` is `unlimited`, and `coredumpctl list` already holds cores from this machine (three entries,
including a `SIGABRT` one, 2026-11-13). `man coredump.conf`: `ProcessSizeMax=` "Defaults to 1G on 32-bit systems,
**32G on 64-bit**", so a multi-GB Wine process is not skipped by default. Limits: a Linux core gives Linux thread
stacks — the Windows frames are on those same stacks, but symbols resolve only for ELF modules (ntdll.so, libc,
libvulkan, the Mesa driver); PE modules appear as addresses. Risk: `kill -ABRT` is delivered to one thread that does
not block it; **UNVERIFIED** whether Wine blocks SIGABRT in its threads (if it does, nothing happens and you must use
`SIGQUIT`, or `coredumpctl` nothing).

**`WINEDEBUG` cost.** `man wine` documents the syntax and shows `WINEDEBUG=relay` = "all relay messages (API calls)",
`win+relay`/`+relay` gives one line per call across every DLL. No quantitative figure is published (Wine's developer
guide wiki page is behind an anti-bot wall: <https://gitlab.winehq.org/wine/wine/-/wikis/Wine-Developer's-Guide/Debugging-Wine.md>
returned an Anubis challenge page) — **UNVERIFIED** as a number, but `+relay` on a 3,000-draw frame stream is not a
practical option; `+seh,+tid` only logs exceptions and thread ids and is affordable.

**Wine's minidump is good enough for stacks.** `winedbg --minidump` writes with `MiniDumpNormal`
(`programs/winedbg/tgt_minidump.c:78-79` in master, fetched). Wine's writer emits, per thread, the context **and the
thread's stack memory** even for `MiniDumpNormal` (`dlls/dbghelp/minidump.c:130-156`, `:666`
`ThreadWriteThread|ThreadWriteStack|ThreadWriteContext`, `:702-708`), so `MiniDumpNormal` already contains what a
stack scan needs. `MiniDumpWriteDump` is exported by Wine's `dbghelp.dll` (`dlls/dbghelp/dbghelp.spec:31`); Wine lists
`MiniDumpWithDataSegs`, `MiniDumpWithHandleData`, `MiniDumpFilterMemory`, `MiniDumpScanMemory` as "NIY"
(`minidump.c:1044-1051`) — do not ask for those.

### 1.6 Recommended: an in-process dump at exit, which is also the fix

Design (all inside our DLL, so no ptrace, no root, no sysctl, works in the game as well as in the replay):

1. `analysis/checks/remix_live.cpp`: add `dump_all_threads(const wchar_t* path)`:
   `LoadLibraryW(L"dbgcore.dll")` first (Windows puts `MiniDumpWriteDump` there), fall back to `dbghelp.dll` (Wine
   only has it there — verified above), `GetProcAddress("MiniDumpWriteDump")`, then
   `MiniDumpWriteDump(GetCurrentProcess(), GetCurrentProcessId(), file, MiniDumpNormal|MiniDumpWithThreadInfo, …)`,
   `MiniDumpWithFullMemory` only behind an env switch (size). Self-dump needs no permissions.
2. Trigger A (harness, proves the path in one run): export `nier_remix_dump()` from the proxy; in
   `analysis/replay/capture_replay.cpp:499-502` (the `REPLAY_EXIT=clean` branch) call it **before** `return 0`.
   One run gives us the stack we have been missing since 2026-11-13.
3. Trigger B (the game, and the real fix): hook `ExitProcess` (and `RtlExitUserProcess`) once, the same way the
   project already patches entry points: on entry, write the dump (bounded, e.g. 5 s watchdog), then
   `TerminateProcess(GetCurrentProcess(), code)` and never let the loader detach the runtime. That is exactly what the
   replayer does today by brute force (`capture_replay.cpp:503`), turned into a deliberate, gated behaviour.
4. Read the dump with the tool that already exists: `analysis/checks/read_minidump.py` parses `STREAM_THREADS`,
   `STREAM_MODULES`, `STREAM_MEM64` (`:11`) but currently prints only the **exception** thread and a heuristic module-RVA
   scan of its stack (`:1-11`, 98 lines). Extend it to loop over every thread in `STREAM_THREADS` (ThreadId, stack
   start/size, context RVA) and scan each stack — that turns any dump into an all-thread stack list, on Linux, with no
   debugger. Because a deadlock has no exception record, this extension is mandatory, not optional.
5. Gate before the code: extend the fake runtime with a switch that wedges **DLL detach** (a `DllMain(DLL_PROCESS_DETACH)`
   that never returns) — the same shape as the real hang — e.g. `FAKE_REMIX_HANG_DETACH=1` next to the existing
   `FAKE_REMIX_FAIL=hang:present` (`analysis/checks/remix_live_fake_runtime.cpp:366`). The gate runs `--mode fake` with
   `REPLAY_EXIT=clean`, and asserts: process exits < 10 s, dump file exists, `read_minidump.py` reports ≥ 2 threads.
   See the "fail for the right reason" rule: with the dump switch off the gate must fail.

Do **not** build the fix on `remixapi_Shutdown`: it is never called, and `remix_api.cpp:1674-1678` force-releases the
game's own COM references anyway (`analysis/replay/research-2026-11-13/remix_exit_path.md`, §1 and the caveat at its end).

### 1.7 The same hang on the laptop, no tooling needed

- `procdump -ma <name|pid>` writes a **Full** dump; even the default `-mm` mini dump "includes directly and indirectly
  referenced memory (**stacks** and what they reference)"
  (<https://learn.microsoft.com/en-us/sysinternals/downloads/procdump>, fetched). Manual timing: run it from a second
  shell while the game hangs on quit — the automatic trigger `-h` waits for an **unresponsive window**
  ("`procdump -h hang.exe`… when one of its windows is unresponsive for more than 5 seconds"), which may not fire
  during a quit, so use the pid form.
- Task Manager: right-click the process → "Create dump file" (**UNVERIFIED** wording on the N1X build; the feature is
  standard on Windows 11).
- Read either dump with the extended `read_minidump.py` — the repo already reads laptop dumps with it
  (`analysis/runtime/laptop-port/dumps/stage2.dmp`, `LAPTOP_PORT.md:145`).

---

## 2. Frame generation when DLSS-G is unavailable or not viable

### 2.1 What the runtime actually has

| Claim | Evidence |
| --- | --- |
| Frame generation in dxvk-remix is **DLSS-G only**, through NGX (`nvngx_dlssg`) | `analysis/runtime/src/dxvk-remix/src/dxvk/rtx_render/rtx_ngx_wrapper.cpp:49-51` (`nvsdk_ngx_helpers_dlssg*.h`), `:907-915` (`NGX_VK_CREATE_DLSSG`), `:1059-1061` (`NGX_VK_EVALUATE_DLSSG`); `rtx_dlfg.{h,cpp}` |
| There is **no FidelityFX / FSR frame generation** in this source tree | `rg -i 'fidelityfx\|ffx_' src` over `analysis/runtime/src/dxvk-remix` → 0 hits (the only `ffx` match is the game name `ffxiv_dx11.exe` in `src/util/config/config.cpp:271`) |
| DLSS-G is a config-visible feature of the runtime in use (`maxInterpolatedFrames`) | `analysis/RTX_OPTIONS_THIS_BUILD.txt:546` (names only, recovered from `.trex/d3d9.dll` strings) |
| So on the AMD desktop "no frame generation" is true *inside* Remix | as above |

### 2.2 The AMD desktop (RX 6800 XT, RDNA2, RADV, Wayland/Hyprland)

**AMD's own AFMF 2 on Linux: does not exist.** AMD's AFMF ships in Adrenalin for Windows; the Linux request is open and
unanswered — <https://community.amd.com/t5/pc-drivers-software/request-for-amd-fluid-motion-frames-2-afmf2-support-on-linux/td-p/763578/jump-to/first-unread-message>
(fetched: "I am a Linux user, I am unable to utilize this feature because it is not currently supported in Linux
drivers"); same conclusion in a Linux Mint forum thread ("System wide frame generation (AFMF) is not yet available in
Linux", <https://forums.linuxmint.com/viewtopic.php?t=431869>).

**Two third-party Vulkan layers are already installed on this machine.** Both hook `vkQueuePresentKHR`, so both see the
game's swapped image — which under Proton *is* our Remix frame, since the proxy blits it into the game's back buffer and
the game presents it.

| Layer | Installed where | Enable / disable (from its own manifest) | State |
| --- | --- | --- | --- |
| afmf-linux 1.3.1 (`VK_LAYER_AFMF`) | `~/.local/lib/afmf-linux/libafmf-linux.so`, manifest `~/.local/share/vulkan/implicit_layer.d/afmf-linux.json` | `AFMF_ENABLE=1` / `DISABLE_AFMF=1` | installed, dormant (`analysis/RESEARCH_RECORD.md:104` item F36; `analysis/VISUAL_STACK.md:15`). Tested by its author on RX 9070 XT (RDNA4) and RX 7800 XT (RDNA3) only — RDNA2 is untested (`analysis/afmf/extract/afmf-linux-1.3.1/README.md:24-40`) |
| lsfg-vk (`VK_LAYER_LS_frame_generation`, package `lsfg-vk-bin 1.0.0-4`) | `/usr/lib/liblsfg-vk.so`, manifest `/usr/share/vulkan/implicit_layer.d/VkLayer_LS_frame_generation.json` | `DISABLE_LSFG=1` in that manifest; the project's current docs use `DISABLE_LSFGVK=1` (v2) | installed **and configured**: `~/.config/lsfg-vk/conf.toml` points at `/home/suraj/.steam/root/steamapps/common/Lossless Scaling` (present) and has one profile, `RPCS3.AppImage`, multiplier 2. Never used for NieR. |

**Hazard, first-party:** afmf-linux's own README says the two must not be stacked, and that the mere presence of
lsfg-vk broke presentation on their test system: *"Do not stack it with another frame generation layer… In particular,
with the **lsfg-vk** implicit layer installed, Vulkan presentation on our RDNA3 test system hung (no window, 8 fps) even
with afmf-linux disabled; uninstall it or set `DISABLE_LSFGVK=1` while using afmf-linux"*
(`analysis/afmf/extract/afmf-linux-1.3.1/README.md`, "Do not stack it…" paragraph). Any frame-generation measurement on
this desktop must therefore pin the environment explicitly (`DISABLE_LSFG=1` or `DISABLE_AFMF=1`) and record which one
was active.

**lsfg-vk state (project):** moved to <https://lsfg-vk.dev> (the GitHub repo README is now just a redirect notice:
<https://github.com/PancakeTAS/lsfg-vk>). It is "a Vulkan layer … hooks into Vulkan applications and generates
additional frames using Lossless Scaling's frame generation" (`https://lsfg-vk.dev/`), i.e. it needs the proprietary
**Lossless Scaling v3.1 frame-generation DLL** from the paid Windows app (installed here), it works per executable
profile, and `DISABLE_LSFGVK=1` turns it off (`https://lsfg-vk.dev/docs/getting-started/`). It therefore attaches to
our app the same way afmf does: at `vkQueuePresentKHR` in the Proton-side Vulkan swapchain.

What neither layer can fix: at ~7-14 fps the source rate is too low for interpolation to look right (afmf's README notes
the gain shrinks when the GPU is already saturated, and its RDNA2-class cost was ~1.2 ms/frame at 3440x1440), and the
presented latency never improves — P2's real target (≥ 40 fps *rendered*) is not reachable this way for the desktop.

### 2.3 The NVIDIA laptop (RTX Spark N1X, Windows on ARM)

Two driver-level facts, both first-party:

1. **Linux NVIDIA driver README, chapter 39 "NVIDIA Smooth Motion"** (fetched from
   <https://download.nvidia.com/XFree86/Linux-x86_64/590.48.01/README/nvpresent.html>): "driver-based AI model that
   delivers smoother gameplay by inferring an additional frame between two rendered frames… on GeForce RTX 40 Series and
   newer GPUs. **The feature supports Vulkan applications.** … enabled by setting the environment variable
   `NVPRESENT_ENABLE_SMOOTH_MOTION=1`… This will enable the `VK_LAYER_NV_present` implicit Vulkan layer". Same page,
   directly relevant to §3: *"The layer presents from an asynchronous compute queue which can cause issues with third
   party overlays. Setting … `NVPRESENT_QUEUE_FAMILY=1` will make the layer present from a graphics queue at the cost of
   some performance."*
2. **Windows / NVIDIA app**: "select a compatible **DirectX 11, DirectX 12 or Vulkan** game in Graphics > Program
   settings… 'Driver Settings', and switch Smooth Motion on" — NVIDIA app update announcing Smooth Motion for RTX 40
   series, <https://www.nvidia.com/en-eu/geforce/news/nvidia-app-global-dlss-overrides-rtx-40-series-smooth-motion/>
   (fetched). Vulkan support for Smooth Motion is reported by
   <https://www.vulkan.org/news/auto-23676-574fc4d693c51106906cc0287881e870> and
   <https://videocardz.com/newz/nvidia-enables-smooth-motion-frame-generation-for-vulkan-api-in-latest-update>.

So on the laptop the promising route is **not** a Remix present takeover: the game presents **D3D11**, and Smooth Motion
has a DX11 path, so it can insert frames into the *game's* presents — which already carry the Remix image, because the
proxy blits Remix's frame into the game's back buffer. That doubles the presented rate without touching Remix, without
DLSS-G, and without the frame-generation/overlay conflict in §3.

Open and **UNVERIFIED**: (a) whether the N1X counts as a "GeForce RTX 40/50 series" GPU for this feature, (b) whether
the NVIDIA app on Windows-on-ARM offers Smooth Motion at all, (c) whether a DX11 *emulated-x64* process qualifies,
(d) whether the feature works in a process that also owns a Vulkan swapchain (ours, once Remix creates its own). Check
(a)–(c) in one minute on the laptop: NVIDIA app → Graphics → Program settings → NieRAutomata → "Driver Settings" →
look for "Smooth Motion".

### 2.4 What the repo already tried

| Attempt | Where | Result |
| --- | --- | --- |
| afmf-linux installed, dormant | `RESEARCH_RECORD.md:21,104` (F36), `VISUAL_STACK.md:15` | "installed and verified" in `PROGRESS.md` refers to install checks only; never tested in game |
| lsfg-vk installed with a profile for RPCS3 | `~/.config/lsfg-vk/conf.toml` | not part of any report; no NieR testing |
| FSR 3.1 / FSR4 frame generation via hookshot | `analysis/replay/research-2026-11-12/fsr4_redstone.md:10-57` | FSR4 ML FG needs Win11 + RX 9000+ and a swapchain it owns; `FrameGeneration.Available=0`; blocked on presentation takeover and on HDR-vs-display-referred colour |
| Dual-GPU split as the speed route | `analysis/DUAL_GPU_PLAN.md` | idea only, not started; the 6800 XT runs the game's own D3D11 frame, the 9070 XT runs Remix |
| DLSS-G off vs on, no present takeover | `LAPTOP_PORT.md:415` | "no measurable change (A vs A2). It stays off while Remix does not present" |

---

## 3. Steam overlay in a process that has both a D3D11 and a Vulkan swapchain

**What Steam supports (first-party):** "The overlay supports games that use DirectX 7 - 12, OpenGL, Metal, and Vulkan"
(<https://partner.steamgames.com/doc/features/overlay>, fetched). It hooks present per API; the docs do not say which one
wins when a process presents on two APIs — **UNVERIFIED**, and in our case the two swapchains belong to different
modules (game D3D11, Remix Vulkan), so the honest statement is "it hooks both what it finds", with per-API hooks:

- Windows: `gameoverlayrenderer64.dll` hooks the D3D11/DXGI Present chain — observed in this project's own process
  (`analysis/DRAW_HOOK_LOSS.md:46-51`, module list; `LAPTOP_PORT.md:144` recursion
  `ours → gameoverlayrenderer64.dll → dxgi.dll`).
- Linux/Proton: the overlay is a **Vulkan implicit layer**, `VK_LAYER_VALVE_steam_overlay_64`, pointing at
  `~/.local/share/Steam/steamrt64/steamoverlayvulkanlayer.so`, with `enable_environment
  ENABLE_VK_LAYER_VALVE_steam_overlay_1=1` and `disable_environment DISABLE_VK_LAYER_VALVE_steam_overlay_1=1`
  (manifest read on this machine: `~/.local/share/vulkan/implicit_layer.d/steamoverlay_x86_64.json`, mtime 2026-11-13).
  **So on the desktop the overlay hooks Vulkan, not the game's D3D11** — it sits in the same place afmf/lsfg/nvpresent
  sit, downstream of DXVK. This confirms the "INFERRED" note at `LAPTOP_PORT.md:171-172` with file evidence.

**Known conflicts with Remix (first-party):** RTX Remix issue #769, still open:
*"Steam and other overlays in general (e.g. MSI Afterburner) are just causing some problems with Remix. We're aware of it
and tracking this internally though as REMIX-3899"* and *"The cause of this has been narrowed down to something with our
**DLSS-FG implementation** not playing well with Steam's overlay layer. As a workaround if you disable Frame Generation in
the Remix menu (accessible by pressing Alt+X) you should be able to take screenshots fine afterwards"*
(<https://github.com/NVIDIAGameWorks/rtx-remix/issues/769>, fetched; duplicates #866, #908). This is the exact pair P2
wants to run together: **DLSS-G + Steam overlay**.

This project's own harder evidence, from the laptop: with the overlay loaded, Remix start ends in a **stack overflow in
the ARM64EC D3D11 driver** through a hook loop `our Present → gameoverlayrenderer64.dll → dxgi.dll → our Present`
(`LAPTOP_PORT.md:142-146`), and **the per-game overlay toggle did not prevent `gameoverlayrenderer64.dll` from being
loaded** — twice: direct launch with `steam_appid.txt` (`LAPTOP_PORT.md:157-160`) and launched through Steam with the
toggle off (`LAPTOP_PORT.md:163-166`: "Steam injects it (screenshots, FPS counter) whatever the toggle says, so the
overlay cannot be avoided by configuration"). Mitigation is on our side: `analysis/checks/test_present_overlay_rehook.py`
(mock overlay that re-hooks) and the fix candidates listed at `LAPTOP_PORT.md:168-170`.

**How to disable it per game / per run**

| Platform | Method | Evidence |
| --- | --- | --- |
| Desktop (Proton, our harness) | set `DISABLE_VK_LAYER_VALVE_steam_overlay_1=1` in the run's env — kills the layer for that run, no Steam setting touched | its manifest on this machine (`disable_environment`), see above |
| Desktop (manual play) | Steam → Library → right-click NieR → Properties → General → "Enable the Steam Overlay while in game" off; global switch in Steam → Settings → In-Game | UI description only; **UNVERIFIED** against a fetched Valve page (the support article <https://help.steampowered.com/en/faqs/view/3978-072C-18DF-FBF9> is JS-rendered and returned no body text) |
| Laptop (Windows) | same per-game toggle — but the repo observed the DLL still loaded and the crash unchanged (`LAPTOP_PORT.md:163-166`), so treat the toggle as insufficient; the reliable switches are ours (forward to the real DXGI Present; wrap rather than patch the shared vtable) | as cited |

---

## 4. Windows on ARM (Prism) — what applies to us

| Point | Evidence |
| --- | --- |
| Prism is the Windows 11 24H2 x86/x64 emulator; "optimized and tuned specifically for Qualcomm Snapdragon processors", with some features limited to Snapdragon X | <https://learn.microsoft.com/en-us/windows/arm/apps-on-arm-x86-emulation> (fetched) |
| "emulation only supports user mode code and doesn't support drivers. Any kernel mode components must be compiled as Arm64" | same page |
| Arm64EC code "interoperates with x64 code running under emulation **within the same process**"; an x64 or Arm64EC process "can load and call into both x64 and Arm64EC binaries, whereas an Arm64 process can only load Arm64 binaries" | <https://learn.microsoft.com/en-us/windows/arm/arm64ec> (fetched) |
| The OS itself leans on this: "Most operating system code loaded by an x64 app running on Windows 11 on Arm is compiled as Arm64EC" | same page |
| Consequence for us: a mixed process is normal and supported — our case (x64 game exe + x64 proxy + ARM64EC D3D11 driver + Remix runtime, x64 or ARM64EC) is exactly the supported shape, but every layer whose hooks cross the emulation boundary is a suspect | inference from the two pages above |
| The laptop's Remix distribution ships both: `.trex\NvRemixBridge.exe` (machine 0x8664) and `.trex_arm64\NvRemixBridge.exe` (0xAA64), the latter with ARM64 `nvngx_dlssg.dll` (frame generation) among the NGX DLLs | `LAPTOP_PORT.md:107-118` |
| Observed failure mode already on file: stack overflow `0xC00000FD` inside `nvwgf2umaxec.dll` (the **ARM64EC** D3D11 driver) with the Steam overlay in the loop | `LAPTOP_PORT.md:142-146` |
| DLSS-G under x64 emulation: not evaluated anywhere in the repo; on the laptop `nvngx_dlssg.dll` was **absent** in the game process during the draw probe (`DRAW_HOOK_LOSS.md:49`) | repo evidence; **UNVERIFIED** whether the x64 `.trex` folder even contains it |
| Smooth Motion under Prism: whether the N1X driver exposes it, and whether it accepts an emulated-x64 DX11 process, is not documented anywhere I could fetch | **UNVERIFIED** — see §2.3 check (a)–(c) |

Not found / not verifiable from here: any Microsoft or NVIDIA statement on **Vulkan + DXGI in one emulated process**
specifically. The nearest documented behaviour is the generic Prism/ARM64EC interop above plus the repo's own crash.

---

## 5. Where this contradicts `PLAN_2026-11-14.md`

1. **C2 is not blocked on permission.** `PLAN_2026-11-14.md:22` says "needs ptrace permission / blocked on permission".
   Three routes need no permission change: Wine's own `winedbg --minidump`/`bt all` inside the prefix (Wine already
   declared the wineserver its ptracer, `dlls/ntdll/unix/server.c:1668` — which also contradicts
   `PLAN_2026-11-13.md:1284-1286`), `kill -ABRT` + `coredumpctl` (systemd-coredump is active here, cores already
   captured), and an in-process dump from our own DLL. The sysctl/sudo route is the *fourth* option, not the first.
2. **The diagnosis in the old plan is probably wrong.** `PLAN_2026-11-13.md:1248-1263` blames
   `RtxInitializer::waitForShaderPrewarm`, reached via `remixapi_Shutdown` → device release. Our proxy never calls
   `remixapi_Shutdown` (`analysis/checks/` has no such call; only the fake runtime assigns `api->Shutdown`,
   `remix_live_fake_runtime.cpp:372`). The wait is in the runtime's CRT/static-destructor detach, so the C2 fix is
   "never run that detach", i.e. `TerminateProcess` at quit, and the C2 evidence is the main thread's stack.
3. **P2's go/no-go test invites the one combination NVIDIA says is broken.** `PLAN_2026-11-14.md:14` wants "Remix
   presents into the game window with the Steam overlay injected" plus "enables DLSS frame generation". RTX Remix #769
   (open) says DLSS-FG + Steam overlay is the crash. Test DLSS-G with the overlay **out** of the process first
   (`DISABLE_VK_LAYER_VALVE_steam_overlay_1=1` on the desktop), and treat overlay+DLSS-G as a separate, likely-failing
   case.
4. **D1's "no frame generation" is only true inside Remix.** `PLAN_2026-11-14.md:24` and `:26-27`. The desktop has two
   Vulkan frame-generation layers installed (`afmf-linux`, `lsfg-vk`), and the laptop has Smooth Motion's DX11 path,
   which does not need Remix to present. And the two desktop layers conflict with each other (afmf README), so the plan
   needs an explicit "which layer is active" pin in every measurement.
5. **The Steam overlay toggle is not a reliable control.** The plan's G-track text (`PLAN_2026-11-13.md:1328-1330`) and
   P2 assume turning it off is enough; the repo already measured that the toggle leaves
   `gameoverlayrenderer64.dll` loaded on the laptop (`LAPTOP_PORT.md:163-166`). Use the Vulkan-layer env var on Linux,
   and fix the hook instead of hiding the overlay on Windows.

---

## 6. Open questions

1. **Does `winedbg` attach work under `ptrace_scope=1` on this machine?** Not tested (it would need the hang
   reproduced). How: reproduce the hang (`run_replay.py … --env REPLAY_EXIT=clean`), then inside the same Proton
   session run `wine winedbg.exe --command "info proc"`, `--command "bt all" <wpid>`, and `--minidump /path/x.dmp <wpid>`.
   Success/failure of each is a one-line result and it settles contradiction (1) in §5.
2. **Which process does `winedbg` need to be a child of, if any?** If attach is denied, check the same command launched
   as `wine winedbg.exe <exe>` (debuggee as child). Also confirm whether pressure-vessel is entered for `proton run`
   (`ps -o pid,cmd --ppid 1 | grep -c pressure-vessel`).
3. **Where exactly does the main thread sit when it hangs?** Only the stack can answer (dpkg: `ntdll.so`/`libc` frames
   will symbolise; PE frames will not). Answered by step 7.1 below.
4. **Does `kill -ABRT` produce a core under Wine/Proton** (are the signals blocked?) — one run, one `coredumpctl list`.
5. **Does `MiniDumpWriteDump` inside the process under Proton return a dump `read_minidump.py` can parse** — and does
   `MiniDumpNormal` from *Wine's* dbghelp contain every thread's stack? (source says yes; needs one run).
6. **Laptop: Smooth Motion availability on the N1X** (RTX 40/50 class? NVIDIA app present? DX11 emulated-x64 accepted?)
   — check in the NVIDIA app; then one run with it on, MangoHud-style capture of the presented rate.
7. **Do afmf-linux or lsfg-vk actually interpolate our Remix-in-game-frame image** (the presents carry a path-traced
   image at 7-14 fps; the layers assume a normal game frame with motion)? Unknown; a single run at 3440x1440 with
   `AFMF_ENABLE=1 DISABLE_LSFG=1` and MangoHud would answer it. Also unknown: whether either layer survives being
   *stacked* with gamescope's own WSI layer (`VkLayer_FROG_gamescope_wsi`) — untested combination, **UNVERIFIED**.
8. **Windows per-game overlay toggle semantics**: does it only stop the *hook* while leaving the DLL mapped? The repo's
   observation implies yes; a definitive statement from Valve was not fetchable.

---

## 7. Recommended steps for the plan

1. **Make a dump possible today, in the replay, with no permission change.**
   File: `analysis/replay/capture_replay.cpp` (the `REPLAY_EXIT=clean` branch, `:499-502`) + `analysis/checks/remix_live.cpp`
   (new exported `nier_remix_dump()` that calls `MiniDumpWriteDump`, dbgcore→dbghelp, `MiniDumpNormal`).
   Check: one `--mode real` run with `REPLAY_EXIT=clean` leaves a `.dmp` in the run directory, and the process still hangs
   (it must — this step only adds the dump).
2. **Extend `analysis/checks/read_minidump.py` to every thread** (`STREAM_THREADS` at `:11`: iterate all threads, print
   each thread's module+RVA stack scan; keep the existing exception path). Check: on the dump from step 1 it prints ≥ 2
   threads, and on the existing `analysis/runtime/laptop-port/dumps/stage2.dmp` it prints the same faulting-thread chain
   as today (regression).
3. **Read the stack from step 1 and name the wait**; record it next to C2. This is the deliverable the plan has been
   missing since 2026-11-13.
4. **Turn the workaround into the fix, gated.** Hook `ExitProcess`/`RtlExitUserProcess` in `remix_live.cpp`: dump (bounded),
   then `TerminateProcess`. Switch `NIER_REMIX_EXIT_DUMP=1` (dump only) / `NIER_REMIX_EXIT_FAST=1` (terminate), both default
   off = today's behaviour. Check: new gate in `analysis/checks/` driven by the fake runtime; add
   `FAKE_REMIX_HANG_DETACH=1` (a `DllMain(DLL_PROCESS_DETACH)` that never returns, `remix_live_fake_runtime.cpp` next to
   `:366`) so `REPLAY_EXIT=clean` wedges by construction; gate asserts exit < 10 s **and** a dump with ≥ 2 threads. The gate
   must fail before the code exists.
5. **Try the no-code routes once each, in this order, and record both outcomes:** (a) `kill -ABRT` + `coredumpctl gdb`
   (`thread apply all bt`) on the hung run; (b) `wine winedbg.exe --minidump` / `--command "bt all"` inside the same
   Proton prefix. Both are permission-free; whichever works becomes the fallback if the in-process dump is ever
   unavailable (e.g. a hang before our DLL loads).
6. **Ask the user only for what is really theirs:** nothing in C2 needs a sysctl now. If steps 1–5 all fail, the ask is
   one line: "may I run one debug session with `sudo sysctl -w kernel.yama.ptrace_scope=0` (reverted immediately after,
   not persisted)".
7. **Frame generation, in this order (each is one measurement, none is a decision for the user):**
   a. Desktop: pin the layers explicitly in `run_replay.py` env — `DISABLE_LSFG=1` always (afmf README's hang), and a
      controlled A/B with `AFMF_ENABLE=1` at 3440x1440 with MangoHud; record presented vs rendered rate. If presentation
      hangs, that is afmf's documented lsfg conflict, and it is evidence for the plan, not a bug to chase.
   b. Laptop: open the NVIDIA app's Driver Settings for `NieRAutomata` and record whether Smooth Motion exists for this
      GPU (one screenshot, no game run). If it does, one run with it on at 2880x1800 with the overlay out of the process.
   c. Keep FSR3-FG off the list: it is absent from the runtime (no FidelityFX in `src`), and the FSR4 route is already
      recorded as blocked (`research-2026-11-12/fsr4_redstone.md`).
8. **Fix P2's spike definition** in the plan: split it into (i) Remix presents into the game window **with the overlay
   layer disabled** (`DISABLE_VK_LAYER_VALVE_steam_overlay_1=1`), and (ii) DLSS-G on top of (i). Case (i) is the go/no-go;
   case (ii) has a known first-party conflict (RTX Remix #769) and must not block the presentation work.
9. **Laptop overlay:** replace the "toggle the Steam overlay off" instruction with the hook fix already scoped
   (`LAPTOP_PORT.md:168-170`: forward to the real DXGI Present, or wrap the swapchain instead of patching the shared
   vtable), and add `gameoverlayrenderer64.dll` to the mock-overlay gate (`test_present_overlay_rehook.py`).
