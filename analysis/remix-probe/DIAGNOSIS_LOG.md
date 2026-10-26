# Diagnosis log — wrong calls and what settled them

Written 2026-10-26 after the material/lighting investigation. Each entry is a hypothesis that was wrong, what
actually disproved it, what it cost, and the cheap check that would have avoided it. Kept because the cost of
these was real GPU time on the user's machines, and because the same mistakes are easy to repeat.

## Wrong hypotheses, in the order they were made

| # | Hypothesis | Disproved by | Cost | Check that would have settled it immediately |
|---|---|---|---|---|
| 1 | The albedo textures fail to load in Remix, so the scene is black | Remix's own log lists every `scene_textures/tex_<id>.dds` as a loaded replacement texture (only a missing-mipmap warning) | 2 runs | `findstr texture` over `stderr.txt` — the log was already being parsed by the runner |
| 2 | The desktop's Vulkan/Proton setup was at fault | The laptop reproduced the identical black frame | 3 runs | Run the same fixture on the other host before theorising about a host |
| 3 | The runtime ignores `CameraInfoParameterizedEXT` | A previous desktop full-scene render had visible geometry with the same camera path | 2 runs | Look at the images already on disk before designing an experiment |
| 4 | Vertex normals point inward (the v1 bug), so N·L ≈ 0 | Negating every normal changed nothing; normals are unit length, 48.5% face the sun | 1 run + 1 offline check | Compute normal length and N·sun distribution offline in one script |
| 5 | The albedo selection picks the wrong UV set or texture | Sampling our albedo at our own UVs gave mean rgb (0.44, 0.40, 0.36) over 40 draws | 0 (offline) | Same — this one was done right and cost nothing |
| 6 | Exposure/lighting was mis-scaled (radiance 30 → 12000 → 3) | Radiance sweeps moved brightness but never produced solid surfaces; the surfaces were **transparent**, not dark | 4 runs | The invariance of the image to albedo/normal/alpha changes should have suggested "not drawn" sooner |
| 7 | A null material is a lighting reference, so materials must be broken | `nullptr` material renders Remix's unlit default; it is not comparable | 1 run | Research says materials do not affect fallback lighting — check the source first |
| 8 | A dome light with uniform radiance gives ambient fill | `LightInfoDomeEXT` with a null `colorTexture` produces no light at all: the texture index stays invalid so radiance is never uploaded | 2 runs | The researcher's source reading, one agent call |

**The actual cause** was one integer: `blendType_value`. `0` renders fully transparent, `1` blends by the
albedo texture's alpha (NieR's maps carry cutout alpha, so almost everything vanishes), `2` is opaque. It was
found in a single run by bisecting the enum — three materials differing only in that field, assigned
round-robin across surfaces, so one image reports the answer.

## Process mistakes

- **Killed my own shell.** `pkill -f desktop-prefix` matched the bash process running it (its command line
  contained the string). Exit 137. Use `pgrep -x <name>` or a bracket pattern, and never `pkill -f` a pattern
  that also appears in the command being run.
- **Left probe windows on the user's workspace.** `kill $pid` only kills the Proton wrapper; the wine process
  survives. Now: `setsid` the launch, `kill -- -$pid`, then verify with `hyprctl clients -j`. The user then
  asked for a separate workspace explicitly, which should have been the default — a render window belongs on
  its own workspace, moved silently, never over the session.
- **Told the user a model was spilling VRAM** at 17.74 GB on a "16 GB card". There are three adapters, both
  discrete ones 16 GB, and LM Studio uses ROCm across both. I never checked `lspci` or the VRAM sysfs files.
- **Blocked on GPU contention that did not exist**, and unloaded the user's model unnecessarily.
- **Dumped a minified JS bundle and a receipt JSON into context** while grepping, twice. Both were avoidable:
  the receipt JSON embeds the probe's entire stdout, so never `grep` inside it.

## Rules for the next investigation on this project

1. **Read the artefact's own log before forming a hypothesis.** Remix logs option parsing, texture loads and
   shader state; the probe logs its effective modes. Both were already on disk.
2. **Prefer checks that need no GPU, in this order:** decode data offline (textures, normals, UVs), grep logs,
   read the runtime's source, then run the smallest possible frame. Most of the entries above were settled
   without a render once the right question was asked.
3. **One variable per run, and make the run self-documenting.** The probe now prints `Scene: modes ...` so a
   receipt proves which switches were active. Any new switch must be printed too.
4. **When a change has no effect, suspect the plumbing before the theory.** Before concluding "Remix ignores
   X", prove the value reached the process.
5. **Bisect enums inside one frame.** Assign variants round-robin to surfaces; the image reports all of them at
   once. This is what finally worked, and it should have been the first move on `blendType`.
6. **"Identical statistics" is a signal, not a coincidence.** Three configs giving the same mean to 4 decimal
   places meant the changed variable was not in the path at all.
7. A null material, a skipped draw or a fallback path is **not** a control condition. Establish what the
   baseline actually renders before using it as a reference.
