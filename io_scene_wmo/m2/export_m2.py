from ..pywowlib.m2_file import M2File
from .m2_scene import BlenderM2Scene

from ..ui import get_addon_prefs

def create_m2(version, filepath, selected_only, fill_textures, root_preset_bounds,animation_preset_bounds):
    print("\n\n### Exporting M2 model ###")
    addon_prefs = get_addon_prefs()
    m2 = M2File(version)
    bl_m2 = BlenderM2Scene(m2, addon_prefs)

    print("\nExporting properties")
    bl_m2.save_properties(filepath, selected_only,root_preset_bounds)
    print("\nExporting bones")
    bl_m2.save_bones(selected_only)
    print("\nExporting cameras")
    bl_m2.save_cameras()
    print("\nExporting attachments")
    bl_m2.save_attachments()
    print("\nExporting events")
    bl_m2.save_events()
    print("\nExporting lights")
    bl_m2.save_lights()
    print("\nExporting animations")
    bl_m2.save_animations(animation_preset_bounds)
    print("\nExporting geosets")
    bl_m2.save_geosets(selected_only, fill_textures)
    print("\nExporting collisions")
    bl_m2.save_collision(selected_only)
    return m2

def export_m2(version, filepath, selected_only, fill_textures, root_preset_bounds,animation_preset_bounds):
    create_m2(version,filepath,selected_only,fill_textures,root_preset_bounds,animation_preset_bounds).write(filepath)