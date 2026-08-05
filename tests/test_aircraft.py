"""Aircraft resolution must never substitute an airframe (§1.4).

The previous build shipped a clip whose HUD read ``FDM JSBSIM F16 - MODEL
F-15``: two independent lookups, no consistency check, and a successful load of
the wrong aircraft.
"""

import pytest

from core.fdm import (
    AircraftMismatchError,
    AircraftResolutionError,
    FlightDynamics,
    available,
    resolve,
)
from core.fdm.aircraft import verify_loaded


def test_both_f15_and_f16_exist_so_substitution_is_possible():
    """The premise of §1.4: this was a silent fallback, not a missing asset."""
    models = available()
    assert "f15" in models and "f16" in models


def test_unknown_aircraft_raises_and_does_not_guess():
    with pytest.raises(AircraftResolutionError) as exc:
        resolve("f-15")           # hyphenated; the real directory is "f15"
    assert "does not substitute" in str(exc.value)


def test_near_miss_is_suggested_but_not_silently_accepted():
    with pytest.raises(AircraftResolutionError) as exc:
        resolve("B747-400")
    assert "B747" in str(exc.value)


def test_resolve_records_license_and_pedigree():
    """§3.3: stock aircraft licensing is inconsistent and must be surfaced."""
    f16 = resolve("f16")
    assert f16.license_name is not None       # f16.xml declares GPL
    f15 = resolve("f15")
    assert f15.license_name is None           # f15.xml declares none at all
    # Every stock model carries the "flies right" disclaimer; VALIDITY.md
    # quotes it rather than paraphrasing.
    assert f15.note and "entertainment" in f15.note


def test_resolve_fingerprints_the_xml_for_provenance():
    m = resolve("global5000")
    assert len(m.sha256) == 64
    assert m.provenance()["sha256"] == m.sha256


def test_loaded_model_is_verified_against_the_request():
    """The direct §1.4 guard."""
    fdm = FlightDynamics("f16")
    assert fdm.aircraft_name == "f16"
    # Simulate the substitution: claim we asked for the F-15.
    with pytest.raises(AircraftMismatchError) as exc:
        verify_loaded(fdm._exec, resolve("f15"))
    assert "Refusing to run" in str(exc.value)
