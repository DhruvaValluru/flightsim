# assets/emissivity -- the ASTER spectral library rows the IR proxy cites (S3)

Nine rows of the ASTER Spectral Library version 2.0 (Baldridge et al. 2009, Remote Sensing
of Environment 113, 711-715; now part of the ECOSTRESS library, Meerdink et al. 2019), each
the directional hemispherical reflectance in percent against wavelength in micrometres,
cached byte for byte with a `.sha256` sidecar. `aster_rows.provenance.json` records per row
the name, sample, measurement, the mirror it was fetched from, the fetch time and the sha256.
The primary (speclib.jpl.nasa.gov) answered 403 through this container's proxy; the rows
came from two GitHub mirrors that vendor the library's files unchanged, and were not
compared with the primary here (`primary_verified: false`).

`core/capture/thermal.py` forms the band emissivity as the Planck-weighted mean of
1 - R/100 over the band (Kirchhoff, an opaque sample). A row that is absent, whose digest is
not its sidecar's, or that the provenance does not record refuses `sensing.ir_table` by
name; the fetch step is to cache the row here with its sidecar and a provenance entry.

The rows are laboratory samples standing in for classes (see `assets/thermal/proxy_v1.json`
for which row stands for which class); the aircraft skin is a bare aluminium row, so a
painted skin is not represented, and no water row is cached (water pixels are unmodelled).
