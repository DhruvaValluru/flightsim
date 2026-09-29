"""P9, the physics engine side: the uncompiled C++ pinned by reading it.

There is no Unreal Engine here, so the host's half of the physics blocks is
written and pinned by tests that READ the source (and, where the code is
pure arithmetic with no engine type in it, compile that part alone against
a minimal stand-in header and run it):

* FlightSimScenarioWorld reads every physics card block with the
  turbulence_properties discipline -- each block's keys equal to the Python
  writer's CARD_KEYS in order, the blocks in the fixed order, a malformed
  block refused by name as "REFUSED -- <name>: <sentence>" -- and every
  name is catalogued;
* the order of the writes: the pre-trim batch (atmosphere, loading, icing
  neutral values) written by the plugin AFTER its RunIC and BEFORE its trim,
  the atmosphere again every step, the gust batch every step zero included,
  the failure schedule once at the first step with t >= at_s, the icing
  writes every step;
* FlightSimWake is a line-for-line port of core/environment/wake.py: the
  32-point Gauss-Legendre table equals numpy's to the bit, and the compiled
  port reproduces the card's selftest vectors and the provider's per-step
  field, and refuses a vector off by more than 1e-9;
* the recorder's channel table carries every REGISTRY.host_channels() entry;
* the plugin's local patches 5 (the aircraft root, the XML sha256 at the
  door) and 6 (the pre-trim batch), recorded in VENDORED.json;
* the render.json environment keys, graded by core/capture/verify.py only
  when present (check.host_physics), and the card's derived_aircraft block.

The first Windows build is the verification of everything read here.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from core.capture import verify
from core.environment import atmosphere, icing, shear, von_karman, wake
from core.messages import is_catalogued
from core.registry import REGISTRY
from core.scenario import card as card_module
from core.scenario import loading
from core.telemetry import failures, limits

REPO = Path(__file__).resolve().parents[1]
BRIDGE = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge"
WORLD_CPP = BRIDGE / "Private/FlightSimScenarioWorld.cpp"
WORLD_H = BRIDGE / "Public/FlightSimScenarioWorld.h"
WAKE_CPP = BRIDGE / "Private/FlightSimWake.cpp"
WAKE_H = BRIDGE / "Public/FlightSimWake.h"
RECORDER_CPP = BRIDGE / "Private/FlightSimTelemetryRecorder.cpp"
PLUGIN = REPO / "ue/Plugins/JSBSimFlightDynamicsModel"
MOVEMENT_CPP = PLUGIN / "Source/JSBSimFlightDynamicsModel/Private/JSBSimMovementComponent.cpp"
MOVEMENT_H = PLUGIN / "Source/JSBSimFlightDynamicsModel/Public/JSBSimMovementComponent.h"

#: The physics blocks, in the fixed order the host reads them, with their
#: Python writers' key orders.
BLOCK_KEYS = {
    "atmosphere_properties": ("AtmosphereCardKeys", atmosphere.CARD_KEYS),
    "loading_properties": ("LoadingCardKeys", loading.CARD_KEYS),
    "failure_schedule": ("FailureCardKeys", failures.CARD_KEYS),
    "icing_schedule": ("IcingCardKeys", icing.CARD_KEYS),
    "gust_table": ("GustTableCardKeys", von_karman.CARD_KEYS),
    "layered_wind": ("LayeredWindCardKeys", shear.CARD_KEYS),
    "wake": ("WakeCardKeys", wake.CARD_KEYS),
    "derived_aircraft": ("DerivedAircraftCardKeys", card_module.DERIVED_AIRCRAFT_CARD_KEYS),
}
REFUSALS = ("card.atmosphere_properties", "card.loading_properties", "card.failure_schedule",
            "card.icing_schedule", "card.gust_table", "gust_table.length", "card.layered_wind",
            "card.wake", "card.derived_aircraft")


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def body(source: str, signature: str) -> str:
    """The text of a C++ function (or namespace) from its signature to the
    brace that closes it."""
    start = source.index(signature)
    open_at = source.index("{", start)
    depth = 0
    for index in range(open_at, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(f"unbalanced braces after {signature!r}")


def cpp_string_array(source: str, name: str):
    match = re.search(r"const TCHAR\* const " + name + r"\[\] = \{(.*?)\};", source, re.S)
    assert match, f"{name} not found"
    return tuple(re.findall(r'TEXT\("([^"]*)"\)', match.group(1)))


# -- the card blocks: the discipline, the order, the refusals ------------------------------

def test_every_block_key_order_is_the_python_writers():
    source = text(WORLD_CPP)
    for block, (array, python_keys) in BLOCK_KEYS.items():
        assert cpp_string_array(source, array) == tuple(python_keys), block
    assert cpp_string_array(source, "LoadingStationKeys") == ("name", "property", "lbs")
    assert cpp_string_array(source, "LoadingTankKeys") == ("index", "property", "lbs")
    assert cpp_string_array(source, "FailureEventKeys") == failures.CARD_EVENT_KEYS
    assert cpp_string_array(source, "IcingKKeys") == icing.K_KEYS
    assert cpp_string_array(source, "WakeSelftestKeys") == wake.SELFTEST_KEYS
    assert cpp_string_array(source, "IcingProperties") == icing.PROPERTIES


def test_blocks_are_read_in_the_fixed_order_with_the_key_discipline():
    reader = re.sub(r"\s+", " ", body(text(WORLD_CPP), "bool ReadPhysicsBlocks("))
    positions = [reader.index(f'HasField(TEXT("{block}"))') for block in BLOCK_KEYS]
    assert positions == sorted(positions), "the blocks are not read in the fixed order"
    for block, (array, _) in BLOCK_KEYS.items():
        assert f"BlockKeysInOrder(*Block, {array}, PhysicsCount({array}), Why)" in reader, block
    # The discipline itself: the exact count, then every key in position.
    check = body(text(WORLD_CPP), "bool BlockKeysInOrder(")
    assert "Block->Values.Num() != Count" in check
    assert "Field.Key != Keys[Position]" in check
    # ReadCard hands every card to the reader after the rate and duration.
    read_card = body(text(WORLD_CPP), "bool FFlightSimScenarioWorld::ReadCard(")
    assert read_card.rstrip("}").rstrip().endswith("return ReadPhysicsBlocks(Root, Out, Error);")


def test_every_refusal_is_named_logged_and_catalogued():
    source = text(WORLD_CPP)
    refuse = body(source, "bool RefuseCard(")
    assert 'TEXT("REFUSED -- %s")' in refuse and "UE_LOG(LogFlightSimScenario, Error" in refuse
    for name in REFUSALS:
        assert f'TEXT("{name}: ' in source, name
        assert is_catalogued(name), name
    # The scanner tests/test_messages.py runs over the engine sees them there.
    from tests.test_messages import ALLOWED_FUTURE, scan_codebase

    found = scan_codebase()
    site = ('TEXT("<name>: " message prefix @ '
            "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimScenarioWorld.cpp")
    for name in REFUSALS:
        assert site in found.get(name, set()), name
        assert name not in ALLOWED_FUTURE, name


def test_gust_table_length_and_digest_follow_the_writer():
    reader = body(text(WORLD_CPP), "bool ReadPhysicsBlocks(")
    # von_karman: one row per step and the first -- int(round(d * r)) + 1.
    # (Python's int(round(x)) is half to even: PhysicsPythonRound, run below.)
    assert "PhysicsPythonRound(Out.DurationSeconds * Out.RateHz) + 1" in reader
    # rows_sha256: fields joined by one space, rows by one newline, ASCII.
    assert 'RowsText += TEXT(" ");' in reader and 'RowsText += TEXT("\\n");' in reader
    assert "Fields->Num() != 5" in reader
    rows = [["0", "1.5", "-2.25e-05", "3", "4"], ["0.0083333333333333332", "5", "6", "7", "8"]]
    joined = "\n".join(" ".join(row) for row in rows)
    assert von_karman.VonKarmanTurbulence.rows_sha256(rows) == \
        hashlib.sha256(joined.encode("ascii")).hexdigest()


# -- the order of the writes ---------------------------------------------------------------

def test_the_pre_trim_batch_runs_after_runic_and_before_the_trim():
    prepare = body(text(MOVEMENT_CPP), "void UJSBSimMovementComponent::PrepareJSBSim()")
    run_ic = prepare.index("Exec->RunIC();")
    batch = prepare.index("LOCAL PATCH 6")
    write = prepare.index("node->setStringValue(TCHAR_TO_UTF8(*PreTrimValues[Write]));")
    relatch = prepare.index("Exec->RunIC();", write)
    trim = prepare.index("DoTrim();")
    assert run_ic < batch < write < relatch < trim
    assert "PreTrimRelatchAfter[Write]" in prepare[write:relatch]
    # The card's CAS is re-stated before every re-latch, as the headless
    # re-latch re-states ic/vc-kts (JSBSim holds the IC speed as TAS: a
    # stated day would otherwise trim both hosts at different airspeeds).
    restate = prepare.index("IC->SetVcalibratedKtsIC(InitialCalibratedAirSpeedKts);", write)
    assert write < restate < relatch
    import inspect

    from core.fdm.fdm import FlightDynamics

    headless = inspect.getsource(FlightDynamics.relatch_initial_conditions)
    assert '"ic/vc-kts"' in headless and headless.index("set_many(speed)") < \
        headless.index("self._exec.run_ic()")
    verify_trim = body(text(WORLD_CPP), "bool FFlightSimScenarioWorld::VerifyTrimmedCondition(")
    assert "const double ExpectedAirspeed = Card.AirspeedKnots;" in verify_trim
    # The bridge hands the batch over before BeginPlay runs PrepareJSBSim,
    # atmosphere first (re-latched after each write), then the loading,
    # then the icing's neutral values.
    populate = body(text(WORLD_CPP), "bool FFlightSimScenarioWorld::Populate(")
    handed = populate.index("Movement->PreTrimProperties = BatchProperties;")
    assert handed < populate.index("Movement->RegisterComponent();")
    assert handed < populate.index("Movement->LoadAircraft(true);")
    order = [populate.index(s) for s in ("Card.AtmosphereProperties[Index]",
                                         "BatchProperties.Append(Card.LoadingProperties);",
                                         "BatchProperties.Add(IcingProperties[Index]);")]
    assert order == sorted(order)
    assert "BatchRelatch.Add(true);" in populate
    # Every host binds (the CG read back) before any wind write or re-trim.
    trim_in_wind = body(text(WORLD_CPP), "bool FFlightSimScenarioWorld::TrimInWind(")
    assert trim_in_wind.index("BindPhysicsBlocks(Card, Error)") < \
        trim_in_wind.index("simulation/do_simple_trim")


def test_the_loading_cg_is_read_back_before_the_trim_against_the_card():
    bind = body(text(WORLD_CPP), "bool FFlightSimScenarioWorld::BindPhysicsBlocks(")
    assert "FMath::Abs(CgIn - Card.LoadingExpectedCgIn) > Card.LoadingToleranceIn" in bind
    assert 'TEXT("card.loading_properties: the centre of gravity read back' in bind
    populate = body(text(WORLD_CPP), "bool FFlightSimScenarioWorld::Populate(")
    reads = populate.index('Movement->PreTrimReadProperties.Add(TEXT("inertia/cg-x-in"));')
    assert reads < populate.index('Movement->PreTrimReadProperties.Add(TEXT("velocities/vc-kts"));')
    assert loading.PROPERTY_CG == "inertia/cg-x-in"


def test_every_step_writes_the_atmosphere_icing_and_gust_and_times_the_failures():
    steps = body(text(WORLD_CPP), "void FFlightSimScenarioWorld::ApplyPhysicsStepWrites(")
    apply = body(text(WORLD_CPP), "void FFlightSimScenarioWorld::ApplyStepWrites(")
    assert "ApplyPhysicsStepWrites(Card);" in apply
    # The run clock is JSBSim's own, latched at the first step (the headless
    # providers' definition).
    assert 'ReadProperty(TEXT("simulation/sim-time-sec"))' in apply
    assert "RunClockSeconds = SimSeconds - RunClockZeroSeconds;" in apply
    assert "Properties.Append(Card.AtmosphereProperties);" in steps
    # The gust batch is written UNCONDITIONALLY -- zero when there is no
    # row -- at the function's own indentation, never inside an if.
    for index in range(3):
        line = f"\tProperties.Add(GustProperties[{index}]);"
        assert f"\n{line}\n" in steps, line
    assert "double GustNorthMps = 0.0;" in steps
    # The table's row for the step, rotated by the card's heading.
    assert "PhysicsPythonRound(RunClockSeconds * Card.RateHz)" in steps
    assert "Along * FMath::Cos(Psi) - Right * FMath::Sin(Psi)" in steps
    # The failure schedule: once each, at the first step with t >= at_s.
    assert "FailureDone[Index] || !(RunClockSeconds >= Event.AtSeconds)" in steps
    assert "FailureDone[Index] = true;" in steps
    assert 'TEXT("propulsion/active_engine")' in steps and 'TEXT("-1")' in steps
    # The plugin re-sends its engine struct each tick: the engine-out holds.
    assert "Command.CutOff" in steps and "Command.Magnetos" in steps
    # The icing ramp: eta_max clamp((t - onset) / ramp, 0, 1), 1 + eta k.
    assert "(RunClockSeconds - Card.IcingOnsetSeconds) / Card.IcingRampSeconds" in steps
    assert "1.0 + Eta * Card.IcingK[Axis]" in steps
    assert icing.eta_at(0.5, 0.2, 0.0, 1.0) == pytest.approx(0.1)
    # The wind layer replaces the base before any additive field.
    assert apply.index("LayeredWindAt(Card") < apply.index("if (bLogProfileReady)")


def test_the_icing_and_failure_properties_are_proven_present_before_the_run():
    bind = body(text(WORLD_CPP), "bool FFlightSimScenarioWorld::BindPhysicsBlocks(")
    assert 'TEXT("card.icing_schedule: the loaded airframe declares no %s' in bind
    assert 'TEXT("card.failure_schedule: the loaded airframe cannot take' in bind
    assert "Declared(GustPEquivalentProperty)" in bind
    assert 'GustPEquivalentProperty = TEXT("gust/p-equivalent-rad_sec")' in text(WORLD_CPP)


# -- the wake port -------------------------------------------------------------------------

def gl_table():
    rows = re.findall(r"\{(-?[0-9.e-]+), ([0-9.e-]+)\},",
                      body(text(WAKE_CPP), "const double GWakeGaussLegendre[][2] = "))
    return [(float(x), float(w)) for x, w in rows]


def test_the_gauss_legendre_table_is_numpys_to_the_bit():
    rows = gl_table()
    assert len(rows) == wake.GL_POINTS == 32
    nodes, weights = np.polynomial.legendre.leggauss(wake.GL_POINTS)
    assert [x for x, _ in rows] == [float(v) for v in nodes]
    assert [w for _, w in rows] == [float(v) for v in weights]
    header = text(WAKE_H)
    assert "static constexpr int32 GaussLegendrePoints = 32;" in header
    assert f"static constexpr double SarpkayaDemiseConstant = {wake.SARPKAYA_DEMISE_CONSTANT};" \
        in header
    assert "static constexpr double MetresPerDegree = 111320.0;" in header
    assert wake.METRES_PER_DEGREE == 111320.0
    assert verify.WAKE_SELFTEST_TOL == 1e-9
    assert "static constexpr double SelftestTolerance = 1e-9;" in header
    assert "if (OutWorst > SelftestTolerance)" in text(WAKE_CPP)


def test_the_wake_selftest_runs_at_the_door():
    reader = body(text(WORLD_CPP), "bool ReadPhysicsBlocks(")
    wake_part = reader[reader.index('HasField(TEXT("wake"))'):reader.index('HasField(TEXT("derived_aircraft"))')]
    assert wake_part.index("Port.Selftest(Out.WakeHostSelftest") < wake_part.index("Out.bWake = true;")
    assert "Vectors->Num() != 5" in wake_part and wake.SELFTEST_COUNT == 5


SHIM = r"""
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <string>
#include <vector>
typedef char TCHAR;
typedef int32_t int32;
typedef uint8_t uint8;
typedef uint32_t uint32;
typedef uint64_t uint64;
typedef int64_t int64;
typedef size_t SIZE_T;
#define TEXT(x) x
#define FLIGHTSIMBRIDGE_API
template <typename T, size_t N> char (&UEArrayCountHelper(const T (&)[N]))[N + 1];
#define UE_ARRAY_COUNT(array) (sizeof(UEArrayCountHelper(array)) - 1)
struct FString
{
	std::string S;
	FString() {}
	FString(const char* In) : S(In) {}
	bool operator==(const char* Other) const { return S == Other; }
	FString& operator+=(const FString& Other) { S += Other.S; return *this; }
	static FString Printf(const char* Format, ...)
	{
		char Buffer[4096];
		va_list Args;
		va_start(Args, Format);
		vsnprintf(Buffer, sizeof(Buffer), Format, Args);
		va_end(Args);
		return FString(Buffer);
	}
};
template <typename T> struct TArray
{
	std::vector<T> V;
	void Reset() { V.clear(); }
	int32 Add(const T& Item) { V.push_back(Item); return (int32)V.size() - 1; }
	int32 Num() const { return (int32)V.size(); }
	void SetNumZeroed(int32 Count) { V.assign(Count, T()); }
	T* GetData() { return V.data(); }
	T& operator[](int32 Index) { return V[Index]; }
	const T& operator[](int32 Index) const { return V[Index]; }
};
template <typename T> struct TNumericLimits
{
	static constexpr T Max() { return std::numeric_limits<T>::max(); }
};
struct FMath
{
	template <typename T> static T Abs(T X) { return X < 0 ? -X : X; }
	template <typename T> static T Max(T A, T B) { return (B < A) ? A : B; }
	template <typename T> static T Min(T A, T B) { return (A < B) ? A : B; }
	static bool IsFinite(double X) { return std::isfinite(X); }
};
struct FMemory
{
	static void Memcpy(void* To, const void* From, size_t Count) { std::memcpy(To, From, Count); }
};
"""

DRIVER = r"""
#include "FlightSimWake.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace Patch5
{
@PATCH5@
}
namespace Physics
{
@PHYSICS@
}

static FString Hash(int Which, const char* Path)
{
	std::vector<uint8> Bytes;
	FILE* File = std::fopen(Path, "rb");
	int C;
	while ((C = std::fgetc(File)) != EOF) { Bytes.push_back((uint8)C); }
	std::fclose(File);
	const uint8* Data = Bytes.empty() ? nullptr : Bytes.data();
	return Which == 5 ? Patch5::JSBSimLocalPatch5::Sha256Hex(Data, Bytes.size())
	                  : Physics::PhysicsSha256Hex(Data, Bytes.size());
}

int main(int Argc, char** Argv)
{
	if (Argc > 1 && std::strcmp(Argv[1], "round") == 0)
	{
		double X = 0.0;
		while (std::scanf("%lf", &X) == 1) { std::printf("%d\n", Physics::PhysicsPythonRound(X)); }
		return 0;
	}
	if (Argc > 1 && std::strcmp(Argv[1], "sha") == 0)
	{
		std::printf("%s %s\n", Hash(5, Argv[2]).S.c_str(), Hash(9, Argv[2]).S.c_str());
		return 0;
	}
	FFlightSimWakeCard C;
	int Model = 0, Eps = 0, NStar = 0, Held = 0;
	if (std::scanf("%lf %lf %lf %d %lf %d %lf %d %lf %lf %d %lf %lf %lf %lf %lf %lf %lf",
	               &C.Gamma0, &C.B0Metres, &C.RcMetres, &Model, &C.EpsStar, &Eps, &C.NStar,
	               &NStar, &C.LateralOffsetMetres, &C.VerticalOffsetMetres, &Held,
	               &C.AgeHeldSeconds, &C.SeparationSeconds, &C.Age0Seconds, &C.OwnSpanMetres,
	               &C.HeadingDegrees, &C.W0Mps, &C.GeneratorSpeedMps) != 18) { return 2; }
	C.DecayModel = Model ? FString("sarpkaya") : FString("none");
	C.bEpsStar = Eps != 0;
	C.bNStar = NStar != 0;
	C.bAgeHeld = Held != 0;
	int Count = 0;
	if (std::scanf("%d", &Count) != 1) { return 3; }
	for (int I = 0; I < Count; ++I)
	{
		FFlightSimWakeVector V;
		if (std::scanf("%lf %lf %lf %lf %lf %lf %lf", &V.YMetres, &V.ZMetres, &V.AgeSeconds,
		               &V.UMps, &V.VMps, &V.WMps, &V.PEqRadPerSec) != 7) { return 4; }
		C.Selftest.Add(V);
	}
	FFlightSimWake W;
	W.Init(C);
	TArray<FFlightSimWakeVector> Host;
	double Worst = 0.0;
	FString Why;
	const bool Ok = W.Selftest(Host, Worst, Why);
	std::printf("selftest %d %.17g %d\n", Ok ? 1 : 0, Worst, FFlightSimWake::GaussLegendreCount());
	for (int I = 0; I < Host.Num(); ++I)
	{
		std::printf("%.17g %.17g %.17g %.17g\n", Host[I].UMps, Host[I].VMps, Host[I].WMps,
		            Host[I].PEqRadPerSec);
	}
	int Steps = 0;
	if (std::scanf("%d", &Steps) != 1) { return 5; }
	for (int I = 0; I < Steps; ++I)
	{
		double Lat, Lon, Alt, T;
		if (std::scanf("%lf %lf %lf %lf", &Lat, &Lon, &Alt, &T) != 4) { return 6; }
		FFlightSimWakeSample S;
		W.Evaluate(Lat, Lon, Alt, T, S);
		std::printf("%.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g\n",
		            S.GustNorthMps, S.GustEastMps, S.GustDownMps, S.PEqRadPerSec, S.VMps, S.WMps,
		            S.GammaM2PerSec, S.AgeSeconds, S.LateralMetres, S.VerticalMetres);
	}
	return 0;
}
"""


@pytest.fixture(scope="module")
def port(tmp_path_factory):
    """FlightSimWake.cpp (unchanged) and the two SHA-256 routines (the
    plugin's patch-5 door, the bridge's gust-row digest; cut from their
    files as written), compiled against a stand-in for CoreMinimal.h."""
    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        pytest.skip("no C++ compiler: the port is pinned by source reading only")
    work = tmp_path_factory.mktemp("wakeport")
    (work / "CoreMinimal.h").write_text(SHIM, encoding="utf-8")
    patch5 = body(text(MOVEMENT_CPP), "namespace JSBSimLocalPatch5")
    physics = (body(text(WORLD_CPP), "FString PhysicsSha256Hex(") + "\n"
               + body(text(WORLD_CPP), "int32 PhysicsPythonRound("))
    driver = DRIVER.replace("@PATCH5@", patch5).replace("@PHYSICS@", physics)
    (work / "driver.cpp").write_text(driver, encoding="utf-8")
    binary = work / "wakeport"
    result = subprocess.run(
        [compiler, "-std=c++17", "-O1", "-I", str(work), "-I", str(WAKE_H.parent),
         str(WAKE_CPP), str(work / "driver.cpp"), "-o", str(binary)],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-4000:]
    return binary


def generator_pair(monkeypatch, model="none", eps_star=None, n_star=None, age_s=None,
                   separation_s=20.0, heading_deg=37.0):
    """A prepared pair with stated numbers (no FDM: the generator's data is
    seeded into the provider's cache under a test name)."""
    monkeypatch.setitem(wake._GENERATORS, "P9GEN",
                        wake.GeneratorData("P9GEN", 735000.0, 195.68, "0" * 64))
    pair = wake.WakeVortexPair(wake._GENERATORS["P9GEN"], lateral_offset_m=25.315,
                               vertical_offset_m=15.0, heading_deg=heading_deg,
                               separation_s=None if age_s is not None else separation_s,
                               age_s=age_s, model=model, eps_star=eps_star, n_star=n_star,
                               generator_speed_kt=250.0, own_aircraft="c172p")
    pair.rho_kgm3 = 1.0581
    pair.own_span_m = 10.9728
    pair.own_tas0_mps = 52.3
    pair.speed_mps = 250.0 * 1852.0 / 3600.0
    pair.gamma_0 = wake.initial_circulation(pair.generator.weight_n, pair.rho_kgm3,
                                            pair.speed_mps, pair.b_0_m)
    pair.w_0 = wake.descent_speed(pair.gamma_0, pair.b_0_m)
    pair.prepared = {"gamma_0_m2_s": pair.gamma_0}
    return pair


def port_input(block, vectors, steps):
    g, d = block["geometry"], block["decay"]
    head = [block["gamma_0"], block["b_0"], block["r_c"], int(d["model"] == "sarpkaya"),
            d["eps_star"] or 0.0, int(d["eps_star"] is not None), d["n_star"] or 0.0,
            int(d["n_star"] is not None), g["lateral_offset_m"], g["vertical_offset_m"],
            int(g["age_s"] is not None), g["age_s"] or 0.0, g["separation_s"] or 0.0,
            g["age_0_s"], g["own_span_m"], g["heading_deg"], g["w_0_mps"],
            block["generator"]["speed_mps"]]
    lines = [" ".join(repr(float(v)) if isinstance(v, float) else str(v) for v in head),
             str(len(vectors))]
    lines += [" ".join(repr(float(v[k])) for k in wake.SELFTEST_KEYS) for v in vectors]
    lines += [str(len(steps))] + [" ".join(repr(float(x)) for x in step) for step in steps]
    return "\n".join(lines) + "\n"


def run_port(binary, block, vectors, steps=()):
    result = subprocess.run([str(binary)], input=port_input(block, vectors, steps),
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    ok, worst, count = lines[0].split()[1:]
    host = [[float(x) for x in line.split()] for line in lines[1:1 + len(vectors)]]
    evaluated = [[float(x) for x in line.split()] for line in lines[1 + len(vectors):]]
    return int(ok), float(worst), int(count), host, evaluated


@pytest.mark.parametrize("decay", [dict(model="none"),
                                   dict(model="sarpkaya", eps_star=0.2, n_star=0.1),
                                   dict(model="none", age_s=12.0)])
def test_the_compiled_port_reproduces_the_card_and_the_provider(port, monkeypatch, decay):
    from core.environment.base import OwnShipState, Position

    pair = generator_pair(monkeypatch, **decay)
    block = json.loads(json.dumps(pair.card_block()))      # through JSON, as the card goes
    ok, worst, count, host, evaluated = run_port(
        port, block, block["selftest"],
        steps=[(47.0 + 1e-4 * i, 8.0 + 2e-4 * i, 1500.0 - 0.5 * i, i / 120.0) for i in range(6)])
    assert count == 32
    assert ok == 1 and worst <= 1e-12, worst
    for expected, got in zip(block["selftest"], host):
        for key, value in zip(("u_mps", "v_mps", "w_mps", "p_eq_rad_s"), got):
            assert value == pytest.approx(expected[key], abs=1e-12), key
    # The per-step field at the own ship: the provider's evaluate + gust_at.
    for i, row in enumerate(evaluated):
        own = OwnShipState(position=Position(47.0 + 1e-4 * i, 8.0 + 2e-4 * i, 1500.0 - 0.5 * i,
                                             1000.0, 500.0),
                           v_north_mps=0.0, v_east_mps=0.0, v_down_mps=0.0, roll_deg=0.0,
                           pitch_deg=0.0, heading_deg=37.0, span_m=pair.own_span_m,
                           tas_mps=52.3)
        gust = pair.gust_at(own, i / 120.0)
        last = pair.last
        expected = [gust.north, gust.east, gust.down, last["wake_p_eq_rad_s"],
                    last["wake_v_mps"], last["wake_w_mps"], last["wake_gamma_m2_s"],
                    last["wake_age_s"], last["wake_lateral_m"], last["wake_vertical_m"]]
        assert row == pytest.approx(expected, abs=1e-9, rel=1e-12)


def test_the_compiled_port_refuses_a_vector_beyond_1e9(port, monkeypatch):
    pair = generator_pair(monkeypatch)
    block = json.loads(json.dumps(pair.card_block()))
    vectors = [dict(v) for v in block["selftest"]]
    vectors[2]["v_mps"] += 2e-9
    ok, worst, _, _, _ = run_port(port, block, vectors)
    assert ok == 0 and worst == pytest.approx(2e-9, rel=1e-3)
    vectors[2]["v_mps"] -= 1.5e-9            # 0.5e-9 off: inside the bound
    ok, _, _, _, _ = run_port(port, block, vectors)
    assert ok == 1


def test_both_sha256_routines_are_hashlibs(port, tmp_path):
    payloads = [b"", b"abc", bytes(range(256)) * 5, b"x" * 55, b"y" * 56, b"z" * 64,
                ("\n".join(" ".join(["0.0083333333333333332", "1.5e-05", "-2", "3", "4"])
                           for _ in range(7))).encode("ascii")]
    for index, payload in enumerate(payloads):
        path = tmp_path / f"payload{index}.bin"
        path.write_bytes(payload)
        result = subprocess.run([str(port), "sha", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        door, rows = result.stdout.split()
        assert door == rows == hashlib.sha256(payload).hexdigest(), index


def test_the_row_count_and_row_index_round_as_python_does(port):
    """von_karman.py counts int(round(d * r)) + 1 rows and indexes
    int(round(t * r)): Python rounds half to even, so the host does too."""
    values = [0.0, 0.5, 1.5, 2.5, 3.5, 3.4999999999999996, 7.2, 359.99999999999994,
              360.0, 360.5, 361.5, 1.0 / 120.0 * 120.0, 2.9999999999999996 * 120.0]
    result = subprocess.run([str(port), "round"], input=" ".join(repr(v) for v in values),
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert [int(x) for x in result.stdout.split()] == [int(round(v)) for v in values]


# -- the recorder's channel table ----------------------------------------------------------

def channel_table():
    rows = re.findall(r'\{TEXT\("([^"]+)"\),\s*TEXT\("([^"]+)"\),\s*[^,]+,\s*(true|false)\}',
                      text(RECORDER_CPP))
    return {column: (prop, required == "true") for column, prop, required in rows}


#: The limits monitor's 0/1 flag columns (post-run annotations on both
#: hosts), under INT-final's *_flag names and the exceed_* names before.
LIMIT_FLAG_COLUMNS = ({column for _, column, *_ in limits.CHECKS} | {limits.ANY_COLUMN}
                      | set(limits.FLAG_RENAMES))


def test_the_recorder_carries_every_registry_host_channel():
    table = channel_table()
    missing = [c for c in REGISTRY.host_channels() if c not in table]
    assert not missing, f"UE recorder lacks the registry's host channels {missing}"
    host = body(text(WORLD_CPP), "double FFlightSimScenarioWorld::HostChannel(")
    for column, (prop, required) in table.items():
        if not prop.startswith("host:"):
            continue
        name = prop[len("host:"):]
        assert name == column, column
        if column in LIMIT_FLAG_COLUMNS:
            # Post-run annotations on both hosts: optional, never served.
            assert not required and f'TEXT("{name}")' not in host, column
        else:
            assert f'Name == TEXT("{name}")' in host, f"HostChannel does not serve {name}"
    recorder = text(RECORDER_CPP)
    assert "FFlightSimScenarioWorld::ReadHostChannel(" in recorder
    assert 'RecorderHostPrefix = TEXT("host:")' in recorder


def test_the_recorder_property_rows_are_the_headless_names():
    table = channel_table()
    state = text(REPO / "core/fdm/state.py") + text(REPO / "core/scenario/runner.py")
    engine = {f"engine{i}_{kind}": failures.engine_property(i, leaf)
              for i in range(2) for kind, leaf in (("thrust_n", "thrust-lbs"),
                                                   ("n1_pct", "n1"), ("rpm", "engine-rpm"))}
    for column in REGISTRY.host_channels():
        prop, _ = table[column]
        if prop.startswith("host:"):
            continue
        if column in engine:
            assert prop == engine[column] and not table[column][1], column
        else:
            assert f'"{prop}"' in state, f"{column} reads {prop}, a name the headless state does not"


# -- the plugin's local patches ------------------------------------------------------------

def test_patch_5_hashes_the_xml_at_the_door_before_jsbsim_reads_it():
    load = body(text(MOVEMENT_CPP), "void UJSBSimMovementComponent::LoadAircraft(")
    digest = load.index("JSBSimLocalPatch5::Sha256Hex(XmlBytes.GetData(), XmlBytes.Num())")
    compare = load.index("!LoadedAircraftXmlSha256.Equals(ExpectedAircraftXmlSha256")
    refused = load.index("bAircraftXmlRefused = true;", compare)
    assert digest < compare < refused < load.index("Exec->LoadModel(")
    init = body(text(MOVEMENT_CPP), "void UJSBSimMovementComponent::InitializeJSBSim()")
    assert init.index("Exec->SetAircraftPath(SGPath(TCHAR_TO_UTF8(*AircraftPath)));") < \
        init.index("Exec->SetAircraftPath(SGPath(TCHAR_TO_UTF8(*OverrideRoot)));")
    header = text(MOVEMENT_H)
    for name in ("FString AircraftRootOverride;", "FString ExpectedAircraftXmlSha256;",
                 "FString LoadedAircraftXmlSha256;", "bool bAircraftXmlRefused = false;",
                 "TArray<FString> PreTrimProperties;", "TArray<bool> PreTrimRelatchAfter;",
                 "TArray<FString> PreTrimReadValues;", "TArray<FString> PreTrimMissing;"):
        assert name in header, name
    # The bridge: the card's root and digest handed over before the load,
    # logged with the card's, refused by name on a mismatch.
    populate = body(text(WORLD_CPP), "bool FFlightSimScenarioWorld::Populate(")
    handed = populate.index("Movement->ExpectedAircraftXmlSha256 = Card.DerivedAircraftSha256;")
    load_at = populate.index("Movement->LoadAircraft(true);")
    assert handed < load_at < populate.index('TEXT("card.derived_aircraft: the airframe XML under')
    assert "!DerivedSha256AtDoor.Equals(Card.DerivedAircraftSha256, ESearchCase::IgnoreCase)" \
        in populate


def test_vendored_json_records_patches_5_and_6():
    vendored = json.loads(text(PLUGIN / "VENDORED.json"))
    patches = vendored["local_patches"]
    assert len(patches) == 6
    by_number = {p.get("patch"): p for p in patches if "patch" in p}
    assert set(by_number) == {5, 6}
    assert "AircraftRootOverride" in by_number[5]["change"]
    assert "ExpectedAircraftXmlSha256" in by_number[5]["change"]
    assert "after its RunIC" in by_number[6]["change"] and "before DoTrim" in by_number[6]["change"]
    assert "SetVcalibratedKtsIC" in by_number[6]["change"]
    for patch in by_number.values():
        assert patch["applied"] == "yes" and "Windows build" in patch["verification"]
    # A fresh vendoring re-applies them (the diff is the committed change).
    script = text(REPO / "scripts/vendor_ue_plugin.sh")
    assert "jsbsim_plugin_patches_5_6.diff" in script and '"patch": 5' in script
    diff = text(REPO / "scripts/jsbsim_plugin_patches_5_6.diff")
    assert "LOCAL PATCH 5" in diff and "LOCAL PATCH 6" in diff
    assert diff.isascii()
    # The diff is the committed change, not a stale copy of it: every line
    # it adds is in the plugin source as committed.
    committed = set(text(MOVEMENT_CPP).splitlines()) | set(text(MOVEMENT_H).splitlines())
    added = [line[1:] for line in diff.splitlines()
             if line.startswith("+") and not line.startswith("+++")]
    assert added and not [line for line in added if line not in committed]
    assert "\t\t\t\tIC->SetVcalibratedKtsIC(InitialCalibratedAirSpeedKts);" in added


def test_every_engine_file_this_item_writes_is_ascii():
    for path in (WAKE_CPP, WAKE_H, MOVEMENT_CPP, MOVEMENT_H, PLUGIN / "VENDORED.json"):
        assert text(path).isascii(), path
    world = text(WORLD_CPP)
    for signature in ("bool ReadPhysicsBlocks(", "bool FFlightSimScenarioWorld::BindPhysicsBlocks(",
                      "void FFlightSimScenarioWorld::ApplyPhysicsStepWrites(",
                      "double FFlightSimScenarioWorld::HostChannel(",
                      "void FFlightSimScenarioWorld::AppendEnvironmentReport("):
        assert body(world, signature).isascii(), signature


# -- render.json environment, graded only when present -------------------------------------

def test_the_render_report_carries_every_graded_key():
    report = body(text(WORLD_CPP), "void FFlightSimScenarioWorld::AppendEnvironmentReport(")
    for key in verify.HOST_PHYSICS_KEYS + ("wake_selftest",):
        assert f'TEXT("{key}")' in report, key
    assert 'TEXT("wake_port") : TEXT("table")' in report


def run_dir(tmp_path, card, environment=None, manifest_fdm=None):
    (tmp_path / "card.json").write_text(json.dumps(card), encoding="utf-8")
    if environment is not None:
        frames = tmp_path / "frames"
        frames.mkdir(exist_ok=True)
        (frames / "render.json").write_text(json.dumps({"environment": environment}),
                                            encoding="utf-8")
    return tmp_path


CARD = {
    "rate_hz": 120.0, "duration_s": 3.0,
    "atmosphere_properties": {"atmosphere/delta-T": 54.0},
    "loading_properties": {"expected_cg_in": 41.2, "tolerance_in": 0.1},
    "failure_schedule": {"events": [{"kind": "control_jam", "target": "aileron", "at_s": 1.0,
                                     "property": "failure/aileron/actuator/malfunction/fail_stuck",
                                     "value": 1.0},
                                    {"kind": "engine_out", "target": 0, "at_s": 5.0,
                                     "property": "propulsion/magneto_cmd", "value": 0.0}],
                         "count": 2},
    "gust_table": {"rows": [["0", "0", "0", "0", "0"]] * 361},
    "derived_aircraft": {"xml_sha256": "ab" * 32},
    "layered_wind": {"kind": "milspec"},
    "icing_schedule": {"eta_max": 0.2},
}
GOOD = {
    "atmosphere_delivery": "pre-trim batch and every step",
    "loading_applied": True, "loading_readback_cg_in": 41.25,
    "failure_schedule_applied": [
        {"kind": "control_jam", "target": "aileron", "at_s": 1.0, "t_applied_s": 1.0},
        {"kind": "engine_out", "target": "0", "at_s": 5.0, "t_applied_s": None}],
    "gust_delivery": "table", "gust_rows_applied": 360,
    "derived_aircraft_sha256": "ab" * 32, "layered_wind": "milspec", "icing_applied": True,
}


def test_host_physics_is_not_run_without_the_engine_keys(tmp_path):
    assert verify.verify_host_physics({}, None).status == verify.NOT_RUN
    assert verify.verify_host_physics({}, tmp_path).status == verify.NOT_RUN
    assert verify.verify_host_physics({}, run_dir(tmp_path, CARD)).status == verify.NOT_RUN
    assert verify.verify_host_physics(
        {}, run_dir(tmp_path, CARD, {"turbulence": "none"})).status == verify.NOT_RUN


def test_host_physics_passes_an_agreeing_report_and_names_each_disagreement(tmp_path):
    result = verify.verify_host_physics({}, run_dir(tmp_path, CARD, GOOD))
    assert result.status == verify.PASS, result.detail
    bad = [
        {"loading_readback_cg_in": 41.35},
        {"loading_applied": False},
        {"failure_schedule_applied": [dict(GOOD["failure_schedule_applied"][0],
                                           t_applied_s=1.0 + 1.0 / 120.0),
                                      GOOD["failure_schedule_applied"][1]]},
        {"failure_schedule_applied": GOOD["failure_schedule_applied"][:1]},
        {"gust_delivery": "wake_port"},
        {"gust_rows_applied": 362},
        {"derived_aircraft_sha256": "cd" * 32},
        {"layered_wind": "layered"},
        {"icing_applied": False},
    ]
    for change in bad:
        result = verify.verify_host_physics({}, run_dir(tmp_path, CARD, dict(GOOD, **change)))
        assert result.status == verify.FAIL and result.failure == "check.host_physics", change
    # The manifest's derivation is the second witness to the XML digest.
    manifest = {"fdm": {"derivation": {"derived_sha256": "ef" * 32}}}
    assert verify.verify_host_physics(manifest, run_dir(tmp_path, CARD, GOOD)).status == verify.FAIL
    # A key the card has no block for is a disagreement too.
    lean = {k: v for k, v in CARD.items() if k != "icing_schedule"}
    assert verify.verify_host_physics({}, run_dir(tmp_path, lean, GOOD)).status == verify.FAIL
    assert is_catalogued("check.host_physics")


# -- the card's derived_aircraft block -----------------------------------------------------

def test_the_card_names_the_derived_airframe_the_host_loads(tmp_path):
    from core.nl.compiler import compile_prompt

    spec = compile_prompt("fly the c172p at 1500 m and 100 kt for 3 seconds")
    spec.set("hold_state", False, frm="test")
    assert card_module.derived_aircraft_card_block(spec) is None
    spec.set("icing.eta_max", 0.2, frm="test")
    block = card_module.derived_aircraft_card_block(spec)
    assert tuple(block) == card_module.DERIVED_AIRCRAFT_CARD_KEYS
    assert block["base"] == "c172p" and block["name"].startswith("c172p-")
    assert block["injections"] == list(icing.INJECTIONS) and "tecs" not in block["injections"]
    xml = Path(block["aircraft_root"]) / block["name"] / f"{block['name']}.xml"
    assert hashlib.sha256(xml.read_bytes()).hexdigest() == block["xml_sha256"]
    assert json.dumps(block).isascii()
