# Configuration surface

Every switch the program reads, each with one decision. **ui**: stays exposed, in the interface (exactly the six fields the settings panel shows). **default**: hidden, value fixed (the environment may still override it for a developer; the app never asks). **dev-only**: tests and debugging scripts only. **remove**: to delete. The table lives in `core/config_surface.py`; this file is `render_markdown()` written to disk and `tests/test_config_surface.py` fails when the two drift, when a source file reads a `FLIGHTSIM_` name that has no row, or when a row's name is read nowhere.

## Environment variables

| name | settings key | bucket | default | where read (file:line) |
|---|---|---|---|---|
| `FLIGHTSIM_RENDER_QUALITY` | `render_quality` | ui | measure | `webapp/runs.py:2290` |
| `FLIGHTSIM_CAPTURE_PASSES` | `capture_passes` | ui | none | `webapp/capture.py:66` |
| `FLIGHTSIM_LLM` | `llm` | dev-only | unset | `core/nl/providers.py:193`, `core/nl/llm_compiler.py:157`, `scripts/llm_check.py:50` |
| `FLIGHTSIM_LLM_MODEL` | `llm_model` | dev-only | unset | `core/nl/providers.py:210`, `core/nl/providers.py:219`, `core/nl/providers.py:254`, `core/nl/providers.py:262` |
| `FLIGHTSIM_RELAY_URL` | `relay_url` | dev-only | unset | `core/nl/providers.py:231` |
| `FLIGHTSIM_GOOGLE_TILES` | `google_tiles` | dev-only | on | `core/scenario/card.py:385` |
| `FLIGHTSIM_WEATHER_BACKEND` | `weather_backend` | default | procedural | `webapp/runs.py:2321` |
| `FLIGHTSIM_RAIN_GAIN` | `rain_gain` | default | 4.0 | `webapp/runs.py:2327`, `scripts/debug_storm_render.py:106` |
| `FLIGHTSIM_RAIN_STYLE` | `rain_style` | default | cinematic | `webapp/runs.py:2328` |
| `FLIGHTSIM_SKY` | `sky` | default | unset | `webapp/runs.py:2473`, `core/registry.py:1317`, `scripts/ue_create_materials.py:2183` |
| `FLIGHTSIM_RENDER_TIMEOUT_SECONDS` | `render_timeout_seconds` | default | unset | `core/render/headless.py:83` |
| `FLIGHTSIM_STALL_SECONDS` | `stall_seconds` | default | unset | `core/render/headless.py:79` |
| `FLIGHTSIM_TERRAIN_PREFETCH` | `terrain_prefetch` | default | on | `webapp/runs.py:377` |
| `FLIGHTSIM_FFMPEG` | `ffmpeg` | dev-only | unset | `core/util/platform.py:76` |
| `FLIGHTSIM_FONT` | `font` | dev-only | unset | `core/util/platform.py:113` |
| `FLIGHTSIM_GEOCODER` | `geocoder` | dev-only | unset | `core/nl/geocode.py:54` |
| `FLIGHTSIM_GEOCODE_CACHE` | `geocode_cache` | dev-only | unset | `core/nl/geocode.py:55` |
| `FLIGHTSIM_REBUILD_MATERIALS` | `rebuild_materials` | dev-only | unset | `scripts/ue_create_materials.py:926` |
| `FLIGHTSIM_MACHINE` | `machine` | dev-only | unset | `scripts/phase3_event.py:37` |
| `FLIGHTSIM_BRANCH` | `branch` | dev-only | unset | `scripts/phase3_monitor.py:235` |
| `FLIGHTSIM_XPLANE_TERRAIN` | `xplane_terrain` | dev-only | unset | `core/xplane/devflags.py:38` |
| `FLIGHTSIM_XPLANE_SKY` | `xplane_sky` | dev-only | unset | `core/xplane/devflags.py:50` |
| `FLIGHTSIM_XPLANE_LIGHTING` | `xplane_lighting` | dev-only | unset | `core/xplane/devflags.py:43` |
| `FLIGHTSIM_WORLD_BEAUTY_OVERRIDES` | `world_beauty_overrides` | dev-only | unset | `core/scene/look_match.py:36` |
| `FLIGHTSIM_DISTANT_CLOUDS` | `distant_clouds` | dev-only | unset | `ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimClouds.cpp:982`, `core/scene/world_beauty.py:481` |
| `FLIGHTSIM_SKY_HDRI` | `sky_hdri` | dev-only | unset | `ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimClouds.cpp:992`, `scripts/ue_create_materials.py:3347` |
| `FLIGHTSIM_HDRI_CACHE` | `hdri_cache` | dev-only | unset | `core/scene/sky_hdri.py:81` |
| `FLIGHTSIM_BEAUTY_POST` | `beauty_post` | dev-only | unset | `scripts/beauty_post.py:73`, `webapp/runs.py:3614`, `scripts/visual_round.py:150` |
| `FLIGHTSIM_RENDER_SWITCHES` | `render_switches` | dev-only | unset | `ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimRenderCommandlet.cpp:3354`, `ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimHeroLighting.cpp:432`, `ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimBeautyLook.cpp:376`, `core/scene/hero_lighting.py:553` |

## Keys not prefixed FLIGHTSIM_

| name | settings key | bucket | default | where read (file:line) |
|---|---|---|---|---|
| `GOOGLE_MAPS_API_KEY` | `google_tiles_key` | ui | none | `ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimGoogleTiles.cpp:79` |
| `UE_ROOT` | `engine` | ui | 5.7.4 | `core/util/platform.py:278` |
| `ANTHROPIC_API_KEY` | `llm_key` | ui | none | `core/nl/providers.py:200`, `core/nl/llm_compiler.py:162`, `core/nl/llm_compiler.py:1536`, `core/nl/camera_prompt.py:361` |
| `CESIUM_ION_TOKEN` | `cesium_ion_token` | dev-only | none | `ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimGoogleTiles.cpp:81`, `core/util/settings.py:67` |

## Derived rows (shown, never set)

| settings key | bucket | default | note |
|---|---|---|---|
| `cesium_status` | ui | unknown | Derived (E2 cesium_status() from toolchain.json plus the plugin probe); shown, never set. |

## Command-line flags

| flag | bucket | where read |
|---|---|---|
| `spec` | ui | `flightsim/capture.py` |
| `--out` | ui | `flightsim/capture.py` |
| `--terrain` | ui | `flightsim/capture.py` |
| `--clip-seconds` | ui | `flightsim/capture.py` |
| `--synth-terrain` | dev-only | `flightsim/capture.py` |
| `--max-previews` | ui | `flightsim/capture.py` |
| `--render` | ui | `flightsim/capture.py` |
| `--void` | dev-only | `flightsim/capture.py` |
| `--passes` | ui | `flightsim/capture.py` |
| `--scene` | ui | `flightsim/capture.py` |
| `--calibration` | dev-only | `flightsim/capture.py` |
| `--sun-lux` | dev-only | `flightsim/capture.py` |
| `--accumulate` | dev-only | `flightsim/capture.py` |
| `--no-host-flight` | dev-only | `flightsim/capture.py` |
| `--card` | ui | `flightsim/capture.py` |
| `--instruments` | ui | `flightsim/capture.py` |
| `--null-tests` | ui | `flightsim/capture.py` |
| `--uncertainty` | ui | `flightsim/capture.py` |
| `--dis` | dev-only | `flightsim/capture.py` |
| `--dis-udp` | dev-only | `flightsim/capture.py` |
| `--dis-entity-type` | dev-only | `flightsim/capture.py` |
| `--dis-epoch` | dev-only | `flightsim/capture.py` |
| `--dis-emitter` | dev-only | `flightsim/capture.py` |
| `--cigi` | dev-only | `flightsim/capture.py` |
| `--hla` | dev-only | `flightsim/capture.py` |
| `--verbose` | dev-only | `flightsim/capture.py` |

## Settings file

The settings file (E2, `GET/PUT /settings`) may hold only: `google_tiles_key`, `render_quality`, `llm_key`, `capture_passes`. `google_tiles` is never in it: `FLIGHTSIM_GOOGLE_TILES=off` is the only off switch, and the storm weather rows (`weather_backend` procedural, `rain_gain` 4, `rain_style` cinematic) stay on by default.

## How to add a setting

1. Add a `Setting` row to `SETTINGS` in `core/config_surface.py` (or a flag to `CLI_FLAGS`) with its bucket, default and every `file:line` that reads it.
2. Regenerate this file: `python3 -c "from core.config_surface import render_markdown; open('docs/CONFIG_SURFACE.md', 'w', encoding='utf-8').write(render_markdown())"`.
3. Run `pytest -q tests/test_config_surface.py`: it fails by name on an unlisted `FLIGHTSIM_` name, a stale row, a bad bucket or a drifted document.
