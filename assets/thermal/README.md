# assets/thermal -- the IR proxy's tables (S3)

`core/capture/thermal.py` reads these and nothing else; every number the IR proxy uses
beyond the stated physical constants is in a file here or in `assets/emissivity/`.

* `proxy_v1.json` -- the thermal table a camera names in `cameras[i].ir.thermal_table`:
  `proxy: true`, the bands (LWIR 8-12 um, MWIR 3-5 um), the transmittance table's name, and
  per class a temperature model (`recovery`, `near_surface_air`,
  `near_surface_air_below_melting`, `none`) and the ASTER row that gives its emissivity, each
  with its source; the object, land cover and engine-palette mappings. A table that does not
  declare `proxy: true`, cites no source or names a row that is not cached refuses
  `sensing.ir_table` by name.
* `transmittance_synthetic.csv` (+ `.sha256`, `.provenance.json`) -- tau(R) per band,
  `range_m,LWIR,MWIR`. **SYNTHETIC**: `tau = exp(-k R)` with invented k (0.1 / km LWIR,
  0.2 / km MWIR), written to exercise the plumbing. It is not an atmosphere. Every record
  and manifest block that uses it carries `synthetic: true`.

## The networked step: a real transmittance table

Run MODTRAN 6 (licensed) or libRadtran's `uvspec` for a stated model atmosphere, aerosol,
altitude and path geometry; band-average the transmittance over 8-12 um and 3-5 um at a set
of ranges starting at 0 m (tau = 1 there); write `<name>.csv`, `<name>.csv.sha256` and
`<name>.provenance.json` with `synthetic: false`, the run's inputs as `source`, `bands_um`
and the csv's `sha256`; point a thermal table's `transmittance` at `<name>`. Nothing in this
container can run either code. Without a provenanced table the proxy refuses
`sensing.ir_transmittance`; it never falls back to Koschmieder or to a constant in code.
