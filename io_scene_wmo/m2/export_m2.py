import os
import time
import importlib
import traceback

import bpy

from ..pywowlib.m2_file import M2File
from ..third_party.tqdm import tqdm
from ..ui.preferences import get_project_preferences
from ..utils.misc import resolve_outside_model_path
from . import m2_scene
from .operations import m2_action_logger as log

def create_m2(version, filepath, selected_only, fill_textures, forward_axis, scale, merge_vertices):
    """
    Creates and prepares an M2 structure from Blender data for export.
    Executes all necessary pipeline steps to build and validate the model.
    """
    # --- Load project settings and initialize M2 container ---
    proj_prefs = get_project_preferences()
    time_import_method = proj_prefs.time_import_method
    m2 = M2File(version)

    # Reload M2 scene builder to ensure latest code
    importlib.reload(m2_scene)
    bl_m2 = m2_scene.BlenderM2Scene(m2, proj_prefs)

    # Resolve internal game path for export
    export_path = resolve_outside_model_path(filepath)
    if export_path:
        bpy.context.scene.wow_scene.game_path = export_path

    print("\n\n##########################")
    print("### Exporting M2 model ###")
    print("##########################")
    print("\n")
    
    # --- Clear logging system ---
    log.clear()

    start_time = time.time()

    # --- Ordered export processing steps ---
    steps = [
        ("prepare_export_axis", lambda: bl_m2.prepare_export_axis(forward_axis, scale)),
        ("prepare_pose", lambda: bl_m2.prepare_pose(selected_only)),
        ("save_properties", lambda: bl_m2.save_properties(filepath, selected_only)),
        ("save_bones", lambda: bl_m2.save_bones(selected_only)),
        ("save_cameras", bl_m2.save_cameras),
        ("save_attachments", bl_m2.save_attachments),
        ("save_events", bl_m2.save_events),
        ("save_lights", bl_m2.save_lights),
        ("save_ribbons", bl_m2.save_ribbons),
        ("save_particles", lambda: bl_m2.save_particles(time_import_method)),
        ("save_animations", lambda: bl_m2.save_animations(time_import_method)),
        ("save_geosets", lambda: bl_m2.save_geosets(selected_only, fill_textures, merge_vertices)),
        ("save_collision", lambda: bl_m2.save_collision(selected_only)),
        ("restore_pose", bl_m2.restore_pose),
    ]

    # --- Execute each export step sequentially ---
    for step_name, func in tqdm(steps, desc="Exporting M2 Steps", ascii=True):
        try:
            log.debug(f"Starting export step: {step_name}")
            func()
            log.debug(f"Completed step: {step_name}")
        except Exception as e:
            tb = traceback.format_exc()
            log.error(f"Export step '{step_name}' failed: {e}\n{tb}")
            continue

    # --- Log final status ---
    log.info(
        f"Successfully exported M2 to '{filepath}' "
        f"(Total export time: {time.strftime('%M minutes %S seconds', time.gmtime(time.time() - start_time))})"
    )
    
    warnings, errors = log.print_export_log()

    # Display viewport notification based on result
    if errors:
        bpy.ops.wbs.viewport_text_display(
            'INVOKE_DEFAULT',
            message="ERROR: M2 Export Failed! Check console!",
            font_size=32, y_offset=120, color=(1, 0, 0, 1)
        )
        return None  
    elif warnings:
        bpy.ops.wbs.viewport_text_display(
            'INVOKE_DEFAULT',
            message="WARNING: M2 Exported with Warnings, check console!",
            font_size=28, y_offset=100, color=(1, 0.15, 0.15, 1)
        )
    else:
        bpy.ops.wbs.viewport_text_display(
            'INVOKE_DEFAULT',
            message="Info: Successfully exported M2!",
            font_size=24, y_offset=67
        )

    # --- Clear logging system ---
    log.clear()

    return m2

def export_m2(version, filepath, selected_only, fill_textures, forward_axis, scale, merge_vertices):
    """
    Exports an M2 file to disk.
    Removes old file, builds M2 data, and writes the final model output.
    """

    # Create and assemble M2 structure
    m2 = create_m2(version, filepath, selected_only, fill_textures, forward_axis, scale, merge_vertices)
    if not m2:
        raise Exception("Export aborted due to critical errors.")

    # Remove existing file to avoid corruption
    if os.path.exists(filepath):
        os.remove(filepath)

    # Write M2 to disk
    m2.write(filepath)
