import bpy

# ---------------------------
# Helpers
# ---------------------------

def find_color_controller():
    for col in bpy.data.collections:
        # Look for collection that has a child called "Color_Transparency"
        # This needs to be changed later to only fetch the controller belonging to the specific m2
        if "Color_Transparency" in col.children:
            subcol = col.children.get("Color_Transparency")
            for obj in subcol.objects:
                if obj.get("is_color_transparency_controller") or obj.name == "ColorTransparencyController":
                    return obj
    return None
    
def draw_color_transparency_ui(layout, controller):
    props = controller.wow_m2_color_transparency

    # Colors (top)
    layout.label(text="Colors")
    layout.template_list("M2_UL_color_list", "", props, "colors", props, "cur_color_index")

    row = layout.row(align=True)
    row.operator("object.wow_m2_add_color", icon='ADD', text="")
    row.operator("object.wow_m2_remove_color", icon='REMOVE', text="")

    layout.separator()  # spacing between sections

    # Transparencies (bottom)
    layout.label(text="Transparencies")
    layout.template_list("M2_UL_transparency_list", "", props, "transparencies", props, "cur_trans_index")

    row = layout.row(align=True)
    row.operator("object.wow_m2_add_transparency", icon='ADD', text="")
    row.operator("object.wow_m2_remove_transparency", icon='REMOVE', text="")

# ---------------------------
# Property groups
# ---------------------------

class WowM2SingleColor(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty()
    color: bpy.props.FloatVectorProperty(
        name='Color', subtype='COLOR',
        default=(1.0, 1.0, 1.0), size=3, min=0.0, max=1.0
    )
    alpha: bpy.props.FloatProperty(
        name="Alpha",
        default=1.0,
        min=0.0,
        max=1.0
    )

class WowM2SingleTransparency(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty()
    value: bpy.props.FloatProperty(
        name='Transparency', default=1.0, min=0.0, max=1.0
    )

class WowM2ColorTransparencyPropertyGroup(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(default=False)
    colors: bpy.props.CollectionProperty(type=WowM2SingleColor)
    transparencies: bpy.props.CollectionProperty(type=WowM2SingleTransparency)
    cur_color_index: bpy.props.IntProperty(default=0)
    cur_trans_index: bpy.props.IntProperty(default=0)

# ---------------------------
# UI lists and panel
# ---------------------------

class M2_UL_color_list(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index, flt_flag):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False, icon='COLOR')
        row.prop(item, "color", text="")
        row.prop(item, "alpha", text="A")

class M2_UL_transparency_list(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index, flt_flag):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False, icon='MOD_OPACITY')
        row.prop(item, "value", text="")

class M2_PT_color_transparency_scene_panel(bpy.types.Panel):
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_label = "M2 Color / Transparency"

    def draw(self, context):
        layout = self.layout
        controller = find_color_controller()

        if not controller:
            layout.label(text="No ColorTransparencyController found", icon='ERROR')
            return

        draw_color_transparency_ui(layout, controller)

class M2_PT_color_transparency_object_panel(bpy.types.Panel):
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"
    bl_label = "M2 Color / Transparency"
    bl_parent_id = "" 

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj and obj.get("is_color_transparency_controller")

    def draw(self, context):
        layout = self.layout
        controller = context.object
        draw_color_transparency_ui(layout, controller)

# ---------------------------
# Operators
# ---------------------------

class M2_OT_add_color(bpy.types.Operator):
    bl_idname = "object.wow_m2_add_color"
    bl_label = "Add Color"
    def execute(self, context):
        controller = find_color_controller()
        if not controller: return {'CANCELLED'}

        props = controller.wow_m2_color_transparency
        c = props.colors.add()
        c.name = f"Color_{len(props.colors)-1}"
        props.cur_color_index = len(props.colors)-1
        return {'FINISHED'}

class M2_OT_remove_color(bpy.types.Operator):
    bl_idname = "object.wow_m2_remove_color"
    bl_label = "Remove Color"
    def execute(self, context):
        controller = find_color_controller()
        if not controller: return {'CANCELLED'}

        props = controller.wow_m2_color_transparency
        if props.colors:
            props.colors.remove(props.cur_color_index)
        return {'FINISHED'}

class M2_OT_add_transparency(bpy.types.Operator):
    bl_idname = "object.wow_m2_add_transparency"
    bl_label = "Add Transparency"
    def execute(self, context):
        controller = find_color_controller()
        if not controller: return {'CANCELLED'}

        props = controller.wow_m2_color_transparency
        t = props.transparencies.add()
        t.name = f"Transparency_{len(props.transparencies)-1}"
        props.cur_trans_index = len(props.transparencies)-1
        return {'FINISHED'}

class M2_OT_remove_transparency(bpy.types.Operator):
    bl_idname = "object.wow_m2_remove_transparency"
    bl_label = "Remove Transparency"
    def execute(self, context):
        controller = find_color_controller()
        if not controller: return {'CANCELLED'}

        props = controller.wow_m2_color_transparency
        if props.transparencies:
            props.transparencies.remove(props.cur_trans_index)
        return {'FINISHED'}

# ---------------------------
# Registration
# ---------------------------

def register():
    bpy.types.Object.wow_m2_color_transparency = bpy.props.PointerProperty(type=WowM2ColorTransparencyPropertyGroup)

def unregister():
    del bpy.types.Object.wow_m2_color_transparency