import bpy

from ....utils.node_builder import NodeTreeBuilder


def update_m2_mat_node_tree_cycles(bl_mat):

    # get textures
    img_1 = bl_mat.wow_m2_material.texture_1 if bl_mat.wow_m2_material.texture_1 else None
    img_2 = bl_mat.wow_m2_material.texture_2 if bl_mat.wow_m2_material.texture_2 else None

    def mapping(mapping_method):
        if mapping_method == "UVMap":
            return 'UVMap'
        elif mapping_method == "UVMap.001":
            return 'UVMap.001'
        elif mapping_method == "Env":
            return 'UVMap.001'  
            
    tex1_uv = mapping(bl_mat.wow_m2_material.texture_1_mapping) if bl_mat.wow_m2_material.texture_1_mapping else None
    tex2_uv = mapping(bl_mat.wow_m2_material.texture_2_mapping) if bl_mat.wow_m2_material.texture_2_mapping else None

    bl_mat.use_nodes = True
    uv = bl_mat.node_tree.nodes.new('ShaderNodeUVMap')
    uv.location = -925, 0
    uv.name = 'Tex1_mapping'
    uv.uv_map = tex1_uv
    uv2 = bl_mat.node_tree.nodes.new('ShaderNodeUVMap')
    uv2.location = -925, -135
    uv2.name = 'Tex2_mapping'
    uv2.uv_map = tex2_uv
    bsdf = bl_mat.node_tree.nodes["Principled BSDF"]
    bsdf.name = 'BSDF'
    tex_image = bl_mat.node_tree.nodes.new('ShaderNodeTexImage')
    tex_image.location = -725, 200
    tex_image.name = 'Tex1_image'
    tex_image2 = bl_mat.node_tree.nodes.new('ShaderNodeTexImage')
    tex_image2.location = -725, -135
    tex_image2.name = 'Tex2_image'

    if img_1:
        tex_image.image = img_1

    if img_2:
        tex_image2.image = img_2

    bsdf.inputs['Specular'].default_value = 0.0
    bl_mat.node_tree.links.new(bsdf.inputs['Base Color'], tex_image.outputs['Color'])
    bl_mat.node_tree.links.new(uv.outputs['UV'], tex_image.inputs['Vector'])
    bl_mat.node_tree.links.new(uv2.outputs['UV'], tex_image2.inputs['Vector'])
    
    if '4' in bl_mat.wow_m2_material.texture_1_render_flags:
        bl_mat.use_backface_culling = False
    else:
        bl_mat.use_backface_culling = True

    if bl_mat.wow_m2_material.texture_1_blending_mode == '0':
        bl_mat.node_tree.links.new(bsdf.inputs['Alpha'], tex_image.outputs['Alpha'])
        bl_mat.node_tree.links.new(uv.outputs['UV'], tex_image.inputs['Vector'])
        bl_mat.blend_method = 'BLEND'
        bl_mat.show_transparent_back = False

    if bl_mat.wow_m2_material.texture_1_blending_mode == '1':
        bl_mat.node_tree.links.new(bsdf.inputs['Alpha'], tex_image.outputs['Alpha'])
        bl_mat.node_tree.links.new(uv.outputs['UV'], tex_image.inputs['Vector'])
        bl_mat.blend_method = 'CLIP'
        bl_mat.alpha_threshold = 0.878431

    if bl_mat.wow_m2_material.texture_1_blending_mode == '2' or bl_mat.wow_m2_material.texture_1_blending_mode == '4':
        bl_mat.node_tree.links.new(bsdf.inputs['Alpha'], tex_image.outputs['Alpha'])
        bl_mat.node_tree.links.new(uv.outputs['UV'], tex_image.inputs['Vector'])
        bl_mat.blend_method = 'BLEND'

    # Opaque settings
    blending_1 = int(bl_mat.wow_m2_material.texture_1_blending_mode)
    if blending_1 in [1, 2, 4, 5, 6]:
        tex_image.image.alpha_mode = 'CHANNEL_PACKED'
    else:
        tex_image.image.alpha_mode = 'NONE'

    # transparency
    t_mult = bl_mat.node_tree.nodes.new('ShaderNodeMath')
    t_mult.location = -300, -50
    t_mult.operation = 'MULTIPLY'
    t_mult.name = 'Transparency'
    t_mult.inputs[1].default_value = 1.0

    transparency_curve = bl_mat.node_tree.driver_add("nodes[\"Transparency\"].inputs[1].default_value")
    driver = transparency_curve.driver
    driver.type = 'SCRIPTED'


    trans_name_var = driver.variables.new()
    trans_name_var.name = 'Transparency'
    trans_name_var.targets[0].id_type = 'SCENE'
    trans_name_var.targets[0].id = bpy.context.scene
    
    trans_name = bl_mat.wow_m2_material.transparency

    trans_index = int(''.join(filter(str.isdigit, trans_name)))
    trans_name_var.targets[0].data_path = f'wow_m2_transparency[{trans_index}].value'
    
    driver.expression = trans_name_var.name

    bl_mat.node_tree.links.new(tex_image.outputs['Alpha'], t_mult.inputs['Value'])   
    bl_mat.node_tree.links.new(t_mult.outputs['Value'], bsdf.inputs['Alpha'])        

""" if img_2:
        if bl_mat.wow_m2_material.texture_1_blending_mode == 0:
            bl_mat.blend_method = 'OPAQUE'
            bl_mat.node_tree.links.new(bsdf.inputs['Alpha'], tex_image2.outputs['Color'])
            bl_mat.node_tree.links.new(uv2.outputs['UV'], tex_image2.inputs['Vector'])
        elif bl_mat.wow_m2_material.texture_1_blending_mode == 1:
            bl_mat.blend_method = 'CLIP'
            bl_mat.node_tree.links.new(bsdf.inputs['Alpha'], tex_image2.outputs['Color'])
            bl_mat.node_tree.links.new(uv2.outputs['UV'], tex_image2.inputs['Vector'])
        elif bl_mat.wow_m2_material.texture_1_blending_mode == 2 or 4:
            bl_mat.blend_method = 'BLEND'
            bl_mat.node_tree.links.new(bsdf.inputs['Alpha'], tex_image2.outputs['Color'])
            bl_mat.node_tree.links.new(uv2.outputs['UV'], tex_image2.inputs['Vector'])
            bl_mat.show_transparent_back = False """
                      
    #else:
        #bl_mat.blend_method = 'OPAQUE' 

        