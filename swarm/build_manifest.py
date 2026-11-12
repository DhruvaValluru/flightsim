"""Generate swarm/manifest.json: the hyper-realism work items (one agent each).

item = domain x component x scenario. Each item names its lane directory (the
only place its agent may write), its measurable gate, and the third-party
source class it should look for. Run: python swarm/build_manifest.py
"""
import itertools
import json
from pathlib import Path

SCENARIOS = {
    "alpine": "Matterhorn / Alps approach, snow, thin air, rotor turbulence",
    "coastal": "coastal VFR, sea haze, water, shoreline, low sun",
    "urban": "low pass over a city, buildings, traffic lights, night glow",
    "storm": "thunderstorm cell, heavy rain, lightning, low visibility",
    "night_ifr": "night instrument approach, runway lighting, stars, moon",
    "desert": "hot desert, heat shimmer, dust, high density altitude",
    "arctic": "polar ice and snow, low sun angle, blowing snow, whiteout",
}

# domain -> (components, scenario keys it applies to, gate)
DOMAINS = {
    "terrain": (["dem_posting", "horizon_lod", "detail_normals", "land_cover_splat", "roads", "rivers_lakes", "coastline", "rock_scree"],
                list(SCENARIOS), "pixel-measured ground sample distance and horizon range on the Windows render"),
    "vegetation_autogen": (["trees", "grass_shrubs", "buildings_osm", "power_lines", "vehicles", "crops"],
                           ["alpine", "coastal", "urban", "desert"], "instance density and frame time inside the hardware budget"),
    "aircraft_exterior": (["pbr_materials", "glass", "decals_wear", "control_surface_motion", "gear_flaps", "propeller_blur", "exhaust_heat", "nav_lights"],
                          list(SCENARIOS), "no dark-aircraft regression (docs/visual round review); albedo within calibrated range"),
    "atmosphere_clouds": (["volumetric_cloud_types", "cloud_shadows", "aerial_perspective", "sun_moon_ephemeris", "stars_milky_way", "haze_dust", "god_rays"],
                          list(SCENARIOS), "radiometric check against SkyAtmosphere reference values"),
    "weather_fx": (["rain_drops", "windscreen_water", "lightning", "snow", "turbulence_visual", "fog", "thunder_audio"],
                   ["storm", "alpine", "coastal", "night_ifr"], "WX.1-WX.6 clauses in docs/WEATHER.md"),
    "water": (["wave_spectrum", "reflections", "shoreline_foam", "wake_spray", "lake_flatness"],
              ["coastal", "alpine", "storm"], "wave statistics vs stated sea state"),
    "airports_lighting": (["runway_markings", "approach_lights", "taxiway_signs", "terminal_autogen", "papi_vasi", "night_halos"],
                          ["night_ifr", "urban", "coastal", "storm"], "runway geometry vs source data to stated metres"),
    "lighting_exposure": (["physical_light_units", "eye_adaptation", "gi_quality", "shadow_quality", "sun_time_of_day"],
                          list(SCENARIOS), "exposure within +/-0.3 EV of the calibrated look"),
    "camera_lens": (["lens_distortion", "depth_of_field", "motion_blur", "bloom_flare", "rolling_shutter", "sensor_noise"],
                    list(SCENARIOS), "lens model parameters stated and read back from pixels"),
    "flight_dynamics": (["ground_effect", "stall_post_stall", "engine_model", "propeller_model", "gear_dynamics", "wind_shear", "icing_effects"],
                        ["alpine", "storm", "desert", "coastal"], "JSBSim readback + with/without null test (core/record_null.py)"),
    "audio": (["engine_sound", "wind_noise", "cockpit_ambience", "doppler"],
              ["alpine", "storm", "urban", "desert"], "spectral check against reference recordings with named licence"),
    "hardware_perf": (["stress_ladder", "vram_budgeting", "streaming_pool", "cpu_job_scheduling", "thermal_throttle_guard", "dlss_fsr_upscaler", "capture_resolution_ladder", "gpu_driver_matrix"],
                      ["alpine", "urban", "storm"], "measured frame time, VRAM and thermals; sets hardware_budget measured=true"),
    "validation": (["pixel_metrics", "regression_baselines", "licence_audit", "provenance_manifest", "visual_review_rubric", "windows_runbook"],
                   list(SCENARIOS), "every lane's gate runnable from one command on Windows"),
}

SOURCES = ("Google 3D tiles (CLAUDE.md rule: ground of every terrain render)", "CC0 / CC-BY assets (no NC, sha256 + licence in manifest)",
           "Open data (OSM, GLO-30, Sentinel-2, EGM2008)", "peer-reviewed formulae with citation")


def build():
    items = []
    for domain, (components, scen, gate) in DOMAINS.items():
        for comp, s in itertools.product(components, scen):
            iid = f"{domain}.{comp}.{s}"
            items.append({
                "id": iid, "domain": domain, "component": comp, "scenario": s,
                "scenario_note": SCENARIOS[s], "gate": gate,
                "lane_dir": f"swarm/lanes/{domain}/{comp}/{s}",
                "source_classes": list(SOURCES),
            })
    return items


if __name__ == "__main__":
    items = build()
    out = Path(__file__).with_name("manifest.json")
    out.write_text(json.dumps(items, indent=1) + "\n")
    print(f"{len(items)} work items -> {out}")
