import bpy
from ....utils.misc import resolve_outside_texture_path, resolve_texture_path

class M2_fill_textures(bpy.types.Operator):
    bl_idname = 'scene.m2_fill_textures'
    bl_label = 'Fill textures'
    bl_description = "Fill Textures fields of WoW materials with paths from applied image"
    bl_options = {'REGISTER'}

    def execute(self, context):

        for ob in bpy.context.selected_objects:
            
            mesh = ob.data
            for material in mesh.materials:
                if material.wow_m2_material.texture_1:
                    texture = material.wow_m2_material.texture_1
                
                    resolved_path = resolve_texture_path(texture.filepath)
                    if resolved_path is None:
                        resolved_path = resolve_outside_texture_path(texture.filepath)

                    texture.wow_m2_texture.path = resolved_path

                if material.wow_m2_material.texture_2:
                    texture2 = material.wow_m2_material.texture_2

                    resolved_path = resolve_texture_path(texture2.filepath)
                    if resolved_path is None:
                        resolved_path = resolve_outside_texture_path(texture2.filepath)

                    texture2.wow_m2_texture.path = resolved_path    

        self.report({'INFO'}, "Done filling texture paths")

        return {'FINISHED'}