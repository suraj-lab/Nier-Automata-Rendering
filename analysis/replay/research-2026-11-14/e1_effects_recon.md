# E1 recon: effects of every kind are missing in Remix (2026-11-14)

Read-only recon for `analysis/PLAN_2026-11-14.md` item E1. Nothing was built, run or installed. Sources: the proxy
(`analysis/checks/`), the plan history, two frame captures, the laptop play log
(`analysis/runtime/laptop-play-20261114/NIER_SCALE.log`), and the partial Remix source drop
(`analysis/runtime/remix-source/0ba9973f.../`).

**Headline: the plan's E1 section is right that our proxy drops the effects, but wrong about two mechanisms and it
underestimates one.** Corrected facts, each with its evidence below:

| # | Fact | Evidence |
|---|---|---|
| 1 | t27/t30 are **structured buffers** (per-effect parameters), not scene colour/depth copies. The scene depth an effect samples is **t13 `g_ZTexture`**; there is no "scene colour copy" slot in the effect family. | `MATERIAL_INPUTS_SLOTS.md:59-60`, `MATERIAL_INPUTS_SLOTS.md:47`, RDEF of the shipped effect shaders (below) |
| 2 | Effect draws are **not** sent to a reduced-size particle buffer in the data we have: every one of them is drawn into the **scene target at scene size**. The class that is dropped before that by the scene-target filter is a different, unmeasured one. | tables in (d) |
| 3 | The overwhelming majority of "effect" draws are **under 128 indices** and are therefore dropped by the size rule *before* the effect rule — and they are invisible to every F9 capture too (the capture has the same 128 floor). | `live_capture.h:1561`, `draw_capture.h:255,266`, `PLAN_2026-11-13.md:168` |
| 4 | The HUD is currently composited by the **native handoff**, not by `hud_replay::draw`: the Remix image is drawn as a full-screen quad into the game's R11G11B10 final target immediately before the game's own HUD sprite shader runs. `ui_pass` is false at native scale, so the sprite-replay path never fires on the laptop. | `remix_live.cpp:1262-1345`, `live_capture.h:1559-1560`, `hud=0` in all 76 stats lines of `NIER_SCALE.log` |
| 5 | The shader table cannot answer "what blend state does an effect shader use": the effect-drop path hard-codes `blended=false`, `target_format=0`. | `live_capture.h:1721` |

---

## (a) Every filter that decides whether a draw reaches Remix

Order is the execution order inside `live_capture::observe` (`live_capture.h:1475`), one draw at a time.

| # | Filter | Where | Condition | Reason bucket |
|---|---|---|---|---|
| 1 | teardown/suspend/frame closed | `live_capture.h:1481-1483` | `!permitted \|\| suspended \|\| !frame_open` | none (invisible) |
| 2 | wrong context | `live_capture.h:1484` | `active_context != context` | none |
| 3 | zero instances | `live_capture.h:1485` | `!instance_count` | none |
| 4 | blend/HUD state read | `live_capture.h:1515-1550` | records `early_target`, `blended`, `blend_on`, `blend_src/dest`, `target_format`, `depth_write` | — |
| 5 | `ui_pass` (HUD) | `live_capture.h:1559-1560` | `hud_enabled && scene_target_enabled && scene_width && final_width && blended && early_target == final_size && {scene_w,scene_h} != final_size`, where `blended` = `!AlphaToCoverage && BlendEnable && BlendOp==ADD && Src==SRC_ALPHA && Dest==INV_SRC_ALPHA` (`:1537`) | `Ui`, captured not dropped (`:2119-2196`) |
| 6 | **size rule** | `live_capture.h:1561-1568` | `!ui_pass && index_count < min_index_count` (default **128**, `:1160`, `NIER_REMIX_LIVE_MIN_INDICES` at `remix_live.cpp:260-261`) | `Small` (+ `note_small` line) |
| 7 | topology rule | `live_capture.h:1571-1575` | `topology != TRIANGLELIST` (strips/lines/points dropped) | `Topology` |
| 8 | layout rule | `live_capture.h:1591-1596` | no IB, no VB, hole in slots, layout unknown, IB format not R16/R32_UINT | `Layout` |
| 9 | waiting for the first scene target | `live_capture.h:1662-1666` | `scene_target_enabled && !scene_width && wait_for_target && !ui_pass` | `Pass` |
| 10 | **scene-target filter** | `live_capture.h:1667-1672` | `scene_target_enabled && scene_width && target != {scene_w,scene_h} && !ui_pass` | `Pass` (`skipped_pass`) |
| 11 | **depth pre-pass rule** | `live_capture.h:1679-1691` | `!ui_pass` and no TEXCOORD/NORMAL/TANGENT/COLOR element | `Prepass` |
| 12 | diagnostic shader drop | `live_capture.h:1697-1701` | `NIER_REMIX_LIVE_SKIP_CODE` matches bytecode FNV (`remix_live.cpp:582`) | `Effect` |
| 13 | **overlay rule** (L7) | `live_capture.h:1702-1711` | `NIER_REMIX_LIVE_SKIP_OVERLAYS=1` and `overlay_rule::is_overlay(...)` | `Effect` (`overlays_skipped`) |
| 14 | **depth-only shader rule** | `live_capture.h:1712-1718` | `pixel.depth_only && skip_depth_ps` (on by default since 2026-11-13, `:553-557`) | `Prepass` (`depth_ps_skipped`) |
| 15 | **effect rule** | `live_capture.h:1719-1725` | `pixel.effect && !keep_effects` | `Effect` |
| 16 | draw budget | `live_capture.h:1739` | `items.size() >= max_draws` (4096, `:1158`) | `Limit` |
| 17 | bones / constants missing | `live_capture.h:1750-1751` | no CB11, or skinned with no 256/48-byte palette | `Bones` / `Constants` |
| 18 | build/read budgets, decode faults, sky switch | `live_capture.h:2201-2502` | per-frame budgets, `live_decode` failures, `NIER_REMIX_LIVE_NO_SKY` (`:251`, `:2463`) | `DeferredBudget`, `DecodeFailed`, `Sky`, … |

The two classifiers behind 13–15:

- `declares_effect_buffers` (`live_capture.h:1414-1424`) scans the **disassembly text** for `dcl_resource_structured … t27,` or `… t30,`. It is a *shader-family* test, cached per `ID3D11PixelShader*` (`:1452`). It says nothing about render targets, scene colour, or blending.
- `depth_only::writes_depth_only` (`depth_only.h:67`) is a taint analysis over the asm: writes only zw-derived values, samples nothing.
- `overlay_rule::is_overlay` (`overlay_rule.h:10-16`): additive (`dest == ONE`), multiplicative (`DEST_COLOR×ZERO` or `ZERO×SRC_COLOR`), or alpha-blend with `!depth_write && !has_material_roles`.

Switches that touch the effect path, all read once at load:

| switch | default | effect on effects | where |
|---|---|---|---|
| `NIER_REMIX_LIVE_EFFECTS=1` | off | keeps t27/t30 draws as scene geometry (the 2026-11-01 diagnostic) | `remix_live.cpp:259`, `live_capture.h:592` |
| `NIER_REMIX_LIVE_MIN_INDICES` | 128 | **the only way** today to let the sub-128 effect/post passes past filter 6 | `remix_live.cpp:260` |
| `NIER_REMIX_LIVE_SKIP_OVERLAYS` | off | drops unlit alpha sheets that also declare t27 | `live_capture.h:574-577` |
| `NIER_REMIX_LIVE_SKIP_DEPTH_PS` | **on** | drops depth-only shaders, including effect-family depth passes | `live_capture.h:553-557` |
| `NIER_REMIX_LIVE_NO_HUD` | off (HUD on) | `ui_pass` and both composite paths | `live_capture.h:250`, `remix_live.cpp:245` |
| `NIER_REMIX_LIVE_NO_SKY`, `…_WAIT_FOR_TARGET`, `…_SKIP_CODE` | on / on / off | indirect (pass accounting, diagnostics) | `:251`, `:562-565`, `:579-583` |

What the game's effect shaders actually declare (RDEF of the 3 effect shaders used in both captures — measured, not
inferred):

```
t0  g_ColorTexture            (tex)      the particle's own colour/alpha texture
t1  EffectParameterIndex      (cbuf)     per-draw effect parameters
t7  ExposureBuffer            (cbuf)
t8  g_VleTexture              (tex) + LightFogParamBuffer (cbuf)   -- only the "fog/VLE" variant
t12 HPixel_Buffer (cbuf) / g_FogLUT (tex)
t13 CamParam_HPixel_Buffer (cbuf) / g_ZTexture (tex)   <-- the scene depth, for soft particles
t19 g_BeforeFogLUT            (tex)
t27 g_EffectPixelCommonBuffers (structured)
```
(`ps_550345096712`, `ps_1844074720` are the fog variant; `ps_550288868808`/`ps_1753805072` and
`ps_550288864328`/`ps_1754005152` are the plain variants. Slot names cross-check with `MATERIAL_INPUTS_SLOTS.md:47,59-60`.)
`g_EffectPixelProjectionBuffers` (t28) exists on 27 shaders (`MATERIAL_INPUTS_SLOTS.md:65`) — the projected/decal
variant, not present in these two frames.

---

## (b) How the HUD replay works, and what it would take to replay effects the same way

### b1. Two composite paths exist, and the one that fires in the game is not the one the plan describes

**Path 1 — `hud_replay::draw` (captured sprites → backbuffer).** Fires only when `ui_pass` was true (filter 5).
- Capture (`live_capture.h:2119-2196`): decode IB+VB with `live_decode`, keep position+texcoord only, keep CB11 as a 3×4 `world` matrix, `PSGetShaderResources(0,1,&ui_srv)` (the sprite's own SRV, kept referenced), push into `UiSnapshot` (`live_capture.h:524-528`), published at `end_frame` by `publish_ui()` (`:532-538`, called `:1245`).
- Replay (`hud_replay.h:210-274`): in the present hook, after `UpdateSubresource(buffer, …, shown.pixels)` (`remix_live.cpp:1454`) the snapshot is drawn with **our own** VS/PS (`hud_replay.h:46-57`), a 4×4 CB from `world` (`:257-265`), `t0` = the game's SRV, our own sampler/raster/blend (`:78-99`), **no depth-stencil view** (`:236` `OMSetRenderTargets(1,&view,nullptr)`), `RSSetViewports` to the whole target (`:234`).
- State saved/restored: `SavedState` (`hud_replay.h:131-207`) covers input layout, 1 VB + IB, VS, PS, VS cb 0, **PS SRV slot 0 only**, **PS sampler slot 0 only**, blend+factor+mask, raster, all RTVs + DSV, GS/HS/DS, topology, viewport. Not covered: VS CBs 1-13, **every PS CB**, SRVs/samplers above slot 0, UAVs, CS, SO targets, scissor rects, blend per-RT 1-7, primitive restart.
- Gates: `test_live_hud_capture.py` (capture counts `hud=`), `test_hud_replay_linkage.py` (VS/PS register linkage — DXVK links by register, `hud_replay.h:55-57`), `test_hud_shader.py`, `test_native_hud.py` (the handoff below, with the captured shipped HUD PS `runtime/hud-evidence/ps_1888250464.dxbc`).

**Path 2 — the native handoff (what the laptop and the desktop actually use).** `remix_live.cpp:1262-1345`, called from
`before_draw` on every indexed draw: when the bound pixel shader is the shipped HUD sprite (`hud_shader::is_sprite`,
DXBC checksum `0xA1B772527CEA5742`, `hud_shader.h:8-15`; `index_count <= 256`), the bound RTV is
`R11G11B10_FLOAT` at the shown size (**and there is no depth view**, `:1284`), the worker's newest Remix frame is uploaded
once into a private `R8G8B8A8_UNORM` texture (`:1310-1326`) and drawn as a full-screen quad into the game's final target
(`:1327-1335`) — then the game's own HUD sprite draws on top of it. Logged once: `remix: native HUD handoff 2880x1800
before game sprites target=2880x1800` (`NIER_SCALE.log:155`; same line at 3440x1440 in
`runtime/game-runs/s2-soak/host.log`).

Why Path 1 never fires in the play logs: `ui_pass` needs `{scene_w,scene_h} != final_size` (`live_capture.h:1559-1560`),
and the laptop plays at **native**: every one of the 76 stats lines in `NIER_SCALE.log` says `scene=2880x1800` with
`hud=0`. The shortcut is documented at `live_capture.h:1556-1558` ("at native scale a blended HUD element of >=
min_index_count indices is submitted as world geometry; telling the swapchain buffer from the scene target by resource
would fix it").

**Consequence for E1:** the model to copy is Path 2, not Path 1 — there is already a place in the frame where "our image"
is inside the game's own final target and the game keeps drawing on top.

### b2. What an effect replay needs, and what is already true

| requirement | HUD sprite replay (today) | effect draws | evidence |
|---|---|---|---|
| where in the frame | after the game's whole frame, in Present | must be **before** the HUD sprites, i.e. at the handoff quad | effect draws are 3368-3380 of 3381 in `frame_30632051`; the final-size draw is 3381 |
| shader | our own trivial PS | **the game's own VS and PS**, or the game must draw them itself | effect PS reads t1/t7/t8/t12/t13/t19/t27; a `tex.Sample` cannot reproduce it |
| vertex semantics | position+uv only | POSITION, TEXCOORD, BLENDINDICES, BLENDWEIGHT, COLOR (+instancing) | `frame_67279062/draw_0917/capture.json` layout |
| constant buffers | CB11 only | VS cbs 0-6,8-13 and PS cbs 1,7,8,12,13 as declared | same capture, `vs_cbs`/`ps_cbs` |
| textures | 1 SRV (slot 0) | t0, t8, t12, t19 (+ t13 depth, t14 dither) | RDEF above |
| blend | our SRC_ALPHA/INV_SRC_ALPHA | the game's exact state: `5>6`, op ADD, depth on, `depth_write=0`, `depth_func=LESS_EQUAL`, `cull=NONE`, dsv `D24_UNORM_S8` | tables in (d) |
| depth test | none | needs the game's scene depth, **same size as the composite target** | see below |
| geometry freshness | decoded per frame (sprites change) | same problem: dynamic VB/IB rewritten every frame | `live_capture.h:2117-2119` comment |
| vertex shader expansion | n/a (our VS) | unknown whether the VS expands billboards from points; if it does, decoding vertices cannot reproduce it | UNVERIFIED (needs the VS asm) |

**Is the game's depth-stencil still alive and same-sized at composite time?** Partly answered by the data:
- The depth buffer the effect draws test against is `dsv_format=45` (`D24_UNORM_S8_UINT`) at **scene size**
  (2880x1800 laptop / 2580x1080 desktop), and it exists as a resource for the whole frame. At the handoff the frame is
  still being drawn (that is the whole point of Path 2), so frame N's depth is still there. Holding a `ID3D11DepthStencilView*`
  reference from the last effect draw is the same technique `ui_srvs` already uses.
- Same size only at native scale: on the desktop the scene is 2580x1080 and the final target 3440x1440
  (`frame_30632051` viewport census). A DSV of 2580x1080 clips the raster to that rectangle, so a depth-tested composite
  onto a 3440x1440 target would put the effects in the top-left 75 %. Not usable without an explicit rescale.
- The game's **depth SRV** (`t13 g_ZTexture`) is bound at the effect draw but *is not visible in the capture*: the
  capture drops any SRV whose texture is `BIND_RENDER_TARGET | BIND_DEPTH_STENCIL | BIND_UNORDERED_ACCESS` or dynamic
  (`texture_capture.h:234-249`) — in `frame_30632051/draw_3368` the declared slots 8, 13, 19 are all absent while 0, 2,
  3, 4, 5, 7, 12, 14 are present. So soft particles read the scene depth **by SRV at draw time**; anything that replays
  the same draw with the same bindings gets soft particles for free.

**What would have to be added for a faithful replay:** all PS CBs (a full `PSGetConstantBuffers(0,14)` save/restore),
all PS SRVs and samplers used, the game's VS + input layout + VS CBs, raw VB/IB byte copies per frame, the blend/depth
states, the DSV (size-matched), and a re-issue point in the frame — i.e. a generic "replay the game's own pipeline"
path, an order of magnitude more than the HUD's `tex.Sample` quad. The alternative that needs almost none of that is in (e).

---

## (c) What was already learned and decided about blended / effect draws

**2026-11-01 — the user's decision.** Effect draws that declare t27/t30 reached Remix as solid cutout geometry and were
left out of the path-traced scene. Recorded as the code comment `live_capture.h:1693-1694` ("they stay out of the
path-traced scene (user decision 2026-11-01)") and repeated in `PLAN_2026-11-14.md:33`. `NIER_REMIX_LIVE_EFFECTS=1` was
kept as the diagnostic that puts them back as geometry. `PLAN_2026-11-01_effect-field.md` is *not* about that decision:
it is a one-expression logging fix for the `effect=` column (the capture path passed a hard-coded `false`,
`PLAN_2026-11-01_effect-field.md:31-33`; the same defect is visible today at `live_capture.h:1721`, where the effect path
also hard-codes `blended=false, target_format=0`).

**2026-11-13/14 — L7 "submit only real surfaces" (`PLAN_2026-11-13.md:549-566, 823-846`).** From each scene draw's
`state` the blended set was classified on `30632051` and `41686139`:

| shaders | blend | depth write | class |
|---|---|---|---|
| `cd8687d6`, `9f9c63c6`, `f5be3a42`, `c69bb592` | alpha | on | lit surfaces (decals, ground overlays) — kept |
| `3fefc02f`, `c2eeb2d4` | alpha | off | unlit darkening sheets |
| `483f6bd1` | alpha | off | soft particle |
| `2f38b1bd` | alpha | off | unlit tint layer |
| `33856d1d` | `DEST_COLOR × ZERO` | on | multiplicative decal |

Result (`PLAN_2026-11-13.md:841-845`): the sheets and particles were **already** dropped by the effect-buffer rule;
`NIER_REMIX_LIVE_SKIP_OVERLAYS=1` removed only the multiplicative decals and the tint layer (camp 961 → 950 meshes,
picture unchanged: mean difference 0.27). Decision: rule stays, default off, low impact.
Cross-check against today's log: the effect-family shaders in `NIER_SCALE.log` include codes `3fefc02f`, `c2eeb2d4`,
`483f6bd1` — i.e. L7's "unlit darkening sheet / soft particle" set **is** the t27 family, so L7 and E1 are the same set
of draws seen from two sides. L7 chose "do not submit"; E1 now has to choose "what instead".

**L6 emission (`PLAN_2026-11-13.md:525-548`)** decided the split that E1 inherits: "opaque unlit surface → emissive;
additive blended sprite (glow, particle) → not a surface, L7". L6 is blocked on data (no night/emissive capture,
`PLAN_2026-11-13.md:191`).

**Prior art on the pass shape** (`SCENE_DOMAIN_INVENTORY.md:35`): the desktop engine dump shows a
**half-res transparency/particles pass** (`6EBC42FB`, ~130 draws into `T4826` RGBA8 + `T4827` D24S8 at 1720×720) that is
composited back into the scene. That is the "reduced-size particle buffer" the plan's bullet 3 refers to — but it did not
appear in either capture analysed here (see (d)); the only half-size pass in `frame_30632051` is 133 draws of
`ps_1798908960`, which declares **no** resources at all (RDEF bound-count 0) and is therefore not a particle pass.

---

## (d) Measurements

Method: for every `draw_NNNN/capture.json`, read `ps_hash`, `state.{blend_enable,src_blend,dest_blend,blend_op,depth_write,depth_enable,depth_func}`, `vp_width/vp_height`, `index_count`; join `ps_hash` to the shader dump
(`ps_<hash>.dxbc`, present for **every** hash used: 24/24 laptop, 30/30 desktop) and parse the DXBC `RDEF` resource
bindings to mark a shader **effect-family** when it binds a structured buffer at 27 or 30. `ps_textures` slots 27/30 are
0 everywhere *by construction* (structured buffers are not textures), so that column of the brief is not measurable this
way — the RDEF join replaces it.

### d1. Totals

| capture | draws | indices | blend_enable=1 | blend-on indices | effect-family draws | effect draws blended | effect draws under 128 idx |
|---|---:|---:|---:|---:|---:|---:|---:|
| laptop `frame_67279062` (2880×1800, camp) | 923 | 12,242,352 | 24 | 117,417 | **10** | 10 (all) | 0 recorded (capture floor) |
| desktop `frame_30632051` (3440×1440, camp, scene 2580×1080) | 3,382 | 24,710,280 | 92 | 389,220 | **11** | 11 (all) | 0 recorded (capture floor) |

Both captures record only `index_count >= 128` (`draw_capture.h:255,266`); the smallest index count present is 129.
Shader corpus: 625 pixel shaders on the laptop, **287 of them effect-family** (t27 and/or t30; 273 t27, 210 t30), but
only 3 of the 24 shaders used in that frame are — i.e. the family is broad, the per-frame use is narrow.

### d2. `frame_67279062` — every blended draw, grouped

`E` = effect-family. Columns: `src>dest` D3D11_BLEND (5 SRC_ALPHA, 6 INV_SRC_ALPHA, 9 DEST_COLOR, 2 ONE, 1 ZERO).

| E | ps_hash | blend | op | depth write | depth func | viewport | draws | indices |
|---|---|---|---|---:|---:|---|---:|---:|
| E | 550345096712 | 5>6 | ADD | 0 | LESS_EQUAL | 2880×1800 | 4 | 13,824 |
| E | 550288868808 | 5>6 | ADD | 0 | LESS_EQUAL | 2880×1800 | 4 | 48,384 |
| E | 550288864328 | 5>6 | ADD | 0 | LESS_EQUAL | 2880×1800 | 2 | 2,304 |
|  | 550421507528 | 5>6 | ADD | 0 | LESS_EQUAL | 2880×1800 | 6 | 31,800 |
|  | 550347550280 | 5>6 | ADD | 1 | LESS_EQUAL | 2880×1800 | 4 | 11,304 |
|  | 550339515912 | 5>6 | ADD | 1 | LESS_EQUAL | 2880×1800 | 2 | 4,833 |
|  | 550347548488 | 5>6 | ADD | 1 | LESS_EQUAL | 2880×1800 | 1 | 3,924 |
|  | 550292875656 | 9>1 | ADD | 1 | LESS_EQUAL | 2880×1800 | 1 | 1,044 |

Unblended rows worth naming (targets): 1024×1024 shadow atlas 538 draws / 7.6 M indices (2 shaders), 2880×1800 scene
356 draws, **1440×900 = exactly half** 29 draws of `ps_550286859080` (93,753 tris). No effect-family draw touches
1024×1024 or 1440×900.

### d3. `frame_30632051` — every blended draw, grouped

| E | ps_hash | blend | op | depth write | depth func | viewport | draws | indices |
|---|---|---|---|---:|---:|---|---:|---:|
| E | 1844074720 | 5>6 | ADD | 0 | LESS_EQUAL | 2580×1080 | 5 | 17,280 |
| E | 1753805072 | 5>6 | ADD | 0 | LESS_EQUAL | 2580×1080 | 4 | 48,384 |
| E | 1754005152 | 5>6 | ADD | 0 | LESS_EQUAL | 2580×1080 | 2 | 2,304 |
|  | 1840405040 | 5>6 | ADD | 1 | LESS_EQUAL | 2580×1080 | 27 | 183,354 |
|  | 1753383696 | 5>6 | ADD | 1 | LESS_EQUAL | 2580×1080 | 25 | 98,454 |
|  | 1753383424 | 5>6 | ADD | 1 | LESS_EQUAL | 2580×1080 | 12 | 12,606 |
|  | 1802569552 | 5>6 | ADD | 1 | LESS_EQUAL | 2580×1080 | 4 | 9,936 |
|  | 1842243472 | **9>1** | ADD | 1 | LESS_EQUAL | 2580×1080 | 10 | 4,512 |
|  | 1962735776 | 5>6 | ADD | 0 | LESS_EQUAL | 2580×1080 | 2 | 12,240 |
|  | 1974932528 | 5>6 | ADD | 1 (depth **disabled**, func LESS) | — | **3440×1440** | 1 | 150 |

Unblended targets: 2048×2048 shadow atlas 1,220 draws (5.7 M+1.4 M indices), 2580×1080 scene 2,028 draws,
**1290×540 = exactly half** 133 draws of `ps_1798908960` (1,493,499 indices, RDEF declares nothing), 3440×1440 one draw.

### d4. What the two tables say

1. **All 21 effect draws in both frames are identical in state**: `SRC_ALPHA/INV_SRC_ALPHA`, op ADD, depth test on,
   `depth_write=0`, `LESS_EQUAL`, cull NONE, `D24_UNORM_S8`, drawn into the **scene target at scene size**. Same three
   shader roles in both areas and the same draw counts (4/4/2 vs 5/4/2) — this is ambient/fog/smoke scenery, not combat.
2. **Zero effect draws on a non-scene target** in either frame ⇒ the plan's bullet 3 ("effects drawn into other targets
   are dropped earlier by the scene-target filter") is **not supported by this data**. It may still be true for the
   half-res particle pass documented in `SCENE_DOMAIN_INVENTORY.md:35`, which was not in these captures and (per the
   funnel ratios below) may be under 128 indices.
3. **The blended population is dominated by ordinary surfaces**, not effects: 27+25+12+4 draws on the desktop of
   `ps_1840405040`, `1753383696`, `1753383424`, `1802569552` — all four bind the light buffer `g_PointLightAryBuffer`
   (t20, RDEF), i.e. lit alpha-blended decals with depth write on, the class L7 kept (`PLAN_2026-11-13.md:829-834`). Any
   rule that "treats blended draws as effects" would hit the wrong 70 %.
4. **The size rule hides most of the effect system.** `NIER_SCALE.log` funnel lines
   (`NIER_SCALE.log:4309,4332,4357,4380,4407,4432`) put the per-window mix at `pass≈53 %`, `prepass≈14 %`,
   `small≈16-18 %`, `unchanged≈15 %`, `effect≈0.8 %` of ~141,000-151,000 draws. The laptop's `small ps=` lines
   (`NIER_SCALE.log:88-103`) show 90 distinct shaders dropped at 4-6 indices, and **7 of the 15 effect-family shaders in
   that log also appear in that small list** — i.e. the full-screen distortion/composite passes are 4-index draws that
   are dropped by filter 6 and never recorded by any F9 capture (`PLAN_2026-11-13.md:168` says the same about the grade).
5. **Shader-table caveat:** `remix: shader … effect=N` cannot be used to describe effect blend states today, because the
   effect-drop path passes `blended=false, target_format=0` (`live_capture.h:1721`). `remix: material … effect=1` lines and
   the F9 captures are the only usable sources. `NIER_SCALE.log` lists 47 material notes: 15 shaders `effect=1`, 32 `effect=0`.
6. **Frame-level counts of effect draws differ by area**: across all nine desktop captures only five have any effect draw at
   all, 7-11 each (`frame_12935626` 7 @640×350, `23275488` 7, `30632051` 11, `41686139` 7, `7991289` 0, others 0 with
   `blend_enable=0` throughout). No capture exists with combat.

### d5. The classifier used above (pure stdlib, safe to reuse)

```python
import json, os, struct
def binds(path):                        # -> [(bind_point, D3D_SIT_type)], empty when RDEF declares nothing
    b = open(path, 'rb').read()
    n = struct.unpack_from('<I', b, 28)[0]                      # DXBC chunk count
    for i in range(n):
        off = struct.unpack_from('<I', b, 32 + 4 * i)[0]
        if b[off:off+4] != b'RDEF': continue
        d = b[off+8:off+8+struct.unpack_from('<I', b, off+4)[0]]
        cb, cboff, count, boff = struct.unpack_from('<4I', d, 0)
        return [(struct.unpack_from('<8I', d, boff + 32*j)[5],       # BindPoint
                 struct.unpack_from('<8I', d, boff + 32*j)[1])       # Type (5 = structured)
                for j in range(count)]
    return []
def effect_family(dxbc): return any(bp in (27, 30) for _, bp in binds(dxbc))
def is_lit(dxbc):        return any(bp == 20 for _, bp in binds(dxbc))     # g_PointLightAryBuffer
```
Bind-point entry layout verified against `MATERIAL_INPUTS_SLOTS.md:59-60` (27 = `g_EffectPixelCommonBuffers`,
30 = `g_EffectPixelCategoryBuffers`) and the names printed by `checks/dump_shader_decls.py`. Note the capture's
`ps_hash` is the shader **pointer** and matches the dump's `ps_<n>.dxbc` file name in all 24 + 30 cases here.

---

## (e) Design: composite the game's effects over the Remix image, in order

The insight that makes this cheap: **compositing a draw that is alpha-blended, depth-write-off, directly onto the Remix
image with the *same* blend state is mathematically identical to what the game does on its own scene** — ROP blending
is per-fragment against the current destination, so within-draw and inter-draw ordering is preserved; only what lies
underneath changes, which is the intent. No alpha channel, no separate layer maths. What is *not* free is getting the
draw to happen at composite time with the game's own VS/PS/state.

So there are two shapes, and the cheap one should be tried first.

**Variant B — divert at draw time, composite at the handoff (recommended first).**
The game renders its own effect draws, unmodified, into our full-scene-size target instead of its scene target; we then
draw that texture over the Remix image at the handoff (Path 2). Everything the effect needs — VS, PS, CBs, t13 depth,
fog LUTs, blend, depth test — is the game's own and is never touched, because we only swap one render target for the
duration of those draws.

1. Create `fxRT` (scene size, same **view** format as the game's scene RTV — query it; the capture only knows the
   typeless format 26) once per size change, on the game thread.
2. In the draw hook, for a draw that `pixel_info(...).effect` is true (`live_capture.h:1719`) and the switch is on:
   `OMGetRenderTargets` → save; `OMSetRenderTargets(1, &fxRTV, gameDSV)` (keep the game's DSV: depth test unchanged,
   **no size problem**, because the RT we replace is the same size as the DSV); forward the draw; restore. The proxy
   already forwards through function pointers (`draw_capture.h:247-269`), so this is a wrapper around the forward call.
   Cost: 2 state calls per effect draw (10-20 per frame), no copies, no decoding.
3. Clear `fxRT` to (0,0,0,0) at frame start (`live_capture::begin_frame`), record the "dirty" bounding box if the clear
   ever shows up in a profile.
4. At the handoff (`remix_live.cpp:1335`, right after the Remix full-screen quad, before the HUD sprites): draw `fxRT`
   as a second full-screen quad with blend `(SrcBlend=ONE, DestBlend=INV_SRC_ALPHA)` and `alpha = fx.a`. This requires
   the accumulated coverage in `fx.a`, i.e. the game's **alpha** blend state must be `(ONE, INV_SRC_ALPHA)` or
   `(SRC_ALPHA, INV_SRC_ALPHA)`; the `D3D11_BLEND_DESC` is already read at `live_capture.h:1534-1540` but only
   `SrcBlend/DestBlend` are kept — keep `SrcBlendAlpha/DestBlendAlpha` and `RenderTargetWriteMask` too (see unknowns).
   If the alpha state is unusable, fall back to `(ONE, ONE-MINUS_SRC_ALPHA)` with a fixed fudge or to "draw fx opaque
   where fx.a > 0" for a look decision.
5. Where the target sizes differ (desktop, 2580×1080 → 3440×1440) the quad is a bilinear upscale, the same thing the
   game's own final pass does.
6. Switch: `NIER_REMIX_LIVE_EFFECT_COMPOSITE=1`, default 0 = today's picture. Gate: a mock case where an effect draw
   (mock shader with a `dcl_resource_structured t27`) goes into `fxRT` and the composite quad reports the diverted draw
   count; mutant (composite off) must fail.

**Variant A — replay the draws at composite time (only if B's picture is wrong).** Needs the generic pipeline replay in
(b2): game VS+PS+layout, all CBs, all SRVs/samplers, raw VB/IB copies (~0.1-2 MB/frame; the capture's `bytes` are whole
buffers so the true range must be computed from the IB), the blend/depth state, and a DSV whose size matches the
composite target (works at native scale only). More faithful for effects that must be occluded by *Remix's* geometry,
which is impossible anyway (Remix's depth is a different buffer), so the only thing A buys over B is that the effects
land in the right frame order relative to HUD.

**Variant C — let Remix render the simple cases** (sparks, glows, emissive). The API supports it:
`remixapi_MaterialInfoTranslucentEXT` (`remix_c.h:236-269`, handled by the runtime at
`runtime/remix-source/0ba9973f.../rtx_remix_api.cpp:236,459`) and the opaque EXT's `blendType_hasvalue` /
`blendType_value` / `useDrawCallAlphaState` (`remix_c.h:250-254`; the repo comment `nscn_scene.h:133-138` records that
`blendType_hasvalue=1, value=2` made every surface see-through before it was set to 0). Our materials never set it
(`nscn_scene.h:125-146`). This is the L6 route and is a look decision for the user, not an E1 blocker. NOTE: the source
drop is commit `0ba9973…` while the shipped runtime logs `remix-main+5a7eec84` (`LAPTOP_PORT.md:96`,
`runtime/laptop-play-20261114/remix.log:6`) — the API surface above must be re-checked against the shipped header
(UNVERIFIED).

**Ordering interaction with P2.** Both composite paths live in the D3D11 Present hook / the game's draw hook. P2
("Remix owns presentation", `PLAN_2026-11-14.md:14`) removes the present-hook composite; Path 2 (the handoff) survives
it because it happens in the game's own frame. E1 should therefore be built **on Path 2 only**, or it will be rewritten
by P2 within days.

**Unknowns that must be measured before code (in this order):**
1. The game's alpha blend factors and write mask for effect draws (`SrcBlendAlpha`, `DestBlendAlpha`,
   `RenderTargetWriteMask`) — one line in the live hook; decides whether Variant B's composite can be exact.
2. The **view** format of the game's scene RTV (UNORM vs SRGB) and of the R11G11B10 final target — needed to create
   `fxRT` with matching blend maths. The capture records the typeless `target_format` only.
3. Whether any effect draw has `depth_write=1` (the tables say no, 21/21) — a diverted depth-writing draw would corrupt
   the game's later depth-dependent passes.
4. Whether the DSV at effect time is the same resource as at the handoff, and whether the game clears or reuses it before
   the handoff. `OMGetRenderTargets` at both points + pointer equality, one log line each.
5. How many effect draws exist **in combat**, and how many are under 128 indices (a `NIER_REMIX_LIVE_MIN_INDICES=4` run
   with the funnel line and the `remix: shader` table, after fixing 6 below). This is the number the whole item stands on,
   and no capture has it.
6. The full-screen post passes (4-index, effect-family, e.g. distortion/bloom/grade): what they read and write, and
   whether they are worth running over the Remix image (that is a different feature: post-chain injection, not
   compositing).

---

## Open questions

1. **How many effect draws per frame in combat, and how many are under 128 indices?** Unknown: no capture with combat
   exists (the only save is the camp, `PLAN_2026-11-13.md:1597`), and the captures have a 128-index floor. Determine with
   the C1 play session (`PLAN_2026-11-14.md:21`) plus `NIER_REMIX_LIVE_MIN_INDICES=4` and the funnel line.
2. **Is the sub-128 population mostly effects or mostly UI/foliage?** 90 distinct small shaders in the laptop log, 7 of
   them effect-family; the rest unidentified. Determine by dumping `ps_<hash>.dxbc` for the small-shader pointers and
   classifying their RDEF (the same script as (d)).
3. **What are the 4-index effect passes?** They are dropped before any classification. Determine with a
   `MIN_INDICES=4` run and the `remix: material effect=1` notes.
4. **Does the effect VS expand billboards from points?** Decides whether Variant A is even possible without a geometry
   shader. Determine by disassembling the VS of a t27 draw (`frame_67279062/draw_0917` has `vs_hash` and `vs_cbs`).
5. **Is the t13 depth SRV really bound at the effect draw?** Strongly indicated (slot 13 declared and absent from
   `ps_textures`, which only drops RT/depth SRVs), not proven. Determine by logging `PSGetShaderResources(13,1)` in the
   live hook for effect draws.
6. **Alpha blend factors of the effect state.** Not in any capture. One line in `live_capture.h:1534-1540`.
7. **Does the shipped runtime (`+5a7eec84`) match the source drop (`0ba9973`)?** The translucent/opaque-EXT field layout
   used in Variant C must be re-verified against the shipped `rtx_remix_api` behaviour, or by trying it and reading the
   Remix log.
8. **Does anything in the game read the scene colour target after the effect draws** (so that diverting them changes the
   game's own frame in a way that reaches the HUD/final target)? The game's post chain does read the scene, but its output
   is discarded. Determine by checking whether any draw after the effect draws binds a slot that the capture omits (RT/depth
   SRVs) and writes to the final target.

## Recommended steps for the plan

1. **Fix the tally first (1 line + gate).** `live_capture.h:1721`: pass the real `blend_on, blend_src, blend_dest` and
   `target_format` into `tally_shader` so `remix: shader … effect=N` carries a usable state; extend
   `test_overlay_rule.py`'s sibling gate (or `test_live_normal_map.py`'s mock shader set, which already has an
   `MOCK_SMALL_DRAW` case) with a draw that has `t27` in its disassembly and a blend state, asserting the logged line.
   Check: `python3 analysis/checks/test_live_normal_map.py` green and red when reverted.
2. **Record the missing state fields** in `live_capture.h:1515-1550`: `SrcBlendAlpha`, `DestBlendAlpha`,
   `RenderTargetWriteMask`, the RTV **view** format, and `PSGetShaderResources(13,1)` presence for effect draws; print
   them on the `remix: material … effect=1` line. Check: mock run logs the fields; gate asserts them.
3. **Run one live session with `NIER_REMIX_LIVE_MIN_INDICES=4`** (laptop, camp + whatever effects exist) and collect the
   funnel line plus `remix: material` and `remix: shader` output. Deliverable: a table of **every** effect-family shader
   with draw count, index count, blend/alpha state, viewport, whether it was under 128 indices, and what it is (one line
   of prose each). This is the plan's own "first step", done correctly. No code change beyond steps 1-2.
4. **Write the unknowns of (e) as a gate fixture** before any rendering change: `test_effect_composite.py` with three
   cases — (i) an effect draw with the switch off goes to the game's scene target and the composite quad is not drawn;
   (ii) with `NIER_REMIX_LIVE_EFFECT_COMPOSITE=1` it goes to `fxRT` and the quad is drawn with blend `(ONE, INV_SRC_ALPHA)`;
   (iii) a non-effect blended draw (a lit decal, `5>6` with `depth_write=1`) is **not** diverted. Mutants: composite
   without diversion, and diversion without the effect test, must both fail.
5. **Implement Variant B behind `NIER_REMIX_LIVE_EFFECT_COMPOSITE`** in `checks/live_capture.h` (divert, ~20 lines around
   `:1719`) plus `checks/remix_live.cpp` (create/clear `fxRT`; one extra quad at the handoff `:1335`) and a
   `hud_replay::draw` variant that takes a blend mode instead of `opaque`. Default off.
6. **A/B on the laptop against the game's own frame** at a still camera in the camp (the camp's ambient fog draws are the
   only effect data we have): with the switch off the fog is absent, with it on the fog matches the game's own frame in
   that region; measure the mean/max difference as in the L1/L7 sheets, and record the sheet path next to E1.
7. **Then, and only then, ask the user** for the two look decisions that Variant B cannot answer: (i) whether composited
   effects should also *light* the scene (Variant C / L6 emission, needs an intensity pick), and (ii) whether the
   full-screen post passes (distortion, bloom, grade) should run over the Remix image at all (post-chain injection, a
   bigger item that also subsumes `W2`).
8. **Keep the solid-geometry path** (`NIER_REMIX_LIVE_EFFECTS=1`) as the diagnostic; do not delete it.
9. **Do not build E1 on `hud_replay`'s present-hook composite** unless P2 is deferred: P2 removes that path
   (`PLAN_2026-11-14.md:14`). The handoff path (`remix_live.cpp:1262-1345`) is the one that survives.
10. **Log every delegated piece** (the shader census in step 3 is a good `local-worker` job; the RDEF classifier script is
    already written in this recon and can be lifted) and re-run the gate yourself before accepting it.
