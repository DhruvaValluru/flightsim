"""The pins live in ONE place: toolchain.json, and every file that repeats
one agrees with it (Phase 3 box B3, docs/phase3/notes/B3.md).

Engine: ``toolchain.json`` engine.version == ``ue/FlightSim.uproject``
EngineAssociation == both ``ue/Source/*.Target.cs`` IncludeOrderVersion ==
``core.util.platform.UE_ENGINE_VERSION``; engine.patch == ``UE_ENGINE_PATCH``.
Every file is read directly, so a hand change to any one of them fails
naming THAT file, even though the constant is itself derived from the json.

Python: ``requirements.lock`` (uv --universal --generate-hashes) covers
every pin in ``requirements.txt`` at the same version.

The B2 loader's refusals (``toolchain.pin_unreadable``) are checked here
too, because B3 owns this file (align_edits in the note).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from core.util import platform as plat

REPO = Path(__file__).resolve().parents[1]

TOOLCHAIN_JSON = REPO / "toolchain.json"
UPROJECT = REPO / "ue" / "FlightSim.uproject"
TARGET_CS_FILES = (
    REPO / "ue" / "Source" / "FlightSim.Target.cs",
    REPO / "ue" / "Source" / "FlightSimEditor.Target.cs",
)
REQUIREMENTS = REPO / "requirements.txt"
REQUIREMENTS_LOCK = REPO / "requirements.lock"
REQUIREMENTS_DEV = REPO / "requirements-dev.txt"
REQUIREMENTS_DEV_LOCK = REPO / "requirements-dev.lock"

try:  # packaging is a pip dependency, present in the repo venv.
    from packaging.requirements import Requirement
    from packaging.specifiers import SpecifierSet
    from packaging.utils import canonicalize_name
    from packaging.version import Version
    HAVE_PACKAGING = True
except ImportError:  # pragma: no cover - system python without packaging
    HAVE_PACKAGING = False

    def canonicalize_name(name: str) -> str:
        return re.sub(r"[-_.]+", "-", name).lower()


# A requirement line, ``name[extras] <op> version`` (fallback when
# ``packaging`` is absent; every requirements.txt pin is ``==``).
_REQ_LINE = re.compile(
    r"^([A-Za-z0-9_.-]+)\s*(?:\[[^\]]*\])?\s*(==|>=|<=|~=|!=|<|>)\s*([^\s;\\]+)")
# A lock entry start: ``name[extras]==version`` optionally followed by a
# ``; marker`` (uv --universal) and a trailing ``\`` before the hash lines.
_LOCK_LINE = re.compile(
    r"^([A-Za-z0-9_.-]+)\s*(?:\[[^\]]*\])?\s*==\s*([^\s;\\]+)")
_INCLUDE_ORDER = re.compile(r"EngineIncludeOrderVersion\.Unreal(\d+)_(\d+)")


def _read_toolchain() -> dict:
    return json.loads(TOOLCHAIN_JSON.read_text(encoding="utf-8"))


def _include_order(path: Path) -> str:
    """``"5.7"`` from ``IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_7``."""
    match = _INCLUDE_ORDER.search(path.read_text(encoding="utf-8"))
    assert match, f"{path.relative_to(REPO)} names no EngineIncludeOrderVersion.UnrealN_N"
    return f"{match.group(1)}.{match.group(2)}"


def _engine_association(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "EngineAssociation" in data, f"{path.relative_to(REPO)} has no EngineAssociation"
    return str(data["EngineAssociation"])


def _requirement_names_and_specs(path: Path) -> dict[str, str]:
    """Canonical name -> specifier string (``"==2.0.2"``) for every pin.

    Blank lines, ``#`` comments, ``-r``/``-c`` includes and other option
    lines (``--index-url`` ...) are skipped.
    """
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        if HAVE_PACKAGING:
            req = Requirement(line)
            pins[canonicalize_name(req.name)] = str(req.specifier)
        else:
            match = _REQ_LINE.match(line)
            assert match, f"{path.relative_to(REPO)}: unparsable requirement {line!r}"
            pins[canonicalize_name(match.group(1))] = match.group(2) + match.group(3)
    return pins


def _lock_pins(path: Path) -> dict[str, str]:
    """Canonical name -> version for a ``--generate-hashes`` lock.

    An entry begins with ``name==version \\`` (uv --universal may add a
    ``; marker``); the ``--hash=sha256:...`` continuation lines and the
    ``# via ...`` comments are skipped. ``name[extra]==v`` reduces to name.
    A name locked twice (once per marker) keeps every version seen.
    """
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("--hash"):
            continue
        match = _LOCK_LINE.match(line)
        if not match:
            continue
        name = canonicalize_name(match.group(1))
        version = match.group(2)
        pins[name] = version if name not in pins or pins[name] == version \
            else pins[name] + "," + version
    return pins


# --- the engine pin ---------------------------------------------------------


def test_engine_pin_is_one_value_in_every_file():
    toolchain = _read_toolchain()
    values = {
        "toolchain.json engine.version": toolchain["engine"]["version"],
        "ue/FlightSim.uproject EngineAssociation": _engine_association(UPROJECT),
        "core/util/platform.py UE_ENGINE_VERSION": plat.UE_ENGINE_VERSION,
    }
    for target in TARGET_CS_FILES:
        values[f"{target.relative_to(REPO).as_posix()} IncludeOrderVersion"] = \
            _include_order(target)
    distinct = sorted(set(values.values()))
    listing = "\n".join(f"  {where}: {value}" for where, value in values.items())
    assert len(distinct) == 1, (
        f"the engine pin is not one value: {distinct}\n{listing}\n"
        "The pin is stated in toolchain.json; the odd file above disagrees with it.")

    # The patch level is the pin's companion (decision 13 / A2).
    assert toolchain["engine"]["patch"] == plat.UE_ENGINE_PATCH, (
        f"toolchain.json engine.patch is {toolchain['engine']['patch']!r} but "
        f"core/util/platform.py UE_ENGINE_PATCH is {plat.UE_ENGINE_PATCH!r}")
    assert isinstance(toolchain["engine"]["patch"], int)


# --- the python pins --------------------------------------------------------


def _assert_lock_covers(requirements: Path, lock: Path) -> None:
    req_name = requirements.relative_to(REPO).as_posix()
    lock_name = lock.relative_to(REPO).as_posix()
    assert lock.exists(), f"{lock_name} is missing; it must cover {req_name}"
    pins = _requirement_names_and_specs(requirements)
    locked = _lock_pins(lock)
    assert pins, f"{req_name} pins nothing"
    assert locked, f"{lock_name} locks nothing (expected name==version \\ entries)"

    problems = []
    for name, spec in pins.items():
        if name not in locked:
            problems.append(f"{name}: pinned {spec or '(any)'} in {req_name}, "
                            f"absent from {lock_name}")
            continue
        versions = locked[name].split(",")
        if spec.startswith("==") and "," not in spec:
            want = spec[2:].strip()
            if any(canonicalize_name(v) != canonicalize_name(want) for v in versions):
                problems.append(f"{name}: {req_name} pins {spec}, "
                                f"{lock_name} locks {locked[name]}")
        elif spec:
            if HAVE_PACKAGING:
                allowed = SpecifierSet(spec)
                bad = [v for v in versions if Version(v) not in allowed]
                if bad:
                    problems.append(f"{name}: {req_name} wants {spec}, "
                                    f"{lock_name} locks {','.join(bad)}")
            else:  # pragma: no cover - the repo's pins are all ``==``
                problems.append(f"{name}: {req_name} spec {spec} needs the "
                                "packaging module to check against "
                                f"{lock_name} {locked[name]}")
    assert not problems, (
        f"{lock_name} does not cover {req_name}:\n  " + "\n  ".join(problems)
        + f"\nRegenerate it: uv pip compile {req_name} --universal "
          f"--generate-hashes -o {lock_name}")


def test_lock_covers_requirements():
    _assert_lock_covers(REQUIREMENTS, REQUIREMENTS_LOCK)
    # requirements-dev.txt is covered only once B1 ships a dev lock (the
    # note: B1 decides); without one there is nothing to compare.
    if REQUIREMENTS_DEV_LOCK.exists():
        _assert_lock_covers(REQUIREMENTS_DEV, REQUIREMENTS_DEV_LOCK)


def test_lock_parser_reads_the_repo_lock_format():
    """The parser understands the real lock: every requirements.txt name is
    found and the hash lines never masquerade as entries."""
    locked = _lock_pins(REQUIREMENTS_LOCK)
    assert "numpy" in locked
    assert not any(name.startswith("hash") for name in locked)
    for version in locked.values():
        for one in version.split(","):
            assert re.match(r"^\d", one), f"lock version {one!r} is not a version"


# --- the B2 loader's refusals (housed here; B3 owns this file) -------------


def test_load_toolchain_refuses_a_missing_file(tmp_path):
    with pytest.raises(RuntimeError, match="toolchain.pin_unreadable"):
        plat.load_toolchain(tmp_path / "absent.json")


def test_load_toolchain_refuses_a_file_without_an_engine_pin(tmp_path):
    path = tmp_path / "toolchain.json"
    path.write_text(json.dumps({"ffmpeg": "9.0.2"}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="toolchain.pin_unreadable") as info:
        plat.load_toolchain(path)
    assert "engine" in str(info.value)


def test_load_toolchain_refuses_bad_json(tmp_path):
    path = tmp_path / "toolchain.json"
    path.write_text('{"engine": {"version": "5.7", "patch": 4', encoding="utf-8")
    with pytest.raises(RuntimeError, match="toolchain.pin_unreadable") as info:
        plat.load_toolchain(path)
    assert "JSON" in str(info.value)


def test_load_toolchain_reads_the_repo_manifest():
    data = plat.load_toolchain(TOOLCHAIN_JSON)
    assert data["engine"]["version"] == plat.UE_ENGINE_VERSION
    assert data["engine"]["patch"] == plat.UE_ENGINE_PATCH
    assert not any(str(key).startswith("_") for key in data)
