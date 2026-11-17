# r151 final check of the merged build, 2afd3525 (p3-windows, 2026-11-16)

## Prep
- Rebuilt at 2afd3525, then ran `ue_create_materials.py` with 0 MATERIAL-FAILED and no tracebacks.
- The first launch was stopped by the harness's low-memory reaper right after prep, before any scene started. There was no orphan Unreal process left.
- I resumed the scenes with Prep none, since prep_stamp was already 2afd3525.

## Round 151: one still each, default flags, then verify (pushed 7fe44db2, verify e239bf4a)

Wall time 2434 s. SSIM is against r147; scenes 3, 9 and 12 had no r147 frame to compare with.

| # | seconds | mean luma | crushed | SSIM vs r147 | max GPU drain s | verify | cloud_material_auto per layer (aircraft_clearance) |
|---|---|---|---|---|---|---|---|
| 1 | 207.3 | 0.172 | 0.0001 | 1.000 | 1.58 | FAIL (old store_sta2 bbox) | [0] ours |
| 3 | 156.8 | 0.224 | 0.0002 | n/a | 1.73 | pass | [0] ours |
| 6 | 197.0 | 0.130 | 0 | 1.000 | 2.33 | pass | [0] ours (cloud moved above, base 3396 m) |
| 7 | 182.4 | 0.220 | 0 | 1.000 | 2.42 | pass | [0] ours |
| 9 | FAILED 1316.4 | - | - | - | 3.53 | FAIL (no capture) | - (TDR, no render.json) |
| 10 | 96.3 | 0.054 | 0.0054 | 1.000 | 1.16 | pass | [0] ours |
| 12 | 105.7 | 0.190 | 0.0495 | n/a | 1.36 | pass | [0] ours |
| 13 | 40.8 | 0.074 | 0 | 0.769 | 0.46 | pass | [0] /Engine/EngineSky/VolumetricClouds/m_SimpleVolumetricCloud_Inst |
| 15 | 101.0 | 0.058 | 0 | 1.000 | 1.25 | pass | [0] ours |

- The HDRI is off in every scene: hdri_sky.switch is off.
- Only #13 drew UE's stock cloud. That is the intended auto rule: the aircraft is above a cumulus layer.
- Every other scene kept our material.
- clouds.layers[].cloud_material is "auto" everywhere.
- #13 matches 1502: luma 0.07406, with distant clouds off.
- Scenes 1, 6, 7, 10 and 15 are pixel-identical to r147 (SSIM 1.000).
- #12's crushed fraction is 0.0495, just under the 0.05 limit.
- The full aircraft_clearance and clouds.layers sections are in `render/NN_<run>_clouds.json`. #6 renders its frames under `frames/wingman/`.

## #9 TDR (run 7937dd1f5d11)
- It hung with DXGI_ERROR_DEVICE_HUNG 0x887A0006 after 1316 s, during the subject-meter re-warm captures. The excerpt is in `09_7937dd1f5d11_tdr_excerpt.txt`.
- The first warm-up drain was 3.53 s, which counts as healthy. The run then logged 56 drained captures, most of them 3.33-3.37 s.
- In the last three captures before the hang, the drain dropped to 2.31 s.
- That 3.3 s to 2.3 s drop, then a hang, is the same signature as this afternoon's degraded-driver state. Only a real Windows Restart cleared it then.
- So before any further #9 run, the laptop likely needs a real Restart. That is the owner's call; I did not restart it.
- I did not retry, as instructed.
- r149's 1492 (#9 at b3174986 with the HDRI off) rendered clean, so this hang is not the HDRI.
- I have not measured why #9 ran 18 re-warm captures and 1316 s, against 256-302 s for #9 earlier today.

## Run ids
#1 50dbfe3244cc, #3 341f401430be, #6 1a2bcbdaff7b, #7 6d7b5a1afe80, #9 7937dd1f5d11, #10 cf532e4d1783, #12 a0b536c985ff, #13 f3f0803eb89e, #15 5f3ac5551e9a
