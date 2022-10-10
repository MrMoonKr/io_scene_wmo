from ..pywowlib.m2_file import M2File
from . import m2_scene
from .operations import m2_export_warnings
import importlib

from ..ui.preferences import get_project_preferences

def create_m2(version, filepath, selected_only, fill_textures, forward_axis, scale):
    print("\n\n### Exporting M2 model ###")
    proj_prefs = get_project_preferences()
    m2 = M2File(version)
    importlib.reload(m2_scene)
    importlib.reload(m2_export_warnings)
    bl_m2 = m2_scene.BlenderM2Scene(m2, proj_prefs)

    print("\nPreparing Axis Settings")
    bl_m2.prepare_export_axis(forward_axis, scale)
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
    print("\nExporting Ribbons")
    bl_m2.save_ribbons()
    print("\nExporting particles")
    bl_m2.save_particles()
    print("\nExporting animations")
    bl_m2.save_animations()
    print("\nExporting geosets")
    bl_m2.save_geosets(selected_only, fill_textures)
    print("\nExporting collisions")
    bl_m2.save_collision(selected_only)
    print("\nRestoring Pose")
    bl_m2.restore_pose()
    m2_export_warnings.print_warnings()
    return m2

def export_m2(version, filepath, selected_only, fill_textures, forward_axis, scale):
    create_m2(version,filepath,selected_only,fill_textures,forward_axis, scale).write(filepath)