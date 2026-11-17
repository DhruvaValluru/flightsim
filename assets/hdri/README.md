# Look HDRIs (round 148, `-look-hdri=auto|light|off`)

Four Poly Haven "pure sky" HDRIs, CC0 1.0 (public domain dedication: no
attribution required, any use allowed; https://polyhaven.com/license), downloaded
on 2026-11-16 at 2K from dl.polyhaven.org and committed byte for byte. They light
and back the beauty render's sky (core/scene/hdri_sky.py,
ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimHdriSky.cpp).
Never used by a measure render or a label pass.

| name | slot | title | licence | source | file | sha256 |
| --- | --- | --- | --- | --- | --- | --- |
| `qwantani_noon_puresky` | clear | Qwantani Noon (Pure Sky), Greg Zaal (photography), Jarod Guest (processing) | CC0-1.0 | https://polyhaven.com/a/qwantani_noon_puresky | https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/2k/qwantani_noon_puresky_2k.hdr (4,184,949 bytes, 2048 x 1024 RGBE) | `d070d48c8e802c92027b0f7b1965b5bd820b0d25afca225503abfec67e00ad07` |
| `syferfontein_6d_clear_puresky` | golden | Syferfontein 6d Clear (Pure Sky), Greg Zaal (original), Jarod Guest (sky edits) | CC0-1.0 | https://polyhaven.com/a/syferfontein_6d_clear_puresky | https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/2k/syferfontein_6d_clear_puresky_2k.hdr (4,650,421 bytes, 2048 x 1024 RGBE) | `3efca43f875db8d790001dad1677bd13c0968effc6d3193bdd2ee12e226e7eaa` |
| `kloofendal_overcast_puresky` | overcast | Kloofendal Overcast (Pure Sky), Greg Zaal (all) | CC0-1.0 | https://polyhaven.com/a/kloofendal_overcast_puresky | https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/2k/kloofendal_overcast_puresky_2k.hdr (4,335,717 bytes, 2048 x 1024 RGBE) | `312b1b04b7f10057a4f1418abc59d1166c8933cc93fc72051502edaf8d6b2fcd` |
| `overcast_soil_puresky` | storm | Overcast Soil (Pure Sky), Sergej Majboroda (original), Jarod Guest (sky edits) | CC0-1.0 | https://polyhaven.com/a/overcast_soil_puresky | https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/2k/overcast_soil_puresky_2k.hdr (4,568,000 bytes, 2048 x 1024 RGBE) | `5414e1ac0c35e451d28595b2a2cba05e2ca301fdeb755b0a469408443093dafc` |

`prepared/` holds what the sky light uses: each photograph with its sun disk
clamped at 32x the upper hemisphere's median luminance, the upper hemisphere's
mean luminance normalised to 1, box-halved to 1024 x 512 (RLE RGBE), and a JSON
sidecar (sha256 of source and copy, the sun's image longitude and elevation, the
clamp, the normalisation). Regenerate with

    python -m core.scene.hdri_sky prepare

The editor imports both sets as TextureCubes under /Game/FlightSim/Sky
(scripts/ue_create_materials.py `create_look_hdris`: T_HdriLight_<name> from
`prepared/`, T_HdriBackdrop_<name> from the 2K original).
