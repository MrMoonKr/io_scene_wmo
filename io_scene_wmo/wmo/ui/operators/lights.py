import bpy

class WMO_OT_add_light(bpy.types.Operator):
    bl_idname = 'scene.wow_add_light'
    bl_label = 'Add light'
    bl_description = 'Add a WoW light object to the scene'

    def execute(self, context):

        light = bpy.data.lights.new(name='WoW Light', type='POINT')
        obj = bpy.data.objects.new('WoW Light', light)

        light.color = (1.0, 0.565, 0.0)
        light.energy = 1.0

        # slot = bpy.context.scene.wow_wmo_root_elements.lights.add()
        # slot.pointer = obj

        # move lights to collection
        scn = bpy.context.scene
        light_collection = bpy.data.collections.get("Lights")
        if not light_collection:
            light_collection = bpy.data.collections.new("Lights")
            scn.collection.children.link(light_collection)
        light_collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        bpy.data.objects[obj.name].select_set(True)

        obj.wow_wmo_light.enabled = True
        obj.wow_wmo_light.use_attenuation = True
        obj.wow_wmo_light.color = light.color # set yellow as default
        obj.wow_wmo_light.color_alpha = 1.0
        obj.wow_wmo_light.intensity = light.energy
        # light.falloff_type = 'INVERSE_LINEAR'
        
        obj.location = bpy.context.scene.cursor.location



        self.report({'INFO'}, "Successfully created WoW light: " + obj.name)
        return {'FINISHED'}