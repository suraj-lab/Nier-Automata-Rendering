# E1.3a handoff at display-space effects — local acceptance, 2026-11-14

Offline only. Default unchanged. NOT live-validated; no visual/artistic acceptance; does not recover pre-tone-map effects.

Motivation (EFFECT_INVENTORY.md, live census run 3): per frame ~12 effect draws go into a pre-tone-map ping-pong
pair, then 4 quads (PS 3fefc02f, straight alpha, depth off) into the display-encoded HUD target before the sprites.
Today's handoff at the first sprite erases those 4. `NIER_REMIX_LIVE_HANDOFF_AT_EFFECT=1` hands off at the first
t27/t30 effect draw whose RT0 IS the HUD target identified by an earlier sprite handoff (pointer identity), so the
game's own draw then blends over the Remix image: exact for this class (same target, same colour space, T1).

- Frozen gate `checks/test_handoff_at_effect.py` c47203f3… (probe moved to 1800,720 before freezing: the first
  oracle point sat under the menu panel). Red "effect not blended over Remix: (199,40,120)", green (227,84,60) vs
  expected (228,84,60); default keeps today's erase; scene-target effects unaffected.
- Reviewer `323e75d5` (anthropic/claude-haiku-5-5): BLOCK P0 - same-format/size scene ping-pong targets would take the
  handoff. Lead had found the same risk: hidden gate `test_handoff_at_effect_hidden.py` 7cf84459… (+mock
  `MOCK_EFFECT_INTO_SCENE_HDR`) red "corner is not the Remix image (25,38,51)" on the unfixed code; fix = effect
  trigger only into the sprite-identified HUD target (fail-safe: can miss, cannot misfire); green. P2 noted: census
  pointer reused as control state; Resource vs Texture2D pointer equality is an assumption supported by run 3.
- Mutations red: `runtime/e1-handoff-at-effect-mutations.json` (never triggers, default on, no identity check).
- Suite s83 127/127. Candidate DLL 174af993… (not installed). remix_live.cpp 4d705b37….
Next: one live run with the switch on + truth tap to see what the 4 quads are and confirm no scene corruption.

## Live run `e1-handoff-at-effect-1` (user-approved; DLL 174af993…, rollback backups/live-scene-20261115T000013768208Z)
Camp recipe, `NIER_REMIX_LIVE_HANDOFF_AT_EFFECT=1` + truth tap. save_ok=true; timeout + exact-token cleanup.
HUD target logged once (0x5b66b730); ordinary sprite handoff happened; **the at-effect trigger never fired** (no
"handoff at effect" line). No visible regression: shots 0-2 vs `t1-tap-camp-2` (switch off) MAD 2.1/8.4/4.3 levels
(session/time variation, same order as T1 cross-session), 4 candidate pairs + 8 rejections as before.
Unresolved cause; hypotheses: (a) the HUD sprites draw BEFORE those 4 quads, so the quads already survive today's
handoff and the switch is unnecessary; (b) a mismatch the census did not reveal. Distinguishing needs a draw-order
diagnostic (effect into HUD target after/before the sprite handoff in the same frame) and another live run.
E1.3a therefore has NO live benefit shown; keep default off; do not claim restored effects.
