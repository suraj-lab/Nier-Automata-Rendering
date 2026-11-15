# Laptop go/no-go measurement — DLSS Ultra Performance, 2026-11-15

User play on `spaghetti` (RTX Spark N1X, driver 32.0.16.2114), normal Steam launch, proxy `9555829d…` (14 Nov build),
`rtx.conf`: DLSS (preset 2) `qualityDLSS = 0` (Ultra Performance), Ray Reconstruction on, `rtx.dlfg.enable = False`,
2880x1800 output, game backbuffer 1600x900. No laptop files changed except the Remix crash marker below.
Log excerpt: `runtime/laptop-play-20261115/play-20261115-excerpt.log` (pid 31020, own lines only, 3,006 lines).

| Setting | Windows | Median fps | p10 | p90 | readback ms/frame |
| --- | ---: | ---: | ---: | ---: | --- |
| DLSS Performance (2026-11-14 play, PLAN baseline) | 75 | 17.0 | 14.1 | 19.8 | median 50.6 |
| **DLSS Ultra Performance (this run)** | 38 | **24.1** | 20.0 | 29.5 | 20–40 |

All windows are the proxy's 60-frame stats lines from first world frame to quit (13:43:22–13:44:55, about 95 s); no
selection. Presented = rendered (no frame generation). Readback = GPU completion wait + transfer (not separable).

## Findings
- Ultra Performance: +42% median over Performance; still GPU-bound (readback dominates frame time).
- Frame generation cannot reach the screen with the copied-output path (`web_remix_present_framegen.md`): needs P2.
  At a 24 fps base, 2x FG would present ~48 fps with ~24 fps responsiveness (estimate, not measured).
- First launch at 13:34 showed the plain game: Remix's "RTX Remix Crash Report" Yes/No box (shown after a crashed
  previous session, `util_sentry.cpp:594-628`, not topmost) blocked `dxvk_CreateD3D9` behind the game window.
  Worked around by renaming `data\rtx-remix\logs\.sentry-native\last_crash` (set-aside copies kept, 1345 and 1350).
- C2 evidence: a normal in-game quit (13:44:56 world gone, process gone by 13:44:59) was again recorded by Remix as a
  crash (`last_crash` 13:44:59). No hang on the laptop; the exit crashes silently, so every launch after a quit prompts.
- Terrain bakes on the laptop still lack mips (C3 not deployed): "suboptimal replacement texture" warnings.
