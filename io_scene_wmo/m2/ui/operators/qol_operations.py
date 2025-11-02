import bpy
from ... import util as util

class M2_OT_disable_drivers(bpy.types.Operator):
    bl_idname = 'scene.m2_ot_disable_drivers'
    bl_label = 'Disable Drivers'
    bl_description = "Disables drivers from materials so you can copy/paste them to other scenes"
    bl_options = {'REGISTER', 'UNDO_GROUPED'}

    def execute(self, context):
        for mat in bpy.data.materials:
            if not mat.node_tree:
                continue

            nodes = mat.node_tree.nodes
            transparency_node = nodes.get("Transparency")
            color_node = nodes.get("Color")
            color_alpha_mix = nodes.get("Color_Alpha_Mix")

            # Transparency
            if transparency_node:
                input_socket = transparency_node.inputs[1]
                if not input_socket.is_linked:
                    transp_driver_path = 'nodes["Transparency"].inputs[1].default_value'
                    transparency_node.label = transparency_node.label.replace("ON", "OFF")

                    if mat.node_tree.animation_data:
                        for drv in mat.node_tree.animation_data.drivers:
                            if drv.data_path == transp_driver_path:
                                try:
                                    transparency_node.inputs[1].driver_remove("default_value")
                                except TypeError as e:
                                    print(f"Error removing Transparency driver: {e}")
                                break

            # Color node (RGB)
            if color_node:
                color_driver_path = 'nodes["Color"].inputs[7].default_value'
                color_node.label = color_node.label.replace("ON", "OFF")
                if mat.node_tree.animation_data:
                    for drv in mat.node_tree.animation_data.drivers:
                        if drv.data_path.startswith(color_driver_path):
                            try:
                                color_node.inputs[7].driver_remove("default_value")
                            except (TypeError, IndexError) as e:
                                print(f"Error removing Color driver: {e}")
                            break

            # Color Alpha Mix
            if color_alpha_mix:
                input_socket = color_alpha_mix.inputs[1]
                if not input_socket.is_linked:
                    col_alpha_driver_path = 'nodes["Color_Alpha_Mix"].inputs[1].default_value'
                    color_alpha_mix.label = color_alpha_mix.label.replace("ON", "OFF")
                    if mat.node_tree.animation_data:
                        for drv in mat.node_tree.animation_data.drivers:
                            if drv.data_path == col_alpha_driver_path:
                                try:
                                    color_alpha_mix.inputs[1].driver_remove("default_value")
                                except TypeError as e:
                                    print(f"Error removing Color_Alpha_Mix driver: {e}")
                                break

        bpy.ops.wbs.viewport_text_display('INVOKE_DEFAULT', message="Info: Drivers Disabled!", font_size=24, y_offset=67)
        return {'FINISHED'}


class M2_OT_enable_drivers(bpy.types.Operator):
    bl_idname = 'scene.m2_ot_enable_drivers'
    bl_label = 'Enable Drivers'
    bl_description = "Enables drivers for materials after copying/pasting them to other scenes"
    bl_options = {'REGISTER', 'UNDO_GROUPED'}

    def execute(self, context):
        controller = util.find_color_transparency_controller()

        for mat in bpy.data.materials:
            if not mat.node_tree:
                continue

            nodes = mat.node_tree.nodes
            transparency_node = nodes.get("Transparency")
            color_node = nodes.get("Color")
            color_alpha_mix = nodes.get("Color_Alpha_Mix")

            # --- Transparency driver ---
            if transparency_node:
                input_socket = transparency_node.inputs[1]
                if not input_socket.is_linked:
                    driver_path = 'nodes["Transparency"].inputs[1].default_value'

                    driver_exists = any(
                        drv.data_path == driver_path
                        for drv in (mat.node_tree.animation_data.drivers if mat.node_tree.animation_data else [])
                    )

                    if not driver_exists:
                        try:
                            driver = transparency_node.inputs[1].driver_add("default_value").driver
                            driver.type = 'SCRIPTED'
                            driver.expression = 'Transparency'

                            var = driver.variables.new()
                            var.name = 'Transparency'
                            var.targets[0].id_type = 'OBJECT'
                            var.targets[0].id = controller

                            trans_name = mat.wow_m2_material.transparency
                            trans_index = int(''.join(filter(str.isdigit, trans_name)))
                            var.targets[0].data_path = f"wow_m2_color_transparency.transparencies[{trans_index}].value"

                            transparency_node.label = transparency_node.label.replace("OFF", "ON")
                        except Exception as e:
                            print(f"Error adding Transparency driver: {e}")

            # --- Color RGB drivers ---
            color_name = mat.wow_m2_material.color
            color_index = int(''.join(filter(str.isdigit, color_name))) if color_name else 0

            if color_node:
                color_components = ['R', 'G', 'B']
                if color_node.inputs[0].default_value == 1.0:
                    color_node.label = color_node.label.replace("OFF", "ON")

                for i, comp in enumerate(color_components):
                    driver_path = f'nodes["Color"].inputs[7].default_value[{i}]'
                    driver_exists = any(
                        drv.data_path == driver_path
                        for drv in (mat.node_tree.animation_data.drivers if mat.node_tree.animation_data else [])
                    )
                    if not driver_exists:
                        try:
                            driver = color_node.inputs[7].driver_add("default_value", i).driver
                            driver.type = 'SCRIPTED'
                            driver.expression = comp

                            var = driver.variables.new()
                            var.name = comp
                            var.targets[0].id_type = 'OBJECT'
                            var.targets[0].id = controller
                            var.targets[0].data_path = f"wow_m2_color_transparency.colors[{color_index}].color[{i}]"

                        except Exception as e:
                            print(f"Error adding Color driver ({comp}): {e}")

            # --- Color Alpha driver ---
            if color_alpha_mix:
                input_socket = color_alpha_mix.inputs[1]
                if not input_socket.is_linked:
                    driver_path = 'nodes["Color_Alpha_Mix"].inputs[1].default_value'

                    driver_exists = any(
                        drv.data_path == driver_path
                        for drv in (mat.node_tree.animation_data.drivers if mat.node_tree.animation_data else [])
                    )

                    if not driver_exists:
                        try:
                            driver = color_alpha_mix.inputs[1].driver_add("default_value").driver
                            driver.type = 'SCRIPTED'
                            driver.expression = 'Alpha'

                            var = driver.variables.new()
                            var.name = 'Alpha'
                            var.targets[0].id_type = 'OBJECT'
                            var.targets[0].id = controller
                            var.targets[0].data_path = f"wow_m2_color_transparency.colors[{color_index}].alpha"

                            color_alpha_mix.label = color_alpha_mix.label.replace("OFF", "ON")
                        except Exception as e:
                            print(f"Error adding Color_Alpha_Mix driver: {e}")

        bpy.ops.wbs.viewport_text_display('INVOKE_DEFAULT', message="Info: Drivers Enabled!", font_size=24, y_offset=67)
        return {'FINISHED'}
