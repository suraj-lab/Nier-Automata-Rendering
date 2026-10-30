# Draw hooks vanish on the laptop — measured, attributed, and what to run next

**Date:** 2026-10-30 evening. **Machine:** laptop (`spaghetti`, Windows 11 on Arm, RTX Spark N1X), game launched with the
project proxy and `--no-ec-hooks`. **No Remix, no GPU capture, no shaders:** `NIER_DRAW_PROBE=1` runs the CPU-only
diagnostic in `analysis/checks/draw_probe.h`.

This file is the record of five runs. It replaces the guesses in `PROGRESS.md` about why Stage 3 never accepted a world
frame: the draw hooks are not present when the game renders, and they are not present because something puts the
pristine D3D11 function pointers back.

## Runs

| # | label / receipt dir | build | result |
| --- | --- | --- | --- |
| 1 | `runtime/laptop-port/draw-probe-camp` | `43bf8685…` | `hook_mask=3` at 1600x900 (title), `hook_mask=0` at 2880x1800 (25 samples), `indexed=0 instanced=0` |
| 2 | `runtime/laptop-port/draw-probe-2` | `51e56854…` | same loss, plus: `install_attempts=1 install_skipped=0 install_ok=1`, `ctx_installed == armed_context`, `table_installed == armed_table`, `slot12 == orig12` → `restored12=1 foreign12=0` |
| 3 | `runtime/laptop-port/draw-probe-rehook` | `5841afc9…` | re-hooking works (`rehook12=hooked`), slots are ours at every sample, `indexed` still 0 |
| 4 | `runtime/laptop-port/draw-probe-maintain` | `0aa3b24b…` | maintenance on every Present: 4,911 calls, **4,909 re-hooks** in 100 s (~50 fps), `indexed=0 instanced=0` |
| 5 | `runtime/laptop-port/draw-probe-noappid` | `a9db6330…` | **invalid A/B**: without `steam_appid.txt` the game idles at 1600x900 with 10 log lines and never presents |
| 6 | `runtime/laptop-port/draw-probe-mods` | `a9db6330…` | module inventory of the working configuration (below) |

The build carrying the canary hook (below) is `e14102c1…`; it has not been run on the laptop yet. Every build here is
hash-stable (`test_build_reproducible.py`), so a rebuild reproduces these numbers exactly.

Each run's raw `NIER_SCALE.log` and the launcher's console output are beside this table's directories. Laptop restored
after every run (`laptop_port.py restore`, verified `d3d11.dll` `6ba266d6…`, `ec_hooks.dll` `c0abc71a…`, no project
files).

## What the numbers say

1. **Not an install failure.** Both draw slots are in the table at 1600x900 (`hook_mask=3`), and the device-level
   `CreateInputLayout` hook is still ours in the world (`layout_hook=1`). The device object was never replaced.
2. **Not a different context.** `ctx_installed == armed_context` and `table_installed == armed_table`: the object and
   the table we hook are the ones presenting. `install_attempts=1` — there was never a second device to refuse.
3. **Not a foreign hook.** At the loss, the slot holds exactly the pointer we chained to (`slot12 == orig12`,
   `restored12=1`, `foreign12=0`). Something writes the pristine function back; nobody else's trampoline is there.
4. **It is per-frame, not once.** With maintenance on every Present, 4,909 of 4,911 opportunities found the slots
   restored again (run 4). At ~50 fps that is one restore per frame.
5. **Being in the table at Present is not enough.** In runs 3 and 4 our hooks were definitely installed at each
   Present, and `indexed`/`instanced` still stayed 0. So the restore happens *after* our last re-hook and *before* the
   frame's draws — the game draws on a table that has already been reset.
6. **The process contains two hooking overlays** (run 6, `draw-probe modules:`):

   ```
   d3d11.dll=00007FFF71DB0000        d3d11_dlaa.dll=00007FFF8A380000   dxgi.dll=00007FFFF2A80000
   gameoverlayrenderer64.dll=00007FFF70EC0000   steam_api64.dll=000000003B400000
   nvspcap64.dll=00007FFF3A560000    nvngx_dlss.dll=absent  nvngx_dlssg.dll=absent
   sl.interposer.dll=absent          nvoglv64.dll=absent
   ```

   `gameoverlayrenderer64.dll` (Steam) and `nvspcap64.dll` (NVIDIA App capture) both hook D3D11 in this process. The
   per-frame "write the saved original back" pattern is exactly the anti-pattern this project already lost a day to in
   `test_present_overlay_rehook.py`: an overlay that keeps one global "original" and restores it around its own calls.
   With `--no-ec-hooks` the DLAA hook library is out of the chain, so it is not the suspect here.

## Ruled out

- capture eligibility, readiness guards, scene-target classification (the hooks never run, so they decide nothing);
- multiple devices or a deferred context being hooked instead of the immediate one;
- our own install path (one attempt, one success, same object);
- the missing camp save (run 1's user confirmation stands).

## Next, in this order

1. **Overlay A/B, one variable at a time** (needs someone at the machine, ~2 minutes each):
   - quit the NVIDIA App from the tray, run the probe;
   - re-enable it, disable the Steam overlay for NieR (Steam → NieR → Properties → uncheck "Enable the Steam Overlay"),
     run again.
   If either run reports `hook_mask=3` in the world *and* `indexed>0`, the capture path has a working configuration and
   the fix is to detect and survive that specific overlay rather than to hunt the driver.
2. **Canary** (build `e14102c1…` ready, `draw_probe.h::kCanarySlot` = slot 108 `IAGetPrimitiveTopology`, a pure
   forward, logged as `canary=` from the state found on entry). One run answers the question the re-hook runs could not:
   - `canary=1` in the world → the two draw slots are restored on their own, so a specific component owns them;
   - `canary=0` → a saved snapshot of the whole table is being re-applied.

   The mock gate asserts the canary survives a slot-specific takeover (`steal-rehook` case). Run it exactly like run 4:
   `run <label> --seconds 100 --no-ec-hooks --draw-probe --rehook`.

   The canary slot is hooked **only while the probe is enabled**: the mock reports `ctx_canary_in_proxy`, the gate
   requires `0` when the probe is off and `1` when it is on, and the mutation "remove the probe guard" was run — it
   fails with `ctx_canary_in_proxy=1`, so the check is not decorative. The shipping path must not gain a hooked slot.
3. **If an overlay provably owns the slots:** hook at code level for `DrawIndexed`/`DrawIndexedInstanced` instead of the
   vtable slot, since a vtable restore cannot undo a detour on the function body. That is a bigger change and needs its
   own gate; do not start it on a hunch — run 1 and 2 above first.

## Notes for the next session

- `steam_appid.txt` is **required** for the game to run (run 5). Do not remove it to test overlay behaviour.
- The SSH/stdin launcher path hung twice with zero side effects before identical calls succeeded; a run that reports no
  PID, no log and no launch script is a transport failure, not a compatibility result. Inline `powershell -Command`
  one-liners over SSH gave a wrong answer once (`Test-Path` reported a missing file that was present) — use scp'd
  `.ps1` files for remote state checks.
- Every probe run leaves `NIER_SCALE.log` in the game folder; `restore` removes it. Copy it out before restoring if it
  matters.

## SOLVED — 2026-10-30 19:41, run `runtime/laptop-port/draw-probe-repair2` (build `77a3206f…`, 120 s, camp)

The draw stream is reachable. Repairing the two slots from calls that happen *before* drawing starts — `OMSetRenderTargets`
(slot 33) and `Map` (slot 14), pure forwarding hooks — keeps our hooks in place through the frame instead of only at
Present:

| window | `hook_mask` | `indexed` | `instanced` | `repairs` |
| --- | --- | --- | --- | --- |
| 19:41:55 | 3 | 91 | 0 | 106 |
| 19:42:10 | 3 | 23,173 | 0 | 2,092 |
| 19:43:00 | 3 | 904,464 | 29,916 | 10,512 |
| 19:43:50 | 3 | **4,810,167** | **167,262** | 29,230 |

`sample=1` from 19:42:10 on: the probe's own CPU sample (IA layout, topology, CB0/CB11, viewport) was taken from a draw
with ≥128 indices, i.e. real world geometry, not UI. `hook_mask` is 3 in every window, so the "lost vtable" failure of
runs 1-7 does not occur while the repair points are active; Present-time re-hooking almost never fires (`rehooks` 34).

The watcher in the same run confirms the adversary's signature unchanged: ours → a hook inside
`C:\Windows\system32\d3d11.dll` (`0x…18065a0` / `0x…17d2450`) → the pristine function (`0x…17f62f0` / `0x…17f60c0`),
all within ~1 ms, once per process start. It says nothing about *which* component owns the middle pointer; it does not
need to, because the repair approach does not depend on knowing.

### What this changes

- The blocker for Stage 3 is a hook-lifetime problem, not a capture-eligibility, scene-classification or save-state
  problem. The evidence for that is now direct: millions of indexed draws reaching our hook in a normal camp session.
- The next step is to move the repair points out of the diagnostic and into the shipping capture install, gated so that
  they only ever repair a slot that holds *our* stored original (never a third party's pointer), and only while capture
  is armed.
- `--no-ec-hooks` was set for every run above. Visual behaviour without it (DLAA's `ec_hooks.dll` in the chain) is untested;
  the user's report of buildings flickering/pop-in outside the camp was seen in this configuration and has no measured
  explanation yet. Compare with `ec_hooks` enabled before attributing it to anything.
