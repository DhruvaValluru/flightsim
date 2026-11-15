"""Build a transient (unsaved) look-dev scene in the open editor level from
a scene's applied baseline (frames/camera0/render.json look_applied + sky.json).

Run inside the editor (Monolith editor_query run_python, mode execute_file):
    C:/Users/kanth/flightsim/runs/lookdev/scripts/build_lookdev.py scene13

Everything spawned is labelled LD_* in a /Temp level; nothing is saved.
Cloud and ocean materials get MaterialInstanceDynamic copies, so the
/Game/FlightSim assets are never modified.
"""
import json
import sys
import unreal

ROOT = "C:/Users/kanth/flightsim/runs/lookdev/ref_runs/"
SCENES = {
    "scene13": {"dir": "scene13_747_ocean", "alt_m": 10000.0, "surface": "ocean",
                "mesh": "/Game/Aircraft/B747", "cam": (-170, 0, 16, -5.4, 0)},
    "scene03": {"dir": "scene03_a320_nyc", "alt_m": 600.0, "surface": "city",
                "mesh": "/Game/Aircraft/A320", "cam": (-90, 0, 12, -12.0, 0)},
}
M = 100.0  # cm per metre

scene = SCENES[sys.argv[1] if len(sys.argv) > 1 else "scene13"]
sky = json.load(open(ROOT + scene["dir"] + "/sky.json"))
base = json.load(open(ROOT + scene["dir"] + "/applied_baseline.json"))
la = base["look_applied"]
atm = la["world_beauty"]["atmosphere"]
hf = atm["height_fog"][0]
layers = la["world_beauty"]["clouds"]["layers"]
look = json.load(open(ROOT + scene["dir"] + "/beauty_look.json"))

eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
for a in eas.get_all_level_actors():
    if a.get_actor_label().startswith("LD_"):
        eas.destroy_actor(a)  # transient look-dev actors only, in the /Temp level


def spawn(cls, label, loc=(0, 0, 0), rot=(0, 0, 0)):
    a = eas.spawn_actor_from_class(cls, unreal.Vector(*loc), unreal.Rotator(rot[2], rot[0], rot[1]))
    a.set_actor_label(label)
    return a


# -- sun (FlightSimSky.cpp Build: rotation (-elev, az+90, 0), lux, atmosphere sun)
sun = sky["sun"]
sun_a = spawn(unreal.DirectionalLight, "LD_Sun")
sun_a.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=-sun["elevation_deg"], yaw=sun["azimuth_deg"] + 90.0), False)
sl = sun_a.light_component
sl.set_mobility(unreal.ComponentMobility.MOVABLE)
sl.set_intensity(sun["illuminance_lux"])
sl.set_editor_property("atmosphere_sun_light", True)
sl.set_editor_property("per_pixel_atmosphere_transmittance", True)
sl.set_editor_property("cast_shadows_on_clouds", True)
sl.set_editor_property("cast_shadows_on_atmosphere", True)
sl.set_editor_property("cast_cloud_shadows", la["world_beauty"]["sun_shafts"]["sun"]["cast_cloud_shadows"])

# -- sky atmosphere (world_beauty.atmosphere)
sa = spawn(unreal.SkyAtmosphere, "LD_SkyAtmosphere").get_component_by_class(unreal.SkyAtmosphereComponent)
sa.set_mie_scattering_scale(atm["mie_scattering_scale_per_km"])
sa.set_mie_absorption_scale(atm["mie_absorption_scale_per_km"])
sa.set_mie_exponential_distribution(atm["mie_scale_height_km"])
sa.set_mie_anisotropy(atm["mie_anisotropy"])
sa.set_multi_scattering_factor(atm["multi_scattering_factor"])
sa.set_aerial_pespective_view_distance_scale(atm["aerial_perspective_view_distance_scale"])
r, g, b = [int(x) / 255.0 for x in atm["ground_albedo_srgb"].split(",")]
sa.set_ground_albedo(unreal.Color(r=int(r * 255), g=int(g * 255), b=int(b * 255), a=255))
sa.set_editor_property("transmittance_min_light_elevation_angle", sun["transmittance_min_elevation_deg"])

# -- height fog
fog_a = spawn(unreal.ExponentialHeightFog, "LD_HeightFog")
fc = fog_a.component
fc.set_fog_density(hf["fog_density_after"])
fc.set_fog_height_falloff(la["fog"]["fog_height_falloff"])
fc.set_fog_max_opacity(la["fog"]["fog_max_opacity"])
fc.set_start_distance(la["fog"]["start_distance_m"] * M)
fc.set_fog_inscattering_color(unreal.LinearColor(0, 0, 0, 1))
fc.set_editor_property("sky_atmosphere_ambient_contribution_color_scale", unreal.LinearColor(1, 1, 1, 1))
fc.set_volumetric_fog(hf["volumetric_fog"])
fc.set_volumetric_fog_distance(hf["volumetric_fog_distance_m"] * M)
fc.set_volumetric_fog_scattering_distribution(hf["volumetric_fog_scattering_distribution"])
fc.set_volumetric_fog_extinction_scale(hf["volumetric_fog_extinction_scale"])
fc.set_directional_inscattering_exponent(hf["directional_inscattering_exponent"])

# -- sky light (real-time capture in the editor so edits show; the render captures once)
skl_a = spawn(unreal.SkyLight, "LD_SkyLight", (0, 0, scene["alt_m"] * M))
skl = skl_a.light_component
skl.set_mobility(unreal.ComponentMobility.MOVABLE)
skl.set_editor_property("real_time_capture", True)
skl.set_intensity(base["beauty_fallback"]["sky_light"]["intensity"])
skl.set_editor_property("min_occlusion", base["beauty_fallback"]["sky_light"]["min_occlusion"])
skl.set_editor_property("cloud_ambient_occlusion", True)
skl.set_editor_property("cloud_ambient_occlusion_strength",
                        la["world_beauty"]["sun_shafts"]["sky_light"]["cloud_ambient_occlusion_strength"])

# -- volumetric cloud layer with a dynamic instance of M_FlightSimCloudLayers
cloud_mids = []
for i, L in enumerate(layers):
    vc_a = spawn(unreal.VolumetricCloud, "LD_Cloud%d" % i)
    vc = vc_a.get_component_by_class(unreal.VolumetricCloudComponent)
    vc.set_layer_bottom_altitude(L["base_m"] / 1000.0)
    # FlightSimClouds.cpp: built to built_top_m, then capped/lowered to base..top
    vc.set_layer_height((L["top_m"] - L["base_m"]) / 1000.0)
    vc.set_editor_property("use_per_sample_atmospheric_light_transmittance", True)
    vc.set_editor_property("sky_light_cloud_bottom_occlusion", L["sky_light_cloud_bottom_occlusion"])
    vc.set_editor_property("shadow_tracing_distance", L["shadow_tracing_distance_km"])
    ar, ag, ab = [int(x) for x in atm["ground_albedo_srgb"].split(",")]
    vc.set_editor_property("ground_albedo", unreal.Color(r=ar, g=ag, b=ab, a=255))
    vc.set_editor_property("tracing_max_distance", la["world_beauty"]["clouds"]["march"]["tracing_max_distance_km"])
    vc.set_view_sample_count_scale(la["world_beauty"]["clouds"]["march"]["view_sample_count_scale"])
    vc.set_shadow_view_sample_count_scale(la["world_beauty"]["clouds"]["march"]["shadow_sample_count_scale"])
    parent = unreal.load_asset(L["material"].split(".")[0])
    mid = unreal.MaterialLibrary.create_dynamic_material_instance(vc_a, parent)
    for key, param in [("cover", "Coverage"), ("coverage_contrast", "CoverageContrast"),
                       ("shape_scale_km", "ShapeScaleKm"), ("detail_scale_km", "DetailScaleKm"),
                       ("detail_erosion", "DetailErosion"), ("bottom_softness", "BottomSoftness"),
                       ("top_rounding", "TopRounding"), ("extinction_per_m", "ExtinctionPerM"),
                       ("extinction_scale", "ExtinctionScale"), ("height_density", "HeightDensity"),
                       ("side_bulge_cells", "SideBulge"),
                       ("shadow_footprint_km_per_sqrt_km", "ShadowFootprintKm")]:
        if key in L:
            mid.set_scalar_parameter_value(param, float(L[key]))
    mid.set_scalar_parameter_value("LayerThicknessKm", (L["top_m"] - L["base_m"]) / 1000.0)
    sx, sy, sz = [float(v) for v in L["seed_offset_km"].split(",")]
    mid.set_vector_parameter_value("SeedOffsetKm", unreal.LinearColor(sx, sy, sz, 0))
    vc.set_material(mid)
    cloud_mids.append(mid)

# -- ocean surface (MID of M_FlightSimOceanBeauty on a large plane at sea level)
sea = spawn(unreal.StaticMeshActor, "LD_Ocean")
smc = sea.static_mesh_component
smc.set_static_mesh(unreal.load_asset("/Engine/BasicShapes/Plane"))
sea.set_actor_scale3d(unreal.Vector(400000, 400000, 1))  # 400 km square
ocean_mid = unreal.MaterialLibrary.create_dynamic_material_instance(
    sea, unreal.load_asset("/Game/FlightSim/M_FlightSimOceanBeauty" if scene["surface"] == "ocean"
                           else "/Game/FlightSim/M_Ground_City"))
smc.set_material(0, ocean_mid)

# -- post process: the beauty look's physical camera, manual exposure and tonemap
ppv = spawn(unreal.PostProcessVolume, "LD_Post")
ppv.set_editor_property("unbound", True)
s = ppv.settings
ex = look["exposure"]
tm = look["tonemap"]
le = look["local_exposure"]
pp = sky["post_process"]
vals = {
    "auto_exposure_method": unreal.AutoExposureMethod.AEM_MANUAL,
    "auto_exposure_apply_physical_camera_exposure": True,
    "camera_iso": ex["iso"], "camera_shutter_speed": 1.0 / ex["shutter_s"],
    "depth_of_field_fstop": ex["aperture_f"], "auto_exposure_bias": ex["AutoExposureBias"],
    "film_slope": tm["FilmSlope"], "film_toe": tm["FilmToe"], "film_shoulder": tm["FilmShoulder"],
    "film_black_clip": tm["FilmBlackClip"], "film_white_clip": tm["FilmWhiteClip"],
    "tone_curve_amount": tm["ToneCurveAmount"], "blue_correction": tm["BlueCorrection"],
    "local_exposure_highlight_contrast_scale": le["LocalExposureHighlightContrastScale"],
    "local_exposure_shadow_contrast_scale": le["LocalExposureShadowContrastScale"],
    "local_exposure_detail_strength": le["LocalExposureDetailStrength"],
    "local_exposure_blurred_luminance_blend": le["LocalExposureBlurredLuminanceBlend"],
    "bloom_intensity": pp["bloom_intensity"], "lens_flare_intensity": pp["lens_flare_intensity"],
    "vignette_intensity": pp["vignette_intensity"], "film_grain_intensity": pp["film_grain_intensity"],
    "motion_blur_amount": pp["motion_blur_amount"],
}
for k, v in vals.items():
    try:
        s.set_editor_property("override_" + k, True)
    except Exception:
        pass
    try:
        s.set_editor_property(k, v)
    except Exception as e:
        print("post skip", k, e)
ppv.set_editor_property("settings", s)

# -- aircraft (static body mesh only) at altitude
body = None
for a in unreal.AssetRegistryHelpers.get_asset_registry().get_assets_by_path(scene["mesh"], recursive=True):
    if str(a.asset_class_path.asset_name) == "StaticMesh" and "body" in str(a.asset_name).lower():
        body = a.get_asset()
        break
if body:
    ac = spawn(unreal.StaticMeshActor, "LD_Aircraft", (0, 0, scene["alt_m"] * M))
    ac.static_mesh_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    ac.static_mesh_component.set_static_mesh(body)

# -- chase camera like the render (170 m behind, 16 m above, looking at the aircraft)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
cx, cy, cz, cp, cyaw = scene["cam"]
ues.set_level_viewport_camera_info(unreal.Vector(cx * M, cy * M, scene["alt_m"] * M + cz * M),
                                   unreal.Rotator(roll=0, pitch=cp, yaw=cyaw))
print("built", sys.argv[1:] or ["scene13"], "aircraft", body.get_path_name() if body else None,
      "clouds", len(cloud_mids))

# -- shot helper state for later sweeps
print("cloud layer", vc.get_editor_property("layer_bottom_altitude"), vc.get_editor_property("layer_height"))
