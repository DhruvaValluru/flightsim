"""The capture manifest's published schema, and a validator for it.

``docs/schemas/capture_manifest.v<N>.schema.json`` is the contract a
downstream consumer validates against before parsing: JSON Schema
(draft 2020-12 vocabulary), one file per manifest version, the
``manifest_version`` pinned by ``const``. The verifier's ``json_schema``
check runs it over every manifest, and a test pins the schema's version
to the writer's.

The validator here is deliberately small and dependency-free (the
repo's install must stay a pip of pinned wheels on a fresh Windows
machine): it implements the subset of keywords the schema uses --
``type``, ``properties``, ``required``, ``additionalProperties``,
``items``, ``minItems`` / ``maxItems``, ``enum``, ``const``,
``minimum`` / ``maximum``, ``pattern``, ``anyOf`` and ``$ref`` into
``$defs`` -- and refuses a schema that uses any other keyword rather
than silently ignoring it, so the file cannot drift past what is
enforced. A consumer with a full validator (``jsonschema``,
``ajv``, ...) can validate the same file directly.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas"

SUPPORTED_KEYWORDS = {
    "$schema", "$id", "$defs", "title", "description", "type", "properties",
    "required", "additionalProperties", "items", "minItems", "maxItems",
    "enum", "const", "minimum", "maximum", "pattern", "anyOf", "$ref",
}

_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: (isinstance(v, (int, float)) and not isinstance(v, bool)
                         and math.isfinite(v)),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


class SchemaError(ValueError):
    """The schema file itself is missing or uses an unsupported keyword."""


def schema_path(manifest: Dict[str, Any]) -> Path:
    version = manifest.get("manifest_version")
    return SCHEMA_DIR / f"capture_manifest.v{version}.schema.json"


def load_schema(path) -> Dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise SchemaError(f"no schema file at {path}")
    schema = json.loads(path.read_text(encoding="utf-8"))
    _check_keywords(schema, "#")
    return schema


def _check_keywords(node: Any, where: str) -> None:
    if isinstance(node, dict):
        unknown = set(node) - SUPPORTED_KEYWORDS
        if unknown and where.rsplit("/", 1)[-1] not in ("properties", "$defs"):
            raise SchemaError(
                f"schema keyword(s) {sorted(unknown)} at {where} are not "
                f"enforced by this validator; add them to core.capture."
                f"schema or do not use them")
        for key, value in node.items():
            if key in ("properties", "$defs"):
                for name, sub in value.items():
                    _check_keywords(sub, f"{where}/{key}/{name}")
            elif key in ("items", "additionalProperties") and isinstance(value, dict):
                _check_keywords(value, f"{where}/{key}")
            elif key == "anyOf":
                for i, sub in enumerate(value):
                    _check_keywords(sub, f"{where}/anyOf/{i}")


def validate(instance: Any, schema: Dict[str, Any],
             root: Optional[Dict[str, Any]] = None, path: str = "$"
             ) -> List[str]:
    """Every violation as ``"<path>: <message>"``; [] when valid."""
    root = root if root is not None else schema
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/"):
            raise SchemaError(f"only #/$defs/<name> references are supported, not {ref!r}")
        target = root.get("$defs", {}).get(ref[len("#/$defs/"):])
        if target is None:
            raise SchemaError(f"unresolved reference {ref!r}")
        return validate(instance, target, root, path)
    out: List[str] = []
    if "anyOf" in schema:
        branches = [validate(instance, sub, root, path) for sub in schema["anyOf"]]
        if not any(not b for b in branches):
            out.append(f"{path}: matches none of {len(branches)} alternatives "
                       f"(first: {branches[0][0] if branches[0] else '?'})")
            return out
    if "const" in schema and instance != schema["const"]:
        out.append(f"{path}: expected {schema['const']!r}, got {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        out.append(f"{path}: {instance!r} is not one of {schema['enum']}")
    if "type" in schema:
        allowed = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_TYPES[t](instance) for t in allowed):
            out.append(f"{path}: expected {'/'.join(allowed)}, got "
                       f"{type(instance).__name__}"
                       + (" (non-finite)" if isinstance(instance, float) else ""))
            return out
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            out.append(f"{path}: {instance!r} is below the minimum {schema['minimum']!r}")
        if "maximum" in schema and instance > schema["maximum"]:
            out.append(f"{path}: {instance!r} is above the maximum {schema['maximum']!r}")
    if isinstance(instance, str) and "pattern" in schema:
        if re.search(schema["pattern"], instance) is None:
            out.append(f"{path}: {instance!r} does not match {schema['pattern']!r}")
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                out.append(f"{path}: missing required key {key!r}")
        properties = schema.get("properties", {})
        for key, value in instance.items():
            if key in properties:
                out.extend(validate(value, properties[key], root, f"{path}.{key}"))
            elif schema.get("additionalProperties", True) is False:
                out.append(f"{path}: unexpected key {key!r}")
            elif isinstance(schema.get("additionalProperties"), dict):
                out.extend(validate(value, schema["additionalProperties"], root,
                                    f"{path}.{key}"))
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            out.append(f"{path}: {len(instance)} item(s), at least "
                       f"{schema['minItems']} required")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            out.append(f"{path}: {len(instance)} item(s), at most "
                       f"{schema['maxItems']} allowed")
        if "items" in schema:
            for i, item in enumerate(instance):
                out.extend(validate(item, schema["items"], root, f"{path}[{i}]"))
    return out


def validate_manifest(manifest: Dict[str, Any]) -> List[str]:
    """The manifest against the schema of its own version."""
    return validate(manifest, load_schema(schema_path(manifest)))
