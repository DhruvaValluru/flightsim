"""Gate 5's comparison: the same scenario, two hosts, one verdict.

The regression that matters here is not a physics bug. It is that the two
recorders sample at *different actual periods* -- the headless one schedules the
next sample from the time of the last, and loses a step every time the FDM clock
lands just short of the deadline, so its nominal 0.1 s comes out at ~0.1075 s;
the UE one counts a float accumulator down against the frame time and hits 0.1 s
exactly. Comparing the two arrays by index compares 60 s of one run against 56 s
of the other and reports the skew as a physics divergence.

Everything below exists to make sure the gate cannot pass on evidence that does
not support it: not on a partial UE run, not on a trajectory with no clock, and
not on a genuine divergence that happens to sit at a convenient index.
"""

import json

import pytest

from experiments.gate5_ue_parity import (
    COMPARED, MIN_OVERLAP_FRACTION, SAMPLE_INTERVAL_S, TOLERANCE, compare,
    reference_spec, write_run_card,
)


def trajectory(path, period, duration, *, offset=0.0, start=None):
    """A straight, boring trajectory sampled at ``period``.

    Every compared channel is a distinct constant plus ``offset``, so a
    comparison that silently drops a channel or crosses two of them shows up.
    """
    start = period if start is None else start
    times = []
    t = start
    while t <= duration + 1e-9:
        times.append(t)
        t += period
    columns = {"t": times}
    for i, channel in enumerate(COMPARED):
        columns[channel] = [float(i) + offset for _ in times]
    path.write_text(json.dumps({"host": "test", "samples": len(times),
                                "interval_s": period, "columns": columns}), encoding="utf-8")
    return path


# -- the time base -------------------------------------------------------


def test_compare_uses_the_recorded_clock_not_the_sample_index(tmp_path):
    """Two hosts flying identically, sampling at different real periods.

    Values are constant, so any difference the comparison reports is skew it
    invented. With index-wise comparison this case would still pass, because
    the values are constant -- the point of the constants is that the *sample
    counts* differ by 7% and the comparison must not care.
    """
    a = trajectory(tmp_path / "headless.json", 0.1075, 60.0)
    b = trajectory(tmp_path / "unreal.json", 0.1, 60.0)
    assert len(json.loads(a.read_text(encoding="utf-8"))["columns"]["t"]) != \
           len(json.loads(b.read_text(encoding="utf-8"))["columns"]["t"])

    results, overlap = compare(a, b)
    assert overlap.ok
    assert all(r.ok for r in results)
    assert all(r.max_difference == 0.0 for r in results)


def test_index_alignment_would_have_reported_a_divergence_that_is_not_there(tmp_path):
    """The bug this comparison exists to avoid, demonstrated on a ramp.

    A channel that *changes* with time is where index alignment does damage: by
    the end of the run the two hosts' sample *i* are four seconds apart, and on
    a ramp four seconds is a large number. The gate must read zero here.

    Note what this implies about the gate's own scenario: 60 s of trimmed
    cruise is nearly flat, so index alignment would not have failed it -- it
    would have quietly consumed part of the tolerance budget on skew. A
    scenario that climbs at 3 m/s would have failed outright. The comparison is
    fixed here rather than left to the shape of one scenario.
    """
    def ramp(path, period):
        times, t = [], period
        while t <= 60.0 + 1e-9:
            times.append(t)
            t += period
        columns = {"t": times}
        for channel in COMPARED:
            columns[channel] = [3000.0 + 3.0 * x for x in times]
        path.write_text(json.dumps({"columns": columns}), encoding="utf-8")
        return path

    a, b = ramp(tmp_path / "h.json", 0.1075), ramp(tmp_path / "u.json", 0.1)
    ha = json.loads(a.read_text(encoding="utf-8"))["columns"]
    ub = json.loads(b.read_text(encoding="utf-8"))["columns"]

    # What comparing by index would have said, on identical physics.
    n = min(len(ha["altitude_m"]), len(ub["altitude_m"]))
    by_index = max(abs(ha["altitude_m"][i] - ub["altitude_m"][i]) for i in range(n))
    assert by_index > TOLERANCE["altitude_m"], (
        "the index-wise comparison should have failed this gate on two "
        "identical trajectories -- if it does not, this test proves nothing"
    )

    results, _ = compare(a, b)
    assert all(r.max_difference < 1e-9 for r in results)


def test_the_trim_snapshot_is_graded_and_must_carry_the_wind(tmp_path):
    """Package A reverses the old exemption. The first sample IS the trim
    snapshot, and it is graded: a headless host whose trim state predates
    the wind (288 kt against the engine host's 301 kt, the case this test
    used to forgive) now fails, because that mismatch is the defect --
    the aircraft was trimmed in calm air and hit the wind as a step. With
    the wind in the initial conditions both hosts' first rows agree, and
    nothing after the first row was ever forgiven either.
    """
    def write(path, first_tas):
        times = [round(0.1 * (i + 1), 3) for i in range(100)]
        columns = {"t": times}
        for channel in COMPARED:
            columns[channel] = [0.0] * len(times)
        columns["tas_kt"] = [first_tas] + [301.0] * (len(times) - 1)
        path.write_text(json.dumps({"columns": columns}), encoding="utf-8")
        return path

    a = write(tmp_path / "h.json", 288.0)    # a calm-trim snapshot: the defect
    b = write(tmp_path / "u.json", 301.0)    # wind already in the trim
    results = {r.channel: r for r in compare(a, b)[0]}
    assert not results["tas_kt"].ok
    assert results["tas_kt"].max_difference == pytest.approx(13.0)

    a = write(tmp_path / "h2.json", 301.0)   # both trimmed in the wind
    results = {r.channel: r for r in compare(a, b)[0]}
    assert results["tas_kt"].ok
    assert results["tas_kt"].max_difference < 1e-9


def test_a_divergence_from_the_second_sample_onward_is_not_forgiven(tmp_path):
    """No sample is exempt any more (Package A); this test predates that
    and still holds: a divergence anywhere, early or late, is a divergence."""
    def write(path, tas):
        times = [round(0.1 * (i + 1), 3) for i in range(100)]
        columns = {"t": times}
        for channel in COMPARED:
            columns[channel] = [0.0] * len(times)
        columns["tas_kt"] = tas
        path.write_text(json.dumps({"columns": columns}), encoding="utf-8")
        return path

    a = write(tmp_path / "h.json", [288.0] + [301.0] * 99)
    b = write(tmp_path / "u.json", [301.0] + [288.0] * 99)   # diverges for good
    results = {r.channel: r for r in compare(a, b)[0]}
    assert not results["tas_kt"].ok
    assert results["tas_kt"].max_difference == pytest.approx(13.0)

    # A divergence that lives only in samples 2-4 and then heals is still a
    # divergence. If this passes, "skip the trim snapshot" has quietly grown
    # into "skip the beginning", which is a different and indefensible rule.
    early_a = write(tmp_path / "ha.json", [288.0] + [301.0] * 99)
    early_b = write(tmp_path / "hb.json",
                    [288.0, 295.0, 295.0, 295.0] + [301.0] * 96)
    results = {r.channel: r for r in compare(early_a, early_b)[0]}
    assert not results["tas_kt"].ok


def test_heading_is_compared_on_the_circle_not_the_number_line(tmp_path):
    """Two hosts drift from 0.5 deg through north to 359.5 deg, identically.

    Every raw heading sample near the seam sits on opposite sides of 360 for
    interpolation purposes: one host's samples read 0.01, the other's grid
    time falls between 0.05 and 359.95 and naive interpolation passes through
    180. The physics here is a 1-degree wander; a number-line comparison
    reports up to ~360 degrees of divergence that never happened. This became
    reachable the moment wind cases joined the matrix -- a crosswind case's
    heading wanders across north within the first seconds.
    """
    def drifting(path, period):
        times, t = [], period
        while t <= 20.0 + 1e-9:
            times.append(round(t, 6))
            t += period
        columns = {"t": times}
        for channel in COMPARED:
            columns[channel] = [0.0] * len(times)
        # 0.5 deg -> through 0/360 -> 359.5 deg, smoothly. The seam is crossed
        # at t = 10.0 exactly.
        columns["heading_deg"] = [(0.5 - 0.05 * x) % 360.0 for x in times]
        path.write_text(json.dumps({"columns": columns}), encoding="utf-8")
        return path

    # Periods chosen so a grid point PROVABLY lands inside the other host's
    # seam-straddling interval: 77 * 0.13 = 10.01, inside host B's (10.0,
    # 10.1). Convenient periods can miss the seam by luck, and a test that
    # depends on luck tests nothing.
    a = drifting(tmp_path / "h.json", 0.13)
    b = drifting(tmp_path / "u.json", 0.1)
    results = {r.channel: r for r in compare(a, b)[0]}
    assert results["heading_deg"].max_difference < 0.01, (
        "identical headings crossing north were reported as divergent -- the "
        "comparison is back on the number line"
    )


def test_a_real_heading_divergence_near_the_seam_is_still_reported(tmp_path):
    """The wrap handling must not also forgive genuine disagreement."""
    def steady(path, heading):
        times = [round(0.1 * (i + 1), 3) for i in range(50)]
        columns = {"t": times}
        for channel in COMPARED:
            columns[channel] = [0.0] * len(times)
        columns["heading_deg"] = [heading % 360.0] * len(times)
        path.write_text(json.dumps({"columns": columns}), encoding="utf-8")
        return path

    a = steady(tmp_path / "h.json", 359.2)
    b = steady(tmp_path / "u.json", 1.8)      # 2.6 deg apart, across the seam
    results = {r.channel: r for r in compare(a, b)[0]}
    assert results["heading_deg"].max_difference == pytest.approx(2.6, abs=1e-6)
    assert not results["heading_deg"].ok


def test_compare_refuses_a_trajectory_with_no_clock(tmp_path):
    a = trajectory(tmp_path / "headless.json", 0.1, 10.0)
    columns = json.loads(a.read_text(encoding="utf-8"))["columns"]
    del columns["t"]
    b = tmp_path / "unreal.json"
    b.write_text(json.dumps({"columns": columns}), encoding="utf-8")

    with pytest.raises(ValueError, match="common time base"):
        compare(a, b)


# -- a divergence is still a divergence ----------------------------------


def test_compare_reports_a_real_divergence(tmp_path):
    a = trajectory(tmp_path / "headless.json", 0.1, 10.0)
    b = trajectory(tmp_path / "unreal.json", 0.1, 10.0, offset=100.0)

    results, _ = compare(a, b)
    assert not any(r.ok for r in results)
    for result in results:
        assert result.max_difference == pytest.approx(100.0)


def test_compare_reports_the_peak_divergence_of_one_channel_only(tmp_path):
    """A divergence in one channel must not be smeared across the others.

    The reference is drifting too, so the peak difference against a reference
    that ends at 3000.2 m is 3050.0 - 3000.2 = 49.8, not 50.
    """
    def write(path, altitude):
        columns = {"t": [0.1, 0.2, 0.3]}
        for channel in COMPARED:
            columns[channel] = [0.0] * 3
        columns["altitude_m"] = altitude
        columns["tas_kt"] = [250.0] * 3
        path.write_text(json.dumps({"columns": columns}), encoding="utf-8")
        return path

    a = write(tmp_path / "a.json", [3000.0, 3000.1, 3000.2])
    same = write(tmp_path / "b.json", [3000.0, 3000.1, 3000.2])
    assert all(r.ok for r in compare(a, same)[0])

    diverged = write(tmp_path / "c.json", [3000.0, 3025.0, 3050.0])
    results = {r.channel: r for r in compare(a, diverged)[0]}
    assert not results["altitude_m"].ok
    assert results["altitude_m"].max_difference == pytest.approx(49.8)
    assert results["tas_kt"].ok          # unaffected channels still pass


def test_a_missing_channel_is_infinite_difference_not_a_pass(tmp_path):
    a = trajectory(tmp_path / "headless.json", 0.1, 10.0)
    payload = json.loads(a.read_text(encoding="utf-8"))
    del payload["columns"]["n_z"]
    b = tmp_path / "unreal.json"
    b.write_text(json.dumps(payload), encoding="utf-8")

    results, _ = compare(a, b)
    missing = [r for r in results if r.channel == "n_z"]
    assert missing and not missing[0].ok


# -- partial evidence ----------------------------------------------------


def test_a_truncated_unreal_run_does_not_pass_on_the_part_it_did_fly(tmp_path):
    """The UE run stops at 20 s of a 60 s scenario, and matches perfectly there.

    Every channel comparison passes. The gate must still not, or a host that
    crashes a third of the way in reports parity (§5: no passing on partial
    evidence).
    """
    a = trajectory(tmp_path / "headless.json", 0.1, 60.0)
    b = trajectory(tmp_path / "unreal.json", 0.1, 20.0)

    results, overlap = compare(a, b)
    assert all(r.ok for r in results)
    assert not overlap.ok
    assert overlap.fraction == pytest.approx(20.0 / 60.0, abs=0.01)


def test_the_overlap_requirement_admits_an_honest_run(tmp_path):
    a = trajectory(tmp_path / "headless.json", 0.1075, 60.0)
    b = trajectory(tmp_path / "unreal.json", 0.1, 60.0)
    _, overlap = compare(a, b)
    assert overlap.fraction >= MIN_OVERLAP_FRACTION


# -- the run card --------------------------------------------------------


def test_the_parity_scenario_is_open_loop_and_mass_held_in_both_hosts():
    """Both halves of the gate must fly the same thing.

    hold_state closes a TECS loop that exists only in the headless host; a
    fuel-burning aircraft has no equilibrium and would drift the two hosts
    apart for reasons that are not the integration.
    """
    spec = reference_spec("fly the 747 at 3000 m and 250 kt for 60 seconds")
    assert spec.hold_state.value is False
    assert spec.mass_held.value is True


def test_the_run_card_commands_the_same_scenario_as_the_spec(tmp_path):
    spec = reference_spec("fly the 747 at 3000 m and 250 kt for 60 seconds")
    card = json.loads(write_run_card(spec, tmp_path / "ue_scenario.json").read_text(encoding="utf-8"))

    assert card["spec_digest"] == spec.digest()
    assert card["aircraft"] == str(spec.aircraft.value)
    assert card["altitude_m"] == float(spec.altitude.value)
    assert card["airspeed_kt"] == float(spec.airspeed.value)
    assert card["airspeed_kind"] == str(spec.airspeed_kind.value)
    assert card["heading_deg"] == float(spec.heading.value)
    assert card["latitude_deg"] == float(spec.latitude.value)
    assert card["longitude_deg"] == float(spec.longitude.value)
    assert card["terrain_elevation_m"] == float(spec.terrain_elevation.value)
    assert card["duration_s"] == float(spec.duration.value)
    assert card["rate_hz"] == float(spec.rate.value)
    assert card["mass_held"] is bool(spec.mass_held.value)
    assert card["hold_state"] is bool(spec.hold_state.value)
    # Carried so the commandlet can refuse them, not so it can ignore them.
    assert card["wind_speed_kt"] == float(spec.wind_speed.value)
    assert card["turbulence"] == str(spec.turbulence.value)


def test_the_run_card_asks_for_the_period_the_headless_recorder_uses():
    """The two hosts must be asked for the same recording.

    The headless period lives in core/scenario/runner.py and the UE one in the
    run card. Nothing links them but this constant, so it is checked against
    the runner rather than against itself.
    """
    import inspect

    from core.scenario import runner

    source = inspect.getsource(runner.run_spec)
    assert f"interval_s={SAMPLE_INTERVAL_S}" in source, (
        "core.scenario.runner no longer records at "
        f"{SAMPLE_INTERVAL_S} s; SAMPLE_INTERVAL_S in the gate is now asking "
        "the UE host for a different sampling period"
    )
