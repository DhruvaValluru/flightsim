"""The flightsim command surface: thin entry points over core/.

``python -m flightsim.capture``  -- validate, run headlessly, solve
camera geometry, schedule captures, write the capture manifest and
geometry previews (rendering only where the UE half exists; refused by
name -- ue.platform -- everywhere else).

``python -m flightsim.verify``   -- the phase's verification summary
over a captured run directory.

Nothing lives here but argument parsing and wiring: every behaviour is
core/'s, tested there.
"""
