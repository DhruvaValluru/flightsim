# Third-party and owner-supplied assets

Assets that render in this project's datasets and are credited here. None of
the files below are committed to this repository: each is fetched or placed
locally (`assets/aircraft_src/`, `assets/generated/` and `ue/Content/` are
gitignored), and every render manifest carries its source and licence.

## Aircraft models

- **A-4 Skyhawk (A-4E/F/G/H/K)**: A-4 Skyhawk (A-4E/F/G/H/K) 3D model and
  textures © 2020 Dhruva Valluru. All rights reserved. Used in this dataset
  with the author's permission. Liveries carry real-world insignia; the Blue
  Angels name and emblem are US Navy trademarks (research use).
  Config: `assets/aircraft_config/A4.json`.
- **c172p, A320, B747, DHC-6, P-51D**: FlightGear models under the licence
  each upstream repository ships, pinned by commit in
  `assets/aircraft_config/<name>.json` (an airframe whose upstream ships no
  licence file stays physics-only).

## Terrain and imagery

Credited per bake in its provenance sidecar and in every render manifest
(Copernicus GLO-30, EOX Sentinel-2 cloudless 2016 CC BY-SA 4.0, ESA
WorldCover CC BY 4.0).
