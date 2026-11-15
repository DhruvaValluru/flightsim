@echo off
rem Windows gate for swarm lane aircraft_exterior.decals_wear.alpine.
rem UNMEASURED: written on the Mac, never run. Run from the repo root:
rem   swarm\lanes\aircraft_exterior\decals_wear\alpine\run_gate.cmd <spec.yaml> [tier0^|tier1^|tier2^|tier3]
rem Exit: 0 pass, 1 wear failed a threshold, 2 inputs missing,
rem       3 not measured (engine did not report the wear value),
rem       4 blocked (the switch is not in this checkout), 5 a capture failed.
setlocal
if "%~1"=="" (
  echo run_gate.usage: run_gate.cmd ^<spec.yaml^> [tier0^|tier1^|tier2^|tier3]
  exit /b 2
)
set "SPEC=%~1"
set "TIER=%~2"
if "%TIER%"=="" set "TIER=tier0"
set "LANE=swarm\lanes\aircraft_exterior\decals_wear\alpine"

findstr /c:"FLIGHTSIM_AIRCRAFT_WEAR" core\render\flags.py >nul 2>&1
if errorlevel 1 (
  echo run_gate.blocked: core\render\flags.py does not read FLIGHTSIM_AIRCRAFT_WEAR.
  echo INTEGRATION.md items 1-4 are not integrated. Nothing was rendered. This is not a wear result.
  exit /b 4
)

rem The quotes keep trailing spaces out of the value.
set "FLIGHTSIM_AIRCRAFT_WEAR=off"
python -m flightsim.capture "%SPEC%" --out runs\alpine_wear_ref --render --passes albedo
if errorlevel 1 exit /b 5
set "FLIGHTSIM_AIRCRAFT_WEAR=%TIER%"
python -m flightsim.capture "%SPEC%" --out runs\alpine_wear_%TIER% --render --passes albedo
if errorlevel 1 exit /b 5
python %LANE%\pixel_gate.py --reference runs\alpine_wear_ref --candidate runs\alpine_wear_%TIER% --expect %TIER%
exit /b %errorlevel%
