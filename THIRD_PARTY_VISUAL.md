# Third-party visual tools and data (visual overhaul, round 5)

Everything the beauty render's visual pipeline takes from outside the
project, with its source, version, licence and sha256. Only CC0, MIT,
Apache, BSD and attributed CC-BY material is allowed in the repository;
binaries are fetched into a cache on first use and never committed
(`scripts/beauty_post.py` checks each one against its sha256). Aircraft,
terrain and imagery credits are in `NOTICE.md`.

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
