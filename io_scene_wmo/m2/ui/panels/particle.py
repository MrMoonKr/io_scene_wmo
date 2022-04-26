import bpy


class M2_PT_particle_panel(bpy.types.Panel):
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "particle"
    bl_label = "M2 Particle"

    def draw(self, context):
        layout = self.layout
        col = layout.column()
        col.prop(context.object.particle_systems.active.settings.wow_m2_particle, 'type')

    @classmethod
    def poll(cls, context):
        return (context.scene is not None
                and context.scene.wow_scene.type == 'M2'
                and context.object is not None
                and context.object.particle_systems.active)


class WowM2ParticlePropertyGroup(bpy.types.PropertyGroup):
    enabled:  bpy.props.BoolProperty(
        name='Enabled',
        description='Enabled this object to be a WoW M2 Particle',
        default=False
    )

    type:  bpy.props.IntProperty()


def register():
    bpy.types.Object.wow_m2_particle = bpy.props.PointerProperty(type=WowM2ParticlePropertyGroup)


def unregister():
    del bpy.Object.wow_m2_particle

