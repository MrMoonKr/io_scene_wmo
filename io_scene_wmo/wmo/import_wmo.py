import bpy
import time
import os
import struct

from ..utils.misc import load_game_data
from .wmo_scene import BlenderWMOScene

from ..pywowlib import WoWVersionManager
from ..pywowlib.wmo_file import WMOFile

from ..ui import get_addon_prefs
from .ui.handlers import DepsgraphLock


def import_wmo_to_blender_scene(filepath: str, client_version: int):
    """ Read and import WoW WMO object to Blender scene"""

    start_time = time.time()

    WoWVersionManager().set_client_version(client_version)

    print("\nImporting WMO")

    addon_prefs = get_addon_prefs()
    game_data = load_game_data()

    if not bpy.wow_game_data.files:
        raise Exception("WoW game data is not loaded. Check settings.")
    
    if not addon_prefs.cache_dir_path:
        raise Exception("Cache directory is not set, textures might not work. Check settings.")

    with DepsgraphLock():
        wmo = WMOFile(client_version, filepath=filepath)
        wmo.read()
        wmo_scene = BlenderWMOScene(wmo=wmo, prefs=addon_prefs)

        # extract textures to cache folder
        game_data.extract_textures_as_png(addon_prefs.cache_dir_path, wmo.motx.get_all_strings())

        # load all WMO components
        wmo_scene.load_materials()
        wmo_scene.load_lights()
        wmo_scene.load_properties()
        wmo_scene.load_fogs()
        wmo_scene.load_groups()
        wmo_scene.load_portals()
        wmo_scene.load_portal_relations()
        wmo_scene.load_doodads()

    # update visibility
    bpy.context.scene.wow_visibility = bpy.context.scene.wow_visibility

    print("\nDone importing WMO. \nTotal import time: ",
          time.strftime("%M minutes %S seconds.\a", time.gmtime(time.time() - start_time)))


def import_wmo_to_blender_scene_gamedata(filepath: str, client_version: int):

    game_data = load_game_data()

    if not game_data or not game_data.files:
        raise FileNotFoundError("Game data is not loaded.")

    addon_prefs = get_addon_prefs()
    cache_dir = addon_prefs.cache_dir_path

    game_data.extract_file(cache_dir, filepath)

    if os.name != 'nt':
        filepath = filepath.lower()
        root_path = os.path.join(cache_dir, filepath.replace('\\', '/'))
    else:
        root_path = os.path.join(cache_dir, filepath)

    with open(root_path, 'rb') as f:
        f.seek(24)
        n_groups = struct.unpack('I', f.read(4))[0]

    group_paths = ["{}_{}.wmo".format(filepath[:-4], str(i).zfill(3)) for i in range(n_groups)]

    game_data.extract_files(cache_dir, group_paths)

    import_wmo_to_blender_scene(root_path, client_version)

    # clean up unnecessary files and directories
    os.remove(root_path)
    for group_path in group_paths:
        os.remove(os.path.join(cache_dir, *group_path.split('\\')))
