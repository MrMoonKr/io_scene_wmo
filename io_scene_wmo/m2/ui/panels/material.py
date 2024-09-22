import bpy
from ..enums import *
from ...bl_render.cycles import update_m2_mat_node_tree_cycles
    
class TexturePathDefaultButton(bpy.types.Operator):
    bl_idname = "wow_m2_texture.set_default_texture"
    bl_label = "Set Default Texture Path"

    texture_index: bpy.props.IntProperty()

    def execute(self, context):
        default_texture_path = "textures\\ShaneCube.blp"
        if self.texture_index == 1:  
            context.material.wow_m2_material.texture_1.wow_m2_texture.path = default_texture_path
        elif self.texture_index == 2:
            context.material.wow_m2_material.texture_2.wow_m2_texture.path = default_texture_path    
        return {'FINISHED'}    
        
class TextureSlotPropertyGroup(bpy.types.PropertyGroup):
    texture_flags: bpy.props.EnumProperty(
        name="Texture flags",
        description="WoW M2 texture flags",
        items=TEXTURE_FLAGS,
        options={"ENUM_FLAG"},
        default={'1', '2'}
    )

    texture_type: bpy.props.EnumProperty(
        name="Texture type",
        description="WoW M2 texture type",
        items=TEXTURE_TYPES
    )
    
    path: bpy.props.StringProperty(
        name='Path',
        description='Path to .blp file in wow file system.'
    )   

class ToggleTexturesOperator(bpy.types.Operator):
    bl_idname = "object.toggle_textures"
    bl_label = "Toggle Textures"
    
    def execute(self, context):
        context.scene.show_textures = not context.scene.show_textures        
        return {'FINISHED'}
    
class ToggleRenderFlagsOperator(bpy.types.Operator):
    bl_idname = "object.toggle_render_flags"
    bl_label = "Toggle Render Flags"

    texture_index: bpy.props.IntProperty()
    
    def execute(self, context):
        if self.texture_index == 1:  
            context.scene.show_t1_render_flags = not context.scene.show_t1_render_flags
        elif self.texture_index == 2:  
            context.scene.show_t2_render_flags = not context.scene.show_t2_render_flags            
        return {'FINISHED'}

bpy.types.Scene.show_textures = bpy.props.BoolProperty(name="Show Textures", default=True)        
bpy.types.Scene.show_t1_render_flags = bpy.props.BoolProperty(name="Show Render Flags", default=False)    
bpy.types.Scene.show_t2_render_flags = bpy.props.BoolProperty(name="Show Render Flags", default=False)

class M2_PT_material_panel(bpy.types.Panel):
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "material"
    bl_label = "M2 Material"

    def draw(self, context):
        layout = self.layout
        col = layout.column()
        col.label(text='Textures')
        col.operator("object.toggle_textures", text="Toggle Textures") 
        if context.scene.show_textures:
            col.separator()
            col.label(text='Texture 1')
            col.prop(context.material.wow_m2_material, "texture_1", text="")
            if context.material.wow_m2_material.texture_1:
                col.prop(context.material.wow_m2_material.texture_1.wow_m2_texture, "flags")
                col.separator()
                col.prop(context.material.wow_m2_material.texture_1.wow_m2_texture, "texture_type")
                # only show path setting if texture type is hardcoded
                if context.material.wow_m2_material.texture_1.wow_m2_texture.texture_type == "0":
                    col.prop(context.material.wow_m2_material.texture_1.wow_m2_texture, "path", text='Path')
                    # Check if path is empty, then show the button
                    if len(context.material.wow_m2_material.texture_1.wow_m2_texture.path) == 0:
                        op = col.operator(TexturePathDefaultButton.bl_idname, text="Set Default Path", icon='FILEBROWSER') 
                        op.texture_index = 1
                col.separator()
                col.label(text='Blending')
                col.prop(context.material.wow_m2_material, "texture_1_blending_mode", text="")  
                to = col.operator("object.toggle_render_flags", text="Toggle Render Flags")  
                to.texture_index = 1        
                if context.scene.show_t1_render_flags:
                    col.separator()
                    col.label(text='Render Flags:')
                    box = col.box()
                    box.prop(context.material.wow_m2_material, "texture_1_render_flags", text="Texture 1 Render Flags", toggle=True)   
                col.separator()
                col.prop(context.material.wow_m2_material, "texture_1_mapping")
                sub_col = col.column()
                row = sub_col.row()
                row.prop(context.material.wow_m2_material, "texture_1_animation") 
                op = row.operator("scene.wow_m2_geoset_add_texture_transform", text='', icon='RNA_ADD') 
                op.channel = 1        

                col.separator()
                col.label(text='Texture 2')
                col.prop(context.material.wow_m2_material, "texture_2", text="")
                if context.material.wow_m2_material.texture_2:
                    col.prop(context.material.wow_m2_material.texture_2.wow_m2_texture, "flags")
                    col.separator()
                    col.prop(context.material.wow_m2_material.texture_2.wow_m2_texture, "texture_type")
                    # only show path setting if texture type is hardcoded
                    if context.material.wow_m2_material.texture_2.wow_m2_texture.texture_type == "0":
                        col.prop(context.material.wow_m2_material.texture_2.wow_m2_texture, "path", text='Path')
                        if len(context.material.wow_m2_material.texture_2.wow_m2_texture.path) == 0:
                            op = col.operator(TexturePathDefaultButton.bl_idname, text="Set Default Path", icon='FILEBROWSER')    
                            op.texture_index = 2
                    col.separator()
                    col.label(text='Blending')
                    col.prop(context.material.wow_m2_material, "texture_2_blending_mode", text="")
                    to = col.operator("object.toggle_render_flags", text="Toggle Render Flags")  
                    to.texture_index = 2        
                    if context.scene.show_t2_render_flags:
                        col.separator()
                        col.label(text='Render Flags:')
                        box = col.box()
                        box.prop(context.material.wow_m2_material, "texture_2_render_flags", text="Texture 2 Render Flags", toggle=True)                     
                    col.separator()
                    col.prop(context.material.wow_m2_material, "texture_2_mapping")
                    sub_col = col.column()
                    row = sub_col.row()
                    row.prop(context.material.wow_m2_material, "texture_2_animation") 
                    op = row.operator("scene.wow_m2_geoset_add_texture_transform", text='', icon='RNA_ADD')  
                    op.channel = 2  
        
        col.separator()
        col.label(text='Flags:')
        col.prop(context.material.wow_m2_material, "flags")
        col.separator()
        col.label(text='Sorting control:')
        col.prop(context.material.wow_m2_material, "priority_plane")
        col.separator()
        col.prop_search(context.material.wow_m2_material, "color",
                        context.scene, "wow_m2_colors", text='Color', icon='COLOR')
        col.prop_search(context.material.wow_m2_material, "transparency",
                        context.scene, "wow_m2_transparency", text='Transparency', icon='RESTRICT_VIEW_OFF')

    @classmethod
    def poll(cls, context):
        return(context.scene is not None
               and context.scene.wow_scene.type == 'M2'
               and context.material is not None)

def update_geoset_uv_transform_1(self, context):
    obj = context.object

    if obj.active_material:
        c_obj = obj.active_material.wow_m2_material.texture_1_animation
        tex_1_mapping = obj.active_material.wow_m2_material.texture_1_mapping

        for node in obj.active_material.node_tree.nodes:
            if node.name == 'Tex1_mapping':
                tex1_mapping = node

        tex1_mapping.uv_map = tex_1_mapping

        if c_obj:

            uv_transform_1 = context.object.modifiers.get('M2TexTransform_1')        
            
            if c_obj is not None:
                if c_obj.wow_m2_uv_transform is not None:
                    if not c_obj.wow_m2_uv_transform.enabled:
                        context.object.wow_m2_geoset.uv_transform = None

            if not uv_transform_1:
                bpy.ops.object.modifier_add(type='UV_WARP')
                uv_transform_1 = context.object.modifiers[-1]
                uv_transform_1.name = 'M2TexTransform_1'
                uv_transform_1.object_from = obj
                uv_transform_1.object_to = c_obj
                uv_transform_1.uv_layer = obj.active_material.wow_m2_material.texture_1_mapping
            else:
                uv_transform_1.object_to = c_obj
                uv_transform_1.uv_layer = obj.active_material.wow_m2_material.texture_1_mapping
        else:
            uv_transform_1 = context.object.modifiers.get('M2TexTransform_1')   
            if uv_transform_1 is not None and c_obj is None:
                context.object.modifiers.remove(uv_transform_1)

def update_geoset_uv_transform_2(self, context):
    obj = context.object

    if obj.active_material:
        c_obj = obj.active_material.wow_m2_material.texture_2_animation
        tex_2_mapping = obj.active_material.wow_m2_material.texture_2_mapping


        for node in obj.active_material.node_tree.nodes:
            if node.name == 'Tex2_mapping':
                tex2_mapping = node

        tex2_mapping.uv_map = tex_2_mapping
        
        if c_obj:

            uv_transform_2 = context.object.modifiers.get('M2TexTransform_2')

            if c_obj is not None:
                if c_obj.wow_m2_uv_transform is not None:
                    if not c_obj.wow_m2_uv_transform.enabled:
                        context.object.wow_m2_geoset.uv_transform = None

            if not uv_transform_2:
                bpy.ops.object.modifier_add(type='UV_WARP')
                uv_transform_2 = context.object.modifiers[-1]
                uv_transform_2.name = 'M2TexTransform_2'
                uv_transform_2.object_from = obj
                uv_transform_2.object_to = c_obj
                uv_transform_2.uv_layer = obj.active_material.wow_m2_material.texture_2_mapping
            else:
                uv_transform_2.object_to = c_obj
                uv_transform_2.uv_layer = obj.active_material.wow_m2_material.texture_2_mapping
        else:
            uv_transform_2 = context.object.modifiers.get('M2TexTransform_2')   
            if uv_transform_2 is not None and c_obj is None:
                context.object.modifiers.remove(uv_transform_2)          

def update_material_texture(self, context):
    obj = context.object

    if obj.active_material:
        tex_1 = obj.active_material.wow_m2_material.texture_1
        tex_2 = obj.active_material.wow_m2_material.texture_2
        
        for node in obj.active_material.node_tree.nodes:
            if node.name == 'Tex1_image':
                tex1_image = node
                tex1_image.image = tex_1
            if node.name == 'Tex2_image':
                tex2_image = node
                tex2_image.image = tex_2       
        
def update_transparency(self, context):
    obj = context.object

    if obj != None and obj.active_material:
            
        transparency_node = obj.active_material.node_tree.nodes.get('Transparency')

        if transparency_node:

            trans_name = obj.active_material.wow_m2_material.transparency
            trans_index = int(''.join(filter(str.isdigit, trans_name)))                    
            transparency_node.label = f'Transparency_{trans_index}_OFF'

            for driver in transparency_node.id_data.animation_data.drivers:
                if driver.data_path == 'nodes["Transparency"].inputs[1].default_value':
                    existing_driver = driver.driver
                    
                    for var in existing_driver.variables:
                        if var.name == 'Transparency':
                            transparency_var = var.targets[0]
                                                            
                            transparency_var.data_path = f'wow_m2_transparency[{trans_index}].value'
                            transparency_node.label = f'Transparency_{trans_index}_ON'

def update_blending(self, context):
    obj = context.object

    if obj != None and obj.active_material and obj.active_material.wow_m2_material:

        blending_1 = int(obj.active_material.wow_m2_material.texture_1_blending_mode)
        Alpha_mode = obj.active_material.node_tree.nodes.get('Tex1_image')

        if blending_1 in [1, 2, 4, 5, 6]:
            Alpha_mode.image.alpha_mode = 'CHANNEL_PACKED'
        else:
            Alpha_mode.image.alpha_mode = 'NONE'

class WowM2MaterialPropertyGroup(bpy.types.PropertyGroup):
    
    enabled:  bpy.props.BoolProperty()

    flags:  bpy.props.EnumProperty(
        name="Material flags",
        description="WoW  M2 material flags",
        items=TEX_UNIT_FLAGS,
        options={"ENUM_FLAG"}
        )

    texture_1_render_flags:  bpy.props.EnumProperty(
        name="Render flags",
        description="WoW  M2 render flags",
        items=RENDER_FLAGS,
        options={"ENUM_FLAG"}
        )
    
    texture_1_animation:  bpy.props.PointerProperty(
        name="UV Transform",
        description="WoW  M2 texture 1 animation",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.wow_m2_uv_transform.enabled,
        update=update_geoset_uv_transform_1
    )

    texture_2_animation:  bpy.props.PointerProperty(
        name="UV Transform",
        description="WoW  M2 texture 2 animation",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.wow_m2_uv_transform.enabled,
        update=update_geoset_uv_transform_2
    )      
    
    texture_2_render_flags:  bpy.props.EnumProperty(
        name="Render flags",
        description="WoW  M2 render flags",
        items=RENDER_FLAGS,
        options={"ENUM_FLAG"}
        )    

    vertex_shader:  bpy.props.EnumProperty(
        items=VERTEX_SHADERS,
        name="Vertex Shader",
        description="WoW vertex shader assigned to this material",
        default='0'
        )

    fragment_shader:  bpy.props.EnumProperty(
        items=FRAGMENT_SHADERS,
        name="Fragment Shader",
        description="WoW fragment shader assigned to this material",
        default='0'
        )

    shader: bpy.props.IntProperty(
        name='Shader'
        )

    texture_1_blending_mode:  bpy.props.EnumProperty(
        items=BLENDING_MODES,
        name="Blending",
        description="WoW material blending mode",
        update=update_blending
        )
    
    texture_2_blending_mode:  bpy.props.EnumProperty(
        items=BLENDING_MODES,
        name="Blending",
        description="WoW material blending mode"
        )     

    texture_1_mapping: bpy.props.EnumProperty(
        items=TEXTURE_MAPPING,
        name="Mapping",
        description="Select the mapping for Texture 1",
        default='UVMap',
        update=update_geoset_uv_transform_1
    )

    texture_2_mapping: bpy.props.EnumProperty(
        items=TEXTURE_MAPPING,
        name="Mapping",
        description="Select the mapping for Texture 2",
        default='UVMap.001',
        update=update_geoset_uv_transform_2
    )  

    texture_1: bpy.props.PointerProperty(
        type=bpy.types.Image,
        update=update_material_texture
    )

    texture_2: bpy.props.PointerProperty(
        type=bpy.types.Image,
        update=update_material_texture
    )

    #Removed layer, we can calculate it on export by material index
    # layer: bpy.props.IntProperty(
    #     min=0,
    #     max=7
    # )  

    priority_plane: bpy.props.IntProperty(
        min=-127,
        max=127,
        default=0
    )

    color: bpy.props.StringProperty(
        name='Color',
        description='Color track linked to this texture.'
    )

    transparency: bpy.props.StringProperty(
        name='Transparency',
        description='Transparency track linked to this texture.',
        update=update_transparency
    )

    self_pointer: bpy.props.PointerProperty(type=bpy.types.Material)

class M2_OT_add_texture_transform(bpy.types.Operator):
    bl_idname = 'scene.wow_m2_geoset_add_texture_transform'
    bl_label = 'Add new UV transform controller'
    bl_options = {'REGISTER', 'INTERNAL', 'UNDO_GROUPED'}

    anim_index:  bpy.props.IntProperty()
    channel:  bpy.props.IntProperty(min=1, max=2)

    def execute(self, context):
        obj = context.object
        bpy.ops.object.empty_add(type='SINGLE_ARROW', location=(0, 0, 0))
        c_obj = bpy.context.view_layer.objects.active
        c_obj.name = "TT_Controller"
        c_obj.wow_m2_uv_transform.enabled = True
        c_obj = bpy.context.view_layer.objects.active
        c_obj.rotation_mode = 'QUATERNION'
        c_obj.empty_display_size = 0.5
        c_obj.animation_data_create()
        c_obj.animation_data.action_blend_type = 'ADD'

        if self.channel == 1:
            obj.active_material.wow_m2_material.texture_1_animation = c_obj
        else:
            obj.active_material.wow_m2_material.texture_2_animation = c_obj

        bpy.context.view_layer.objects.active = obj

        return {'FINISHED'}
    
def register():
    bpy.utils.register_class(TexturePathDefaultButton)
    bpy.types.Material.wow_m2_material = bpy.props.PointerProperty(type=WowM2MaterialPropertyGroup)

def unregister():
    bpy.utils.unregister_class(TexturePathDefaultButton)
    del bpy.types.Material.wow_m2_material
