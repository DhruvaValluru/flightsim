"""Show the catalogue, or render one entry.

    python -m core.messages                       every entry, sentence and hint
    python -m core.messages camera.terrain_clearance actual=-89.5 limit=2

Parameters are ``name=value``; a value that parses as a number is
passed as one (so plural forms and derived numbers work), anything
else as text. Exit 1 when a named entry is not in the catalogue -- the
raw name is printed, which is exactly what the interface would show.
"""
from __future__ import annotations

import os
import sys
from typing import Any

from . import catalogue, hint, is_catalogued, render


def _value(text: str) -> Any:
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        width = max(len(name) for name in catalogue())
        try:
            for name, entry in catalogue().items():
                print(f"{name:<{width}}  {entry['sentence']}")
                if entry.get("hint"):
                    print(f"{'':<{width}}    -> {entry['hint']}")
        except BrokenPipeError:
            # `| head` closed the pipe: not an error worth a traceback.
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    name, rest = argv[0], argv[1:]
    params = {}
    for item in rest:
        key, _, value = item.partition("=")
        params[key] = _value(value)
    print(render(name, **params))
    if hint(name, **params):
        print(f"  -> {hint(name, **params)}")
    print(f"  [{name}]")
    return 0 if is_catalogued(name) else 1


if __name__ == "__main__":
    sys.exit(main())
