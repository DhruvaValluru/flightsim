"""The roughness inference from land cover (W1, core/environment/surface.py).

The claims under test: two new classes (snow, bare) with z0 'smooth' as a
STATED choice and no thermals; the map from the dominant WorldCover class
to a roughness class; the dominance threshold refusing by name; ROUGHNESS
ONLY (the inferred class attaches no thermals whatever its word's table
row says); provenance 'inferred' naming the tile, the fraction and the
row; a user-stated surface never overridden; the environment.surface
record with its readback and a null test measured on the run; and the
two-flight null pair through core/record_null.run_null_pair on the c172p
at 50 m AGL in 15 kt of wind. The real bakes are measured when present
and skipped by name otherwise; the numbers are in the report.
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import os
from pathlib import Path

import pytest

from core.environment.surface import (
    DOMINANCE_THRESHOLD, EFFECT_CHANNELS, JSBSIM_WIND_PROPERTIES, ROUGHNESS_OF_COVER,
    SURFACE_CLASSES, UNSPECIFIED, InferredRoughnessWind, SurfaceInferenceError,
    infer_surface_for_spec, roughness_only, surface_class, surface_from_landcover,
)
from core.environment.wind import LogProfileWind
from core.messages import name_of
from core.record_null import KT_TO_MPS, run_null_pair
from core.records import JsbsimWrite
from core.registry import EffectChannel, ReadbackTolerance, Registry, VariableRecord
from core.scenario.fields import Quantity
from core.scenario.spec import ScenarioSpec
from core.terrain.landcover import LEGEND, LEGEND_CODES

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples/cameras_waypoint.yaml"

#: The map rows as the blueprint states them.
ROWS_AS_STATED = {10: "forest", 20: "grassland", 30: "grassland", 40: "grassland",
                  100: "grassland", 60: "bare", 70: "snow", 50: "city",
                  80: "ocean", 90: "ocean", 95: "ocean"}
#: The z0 each row lands on (LogProfileWind.ROUGHNESS_M keys).
Z0_KEY_AS_STATED = {"forest": "forest", "grassland": "open", "bare": "smooth", "snow": "smooth",
                    "city": "city", "ocean": "water"}


def real_bake_dir() -> Path:
    return Path(os.environ.get("FLIGHTSIM_BAKE_DIR") or (REPO / "runs" / "terrain"))


def write_landcover_json(path: Path, dominant: str, fraction: float, code=None,
                         tiles=("N36W120",)) -> Path:
    """A landcover.json with the keys the inference reads (the I7
    document's shape), the rest of the scene split evenly."""
    keys = {c.key: c.code for c in LEGEND}
    if code is not None:
        keys[dominant] = code
    others = [k for k in keys if k != dominant]
    rest = (1.0 - fraction) / len(others)
    fractions = {k: (fraction if k == dominant else rest) for k in keys}
    document = {
        "classes": [{"code": keys[k], "key": k, "title": k, "rgb": [0, 0, 0],
                     "file": f"{k}_weight.png", "fraction": fractions[k]} for k in keys],
        "fractions": fractions, "nodata_fraction": 0.0, "dominant_class": dominant,
        "source": {"tiles": {stem: {"url": "x"} for stem in tiles}},
        "sha256": "ab" * 32,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def spec_at_50_m(wind_kt: float = 15.0) -> ScenarioSpec:
    """The c172p at 50 m AGL (flat sea-level slab), 80 kt, a 15 kt wind
    from the west, 3 s open loop."""
    spec = ScenarioSpec.read(EXAMPLE)
    spec.set("duration", 3.0)
    spec.set("altitude", 50.0)
    spec.set("airspeed", 80.0)
    spec.set("wind_speed", wind_kt)
    spec.set("wind_direction", 270.0)
    return spec


# -- the two new classes ------------------------------------------------------------

def test_snow_and_bare_take_z0_smooth_as_a_stated_choice_with_no_thermals():
    for word in ("snow", "bare"):
        cls = surface_class(word)
        assert cls is not None and cls.roughness == "smooth"
        assert cls.z0_m == LogProfileWind.ROUGHNESS_M["smooth"] == 0.005
        assert cls.thermals is None
        assert "no convective thermals" in cls.thermal_basis
        assert "stated choice" in cls.description
    assert "no snow row" in SURFACE_CLASSES["snow"].description
    assert "Table 9-6" in SURFACE_CLASSES["snow"].description


def test_the_validator_accepts_the_new_words_and_still_refuses_an_unmodelled_one():
    from core.scenario.validate import validate

    for word in ("snow", "bare"):
        spec = ScenarioSpec.read(EXAMPLE)
        spec.set("surface", word, frm="test")
        report = validate(spec, check_feasibility=False)
        assert [v.constraint for v in report.violations] == [], word
    spec = ScenarioSpec.read(EXAMPLE)
    spec.set("surface", "tundra", frm="test")
    report = validate(spec, check_feasibility=False)
    assert [v.constraint for v in report.violations] == ["environment.surface"]


# -- the map ----------------------------------------------------------------------------

def test_the_roughness_map_covers_the_legend_with_the_stated_rows():
    assert ROUGHNESS_OF_COVER == ROWS_AS_STATED
    assert set(ROUGHNESS_OF_COVER) == set(LEGEND_CODES)
    for code, word in ROUGHNESS_OF_COVER.items():
        assert SURFACE_CLASSES[word].roughness == Z0_KEY_AS_STATED[word], code
        assert SURFACE_CLASSES[word].roughness in LogProfileWind.ROUGHNESS_M


def test_the_inference_names_the_tile_the_fraction_and_the_row(tmp_path):
    path = write_landcover_json(tmp_path / "landcover.json", "tree_cover", 0.6866)
    inferred = surface_from_landcover(path)
    assert inferred.word == "forest" and inferred.surface.roughness == "forest"
    assert inferred.surface.z0_m == 1.0
    assert inferred.source == "inferred"
    assert inferred.code == 10 and inferred.key == "tree_cover"
    assert inferred.fraction == pytest.approx(0.6866)
    assert inferred.tile == "N36W120" and inferred.sha256 == "ab" * 32
    assert "N36W120" in inferred.frm and "0.6866" in inferred.frm
    assert "10 -> 'forest' -> z0 'forest' = 1.0 m" in inferred.frm
    assert "Table 9-6" in inferred.std
    assert inferred.threshold == DOMINANCE_THRESHOLD == 0.5


@pytest.mark.parametrize("dominant,word,z0", [
    ("grassland", "grassland", 0.03), ("shrubland", "grassland", 0.03),
    ("cropland", "grassland", 0.03), ("moss_lichen", "grassland", 0.03),
    ("bare_sparse", "bare", 0.005), ("snow_ice", "snow", 0.005), ("built_up", "city", 2.0),
    ("permanent_water", "ocean", 0.0002), ("herbaceous_wetland", "ocean", 0.0002),
    ("mangroves", "ocean", 0.0002)])
def test_every_row_lands_on_its_class(tmp_path, dominant, word, z0):
    inferred = surface_from_landcover(
        write_landcover_json(tmp_path / "landcover.json", dominant, 0.75))
    assert inferred.word == word and inferred.surface.z0_m == z0
    assert inferred.surface.thermals is None


# -- the threshold and the refusals ------------------------------------------------------

def test_a_dominant_class_below_half_the_scene_refuses_landcover_surface_inference(tmp_path):
    path = write_landcover_json(tmp_path / "landcover.json", "tree_cover", 0.49)
    with pytest.raises(SurfaceInferenceError) as err:
        surface_from_landcover(path)
    assert name_of(err.value) == "landcover.surface_inference"
    assert "0.4900" in err.value.message and "0.5" in err.value.message
    # Exactly the threshold passes: "at least".
    assert surface_from_landcover(
        write_landcover_json(tmp_path / "half.json", "tree_cover", 0.5)).word == "forest"


def test_a_dominant_code_with_no_row_and_an_unreadable_file_refuse_by_name(tmp_path):
    path = write_landcover_json(tmp_path / "landcover.json", "tree_cover", 0.9, code=37)
    with pytest.raises(SurfaceInferenceError) as err:
        surface_from_landcover(path)
    assert name_of(err.value) == "landcover.surface_inference"
    assert "37" in err.value.message
    with pytest.raises(SurfaceInferenceError) as err:
        surface_from_landcover(tmp_path / "absent.json")
    assert name_of(err.value) == "landcover.surface_inference"
    (tmp_path / "empty.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SurfaceInferenceError):
        surface_from_landcover(tmp_path / "empty.json")


# -- roughness only -------------------------------------------------------------------------

def test_the_inferred_class_carries_no_thermals_whatever_the_table_says(tmp_path):
    """forest's table row attaches the TM's October proxy; the inferred
    forest attaches nothing -- roughness only. Same for city (April)."""
    assert SURFACE_CLASSES["forest"].thermals is not None
    forest = surface_from_landcover(write_landcover_json(tmp_path / "f.json", "tree_cover", 0.7))
    assert forest.surface.thermals is None
    assert "roughness only" in forest.surface.thermal_basis
    assert forest.surface.roughness == SURFACE_CLASSES["forest"].roughness
    city = surface_from_landcover(write_landcover_json(tmp_path / "c.json", "built_up", 0.7))
    assert city.surface.thermals is None and city.surface.z0_m == 2.0
    assert roughness_only(SURFACE_CLASSES["desert"]).thermals is None
    assert forest.provenance()["thermals"] is None
    assert "roughness_only" in forest.provenance()


# -- the runner's gate: user beats inferred ----------------------------------------------------

def test_a_stated_surface_is_never_overridden_and_the_default_is_inferred(tmp_path):
    path = write_landcover_json(tmp_path / "landcover.json", "tree_cover", 0.7)
    spec = ScenarioSpec.read(EXAMPLE)
    assert str(spec.surface.value) == UNSPECIFIED and str(spec.surface.source) == "default"
    assert infer_surface_for_spec(spec, path).word == "forest"
    assert infer_surface_for_spec(spec, None) is None            # no land cover at hand
    spec.set("surface", "desert", frm="the user said desert")   # source user
    assert infer_surface_for_spec(spec, path) is None
    spec.set("surface", UNSPECIFIED, frm="the user said no surface")
    assert infer_surface_for_spec(spec, path) is None            # a stated 'unspecified' holds
    prompt = ScenarioSpec.read(EXAMPLE)
    prompt.surface = Quantity.inferred("grassland", frm="ground cover 'prairie'")
    assert infer_surface_for_spec(prompt, path) is None          # the prompt's word holds too


# -- the record on a real flight ---------------------------------------------------------------

@pytest.fixture(scope="module")
def inferred_flight(tmp_path_factory):
    """The c172p at 50 m AGL in 15 kt from the west for 3 s with the
    inferred forest roughness carrying the wind (the stack the runner
    builds for an inferred surface), recorded."""
    from core.environment.stack import EnvironmentStack
    from core.environment.turbulence import DrydenTurbulence
    from core.fdm import units as u
    from core.scenario.runner import SURFACES, configure_from_spec
    from core.telemetry.recorder import Recorder

    path = write_landcover_json(tmp_path_factory.mktemp("lc") / "landcover.json",
                                "tree_cover", 0.6866)
    spec = spec_at_50_m()
    inferred = infer_surface_for_spec(spec, path)
    provider = InferredRoughnessWind(inferred, u.kt_to_mps(15.0), 270.0)
    stack = EnvironmentStack([provider, DrydenTurbulence("none", seed=1)])
    with contextlib.redirect_stdout(io.StringIO()):
        fdm = configure_from_spec(spec, stack)
        stack.configure(fdm)
        recorder = Recorder(fdm, interval_s=0.1, extra=SURFACES)
        recorder.sample(force=True)
        stack.run_for(fdm, 3.0, recorder)
    return spec, inferred, provider, stack, fdm, recorder


@pytest.mark.timeout(300)
def test_the_record_carries_the_readback_the_writes_and_a_measured_null_test(inferred_flight):
    """Measured here: the profile writes 10.29 kt at 50 m AGL over z0 1.0 m
    against the spec's 15 kt -- 4.71 kt, above the stated 0.5 kt."""
    spec, inferred, provider, stack, fdm, recorder = inferred_flight
    (record,) = stack.applied_variables()
    assert record.name == "environment.surface"
    assert record.value == "forest" and record.unit == "word" and record.source == "inferred"
    assert record.frm == inferred.frm and "Table 9-6" in record.std
    assert record.readback.property == "log_profile_wind.z0_m"
    assert record.readback.value == 1.0 == record.readback.written and record.readback.agrees
    assert record.properties_written == JSBSIM_WIND_PROPERTIES
    assert [w.property for w in record.jsbsim_writes] == list(JSBSIM_WIND_PROPERTIES)
    assert all("every step" in w.when for w in record.jsbsim_writes)
    assert record.telemetry_columns == EFFECT_CHANNELS
    assert set(EFFECT_CHANNELS) <= set(recorder.columns)          # recorded, not asserted
    null = record.null_test
    assert null.kind == "reached" and null.unit == "kt" and null.threshold == 0.5
    assert null.without_value == pytest.approx(15.0)
    expected_with = 15.0 * math.log(50.0 / 1.0) / math.log(300.0 / 1.0)
    assert null.with_value == pytest.approx(expected_with, rel=1e-6)
    assert abs(null.difference) == pytest.approx(4.712, abs=0.01) and null.ok
    assert record.parameters["dominant_fraction"] == pytest.approx(0.6866)
    assert record.parameters["thermals"] is None
    assert record.model.parameters["z0_m"] == 1.0
    assert any("roughness only" in s for s in record.not_claimed)
    d = record.to_dict()
    assert d["from"] == inferred.frm and d["readback"]["agrees"] is True
    # The stack attached no thermals: roughness only reached the FDM.
    assert [p.__class__.__name__ for p in stack.providers] == ["InferredRoughnessWind",
                                                               "DrydenTurbulence"]
    assert stack.provenance()[0]["inferred_surface"]["source"] == "inferred"
    # The recorded wind at the aircraft is the profile's, not the spec's.
    assert recorder.columns["wind_speed_mps"][1] == pytest.approx(expected_with * KT_TO_MPS, rel=1e-4)   # the AGL drifts by centimetres in 0.1 s
    assert recorder.columns["agl_m"][0] == pytest.approx(50.0, abs=0.01)


@pytest.mark.timeout(300)
def test_the_wind_properties_read_back_exact_before_and_after_a_step(inferred_flight):
    """The registry's readback tolerance for the wind writes (0, absolute):
    measured on the trimmed c172p -- written 12.5 fps, read 12.5 before
    and after three steps, the total-wind channel 12.5 (no turbulence)."""
    spec, inferred, provider, stack, fdm, recorder = inferred_flight
    for prop in JSBSIM_WIND_PROPERTIES:
        fdm.props.set(prop, 12.5)
        assert fdm.props.get(prop) == 12.5
        with contextlib.redirect_stdout(io.StringIO()):
            for _ in range(3):
                fdm.step()
        assert fdm.props.get(prop) == 12.5
        assert fdm.props.get(prop.replace("wind-", "total-wind-")) == 12.5


def test_a_record_before_any_step_is_refused(tmp_path):
    inferred = surface_from_landcover(write_landcover_json(tmp_path / "l.json", "tree_cover", 0.7))
    provider = InferredRoughnessWind(inferred, 7.7, 270.0)
    with pytest.raises(ValueError, match="never called"):
        provider.applied_variable()


# -- the two-flight null pair -------------------------------------------------------------------

def surface_registry() -> Registry:
    """The environment.surface entry as the integration patch registers
    it: null the unstated default word, the recorded wind channels."""
    return Registry((VariableRecord(
        name="environment.surface", spec_path="environment.surface", unit="word",
        jsbsim_writes=tuple(JsbsimWrite(p, "every step") for p in JSBSIM_WIND_PROPERTIES),
        effect_channels=tuple(EffectChannel(c, "m/s") for c in EFFECT_CHANNELS),
        null_value=UNSPECIFIED, null_basis="the unstated default: no surface coupling",
        readback_tolerance=ReadbackTolerance(0.0, "absolute", "measured exact on the c172p")),))


@pytest.mark.timeout(600)
def test_the_null_pair_inferred_forest_against_unspecified_moves_the_wind_by_over_half_a_knot(tmp_path):
    """core/record_null.run_null_pair on the c172p at 50 m AGL, 15 kt from
    the west, 3 s: the inferred word 'forest' (through the SAME
    LogProfileWind path the runner takes for a stated word) against the
    unstated 'unspecified' (the steady wind). Measured here: wind_speed_mps
    peak 2.4241 m/s = 4.712 kt (10.288 kt with, 15.0 kt without), the
    output digests differ, ~4 s for the pair."""
    inferred = surface_from_landcover(write_landcover_json(tmp_path / "l.json", "tree_cover", 0.6866))
    spec = spec_at_50_m()
    spec.surface = Quantity.inferred(inferred.word, frm=inferred.frm, std=inferred.std)
    assert spec.to_dict()["environment"]["surface"]["source"] == "inferred"
    with contextlib.redirect_stdout(io.StringIO()):
        pair = run_null_pair(spec, "environment.surface", registry=surface_registry())
    assert pair.verdict == "reached" and pair.digests_differ
    effect = {e.channel: e for e in pair.effects}
    peak_kt = effect["wind_speed_mps"].peak_abs / KT_TO_MPS
    assert peak_kt >= 0.5
    assert peak_kt == pytest.approx(4.712, abs=0.02)
    assert effect["wind_speed_mps"].without_at_peak == pytest.approx(15.0 * KT_TO_MPS, rel=1e-6)
    assert effect["wind_east_mps"].peak_abs == pytest.approx(effect["wind_speed_mps"].peak_abs, rel=1e-6)
    assert effect["wind_north_mps"].peak_abs == pytest.approx(0.0, abs=1e-9)
    assert pair.null_value == UNSPECIFIED
    print(f"null pair c172p 50 m AGL 15 kt: {peak_kt:.3f} kt, {pair.elapsed_s:.1f} s")


# -- the real bakes, when present -----------------------------------------------------------------

def test_yosemite_infers_forest_and_grand_canyon_refuses_by_name():
    """Measured here: Yosemite tree cover 0.6866 -> forest, z0 1.0 m; Grand
    Canyon tree cover 0.3015 < 0.5 -> landcover.surface_inference."""
    yosemite = real_bake_dir() / "yosemite_landcover" / "landcover.json"
    canyon = real_bake_dir() / "grand_canyon_landcover" / "landcover.json"
    if not (yosemite.is_file() and canyon.is_file()):
        pytest.skip(f"the real bakes' land cover is not at {real_bake_dir()}; nothing measured here")
    inferred = surface_from_landcover(yosemite)
    assert inferred.word == "forest" and inferred.surface.z0_m == 1.0
    assert inferred.fraction == pytest.approx(0.6866, abs=0.0005)
    assert inferred.tile == "N36W120" and inferred.surface.thermals is None
    with pytest.raises(SurfaceInferenceError) as err:
        surface_from_landcover(canyon)
    assert name_of(err.value) == "landcover.surface_inference"
    assert "0.3015" in err.value.message


def test_nothing_visual_or_seasonal_is_read_by_the_inference():
    """The inference reads the land cover document and the surface table
    only: no season, vegetation, snowline or look module is imported."""
    text = (REPO / "core" / "environment" / "surface.py").read_text(encoding="utf-8")
    imports = [line for line in text.splitlines() if line.startswith(("from ", "import "))]
    for line in imports:
        for forbidden in ("weather_visuals", "vegetation", "scene", "capture", "render"):
            assert forbidden not in line, line
    assert text.isascii()


# -- the runner (integrated): inference is an offer, never a refusal of the flight ----------------

def test_the_runner_infers_a_dominant_class_and_otherwise_flies_the_default_and_says_why(tmp_path):
    """A scene the map cannot read (no class holds half of it) is not a
    refusal of a flight whose user stated no surface: the default surface
    flies in the spec's wind and the reason is carried beside the
    providers' provenance (the manifest's environment block)."""
    from core.environment.wind import SteadyWind
    from core.scenario.runner import environment_for

    spec = ScenarioSpec.read(EXAMPLE)
    spec.set("wind_speed", 15.0, frm="test")
    canyon = write_landcover_json(tmp_path / "canyon.json", "tree_cover", 0.49)
    stack = environment_for(spec, landcover_json=canyon)
    assert not any(isinstance(w, InferredRoughnessWind) for w in stack.wind)
    assert any(isinstance(w, SteadyWind) for w in stack.wind)
    assert len(stack.notes) == 1
    note = stack.notes[0]
    assert note["constraint"] == "landcover.surface_inference" and note["applied"] is False
    assert "0.49" in note["reason"]
    assert stack.provenance()[-1] == note                 # the manifest carries it
    forest = write_landcover_json(tmp_path / "forest.json", "tree_cover", 0.7)
    stack = environment_for(spec, landcover_json=forest)
    assert stack.notes == []
    assert sum(isinstance(w, InferredRoughnessWind) for w in stack.wind) == 1
    spec.set("surface", "desert", frm="test")               # a stated surface: never overridden
    stack = environment_for(spec, landcover_json=forest)
    assert stack.notes == [] and not any(isinstance(w, InferredRoughnessWind) for w in stack.wind)
