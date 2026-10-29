# Minecraft mod: digests of two reference docs

Produced by `local-helper` (laptop `pair/qwen3.6-35b-a3b`, run 5644c269) on 2026-10-29 from
`minecraft-RENDERING_DIAGNOSTICS.md` and `minecraft-TUNING.md` only, then verified by the lead: all 54 cited
`rtxremix.*` names were checked against the sources (one namespace error, `chunk.floodSliceNs`, corrected to
`light.floodSliceNs`), and all 12 quotations were checked verbatim (two are paraphrases: one drops a markdown link,
one elides with an ellipsis). Nothing else in this file was rewritten by the lead.

## Failure signatures we do not detect

- World reconfiguration (EnterReconfigurationS2CPacket) fires JOIN without closing the connection; "The null-world frame path hides retained terrain and discards the prepared particle payload" — World Transitions
- Terrain recapture clear alone: "A clear alone leaves an empty path-traced world until vanilla happens to rebuild"; reload alone: "can omit terrain the prior scene held" — Terrain Recapture
- Material update API returns success but "The runtime can reject a type or sprite-sheet-layout change with a warning" — Material Updates And Surface Capacity
- Per-frame drawInstance submissions "can return success while the runtime drops them for lack of a free surface slot"; "`Cloud.Draws` counts calls made, not surfaces accepted, and `latest.log` need not contain an error" — Material Updates And Surface Capacity

## Performance and stability knobs

### Terrain Capture
- `rtxremix.chunk.sectionBuilders`: Concurrent vanilla section builds; "Vanilla allocates one buffer per logical CPU" — SectionBuildConcurrency
- `rtxremix.blockDataQueue.maxPendingItems`: Section captures queued for the render thread — BlockDataQueue
- `rtxremix.blockDataQueue.maxPendingBytes`: Bytes of queued captures — BlockDataQueue
- `rtxremix.blockDataQueue.maxDrainItems`: Captures drained per render-thread pass — BlockDataQueue
- `rtxremix.blockDataQueue.maxDrainBytes`: Bytes drained per pass — BlockDataQueue
- `rtxremix.blockDataQueue.publishWaitBudgetNs`: Initial worker wait budget before attempting FIFO eviction — BlockDataQueue
- `rtxremix.chunk.localBatchPacing`: Pace integrated server chunk delivery while capture is on, spreading bursts across frames — LocalChunkBatchPacing
- `rtxremix.chunk.localBatchBudgetMs`: Measured render-thread chunk-apply time the paced batch may fill per tick — LocalChunkBatchPacing
- `rtxremix.chunk.localBacklogBudgetMs`: Ceiling the per-tick budget rises to while a backlog is waiting — LocalChunkBatchPacing
- `rtxremix.chunk.localBatchBacklogDivisor`: Share of the backlog added to the per-tick budget — LocalChunkBatchPacing
- `rtxremix.chunk.localBatchMaxChunks`: Cap on chunks in one paced batch — LocalChunkBatchPacing
- `rtxremix.chunk.localBacklogMaxChunks`: Ceiling that cap rises to while a backlog is waiting — LocalChunkBatchPacing
- `rtxremix.chunk.localUnloadPacing`: Pace chunk unload packets alongside chunk data — LocalChunkBatchPacing
- `rtxremix.chunk.localUnloadBudgetMs`: Measured render-thread unload time the paced unloads may fill per tick — LocalChunkBatchPacing
- `rtxremix.chunk.neighbourReflagFilter`: Drop vanilla's chunk-load and light-data neighbour rebuild flags — NeighbourReflagFilter
- `rtxremix.light.vanillaSnapshot`: Clone section map every pass (true) or publish live map (false) — ClientLightSnapshotPolicy
- `rtxremix.light.vanillaSurfaceScan`: Start sky-light surface walk at top of chunk (true) or seed at WORLD_SURFACE (false) — SkyLightSurfaceScanPolicy
- `rtxremix.vanillaVisibilityWalk`: Leave visibility walk to vanilla with RTX on (true) — ChunkRenderingDataPreparerMixin
- `rtxremix.logVisibleSet`: Log size and position hash of every full visibility walk's result when it changes — ChunkRenderingDataPreparerMixin
- `rtxremix.joinHold`: Keep terrain-download screen up until frame times settle after a world join — JoinBurstHold

### Terrain Assembly And Publication
- `rtxremix.chunk.meshBuildThreads`: Threads in the column merge executor — ChunkManager
- `rtxremix.chunk.maxPendingBuilds`: Merges outstanding at once — ChunkManager
- `rtxremix.chunk.maxPendingMeshBytes`: Bytes of merged but not yet installed geometry — ChunkManager
- `rtxremix.chunk.installBudgetNs`: Render-thread time per frame spent installing columns — ChunkManager
- `rtxremix.chunk.maxInstalledColumnsPerFrame`: Columns published per frame — ChunkManager
- `rtxremix.chunk.columnStreamSettleFrames`: Frames a column waits for its neighbours before publishing — ChunkManager
- `rtxremix.chunk.columnStreamMaxWaitFrames`: Hard cap on neighbour-wait frames — ChunkManager
- `rtxremix.chunk.maxSectionRemovalsPerFrame`: Deferred section removals per frame — ChunkManager
- `rtxremix.chunk.maxSectionRemovalValidationsPerFrame`: Removal checks per frame — ChunkManager
- `rtxremix.chunk.maintenanceBudgetNs`: Render-thread time per frame for terrain maintenance — ChunkManager
- `rtxremix.chunk.maxColumnUnloadsPerFrame`: Column unloads processed per frame — ChunkManager
- `rtxremix.chunk.meshPageBytes`: Byte cap on one terrain mesh page — BlockMeshBuilder
- `rtxremix.chunk.meshRetireBudgetNs`: Render-thread time per frame spent retiring replaced pages — TerrainAssetRetirementQueue
- `rtxremix.chunk.meshRetireSoftCount`: Queued retirements before backpressure starts — TerrainAssetRetirementQueue
- `rtxremix.chunk.meshRetireHardCount`: Queued retirements that force the queue to drain — TerrainAssetRetirementQueue
- `rtxremix.chunk.meshRetireSoftBytes`: Byte equivalent of the soft count — TerrainAssetRetirementQueue
- `rtxremix.chunk.meshRetireHardBytes`: Byte equivalent of the hard count — TerrainAssetRetirementQueue

### Block Lights
- `rtxremix.chunk.maxLightOpsPerFrame`: Light create, update, and destroy calls per frame — ChunkManager
- `rtxremix.chunk.lightBudgetNs`: Render-thread time per frame for light calls — ChunkManager
- `rtxremix.chunk.maxPendingLightOps`: Queued light work before backpressure — ChunkManager
- `rtxremix.light.floodSliceNs`: Render-thread time per frame a connectivity rebuild may take — TerrainState

### Entities, Textures, And Particles
- `rtxremix.entity.meshCache.maxEntries`: Pooled entity meshes kept for reuse — RemixEntitySubmitter
- `rtxremix.dynamicTextureCache.maxEntries`: Entries in the dynamic texture cache for skins and glyph pages — DynamicTextureCache
- `rtxremix.directBufferPool.maxBytes`: Bytes of idle direct buffers kept pooled; 0 disables pooling — DirectBufferPool
- `rtxremix.waterRapids.spawnBudgetPerTick`: Foam and mist particles spawned per tick near fast water; 0 turns the effect off — WaterRapidParticleSpawner
- `rtxremix.particles.fastAirCollision`: Fast path through particle collision when every swept cell is air — ParticleStateMixin
- `rtxremix.particles.fastAirCollisionMaxBlocks`: Largest sweep that the fast path handles — ParticleStateMixin

### Profiling And Diagnostics
- `rtxremix.benchmark.jfrPath`: Names the JFR dump the benchmark flushes before writing its result; non-empty also turns Java phase events on — ProfileScope, BenchmarkController
- `rtxremix.profile.javaPhases`: Enable Java phase events in JFR — ProfileScope
- `rtxremix.profile.tracyJavaZones`: Mirror the same phases as Tracy zones — ProfileScope
- `rtxremix.profile.tracyJavaMaxDepth`: Nesting depth limit for those Tracy zones; -1 means unlimited — ProfileScope
- `rtxremix.profile.clientTasks`: Enable per-client-task JFR events — ProfileScope
- `rtxremix.profile.clientTaskSlowThresholdNs`: A client task slower than this gets its own JFR event — ProfileScope
- `rtxremix.debug.entityTypeSummary`: Enable a periodic per-entity-type capture summary in the log — RemixEntityPass

### Gradle Pass-Throughs
- `-Parch=win64` or `-Parch=arm64`: Build and package one architecture instead of both
- `-PrtxPreset=<low|medium|high|ultra>`: Selects Remix's graphics tier for that session only
- `-PmcQuickPlayServer=<host:port>`: Join a server on launch
- `-PbenchmarkJfrPath=<file.jfr>`: Starts a JFR recording, sets `rtxremix.benchmark.jfrPath`, and turns Java phases on
- `-PbenchmarkTracyJavaMaxDepth=<n>`: Sets `rtxremix.profile.tracyJavaMaxDepth`; only applies when a JFR path is given
- `-PbenchmarkJfrThrowables=true`: Adds exception and error throw events to that recording
- `-PbenchmarkQuickPlayWorld=<name>`: Loads a single-player world on launch

## Measurement practice

- "`Cloud.Draws` counts calls made, not surfaces accepted" — drawInstance success does not prove visible output (Material Updates And Surface Capacity)
- "Look in `rtx-remix/logs/remix-dxvk.log` … for `GPU-resident scene exceeded its fixed surface capacity`. The runtime emits that warning only once per process." (Material Updates And Surface Capacity)
- "`BlockLightIntensityControlsTest` checks distinct control mappings but cannot build the registry-bootstrapped catalog" — unit tests do not cover all failure paths (Block Lights And Resource Reload)
- "Use a Remix debug view to isolate texture coordinates, normals, emission, or mesh identity. A defect already visible in those inputs points toward capture … a clean input with a defect only in the final image points toward shading or denoising." (Separating Capture From Shading)
- "`ProfileScope` is the per-call timing instrument; `TerrainNativeCallStats` keeps the frame tallies clock-free" — avoid adding clock reads inside budgeted loops (Terrain Assembly And Publication)
