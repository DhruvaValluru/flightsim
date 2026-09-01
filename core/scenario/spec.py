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

from .camera import CameraSpec
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
SPEC_VERSION = 6


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

        match = re.fullmatch(r"cameras\[(\d+)\]\.(\w+)", name)
        if match is None:
            return None
        index = int(match.group(1))
        if index >= len(self.cameras):
            raise ValueError(
                f"spec has {len(self.cameras)} camera(s); {name} does not "
                f"exist")
        field = match.group(2)
        if field not in CameraSpec.FIELD_ORDER:
            raise ValueError(f"{field!r} is not a camera field")
        return self.cameras[index], field

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
        # Always present: the canonical form has exactly one spelling of
        # "no cameras" (the empty list), so the digest cannot fork on an
        # absent-vs-empty distinction.
        out["cameras"] = [camera.to_dict() for camera in self.cameras]
        if self.notes:
            out["notes"] = list(self.notes)
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScenarioSpec":
        version = data.get("spec_version")
        if version != SPEC_VERSION:
            raise ValueError(
                f"spec_version {version!r} is not supported by this build "
                f"(expects {SPEC_VERSION}). Refusing to guess at the schema."
            )
        kwargs = {}
        for section, name in cls.FIELD_ORDER:
            try:
                kwargs[name] = Quantity.from_dict(data[section][name])
            except KeyError as exc:
                raise ValueError(
                    f"spec is missing required field {section}.{name}"
                ) from exc
        cameras_data = data.get("cameras", [])
        if not isinstance(cameras_data, list):
            raise ValueError("spec 'cameras' must be a list of camera "
                             "mappings")
        return cls(
            name=data.get("name", "scenario"),
            prompt=data.get("prompt"),
            notes=list(data.get("notes", [])),
            cameras=[CameraSpec.from_dict(entry) for entry in cameras_data],
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
