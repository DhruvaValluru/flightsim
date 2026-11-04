# Toolchain

The engine pin for Phase 3 and the machines it was measured on. One row per
machine; every row must show the same engine version (checklist A1).

**Decision, 2026-11-04 (owner override, recorded by the Phase 3 Windows
decision agent as decision 10):** the engine is pinned to **Unreal Engine 5.7**
for Phase 3; the owner states the integration was instructed to 5.7. This
replaces the 2026-11-03 pin to 5.5 (decision 1, which had no Cesium for Unreal
release on this machine). Written in `docs/phase3/decisions.md`, item 10.

| Machine | Engine (`Engine/Build/Build.version`) | Changelist | MSVC toolset | Windows SDK | Measured |
|---|---|---|---|---|---|
| Windows laptop (Phase 3 Windows session, `UE_ROOT=C:\Program Files\Epic Games\UE_5.7`) | 5.7.4 (`++UE5+Release-5.7`) | 51494982 (compatible 47537391) | 14.44.35207 | 10.0.26100.0 | 2026-11-04 |
| Reviewer's machine | 5.7.x, row pending: fill from `Engine/Build/Build.version` | pending | pending | pending | pending |
| Third machine | 5.7.x, row pending: fill from `Engine/Build/Build.version` | pending | pending | pending | pending |

Notes:

- The Windows laptop also has `UE_5.5` (5.5.4, changelist 40574608) installed
  next to 5.7. A3 uses it as the "other version" for the
  `engine.version_mismatch` check; nothing builds on it. Cesium for Unreal
  2.30.0 is installed in the 5.7 engine's `Engine/Plugins/Marketplace`.
- Rows marked pending are filled by the machine itself when it first runs the
  A1 check; the version must read 5.7 or the row is a failure, not a new pin.
