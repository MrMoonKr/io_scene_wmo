import bpy

class M2_OT_disable_drivers(bpy.types.Operator):
    bl_idname = 'scene.m2_ot_disable_drivers'
    bl_label = 'Disable Drivers'
    bl_description = "Disables drivers from materials so you can copy/paste them to other scenes"
    bl_options = {'REGISTER', 'UNDO_GROUPED'}

    def execute(self, context):
        for mat in bpy.data.materials:
            if mat.node_tree:
                nodes = mat.node_tree.nodes
                transparency_node = nodes.get("Transparency")
                if transparency_node:
                    input_socket = transparency_node.inputs[1]
                    if input_socket.is_linked:
                        continue
                    driver_path = f'nodes["Transparency"].inputs[1].default_value'
                    transparency_node.label = transparency_node.label.replace("ON", "OFF")
                    
                    if mat.node_tree.animation_data:
                        for driver in mat.node_tree.animation_data.drivers:
                            if driver.data_path == driver_path:
                                # Remove the driver
                                try:
                                    transparency_node.inputs[1].driver_remove("default_value")
                                except TypeError as e:
                                    print(f"Error removing driver: {e}")
                                break

        bpy.ops.wbs.viewport_text_display('INVOKE_DEFAULT', message="Info: Drivers Disabled!", font_size=24, y_offset=67)      
        return {'FINISHED'}

class M2_OT_enable_drivers(bpy.types.Operator):
    bl_idname = 'scene.m2_ot_enable_drivers'
    bl_label = 'Enable Drivers'
    bl_description = "Enables drivers for materials after copying/pasting them to other scenes"
    bl_options = {'REGISTER', 'UNDO_GROUPED'}

    def execute(self, context):
        for mat in bpy.data.materials:
            if mat.node_tree:
                nodes = mat.node_tree.nodes
                transparency_node = nodes.get("Transparency")
                if transparency_node:
                    input_socket = transparency_node.inputs[1]
                    if input_socket.is_linked:
                        continue
                    driver_path = f'nodes["Transparency"].inputs[1].default_value'
                    
                    # Check if driver already exists
                    driver_exists = False
                    if mat.node_tree.animation_data:
                        for driver in mat.node_tree.animation_data.drivers:
                            if driver.data_path == driver_path:
                                driver_exists = True
                                break

                    if not driver_exists:
                        # Add the driver if it does not exist
                        try:
                            driver = transparency_node.inputs[1].driver_add("default_value").driver
                            driver.type = 'SCRIPTED'
                            driver.expression= 'Transparency'
                            trans_name_var = driver.variables.new()
                            trans_name_var.name = 'Transparency'
                            trans_name_var.targets[0].id_type = 'SCENE'
                            trans_name_var.targets[0].id = bpy.context.scene
                            trans_name = mat.wow_m2_material.transparency
                            trans_index = int(''.join(filter(str.isdigit, trans_name)))
                            trans_name_var.targets[0].data_path = f'wow_m2_transparency[{trans_index}].value'
                            transparency_node.label = transparency_node.label.replace("OFF", "ON")
                        except Exception as e:
                            print(f"Error adding driver: {e}")

        bpy.ops.wbs.viewport_text_display('INVOKE_DEFAULT', message="Info: Drivers Enabled!", font_size=24, y_offset=67)                                  
        return {'FINISHED'}