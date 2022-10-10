import bpy
import traceback

from ...import_wmo import import_wmo_to_blender_scene_gamedata
from ...utils.wmv import wmv_get_last_wmo
from ....utils.misc import load_game_data


class WMO_OT_import_last_wmo_from_wmv(bpy.types.Operator):
    bl_idname = "scene.wow_import_last_wmo_from_wmv"
    bl_label = "Load last WMO from WMV"
    bl_description = "Load last WMO from WMV"
    bl_options = {'UNDO', 'REGISTER'}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):

        game_data = load_game_data()

        if not game_data or not game_data.files:
            self.report({'ERROR'}, "Failed to import model. Connect to game client first.")
            return {'CANCELLED'}

        wmo_path = wmv_get_last_wmo()

        if not wmo_path:
            self.report({'ERROR'}, """WoW Model Viewer log contains no WMO entries.
            Make sure to use compatible WMV version or open a .wmo there.""")
            return {'CANCELLED'}

        try:
            import_wmo_to_blender_scene_gamedata(wmo_path, bpy.context.scene.wow_scene.version)
        except:
            traceback.print_exc()
            self.report({'ERROR'}, "Failed to import model.")
            return {'CANCELLED'}

        self.report({'INFO'}, "Done importing WMO object to scene.")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)
