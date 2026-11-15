# T1.1 pre-overwrite tap + T1.2 R11G11B10 decode — local acceptance, 2026-11-14

Offline only (software Wine/llvmpipe, fake Remix, private owned prefixes). No game run, deploy, GPU render, remote or
Toolkit action. NOT calibrated truth: T1.3 (real final-screenshot validation, live-run permission) still required.

## T1.1 opt-in tap (`NIER_REMIX_LIVE_TRUTH_PAIR_DIR`, default off)
- Frozen gate `checks/test_truth_pair_tap.py` SHA cf5434be…570e0. Red: "opt-in tap missing" (an initial oracle
  matched any 'truth-pair' substring in the log path; narrowed to the `remix: truth-pair` log prefix before freezing).
- Worker: Luna `a0540801` wrote the tap, then hit the Codex usage limit before reporting; lead reran the gate (green).
- Lead review defect: game camera/frame were taken from the Remix frame's INPUT, so a moving game camera still
  "matched". Hidden gate `test_truth_pair_tap_hidden.py` SHA ae8a366a… (+`MOCK_CAMERA_DRIFT` in the mock) red for that
  reason; lead fix: `camera_capture::current()` = camera decoded for the game frame being drawn (sequence predicted
  as published+1, only while permitted), `game_frame_id` = `live_capture::frame_number` at tap time.
- Reviewer `721187d6` (anthropic/claude-haiku-5-5): OK with notes; fixed BGRA/RGBA encoding label, ArraySize/MipLevels
  ==1 required for the tap only (handoff guard unchanged), `current()` checks `permitted`.
- Mutations red (`runtime/t1-tap-mutations.json`): tap after overwrite, unbounded attempts (v2; v1 was a compile
  error, recorded as invalid), camera always matched; pre-fix code is the hidden-gate mutation.
## T1.2 decoder (`replay/raw_image.py` decode_raw; `run_replay.raw_to_png` refuses HDR)
- Frozen gate `checks/test_raw_hdr_decode.py` SHA 730732b3…; red "decoder absent"; worker Luna `1739f836`.
- Mutations red (`runtime/t1-hdr-mutations.json`): exponent bias, blue mantissa width, HDR clamp.
## Integration
remix_live.cpp a98f1046…, camera_capture.h 86c4d3f4…, raw_image.py a46411a5…. Suites s76 and s77 (after review
fixes) 122/122. Candidate DLL not rebuilt into the game folder.
