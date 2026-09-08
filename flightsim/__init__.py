"""The flightsim command surface: thin entry points over core/.

``python -m flightsim.capture``  -- validate, run headlessly, solve
camera geometry, schedule captures, write the capture manifest and
geometry previews (rendering only where the UE half exists; refused by
name -- ue.platform -- everywhere else).

``python -m flightsim.verify``   -- the phase's verification summary
over a captured run directory.

``python -m flightsim.demo``     -- THE single verification command:
captures a specification twice with different camera sets and reports
temporal alignment, geometry recovery and cross-view consistency in one
pass/fail summary. Temporal alignment is a statement about two runs, so
it cannot be made from one directory -- this command makes both.

Nothing lives here but argument parsing and wiring: every behaviour is
core/'s, tested there.
"""
