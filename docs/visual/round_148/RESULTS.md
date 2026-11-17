# r148 (HDRI sky) on b3174986 (p3-windows, 2026-11-16)

## Prep
- Rebuilt FlightSimEditor at b3174986.
- `ue_create_materials.py` imported all 8 HDRIs with HDRI-IMPORTED: a T_HdriLight_* and a T_HdriBackdrop_* for each of 4 skies. It created M_FlightSimHdriBackdrop and MI_FlightSimCloudImpostor_cloud00-03. There were no MATERIAL-FAILED lines.
- The log also has `SKY-HDRI-SKIPPED: FLIGHTSIM_SKY_HDRI names no pinned sky`. That is the old pinned-sky path, so it is expected.

## Round 148: one still each, default flags (pushed b49ec3ac, verify a7cfb09a)

Wall time 579 s. SSIM is against round 147; scene 9 had no round 147 frame to compare with.

| # | seconds | mean luma | crushed | SSIM vs 147 | max GPU drain s | HDRI slot / sky | verify |
|---|---|---|---|---|---|---|---|
| 1 | 126.1 | 0.195 | 0 | 0.867 | 1.45 | golden / syferfontein_6d_clear_puresky (sun 6.0 deg) | FAIL (old store_sta2 bbox) |
| 7 | 146.3 | 0.166 | 0 | 0.957 | 2.25 | storm / overcast_soil_puresky (sun 51.6 deg) | pass |
| 9 | FAILED 35.8 | - | - | - | - | - | FAIL (no capture) |
| 13 | 61.0 | 0.100 | 0.0001 | 0.997 | 0.60 | clear / qwantani_noon_puresky (sun 89.9 deg) | pass |
| 15 | 121.1 | 0.139 | 0 | 0.677 | 1.67 | storm / overcast_soil_puresky (sun 51.6 deg) | pass |

## #9 HANG / TDR
- The GPU hung (TDR) on the FIRST warm-up capture, before any drain line was written. Run 16aacddc80b1.
- Warm-up started at 01:58:09.181 UTC, and the hang came 4.1 s later:
  - DXGI_ERROR_DEVICE_HUNG 0x887A0006 at 01:58:13.308 (D3D11Query.cpp:396)
  - "Unreal Engine is exiting due to D3D device being lost".
- The excerpt is in `09_16aacddc80b1_tdr_excerpt.txt`.
- I did not retry.
- For comparison, the laptop's GPU was healthy earlier today. On 9ef62483 and da82dc78, #9 was clean 4 of 4, with a first warm-up drain of 3.3-3.5 s.
- So b3174986 likely raises #9's per-capture cost past the TDR limit, which could come from the HDRI sky-light capture or the backdrop.
- Unmeasured: whether `-look-hdri=off` on #9 renders clean at this commit. That one still would show whether the HDRI is the cause.

## Other notes
- In #1, #7 and #13 the frame has no hdri_backdrop_opacity in its summary, so check `frames[].hdri_backdrop_opacity` in render.json for the backdrop law. All scenes use full_below_agl_m 600 and none_above_agl_m 1000.
- Brightness in #1 went 0.172 to 0.195 against r147, and in #15 0.058 to 0.139 (SSIM 0.68, a big change). #7 went 0.220 to 0.166, back darker.

## hdri_sky sections
The full `look_applied.world_beauty.hdri_sky` from each render.json is in `hdri_sky/NN_<run>_hdri_sky.json`. There is none for #9, which produced no render.json.

## Run ids
#1 e93fbb705a63, #7 d2a55afd54e0, #9 16aacddc80b1 (TDR), #13 9ce7b30016bd, #15 39790ab8ac3c
