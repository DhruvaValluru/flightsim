# r147 render.json and cloud log excerpts

These files support p3-mac's question about why scene 13's clouds and the probe arm did not change.

## Files
- `13_4af29b286dc4_*`: #13 at default flags.
- `13_probe_a0d4fa54c6be_*`: #13 with -cloud-march=probe.
- `01_cd5fca09373b_*`: #1 at default flags.

`*_cloudlog.txt` holds the lines of frames/render.log that match cloud, march, volumetric or probe.
Lines with tokens or keys were dropped. The render.json files had no token values; they were checked before committing.

## Probe did take effect
Both runs report the march in `look_applied.world_beauty.clouds.march`:

| Run | tier | word source | view_samples_max | shadow_samples | trace |
|---|---|---|---|---|---|
| default | integrated | default auto | 192 | 10 | 80 km |
| probe | probe | switch | 288 | 20 | 80 km |

The GPU is Intel(R) Graphics: rhi_device_is_integrated = true, feature_level_sm6 = false.

`distant_clouds.volumetric_trace.march_tier` is probe in the probe run. The volumetric trace runs out to 32 km, with the fade starting at 24 km.

## Why the frame barely changed
The march did change, but the frame is almost the same: SSIM 0.9986, luma 0.0997 against 0.1010.
The extra samples barely show in #13's sky, which suggests the march sample count is not what limits this scene's clouds.

The render log has no explicit march line; render.json is the only record of the march settings.
