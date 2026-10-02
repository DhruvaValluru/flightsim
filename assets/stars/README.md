# The star catalogue (W3, core/scene/night.py)

The night look draws its starfield from the Yale Bright Star Catalogue,
5th revised edition (Hoffleit & Warren 1991), read from a CACHED file whose
sha256 the code checks on every load. Nothing is downloaded during a run.

## The fetch step (on a networked machine)

The primary hosts (CDS `V/50`, `tdc-www.harvard.edu/catalogs/bsc5.html`)
refused the CONNECT through the build container's proxy (measured
2026-09-29), so the cached file is the brettonw/YaleBrightStarCatalog
mirror's JSON conversion of the Harvard ASCII catalogue (HR, RA/Dec J2000,
V, K):

    curl -sS -o assets/stars/bsc5-short.json \
      https://raw.githubusercontent.com/brettonw/YaleBrightStarCatalog/master/bsc5-short.json
    sha256sum assets/stars/bsc5-short.json

The digest must read

    94b0581379ef9ea49f1ce664734a06d2fbbff2d7487f926acad3e9ef0960e0d8

(954 206 bytes, 9096 stars with a V magnitude; Sirius V -1.46 at RA
06h45m08.9s, Dec -16 42 58). That is `CATALOGUE_SHA256` in
core/scene/night.py. A file with any other digest is refused
`look.stars` -- by the validator before a run and by the loader -- in
every star mode that reads it; a corrupt cache never silently becomes a
procedural sky. If the mirror changes, the new file is a new input: fetch
it, measure it, and change the constant with the measurement.

## Without the file

`stars: auto` (the default) draws a SEEDED PROCEDURAL field and records
it as `procedural` (mode, seed, count, the rows' sha256) in the card's
`look.night.stars_mode` and the `scene.world` record: 9000 isotropic
stars, magnitudes by N(<V) proportional to 10^(0.5 V) to V 6.5, the
brightest clamped at -1.46. It is not the real sky and is not claimed to
be. `stars: catalogue` without the file is refused `look.stars`;
`stars: procedural` never reads the file; `stars: off` draws none.

## Licence

The BSC5 is distributed by CDS and the Harvard-Smithsonian Center for
Astrophysics for research use; the mirror's repository states no licence
of its own for the converted file [unverified here]. The file is NOT
committed: each machine fetches and verifies it.
