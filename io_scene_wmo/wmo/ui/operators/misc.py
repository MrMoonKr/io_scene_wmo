import bpy
import io
import os
import bmesh
from .... import PACKAGE_NAME
from ....utils.misc import load_game_data
from ....pywowlib.blp import PNG2BLP
# from ....pywowlib.io_utils.types import *
from ...ui.custom_objects import *
from ..collections import get_wmo_collection, SpecialCollections
from ....ui.preferences import get_project_preferences

from ....third_party.tqdm import tqdm


class WMO_OT_add_scale(bpy.types.Operator):
    bl_idname = 'scene.wow_add_scale_reference'
    bl_label = 'Add scale'
    bl_description = 'Add a WoW scale prop'
    bl_options = {'REGISTER', 'UNDO'}

    scale_type:  bpy.props.EnumProperty(
        name="Scale Type",
        description="Select scale reference type",
        items=[('HUMAN', "Human Scale (average)", ""),
               ('TAUREN', "Tauren Scale (thickest)", ""),
               ('TROLL', "Troll Scale (tallest)", ""),
               ('GNOME', "Gnome Scale (smallest)", "")
               ],
        default='HUMAN'
    )

    def execute(self, context):
        if self.scale_type == 'HUMAN':
            bpy.ops.object.add(type='LATTICE')
            scale_obj = bpy.context.object
            scale_obj.name = "Human Scale"
            scale_obj.dimensions = (0.582, 0.892, 1.989)

        elif self.scale_type == 'TAUREN':
            bpy.ops.object.add(type='LATTICE')
            scale_obj = bpy.context.object
            scale_obj.name = "Tauren Scale"
            scale_obj.dimensions = (1.663, 1.539, 2.246)

        elif self.scale_type == 'TROLL':
            bpy.ops.object.add(type='LATTICE')
            scale_obj = bpy.context.object
            scale_obj.name = "Troll Scale"
            scale_obj.dimensions = (1.116, 1.291, 2.367)

        elif self.scale_type == 'GNOME':
            bpy.ops.object.add(type='LATTICE')
            scale_obj = bpy.context.object
            scale_obj.name = "Gnome Scale"
            scale_obj.dimensions = (0.362, 0.758, 0.991)

        self.report({'INFO'}, "Successfully added " + self.scale_type + " scale")
        return {'FINISHED'}


class WMO_OT_quick_collision(bpy.types.Operator):
    bl_idname = 'scene.wow_quick_collision'
    bl_label = 'Generate collision'
    bl_description = 'Generate WoW collision equal to geometry of the selected objects'
    bl_options = {'REGISTER', 'UNDO'}

    leaf_size:  bpy.props.IntProperty(
        name="Node max size",
        description="Max count of faces for a node in bsp tree",
        default=2500,
        min=1,
        soft_max=5000
    )

    clean_up:  bpy.props.BoolProperty(
        name="Clean up",
        description="Remove unreferenced vertex groups",
        default=False
    )

    def execute(self, context):

        success = False
        selected_objects = bpy.context.selected_objects[:]
        bpy.ops.object.select_all(action='DESELECT')
        for ob in tqdm(selected_objects, desc='Generating collision', ascii=True):

            if WoWWMOGroup.match(ob):

                bpy.context.view_layer.objects.active = ob

                if self.clean_up:
                    for vertex_group in ob.vertex_groups:
                        if vertex_group.name != ob.wow_wmo_vertex_info.vertex_group:
                            ob.vertex_groups.remove(vertex_group)

                if ob.vertex_groups.get(ob.wow_wmo_vertex_info.vertex_group):
                    bpy.ops.object.vertex_group_set_active(group=ob.wow_wmo_vertex_info.vertex_group)
                else:
                    new_vertex_group = ob.vertex_groups.new(name="Collision")
                    bpy.ops.object.vertex_group_set_active(group=new_vertex_group.name)
                    ob.wow_wmo_vertex_info.vertex_group = new_vertex_group.name

                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.object.vertex_group_assign()
                bpy.ops.mesh.select_all(action='DESELECT')
                bpy.ops.object.mode_set(mode='OBJECT')
                ob.wow_wmo_vertex_info.node_size = self.leaf_size

                success = True

        if success:
            self.report({'INFO'}, "Successfully generated automatic collision for selected WMO groups")
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, "No WMO group objects found among selected objects")
            return {'CANCELLED'}


class WMO_OT_select_entity(bpy.types.Operator):
    bl_idname = 'scene.wow_wmo_select_entity'
    bl_label = 'Select WMO entities'
    bl_description = 'Select all WMO entities of given type'
    bl_options = {'REGISTER', 'INTERNAL'}

    entity:  bpy.props.EnumProperty(
        name="Entity",
        description="Select WMO component entity objects",
        items=[
            ("Outdoor", "Outdoor", ""),
            ("Indoor", "Indoor", ""),
            ("wow_wmo_portal", "Portals", ""),
            ("wow_wmo_liquid", "Liquids", ""),
            ("wow_wmo_fog", "Fogs", ""),
            ("wow_wmo_light", "Lights", ""),
            ("wow_wmo_doodad", "Doodads", ""),
            ("Collision", "Collision", "")
        ]
    )

    def execute(self, context):
        
        # can optimise by selecting by collection
        scene = bpy.context.scene
        if self.entity == "Outdoor":
            for obj in get_wmo_collection(scene, SpecialCollections.Outdoor).objects:
                obj.select_set(True)

        elif self.entity == "Indoor":
            for obj in get_wmo_collection(scene, SpecialCollections.Indoor).objects:
                obj.select_set(True)

        elif self.entity == "wow_wmo_portal":
            for obj in get_wmo_collection(scene, SpecialCollections.Portals).objects:
                obj.select_set(True)

        elif self.entity == "wow_wmo_liquid":
            for obj in get_wmo_collection(scene, SpecialCollections.Liquids).objects:
                obj.select_set(True)

        elif self.entity == "wow_wmo_fog":
            for obj in get_wmo_collection(scene, SpecialCollections.Fogs).objects:
                obj.select_set(True)

        elif self.entity == "wow_wmo_light":
            for obj in get_wmo_collection(scene, SpecialCollections.Lights).objects:
                obj.select_set(True)

        elif self.entity == "wow_wmo_doodad":
            for obj in get_wmo_collection(scene, SpecialCollections.Doodads).all_objects:
                if not obj.hide_get():
                    obj.select_set(True)
                
        elif self.entity == "Collision":
            for obj in get_wmo_collection(scene, SpecialCollections.Collision).objects:
                obj.select_set(True)


        return {'FINISHED'}


class WMO_OT_generate_minimaps(bpy.types.Operator):
    bl_idname = 'scene.wow_wmo_generate_minimaps'
    bl_label = 'Generate Minimaps'
    bl_description = 'Generate a wow minimap for WMO indoor groups(To the project folder)'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.scene.wow_scene.type == 'WMO'


    def execute(self, context):
        # name = 'Deadmines'
        #md5_path = r'WMO\Dungeon\Test'
        if not context.scene.wow_scene.game_path:
            raise Exception("Game path is empty. You must set the model's client path in |Scene properties->WoW Scene-> Game Path| to use this feature.\n(Example : World\wmo\Dungeon\AZ_Deadmines\AZ_Deadmines_A.wmo)")

        # md5_path = os.path.relpath(os.path.dirname(context.scene.wow_scene.game_path).lower(), 'world')  # wmo\Dungeon\AZ_Deadmines. removes the filename.wmo, then "World"
        md5_path = os.path.relpath(context.scene.wow_scene.game_path.split('.')[0].lower(), 'world')
        name = str(context.scene.wow_scene.game_path).split('\\')[-1].split('.')[0]
        # md5_ref = r'Deadmines'
        md5_ref = name
        print("path is : " + md5_path)
        print("name is : " + name)
        md5_entries = []

        game_data = load_game_data()

        try:
            file, _ = game_data.read_file("textures\\Minimap\\md5translate.trs")
            md5_file = io.BytesIO(file)
        except KeyError:
            raise FileNotFoundError("\nMD5 File <<{}>> not found in WoW file system.".format("textures\\Minimap\\md5translate.trs"))

        md5_file = md5_file.read()
        ###########

        # TODOs:
        # BLP conversion?

        def create_camera_object():
            # Return if a camera exists.
            if bpy.data.cameras.find('MinimapsCamera') == -1:
                bpy.data.cameras.new(name='MinimapsCamera')
            if bpy.data.objects.find('MinimapsCamera') != -1:
                if bpy.data.scenes["Scene"].collection.objects.find('MinimapsCamera') == -1:
                    bpy.data.scenes["Scene"].collection.objects.link(bpy.data.objects['MinimapsCamera'])
            else:
                cam_obj = bpy.data.objects.new('MinimapsCamera', bpy.data.cameras["MinimapsCamera"])
                bpy.data.scenes["Scene"].collection.objects.link(cam_obj)

            bpy.data.scenes["Scene"].camera = bpy.data.objects['MinimapsCamera']

        def set_mat_backface_culling():
            # for wmo_mat in bpy.data.scenes["Scene"].wow_wmo_root_elements.materials:
            for wmo_mat in bpy.data.materials:
                wmo_mat.pointer.use_backface_culling = True


        def disable_object_wmo_render_visiblity():
            for obj in bpy.context.scene.objects:
                obj.hide_render = True

            # for wmo_group in bpy.data.scenes["Scene"].wow_wmo_root_elements.groups:
            #     group_obj = wmo_group.pointer.hide_render = True


        def apply_render_settings():
            bpy.context.scene.view_settings.view_transform = 'Filmic'
            bpy.context.scene.view_settings.exposure = -0.5
            bpy.context.scene.view_settings.gamma = 1.5
            bpy.context.scene.view_settings.look = 'None'

            bpy.context.scene.render.image_settings.file_format = 'PNG'
            bpy.context.scene.render.image_settings.color_mode = 'RGBA'
            bpy.context.scene.render.film_transparent = True
            bpy.data.cameras["MinimapsCamera"].type = 'ORTHO'
            bpy.data.cameras["MinimapsCamera"].ortho_scale = 128.0


        def iterate_groups():
            wmo_outdoor_collection = bpy.data.collections.get('Outdoor')
            wmo_indoor_collection = bpy.data.collections.get('Indoor')
            for i, wmo_group in enumerate(list(wmo_outdoor_collection.objects) + list(wmo_indoor_collection.objects)):
                if WoWWMOGroup.is_indoor():
                    # group_id = wmo_group.pointer.wow_wmo_group.group_id
                    render_images(wmo_group.pointer, i)


        def render_images(obj, group_id):
            bpy.context.view_layer.objects.active = obj
            camera = bpy.data.cameras["MinimapsCamera"]
            # output_path = bpy.context.scene.render.filepath
            if not get_project_preferences().project_dir_path: # if project dir not set in settings, use blender's render path
                output_path = bpy.context.scene.render.filepath
            else:
                output_path = os.path.join(get_project_preferences().project_dir_path, r'textures\Minimap')

            # md5_text = ""
            md5_text = b''

            def set_render_resolution(res):
                if res == 128:
                    camera.ortho_scale = 64
                elif res == 64:
                    camera.ortho_scale = 32
                elif res == 32:
                    camera.ortho_scale = 16
                else:
                    camera.ortho_scale = 128
                bpy.context.scene.render.resolution_x = res
                bpy.context.scene.render.resolution_y = res


            def position_camera(bounds, offset_x, offset_y):
                # Align bottom left corner of camera frame to bottom left corner of bounding box
                center_offset = 64
                if camera.ortho_scale == 64:
                    center_offset = 32
                elif camera.ortho_scale == 32:
                    center_offset = 16
                tile_offset_size = center_offset * 2
                tile_x = tile_offset_size * offset_x
                tile_y = tile_offset_size * offset_y

                cam_position = [(bounds[0] + center_offset + tile_x), (bounds[1] + center_offset + tile_y), (bounds[2])]
                bpy.data.objects["MinimapsCamera"].location = cam_position


            def add_md5_entry(offset_x, offset_y, md5_text):
                offset_name = str(offset_x).zfill(2) + '_' + str(offset_y).zfill(2)
                md5_a = md5_path + "_" + str(group_id).zfill(3) + '_' + offset_name + '.blp'
                md5_b = md5_ref + "_" + str(group_id).zfill(3) + '_' + offset_name + '.blp'
                # md5_text += md5_a + '\t' + md5_b + '\n'
                md5_text += md5_a.encode() + b'\t' + md5_b.encode() + b'\r\n'
                md5_entries.append(md5_text)

            def renderliquid(liquidobj):
                # create bmesh
                # bm = bmesh.new()
                # bm.from_object(liquidobj, bpy.context.evaluated_depsgraph_get())

                bm = liquidobj.copy()
                
                bpy.context.collection.objects.link(bm)
                bpy.context.view_layer.update()
                bpy.ops.object.mode_set(mode = 'OBJECT') 
                bpy.context.view_layer.objects.active = bm
                bpy.ops.object.mode_set(mode = 'EDIT')
    
                mesh = bm.data

                renderflag_layer = mesh.vertex_colors['flag_0']

                def comp_colors(color1, color2):
                    for i in range(3):
                        if color1[i] != color2[i]:
                            return False
                    return True

                blue = [0.0, 0.0, 1.0]
                for poly in mesh.polygons:
                    if comp_colors(renderflag_layer.data[poly.loop_indices[0]].color, blue):
                        poly.select = True

                # bpy.ops.object.mode_set(mode = 'EDIT')
                # bpy.ops.object.editmode_toggle()
                bpy.ops.mesh.delete(type='FACE')
                bpy.ops.object.mode_set(mode = 'OBJECT')
                bm.hide_render = False

                return bm

            
            def render(offset_x, offset_y):
                offset_name = str(offset_x).zfill(2) + '_' + str(offset_y).zfill(2)
                png_name = name + "_" + str(group_id).zfill(3) + '_' + offset_name + '.png'
                bpy.context.scene.render.filepath = output_path + '\\' + png_name

                obj.hide_render = False
                # titi liquids
                liquidobj = obj.wow_wmo_group.liquid_mesh
                if liquidobj:
                    bm = renderliquid(liquidobj)
                    
                bpy.ops.render.render(write_still=True)

                
                obj.hide_render = True
                if liquidobj:
                    # bm.free()
                    bpy.ops.object.delete() # should delete previosuly selected liquid copy
                
                bpy.context.scene.render.filepath = output_path

                # titi, attempt to covnert to blp using png2blp
                # minimaps format : DXTC, alphachannem 0 bit, header 1024, 1 mipmap
                # img = PNG2BLP().load(pngData, uint32_t pngSize)
                # blp = PNG2BLP().createBlpDxtInMemory(bool generateMipMaps, int dxtFormat, uint32_t& fileSize)

                # with open(output_path + '\\' + png_name, "rb") as f:
                #     
                #     print("test blp")
                #     # img = PNG2BLP().load(f, 256)
                #     pngbytes = f.read()
# # 
                #     # print(img)  World\wmo\Dungeon\AZ_Deadmines\AZ_Deadmines_A.wmo
# 
                #     # blpdata = PNG2BLP(pngbytes, 256).createBlpDxtInMemory(True, 1, 256)
                #     blpdata = PNG2BLP(pngbytes, len(pngbytes)).create_blp_paletted_in_memory(True, 1)
# 
                #     print(blpdata)
# 
                #     with open(output_path + '\\' + name + "_" + str(group_id).zfill(3) + '_' + offset_name + '.blp', "wb") as blp:
                #         blp.write(blpdata)

                # write blp file


            # Get necessary bounding box values
            bounds = [v[:] for v in obj.bound_box]
            bounds_size_x = abs(bounds[0][0] - bounds[4][0])
            bounds_size_y = abs(bounds[0][1] - bounds[3][1])

            if bounds_size_x <= 16 and bounds_size_y <= 16:
                set_render_resolution(32)
            elif bounds_size_x and bounds_size_y <= 32:
                set_render_resolution(64)
            elif bounds_size_x and bounds_size_y <= 64:
                set_render_resolution(128)
            else:
                set_render_resolution(256)


            tiles_x = int(bounds_size_x / 128) + 1
            tiles_y = int(bounds_size_y / 128) + 1
            for offset_x in range(tiles_x):
                for offset_y in range(tiles_y):
                    position_camera(bounds[1], offset_x, offset_y)
                    render(offset_x, offset_y)
                    add_md5_entry(offset_x, offset_y, md5_text)


        def write_md5_entries(md5_file):
            # md5_output = ""
            # md5_output += "dir: " + os.path.dirname(md5_path) + '\n'
            md5_output = b''
            md5_output += b'dir: ' + os.path.dirname(md5_path).encode() + b'\r\n'


            for entry in md5_entries:
                md5_output += entry

            if not get_project_preferences().project_dir_path: # if project dir not set in settings, use blender's render path
                output_path = os.path.join(bpy.context.scene.render.filepath, r'md5translate.trs')
            else:
                output_path = os.path.join(get_project_preferences().project_dir_path, r'textures\Minimap\md5translate.trs')

            with open(output_path, "wb") as f:
                f.write(md5_file)
                f.write(md5_output)

        create_camera_object()
        set_mat_backface_culling()
        disable_object_wmo_render_visiblity()
        apply_render_settings()
        iterate_groups()
        write_md5_entries(md5_file)

        return {'FINISHED'}