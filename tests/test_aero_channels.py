"""The aero panel's channels: recorded at the source, proven to respond.

The aerodynamics panel (web side panel + interactive HUD) displays what the
air is doing TO the aircraft -- the FDM's own aerodynamic state, never a
flow field (JSBSim is coefficient tables, not CFD). These tests pin:

* the channels exist on the SHARED schema: headless ``DEFAULT_CHANNELS``
  and the UE recorder's own channel table (parsed from its source, so the
  two cannot drift apart silently);
* the property-existence discipline (hazard 1, docs/JSBSIM_CORRECTIONS.md
  §3: reading an unknown property fails SILENTLY) -- headless via
  ``REQUIRED_PROPERTIES`` (the observer refuses a model missing one), UE via
  the ``SelftestProperties`` refusal wired into all three hosts;
* the gust null test: alpha and the aero forces MOVE when a discrete gust
  hits and are quiet before -- connection proven by difference, not by
  presence (the Gate 3 pattern);
* the Gate 5 graded channel set does NOT grow: the new channels are
  recorded, not graded, and a test freezes the comparison list.
"""

import re
from pathlib import Path

import pytest

from core.fdm import FlightDynamics, TrimMode
from core.fdm import units as u
from core.fdm.state import REQUIRED_PROPERTIES
from core.telemetry.recorder import DEFAULT_CHANNELS, Recorder

REPO = Path(__file__).resolve().parents[1]
BRIDGE = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge"
RECORDER_CPP = BRIDGE / "Private/FlightSimTelemetryRecorder.cpp"
HOST_SOURCES = (
    BRIDGE / "Private/FlightSimScenarioCommandlet.cpp",
    BRIDGE / "Private/FlightSimRenderCommandlet.cpp",
    BRIDGE / "Private/FlightSimInteractiveMode.cpp",
)

#: The aero block, by column name -- shared between the two recorders.
AERO_CHANNELS = (
    "alpha_deg", "beta_deg", "qbar_pa",
    "f_aero_x_n", "f_aero_y_n", "f_aero_z_n",
    "drag_n", "side_force_n", "lift_n",
    "flight_path_angle_deg",
    "wind_north_mps", "wind_east_mps", "wind_down_mps",
    "v_north_mps", "v_east_mps", "v_down_mps",
)

#: JSBSim property names verified against the LIVE catalog of the pinned
#: JSBSim (2026-08-10; hazard 1 -- never re-guess these). fw* are the FDM's
#: own wind-axis force outputs: fwx drag, fwy side force, fwz lift.
VERIFIED_AERO_PROPERTIES = {
    "alpha_deg": "aero/alpha-deg",
    "beta_deg": "aero/beta-deg",
    "qbar_pa": "aero/qbar-psf",
    "f_aero_x_n": "forces/fbx-aero-lbs",
    "f_aero_y_n": "forces/fby-aero-lbs",
    "f_aero_z_n": "forces/fbz-aero-lbs",
    "drag_n": "forces/fwx-aero-lbs",
    "side_force_n": "forces/fwy-aero-lbs",
    "lift_n": "forces/fwz-aero-lbs",
    "flight_path_angle_deg": "flight-path/gamma-deg",
}

LEVEL = {
    "gamma-deg": 0.0, "phi-deg": 0.0, "psi-true-deg": 0.0, "beta-deg": 0.0,
    "lat-geod-deg": 0.0, "long-gc-deg": 0.0, "terrain-elevation-ft": 0.0,
}


# -- the shared schema ------------------------------------------------------

def test_headless_recorder_carries_the_aero_channels():
    assert set(AERO_CHANNELS) <= set(DEFAULT_CHANNELS)


def test_aero_force_properties_are_required_headless():
    """The observer refuses a model missing one of these at construction --
    the headless half of the property-existence selftest."""
    for prop in ("forces/fbx-aero-lbs", "forces/fby-aero-lbs",
                 "forces/fbz-aero-lbs", "forces/fwx-aero-lbs",
                 "forces/fwy-aero-lbs", "forces/fwz-aero-lbs"):
        assert prop in REQUIRED_PROPERTIES


def _ue_channel_table():
    """Parse the UE recorder's channel table from its source, so schema
    drift between the two recorders fails a test rather than a comparison."""
    text = RECORDER_CPP.read_text()
    rows = re.findall(
        r'\{TEXT\("([^"]+)"\),\s*TEXT\("([^"]+)"\),\s*[^,]+,\s*(true|false)\}',
        text)
    assert rows, "could not parse the UE recorder channel table"
    return {column: (prop, required == "true")
            for column, prop, required in rows}


def test_ue_recorder_table_carries_the_aero_block_with_verified_names():
    table = _ue_channel_table()
    for column, prop in VERIFIED_AERO_PROPERTIES.items():
        assert column in table, f"UE recorder lacks column {column!r}"
        assert table[column][0] == prop, (
            f"UE recorder reads {column!r} from {table[column][0]!r}, not "
            f"the live-verified {prop!r} (hazard 1: do not re-guess names)")
        assert table[column][1], f"aero channel {column!r} must be required"
    for column in AERO_CHANNELS:
        assert column in table


def test_ue_recorder_and_headless_recorder_share_the_aero_schema():
    table = _ue_channel_table()
    shared = set(AERO_CHANNELS)
    assert shared <= set(table)
    assert shared <= set(DEFAULT_CHANNELS)


# -- hazard 1: the selftest is wired into every host ------------------------

def test_ue_hosts_refuse_on_selftest_failure():
    """Each host must call SelftestProperties and REFUSE the run on failure
    -- a missing property records nothing, loudly, never NaN forever."""
    for source in HOST_SOURCES:
        text = source.read_text()
        assert re.search(r"if \(!\w*Recorder->SelftestProperties\(Error\)\)",
                         text), f"{source.name} does not refuse on selftest"


def test_ue_recorder_selftest_reads_the_channel_table():
    """The selftest must iterate the SAME table sampling uses -- a channel
    cannot be sampled without being selftested."""
    text = RECORDER_CPP.read_text()
    selftest = text.split("SelftestProperties", 2)[-1]
    assert "ChannelTable()" in selftest.split("TickComponent")[0]


# -- the graded channel set does not grow -----------------------------------

def test_gate5_graded_channel_set_is_frozen():
    """Replay parity untouched: the new channels are recorded, not graded.
    Extending the graded set is a separate, deliberate decision with its
    own tolerance derivation -- this freeze makes the growth a test failure
    instead of a drive-by."""
    from experiments.gate5_ue_parity import COMPARED

    assert set(COMPARED) == {
        "altitude_m", "tas_kt", "roll_deg", "pitch_deg", "heading_deg",
        "n_z", "lat_deg", "lon_deg",
    }


# -- the gust null test: connection proven by difference --------------------

@pytest.fixture(scope="module")
def trimmed():
    fdm = FlightDynamics("global5000")
    fdm.set_initial_conditions(
        {"h-sl-ft": u.m_to_ft(3000), "vc-kts": 250, **LEVEL})
    fdm.start_engines()
    fdm.trim(TrimMode.LONGITUDINAL)
    return fdm


def _fly(fdm, seconds):
    alphas, lifts = [], []
    for _ in range(int(seconds * fdm.rate_hz)):
        fdm.step()
        state = fdm.state()
        alphas.append(state.alpha_deg)
        lifts.append(state.lift_n)
    return alphas, lifts


def test_aero_channels_respond_to_a_gust(trimmed):
    """Quiet before the gust, moving after it -- a panel whose channels
    cannot be shown to respond to physics is a decoration, not a
    measurement."""
    quiet_alpha, quiet_lift = _fly(trimmed, 2.0)
    quiet_alpha_span = max(quiet_alpha) - min(quiet_alpha)
    quiet_lift_span = max(quiet_lift) - min(quiet_lift)
    mean_lift = sum(quiet_lift) / len(quiet_lift)
    assert quiet_alpha_span < 0.2       # trimmed flight is quiet
    assert quiet_lift_span < 0.02 * abs(mean_lift)

    # A discrete vertical gust: ~6 m/s updraft written into the same wind
    # property the runner writes. At 250 kt this commands roughly a 2.6 deg
    # alpha change -- an order above the quiet span.
    trimmed.props.set("atmosphere/wind-down-fps", -20.0)
    gust_alpha, gust_lift = _fly(trimmed, 2.0)
    gust_alpha_span = max(gust_alpha) - min(gust_alpha)
    gust_lift_span = max(gust_lift) - min(gust_lift)
    assert gust_alpha_span > 1.0
    assert gust_alpha_span > 5.0 * max(quiet_alpha_span, 1e-9)
    assert gust_lift_span > 0.05 * abs(mean_lift)
    assert gust_lift_span > 5.0 * max(quiet_lift_span, 1e-9)


def test_recorder_samples_every_aero_channel_finite(trimmed):
    """The headless recorder resolves every panel channel to a finite value
    in flight -- a renamed state attribute fails here, not in a chart."""
    recorder = Recorder(trimmed, interval_s=0.05)
    recorder.run_for(0.5)
    assert len(recorder) >= 9
    for channel in AERO_CHANNELS:
        values = recorder.series(channel)
        assert values, f"channel {channel!r} recorded nothing"
        assert all(v == v and abs(v) != float("inf") for v in values), (
            f"channel {channel!r} recorded a non-finite value")
