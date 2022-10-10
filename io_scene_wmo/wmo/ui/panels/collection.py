from ....utils.callbacks import string_property_validator, string_filter_internal_dir
from .common import panel_poll

import bpy


class WMO_PT_collection(bpy.types.Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'collection'
    bl_label = 'World Map Object'

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.enabled = context.collection.wow_wmo.enabled
        layout.prop(context.collection.wow_wmo, "dir_path")

    def draw_header(self, context):
        layout = self.layout
        row = layout.row()
        row.prop(context.collection.wow_wmo, 'enabled', text='')

    @classmethod
    def poll(cls, context):
        return panel_poll(cls, context) and context.collection.name in context.scene.collection.children


class WoWWMOCollectionPropertyGroup(bpy.types.PropertyGroup):

    enabled: bpy.props.BoolProperty(
        name='Enabled'
        , description='Enable this collection as a WMO object.'
        , default=False
    )

    dir_path: bpy.props.StringProperty(
        name='Directory path'
        , description='Full path of the WMO in WoW filesystem.'
        , options={'TEXTEDIT_UPDATE'}
        , update=lambda self, ctx: string_property_validator(self, ctx
                                                             , name='dir_path'
                                                             , str_filter=string_filter_internal_dir
                                                             , lockable=True)
    )


def register():
    bpy.types.Collection.wow_wmo = bpy.props.PointerProperty(type=WoWWMOCollectionPropertyGroup)


def unregister():
    del bpy.types.Collection.wow_wmo
