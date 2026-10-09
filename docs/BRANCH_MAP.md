# Branch map (2026-10-05)

Which branch holds the latest, most complete Phase 2 work, and which
branches are already contained in it.

## The one branch to keep

`phase-2-testing` is the consolidated tip. It now carries the two
chase-camera commits that were previously only on
`claude/magical-dijkstra-7uar9g` (`b323235`, `c06148e`). Nothing from any
other branch is missing from it: every other branch is a strict ancestor.

History is linear, not scattered. `phase-2-testing` was built by merging
each Phase 2 feature branch in turn, then fixing the merged whole, so
there was no "best of each" to pick between: the later branch always
contains the earlier one.

## Containment, branch by branch

| Branch | Last commit | Status |
| --- | --- | --- |
| `claude/magical-dijkstra-7uar9g` | 2026-10-04 | Fully contained (fast-forwarded into `phase-2-testing`). Chase camera settles before the first Tick; `-chase=` on the interactive host; offset derived from the measured mesh. |
| `phase-2-testing` | 2026-10-05 | **Keep.** The Phase 2 integration branch (PR 13). |
| `claude/bold-goodall-a4kyzu` | 2026-09-30 | Fully contained (merged at `11c500f`). Physical sky. |
| `claude/kind-cerf-7ymn77` | 2026-09-30 | Fully contained (merged at `9c8dc6e`). Beauty quality, sun from time of day. |
| `claude/ecstatic-lovelace-mu2w0l` | 2026-09-30 | Fully contained (merged at `46eb33c`). A-4 model + flight model. |
| `phase2` / `claude/relaxed-cori-gccjvx` | 2026-09-29 | Fully contained. The original Phase 2 branch (both names point at `bbe6c13`). |
| `claude/phase-2-brainstorm-xa4ysv` | 2026-09-25 | Fully contained. `CLAUDE.md` and `docs/PHASE2_BRAINSTORM.md` are both on this branch. |
| `phase-one-finished-branch-windows` | 2026-09-11 | Fully contained. Phase 1 on Windows. |
| `master` | 2026-09-01 | Fully contained. Phase 1 base; 176 commits behind. |
| `macos-original` | 2026-08-13 | Fully contained. Pre-Windows ancestor of `master`. |

## What remains open in the code itself

See `docs/PHASE2_SUMMARY.md`, "What remains": the annotation gates still
need a passing real render on the Windows machine, and every C++ change
since the last Windows build (including the two chase-camera commits
above) is uncompiled until that rebuild.
