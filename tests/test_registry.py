"""The variable registry (core/registry.py): every introduced variable has
an entry; the refusals by name; the manifest consults it before the
suffix table; the readbacks measured on the c172p; the committed
examples keep their digests.
"""

import contextlib
import io
from pathlib import Path

import pytest

from core.capture.manifest import channel_unit, state_units, suffix_unit
from core.records import JsbsimWrite, Readback
from core.registry import (
    HPA_TO_PSF, NO_NULL, REGISTRY, EffectChannel, ReadbackTolerance, RecordError, Registry,
    UInputRule, VariableRecord, unregistered_fields,
)

REPO = Path(__file__).resolve().parents[1]

BATCH_1 = ("scene.geoid_undulation_m", "limits.monitor", "instruments.profile", "scene.landcover")
PHYSICS = ("atmosphere.temperature_deviation_c", "atmosphere.sea_level_pressure_hpa",
           "atmosphere.dew_point_c", "atmosphere.relative_humidity_pct")
#: The block's fifth field: a word the provider expands into the numeric
#: fields, so it writes no property of its own but is the variable that moved.
WORDS = ("atmosphere.day",)
DATUM = ("datum.vertical", "datum.physics_frame", "datum.geoid_model")
#: P2's injected properties: written after load and held by the property
#: store; the failure authorities and the roll gust have no spec field
#: until their items land (P3's kinds are registered separately; P6/P7
#: gust); P5 gave the icing ones their spec fields (ICING below) and kept
#: the six factors as producer-measured observers (ICING_FACTORS).
INJECTED = ("failures.elevator_authority", "failures.aileron_authority",
            "failures.rudder_authority", "gust.p_equivalent_rad_s")
#: P5: the icing block -- the number (icing.eta reads icing.eta_max), the
#: word, the onset, the ramp, the shift (icing.alpha_shift_rad reads
#: icing.alpha_shift_deg) and the envelope word; the six factors are
#: written every step from eta and the airframe's k-table and have no
#: spec field of their own.
ICING = ("icing.eta", "icing.severity", "icing.onset_s", "icing.ramp_s",
         "icing.alpha_shift_rad", "icing.envelope")
ICING_FACTORS = ("icing.lift_factor", "icing.drag_factor", "icing.side_factor",
                 "icing.roll_factor", "icing.pitch_factor", "icing.yaw_factor")
#: P6: the turbulence model and wind profile blocks, one entry per field (the
#: words included); the model and kind words write the gust / wind channels.
P6 = ("turbulence_model.model", "turbulence_model.intensity", "turbulence_model.seed",
      "wind_profile.kind", "wind_profile.layers", "wind_profile.roughness_ft",
      "wind_profile.fixture")
#: W1: the environment section, claimed whole once environment.surface (the
#: roughness inference's spec field) is registered, so every spec-8 field of
#: it is an entry with its default as the null.
ENVIRONMENT = ("environment.wind_speed", "environment.wind_direction", "environment.turbulence",
               "environment.surface", "environment.weather_date", "environment.weather_event")
#: P3: the failure schedule -- the block's one field (the event list, null
#: the empty list) and the five kinds (no spec field of their own; the
#: producer's measured null tests).
FAILURES = ("failures.events",)
FAILURE_KINDS = ("failures.engine_out", "failures.control_jam", "failures.hardover",
                 "failures.float", "failures.authority_loss")
#: P4: the loading block, one entry per field (payload is one field whose
#: value is the {station: kg} mapping); every write is made once before
#: the trim, the payload read back through cg-x-in against the hand CG.
LOADING = ("loading.payload_kg", "loading.fuel_kg", "loading.fuel_fraction")
#: D2: the dis block, one entry per field; none writes a property or moves a
#: recorded column (the export reads them), nulls are the block's defaults.
DIS = ("dis.site", "dis.application", "dis.entity", "dis.force_id", "dis.marking",
       "dis.timestamp_mode")
#: S1: the scene section claimed whole (nulls the block's defaults; the
#: effect channels are the columns the scene's consumers read) and the
#: four sensing observers (no section.leaf spec field: cameras[i].<field>
#: is a list element; recorded through the manifest's sensing block).
SCENE = ("scene.terrain_source", "scene.terrain", "scene.sun_lux", "scene.buildings")
#: W2: the runway block, one entry per field; none writes a property, the
#: effect channel is agl_m (the flatten pad's heights), nulls the absent
#: block's (no designator = no runway).
RUNWAY = ("runway.designator", "runway.threshold_lat_deg", "runway.threshold_lon_deg",
          "runway.heading_deg", "runway.length_m", "runway.width_m", "runway.surface",
          "runway.markings")
SENSING = ("sensing.radiometry", "sensing.bands", "sensing.optics", "sensing.motion_blur",
           "sensing.ir", "sensing.ir_transmittance")
#: S2: the four derived passes, observers (cameras[i].passes / .stereo are
#: list elements; recorded through the manifest's applied_variables).
PASSES = ("passes.flow", "passes.disparity", "passes.points", "passes.amodal")
#: P7: the wake block, one entry per field (the generator and decay words
#: included); every field drives the four gust / roll-property writes,
#: read back exact; nulls are the block's defaults (no generator = no wake).
WAKE = ("wake.generator", "wake.generator_speed_kt", "wake.lateral_offset_m",
        "wake.vertical_offset_m", "wake.separation_s", "wake.age_s", "wake.model",
        "wake.eps_star", "wake.n_star")
#: R2: the instruments block, one entry per instrument (each a {profile,
#: lever_arm_m} mapping, null = the ideal at the CG; no JSBSim write, the
#: effect channels the meas_* recorder columns the instrument owns) and the
#: record block, one entry per field (no write, no recorded column moved).
INSTRUMENTS = ("instruments.imu", "instruments.gps", "instruments.pitot_static",
               "instruments.magnetometer")
RECORD = ("record.null_tests", "record.convergence", "record.sensitivity_pairs")
#: W3: the night sky (a scene field) and the rain rate (an optional
#: environment field outside ScenarioSpec.FIELD_ORDER), each a bounded
#: invariance on recorded columns, and the world record (an observer: no
#: spec field; its null tests are the render-side predictions).
WORLD_LOOK = ("scene.night", "environment.precipitation_rate_mmh", "scene.world")
#: The render's time of day (visual plan V1 / the physical sky): an
#: optional environment field outside FIELD_ORDER, a bounded invariance.
TIME_OF_DAY = ("environment.time_of_day",)


def _entry(**overrides):
    fields = dict(name="test.thing", spec_path="test.thing", unit="m",
                  null_value=0.0, null_basis="zero is off")
    fields.update(overrides)
    return VariableRecord(**fields)


# -- the population ------------------------------------------------------------

def test_every_batch_1_variable_and_every_physics_variable_is_registered():
    assert set(REGISTRY.names()) == (set(BATCH_1) | set(PHYSICS) | set(WORDS) | set(DATUM)
                                     | set(INJECTED) | set(P6) | set(ENVIRONMENT)
                                     | set(LOADING) | set(FAILURES) | set(FAILURE_KINDS)
                                     | set(ICING) | set(ICING_FACTORS) | set(DIS) | set(WAKE)
                                     | set(SCENE) | set(SENSING) | set(PASSES) | set(RUNWAY)
                                     | set(INSTRUMENTS) | set(RECORD) | set(WORLD_LOOK)
                                     | set(TIME_OF_DAY))
    assert REGISTRY.get("environment.time_of_day").null_value == "none"
    for name in INSTRUMENTS + RECORD:
        entry = REGISTRY.get(name)
        assert entry.spec_path == name and entry.null_value is not NO_NULL
        assert not entry.jsbsim_writes and entry.readback_tolerance is None
        assert entry.effect_channels and entry.null_basis
    assert [c.name for c in REGISTRY.get("instruments.imu").effect_channels] == [
        "meas_n_z", "meas_p_dps", "meas_q_dps", "meas_r_dps"]
    assert REGISTRY.get("instruments.gps").null_value is None
    assert REGISTRY.get("record.null_tests").null_value is False
    assert REGISTRY.get("record.convergence").null_value is None
    assert REGISTRY.get("record.sensitivity_pairs").null_value is False
    for name in RUNWAY:
        entry = REGISTRY.get(name)
        assert entry.spec_path == name and entry.null_value is not NO_NULL
        assert not entry.jsbsim_writes and entry.readback_tolerance is None
        assert [c.name for c in entry.effect_channels] == ["agl_m"] and entry.null_basis
    assert REGISTRY.get("runway.designator").null_value is None
    assert REGISTRY.get("runway.surface").null_value == "asphalt"
    assert REGISTRY.get("scene.buildings").null_value is None
    for name in SCENE:
        entry = REGISTRY.get(name)
        assert entry.spec_path == name and entry.null_value is not NO_NULL
        assert not entry.jsbsim_writes and entry.effect_channels and entry.null_basis
    assert REGISTRY.get("scene.terrain_source").null_value == "auto"
    assert REGISTRY.get("scene.terrain").null_value is None
    assert REGISTRY.get("scene.sun_lux").null_value is None and REGISTRY.get("scene.sun_lux").unit == "lx"
    for name in SENSING + PASSES:
        entry = REGISTRY.get(name)
        assert entry.spec_path is None and entry.null_value is NO_NULL and entry.null_basis
    for name in WAKE:
        entry = REGISTRY.get(name)
        assert entry.spec_path == name and entry.null_value is not NO_NULL
        assert entry.jsbsim_writes and entry.readback_tolerance is not None
        assert entry.effect_channels and entry.null_basis
        assert [w.property for w in entry.jsbsim_writes][-1] == "gust/p-equivalent-rad_sec"
    assert REGISTRY.get("wake.generator").null_value is None
    assert REGISTRY.get("wake.model").null_value == "none"
    for name in DIS:
        entry = REGISTRY.get(name)
        assert entry.spec_path == name and entry.null_value is not NO_NULL
        assert not entry.jsbsim_writes and entry.readback_tolerance is None
        assert [c.name for c in entry.effect_channels] == ["lat_deg", "lon_deg", "hae_m"]
    assert REGISTRY.get("dis.marking").null_value == ""
    assert REGISTRY.get("dis.timestamp_mode").null_value == "relative"
    for name in ICING:
        entry = REGISTRY.get(name)
        assert entry.spec_path.startswith("icing.") and entry.null_value is not NO_NULL
        assert entry.effect_channels and entry.null_basis
    assert REGISTRY.get("icing.eta").spec_path == "icing.eta_max"
    assert REGISTRY.get("icing.eta").null_value == 0.0
    assert REGISTRY.get("icing.alpha_shift_rad").spec_path == "icing.alpha_shift_deg"
    assert REGISTRY.get("icing.severity").null_value is None
    for name in ICING_FACTORS:
        entry = REGISTRY.get(name)
        assert entry.spec_path is None and entry.null_value is NO_NULL
        assert entry.jsbsim_writes and entry.readback_tolerance is not None and entry.null_basis
    events = REGISTRY.get("failures.events")
    assert events.spec_path == "failures.events" and events.null_value == [] and events.unit == "events"
    for name in FAILURE_KINDS:
        entry = REGISTRY.get(name)
        assert entry.spec_path is None and entry.null_value is NO_NULL
        assert entry.jsbsim_writes and entry.readback_tolerance is not None
        assert entry.effect_channels and entry.null_basis
    for name in P6:
        entry = REGISTRY.get(name)
        assert entry.spec_path == name and entry.effect_channels and entry.null_basis
    assert REGISTRY.get("turbulence_model.model").null_value == "dryden"
    assert REGISTRY.get("wind_profile.kind").null_value == "uniform"
    for name in BATCH_1:
        entry = REGISTRY.get(name)
        assert entry.spec_path is None and entry.null_value is NO_NULL
        assert entry.null_basis                     # why there is no spec null, stated
    for name in PHYSICS:
        entry = REGISTRY.get(name)
        assert entry.spec_path == name
        assert entry.jsbsim_writes and entry.readback_tolerance is not None
        assert entry.effect_channels
    for name in WORDS:
        entry = REGISTRY.get(name)
        assert entry.spec_path == name and entry.unit == "word"
        assert not entry.jsbsim_writes and entry.readback_tolerance is None
        assert entry.effect_channels and entry.null_value == "isa"
    for name in DATUM:
        entry = REGISTRY.get(name)
        assert entry.spec_path == name and entry.unit == "word"
        assert not entry.jsbsim_writes and entry.readback_tolerance is None
        assert [c.name for c in entry.effect_channels] == ["undulation_m", "hae_m"]
    assert REGISTRY.get("datum.geoid_model").null_value is None
    for name in INJECTED:
        entry = REGISTRY.get(name)
        assert entry.spec_path is None and entry.null_value is NO_NULL
        assert entry.jsbsim_writes and entry.readback_tolerance is not None
        assert entry.null_basis                     # the neutral value, and why it is neutral
    for name in ENVIRONMENT:
        entry = REGISTRY.get(name)
        assert entry.spec_path == name and entry.null_value is not NO_NULL
        assert entry.effect_channels and entry.null_basis
    surface = REGISTRY.get("environment.surface")
    assert surface.unit == "word" and surface.null_value == "unspecified"
    assert [w.property for w in surface.jsbsim_writes] == [
        "atmosphere/wind-north-fps", "atmosphere/wind-east-fps", "atmosphere/wind-down-fps"]
    assert surface.readback_tolerance.value == 0.0
    for name in LOADING:
        entry = REGISTRY.get(name)
        assert entry.spec_path.startswith("loading.") and entry.null_value is None
        assert entry.jsbsim_writes and entry.readback_tolerance is not None
        assert entry.effect_channels and entry.null_basis
    assert REGISTRY.get("loading.payload_kg").readback_tolerance.value == 0.1
    assert REGISTRY.sections() == ("atmosphere", "datum", "dis", "environment", "failures", "icing",
                                   "instruments", "loading", "record", "runway", "scene",
                                   "turbulence_model", "wake", "wind_profile")
    # Every spec field of the claimed blocks, and every environment quantity
    # of the spec, is claimed: the validator's record.unregistered check is
    # what a stated block meets first.
    from core.scenario.blocks import (
        AtmosphereSpec, DatumSpec, DisSpec, FailuresSpec, IcingSpec, LoadingSpec, TurbulenceModelSpec,
        SceneSpec, WakeSpec, WindProfileSpec,
    )
    from core.scenario.blocks import RunwayBlockSpec
    from core.scenario.blocks import InstrumentsSpec, RecordSpec
    from core.scenario.spec import ScenarioSpec
    assert set(REGISTRY.spec_fields()) == (
        {f"atmosphere.{f}" for f in AtmosphereSpec.FIELD_ORDER}
        | {f"datum.{f}" for f in DatumSpec.FIELD_ORDER}
        | {f"turbulence_model.{f}" for f in TurbulenceModelSpec.FIELD_ORDER}
        | {f"wind_profile.{f}" for f in WindProfileSpec.FIELD_ORDER}
        | {f"loading.{f}" for f in LoadingSpec.FIELD_ORDER}
        | {f"failures.{f}" for f in FailuresSpec.FIELD_ORDER}
        | {f"icing.{f}" for f in IcingSpec.FIELD_ORDER}
        | {f"dis.{f}" for f in DisSpec.FIELD_ORDER}
        | {f"wake.{f}" for f in WakeSpec.FIELD_ORDER}
        | {f"scene.{f}" for f in SceneSpec.FIELD_ORDER}
        | {f"runway.{f}" for f in RunwayBlockSpec.FIELD_ORDER}
        | {f"instruments.{f}" for f in InstrumentsSpec.FIELD_ORDER}
        | {f"record.{f}" for f in RecordSpec.FIELD_ORDER}
        | {f"{sec}.{n}" for sec, n in ScenarioSpec.FIELD_ORDER if sec == "environment"}
        | {"environment.precipitation_rate_mmh", "environment.time_of_day"})
    # W3: scene.world is an observer (no spec field, no spec null).
    assert REGISTRY.get("scene.world").spec_path is None
    assert REGISTRY.get("scene.world").null_value is NO_NULL


def test_the_physics_readback_tolerances_are_the_measured_ones():
    dt = REGISTRY.get("atmosphere.temperature_deviation_c")
    assert dt.jsbsim_writes == (JsbsimWrite("atmosphere/delta-T", "before trim and every step"),)
    assert dt.readback_tolerance.value == 0.0 and dt.readback_tolerance.kind == "absolute"
    psl = REGISTRY.get("atmosphere.sea_level_pressure_hpa")
    assert psl.jsbsim_writes[0].property == "atmosphere/P-sl-psf"
    assert psl.readback_tolerance.value == 0.0
    assert psl.null_value == 1013.25
    rh = REGISTRY.get("atmosphere.relative_humidity_pct")
    assert rh.jsbsim_writes[0].property == "atmosphere/RH"
    assert rh.readback_tolerance.value == 1e-6 and rh.readback_tolerance.kind == "relative"
    assert "Magnus" in rh.readback_tolerance.reason      # the reason is stated
    assert REGISTRY.get("atmosphere.dew_point_c").null_value is None   # absent = dry air
    assert HPA_TO_PSF == pytest.approx(2.08854342, rel=1e-8)


def test_the_registry_serialises_and_lists_its_channels():
    d = REGISTRY.to_dict()
    assert d["atmosphere.temperature_deviation_c"]["readback_tolerance"]["value"] == 0.0
    assert d["scene.geoid_undulation_m"]["has_null_value"] is False
    assert d["atmosphere.dew_point_c"]["has_null_value"] is True
    units = REGISTRY.channel_units()
    assert units["temperature_k"] == "K" and units["density_altitude_m"] == "m"
    assert units["rh_pct"] == "%" and units["pressure_hpa"] == "hPa"
    assert "sigma" not in units          # not a recorded channel: no entry may name it
    assert "density_altitude_m" in REGISTRY.host_channels()
    assert REGISTRY.spec_fields()["atmosphere.temperature_deviation_c"] == "atmosphere.temperature_deviation_c"


# -- the refusals, by name -------------------------------------------------------

def test_an_unknown_variable_refuses_record_unregistered():
    with pytest.raises(RecordError) as err:
        REGISTRY.get("atmosphere.nothing")
    assert err.value.constraint == "record.unregistered"
    assert "atmosphere.nothing" in str(err.value)


def test_a_spec_field_outside_the_registry_refuses_record_unregistered():
    data = {"atmosphere": {"temperature_deviation_c": {"value": 15.0, "source": "user"},
                           "lapse_rate_k_per_km": {"value": 6.5, "source": "user"}}}
    assert unregistered_fields(data) == ["atmosphere.lapse_rate_k_per_km"]
    with pytest.raises(RecordError) as err:
        REGISTRY.require_registered(data)
    assert err.value.constraint == "record.unregistered"
    # A spec that states no claimed section (every spec-8 example) reports nothing.
    assert unregistered_fields({"initial": {"altitude": {"value": 1.0}}}) == []
    assert REGISTRY.stated_variables(data) == {
        "atmosphere.temperature_deviation_c": {"value": 15.0, "source": "user"}}


def test_a_spec_field_variable_without_a_null_value_refuses_record_null_value():
    with pytest.raises(RecordError) as err:
        _entry(null_value=NO_NULL)
    assert err.value.constraint == "record.null_value"
    _entry(spec_path=None, null_value=NO_NULL, null_basis="an observer")   # allowed
    _entry(null_value=None)                                                # absent = null


def test_an_effect_channel_without_a_unit_or_against_its_name_refuses():
    with pytest.raises(RecordError) as err:
        _entry(effect_channels=(EffectChannel("sigma", ""),))
    assert err.value.constraint == "record.effect_channel_unit"
    with pytest.raises(RecordError) as err:
        _entry(effect_channels=(EffectChannel("density_altitude_m", "ft"),))
    assert err.value.constraint == "record.effect_channel_unit"
    assert "says 'm'" in str(err.value)
    _entry(effect_channels=(EffectChannel("sigma", "1"),))                 # no suffix: fine
    _entry(effect_channels=(EffectChannel("density_altitude_m", "m"),))    # agrees: fine


def test_duplicates_and_malformed_entries_are_programming_errors():
    reg = Registry((_entry(),))
    with pytest.raises(ValueError, match="already registered"):
        reg.register(_entry())
    with pytest.raises(ValueError, match="claimed by both"):
        reg.register(_entry(name="test.other"))
    with pytest.raises(ValueError, match="readback tolerance"):
        _entry(jsbsim_writes=(JsbsimWrite("atmosphere/delta-T", "setup"),))
    with pytest.raises(ValueError, match="dotted"):
        _entry(name="thing")
    with pytest.raises(ValueError, match="basis"):
        _entry(null_basis="")
    with pytest.raises(ValueError, match="reason"):
        ReadbackTolerance(0.0, "absolute", "")
    with pytest.raises(ValueError, match="positive"):
        UInputRule(bin_width=0.0)


# -- the manifest consults the registry before the suffix table ------------------

def test_state_units_takes_the_registry_unit_first_and_never_a_question_mark():
    columns = {name: [0.0] for name in REGISTRY.channel_units()}
    columns.update({"t": [0.0], "altitude_m": [1.0]})
    units = state_units(columns)
    assert "?" not in units.values()
    assert units["temperature_k"] == "K" and units["rh_pct"] == "%"
    assert units["vapour_pressure_pa"] == "Pa" and units["pressure_hpa"] == "hPa"
    assert units["any_exceedance_flag"] == "1" and units["nz_pos_flag"] == "1"   # INT-final's names
    assert suffix_unit("vne_or_vmo_flag") == "1"          # read from the name alone now
    assert channel_unit("something_unknown") == "?"        # still a question, not a guess


def test_the_new_unit_suffixes_read_back():
    assert suffix_unit("f_x_mps2") == "m/s^2"
    assert suffix_unit("omega_rads") == "rad/s"
    assert suffix_unit("b_north_ut") == "uT"
    assert suffix_unit("p_sl_hpa") == "hPa"
    assert suffix_unit("t_static_k") == "K"
    assert suffix_unit("rh_pct") == "%"
    assert suffix_unit("rho_kgm3") == "kg/m^3"
    assert suffix_unit("iyy_kgm2") == "kg m^2"        # P4: the pitch-inertia channel
    assert suffix_unit("stall_flag") == "1"
    # A per-second name is never read as seconds (P6's two channels; the
    # registry keeps no table of its own -- this one, longest first).
    assert suffix_unit("gust_p_equivalent_rad_s") == "rad/s"
    assert suffix_unit("shear_dv_dz_per_s") == "1/s"
    assert suffix_unit("wake_gamma_m2_s") == "m^2/s"       # P7: a circulation, never seconds
    # Longest-first: none of the new suffixes shadows an old one.
    assert suffix_unit("v_mps") == "m/s" and suffix_unit("q_rad") == "rad"
    assert suffix_unit("qbar_pa") == "Pa" and suffix_unit("m_kg") == "kg"
    assert suffix_unit("cas_kt") == "kt" and suffix_unit("north_m") == "m"
    assert channel_unit("f_x_mps2") == "m/s^2"


# -- the committed examples keep their digests ------------------------------------

#: Re-pinned at INT-final (spec 9): the examples regenerated by the writer
#: differ from their spec-8 selves by the version line alone, and the
#: version is hashed, so each digest moved once (the spec-8 values are
#: tests/test_versions.py's SPEC8_DIGESTS, still measured from the frozen
#: files under tests/data/spec8_examples).
EXAMPLE_DIGESTS = {
    "examples/cameras_event_trigger.yaml": "cecfcf1a5882d34fd97bdd7cbdbc6a69710d9c7956f835a897fbf1c712ab2ccf",
    "examples/cameras_hazard_refusal.yaml": "bcd32ebe8fed244be2bd8f6761a879b3bbe965c6d3c884fbc65b3deb2b12e9ea",
    "examples/cameras_mountain_refusal.yaml": "d49cbc463d0f402ef39d95b86325d97d6fdfa4fb89ea414ab47e066b949cfe6c",
    "examples/cameras_multi.yaml": "995ec65631ba52092140458c7799eb3c7a6b82a9baa1807f9c017724ae4c5390",
    "examples/cameras_refusal.yaml": "04d38d5b97052b61181530e544df1cb56c3b6037e85e7ffd1ee0e663d398c055",
    "examples/cameras_terrain.yaml": "e57b408868065d75c99ca3711627601c199b43c3d50dd2675ac6e2b1c20b1325",
    "examples/cameras_waypoint.yaml": "aba90b44eae4644a139cf65d8f593cdadd9b78cc320c15f9642d79fb4fee2f00",
    "examples/randomized.yaml": "bc9982ba15a79c63a1c748eacb70efddc753c174532e80735019b48904309428",
    # Phase 2: the first committed example with a traffic block (spec 9).
    "examples/traffic.yaml": "9db4704441d8b82b8901bb0ea5ad1287aae1a1e6c229b956bae807a7fdd28fab",
}


def test_a_spec_that_states_no_registered_field_keeps_its_digest_and_needs_no_record():
    """Absent-canonical: the registry adds no key to a spec, so every
    committed example digests as it did at HEAD 9ec2c31 (measured then,
    pinned here), states the environment section only (W1 registers all
    six of its fields, so nothing is unregistered), and refuses nothing."""
    from core.scenario.spec import ScenarioSpec

    for path, digest in EXAMPLE_DIGESTS.items():
        spec = ScenarioSpec.read(REPO / path)
        assert spec.digest() == digest, path
        data = spec.to_dict()
        # S1: the one example that states a scene block now states a
        # claimed section (scene, its two fields registered); its sun_lux
        # is absent-canonical, so the digest above is unchanged.
        states_scene = "scene" in data
        expected_sections = ["environment", "scene"] if states_scene else ["environment"]
        assert [s for s in REGISTRY.sections() if s in data] == expected_sections, path
        assert unregistered_fields(data) == []
        expected = set(ENVIRONMENT) | ({"scene.terrain_source", "scene.terrain"} if states_scene else set())
        assert set(REGISTRY.stated_variables(data)) == expected, path


# -- the readbacks, measured on the c172p --------------------------------------------

@pytest.mark.timeout(120)
def test_the_physics_readbacks_measure_as_the_registry_declares():
    """Write each registered property on a trimmed c172p, step three
    times, read back: delta-T, P-sl and the pointmass exact; RH within
    the 1e-6 relative tolerance (measured 1.0e-10 here)."""
    from core.scenario.runner import configure_from_spec
    from core.scenario.spec import ScenarioSpec

    spec = ScenarioSpec.read(REPO / "examples/cameras_waypoint.yaml")
    spec.set("duration", 1.0)
    with contextlib.redirect_stdout(io.StringIO()):
        fdm = configure_from_spec(spec)
    cases = [
        ("atmosphere.temperature_deviation_c", "atmosphere/delta-T", 36.0),
        ("atmosphere.sea_level_pressure_hpa", "atmosphere/P-sl-psf", 1000.0 * HPA_TO_PSF),
        ("atmosphere.relative_humidity_pct", "atmosphere/RH", 0.5),
    ]
    readbacks = {}
    for name, prop, written in cases:
        entry = REGISTRY.get(name)
        assert entry.jsbsim_writes[0].property == prop
        fdm.props.set(prop, written)
        with contextlib.redirect_stdout(io.StringIO()):
            for _ in range(3):
                fdm.step()
        readbacks[name] = Readback(prop, fdm.props.get(prop), written,
                                   entry.readback_tolerance.value,
                                   entry.readback_tolerance.kind,
                                   entry.readback_tolerance.reason)
    for name, rb in readbacks.items():
        assert rb.agrees, (name, rb.to_dict())
    assert readbacks["atmosphere.temperature_deviation_c"].difference == 0.0
    assert readbacks["atmosphere.sea_level_pressure_hpa"].difference == 0.0
    rh = readbacks["atmosphere.relative_humidity_pct"]
    assert abs(rh.difference) / 0.5 < 1e-6
    # The W&B station the loading wave will write: exact, measured here too.
    fdm.props.set("inertia/pointmass-weight-lbs[1]", 300.0)
    assert fdm.props.get("inertia/pointmass-weight-lbs[1]") == 300.0
