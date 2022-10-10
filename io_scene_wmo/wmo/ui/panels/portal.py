from ..enums import *
from ..custom_objects import WoWWMOPortal
from ....ui.panels import WBS_PT_object_properties_common
from ....ui.enums import WoWSceneTypes

import bpy


class WMO_PT_portal(WBS_PT_object_properties_common, bpy.types.Panel):
    bl_label = "WMO Portal"
    bl_context = "object"

    __wbs_custom_object_type__ = WoWWMOPortal
    __wbs_scene_type__ = WoWSceneTypes.WMO

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True

        column = layout.column()
        column.prop(context.object.wow_wmo_portal, "first")
        column.prop(context.object.wow_wmo_portal, "second")

        col = layout.column()

        col.separator()
        col.prop(context.object.wow_wmo_portal, "detail", expand=True)

        col.separator()
        col.prop(context.object.wow_wmo_portal, "algorithm", expand=True)


def portal_validator(self, context):
    if self.second and not self.second.wow_wmo_group.enabled:
        self.second = None

    if self.first and not self.first.wow_wmo_group.enabled:
        self.first = None


class WowPortalPlanePropertyGroup(bpy.types.PropertyGroup):

    first:  bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="First group",
        poll=lambda self, obj: obj.wow_wmo_group.enabled and self.second != obj and obj.name in bpy.context.scene.objects,
        update=portal_validator
    )

    second:  bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="Second group",
        poll=lambda self, obj: obj.wow_wmo_group.enabled and self.first != obj and obj.name in bpy.context.scene.objects,
        update=portal_validator
    )

    detail: bpy.props.EnumProperty(
        items=portal_detail_enum,
        name="Detail",
        description="Disable this group will only work as a target for the portal. "
                    "See Stormwind cathedral for reference.",
        default="0"
    )

    portal_id:  bpy.props.IntProperty(
        name="Portal's ID",
        description="Portal ID"
    )

    algorithm:  bpy.props.EnumProperty(
        items=portal_dir_alg_enum,
        name="Algorithm",
        default="0"
    )


def register():
    bpy.types.Object.wow_wmo_portal = bpy.props.PointerProperty(type=WowPortalPlanePropertyGroup)


def unregister():
    del bpy.types.Object.wow_wmo_portal

