"""The property layer must turn silent failures into loud ones.

Each test here corresponds to a measured JSBSim behaviour that would otherwise
produce a run that reports a condition it does not have (§1.6, §2.7).
"""

import pytest

from core.fdm import FlightDynamics, ReadOnlyPropertyError, UnknownPropertyError

AIRCRAFT = "global5000"


@pytest.fixture(scope="module")
def fdm():
    return FlightDynamics(AIRCRAFT)


def test_catalog_is_populated(fdm):
    assert len(fdm.props) > 500
    assert "velocities/vtrue-kts" in fdm.props.names()


def test_unknown_write_raises_rather_than_creating_a_node(fdm):
    """JSBSim would accept this write, store it, and never apply it."""
    with pytest.raises(UnknownPropertyError):
        fdm.props.set("totally/made/up/property", 42.0)


def test_unknown_read_raises_rather_than_returning_zero(fdm):
    """JSBSim would return 0.0, which is indistinguishable from a real reading."""
    with pytest.raises(UnknownPropertyError):
        fdm.props.get("never/written/at/all")


def test_misspelled_wind_property_is_rejected(fdm):
    """The §1.6 case: a typo'd wind name must not look like a successful write."""
    with pytest.raises(UnknownPropertyError):
        fdm.props.set("atmosphere/wind-north-fbs", 25.0)   # fbs, not fps


def test_write_to_read_only_property_raises(fdm):
    """JSBSim ignores these writes with no diagnostic at all."""
    assert fdm.props.access_of("velocities/vtrue-kts") == "(R)"
    with pytest.raises(ReadOnlyPropertyError):
        fdm.props.set("velocities/vtrue-kts", 999.0)


def test_ic_wind_ned_components_are_read_only(fdm):
    """Documented as settable ICs in the reference; measured read-only in 1.2.4.

    Setting these is how you would think to specify an initial wind, and doing
    so has no effect whatsoever.
    """
    for name in ("ic/vw-north-fps", "ic/vw-east-fps", "ic/vw-down-fps"):
        assert fdm.props.access_of(name) == "(R)"
        with pytest.raises(ReadOnlyPropertyError):
            fdm.props.set(name, 10.0)
    # The writable route is magnitude/direction.
    assert fdm.props.access_of("ic/vw-mag-fps") == "(RW)"
    assert fdm.props.access_of("ic/vw-dir-deg") == "(RW)"


def test_index_zero_subscript_resolves_to_unindexed_node(fdm):
    """The catalog omits ``[0]`` but the name aliases correctly."""
    assert "fcs/throttle-cmd-norm[0]" not in fdm.props.names()
    assert fdm.props.has("fcs/throttle-cmd-norm[0]")
    fdm.props.set("fcs/throttle-cmd-norm[0]", 0.42)
    assert fdm.props.get("fcs/throttle-cmd-norm") == pytest.approx(0.42)


def test_set_many_validates_everything_before_writing_anything(fdm):
    """A typo in the last entry must not leave the sim half-configured."""
    before = fdm.props.get("fcs/aileron-cmd-norm")
    with pytest.raises(UnknownPropertyError):
        fdm.props.set_many(
            {"fcs/aileron-cmd-norm": 0.9, "fcs/not-a-real-control": 0.5}
        )
    assert fdm.props.get("fcs/aileron-cmd-norm") == pytest.approx(before)


def test_require_lists_every_missing_name_at_once(fdm):
    with pytest.raises(UnknownPropertyError) as exc:
        fdm.props.require(["velocities/vtrue-kts", "bogus/one", "bogus/two"])
    assert "bogus/one" in str(exc.value)
    assert "bogus/two" in str(exc.value)
