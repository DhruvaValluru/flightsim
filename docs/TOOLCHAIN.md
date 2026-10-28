# Toolchain — the engine and build tools on each machine

Phase 3, step A1 (`tasks/phase3_todo.md`). One engine version, the same on
every machine that builds or renders FlightSim.

## Decision

**2026-10-27 — Dhruva Valluru (owner): the engine is Unreal Engine 5.7, patch
5.7.4, on all three machines.** This confirms the 2026-10-19 decision (5.7, for
render quality). There is no fallback to an older engine and no building on
two versions at once. A machine without 5.7.4 installs it before any other A-step.

The project already names 5.7 everywhere it pins the engine:
`ue/FlightSim.uproject` (`EngineAssociation`), `ue/Source/FlightSim.Target.cs`
and `ue/Source/FlightSimEditor.Target.cs` (`EngineIncludeOrderVersion.Unreal5_7`),
`core/util/platform.py` (`UE_ENGINE_VERSION`), `scripts/build_ue.ps1` and
`scripts/ue_preflight.ps1`. A2 adds the patch level (`UE_ENGINE_PATCH = "5.7.4"`).

## Per machine

Read the engine version from `<UE_ROOT>/Engine/Build/Build.version`
(`MajorVersion.MinorVersion.PatchVersion` and `Changelist`). Read the MSVC
toolset and Windows SDK from the build log's first lines (`Using Visual Studio
… toolchain … and Windows … SDK`).

| Machine | Engine (Major.Minor.Patch) | Changelist | MSVC toolset | Windows SDK | Recorded |
|---|---|---|---|---|---|
| Owner's machine | 5.7.4 | *to record* | *to record* | *to record* | 5.7.4 measured in earlier runs; other columns pending |
| Reviewer's machine | 5.7.4 (to install; had 5.5) | *to record* | *to record* | *to record* | pending |
| Third machine | 5.7.4 (to install) | *to record* | *to record* | *to record* | pending |

A1 is done when all three rows are measured from the machine itself, show the
same engine version and changelist, and each "Recorded" cell carries the date and
who read it.
