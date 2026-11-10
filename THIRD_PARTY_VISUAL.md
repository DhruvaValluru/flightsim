# Third-party visual assets and tools

Every asset or tool the visual pipeline fetches or vendors, with its licence,
source, version and sha256 (the project rule: CC0, MIT, Apache, BSD or CC-BY
with an entry here; nothing NC, nothing from Fab or Megascans). Large files
are downloaded into a cache and verified at first use, never committed.

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
