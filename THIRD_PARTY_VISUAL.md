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

## Tornado smoke puffs (committed: `assets/looks/tornado/`, visual push lane C)

The tornado's dust cloud and the wall cloud's scud in beauty
(`FlightSimTornadoBeauty.cpp`, drawn through `M_TornadoPuff`). Four PNGs of
Kenney's "Smoke Particles" pack, packed unaltered in shape into one 512 x 512
grey + alpha atlas (`puffs_atlas.png`, 177,335 bytes, sha256
`bb3513978381acf63200dbec6eaee6c5fca7df31c57747b4de24f75b64389da3`) by
`scripts/make_tornado_puffs.py` (standard library, deterministic; `--fetch`
downloads the pinned inputs and checks each digest). kenney.nl hands out only
signed download links, so the inputs are pinned at a GitHub mirror that carries
the pack and its licence file unmodified; `assets/looks/tornado/PIN.json` has
each file's URL, size and sha256.

| file | author | licence | source | sha256 |
| --- | --- | --- | --- | --- |
| `whitePuff00.png` (57,599 bytes) | Kenney Vleugels (kenney.nl) | CC0-1.0 | https://raw.githubusercontent.com/fighter-435/Break-the-Battle-Formation/cc899ce7e9eeb2e127d677b24f0bc2420452142c/sci-fi-fps/assets/Kenney%27s_assets/PNG/White%20puff/whitePuff00.png | `33f894c2279bee9f77874dbfa3c0e9f071a0ee5e1a7065dcc40196029d699f58` |
| `whitePuff07.png` (58,796 bytes) | Kenney Vleugels (kenney.nl) | CC0-1.0 | same commit, `PNG/White puff/whitePuff07.png` | `810f3959b1beea2fe2ad077c8dd01caf48e04bf4422743fe680676948ed253ee` |
| `whitePuff16.png` (62,341 bytes) | Kenney Vleugels (kenney.nl) | CC0-1.0 | same commit, `PNG/White puff/whitePuff16.png` | `603f5f2faa71e1c18e5a2eb45ed16e01aa7642ca8222d4e80fa32a038979d764` |
| `whitePuff22.png` (62,775 bytes) | Kenney Vleugels (kenney.nl) | CC0-1.0 | same commit, `PNG/White puff/whitePuff22.png` | `e64dbe5dc2b5d484c29b450b2856fbfe6299aa4cea1ec506bd25ff262c5db8c7` |
| `LICENSE` (the pack's `license.txt`, 473 bytes) | Kenney Vleugels | CC0-1.0 | same commit, `license.txt` | `2070f53570f285a213f6ca5e75c1ef75c7104e5530cb533b795a42597b29b055` |

CC0 needs no attribution (the pack's licence: "Credit ... would be nice but is
not mandatory"); credit is given here anyway. No OpenVDB volume is used: the
render machine is D3D11 / SM5, and UE 5.7's sparse volume textures and
heterogeneous volumes need SM6.

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
