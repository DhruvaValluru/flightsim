# validation.pixel_metrics.alpine: one command for every alpine pixel gate

Visual-only validation tooling. CPU only: it reads PNGs that already exist; it
never starts Unreal, never touches the GPU and changes no render setting.

**Status: UNMEASURED.** Nothing here has run on the Windows laptop. No alpine
frame has been through these metrics, and every threshold in
`alpine_metrics.py` is an uncalibrated starting value. The Mac ran only the
code-level tests in `tests/test_swarm_validation_pixel_metrics_alpine.py`.

## Files

| file | role |
| --- | --- |
| `build_gate_manifest.py` | Mac generator. Reads each `swarm/lanes/*/*/alpine/{measure_*,*gate*}.py` as text (AST; never imports or runs it) and writes the three outputs below |
| `alpine_gates.json` | the alpine gate scripts found on 2026-11-12 (11 at last bake; a snapshot; see change 3 below): script, sha256, required/optional args |
| `shot.template.json` | the one file the operator fills in |
| `calib/*.png`, `calib/expected.json` | five 160x96 synthetic frames and the metric values baked for them |
| `alpine_metrics.py` | frame-health metrics (blank frame, blown snow, crushed blacks, snow tint, SSIM, detail, flicker) |
| `run_alpine_gates.py` | the Windows runner |

## The Windows command (UNMEASURED until it has run there)

Close Unreal first: the runner and a UE render process should not share the
laptop's RAM. Gates run one at a time.

```
copy swarm\lanes\validation\pixel_metrics\alpine\shot.template.json runs\alpine_gates\shot.json
rem fill every null in runs\alpine_gates\shot.json (paths, boxes, distances of the shot)
python swarm\lanes\validation\pixel_metrics\alpine\run_alpine_gates.py --shot runs\alpine_gates\shot.json --out runs\alpine_gates\report.json --tier 0
```

Exit 0 only when the health check passes and every gate is PASS. Exit 1 when
anything is FAIL, ERROR, UNMEASURED, STALE or UNLISTED. Exit 3 when the
calibration selfcheck fails (this machine's numpy/Pillow disagree with the
bake; no number from the run is usable).

A gate with a null argument is listed as UNMEASURED with the names of the
missing arguments and is not launched. `--only <lane id>` runs a subset.

Filling the shot file: `reference` / `candidate` are run directories for the
two aircraft lanes and PNG files for the rest, so set them in the lane block
where they differ from `common`. A lane block may also carry arguments the
manifest does not list (`hardware_perf.vram_budgeting.alpine` builds some of
its argument names at run time; see that lane's INTEGRATION.md). `true` sends
a bare flag.

## Gate

- metric 1: `summary.gates_passed == summary.gates_total`, with
  `gates_unmeasured == 0`, `gates_error == 0`, no stale or unlisted script.
- metric 2: `health.penalty_delta = penalty(candidate) - penalty(reference)`,
  where `penalty = snow_clip/0.02 + crushed/0.05 + snow_chroma/0.12`.
  Threshold `<= 0.05`, together with `ssim >= 0.35`, `detail_ratio >= 0.95`
  and the absolute limits (`snow_clip <= 0.02`, `crushed <= 0.05`,
  `snow_chroma <= 0.12`, mean linear luminance in `[0.05, 0.60]`, not blank).

The reference is the baseline capture of the same shot (same camera, same
time of day) before the change under test.

## Tiers (cost of the validation pass, not of a render)

All tiers use zero VRAM. RAM figures are estimates from array sizes, not
measurements.

| tier | what it reads | est. peak RAM |
| --- | --- | --- |
| 0 | first frame of each run, downscaled to 640 px wide | ~40 MB |
| 1 | first frame at up to 1280 px | ~120 MB |
| 2 | every candidate frame at 640 px, one in memory at a time: blank-frame scan (the frame a lost D3D11 device leaves) and flicker | ~40 MB |
| 3 | every candidate frame at 1280 px | ~120 MB |

Lane gates load their own images at their own size regardless of `--tier`.

## Known limits

- `snow_chroma` takes the brightest 5 % of unclipped pixels to be sunlit
  snow. A shot whose brightest region is the sun disc, a cloud edge or the
  aircraft will read wrong; frame the health reference so snow is the
  brightest thing, or ignore that one check for that shot.
- SSIM here is block SSIM on luminance, a same-shot sanity check, not a
  perceptual quality score.
- A frame sequence is "every PNG under the directory in name order"; a run
  directory that also holds albedo or depth passes needs the beauty
  sub-directory given instead.
- The runner trusts each lane gate's exit code (0 pass, 1 fail). It does not
  re-derive their metrics.

## Proposed changes to shared files (for the integrator; none made here)

1. `docs/COMMANDS.md`: add the command above under the Windows section.
2. `scripts/capture_windows.ps1`: nothing required. Optional: after a capture
   run finishes and UE has exited, print the command above.
3. When a lane adds or edits an alpine gate script, re-run
   `python swarm/lanes/validation/pixel_metrics/alpine/build_gate_manifest.py`
   on the Mac and commit `alpine_gates.json` + `shot.template.json`. Until then the Mac
   test only warns, and the Windows runner reports the script as STALE or
   UNLISTED and exits 1. Sibling lanes were still being edited when this
   manifest was written, so **the integrator must re-run the generator once
   all alpine lanes have landed.**

## Shared look parameters

This lane sets none. The values below were read from sibling alpine lanes'
files and are what the health limits assume; they are not authoritative:
sun elevation 30 deg, horizontal FOV 54.4 deg, snow albedo 0.90, haze
density 0.005 /km, capture width at most 1280 px, 8-bit sRGB PNG beauty frames.
