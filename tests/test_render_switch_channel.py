"""Every -Switches flag (FLIGHTSIM_RENDER_SWITCHES) reaches the engine's argv,
ahead of the planned flags (UE's FParse::Value takes the first match), and
-beauty-look=off is a no-sidecar run. Rounds 13-18 bisected switches that
never arrived."""

from webapp.runs import with_render_switches

PLANNED = ["UnrealEditor-Cmd.exe", "FlightSim.uproject", "-run=FlightSimBridge.FlightSimRender",
           "-quality=beauty", "-beauty-look=C:/runs/x/beauty_look.json", "-labels"]


def test_each_switch_reaches_the_argv_ahead_of_the_planned_flags():
    out = with_render_switches(PLANNED, "-aircraft-materials=off -look-ssgi=off -subject-meter=off")
    run = out.index("-run=FlightSimBridge.FlightSimRender")
    assert out[run + 1:run + 4] == ["-aircraft-materials=off", "-look-ssgi=off", "-subject-meter=off"]
    assert out[run + 4:] == PLANNED[3:]


def test_beauty_look_off_drops_the_sidecar():
    out = with_render_switches(PLANNED, "-beauty-look=off -deck-shadow=off")
    assert not any(t.startswith("-beauty-look=") for t in out)
    assert "-deck-shadow=off" in out and "-quality=beauty" in out


def test_no_switches_leaves_the_command_unchanged(monkeypatch):
    monkeypatch.delenv("FLIGHTSIM_RENDER_SWITCHES", raising=False)
    assert with_render_switches(PLANNED) == PLANNED
    assert with_render_switches(PLANNED, "  ") == PLANNED


def test_the_scene09_stability_switches_reach_the_argv():
    # 2026-11-13: -lightning-shadows= (FlightSimWeather.cpp), -tiles-cache-mb=
    # and -tiles-sse= (FlightSimGoogleTiles.cpp) ride the same channel.
    out = with_render_switches(PLANNED, "-lightning-shadows=on -tiles-cache-mb=160 -tiles-sse=16")
    run = out.index("-run=FlightSimBridge.FlightSimRender")
    assert out[run + 1:run + 4] == ["-lightning-shadows=on", "-tiles-cache-mb=160", "-tiles-sse=16"]
    assert out[run + 4:] == PLANNED[3:]
