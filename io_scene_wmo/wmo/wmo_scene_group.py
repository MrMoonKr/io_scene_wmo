import bpy
import mathutils
import bmesh
import sys
import inspect

from math import pi, ceil, floor, isclose
from logging import exception
from typing import Tuple

from ..pywowlib.file_formats.wmo_format_root import MOHDFlags, PortalRelation
from ..pywowlib.file_formats.wmo_format_group import MOGPFlags, LiquidVertex
from ..pywowlib.wmo_file import WMOGroupFile
from .bsp_tree import *
from .bl_render import BlenderWMOObjectRenderFlags
from ..pywowlib import WoWVersionManager, WoWVersions
from ..wbs_kernel.wmo_utils import CWMOGeometryBatcher, WMOGeometryBatcherMeshParams


class BlenderWMOSceneGroup:
    def __init__(self, wmo_scene, wmo_group, obj=None):
        self.wmo_group: WMOGroupFile = wmo_group
        self.wmo_scene: 'BlenderWMOSceneGroup' = wmo_scene
        self.bl_object: bpy.types.Object = obj
        self.name = wmo_scene.wmo.mogn.get_string(wmo_group.mogp.group_name_ofs)
        self.has_blending: bool = False

    @staticmethod
    def get_avg(list_):
        """ Get single average normal vector from a split normal """
        normal = [0.0, 0.0, 0.0]

        for n in list_:
            for i in range(0, 3):
                normal[i] += n[i]

        for i in range(0, 3):
            normal[i] /= len(list_)

        return normal

    @staticmethod
    def comp_colors(color1, color2):
        """ Compare two colors """

        for i in range(3):
            if color1[i] != color2[i]:
                return False
        return True

    @staticmethod
    def comp_colors_key(color1):
        for i in range(len(color1)):
            if color1[i] > 0:
                return True
        return False

    @staticmethod
    def get_batch_type(b_face, batch_map_trans, batch_map_int):
        """ Find which MOBA batch type a passed bmesh face belongs two """

        if not batch_map_trans and not batch_map_int:
            return 2

        trans_count = 0
        int_count = 0

        n_verts = len(b_face.loops)

        for loop in b_face.loops:
            if batch_map_trans and BlenderWMOSceneGroup.comp_colors_key(loop[batch_map_trans]):
                trans_count += 1

            if batch_map_int and BlenderWMOSceneGroup.comp_colors_key(loop[batch_map_int]):
                int_count += 1

        if trans_count == n_verts:
            return 0
        elif int_count == n_verts:
            return 1
        else:
            return 2

    @staticmethod
    def get_material_viewport_image(material):
        """ Get viewport image assigned to a material """

        if material.wow_wmo_material.diff_texture_1:
            return material.wow_wmo_material.diff_texture_1

    @staticmethod
    def get_linked_faces(b_face, face_batch_type, uv, uv2, batch_map_trans, batch_map_int, stack=len(inspect.stack())):
        # check if face was already processed
        if b_face.tag:
            return []

        f_linked = [b_face]
        mat_idx = b_face.material_index
        b_face.tag = True

        # Select edges that link two faces
        for link_edge in b_face.edges:
            # check if edge is shared with another face
            if not len(link_edge.link_faces) == 2:
                continue

            # prevent recursion stack overflow
            if stack >= sys.getrecursionlimit() - 1:
                break

            for link_face in link_edge.link_faces:
                # check if face was already processed and if it shares the same material
                if link_face.tag or link_face.material_index != mat_idx:
                    continue

                # check if face is located within same UV island.
                linked_uvs = 0
                for loop in b_face.loops:

                    for l_loop in loop.vert.link_loops:
                        if l_loop.face is link_face:
                            if isclose(l_loop[uv].uv[0], loop[uv].uv[0]) and isclose(l_loop[uv].uv[1], loop[uv].uv[1]):
                                linked_uvs += 1
                            if uv2 and isclose(l_loop[uv2].uv[0], loop[uv2].uv[0]) and isclose(l_loop[uv2].uv[1],
                                                                                               loop[uv2].uv[1]):
                                linked_uvs += 1

                if (not uv2 and linked_uvs < 2) or (uv2 and linked_uvs < 4):
                    continue

                # check if face is located within the same batch
                batch_type = BlenderWMOSceneGroup.get_batch_type(link_face, batch_map_trans, batch_map_int)

                if batch_type != face_batch_type:
                    continue

                # call this function recursively on this face if all checks are passed
                f_linked.extend(BlenderWMOSceneGroup.get_linked_faces(link_face, batch_type, uv, uv2, batch_map_trans,
                                                                      batch_map_int, stack=stack + 1))

        return f_linked

    def from_wmo_liquid_type(self, basic_liquid_type):
        """ Convert simplified WMO liquid type IDs to real LiquidType.dbc IDs """
        real_liquid_type = 0

        if basic_liquid_type < 20:
            if basic_liquid_type == 0:
                real_liquid_type = 14 if self.wmo_group.mogp.flags & 0x80000 else 13
            elif basic_liquid_type == 1:
                real_liquid_type = 14
            elif basic_liquid_type == 2:
                real_liquid_type = 19
            elif basic_liquid_type == 15:
                real_liquid_type = 17
            elif basic_liquid_type == 3:
                real_liquid_type = 20
        else:
            real_liquid_type = basic_liquid_type + 1

        return real_liquid_type

    def get_legacy_water_type(self, liquid_type):
        # Copied 1:1 from blizzard's decompiled code...
        liquid_type += 1
        if (liquid_type - 1) <= 0x13:
            newwater = (liquid_type - 1) & 3
            if newwater == 1:
                liquid_type = 14
                return liquid_type

            if newwater >= 1:
                if newwater == 2:
                    liquid_type = 19
                elif newwater == 3:
                    liquid_type = 20

                return liquid_type

            liquid_type = 13

        return liquid_type

    # return array of vertices and array of faces in a tuple
    def load_liquids(self, group_name, pos):
        """ Load liquid plane of the WMO group. Should only be called if MLIQ is present. """

        group = self.wmo_group

        # load vertices
        vertices = []
        for y in range(0, group.mliq.y_verts):
            y_pos = group.mliq.position[1] + y * 4.1666625
            for x in range(0, group.mliq.x_verts):
                x_pos = group.mliq.position[0] + x * 4.1666625
                vertices.append((x_pos, y_pos, group.mliq.vertex_map[y * group.mliq.x_verts + x].height))

        # calculate faces
        indices = []
        for y in range(group.mliq.y_tiles):
            for x in range(group.mliq.x_tiles):
                indices.append(y * group.mliq.x_verts + x)
                indices.append(y * group.mliq.x_verts + x + 1)
                indices.append((y + 1) * group.mliq.x_verts + x)
                indices.append((y + 1) * group.mliq.x_verts + x + 1)

        faces = []

        for i in range(0, len(indices), 4):
            faces.append((indices[i], indices[i + 1], indices[i + 3], indices[i + 2]))

        # create mesh and object
        name = group_name + "_Liquid"
        mesh = bpy.data.meshes.new(name)
        obj = bpy.data.objects.new(name, mesh)

        # create mesh from python data
        mesh.from_pydata(vertices, [], faces)
        mesh.update(calc_edges=True)
        mesh.validate()
        
        render_state_list = []
        
        # load legacy liquid type (vanilla/bc models) and render state from MLIQ tiles flags
        legacy_liquid_type = 0
        for poly in mesh.polygons:
            bit = 1
            tile_flags = 0
            while bit <= 0x8:
                tile_flag = group.mliq.tile_flags[poly.index]
                if tile_flag & bit:
                    tile_flags += bit
                bit <<= 1
            if tile_flags != 15:  # 15 = don't render/no liquid, ignore those tiles
                # and get the flags from the first non 15 tile.
                legacy_liquid_type = tile_flags
                # break
                render_state = True
            else:
                render_state = False

            render_state_list.append(render_state)

        # getting Liquid Type ID
        if self.wmo_scene.wmo.mohd.flags & 0x4:
            real_liquid_type = group.mogp.liquid_type
        else:
            real_liquid_type = self.get_legacy_water_type(legacy_liquid_type)
            # real_liquid_type = self.from_wmo_liquid_type(group.mogp.liquid_type)

        # create uv map if liquid is lava or slime
        if real_liquid_type in {3, 4, 7, 8, 11, 12, 15, 19, 20, 21, 121, 141}:
            uv_map = {}

            for vertex in mesh.vertices:
                uv_map[vertex.index] = (group.mliq.vertex_map[vertex.index].u,
                                        group.mliq.vertex_map[vertex.index].v)

            mesh.uv_layers.new(name="UVMap")
            uv_layer1 = mesh.uv_layers[0]

            for poly in mesh.polygons:
                for loop_index in poly.loop_indices:
                    uv_layer1.data[loop_index].uv = (uv_map.get(mesh.loops[loop_index].vertex_index)[0] / 255,
                                                     - uv_map.get(mesh.loops[loop_index].vertex_index)[1] / 255)

        # setting flags in a hacky way using vertex colors
        bit = 1
        counter = 0
        while bit <= 0x80:
            # if bit == 0x8: # hackfix to make layer 4 the vertex layer used by the WMO shader
            #     vc_layer = mesh.vertex_colors.new(name="Col")
            # else:
            #     vc_layer = mesh.vertex_colors.new(name="flag_" + str(counter))
            vc_layer = mesh.vertex_colors.new(name="flag_" + str(counter))
            counter += 1

            if bit <= 0x8:
                bit <<= 1
                continue # ignore legacy liquid type flags
            for poly in mesh.polygons:
                tile_flag = group.mliq.tile_flags[poly.index]
                for loop in poly.loop_indices:
                    if tile_flag & bit:
                        vc_layer.data[loop].color = (0, 0, 255, 255)
                    else:
                        vc_layer.data[loop].color = (255, 255, 255, 255)
            bit <<= 1

        # legacy liquid flags, if "no render", set all 4, else set none.
        # Cleanup blizzlike data to make flag 4 the "no render flag" used by the liquid flag editor.
        for i, poly in enumerate(mesh.polygons):
            render_state = render_state_list[i]

            bit = 1
            counter = 0
            while bit <= 0x8:
                vc_layer = mesh.vertex_colors["flag_{}".format(counter)]
                for loop in poly.loop_indices:
                    if not render_state:
                        vc_layer.data[loop].color = (0, 0, 255, 255)
                    else:
                        vc_layer.data[loop].color = (255, 255, 255, 255)
                bit <<= 1
                counter += 1

        # assign WMO liquid material
        liquid_material = self.wmo_scene.bl_materials[group.mliq.material_id]   
        mesh.materials.append(liquid_material)

        # assign ghost material to unrendered tiles
        mat_ghost = bpy.data.materials.get("WowMaterial_ghost_Liquid")
        if mat_ghost is None:
            mat_ghost = bpy.data.materials.new("WowMaterial_ghost_Liquid")
            mat_ghost.blend_method = 'BLEND'
            mat_ghost.use_nodes = True
            mat_ghost.node_tree.nodes.remove(mat_ghost.node_tree.nodes.get('Principled BSDF'))
            material_output = mat_ghost.node_tree.nodes.get('Material Output')
            transparent = mat_ghost.node_tree.nodes.new('ShaderNodeBsdfTransparent')
            mat_ghost.node_tree.links.new(material_output.inputs[0], transparent.outputs[0])
            mat_ghost.node_tree.nodes["Transparent BSDF"].inputs[0].default_value = (1, 1, 1, 1)
        mesh.materials.append(mat_ghost)

        # create a material for blender rendering
        liquid_render_mat = bpy.data.materials.new("WowMaterial_" + name)
        liquid_render_mat.blend_method = 'BLEND'
        liquid_render_mat.use_nodes = True
        liquid_render_mat.node_tree.nodes.remove(liquid_render_mat.node_tree.nodes.get('Principled BSDF'))
        material_output = liquid_render_mat.node_tree.nodes.get('Material Output')
        # transparent = liquid_render_mat.node_tree.nodes.new('ShaderNodeBsdfTransparent')
        transparent = liquid_render_mat.node_tree.nodes.new('ShaderNodeBsdfDiffuse') # diffuse looks better ?
        liquid_render_mat.node_tree.links.new(material_output.inputs[0], transparent.outputs[0])

        if real_liquid_type in {3, 7, 11, 15, 19, 121, 141}:# lava
            material_color = (1, 0.1, 0.0, 1.0) # orange
        elif real_liquid_type in {4, 8, 12, 20, 21}: # slime
            material_color = (0.06274, 0.77647, 0.0, 1.0) # green
        else:
            material_color = self.wmo_scene.bl_materials[group.mliq.material_id].wow_wmo_material.diff_color

        # liquid_render_mat.node_tree.nodes["Transparent BSDF"].inputs[0].default_value = material_color
        liquid_render_mat.node_tree.nodes["Diffuse BSDF"].inputs[0].default_value = material_color
        mesh.materials.append(liquid_render_mat)

        for poly in mesh.polygons:
            tile_flag = group.mliq.tile_flags[poly.index]
            if tile_flag & 0x1 and tile_flag & 0x2 and tile_flag & 0x4 and tile_flag & 0x8:
                poly.material_index = 1 # assign ghost_material to non rendered tiles
            else:
                # if group.mogp.liquid_type in {3, 4, 7, 8, 11, 12, 15, 19, 20, 21, 121, 141}:
                #     poly.material_index = 0
                # else:
                #     poly.material_index = 2
                poly.material_index = 2

        # set mesh location
        obj.location = pos

        scn = bpy.context.scene
        liquid_collection = bpy.data.collections.get("Collision")
        if not liquid_collection:
            liquid_collection = bpy.data.collections.new("Collision")
            scn.collection.children.link(liquid_collection)

        liquid_collection.objects.link(obj)

        bpy.context.view_layer.objects.active = obj

        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.normals_make_consistent(inside=True)
        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.object.mode_set(mode='OBJECT')

        obj.lock_scale = [True, True, True]
        obj.lock_rotation[2] = True

        obj.wow_wmo_liquid.enabled = True


        obj.wow_wmo_liquid.color = self.wmo_scene.bl_materials[group.mliq.material_id].wow_wmo_material.diff_color

        wmo_group_obj = bpy.context.scene.objects[group_name]
        wmo_group_obj.wow_wmo_group.liquid_type = str(real_liquid_type)
        wmo_group_obj.wow_wmo_group.liquid_mesh = obj

    # Return faces indices
    def get_bsp_node_indices(self, i_node, nodes, faces, indices):
        """ Get indices of a WMO BSP tree nodes """
        # last node in branch
        node_indices = []
        if nodes[i_node].plane_type & BSPPlaneType.Leaf:
            for i in range(nodes[i_node].first_face, nodes[i_node].first_face + nodes[i_node].num_faces):
                node_indices.append(faces[i])

        if nodes[i_node].children[0] != -1:
            node_indices.extend(self.get_bsp_node_indices(nodes[i_node].children[0], nodes, faces, indices))

        if nodes[i_node].children[1] != -1:
            node_indices.extend(self.get_bsp_node_indices(nodes[i_node].children[1], nodes, faces, indices))

        return node_indices

    def get_collision_indices(self):
        """ Get indices of a WMO BSP tree nodes that have collision """

        group = self.wmo_group
        node_indices = self.get_bsp_node_indices(0, group.mobn.nodes, group.mobr.faces, group.movi.indices)
        indices = []
        for i in node_indices:
            if not group.mopy.triangle_materials[i].flags & 0x04:
                indices.append(group.movi.indices[i * 3])
                indices.append(group.movi.indices[i * 3 + 1])
                indices.append(group.movi.indices[i * 3 + 2])

        return indices

    def load_object(self):
        """ Load WoW WMO group as an object to the Blender scene """

        group = self.wmo_group

        vertices = group.movt.vertices
        normals = group.monr.normals
        tex_coords = group.motv.tex_coords
        faces = [group.movi.indices[i:i + 3] for i in range(0, len(group.movi.indices), 3)]

        # create mesh
        mesh = bpy.data.meshes.new(self.name)
        mesh.from_pydata(vertices, [], faces)

        # create object
        scn = bpy.context.scene

        nobj = bpy.data.objects.new(self.name, mesh)

        collision_face_ids = []
        for i, poly in enumerate(mesh.polygons):
            poly.use_smooth = True

            if group.mopy.triangle_materials[i].material_id == 0xFF:
                collision_face_ids.append(i)

        # set normals
        for i in range(len(normals)):
            mesh.vertices[i].normal = normals[i]

        custom_normals = [(0.0, 0.0, 0.0)] * len(mesh.loops)
        mesh.use_auto_smooth = True
        for i, loop in enumerate(mesh.loops):
            mesh.vertices[loop.vertex_index].normal = normals[loop.vertex_index]
            custom_normals[i] = normals[loop.vertex_index]

        mesh.normals_split_custom_set(custom_normals)

        pass_index = 0

        # set vertex color
        vertex_color_layer = None
        if group.mogp.flags & MOGPFlags.HasVertexColor:
            flag_set = nobj.wow_wmo_group.flags
            flag_set.add('0')
            nobj.wow_wmo_group.flags = flag_set
            vertex_color_layer = mesh.vertex_colors.new(name="Col")
            mesh.vertex_colors.new(name="Lightmap")

            pass_index |= BlenderWMOObjectRenderFlags.HasVertexColor
            pass_index |= BlenderWMOObjectRenderFlags.HasLightmap

        blendmap = None
        if group.mogp.flags & MOGPFlags.HasTwoMOCV:
            blendmap = mesh.vertex_colors.new(name="Blendmap")

            pass_index |= BlenderWMOObjectRenderFlags.HasBlendmap

        # set uv
        mesh.uv_layers.new(name="UVMap")
        uv_layer1 = mesh.uv_layers[0]

        for i, uv_loop in enumerate(uv_layer1.data):
            uv = tex_coords[mesh.loops[i].vertex_index]
            uv_layer1.data[i].uv = (uv[0], 1 - uv[1])

        if group.mogp.flags & MOGPFlags.HasTwoMOTV:
            uv2 = mesh.uv_layers.new(name="UVMap.001")
            nobj.wow_wmo_vertex_info.second_uv = uv2.name
            uv_layer2 = mesh.uv_layers[1]

            for i, uv_loop in enumerate(uv_layer2.data):
                uv = group.motv2.tex_coords[mesh.loops[i].vertex_index]
                uv_loop.uv = (uv[0], 1 - uv[1])

        # map wmo material ID to index in mesh materials
        material_indices = {}
        material_viewport_textures = {}

        # create batch vertex groups

        batch_map_a = None
        batch_map_b = None

        if group.mogp.n_batches_a != 0:
            batch_map_a = mesh.vertex_colors.new(name="BatchmapTrans")
            pass_index |= BlenderWMOObjectRenderFlags.HasBatchA

        if group.mogp.n_batches_b != 0:
            batch_map_b = mesh.vertex_colors.new(name="BatchmapInt")
            pass_index |= BlenderWMOObjectRenderFlags.HasBatchB

        # nobj.wow_wmo_vertex_info.batch_map = batch_map.name

        batch_material_map = {}

        batch_a_range = range(0, group.moba.batches[group.mogp.n_batches_a - 1].last_vertex + 1
        if group.mogp.n_batches_a else 0)

        batch_b_range = range(len(batch_a_range) - 1,
                              group.moba.batches[group.mogp.n_batches_a + group.mogp.n_batches_b - 1].last_vertex + 1
                              if group.mogp.n_batches_b else len(batch_a_range) - 1)

        # add materials
        for i, batch in enumerate(group.moba.batches):

            material = self.wmo_scene.bl_materials[group.moba.batches[i].material_id]

            mat_index_local = material_indices.get(batch.material_id)

            if mat_index_local is None:
                mat_id = len(mesh.materials)
                material_indices[batch.material_id] = mat_id

                image = self.get_material_viewport_image(material)
                material_viewport_textures[mat_id] = image
                mesh.materials.append(material)
                mat_index_local = mat_id

            for poly in mesh.polygons[batch.start_triangle // 3: (batch.start_triangle + batch.n_triangles) // 3]:

                poly.material_index = mat_index_local

            batch_material_map[(batch.start_triangle // 3,
                                (batch.start_triangle + group.moba.batches[i].n_triangles) // 3)] = batch.material_id

        # set layer data
        for i, loop in enumerate(mesh.loops):

            if vertex_color_layer is not None:
                mesh.vertex_colors['Col'].data[i].color = (group.mocv.vert_colors[loop.vertex_index][2] / 255,
                                                           group.mocv.vert_colors[loop.vertex_index][1] / 255,
                                                           group.mocv.vert_colors[loop.vertex_index][0] / 255,
                                                           1.0)

                mesh.vertex_colors['Lightmap'].data[i].color = (group.mocv.vert_colors[loop.vertex_index][3] / 255,
                                                                group.mocv.vert_colors[loop.vertex_index][3] / 255,
                                                                group.mocv.vert_colors[loop.vertex_index][3] / 255,
                                                                1.0)

            if blendmap is not None:
                mocv_layer = group.mocv2 if group.mogp.flags & MOGPFlags.HasVertexColor else group.mocv
                mesh.vertex_colors['Blendmap'].data[i].color = (mocv_layer.vert_colors[loop.vertex_index][3] / 255,
                                                                mocv_layer.vert_colors[loop.vertex_index][3] / 255,
                                                                mocv_layer.vert_colors[loop.vertex_index][3] / 255,
                                                                1.0)

            if batch_map_a:
                mesh.vertex_colors['BatchmapTrans'].data[i].color = (1, 1, 1, 1) if loop.vertex_index in batch_a_range \
                    else (0, 0, 0, 0)

            if batch_map_b:
                mesh.vertex_colors['BatchmapInt'].data[i].color = (1, 1, 1, 1) if loop.vertex_index in batch_b_range \
                    else (0, 0, 0, 0)
        '''
        # set faces material
        for i in range(len(mesh.polygons)):
            mat_id = group.mopy.triangle_materials[i].material_id
 
            mesh.polygons[i].material_index = material_indices[mat_id]
 
            # set texture displayed in viewport
            img = material_viewport_textures[material_indices[mat_id]]
            if img is not None:
                uv1.data[i].image = img
 
        '''

        # DEBUG BSP
        """for iNode in range(len(group.mobn.Nodes)):
            bsp_node_indices = group.GetBSPNodeIndices(iNode, group.mobn.Nodes, group.mobr.Faces, group.movi.Indices)
            bsp_node_vg = nobj.vertex_groups.new("debug_bsp")
 
            #for i in bsp_n1_indices:
            #    bsp_n1_GroupIndices.append(i)
 
            bsp_node_vg.add(bsp_node_indices, 1.0, 'ADD')"""
        # DEBUG BSP

        # add collision vertex group
        collision_indices = self.get_collision_indices()

        if collision_indices:
            collision_vg = nobj.vertex_groups.new(name="Collision")
            collision_vg.add(collision_indices, 1.0, 'ADD')
            nobj.wow_wmo_vertex_info.vertex_group = collision_vg.name

        # add WMO group properties
        nobj.wow_wmo_group.enabled = True
        nobj.wow_wmo_group.description = self.wmo_scene.wmo.mogn.get_string(group.mogp.desc_group_name_ofs)
        nobj.wow_wmo_group.group_dbc_id = int(group.mogp.group_id)

        nobj.wow_wmo_group.fog1 = self.wmo_scene.bl_fogs[group.mogp.fog_indices[0]]
        nobj.wow_wmo_group.fog2 = self.wmo_scene.bl_fogs[group.mogp.fog_indices[1]]
        nobj.wow_wmo_group.fog3 = self.wmo_scene.bl_fogs[group.mogp.fog_indices[2]]
        nobj.wow_wmo_group.fog4 = self.wmo_scene.bl_fogs[group.mogp.fog_indices[3]]

        if group.mogp.flags & MOGPFlags.Indoor:
            nobj.wow_wmo_group.place_type = str(0x2000)
            pass_index |= BlenderWMOObjectRenderFlags.IsIndoor
        else:
            nobj.wow_wmo_group.place_type = str(0x8)
            pass_index |= BlenderWMOObjectRenderFlags.IsOutdoor

        flag_set = nobj.wow_wmo_group.flags

        if group.mogp.flags & MOGPFlags.DoNotUseLocalLighting:
            flag_set.add('1')
            pass_index |= BlenderWMOObjectRenderFlags.NoLocalLight

        if group.mogp.flags & MOGPFlags.AlwaysDraw:
            flag_set.add('2')

        if group.mogp.flags & MOGPFlags.IsMountAllowed:
            flag_set.add('3')

        if group.mogp.flags & MOGPFlags.HasSkybox:
            flag_set.add('4')

        nobj.wow_wmo_group.flags = flag_set
        nobj.pass_index = pass_index

        # move objects to collection

        wmo_outdoor_collection = bpy.data.collections.get("Outdoor")
        if not wmo_outdoor_collection:
            wmo_outdoor_collection = bpy.data.collections.new("Outdoor")
            scn.collection.children.link(wmo_outdoor_collection)

        wmo_indoor_collection = bpy.data.collections.get("Indoor")
        if not wmo_indoor_collection:
            wmo_indoor_collection = bpy.data.collections.new("Indoor")
            scn.collection.children.link(wmo_indoor_collection)

        if nobj.wow_wmo_group.place_type == '8':
            wmo_outdoor_collection.objects.link(nobj)

        if nobj.wow_wmo_group.place_type == '8192':
            wmo_indoor_collection.objects.link(nobj)

        # remove collision faces from mesh
        if collision_face_ids:

            bm_col = bmesh.new()

            bm = bmesh.new()
            bm.from_mesh(mesh)

            bm.faces.ensure_lookup_table()
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm_collision_faces = [bm.faces[i] for i in collision_face_ids]

            # create collision mesh
            vert_map = {}
            for face in bm_collision_faces:
                face_verts = [None, None, None]
                for j, vert in enumerate(face.verts):

                    n_vert = vert_map.get(vert.index)
                    if not n_vert:
                        n_vert = bm_col.verts.new(vert.co)
                        vert_map[vert.index] = n_vert

                    face_verts[j] = n_vert

                try:
                    bm_col.faces.new(face_verts)
                except ValueError:
                    pass
                    # print('\nWARNING: Duplicated face was removed from collision geometry.')

            c_mesh = bpy.data.meshes.new(name=self.name + '_Collision')
            bm_col.to_mesh(c_mesh)
            bm_col.free()

            # remove collision faces from original mesh
            bmesh.ops.delete(bm, geom=bm_collision_faces, context='FACES')
            bm.to_mesh(mesh)
            mesh.update()
            bpy.context.view_layer.update()
            bm.free()

            c_obj = bpy.data.objects.new(c_mesh.name, c_mesh)
            nobj.wow_wmo_group.collision_mesh = c_obj
            c_obj.wow_wmo_collision_rel = nobj

            collision_collection = bpy.data.collections.get("Collision")
            if not collision_collection:
                collision_collection = bpy.data.collections.new("Collision")
                scn.collection.children.link(collision_collection)

            collision_collection.objects.link(c_obj)

        # assign ghost material
        if nobj.wow_wmo_group.collision_mesh:
            mat = bpy.data.materials.get("WowMaterial_ghost")
            nobj.wow_wmo_group.collision_mesh.data.materials.append(mat)

        # handle liquids
        if group.mogp.flags & MOGPFlags.HasWater:
            self.load_liquids(nobj.name, nobj.location)

        else:
            # getting Liquid Type ID

            if self.wmo_scene.wmo.mohd.flags & MOHDFlags.UseLiquidTypeDBCId: 
                real_liquid_type = group.mogp.liquid_type
            else:
                real_liquid_type = self.from_wmo_liquid_type(group.mogp.liquid_type)
                real_liquid_type = 0 if real_liquid_type == 17 else real_liquid_type

            nobj.wow_wmo_group.liquid_type = str(real_liquid_type)

    @staticmethod
    def try_calculate_direction(group_obj: bpy.types.Object
                                , portal_obj: bpy.types.Object
                                , portal_bmesh: bmesh.types.BMesh
                                , bound_relation: PortalRelation):

        mesh = group_obj.data
        normal = portal_bmesh.faces[0].normal

        for poly in mesh.faces:
            poly_normal = mathutils.Vector(poly.normal)
            g_center = poly.calc_center_median() + poly_normal * sys.float_info.epsilon

            dist = normal[0] * g_center[0] + normal[1] * g_center[1] \
                   + normal[2] * g_center[2] - portal_bmesh.faces[0].normal[0] \
                   * portal_bmesh.verts[portal_bmesh.faces[0].verts[0]].co[0] \
                   - portal_bmesh.faces[0].normal[1] \
                   * portal_bmesh.verts[portal_bmesh.faces[0].verts[0]].co[1] \
                   - portal_bmesh.faces[0].normal[2] \
                   * portal_bmesh.verts[portal_bmesh.faces[0].verts[0]].co[2]

            if dist == 0:
                continue

            for portal_poly in portal_bmesh.faces:

                direction = portal_poly.calc_center_median() - g_center
                length = mathutils.Vector(direction).length
                direction.normalize()

                angle = mathutils.Vector(direction).angle(poly.normal, None)

                if angle is None or angle >= pi * 0.5:
                    continue

                ray_cast_result = bpy.context.scene.ray_cast(bpy.context.evaluated_depsgraph_get(), g_center,
                                                             direction)

                if not ray_cast_result[0] \
                        or ray_cast_result[4].name == portal_obj.name \
                        or mathutils.Vector(
                    (ray_cast_result[1][0] - g_center[0], ray_cast_result[1][1] - g_center[1],
                     ray_cast_result[1][2] - g_center[2])).length > length:
                    result = 1 if dist > 0 else -1

                    if bound_relation.side == 0:
                        bound_relation.side = -result

                    return result

        return 0

    def get_portal_direction(self
                             , portal_obj: bpy.types.Object
                             , portal_bmesh: bmesh.types.BMesh
                             , group_obj: bpy.types.Object):
        """ Get the direction of MOPR portal relation given a portal object and a target group """

        # check if this portal was already processed
        bound_relation_side = None
        bound_relation = None
        for relation in self.wmo_scene.wmo.mopr.relations:
            if relation.portal_index == portal_obj.wow_wmo_portal.portal_id:
                bound_relation_side = relation.side
                bound_relation = relation

        if bound_relation_side:
            return -bound_relation_side

        if portal_obj.wow_wmo_portal.algorithm != '0':
            return 1 if portal_obj.wow_wmo_portal.algorithm == '1' else -1

        result = BlenderWMOSceneGroup.try_calculate_direction(group_obj, portal_obj, portal_bmesh, bound_relation)

        if result:
            return result

        # triangulate the proxy portal bmesh
        bmesh.ops.triangulate(portal_bmesh, faces=portal_bmesh.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY')
        portal_bmesh.verts.ensure_lookup_table()
        portal_bmesh.faces.ensure_lookup_table()

        result = BlenderWMOSceneGroup.try_calculate_direction(group_obj, portal_obj, portal_bmesh, bound_relation)

        if result:
            return result

        if bound_relation_side is None:
            print("\nFailed to calculate direction for portal \"{}\". "
                  "Calculation from another side will be attempted.".format(portal_obj.name))
        else:
            print("\nFailed to calculate direction from the opposite side for portal \"{}\" "
                  "You may consider setting up the direction manually.".format(portal_obj.name))

        return 0

    def save_liquid(self, ob):

        group = self.wmo_group

        mesh = ob.data

        # apply mesh transformations
        active = bpy.context.view_layer.objects.active
        bpy.context.view_layer.objects.active = ob
        ob.select_set(True)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        ob.select_set(False)
        bpy.context.view_layer.objects.active = active

        start_vertex = 0
        sum = 0
        for vertex in mesh.vertices:
            cur_sum = vertex.co[0] + vertex.co[1]

            if cur_sum < sum:
                start_vertex = vertex.index
                sum = cur_sum

        group.mliq.x_tiles = round(ob.dimensions[0] / 4.1666625)
        group.mliq.y_tiles = round(ob.dimensions[1] / 4.1666625)
        group.mliq.x_verts = group.mliq.x_tiles + 1
        group.mliq.y_verts = group.mliq.y_tiles + 1
        group.mliq.position = mesh.vertices[start_vertex].co.to_tuple()

        group.mogp.flags |= MOGPFlags.HasWater # do we really need that?

        types_1 = {3, 7, 11, 15, 19, 121, 141} # lava
        types_2 = {4, 8, 12, 20, 21} # slime

        diff_color = (int(ob.wow_wmo_liquid.color[2] * 255),
                      int(ob.wow_wmo_liquid.color[1] * 255),
                      int(ob.wow_wmo_liquid.color[0] * 255),
                      int(ob.wow_wmo_liquid.color[3] * 255)
                     )

        try:
            if not mesh.materials[0].wow_wmo_material.enabled:
                raise exception()
            group.mliq.material_id = bpy.context.scene.wow_wmo_root_elements.materials.find(
                    mesh.materials[0].name)
        except: # if no mat or if the mat isn't a wmo mat, create a new one
            texture1 = "DUNGEONS\\TEXTURES\\STORMWIND\\GRAY12.BLP"

            if group.mogp.liquid_type in types_1:
                texture1 = "DUNGEONS\\TEXTURES\\METAL\\BM_BRSPIRE_CATWALK01.BLP"

            elif group.mogp.liquid_type in types_2:
                texture1 = "DUNGEONS\\TEXTURES\\FLOOR\\JLO_UNDEADZIGG_SLIMEFLOOR.BLP"

            group.mliq.material_id = self.wmo_scene.wmo.add_material(texture1, diff_color=diff_color)

        if group.mogp.liquid_type in types_1 or group.mogp.liquid_type in types_2:

            if mesh.uv_layers.active:

                uv_map = {}

                for poly in mesh.polygons:
                    for loop_index in poly.loop_indices:
                        if mesh.loops[loop_index].vertex_index not in uv_map:
                            uv_map[mesh.loops[loop_index].vertex_index] = mesh.uv_layers.active.data[loop_index].uv

                for i in range(group.mliq.x_verts * group.mliq.y_verts):
                    vertex = LiquidVertex()
                    vertex.is_water = False
                    group.mliq.is_water = False

                    vertex.u = int(uv_map.get(mesh.vertices[i].index)[0] * 255)
                    vertex.v = int(uv_map.get(mesh.vertices[i].index)[1] * 255)

                    vertex.height = (ob.matrix_world @ mesh.vertices[i].co)[2]
                    group.mliq.vertex_map.append(vertex)
            else:
                raise Exception("\nError saving WMO. Slime and magma (lava) liquids require a UV map to be created.")

        else:

            for j in range(group.mliq.x_verts * group.mliq.y_verts):
                vertex = LiquidVertex()

                vertex.height = mesh.vertices[j].co[2]
                group.mliq.vertex_map.append(vertex)

        for poly in mesh.polygons:
            tile_flag = 0
            blue = [0.0, 0.0, 1.0]

            counter = 0
            bit = 1
            not_rendered = False
            while bit <= 0x80:
                vc_layer = mesh.vertex_colors["flag_{}".format(counter)]
                
                if bit == 0x1:
                    if self.comp_colors(vc_layer.data[poly.loop_indices[0]].color, blue):
                        not_rendered = True

                if bit <= 0x8: # legacy/no render tile flags : set not rendered from layer 0
                    if not_rendered:
                        tile_flag |= bit
                    # TODO : For vanilla/BC, set liquid type flags here
                else:
                    if self.comp_colors(vc_layer.data[poly.loop_indices[0]].color, blue):
                        tile_flag |= bit

                bit <<= 1

                counter += 1

            group.mliq.tile_flags.append(tile_flag)

    def create_batching_parameters(self) -> Tuple[bpy.types.Mesh, WMOGeometryBatcherMeshParams]:
        """ Prepare the WoW WMO group proxy mesh for export.
            Mesh is returned in order to keep its lifetime beyond the function scope.
        """

        obj = self.bl_object
        depsgraph = bpy.context.evaluated_depsgraph_get()

        obj_eval = obj.evaluated_get(depsgraph)

        group = self.wmo_group
        scene = bpy.context.scene

        bpy.context.view_layer.objects.active = obj
        mesh = obj_eval.data

        if mesh.has_custom_normals:
            mesh.calc_normals_split()

        # create bmesh
        bm = bmesh.new()
        bm.from_mesh(mesh)

        # handle separate collision
        if obj.wow_wmo_group.collision_mesh:
            col_mesh_eval = obj.wow_wmo_group.collision_mesh.evaluated_get(depsgraph).data

            for poly in col_mesh_eval.polygons:
                poly.material_index = 32767

            bm.from_mesh(col_mesh_eval)
            bm.verts.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

        # triangulate bmesh
        bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY')

        vertices = bm.verts
        edges = bm.edges
        faces = bm.faces

        vertices.ensure_lookup_table()
        edges.ensure_lookup_table()
        faces.ensure_lookup_table()

        if not bm.loops.layers.uv.get('UVMap'):
            raise Exception('\nThe group \"{}\" must have a UV map layer.'.format(obj.name))

        self.has_blending = bm.loops.layers.uv.get('UVMap.001') and bm.loops.layers.color.get('Blendmap')
        if self.has_blending:
            group.add_blendmap_chunks()

        mesh_final = bpy.data.meshes.new("Temp")
        bm.to_mesh(mesh_final)
        mesh_final.calc_normals()
        bm.free()

        use_vertex_color = '0' in obj.wow_wmo_group.flags \
                           or (obj.wow_wmo_group.place_type == '8192' and '1' not in obj.wow_wmo_group.flags)

        vg_collision_index = -1

        if obj.wow_wmo_vertex_info.vertex_group:
            obj_collision_vg = obj.vertex_groups.get(obj.wow_wmo_vertex_info.vertex_group)

            if obj_collision_vg:
                vg_collision_index = obj_collision_vg.index

        material_mapping = []

        for material in mesh.materials:
            mat_id = scene.wow_wmo_root_elements.materials.find(material.name)

            if mat_id < 0:
                raise Exception('Error: Assigned material \"{}\" is not registered as WoW Material.'.format(
                    material.name))

            material_mapping.append(mat_id)

        return mesh_final, WMOGeometryBatcherMeshParams(mesh_final.as_pointer()
                                                        , False
                                                        , use_vertex_color
                                                        , vg_collision_index
                                                        , obj.wow_wmo_vertex_info.node_size
                                                        , material_mapping)

    def save(self, batcher: CWMOGeometryBatcher, group_index: int):
        """ Save WoW WMO group data for future export """
        obj = self.bl_object

        self.wmo_group.movt.from_bytes(batcher.vertices(group_index))
        self.wmo_group.monr.from_bytes(batcher.normals(group_index))
        self.wmo_group.moba.from_bytes(batcher.batches(group_index))
        self.wmo_group.movi.from_bytes(batcher.triangle_indices(group_index))
        self.wmo_group.mopy.from_bytes(batcher.triangle_materials(group_index))
        self.wmo_group.motv.from_bytes(batcher.tex_coords(group_index))
        self.wmo_group.mocv.from_bytes(batcher.vertex_colors(group_index))
        self.wmo_group.mobn.from_bytes(batcher.bsp_nodes(group_index))
        self.wmo_group.mobr.from_bytes(batcher.bsp_faces(group_index))

        if self.has_blending:
            self.wmo_group.motv2.from_bytes(batcher.tex_coords2(group_index))
            self.wmo_group.mocv2.from_bytes(batcher.vertex_colors2(group_index))

        # bsp = BSPTree()
        # bsp.generate_bsp(self.wmo_group.movt.vertices, self.wmo_group.movi.indices, obj.wow_wmo_vertex_info.node_size)

        # write header
        bb = batcher.bounding_box(group_index)
        self.wmo_group.mogp.bounding_box_corner1 = bb.min
        self.wmo_group.mogp.bounding_box_corner2 = bb.max

        '''
        if len(group.movt.vertices) > 65535:
            raise Exception('\nThe group \"{}\" has too many vertices : {} (max allowed = 65535)'.format(
                obj.name, str(len(group.movt.vertices))))
                
        '''

        batch_count_info = batcher.batch_count_info(group_index)
        self.wmo_group.mogp.n_batches_a = batch_count_info.n_batches_trans
        self.wmo_group.mogp.n_batches_b = batch_count_info.n_batches_int
        self.wmo_group.mogp.n_batches_c = batch_count_info.n_batches_ext

        self.wmo_group.mogp.flags |= MOGPFlags.HasCollision  # /!\ MUST HAVE 0x1 FLAG ELSE THE GAME CRASH !
        if '0' in obj.wow_wmo_group.flags:
            self.wmo_group.mogp.flags |= MOGPFlags.HasVertexColor
        if '4' in obj.wow_wmo_group.flags:
            self.wmo_group.mogp.flags |= MOGPFlags.HasSkybox
        if '1' in obj.wow_wmo_group.flags:
            self.wmo_group.mogp.flags |= MOGPFlags.DoNotUseLocalLighting
        if '2' in obj.wow_wmo_group.flags:
            self.wmo_group.mogp.flags |= MOGPFlags.AlwaysDraw
        if '3' in obj.wow_wmo_group.flags:
            self.wmo_group.mogp.flags |= MOGPFlags.IsMountAllowed

        self.wmo_group.mogp.flags |= int(obj.wow_wmo_group.place_type)

        if self.has_blending:
            self.wmo_group.mogp.flags |= MOGPFlags.HasTwoMOCV
            self.wmo_group.mogp.flags |= MOGPFlags.HasTwoMOTV

        has_lights = False

        fogs = (obj.wow_wmo_group.fog1,
                obj.wow_wmo_group.fog2,
                obj.wow_wmo_group.fog3,
                obj.wow_wmo_group.fog4)


        # set fog references
        self.wmo_group.mogp.fog_indices = (fogs[0].wow_wmo_fog.fog_id if fogs[0] else 0,
                                  fogs[1].wow_wmo_fog.fog_id if fogs[1] else 0,
                                  fogs[2].wow_wmo_fog.fog_id if fogs[2] else 0,
                                  fogs[3].wow_wmo_fog.fog_id if fogs[3] else 0)
        # save lamps
        lamps = obj.wow_wmo_group.relations.lights
        if lamps:
            has_lights = True
            for lamp in lamps:
                self.wmo_group.molr.light_refs.append(lamp.id)

        self.wmo_group.mogp.group_id = int(obj.wow_wmo_group.group_dbc_id)
        group_info = self.wmo_scene.add_group_info(self.wmo_group.mogp.flags,
                                                      [self.wmo_group.mogp.bounding_box_corner1
                                                      , self.wmo_group.mogp.bounding_box_corner2],
                                                  obj.name,
                                                  obj.wow_wmo_group.description)

        self.wmo_group.mogp.group_name_ofs = group_info[0]
        self.wmo_group.mogp.desc_group_name_ofs = group_info[1]

        if len(obj.wow_wmo_group.modr):
            for doodad in obj.wow_wmo_group.modr:
                self.wmo_group.modr.doodad_refs.append(doodad.value)
            self.wmo_group.mogp.flags |= MOGPFlags.HasDoodads
        elif obj.wow_wmo_group.relations.doodads:
            for doodad in obj.wow_wmo_group.relations.doodads:
                self.wmo_group.modr.doodad_refs.append(doodad.id)
            self.wmo_group.mogp.flags |= MOGPFlags.HasDoodads
        else:
            self.wmo_group.modr = None

        if '0' not in obj.wow_wmo_group.flags:
            if obj.wow_wmo_group.place_type == '8192':
                if '1' in obj.wow_wmo_group.flags \
                        and not len(obj.data.vertex_colors):
                    self.wmo_group.mocv = None
                else:
                    self.wmo_group.mogp.flags |= MOGPFlags.HasVertexColor
            else:
                self.wmo_group.mocv = None
        
        self.wmo_group.mogp.liquid_type = int(obj.wow_wmo_group.liquid_type)

        if obj.wow_wmo_group.liquid_mesh:
            self.save_liquid(obj.wow_wmo_group.liquid_mesh)
        else:
            self.wmo_group.mliq = None
            self.wmo_group.mogp.flags |= MOGPFlags.IsNotOcean  # TODO: check if this is necessary
            wow_version = int(bpy.context.scene.wow_scene.version)
            if wow_version >= WoWVersions.WOTLK:
                # this flag causes wmo groups to fill with liquid if liquid type is not 0.
                self.wmo_group.root.mohd.flags |= MOHDFlags.UseLiquidTypeDBCId

        if not has_lights:
            self.wmo_group.molr = None
        else:
            self.wmo_group.mogp.flags |= MOGPFlags.HasLight

        # write second MOTV and MOCV
        if not self.has_blending:
            self.wmo_group.motv2 = None
            self.wmo_group.mocv2 = None



