# Toolchain

The engine pin for Phase 3 and the machines it was measured on. One row per
machine; every row must show the same engine version (checklist A1).

**Decision, 2026-11-04 (decision 10, owner override of decision 1):** the engine is pinned
to **Unreal Engine 5.7** for Phase 3. The 2026-11-03 pin to 5.5 is superseded.
The Windows laptop has UE_5.7 installed. Written in `docs/phase3/decisions.md`
as decision 10. The 5.5 figures below (5.5.4, changelist 40574608, measured
2026-11-03) are measured history, kept because every number before this
decision was taken on 5.5.

| Machine | Engine (`Engine/Build/Build.version`) | Changelist | MSVC toolset | Windows SDK | Measured |
|---|---|---|---|---|---|
| Windows laptop (Phase 3 Windows session, `UE_ROOT=C:\Program Files\Epic Games\UE_5.7`) | 5.7.4 (`++UE5+Release-5.7`) | 51494982 (compatible 47537391) | 14.44.35207 | 10.0.26100.0 | 2026-11-04 |
| Reviewer's machine | 5.7.x, row pending: fill from `Engine/Build/Build.version` | pending | pending | pending | pending |
| Third machine | 5.7.x, row pending: fill from `Engine/Build/Build.version` | pending | pending | pending | pending |

Notes:

- The Windows laptop also has `UE_5.5` installed (5.5.4, `++UE5+Release-5.5`,
  changelist 40574608, compatible 37670630, MSVC 14.44.35207, SDK 10.0.26100.0,
  measured 2026-11-03). A3 uses it as the "other version" for the
  `engine.version_mismatch` check; nothing builds on it.
- Rows marked pending are filled by the machine itself when it first runs the
  A1 check; the version must read 5.7 or the row is a failure, not a new pin.
