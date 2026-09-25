"""The scene package: what the render is GIVEN, computed once in Python.

``weather_visuals`` is the one table from spec values to engine
parameters (contracts §5.4); ``realised_plot`` draws the realised
distribution of a set of runs. Nothing here draws a random number or
reads a spec: the randomisation sampler (``core.scenario.randomization``)
passes plain values in and records what comes back.
"""
