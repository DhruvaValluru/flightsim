"""Surface classes (Phase 9.1): ground cover changes the air, by the book.

The claim under test: a surface word attaches exactly two modelled
couplings -- Davenport-Wieringa roughness (log-profile shear) and Allen
thermal forcing with a STATED basis -- and nothing else. Unknown ground
cover refuses by name; the ocean honestly attaches no thermals.
"""

import pytest

from core.environment.surface import (
    SURFACE_CLASSES, UNSPECIFIED, surface_class,
)
from core.environment.thermals import SEASON_TABLE
from core.environment.wind import LogProfileWind
from core.nl.compiler import compile_prompt
from core.scenario.validate import validate


# -- the class table -----------------------------------------------------


def test_every_class_roughness_is_a_documented_davenport_value():
    for name, cls in SURFACE_CLASSES.items():
        assert cls.roughness in LogProfileWind.ROUGHNESS_M, name
        assert cls.z0_m == LogProfileWind.ROUGHNESS_M[cls.roughness], name


def test_every_thermal_anchor_is_a_tm_table2_value_with_a_basis():
    """(w*, zi) must be the TM's own Table 2 climatology (or None), never
    an invented number; every basis string says which month and whether it
    is a proxy."""
    table = set(SEASON_TABLE.values())
    for name, cls in SURFACE_CLASSES.items():
        if cls.thermals is None:
            assert "no convective thermals" in cls.thermal_basis, name
        else:
            assert cls.thermals in table, name
            assert "Table 2" in cls.thermal_basis, name


def test_desert_is_the_tms_own_site_and_city_states_the_uhi_gap():
    assert SURFACE_CLASSES["desert"].thermals == SEASON_TABLE["summer"]
    assert "own site" in SURFACE_CLASSES["desert"].thermal_basis
    assert "NOT separately modelled" in SURFACE_CLASSES["city"].thermal_basis


def test_unknown_surface_raises_and_unspecified_is_none():
    assert surface_class(UNSPECIFIED) is None
    with pytest.raises(ValueError):
        surface_class("tundra")


# -- compilation ---------------------------------------------------------


def test_prompt_ground_cover_compiles_to_the_class():
    spec = compile_prompt("fly the 747 at 3000 m and 250 kt over grasslands")
    assert str(spec.surface.value) == "grassland"
    assert str(spec.surface.source) == "inferred"

    ocean = compile_prompt("fly the 747 at 3000 m over the sea")
    assert str(ocean.surface.value) == "ocean"

    plain = compile_prompt("fly the 747 at 3000 m and 250 kt")
    assert str(plain.surface.value) == "unspecified"
    assert str(plain.surface.source) == "default"


def test_unmodelled_surface_word_refuses_by_name():
    spec = compile_prompt("fly the 747 at 3000 m and 250 kt")
    spec.set("surface", "swamp", frm="test")
    report = validate(spec, check_feasibility=False)
    assert not report.ok
    assert [v.constraint for v in report.violations] == [
        "environment.surface"]


# -- the physics reaches the FDM ----------------------------------------


def test_surface_wind_decays_toward_the_ground_and_holds_at_cruise():
    """The log profile carries the base wind: at/above the 300 m layer top
    the aircraft flies exactly the spec's wind; near the ground it decays.
    Measured through the environment stack, not asserted from theory."""
    from core.environment.base import Position
    from core.scenario.runner import environment_for

    spec = compile_prompt(
        "fly the 747 at 3000 m and 250 kt over grasslands "
        "in a strong crosswind")
    stack = environment_for(spec)
    provider = next(p for p in stack.providers
                    if p.__class__.__name__ == "LogProfileWind")
    cruise = provider.speed_at(3000.0)
    low = provider.speed_at(30.0)
    from core.fdm import units as u
    assert cruise == pytest.approx(u.kt_to_mps(25.0), rel=1e-9)
    assert 0.0 < low < cruise


def test_ocean_attaches_no_thermals_and_grassland_does():
    from core.scenario.runner import environment_for

    grass = environment_for(compile_prompt(
        "fly the 747 at 3000 m over grasslands"))
    ocean = environment_for(compile_prompt(
        "fly the 747 at 3000 m over the ocean"))
    names = lambda s: [p.__class__.__name__ for p in s.providers]
    assert "AllenThermals" in names(grass)
    assert "AllenThermals" not in names(ocean)


def test_surface_run_output_differs_from_bare_run():
    """The coupling reaches the FDM: same spec with and without the surface
    word produces different telemetry (thermals move the aircraft)."""
    from core.scenario.runner import run_spec

    bare = compile_prompt("fly the 747 at 800 m and 250 kt for 4 seconds")
    surfaced = compile_prompt(
        "fly the 747 at 800 m and 250 kt for 4 seconds over grasslands")
    surfaced.set("seed", 7, frm="test determinism")
    a = run_spec(bare, validate_first=False)
    b = run_spec(surfaced, validate_first=False)
    assert a.output_digest != b.output_digest
    assert "thermal" in str(b.manifest["environment"]).lower()


# -- the card ------------------------------------------------------------


def test_card_blocks_carry_base_flag_and_flat_scene_crs():
    from core.environment.thermals import AllenThermals
    from core.environment.wind import LogProfileWind
    from webapp.runs import utm_zone_crs

    shear = LogProfileWind(10.0, 90.0, reference_height_m=300.0,
                           terrain="open")
    assert shear.card_block(carries_base=True)["carries_base"] is True
    assert "carries_base" not in shear.card_block()

    thermals = AllenThermals(wstar_mps=2.0, zi_m=1200.0,
                             area_north_m=4000.0, area_east_m=4000.0,
                             origin_north_m=-2000.0, origin_east_m=-2000.0,
                             seed=3)
    block = thermals.card_block(1.0, 2.0, crs="EPSG:32631")
    assert block["crs"] == "EPSG:32631"
    assert "crs" not in thermals.card_block(1.0, 2.0)

    assert utm_zone_crs(0.0, 0.0) == "EPSG:32631"
    assert utm_zone_crs(-35.0, 150.0) == "EPSG:32756"


def test_ue_step_replaces_base_wind_only_for_carries_base_cards():
    """Source-pinned like the contact check: the UE step must respect the
    carries_base flag (replace) while Phase 7 cards stay additive."""
    from pathlib import Path

    cpp = (Path(__file__).resolve().parents[1] / "ue" / "Plugins"
           / "FlightSimBridge" / "Source" / "FlightSimBridge" / "Private"
           / "FlightSimScenarioWorld.cpp").read_text(encoding="utf-8")
    assert "if (Card.bLogProfileCarriesBase)" in cpp
    body = cpp.split("Card.bLogProfileCarriesBase)", 1)[-1]
    assert "NorthFps = SpeedMps" in body.split("else")[0]
    assert 'TryGetStringField(TEXT("crs"), Out.ThermalsCrs)' in cpp
