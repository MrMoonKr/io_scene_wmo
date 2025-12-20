import os
import struct
import time
import importlib
import traceback

import bpy

from ..pywowlib.m2_file import M2File, M2Versions
from ..third_party.tqdm import tqdm
from ..ui.preferences import get_project_preferences
from ..utils.misc import load_game_data
from . import m2_scene
from .operations import m2_action_logger as log
from . import util as util

def import_m2(version, filepath, is_local_file, time_import_method):
    """
    Imports a World of Warcraft M2 model into Blender.

    Loads game data, extracts required M2 dependencies, processes imported assets,
    and builds the Blender object hierarchy.
    """
    start_time = time.time()

    print("\n\n##########################")
    print("### Importing M2 model ###")
    print("##########################")
    print("\n")
    
    # --- Clear logging system ---
    log.clear()

    # --- Get project and game data ---
    project_preferences = get_project_preferences()

    try:
        game_data = load_game_data()
    except UserWarning:
        game_data = None

    m2_file = M2File(version, filepath=filepath)
    m2 = m2_file.root
    m2.filepath = filepath  # Temporary assignment workaround
    
    extract_dir = os.path.dirname(filepath) if is_local_file else project_preferences.cache_dir_path

    if not extract_dir:
        raise Exception('Error: cache directory is not specified. Check addon settings.')

    # --- Extract M2 asset files ---
    if game_data and game_data.files:
        log.info("Extracting M2 required files into cache folder")
        dependencies = m2_file.find_model_dependencies()

        # Extract textures
        m2_file.texture_path_map = game_data.extract_textures_as_png(project_preferences.cache_dir_path, dependencies.textures)

        # Extract animations
        anim_filepaths = {}
        for key, identifier in dependencies.anims.items():
            if is_local_file:
                full_path = os.path.join(extract_dir, os.path.split(identifier)[-1])
                if os.path.exists(full_path):
                    anim_filepaths[key] = full_path
                else:
                    anim_filepaths[key] = os.path.split(identifier)[-1]
                    print("\n.anim not found at:", full_path, '\n')
            else:
                try:
                    anim_filepaths[key] = game_data.extract_file(extract_dir, identifier, 'anim')
                except:
                    anim_filepaths[key] = os.path.split(identifier)[-1]
                    print("\nFailed to extract anim from game data:", identifier)

        # Extract skin and supporting files
        skin_filepaths = dependencies.skins if is_local_file else game_data.extract_files(extract_dir, dependencies.skins, 'skin')

        if version >= M2Versions.WOD:
            game_data.extract_files(extract_dir, dependencies.bones, 'bone', True)
            game_data.extract_files(extract_dir, dependencies.lod_skins, 'skin', True)
    else:
        raise NotImplementedError('Error: Importing without gamedata loaded is not yet implemented.')

    # --- Cleanup and load additional M2 data ---
    skin_filepaths = [p for p in skin_filepaths if p]
    if isinstance(anim_filepaths, dict):
        anim_filepaths = {k: v for k, v in anim_filepaths.items() if v is not None}

    try:
        m2_file.read_additional_files(skin_filepaths, anim_filepaths)
    except KeyError as e:
        log.warn(f"Missing animation {e.args[0]} - skipping.")

    m2_file.root.assign_bone_names()

    if not is_local_file:
        for key, identifier in dependencies.anims.items():
            path_to_remove = os.path.join(extract_dir, identifier)
            if os.path.exists(path_to_remove):
                os.remove(path_to_remove)

    # --- Reload M2 scene handler and prepare Blender scene ---
    importlib.reload(m2_scene)
    bl_m2 = m2_scene.BlenderM2Scene(m2_file, project_preferences)

    cache_dir = project_preferences.cache_dir_path
    end_index = filepath.find(cache_dir) + len(cache_dir)
    m2_filepath = filepath[end_index:]
    
    if not is_local_file:
        bpy.context.scene.wow_scene.game_path = m2_filepath
    else:
        normalized_path = os.path.normpath(filepath)
        path_parts = [part.lower() for part in normalized_path.split(os.sep)]
        wow_root_folders = ["character", "creature", "environments", "item", "spells", "world"]
        base_path_index = next((path_parts.index(cat) for cat in wow_root_folders if cat in path_parts), 0)
        bpy.context.scene.wow_scene.game_path = os.sep.join(path_parts[base_path_index:])
        log.debug(f"Normalized path '{normalized_path}'")

    # --- Create Blender collection for M2 object ---
    m2_name = os.path.splitext(os.path.basename(filepath))[0]
    main_collection, collections = util.get_or_create_m2_collection(m2_name)

    # --- Import pipeline steps ---
    steps = [
        ("load_armature", bl_m2.load_armature, None, collections["armature"], []),
        ("load_animations", bl_m2.load_animations, None, None, []),
        ("load_colors", bl_m2.load_colors, None, collections["color_transparency"], [time_import_method]),
        ("load_transparency", bl_m2.load_transparency, None, collections["color_transparency"], [time_import_method]),
        ("load_materials", bl_m2.load_materials, "dbc_textures", None, []),
        ("load_geosets", bl_m2.load_geosets, None, collections["geosets"], []),
        ("load_texture_transforms", bl_m2.load_texture_transforms, None, collections["texture_transforms"], []),
        ("load_collision", bl_m2.load_collision, None, collections["collision"], []),
        ("load_attachments", bl_m2.load_attachments, None, collections["attachments"], []),
        ("load_lights", bl_m2.load_lights, None, collections["lights"], []),
        ("load_events", bl_m2.load_events, None, collections["events"], []),
        ("load_cameras", bl_m2.load_cameras, None, collections["cameras"], [time_import_method]),
        ("load_ribbons", bl_m2.load_ribbons, None, collections["ribbons"], []),
        ("load_particles", bl_m2.load_particles, None, collections["particles"], [time_import_method]),
        ("load_globalflags", bl_m2.load_globalflags, None, main_collection, []),
    ]

    # --- Execute import steps ---
    results = {}
    for step_name, func, result_key, target_collection, extra_args in tqdm(steps, total=len(steps), desc="Importing M2 Steps", ascii=True):
        try:
            log.debug(f"Starting import step: {step_name}")
            args = []
            if target_collection:
                args.append(target_collection)
            if extra_args:
                args.extend(extra_args)
            result = func(*args)
            log.debug(f"Completed import step: {step_name}")
            if result_key:
                results[result_key] = result
        except Exception as e:
            tb = traceback.format_exc()
            log.error(f"Import step '{step_name}' failed: {e}\n{tb}")
            continue

    # --- Handle results ---
    dbc_textures = results.get("dbc_textures")
    if dbc_textures:
        bpy.ops.scene.wow_creature_load_textures(LoadAll=True)

    # --- Display viewport notification based on result and log final status ---
    if log.log_has_errors():
        bpy.ops.wbs.viewport_text_display('INVOKE_DEFAULT', message="ERROR: M2 Import Failed! Check console!", font_size=32, y_offset=120, color=(1, 0, 0, 1))
        log.error("M2 import failed due to errors. See log summary for details.")
        m2_file = None
    elif log.log_has_warnings():
        bpy.ops.wbs.viewport_text_display('INVOKE_DEFAULT', message="WARNING: M2 Imported with Warnings, check console!", font_size=28, y_offset=100, color=(1, 0.15, 0.15, 1))
        log.warn(f"Successfully imported M2 with warnings, see log summary for details. (Total import time: {time.strftime('%M minutes %S seconds.', time.gmtime(time.time() - start_time))})")
    else:
        bpy.ops.wbs.viewport_text_display('INVOKE_DEFAULT', message="Info: Successfully imported M2!", font_size=24, y_offset=67)
        log.info(f"Successfully imported M2. (Total import time: {time.strftime('%M minutes %S seconds.', time.gmtime(time.time() - start_time))})")

    # --- Print import log ---
    log.print_import_log()


    log.clear()
    return m2_file

def import_m2_gamedata(version, filepath, is_local_file):
    """
    Imports an M2 directly from game data storage.

    Extracts the M2 and skin files into the cache, runs the M2 import routine,
    and cleans up extracted files after processing.
    """
    game_data = load_game_data()

    if not game_data or not game_data.files:
        raise FileNotFoundError("Game data is not loaded.")

    addon_prefs = get_project_preferences()
    cache_dir = addon_prefs.cache_dir_path
    time_import_method = addon_prefs.time_import_method

    # --- Configure scene timing based on import mode ---
    if time_import_method == 'Convert':
        bpy.context.scene.render.fps = 30
        bpy.context.scene.sync_mode = 'NONE'
    else:
        bpy.context.scene.render.fps = 1000
        bpy.context.scene.sync_mode = 'FRAME_DROP'

    # --- Extract and prepare core M2 file ---
    game_data.extract_file(cache_dir, filepath)

    if os.name != 'nt':
        filepath = filepath.lower()
        root_path = os.path.join(cache_dir, filepath.replace('\\', '/'))
    else:
        root_path = os.path.join(cache_dir, filepath)

    # --- Determine number of skins ---
    with open(root_path, 'rb') as f:
        f.seek(68)
        n_skins = struct.unpack('I', f.read(4))[0]

    skin_paths = [f"{filepath[:-3]}{str(i).zfill(2)}.skin" for i in range(n_skins)]
    game_data.extract_files(cache_dir, skin_paths)

    # --- Import complete M2 ---
    import_m2(version, root_path, is_local_file, time_import_method)    

    # --- Cleanup extracted files ---
    os.remove(root_path)
    for skin_path in skin_paths:
        os.remove(os.path.join(cache_dir, *skin_path.split('\\')))
