"""Apply look-dev tweaks to the LD_* actors and queue a screenshot.

    tweak.py <shot_name> <json list of [target, property, value]>

target: sun | atmosphere | fog | skylight | cloud | cloudmat | ocean | post | camera
  component targets use set_editor_property (snake_case UE names);
  cloudmat / ocean set scalar params on the dynamic material instances;
  post sets PostProcessSettings fields (override_ flag set automatically);
  camera: property 'view' value [x_m, y_m, z_m, pitch, yaw].
Prints old -> new for every change (that line goes into LOG.md).
"""
import json
import sys
import unreal

name = sys.argv[1]
changes = json.loads(" ".join(sys.argv[2:])) if len(sys.argv) > 2 else []
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actors = {a.get_actor_label(): a for a in eas.get_all_level_actors() if a.get_actor_label().startswith("LD_")}


def comp(target):
    if target == "sun":
        return actors["LD_Sun"].light_component
    if target == "atmosphere":
        return actors["LD_SkyAtmosphere"].get_component_by_class(unreal.SkyAtmosphereComponent)
    if target == "fog":
        return actors["LD_HeightFog"].component
    if target == "skylight":
        return actors["LD_SkyLight"].light_component
    if target == "cloud":
        return actors["LD_Cloud0"].get_component_by_class(unreal.VolumetricCloudComponent)
    raise KeyError(target)


for target, prop, value in changes:
    if target in ("cloudmat", "ocean"):
        if target == "cloudmat":
            mid = comp("cloud").get_editor_property("material")
        else:
            mid = actors["LD_Ocean"].static_mesh_component.get_material(0)
        old = mid.get_scalar_parameter_value(prop)
        mid.set_scalar_parameter_value(prop, float(value))
        new = mid.get_scalar_parameter_value(prop)
    elif target == "post":
        ppv = actors["LD_Post"]
        s = ppv.settings
        old = s.get_editor_property(prop)
        try:
            s.set_editor_property("override_" + prop, True)
        except Exception:
            pass
        s.set_editor_property(prop, value)
        ppv.set_editor_property("settings", s)
        new = ppv.settings.get_editor_property(prop)
    elif target == "camera":
        x, y, z, pitch, yaw = value
        unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).set_level_viewport_camera_info(
            unreal.Vector(x * 100.0, y * 100.0, z * 100.0), unreal.Rotator(roll=0, pitch=pitch, yaw=yaw))
        old, new = "-", value
    else:
        c = comp(target)
        old = c.get_editor_property(prop)
        if isinstance(value, list):
            value = unreal.LinearColor(*value) if len(value) == 4 else unreal.LinearColor(value[0], value[1], value[2], 1.0)
        c.set_editor_property(prop, value)
        try:
            c.mark_render_state_dirty()
        except Exception:
            pass
        new = c.get_editor_property(prop)
    print("CHANGE %s.%s %s -> %s" % (target, prop, old, new))

if name != "-":
    unreal.AutomationLibrary.take_high_res_screenshot(
        1280, 720, "C:/Users/kanth/flightsim/runs/lookdev/shots/%s.png" % name, delay=3.0)
    print("SHOT", name)
