import bpy

class WMO_OT_add_light(bpy.types.Operator):
    bl_idname = 'scene.wow_add_light'
    bl_label = 'Add light'
    bl_description = 'Add a WoW light object to the scene'

    def execute(self, context):

        light = bpy.data.lights.new(name='LIGHT', type='POINT')
        obj = bpy.data.objects.new('LIGHT', light)

        light.color = (1.0, 0.565, 0.0)
        light.energy = 1.0

        obj.wow_wmo_light.enabled = True
        obj.wow_wmo_light.use_attenuation = True
        obj.wow_wmo_light.color = light.color # set yellow as default
        obj.wow_wmo_light.color_alpha = 1.0
        obj.wow_wmo_light.intensity = light.energy
        # light.falloff_type = 'INVERSE_LINEAR'

        bpy.context.collection.objects.link(obj)
        obj.location = bpy.context.scene.cursor.location



        self.report({'INFO'}, "Successfully сreated WoW light: " + obj.name)
        return {'FINISHED'}