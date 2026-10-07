"""The scenario spec: the reproducible unit of this system.

§2.6: ``prompt -> scenario spec -> validate -> run``. Never ``prompt -> run``.

The spec, not the prompt, goes in the provenance manifest. Parsing English is
nondeterministic, so a run that can only be reproduced by re-parsing a sentence
is not reproducible at all. Once a spec exists the prompt is a historical note,
retained for provenance and never re-read.

The spec is deliberately editable. A user is expected to read the rendered
table, disagree with an inferred value, change it, and re-run -- at which point
the edited field's source becomes ``user`` and the record shows that a human
overrode an inference.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .blocks import (
    AtmosphereSpec, DatumSpec, DisSpec, FailuresSpec, IcingSpec, InstrumentsSpec, LoadingSpec,
    RainSpec, RecordSpec, SceneSpec, TaxonomySpec,
    TrafficSpec, TurbulenceModelSpec, WakeSpec, WindProfileSpec,
)
from .blocks import RunwayBlockSpec
from .camera import CameraSpec
from .randomization import RandomizationSpec
from .fields import Quantity, Source

# 2 (2026-08-11): environment.surface added (Phase 9.1 ground-cover
# classes). from_dict refuses version-1 dicts by design -- completed runs
# recover from provenance.json, never by re-parsing an old spec.
# 3 (2026-08-11): environment.weather_date added (ERA5 historical weather).
# 4 (2026-08-11): environment.weather_event added (Phase 9.2/9.3 storm cell
# and tornado -- composed/kinematic condition models, refused when unknown).
# 5 (2026-08-13): provenance source "model" added (the scene director's
# declared interpretation). The field list is unchanged, but a version-5
# dict may carry a source value version-4 builds refuse (Source("model")
# raises), so the refuse-old-dicts convention applies in BOTH directions:
# bumping keeps the failure a named version error instead of a KeyError
# deep in Quantity. Completed runs recover from provenance.json as always.
# 6 (2026-08-31): cameras added (Camera Phase 1) -- a list of CameraSpec
# blocks, each field a provenanced Quantity, serialized as an
# always-present list (an empty list IS the documented default camera
# behaviour and drives the render pipeline unchanged, pinned by test).
# The list is digest-relevant, so the version bump changes every digest
# by design: version-5 dicts refuse by name; completed runs recover
# from provenance.json, never by re-parsing.
# 7 (2026-09-11): cameras[].profile added (Phase 10, package 3: the
# sensor model -- lens distortion, rolling shutter, noise, vignetting,
# applied as a seeded post-pass; "ideal_pinhole" by default). The one
# version bump of Phase 10: the randomisation block (package 7) lands
# under this same version as an optional, defaulted section. Version-6
# dicts refuse by name; completed runs recover from provenance.json.
# Every digest changes with the version field, by design, as it did at 6.
# 8 (2026-09-25): Phase 2's one bump (docs/PHASE2_CONTRACTS.md §0, §12):
# scene.terrain_source + scene.terrain (package A), taxonomy.classes and
# traffic[] (B), randomization.policy (F), cameras[].exposure (Look).
# Every new block is OPTIONAL and absent-canonical (serialised like the
# randomisation block, not like cameras): a spec that states none of
# them has the same canonical form it had at 7 apart from this version
# field -- pinned by a test against the committed version-7 examples.
# The bump is what makes the new blocks safe: a version-7 reader
# tolerates unknown top-level keys and would silently DROP them.
# Version-7 dicts refuse by name; completed runs recover from
# provenance.json, never by re-parsing.
# 9 (2026-09-29): the advancement addition's one bump (INT-final;
# docs/ADVANCEMENTS_BLUEPRINT.md "Versions and keys"). The blocks the
# addition's items landed under 8 as OPTIONAL, absent-canonical keys --
# SPEC9_BLOCKS, SPEC9_SCENE_FIELDS, SPEC9_ENVIRONMENT_FIELDS and
# SPEC9_CAMERA_FIELDS below -- are version 9's. Each stays optional and
# absent-canonical, so a version-9 spec that states none of them is a
# version-8 spec with this one number changed (pinned against the
# committed version-8 examples, frozen under tests/data/spec8_examples).
# The rule for older dicts, unlike 7 -> 8: a version-8 dict still READS
# (it becomes a version-9 spec; the digest moves with the hashed version
# line only), UNLESS it states a version-9 block -- that is refused by
# name (spec.version, naming the block), because a version-8 reader
# built before the block existed would have dropped or refused it, so a
# file claiming 8 and carrying it was not written by any version-8
# writer. Version 7 and older refuse by name as before. (The field
# notes below were written under 8: where they say an example "keeps its
# digest", read "keeps its canonical form"; the version line moved.)
SPEC_VERSION = 9

#: The versions from_dict reads: this one, and 8 without a version-9 block.
READABLE_SPEC_VERSIONS = (8, 9)

#: Version 9's top-level blocks (each absent-canonical).
SPEC9_BLOCKS = ("atmosphere", "datum", "turbulence_model", "wind_profile", "loading",
                "failures", "icing", "dis", "wake", "instruments", "record", "runway",
                "rain")
#: Version 9's optional fields inside version-8 sections.
SPEC9_SCENE_FIELDS = ("sun_lux", "buildings", "night")
SPEC9_ENVIRONMENT_FIELDS = ("precipitation_rate_mmh", "time_of_day")
SPEC9_CAMERA_FIELDS = ("exposure_compensation_ev", "bands", "stereo", "passes", "ir")


def spec9_keys_in(data: Dict[str, Any]) -> List[str]:
    """Every version-9 key a spec dict states, dotted (``wake``,
    ``scene.night``, ``cameras[0].ir``); [] for a dict that states none."""
    found = [name for name in SPEC9_BLOCKS if data.get(name) is not None]
    for section, names in (("scene", SPEC9_SCENE_FIELDS),
                           ("environment", SPEC9_ENVIRONMENT_FIELDS)):
        block = data.get(section)
        if isinstance(block, dict):
            found += [f"{section}.{name}" for name in names if block.get(name) is not None]
    cameras = data.get("cameras")
    for index, camera in enumerate(cameras if isinstance(cameras, list) else []):
        if isinstance(camera, dict):
            found += [f"cameras[{index}].{name}" for name in SPEC9_CAMERA_FIELDS
                      if camera.get(name) is not None]
    return found


def _default_time_of_day() -> Quantity:
    """``environment.time_of_day`` unstated -- the documented default look
    (the harness's calibrated sun; core.render.flags DEFAULT_LOOK)."""
    return Quantity.default("none", frm="no time of day stated; default render look")


def _default_precipitation_rate() -> Quantity:
    """W3: ``environment.precipitation_rate_mmh`` unstated -- no rain rate
    (the precipitation word, if any, keeps its visibility floor)."""
    return Quantity.default(None, "mm/h", frm="no rain rate stated: no drop-size "
                                              "distribution, no streaks")


@dataclass
class ScenarioSpec:
    """A fully-specified, reproducible simulation scenario.

    Mutable by design: editing is part of the workflow (§2.6). Immutability
    arrives at validation, which produces a frozen digest that the run harness
    records.
    """

    aircraft: Quantity
    altitude: Quantity
    airspeed: Quantity
    #: "cas" or "tas". Which one is meant changes the condition materially.
    airspeed_kind: Quantity
    heading: Quantity
    latitude: Quantity
    longitude: Quantity
    terrain_elevation: Quantity
    duration: Quantity
    rate: Quantity
    seed: Quantity
    mass_held: Quantity
    hold_state: Quantity
    wind_speed: Quantity
    wind_direction: Quantity
    turbulence: Quantity
    #: Ground-cover class (core.environment.surface): roughness + thermal
    #: forcing, or "unspecified" for no surface coupling.
    surface: Quantity
    #: ISO date for ERA5 historical weather (core.environment.era5), or
    #: "none" -- the reanalysis mean wind applies as a recorded edit.
    weather_date: Quantity
    #: Severe-weather event: "none", "thunderstorm" (a COMPOSITION of the
    #: existing microburst + gust front + severe turbulence), or "tornado"
    #: (core.environment.tornado, a kinematic Rankine vortex).
    weather_event: Quantity

    name: str = "scenario"
    #: Retained for provenance only. Never re-parsed to reproduce a run.
    prompt: Optional[str] = None
    notes: List[str] = dc_field(default_factory=list)
    #: Cameras (Phase 1 camera control): a list of CameraSpec blocks,
    #: digest-relevant. EMPTY means the documented default camera
    #: behaviour -- exactly the pre-camera build, via default_cameras().
    cameras: List["CameraSpec"] = dc_field(default_factory=list)
    #: Domain randomisation (Phase 10, package 7): a provenanced block
    #: with its own seed and the drawn values written back as derived
    #: fields. The documented default is "off", and the canonical form
    #: OMITS a default block -- so every spec written before the block
    #: existed keeps its digest, and "absent" and "all defaults" are one
    #: spelling. Same version 7; no bump.
    randomization: "RandomizationSpec" = dc_field(
        default_factory=RandomizationSpec.defaulted)
    #: Spec 8 (package F's field, carried here): the randomisation
    #: POLICY -- a mapping of distribution leaves (contracts §5.2),
    #: carried whole as one provenanced Quantity (its value is the
    #: mapping) and serialised under ``randomization.policy``. Absent
    #: is the documented default ("no sampling"). This package validates
    #: its SHAPE only (each leaf one of the documented distribution
    #: forms); the meaning of each leaf and the sampling are package F's
    #: and are not implemented here. It rides on the spec rather than on
    #: RandomizationSpec so the block's own 20-field reader (which
    #: refuses unknown keys) is untouched; the on-disk shape is the
    #: contract's, and package F may move the attribute inside the block
    #: without changing a file.
    randomization_policy: Optional[Quantity] = None
    #: Spec 8, package A: where the terrain comes from (absent-canonical).
    scene: "SceneSpec" = dc_field(default_factory=SceneSpec.defaulted)
    #: Spec 8, package B's field: the ordered class list (absent-canonical).
    taxonomy: "TaxonomySpec" = dc_field(default_factory=TaxonomySpec.defaulted)
    #: Spec 8, package B's field: scripted traffic aircraft, at most
    #: MAX_TRAFFIC; an empty list is the default and is omitted.
    traffic: List["TrafficSpec"] = dc_field(default_factory=list)
    #: Gap P1 (spec 9: INT-final's bump): the day the
    #: flight is in -- temperature deviation, sea-level pressure, dew
    #: point or relative humidity, a day word -- absent-canonical: the
    #: ISA day is the default and is omitted, so every committed spec-8
    #: example keeps its digest (pinned by test).
    atmosphere: "AtmosphereSpec" = dc_field(default_factory=AtmosphereSpec.defaulted)
    #: Gap P10, D1 (spec 9: INT-final's bump): the vertical
    #: datum the run declares -- vertical, physics_frame, geoid_model --
    #: absent-canonical: the orthometric frame is the default and is
    #: omitted, so every committed spec-8 example keeps its digest.
    datum: "DatumSpec" = dc_field(default_factory=DatumSpec.defaulted)
    #: Gap P2, P6 (spec 9: INT-final's bump): the
    #: turbulence spectrum (dryden = today's path | von_karman) with its
    #: intensity and seed, and the wind profile (uniform = today's path |
    #: layered | milspec | nwp) -- both absent-canonical: the defaults are
    #: omitted, so every committed spec-8 example keeps its digest.
    turbulence_model: "TurbulenceModelSpec" = dc_field(
        default_factory=TurbulenceModelSpec.defaulted)
    wind_profile: "WindProfileSpec" = dc_field(default_factory=WindProfileSpec.defaulted)
    #: Gap P4 (spec 9: INT-final's bump): the payload
    #: stations and the fuel the flight starts with -- absent-canonical:
    #: the XML's own loading is the default and is omitted, so every
    #: committed spec-8 example keeps its digest.
    loading: "LoadingSpec" = dc_field(default_factory=LoadingSpec.defaulted)
    #: P3 (spec 9: INT-final's bump): the failure schedule
    #: -- events of {kind, target, at_s, value} -- absent-canonical: the
    #: empty list is the default and is omitted, so every committed
    #: spec-8 example keeps its digest.
    failures: "FailuresSpec" = dc_field(default_factory=FailuresSpec.defaulted)
    #: P5 (spec 9: INT-final's bump): the icing severity
    #: ramp -- severity word | eta_max, onset_s, ramp_s, alpha_shift_deg,
    #: envelope word -- absent-canonical: no ice (the stock airframe) is
    #: the default and is omitted, so every committed spec-8 example
    #: keeps its digest.
    icing: "IcingSpec" = dc_field(default_factory=IcingSpec.defaulted)
    #: Spec 9, optional: what the stated rain rate does to the aircraft
    #: and the runway -- aerodynamics, lift_loss_at_ref, drag_rise_at_ref,
    #: frontal_area_m2, runway_condition, tire_pressure_psi --
    #: absent-canonical: no rain physics is the default and is omitted
    #: (core/environment/rain.py).
    rain: "RainSpec" = dc_field(default_factory=RainSpec.defaulted)
    #: D2 (spec 9: INT-final's bump): how the Entity State
    #: PDU log is labelled -- site, application, entity, force_id, marking,
    #: timestamp_mode -- absent-canonical: the documented defaults are
    #: omitted, so every committed spec-8 example keeps its digest.
    dis: "DisSpec" = dc_field(default_factory=DisSpec.defaulted)
    #: P7 (spec 9: INT-final's bump): the wake-vortex
    #: encounter -- generator, its speed, the own ship's offsets from the
    #: pair, the wake's age, the decay and its inputs -- absent-canonical:
    #: no wake is the default and is omitted, so every committed spec-8
    #: example keeps its digest.
    wake: "WakeSpec" = dc_field(default_factory=WakeSpec.defaulted)
    #: R2 (spec 9: INT-final's bump): the instrument models
    #: at the FDM rate -- imu, gps, pitot_static, magnetometer, each a
    #: profile with a lever arm -- and the record block -- null_tests,
    #: convergence, sensitivity_pairs -- both absent-canonical: the ideal
    #: instruments at the CG and no extra flights are the defaults and are
    #: omitted, so every committed spec-8 example keeps its digest.
    instruments: "InstrumentsSpec" = dc_field(default_factory=InstrumentsSpec.defaulted)
    record: "RecordSpec" = dc_field(default_factory=RecordSpec.defaulted)
    #: W3 (spec 9: INT-final's bump): the rain rate in mm/h
    #: under ``environment`` -- the fitted drop-size distribution, the
    #: streaks and the reconciled extinction (core/scene/precipitation.py)
    #: -- absent-canonical: unstated is omitted from the environment
    #: section, so every committed spec-8 example keeps its digest.
    precipitation_rate_mmh: Quantity = dc_field(default_factory=_default_precipitation_rate)
    #: W2 (spec 9: INT-final's bump): one runway --
    #: designator, threshold, heading, length, width, surface, markings --
    #: absent-canonical: no runway is the default and is omitted, so
    #: every committed spec-8 example keeps its digest.
    runway: "RunwayBlockSpec" = dc_field(default_factory=RunwayBlockSpec.defaulted)
    #: Render sun (core.environment.sun, visual-fidelity plan V1; the
    #: physical sky of core.sky reads it too): a named time ("dawn",
    #: "noon", "golden hour", ...), "HH:MM" local apparent solar time,
    #: "HH:MMZ" UTC, or "none" for the documented default look. VISUAL
    #: ONLY -- physics never reads it. Spec 9, absent-canonical: unstated
    #: is omitted from the environment section, so every committed spec-8
    #: example keeps its canonical form.
    time_of_day: Quantity = dc_field(default_factory=_default_time_of_day)

    #: Field order for both serialisation and the rendered table.
    FIELD_ORDER = (
        ("aircraft", "aircraft"),
        ("initial", "altitude"),
        ("initial", "airspeed"),
        ("initial", "airspeed_kind"),
        ("initial", "heading"),
        ("initial", "latitude"),
        ("initial", "longitude"),
        ("initial", "terrain_elevation"),
        ("environment", "wind_speed"),
        ("environment", "wind_direction"),
        ("environment", "turbulence"),
        ("environment", "surface"),
        ("environment", "weather_date"),
        ("environment", "weather_event"),
        ("run", "duration"),
        ("run", "rate"),
        ("run", "seed"),
        ("run", "mass_held"),
        ("run", "hold_state"),
    )

    # -- access --------------------------------------------------------

    def quantities(self):
        """(section, name, Quantity) in canonical order."""
        for section, name in self.FIELD_ORDER:
            yield section, name, getattr(self, name)

    def _camera_address(self, name: str):
        """Parse ``cameras[<i>].<field>`` -> (CameraSpec, field) or None.

        Camera fields are addressable through the same set()/plan() front
        door as every scalar field, so the review-table edit path and the
        planners need no second dispatch mechanism.
        """
        import re

        match = re.fullmatch(r"cameras\[(\d+)\]\.(\w+)(?:\.(\w+))?", name)
        if match is None:
            return None
        index = int(match.group(1))
        if index >= len(self.cameras):
            raise ValueError(
                f"spec has {len(self.cameras)} camera(s); {name} does not "
                f"exist")
        field = match.group(2)
        # Spec 8: ``cameras[i].exposure.<field>`` addresses the nested
        # exposure block, which carries the same set()/plan() doctrine.
        if field == "exposure" and match.group(3) is not None:
            return self.cameras[index].exposure, match.group(3)
        if match.group(3) is not None or field not in CameraSpec.FIELD_ORDER:
            raise ValueError(f"{field!r} is not a camera field")
        return self.cameras[index], field

    def _block_address(self, name: str):
        """Parse ``scene.<field>``, ``taxonomy.<field>`` or
        ``traffic[<i>].<field>`` -> (block, field) or None. The blocks
        carry the spec's own set()/plan() doctrine."""
        import re

        match = re.fullmatch(r"(scene|taxonomy|atmosphere|datum|turbulence_model|wind_profile|loading|failures|icing|rain|dis|wake|instruments|record|runway)\.(\w+)", name)
        if match is not None:
            block = getattr(self, match.group(1))
            return block, match.group(2)
        match = re.fullmatch(r"traffic\[(\d+)\]\.(\w+)", name)
        if match is not None:
            index = int(match.group(1))
            if index >= len(self.traffic):
                raise ValueError(
                    f"spec has {len(self.traffic)} traffic entr"
                    f"{'y' if len(self.traffic) == 1 else 'ies'}; {name} "
                    f"does not exist")
            return self.traffic[index], match.group(2)
        return None

    def _randomization_address(self, name: str):
        """Parse ``randomization.<field>`` -> field or None."""
        if not name.startswith("randomization."):
            return None
        field = name[len("randomization."):]
        if field not in RandomizationSpec.FIELD_ORDER:
            raise ValueError(f"{field!r} is not a randomization field")
        return field

    def set(self, name: str, value: Any, frm: str = "edited by hand") -> None:
        """Override a field, recording that a human did it.

        This is the edit step of §2.6. The source becomes ``user`` because a
        human overriding an inference is exactly the distinction the provenance
        record exists to preserve. Camera fields are addressed as
        ``cameras[0].focal_length_mm``.
        """
        camera = self._camera_address(name)
        if camera is not None:
            camera[0].set(camera[1], value, frm=frm)
            return
        block = self._block_address(name)
        if block is not None:
            block[0].set(block[1], value, frm=frm)
            return
        if name == "randomization.policy":
            self.randomization_policy = Quantity(
                value=value, source=Source.USER, frm=frm)
            return
        block_field = self._randomization_address(name)
        if block_field is not None:
            self.randomization.set(block_field, value, frm=frm)
            return
        current = getattr(self, name)
        setattr(
            self,
            name,
            Quantity(value=value, unit=current.unit, source=Source.USER,
                     frm=frm, std=current.std, detail=dict(current.detail)),
        )

    def plan(self, name: str, value: Any, frm: str) -> None:
        """Move a field the SYSTEM chose, keeping that fact on record.

        The planners' edit step (terrain clearance, envelope floors): the
        result is the system's own computation, not the user's words, so
        the source becomes ``derived`` -- and, unlike a ``set()``, a later
        planner may move it again. Only defaulted, derived or
        model-sourced fields may be planned (a model guess is the
        system's choice too -- declared, and overridable by physics); a
        user-stated or inferred value is never silently moved (§2.6) --
        planners refuse by name instead. Camera fields are addressed as
        ``cameras[0].focal_length_mm`` and follow the same rule.
        """
        camera = self._camera_address(name)
        if camera is not None:
            camera[0].plan(camera[1], value, frm=frm)
            return
        block = self._block_address(name)
        if block is not None:
            block[0].plan(block[1], value, frm=frm)
            return
        if name == "randomization.policy":
            current = self.randomization_policy
            if current is not None and current.source not in (
                    Source.DEFAULT, Source.DERIVED, Source.MODEL):
                raise ValueError(
                    f"plan() only moves defaulted/derived/model fields; "
                    f"randomization.policy is {current.source.value!r} -- "
                    f"a stated value is never silently moved")
            self.randomization_policy = Quantity(
                value=value, source=Source.DERIVED, frm=frm)
            return
        block_field = self._randomization_address(name)
        if block_field is not None:
            self.randomization.plan(block_field, value, frm=frm)
            return
        current = getattr(self, name)
        if current.source not in (Source.DEFAULT, Source.DERIVED,
                                  Source.MODEL):
            raise ValueError(
                f"plan() only moves defaulted/derived/model fields; {name} "
                f"is {current.source.value!r} -- a stated value is never "
                f"silently moved")
        setattr(
            self,
            name,
            Quantity(value=value, unit=current.unit, source=Source.DERIVED,
                     frm=frm, std=current.std, detail=dict(current.detail)),
        )

    # -- serialisation --------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Canonical nested mapping, deterministic in key order."""
        out: Dict[str, Any] = {
            "spec_version": SPEC_VERSION,
            "name": self.name,
        }
        if self.prompt is not None:
            out["prompt"] = self.prompt
        for section, name, q in self.quantities():
            out.setdefault(section, {})[name] = q.to_dict()
        # W3: the rain rate rides under environment only when stated.
        if self.precipitation_rate_mmh.to_dict() != _default_precipitation_rate().to_dict():
            out["environment"]["precipitation_rate_mmh"] = self.precipitation_rate_mmh.to_dict()
        # The render sun rides under environment only when stated.
        if self.time_of_day.to_dict() != _default_time_of_day().to_dict():
            out["environment"]["time_of_day"] = self.time_of_day.to_dict()
        # Always present: the canonical form has exactly one spelling of
        # "no cameras" (the empty list), so the digest cannot fork on an
        # absent-vs-empty distinction.
        out["cameras"] = [camera.to_dict() for camera in self.cameras]
        # The randomisation block appears only when it differs from the
        # documented default: absent IS the default, one spelling, and
        # pre-block specs keep their digests (no version bump).
        if not self.randomization.is_default():
            out["randomization"] = self.randomization.to_dict()
        # Spec 8: the policy rides under the same key (contracts §5.2);
        # absent is "no sampling" and is omitted.
        if self.randomization_policy is not None:
            out.setdefault("randomization", {})["policy"] = (
                self.randomization_policy.to_dict())
        # Spec 8 blocks, each absent-canonical: a spec that states none
        # of them keeps the canonical form it had at 7 (apart from the
        # version field). The order is documentary only; the digest
        # sorts keys.
        if not self.scene.is_default():
            out["scene"] = self.scene.to_dict()
        if not self.taxonomy.is_default():
            out["taxonomy"] = self.taxonomy.to_dict()
        if self.traffic:
            out["traffic"] = [entry.to_dict() for entry in self.traffic]
        # Gap P1: the atmosphere block, absent-canonical like the others.
        if not self.atmosphere.is_default():
            out["atmosphere"] = self.atmosphere.to_dict()
        # Gap P10 (D1): the datum block, absent-canonical like the others.
        if not self.datum.is_default():
            out["datum"] = self.datum.to_dict()
        # P6: the turbulence model and the wind profile, absent-canonical.
        if not self.turbulence_model.is_default():
            out["turbulence_model"] = self.turbulence_model.to_dict()
        if not self.wind_profile.is_default():
            out["wind_profile"] = self.wind_profile.to_dict()
        # P4: the loading block, absent-canonical like the others.
        if not self.loading.is_default():
            out["loading"] = self.loading.to_dict()
        # P3: the failure schedule, absent-canonical like the others.
        if not self.failures.is_default():
            out["failures"] = self.failures.to_dict()
        # P5: the icing block, absent-canonical like the others.
        if not self.icing.is_default():
            out["icing"] = self.icing.to_dict()
        # The rain block, absent-canonical like the others.
        if not self.rain.is_default():
            out["rain"] = self.rain.to_dict()
        # D2: the dis block, absent-canonical like the others.
        if not self.dis.is_default():
            out["dis"] = self.dis.to_dict()
        # P7: the wake block, absent-canonical like the others.
        if not self.wake.is_default():
            out["wake"] = self.wake.to_dict()
        # R2: the instruments and record blocks, absent-canonical like the others.
        if not self.instruments.is_default():
            out["instruments"] = self.instruments.to_dict()
        if not self.record.is_default():
            out["record"] = self.record.to_dict()
        # W2: the runway block, absent-canonical like the others.
        if not self.runway.is_default():
            out["runway"] = self.runway.to_dict()
        if self.notes:
            out["notes"] = list(self.notes)
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScenarioSpec":
        version = data.get("spec_version")
        if version != SPEC_VERSION:
            if version not in READABLE_SPEC_VERSIONS:
                raise ValueError(
                    f"spec_version {version!r} is not supported by this build "
                    f"(expects {SPEC_VERSION}; reads {READABLE_SPEC_VERSIONS}). "
                    f"Refusing to guess at the schema."
                )
            # Version 8 reads only as the file a version-8 writer could
            # have written: a version-9 key under it is refused by name.
            stated = spec9_keys_in(data)
            if stated:
                raise ValueError(
                    f"spec_version {version!r} with the version-9 block(s) "
                    f"{', '.join(stated)} is not supported by this build: those "
                    f"blocks are spec_version {SPEC_VERSION}'s, so state "
                    f"spec_version: {SPEC_VERSION}. Refusing to guess at the schema."
                )
        kwargs = {}
        for section, name in cls.FIELD_ORDER:
            try:
                kwargs[name] = Quantity.from_dict(data[section][name])
            except KeyError as exc:
                raise ValueError(
                    f"spec is missing required field {section}.{name}"
                ) from exc
        # W3: the optional environment field (absent = no rain rate).
        rate_data = (data.get("environment") or {}).get("precipitation_rate_mmh")
        kwargs["precipitation_rate_mmh"] = (_default_precipitation_rate() if rate_data is None
                                            else Quantity.from_dict(rate_data))
        # The optional render sun (absent = the default look).
        time_data = (data.get("environment") or {}).get("time_of_day")
        kwargs["time_of_day"] = (_default_time_of_day() if time_data is None
                                 else Quantity.from_dict(time_data))
        cameras_data = data.get("cameras", [])
        if not isinstance(cameras_data, list):
            raise ValueError("spec 'cameras' must be a list of camera "
                             "mappings")
        randomization_data = data.get("randomization")
        policy = None
        if isinstance(randomization_data, dict) and "policy" in randomization_data:
            # The policy is lifted out before the block's own reader
            # (which refuses unknown keys) sees the rest; a policy-only
            # block leaves the ranges at their defaults.
            randomization_data = dict(randomization_data)
            policy_data = randomization_data.pop("policy")
            if not isinstance(policy_data, dict) or "value" not in policy_data:
                raise ValueError("randomization.policy must be a "
                                 "provenanced mapping ({value, source, "
                                 "from})")
            policy = Quantity.from_dict(policy_data)
            if not randomization_data:
                randomization_data = None
        randomization = (RandomizationSpec.defaulted()
                         if randomization_data is None
                         else RandomizationSpec.from_dict(randomization_data))
        scene_data = data.get("scene")
        scene = (SceneSpec.defaulted() if scene_data is None
                 else SceneSpec.from_dict(scene_data))
        taxonomy_data = data.get("taxonomy")
        taxonomy = (TaxonomySpec.defaulted() if taxonomy_data is None
                    else TaxonomySpec.from_dict(taxonomy_data))
        traffic_data = data.get("traffic", [])
        if not isinstance(traffic_data, list):
            raise ValueError("spec 'traffic' must be a list of traffic "
                             "mappings")
        atmosphere_data = data.get("atmosphere")
        atmosphere = (AtmosphereSpec.defaulted() if atmosphere_data is None
                      else AtmosphereSpec.from_dict(atmosphere_data))
        datum_data = data.get("datum")
        datum = (DatumSpec.defaulted() if datum_data is None
                 else DatumSpec.from_dict(datum_data))
        turbulence_data = data.get("turbulence_model")
        turbulence_model = (TurbulenceModelSpec.defaulted() if turbulence_data is None
                            else TurbulenceModelSpec.from_dict(turbulence_data))
        profile_data = data.get("wind_profile")
        wind_profile = (WindProfileSpec.defaulted() if profile_data is None
                        else WindProfileSpec.from_dict(profile_data))
        loading_data = data.get("loading")
        loading = (LoadingSpec.defaulted() if loading_data is None
                   else LoadingSpec.from_dict(loading_data))
        failures_data = data.get("failures")
        failures = (FailuresSpec.defaulted() if failures_data is None
                    else FailuresSpec.from_dict(failures_data))
        icing_data = data.get("icing")
        icing = (IcingSpec.defaulted() if icing_data is None
                 else IcingSpec.from_dict(icing_data))
        rain_data = data.get("rain")
        rain = (RainSpec.defaulted() if rain_data is None
                else RainSpec.from_dict(rain_data))
        dis_data = data.get("dis")
        dis = (DisSpec.defaulted() if dis_data is None
               else DisSpec.from_dict(dis_data))
        wake_data = data.get("wake")
        wake = (WakeSpec.defaulted() if wake_data is None
                else WakeSpec.from_dict(wake_data))
        instruments_data = data.get("instruments")
        instruments = (InstrumentsSpec.defaulted() if instruments_data is None
                       else InstrumentsSpec.from_dict(instruments_data))
        record_data = data.get("record")
        record = (RecordSpec.defaulted() if record_data is None
                  else RecordSpec.from_dict(record_data))
        runway_data = data.get("runway")
        runway = (RunwayBlockSpec.defaulted() if runway_data is None
                  else RunwayBlockSpec.from_dict(runway_data))
        return cls(
            name=data.get("name", "scenario"),
            prompt=data.get("prompt"),
            notes=list(data.get("notes", [])),
            cameras=[CameraSpec.from_dict(entry) for entry in cameras_data],
            randomization=randomization,
            randomization_policy=policy,
            scene=scene,
            taxonomy=taxonomy,
            traffic=[TrafficSpec.from_dict(entry) for entry in traffic_data],
            atmosphere=atmosphere,
            datum=datum,
            turbulence_model=turbulence_model,
            wind_profile=wind_profile,
            loading=loading,
            failures=failures,
            icing=icing,
            rain=rain,
            dis=dis,
            wake=wake,
            instruments=instruments,
            record=record,
            runway=runway,
            **kwargs,
        )

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False, default_flow_style=False)

    @classmethod
    def from_yaml(cls, text: str) -> "ScenarioSpec":
        return cls.from_dict(yaml.safe_load(text))

    def write(self, path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_yaml(), encoding="utf-8")
        return path

    @classmethod
    def read(cls, path) -> "ScenarioSpec":
        return cls.from_yaml(Path(path).read_text(encoding="utf-8"))

    # -- identity -------------------------------------------------------

    def digest(self) -> str:
        """SHA-256 over the canonical form, for the run manifest (§7.4).

        Excludes ``prompt`` and ``notes``: two specs that command the same
        simulation must hash identically even if they were reached from
        different sentences. What the run depends on is the numbers.
        """
        payload = self.to_dict()
        payload.pop("prompt", None)
        payload.pop("notes", None)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    # -- presentation ---------------------------------------------------

    def render_table(self, width: int = 78) -> str:
        """The human-readable table §2.6 requires before a run executes."""
        rows = []
        for section, name, q in self.quantities():
            rows.append((section, name.replace("_", " "), q.render(),
                         str(q.source), q.note()))
        # W3: a stated rain rate renders with the environment rows.
        if self.precipitation_rate_mmh.value is not None:
            q = self.precipitation_rate_mmh
            at = max(i for i, row in enumerate(rows) if row[0] == "environment") + 1
            rows.insert(at, ("environment", "precipitation rate mmh", q.render(),
                             str(q.source), q.note()))
        # A stated time of day renders with the environment rows.
        if self.time_of_day.to_dict() != _default_time_of_day().to_dict():
            q = self.time_of_day
            at = max(i for i, row in enumerate(rows) if row[0] == "environment") + 1
            rows.insert(at, ("environment", "time of day", q.render(),
                             str(q.source), q.note()))
        # Each camera renders as its own labeled block, per-field sources
        # exactly like every scalar row. No cameras = no block: the table
        # states defaults through default_cameras at the render flow, not
        # by inventing rows the digest does not carry.
        for index, camera in enumerate(self.cameras):
            section = f"camera[{index}] {camera.camera_id.value}"
            for name, q in camera.quantities():
                rows.append((section, name.replace("_", " "), q.render(),
                             str(q.source), q.note()))
            if camera.moves:
                rows.append((section, "moves",
                             f"{len(camera.moves)} keyframes", "-",
                             "; ".join(f"t={m.get('t_s')}s"
                                       for m in camera.moves)))
            # Spec 8: a stated exposure renders with its sources; the
            # preset's default is not a row, exactly as it is not a key.
            if not camera.exposure.is_default(str(camera.preset.value)):
                for name, q in camera.exposure.quantities():
                    rows.append((section, f"exposure {name}", q.render(),
                                 str(q.source), q.note()))
        # The randomisation block, when it is not the documented default
        # (off): ranges and the drawn values, each with its source.
        if not self.randomization.is_default():
            for name, q in self.randomization.quantities():
                rows.append(("randomization", name.replace("_", " "),
                             q.render(), str(q.source), q.note()))
        if self.randomization_policy is not None:
            q = self.randomization_policy
            leaves = sorted(q.value) if isinstance(q.value, dict) else []
            rows.append(("randomization", "policy", f"{len(leaves)} leaves",
                         str(q.source),
                         "; ".join(bit for bit in (q.note(),
                                                   ", ".join(leaves)) if bit)))
        # Spec 8 blocks, when stated.
        for block_name, block in (("scene", self.scene),
                                  ("taxonomy", self.taxonomy),
                                  ("atmosphere", self.atmosphere),
                                  ("datum", self.datum),
                                  ("turbulence_model", self.turbulence_model),
                                  ("wind_profile", self.wind_profile),
                                  ("loading", self.loading),
                                  ("failures", self.failures),
                                  ("icing", self.icing),
                                  ("rain", self.rain),
                                  ("dis", self.dis),
                                  ("wake", self.wake),
                                  ("instruments", self.instruments),
                                  ("record", self.record),
                                  ("runway", self.runway)):
            if not block.is_default():
                for name, q in block.quantities():
                    rows.append((block_name, name.replace("_", " "),
                                 q.render(), str(q.source), q.note()))
        for index, entry in enumerate(self.traffic):
            for name, q in entry.quantities():
                rows.append((f"traffic[{index}]", name.replace("_", " "),
                             q.render(), str(q.source), q.note()))

        w_name = max(len(r[1]) for r in rows) + 1
        w_val = max(len(r[2]) for r in rows) + 1
        w_src = max(len(r[3]) for r in rows) + 1

        lines = [
            f"scenario: {self.name}",
        ]
        if self.prompt:
            lines.append(f'prompt:   "{self.prompt}"')
        lines.append(f"digest:   {self.digest()[:16]}")
        lines.append("")
        lines.append(
            f"  {'field'.ljust(w_name)} {'value'.ljust(w_val)} "
            f"{'source'.ljust(w_src)} provenance"
        )
        lines.append("  " + "-" * (width - 2))

        last_section = None
        for section, name, value, source, note in rows:
            if section != last_section:
                lines.append(f"  [{section}]")
                last_section = section
            lines.append(
                f"  {name.ljust(w_name)} {value.ljust(w_val)} "
                f"{source.ljust(w_src)} {note}"
            )

        counts = {}
        for _, _, q in self.quantities():
            counts[str(q.source)] = counts.get(str(q.source), 0) + 1
        lines.append("  " + "-" * (width - 2))
        lines.append(
            "  " + ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))
        )
        if self.notes:
            lines.append("")
            for note in self.notes:
                lines.append(f"  note: {note}")
        return "\n".join(lines)
