# Remix C API: what our vendored header has vs Remix Plus

* our vendored `analysis/remix-probe/vendor/remix_c.h` — version 0.6.6 (identical to upstream dxvk-remix `main`)
* `analysis/reference/remix-plus-remix_c.h` — Remix Plus fork, version 0.1000.0

## Interface members appended after our build (callable only with the fork runtime)

* `CreateMeshBatched`
* `CreateLightBatched`
* `AddTextureHash`
* `RemoveTextureHash`
* `CreateTexture`
* `DestroyTexture`
* `dxvk_GetTextureHash`
* `dxvk_GetSharedD3D11TextureHandle`
* `RegisterCallbacks`
* `AutoInstancePersistentLights`
* `UpdateLightDefinition`
* `DrawScreenOverlay`
* `SetGameValue`
* `RequestVramCompaction`
* `GetVramStats`
* `RequestTextureVramFree`
* `GetGameValue`

## Functions added by the fork

* `AddTextureHash`
* `AutoInstancePersistentLights`
* `BridgeCallback`
* `CreateLightBatched`
* `CreateMeshBatched`
* `CreateTexture`
* `DestroyTexture`
* `DrawScreenOverlay`
* `GetGameValue`
* `GetVramStats`
* `RegisterCallbacks`
* `RemoveTextureHash`
* `RequestTextureVramFree`
* `RequestVramCompaction`
* `SetGameValue`
* `UpdateLightDefinition`
* `dxvk_GetSharedD3D11TextureHandle`
* `dxvk_GetTextureHash`

## Struct types added by the fork

* `REMIXAPI_STRUCT_TYPE_TEXTURE_INFO`

## Shared surface: 24 functions, 28 struct types

Field-level differences inside the shared structs are the risky part: the fork edits structs in
place (e.g. added fields before existing ones), so a binary layout from one is not safe to use with
the other runtime. Check before mixing.

## Field-level differences in structs we compile against

### `remixapi_StartupInfo`
* fork lacks: `remixapi_Bool combineGuiInFinalColor`

### `remixapi_MaterialInfoOpaqueEXT`
* fork lacks: `remixapi_Bool enableDlssControlMask`
* fork lacks: `float dlssControlMaskIntensity`
* fork lacks: `float dlssControlMaskToneStrength`
* fork lacks: `float dlssControlMaskStructuralStrength`
* fork lacks: `float textureScrollRate`
* fork lacks: `float textureScrollAngle`
* fork lacks: `remixapi_Bool textureScale_hasvalue`
* fork lacks: `remixapi_Float2D textureScale_value`
* fork lacks: `remixapi_Float2D textureOffset`
* fork lacks: `float textureRotation`

### `remixapi_MaterialInfoTranslucentEXT`
* fork lacks: `float textureScrollRate`
* fork lacks: `float textureScrollAngle`
* fork lacks: `remixapi_Bool textureScale_hasvalue`
* fork lacks: `remixapi_Float2D textureScale_value`
* fork lacks: `remixapi_Float2D textureOffset`
* fork lacks: `float textureRotation`

### `remixapi_LightInfo`
* fork adds: `remixapi_Bool isDynamic`
* fork adds: `remixapi_Bool ignoreViewModel`

### `remixapi_Interface`
* fork adds: `PFN_remixapi_CreateMeshBatched CreateMeshBatched`
* fork adds: `PFN_remixapi_CreateLightBatched CreateLightBatched`
* fork adds: `PFN_remixapi_AddTextureHash AddTextureHash`
* fork adds: `PFN_remixapi_RemoveTextureHash RemoveTextureHash`
* fork adds: `PFN_remixapi_CreateTexture CreateTexture`
* fork adds: `PFN_remixapi_DestroyTexture DestroyTexture`
* fork adds: `PFN_remixapi_dxvk_GetTextureHash dxvk_GetTextureHash`
* fork adds: `PFN_remixapi_dxvk_GetSharedD3D11TextureHandle dxvk_GetSharedD3D11TextureHandle`
* fork adds: `remixapi_UIState (REMIXAPI_PTR *GetUIState)(void)`
* fork adds: `remixapi_ErrorCode (REMIXAPI_PTR *SetUIState)(remixapi_UIState state)`
* fork adds: `PFN_remixapi_RegisterCallbacks RegisterCallbacks`
* fork adds: `PFN_remixapi_AutoInstancePersistentLights AutoInstancePersistentLights`
* fork adds: `PFN_remixapi_UpdateLightDefinition UpdateLightDefinition`
* fork adds: `PFN_remixapi_DrawScreenOverlay DrawScreenOverlay`
* fork adds: `PFN_remixapi_SetGameValue SetGameValue`
* fork adds: `PFN_remixapi_RequestVramCompaction RequestVramCompaction`
* fork adds: `PFN_remixapi_GetVramStats GetVramStats`
* fork adds: `PFN_remixapi_RequestTextureVramFree RequestTextureVramFree`
* fork adds: `PFN_remixapi_GetGameValue GetGameValue`
