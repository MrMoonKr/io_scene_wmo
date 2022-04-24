import os
import re

from math import sqrt, isinf, asin, atan2, sin, cos
from functools import partial

import bpy
import ctypes
from mathutils import Vector

from .bl_render import update_m2_mat_node_tree
from ..render.m2.shaders import M2ShaderPermutations
from ..utils.misc import parse_bitfield, construct_bitfield, load_game_data
from ..utils.misc import resolve_texture_path, get_origin_position, get_objs_boundbox_world, get_obj_boundbox_center, \
    get_obj_radius
from .ui.enums import mesh_part_id_menu
from .ui.panels.camera import update_follow_path_constraints
from ..pywowlib.enums.m2_enums import M2SkinMeshPartID, M2AttachmentTypes, M2EventTokens, M2SequenceNames
from ..pywowlib.file_formats.wow_common_types import *
from ..pywowlib.file_formats.m2_format import *
from ..pywowlib.m2_file import M2File
from ..pywowlib.io_utils.types import vec3D

class BlenderM2Scene:
    """ This class is used for assembling a Blender scene from an M2 file or saving the scene back to it."""

    def __init__(self, m2: M2File, prefs):
        self.m2 = m2
        self.materials = {}
        self.bone_ids = {}
        self.attachment_ids = {}
        self.event_ids = {}
        self.camera_ids = {}
        self.camera_target_ids = {}
        self.color_ids = {}
        self.transparency_ids = {}
        self.texture_transform_ids = {}
        self.light_ids = {}
        self.uv_transforms = {}
        self.geosets = []
        self.animations = []
        self.alias_animation_lookup = {}
        self.global_sequences = []
        self.old_actions = []
        self.old_selections = []
        self.old_active = None
        self.old_mode = None
        self.reset_pose_actions = []
        self.axis_order = [0,1]
        self.axis_polarity = [1,1]
        self.rig = None
        self.collision_mesh = None
        self.settings = prefs

        self.scene = bpy.context.scene

    def load_colors(self):

        def animate_color(anim_pair, color_track, color_index, anim_index):

            action = anim_pair.action

            try:
                frames = color_track.timestamps[anim_index]
                track = color_track.values[anim_index]
            except IndexError:
                return

            if not len(frames):
                return

            # create fcurve
            f_curves = [action.fcurves.new(data_path='wow_m2_colors[{}].color'.format(color_index),
                                           index=k, action_group='Color_{}'.format(color_index)) for k in range(3)]

            # init keyframes on the curve
            for f_curve in f_curves:
                f_curve.keyframe_points.add(len(frames))

            # set translation values for each channel
            for i, timestamp in enumerate(frames):
                frame = timestamp * 0.0266666

                for j in range(3):
                    keyframe = f_curves[j].keyframe_points[i]
                    keyframe.co = frame, track[i][j]
                    keyframe.interpolation = 'LINEAR' if color_track.interpolation_type == 1 else 'CONSTANT'

        def animate_alpha(anim_pair, alpha_track, color_index, anim_index):

            action = anim_pair.action

            try:
                frames = alpha_track.timestamps[anim_index]
                track = alpha_track.values[anim_index]
            except IndexError:
                return

            if not len(frames):
                return

            # create fcurve
            f_curve = action.fcurves.new(data_path='wow_m2_colors[{}].alpha'.format(color_index),
                                         index=0, action_group='Color_{}'.format(color_index))

            # init keyframes on the curve
            f_curve.keyframe_points.add(len(frames))

            # set translation values for each channel
            for i, timestamp in enumerate(frames):
                frame = timestamp * 0.0266666

                keyframe = f_curve.keyframe_points[i]
                keyframe.co = frame, track[i] / 0x7FFF
                keyframe.interpolation = 'LINEAR' if alpha_track.interpolation_type == 1 else 'CONSTANT'

        if not len(self.m2.root.colors):
            print("\nNo colors found to import.")
            return

        else:
            print("\nImporting colors.")

        bpy.context.scene.animation_data_create()
        bpy.context.scene.animation_data.action_blend_type = 'ADD'
        n_global_sequences = len(self.global_sequences)

        for i, m2_color in enumerate(self.m2.root.colors):
            bl_color = bpy.context.scene.wow_m2_colors.add()
            bl_color.name = 'Color_{}'.format(i)
            bl_color.color = (1.0, 1.0, 1.0, 1.0)

            # load global sequences
            for j, seq_index in enumerate(self.global_sequences):
                anim = bpy.context.scene.wow_m2_animations[j]

                anim_pair = None
                for pair in anim.anim_pairs:
                    if pair.type == 'SCENE':
                        anim_pair = pair
                        break

                if m2_color.color.global_sequence == seq_index:
                    animate_color(anim_pair, m2_color.color, i, 0)

                if m2_color.alpha.global_sequence == seq_index:
                    animate_alpha(anim_pair, m2_color.alpha, i, 0)

            # load animations
            for j, anim_index in enumerate(self.animations):
                anim = bpy.context.scene.wow_m2_animations[j + n_global_sequences]

                anim_pair = None
                for pair in anim.anim_pairs:
                    if pair.type == 'SCENE':
                        anim_pair = pair
                        break

                if m2_color.color.global_sequence < 0:
                    animate_color(anim_pair, m2_color.color, i, anim_index)

                if m2_color.alpha.global_sequence < 0:
                    animate_alpha(anim_pair, m2_color.alpha, i, anim_index)

    def load_transparency(self):

        def animate_transparency(anim_pair, trans_track, trans_index, anim_index):

            action = anim_pair.action

            try:
                frames = trans_track.timestamps[anim_index]
                track = trans_track.values[anim_index]
            except IndexError:
                return

            if not len(frames):
                return

            # create fcurve
            f_curve = action.fcurves.new(data_path='wow_m2_transparency[{}].value'.format(trans_index),
                                         index=0, action_group='Transparency_{}'.format(trans_index))

            # init keyframes on the curve
            f_curve.keyframe_points.add(len(frames))

            # set translation values for each channel
            for i, timestamp in enumerate(frames):
                frame = timestamp * 0.0266666

                keyframe = f_curve.keyframe_points[i]
                keyframe.co = frame, track[i] / 0x7FFF
                keyframe.interpolation = 'LINEAR' if trans_track.interpolation_type == 1 else 'CONSTANT'

        if not len(self.m2.root.texture_weights):
            print("\nNo transparency tracks found to import.")
            return

        else:
            print("\nImporting transparency.")

        bpy.context.scene.animation_data_create()
        bpy.context.scene.animation_data.action_blend_type = 'ADD'
        n_global_sequences = len(self.global_sequences)

        for i, m2_transparency in enumerate(self.m2.root.texture_weights):
            bl_transparency = bpy.context.scene.wow_m2_transparency.add()
            bl_transparency.name = 'Transparency_{}'.format(i)

            # load global sequences
            for j, seq_index in enumerate(self.global_sequences):
                anim = bpy.context.scene.wow_m2_animations[j]

                anim_pair = None
                for pair in anim.anim_pairs:
                    if pair.type == 'SCENE':
                        anim_pair = pair
                        break

                if m2_transparency.global_sequence == seq_index:
                    animate_transparency(anim_pair, m2_transparency, i, 0)

            # load animations
            for j, anim_index in enumerate(self.animations):
                anim = bpy.context.scene.wow_m2_animations[j + n_global_sequences]

                anim_pair = None
                for pair in anim.anim_pairs:
                    if pair.type == 'SCENE':
                        anim_pair = pair
                        break

                if m2_transparency.global_sequence < 0:
                    animate_transparency(anim_pair, m2_transparency, i, anim_index)

    def load_materials(self):

        skin = self.m2.skins[0]

        loaded_textures = {}

        for tex_unit in skin.texture_units:
            m2_mat = self.m2.root.materials[tex_unit.material_index]

            blender_mat = bpy.data.materials.new(name='Unknown')
            blender_mat.wow_m2_material.live_update = True

            for i in range(tex_unit.texture_count):

                texture = self.m2.root.textures[self.m2.root.texture_lookup_table[tex_unit.texture_combo_index + i]]
                tex = loaded_textures.get(self.m2.root.texture_lookup_table[tex_unit.texture_combo_index + i])

                if not tex:

                    tex_path_png = ""

                    if not texture.type:  # check if texture is hardcoded

                        try:
                            tex_path_blp = self.m2.texture_path_map[texture.fdid] \
                                if texture.fdid else self.m2.texture_path_map[texture.filename.value]

                            tex_path_png = os.path.splitext(tex_path_blp)[0] + '.png'
                        except KeyError:
                            pass

                    if tex_path_png:
                        try:
                            tex = bpy.data.images.load(tex_path_png)
                        except RuntimeError:
                            print("\nWarning: failed to load texture \"{}\".".format(tex_path_png))

                    if not tex:
                        tex = bpy.data.images.new('Failed Loading', 256, 256)
                    
                    # titi test textures ui
                    slot = bpy.context.scene.wow_m2_root_elements.textures.add()
                    slot.pointer = tex
                    ####

                    loaded_textures[self.m2.root.texture_lookup_table[tex_unit.texture_combo_index + i]] = tex

                setattr(blender_mat.wow_m2_material, "texture_{}".format(i + 1), tex)
                tex.wow_m2_texture.flags = parse_bitfield(texture.flags, 0x2)
                tex.wow_m2_texture.texture_type = str(texture.type)
                tex.wow_m2_texture.path = texture.filename.value

            # bind transparency to material
            if tex_unit.texture_weight_combo_index >= 0:
                real_tw_index = self.m2.root.transparency_lookup_table[tex_unit.texture_weight_combo_index]
                transparency = bpy.context.scene.wow_m2_transparency[real_tw_index]
                blender_mat.wow_m2_material.transparency = transparency.name

            # bind color to material
            if tex_unit.color_index >= 0:
                color = bpy.context.scene.wow_m2_colors[tex_unit.color_index]
                blender_mat.wow_m2_material.color = color.name

            blender_mat.name = blender_mat.wow_m2_material.texture_1.name
            update_m2_mat_node_tree(blender_mat)

            '''

            # setup node render node tree
            blender_mat.use_nodes = True
            tree = blender_mat.node_tree
            links = tree.links

            # clear default nodes
            for n in tree.nodes:
                tree.nodes.remove(n)

            # create input materail node
            mat_node = tree.nodes.new('ShaderNodeDiffuseBSDF')
            mat_node.location = 530, 1039
            mat_node.material = blender_mat

            # create color ramp nodes
            c_ramp = tree.nodes.new('ShaderNodeValToRGB')
            c_ramp.location = 896, 579
            c_ramp.inputs[0].default_value = 1.0
            c_ramp.color_ramp.elements.remove(c_ramp.color_ramp.elements[1])
            c_ramp.color_ramp.elements[0].color = 1.0, 1.0, 1.0, 1.0
            # create multiply nodes

            # transparency
            t_mult = tree.nodes.new('ShaderNodeMath')
            t_mult.location = 975, 878
            t_mult.operation = 'MULTIPLY'
            t_mult.inputs[1].default_value = 1.0

            # alpha
            a_mult = tree.nodes.new('ShaderNodeMath')
            a_mult.location = 1386, 757
            a_mult.operation = 'MULTIPLY'

            # color
            c_mult = tree.nodes.new('ShaderNodeMixRGB')
            c_mult.location = 1304, 1083
            c_mult.blend_type = 'MULTIPLY'
            c_mult.inputs[0].default_value = 1.0

            # create output node
            output = tree.nodes.new('ShaderNodeOutput')
            output.location = 1799, 995

            # link nodes to each other
            links.new(mat_node.outputs[0], c_mult.inputs[1])
            links.new(c_mult.outputs[0], output.inputs[0])
            links.new(mat_node.outputs[1], t_mult.inputs[0])
            links.new(t_mult.outputs[0], a_mult.inputs[0])
            links.new(a_mult.outputs[0], output.inputs[1])
            links.new(c_ramp.outputs[0], c_mult.inputs[2])
            links.new(c_ramp.outputs[1], a_mult.inputs[1])

            # add UI property drivers
            color_curves = tree.driver_add("nodes[\"ColorRamp\"].color_ramp.elements[0].color")
            transparency_curve = tree.driver_add("nodes[\"Math\"].inputs[1].default_value")

            # colors
            for i, fcurve in enumerate(color_curves):
                driver = fcurve.driver
                driver.type = 'SCRIPTED'

                color_name_var = driver.variables.new()
                color_name_var.name = 'color_name'
                color_name_var.targets[0].id_type = 'TEXTURE'
                color_name_var.targets[0].id = tex1
                color_name_var.targets[0].data_path = 'wow_m2_texture.color'

                color_col_var = driver.variables.new()
                color_col_var.name = 'colors'
                color_col_var.targets[0].id_type = 'SCENE'
                color_col_var.targets[0].id = bpy.context.scene
                color_col_var.targets[0].data_path = 'wow_m2_colors'

                driver.expression = 'colors[color_name].color[{}] if color_name in colors else 1.0'.format(i)

            # transparency
            driver = transparency_curve.driver
            driver.type = 'SCRIPTED'

            trans_name_var = driver.variables.new()
            trans_name_var.name = 'trans_name'
            trans_name_var.targets[0].id_type = 'TEXTURE'
            trans_name_var.targets[0].id = tex1
            trans_name_var.targets[0].data_path = 'wow_m2_texture.transparency'

            color_col_var = driver.variables.new()
            color_col_var.name = 'trans_values'
            color_col_var.targets[0].id_type = 'SCENE'
            color_col_var.targets[0].id = bpy.context.scene
            color_col_var.targets[0].data_path = 'wow_m2_transparency'

            driver.expression = 'trans_values[trans_name].value if trans_name in trans_values else 1.0'

            # bind color to texture
            if tex_unit.color_index >= 0:
                color = bpy.context.scene.wow_m2_colors[tex_unit.color_index]
                tex1.wow_m2_texture.color = color.name
                
            '''

            # filling material settings
            blender_mat.wow_m2_material.flags = parse_bitfield(tex_unit.flags, 0x80)  # texture unit flags
            blender_mat.wow_m2_material.render_flags = parse_bitfield(m2_mat.flags, 0x800)  # render flags

            blender_mat.wow_m2_material.blending_mode = str(m2_mat.blending_mode)

            blender_mat.wow_m2_material.layer = tex_unit.material_layer
            blender_mat.wow_m2_material.priority_plane = tex_unit.priority_plane
            blender_mat.wow_m2_material.tex_unit_coord = self.m2.root.tex_unit_lookup_table[tex_unit.texture_coord_combo_index]

            vertex_shader = M2ShaderPermutations().get_vertex_shader_id(tex_unit.texture_count, tex_unit.shader_id)
            pixel_shader = M2ShaderPermutations().get_pixel_shader_id(tex_unit.texture_count, tex_unit.shader_id)

            try:
                blender_mat.wow_m2_material.vertex_shader = str(vertex_shader)
                blender_mat.wow_m2_material.fragment_shader = str(pixel_shader)
            except TypeError:
                print('\"Error: Failed to set shader ID ({}) to material \"{}\".'.format(tex_unit.shader_id,
                                                                                         blender_mat.name))

            # TODO: other settings

            if not tex_unit.skin_section_index in self.materials:
                self.materials[tex_unit.skin_section_index] = []

            self.materials[tex_unit.skin_section_index].append((blender_mat, tex_unit))
            
            # root ui stuff, titi 
            slot = bpy.context.scene.wow_m2_root_elements.materials.add()
            slot.pointer = blender_mat

    def load_armature(self):
        if not len(self.m2.root.bones):
            print("\nNo armature found to import.")
            return

        print("\nImporting armature")

        # Create armature
        armature = bpy.data.armatures.new('{}_Armature'.format(self.m2.root.name.value))
        rig = bpy.data.objects.new(self.m2.root.name.value, armature)
        rig.location = (0, 0, 0)
        self.rig = rig

        # Link the object to the scene
        bpy.context.collection.objects.link(rig)
        bpy.context.view_layer.objects.active = rig

        bpy.context.view_layer.update()

        bpy.ops.object.mode_set(mode='EDIT')

        for i, bone in enumerate(self.m2.root.bones):  # add bones to armature.
            bl_edit_bone = armature.edit_bones.new(bone.name)
            bl_edit_bone.head = Vector(bone.pivot)

            bl_edit_bone.tail.x = bl_edit_bone.head.x + 0.1  # TODO: mess with bones parenting even more
            bl_edit_bone.tail.y = bl_edit_bone.head.y
            bl_edit_bone.tail.z = bl_edit_bone.head.z

            bl_edit_bone.wow_m2_bone.sort_index = i
            bl_edit_bone.wow_m2_bone.flags = parse_bitfield(bone.flags)
            bl_edit_bone.wow_m2_bone.submesh_id = bone.submesh_id
            bl_edit_bone.wow_m2_bone.bone_name_crc = ctypes.c_int(bone.bone_name_crc).value

            try:
                bl_edit_bone.wow_m2_bone.key_bone_id = str(bone.key_bone_id)
            except TypeError:
                print('\nFailed to set keybone ID \"{}\". Unknown keybone ID'.format(bone.key_bone_id))

        # link children to parents
        for i, bone in enumerate(self.m2.root.bones):
            if bone.parent_bone >= 0:
                bl_edit_bone = armature.edit_bones[bone.name]
                parent = armature.edit_bones[self.m2.root.bones[bone.parent_bone].name]
                bl_edit_bone.parent = parent

        bpy.context.view_layer.update()  # update scene.
        bpy.ops.object.mode_set(mode='OBJECT')  # return to object mode.

    @staticmethod
    def _populate_bl_fcurve(f_curves, frames, track, length, callback, interp_type):

        # init keyframes on the curve
        for f_curve in f_curves:
            f_curve.keyframe_points.add(len(frames))

        # set values for each channel

        if track:

            for j, timestamp in enumerate(frames):
                value = callback(value=track[j])
                frame = timestamp * 0.0266666

                for k in range(len(value)):
                    keyframe = f_curves[k].keyframe_points[j]
                    keyframe.co = frame, value[k]
                    keyframe.interpolation = interp_type

        else:

            for j, timestamp in enumerate(frames):
                frame = timestamp * 0.0266666
                keyframe = f_curves[0].keyframe_points[j]
                keyframe.co = frame, True
                keyframe.interpolation = interp_type

    @staticmethod
    def _bl_create_fcurves(action, action_group, callback, length, anim_index, data_path, anim_track):

        if anim_track.timestamps.n_elements > anim_index:

            frames = anim_track.timestamps[anim_index]

            try:
                track = anim_track.values[anim_index]
            except AttributeError:
                track = None

            if frames:
                t_fcurves = [action.fcurves.new(data_path=data_path, index=k, action_group=action_group)
                             for k in range(length)]

                BlenderM2Scene._populate_bl_fcurve(t_fcurves, frames, track, length, callback,
                                                   'LINEAR' if anim_track.interpolation_type == 1 else 'CONSTANT')

    @staticmethod
    def _bl_create_action(anim_pair, name: str) -> bpy.types.Action:

        if not anim_pair.action:

            action = bpy.data.actions.new(name=name)
            action.use_fake_user = True
            anim_pair.action = action

            return action

        return anim_pair.action

    @staticmethod
    def _bl_convert_track_dummy(value=None):
        return [value]

    @staticmethod
    def _bl_convert_track_value(value=None):
        return [value]

    @staticmethod
    def _bl_convert_track_tuple(value=None):
        return value

    def _bl_add_sequence(self, name: str = "Sequence", is_global: bool = False, is_alias: bool = False):
        seq = self.scene.wow_m2_animations.add()
        seq.is_global_sequence = is_global

        # register scene in the sequence
        anim_pair_scene = seq.anim_pairs.add()
        anim_pair_scene.type = 'SCENE'
        anim_pair_scene.scene = bpy.context.scene

        # register rig in the sequence
        anim_pair = seq.anim_pairs.add()
        anim_pair.type = 'OBJECT'
        anim_pair.object = self.rig

        if not is_alias:
            action = bpy.data.actions.new(name='SC_{}'.format(name))
            action.use_fake_user = True
            anim_pair_scene.action = action

            action = bpy.data.actions.new(name=name)
            action.use_fake_user = True
            anim_pair.action = action

        return seq

    def _bl_load_sequences(self):
        anim_data_table = M2SequenceNames()

        # import global sequence animations
        for i in range(len(self.m2.root.global_sequences)):
            self._bl_add_sequence(name='Global_Sequence_{}'.format(str(i).zfill(3)), is_global=True)
            self.global_sequences.append(len(self.scene.wow_m2_animations) - 1)

        m2_sequences = sorted(enumerate(self.m2.root.sequences),
                              key=lambda item: (item[0], item[1].id, item[1].variation_index))

        # import animation sequence
        for i, pair in enumerate(m2_sequences):
            idx, sequence = pair

            # create sequence
            field_name = anim_data_table.get_sequence_name(sequence.id)
            name = '{}_UnkAnim'.format(str(i).zfill(3)) \
                if not field_name else "{}_{}_({})".format(str(i).zfill(3), field_name, sequence.variation_index)

            # check if sequence is an alias
            is_alias = sequence.flags & 0x40

            # create sequence
            anim = self._bl_add_sequence(name=name, is_global=False, is_alias=is_alias)

            # find real animation index
            if is_alias:
                anim.is_alias = True

                for j, seq in m2_sequences:
                    anim.alias_next = j
                    if j == sequence.alias_next:
                        self.alias_animation_lookup[i] = j
                        break

            # add animation properties
            anim.animation_id = str(sequence.id)
            anim.flags = parse_bitfield(sequence.flags, 0x800)
            anim.move_speed = sequence.movespeed
            anim.frequency = sequence.frequency
            anim.replay_min = sequence.replay.minimum
            anim.replay_max = sequence.replay.maximum
            anim.VariationNext = sequence.variation_next

            if self.m2.root.version >= M2Versions.WOD:
                anim.blend_time_in = sequence.blend_time_in
                anim.blend_time_out = sequence.blend_time_out

            else:
                anim.blend_time = sequence.blend_time

            self.animations.append(idx)

    @staticmethod
    def _bl_create_action_group(action: bpy.types.Action, name: str) -> str:
        if name not in action.groups:
            action.groups.new(name=name)

        return name

    def load_animations(self):

        # TODO: pre-wotlk

        def bl_convert_trans_track(value=None, bl_bone=None, bone=None):
            return bl_bone.bone.matrix_local.inverted() @ (Vector(bone.pivot) + Vector(value))

        def bl_convert_rot_track(value=None):
            return value.to_quaternion()

        def bl_convert_scale_track(value=None):

            value = list(value)

            for i, val in enumerate(value):
                if isinf(val):
                    print("\nWarning: Fixed infinite scale value!")  #TODO: figure out infinite values there
                    value[i] = 1.0

            return tuple(value)

        if not len(self.m2.root.sequences) and not len(self.m2.root.global_sequences):
            print("\nNo animation data found to import.")
            return
        else:
            print("\nImporting animations.")

        if not self.rig:
            print("\nArmature is not present on the scene. Skipping animation import. M2 is most likely corrupted.")
            return

        # create animation data for rig and set it as an active object
        scene = self.scene
        rig = self.rig
        rig.animation_data_create()
        rig.animation_data.action_blend_type = 'ADD'
        bpy.context.view_layer.objects.active = rig

        self._bl_load_sequences()

        # import fcurves
        for bone in self.m2.root.bones:
            bl_bone = rig.pose.bones[bone.name]

            is_global_seq_trans = bone.translation.global_sequence >= 0
            is_global_seq_rot = bone.rotation.global_sequence >= 0
            is_global_seq_scale = bone.scale.global_sequence >= 0

            glob_sequences = self.global_sequences

            # write global sequence fcurves
            if is_global_seq_trans:
                action = scene.wow_m2_animations[glob_sequences[bone.translation.global_sequence]].anim_pairs[1].action
                self._bl_create_action_group(action, bone.name)
                self._bl_create_fcurves(action, bone.name, partial(bl_convert_trans_track, bl_bone=bl_bone, bone=bone),
                                        3, 0, 'pose.bones.["{}"].location'.format(bl_bone.name), bone.translation)

            if is_global_seq_rot:
                action = scene.wow_m2_animations[glob_sequences[bone.rotation.global_sequence]].anim_pairs[1].action
                self._bl_create_action_group(action, bone.name)
                self._bl_create_fcurves(action, bone.name, partial(bl_convert_rot_track), 4, 0,
                                        'pose.bones.["{}"].rotation_quaternion'.format(bl_bone.name), bone.rotation)

            if is_global_seq_scale:
                action = scene.wow_m2_animations[glob_sequences[bone.scale.global_sequence]].anim_pairs[1].action
                self._bl_create_action_group(action, bone.name)
                self._bl_create_fcurves(action, bone.name, partial(bl_convert_scale_track), 3, 0,
                                        'pose.bones.["{}"].scale'.format(bl_bone.name), bone.scale)

            # write regular animation fcurves
            n_global_sequences = len(self.m2.root.global_sequences)
            for i, anim_index in enumerate(self.animations):
                anim = scene.wow_m2_animations[i + n_global_sequences]
                action = anim.anim_pairs[1].action

                if not action:
                    continue

                # translate bones
                if not is_global_seq_trans and bone.translation.timestamps.n_elements > anim_index:
                    self._bl_create_action_group(action, bone.name)
                    self._bl_create_fcurves(action, bone.name, partial(bl_convert_trans_track, bl_bone=bl_bone,
                                            bone=bone), 3, anim_index,
                                            'pose.bones.["{}"].location'.format(bl_bone.name),
                                            bone.translation)

                # rotate bones
                if not is_global_seq_rot and bone.rotation.timestamps.n_elements > anim_index:
                    self._bl_create_action_group(action, bone.name)
                    self._bl_create_fcurves(action, bone.name, partial(bl_convert_rot_track), 4,
                                            anim_index,'pose.bones.["{}"].rotation_quaternion'.format(bl_bone.name),
                                            bone.rotation)

                # scale bones
                if not is_global_seq_scale and bone.scale.timestamps.n_elements > anim_index:
                    self._bl_create_action_group(action, bone.name)
                    self._bl_create_fcurves(action, bone.name, partial(bl_convert_scale_track), 3, anim_index,
                                            'pose.bones.["{}"].scale'.format(bl_bone.name),
                                            bone.scale)

    def load_geosets(self):

        if not len(self.m2.root.vertices):
            print("\nNo mesh geometry found to import.")
            return

        else:
            print("\nImporting geosets.")

        skin = self.m2.skins[0]

        for smesh_i, smesh in enumerate(skin.submeshes):

            vertices = [self.m2.root.vertices[skin.vertex_indices[i]].pos
                        for i in range(smesh.vertex_start, smesh.vertex_start + smesh.vertex_count)]

            normals = [self.m2.root.vertices[skin.vertex_indices[i]].normal
                       for i in range(smesh.vertex_start, smesh.vertex_start + smesh.vertex_count)]

            tex_coords = [self.m2.root.vertices[skin.vertex_indices[i]].tex_coords
                          for i in range(smesh.vertex_start, smesh.vertex_start + smesh.vertex_count)]

            tex_coords2 = [self.m2.root.vertices[skin.vertex_indices[i]].tex_coords2
                          for i in range(smesh.vertex_start, smesh.vertex_start + smesh.vertex_count)]

            triangles = [[skin.triangle_indices[i + j] - smesh.vertex_start for j in range(3)]
                         for i in range(smesh.index_start, smesh.index_start + smesh.index_count, 3)]

            # create mesh
            mesh = bpy.data.meshes.new(self.m2.root.name.value)
            mesh.from_pydata(vertices, [], triangles)

            for poly in mesh.polygons:
                poly.use_smooth = True

            # set normals
            for index, vertex in enumerate(mesh.vertices):
                vertex.normal = normals[index]

            # set uv
            mesh.uv_layers.new(name="UVMap")
            uv_layer1 = mesh.uv_layers[0]
            for i in range(len(uv_layer1.data)):
                uv = tex_coords[mesh.loops[i].vertex_index]
                uv_layer1.data[i].uv = (uv[0], 1 - uv[1])

            mesh.uv_layers.new(name="UVMap.001")
            uv_layer2 = mesh.uv_layers[1]
            for i in range(len(uv_layer2.data)):
                uv = tex_coords2[mesh.loops[i].vertex_index]
                uv_layer2.data[i].uv = (uv[0], 1 - uv[1])

            # set textures and materials
            for material, tex_unit in self.materials[smesh_i]:
                mesh.materials.append(material)

            for i, poly in enumerate(mesh.polygons):
                poly.material_index = 0  # TODO: excuse me wtf?

            # get object name
            name = M2SkinMeshPartID.get_mesh_part_name(smesh.skin_section_id)
            obj = bpy.data.objects.new(name if name else 'Geoset', mesh)
            bpy.context.collection.objects.link(obj)

            try:
                obj.wow_m2_geoset.mesh_part_group = name
                obj.wow_m2_geoset.mesh_part_id = str(smesh.skin_section_id)
            except TypeError:
                print('Warning: unknown mesh part ID \"{}\"'.format(smesh.skin_section_id))
            for item in mesh_part_id_menu(obj.wow_m2_geoset, None):
                if item[0] == smesh.skin_section_id:
                    obj.name = item[1]

            if self.rig:
                obj.parent = self.rig

                # bind armature to geometry
                bpy.context.view_layer.objects.active = obj
                bpy.ops.object.modifier_add(type='ARMATURE')
                bpy.context.object.modifiers["Armature"].object = self.rig

                vgroups = {}
                for j in range(smesh.vertex_start, smesh.vertex_start + smesh.vertex_count):
                    m2_vertex = self.m2.root.vertices[skin.vertex_indices[j]]

                    for b_index, bone_index in enumerate(filter(lambda x: x > 0, m2_vertex.bone_indices)):
                        vgroups.setdefault(self.m2.root.bones[bone_index].name, []).append(
                            (j - smesh.vertex_start, m2_vertex.bone_weights[b_index] / 255))

                for name in vgroups.keys():
                    if len(vgroups[name]) > 0:
                        grp = obj.vertex_groups.new(name=name)
                        for (v, w) in vgroups[name]:
                            grp.add([v], w, 'REPLACE')

            self.geosets.append(obj)
            
            slot = bpy.context.scene.wow_m2_root_elements.geosets.add()
            slot.pointer = obj

    def load_texture_transforms(self):

        def bl_convert_trans_track(value=None):
            return Vector((0, 0, 0)) + Vector(value)

        def bl_convert_rot_track(value=None):
            return value[3], -value[1], value[0], value[2]

        if not self.geosets:
            print('\nNo geosets found. Skipping texture transform import')
            return
        else:
            print('\nImporting texture transforms')

        skin = self.m2.skins[0]

        for smesh_pair, obj in zip(enumerate(skin.submeshes), self.geosets):
            smesh_i, smesh = smesh_pair

            for _, tex_unit in self.materials[smesh_i]:

                for i in range(2 if tex_unit.texture_count > 1 else 1):

                    combo_index = tex_unit.texture_transform_combo_index + i

                    if combo_index >= self.m2.root.texture_lookup_table.n_elements:
                        break

                    tex_tranform_index = self.m2.root.texture_transforms_lookup_table[combo_index]

                    if tex_tranform_index >= 0:

                        c_obj = self.uv_transforms.get(tex_tranform_index)
                        tex_transform = self.m2.root.texture_transforms[tex_tranform_index]
                        seq_name_table = M2SequenceNames()
                        n_global_sequences = len(self.global_sequences)

                        if not c_obj:
                            bpy.ops.object.empty_add(type='SINGLE_ARROW', location=(0, 0, 0))
                            c_obj = bpy.context.view_layer.objects.active
                            c_obj.name = "TT_Controller"
                            c_obj.wow_m2_uv_transform.enabled = True
                            c_obj = bpy.context.view_layer.objects.active
                            c_obj.rotation_mode = 'QUATERNION'
                            c_obj.empty_display_size = 0.5
                            c_obj.animation_data_create()
                            c_obj.animation_data.action_blend_type = 'ADD'

                            self.uv_transforms[tex_tranform_index] = c_obj

                        bpy.context.view_layer.objects.active = obj
                        bpy.ops.object.modifier_add(type='UV_WARP')
                        uv_transform = bpy.context.object.modifiers[-1]
                        uv_transform.name = 'M2TexTransform_{}'.format(i + 1)
                        uv_transform.object_from = obj
                        uv_transform.object_to = c_obj
                        uv_transform.uv_layer = 'UVMap' if not i else 'UVMap.001'

                        setattr(obj.wow_m2_geoset, 'uv_transform_{}'.format(i + 1), c_obj)

                        # load global sequences
                        for j, seq_index in enumerate(self.global_sequences):
                            anim = bpy.context.scene.wow_m2_animations[seq_index]

                            name = "TT_{}_{}_Global_Sequence_{}".format(tex_tranform_index, obj.name, str(j).zfill(3))

                            cur_index = len(anim.anim_pairs)
                            anim_pair = anim.anim_pairs.add()
                            anim_pair.type = 'OBJECT'
                            anim_pair.object = c_obj

                            if tex_transform.translation.global_sequence == j \
                            and tex_transform.translation.timestamps.n_elements:
                                action = self._bl_create_action(anim_pair, name)
                                self._bl_create_fcurves(action, obj.name, bl_convert_trans_track, 3, 0, 'location',
                                                        tex_transform.translation)

                            if tex_transform.rotation.global_sequence == j \
                            and tex_transform.rotation.timestamps.n_elements:
                                action = self._bl_create_action(anim_pair, name)
                                self._bl_create_fcurves(action, obj.name, bl_convert_rot_track, 4, 0, 'rotation_quaternion',
                                                        tex_transform.rotation)

                            if tex_transform.scaling.global_sequence == j \
                            and tex_transform.scaling.timestamps.n_elements:
                                action = self._bl_create_action(anim_pair, name)
                                self._bl_create_fcurves(action, obj.name, self._bl_convert_track_dummy, 3, 0, 'scale',
                                                        tex_transform.scaling)

                            if not anim_pair.action:
                                    anim.anim_pairs.remove(cur_index)

                    # load animations
                        for j, anim_index in enumerate(self.animations):

                            # skip alias
                            if self.alias_animation_lookup.get(j):
                                continue

                            anim = bpy.context.scene.wow_m2_animations[j + n_global_sequences]
                            sequence = self.m2.root.sequences[anim_index]

                            field_name = seq_name_table.get_sequence_name(sequence.id)
                            name = 'TT_{}_{}_{}_UnkAnim'.format(tex_tranform_index, obj.name, str(j).zfill(3)) \
                                 if not field_name else "TT_{}_{}_{}_{}_({})".format(tex_tranform_index,
                                                                                     obj.name,
                                                                                     str(j).zfill(3),
                                                                                     field_name,
                                                                                     sequence.variation_index)

                            cur_index = len(anim.anim_pairs)
                            anim_pair = anim.anim_pairs.add()
                            anim_pair.type = 'OBJECT'
                            anim_pair.object = c_obj

                            if tex_transform.translation.global_sequence < 0 \
                            and tex_transform.translation.timestamps.n_elements > j:
                                action = self._bl_create_action(anim_pair, name)
                                self._bl_create_fcurves(action, obj.name, bl_convert_trans_track, 3, j, 'location',
                                                        tex_transform.translation)

                            if tex_transform.rotation.global_sequence < 0 \
                                    and tex_transform.rotation.timestamps.n_elements > j:
                                action = self._bl_create_action(anim_pair, name)
                                self._bl_create_fcurves(action, obj.name, bl_convert_rot_track, 4, j, 'rotation_quaternion',
                                                        tex_transform.rotation)

                            if tex_transform.scaling.global_sequence < 0 \
                                    and tex_transform.scaling.timestamps.n_elements > j:
                                action = self._bl_create_action(anim_pair, name)
                                self._bl_create_fcurves(action, obj.name, self._bl_convert_track_tuple, 3, j,
                                                        'scale', tex_transform.scaling)

                            if not anim_pair.action:
                                anim.anim_pairs.remove(cur_index)

    def load_attachments(self):
        # TODO: unknown field

        for i, attachment in enumerate(self.m2.root.attachments):
            bpy.ops.object.empty_add(type='SPHERE', location=(0, 0, 0))
            obj = bpy.context.view_layer.objects.active
            obj.empty_display_size = 0.07
            bpy.ops.object.constraint_add(type='CHILD_OF')
            constraint = obj.constraints[-1]
            constraint.target = self.rig
            obj.parent = self.rig
            bone = self.m2.root.bones[attachment.bone]
            constraint.subtarget = bone.name

            bl_edit_bone = self.rig.data.bones[bone.name]
            obj.location = attachment.position

            obj.name = M2AttachmentTypes.get_attachment_name(attachment.id, i)
            obj.wow_m2_attachment.enabled = True
            obj.wow_m2_attachment.type = str(attachment.id)

            # animate attachment
            obj.animation_data_create()
            obj.animation_data.action_blend_type = 'ADD'
            seq_name_table = M2SequenceNames()
            n_global_sequences = len(self.global_sequences)

            # titi test
            slot = bpy.context.scene.wow_m2_root_elements.attachments.add()
            slot.pointer = obj

            # load global sequence
            if attachment.animate_attached.global_sequence >= 0:
                anim = bpy.context.scene.wow_m2_animations[attachment.animate_attached.global_sequence]

                if not attachment.animate_attached.timestamps.n_elements \
                or not attachment.animate_attached.timestamps[0]:
                    return

                name = "AT_{}_{}_Global_Sequence_{}".format(i, obj.name,
                                                            str(attachment.animate_attached.global_sequence).zfill(3))

                anim_pair = anim.anim_pairs.add()
                anim_pair.type = 'OBJECT'
                anim_pair.object = obj
                anim_pair.action = self._bl_create_action(anim_pair, name)

                self._bl_create_fcurves(anim_pair.action, "", self._bl_convert_track_dummy, 1, 0,
                                        'wow_m2_attachment.animate', attachment.animate_attached)

                return

            # load animations
            for j, anim_index in enumerate(self.animations):
                anim = bpy.context.scene.wow_m2_animations[j + n_global_sequences]
                sequence = self.m2.root.sequences[anim_index]

                if attachment.animate_attached.timestamps.n_elements > anim_index:
                    if not len(attachment.animate_attached.timestamps[anim_index]):
                        continue

                    field_name = seq_name_table.get_sequence_name(sequence.id)
                    name = 'AT_{}_{}_UnkAnim'.format(i, obj.name, str(j).zfill(3)) \
                         if not field_name else "AT_{}_{}_{}_({})".format(i, obj.name, str(j).zfill(3), field_name,
                                                                          sequence.variation_index)

                    anim_pair = anim.anim_pairs.add()
                    anim_pair.type = 'OBJECT'
                    anim_pair.object = obj
                    self._bl_create_action(anim_pair, name)

                    self._bl_create_fcurves(anim_pair.action, "", self._bl_convert_track_dummy, 1, j,
                                            'wow_m2_attachment.animate', attachment.animate_attached)

    def load_lights(self):

        def animate_property(anim_pair, m2_light, prop_name, length, action_name, anim_index):

            prop_track = getattr(m2_light, prop_name)

            try:
                frames = prop_track.timestamps[anim_index]
            except IndexError:
                return

            if not len(frames):
                return

            self._bl_create_action(anim_pair, action_name)
            action_group = self._bl_create_action_group(anim_pair.action, 'Color_{}'.format(prop_name))

            self._bl_create_fcurves(anim_pair.action, action_group, self._bl_convert_track_value if length == 1 else self._bl_convert_track_tuple, length, anim_index,
                                    'data.wow_m2_light.{}'.format(prop_name), prop_track)

        for i, light in enumerate(self.m2.root.lights):
            #bpy.ops.object.lamp_add(type='POINT' if light.type else 'SPOT', location=(0, 0, 0))
            bpy.ops.object.light_add(type='POINT' if light.type else 'SPOT', location=(0, 0, 0))
            obj = bpy.context.view_layer.objects.active
            obj.data.wow_m2_light.type = str(light.type)
            obj.data.wow_m2_light.enabled = True

            if self.rig:
                obj.parent = self.rig

            if light.bone >= 0:
                bpy.ops.object.constraint_add(type='CHILD_OF')
                constraint = obj.constraints[-1]
                constraint.target = self.rig
                bone = self.m2.root.bones[light.bone]
                constraint.subtarget = bone.name

                bl_edit_bone = self.rig.data.bones[bone.name]
                obj.location = light.position

            # animate light
            obj.animation_data_create()
            obj.animation_data.action_blend_type = 'ADD'
            seq_name_table = M2SequenceNames()
            n_global_sequences = len(self.global_sequences)

            channels = [('ambient_color', 3), ('ambient_intensity', 1), ('diffuse_color', 3),
                        ('diffuse_intensity', 1), ('attenuation_start', 1), ('attenuation_end', 1), ('visibility', 1)]
            
            # titi test
            slot = bpy.context.scene.wow_m2_root_elements.lights.add()
            slot.pointer = obj

            # load global sequences
            for j, seq_index in enumerate(self.global_sequences):
                anim = bpy.context.scene.wow_m2_animations[seq_index]
                action_name = "LT_{}_{}_Global_Sequence_{}".format(i, obj.name, str(j).zfill(3))

                anim_pair = anim.anim_pairs.add()
                anim_pair.type = 'OBJECT'
                anim_pair.object = obj

                for channel, array_length in channels:
                    if getattr(light, channel).global_sequence == seq_index:
                        animate_property(anim_pair, light, channel, array_length, action_name, 0)

                if not anim_pair.action:
                    anim.anim_pairs.remove(-1)

            # load animations
            for j, anim_index in enumerate(self.animations):
                anim = bpy.context.scene.wow_m2_animations[j + n_global_sequences]
                sequence = self.m2.root.sequences[anim_index]

                field_name = seq_name_table.get_sequence_name(sequence.id)
                action_name = 'LT_{}_UnkAnim'.format(i, str(j).zfill(3)) if not field_name \
                    else "LT_{}_{}_({})".format(i, str(j).zfill(3), field_name, sequence.variation_index)

                anim_pair = anim.anim_pairs.add()
                anim_pair.type = 'OBJECT'
                anim_pair.object = obj

                for channel, array_length in channels:
                    if getattr(light, channel).global_sequence < 0:
                        animate_property(anim_pair, light, channel, array_length, action_name, anim_index)

                if not anim_pair.action:
                    anim.anim_pairs.remove(-1)

    def load_events(self):

        if not len(self.m2.root.events):
            print("\nNo events found to import.")
            return
        else:
            print("\nImport events.")

        for event in self.m2.root.events:
            bpy.ops.object.empty_add(type='CUBE', location=(0, 0, 0))
            obj = bpy.context.view_layer.objects.active
            obj.scale = (0.019463, 0.019463, 0.019463)
            bpy.ops.object.constraint_add(type='CHILD_OF')
            constraint = obj.constraints[-1]
            constraint.target = self.rig
            obj.parent = self.rig
            bone = self.m2.root.bones[event.bone]
            constraint.subtarget = bone.name

            bl_edit_bone = self.rig.data.bones[bone.name]
            obj.location = bl_edit_bone.matrix_local.inverted() @ Vector(event.position)
            token = M2EventTokens.get_event_name(event.identifier)
            obj.name = "Event_{}".format(token)
            obj.wow_m2_event.enabled = True

            try:
                obj.wow_m2_event.token = event.identifier
            except TypeError:
                print('Warning: unknown event token \"{}\".'.format(event.identifier))

            if token in ('PlayEmoteSound',
                         'DoodadSoundUnknown',
                         'DoodadSoundOneShot',
                         'GOPlaySoundKitCustom',
                         'GOAddShake'):
                obj.wow_m2_event.data = event.data

            # animate event firing
            obj.animation_data_create()
            obj.animation_data.action_blend_type = 'ADD'
            seq_name_table = M2SequenceNames()
            n_global_sequences = len(self.global_sequences)
            
            #titi test
            slot = bpy.context.scene.wow_m2_root_elements.events.add()
            slot.pointer = obj

            # load global sequences
            if event.enabled.global_sequence >= 0:
                anim = bpy.context.scene.wow_m2_animations[event.enabled.global_sequence]
                if not event.enabled.timestamps.n_elements \
                or not event.enabled.timestamps[0]:
                    return

                anim_pair = anim.anim_pairs.add()
                anim_pair.type = 'OBJECT'
                anim_pair.object = obj

                name = 'ET_{}_{}_UnkAnim'.format(token, str(event.enabled.global_sequence).zfill(3))

                self._bl_create_action(anim_pair, name)
                self._bl_create_fcurves(anim_pair.action, "", self._bl_convert_track_dummy, 1, 0, 'wow_m2_event.fire',
                                        event.enabled)

                return

            # load animations
            for j, anim_index in enumerate(self.animations):
                anim = bpy.context.scene.wow_m2_animations[j + n_global_sequences]
                sequence = self.m2.root.sequences[anim_index]

                if event.enabled.timestamps.n_elements > anim_index:
                    if not event.enabled.timestamps[anim_index]:
                        continue

                    anim_pair = anim.anim_pairs.add()
                    anim_pair.type = 'OBJECT'
                    anim_pair.object = obj

                    field_name = seq_name_table.get_sequence_name(sequence.id)
                    name = 'ET_{}_{}_UnkAnim'.format(token, str(anim_index).zfill(3)) if not field_name \
                           else "ET_{}_{}_{}_({})".format(token, str(anim_index).zfill(3), field_name,
                                                          sequence.variation_index)

                    self._bl_create_action(anim_pair, name)
                    self._bl_create_fcurves(anim_pair.action, "", self._bl_convert_track_dummy, 1, j,
                                            'wow_m2_event.fire', event.enabled)

    def load_cameras(self):

        def animate_camera_loc(anim_pair, name, cam_track, anim_index):

            try:
                frames = cam_track.timestamps[anim_index]
                track = cam_track.values[anim_index]
            except IndexError:
                return

            if not len(frames) > 1:
                return

            # create a parent for curve segments
            p_obj = bpy.data.objects.new(name, None)
            bpy.context.collection.objects.link(p_obj)

            curves = []
            for i in range(1, len(frames)):
                frame1 = frames[i - 1] * 0.0266666
                frame2 = frames[i] * 0.0266666

                curve_name = '{}_Path'.format(anim_pair.object.name)
                curve = bpy.data.curves.new(name=curve_name, type='CURVE')
                curve_obj = bpy.data.objects.new(name=curve_name, object_data=curve)
                curve_obj.parent = p_obj
                bpy.context.collection.objects.link(curve_obj)

                curve.dimensions = '3D'
                curve.resolution_u = 64

                spline = curve.splines.new('BEZIER')
                spline.resolution_u = 64
                spline.bezier_points.add(count=1)

                for j, k in enumerate((i - 1, i)):
                    spline_point = spline.bezier_points[j]
                    spline_point.co = Vector(track[k].value) + anim_pair.object.location
                    spline_point.handle_left_type = 'FREE'
                    spline_point.handle_left = Vector(track[k].in_tan) + anim_pair.object.location
                    spline_point.handle_right_type = 'FREE'
                    spline_point.handle_right = Vector(track[k].out_tan) + anim_pair.object.location

                curve_slot = anim_pair.object.wow_m2_camera.animation_curves.add()
                curve_slot.object = curve_obj
                curve_slot.duration = frame2 - frame1

                curves.append(curve_obj)

            # zero in tan of frist point and out tan of last point
            first_point = curves[0].data.splines[0].bezier_points[0]
            first_point.handle_left = first_point.co
            last_point = curves[-1].data.splines[0].bezier_points[-1]
            last_point.handle_right = last_point.co

            # create contraints and set appropriate drivers for each curve
            anim_pair.object.location = (0, 0, 0)

            # active object is required for constraints / drivers to install properly
            bpy.context.view_layer.objects.active = anim_pair.object
            update_follow_path_constraints(None, bpy.context)

        def animate_camera_roll(anim_pair, name, cam_track, anim_index):

            action = anim_pair.action

            try:
                frames = cam_track.timestamps[anim_index]
                track = cam_track.values[anim_index]
            except IndexError:
                return

            if not len(frames):
                return

            if not action:
                action = anim_pair.action = bpy.data.actions.new(name=name)

            # create fcurve
            f_curve = action.fcurves.new(data_path='rotation_axis_angle', index=0, action_group='Roll')

            # init keyframes on the curve
            f_curve.keyframe_points.add(len(frames))

            # set translation values for each channel
            for i, timestamp in enumerate(frames):
                frame = timestamp * 0.0266666

                keyframe = f_curve.keyframe_points[i]
                keyframe.co = frame, track[i].value
                keyframe.handle_left = frame, track[i].in_tan
                keyframe.handle_left_type = 'ALIGNED'
                keyframe.handle_right = frame, track[i].out_tan
                keyframe.handle_right_type = 'ALIGNED'
                keyframe.interpolation = 'BEZIER'  # TODO: hermite

        if not len(self.m2.root.cameras):
            print("\nNo cameras found to import.")
            return
        else:
            print("\nImporting cameras.")

        camera_names = {
            0: "PortraitCam",
            1: "CharInfoCam",
            -1: "MiscCam"
        }

        for camera in self.m2.root.cameras:

            # create camera object
            cam = bpy.data.cameras.new(camera_names[camera.type])
            obj = bpy.data.objects.new(camera_names[camera.type], cam)
            bpy.context.collection.objects.link(obj)

            obj.location = camera.position_base
            obj.wow_m2_camera.type = str(camera.type)
            obj.data.clip_start = camera.near_clip
            obj.data.clip_end = camera.far_clip
            obj.data.lens_unit = 'FOV'
            obj.data.angle = camera.fov

            obj.animation_data_create()
            obj.animation_data.action_blend_type = 'ADD'

            # create camera target object
            t_obj = bpy.data.objects.new("{}_Target".format(obj.name), None)
            bpy.context.collection.objects.link(t_obj)

            t_obj.location = camera.target_position_base
            t_obj.wow_m2_camera.enabled = True
            t_obj.empty_display_size = 0.07
            t_obj.empty_display_type = 'CONE'
            t_obj.rotation_mode = 'AXIS_ANGLE'
            t_obj.rotation_axis_angle = (0, 1, 0, 0)
            t_obj.lock_rotation = (True, True, True)

            t_obj.animation_data_create()
            t_obj.animation_data.action_blend_type = 'ADD'

            # animate camera

            # load global sequences
            n_global_sequences = len(self.global_sequences)
            for j, seq_index in enumerate(self.global_sequences):
                anim = bpy.context.scene.wow_m2_animations[j]

                c_anim_pair = anim.anim_pairs.add()
                c_anim_pair.type = 'OBJECT'
                c_anim_pair.object = obj

                t_anim_pair = anim.anim_pairs.add()
                t_anim_pair.type = 'OBJECT'
                t_anim_pair.object = t_obj

                name = '{}_UnkAnim'.format(str(j).zfill(3))
                c_name = "CM{}".format(name)
                t_name = "CT{}".format(name)

                if camera.positions.global_sequence == seq_index:
                    animate_camera_loc(c_anim_pair, c_name, camera.positions, 0)

                if camera.target_position.global_sequence == seq_index:
                    animate_camera_loc(t_anim_pair, t_name, camera.target_position, 0)

                if camera.roll.global_sequence == seq_index:
                    animate_camera_roll(t_anim_pair, t_name, camera.roll, 0)

            # load animations
            anim_data_table = M2SequenceNames()
            for j, anim_index in enumerate(self.animations):
                anim = bpy.context.scene.wow_m2_animations[j + n_global_sequences]
                sequence = self.m2.root.sequences[anim_index]

                c_anim_pair = anim.anim_pairs.add()
                c_anim_pair.type = 'OBJECT'
                c_anim_pair.object = obj

                t_anim_pair = anim.anim_pairs.add()
                t_anim_pair.type = 'OBJECT'
                t_anim_pair.object = t_obj

                field_name = anim_data_table.get_sequence_name(sequence.id)
                name = '_{}_UnkAnim'.format(str(anim_index).zfill(3)) if not field_name \
                    else "_{}_{}_({})".format(str(anim_index).zfill(3), field_name, sequence.variation_index)

                c_name = "CM{}".format(name)
                t_name = "CT{}".format(name)

                if camera.positions.global_sequence < 0:
                    animate_camera_loc(c_anim_pair, c_name, camera.positions, anim_index)

                if camera.target_position.global_sequence < 0:
                    animate_camera_loc(t_anim_pair, t_name, camera.target_position, anim_index)

                if camera.roll.global_sequence < 0:
                    animate_camera_roll(t_anim_pair, t_name, camera.roll, anim_index)

            # set target for camera
            bpy.context.view_layer.objects.active = obj  # active object is required for constraints to install properly
            obj.wow_m2_camera.target = t_obj

    def load_particles(self):
        if not len(self.m2.root.particles):
            print("\nNo particles found to import.")
            return
        else:
            print("\nImport particles.")

        for particle in self.m2.root.particles:
            if particle.emitter_type == 1:
                bpy.ops.mesh.primitive_plane_add(radius=1, location=(0, 0, 0))
                emitter = bpy.context.view_layer.objects.active
                emitter.dimensions[0] = particle.emission_area_length
                emitter.dimensions[1] = particle.emission_area_width

            elif particle.emitter_type == 2:
                bpy.ops.mesh.primitive_uv_sphere_add(size=particle.emission_area_length, location=(0, 0, 0))
                emitter = bpy.context.view_layer.objects.active
                # TODO: emission_area_with

            elif particle.emitter_type == 3:
                pass

    def load_collision(self):

        if not len(self.m2.root.collision_vertices):
            print("\nNo collision mesh found to import.")
            return
        else:
            print("\nImporting collision mesh.")

        vertices = [vertex for vertex in self.m2.root.collision_vertices]
        triangles = [self.m2.root.collision_triangles[i:i+3]
                     for i in range(0, len(self.m2.root.collision_triangles), 3)]

        # create mesh
        mesh = bpy.data.meshes.new(self.m2.root.name.value)
        mesh.from_pydata(vertices, [], triangles)

        for poly in mesh.polygons:
            poly.use_smooth = True

        # create object
        obj = bpy.data.objects.new('Collision', mesh)
        bpy.context.collection.objects.link(obj)
        obj.wow_m2_geoset.collision_mesh = True
        obj.hide_set(True)
        # TODO: add transparent material

    def prepare_export_axis(self, forward_axis):
        if forward_axis == 'X+':
            self.axis_order = [0,1]
            self.axis_polarity = [1,1]
        elif forward_axis == 'X-':
            self.axis_order = [0,1]
            self.axis_polarity = [-1,-1]
        elif forward_axis == 'Y+':
            self.axis_order = [1,0]
            self.axis_polarity = [1,-1]
        elif forward_axis == 'Y-':
            self.axis_order = [1,0]
            self.axis_polarity = [-1,1]
        else:
            raise ValueError(f'Invalid forward axis: {forward_axis}')

    def _convert_vec(self,vec):
        return (
            vec[self.axis_order[0]]*self.axis_polarity[0],
            vec[self.axis_order[1]]*self.axis_polarity[1],
            vec[2]
        )

    def prepare_pose(self, selected_only):
        self.old_mode = bpy.context.object.mode
        self.old_selections = [obj for obj in bpy.context.selected_objects]
        self.old_active = bpy.context.active_object

        # TODO: this is a temporary fix to reset pose, because wbs uses the wrong data
        #       when reading bone and vertex positions.
        objects = bpy.context.selected_objects if selected_only else bpy.context.scene.objects

        for obj in objects:
            if obj.type != 'ARMATURE':
                continue
            if obj.animation_data and obj.animation_data.action:
                self.old_actions.append((obj,obj.animation_data.action))

            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.select_all(action='DESELECT')
            action = bpy.data.actions.new(name=obj.name+"__RESET_POSE")
            self.reset_pose_actions.append(action)
            for bone in obj.data.bones:
                def make_curve(data_path,index, value):
                    curve = action.fcurves.new(data_path = data_path, index = index)
                    curve.keyframe_points.add(1)
                    curve.keyframe_points[0].co[0] = 0
                    curve.keyframe_points[0].co[1] = value

                make_curve(f"pose.bones[\"{bone.name}\"].rotation_quaternion", 0, 1)
                for i in range(3):
                    make_curve(f"pose.bones[\"{bone.name}\"].location", i, 0)
                    make_curve(f"pose.bones[\"{bone.name}\"].scale", i, 1)
                    make_curve(f"pose.bones[\"{bone.name}\"].rotation_quaternion", i+1, 0)
            obj.animation_data.action = action

    def restore_pose(self):
        for (obj,action) in self.old_actions:
            obj.animation_data.action = action

        for action in self.reset_pose_actions:
            bpy.data.actions.remove(action)

        bpy.ops.object.select_all(action='DESELECT')
        for obj in self.old_selections:
            obj.select_set(True)
        if self.old_active:
            bpy.context.view_layer.objects.active = self.old_active
        if self.old_mode:
            bpy.ops.object.mode_set( mode = self.old_mode )

    def save_properties(self, filepath, selected_only):
        self.m2.root.name.value = os.path.basename(filepath)
        objects = bpy.context.selected_objects if selected_only else bpy.context.scene.objects

        b_min, b_max = get_objs_boundbox_world(filter(lambda ob: not ob.wow_m2_geoset.collision_mesh
                                                                and ob.type == 'MESH'
                                                                and not ob.hide_get(), objects))
        self.m2.root.bounding_box.min = b_min
        self.m2.root.bounding_box.max = b_max
        self.m2.root.bounding_sphere_radius = sqrt((b_max[self.axis_order[0]]-b_min[self.axis_order[0]]) ** 2
                                                + (b_max[self.axis_order[1]]-b_min[self.axis_order[1]]) ** 2
                                                + (b_max[2]-b_min[2]) ** 2) / 2

        # TODO: flags, collision bounding box

    def save_bones(self, selected_only):

        def add_bone(bl_bone):
            key_bone_id = int(bl_bone.wow_m2_bone.key_bone_id)
            flags = construct_bitfield(bl_bone.wow_m2_bone.flags)
            parent_bone = self.bone_ids[bl_bone.parent.name] if bl_bone.parent else -1
            pivot = self._convert_vec(bl_bone.head)

            m2_bone = self.bone_ids[bl_bone.name] = self.m2.add_bone(
                pivot,
                key_bone_id,
                flags,
                parent_bone,
                bl_bone.wow_m2_bone.submesh_id,
                ctypes.c_uint(bl_bone.wow_m2_bone.bone_name_crc).value
            )

        rigs = list(filter(lambda ob: ob.type == 'ARMATURE' and not ob.hide_get(), bpy.context.scene.objects))

        if len(rigs) > 1:
            raise Exception('Error: M2 exporter does not support more than one armature. Hide or remove the extra one.')

        for rig in rigs:
            self.rig = rig
            bpy.context.view_layer.objects.active = rig
            bpy.ops.object.mode_set(mode='EDIT')

            armature = rig.data

            has_unsorted_bones = False
            for bone in armature.edit_bones:
                if bone.wow_m2_bone.sort_index < 0:
                    has_unsorted_bones = True
                    break

            if has_unsorted_bones:
                # find root bone, check if we only have one root bone
                root_bone = None
                global_bones = []
                for bone in armature.edit_bones:
                    if root_bone is not None and bone.parent is None and bone.children:
                        raise Exception('Error: M2 exporter does not support more than one global root bone.')

                    if bone.parent is None:
                        if bone.children:
                            root_bone = bone
                            add_bone(root_bone)
                        else:
                            global_bones.append(bone)

                # add global bones
                for bone in global_bones:
                    add_bone(bone)

                # find root keybone, write additional bones
                root_keybone = None

                if root_bone:
                    for bone in root_bone.children:

                        if bone.wow_m2_bone.key_bone_id == '26':
                            root_keybone = bone
                            continue

                        add_bone(bone)
                        for child_bone in bone.children_recursive:
                            add_bone(child_bone)

                # write root keybone and its children
                if root_keybone:
                    add_bone(root_keybone)
                    for bone in root_keybone.children_recursive:
                        add_bone(bone)
            else:
                all_bones = [bone for bone in armature.edit_bones]
                all_bones.sort(key=lambda x:x.wow_m2_bone.sort_index)
                for bone in all_bones: add_bone(bone)

            bpy.ops.object.mode_set(mode='OBJECT')

            break

        else:
            # Add an empty bone, if the model is not animated
            if selected_only:
                bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY')
                origin = self._convert_vec(get_origin_position())
            else:
                origin = self._convert_vec(get_origin_position())

        # TODO: should we always do this?
        if len(self.m2.root.key_bone_lookup) == 0:
            self.m2.root.key_bone_lookup.append(-1)

    def save_cameras(self):
        cameras = [cam for cam in bpy.data.objects if cam.type == 'CAMERA']
        cameras.sort(key=lambda cam: int(cam.wow_m2_camera.type) if int(cam.wow_m2_camera.type) >= 0 else 3)
        for i, blender_cam in enumerate(cameras):
            self.camera_ids[blender_cam.name] = i
            m2_cam = M2Camera()
            m2_cam.position_base = self._convert_vec(blender_cam.location)
            m2_cam.type = int(blender_cam.wow_m2_camera.type)
            m2_cam.near_clip = blender_cam.data.clip_start
            m2_cam.far_clip = blender_cam.data.clip_end
            m2_cam.fov = blender_cam.data.angle

            if blender_cam.wow_m2_camera.target:
                m2_cam.target_position_base = self._convert_vec(blender_cam.wow_m2_camera.target.location)
                self.camera_target_ids[blender_cam.wow_m2_camera.target.name] = i

            self.m2.root.cameras.append(m2_cam)
            if m2_cam.type >= 0:
                while len(self.m2.root.camera_lookup_table) <= m2_cam.type:
                    self.m2.root.camera_lookup_table.append(-1)
                self.m2.root.camera_lookup_table.set_index(m2_cam.type, i)

    def save_attachments(self):
        attachments = [obj for obj in bpy.data.objects if obj.type == 'EMPTY' and obj.wow_m2_attachment.enabled]
        attachments.sort(key=lambda att: int(att.wow_m2_attachment.type) if int(att.wow_m2_attachment.type) >= 0 else float('inf'))
        for i, bl_att in enumerate(attachments):
            self.attachment_ids[bl_att.name] = i
            att = M2Attachment()
            self.m2.root.attachments.append(att)
            att.id = int(bl_att.wow_m2_attachment.type)
            if len(bl_att.constraints) > 0:
                # TODO: properly find constraint
                att.bone = self.bone_ids[bl_att.constraints[0].subtarget]
                att.position = self._convert_vec(bl_att.location)
            while len(self.m2.root.attachment_lookup_table) <= att.id:
                self.m2.root.attachment_lookup_table.append(0xffff)
            self.m2.root.attachment_lookup_table.set_index(att.id,i)

    def save_events(self):
        events = [obj for obj in bpy.data.objects if obj.type == 'EMPTY' and obj.wow_m2_event.enabled]
        for i, bl_evt in enumerate(events):
            self.event_ids[bl_evt.name] = i
            evt = M2Event()
            self.m2.root.events.append(evt)
            evt.identifier = bl_evt.wow_m2_event.token
            token = M2EventTokens.get_event_name(evt.identifier)
            if len(bl_evt.constraints) > 0:
                # TODO: properly find constraint
                evt.bone = self.bone_ids[bl_evt.constraints[0].subtarget]
                evt.position = bl_evt.location
            if token in ('PlayEmoteSound',
                'DoodadSoundUnknown',
                'DoodadSoundOneShot',
                'GOPlaySoundKitCustom',
                'GOAddShake'):
                evt.data = bl_evt.wow_m2_event.data

    def save_lights(self):
        lights = [light for light in bpy.data.objects if light.type == 'LIGHT' and light.data.wow_m2_light.enabled]
        for i, bl_light in enumerate(lights):
            self.light_ids[bl_light.name] = i
            light = M2Light()
            self.m2.root.lights.append(light)
            light.type = int(bl_light.data.wow_m2_light.type)
            if len(bl_light.constraints) > 0:
                # TODO: properly find constraint
                light.bone = self.bone_ids[bl_light.constraints[0].subtarget]
            light.position = self._convert_vec(bl_light.location)

    def save_animations(self):
        def bl_to_m2_time(bl):
            return int(round(bl/0.02666666))

        def bl_to_m2_quat(n):
            n = max(min(n,1),-1) * 32767
            return int(n + 32767 if n <= 0 else n-32768)

        def bl_to_m2_interpolation(interpolation):
            if interpolation == 'CONSTANT': return 0
            if interpolation == 'LINEAR': return 1
            if interpolation == 'BEZIER': return 2
            if interpolation == 'CUBIC': return 3
            raise AssertionError('Invalid interpolation type ' + interpolation)

        def bl_find_interpolation(fcurve):
            last_interp = None
            for point in fcurve.keyframe_points:
                if last_interp is None:
                    last_interp = point.interpolation
                else:
                    # wow does not support changing interpolation type
                    assert last_interp == point.interpolation
            return last_interp

        # Used to measure the highest duration for any keyframe of a given sequence index
        global_seq_durations = {}
        seq_durations = {}

        # Used to ensure consistent data between tracks
        track_global_sequences = {}
        track_interpolations = {}

        class TrackCompound:
            def __init__(self,seq_id,global_seq_id,data):
                self.seq_id = seq_id
                self.global_seq_id = global_seq_id
                self.data = data

            def get_paths(self):
                return self.data.keys()

            def get_frames(self, path):
                return self.data[path]['frames']

            def get_interpolation(self, path):
                return self.data[path]['interpolation']

            def write_track(self, path,m2_track,value_type,converter = lambda x: x):
                if not path in self.data:
                    return

                frames = self.get_frames(path)
                if len(frames) == 0:
                    return

                while len(m2_track.timestamps) <= self.seq_id:
                    m2_track.timestamps.add(M2Array(uint32))
                m2_times = m2_track.timestamps[seq_id]

                highest_time = 0
                if not value_type is None:
                    while len(m2_track.values) <= self.seq_id:
                        m2_track.values.add(M2Array(value_type))
                    m2_values = m2_track.values[seq_id]
                    for (time,value) in frames:
                        highest_time = bl_to_m2_time(time)
                        m2_times.add(highest_time)
                        m2_values.add(converter(value))
                else:
                    for (time,_) in frames:
                        highest_time = bl_to_m2_time(time)
                        m2_times.add(highest_time)

                if self.global_seq_id >= 0:
                    if not self.global_seq_id in global_seq_durations or highest_time > global_seq_durations[self.global_seq_id]:
                        global_seq_durations[self.global_seq_id] = highest_time
                else:
                    if not self.seq_id in seq_durations or highest_time > seq_durations[self.seq_id]:
                        seq_durations[self.seq_id] = highest_time

                if not m2_track in track_global_sequences:
                    track_global_sequences[m2_track] = self.global_seq_id
                    m2_track.global_sequence = self.global_seq_id
                else:
                    assert track_global_sequences[m2_track] == self.global_seq_id

                if not m2_track in track_interpolations:
                    track_interpolations[m2_track] = self.get_interpolation(path)
                    m2_track.interpolation_type = bl_to_m2_interpolation(self.get_interpolation(path))
                else:
                    assert track_interpolations[m2_track] == self.get_interpolation(path)

        def write_data_compound(seq_id,global_seq_id, pair, callback):
            compound_data = {} # { channel: {interpolation:string, keyframes: {[timestamps]:<PointType>[]}} }
            for curve in pair.action.fcurves:
                def next_item(cur,key,val):
                    if not key in cur: cur[key] = val
                    return cur[key]
                curve_data = next_item(compound_data, curve.data_path, {})
                curve_data["interpolation"] = bl_find_interpolation(curve)
                curve_frames = next_item(curve_data,"frames",{})
                index = int(curve.array_index)
                for i,point in enumerate(curve.keyframe_points):
                    keyframe_data = next_item(curve_frames,point.co[0],[])
                    while len(keyframe_data) <= index:
                        keyframe_data.append(None)
                    keyframe_data[index] = point.co[1]

            for name,tracks in compound_data.items():
                frames = tracks['frames'] = [(timestamp,tuple(values) if len(values) > 1 else values[0]) for timestamp,values in tracks['frames'].items()]
                frames.sort(key=lambda frame:frame[0])

            callback(TrackCompound(seq_id,global_seq_id,compound_data), pair)

        def write_light(cpd, pair):
            m2_light = self.m2.root.lights.values[self.light_ids[pair.object.name]]
            cpd.write_track('data.wow_m2_light.ambient_color',
                m2_light.ambient_color,vec3D)

            cpd.write_track('data.wow_m2_light.diffuse_color',
                m2_light.diffuse_color,vec3D)

            cpd.write_track('data.wow_m2_light.ambient_intensity',
                m2_light.ambient_intensity,float32)

            cpd.write_track('data.wow_m2_light.diffuse_intensity',
                m2_light.diffuse_intensity,float32)

            cpd.write_track('data.wow_m2_light.attenuation_start',
                m2_light.attenuation_start,float32)

            cpd.write_track('data.wow_m2_light.attenuation_end',
                m2_light.attenuation_end,float32)

            cpd.write_track('data.wow_m2_light.visibility',
                m2_light.visibility,uint8, lambda x: int(x)
            )

        def write_attachment(cpd, pair):
            m2_attachment = self.m2.root.attachments.values[self.attachment_ids[pair.object.name]]
            cpd.write_track('wow_m2_attachment.animate',
                m2_attachment.animate_attached,boolean,lambda x: bool(x))

        def write_bone(cpd, pair):
            for path in cpd.get_paths():
                bone = re.search('"(.+?)"',path).group(1)
                curve_type = re.search('([a-zA-Z_]+)$',path).group(0)

                m2_bone = self.m2.root.bones.values[self.bone_ids[bone]]
                m2_bone.flags = m2_bone.flags | 512

                if curve_type == 'rotation_quaternion':
                    cpd.write_track(path,m2_bone.rotation,M2CompQuaternion,
                        lambda x: M2CompQuaternion((
                            bl_to_m2_quat(x[0]),
                            bl_to_m2_quat(x[self.axis_order[0] + 1] * self.axis_polarity[0]),
                            bl_to_m2_quat(x[self.axis_order[1] + 1] * self.axis_polarity[1]),
                            bl_to_m2_quat(x[3])
                        ))
                    )

                if curve_type == 'scale':
                    cpd.write_track(path,m2_bone.scale,vec3D,
                        lambda x: self._convert_vec(x))

                # TODO: this probably doesn't work if bone is not at 0,0,0
                if curve_type == 'location':
                    cpd.write_track(path,m2_bone.translation,vec3D,
                        lambda x: self._convert_vec((x[1],-x[0],x[2])))

        def write_scene(cpd, pair):
            def extract_scene_data(path):
                index = re.search('\\[(.+?)\\]', path).group(1)
                data_path = re.search('\\]\.(.+)', path).group(1)
                return (int(index),data_path)

            for path in cpd.get_paths():
                if path.startswith("wow_m2_colors"):
                    (index,data_path) = extract_scene_data(path)
                    while len(self.m2.root.colors) <= index:
                        self.m2.root.colors.append(M2Color())

                    col = self.m2.root.colors[index]
                    col_name = bpy.context.scene.wow_m2_colors[index].name
                    if col_name in self.color_ids:
                        old_index = self.color_ids[col_name]
                        assert old_index == index,f'Color {col_name} has multiple ids: {index},{old_index}'
                    else:
                        self.color_ids[col_name] = index

                    if data_path == 'color':
                        cpd.write_track(path,col.color,vec3D)
                    if data_path == 'alpha':
                        cpd.write_track(path,col.alpha,fixed16,lambda x: int(x*0x7fff))

                if path.startswith("wow_m2_transparency"):
                    (index,_) = extract_scene_data(path)
                    while len(self.m2.root.texture_weights) <= index:
                        self.m2.root.texture_weights.append(M2Track(fixed16,M2Header))

                    # (3.3.5a)
                    # The transparency lookup table is seemingly worthless,
                    # it always just contains 0,1,2,3,4... in blizzard m2s
                    lt = self.m2.root.transparency_lookup_table
                    while len(lt) <= index:
                        lt.append(len(lt))

                    weight = self.m2.root.texture_weights.values[index]

                    weight_name = bpy.context.scene.wow_m2_transparency[index].name
                    if weight_name in self.transparency_ids:
                        old_index = self.transparency_ids[weight_name]
                        assert old_index == index,f'Transparency {weight_name} has multiple ids: {index},{old_index}'
                    else:
                        self.transparency_ids[weight_name] = index

                    cpd.write_track(path,weight,fixed16, lambda x: int(x*0x7fff))

        def write_event(cpd, pair):
            m2_event = self.m2.root.events[self.event_ids[pair.object.name]]
            cpd.write_track("wow_m2_event.fire",m2_event.enabled,None)

        def write_texture_transform(cpd, pair):
            self.texture_transform_ids[pair.object.name] = len(self.m2.root.texture_transforms)
            trans = M2TextureTransform()
            self.m2.root.texture_transforms.append(trans)

            cpd.write_track("location",trans.translation,vec3D)
            cpd.write_track("scale",trans.scaling,vec3D)

            # TODO: fix this with axis order!
            cpd.write_track("rotation_quaternion",trans.rotation,quat,
                lambda x: (
                     x[2],
                    -x[1],
                     x[3],
                     x[0]
                )
            )

        def write_ribbon(cpd, pair):
            pass

        def write_particle(cpd, pair):
            pass

        def write_camera(cpd, pair):
            pass

        def write_camera_target(cpd, pair):
            m2_camera = self.m2.root.cameras[self.camera_target_ids[pair.object.name]]
            def convert_spline(x):
                key = M2SplineKey(float32)
                key.value = x
                return key
            # TODO: can't write this because the track thinks the m2array type is generic for some reason
            #cpd.write_track("rotation_axis_angle",m2_camera.roll,float32,convert_spline)

        self.m2.root.transparency_lookup_table.add(len(self.m2.root.texture_weights))

        global_seq_count = 0
        for wow_seq in self.scene.wow_m2_animations:
            if wow_seq.is_global_sequence:
                global_seq_count += 1

        for wow_seq in self.scene.wow_m2_animations:
            seq_id = 0
            global_seq_id = -1

            if wow_seq.is_global_sequence:
                global_seq_id = len(self.m2.root.global_sequences)
                self.m2.root.global_sequences.append(0)
            else:
                is_alias = "64" in wow_seq.flags

                # TODO using root boundings hwen not using preset, better than nothing

                seq_id = self.m2.add_anim(
                    int(wow_seq.animation_id),
                    wow_seq.chain_index, # titi, to test
                    (0,0), # set it later
                    wow_seq.move_speed,
                    construct_bitfield(wow_seq.flags),
                    wow_seq.frequency,
                    (wow_seq.replay_min, wow_seq.replay_max),
                    wow_seq.blend_time,  # TODO: multiversioning
                    ((self.m2.root.bounding_box.min,self.m2.root.bounding_box.max),
                        self.m2.root.bounding_sphere_radius),
                    wow_seq.VariationNext,
                    wow_seq.alias_next
                )

            for pair in wow_seq.anim_pairs:
                if (pair.type != 'SCENE' and pair.object is None) or pair.action is None:
                    continue

                if pair.type == 'SCENE':
                    write_data_compound(seq_id, global_seq_id, pair, write_scene)
                elif pair.object.type == 'ARMATURE':
                    write_data_compound(seq_id, global_seq_id, pair, write_bone)
                elif pair.object.type == 'LIGHT':
                    write_data_compound(seq_id, global_seq_id, pair, write_light)
                elif pair.object.type == 'CAMERA':
                    write_data_compound(seq_id, global_seq_id, pair, write_camera)
                elif pair.object.type == 'CAMERA_TARGET':
                    write_data_compound(seq_id, global_seq_id, pair, write_camera_target)
                elif pair.object.type == 'EMPTY':
                    if pair.object.wow_m2_attachment.enabled:
                        write_data_compound(seq_id, global_seq_id, pair, write_attachment)
                    elif pair.object.wow_m2_event.enabled:
                        write_data_compound(seq_id, global_seq_id, pair, write_event)
                    elif pair.object.wow_m2_camera.enabled:
                        write_data_compound(seq_id, global_seq_id, pair, write_camera_target)
                    elif pair.object.wow_m2_uv_transform.enabled:
                        write_data_compound(seq_id, global_seq_id, pair, write_texture_transform)

            for global_seq_id,duration in global_seq_durations.items():
                assert global_seq_id < len(self.m2.root.global_sequences)
                self.m2.root.global_sequences.set_index(global_seq_id,duration)

            for seq_id,duration in seq_durations.items():
                assert seq_id < len(self.m2.root.sequences)
                self.m2.root.sequences[seq_id].duration = duration

        # Add dummy texture weight
        if len(self.m2.root.texture_weights) == 0:
            texture_weight = self.m2.root.texture_weights.new()
            if self.m2.root.version >= M2Versions.WOTLK:
                texture_weight.timestamps.new().add(0)
                texture_weight.values.new().add(32767)

        # Write alias durations
        for i,wow_seq in enumerate(self.m2.root.sequences.values):
            if not 64 & wow_seq.flags: continue
            cur_seq = wow_seq
            visited = [i]
            while 64 & cur_seq.flags:
                assert cur_seq.alias_next != -1,"alias action without alias_next set"
                assert not (cur_seq.alias_next in visited),f"Circular alias_next: {cur_seq.alias_next} ({visited})"
                assert cur_seq.alias_next < len(self.m2.root.sequences.values)
                visited.append(cur_seq.alias_next)
                cur_seq = self.m2.root.sequences.values[cur_seq.alias_next]
            wow_seq.duration = cur_seq.duration

        if len(self.m2.root.sequences) == 0:
            self.m2.add_dummy_anim_set((0,0,0))

        while len(self.m2.root.sequence_lookup) < 5: # don't crash creatures
            self.m2.root.sequence_lookup.append(0xffff)
        if self.m2.root.sequence_lookup[4] == -1:
            self.m2.root.sequence_lookup[4] = 0



    def save_geosets(self, selected_only, fill_textures):
        objects = bpy.context.selected_objects if selected_only else bpy.context.scene.objects
        if not objects:
            raise Exception('Error: no mesh found on the scene or selected.')

        # deselect all objects before saving geosets
        bpy.ops.object.select_all(action='DESELECT')

        proxy_objects = []
        for obj in filter(lambda ob: not ob.wow_m2_geoset.collision_mesh and ob.type == 'MESH' and not ob.hide_get(), objects):

            new_obj = obj.copy()
            new_obj.data = obj.data.copy()
            proxy_objects.append(new_obj)

            bpy.context.collection.objects.link(new_obj)

            bpy.context.view_layer.objects.active = new_obj
            mesh = new_obj.data

            # security checks

            if not mesh.uv_layers.active:
                raise Exception("Mesh <<{}>> has no UV map.".format(obj.name))

            # apply all modifiers
            if len(obj.modifiers):
                for modifier in obj.modifiers:
                    bpy.ops.object.modifier_apply(modifier=modifier.name)

            # triangulate mesh, delete loose geometry
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.reveal()
            bpy.ops.mesh.quads_convert_to_tris()
            bpy.ops.mesh.delete_loose()
            bpy.ops.mesh.select_all(action='DESELECT')
            bpy.ops.object.mode_set(mode='OBJECT')

            # prepare scene
            ###################################

            # perform edge split
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.seams_from_islands(mark_seams=False, mark_sharp=True)
            bpy.ops.mesh.select_all(action='DESELECT')
            bpy.ops.object.mode_set(mode='OBJECT')

            bpy.ops.object.modifier_add(type='EDGE_SPLIT')
            bpy.context.object.modifiers["EdgeSplit"].use_edge_angle = False
            bpy.ops.object.modifier_apply(modifier="EdgeSplit")

            # smooth edges
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.mark_sharp(clear=True)
            bpy.ops.mesh.select_all(action='DESELECT')
            bpy.ops.object.mode_set(mode='OBJECT')

            # export vertices
            vertices = [self._convert_vec(new_obj.matrix_world @ vertex.co) for vertex in mesh.vertices]
            normals = [self._convert_vec(vertex.normal) for vertex in mesh.vertices]
            tex_coords = [(0.0, 0.0)] * len(vertices)

            for loop in mesh.loops:
                tex_coords[loop.vertex_index] = (mesh.uv_layers.active.data[loop.index].uv[0],
                                                 1 - mesh.uv_layers.active.data[loop.index].uv[1])

            tris = [poly.vertices for poly in mesh.polygons]

            tex_coords2 = []
            if len(mesh.uv_layers) >= 2:
                tex_coords2 = [mesh.uv_layers[1].data[loop.vertex_index].uv for loop in mesh.loops]

            # old system
            # bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY')
            # origin = new_obj.location

            vertx = 0.0
            verty = 0.0
            vertz = 0.0
            vertcount = len(vertices)
            
            for vert in vertices:
                vertx += vert[0]
                verty += vert[1]
                vertz += vert[2]
            
            origin = ( vertx / vertcount, verty / vertcount, vertz / vertcount )
            
            sort_pos = get_obj_boundbox_center(new_obj)
            sort_radius = get_obj_radius(new_obj, sort_pos)

            # collect rig data
            if new_obj.vertex_groups:
                bpy.ops.object.vertex_group_limit_total()

            if self.rig:

                bone_indices = []
                bone_weights = []

                for vertex in mesh.vertices:
                    v_bone_indices = [0, 0, 0, 0]
                    v_bone_weights = [0, 0, 0, 0]

                    for i, group_info in enumerate(vertex.groups):
                        bone_id = self.bone_ids.get(new_obj.vertex_groups[group_info.group].name)
                        weight = group_info.weight

                        if bone_id is None:
                            bone_id = 0
                            weight = 0

                        v_bone_indices[i] = bone_id
                        v_bone_weights[i] = int(weight * 255)

                    bone_indices.append(v_bone_indices)
                    bone_weights.append(v_bone_weights)

            else:
                bone_indices = [[0, 0, 0, 0] for _ in mesh.vertices]
                bone_weights = [[255, 0, 0, 0] for _ in mesh.vertices]

            # add geoset
            g_index = self.m2.add_geoset(vertices, normals, tex_coords, tex_coords2, tris, bone_indices, bone_weights,
                                         origin, sort_pos, sort_radius, int(new_obj.wow_m2_geoset.mesh_part_id))  # TODO: second UV

            for i, material in enumerate(mesh.materials):

                textures = [material.wow_m2_material.texture_1, material.wow_m2_material.texture_2,
                            material.wow_m2_material.texture_3, material.wow_m2_material.texture_4]

                texture_count = 0

                for bl_texture in textures:
                    if bl_texture:
                        texture_count += 1
                        wow_path = bl_texture.wow_m2_texture.path

                        if bl_texture.wow_m2_texture.texture_type == 0:
                            if fill_textures and not wow_path:
                                wow_path = resolve_texture_path(bl_texture.filepath)

                        tmp_tex_id = self.m2.add_texture(wow_path,
                                                     construct_bitfield(bl_texture.wow_m2_texture.flags),
                                                     int(bl_texture.wow_m2_texture.texture_type)
                                                     )
                        if texture_count == 1:
                            tex_id = tmp_tex_id

                tex_unit_coord = material.wow_m2_material.tex_unit_coord
                render_flags = construct_bitfield(material.wow_m2_material.render_flags)
                flags = construct_bitfield(material.wow_m2_material.flags)
                priority_plane = int(material.wow_m2_material.priority_plane)
                bl_mode = int(material.wow_m2_material.blending_mode)
                shader_id = int(material.wow_m2_material.shader)
                mat_layer = int(material.wow_m2_material.layer)
                color_id = self.color_ids[material.wow_m2_material.color] if material.wow_m2_material.color != "" else -1
                transparency_id = self.transparency_ids[material.wow_m2_material.transparency] if material.wow_m2_material.transparency != "" else 0

                self.m2.add_material_to_geoset(g_index, render_flags, bl_mode, flags, shader_id, tex_id,
                                                tex_unit_coord, priority_plane, mat_layer, texture_count, color_id, transparency_id)

            bpy.data.objects.remove(new_obj, do_unlink=True)

        # remove temporary objects
        # for obj in proxy_objects:
        #     bpy.data.objects.remove(obj, do_unlink=True)

    def save_collision(self, selected_only):
        objects = bpy.context.selected_objects if selected_only else bpy.context.scene.objects
        objects = list(filter(lambda ob: ob.wow_m2_geoset.collision_mesh and ob.type == 'MESH', objects))

        proxy_objects = []

        for obj in objects:
            new_obj = obj.copy()
            new_obj.data = obj.data.copy()
            proxy_objects.append(new_obj)

            bpy.context.collection.objects.link(new_obj)

            bpy.context.view_layer.objects.active = new_obj
            mesh = new_obj.data

            # apply all modifiers
            if len(obj.modifiers):
                for modifier in obj.modifiers:
                    bpy.ops.object.modifier_apply(modifier=modifier.name)

            # triangulate mesh, delete loose geometry
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.reveal()
            bpy.ops.mesh.quads_convert_to_tris()
            bpy.ops.mesh.delete_loose()
            bpy.ops.mesh.select_all(action='DESELECT')
            bpy.ops.object.mode_set(mode='OBJECT')

            # collect geometry data
            vertices = [self._convert_vec(tuple(new_obj.matrix_world @ vertex.co)) for vertex in mesh.vertices]
            faces = [tuple([vertex for vertex in poly.vertices]) for poly in mesh.polygons]
            normals = [self._convert_vec(tuple(poly.normal)) for poly in mesh.polygons]

            self.m2.add_collision_mesh(vertices, faces, normals)
            bpy.data.objects.remove(new_obj, do_unlink=True)

        # remove temporary objects
        #for obj in proxy_objects:
        #    bpy.data.objects.remove(obj, do_unlink=True)

        # calculate collision bounding box
        b_min, b_max = get_objs_boundbox_world(objects)
        self.m2.root.collision_box.min = b_min
        self.m2.root.collision_box.max = b_max
        self.m2.root.collision_sphere_radius = sqrt((b_max[self.axis_order[0]] - b_min[self.axis_order[0]]) ** 2
                                                    + (b_max[self.axis_order[1]] - b_min[self.axis_order[1]]) ** 2
                                                    + (b_max[2] - b_min[2]) ** 2) / 2

