**Phase 3 — Requirements**

Consolidation, component-level annotation, and a demonstration anyone
can watch

|               |                                                       |
|---------------|-------------------------------------------------------|
| **To / date** | Shashank Aitharaju · Dhruva Valluru · 13 October 2026 |
| **Theme**     | Pull back — refine and consolidate rather than extend |

Phase 3 is deliberately narrower than the two before it. The capability
is largely there; what is missing is the ability for someone other than
the two of you to use it, start to finish, without guidance. Everything
below serves that goal, and anything that does not is out of scope.

1 · Consolidate the capture pipeline

Phase 3 consolidates the capture pipeline into a single, simplified tool
with sane defaults, fewer exposed parameters, and one configuration
path. The measure of success is concrete: **a new student can run a full
capture without reading the workflow notes.** If a step requires knowing
a flag, an environment variable, or a paragraph in NEXT.md, it has not
been consolidated.

In practice: one way to configure a run rather than several, defaults
that produce a working capture when nothing is stated, and parameters
most users never see because the sensible value is already chosen. Where
a setting must stay exposed, it belongs in the interface rather than on
a command line. Reducing the surface is as valuable as any new
capability this phase, and removing a path nobody needs counts as
progress.

2 · New subjects and environments

Add **one or two Chinese aircraft** as new subjects — J-35, J-15 and/or
J-11 — and **one or two environments**, most likely desert and forest.
Run the same pipeline, unchanged, across both. The point is to prove the
pipeline generalises beyond the aircraft and scene it was built around,
not to build a library.

|                                                                                                                                                                                                                                   |
|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Not in scope: full world simulation.** Global terrain, worldwide imagery and large-area streaming are scope creep here. Two representative environments that work reliably are worth more than a world that works occasionally. |

3 · Component-level annotation

Each aircraft should carry **one to two annotated components of interest
— payload first, landing gear second as an option**. These need **2-D
bounding boxes generated automatically during capture**, written into
the label manifest alongside the existing fields. No hand-labelling, and
no separate post-processing pass the user has to remember to run.

That gives us component-level annotation in the dataset itself, ready
for a later training phase. Today the labels describe the aircraft as a
whole and parts exist only as keypoints, which are points rather than
regions. Component boxes close that gap, and they are the one genuinely
new capability this phase asks for.

**Payload — required.** A 2-D box per visible payload, in every frame,
written automatically into the label manifest.

**Landing gear — optional.** The same treatment, if the payload work
lands cleanly within the phase.

Components should follow the existing conventions rather than a parallel
scheme: the same frame record, the same naming and provenance style, the
same handling of objects out of frame or hidden.

4 · The demonstration

The second half of the phase is demonstration. The deliverable is **a
clean end-to-end run that someone can watch: configure, capture, and
label, with no manual intervention and no dependency on tooling versions
we know to be unstable.** A very short video satisfies this part.

"No manual intervention" is meant literally — no importing an asset by
hand first, no editing a file between steps, no flag added to get past a
failure. **Keeping the demo path on a stable toolchain matters more than
using the newest one**: if a newer engine or dependency cannot be relied
on, pin back to what can. A demonstration that runs today on three
machines beats one that will run everywhere after an upgrade.

5 · Close-out

The close-out should include **a short written guide and a recorded
run**, so the pipeline is usable by almost anyone, **with no reliance on
the command line**. The guide should be short enough that someone reads
all of it: what to open, what to type, what to expect, and what the
output contains. Automated tests stay on the command line, as they
should — that is a developer concern, not part of the user path.

What "done" looks like

| **\#** | **Acceptance criterion**                                                                                                                        |
|--------|-------------------------------------------------------------------------------------------------------------------------------------------------|
| 1      | Someone new to the project completes a full capture, start to finish, without reading the workflow notes or asking either of you a question.    |
| 2      | One or two of the J-35 / J-15 / J-11 are available as subjects, and the same pipeline runs unchanged in both new environments (desert, forest). |
| 3      | Payload boxes appear automatically in the label manifest for every frame where the payload is visible, in the existing conventions.             |
| 4      | One end-to-end run — configure, capture, label — completes with no manual steps between, on a pinned toolchain known to work.                   |
| 5      | A short video of that run exists, together with a written guide short enough to be read in full.                                                |
| 6      | Nothing on the user path requires the command line.                                                                                             |

**Sequencing.** Clear the Phase 2 items that block this work first —
chiefly the label record that is never completed from the rendered
bundle, and the build that compiles against no engine anyone has
installed; component boxes are written by the same path that currently
leaves the aircraft's own tight box empty. If something here proves more
expensive than it looks, say so early and we will cut it: the default in
Phase 3 is to do less, and to make what remains work for someone outside
this conversation.
