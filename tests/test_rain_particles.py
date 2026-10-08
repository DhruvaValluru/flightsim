"""The rain the camera sees: the card's rain_particles block
(core/scene/rain_particles.py) and the engine side that draws it
(FlightSimRainParticles.cpp, uncompiled here, so pinned by its text).

Measured here: the block rides the card only with a rain rate, in its fixed
key order; the drawn count grows with the rate in proportion to the visible
drops' density and stays within its budget; the diameter law samples the
truncated Marshall-Palmer distribution (its mean matches the analytic one).
Pinned: the C++ diameter and wrap formulas are the ones re-implemented
here; every card key the C++ reads is one the block writes; the drops are a
beauty-only actor (the label captures hide it); the material and its
parameter are the ones the script creates; the commandlet places the drops
after the camera's pose and before the render-state flush, with the solved
track's velocity.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest

from core.nl.compiler import compile_prompt
from core.scene import rain_particles as rp
from core.scene.precipitation import ATLAS_A, ATLAS_B, ATLAS_C, fitted_lambda

REPO = Path(__file__).resolve().parents[1]
BRIDGE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
RAIN_CPP = (BRIDGE / "Private" / "FlightSimRainParticles.cpp").read_text(encoding="utf-8")
SCENE_CPP = (BRIDGE / "Private" / "FlightSimVisualScene.cpp").read_text(encoding="utf-8")
SCENE_H = (BRIDGE / "Public" / "FlightSimVisualScene.h").read_text(encoding="utf-8")
DIRECTOR_CPP = (BRIDGE / "Private" / "FlightSimCameraDirector.cpp").read_text(encoding="utf-8")
COMMANDLET_CPP = (BRIDGE / "Private" / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
SCRIPT = (REPO / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")


def spec_for(prompt):
    return compile_prompt(prompt)


# -- the block ------------------------------------------------------------------------

def test_the_block_is_in_its_fixed_order_with_the_fitted_lambda():
    block = rp.particle_block(4.0, 11)
    assert tuple(block) == rp.CARD_KEYS
    assert block["lambda_per_mm"] == pytest.approx(fitted_lambda(4.0), abs=1e-6)
    assert block["fall_speed_law"] == [ATLAS_A, ATLAS_B, ATLAS_C]
    assert block["seed"] == 11 and block["box_m"] == rp.BOX_M
    assert block["streak_exposure_s"] == pytest.approx(1.0 / 60.0, abs=1e-6)


def test_heavier_rain_draws_more_drops_within_the_budget():
    counts = [rp.drop_count(rate) for rate in (0.1, 1.0, 4.0, 10.0, 40.0, 200.0)]
    assert counts == sorted(counts)
    assert counts[0] == rp.MIN_DROPS and counts[-1] == rp.MAX_DROPS
    assert rp.drop_count(rp.REFERENCE_RATE_MMH) == rp.MAX_DROPS
    # In proportion to the visible drops' density between the clamps.
    share = (rp.visible_density_per_m3(fitted_lambda(10.0))
             / rp.visible_density_per_m3(fitted_lambda(rp.REFERENCE_RATE_MMH)))
    assert rp.drop_count(10.0) == round(rp.MAX_DROPS * share)


def test_the_visible_density_is_the_truncated_integral():
    lam = fitted_lambda(1.0)
    steps = 200000
    width = (rp.D_MAX_MM - rp.D_MIN_MM) / steps
    numeric = sum(8000.0 * math.exp(-lam * (rp.D_MIN_MM + (i + 0.5) * width)) * width
                  for i in range(steps))
    assert rp.visible_density_per_m3(lam) == pytest.approx(numeric, rel=1e-6)


def test_the_diameter_law_samples_the_truncated_distribution():
    lam = fitted_lambda(4.0)
    assert rp.diameter_mm(0.0, lam) == pytest.approx(rp.D_MIN_MM)
    assert rp.diameter_mm(1.0 - 1e-15, lam) == pytest.approx(rp.D_MAX_MM, rel=1e-6)
    n = 100000
    sampled = sum(rp.diameter_mm((i + 0.5) / n, lam) for i in range(n)) / n
    # The truncated exponential's mean, analytically.
    a, b = rp.D_MIN_MM, rp.D_MAX_MM

    def first_moment(d):
        return -math.exp(-lam * d) * (d / lam + 1.0 / lam ** 2)

    mass = (math.exp(-lam * a) - math.exp(-lam * b)) / lam
    assert sampled == pytest.approx((first_moment(b) - first_moment(a)) / mass, rel=1e-4)


def test_the_card_carries_the_block_only_with_a_rain_rate(tmp_path):
    from core.scenario.card import write_run_card

    dry = spec_for("fly the c172p at 1500 m and 100 kt over the ocean")
    card = json.loads(write_run_card(dry, tmp_path / "a.json").read_text(encoding="utf-8"))
    assert "weather_look" in card and "rain_particles" not in card
    wet = spec_for("fly the c172p at 1500 m and 100 kt in heavy rain")
    card = json.loads(write_run_card(wet, tmp_path / "b.json").read_text(encoding="utf-8"))
    rate = card["weather_look"]["rain_rate_mmh"]
    assert rate and card["rain_particles"] == rp.particle_block(rate, card["weather_look"]["seed"])


# -- the engine side, pinned by text --------------------------------------------------

def _cpp_wrap(value, half):
    period = 2.0 * half
    return value - period * math.floor((value + half) / period)


def test_the_cpp_formulas_are_the_ones_measured_here():
    assert ("return DMinMm - FMath::Loge(1.0 - U * Span) / LambdaPerMm;" in RAIN_CPP
            and "1.0 - FMath::Exp(-LambdaPerMm * (DMaxMm - DMinMm));" in RAIN_CPP)
    assert "return Value - Period * FMath::FloorToDouble((Value + Half) / Period);" in RAIN_CPP
    for value in (-1250.0, -600.0, -0.1, 0.0, 599.9, 600.0, 7300.0):
        wrapped = _cpp_wrap(value, 600.0)
        assert -600.0 <= wrapped < 600.0
        assert (value - wrapped) / 1200.0 == pytest.approx(round((value - wrapped) / 1200.0))
    assert "FMath::Max(LawA - LawB * FMath::Exp(-LawC * DiameterMm), 0.0)" in RAIN_CPP


def test_every_key_the_cpp_reads_is_one_the_block_writes():
    read = set(re.findall(r'RainNumber\(Block, TEXT\("(\w+)"\)', RAIN_CPP))
    read |= set(re.findall(r'TryGetArrayField\(TEXT\("(\w+)"\)', RAIN_CPP))
    assert read and read <= set(rp.CARD_KEYS)
    assert set(rp.CARD_KEYS) - read == {"rate_mmh", "visible_density_per_m3"}   # recorded by Python
    assert 'TryGetObjectField(TEXT("rain_particles")' in RAIN_CPP


def test_the_material_and_its_parameter_are_the_scripts():
    path = re.search(r'RainDropMaterialPath = TEXT\("/Game/FlightSim/(\w+)\.\1"\)', RAIN_CPP)
    assert path and f'_weather_material("{path.group(1)}")' in SCRIPT
    assert "create_rain_drop()\n" in SCRIPT
    parameter = re.search(r'RainDropOpacityParameter = TEXT\("(\w+)"\)', RAIN_CPP).group(1)
    assert f'RAIN_DROP_PARAMETERS = ("{parameter}",)' in SCRIPT
    drop = SCRIPT[SCRIPT.index("def create_rain_drop():"):]
    drop = drop[:drop.index("\n\n\n")]
    assert '"used_with_instanced_static_meshes", True' in drop
    assert "MaterialExpressionPerInstanceCustomData" in drop and "MP_OPACITY" in drop
    assert "RainDrops->SetNumCustomDataFloats(1);" in RAIN_CPP
    assert "SetCustomDataValue(Index, 0, RainCoverage[Index], false);" in RAIN_CPP


def test_the_drops_are_beauty_only_and_never_refused():
    assert RAIN_CPP.count("BeautyOnlyActors.Add(Rain);") == 1
    assert "Label->HiddenActors.Append(VisualScene.BeautyOnlyActors);" in COMMANDLET_CPP
    # Recorded, never refused: no refusal-name prefix, no false return.
    assert not re.search(r'TEXT\("[a-z_]+\.[a-z_]+: ', RAIN_CPP)
    assert "return false;" not in RAIN_CPP
    # The Look lane stops listing the particles as not drawn when they are.
    assert '(Word == TEXT("precipitation_particles") && DrawsRainParticles())' in SCENE_CPP
    assert "no Niagara rain/snow asset" not in SCENE_CPP


def test_build_applies_the_rain_after_the_weather_look():
    look = SCENE_CPP.index("if (!ApplyWeatherLook(World, Options, Error))")
    rain = SCENE_CPP.index("if (!ApplyRainParticles(World, Options, Error))")
    assert look < rain < look + 400
    assert "bool DrawsRainParticles() const { return RainDrops != nullptr; }" in SCENE_H


def test_the_commandlet_places_the_drops_with_this_frames_camera():
    pose = COMMANDLET_CPP.index("if (!Director->ApplyPoseAtTime(")
    advance = COMMANDLET_CPP.index("VisualScene.AdvanceRain(RainNow, RainCameraCm,")
    flush = COMMANDLET_CPP.index("World->SendAllEndOfFrameUpdates();", advance)
    beauty = COMMANDLET_CPP.index("\t\tCapture->CaptureScene();", advance)
    assert pose < advance < flush < beauty
    block = COMMANDLET_CPP[COMMANDLET_CPP.rindex("if (bVisual && VisualScene.DrawsRainParticles())",
                                                 0, advance):advance]
    assert "Director->PoseVelocityAtTime(RainNow, RainCameraVelocity)" in block
    # The velocity is the derivative of the track's linear interpolation.
    velocity = DIRECTOR_CPP[DIRECTOR_CPP.index("bool AFlightSimCameraDirector::PoseVelocityAtTime"):]
    velocity = velocity[:velocity.index("\n}\n")]
    assert "(PoseLocations[Upper] - PoseLocations[Upper - 1]) / Span" in velocity


def test_a_wrapped_drop_is_teleported_not_blurred():
    assert "RainDrops->BatchUpdateInstancesTransforms(0, RainTransforms, true, false, true);" in RAIN_CPP
