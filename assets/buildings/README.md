# Cached building footprints (W2, core/scene/buildings.py)

No footprint set is committed here. One set = two files the operator places
on a networked machine and commits (or ships) with the scene:

* `<key>.jsonl` -- one JSON object per line: `{"id": "<stable string>",
  "polygon": [[lon, lat], ...] (WGS 84, open or closed ring, at least three
  vertices), "height_m": <number> | null, "height_source": "<word>" | null}`.
  A footprint with no height is extruded to the 6 m default and recorded
  with source `default` and the basis "no CityGML basis" (a stand-in).
* `<key>.provenance.json` -- `source` (the dataset and how it was cut),
  `licence` (one of the allow-list below), `fetched_at` (ISO 8601, or null
  for a synthetic set), `sha256` (of the data file's bytes), `attribution`
  (the text the licence requires), `synthetic` (true for a hand-written
  stand-in), and any URL or query that reproduces the cut.

The run reads the cache only. Nothing is fetched during a run; no OSM is
used anywhere (the Overpass and tile hosts are unreachable from the build
container and ODbL share-alike would bind the dataset). Refusals by name:
`buildings.uncached` (either file absent), `buildings.licence` (a licence
outside the allow-list), `buildings.unverified` (the data file's digest is
not the sidecar's), `buildings.ids` (an id missing, empty, not a string or
stated twice).

## Licence allow-list (`ALLOWED_LICENCES`)

| licence | share-alike | attribution | dataset distribution | AI training | basis |
|---|---|---|---|---|---|
| CDLA-Permissive-2.0 | no | no | yes | yes | Microsoft Building Footprints README (verified in the blueprint's research session); the licence text itself unverified here |
| CC-BY-4.0 | no | yes | yes | not stated | Google Open Buildings (CC BY 4.0 / ODbL, unverified here) |
| ODbL-1.0 | yes | yes | yes (share-alike) | not stated | Overture / Open Buildings alternative (unverified here) |
| CC0-1.0 | no | no | yes | yes | public-domain dedication |
| synthetic | no | no | yes | yes | a hand-written stand-in; the sidecar says `synthetic: true` |

The verdict for the set's licence rides into the buildings document, the
capture manifest's `scene.buildings` record and the run card's `world`
block. "not stated" is recorded as null, never as yes.

## Making a set (the networked step)

1. On a machine that reaches the source, cut the footprints inside the
   bake's bounding box (the bake sidecar's `provenance.bbox_deg`, or
   `core.terrain.landcover.bbox_for_grid` for a bake without one) into
   `<key>.jsonl`, one object per line, ids taken from the source (never
   generated).
2. Write the sidecar with `sha256sum <key>.jsonl` and the licence word.
3. State `scene.buildings: <key>` in the spec; `flightsim.capture` extrudes
   the set over the bake into `<bake>_buildings.json` (LoD1 blocks on the
   DTM pad, the height-source histogram, the vintage fraction) and composes
   the `building:all` object.

`core.scene.buildings.write_fixture_set` writes a synthetic set with a
correct sidecar (the tests use it); it is the same two files.
