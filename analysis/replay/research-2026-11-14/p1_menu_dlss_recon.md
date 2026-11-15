# P1 recon — standard DLSS modes as a row in our Insert menu

Read-only recon, 2026-11-14. Every claim carries `file:line`. Two Remix trees are cited explicitly:
**[full]** = `analysis/runtime/src/dxvk-remix/` (the complete source tree),
**[partial]** = `analysis/runtime/remix-source/0ba9973f…` (14-file drop; not needed here).

## 0. Bottom line

1. There is no row table. The panel is one hardcoded ImGui combo with two entries in
   `analysis/menu-preview/panel.cpp:199-206`; `Mode` has exactly two values
   (`analysis/checks/render_settings.h:9`). A "row" today = one `Selectable` + one line of label text.
2. Today the panel is **next-launch only**: `analysis/IN_GAME_MENU.md:8` "Save writes `NIER_RENDER.ini` for the
   **next launch** only. Nothing changes live." P1 asks for a live change, which does not exist yet in any form.
3. `SetConfigVariable` is in the C API and in [full]: declaration `analysis/runtime/remix-probe/sample/include/remix/remix_c.h:724`
   (typedef), `:810` (interface member); implementation [full]
   `src/dxvk/rtx_render/rtx_remix_api.cpp:1245-1273`; slot filled at `:1797`.
4. Our proxy calls **zero** Remix config functions today (`grep SetConfigVariable analysis/checks/` → nothing).
5. Two silent overriders sit above the layer that `SetConfigVariable` writes (User, priority `0xFFFFFFFE`):
   the Quality layer (`0xFFFFFFFF`, `rtx_option_constants.h:194`) and `rtx.dlssPreset != Custom`
   (`rtx_options.cpp:608-610`, `:167-181`). Both must be pinned by the design or the menu row will do nothing.
6. On the laptop the "Auto" profile is **not** resolution-derived: RTX Spark forces `MaxPerf`
   (`rtx_gpu_profile.cpp:42`, `:225-232`; consumed `rtx_dlss.cpp:103-107`). Picking Auto in the menu gives
   Performance on the laptop and something else on the desktop.

## 1. How the Insert menu is built

| Piece | File:line | What it does |
| --- | --- | --- |
| Hook + window + input | `analysis/checks/menu_overlay.cpp:550-640` | `render_panel()`: Insert/Esc polling, cursor release, `menu_preview::draw_panel`, one backbuffer RTV per frame |
| Panel body | `analysis/menu-preview/panel.cpp:96-253` | A single function, no table: title, ACTIVE section, one combo, save/discard, footer |
| The row itself | `analysis/menu-preview/panel.cpp:199-206` | `ImGui::BeginCombo("##preset", …)` then two `ImGui::Selectable`, each calling `render_menu::select(state, Mode::…)` |
| Row label/help text | `analysis/menu-preview/panel.cpp:210-212` | one `text(..., Secondary, ...)` line per state |
| Geometry published for tests | `analysis/menu-preview/panel.cpp:200`, `panel.h:15-20` | `observed.preset = last_item()` → `Geometry::preset` rect |
| Scroll body | `analysis/menu-preview/panel.cpp:169` | `ImGui::BeginChild("body", …avail minus footer…)`: content that overflows scrolls, so a new row does not need a taller panel |
| Panel size | `analysis/menu-design/claude_style_tokens.json:25-37` | `width 552`, `nominal_height 516`, `combo_height 46`; frozen by `checks/test_menu_style_tokens.py:70-74` |
| State machine | `analysis/checks/menu_state.h:12-70` | `State` (active/saved/edited), `select()`, `can_save()`, `notice()`, `complete_save()` |
| Labels per mode | `analysis/menu-preview/panel.cpp:18` | `mode_name()` — a second place the mode names are written |

**A "row" therefore consists of:** an enum value in `render_settings::Mode`
(`checks/render_settings.h:9`), an accepted string in `render_settings::select()`
(`render_settings.h:40-41`), a `name()` (`render_settings.h:56`), a `mode_name()` case
(`menu-preview/panel.cpp:18`), a `Selectable` (`panel.cpp:203` and `:205`), the combo's current-text ternary
(`panel.cpp:198`), and a `render_menu::select()` guard (`menu_state.h:37-42`). Nothing is table-driven; a
four-value DLSS row added naively duplicates five switch sites.

## 2. How a value is applied live — and how it is persisted

Live: **nothing is applied**. The row only sets `state.edited` (`checks/menu_state.h:37-42`); the panel's
own text says "Save to repair/… Restart required" (`panel.cpp:128-131`), and `Notice::RestartRequired`
(`menu_state.h:65-69`) exists precisely because the value cannot take effect this session.

Persisted path for what exists today:
1. Click Save → `panel.cpp:236-237` calls the `SavePreset` callback with `state.edited`.
2. `menu_overlay.cpp` wires that callback to `menu_settings_io::save()`
   (`checks/menu_settings_io.h:45-56`).
3. `settings_save::save()` does an atomic replace with recovery copies (`checks/settings_save.h:20-30`, `save()` at `:78`), then `menu_settings_io::observe()` re-reads the file — the state
   machine requires that second observation (`menu_state.h:46-52`, `menu_settings_io.h:20-45`).
4. The bytes are produced by the frozen pure rewriter `render_settings_file::rewrite()`
   (`checks/preset_rewrite.h:10-111`, contract `checks/PRESET_REWRITE_CONTRACT.md:1-40`): it replaces the value of
   the single `[Rendering] Preset` key, byte-exact, 64 KiB cap, `Ambiguous`/`Malformed` refusals.
5. The file is `<proxy dir>\NIER_RENDER.ini`, read at startup by `d3d11_scale_setter.cpp:311-345`
   (`GetPrivateProfileStringW(L"Rendering", L"Preset", …)`, logged as
   `render settings: Preset=%ls scale=%.3f valid=%d defaulted=%d (startup only)`).

Two files exist, and they are different channels:
- `NIER_RENDER.ini` — our own menu's next-launch preset (`[Rendering] Preset`), written by us.
- `NIER_ENV.ini` — `NIER_*` environment settings for Steam launches (`checks/env_file.h:1-46`), parsed and pushed
  into the process environment at proxy init (`checks/d3d11_scale_setter.cpp:430-455`, log line
  `NIER_ENV.ini: %d settings applied, %d already set in the environment`). An already-set variable wins
  (`d3d11_scale_setter.cpp:447-449`). **This is the cheapest channel for a Remix option**: a
  `NIER_REMIX_DLSS_PROFILE` line needs no new INI writer, only a reader.

Remix's own user layer is **not** saved by `SetConfigVariable`. Unmanaged writes live in memory; the only
`save()` call on the user layer is the Remix UI's "Save Settings" button
([full] `src/dxvk/imgui/rtx_user_menu.cpp:276-279` → `rtx_option_layer.cpp:406-437`, file name
`user.conf`, `rtx_option_constants.h:124`, layer acquired at `rtx_option_layer.cpp:735`). So our menu must
persist the key itself.

## 3. Which gates test the menu, and how a row is added to them

| Gate | Asserts (evidence) | What a new row must do |
| --- | --- | --- |
| `checks/test_menu_state.py` (frozen; `menu_state_test.cpp`) | `select`/`can_save`/`notice` transitions | add `select()` cases and `can_save()` rules for the new modes |
| `checks/test_menu_file_state.py` (frozen; `menu_file_state_test.cpp`, 2 TUs, ASan/UBSan, MinGW x64) | file-state → save-enabled rules | new enum values must not change existing expectations |
| `checks/test_menu_session.py` (frozen; `menu_session_test.cpp`) | startup outcome → `SessionMode` | unaffected unless a new session mode is added |
| `checks/test_preset_rewrite.py` + `checks/preset_rewrite_test.cpp` | byte-exact `[Rendering] Preset` rewrite, 30+ cases | **untouched** if the DLSS key is separate; broken if `Mode` gains values without updating `select()` |
| `checks/test_settings_save.py` (230 lines) + `checks/save_commit_cases.py` | atomic replace, external-change detection, recovery | writer path only; must keep passing |
| `checks/test_menu_overlay.py` (265 lines, Wine + Xvfb + mock game + stub DLAA) | panel pixels at `1920-32-552, 32` (`:99-115`), `menu: save Native -> outcome=0`, INI bytes `b'[Rendering]\r\nPreset=Native\r\n'` (`:114-115`), `cs_lost=0`, frame capture cadence | a new combo entry + one click scenario + one log line; the pixel probes at `(x0+10,y0+20)` stay valid because they sample the panel background, not the row |
| `checks/test_remix_live.py` (282 lines, fake runtime) | lifecycle order, `CreateMesh`…, and "menu must draw over Remix" (`:141`) | the place to assert a `SetConfigVariable` fake-log line |
| `menu-preview/panel_test.cpp` (via `menu-preview/build.py:54-56`) | Save/Discard rects inside the panel (`panel_test.cpp:97-108`), body must scroll at 1080p×2 (`:109-119`) | a new row goes **inside the scrolling body**, above the notice box; never below Save |
| `checks/test_menu_style_tokens.py` | `data == EXPECTED` against the frozen handoff (`:70-74`) | only if `nominal_height` changes; keep the height, let the body scroll |
| `checks/gates.py:31-42,52-68` | dependency map: any gate text naming a header picks it up; `DLL_HEADERS`/`DLL_SOURCES` select the DLL rebuild | a new header must be named in its gate and added to `DLL_HEADERS` if the DLL includes it |

## 4. How the proxy talks to Remix today

- Interface obtained once: `remixapi_lib_loadRemixDllAndInitialize(runtime_path, &api, &module)`
  (`checks/remix_live.cpp:765`), then a null-check of 14 members (`:768-772`). `SetConfigVariable` is not
  checked, not called.
- `remixapi_Interface api` is a **member of `Worker`** (`checks/remix_live.cpp:476-479`), and the comment above
  that struct is explicit: "Everything Remix-side lives on this thread."
- The worker is a detached thread started from the game's first Present
  (`remix_live.cpp:1370-1435`), running `Worker::run()` (`:1172-1230`); it calls
  `api.dxvk_CreateD3D9` … `api.Present` (`:784-1134`).
- Existing cross-thread channel that a config hand-off can copy: Present writes
  `want_width/want_height/want_format` under `std::mutex published` (`remix_live.cpp:112-114`, written at `:1417`), the worker reads
  them at the top of each loop iteration (`:1179-1189`). That loop is the natural place to poll a pending
  config request (one call per iteration, before `frame()`).
- `checks/remix_live.h:14-21` is the whole Game↔worker contract: `before_draw`, `on_present`, `begin_game_frame`.
  A config request would be a fourth entry.
- Fake runtime: `checks/remix_live_fake_runtime.cpp:363-402` default-constructs the interface and fills 16
  members; **`SetConfigVariable` stays null**. Calling it under the gate would jump through a null pointer —
  the fake must implement it before any test of the feature can exist, and its log (`note()`, `:20-26`,
  writes `fake-remix.log`) is the assertion surface.

## 5. `SetConfigVariable` in the Remix source

Declaration ([0.6.6 header, shipped with the probe] `remix_c.h:721-726`):
```
// Writes an RtxOption value to the user layer. Keys in a registered dynamic option namespace are
// validated immediately and applied at the next frame's option update. Returns INVALID_ARGUMENTS for an
// invalid key or value, GENERAL_FAILURE for an unknown key.
typedef remixapi_ErrorCode(REMIXAPI_PTR* PFN_remixapi_SetConfigVariable)(const char* key, const char* value);
```
Struct member: `remix_c.h:799` (struct opens), `:810` `PFN_remixapi_SetConfigVariable SetConfigVariable;` —
it sits between `DrawLightInstance` and the `dxvk_*` block. The same member exists at the same relative
position in the older headers we ship (`runtime/prior-art-deep-20261031/fo4/kim-runtime/remix_c.h:997`,
`fo4/plus-runtime/remix_c.h:1012`), so the slot is stable across versions.

Implementation ([full] `src/dxvk/rtx_render/rtx_remix_api.cpp:1245-1273`):
1. `std::lock_guard lock { s_mutex }` — the API serialises on its own mutex (`:1248`).
2. Rejects null/empty key, null value → `INVALID_ARGUMENTS` (`:1250-1252`).
3. `RtxOptionImpl::getOptionByFullName(key)`; if unknown **or dynamic** it goes to
   `RtxOptionManager::queueDynamicValue` and returns `Success`/`InvalidArgument`/`GENERAL_FAILURE` (`:1256-1266`).
4. Otherwise `Config newSetting; newSetting.setOptionMove(key, value); option->readOption(newSetting, RtxOptionLayer::getUserLayer())` (`:1268-1270`).
   `readOption` creates the User-layer value and calls `markDirty()` (`rtx_option.cpp:447-466`), so the value is
   visible to the next read of the option; `readValue` parses by type (`rtx_option.cpp:407-445`), i.e. an
   **enum option must be given its integer**, not its name. A value that fails to parse falls back to the
   current value (`getOption<int>(name, value.i)`) and still returns `SUCCESS` — UNVERIFIED whether a warning is
   logged; assume silent.
5. Registered as `interf.SetConfigVariable = remixapi_SetConfigVariable;` (`:1797`), struct size pinned by
   `static_assert(sizeof(interf) == 176)` (`:1807`).

Not applicable to the dynamic option namespaces we care about: `qualityDLSS`, `upscalerType`,
`dlssPreset` and `rtx.xess.preset` are all statically declared options
([full] `rtx_options.h:569`, `:508`, `:323`, `rtx_xess.h:53`), so they take path 4.

## 6. The options and their layer behaviour

| Option | Declared | Type / default | Values |
| --- | --- | --- | --- |
| `rtx.qualityDLSS` | [full] `rtx_options.h:569` (`environment = "RTX_QUALITY_DLSS"`, `UserSetting`) | `DLSSProfile`, default `Auto` | `UltraPerf=0, MaxPerf=1, Balanced=2, MaxQuality=3, Auto=4, FullResolution=5, Invalid=6` (`rtx_dlss.h:35-43`) |
| `rtx.upscalerType` | `rtx_options.h:508` | `UpscalerType`, default `DLSS` | `None=0, DLSS=1, NIS=2, TAAU=3, XeSS=4` (`rtx_options.h:70-76`) |
| `rtx.dlssPreset` | `rtx_options.h:323` | `DlssPreset`, default `On` | `Off=0, On=1, Custom=2` (`rtx_options.h:82-86`) |
| `rtx.enableRayReconstruction` | `rtx_options.h:511` | `bool`, default `true` | — |
| `rtx.xess.preset` | [full] `rtx_xess.h:53` (`UserSetting`) | `XeSSPreset`, default `Balanced` | `UltraPerf=0, Performance=1, Balanced=2, Quality=3, UltraQuality=4, UltraQualityPlus=5, NativeAA=6, Custom=7, Invalid=8` (`rtx_options.h:89-98`) |

Generated option reference with defaults: `[full] RtxOptions.md:199` (`rtx.dlssPreset` default 1),
`:626` (`rtx.qualityDLSS` default 4), `:879` (`rtx.upscalerType` default 1), `:975` (`rtx.xess.preset` default 2).

Menu labels in the runtime (they differ from the enum names — copy these, not the enum):
`dxvk_imgui.cpp:313-319` `{UltraPerf,"Ultra Performance"}, {MaxPerf,"Performance"}, {Balanced,"Balanced"},
{MaxQuality,"Quality"}, {FullResolution,"Full Resolution"}, {Auto,"Auto"}`; strings in
`rtx_dlss.cpp:41-51` ("Max Performance", "Max Quality"); XeSS labels `dxvk_imgui.cpp:339-346`.
GPU-override string names (a third spelling, `rtx.gpuOverride.dlssMode.<VVVV_DDDD>`):
`rtx_gpu_overrides.cpp:87-92` "UltraPerformance/Performance/Balanced/Quality/FullResolution".

**Layer priority** ([full] `rtx_option_constants.h:186-194`): Default 0 < DXVK 1 < ConfigCpp 2 < **rtx.conf 3** <
baseGameMod 4 < Environment 5 < Derived 6 < **User 0xFFFFFFFE** < **Quality 0xFFFFFFFF**.
`SetConfigVariable` passes the User layer explicitly (`rtx_remix_api.cpp:1270`), and an explicit layer wins over
flag routing (`rtx_option.cpp:902-905`). Consequence: **anything written into the Quality layer outranks the
menu**, and Derived does not.

Who writes `qualityDLSS` above us:
- `updateUpscalerFromDlssPreset()` (`rtx_options.cpp:159-181`): `DlssPreset::On` → `upscalerType=DLSS` **and**
  `qualityDLSS = Auto` (both `setImmediately`, Derived target → Quality layer because a non-Custom graphics preset
  is active); `Off` → `upscalerType=None`, `reflexMode=None`.
- `updateGraphicsPresets()` (`rtx_options.cpp:410-613`): `if (dlssPreset() != DlssPreset::Custom) qualityDLSS.setDeferred(DLSSProfile::Auto)` (`:608-610`).
- Switching to `graphicsPreset = Custom` migrates the whole Quality layer into User (`rtx_options.cpp:66-84`).
- Routing rule in prose and code: code-driven `UserSetting` writes → Quality layer, unless `graphicsPreset == Custom`
  (`rtx_option_layer.h:44-56`, `rtx_option.cpp:902-930`).

So: **`rtx.dlssPreset = 2` (Custom) is a hard precondition** for the menu's `rtx.qualityDLSS` to have any effect,
and it is already in both live confs (§8). A second precondition, on the laptop specifically: see §7.

## 7. How DLSS picks its render resolution, and whether it survives a live change

- `DxvkDLSS::setSetting(displaySize, profile, outRenderSize)` ([full] `rtx_dlss.cpp:132-176`):
  `Auto` → `getAutoProfile()`; if profile and output size are unchanged it returns the cached size (`:145-150`);
  otherwise `mRecreate = true` (`:155`), `profileToQuality()` (`:78-92`:
  UltraPerf→`NVSDK_NGX_PerfQuality_Value_UltraPerformance`, MaxPerf→`MaxPerf`, Balanced→`Balanced`,
  MaxQuality→`MaxQuality`, FullResolution→`DLAA`), then **`queryOptimalSettings`** decides the input size
  (`:166-172`). `assert(input ≤ output)` at `:175`.
- The recreation is real: `dispatch()` does `mRecreate |= …; if (mRecreate) { releaseNGXFeature(); … }`
  (`rtx_dlss.cpp:208-220`). A profile change therefore rebuilds the DLSS feature on the next frame — a live
  change is supported by construction. Same structure for Ray Reconstruction:
  `rtx_ray_reconstruction.cpp:384-417` (`mRecreate = true` at `:401`).
- **Auto is resolution-derived only without a per-GPU override**: `getAutoProfile` returns early when
  `selectAutoDlssMode(GpuOverrides::getDlssMode(), GpuProfile::isRtxSpark())` gives a value
  (`rtx_dlss.cpp:103-107`), and `selectAutoDlssMode` returns `kRtxSparkDlssMode = DLSSProfile::MaxPerf`
  for RTX Spark (`rtx_gpu_profile.cpp:42`, `:225-232`), else the per-GPU override. Only when both are absent does
  height decide: ≤1080 MaxQuality, <2160 Balanced, <4320 MaxPerf, else UltraPerf, one step lower on Medium,
  two on Low (`rtx_dlss.cpp:109-133`).
- **Render sizes are computed by NGX, not by a table in our tree** — `queryOptimalSettings`
  (`rtx_ngx_wrapper.h:169`, `:248`) is the only source. Expected sizes from the SDK's documented per-axis
  factors (Quality 2/3, Balanced 0.58, Performance 1/2, Ultra Performance 1/3, DLAA 1.0). Exact rounding is
  NGX's; treat these as **expected, not verified in source**:

| Mode (`qualityDLSS`) | factor | 2880×1800 | 3440×1440 |
| --- | --- | --- | --- |
| Quality (`3`) | 2/3 | 1920×1200 | 2293×960 |
| Balanced (`2`) | 0.58 | ~1671×1044 | ~1995×835 |
| Performance (`1`) | 1/2 | 1440×900 | 1720×720 |
| Ultra Performance (`0`) | 1/3 | 960×600 | ~1146×480 |
| Full Resolution / DLAA (`5`) | 1.0 | 2880×1800 | 3440×1440 |

  (For comparison the XeSS path *does* have a scale table in source: `getUpscaleFactor`
  [full] `rtx_xess.cpp:374-386` = 3.0/2.3/2.0/1.7/1.5/1.3/1.0, with the SDK's
  `xessGetOptimalInputResolution` preferred and a truncating fallback `displaySize * (1/upscale)` at `:740-745`.
  XeSS preset change → `m_recreate = true` at `:708`.)
- Ray Reconstruction has its own profile: `enableRayReconstruction = True` means the *rendered* profile comes
  from `rayReconstruction.getCurrentProfile()` and the UI reads `qualityDLSS` into `setSettings` too
  (`rtx_user_menu.cpp:415-431`). Both setters call the same `profileToQuality` on the same
  `qualityDLSS` value, so one option drives both. UNVERIFIED: whether DLSS-RR on the laptop ends up one profile
  off; the log does not print either output profile.

## 8. PLAN_2026-11-13 §11.1, summarised and corrected

§11.1 (`analysis/PLAN_2026-11-13.md:1681-1693`) says:
1. `rtx.dlssPreset` defaults to `On` and writes `upscalerType = DLSS` into the Derived layer, above `rtx.conf`;
   without NGX it falls back to TAAU at `resolutionScale` 0.5 — therefore every conf carries `rtx.dlssPreset = 2`.
   **Still true** (`rtx_options.cpp:167-181`, `rtx_context.cpp` fallback path as cited there).
2. A graphics preset other than Custom writes over the preset-owned keys; only `graphicsPreset = 4` protects those.
   **Still true** (`rtx_options.cpp:410-613`), and now precisely located for our key: `:608-610`.
3. Custom is not free (it starts from stock quality); Auto picks Low on the AMD card; an unknown/misspelt key
   **gives no error** — this last row was marked "assumed, not read in source".
   **Corrected:** unknown keys are detected. `SetConfigVariable` returns `GENERAL_FAILURE` for an unknown key
   (`rtx_remix_api.cpp:1257-1265`, documented `remix_c.h:721-723`). A *valid key with an unparsable value* is
   still silent (`rtx_option.cpp:412-414`).
4. "Auto DLSS profile by output height" — **incomplete for the laptop**: the GPU override / RTX Spark branch
   short-circuits height entirely (`rtx_dlss.cpp:103-107`).

## 9. What the live confs set today

`deploy/rtx/laptop-game.conf:5-10`: `rtx.enableRayReconstruction = True`, `rtx.dlssPreset = 2`,
`rtx.upscalerType = 1`, `rtx.qualityDLSS = 0` (Ultra Performance), with the comment "2026-11-14: laptop play was
17 fps, GPU-bound, at 1 = Performance; +40% measured at 2880x1800" and "Rollback: rtx.qualityDLSS = 1".

`deploy/rtx/game.conf:30-33` (desktop, 6800 XT): `rtx.dlssPreset = 2`, `rtx.upscalerType = 4` (XeSS),
`rtx.xess.preset = 1` (Performance), `rtx.enableRayReconstruction = False`. The older
`deploy/rtx/desktop-replay.conf:3-9` (same values) documents why Custom is needed: with `On` the runtime writes
`upscalerType = DLSS` above `rtx.conf` and falls back to TAAU.

Confirmed in the laptop run: `analysis/runtime/laptop-play-20261114/remix.log:5` `DXVK_Remix: remix-main+5a7eec84`,
`:11-15` the option-layer init, and **`:52-63` "Effective RtxOption values (after all config layers and
migrations)"** which prints `rtx.qualityDLSS = 1`, `rtx.dlssPreset = 2`, `rtx.upscalerType = 1`,
`rtx.enableRayReconstruction = True`. That block is the only place the runtime prints these values, and it is
printed **once at startup** — so it proves a *persisted* value, never a live change. The game buffer is
`2880x1800` (`remix.log:259-274`).
Caveat: the deployed runtime is **`remix-main+5a7eec84`**, not the 1.6.1 build named in the proxy comments
(`checks/remix_live.cpp:740`); the option names above are all present in `RTX_OPTIONS_THIS_BUILD.txt:204,313,685,725,880`
(recovered from a different build's `d3d9.dll`, so treat the *name set* as indicative, not the version).

## 10. Gated design for the row

**The row.** New option row "DLSS MODE" in the scrolling body of `menu-preview/panel.cpp`, directly under the
existing preset combo (after `panel.cpp:212`). Values: `Auto`, `Quality`, `Balanced`, `Performance`,
`Ultra Performance`, in that order (Auto first = today's behaviour, `rtx_options.h:569` default). On a machine
without NGX the row is disabled with the reason text "DLSS unavailable on this GPU" — the desktop AMD box shows
XeSS instead: `Quality`, `Balanced`, `Performance`, `Ultra Performance` mapping to `rtx.xess.preset` 3/2/1/0.
Do **not** reuse `render_settings::Mode`: that enum drives the game's own upscale patch
(`render_settings.h:45-54`, `startup_scale()`) and is frozen by `preset_rewrite_test.cpp`. Add a separate
`enum class DlssMode { Unset, Auto, Quality, Balanced, Performance, UltraPerformance }` and a separate key.

**The write path (live).** New pure header `checks/remix_config.h`:
`struct Request { const char* key; char value[8]; unsigned generation; }`, plus
`set_key(key, value)` / `take(pending, out)` with a generation counter so a value repeated twice is still
delivered once. Pure, no Win32 — same shape as `menu_state.h`, testable natively.
- Menu thread (game thread, inside `render_panel`) calls `remix_config::set_key("rtx.qualityDLSS", "3")`.
- Worker polls at the top of `Worker::run`'s loop (before `frame()`, i.e. `checks/remix_live.cpp:1179`):
  `if (remix_config::take(req) && api.SetConfigVariable) { rc = api.SetConfigVariable(req.key, req.value); log(...) }`.
  Never call the API from the menu thread: `api` is owned by the worker (`remix_live.cpp:476-479`, `:17-24`),
  `RtxOptionImpl` takes its own mutex but layer/UI state is not documented as thread-safe from an arbitrary
  thread, and the fake runtime would be called from a thread it never saw.
- Startup seeding: the persisted key is read before the worker starts and pushed through the same queue, so
  there is exactly one code path.
- Precondition guard: the same call also sets `rtx.dlssPreset = 2` once (idempotent) if the effective value is not
  Custom — otherwise a user with the default `On` would see the row do nothing (§6).
- Log line (our own, since the runtime logs nothing on a config write): `remix: config %s = %s -> rc=%d`.

**The persisted key.** `NIER_ENV.ini` beside the proxy: `NIER_REMIX_DLSS_PROFILE=3` (or `quality`). Reasons: the
parser already exists and is tested (`checks/env_file.h`), the file is read at proxy init on both platforms
(`checks/d3d11_scale_setter.cpp:430-455`), an environment variable set by hand still wins, and the frozen
`NIER_RENDER.ini` rewriter is left alone. The menu's Save button then writes two things: the existing
`Preset` (unchanged) and this new line. The write itself is a small pure "set one NIER_* line" function,
mirroring `preset_rewrite.h`'s rules (byte-exact, duplicates in other sections ignored, 64 KiB cap) — gated
separately, `checks/test_env_file_write.py`, before it is wired into Save.
(If the team would rather keep one file, the same function can target `[Rendering] Dlss`; it costs a second
rewriter and a second byte-exact gate. `NIER_ENV.ini` is the cheaper of the two.)

**The gate on the fake runtime.** Extend `checks/test_remix_live.py` (it already runs the live proxy against
`checks/remix_live_fake_runtime.cpp` and reads `fake-remix.log`):
1. Fake runtime: implement `api->SetConfigVariable` (`remix_live_fake_runtime.cpp:371-401` default-constructs the
   interface; add the member next to `api->Present`), logging `SetConfigVariable key=%s value=%s` via the
   existing `note()` (`:20-26`), returning `GENERAL_FAILURE` for a key not in a small known set.
2. Scenario A (`off`): `NIER_REMIX_DLSS_PROFILE` unset → **no** `SetConfigVariable` line in `fake-remix.log`
   (today's behaviour, byte-identical to the current expectation at `test_remix_live.py:96-106`).
3. Scenario B: `NIER_REMIX_DLSS_PROFILE=3` → exactly one `SetConfigVariable key=rtx.qualityDLSS value=3` line,
   and our log line `remix: config rtx.qualityDLSS = 3 -> rc=0`. The gate asserts both strings plus the existing
   frame/lifecycle assertions.
4. Scenario C: a value the fake rejects → `rc=4` (`REMIXAPI_ERROR_CODE_GENERAL_FAILURE`) and
   `remix: config ... rc=` non-zero, so a silent failure cannot look like success.
5. Menu gate: `checks/test_menu_overlay.py` gains one scenario that opens the panel, clicks the new row
   (`Geometry` needs a second rect, `panel.h:15-20`) and asserts `NIER_ENV.ini` gained
   `NIER_REMIX_DLSS_PROFILE=3` while `NIER_RENDER.ini`'s `[Rendering] Preset` stayed byte-identical.

**The mutation that must turn each gate red.**
- Pure queue gate: make `set_key` not bump `generation` (a repeated value is dropped) → the "same value twice
  must be delivered twice" case fails.
- Fake-runtime gate: change the worker's call to `remix_config::set_key("rtx.qualityDlss", …)` (wrong case in the
  key) → the `key=rtx.qualityDLSS` assert fails; or comment out the `api.SetConfigVariable` call → the line is
  missing.
- Menu gate: change the row to call `render_menu::select` only (no `remix_config::set_key`) → no
  `NIER_ENV.ini` change; or write the wrong value (Performance's `1` for the Quality row) → the expected line
  fails.
- Persistence gate: write the key into a comment line → the byte-exact expectation fails.

**The laptop check.** Which log line shows the new render size: **none does.** The runtime prints the DLSS input
size only in its own menu text (`rtx_user_menu.cpp:430`), which we cannot see through Remix's hidden window, and
nothing in `rtx_dlss.cpp` logs sizes. So the laptop check is:
1. Next launch's `remix.log` "Effective RtxOption values" block must show the persisted value
   (`rtx.qualityDLSS = 3`) — proves persistence, not liveness.
2. Liveness: our own `remix: config rtx.qualityDLSS = 3 -> rc=0` line, plus `remix: %.1f fps over the last %llu
   frames` (`remix_live.cpp:1218-1222`) changing in the expected direction. The measured anchors are
   `deploy/rtx/laptop-game.conf:8-9`: 17 fps at Performance, +40 % at Ultra Performance, at 2880x1800.
3. Optional, if the exact pixel size is wanted in a log: add one line in our proxy that recomputes the expected
   size from the same factors and logs `remix: qualityDLSS=3 expects 1920x1200 at 2880x1800` — clearly labelled
   as an expectation, and turned into a fact only if a future runtime patch logs the NGX answer.

## Open questions

1. **Exact NGX input sizes per profile.** Not in source; `queryOptimalSettings` is opaque
   (`rtx_dlss.cpp:166-172`). Determine by: a one-off build of the full tree with a log line in
   `DxvkDLSS::setSetting` after `optimalSettings`, run on the laptop; or NVSDK docs. Until then the P1 gate must
   not assert pixel sizes.
2. **Does a live `qualityDLSS` change actually re-create the feature in the deployed runtime
   (`remix-main+5a7eec84`)?** Source in hand says yes (`rtx_dlss.cpp:145-176`, `:208-220`), but the deployed
   binary is not this source. Determine by: watching fps across a live change on the laptop with Ray
   Reconstruction on and off.
3. **Ray Reconstruction's own profile vs `qualityDLSS`.** `enableRayReconstruction` selects
   `getCurrentProfile()` from the RR pass (`rtx_user_menu.cpp:421`); both passes are fed `qualityDLSS`
   (`:415-427`) but the RR profile resolution is in `rtx_ray_reconstruction.cpp:384-417` and the *reported*
   profile there is never logged. Determine by: an RR-only log patch, or a look at the Remix menu on Windows.
4. **Whether a non-numeric value logs anything.** `rtx_option.cpp:412-414` silently keeps the old value and
   `SetConfigVariable` still returns `SUCCESS`. UNVERIFIED whether `Config::getOption<int>` warns. Determine by:
   fake-free test on the real runtime with `value=x` and a grep of the log; assume silent when designing the gate.
5. **Does the user layer's unsaved state interfere with the Remix UI's "Save Settings"?** A `SetConfigVariable`
   write marks the user layer dirty (`rtx_option.cpp:465`), so the next Remix UI session may show "unsaved
   changes" and offer to save `user.conf`. Not investigated. Determine by: opening the Remix menu after a live
   change on the laptop.
6. **The desktop AMD path.** `RtxOptions::updateUpscalerFromXeSSPreset` is declared
   ([full] `rtx_options.h:1406`) with no definition and no caller anywhere in the tree; XeSS preset changes are
   consumed directly in `rtx_xess.cpp:690-752`. UNVERIFIED whether the declaration is dead. Consequence: on the
   AMD desktop the row maps straight onto `rtx.xess.preset` and needs no coupling code.
7. **Which runtime the laptop actually runs vs the tree.** `remix.log:5` says `remix-main+5a7eec84`; the tree
   `analysis/runtime/src/dxvk-remix` is that checkout's source only by assumption. `RTX_OPTIONS_THIS_BUILD.txt`
   was recovered from a Portal RTX `d3d9.dll`, a third build. Determine by: a hash/version map of every runtime
   folder we ship (`deploy/`, `runtime/`).

## Recommended steps for the plan

1. **Precondition, before any UI work.** Add the `rtx.dlssPreset = 2` guard to the live path: when the menu
   sends a DLSS mode, the same queued request must first ensure `rtx.dlssPreset` is Custom. Check: fake-runtime
   gate sees `SetConfigVariable key=rtx.dlssPreset value=2` before the first `qualityDLSS` line, and only once
   across frames. Gate asserts the order; mutation = send `qualityDLSS` first → red.
2. **`checks/remix_config.h` + `checks/test_remix_config.py`** (frozen, pure, ASan/UBSan + MinGW x64, two TUs —
   copy the shape of `checks/test_menu_state.py`). Asserts: empty queue delivers nothing; one `set_key` delivers
   exactly once; the same key+value twice delivers twice; a newer value supersedes an undelivered one; no
   allocation, no Win32. Mutation: remove the generation bump → the "twice" case fails.
3. **`NIER_ENV.ini` writer**: `checks/env_file_write.h` (pure) + `checks/test_env_file_write.py` (frozen,
   byte-exact cases mirroring `preset_rewrite_test.cpp`): set an existing `NIER_*` line in place, append a new line
   with CRLF, refuse malformed input, 64 KiB cap, leave comments and other keys untouched. Mutation: rewrite the
   whole file with sorted keys → the comment-preservation case fails.
4. **Fake runtime**: implement `api->SetConfigVariable` in `checks/remix_live_fake_runtime.cpp` (log
   `SetConfigVariable key=%s value=%s`, known-key table, reject others with `GENERAL_FAILURE`) and make
   `checks/test_remix_live.py` fail today for the right reason — i.e. add the three scenarios of §10 first and
   watch them go red with `UNIMPLEMENTED`/missing lines.
5. **Worker hand-off**: poll `remix_config::take()` at the top of `Worker::run`'s loop (`checks/remix_live.cpp:1175-1185`),
   call `api.SetConfigVariable`, log `remix: config %s = %s -> rc=%d`. Seed the queue from the environment
   (`NIER_REMIX_DLSS_PROFILE`, applied to the process env by `apply_env_file()`,
   `checks/d3d11_scale_setter.cpp:430-455`) before the worker starts. Gate: scenarios B and C of §10.
6. **Menu row**: in `menu-preview/panel.cpp` after line 212, one combo built the same way as the existing one
   (`panel.cpp:199-206`), values and labels from `dxvk_imgui.cpp:313-319`. The C API has **no** "is DLSS
   supported" query (`remix_c.h` has none; `supportsDLSS()` is internal, `rtx_dlss.cpp:94-96`), so the proxy
   cannot know: choose the row by GPU vendor from the game's adapter description (NVIDIA → `rtx.qualityDLSS`,
   otherwise → `rtx.xess.preset`), and accept that an NVIDIA machine without working NGX shows a row that does
   nothing — the runtime then logs `NVIDIA DLSS not supported` (`rtx_ngx_wrapper.cpp:327`). Publish its
   rect in `menu_preview::Geometry` (`panel.h:15-20`). Gate: `checks/test_menu_overlay.py` new scenario clicks it
   and asserts both the `NIER_ENV.ini` line and unchanged `[Rendering] Preset` bytes; the existing pixel probes
   (`test_menu_overlay.py:99-115`) must stay green — mutation = write the value into `Preset` instead → the
   INI-bytes assert fails.
7. **Save wiring**: the Save button (`panel.cpp:236-237`) writes both files through
   `menu_settings_io::save()` + `env_file_write`, and `complete_save` keeps its "re-observe after write"
   contract (`menu_state.h:44-52`). Gate: extend the `test_menu_overlay.py` save scenario to assert both files.
8. **Laptop run, one session**: log `rtx.qualityDLSS` in the next launch's "Effective RtxOption values" block
   (`remix.log:52-63`), the live `remix: config …` line, and `remix: %.1f fps` (`remix_live.cpp:1218`) for each
   of the four modes at 2880x1800. Record the fps table next to P1. No pixel-size claim until Open Question 1 is
   answered.
9. **Desktop (AMD) run**: the same row against `rtx.xess.preset`, one conf, one session at 3440x1440; check the
   `remix: config rtx.xess.preset = <n>` line and the fps table. This is also the first honest measurement behind
   D1.
10. **Update `analysis/IN_GAME_MENU.md`** (it still says "Nothing changes live", line 8) and add the row to
    `checks/gates.py`'s dependency map if a new header is introduced (`gates.py:31-42,52-68`).
