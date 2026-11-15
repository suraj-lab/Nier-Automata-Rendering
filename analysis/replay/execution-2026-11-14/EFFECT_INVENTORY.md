# Effect inventory — bounded legacy samples, not an effects census

2026-11-14. Existing inventory SHA-256: `b750723ef57564921c9d7af910de35bb50aa74b1a34af74b5bff798acf1980cb`.
Read current captured draw metadata and join shader IDs to the repaired RDEF inventory. Independently checked
state-count sum == recorded-draw count and joined candidate-count sum == shader sampled-draw count for each area.
Raw captures were not modified, repacked or reinterpreted as complete frames.

| Area | Recorded draws | Blend enabled | SRC_ALPHA/INV_SRC_ALPHA ADD | Structured t27/t30 candidates / draws |
| --- | ---: | ---: | ---: | ---: |
| camp | 3382 | 92 | 82 | 3 / 11 |
| desert | 923 | 24 | 23 | 3 / 10 |
| pond | 1176 | 47 | 46 | 3 / 27 |

D3D11 raw enums: SRC_ALPHA=5, INV_SRC_ALPHA=6, ADD=1. These are observed state tuples, not proof of shader output
alpha semantics (straight versus premultiplied), depth occlusion, visual class, or successful Remix rendering.
Blend src=9/dst=1 is not ordinary straight-alpha. Offscreen composites and small draws may be absent entirely.

## Classification / acceptance gaps

| Class | What these samples establish | Still required |
| --- | --- | --- |
| Alpha/additive particles | Three shared structured-t27 shader-bytecode identities occur in all areas; blend tuples below | VS+PS operations/resources, full alpha/ops/masks, sizes/depth, scene dependencies and calibrated crop; no smoke/spark identity assigned |
| Opaque/dithered effects | A non-blended state is not evidence of ordinary geometry | discard/dither/depth analysis and side-effect exclusions |
| Distortion/refraction | Parameter-name candidates include refract/water-fog, not proof of a display-space distortion pass | identify source scene-color/depth, prove sampling of Remix scene, calibrated T1 comparison |
| Bloom/post/offscreen composite | Legacy metadata is insufficient to enumerate or classify these | R2 metadata/small-pass capture and target/resource relationships |
| Combat smoke/sparks/explosions | Missing combat session | US2 combat capture + original/Remix truth; cannot accept from peaceful-area frames |
| Water versus effects | Water-related declarations also occur outside the pond | one-candidate-at-a-time visibility isolation, durable bytecode identity and W3 negative classes |

## Fresh diagnostic repair (E1.1 partial)

The production effect-drop branch hardcoded blend=false, src=dest=0, alpha-test=false, target-format=0 in its tally,
even though the draw's raw blend and view-format fields were already read. It now passes those observed fields.
The branch still drops those effects by default, releases the same resources and returns at the same point.
No effect geometry, composites, intensity or artistic default changed.

`checks/test_effect_tally.py` compiles real structured t27 and t30 SM5 shaders in the Wine mock, alongside ordinary
geometry (an all-effects fixture leaves no scene for the worker's reporting loop). Positive cases pin observed
straight-alpha 5>6 and additive 2>2 plus DXGI_FORMAT_R8G8B8A8_UNORM=28; an ordinary-geometry negative twin must not
be classified as an effect. Frozen gate was red with actual rows `blend=off:0>0 rt=0`; green after the targeted fix;
restoring the old hardcoded arguments is mutation-red; restored green afterwards.

**Historical gap at the tally-only checkpoint (superseded locally by the census below):** alpha blend factors/ops, write masks, full depth state, topology, target dimensions and bound
VS/PS resources still need bounded records. `ShaderTally` aggregates by shader and retains only last observed state;
it cannot represent all state combinations. The existing small-note path is before the 128-index rejection but
only records shader/indices/instances and only when the scene target is known. Neither is a complete effect census.
No layered-composite spike or pixel/material acceptance is claimed.

## Shader identity caveat

SHA-256 pins the bytecode inspected now. Legacy shader files live in shared sibling `shaders/`, keyed originally by
pointer; they are not independently proven frame-local payloads. R2 must eliminate pointer-reuse ambiguity. The
resource declaration match is a candidate family only, never a durable semantic material label.

### camp

Capture `/mnt/second/SteamLibrary/steamapps/common/NieRAutomata/NIER_CAPTURE/frame_30632051`. Effect-family declaration candidates (not visual classification):


| PS SHA-256 | Recorded draws |
| --- | ---: |

| `dcb71c89b488590ebc2f68174f384c1bd598aac6b3a6946c59e20cf4425295f8` | 5 |

| `79107fca15205799926a9d52e968d6681756680c87efefa8f9a2fad99b8c3f05` | 4 |

| `ae8d9d86683179c01b573c39ff4cd625dadea645ed56607bad9d211208273bae` | 2 |


Actual sampled candidate state tuples `(blend,src,dst,op,depthwrite)`:


- `(1, 5, 6, 1, 0)`: 11 draws

### desert

Capture `/home/suraj/Projects/Nier-Automata-Rendering/analysis/runtime/laptop-play-20261114/frame_67279062`. Effect-family declaration candidates (not visual classification):


| PS SHA-256 | Recorded draws |
| --- | ---: |

| `dcb71c89b488590ebc2f68174f384c1bd598aac6b3a6946c59e20cf4425295f8` | 4 |

| `79107fca15205799926a9d52e968d6681756680c87efefa8f9a2fad99b8c3f05` | 4 |

| `ae8d9d86683179c01b573c39ff4cd625dadea645ed56607bad9d211208273bae` | 2 |


Actual sampled candidate state tuples `(blend,src,dst,op,depthwrite)`:


- `(1, 5, 6, 1, 0)`: 10 draws

### pond

Capture `/home/suraj/Projects/Nier-Automata-Rendering/analysis/runtime/laptop-play-20261114/frame_67078468`. Effect-family declaration candidates (not visual classification):


| PS SHA-256 | Recorded draws |
| --- | ---: |

| `dcb71c89b488590ebc2f68174f384c1bd598aac6b3a6946c59e20cf4425295f8` | 18 |

| `ae8d9d86683179c01b573c39ff4cd625dadea645ed56607bad9d211208273bae` | 5 |

| `79107fca15205799926a9d52e968d6681756680c87efefa8f9a2fad99b8c3f05` | 4 |


Actual sampled candidate state tuples `(blend,src,dst,op,depthwrite)`:


- `(1, 5, 6, 1, 0)`: 27 draws

## Bounded diagnostic census — local acceptance after s73

Implemented `NIER_REMIX_LIVE_EFFECT_CENSUS=1`, default OFF. `effect_census.h` emits version1 JSON records only for
known structured-t27/t30 effect-family PS draws, before the small-index cutoff, without capturing/submitting
geometry. Descriptors: raw blend/alpha factors+ops/write mask, RT0 view format/mip-sized 2D extent/samples,
depth enable/write mask/function, topology, draw count, verified PS-bytecode FNV identity, bound VS/PS SRV view
metadata. Structured buffers retain actual stride and view FirstElement/NumElements. Other view types are identified
or explicitly unsupported. No staging, Map or buffer-data dump is performed by this diagnostic.

At most64 metadata records/gameframe and256/session (including pending queue); an explicit one-time limit notice
states that additional records were omitted. The worker drains independently of world-scene availability, including
an all-small-effects fixture. COM getter references are released before potentially allocating string formatting.
Allocation errors are caught at the diagnostic callsite and cannot change geometry eligibility; report is limited.
This is sampled evidence, not a full effect census. RT0-only/2D view sizing and pointer-cache/legacy payload gaps
remain documented; no layered composite or artistic/material/default change has been accepted.

Frozen gate `checks/test_effect_census.py`: original SHA940bfd062255a87c1fef01b3d0e58eb887c1e1730348acc38792600af6e68d51
was correctly red for absent census, but its target-size oracle was wrong (expected backbuffer1920x1080 instead of
actual mock scene resource960x540, verified at mock source descriptor). Original preserved as
`effect-census-gate-original.py`; corrected gate adds both half-size and native-size targets, all-small/no-world
scene and overflow disclosure; current SHA `b39917ef2d7bbc4923226d5a2f4a6d8dc6e09045fa908c437fc45ee1fa1a65b4`.
All seven cases green. SIX mutation-red results in `runtime/effect-census-mutations.json`: default-on; omitted small
draws; wrong SRV view first; removed per-frame cap; removed session cap(5056 records); wrong bytecode identity.
Every mutation restored. `runtime/suite-s73-acceptance/full-suite.json`: **114/114, source_unchanged=true,249.2s**.
Identity receipt `runtime/suite-s73-acceptance/integration-sha256.json`.

Delegation532100f5 (local-worker role, explicitly openai-codex/gpt-6-luna) ran the red gate but completed NO
implementation; no worker result accepted. Lead implemented/integrated after recording that outcome. Independent
Luna reviewer1b3c1691: OK with notes, no blockers; reviewer did not rerun tests, lead owns acceptance. Shared-ledger
sync pending; no outside-repository ledger/config writes.

**E1 still open:** no fresh game census, real overhead, complete class census, combat evidence, safe layered-composite
prototype, pixel/visual/depth/HDR acceptance or user pick. These records are diagnostic controls, not effect recovery.

## E1.2 replay census rows — camp / desert / pond (2026-11-14, offline)

`run_replay.py e1-census-<area> <capture> --mode fake --isolated-prefix --frames 120 --frame-ms 16
--env REPLAY_EXIT=clean --env NIER_REMIX_LIVE_EFFECT_CENSUS=1` (Wine + fake runtime; proxy as built at T1 v2).
All three exit 0. Per replayed frame the census saw 11 / 10 / 27 effect-family draws (below the 64/frame cap, so each
frame is complete; the 256/session cap only truncated later repeats of the same frame). Counts equal the legacy
sampled draws above. Summary: `runtime/e1-replay-census-summary.json`.

| Area | PS code (FNV) | Draws/frame | Blend (color; alpha) | RT0 | Depth | Topology | Structured SRVs |
| --- | --- | ---: | --- | --- | --- | --- | --- |
| camp | 483f6bd1… / 3fefc02f… / c2eeb2d4… | 5 / 4 / 2 | SRC_ALPHA>INV_SRC_ALPHA ADD; same | RGBA8 2580x1080 1x | test LESS_EQUAL, no write | tri list | t20 (stride 48), t22 (stride 80) |
| desert | same three | 4 / 4 / 2 | same | RGBA8 2880x1800 1x | same | tri list | same |
| pond | same three | 18 / 5 / 4 | same | RGBA8 2880x1800 1x | same | tri list | same |

Reading: in these peaceful frames there is exactly ONE state class — straight-alpha "over" blending, depth-tested
against the scene without depth write, full scene-size target, not reduced resolution, no additive, no MSAA. The
structured buffers actually bound are t20/t22 (the earlier "t27/t30" label is the declaration family; slots differ).
Limits: replay RT format/size are the replayer's scene target, not proof of the live game's target (live tap target
is R11G11B10); no visual class (smoke vs dust vs foliage card) assigned; combat classes (additive sparks,
explosions, distortion) still need US2. Offscreen/bloom passes outside this PS family remain uncounted (R2).

## E1 live census — `e1-census-camp-live` (desktop, user-approved, DLL 74ded3a6…)

Same camp recipe at 3440x1440 with `NIER_REMIX_LIVE_EFFECT_CENSUS=1`. RX 6800 XT; save_ok=true; exit timeout with
exact-token forced cleanup (not a clean quit). The proxy log is the game folder's NIER_SCALE.log (written by the
game process, not by the tooling); this run's lines were copied read-only to
`runtime/game-runs/e1-census-camp-live/NIER_SCALE.run-excerpt.log`. 256 records over 18 frames from world entry
(session cap reached, disclosed); max 16/frame. Classes: `runtime/game-runs/e1-census-camp-live/effect-census-classes.json`.

What the real game does (differs from the replay!):
- Every censused effect is a **4-index triangle strip** (particle quad), drawn into an **R11G11B10_FLOAT 3440x1440**
  target - the same format and size as the native-HUD target.
- Blends: straight-alpha colour SRC_ALPHA>INV_SRC_ALPHA with alpha ONE>INV_SRC_ALPHA (most shaders); **additive**
  SRC_ALPHA>ONE (PS e523a07c…, the largest single class); one shader writes RGB only (mask 7); one variant has depth
  disabled with write mask set. Most: depth test LESS_EQUAL, no depth write.
- PS SRVs include t8 R11G11B10 (scene colour?), t10 RGBA16F, t13 R32_FLOAT (depth copy - soft particles?), cubes,
  and structured t20-t30. Semantics unverified.

Open question decided by the next diagnostic: is that R11G11B10 effect target the HUD/tap target itself (effects
after tone mapping => composite in display space is exact) or a pre-tone-map scene buffer? Census v1 records now
carry `rt_resource` and `hud_target_resource` (pointer identity, session-local). Gate
`checks/test_effect_census_target.py` 347c0615… red "rt_resource missing", green after; mutations red
(`runtime/e1-census-target-mutations.json`); suite s81 125/125. Candidate DLL 20dff32b… (not installed).

### Live census run 2 — `e1-census-camp-live-2` (DLL 20dff32b…, user-approved; rollback backups/live-scene-20261114T223227454191Z)
save_ok=true; timeout + exact-token cleanup. 256 records 22:33:00.4-00.7 (world entry); first native-HUD handoff only
at 22:33:55, so every record has `hud_target_resource=0x0`: **inconclusive** (census cap spent before handoff).
New fact: effect RT0 rotates among 3 distinct R11G11B10 resources (104/100/52 records) - a ring of targets.
Fix v2: the handoff path logs each newly seen HUD target pointer (`remix: native HUD target 0x… change n`, <=8/session),
so the effect-RT pointers can be compared across time. Gate v2 `test_effect_census_target.py` daa4089a… (v1 archived
`effect-census-target-gate-v1.py`): v1 code red "HUD target pointer not logged", v2 green; the 8-line bound is not
exercised by the mock (constant target). Suite s82 125/125. Candidate DLL 1a890139… (not installed). Pointer identity
across 55 s is evidence only if the resource is not reallocated; a match is suggestive, a non-match among a stable
ring is strong.

### Live census run 3 — `e1-census-camp-live-3` (DLL 1a890139…, user-approved; rollback backups/live-scene-20261114T233315422339Z)
save_ok=true; timeout + exact-token cleanup. Logged HUD target `0x5b67fc20` (one change). Effect RT0 pointers:
`0x5b67e1e0` 104, `0x5b67de20` 100, **`0x5b67fc20` 52 = the HUD target**. Per frame (e.g. 1762-1764) the order is
~11-12 draws into one of two alternating scene targets (e1e0/de20 swap every frame), then 4 draws into the HUD target.
Classes per target: `runtime/game-runs/e1-census-camp-live-3/effect-rt-classes.json`.

| Target | Role (inferred) | Effect classes |
| --- | --- | --- |
| e1e0 / de20 (alternate frames) | pre-tone-map scene colour ping-pong | straight-alpha 3fefc02f, 589e85d4, 30784504, caf5f428 (RGB-only), **additive e523a07c**; depth test, no write |
| fc20 (HUD/tap target) | display-encoded final image (T1: values <=0.992, matches original final) | 3fefc02f only, 4 draws/frame, **depth disabled**, straight alpha |

Consequences for E1.3 (design input, not accepted behaviour):
1. Most effects, including the additive class, are drawn BEFORE tone mapping. Compositing them over the Remix image
   needs a tone-map approximation (plan step 5: not exact; must be labelled with residuals) or Remix-side rendering.
2. A small class (4 quads/frame, same PS as the main straight-alpha family) is drawn into the display-space HUD target
   before the HUD sprites and is erased by today's handoff. For this class an exact fix exists in principle: hand off
   before these draws instead of at the first sprite. Visual identity of these quads is unknown (needs a crop).
Limits: pointer identity over ~50 s (stable ring observed, not proven non-reallocated); one camp session; combat absent.
