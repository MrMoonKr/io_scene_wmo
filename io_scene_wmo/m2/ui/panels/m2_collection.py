import bpy
from ... import util

# ---------------------------
# Property + Update Callback
# ---------------------------

def m2_collection_enable_update(self, context):
    """Called when user toggles the enable checkbox."""
    try:
        if self.wow_enable_m2_collection:
            # Run collection setup
            util.get_or_create_m2_collection(self)
            # Disable the checkbox permanently once used
            self.wow_enable_m2_collection = False
            bpy.ops.wm.redraw_timer(type='DRAW_WIN', iterations=1)
    except Exception as e:
        print(f"[M2] Failed to initialize M2 Collection: {e}")


# ---------------------------
# UI Panel (Collection Properties Tab)
# ---------------------------

class M2_PT_collection(bpy.types.Panel):
    bl_label = "M2 Collection"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "collection"

    @classmethod
    def poll(cls, context):
        col = context.collection
        if not col:
            return False

        # Must be a root collection (direct child of scene)
        is_root = any(child is col for child in context.scene.collection.children)

        return is_root

    def draw(self, context):
        col = context.collection
        layout = self.layout
        box = layout.box()

        if col.get("wow_m2_collection", False):
            box.label(text="This collection is an M2 Collection", icon="CHECKMARK")
            box.label(text="It contains M2 scene data & controllers.")
        else:
            box.label(text="Convert this collection to M2 structure", icon="MOD_BUILD")
            box.prop(col, "wow_enable_m2_collection", text="Enable")


# ---------------------------
# Registration
# ---------------------------

def register():
    bpy.types.Collection.wow_enable_m2_collection = bpy.props.BoolProperty(
        name="Enable",
        description="Convert this collection into an M2 collection",
        default=False,
        update=m2_collection_enable_update,
    )

def unregister():
    del bpy.types.Collection.wow_enable_m2_collection