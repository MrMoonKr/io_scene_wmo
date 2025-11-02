import bpy
from ..enums import GLOBAL_FLAGS


# ---------------------------
# Property Group
# ---------------------------

class WowM2globalflagsPropertyGroup(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(
        name="Enabled",
        description="Enable M2 global flags for this collection",
        default=False,
    )

    flagsLK: bpy.props.EnumProperty(
        name="WotLK Flags",
        description="M2 global flags used in WotLK",
        items=GLOBAL_FLAGS[:5],
        options={"ENUM_FLAG"},
    )

    flagsLegion: bpy.props.EnumProperty(
        name="Legion Flags",
        description="M2 global flags used in Legion/Retail",
        items=GLOBAL_FLAGS[5:],
        options={"ENUM_FLAG"},
    )

# ---------------------------
# User Interface
# ---------------------------

class M2_PT_global_flags_panel(bpy.types.Panel):
    bl_label = "M2 Global Flags"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "collection"

    @classmethod
    def poll(cls, context):
        col = getattr(context, "collection", None)
        if not col:
            return False

        # Only show on collections marked as M2 roots
        return col.get("wow_m2_collection", False)

    def draw_header(self, context):
        self.layout.prop(context.collection.wow_m2_globalflags, "enabled", text="")

    def draw(self, context):
        col = context.collection
        flags = col.wow_m2_globalflags
        scene = context.scene

        layout = self.layout
        layout.enabled = flags.enabled

        box = layout.box()
        box.label(text="Global Flags", icon="WORLD_DATA")

        # Determine version (2 = WotLK, 6 = Legion/Retail)
        if hasattr(scene, "wow_scene"):
            version = scene.wow_scene.version
        else:
            version = "2"

        # --- WotLK flags ---
        box.label(text="WotLK Flags")
        wl_box = box.column(align=True)

        from ..enums import GLOBAL_FLAGS  # ensure correct import path if needed

        for identifier, label, tooltip, icon, bit in GLOBAL_FLAGS[:5]:
            wl_box.prop_enum(flags, "flagsLK", identifier, text=label, icon=icon)

        # --- Legion flags (only if version >= 6, else optional) ---
        if version == '6':
            box.separator()
            box.label(text="Legion Flags")
            lg_box = box.column(align=True)

            for identifier, label, tooltip, icon, bit in GLOBAL_FLAGS[5:]:
                lg_box.prop_enum(flags, "flagsLegion", identifier, text=label, icon=icon)

# ---------------------------
# Register
# ---------------------------

def register():
    bpy.types.Collection.wow_m2_globalflags = bpy.props.PointerProperty(type=WowM2globalflagsPropertyGroup)


def unregister():
    del bpy.types.Collection.wow_m2_globalflags