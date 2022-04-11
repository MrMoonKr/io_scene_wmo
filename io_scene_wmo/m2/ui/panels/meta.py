import bpy

class M2_PT_meta_panel(bpy.types.Panel):
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_label = "M2 Meta"

    def draw(self, context):
        layout = self.layout
        col = layout.column()
        col.prop(context.scene.m2_meta, 'min_animation_lookups')

    @classmethod
    def poll(cls, context):
        return context.scene is not None and context.scene.wow_scene.type == 'M2'

class WowM2MetaProperties(bpy.types.PropertyGroup):
    min_animation_lookups:  bpy.props.IntProperty(
        name='Min Animation Lookups',
        description="Minimum amount of animation lookups to write",
        default=0,
        min=0
    )

def register():
    bpy.types.Scene.m2_meta = bpy.props.PointerProperty(type=WowM2MetaProperties)

def unregister():
    del bpy.types.Scene.m2_meta

