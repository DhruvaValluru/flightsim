# Third-party visual assets and tools

Every asset or tool the visual overhaul brings into the repository, with its
licence, source, version or commit, and sha256. Nothing here is NC-licensed,
and no Fab or Megascans content is committed. Large binaries are never
committed: they are fetched into a cache and checked against their sha256 on
first use.

## Physically Based API (materials database)

- What: `assets/looks/physically_based/materials.json`, the measured and
  referenced material constants (base colour / F0, roughness, IOR) the
  aircraft master materials are calibrated from (`scripts/aircraft_look.py`
  via `scripts/physically_based.py`).
- Source: https://github.com/AntonPalmqvist/physically-based-api,
  `deploy/v2/materials.json` at commit
  `bed520ab9800de4fc9800304f6557f85ce788e69` (2026-11-09).
- Licence: CC0 1.0 Universal (`assets/looks/physically_based/LICENSE`;
  the upstream README: "All data is released under CC0 1.0"). No attribution
  is required; this entry is the pin.
- sha256: `9f9b55460e01c69a24ca5021642e2980a33d852e0f77c5c5826f7d6c64e32692`
  (`assets/looks/physically_based/PIN.json` carries the per-file pins and
  the names used).

## Sky HDRIs (core/scene/sky_hdri.py, visual round 5 lane L3)

Used only behind `-sky-hdri=<name>` / `FLIGHTSIM_SKY_HDRI` as the sky light's
specified cubemap (a probe on the clear and hazy beauty presets). The cached
copy is prepared by `python -m core.scene.sky_hdri prepare <name>` (sun disk
clamped, upper hemisphere normalised); the sidecar beside it records the clamp.

| name | title | licence | source | file | sha256 |
| --- | --- | --- | --- | --- | --- |
| `qwantani_puresky` | Qwantani (Pure Sky), Greg Zaal (original), Jarod Guest (sky edits) | CC0-1.0 | https://polyhaven.com/a/qwantani_puresky | https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/4k/qwantani_puresky_4k.hdr (17,919,364 bytes, 4096 x 2048 RGBE) | `5776f890607ff98e21cc1f04bdc3dacbdf33795386dbebb418f42b0fc92814d1` |

CC0 needs no attribution; the entry is kept so every pinned asset is listed in
one place.

## Film-stock LUTs (committed: `assets/looks/film/`)

- **Generator: spectral_film_lut** by Jan Lohse, MIT.
  https://github.com/JanLohse/spectral_film_lut, tag v0.18.14, commit
  `a15043f6fe2d365d0c359d22e0868076800916d9`. Not a repository dependency:
  it runs from a scratch virtual environment (`scripts/make_film_luts.py`
  says how). It digitises published film datasheets and simulates the
  stock's reaction to light through to the print or the slide.
- **The LUTs** (`kodak_portra_160.cube`, `kodak_ektachrome_100d.cube`,
  `kodak_vision3_250d_2383.cube`) are this project's own output of that
  generator and are dedicated **CC0-1.0**. Each one's generator commit,
  stock, parameters, corrections (grey-axis neutralisation, tone-curve
  normalisation, scene recovery) and sha256 are in
  `assets/looks/film/film_luts.json`; `tests/test_film_luts.py` checks the
  files against those digests and holds neutral grey within 2 %.
  The stock names (Kodak Portra, Ektachrome, Vision3, Vision) are their
  manufacturers' trademarks, used to say which datasheet was emulated.

## Post-render tools (cached, never committed: `%LOCALAPPDATA%\flightsim\tools`)

Pinned in `scripts/beauty_post.py` `TOOLS`; the sha256 is GitHub's own
release digest where the release carries one.

| Tool | Version | Licence | Release zip | sha256 |
| --- | --- | --- | --- | --- |
| Intel Open Image Denoise (`oidnDenoise.exe`) | 2.5.1 | Apache-2.0 | https://github.com/RenderKit/oidn/releases/download/v2.5.1/oidn-2.5.1.x64.windows.zip | `f11f91bc072a5e3a564515724cb72ab8fcfbc445c84a84c197ff9b16cc01396f` |
| ffmpeg, BtbN FFmpeg-Builds win64 **LGPL** build, release branch 8.1 | n8.1.3-34-ga35157abb9 (autobuild-2026-11-09-12-42) | LGPL-2.1-or-later | https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-11-09-12-42/ffmpeg-n8.1.3-34-ga35157abb9-win64-lgpl-8.1.zip | `7bdec3860d33145a7cd68146eb8e1414e8881cac76205401211fbdad38ef0ed3` |
| Real-ESRGAN-ncnn-vulkan (`realesrgan-ncnn-vulkan.exe` + models) | v0.2.0 binary, 20220424 zip (Real-ESRGAN release v0.2.5.0) | MIT (code), BSD-3-Clause (models) | https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip | `abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d` |

Notes.

- The Real-ESRGAN-ncnn-vulkan repository's own v0.2.0 Windows zip
  (`realesrgan-ncnn-vulkan-v0.2.0-windows.zip`, sha256
  `1bbbdb12d470af80b035c773682e144c6c2f6ece9210832a289af0a48ce3fa9a`)
  holds the same executable and no models; the zip pinned above is the
  one that ships `models/realesrgan-x4plus.{param,bin}`. The 2022 releases
  predate GitHub's digests, so these two were computed from the downloads
  on 2026-11-10.
- ffmpeg's LGPL build is the one without GPL-only components (no x264,
  x265 or other GPL libraries); the pipeline uses only built-in filters
  (`lut3d`, `gblur`, `colorlevels`, `colorchannelmixer`, `blend`, `noise`,
  `vignette`, `scale`) and the PNG and PPM codecs.
- Open Image Denoise's release bundles its own runtime libraries under the
  same Apache-2.0 licence (its `doc/LICENSE.txt` in the zip).

## Terrain and ocean detail (committed: `assets/terrain_detail/`)

Lane B of the non-urban visual push (2026-11-11). Beauty only:
`M_FlightSimTilesBeauty` lays them over the Google tiles as detail (the tiles
stay the ground), and `M_FlightSimOceanBeauty` draws the open sea with the
ocean normal. Imported by `scripts/ue_create_materials.py`
(`TERRAIN_DETAIL_TEXTURES`), which checks each file's sha256 against
`assets/terrain_detail/PIN.json` before importing. 1K JPEGs, albedo and
OpenGL normal only (roughness is a per-role constant), 9.1 MB in all.
CC0 needs no attribution; the rows are the pins.

| role | asset | licence | file (Poly Haven 1K) | bytes | sha256 |
| --- | --- | --- | --- | --- | --- |
| rock | Rocky Terrain 02 (Amal Kumar), 90 m tile, https://polyhaven.com/a/rocky_terrain_02 | CC0-1.0 | https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/rocky_terrain_02/rocky_terrain_02_diff_1k.jpg | 843,188 | `d570c10b1d5302f4fde9e0e94f4cbab0d5e112fc3fe2b3b91c38a98bd3ddaf4b` |
| rock | (normal) | CC0-1.0 | https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/rocky_terrain_02/rocky_terrain_02_nor_gl_1k.jpg | 993,692 | `f4f9d9671c660f4e509e96d5da3091887dfd557e1353e313fa2d1dc789499ffd` |
| scree | Aerial Rocks 04 (Rob Tuytel), 80 m tile, https://polyhaven.com/a/aerial_rocks_04 | CC0-1.0 | https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/aerial_rocks_04/aerial_rocks_04_diff_1k.jpg | 841,479 | `5ac472016a6740bd3c62b1d719bf128e0659022fb35853f4e847737522337ffa` |
| scree | (normal) | CC0-1.0 | https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/aerial_rocks_04/aerial_rocks_04_nor_gl_1k.jpg | 1,242,717 | `b4fe185783020d81b595397ef3b920475268a4873dc8b6efdd58f4312e07140b` |
| snow | Snow Field Aerial (Rob Tuytel), 80 m tile, https://polyhaven.com/a/snow_field_aerial | CC0-1.0 | https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/snow_field_aerial/snow_field_aerial_col_1k.jpg | 754,873 | `902e1fef8f1bcc2f158fbb118239e29159978fd7b8e241d2d0f404b8dbecf718` |
| snow | (normal) | CC0-1.0 | https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/snow_field_aerial/snow_field_aerial_nor_gl_1k.jpg | 640,692 | `2037817e0166673e68039c4dd2c56fa014d6999e1d6d492e2e3e7e3cfec3862b` |
| grass | Aerial Grass Rock (Rob Tuytel), 15 m tile, https://polyhaven.com/a/aerial_grass_rock | CC0-1.0 | https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/aerial_grass_rock/aerial_grass_rock_diff_1k.jpg | 666,655 | `57b8041bfe0d0f01430e4dbaad45e7ddddf0a9fc97317f90dbc51f7b0d9e1b5d` |
| grass | (normal) | CC0-1.0 | https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/aerial_grass_rock/aerial_grass_rock_nor_gl_1k.jpg | 904,956 | `1aa3e23bff453f152e089b9f83aa36b4901651e019f7e2ca01d5331a9bbbda78` |
| sand | Aerial Sand (Rob Tuytel), 15 m tile, https://polyhaven.com/a/aerial_sand | CC0-1.0 | https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/aerial_sand/aerial_sand_diff_1k.jpg | 490,916 | `d5195c44aec087d2a30d3ca3a3fa3458a1898986e0572e9a8043f8245598557a` |
| sand | (normal) | CC0-1.0 | https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/aerial_sand/aerial_sand_nor_gl_1k.jpg | 665,488 | `cba74d670a681dfcdd72db72afbcb9879c7ec9f5854adae24cac8da2c432ad99` |
| soil | Dirt Aerial 02 (Rob Tuytel), 20 m tile, https://polyhaven.com/a/dirt_aerial_02 | CC0-1.0 | https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/dirt_aerial_02/dirt_aerial_02_diff_1k.jpg | 431,838 | `6a039c20e1e702733b88c429c06994cc9403c1a049e72af70750db1ea3e3e743` |
| soil | (normal) | CC0-1.0 | https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/dirt_aerial_02/dirt_aerial_02_nor_gl_1k.jpg | 607,060 | `4abbec8698563135d236a7bdc4d4bac5d7932aa4eb022e0557e6842f35dd9254` |
| ocean | FlightSim ocean wave normal, 256 m tile: this project's own output of `scripts/make_ocean_normal.py` (Phillips spectrum, Tessendorf 2001; seed and parameters in `assets/terrain_detail/ocean/ocean_normal.json`) | CC0-1.0 (dedicated) | `assets/terrain_detail/ocean/ocean_normal_512.png` (512 x 512 RGB) | 665,378 | `0744cfae56654861fe372055ad73f5d9d6bf78ba9a7a907a4c8945743ad6f4c9` |

Why a generated ocean normal: Poly Haven and ambientCG were both searched on
2026-11-11 and carry no water normal maps; other "water normal" files in
circulation (for example three.js's `waternormals.jpg`) have no stated
licence for the image itself, so none was taken.
