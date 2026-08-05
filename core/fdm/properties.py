"""Validated access to the JSBSim property tree.

Why this module exists
----------------------
``FGPropertyManager`` creates nodes on demand. Measured against the pinned
JSBSim 1.2.4:

    >>> fdm.set_property_value("totally/made/up/property", 42.0)
    >>> fdm.get_property_value("totally/made/up/property")
    42.0
    >>> fdm.get_property_value("never/written/at/all")
    0.0

A misspelled property therefore writes successfully, reads back the value you
wrote, and has no effect whatsoever on the simulation. A misspelled read
returns a plausible zero. This is the lowest-level instance of the failure that
made the previous build's conditions unverifiable (§1.6): the HUD advertised
wind that the FDM never received.

Every access in this codebase goes through :class:`PropertyAccess`, which
resolves names against the loaded model's catalog and raises on anything it
cannot account for.

Catalog quirks, measured rather than assumed
--------------------------------------------
* Index 0 is written *without* a subscript. The catalog contains
  ``fcs/throttle-cmd-norm`` and ``fcs/throttle-cmd-norm[1]`` but never
  ``fcs/throttle-cmd-norm[0]`` -- though that name does alias correctly to the
  unindexed node. ``[0]`` suffixes are therefore stripped before lookup rather
  than rejected. The same applies to ``gear/unit[0]/...``.
* Access flags are ``(R)``, ``(RW)`` and ``(W)``. Writes to an ``(R)`` node are
  ignored by JSBSim without any diagnostic, so they are rejected here.
* The catalog grows during load and ``run_ic``; :meth:`refresh` re-reads it.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional

from .errors import ReadOnlyPropertyError, UnknownPropertyError

#: Matches an explicit ``[0]`` subscript on any path segment.
_ZERO_INDEX = re.compile(r"\[0\]")

READABLE = frozenset({"(R)", "(RW)"})
WRITABLE = frozenset({"(W)", "(RW)"})


def _canonical(name: str) -> str:
    """Strip ``[0]`` subscripts, which JSBSim omits in catalog entries."""
    return _ZERO_INDEX.sub("", name)


class PropertyAccess:
    """A checked facade over ``FGFDMExec``'s property getters and setters.

    Parameters
    ----------
    exec_:
        A loaded ``jsbsim.FGFDMExec``. The model must already be loaded; the
        catalog is empty before that.
    """

    def __init__(self, exec_) -> None:
        self._exec = exec_
        self._access: Dict[str, str] = {}
        self.refresh()

    # -- catalog -------------------------------------------------------

    def refresh(self) -> None:
        """Re-read the property catalog from the executive.

        Call after loading a model or running initial conditions; JSBSim adds
        nodes at both points.
        """
        access: Dict[str, str] = {}
        for entry in self._exec.get_property_catalog():
            parts = entry.rsplit(" ", 1)
            if len(parts) == 2 and parts[1].startswith("("):
                access[parts[0]] = parts[1]
            else:
                # No flag reported; treat as read/write rather than guessing.
                access[entry] = "(RW)"
        self._access = access

    def __len__(self) -> int:
        return len(self._access)

    def names(self) -> List[str]:
        """All catalog property names, sorted."""
        return sorted(self._access)

    def has(self, name: str) -> bool:
        """True if ``name`` resolves to a real node in the loaded model."""
        return _canonical(name) in self._access

    def access_of(self, name: str) -> Optional[str]:
        """The ``(R)``/``(RW)``/``(W)`` flag for ``name``, or None if unknown."""
        return self._access.get(_canonical(name))

    def search(self, fragment: str) -> List[str]:
        """Catalog names containing ``fragment``. For interactive use."""
        return sorted(n for n in self._access if fragment in n)

    # -- checked access ------------------------------------------------

    def _resolve_readable(self, name: str) -> str:
        canon = _canonical(name)
        flag = self._access.get(canon)
        if flag is None:
            raise UnknownPropertyError(
                f"{name!r} is not in the loaded model's property catalog "
                f"({len(self._access)} entries). JSBSim would silently return "
                f"0.0 for this read. Check spelling; note that index 0 is "
                f"written without a subscript."
            )
        if flag not in READABLE:
            raise UnknownPropertyError(
                f"{name!r} is write-only ({flag}); it cannot be read."
            )
        return canon

    def _resolve_writable(self, name: str) -> str:
        canon = _canonical(name)
        flag = self._access.get(canon)
        if flag is None:
            raise UnknownPropertyError(
                f"{name!r} is not in the loaded model's property catalog "
                f"({len(self._access)} entries). JSBSim would silently create "
                f"this node, accept the write, and never apply it to the "
                f"simulation. Check spelling; note that index 0 is written "
                f"without a subscript."
            )
        if flag not in WRITABLE:
            raise ReadOnlyPropertyError(
                f"{name!r} is read-only ({flag}). JSBSim ignores writes to it "
                f"without any diagnostic, so this would appear to succeed."
            )
        return canon

    def get(self, name: str) -> float:
        """Read a property, raising if it does not exist."""
        return self._exec.get_property_value(self._resolve_readable(name))

    def set(self, name: str, value: float) -> None:
        """Write a property, raising if it does not exist or is read-only."""
        self._exec.set_property_value(self._resolve_writable(name), float(value))

    def get_many(self, names: Iterable[str]) -> Dict[str, float]:
        """Read several properties into a dict, raising on the first bad name."""
        return {n: self.get(n) for n in names}

    def set_many(self, values: Dict[str, float]) -> None:
        """Write several properties.

        Names are validated *before* any write, so a typo in the last entry
        cannot leave the simulation half-configured.
        """
        resolved = {self._resolve_writable(n): float(v) for n, v in values.items()}
        for canon, value in resolved.items():
            self._exec.set_property_value(canon, value)

    def require(self, names: Iterable[str]) -> None:
        """Assert that every name in ``names`` exists, listing all that do not.

        Used at construction time by subsystems that depend on a fixed set of
        properties, so a model missing one fails immediately with a complete
        list rather than at some later step with a partial one.
        """
        missing = [n for n in names if not self.has(n)]
        if missing:
            raise UnknownPropertyError(
                f"{len(missing)} required propert"
                f"{'y is' if len(missing) == 1 else 'ies are'} absent from the "
                f"loaded model: {sorted(missing)}"
            )
