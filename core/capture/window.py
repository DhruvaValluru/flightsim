"""The flight window a capture solves and checks over.

The web app's single run caps its clip at ``webapp.runs.CLIP_SECONDS``
while the spec keeps its own duration; ``flightsim.capture --clip-seconds``
applies the same cut, so a campaign case (the CLI path) flies, solves and
checks the window POST /run does instead of the spec's whole duration
(measured, packet A10-2: a 120 s default duration over the 24 km
grand_canyon bake put 608 of 1155 chase poses off the raster while the
single run's 22 s clip of the same card rendered whole).
"""
from typing import Dict, Optional


def clip_columns(columns: Dict, duration_s: Optional[float]) -> Dict:
    """The recorded flight, cut to the window the host will actually fly.

    The web run caps its clip at CLIP_SECONDS while the SPEC keeps its
    own duration, and the headless pre-run flies the spec's. Solving
    capture schedules over the full flight therefore laid capture
    instants out past the end of the clip, and the render commandlet
    refused -- correctly, and only once it had flown:

        consume-poses: emitted 3 of the 4 scheduled images; the run
        ended before the schedule did, so the manifest would name
        frames that do not exist

    A manifest naming frames that cannot exist is the exact failure this
    phase is about, so the schedule is cut to fit the flight rather than
    the flight stretched to fit the schedule. The CLI never hit this
    because it caps nothing: its host flies the spec's own duration.
    """
    if duration_s is None:
        return columns
    times = [float(t) for t in columns["t"]]
    keep = sum(1 for t in times if t <= duration_s)
    if keep >= len(times) or keep < 2:
        return columns
    return {name: list(values)[:keep] for name, values in columns.items()}
