# Third-party and owner-supplied assets

Assets that render in this project's datasets and are credited here. None of
the files below are committed to this repository: each is fetched or placed
locally (`assets/aircraft_src/`, `assets/generated/` and `ue/Content/` are
gitignored), and every render manifest carries its source and licence.

## Aircraft models

- **c172p, A320, B747, DHC-6, P-51D**: FlightGear models under the licence
  each upstream repository ships, pinned by commit in
  `assets/aircraft_config/<name>.json` (an airframe whose upstream ships no
  licence file stays physics-only).
- **A-4 Skyhawk (A-4E/F/G/H/K)**: the visual model and textures under
  `assets/aircraft_models/A4/` are committed at the owner's direction; their
  licence statement is `assets/aircraft_models/A4/NOTICE.txt` and the
  source record is `assets/aircraft_config/A4.json`. Its licence is not on
  the dataset allow-list, so the export gate refuses to ship it.
- **Higher-detail candidates (none renders yet)**: the table in
  `scripts/fetch_aircraft_models.py`, each row with its licence evidence.
  Pinned: FlightGear FGAddon `Aircraft/Sukhoi-Su-33` by Emmanuel Baranger
  (helijah), GPL-2.0 (its `COPYING`), SVN r18942, tree sha256 recorded.
  The Sketchfab rows are CC BY 4.0 and unpinned; one used later must be
  credited "Model: <title> by <author> (Sketchfab), CC BY 4.0" with the
  licence link. Rows whose uploader did not make the model, game rips,
  NonCommercial and store licences are recorded as REJECTED.

## Terrain and imagery

Credited per bake in its provenance sidecar and in every render manifest
(Copernicus GLO-30, EOX Sentinel-2 cloudless 2016 CC BY-SA 4.0, ESA
WorldCover CC BY 4.0).

## Ground textures

Fetched on the owner's machine by `scripts/fetch_ground_textures.py`
into `data/textures/polyhaven/` (not committed): Poly Haven
(polyhaven.com), CC0 1.0. Poly Haven's API terms ask software that uses
the live API to credit it visibly: "Textures: Poly Haven (polyhaven.com),
CC0". Each surface's `provenance.json` names the asset, its URLs and the
files' digests. Without the step, every ground material is procedural.

## Ground-scatter models (beauty renders)

Fetched by `scripts/fetch_scatter_assets.py` into `data/scatter/polyhaven/`
(not committed), pinned in `assets/scatter/polyhaven_pins.json` (source URL,
md5 from Poly Haven's API, sha256): Poly Haven (polyhaven.com), CC0 1.0.
"Models: Poly Haven (polyhaven.com), CC0". Visual only; a species without a
complete pin is never drawn.
