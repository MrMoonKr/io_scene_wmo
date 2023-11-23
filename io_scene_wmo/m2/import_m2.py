import os
import struct

import bpy
from ..utils.misc import load_game_data
import importlib
from . import m2_scene
from ..pywowlib.m2_file import M2File, M2Versions
from ..ui.preferences import get_project_preferences


def import_m2(version, filepath, is_local_file=False):

    # get global variables
    project_preferences = get_project_preferences()

    try:
        game_data = load_game_data()

    except UserWarning:
        game_data = None

    m2_file = M2File(version, filepath=filepath)
    m2 = m2_file.root
    m2.filepath = filepath  # TODO: HACK
    
    extract_dir = os.path.dirname(filepath) if is_local_file else project_preferences.cache_dir_path

    if not extract_dir:
        raise Exception('Error: cache directory is not specified. Check addon settings.')

    if game_data and game_data.files:

        # extract and read skel
        skel_fdid = m2_file.find_main_skel()

        while skel_fdid:
            skel_path = game_data.extract_file(extract_dir, skel_fdid, 'skel')
            skel_fdid = m2_file.read_skel(skel_path)

        m2_file.process_skels()

        dependencies = m2_file.find_model_dependencies()

        # extract textures
        m2_file.texture_path_map = game_data.extract_textures_as_png(extract_dir, dependencies.textures)

        # extract anims
        anim_filepaths = {}
        for key, identifier in dependencies.anims.items():
            try:
                anim_filepaths[key] = game_data.extract_file(extract_dir, identifier, 'anim')
            except:
                anim_filepaths[key] = game_data.extract_file(os.path.dirname(filepath), identifier, 'anim')

        # extract skins and everything else
        skin_filepaths = game_data.extract_files(extract_dir, dependencies.skins, 'skin')

        if version >= M2Versions.WOD:
            game_data.extract_files(extract_dir, dependencies.bones, 'bone', True)
            game_data.extract_files(extract_dir, dependencies.lod_skins, 'skin', True)

    else:
        raise NotImplementedError('Error: Importing without gamedata loaded is not yet implemented.')

    m2_file.read_additional_files(skin_filepaths, anim_filepaths)
    m2_file.root.assign_bone_names()

    print("\n\n### Importing M2 model ###")

    importlib.reload(m2_scene)
    bl_m2 = m2_scene.BlenderM2Scene(m2_file, project_preferences)

    cache_dir = project_preferences.cache_dir_path
    end_index = filepath.find(cache_dir) + len(cache_dir)
    m2_filepath = filepath[end_index:]
    bpy.context.scene.wow_scene.game_path = m2_filepath

    bl_m2.load_armature()
    bl_m2.load_animations()
    bl_m2.load_colors()
    bl_m2.load_transparency()
    bl_m2.load_materials()
    bl_m2.load_geosets()
    bl_m2.load_texture_transforms()
    bl_m2.load_collision()
    bl_m2.load_attachments()
    bl_m2.load_lights()
    bl_m2.load_events()
    bl_m2.load_cameras()
    bl_m2.load_ribbons()
    bl_m2.load_particles()
    bl_m2.load_globalflags()
    bpy.ops.scene.wow_creature_load_textures(LoadAll=True) 
    return m2_file


def import_m2_gamedata(version, filepath):


    game_data = load_game_data()

    if not game_data or not game_data.files:
        raise FileNotFoundError("Game data is not loaded.")

    addon_prefs = get_project_preferences()
    cache_dir = addon_prefs.cache_dir_path

    game_data.extract_file(cache_dir, filepath)

    if os.name != 'nt':
        filepath = filepath.lower()
        root_path = os.path.join(cache_dir, filepath.replace('\\', '/'))
    else:
        root_path = os.path.join(cache_dir, filepath)

    with open(root_path, 'rb') as f:
        f.seek(68)
        n_skins = struct.unpack('I', f.read(4))[0]

    skin_paths = ["{}{}.skin".format(filepath[:-3], str(i).zfill(2)) for i in range(n_skins)]
    game_data.extract_files(cache_dir, skin_paths)

    import_m2(version, root_path)    

    # clean up unnecessary files and directories
    os.remove(root_path)
    for skin_path in skin_paths:
        os.remove(os.path.join(cache_dir, *skin_path.split('\\')))