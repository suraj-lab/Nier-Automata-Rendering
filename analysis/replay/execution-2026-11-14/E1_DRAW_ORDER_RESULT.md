# E1 draw-order check — 2026-11-14/15 (user asked: "check the draw order")

## Diagnostic (offline, gated)
Census records gain `after_hud_handoff` (native handoff already composed in this frame). `NIER_REMIX_LIVE_EFFECT_CENSUS=handoff`
defers sampling until the HUD target is known and (v2) records only effects drawn into that target.
Gate `checks/test_effect_census_order.py` (+mock `MOCK_EFFECT_AFTER_SPRITE`): v1 711380de… red "reported after the
handoff" (field absent), green; live run 2 showed v1's flaw (64 scene-target effects/frame filled the per-frame cap
before any late HUD-target quad), v2 9fd60435… (v1 archived `effect-census-order-gate-v1.py`) red on v1 code
"recorded non-HUD-target effects", green. Mutations red: `runtime/e1-census-order-mutations.json`.

## Live runs (desktop RX 6800 XT, camp recipe, save_ok=true every run, timeouts with exact-token cleanup)
| Run | DLL | Result |
| --- | --- | --- |
| e1-draw-order-1 | 8e000a0e… | launch failure after 2.3 s (Proton "Primary child shut down", NieR never started, proxy not loaded); transient, retried once |
| e1-draw-order-2 | 8e000a0e… | 256 records, all scene targets, 64/frame cap hit: inconclusive -> gate v2 |
| e1-draw-order-3 | a6ed67c9… | **0 effect draws into the HUD target** in ~100 s after the handoff began (target 0x783e1240) |
Process slip disclosed: run 3 was launched before noticing suite s85 was 127/128 (test_live_visibility flaked under load;
passed alone; s86 128/128 on the same source). Rollback folders under `backups/live-scene-20261115T*`.

## Conclusion
Census run 3's 4 HUD-target quads/frame (PS 3fefc02f, depth off) were sampled at 23:33:48, during the phase where the
proxy reports "world gone ... showing the game's own frame" (handoff not active until 23:34:43) - consistent with a
loading/transition overlay, not gameplay effects. In steady camp gameplay no effect draws target the HUD image, so
today's handoff erases no display-space effects there; all observed gameplay effects are pre-tone-map (scene ping-pong).
**E1.3a `NIER_REMIX_LIVE_HANDOFF_AT_EFFECT` rejected and removed** (no target class; code + both gates archived in
`rejected-e1-handoff-at-effect/` with SHA256.json). Census diagnostics (rt/HUD-target identity, order, deferred mode)
kept. Suite s88 126/126 after removal (s87 one load flake in test_live_normal_map, exit -9; passed alone).
Candidate DLL 82cb26c7… not installed; the game folder still has a6ed67c9… (includes the now-removed switch, default off).
Limits: one camp session; combat/other areas may draw display-space effects (US2).
Next for E1: pre-tone-map effects need a composite with a tone-map approximation (labelled residuals) or Remix-side
rendering; that requires the game's tone-map inputs (exposure) - not yet identified.
