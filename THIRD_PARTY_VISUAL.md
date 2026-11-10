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
