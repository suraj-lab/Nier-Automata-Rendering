# GPU headroom: 30-second live capture

GPU: RX 9070 XT, PCI 0000:03:00.0 (identified among three AMD adapters).
Game process: 629278. Read-only sampling, 61 samples at 0.5-second intervals.

- Whole-device GPU busy: mean 49.7%, median 51%, p95 72%, maximum 88%.
- Reported GPU power: mean 99.1 W, maximum 146 W; configured PPT cap 360 W.
- GPU clock: median 2134 MHz, maximum 2560 MHz; clocks varied with demand.
- Temperatures: edge mean 51.4 C/max 54 C; junction mean 55.9 C/max 58 C;
  memory mean 74.9 C/max 76 C.
- VRAM: about 5.48 GiB used of 15.92 GiB exposed.
- Memory-controller busy: mean 17.9%, maximum 32%.

Interpretation: promising margin for a controlled frame-generation test at the
current cap in the sampled workload; no sustained full GPU saturation observed.
Do not translate unused utilization or unused power budget directly into an FPS
prediction. Dynamic clocks, overlapping GPU engines, compositor work and other
processes affect these readings. The two game DRM engine rates must not be added
as GPU wall time. Brief peaks still reduce margin in heavier scenes.

This is not a worst-case benchmark, frame-pacing trace, per-frame GPU-time
measurement, or a frame-generation test. It does not quantify FG latency or
prove stable 120 FPS output. No game, driver, clock, fan, or power setting changed.

Raw samples: samples.csv. Full statistics: summary.json.
