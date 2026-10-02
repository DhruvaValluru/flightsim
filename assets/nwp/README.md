# Cached NWP wind profiles (P6, core/environment/shear.py)

One fixture = two files: `<name>.json` (the data: `levels` of
`[pressure_hpa, u_mps eastward, v_mps northward]`) and
`<name>.provenance.json` (the sidecar: `url`, `fetched_at`, `sha256` of the
data file's bytes, `synthetic`). `NwpFixture` refuses `weather.fixture_missing`
when either file is absent and `weather.fixture_digest` when the data file's
digest is not the sidecar's. Levels become a layered wind at the
standard-atmosphere height of each pressure (stated in the record).

`synthetic_profile_2026-09-28` is a SYNTHETIC STAND-IN: the NOMADS host is not
reachable from the build container, so its sidecar carries the URL the cache
would have fetched and `fetched_at: null`. Nothing in it is a forecast.
