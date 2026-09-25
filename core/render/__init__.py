"""The render command, built in one place (Phase 2, package A).

``core.render.flags`` is the only module that knows which flags the
FlightSimRender commandlet takes and in which order the harness passes
them. The CLI (``flightsim/capture.py``) and the web app
(``webapp/runs.py``) both build their commands from it, so the two
render paths cannot drift apart again by one of them forgetting a flag
(measured: the CLI never passed ``-mesh=`` and drew placeholder boxes
under a manifest that named the real mesh).
"""
