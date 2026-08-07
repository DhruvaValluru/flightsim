# Phase 6 and Gate 6, as the brief states them

Provenance: the §-numbered brief this repository builds to was delivered in the
session that started the rebuild and was never copied into the tree — every
other gate quotes its clause from that document, and Gate 6 could not be built
until its text was recovered. Extracted verbatim on 2026-08-06 from the
originating session transcript
(`~/.claude/projects/-Users-dhruvavalluru/50e3ffdc-2996-45c0-8537-4b26082c8700.jsonl`).
Nothing below is invented; editorial notes are marked as such.

## Phase 6 — Visual realism (verbatim)

> Settings in §6.6. Priority order — atmosphere and shadows before anything
> else, they close most of the gap:
>
> * Sky Atmosphere + Exponential Height Fog (aerial perspective — the biggest
>   single tell)
> * Directional light shadows via Virtual Shadow Maps; aircraft casts a ground
>   shadow
> * CineCamera with manual exposure
> * MRQ with temporal sub-sampling
> * Land-cover-driven terrain materials; fix foliage (sample the same mesh
>   that renders, reject slopes above threshold)

## GATE 6 (verbatim)

> GATE 6. Side-by-side against the old footage. Distant terrain shows
> range-based extinction. Peaks shadow the valley. The aircraft has a ground
> shadow. Exposure does not breathe when the aircraft banks.

## §6.6 Unreal rendering settings (excerpts relied on)

> **Sky Atmosphere** — the biggest single visual win. Use real Earth values:
> Ground Radius ≈ 6360 km, Atmosphere Height ≈ 60 km. An artistically-shrunk
> planet makes altitude-dependent falloff wrong. Enable Multiscattering (sky
> going black away from the sun is a classic game tell). Directional Light:
> Atmosphere Sun Light = true. SkyLight: Real Time Capture.
> GOTCHA — ground blacks out at altitude/from georeferenced origins: set
> Transmittance Minimum Angle from its default −90° to +90°. GOTCHA — hard
> haze transition line: set Transform Mode to Planet Top at Component
> Transform and move the SkyAtmosphere actor's Z to match actual terrain
> ground level.
>
> **Exponential Height Fog** — primary long-range haze layer. Lower Fog
> Height Falloff extends fog to greater altitude. Set Fog Max Opacity below 1
> so distant terrain keeps faint detail. Use Start Distance to avoid a milky
> look right in front of the camera.
>
> **Shadows — Virtual Shadow Maps.** Directional clipmaps give the range.
> VSM requires Nanite to perform well … If you can't do Nanite, use CSM
> near-field + Distance Field Shadows beyond the Dynamic Shadow Distance
> instead. The aircraft must cast a ground shadow. Its absence was a major
> tell in the old footage.
>
> **CineCamera.** Real filmback values … manual exposure.

## Editorial notes (not the brief)

* "Side-by-side against the old footage" is a human-judgment clause: the gate
  harness produces the side-by-side and measures the four physical clauses
  from the pixels; it does not pretend to judge likeness. The old footage
  lives in `~/FlightScene`.
* "MRQ with temporal sub-sampling" applies to the movie-render path. The gate
  harness renders through the offscreen commandlet, which MRQ does not drive;
  this is recorded as a deviation in `docs/VALIDITY.md` rather than silently
  dropped.
* The foliage and land-cover-material items require content (meshes,
  materials, land-cover data) that does not exist in this repository yet.
  They are Phase 6 work that Gate 6's four measurable clauses do not depend
  on; what is and is not done is tracked in `docs/VALIDITY.md`.
