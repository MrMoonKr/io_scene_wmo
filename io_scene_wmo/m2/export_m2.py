from ..pywowlib.m2_file import M2File
from . import m2_scene
import importlib

from ..ui import get_addon_prefs

def create_m2(version, filepath, selected_only, fill_textures):
    print("\n\n### Exporting M2 model ###")
    addon_prefs = get_addon_prefs()
    m2 = M2File(version)
    importlib.reload(m2_scene)
    bl_m2 = m2_scene.BlenderM2Scene(m2, addon_prefs)

    print("\nPreparing Pose")
    bl_m2.prepare_pose(selected_only)
    print("\nExporting properties")
    bl_m2.save_properties(filepath, selected_only)
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
    bl_m2.save_animations()
    print("\nExporting geosets")
    bl_m2.save_geosets(selected_only, fill_textures)
    print("\nExporting collisions")
    bl_m2.save_collision(selected_only)
    print("\nRestoring Pose")
    bl_m2.restore_pose()
    return m2

def export_m2(version, filepath, selected_only, fill_textures):
    create_m2(version,filepath,selected_only,fill_textures).write(filepath)