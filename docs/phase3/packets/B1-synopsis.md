# B1 synopsis

run_id: B-1
machine: windows
written: 2026-11-04T18:07:42Z

## B1 step 8: fresh 3.12.10 venv, pip install --require-hashes -r requirements.lock

- log: `runs/p3/A-2/B1-pip-install.log`
- exit: 0 (expected 0) -> PASS

```
Collecting packaging==26.3 (from -r requirements.lock (line 299))
  Using cached packaging-26.3-py3-none-any.whl (129 kB)
Collecting pillow==11.3.0 (from -r requirements.lock (line 303))
  Using cached pillow-11.3.0-cp312-cp312-win_amd64.whl (7.0 MB)
Collecting pluggy==1.7.0 (from -r requirements.lock (line 411))
  Downloading pluggy-1.7.0-py3-none-any.whl (27 kB)
Collecting pydantic==2.14.2 (from -r requirements.lock (line 415))
  Downloading pydantic-2.14.2-py3-none-any.whl (490 kB)
Collecting pydantic-core==2.50.2 (from -r requirements.lock (line 421))
  Downloading pydantic_core-2.50.2-cp312-cp312-win_amd64.whl (2.3 MB)
     ---------------------------------------- 2.3/2.3 MB 837.9 kB/s eta 0:00:00
Collecting pygments==2.21.0 (from -r requirements.lock (line 564))
  Using cached pygments-2.21.0-py3-none-any.whl (1.3 MB)
Collecting pyparsing==3.3.3 (from -r requirements.lock (line 568))
  Downloading pyparsing-3.3.3-py3-none-any.whl (126 kB)
Collecting pyproj==3.6.1 (from -r requirements.lock (line 572))
  Using cached pyproj-3.6.1-cp312-cp312-win_amd64.whl (6.1 MB)
Collecting pytest==8.4.2 (from -r requirements.lock (line 601))
  Using cached pytest-8.4.2-py3-none-any.whl (365 kB)
Collecting pytest-timeout==2.3.1 (from -r requirements.lock (line 607))
  Using cached pytest_timeout-2.3.1-py3-none-any.whl (14 kB)
Collecting pyyaml==6.0.3 (from -r requirements.lock (line 611))
  Using cached pyyaml-6.0.3-cp312-cp312-win_amd64.whl (154 kB)
Collecting rasterio==1.4.3 (from -r requirements.lock (line 686))
  Using cached rasterio-1.4.3-cp312-cp312-win_amd64.whl (25.4 MB)
Collecting sniffio==1.3.1 (from -r requirements.lock (line 709))
  Using cached sniffio-1.3.1-py3-none-any.whl (10 kB)
Collecting starlette==0.52.1 (from -r requirements.lock (line 713))
  Using cached starlette-0.52.1-py3-none-any.whl (74 kB)
Collecting typing-extensions==4.16.0 (from -r requirements.lock (line 717))
  Using cached typing_extensions-4.16.0-py3-none-any.whl (45 kB)
Collecting typing-inspection==0.4.5 (from -r requirements.lock (line 728))
  Downloading typing_inspection-0.4.5-py3-none-any.whl (14 kB)
Collecting uvicorn==0.39.0 (from -r requirements.lock (line 734))
  Using cached uvicorn-0.39.0-py3-none-any.whl (68 kB)
Installing collected packages: typing-extensions, sniffio, pyyaml, pyparsing, pygments, pluggy, pillow, packaging, numpy, jiter, iniconfig, idna, h11, docstring-parser, distro, colorama, click, certifi, attrs, annotated-types, annotated-doc, uvicorn, typing-inspection, pytest, pyproj, pydantic-core, jsbsim, httpcore, cligj, click-plugins, anyio, affine, starlette, rasterio, pytest-timeout, pydantic, httpx, fastapi, anthropic
Successfully installed affine-3.0.1 annotated-doc-0.0.5 annotated-types-0.8.0 anthropic-0.121.0 anyio-4.16.0 attrs-26.1.0 certifi-2026.10.23 click-8.5.0 click-plugins-1.1.1.2 cligj-0.7.2 colorama-0.4.6 distro-1.9.0 docstring-parser-0.18.0 fastapi-0.128.8 h11-0.16.0 httpcore-1.0.9 httpx-0.28.1 idna-3.20 iniconfig-2.3.1 jiter-0.18.0 jsbsim-1.2.4 numpy-2.0.2 packaging-26.3 pillow-11.3.0 pluggy-1.7.0 pydantic-2.14.2 pydantic-core-2.50.2 pygments-2.21.0 pyparsing-3.3.3 pyproj-3.6.1 pytest-8.4.2 pytest-timeout-2.3.1 pyyaml-6.0.3 rasterio-1.4.3 sniffio-1.3.1 starlette-0.52.1 typing-extensions-4.16.0 typing-inspection-0.4.5 uvicorn-0.39.0

[notice] A new release of pip is available: 25.0.1 -> 26.3
[notice] To update, run: C:\Users\kanth\flightsim\runs\p3\A-2\venv-B1\Scripts\python.exe -m pip install --upgrade pip
```

## B1 step 8: the box's pytest in the fresh venv (FLIGHTSIM_GOOGLE_TILES unset)

- log: `runs/p3/A-2/B1-pytest-2.log`
- exit: 0 (expected 0) -> PASS

```
.....................                                                    [100%]
============================== warnings summary ===============================
tests/test_platform.py::test_webapp_refuses_ue_platform_without_the_engine
  C:\Users\kanth\flightsim\runs\p3\A-2\venv-B1\Lib\site-packages\starlette\testclient.py:45: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
            [JSBSim-ML v2.0]

JSBSim startup beginning ...

```

## B1 step 9: deploy_windows.ps1 -NoLaunch good run (clone, venv, lock, verify imports)

- log: `runs/p3/A-2/B1-deploy-2.log`
- exit: 0 (expected 0) -> PASS

```
Updating files:  78% (13389/17165)
Updating files:  79% (13561/17165)
Updating files:  80% (13732/17165)
Updating files:  80% (13878/17165)
Updating files:  81% (13904/17165)
Updating files:  82% (14076/17165)
Updating files:  83% (14247/17165)
Updating files:  84% (14419/17165)
Updating files:  85% (14591/17165)
Updating files:  85% (14682/17165)
Updating files:  86% (14762/17165)
Updating files:  87% (14934/17165)
Updating files:  88% (15106/17165)
Updating files:  89% (15277/17165)
Updating files:  90% (15449/17165)
Updating files:  90% (15525/17165)
Updating files:  91% (15621/17165)
Updating files:  91% (15740/17165)
Updating files:  92% (15792/17165)
Updating files:  92% (15804/17165)
Updating files:  93% (15964/17165)
Updating files:  94% (16136/17165)
Updating files:  94% (16297/17165)
Updating files:  95% (16307/17165)
Updating files:  96% (16479/17165)
Updating files:  97% (16651/17165)
Updating files:  98% (16822/17165)
Updating files:  99% (16994/17165)
Updating files:  99% (17144/17165)
Updating files: 100% (17165/17165)
Updating files: 100% (17165/17165), done.
==> this install is at: e35545c3 Phase 3 run A-2: A7 step 8 rows (import once, render completes on a quiet machine)
==> creating venv
==> installing the hashed lock, requirements.lock (first run downloads ~200 MB of wheels)
==> verifying the physics and server imports

Set up. Start it any time with:
  cd C:/Users/kanth/flightsim/runs/p3/A-2/B1-deploy2
  .\.venv\Scripts\python.exe -m uvicorn webapp.server:app --port 8008
deployed venv imports ok; jsbsim 1.2.4
```

## B1 step 9 after cfa48660: broken clone stage must refuse by name

- log: `runs/p3/A-2/B1-deploy-broken.log`
- exit: 1 (expected 1) -> PASS

```
==> using py -3.12
==> cloning https://github.com/DhruvaValluru/flightsim.git -> C:/Users/kanth/flightsim/runs/p3/A-2/B1-deploy-broken
Cloning into 'C:/Users/kanth/flightsim/runs/p3/A-2/B1-deploy-broken'...
fatal: Remote branch no-such-branch-b1 not found in upstream origin
install.clone_failed: git exited 128 -- the clone of https://github.com/DhruvaValluru/flightsim.git (branch 
'no-such-branch-b1') into C:/Users/kanth/flightsim/runs/p3/A-2/B1-deploy-broken did not complete (network cut, or no 
such branch); remove C:/Users/kanth/flightsim/runs/p3/A-2/B1-deploy-broken and re-run
At C:\Users\kanth\flightsim\scripts\deploy_windows.ps1:64 char:9
+         throw "${stage}: $tool exited $LASTEXITCODE -- $cause"
+         ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : OperationStopped: (install.clone_f...oken and re-run:String) [], RuntimeException
    + FullyQualifiedErrorId : install.clone_failed: git exited 128 -- the clone of https://github.com/DhruvaValluru/fl 
   ightsim.git (branch 'no-such-branch-b1') into C:/Users/kanth/flightsim/runs/p3/A-2/B1-deploy-broken did not comple  
  te (network cut, or no such branch); remove C:/Users/kanth/flightsim/runs/p3/A-2/B1-deploy-broken and re-run
 
```

note: run B-1 on 3e59358d + the Windows builder's cfa48660 (merged 85ac89be); step 10 (CI matrix) is 'CI: pending draft PR' per the Mac (ci.yml runs on master pushes and pull_request only); packet B1-1 closed by the builder

## verdict

PASS
