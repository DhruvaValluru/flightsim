# Mac session resume sheet (written 2026-11-04 before a ~1 h connection outage)

Letters: A proving on Windows (open: A7, A13, A10 retry 2 building here); B proving
(B1 B2 B3 PASS, B4 FAIL engine-side, Windows bisects); C pushed 845f014d (C2 C3
PASS, C4 and C7 step 6 with Windows); D: D4, D5 integrated; D2 fix building; D6
built on p3-D6 (37867764), not integrated; A12 retry 2 building.

In flight on the Mac when the connection dropped (each is a Workflow with one fable
builder; if its result is null or empty, read the worktree's `git log`/`git status`:
the commit on the branch is the deliverable):
- A12 retry 2: worktree ../p3-A12r2, branch p3-A12r2, run wf_a91ce06c-bb8
  (sha-gated relocated-bundle lookup in core/capture/verify.py; the fixture now has
  tests/fixtures/engine_bundle_min/cited/* with hashes under GOLDEN.json cited_files,
  so the lookup must read that layout; integrator checks it).
- A10 retry 2: worktree ../p3-A10r2, branch p3-A10r2, run wf_f7ba8c67-a98
  (campaign placement parity with /run, raw llm response recorded, moves shape).
- D2 gear fix: worktree ../p3-D2, branch p3-D2 (merge a98d5258 + fix), run
  wf_56148ae8-c46 (gear split only for a single landing_gear component).

Then, in order: integrate D2 (`bash scripts/phase3_integrate.sh D2 <tests>`), D6
(merge p3-D2 and p3-D4 into p3-D6 first), A12r2, A10r2 (BRANCH=... override);
audit D (letter tests + mutation subset, no suite); push D with
`P3 pushed <c> letter=D boxes=D2 D4 D5 D6` (D1 decided, D3 cut); push A10/A12
retries alone. Letter E breakdown may start any time (decisions 4, 5 exist).

CI on the branch: runs 41885321776, 41885364443, 41885590944, 41885828200,
41890137827, 41891183491, 41891184709, 41893674381, 41893679708 (ebc5ca4d ..
845f014d); read `gh run list -b phase-2-final` and send the three job results of
the first finished run to Windows (B1 step 10, gate rows).

Rules that stuck today: pull with `git pull --no-rebase`; event logs union-merge;
never message a running Workflow agent; builders only via Workflow on fable;
Windows runs only the sheet's check lines; full suite only at phase end.

**Update 2026-11-04 night:** all Mac builds done, F5 written; see docs/PHASE3_REPORT.md for what is open. Stage 7 overlap, phase-end and PR not run.
