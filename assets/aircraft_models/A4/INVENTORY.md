# A-4 Skyhawk model — extraction inventory

## Installers
| Installer | Type | Files |
|---|---|---|
| `A4EFGHKP3Dv44_v103.exe` (P3D v4.4, v1.03, 484,776,290 B) | Clickteam Install Creator (PE32, zlib-compressed data blocks `0x143A` file list / `0x7F7F` data) | 439 |
| `A4EFGHKFSX_version102.exe` (FSX, v1.02, 338,733,271 B) | Clickteam Install Creator | 452 |

Extracted with a custom python3 reader (no Wine, installers never executed); all files matched their declared sizes.

## .mdl files (bytes)
| model | P3D v1.03 | FSX v1.02 | role |
|---|---|---|---|
| A4E.mdl | 31,070,885 | 13,990,980 | exterior (A-4E; A-4F nohump) |
| A4F.mdl | 31,395,697 | 14,076,604 | exterior (hump: A-4E withhump / upgraded / A-4F) |
| A4G.mdl | 31,101,305 | 14,025,020 | exterior (A-4G / A-4K) |
| A4SF.mdl | 31,461,637 | 13,992,620 | exterior (Super Fox) |
| A4SFBA.mdl | 31,326,513 | 14,003,876 | exterior (Super Fox Blue Angels) |
| A4Evc.mdl | 39,365,763 | 19,207,091 | interior / VC (not included here) |

All variants reference models in `SimObjects/Airplanes/A-4E/model/` via their `Model.cfg`.

## aircraft.cfg `[fltsim.N]` title= / texture= (identical P3D and FSX)
**A-4E**: 0 A-4E Skyhawk VA-12 Flying Ubangis / VA-12 · 1 A-4E Skyhawk VA-94 Mighty Shrikes / VA-94 · 2 A-4E Skyhawk VMA-121 Green Knights / VMA-121 · 3 A-4E Skyhawk VA-153 Blue Tail Flies / VA-153 · 4 A-4E Skyhawk VA-212 Rampant Raiders / VA-212

**A-4E_upgraded** (model=withhump): 0 A-4E Skyhawk VA-152 Fighting Aces / VA-152 · 1 A-4E Skyhawk VA-144 Roadrunners / VA-144 · 2 A-4E Skyhawk VMA-211 Wake Island Avengers / VMA-211 · 3 A-4F Skyhawk VC-1 Blue Alii / VC-1 · 4 A-4F Skyhawk VA-45 Blackbirds / VA-45

**A-4F** (withhump): 0 A-4F Skyhawk VMA-214 Blacksheep / VMA-214 · 1 A-4F Skyhawk VMA-311 Tomcats / VMA-311 · 2 A-4F Skyhawk VA-164 Ghostriders Lady Jessie / VA-164 · 3 A-4F Skyhawk VMAT-102 Skyhawks / VMAT-102 · 4 A-4F Skyhawk VMA-324 Devildogs / VMA-324 · 5 A-4H Skyhawk Israeli Air Force / Israel · 6 A-4F Skyhawk VA-23 Black Knights / VA-23

**A-4G** (nohump): 0 A-4G Skyhawk Royal Australian Navy 882 / Australia · 1 A-4G Skyhawk Royal Australian Navy 887 / Australia2 · 2 A-4G Skyhawk Royal Australian Navy 888 / Australia3 · 3 A-4K Skyhawk Royal New Zealand Air Force / RNZAF · 4 A-4G Skyhawk Royal Australian Navy 884 / Australia4

**A-4SuperFox**: 0 A-4F Super Fox Skyhawk Top Gun 50 / TopGun50 · 1 A-4F Super Fox Skyhawk Top Gun 52 / TopGun52 · 2 A-4F Super Fox Skyhawk Top Gun Movie "Jester" / jester

**A-4SuperFoxBlueAngels**: 0 A-4F Super Fox Skyhawk Blue Angels / BlueAngels

## Texture folders (P3D; FSX identical minus the PBR folders)
| folder | files | bytes |
|---|---|---|
| A-4E/texture (shared fallback) | 88 | 354,217,632 |
| A-4E/texture.PBRGlossy / PBRNonGlossy / PBRSemiGlossy / PBRSuperGlossy (P3D only) | 2 each | 134,217,984 each |
| 2-sheet liveries (VA-12, VA-94, VMA-121, VA-212, VA-152, VA-164, VA-23, VMA-214, VMA-311, VMA-324, VMAT-102, TopGun50, TopGun52) | 2 | 33,554,688 |
| 3-sheet liveries (VA-153, VA-144, VA-45, VC-1, VMA-211, Israel, Australia 1-4, RNZAF, jester) | 3 | 37,749,120 |
| BlueAngels | 4 | 41,943,552 |

Livery sheets: `A4E_1.dds`, `A4E_2.dds` (16,777,344 B each, 4096² DXT). Shared exterior maps in `texture/`: `A4E_1_bump`/`A4E_2_bump` (22,369,744), `A4E_1_spec`/`A4E_2_spec` (16,777,344), `TA4J_3.dds`, `TA4J_glass.dds`, `TA4J_3_metallic.dds`; PBR folders hold `A4E_1_metallic`/`A4E_2_metallic` (67,108,992 each).
Included livery: **A-4E VA-12 Flying Ubangis** (gull grey over white, USN); its `texture.cfg` falls back to `..\texture` then `..\texture.PBRGlossy`, both included.

## Exterior .mdl structure — P3D `A4SF.mdl` (largest exterior)
```
00000000: 5249 4646 fd10 e001 5056 3434 4d44 4c48  RIFF....PV44MDLH
00000010: 0800 0000 40e2 0100 0000 2041 4d44 4c47  ....@..... AMDLG
00000020: 1000 0000 35b3 fa51 311f 3044 b05f 864a  ....5..Q1.0D._.J
00000030: 5ef8 6ed4 4d44 4c4e 0500 0000 5441 344a  ^.n.MDLN....TA4J
00000040: 0050 4152 4100 0000 0043 5241 5344 0500  .PARA....CRASD..
```
RIFF chunk tree (id, size, offset):
```
RIFF form=PV44 size=31461629 off=0
  MDLH size=8 off=12
  MDLG size=16 off=28
  MDLN size=5 off=52
  PARA size=0 off=65
  CRAS size=1348 off=73
  BBOX size=24 off=1429
  RADI size=4 off=1461
  MDLD size=31460156 off=1473
    TEXT size=3328 off=1481
    MAT3 size=1240 off=4817
    EMT1 size=1240 off=6065
    PBRM size=5520 off=7313
    IND3 size=5064660 off=12841
    VERB size=26262380 off=5077509
      VERT size=8894112 off=5077517
      VERT size=8256 off=13971637
      BMAP size=8 off=13979901
      SKIN size=2068 off=13979917
      VERT size=29568 off=13981993
      BMAP size=8 off=14011569
      SKIN size=7396 off=14011585
      VERT size=3616 off=14018989
      BMAP size=8 off=14022613
      SKIN size=908 off=14022629
      VERT size=15744 off=14023545
      BMAP size=8 off=14039297
      SKIN size=3940 off=14039313
      VERT size=145152 off=14043261
      BMAP size=64 off=14188421
      SKIN size=36292 off=14188493
      VERT size=9473888 off=14224793
      TANS size=7105420 off=23698689
      VERT size=428608 off=30804117
      UVST size=107156 off=31232733
    TRAN size=13824 off=31339897
    VISL size=4373 off=31353729
    MRE2 size=6292 off=31358110
    MRI2 size=164 off=31364410
    AMAP size=1856 off=31364582
    SCEN size=1856 off=31366446
    SGAL size=464 off=31368310
    SGVL size=464 off=31368782
    SGJC size=464 off=31369254
    SGBR size=464 off=31369726
    SGBN size=14848 off=31370198
    LODT size=10000 off=31385054
      LODE size=9992 off=31385062 lod=100
        PART size=36 off=31385074
        PART size=36 off=31385118
        PART size=36 off=31385162
        ... (224 more PART chunks)
    ANIB size=65536 off=31395062
      RIFF size=33430 off=31395070
        XANH size=4 off=31395078
        XANL size=33410 off=31395090
          XANI size=2360 off=31395098 name='Standard'
          XANI size=404 off=31397466 name='Sim'
          XANI size=309 off=31397878 name='Sim'
          ... (55 more XANI chunks)
      (32098 bytes zero padding at off=31428508)
    REFL size=181 off=31460606
    ATTO size=666 off=31460795
    SCRP size=160 off=31461469
chunk counts: PART=227, XANI=58, VERT=8, BMAP=5, SKIN=5, RIFF=2, MDLH=1, MDLG=1, MDLN=1, PARA=1, CRAS=1, BBOX=1, RADI=1, MDLD=1, TEXT=1, MAT3=1, EMT1=1, PBRM=1, IND3=1, VERB=1, TANS=1, UVST=1, TRAN=1, VISL=1, MRE2=1, MRI2=1, AMAP=1, SCEN=1, SGAL=1, SGVL=1, SGJC=1, SGBR=1, SGBN=1, LODT=1, LODE=1, ANIB=1, XANH=1, XANL=1, REFL=1, ATTO=1, SCRP=1
```
FSX `A4SF.mdl` uses `RIFF form=MDLX` with MATE, INDE (16-bit indices), 6 × ~2 MB VERT, MREC/MREI, 189 PART, 42 XANI; no TANS/UVST/PBRM.

## Scene-graph / animation names
No scene-graph node names are stored (parts are indexed; stock animations are referenced by GUID).

- **TEXT (texture list):** A4E_1, A4E_2, A4E_1_BUMP, A4E_2_BUMP, A4E_1_METALLIC, A4E_2_METALLIC, TA4J_3, TA4J_3_METALLIC, TA4J_GLASS, A4ECM, A4JVC6/7/11, TA4JVC1-4/8-10, ESCAPAC1/2, pilot, weapon (AGM12, AGM45, AIM-9B, BDU-33, LAU-10, MK-82/82SE/83), gauge and glass textures.
- **Attach points (ATTO/REFL):** attachpt_landing_9 (fx_landing), attachpt_navgre_5 (fx_navgre), attachpt_navorange_t45_4 (fx_navorange_t45), attachpt_navred_3 (fx_navred), attachpt_fueldump_10 (fx_fueldump).
- **Script (SCRP):** IndiafoxtechoPBRPanelLight.lua.
- **Visibility (VISL):** (L:CustomVisibilityNN), LIGHT LANDING, AoA indexer lights (L:light_AOA_slow/on_speed/fast), FUEL DUMP ACTIVE, (L:ElecticalPowerAvailable), store rails (L:STA1-5_RAIL).
- **Animations (58 XANI):**
  - `Standard` — stock FS animations by GUID (primary control surfaces: aileron, elevator, rudder).
  - Gear: GEAR ANIMATION POSITION:0/1/2 (keyframe), CENTER/LEFT/RIGHT WHEEL ROTATION ANGLE, GEAR CENTER STEER ANGLE.
  - Canopy: EXIT OPEN:0, EXIT OPEN:1.
  - Flaps: TRAILING EDGE FLAPS LEFT PERCENT, TRAILING EDGE FLAPS RIGHT PERCENT.
  - Speed brake: SPOILERS HANDLE POSITION.
  - Tailhook: TAILHOOK POSITION:1, (A:TAILHOOK HANDLE).
  - Trim: ELEVATOR TRIM PCT (×3), AILERON TRIM PCT, RUDDER TRIM PCT (×2).
  - Cockpit controls: YOKE X POSITION, YOKE Y POSITION, RUDDER PEDAL POSITION, GEAR HANDLE POSITION, GENERAL ENG FUEL VALVE:1, (L:Throttle_lever_STOP_0).
  - Instruments: AIRSPEED INDICATED, Turn coordinator ball, LOCAL TIME hour/minute/second, PLANE HEADING DEGREES GYRO, Delta heading rate, (L:AoABug), (L:AOAIndexer), (L:IFFMode2Digit1).
  - Custom: (L:Custom_Animation_7/8/10), (L:SwitchGeneric13-15, 19-22, 31, 35-38, 74-79).
