# A0 live-runtime evidence — 2026-11-14 (desktop, headless RX 6800 XT)

Permission: user granted full access to desktop and laptop in-session. Runs used the fixed guards, a copied
Proton prefix and the headless 6800 XT. No system/Steam setting was changed; the real save was hashed before and
after and never restored.

## Runs

| Label | Command (from `analysis/`) | Result |
| --- | --- | --- |
| `a0-live-identity-1` | `python3 runtime/game-runs/game_run.py a0-live-identity-1 --live --limit 90 --shots 40,60` | `exit=timeout`, `save_ok=true`, `forced_pids=[2777694, 2777743]`, 2 shots |
| `a0-live-identity-2` | `python3 runtime/game-runs/game_run.py a0-live-identity-2 --live --limit 150 --menu-drive "wait:30,press:A:0.3,wait:4,press:A:0.3,wait:20" --shots 70,90` | `exit=timeout`, `save_ok=true`, `forced_pids=[2778568, 2778612]`, 2 shots |

`forced_pids` are the run's own `gamescopereaper`/proton children killed by exact token+prefix ownership after the
deadline — expected for a deadline exit, and not a clean shutdown. `save_ok=true` in both runs, with identical
before/after SHA-256 for `GameData.dat`, `SlotData_0.dat`, `SystemData.dat`, `Graphic.ini` and `steam_autocloud.vdf`.

## Loaded runtime identity (from `NIER_SCALE.log`, pid 364 at 11:35:52)

```
remix: enabled runtime=Z:/mnt/second/SteamLibrary/steamapps/common/PortalRTX/bin/.trex/d3d9.dll scene=...\remix-probe\textured-scene\scene.bin
remix: started 1920x1080 startup=5 surfaces=0 sky_skipped=0 untextured=0 live=1
remix: paused (game backbuffer 1600x900, Remix 1920x1080); game frames shown
remix: world gone (10 game frames without scene draws); showing the game's own frame
```

- The proxy's `remixapi_InitializeLibrary` path succeeds against the real Portal runtime
  (`ca71edf1d7d03d792a3e8d1d6b00c75d122220e4b4f323ef93e6f71bb9392dc1`) and reports `live=1`. That upgrades the
  earlier static-only claim: the interface now initializes in an actual process. It still does not prove every
  used slot agrees with the header; the call sites exercised are Startup/Present/SetConfigVariable plus the live
  handoff path.
- Adapter verified from `host.log` (gamescope `AMD Radeon RX 6800 XT (RADV NAVI21)`) and `remix-dxvk.log`
  (`Device ID: 0x73bf`). The monitor-driving RX 9070 XT was not used.
- Runtime build string: `DXVK_Remix: remix-main+5a7eec84`.

## New blockers this evidence exposes (not previously known)

1. **The resolution/depth patch no longer matches this game build.** `depth patch result: signature-mismatch`,
   `depth patch failed (signature-mismatch): NOT scaling to avoid the black scene`, `setter ... target_scale=0.750`
   never applies. Consequence: the game backbuffer stays 1600x900 while Remix runs 1920x1080, the proxy stays
   `paused` and shows the game's own frames. Both live runs therefore produced **zero scene draws**
   (`world gone`), so they are identity/guard evidence only — not truth captures, not D1 measurements.
2. **Screenshots are 640x350** (`menu: screenshot 0 written 640x350 format=28`). Any image claim from these runs
   inherits that resolution; the plan already forbids treating 640x350 as a performance result.
3. Startup takes longer than the driven window: the world was not reached inside 150 s, so T1/C2 need a longer
   hold plus a driver script that actually leaves the menu, with `remix: live draws=` proof before capture.

## Consequence for the plan order

T1 (truth capture) and D1 (real-resolution measurement) both depend on the resolution patch working, because the
native handoff/`paused` behaviour decides which image is even being observed. The next ready work is therefore the
scale-setter signature repair, gated offline against the installed game binary and the existing proxy pattern
fixtures — not more blind live runs.

Local suite state is unaffected: `runtime/suite-s60-acceptance/full-suite.json` remains 104/104 with
`source_unchanged: true`; today's live runs changed no repository source.
