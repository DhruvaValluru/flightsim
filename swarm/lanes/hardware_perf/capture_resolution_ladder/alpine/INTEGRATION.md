# Alpine capture-resolution ladder: integration

Lane `hardware_perf.capture_resolution_ladder.alpine`. Visual-only. **Nothing
here is measured.** Everything below was written and source-tested on the Mac;
frame time, VRAM, temperature and every statement about the rendered frame are
UNMEASURED until the commands in "Measure on the Windows laptop" have run there.

## The idea

The laptop loses its D3D11 device when a single frame is too heavy. So the
ladder never makes a single frame heavier than about today's 1280x800: it
raises what a still delivers by rendering more small passes and combining
them on the CPU.

| tier | delivered | passes | one pass renders | samples/pixel | render targets (ESTIMATE) |
|---|---|---|---|---|---|
| 0 | 1280x800 | 1 | 1280x800 | 1 | 71 MB |
| 1 | 1280x800 | 4 sub-pixel shifted | 1280x800 | 4 | 71 MB |
| 2 | 2560x1600 | 2x2 tiles | 1344x864 (32 px gutter) | 1 | 81 MB |
| 3 | 2560x1600 | 2x2 tiles x 4 shifts | 1344x864 | 4 | 81 MB |

The render-target figure is 73 bytes per pixel of one pass (the stress_ladder
lane's estimate) and excludes the tile pool, meshes and shaders. If tier 0
itself fails, `tier0_step_down` in the plan renders 1024x640 or 960x600 and the
resolver Lanczos-enlarges it to 1280x800.

## Files in this lane

- `bake_capture_ladder.py`: Mac generator. Writes the two files below.
- `alpine_capture_ladder.json`: per tier and per pass, the pixel window of the
  full frame, the clip-space scale and offset for the off-centre projection,
  the paste position, the weight and the warm-up frame count.
- `blue_noise_64.r8`: 64x64 R8 void-and-cluster tile; the resolver dithers the
  averaged frame with it so the sky gradient does not band at 8 bits.
- `resolve_capture.py`: CPU resolver (numpy + Pillow). Passes in, frame out,
  plus `<out>_display.png` (1536x960) and `<out>.resolve.json`.
- `measure_capture_gate.py`: the gate. Reads recorded counters, log and frames.

## Proposed changes to shared files (not made by this lane)

### 1. `ue/Plugins/FlightSimBridge/.../FlightSimVisualScene.cpp`: multi-pass beauty capture

When `FLIGHTSIM_CAPTURE_LADDER_TIER` is 1, 2 or 3 and the scenario is alpine,
read `alpine_capture_ladder.json` and, for each pass of that tier, in order:

```cpp
// Base = the beauty capture's normal projection for the FULL delivered frame
// (same FOV as today, aspect 16:10). UE matrices are row-vector: clip = v * M,
// and for a perspective matrix clip.w = view z (M[2][3] == 1).
FMatrix P = Base;
P.M[0][0] = Sx * Base.M[0][0];   P.M[2][0] = Sx * Base.M[2][0] + Ox;
P.M[1][1] = Sy * Base.M[1][1];   P.M[2][1] = Sy * Base.M[2][1] + Oy;
Beauty->bUseCustomProjectionMatrix = true;
Beauty->CustomProjectionMatrix = P;       // Sx,Sy = ndc_scale; Ox,Oy = ndc_offset
// render target resized ONCE per tier to pass_render_px, never per pass
// tick warmup_frames frames with the sim paused, then capture and write
// <FLIGHTSIM_CAPTURE_LADDER_DIR>/<pass.file>
```

Rules the passes depend on:

- The simulation, clouds and weather time are paused for the whole tier.
- Exposure is the fixed manual or physical value (`ApplyManualExposure` /
  `ApplyPhysicalExposure`); auto-exposure would differ per tile.
- For tiers 2 and 3, effects that depend on the position in the frame are off
  in the tile passes: bloom, vignette, lens drops (`ApplyLensDropsToBeauty`),
  lens flare. The 32 px gutter covers ambient occlusion and TAA edge
  behaviour only. If bloom is wanted, apply it to the resolved frame later.
- Passes run one at a time (`gpu_render_jobs` stays 1); the label capture is
  not repeated per pass.
- Tier 0 does not go through this path: it is today's capture, unchanged.

The matrix lines are written from the UE convention and are not compiled here.
`tests/...::test_ndc_window_maps_the_pass_window_to_clip_space` checks the
scale and offset numbers; the sign of the y offset on the D3D11 capture must be
confirmed by the seam check on the first tier 2 frame (a flipped sign shows as
a seam excess far above 1 level).

### 2. Cesium / Google tiles camera for tile passes

Google tiles stay on in every tier. For tiers 2 and 3 the tile selection must
see the delivered pixel density or the larger frame holds no more ground
detail. Per tile pass, give the Cesium camera manager a camera aimed at the
tile's centre with the tile's angular size and a viewport of `pass_render_px`,
so only the quarter being rendered is refined and the tile cache stays near
the 1280 case. Registering the whole 2560x1600 frame at once would refine all
four quarters together and is expected to overrun the 491 MB pool (ESTIMATE);
the vram_budgeting lane's cap still applies.

### 3. `scripts/run_test_scenarios.py`: drive the tier

`--capture-ladder-tier N` (alpine only): sets the two environment variables,
adds `-csvprofile` to the UE launch, and after UE exits runs
`resolve_capture.py --tier N --passes <dir> --out runs\test_scenarios\11_ladder_tN.png`.
A missing pass makes the resolver refuse; the run must then fail by name
rather than deliver a partial frame.

### 4. `core/render/hardware_budget.py`: accept the measured patch

`measure_capture_gate.py --write-measured` writes
`{"measured": true, "max_capture_width", "max_pass_render_px", "capture_ladder_tier", "measurements"}`
only when the tier passed and frame time, GPU memory and temperature were all
recorded. Proposed: `_integrated_budget` overlays
`docs/hardware/capture_ladder_measured.json` when it exists. The lane never
writes that file itself and no Mac run can produce it.

## Measure on the Windows laptop (UNMEASURED until run)

Needs changes 1 to 3. Boxes are in pixels of the 1280x800 tier 0 frame: pick the
ridge box on the summit silhouette against sky, the ground box on rock or
textured valley floor, both clear of the aircraft.

```bat
rem idle counters, 20 s
typeperf "\GPU Adapter Memory(*)\Shared Usage" "\GPU Adapter Memory(*)\Dedicated Usage" "\Thermal Zone Information(*)\Temperature" -si 1 -sc 20 -f CSV -o runs\ladder_idle.csv -y

rem reference: tier 0, today's frame
python scripts\run_test_scenarios.py --still --only 11
copy runs\test_scenarios\11_*.png runs\alpine_ladder_t0.png

rem candidate: tier 1 (repeat with 2, then 3; stop at the first tier that fails)
start /b typeperf "\GPU Adapter Memory(*)\Shared Usage" "\GPU Adapter Memory(*)\Dedicated Usage" "\Thermal Zone Information(*)\Temperature" -si 1 -f CSV -o runs\ladder_t1.csv -y
python scripts\run_test_scenarios.py --still --only 11 --capture-ladder-tier 1
taskkill /im typeperf.exe /f

python swarm\lanes\hardware_perf\capture_resolution_ladder\alpine\measure_capture_gate.py --tier 1 --reference runs\alpine_ladder_t0.png --candidate runs\test_scenarios\11_ladder_t1.png --resolve-report runs\test_scenarios\11_ladder_t1.resolve.json --ridge-box <x0,y0,x1,y1> --ground-box <x0,y0,x1,y1> --typeperf runs\ladder_t1.csv --idle runs\ladder_idle.csv --log <UE log of the run> --frames <CsvProfiler csv of the run> --write-measured docs\hardware\capture_ladder_measured.json
```

Exit code 0 and `"passed": true` means, for that tier on that run:

| check | threshold | why |
|---|---|---|
| device-lost lines in the log | 0 | the 12 crashes on scene 9 |
| max frame time | <= 1000 ms | half of Windows' 2 s GPU watchdog (confirm no `TdrDelay` override) |
| peak GPU memory above idle | <= 491 MB | the unmeasured start pool |
| peak thermal-zone temperature | <= 90 C | ESTIMATE; some laptops expose no useful zone, then the tier stays unmeasured |
| seam excess (tiers 2, 3) | <= 1.0 level | tiles must not show |
| sample spread (tiers 1, 3) | <= 1.0 level | the scene must not move between sub-pixel passes |
| alias ratio, ridge box | <= 0.75 | fewer stair steps than the reference at the same 1280x800 size |
| ground sharpness ratio (tiers 2, 3) | >= 1.0 | the 2560 frame holds ground detail the enlarged 1280 frame does not |

One passing run is one measurement, not "sustained": the stress_ladder lane
decides how many repeats count.

## Known limits

- FrameTime in the CsvProfiler file is whole-frame time, a conservative
  stand-in for GPU time; a hitch from tile loading can fail the 1000 ms check
  without any GPU risk. Re-run before lowering a tier on that alone.
- The alias metric (diagonal share of 2x2 Haar detail) also responds to
  diagonal texture; keep the ridge box on the silhouette.
- Tier 1 has no sharpness floor on purpose: supersampling removes aliasing
  that a Laplacian counts as detail (the synthetic test shows a ratio of 0.06
  on sub-pixel texture with a correct resolve).
- Passes are 8-bit PNG. Four averaged samples carry about 10 bits, which the
  dither preserves; single-sample tiers gain nothing from the dither.
- Rain streaks, lens drops and anything animated per frame are not handled by
  multi-pass capture. Alpine is a clear-air scenario; do not reuse this plan
  for the storm scenario without pausing those effects.
- Wall time grows with the pass count: tier 3 is 16 passes and about 128 GPU
  frames with warm-up (ESTIMATE), which is also the longest thermal soak.

## Mac checks

`.venv/bin/python -m pytest tests/test_swarm_hardware_perf_capture_resolution_ladder_alpine.py`
(15 tests: plan arithmetic, committed files against the generator, resolver and
gate on a synthetic scene, parsers, decision table). Not a render result.
