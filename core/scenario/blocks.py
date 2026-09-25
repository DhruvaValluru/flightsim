"""The spec-8 blocks: ``scene``, ``taxonomy`` and ``traffic[]``.

Phase 2 (contracts §2.1, §2.2, §12) adds three top-level blocks to the
scenario spec. Each is serialised like the randomisation block, NOT
like the camera list: an absent block IS the documented default and is
omitted from the canonical form, so the digest of a spec that states
none of them is unchanged by construction (pinned by a test that reads
the committed version-7 examples). Every field is a provenanced
:class:`Quantity`, addressable through the spec's own ``set()`` /
``plan()`` front door (``scene.terrain_source``, ``taxonomy.classes``,
``traffic[0].range_m``), and a user-stated field is never silently
moved.

What each block means -- and what this module does NOT do:

* ``scene.terrain_source`` (``auto`` | ``flat`` | ``synthesised`` |
  ``baked``) names the terrain the flight is over. ``auto`` is exactly
  today's behaviour (the web app's ``pick_scene``; the CLI's
  ``--terrain`` / ``--synth-terrain`` flags); ``flat`` forces the spec's
  datum; ``synthesised`` synthesises the deterministic ridge centred on
  the spec's own origin; ``baked`` uses the bake ``scene.terrain`` (or
  the CLI's ``--terrain``) names and refuses by name when none is baked.
  The honouring lives in ``flightsim/capture.py`` and
  ``webapp/runs.py``; this module only carries and validates the field.
* ``taxonomy.classes`` is the ordered class list (``class_id`` =
  position + 1; 0 is reserved for sky/none). Only the list is carried
  here: object composition and the ID image are package B's.
* ``traffic[]`` states up to two scripted traffic aircraft (airframe,
  track kind, range, livery). Only the fields are carried and validated;
  no traffic is composed, flown or rendered by this package.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .fields import PLANNABLE_SOURCES, Quantity, Source

#: The terrain sources a spec may name (contracts §12).
TERRAIN_SOURCES = ("auto", "flat", "synthesised", "baked")
#: The documented class list (contracts §2.1). ``cloud`` is a class in
#: the visibility record only: volumetrics write no ID.
DEFAULT_CLASSES = ("aircraft", "terrain", "building", "vegetation",
                   "water", "cloud")
#: The three traffic tracks that produce object-object occlusion
#: (brainstorm §3.4).
TRAFFIC_TRACKS = ("formation", "crossing", "overtaking")
#: Documented traffic defaults (contracts §2.2).
DEFAULT_TRAFFIC_RANGE_M = 400.0
DEFAULT_TRAFFIC_TRACK = "crossing"
DEFAULT_TRAFFIC_LIVERY = "default"
#: At most this many traffic entries (contracts §5.2 ``traffic_count
#: max: 2``; the render's Populate holds one FDM actor plus N scripted
#: mesh actors and two is what the occlusion checks are specified for).
MAX_TRAFFIC = 2

#: Where a "configured airframe" is declared: one JSON per airframe the
#: asset pipeline can convert and import (the same directory the
#: randomisation block reads liveries from).
CONFIG_DIR = Path(__file__).resolve().parents[2] / "assets" / "aircraft_config"


def configured_airframes(config_dir: Optional[Path] = None) -> List[str]:
    """Every airframe with an asset-pipeline config -- the ones a
    traffic entry may name (its mesh must be importable like the
    primary's; contracts §2.2)."""
    directory = Path(config_dir) if config_dir is not None else CONFIG_DIR
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.json"))


class ProvenancedBlock:
    """A block of provenanced fields with the spec's own edit doctrine.

    Subclasses are dataclasses whose every field is a :class:`Quantity`,
    listed in ``FIELD_ORDER``; ``BLOCK`` names the block in messages and
    in ``from_dict`` refusals.
    """

    FIELD_ORDER: tuple = ()
    BLOCK = "block"

    def quantities(self):
        """(name, Quantity) in canonical order."""
        for name in self.FIELD_ORDER:
            yield name, getattr(self, name)

    def set(self, name: str, value: Any, frm: str = "edited by hand") -> None:
        """Override a field, recording that a human did it."""
        current = self._field(name)
        setattr(self, name, Quantity(value=value, unit=current.unit,
                                     source=Source.USER, frm=frm,
                                     std=current.std,
                                     detail=dict(current.detail)))

    def plan(self, name: str, value: Any, frm: str) -> None:
        """Move a field the SYSTEM chose. Same doctrine as the spec's,
        the camera's and the randomisation block's: only a defaulted /
        derived / model field moves; a stated one refuses by name."""
        current = self._field(name)
        if current.source not in PLANNABLE_SOURCES:
            raise ValueError(
                f"plan() only moves defaulted/derived/model fields; "
                f"{self.BLOCK}.{name} is {current.source.value!r} -- a "
                f"stated value is never silently moved")
        setattr(self, name, Quantity(value=value, unit=current.unit,
                                     source=Source.DERIVED, frm=frm,
                                     std=current.std,
                                     detail=dict(current.detail)))

    def _field(self, name: str) -> Quantity:
        if name not in self.FIELD_ORDER:
            raise ValueError(f"{name!r} is not a {self.BLOCK} field")
        return getattr(self, name)

    # -- serialisation --------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {name: q.to_dict() for name, q in self.quantities()}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        if not isinstance(data, dict):
            raise ValueError(f"spec '{cls.BLOCK}' must be a mapping of "
                             f"provenanced fields")
        kwargs = {}
        for name in cls.FIELD_ORDER:
            try:
                kwargs[name] = Quantity.from_dict(data[name])
            except KeyError as exc:
                raise ValueError(
                    f"{cls.BLOCK} is missing required field {name}") from exc
        unknown = set(data) - set(cls.FIELD_ORDER)
        if unknown:
            raise ValueError(
                f"{cls.BLOCK} carries unknown fields {sorted(unknown)}; "
                f"refusing to guess at their meaning")
        return cls(**kwargs)

    def is_default(self) -> bool:
        """The documented default, field for field, source for source
        -- the one spelling the canonical spec omits."""
        return self.to_dict() == self.defaulted().to_dict()

    @classmethod
    def defaulted(cls):
        raise NotImplementedError


@dataclass
class SceneSpec(ProvenancedBlock):
    """``scene``: where the terrain under the flight comes from."""

    terrain_source: Quantity
    #: A bake stem (as the CLI's ``--terrain``: ``<stem>.r16`` +
    #: ``.json``), required when ``terrain_source`` is ``baked``; None
    #: otherwise.
    terrain: Quantity

    FIELD_ORDER = ("terrain_source", "terrain")
    BLOCK = "scene"

    @classmethod
    def defaulted(cls) -> "SceneSpec":
        return cls(
            terrain_source=Quantity.default(
                "auto", frm="today's scene selection: the web app's "
                            "pick_scene; the CLI's --terrain / "
                            "--synth-terrain flags"),
            terrain=Quantity.default(
                None, frm="no bake stem stated; required when "
                          "terrain_source is baked"),
        )


@dataclass
class TaxonomySpec(ProvenancedBlock):
    """``taxonomy``: the ordered class list a dataset's categories come
    from (never from what happened to be in the scene)."""

    classes: Quantity

    FIELD_ORDER = ("classes",)
    BLOCK = "taxonomy"

    @classmethod
    def defaulted(cls) -> "TaxonomySpec":
        return cls(classes=Quantity.default(
            list(DEFAULT_CLASSES), frm="the documented class list"))


@dataclass
class TrafficSpec(ProvenancedBlock):
    """One scripted traffic aircraft (contracts §2.2)."""

    aircraft: Quantity
    track: Quantity
    range_m: Quantity
    livery: Quantity

    FIELD_ORDER = ("aircraft", "track", "range_m", "livery")
    BLOCK = "traffic"

    @classmethod
    def defaulted(cls, aircraft: str, track: str = DEFAULT_TRAFFIC_TRACK,
                  frm: str = "documented traffic default") -> "TrafficSpec":
        """A traffic entry for a stated airframe; the airframe is the
        one field with no documented default, so it is ``user``."""
        return cls(
            aircraft=Quantity.user(aircraft, frm=f"traffic: {aircraft}"),
            track=Quantity.default(track, frm=frm),
            range_m=Quantity.default(DEFAULT_TRAFFIC_RANGE_M, "m", frm=frm),
            livery=Quantity.default(DEFAULT_TRAFFIC_LIVERY, frm=frm),
        )
