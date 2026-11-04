# Toolchain

The engine pin for Phase 3 and the machines it was measured on. One row per
machine; every row must show the same engine version (checklist A1).

**Decision, 2026-11-03 (Phase 3 Windows decision agent, per the plan's
recommendation and the weekend Windows review):** the engine is pinned to
**Unreal Engine 5.5** for Phase 3. 5.7 never built on the reviewer's machines;
5.5 is installed and every measurement before October was taken on it.
Written in `docs/phase3/decisions.md`, line 1.

| Machine | Engine (`Engine/Build/Build.version`) | Changelist | MSVC toolset | Windows SDK | Measured |
|---|---|---|---|---|---|
| Windows laptop (Phase 3 Windows session, `UE_ROOT=C:\Program Files\Epic Games\UE_5.5`) | 5.5.4 (`++UE5+Release-5.5`) | 40574608 (compatible 37670630) | 14.44.35207 | 10.0.26100.0 | 2026-11-03 |
| Reviewer's machine | 5.5.x, row pending: fill from `Engine/Build/Build.version` | pending | pending | pending | pending |
| Third machine | 5.5.x, row pending: fill from `Engine/Build/Build.version` | pending | pending | pending | pending |

Notes:

- The Windows laptop also has `UE_5.7` installed next to 5.5. A3 uses it as the
  "other version" for the `engine.version_mismatch` check; nothing builds on it.
- Rows marked pending are filled by the machine itself when it first runs the
  A1 check; the version must read 5.5 or the row is a failure, not a new pin.
