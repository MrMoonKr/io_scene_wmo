import bpy

class M2_PT_meta_panel(bpy.types.Panel):
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_label = "M2 Meta"

    def draw(self, context):
        layout = self.layout
        col = layout.column()

        row = col.row(align=True)
        row.label(text='Animations:')

        row = col.row(align=True)
        col.prop(context.scene.m2_meta, 'min_animation_lookups')

        row = col.row(align=True)
        row.label(text='Preset Bounds:')

        row = col.row(align=True)
        row.prop(context.scene.m2_meta, 'preset_bounds_min_x')
        row.prop(context.scene.m2_meta, 'preset_bounds_min_y')
        row.prop(context.scene.m2_meta, 'preset_bounds_min_z')

        row = col.row(align=True)
        row.prop(context.scene.m2_meta, 'preset_bounds_max_x')
        row.prop(context.scene.m2_meta, 'preset_bounds_max_y')
        row.prop(context.scene.m2_meta, 'preset_bounds_max_z')

        row = col.row(align=True)
        row.prop(context.scene.m2_meta, 'preset_bounds_radius')

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

    preset_bounds_min_x: bpy.props.FloatProperty(
        name="Min X",
        description="",
        default=0,
    )

    preset_bounds_min_y: bpy.props.FloatProperty(
        name="Min Y",
        description="",
        default=0,
    )

    preset_bounds_min_z: bpy.props.FloatProperty(
        name="Min Z",
        description="",
        default=0,
    )

    preset_bounds_max_x: bpy.props.FloatProperty(
        name="Max X",
        description="",
        default=0,
    )

    preset_bounds_max_y: bpy.props.FloatProperty(
        name="Max Y",
        description="",
        default=0,
    )

    preset_bounds_max_z: bpy.props.FloatProperty(
        name="Max Z",
        description="",
        default=0,
    )

    preset_bounds_radius: bpy.props.FloatProperty(
        name="Radius",
        description="",
        default=0,
    )



def register():
    bpy.types.Scene.m2_meta = bpy.props.PointerProperty(type=WowM2MetaProperties)

def unregister():
    del bpy.types.Scene.m2_meta

