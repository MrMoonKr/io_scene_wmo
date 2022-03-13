import bpy

from ...utils.fogs import create_fog_object

class WMO_OT_add_fog(bpy.types.Operator):
    bl_idname = 'scene.wow_add_fog'
    bl_label = 'Add fog'
    bl_description = 'Add a WoW fog object to the scene'

    def execute(self, context):

        fog_obj = create_fog_object()

        # move fogs to collection
        scn = bpy.context.scene
        fog_collection = bpy.data.collections.get("Fogs")
        if not fog_collection:
            fog_collection = bpy.data.collections.new("Fogs")
            scn.collection.children.link(fog_collection)
        fog_collection.objects.link(fog_obj)
        bpy.context.view_layer.objects.active = fog_obj
        # applying object properties
        fog_obj.wow_wmo_fog.enabled = True

        fog_obj.scale = (5.0, 5.0, 5.0) # default size to 5

        fog_obj.wow_wmo_fog.color2 = (0.0, 0.0, 1.0) # set underwater color as blue



        self.report({'INFO'}, "Successfully created WoW fog: " + fog_obj.name)
        return {'FINISHED'}