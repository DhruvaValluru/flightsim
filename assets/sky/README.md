# Star catalogue (physical sky)

`hipparcos_bright.csv` holds 8,870 naked-eye stars (V ≤ 6.5) that have a
Hipparcos (HIP) identifier. `core/sky/plan.py` draws them in the physical
sky. It is derived data, carried under the source's license.

| | |
|---|---|
| Source | HYG star database v4.1, `hyg/CURRENT/hygdata_v41.csv`, from `github.com/astronexus/HYG-Database` (the archive repo; live development continues at `codeberg.org/astronexus/hyg`) |
| Source sha256 | `d9f69fd86bbf90a4e4d52b4c5c53eacfa6dfc0bfdef85bfd94f095e0bebe4ebd` |
| Derived file sha256 | `900f8f16851dbbfde99eb2ba58a65250316b008cd3916143bd72e3f5c7a890b9` |
| License | CC BY-SA 4.0 (David Nash / astronexus). This derived file is shared under the same license. |
| Underlying catalogue | ESA Hipparcos (1997). HYG's positions for HIP stars come from it, at epoch and equinox J2000. |
| Fetched | 2026-09-30 |

## Derivation

1. Keep rows that have a `hip` identifier and `mag` ≤ 6.5. Drop the Sun.
2. Keep these columns: `hip`, `ra` (hours), `dec` (degrees), `mag` (V), `ci` (B−V, blank when unknown) and `proper`.
3. Sort by magnitude.

The file stores J2000 positions. Precession to the render date happens at
runtime (`core.sky.astro.precess_j2000`). Proper motion is ignored; it is
under 30″ over this century for all but a few of these stars, and far below
a rendered pixel.
