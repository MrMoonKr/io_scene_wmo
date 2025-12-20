import ctypes
import io
import os
import re
import sys
import traceback
from functools import partial
from math import asin, atan2, cos, isinf, sin, sqrt

import bpy
from mathutils import Vector

from ..pywowlib.enums.m2_enums import M2AttachmentTypes, M2EventTokens, M2SequenceNames, M2SkinMeshPartID
from ..pywowlib.file_formats.m2_format import *
from ..pywowlib.file_formats.wow_common_types import *
from ..pywowlib.io_utils.types import vec3D
from ..pywowlib.m2_file import M2File
from ..render.m2.shaders import M2ShaderPermutations
from ..third_party.tqdm import tqdm
from ..ui.preferences import get_project_preferences
from ..utils.misc import (
    construct_bitfield,
    get_obj_boundbox_center,
    get_obj_radius,
    get_objs_boundbox_world,
    get_origin_position,
    load_game_data,
    parse_bitfield,
    resolve_texture_path,
)
from . import bl_render
from . import util as util
from .bl_render import load_m2_shader_dependencies, update_m2_mat_node_tree
from .operations import m2_action_logger as log
from .ui.enums import TEXTURE_TYPES, get_texture_type_name, mesh_part_id_menu
from .ui.panels.animation_editor import convert_frequency_percentage, get_frequency_percentage
from .ui.panels.camera import update_follow_path_constraints
from .util import get_bone_groups, make_fcurve_compound, _find_final_alias

class BlenderM2Scene:
    """ This class is used for assembling a Blender scene from an M2 file or saving the scene back to it."""

    def __init__(self, m2: M2File, prefs):
        self.m2 = m2
        self.materials = {}
        self.loaded_textures = {}
        self.bone_ids = {}
        self.attachment_ids = {}
        self.event_ids = {}
        self.camera_ids = {}
        self.camera_target_ids = {}
        self.color_ids = {}
        self.transparency_ids = {}
        self.texture_transform_ids = {}
        self.light_ids = {}
        self.ribbon_ids = {}
        self.particle_ids = {}
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
        self.forward_axis = 'X+'
        self.axis_order = [0,1]
        self.axis_polarity = [1,1]
        self.scale = 1
        self.rig = None
        self.collision_mesh = None
        self.color_transparency = None
        self.settings = prefs
        self.actions = {} # maps action names to actions
        self.final_textures = {}
        self.anim_data_table = M2SequenceNames()
        self.final_events = {}

        self.scene = bpy.context.scene
        
        render = self.scene.render
        self.fps = render.fps / render.fps_base

    def convert_timestamps(self, timestamps, convert=True):
        """Convert a list (or iterable) of timestamps to frames if convert=True."""
        for i, ts in enumerate(timestamps):
            if convert:
                yield i, int(round(ts * (self.fps / 1000)))
            else:
                yield i, ts

    def load_colors(self, collection, timestamp_convert):
        """Import M2 color animation data into the unified color_transparency object."""

        # --- Internal animation helpers ---
        def animate_color(anim_pair, color_track, color_index, anim_index):
            action = anim_pair.action
            try:
                frames = color_track.timestamps[anim_index]
                track = color_track.values[anim_index]
            except IndexError:
                return
            if not frames:
                return

            fcurves = [
                action.fcurves.new(
                    data_path=f"wow_m2_color_transparency.colors[{color_index}].color",
                    index=k,
                    action_group=f"Color_{color_index}"
                )
                for k in range(3)
            ]
            for fc in fcurves:
                fc.keyframe_points.add(len(frames))

            for i, frame in self.convert_timestamps(frames, convert=(timestamp_convert == "Convert")):
                for j in range(3):
                    key = fcurves[j].keyframe_points[i]
                    key.co = frame, track[i][j]
                    key.interpolation = "LINEAR" if color_track.interpolation_type == 1 else "CONSTANT"

        def animate_alpha(anim_pair, alpha_track, color_index, anim_index):
            action = anim_pair.action
            try:
                frames = alpha_track.timestamps[anim_index]
                track = alpha_track.values[anim_index]
            except IndexError:
                return
            if not frames:
                return

            fcurve = action.fcurves.new(
                data_path=f"wow_m2_color_transparency.colors[{color_index}].alpha",
                index=0,
                action_group=f"Color_{color_index}_Alpha"
            )
            fcurve.keyframe_points.add(len(frames))

            for i, frame in self.convert_timestamps(frames, convert=(timestamp_convert == "Convert")):
                key = fcurve.keyframe_points[i]
                key.co = frame, track[i] / 0x7FFF
                key.interpolation = "LINEAR" if alpha_track.interpolation_type == 1 else "CONSTANT"

        # --- Create or reuse unified controller ---
        obj, props = util.ensure_color_transparency_controller(collection)
        self.color_transparency = obj

        if not self.m2.root.colors:
            log.info("No colors found to import.")
            return

        # --- Main loop ---
        for i, m2_color in tqdm(enumerate(self.m2.root.colors), total=len(self.m2.root.colors), desc="Importing Colors", ascii=True):
            # --- Create color slot ---
            c = props.colors.add()
            c.name = f"Color_{i}"

            # --- Global sequences ---
            for j, seq_index in enumerate(self.global_sequences):
                anim = bpy.context.scene.wow_m2_animations[j]
                if anim.is_alias:
                    continue

                anim_pair = next((p for p in anim.anim_pairs if p.object == obj), None)
                if not anim_pair:
                    anim_pair = anim.anim_pairs.add()
                    anim_pair.type = "OBJECT"
                    anim_pair.object = obj

                # Only create an action if there’s something to animate
                needs_color = (m2_color.color.global_sequence == seq_index)
                needs_alpha = (m2_color.alpha.global_sequence == seq_index)
                if not (needs_color or needs_alpha):
                    continue

                # Ensure action exists
                self._bl_create_action(anim_pair, f"Color_{i}_GlobalSeq_{j}")

                if not anim_pair.action:
                    log.warn(f"Failed to animate color #{i}, no action for global seq #{j}")
                    continue

                if needs_color:
                    animate_color(anim_pair, m2_color.color, i, 0)
                if needs_alpha:
                    animate_alpha(anim_pair, m2_color.alpha, i, 0)

            # --- Per-animation ---
            for j, anim_index in enumerate(self.animations):
                anim = bpy.context.scene.wow_m2_animations[j + len(self.global_sequences)]
                if anim.is_alias:
                    continue

                anim_pair = next((p for p in anim.anim_pairs if p.object == obj), None)
                if not anim_pair:
                    anim_pair = anim.anim_pairs.add()
                    anim_pair.type = "OBJECT"
                    anim_pair.object = obj

                # Only create an action if this color isn’t controlled by a global sequence
                needs_color = (m2_color.color.global_sequence < 0)
                needs_alpha = (m2_color.alpha.global_sequence < 0)
                if not (needs_color or needs_alpha):
                    continue

                self._bl_create_action(anim_pair, f"Color_{i}_Anim_{anim_index}")

                if not anim_pair.action:
                    log.warn(f"Failed to animate color #{i}, no action for anim #{anim_index}")
                    continue

                if needs_color:
                    animate_color(anim_pair, m2_color.color, i, anim_index)
                if needs_alpha:
                    animate_alpha(anim_pair, m2_color.alpha, i, anim_index)

        log.info(f"Imported {len(self.m2.root.colors)} colors into {obj.name}.")

    def load_transparency(self, collection, timestamp_convert):
        """Import M2 transparency (texture weight) animation data into the unified color_transparency object."""

        # --- Helper for animation ---
        def animate_transparency(anim_pair, trans_track, trans_index, anim_index):
            action = anim_pair.action
            try:
                frames = trans_track.timestamps[anim_index]
                track = trans_track.values[anim_index]
            except IndexError:
                return
            if not frames:
                return

            fcurve = action.fcurves.new(
                data_path=f"wow_m2_color_transparency.transparencies[{trans_index}].value",
                index=0,
                action_group=f"Transparency_{trans_index}"
            )
            fcurve.keyframe_points.add(len(frames))

            for i, frame in self.convert_timestamps(frames, convert=(timestamp_convert == "Convert")):
                key = fcurve.keyframe_points[i]
                key.co = frame, track[i] / 0x7FFF
                key.interpolation = "LINEAR" if trans_track.interpolation_type == 1 else "CONSTANT"

        # --- Create or reuse unified controller ---
        obj, props = util.ensure_color_transparency_controller(collection)
        self.color_transparency = obj

        if not self.m2.root.texture_weights:
            log.info("No transparency tracks found to import.")
            return

        # --- Main loop ---
        for i, m2_trans in tqdm(enumerate(self.m2.root.texture_weights), total=len(self.m2.root.texture_weights), desc="Importing Transparency", ascii=True):
            # --- Create transparency slot ---
            t = props.transparencies.add()
            t.name = f"Transparency_{i}"

            # --- Global sequences ---
            for j, seq_index in enumerate(self.global_sequences):
                anim = bpy.context.scene.wow_m2_animations[j]
                if anim.is_alias:
                    continue

                anim_pair = next((p for p in anim.anim_pairs if p.object == obj), None)
                if not anim_pair:
                    anim_pair = anim.anim_pairs.add()
                    anim_pair.type = "OBJECT"
                    anim_pair.object = obj

                self._bl_create_action(anim_pair, f"Transparency_{i}_GlobalSeq_{j}")

                if m2_trans.global_sequence == seq_index:
                    animate_transparency(anim_pair, m2_trans, i, 0)

            # --- Per-animation ---
            for j, anim_index in enumerate(self.animations):
                anim = bpy.context.scene.wow_m2_animations[j + len(self.global_sequences)]
                if anim.is_alias:
                    continue

                anim_pair = next((p for p in anim.anim_pairs if p.object == obj), None)
                if not anim_pair:
                    anim_pair = anim.anim_pairs.add()
                    anim_pair.type = "OBJECT"
                    anim_pair.object = obj

                self._bl_create_action(anim_pair, f"Transparency_{i}_Anim_{anim_index}")

                if m2_trans.global_sequence < 0:
                    animate_transparency(anim_pair, m2_trans, i, anim_index)

        log.info(f"Imported {len(self.m2.root.texture_weights)} transparency tracks into {obj.name}.")

    def load_texture(self, index):
        """Load or create a texture for the given M2 texture index."""

        # Return already-loaded texture if available
        if index in self.loaded_textures:
            return self.loaded_textures[index]

        texture = self.m2.root.textures[index]
        tex_path_png = ""

        # --- Resolve texture path ---
        if texture.type == 0:  # Hardcoded texture
            try:
                tex_path_blp = (
                    self.m2.texture_path_map[texture.fdid]
                    if texture.fdid
                    else self.m2.texture_path_map[texture.filename.value]
                )
                tex_path_png = os.path.splitext(tex_path_blp)[0] + ".png"
            except KeyError:
                pass

        tex = None

        # --- Try loading PNG texture if available ---
        if tex_path_png:
            try:
                tex = bpy.data.images.load(tex_path_png)
            except RuntimeError:
                log.warn(f"Failed to load texture '{tex_path_png}'.")

        # --- Create placeholder texture if loading failed ---
        if not tex:
            if texture.type == 0:  # Hardcoded texture
                tex = bpy.data.images.new(os.path.basename(texture.filename.value), 256, 256)
            else:  # DBC texture
                tex_name = get_texture_type_name(texture.type)
                tex = bpy.data.images.new(os.path.basename(tex_name), 256, 256)

        # --- Apply M2 texture metadata ---
        tex.wow_m2_texture.enabled = True
        tex.wow_m2_texture.flags = parse_bitfield(texture.flags, 0x2)
        tex.wow_m2_texture.texture_type = str(texture.type)
        tex.wow_m2_texture.path = texture.filename.value

        # Cache loaded texture
        self.loaded_textures[index] = tex
        return tex

    def load_materials(self):
        """Import M2 material data and build Blender material objects."""
        dbc_textures = False
        BLENDING_MODES_DICT = {
            "0": "Opaque",
            "1": "AlphaKey",
            "2": "Alpha",
            "3": "NoAlphaAdd",
            "4": "Add",
            "5": "Mod",
            "6": "Mod2X",
            "7": "BlendAdd",
        }

        if "UV Picker" not in bpy.data.node_groups:
            load_m2_shader_dependencies(reload_shader=True)

        def create_m2_material(
            mat_flags,
            priority_plane,
            texture1,
            t1_flags,
            t1_bl_mode,
            t1_mapping,
            texture_count,
            transparency=None,
            color=None,
            texture2=None,
            t2_flags=None,
            t2_bl_mode=None,
            t2_mapping=None,
        ):
            blender_mat = bpy.data.materials.new(name="Unknown")

            if transparency is not None:
                blender_mat.wow_m2_material.transparency = transparency
            if color is not None:
                blender_mat.wow_m2_material.color = color

            blender_mat.wow_m2_material.flags = mat_flags
            blender_mat.wow_m2_material.priority_plane = priority_plane

            # Texture 1
            blender_mat.wow_m2_material.texture_1 = texture1
            blender_mat.wow_m2_material.texture_1_render_flags = t1_flags
            blender_mat.wow_m2_material.texture_1_blending_mode = t1_bl_mode
            blender_mat.wow_m2_material.texture_1_mapping = t1_mapping

            # Texture 2
            if texture_count == 2:
                blender_mat.wow_m2_material.texture_2 = texture2
                blender_mat.wow_m2_material.texture_2_render_flags = t2_flags
                blender_mat.wow_m2_material.texture_2_blending_mode = t2_bl_mode
                blender_mat.wow_m2_material.texture_2_mapping = t2_mapping

                blender_mat.name = (
                    f"T1_{texture1.name}({BLENDING_MODES_DICT.get(str(t1_bl_mode), 'Unknown')})_"
                    f"T2_{texture2.name}({BLENDING_MODES_DICT.get(str(t2_bl_mode), 'Unknown')})"
                )
            else:
                blender_mat.name = (
                    f"T1_{texture1.name}({BLENDING_MODES_DICT.get(str(t1_bl_mode), 'Unknown')})"
                )

            update_m2_mat_node_tree(blender_mat)
            return blender_mat

        skin = self.m2.skins[0]
        flags = parse_bitfield(self.m2.root.global_flags, 0x10)
        unique_materials = {}

        for k, tex_unit in tqdm(enumerate(skin.texture_units), total=len(skin.texture_units), desc="Importing Materials", ascii=True):
            try:
                m2_mat = self.m2.root.materials[tex_unit.material_index]
            except IndexError:
                msg = (
                    f"Material with index {tex_unit.material_index} not found in M2 file. "
                    f"This may indicate a corrupt M2 file."
                )
                raise IndexError(msg) from None

            # Handle second texture material if applicable
            if tex_unit.texture_count == 2 and "8" not in flags:
                try:
                    m2_mat2 = self.m2.root.materials[tex_unit.material_index + 1]
                except IndexError as e:
                    log.warn(f"Material for second texture not found, using first texture material: {e}")
                    m2_mat2 = m2_mat

            t1_flags = t2_flags = ()
            tex1 = t1_bl_mode = t1_mapping = None
            tex2 = t2_bl_mode = t2_mapping = None

            # --- Load textures ---
            for i in range(tex_unit.texture_count):
                try:
                    texid = self.m2.root.texture_lookup_table[
                        tex_unit.texture_combo_index + i
                    ]
                except IndexError as e:
                    log.warn(f"Texture not found, probably invalid M2: {e}")
                    continue

                tex = self.load_texture(texid)
                if i == 0:
                    tex1 = tex
                else:
                    tex2 = tex

                texture = self.m2.root.textures[texid]
                if texture.type != 0:
                    dbc_textures = True  # Will trigger DBC texture import later

            # --- Transparency binding ---
            if tex_unit.texture_weight_combo_index >= 0:
                real_tw_index = self.m2.root.transparency_lookup_table[
                    tex_unit.texture_weight_combo_index
                ]
                transparency = self.color_transparency.wow_m2_color_transparency.transparencies[real_tw_index].name
            else:
                transparency = None

            # --- Color binding ---
            color = None
            if tex_unit.color_index >= 0:
                try:
                    color = self.color_transparency.wow_m2_color_transparency.colors[tex_unit.color_index].name
                except Exception:
                    log.warn(
                        f"TexUnit {k} references non-existing color {tex_unit.color_index}, importing without color."
                    )

            # --- Mapping IDs ---
            int_to_enum_mapping = {-1: "Env", 0: "UVMap", 1: "UVMap.001"}

            # --- Material parameters ---
            mat_flags = parse_bitfield(tex_unit.flags, 0x80)
            t1_flags = parse_bitfield(m2_mat.flags, 0x800)
            t1_bl_mode = str(m2_mat.blending_mode)
            t1_mapping = int_to_enum_mapping.get(
                self.m2.root.tex_unit_lookup_table[tex_unit.texture_coord_combo_index]
            )
            texture_count = 2 if tex_unit.texture_count == 2 else 1

            # --- Handle dual-texture cases ---
            if texture_count == 2 and "8" in flags:  # Global flag overrides
                try:
                    t2_flags = parse_bitfield(
                        self.m2.root.texture_combiner_combos[tex_unit.shader_id], 0x800
                    )
                    t2_bl_mode = str(
                        self.m2.root.texture_combiner_combos[tex_unit.shader_id + 1]
                    )
                    t2_mapping = int_to_enum_mapping.get(
                        self.m2.root.tex_unit_lookup_table[
                            tex_unit.texture_coord_combo_index + 1
                        ]
                    )
                except Exception:
                    log.warn("Texture 2 flags or blending mode not found, falling back to index 0.")
                    t2_flags = parse_bitfield(self.m2.root.texture_combiner_combos[0], 0x800)
                    t2_bl_mode = str(self.m2.root.texture_combiner_combos[1])
                    try:
                        t2_mapping = int_to_enum_mapping.get(
                            self.m2.root.tex_unit_lookup_table[
                                tex_unit.texture_coord_combo_index + 1
                            ]
                        )
                    except Exception:
                        log.warn("Second UVMap not found, using first one.")
                        t2_mapping = int_to_enum_mapping.get(
                            self.m2.root.tex_unit_lookup_table[
                                tex_unit.texture_coord_combo_index
                            ]
                        )

            elif texture_count == 2 and "8" not in flags:
                t2_flags = parse_bitfield(m2_mat2.flags, 0x800)
                t2_bl_mode = str(m2_mat2.blending_mode)
                try:
                    t2_mapping = int_to_enum_mapping.get(
                        self.m2.root.tex_unit_lookup_table[
                            tex_unit.texture_coord_combo_index + 1
                        ]
                    )
                except IndexError as e:
                    log.warn(f"Mapping for second texture not found, using first texture mapping: {e}")
                    t2_mapping = int_to_enum_mapping.get(
                        self.m2.root.tex_unit_lookup_table[
                            tex_unit.texture_coord_combo_index
                        ]
                    )

            priority_plane = tex_unit.priority_plane

            # --- Store material by skin section ---
            if tex_unit.skin_section_index not in self.materials:
                self.materials[tex_unit.skin_section_index] = []

            material_key = (
                tuple(mat_flags),
                priority_plane,
                tex1.name,
                tuple(t1_flags),
                t1_bl_mode,
                t1_mapping,
                texture_count,
                transparency,
                color,
                tex2.name if tex2 else None,
                tuple(t2_flags),
                t2_bl_mode,
                t2_mapping,
            )

            if material_key in unique_materials:
                material = unique_materials[material_key]
            else:
                material = create_m2_material(
                    mat_flags,
                    priority_plane,
                    tex1,
                    t1_flags,
                    t1_bl_mode,
                    t1_mapping,
                    texture_count,
                    transparency,
                    color,
                    tex2,
                    t2_flags,
                    t2_bl_mode,
                    t2_mapping,
                )
                unique_materials[material_key] = material

            self.materials[tex_unit.skin_section_index].append((material, tex_unit))

        log.info(f"Imported {sum(len(mats) for mats in self.materials.values())} materials.")

        return dbc_textures

    def load_armature(self, collection):
        bones = self.m2.root.bones
        model_name = self.m2.root.name.value

        if not bones:
            log.info("No armature found to import.")
            return

        # Create armature and rig object
        armature = bpy.data.armatures.new(f"{model_name}_Armature")
        rig = bpy.data.objects.new(model_name, armature)
        rig.location = (0.0, 0.0, 0.0)
        self.rig = rig

        # Link the armature to the scene and activate it
        util._link_to_single_collection(rig, collection)

        bpy.context.view_layer.objects.active = rig
        bpy.context.view_layer.update()

        bpy.ops.object.mode_set(mode="EDIT")

        # Create bones
        for i, bone in tqdm(enumerate(self.m2.root.bones), total=len(self.m2.root.bones), desc="Importing Armature Bones", ascii=True):
            bl_edit_bone = armature.edit_bones.new(bone.name)
            bl_edit_bone.head = Vector(bone.pivot)
            bl_edit_bone.tail = bl_edit_bone.head + Vector((0.1, 0.0, 0.0)) # small offset along X

            wow_bone = bl_edit_bone.wow_m2_bone
            wow_bone.sort_index = i
            wow_bone.flags = parse_bitfield(bone.flags)
            wow_bone.submesh_id = bone.submesh_id
            wow_bone.bone_name_crc = ctypes.c_int(bone.bone_name_crc).value

            try:
                wow_bone.key_bone_id = str(bone.key_bone_id)
            except TypeError:
                log.warn(f"Failed to set keybone ID '{bone.key_bone_id}'. Unknown keybone ID.")

            # Assign layers
            layers = bl_edit_bone.layers
            for j in range(5):
                layers[j] = False

            if "AT_" in bone.name:
                layers[3] = True
            elif "ET" in bone.name:
                layers[4] = True
            elif "Bone_" in bone.name:
                layers[2] = True
            elif bone.key_bone_id == -1:
                layers[1] = True
            else:
                layers[0] = True
                
            log.debug(f"Bone {i}: name='{bone.name}', crc={bone.bone_name_crc}")

        # Link children to parents
        for bone in bones:
            if bone.parent_bone >= 0:
                child = armature.edit_bones[bone.name]
                parent = armature.edit_bones[bones[bone.parent_bone].name]
                child.parent = parent

        bpy.ops.object.mode_set(mode="POSE")

        # Create bone groups

        pose = rig.pose

        group_default = pose.bone_groups.new(name="DEFAULT")
        group_unkeyed = pose.bone_groups.new(name="UNKEYED")
        group_skeletal = pose.bone_groups.new(name="SKELETAL")
        group_attachment = pose.bone_groups.new(name="ATTACHMENT")
        group_event = pose.bone_groups.new(name="EVENT")

        group_default.color_set = 'DEFAULT'
        group_unkeyed.color_set = 'THEME09'
        group_skeletal.color_set = 'THEME03'
        group_attachment.color_set = 'THEME04'
        group_event.color_set = 'THEME01'

        # Assign pose bones to groups
        for bone in self.m2.root.bones:
            pbone = pose.bones[bone.name]

            if "AT_" in bone.name:
                pbone.bone_group = group_attachment
            elif "ET" in bone.name:
                pbone.bone_group = group_event
            elif "Bone_" in bone.name:
                pbone.bone_group = group_skeletal
            elif bone.key_bone_id == -1:
                pbone.bone_group = group_unkeyed
            else:
                pbone.bone_group = group_default

        bpy.ops.object.mode_set(mode="OBJECT")

        log.info(f"Imported armature with {len(bones)} bones for '{model_name}'.")


    def _populate_bl_fcurve(self, f_curves, frames, track, length, callback, interp_type):
        """Populate Blender FCurves with keyframe data from an M2 track."""
        
        # --- Initialize keyframe points for all FCurves ---
        frame_count = len(frames)
        for f_curve in f_curves:
            f_curve.keyframe_points.add(frame_count)

        # --- Retrieve timestamp conversion mode ---
        preferences = get_project_preferences()
        convert = (preferences.time_import_method == "Convert")

        # --- Populate keyframes ---
        for j, frame in self.convert_timestamps(frames, convert=convert):
            if track:
                value = callback(value=track[j])

                # Convert vector to a tuple
                if isinstance(value, Vector):
                    value = tuple(value)

                # Ensure we're always working with a list of floats, even single channel
                values = value if isinstance(value, (tuple, list)) else [value]

                for k, v in enumerate(values):
                    keyframe = f_curves[k].keyframe_points[j]
                    keyframe.co = (float(frame), float(v))
                    keyframe.interpolation = interp_type
            else:
                # Trackless FCurve (e.g. boolean toggle or empty channel)
                keyframe = f_curves[0].keyframe_points[j]
                keyframe.co = (float(frame), 1.0)
                keyframe.interpolation = interp_type

    def _bl_create_sequences(self, m2_obj, m2_track_name: str, prefix: str, bl_obj, bl_obj_name: str, bl_track_name: str, track_count: int, conv):
        """Create Blender FCurves for all animation sequences for a specific M2Track."""

        track = getattr(m2_obj, m2_track_name)
        seq_name_table = M2SequenceNames()
        n_global_sequences = len(self.global_sequences)
        data_path = f"{bl_obj_name}.{bl_track_name}"

        # --- Handle Global Sequences ---
        if track.global_sequence >= 0:
            global_seq_str = f"{track.global_sequence:03}"
            action_name = f"{prefix}_{bl_obj.name}_Global_sequence_{global_seq_str}"

            # Get or create action for the global sequence
            if action_name in self.actions:
                action = self.actions[action_name]
            else:
                sequence_index = self.global_sequences[track.global_sequence]
                sequence = bpy.context.scene.wow_m2_animations[sequence_index]
                anim_pair = sequence.anim_pairs.add()
                anim_pair.object = bl_obj
                anim_pair.action = BlenderM2Scene._bl_create_action(anim_pair, action_name)
                action = self.actions[action_name] = anim_pair.action

            # Create the fcurves for this track
            self._bl_create_fcurves(
                action,
                action_group="",
                callback=conv,
                length=track_count,
                anim_index=0,
                data_path=data_path,
                anim_track=track,
            )
            return  # Global sequences handled; exit early

        # --- Handle Normal Sequences ---
        for j, anim_index in enumerate(self.animations):
            anim = bpy.context.scene.wow_m2_animations[j + n_global_sequences]
            sequence = self.m2.root.sequences[anim_index]

            # Skip if timestamps are missing or empty
            if track.timestamps.n_elements <= anim_index or not len(track.timestamps[anim_index]):
                continue

            # Construct a readable action name
            field_name = seq_name_table.get_sequence_name(sequence.id)
            action_name = f"{prefix}_{bl_obj.name}_{j:03}_{sequence.variation_index}"

            # Get or create action for this animation
            if action_name in self.actions:
                action = self.actions[action_name]
            else:
                anim_pair = anim.anim_pairs.add()
                anim_pair.type = "OBJECT"
                anim_pair.object = bl_obj
                anim_pair.action = BlenderM2Scene._bl_create_action(anim_pair, action_name)
                action = self.actions[action_name] = anim_pair.action

            # Create the fcurves for this track
            self._bl_create_fcurves(
                action,
                action_group="",
                callback=conv,
                length=track_count,
                anim_index=j,
                data_path=data_path,
                anim_track=track,
            )

    def _bl_create_fcurves(self, action, action_group, callback, length, anim_index, data_path, anim_track):
        """Create Blender FCurves for an M2 animation track."""

        # --- Ensure valid animation index ---
        if anim_track.timestamps.n_elements <= anim_index:
            return  # Nothing to do

        frames = anim_track.timestamps[anim_index]

        # --- Try to get value track (optional) ---
        track = getattr(anim_track, "values", None)
        track = track[anim_index] if track and len(track) > anim_index else None

        if not frames:
            return  # No keyframes to process

        # --- Create new FCurves ---
        t_fcurves = [
            action.fcurves.new(data_path=data_path, index=k, action_group=action_group)
            for k in range(length)
        ]

        # --- Determine interpolation type ---
        interp_type = "LINEAR" if getattr(anim_track, "interpolation_type", 0) == 1 else "CONSTANT"

        # --- Populate the FCurves ---
        self._populate_bl_fcurve(t_fcurves, frames, track, length, callback, interp_type)

    @staticmethod
    def _bl_create_action(anim_pair, name: str) -> bpy.types.Action:
        """Create or return an existing Blender Action for the given animation pair."""

        # If no action exists, create one and assign it
        if not getattr(anim_pair, "action", None):
            action = bpy.data.actions.new(name=name)
            action.use_fake_user = True
            anim_pair.action = action

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

    def _bl_add_sequence(self, name: str = "Sequence", is_global: bool = False, is_alias: bool = False) -> bpy.types.PropertyGroup:
        """Create and register a new M2 animation sequence in the Blender scene."""

        seq = self.scene.wow_m2_animations.add()
        seq.is_global_sequence = is_global

        # --- Rig-level animation pair only ---
        anim_pair_rig = seq.anim_pairs.add()
        anim_pair_rig.type = "OBJECT"
        anim_pair_rig.object = self.rig

        # --- Create and assign actions ---
        if not is_alias:
            anim_pair_rig.action = self._bl_create_action(anim_pair_rig, name)

        return seq


    def _bl_load_sequences(self):
        """Load M2 animation sequences and register them as Blender animation sequences."""

        # --- Import global sequences ---
        for i, _ in enumerate(self.m2.root.global_sequences):
            seq_name = f"Global_Sequence_{i:03}"
            self._bl_add_sequence(name=seq_name, is_global=True)
            self.global_sequences.append(len(self.scene.wow_m2_animations) - 1)

        # --- Sort and import regular sequences ---
        m2_sequences = sorted(
            enumerate(self.m2.root.sequences),
            key=lambda item: (item[0], item[1].id, item[1].variation_index),
        )

        for i, (idx, sequence) in enumerate(m2_sequences):
            # --- Sequence naming ---
            field_name = self.anim_data_table.get_sequence_name(sequence.id)
            name = (
                f"{i:03}_{field_name}_({sequence.variation_index})"
                if field_name else f"{i:03}_UnkAnim"
            )

            # --- Check alias ---
            is_alias = bool(sequence.flags & 0x40)
            anim = self._bl_add_sequence(name=name, is_global=False, is_alias=is_alias)

            # --- Handle alias sequences ---
            if is_alias:
                anim.is_alias = True
                for j, seq in m2_sequences:
                    anim.alias_next = j
                    if j == sequence.alias_next:
                        self.alias_animation_lookup[i] = j
                        break

            # --- Animation properties ---
            anim.animation_id = str(sequence.id)
            anim.flags = parse_bitfield(sequence.flags, 0x800)

            if "32" not in anim.flags:
                anim.flags |= {"32"}

            anim.move_speed = sequence.movespeed
            anim.frequency = get_frequency_percentage(sequence.frequency)
            anim.replay_min = sequence.replay.minimum
            anim.replay_max = sequence.replay.maximum
            anim.VariationNext = sequence.variation_next

            # --- Bounds ---
            anim.use_preset_bounds = True
            anim.preset_bounds_min_x, anim.preset_bounds_min_y, anim.preset_bounds_min_z = sequence.bounds.extent.min
            anim.preset_bounds_max_x, anim.preset_bounds_max_y, anim.preset_bounds_max_z = sequence.bounds.extent.max
            anim.preset_bounds_radius = sequence.bounds.radius

            # --- Duration / blending ---
            anim.use_preset_duration = False
            anim.duration = sequence.duration

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
        """Imports animation data for the current M2 rig into Blender."""

        if not self.m2.root.sequences and not self.m2.root.global_sequences:
            log.info("No animation data found to import.")
            return

        if not self.rig:
            log.warn("Armature not found — skipping animation import.")
            return

        def bl_convert_trans_track(value=None, bl_bone=None, bone=None):
            return bl_bone.bone.matrix_local.inverted() @ (Vector(bone.pivot) + Vector(value))

        def bl_convert_rot_track(value=None):
            return value.to_quaternion()

        def bl_convert_scale_track(value=None):
            value = list(value)
            for i, val in enumerate(value):
                if isinf(val):
                    log.warn("Infinite scale value fixed to 1.0")
                    value[i] = 1.0
            return (value[1], value[0], value[2])

        # --- Alias resolver (only rig now) ---
        def load_alias_actions():
            scene = self.scene
            n_global_sequences = len(self.m2.root.global_sequences)

            for i, anim_index in enumerate(self.animations):
                anim = scene.wow_m2_animations[i + n_global_sequences]
                action = anim.anim_pairs[0].action
                alias_next = anim.alias_next

                final_alias = _find_final_alias(self, n_global_sequences, alias_next)

                if not action:
                    alias_anim = scene.wow_m2_animations[final_alias]
                    anim.anim_pairs[0].action = alias_anim.anim_pairs[0].action

        try:
            scene = self.scene
            rig = self.rig

            rig.animation_data_create()
            rig.animation_data.action_blend_type = "ADD"
            bpy.context.view_layer.objects.active = rig

            self._bl_load_sequences()

            # --- Import per-bone fcurves ---
            for bone in tqdm(self.m2.root.bones, total=len(self.m2.root.bones), desc="Importing Animations", ascii=True):
                try:
                    bl_bone = rig.pose.bones[bone.name]
                except KeyError:
                    log.warn(f"Bone '{bone.name}' missing — skipping.")
                    continue

                is_global_seq_trans = bone.translation.global_sequence >= 0
                is_global_seq_rot = bone.rotation.global_sequence >= 0
                is_global_seq_scale = bone.scale.global_sequence >= 0
                glob_sequences = self.global_sequences
                n_global_sequences = len(self.m2.root.global_sequences)

                # --- Global sequences ---
                if is_global_seq_trans:
                    action = scene.wow_m2_animations[glob_sequences[bone.translation.global_sequence]].anim_pairs[0].action
                    self._bl_create_action_group(action, bone.name)
                    self._bl_create_fcurves(
                        action, bone.name,
                        partial(bl_convert_trans_track, bl_bone=bl_bone, bone=bone),
                        3, 0,
                        f'pose.bones["{bl_bone.name}"].location',
                        bone.translation,
                    )

                if is_global_seq_rot:
                    action = scene.wow_m2_animations[glob_sequences[bone.rotation.global_sequence]].anim_pairs[0].action
                    self._bl_create_action_group(action, bone.name)
                    self._bl_create_fcurves(
                        action, bone.name,
                        partial(bl_convert_rot_track),
                        4, 0,
                        f'pose.bones["{bl_bone.name}"].rotation_quaternion',
                        bone.rotation,
                    )

                if is_global_seq_scale:
                    action = scene.wow_m2_animations[glob_sequences[bone.scale.global_sequence]].anim_pairs[0].action
                    self._bl_create_action_group(action, bone.name)
                    self._bl_create_fcurves(
                        action, bone.name,
                        partial(bl_convert_scale_track),
                        3, 0,
                        f'pose.bones["{bl_bone.name}"].scale',
                        bone.scale,
                    )

                # --- Regular animations ---
                for i, anim_index in enumerate(self.animations):
                    anim = scene.wow_m2_animations[i + n_global_sequences]
                    action = anim.anim_pairs[0].action
                    if not action:
                        continue

                    if not is_global_seq_trans and bone.translation.timestamps.n_elements > anim_index:
                        self._bl_create_action_group(action, bone.name)
                        self._bl_create_fcurves(
                            action, bone.name,
                            partial(bl_convert_trans_track, bl_bone=bl_bone, bone=bone),
                            3, anim_index,
                            f'pose.bones["{bl_bone.name}"].location',
                            bone.translation,
                        )

                    if not is_global_seq_rot and bone.rotation.timestamps.n_elements > anim_index:
                        self._bl_create_action_group(action, bone.name)
                        self._bl_create_fcurves(
                            action, bone.name,
                            partial(bl_convert_rot_track),
                            4, anim_index,
                            f'pose.bones["{bl_bone.name}"].rotation_quaternion',
                            bone.rotation,
                        )

                    if not is_global_seq_scale and bone.scale.timestamps.n_elements > anim_index:
                        self._bl_create_action_group(action, bone.name)
                        self._bl_create_fcurves(
                            action, bone.name,
                            partial(bl_convert_scale_track),
                            3, anim_index,
                            f'pose.bones["{bl_bone.name}"].scale',
                            bone.scale,
                        )

            load_alias_actions()
            log.info(f"Imported {len(self.m2.root.sequences)} animations ({len(self.m2.root.global_sequences)} global sequences).")

        except Exception as e:
            tb = traceback.format_exc()
            log.error(f"Failed to import Animations: {e}\n{tb}")

    def load_geosets(self, collection):
        """Import geosets (submeshes) from the M2 model into Blender."""

        if not len(self.m2.root.vertices):
            log.info("No mesh geometry found to import.")
            return

        skin = self.m2.skins[0]
        for smesh_i, smesh in tqdm(enumerate(skin.submeshes), total=len(skin.submeshes), desc="Importing Geosets", ascii=True):
            # --- Collect geometry data ---
            vertices = [
                self.m2.root.vertices[skin.vertex_indices[i]].pos
                for i in range(smesh.vertex_start, smesh.vertex_start + smesh.vertex_count)
            ]

            normals = [
                self.m2.root.vertices[skin.vertex_indices[i]].normal
                for i in range(smesh.vertex_start, smesh.vertex_start + smesh.vertex_count)
            ]

            tex_coords = [
                self.m2.root.vertices[skin.vertex_indices[i]].tex_coords
                for i in range(smesh.vertex_start, smesh.vertex_start + smesh.vertex_count)
            ]

            tex_coords2 = [
                self.m2.root.vertices[skin.vertex_indices[i]].tex_coords2
                for i in range(smesh.vertex_start, smesh.vertex_start + smesh.vertex_count)
            ]

            triangles = [
                [skin.triangle_indices[i + j] - smesh.vertex_start for j in range(3)]
                for i in range(smesh.index_start, smesh.index_start + smesh.index_count, 3)
            ]

            # --- Create mesh ---
            mesh = bpy.data.meshes.new(self.m2.root.name.value)
            mesh.from_pydata(vertices, [], triangles)

            for poly in mesh.polygons:
                poly.use_smooth = True

            # --- Set normals ---
            mesh.auto_smooth_angle = 3.14159
            mesh.use_auto_smooth = True
            custom_normals = [normals[loop.vertex_index] for loop in mesh.loops]
            mesh.normals_split_custom_set(custom_normals)

            # --- Create UV layers ---
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

            # --- Assign materials ---
            for material, tex_unit in self.materials[smesh_i]:
                mesh.materials.append(material)

            # --- Determine sub-collection ---
            name = M2SkinMeshPartID.get_mesh_part_name(smesh.skin_section_id)
            sub_name = name if name else "Unknown"
            sub_collection = util.get_or_create_collection(sub_name, parent=collection, color_tag='COLOR_04')

            # --- Create object ---
            obj = bpy.data.objects.new(name if name else "Geoset", mesh)
            util._link_to_single_collection(obj, sub_collection)

            try:
                obj.wow_m2_geoset.mesh_part_group = name
                obj.wow_m2_geoset.mesh_part_id = str(smesh.skin_section_id)
            except TypeError:
                log.warn(f"Unknown mesh part ID '{smesh.skin_section_id}'.")

            # Rename object if it matches a known part name
            for item in mesh_part_id_menu(obj.wow_m2_geoset, None):
                if item[0] == smesh.skin_section_id:
                    obj.name = item[1]

            # --- Parent and rig binding ---
            if self.rig:
                armature_modifier = obj.modifiers.new(name="Armature", type="ARMATURE")
                armature_modifier.object = self.rig

                vgroups = {}
                for j in range(smesh.vertex_start, smesh.vertex_start + smesh.vertex_count):
                    m2_vertex = self.m2.root.vertices[skin.vertex_indices[j]]

                    for b_index, bone_index in enumerate(
                        filter(lambda x: x >= 0, m2_vertex.bone_indices)
                    ):
                        bone_name = self.m2.root.bones[bone_index].name
                        vgroups.setdefault(bone_name, []).append(
                            (j - smesh.vertex_start, m2_vertex.bone_weights[b_index] / 255)
                        )

                for name, verts in vgroups.items():
                    if verts:
                        grp = obj.vertex_groups.new(name=name)
                        for v, w in verts:
                            grp.add([v], w, "ADD")

            self.geosets.append(obj)
            
        # --- Log success ---
        log.info(f"Imported {len(self.geosets)} geosets.")

    def load_texture_transforms(self, collection):
        """Import texture transformation animations (translation, rotation, scaling) for UVs."""

        def bl_convert_trans_track(value=None):
            return Vector((0, 0, 0)) + Vector((-value[0], value[1], value[2]))

        def bl_convert_rot_track(value=None):
            return value[3], -value[1], value[0], value[2]

        # --- Validation ---
        if not self.geosets:
            log.info("No geosets found. Skipping texture transform import.")
            return

        skin = self.m2.skins[0]

        for smesh_i, smesh in tqdm(enumerate(skin.submeshes), total=len(skin.submeshes), desc="Importing Texture Transforms", ascii=True):
            obj = self.geosets[smesh_i]

            for _, tex_unit in self.materials[smesh_i]:
                texture_count = 2 if tex_unit.texture_count > 1 else 1

                for i in range(texture_count):
                    combo_index = tex_unit.texture_transform_combo_index + i

                    # --- Lookup transform index ---
                    try:
                        tex_transform_index = self.m2.root.texture_transforms_lookup_table[combo_index]
                    except IndexError:
                        log.warn(
                            f"Texture animation with index {combo_index} doesn't exist in the M2 — skipping."
                        )
                        continue

                    if tex_transform_index < 0 or self.m2.root.texture_transforms_lookup_table[combo_index] == -1:
                        continue

                    c_obj = self.uv_transforms.get(tex_transform_index)

                    # --- Retrieve transform data ---
                    try:
                        tex_transform = self.m2.root.texture_transforms[tex_transform_index]
                    except IndexError:
                        log.warn(f"Texture animation {tex_transform_index} not found — skipping import.")
                        continue

                    seq_name_table = M2SequenceNames()
                    n_global_sequences = len(self.global_sequences)
                    TT_controllers = [o for o in bpy.data.objects if o.wow_m2_uv_transform.enabled]

                    # --- Create or reuse controller object ---
                    if not c_obj:
                        bpy.ops.object.empty_add(type="SINGLE_ARROW", location=(0, 0, 0))
                        c_obj = bpy.context.view_layer.objects.active
                        c_obj.name = f"TT_Controller_{len(TT_controllers)}"
                        c_obj.wow_m2_uv_transform.enabled = True
                        c_obj.rotation_mode = "QUATERNION"
                        c_obj.empty_display_size = 0.5
                        c_obj.animation_data_create()
                        c_obj.animation_data.action_blend_type = "ADD"
                        util._link_to_single_collection(c_obj, collection)
                        self.uv_transforms[tex_transform_index] = c_obj
                        create_actions = True
                    else:
                        create_actions = False

                    # --- Assign controller to material slot ---
                    material = obj.active_material
                    obj.active_material = material.copy()
                    if i == 0:
                        obj.active_material.wow_m2_material.texture_1_animation = c_obj
                    else:
                        obj.active_material.wow_m2_material.texture_2_animation = c_obj

                    # --- Add UV warp modifier ---
                    bpy.context.view_layer.objects.active = obj
                    bpy.ops.object.modifier_add(type="UV_WARP")
                    uv_transform = bpy.context.object.modifiers[-1]
                    uv_transform.name = f"M2TexTransform_{i + 1}"
                    uv_transform.object_from = obj
                    uv_transform.object_to = c_obj
                    uv_transform.uv_layer = "UVMap" if not i else "UVMap.001"

                    setattr(obj.wow_m2_geoset, f"uv_transform_{i + 1}", c_obj)

                    # --- Create actions and FCurves ---
                    if create_actions:
                        # --- Global sequences ---
                        for j, seq_index in enumerate(self.global_sequences):
                            anim = bpy.context.scene.wow_m2_animations[seq_index]
                            name = f"TT_{tex_transform_index}_{obj.name}_Global_Sequence_{str(j).zfill(3)}"

                            cur_index = len(anim.anim_pairs)
                            anim_pair = anim.anim_pairs.add()
                            anim_pair.type = "OBJECT"
                            anim_pair.object = c_obj

                            if (
                                tex_transform.translation.global_sequence == j
                                and tex_transform.translation.timestamps.n_elements
                            ):
                                action = self._bl_create_action(anim_pair, name)
                                self._bl_create_fcurves(
                                    action,
                                    c_obj.name,
                                    bl_convert_trans_track,
                                    3,
                                    0,
                                    "location",
                                    tex_transform.translation,
                                )

                            if (
                                tex_transform.rotation.global_sequence == j
                                and tex_transform.rotation.timestamps.n_elements
                            ):
                                action = self._bl_create_action(anim_pair, name)
                                self._bl_create_fcurves(
                                    action,
                                    c_obj.name,
                                    bl_convert_rot_track,
                                    4,
                                    0,
                                    "rotation_quaternion",
                                    tex_transform.rotation,
                                )

                            if (
                                tex_transform.scaling.global_sequence == j
                                and tex_transform.scaling.timestamps.n_elements
                            ):
                                action = self._bl_create_action(anim_pair, name)
                                self._bl_create_fcurves(
                                    action,
                                    c_obj.name,
                                    bl_convert_trans_track,
                                    3,
                                    0,
                                    "scale",
                                    tex_transform.scaling,
                                )

                            if not anim_pair.action:
                                anim.anim_pairs.remove(cur_index)

                        # --- Regular animations ---
                        for j, anim_index in enumerate(self.animations):
                            # Skip alias animations
                            if self.alias_animation_lookup.get(j):
                                continue

                            anim = bpy.context.scene.wow_m2_animations[j + n_global_sequences]
                            sequence = self.m2.root.sequences[anim_index]
                            field_name = seq_name_table.get_sequence_name(sequence.id)

                            name = (
                                f"TT_{tex_transform_index}_{obj.name}_{str(j).zfill(3)}_UnkAnim"
                                if not field_name
                                else f"TT_{tex_transform_index}_{obj.name}_{str(j).zfill(3)}_{field_name}({sequence.variation_index})"
                            )

                            cur_index = len(anim.anim_pairs)
                            anim_pair = anim.anim_pairs.add()
                            anim_pair.type = "OBJECT"
                            anim_pair.object = c_obj

                            if (
                                tex_transform.translation.global_sequence < 0
                                and tex_transform.translation.timestamps.n_elements > j
                            ):
                                action = self._bl_create_action(anim_pair, name)
                                self._bl_create_fcurves(
                                    action,
                                    obj.name,
                                    bl_convert_trans_track,
                                    3,
                                    j,
                                    "location",
                                    tex_transform.translation,
                                )

                            if (
                                tex_transform.rotation.global_sequence < 0
                                and tex_transform.rotation.timestamps.n_elements > j
                            ):
                                action = self._bl_create_action(anim_pair, name)
                                self._bl_create_fcurves(
                                    action,
                                    obj.name,
                                    bl_convert_rot_track,
                                    4,
                                    j,
                                    "rotation_quaternion",
                                    tex_transform.rotation,
                                )

                            if (
                                tex_transform.scaling.global_sequence < 0
                                and tex_transform.scaling.timestamps.n_elements > j
                            ):
                                action = self._bl_create_action(anim_pair, name)
                                self._bl_create_fcurves(
                                    action,
                                    obj.name,
                                    bl_convert_trans_track,
                                    3,
                                    j,
                                    "scale",
                                    tex_transform.scaling,
                                )

                            if not anim_pair.action:
                                anim.anim_pairs.remove(cur_index)
        # --- Log success ---
        log.info(f"Imported texture transforms for {len(skin.submeshes)} geosets.")

    def load_attachments(self, collection):
        """Import M2 attachments (points like weapons, particle anchors, etc.) into Blender."""

        for i, attachment in tqdm(enumerate(self.m2.root.attachments), total=len(self.m2.root.attachments), desc="Importing Attachments", ascii=True):
            # --- Create attachment object ---
            bpy.ops.object.empty_add(type="SPHERE", location=(0, 0, 0))
            obj = bpy.context.view_layer.objects.active
            obj.empty_display_size = 0.07
            
            # Link object to respective collection
            util._link_to_single_collection(obj, collection)

            # --- Add and configure constraint ---
            bpy.ops.object.constraint_add(type="CHILD_OF")
            constraint = obj.constraints[-1]
            constraint.target = self.rig

            try:
                bone = self.m2.root.bones[attachment.bone]
                constraint.subtarget = bone.name
                bl_edit_bone = self.rig.data.bones[bone.name]
            except (IndexError, KeyError):
                log.warn(f"Attachment {i} references an invalid bone index ({attachment.bone}). Skipping binding.")
                continue

            obj.location = attachment.position

            # --- Name and enable attachment ---
            obj.name = M2AttachmentTypes.get_attachment_name(attachment.id, i)
            obj.wow_m2_attachment.enabled = True
            obj.wow_m2_attachment.type = str(attachment.id)

            # --- Setup animation data ---
            obj.animation_data_create()
            obj.animation_data.action_blend_type = "ADD"

            seq_name_table = M2SequenceNames()
            n_global_sequences = len(self.global_sequences)

            # --- Handle global sequence animation ---
            if attachment.animate_attached.global_sequence >= 0:
                anim = bpy.context.scene.wow_m2_animations[
                    attachment.animate_attached.global_sequence
                ]

                if (
                    not attachment.animate_attached.timestamps.n_elements
                    or not attachment.animate_attached.timestamps[0]
                ):
                    continue

                name = (
                    f"AT_{i}_{obj.name}_Global_Sequence_"
                    f"{str(attachment.animate_attached.global_sequence).zfill(3)}"
                )

                anim_pair = anim.anim_pairs.add()
                anim_pair.type = "OBJECT"
                anim_pair.object = obj
                anim_pair.action = self._bl_create_action(anim_pair, name)

                self._bl_create_fcurves(
                    anim_pair.action,
                    "",
                    self._bl_convert_track_dummy,
                    1,
                    0,
                    "wow_m2_attachment.animate",
                    attachment.animate_attached,
                )

                # Global sequence attachments stop here
                continue

            # --- Handle regular per-animation sequences ---
            for j, anim_index in enumerate(self.animations):
                anim = bpy.context.scene.wow_m2_animations[j + n_global_sequences]
                sequence = self.m2.root.sequences[anim_index]

                if attachment.animate_attached.timestamps.n_elements <= anim_index:
                    continue

                if not len(attachment.animate_attached.timestamps[anim_index]):
                    continue

                field_name = seq_name_table.get_sequence_name(sequence.id)
                name = (
                    f"AT_{i}_{obj.name}_UnkAnim"
                    if not field_name
                    else f"AT_{i}_{obj.name}_{str(j).zfill(3)}_{field_name}({sequence.variation_index})"
                )

                anim_pair = anim.anim_pairs.add()
                anim_pair.type = "OBJECT"
                anim_pair.object = obj
                self._bl_create_action(anim_pair, name)

                self._bl_create_fcurves(
                    anim_pair.action,
                    "",
                    self._bl_convert_track_dummy,
                    1,
                    j,
                    "wow_m2_attachment.animate",
                    attachment.animate_attached,
                )

        # --- Log success ---
        log.info(f"Imported {len(self.m2.root.attachments)} attachments.")

    def load_lights(self, collection):
        """Import M2 lights and their animation data into Blender."""

        def animate_property(anim_pair, m2_light, prop_name, length, action_name, anim_index):
            """Create and populate FCurves for a given light property."""
            prop_track = getattr(m2_light, prop_name)

            try:
                frames = prop_track.timestamps[anim_index]
            except IndexError:
                return

            if not len(frames):
                return

            self._bl_create_action(anim_pair, action_name)
            action_group = self._bl_create_action_group(
                anim_pair.action, f"Color_{prop_name}"
            )

            self._bl_create_fcurves(
                anim_pair.action,
                action_group,
                self._bl_convert_track_value if length == 1 else self._bl_convert_track_tuple,
                length,
                anim_index,
                f"data.wow_m2_light.{prop_name}",
                prop_track,
            )

        if not len(self.m2.root.lights):
            log.info("No lights found to import.")
            return

        for i, light in tqdm(enumerate(self.m2.root.lights), total=len(self.m2.root.lights), desc="Importing Lights", ascii=True):
            # --- Create light object ---
            light_type = "POINT" if light.type else "SPOT"
            bpy.ops.object.light_add(type=light_type, location=(0, 0, 0))
            obj = bpy.context.view_layer.objects.active
            
            # Link object to respective collection
            util._link_to_single_collection(obj, collection)

            obj.data.wow_m2_light.type = str(light.type)
            obj.data.wow_m2_light.enabled = True

            if self.rig:
                obj.parent = self.rig

            # --- Attach light to bone if available ---
            if light.bone >= 0:
                try:
                    bpy.ops.object.constraint_add(type="CHILD_OF")
                    constraint = obj.constraints[-1]
                    constraint.target = self.rig
                    bone = self.m2.root.bones[light.bone]
                    constraint.subtarget = bone.name
                    obj.location = light.position
                except (IndexError, KeyError):
                    log.warn(f"Light {i} references an invalid bone index ({light.bone}). Skipping bone binding.")

            # --- Setup animation data ---
            obj.animation_data_create()
            obj.animation_data.action_blend_type = "ADD"

            seq_name_table = M2SequenceNames()
            n_global_sequences = len(self.global_sequences)

            channels = [
                ("ambient_color", 3),
                ("ambient_intensity", 1),
                ("diffuse_color", 3),
                ("diffuse_intensity", 1),
                ("attenuation_start", 1),
                ("attenuation_end", 1),
                ("visibility", 1),
            ]

            # --- Load global sequences ---
            for j, seq_index in enumerate(self.global_sequences):
                anim = bpy.context.scene.wow_m2_animations[j]
                if anim.is_alias:
                    continue

                # Determine if anything in this light uses this global sequence
                needs_animation = any(
                    getattr(light, channel).global_sequence == seq_index
                    for channel, _ in channels
                )
                if not needs_animation:
                    continue

                # Create a new anim_pair
                anim_pair = anim.anim_pairs.add()
                anim_pair.type = "OBJECT"
                anim_pair.object = obj

                action_name = f"LT_{i}_{obj.name}_Global_Sequence_{str(j).zfill(3)}"
                self._bl_create_action(anim_pair, action_name)

                if not anim_pair.action:
                    log.warn(f"Failed to create action for light {i}, global seq #{j}")
                    continue

                for channel, array_length in channels:
                    if getattr(light, channel).global_sequence == seq_index:
                        animate_property(anim_pair, light, channel, array_length, action_name, 0)

            # --- Load regular animations ---
            for j, anim_index in enumerate(self.animations):
                anim = bpy.context.scene.wow_m2_animations[j + n_global_sequences]
                if anim.is_alias:
                    continue

                # Determine if any channel of this light animates in this animation
                needs_animation = any(
                    getattr(light, channel).global_sequence < 0
                    for channel, _ in channels
                )
                if not needs_animation:
                    continue

                sequence = self.m2.root.sequences[anim_index]
                field_name = seq_name_table.get_sequence_name(sequence.id)
                if field_name:
                    action_name = f"LT_{i}_{str(j).zfill(3)}_{field_name}({sequence.variation_index})"
                else:
                    action_name = f"LT_{i}_{str(j).zfill(3)}_UnkAnim"

                anim_pair = anim.anim_pairs.add()
                anim_pair.type = "OBJECT"
                anim_pair.object = obj

                self._bl_create_action(anim_pair, action_name)

                if not anim_pair.action:
                    log.warn(f"Failed to create action for light {i}, anim #{anim_index}")
                    continue

                for channel, array_length in channels:
                    if getattr(light, channel).global_sequence < 0:
                        animate_property(anim_pair, light, channel, array_length, action_name, anim_index)

        # --- Log success ---
        log.info(f"Imported {len(self.m2.root.lights)} lights.")

    def load_events(self, collection):
        """Import M2 events and link them to their corresponding bones."""

        if not len(self.m2.root.events):
            log.info("No events found to import.")
            return

        for i, event in tqdm(enumerate(self.m2.root.events),total=len(self.m2.root.events), desc="Importing Events", ascii=True):
            # --- Create event object ---
            bpy.ops.object.empty_add(type="CUBE", location=(0, 0, 0))
            obj = bpy.context.view_layer.objects.active
            obj.scale = (0.019463, 0.019463, 0.019463)
            
            # Link object to respective collection
            util._link_to_single_collection(obj, collection)
            
            # --- Add and configure constraint ---
            bpy.ops.object.constraint_add(type="CHILD_OF")
            constraint = obj.constraints[-1]
            constraint.target = self.rig
            
            try:
                bone = self.m2.root.bones[event.bone]
                constraint.subtarget = bone.name
                obj.location = event.position
            except (IndexError, KeyError):
                log.warn(f"Event {event.identifier} references invalid bone index ({event.bone}). Skipping binding.")
                continue

            # --- Configure event object ---
            token = M2EventTokens.get_event_name(event.identifier)
            obj.name = f"Event_{token}_{event.identifier}"
            obj.wow_m2_event.enabled = True

            try:
                obj.wow_m2_event.token = event.identifier
            except TypeError:
                log.warn(f"Unknown event token '{event.identifier}'.")

            if token in (
                "PlayEmoteSound",
                "DoodadSoundUnknown",
                "DoodadSoundOneShot",
                "GOPlaySoundKitCustom",
                "GOAddShake",
            ):
                obj.wow_m2_event.data = event.data

            # --- Setup animation data ---
            obj.animation_data_create()
            obj.animation_data.action_blend_type = "ADD"

            seq_name_table = M2SequenceNames()
            n_global_sequences = len(self.global_sequences)

            # --- Handle global sequence animation ---
            if event.enabled.global_sequence >= 0:
                anim = bpy.context.scene.wow_m2_animations[event.enabled.global_sequence]

                if (
                    not event.enabled.timestamps.n_elements
                    or not event.enabled.timestamps[0]
                ):
                    continue

                anim_pair = anim.anim_pairs.add()
                anim_pair.type = "OBJECT"
                anim_pair.object = obj

                name = f"ET_{token}_{str(event.enabled.global_sequence).zfill(3)}_UnkAnim"

                self._bl_create_action(anim_pair, name)
                self._bl_create_fcurves(
                    anim_pair.action,
                    "",
                    self._bl_convert_track_dummy,
                    1,
                    0,
                    "wow_m2_event.fire",
                    event.enabled,
                )

                # Return to skip redundant per-anim handling
                continue

            # --- Handle per-animation events ---
            for j, anim_index in enumerate(self.animations):
                anim = bpy.context.scene.wow_m2_animations[j + n_global_sequences]
                sequence = self.m2.root.sequences[anim_index]

                if event.enabled.timestamps.n_elements <= anim_index:
                    continue

                if not event.enabled.timestamps[anim_index]:
                    continue

                # --- Handle alias animations ---
                if "64" in anim.flags:
                    alias_next = anim.alias_next
                    final_alias = _find_final_alias(self, n_global_sequences, alias_next)
                    alias_anim = bpy.context.scene.wow_m2_animations[final_alias]

                    for anim_pair_alias in alias_anim.anim_pairs:
                        if anim_pair_alias.type == "OBJECT" and anim_pair_alias.object == obj:
                            anim_pair = anim.anim_pairs.add()
                            anim_pair.type = "OBJECT"
                            anim_pair.object = obj
                            anim_pair.action = anim_pair_alias.action
                else:
                    anim_pair = anim.anim_pairs.add()
                    anim_pair.type = "OBJECT"
                    anim_pair.object = obj

                    field_name = seq_name_table.get_sequence_name(sequence.id)
                    name = (
                        f"ET_{token}_{str(anim_index).zfill(3)}_UnkAnim"
                        if not field_name
                        else f"ET_{token}_{str(anim_index).zfill(3)}_{field_name}({sequence.variation_index})"
                    )

                    self._bl_create_action(anim_pair, name)
                    self._bl_create_fcurves(
                        anim_pair.action,
                        "",
                        self._bl_convert_track_dummy,
                        1,
                        anim_index,
                        "wow_m2_event.fire",
                        event.enabled,
                    )

        # --- Log success ---
        log.info(f"Imported {len(self.m2.root.events)} events.")

    def load_cameras(self, collection, timestamp_convert):
        """Import M2 camera objects, targets, and animation data into Blender."""

        def animate_camera_loc(anim_pair, name, cam_track, anim_index):
            """Animate camera or target location using track data."""
            try:
                frames = cam_track.timestamps[anim_index]
                track = cam_track.values[anim_index]
            except IndexError:
                return

            if len(frames) <= 1:
                return

            # Create a parent object for curve segments
            parent_obj = bpy.data.objects.new(name, None)
            bpy.context.collection.objects.link(parent_obj)

            curves = []
            convert = (timestamp_convert == "Convert")
            converted_frames = [frame for _, frame in self.convert_timestamps(frames, convert)]

            for i in range(1, len(converted_frames)):
                frame1 = converted_frames[i - 1]
                frame2 = converted_frames[i]

                curve_name = f"{anim_pair.object.name}_Path"
                curve = bpy.data.curves.new(name=curve_name, type="CURVE")
                curve_obj = bpy.data.objects.new(name=curve_name, object_data=curve)
                curve_obj.parent = parent_obj
                bpy.context.collection.objects.link(curve_obj)

                curve.dimensions = "3D"
                curve.resolution_u = 64

                spline = curve.splines.new("BEZIER")
                spline.resolution_u = 64
                spline.bezier_points.add(count=1)

                for j, k in enumerate((i - 1, i)):
                    spline_point = spline.bezier_points[j]
                    spline_point.co = Vector(track[k].value) + anim_pair.object.location
                    spline_point.handle_left_type = "FREE"
                    spline_point.handle_left = Vector(track[k].in_tan) + anim_pair.object.location
                    spline_point.handle_right_type = "FREE"
                    spline_point.handle_right = Vector(track[k].out_tan) + anim_pair.object.location

                curve_slot = anim_pair.object.wow_m2_camera.animation_curves.add()
                curve_slot.object = curve_obj
                curve_slot.duration = frame2 - frame1
                curves.append(curve_obj)

            # Adjust endpoints (zero tangent handles)
            first_point = curves[0].data.splines[0].bezier_points[0]
            first_point.handle_left = first_point.co
            last_point = curves[-1].data.splines[0].bezier_points[-1]
            last_point.handle_right = last_point.co

            # Set up follow path constraints and drivers
            anim_pair.object.location = (0, 0, 0)
            bpy.context.view_layer.objects.active = anim_pair.object
            update_follow_path_constraints(None, bpy.context)

        def animate_camera_roll(anim_pair, name, cam_track, anim_index):
            """Animate camera roll using axis-angle rotation."""
            try:
                frames = cam_track.timestamps[anim_index]
                track = cam_track.values[anim_index]
            except IndexError:
                return

            if not len(frames):
                return

            action = anim_pair.action or bpy.data.actions.new(name=name)
            anim_pair.action = action

            # Create roll F-curve
            fcurve = action.fcurves.new(
                data_path="rotation_axis_angle", index=0, action_group="Roll"
            )
            fcurve.keyframe_points.add(len(frames))

            for i, frame in self.convert_timestamps(frames, convert=(timestamp_convert == "Convert")):
                key = fcurve.keyframe_points[i]
                key.co = frame, track[i].value
                key.handle_left = frame, track[i].in_tan
                key.handle_left_type = "ALIGNED"
                key.handle_right = frame, track[i].out_tan
                key.handle_right_type = "ALIGNED"
                key.interpolation = "BEZIER"  # TODO: Hermite interpolation

        # --- Validation ---
        if not len(self.m2.root.cameras):
            log.info("No cameras found to import.")
            return

        camera_names = {0: "PortraitCam", 1: "CharInfoCam", -1: "MiscCam"}
        n_global_sequences = len(self.global_sequences)

        for i, camera in tqdm(enumerate(self.m2.root.cameras), total=len(self.m2.root.cameras), desc="Importing Cameras", ascii=True):
            # --- Create camera object ---
            cam_data = bpy.data.cameras.new(camera_names.get(camera.type, "UnknownCam"))
            obj = bpy.data.objects.new(camera_names.get(camera.type, "UnknownCam"), cam_data)
            
            # Link object to respective collection
            util._link_to_single_collection(obj, collection)

            obj.location = camera.position_base
            obj.wow_m2_camera.type = str(camera.type)
            obj.data.clip_start = camera.near_clip
            obj.data.clip_end = camera.far_clip
            obj.data.lens_unit = "FOV"
            obj.data.angle = camera.fov
            obj.animation_data_create()
            obj.animation_data.action_blend_type = "ADD"

            # --- Create camera target object ---
            t_obj_name = f"{obj.name}_Target"
            t_obj = bpy.data.objects.new(t_obj_name, None)
            
            # Link target object to respective collection
            util._link_to_single_collection(t_obj, collection)
            
            t_obj.location = camera.target_position_base
            t_obj.wow_m2_camera.enabled = True
            t_obj.empty_display_size = 0.07
            t_obj.empty_display_type = "CONE"
            t_obj.rotation_mode = "AXIS_ANGLE"
            t_obj.rotation_axis_angle = (0, 1, 0, 0)
            t_obj.lock_rotation = (True, True, True)
            t_obj.animation_data_create()
            t_obj.animation_data.action_blend_type = "ADD"

            # --- Global sequence animations ---
            for j, seq_index in enumerate(self.global_sequences):
                anim = bpy.context.scene.wow_m2_animations[j]

                c_anim_pair = anim.anim_pairs.add()
                c_anim_pair.type = "OBJECT"
                c_anim_pair.object = obj

                t_anim_pair = anim.anim_pairs.add()
                t_anim_pair.type = "OBJECT"
                t_anim_pair.object = t_obj

                base_name = f"_{str(j).zfill(3)}_UnkAnim"
                c_name = f"CM{base_name}"
                t_name = f"CT{base_name}"

                if camera.positions.global_sequence == seq_index:
                    animate_camera_loc(c_anim_pair, c_name, camera.positions, 0)
                if camera.target_position.global_sequence == seq_index:
                    animate_camera_loc(t_anim_pair, t_name, camera.target_position, 0)
                if camera.roll.global_sequence == seq_index:
                    animate_camera_roll(t_anim_pair, t_name, camera.roll, 0)

            # --- Per-animation sequences ---
            seq_names = M2SequenceNames()
            for j, anim_index in enumerate(self.animations):
                anim = bpy.context.scene.wow_m2_animations[j + n_global_sequences]
                sequence = self.m2.root.sequences[anim_index]

                # --- Handle alias animations ---
                if "64" in anim.flags:
                    alias_next = anim.alias_next
                    final_alias = _find_final_alias(self, n_global_sequences, alias_next)
                    alias_anim = bpy.context.scene.wow_m2_animations[final_alias]

                    for alias_pair in alias_anim.anim_pairs:
                        if alias_pair.type == "OBJECT":
                            if alias_pair.object == obj or alias_pair.object == t_obj:
                                new_pair = anim.anim_pairs.add()
                                new_pair.type = "OBJECT"
                                new_pair.object = alias_pair.object
                                new_pair.action = alias_pair.action
                    continue

                # --- Normal animation ---
                c_anim_pair = anim.anim_pairs.add()
                c_anim_pair.type = "OBJECT"
                c_anim_pair.object = obj

                t_anim_pair = anim.anim_pairs.add()
                t_anim_pair.type = "OBJECT"
                t_anim_pair.object = t_obj

                field_name = seq_names.get_sequence_name(sequence.id)
                base_name = (
                    f"_{str(anim_index).zfill(3)}_UnkAnim"
                    if not field_name
                    else f"_{str(anim_index).zfill(3)}_{field_name}({sequence.variation_index})"
                )
                c_name = f"CM{base_name}"
                t_name = f"CT{base_name}"

                if camera.positions.global_sequence < 0:
                    animate_camera_loc(c_anim_pair, c_name, camera.positions, anim_index)
                if camera.target_position.global_sequence < 0:
                    animate_camera_loc(t_anim_pair, t_name, camera.target_position, anim_index)
                if camera.roll.global_sequence < 0:
                    animate_camera_roll(t_anim_pair, t_name, camera.roll, anim_index)

            # --- Set camera target ---
            bpy.context.view_layer.objects.active = obj
            obj.wow_m2_camera.target = t_obj
            
        # --- Log success ---
        log.info(f"Imported {len(self.m2.root.cameras)} cameras.")

    def load_ribbons(self, collection):
        """Import ribbon emitters from the M2 file into Blender."""

        # --- Validation ---
        if not len(self.m2.root.ribbon_emitters):
            log.info("No ribbons found to import.")
            return

        loaded_mats = {}

        for i, ribbon in tqdm(enumerate(self.m2.root.ribbon_emitters), total=len(self.m2.root.ribbon_emitters), desc="Importing Ribbons", ascii=True):
            # --- Create ribbon object ---
            bpy.ops.object.empty_add(type="SPHERE", location=(0, 0, 0))
            obj = bpy.context.view_layer.objects.active
            obj.empty_display_size = 0.07
            
            # Link object to respective collection
            util._link_to_single_collection(obj, collection)

            # --- Attach to bone ---
            bpy.ops.object.constraint_add(type="CHILD_OF")
            constraint = obj.constraints[-1]
            constraint.target = self.rig

            try:
                bone = self.m2.root.bones[ribbon.bone_index]
                constraint.subtarget = bone.name
                obj.location = ribbon.position
            except (IndexError, KeyError):
                log.warn(f"Ribbon {i} references invalid bone index ({ribbon.bone_index}). Skipping binding.")
                continue

            # --- Set object properties ---
            obj.name = f"Ribbon_{i}"
            obj.wow_m2_ribbon.enabled = True

            obj.wow_m2_ribbon.edges_per_second = ribbon.edges_per_second
            obj.wow_m2_ribbon.edge_lifetime = ribbon.edge_lifetime
            obj.wow_m2_ribbon.gravity = ribbon.gravity
            obj.wow_m2_ribbon.texture_rows = ribbon.texture_rows
            obj.wow_m2_ribbon.texture_cols = ribbon.texture_cols

            obj.animation_data_create()
            obj.animation_data.action_blend_type = "ADD"

            # --- Load textures ---
            for tex_id in ribbon.texture_indices:
                try:
                    tex = self.load_texture(tex_id)
                    tex_slot = obj.wow_m2_ribbon.textures.add()
                    tex_slot.pointer = tex
                except Exception as e:
                    log.warn(f"Failed to load texture {tex_id} for Ribbon {i}: {e}")
                    continue

            # --- Load materials ---
            mat = None
            for mat_id in ribbon.material_indices:
                if mat_id in loaded_mats:
                    mat = loaded_mats[mat_id]
                else:
                    try:
                        material = self.m2.root.materials[mat_id]
                        mat = bpy.data.materials.new(name=f"Ribbon_Material_{mat_id}")
                        mat.wow_m2_material.enabled = True
                        mat.wow_m2_material.texture_1_render_flags = parse_bitfield(material.flags, 0x800)
                        mat.wow_m2_material.texture_1 = tex
                        mat.wow_m2_material.texture_1_blending_mode = str(material.blending_mode)
                        loaded_mats[mat_id] = mat
                    except IndexError:
                        log.warn(f"Material index {mat_id} out of range for Ribbon {i}. Skipping.")
                        continue

            # --- Assign material to ribbon ---
            if mat:
                mat_slot = obj.wow_m2_ribbon.materials.add()
                mat_slot.pointer = mat

            # --- Animate ribbon tracks ---
            ribbon_tracks = [
                ("color_track",        "color",         3, self._bl_convert_track_tuple),
                ("alpha_track",        "alpha",         1, lambda v: [v / 0x7FFF]),
                ("height_above_track", "height_above",  1, self._bl_convert_track_value),
                ("height_below_track", "height_below",  1, self._bl_convert_track_value),
                ("tex_slot_track",     "texture_slot",  1, self._bl_convert_track_value),
                ("visibility_track",   "visibility",    1, self._bl_convert_track_value),
            ]

            for track_name, m2_prop, dimension, converter in ribbon_tracks:
                self._bl_create_sequences(ribbon, track_name, f"RB_{i}", obj, "wow_m2_ribbon", m2_prop, dimension, converter)

        # --- Log success ---
        log.info(f"Imported {len(self.m2.root.ribbon_emitters)} ribbon emitters.")

    def load_particles(self, collection, timestamp_convert):
        """Import M2 particle emitters into Blender, preserving all animation tracks."""

        # --- Validation ---
        if not len(self.m2.root.particle_emitters):
            log.info("No particles found to import.")
            return

        for i, m2_particle in tqdm(enumerate(self.m2.root.particle_emitters), total=len(self.m2.root.particle_emitters), desc="Importing Particles", ascii=True):
            # --- Create particle object ---
            bpy.ops.object.empty_add(type="SPHERE", location=(0, 0, 0))
            obj = bpy.context.view_layer.objects.active
            obj.empty_display_size = 0.07
            
            # Link object to respective collection
            util._link_to_single_collection(obj, collection)

            # --- Attach to bone ---
            bpy.ops.object.constraint_add(type="CHILD_OF")
            constraint = obj.constraints[-1]
            constraint.target = self.rig

            try:
                bone = self.m2.root.bones[m2_particle.bone]
                constraint.subtarget = bone.name
                obj.location = m2_particle.position
            except (IndexError, KeyError):
                log.warn(f"Particle {i} references invalid bone index ({m2_particle.bone}). Skipping binding.")
                continue

            # --- Initialize particle object ---
            obj.name = f"Particle_{i}"
            obj.wow_m2_particle.enabled = True
            obj.animation_data_create()
            bl_particle = obj.wow_m2_particle

            # --- Static properties ---
            bl_particle.flags = parse_bitfield(m2_particle.flags, 0x80000)
            bl_particle.texture = self.load_texture(m2_particle.texture)
            bl_particle.geometry_model_filename = m2_particle.geometry_model_filename.value
            bl_particle.recursion_model_filename = m2_particle.recursion_model_filename.value
            bl_particle.blending_type = str(m2_particle.blending_type)
            bl_particle.emitter_type = str(m2_particle.emitter_type)
            bl_particle.particle_color_index = m2_particle.particle_color_index

            try:
                bl_particle.particle_type = str(m2_particle.particle_type)
            except TypeError:
                bl_particle.particle_type = "0"

            try:
                bl_particle.side = str(m2_particle.head_or_tail)
            except TypeError:
                bl_particle.side = "0"

            bl_particle.texture_tile_rotation = m2_particle.texture_tile_rotation
            bl_particle.texture_dimensions_rows = m2_particle.texture_dimensions_rows
            bl_particle.texture_dimensions_cols = m2_particle.texture_dimension_columns
            bl_particle.lifespan_vary = m2_particle.life_span_vary
            bl_particle.emission_rate_vary = m2_particle.emission_rate_vary
            bl_particle.scale_vary = m2_particle.scale_vary
            bl_particle.tail_length = m2_particle.tail_length
            bl_particle.twinkle_speed = m2_particle.twinkle_speed
            bl_particle.twinkle_percent = m2_particle.twinkle_percent
            bl_particle.twinkle_scale = (m2_particle.twinkle_scale.min, m2_particle.twinkle_scale.max)
            bl_particle.burst_multiplier = m2_particle.burst_multiplier
            bl_particle.drag = m2_particle.drag
            bl_particle.basespin = m2_particle.basespin
            bl_particle.base_spin_vary = m2_particle.base_spin_vary
            bl_particle.spin = m2_particle.spin
            bl_particle.spin_vary = m2_particle.spin_vary
            bl_particle.tumble_min = m2_particle.tumble.model_rotation_speed_min
            bl_particle.tumble_max = m2_particle.tumble.model_rotation_speed_max
            bl_particle.wind = m2_particle.wind_vector
            bl_particle.wind_time = m2_particle.wind_time
            bl_particle.follow_speed_1 = m2_particle.follow_speed1
            bl_particle.follow_scale_1 = m2_particle.follow_scale1
            bl_particle.follow_speed_2 = m2_particle.follow_speed2
            bl_particle.follow_scale_2 = m2_particle.follow_scale2

            # --- Standard track-based animations ---
            particle_tracks = [
                ("emission_speed",        "emission_speed"),
                ("speed_variation",       "speed_variation"),
                ("vertical_range",        "vertical_range"),
                ("horizontal_range",      "horizontal_range"),
                ("gravity",               "gravity"),
                ("lifespan",              "lifespan"),
                ("emission_rate",         "emission_rate"),
                ("emission_area_length",  "emission_area_length"),
                ("emission_area_width",   "emission_area_width"),
                ("z_source",              "z_source"),
                ("enabled_in",            "active"),
            ]

            for track_name, m2_prop in particle_tracks:
                self._bl_create_sequences(m2_particle, track_name, f"PT_{i}", obj, "wow_m2_particle", m2_prop, 1, self._bl_convert_track_value)

            # --- Helper: generic fcurve creation ---
            def create_fcurve_track(action, m2_track, bl_track_name, group_name, track_count, conv=lambda x: x):
                """Create Blender FCurves for a given particle track."""
                fcurves = [
                    action.fcurves.new(
                        data_path=f"wow_m2_particle.{bl_track_name}",
                        index=k,
                        action_group=group_name
                    )
                    for k in range(track_count)
                ]

                frame_count = len(m2_track.timestamps)
                for fcurve in fcurves:
                    fcurve.keyframe_points.add(frame_count)

                for (k, time), key in zip(
                    self.convert_timestamps(m2_track.timestamps, convert=(timestamp_convert == "Convert")),
                    m2_track.keys
                ):
                    value = conv(key)
                    for j, fcurve in enumerate(fcurves):
                        keyframe = fcurve.keyframe_points[k]
                        keyframe.co = (time, value if track_count == 1 else value[j])
                        keyframe.interpolation = "LINEAR"

            # --- Animated color, alpha, scale, cell tracks ---
            obj.animation_data_create()
            obj.animation_data.action_blend_type = "ADD"

            particle_action = bpy.data.actions.new(name=f"PT_{obj.name}_particle_tracks")
            particle_action.use_fake_user = True
            obj.wow_m2_particle.action = particle_action

            create_fcurve_track(
                particle_action, m2_particle.color_track,
                "color", "Color", 3, lambda x: (x[0] / 255, x[1] / 255, x[2] / 255)
            )

            create_fcurve_track(
                particle_action, m2_particle.alpha_track,
                "alpha", "", 1, lambda x: x / 0x7FFF
            )

            create_fcurve_track(particle_action, m2_particle.scale_track, "scale", "Scale", 2)
            create_fcurve_track(particle_action, m2_particle.head_cell_track, "head_cell", "", 1)
            create_fcurve_track(particle_action, m2_particle.tail_cell_track, "tail_cell", "", 1)

            # --- Animated spline track ---
            spline_action = bpy.data.actions.new(name=f"PT_{obj.name}_particle_spline")
            spline_action.use_fake_user = True
            obj.wow_m2_particle.spline_action = spline_action

            fake_spline_fcurve = FBlock(vec3D)
            fake_spline_fcurve.interpolation_type = 1

            convert = (timestamp_convert == "Convert")
            scale = self.fps / 1000.0

            for i, spline in enumerate(m2_particle.spline_points):
                timestamp = int(round(i / scale)) if convert else i
                fake_spline_fcurve.timestamps.append(timestamp)
                fake_spline_fcurve.keys.append(spline)

            create_fcurve_track(spline_action, fake_spline_fcurve, "spline_point", "Spline", 3)
            
        # --- Log success ---
        log.info(f"Imported {len(self.m2.root.particle_emitters)} particle emitter.")

    def load_collision(self, collection):
        """Import the M2 collision mesh into Blender."""

        # --- Validation ---
        if not len(self.m2.root.collision_vertices):
            log.info("No collision mesh found to import.")
            return

        # --- Prepare mesh data ---
        vertices = [v for v in self.m2.root.collision_vertices]
        triangles = [
            self.m2.root.collision_triangles[i:i + 3]
            for i in range(0, len(self.m2.root.collision_triangles), 3)
        ]

        # --- Create mesh ---
        mesh = bpy.data.meshes.new(self.m2.root.name.value)
        mesh.from_pydata(vertices, [], triangles)

        for poly in mesh.polygons:
            poly.use_smooth = True

        # --- Create Blender object ---
        obj = bpy.data.objects.new("Collision", mesh)
        
        # Link object to respective collection
        util._link_to_single_collection(obj, collection)

        obj.wow_m2_geoset.collision_mesh = True
        obj.hide_set(True)

        # --- Create transparent material ---
        bl_mat = bpy.data.materials.new(name="Collision")
        bl_mat.blend_method = "BLEND"
        bl_mat.use_nodes = True

        node_tree = bl_mat.node_tree

        # Clear default nodes
        for node in list(node_tree.nodes):
            node_tree.nodes.remove(node)

        # Transparent shader setup
        transparent_bsdf = node_tree.nodes.new(type="ShaderNodeBsdfTransparent")
        output_node = node_tree.nodes.new(type="ShaderNodeOutputMaterial")
        node_tree.links.new(transparent_bsdf.outputs["BSDF"], output_node.inputs["Surface"])

        bsdf = node_tree.nodes["Transparent BSDF"]
        bsdf.inputs["Color"].default_value = (0.381325, 0.887923, 0.371238, 1)

        obj.data.materials.append(bl_mat)
        
        # --- Log success ---
        log.info("Imported collision mesh.")

    def load_globalflags(self, collection):
        """Import M2 global flags and attach to the M2 root collection."""
        if not collection or not hasattr(collection, "wow_m2_globalflags"):
            log.warn("No M2 root collection to attach global flags.")
            return

        bl_globalflags = collection.wow_m2_globalflags
        bl_globalflags.enabled = True

        flags_value = self.m2.root.global_flags

        try:
            if self.m2.root.version >= M2Versions.WOTLK:
                flags_lk = parse_bitfield(self.m2.root.global_flags, 0x10)
                bl_globalflags.flagsLK = set(flags_lk)
                log.debug(f"Parsed LK flags: {flags_lk}")
            else:
                flags_legion = parse_bitfield(self.m2.root.global_flags, 0x200000)
                bl_globalflags.flagsLegion = set(flags_legion)
                log.info(f"Parsed Legion flags: {flags_legion}")

            log.info(f"Imported global flags to collection '{collection.name}'")

        except Exception as e:
            tb = traceback.format_exc()
            log.error(f"Failed to import global flags: {e}\n{tb}")

    def prepare_export_axis(self, forward_axis, scale):
        self.scale = scale
        self.forward_axis = forward_axis

        # Apply armature scale if present
        armatures = [obj for obj in bpy.data.objects if obj.type == 'ARMATURE']
        if armatures:
            armature = armatures[0]
            arm_scale = armature.scale

            # Check non-uniform scaling
            if (
                abs(arm_scale[0] - arm_scale[1]) > 0.0001
                or abs(arm_scale[0] - arm_scale[2]) > 0.0001
            ):
                raise ValueError(f"Non-uniform object scaling in armature {armature.name}, WBS can't handle this yet :(")

            self.scale *= arm_scale[0]

        # Axis mapping table
        axis_map = {
            "X+": ([0, 1], [ 1,  1]),
            "X-": ([0, 1], [-1, -1]),
            "Y+": ([1, 0], [ 1, -1]),
            "Y-": ([1, 0], [-1,  1]),
        }

        try:
            self.axis_order, self.axis_polarity = axis_map[forward_axis]
        except KeyError:
            raise ValueError(f"Invalid forward axis: {forward_axis}") from None

    def _convert_vec(self,vec):
        return (
            vec[self.axis_order[0]] * self.axis_polarity[0] * self.scale,
            vec[self.axis_order[1]] * self.axis_polarity[1] * self.scale,
            vec[2] * self.scale
        )

    def prepare_pose(self, selected_only):

        if bpy.context.object:
            self.old_mode = bpy.context.object.mode
        else:
            armatures = [obj for obj in bpy.data.objects if obj.type == 'ARMATURE']
            armature = armatures[0]
            bpy.data.objects[armature.name].select_set(True)
            bpy.context.view_layer.objects.active = bpy.data.objects[armature.name]
            self.old_mode = bpy.context.object.mode 
        
        

        self.old_selections = [obj for obj in bpy.context.selected_objects]
        self.old_active = bpy.context.active_object

        objects = bpy.context.selected_objects if selected_only else bpy.context.scene.objects

        # TODO: this is a temporary fix to reset pose, because wbs uses the wrong data
        #       when reading bone and vertex positions.
        for obj in objects:
            if obj.type != 'ARMATURE' or not obj.animation_data:
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
        """
        Exports model root properties such as name, bounding box, and bounding sphere.
        """
        try:
            # --- Set model name ---
            try:
                self.m2.root.name.value = os.path.basename(os.path.splitext(filepath)[0])
                log.debug(f"Set model name to '{self.m2.root.name.value}'")
            except Exception as e:
                log.error(f"Failed to set model name from filepath '{filepath}': {e}")
                self.m2.root.name.value = "UnnamedModel"

            # --- Collect objects ---
            try:
                objects = bpy.context.selected_objects if selected_only else bpy.context.scene.objects
                log.debug(f"Collected {len(objects)} objects ({'selected only' if selected_only else 'entire scene'}).")
            except Exception as e:
                log.error(f"Failed to retrieve Blender objects: {e}")
                return

            # --- Filter valid mesh objects ---
            try:
                valid_objects = list(filter(
                    lambda ob: (
                        hasattr(ob, "wow_m2_geoset")
                        and not ob.wow_m2_geoset.collision_mesh
                        and ob.type == 'MESH'
                        and not ob.hide_get()
                    ),
                    objects
                ))

                if not valid_objects:
                    log.warn("No valid mesh objects found for bounding box calculation.")
                    return

                log.debug(f"Filtered {len(valid_objects)} valid mesh objects for bounding box.")
            except Exception as e:
                log.error(f"Failed to filter valid mesh objects: {e}")
                return

            # --- Compute bounding box ---
            try:
                b_min, b_max = get_objs_boundbox_world(valid_objects)
                b_min = self._convert_vec(b_min)
                b_max = self._convert_vec(b_max)
                log.debug(f"Computed bounding box: min={b_min}, max={b_max}")
            except Exception as e:
                log.error(f"Failed to compute bounding box: {e}")
                b_min = (0.0, 0.0, 0.0)
                b_max = (1.0, 1.0, 1.0)
                log.warn("Using default bounding box values (0,0,0)-(1,1,1).")

            # --- Assign bounding box to model ---
            try:
                self.m2.root.bounding_box.min = b_min
                self.m2.root.bounding_box.max = b_max
            except Exception as e:
                log.error(f"Failed to assign bounding box values: {e}")

            # --- Compute bounding sphere radius ---
            try:
                dx = (b_max[self.axis_order[0]] - b_min[self.axis_order[0]]) * self.axis_polarity[0] * self.scale
                dy = (b_max[self.axis_order[1]] - b_min[self.axis_order[1]]) * self.axis_polarity[1] * self.scale
                dz = (b_max[2] - b_min[2])
                self.m2.root.bounding_sphere_radius = sqrt(dx**2 + dy**2 + dz**2) / 2
                log.debug(f"Bounding sphere radius computed: {self.m2.root.bounding_sphere_radius:.4f}")
            except Exception as e:
                self.m2.root.bounding_sphere_radius = 1.0
                log.warn(f"Failed to compute bounding sphere radius: {e}, using default value (1.0).")

            # --- Placeholder for future flags / collision boxes ---
            # log.debug("TODO: Implement flags and collision bounding box export.")

            # --- Log success ---
            log.info(f"Exported model properties for '{self.m2.root.name.value}'.")

        except Exception as e:
            tb = traceback.format_exc()
            log.error(f"Unhandled exception in save_properties: {e}\n{tb}")

    def save_bones(self, selected_only):
        """
        Exports bones from the active armature to M2 format.
        """
        def add_bone(bl_bone):
            try:
                key_bone_id = int(bl_bone.wow_m2_bone.key_bone_id)
            except Exception:
                key_bone_id = -1
                log.warn(f"Bone '{bl_bone.name}' has invalid key_bone_id, defaulting to -1.")

            try:
                flags = construct_bitfield(bl_bone.wow_m2_bone.flags)
            except Exception:
                flags = 0
                log.warn(f"Bone '{bl_bone.name}' has invalid flags, defaulting to 0.")

            parent_bone = -1
            if bl_bone.parent:
                if bl_bone.parent.name in self.bone_ids:
                    parent_bone = self.bone_ids[bl_bone.parent.name]
                else:
                    log.warn(f"Bone '{bl_bone.name}' references parent '{bl_bone.parent.name}' "
                               f"which is not yet registered.")
            else:
                parent_bone = -1

            try:
                pivot = self._convert_vec(tuple(bl_bone.head))
            except Exception:
                pivot = tuple(bl_bone.head)
                log.warn(f"Bone '{bl_bone.name}' pivot conversion failed, using raw coordinates.")

            try:
                submesh_id = int(bl_bone.wow_m2_bone.submesh_id)
            except Exception:
                submesh_id = 0
                log.warn(f"Bone '{bl_bone.name}' has invalid submesh_id, defaulting to 0.")

            try:
                bone_crc = ctypes.c_uint(bl_bone.wow_m2_bone.bone_name_crc).value
            except Exception:
                bone_crc = 0
                log.warn(f"Bone '{bl_bone.name}' has invalid CRC, defaulting to 0.")

            m2_bone = self.m2.add_bone(pivot, key_bone_id, flags, parent_bone, submesh_id, bone_crc)
            self.bone_ids[bl_bone.name] = m2_bone

            log.debug(f"Added bone '{bl_bone.name}' (KeyBone={key_bone_id}, Parent={parent_bone}, Flags={flags})")

        # --- Find armatures ---
        rigs = [
            ob for ob in bpy.context.scene.objects
            if ob.type == 'ARMATURE' and not ob.hide_get()
        ]

        if len(rigs) > 1:
            log.error("M2 exporter does not support more than one armature. Hide or remove the extra one.")
            raise Exception("Error: M2 exporter does not support more than one armature. Hide or remove the extra one.")

        if not rigs:
            log.debug("No armature found — creating a dummy bone at origin.")
            if selected_only:
                bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY')
            origin = self._convert_vec(get_origin_position())
            return

        # --- Process first (and only) rig ---
        rig = rigs[0]
        self.rig = rig
        bpy.context.view_layer.objects.active = rig
        bpy.ops.object.mode_set(mode='EDIT')
        armature = rig.data

        # --- Check if bones have sort indices ---
        has_unsorted_bones = any(bone.wow_m2_bone.sort_index < 0 for bone in armature.edit_bones)

        if has_unsorted_bones:
            log.debug("Bone sort indices not found — performing hierarchy-based export order.")
            root_bone = None
            global_bones = []

            for bone in armature.edit_bones:
                if root_bone and bone.parent is None and bone.children:
                    log.error("Multiple root bones with children detected. Only one global root bone is allowed.")
                    raise Exception("Error: Multiple global root bones found. Only one root bone with children is allowed.")

                if bone.parent is None:
                    if bone.children:
                        root_bone = bone
                        add_bone(root_bone)
                    else:
                        global_bones.append(bone)

            # Add global non-parented bones
            for bone in global_bones:
                add_bone(bone)

            # Find keybone #26 if any
            root_keybone = None
            if root_bone:
                for bone in root_bone.children:
                    if bone.wow_m2_bone.key_bone_id == '26':
                        root_keybone = bone
                        continue
                    add_bone(bone)
                    for child in bone.children_recursive:
                        add_bone(child)

            if root_keybone:
                add_bone(root_keybone)
                for child in root_keybone.children_recursive:
                    add_bone(child)
        else:
            log.debug("Using predefined bone sort order for export.")
            all_bones = sorted(armature.edit_bones, key=lambda b: b.wow_m2_bone.sort_index)
            for bone in all_bones:
                add_bone(bone)

        bpy.ops.object.mode_set(mode='OBJECT')

        # --- Ensure key bone lookup is initialized ---
        if len(self.m2.root.key_bone_lookup) == 0:
            self.m2.root.key_bone_lookup.append(-1)
            log.debug("Initialized empty key bone lookup table (no keybones defined).")

        log.info(f"Exported {len(self.bone_ids)} bones from armature '{rig.name}'.")

    def save_cameras(self):
        """
        Exports all M2 cameras from Blender camera objects with wow_m2_camera data.
        """
        # --- Collect cameras ---
        cameras = [
            cam for cam in bpy.data.objects
            if cam.type == 'CAMERA' and getattr(cam, "wow_m2_camera", None)
        ]

        if not cameras:
            log.info("No cameras found in the scene.")
            return

        # --- Sort cameras by type (default fallback = 3) ---
        cameras.sort(
            key=lambda cam: int(cam.wow_m2_camera.type)
            if int(cam.wow_m2_camera.type) >= 0 else 3
        )

        success_count = 0

        for i, bl_cam in tqdm(enumerate(cameras), total=len(cameras), desc='Exporting Cameras', ascii=True):
            try:
                # --- Register camera ---
                self.camera_ids[bl_cam.name] = i
                m2_cam = M2Camera()
                bl_data = bl_cam.wow_m2_camera

                # --- Position and type ---
                try:
                    m2_cam.position_base = self._convert_vec(tuple(bl_cam.location))
                except Exception:
                    m2_cam.position_base = tuple(bl_cam.location)
                    log.warn(f"Camera '{bl_cam.name}' position could not be converted properly, using raw location.")

                try:
                    m2_cam.type = int(bl_data.type)
                except Exception:
                    m2_cam.type = 0
                    log.warn(f"Camera '{bl_cam.name}' has invalid type, defaulting to 0.")

                # --- Camera clipping distances ---
                try:
                    m2_cam.near_clip = float(bl_cam.data.clip_start)
                    m2_cam.far_clip = float(bl_cam.data.clip_end)
                except Exception:
                    m2_cam.near_clip = 0.1
                    m2_cam.far_clip = 500.0
                    log.warn(f"Camera '{bl_cam.name}' missing valid clip distances, using defaults (0.1 / 500.0).")

                # --- Field of view ---
                try:
                    m2_cam.fov = float(bl_cam.data.angle)
                except Exception:
                    m2_cam.fov = 0.785398  # ~45 degrees
                    log.warn(f"Camera '{bl_cam.name}' has invalid FOV, using default 45°.")

                # --- Handle camera target ---
                try:
                    if getattr(bl_data, "target", None):
                        target = bl_data.target
                        if target and target.type == "EMPTY":
                            m2_cam.target_position_base = self._convert_vec(tuple(target.location))
                            self.camera_target_ids[target.name] = i
                            log.debug(f"Camera '{bl_cam.name}' assigned target '{target.name}'.")
                        else:
                            log.warn(f"Camera '{bl_cam.name}' has invalid or missing target object.")
                            m2_cam.target_position_base = (0.0, 0.0, 0.0)
                    else:
                        m2_cam.target_position_base = (0.0, 0.0, 0.0)
                        log.debug(f"Camera '{bl_cam.name}' has no target assigned.")
                except Exception as e:
                    log.error(f"Failed to process camera target for '{bl_cam.name}': {e}")
                    m2_cam.target_position_base = (0.0, 0.0, 0.0)

                # --- Append to model ---
                self.m2.root.cameras.append(m2_cam)

                # --- Manage lookup table safely ---
                if m2_cam.type >= 0:
                    while len(self.m2.root.camera_lookup_table) <= m2_cam.type:
                        self.m2.root.camera_lookup_table.append(-1)
                    try:
                        self.m2.root.camera_lookup_table.set_index(m2_cam.type, i)
                    except Exception as e:
                        log.warn(f"Failed to set camera lookup table index for '{bl_cam.name}': {e}")

                # --- Log success ---
                log.debug(f"Exported Camera '{bl_cam.name}'")
                success_count += 1

            except Exception as e:
                tb = traceback.format_exc()
                log.error(f"Failed exporting camera '{bl_cam.name}': {e}\n{tb}")
                continue
                
        # --- Final summary ---
        log.info(f"Exported {success_count}/{len(cameras)} cameras successfully.")

    def save_attachments(self):
        """
        Exports all M2 attachments from Blender empties with wow_m2_attachment enabled.
        """
        # --- Collect enabled attachments ---
        attachments = [
            obj for obj in bpy.data.objects
            if obj.type == 'EMPTY' and getattr(obj, "wow_m2_attachment", None) and obj.wow_m2_attachment.enabled
        ]

        if not attachments:
            log.info("No attachments found in the scene.")
            return

        # --- Sort by attachment type (unknown types go last) ---
        attachments.sort(
            key=lambda att: int(att.wow_m2_attachment.type)
            if int(att.wow_m2_attachment.type) >= 0 else float('inf')
        )

        success_count = 0

        for i, bl_att in tqdm(enumerate(attachments), total=len(attachments), desc='Exporting Attachments', ascii=True):
            try:
                # --- Register attachment ---
                self.attachment_ids[bl_att.name] = i
                m2_att = M2Attachment()
                self.m2.root.attachments.append(m2_att)
                bl_data = bl_att.wow_m2_attachment

                # --- Attachment type ---
                try:
                    m2_att.id = int(bl_data.type)
                except Exception:
                    m2_att.id = 0
                    log.warn(f"Attachment '{bl_att.name}' has invalid type, defaulting to 0.")

                # --- Constraint / Bone assignment ---
                if bl_att.constraints:
                    constraint = bl_att.constraints[0]
                    subtarget = getattr(constraint, "subtarget", None)
                    if subtarget:
                        if subtarget in self.bone_ids:
                            m2_att.bone = self.bone_ids[subtarget]
                        else:
                            log.warn(f"Attachment '{bl_att.name}' references unknown bone '{subtarget}'. Using bone index 0.")
                            m2_att.bone = 0
                    else:
                        log.warn(f"Attachment '{bl_att.name}' has a constraint without subtarget. Using bone index 0.")
                        m2_att.bone = 0
                else:
                    log.warn(f"Attachment '{bl_att.name}' has no constraints. Using bone index 0.")
                    m2_att.bone = 0

                # --- Position conversion ---
                try:
                    m2_att.position = self._convert_vec(tuple(bl_att.location))
                except Exception:
                    m2_att.position = tuple(bl_att.location)

                # --- Ensure lookup table is large enough ---
                while len(self.m2.root.attachment_lookup_table) <= m2_att.id:
                    self.m2.root.attachment_lookup_table.append(0xFFFF)

                # --- Register attachment index ---
                try:
                    self.m2.root.attachment_lookup_table.set_index(m2_att.id, i)
                except Exception as e:
                    log.warn(f"Failed setting lookup index for attachment '{bl_att.name}' (id={m2_att.id}): {e}")

                # --- Log success ---
                log.debug(f"Exported Attachment '{bl_att.name}', Bone={m2_att.bone}")
                success_count += 1

            except Exception as e:
                tb = traceback.format_exc()
                log.error(f"Failed exporting attachment '{bl_att.name}': {e}\n{tb}")
                continue
                
        # --- Final summary ---
        log.info(f"Exported {success_count}/{len(attachments)} attachments successfully.")

    def save_events(self):
        """
        Exports all M2 events from Blender empties with wow_m2_event enabled.
        """
        # --- Collect enabled event empties ---
        events = [
            obj for obj in bpy.data.objects
            if obj.type == 'EMPTY' and getattr(obj, "wow_m2_event", None) and obj.wow_m2_event.enabled
        ]

        if not events:
            log.info("No M2 events found in the scene.")
            return

        success_count = 0

        for i, bl_evt in tqdm(enumerate(events), total=len(events), desc='Exporting Events', ascii=True):
            try:
                # --- Register event ---
                self.event_ids[bl_evt.name] = i
                m2_event = M2Event()
                self.m2.root.events.append(m2_event)
                bl_data = bl_evt.wow_m2_event

                # --- Event identifier ---
                m2_event.identifier = bl_data.token
                token_name = M2EventTokens.get_event_name(m2_event.identifier)
                if not token_name:
                    log.warn(f"Event '{bl_evt.name}' uses unknown event token '{m2_event.identifier}'.")

                # --- Safe constraint handling ---
                if bl_evt.constraints:
                    constraint = bl_evt.constraints[0]
                    subtarget = getattr(constraint, "subtarget", None)
                    if subtarget:
                        if subtarget in self.bone_ids:
                            m2_event.bone = self.bone_ids[subtarget]
                        else:
                            log.warn(f"Event '{bl_evt.name}' references unknown bone '{subtarget}'. Using bone index 0.")
                            m2_event.bone = 0
                    else:
                        log.warn(f"Event '{bl_evt.name}' has a constraint without subtarget. Using bone index 0.")
                        m2_event.bone = 0
                else:
                    log.warn(f"Event '{bl_evt.name}' has no constraints. Using bone index 0.")
                    m2_event.bone = 0

                # --- Position ---
                try:
                    m2_event.position = self._convert_vec(tuple(bl_evt.location))
                except Exception:
                    m2_event.position = tuple(bl_evt.location)

                # --- Event-specific data handling ---
                event_data_tokens = {
                    'PlayEmoteSound',
                    'DoodadSoundUnknown',
                    'DoodadSoundOneShot',
                    'GOPlaySoundKitCustom',
                    'GOAddShake'
                }

                if token_name in event_data_tokens:
                    try:
                        m2_event.data = bl_data.data
                    except Exception as e:
                        log.warn(f"Event '{bl_evt.name}' ({token_name}) missing valid data field: {e}")
                        m2_event.data = 0
                else:
                    m2_event.data = 0

                # Register final event mapping
                self.final_events[bl_evt.name] = m2_event

                # --- Summary info ---
                log.debug(f"Exported Event '{bl_evt.name}'")
                success_count += 1

            except Exception as e:
                tb = traceback.format_exc()
                log.error(f"Failed exporting event '{bl_evt.name}': {e}\n{tb}")
                continue
                
        # --- Final summary ---
        log.info(f"Exported {success_count}/{len(events)} events successfully.")

    def save_lights(self):
        """
        Exports all M2 lights from Blender objects with wow_m2_light enabled.
        """
        # --- Collect eligible lights ---
        lights = [
            light for light in bpy.data.objects
            if light.type == 'LIGHT'
            and getattr(light.data, "wow_m2_light", None)
            and light.data.wow_m2_light.enabled
        ]

        if not lights:
            log.info("No lights found in the scene.")
            return

        success_count = 0

        for i, bl_light in tqdm(enumerate(lights), desc='Exporting Lights', ascii=True):
            try:
                # --- Register light ---
                self.light_ids[bl_light.name] = i
                m2_light = M2Light()
                self.m2.root.lights.append(m2_light)

                bl_data = bl_light.data.wow_m2_light

                # --- Type ---
                try:
                    m2_light.type = int(bl_data.type)
                except Exception:
                    m2_light.type = 0
                    log.warn(f"Light '{bl_light.name}' has invalid type, defaulting to 0.")

                # --- Constraint handling ---
                if bl_light.constraints:
                    constraint = bl_light.constraints[0]
                    subtarget = getattr(constraint, "subtarget", None)
                    if subtarget:
                        if subtarget in self.bone_ids:
                            m2_light.bone = self.bone_ids[subtarget]
                        else:
                            log.warn(f"Light '{bl_light.name}' references unknown bone '{subtarget}'. Using bone index 0.")
                            m2_light.bone = 0
                    else:
                        log.warn(f"Light '{bl_light.name}' has a constraint without subtarget. Using bone index 0.")
                        m2_light.bone = 0
                else:
                    log.warn(f"Light '{bl_light.name}' has no constraints. Using bone index 0.")
                    m2_light.bone = 0

                # --- Position ---
                try:
                    m2_light.position = self._convert_vec(tuple(bl_light.location))
                except Exception as e:
                    log.warn(f"Light '{bl_light.name}' failed to convert position: {e}")
                    m2_light.position = tuple(bl_light.location)

                log.debug(f"Exported light '{bl_light.name}' successfully.")
                success_count += 1

            except Exception as e:
                tb = traceback.format_exc()
                log.error(f"Failed exporting light '{bl_light.name}': {e}\n{tb}")
                continue

        # --- Final summary ---
        log.info(f"Exported {success_count}/{len(lights)} lights successfully.")

    def save_ribbons(self):
        """
        Exports all M2 ribbon emitters from Blender empties with wow_m2_ribbon enabled.
        """
        ribbons = [
            obj for obj in bpy.data.objects
            if obj.type == 'EMPTY' and getattr(obj, "wow_m2_ribbon", None) and obj.wow_m2_ribbon.enabled
        ]

        if not ribbons:
            log.info("No ribbons found in the scene.")
            return

        ribbon_textures = {}
        ribbon_materials = {}

        success_count = 0

        for i, bl_ribbon in tqdm(enumerate(ribbons), total=len(ribbons), desc='Exporting Ribbons', ascii=True):
            try:
                self.ribbon_ids[bl_ribbon.name] = i
                m2_ribbon = M2Ribbon()
                self.m2.root.ribbon_emitters.append(m2_ribbon)
                bl_data = bl_ribbon.wow_m2_ribbon

                # --- Constraint / Bone assignment ---
                if bl_ribbon.constraints:
                    constraint = bl_ribbon.constraints[0]
                    subtarget = getattr(constraint, "subtarget", None)
                    if subtarget:
                        if subtarget in self.bone_ids:
                            m2_ribbon.bone_index = self.bone_ids[subtarget]
                        else:
                            log.warn(f"Ribbon '{bl_ribbon.name}' references unknown bone '{subtarget}'. Using bone index 0.")
                            m2_ribbon.bone_index = 0
                    else:
                        log.warn(f"Ribbon '{bl_ribbon.name}' has a constraint without subtarget. Using bone index 0.")
                        m2_ribbon.bone_index = 0
                else:
                    log.warn(f"Ribbon '{bl_ribbon.name}' has no constraints. Using bone index 0.")
                    m2_ribbon.bone_index = 0

                # --- Base ribbon data ---
                try:
                    m2_ribbon.position = self._convert_vec(tuple(bl_ribbon.location))
                except Exception:
                    m2_ribbon.position = tuple(bl_ribbon.location)

                m2_ribbon.edges_per_second = bl_data.edges_per_second
                m2_ribbon.edge_lifetime = bl_data.edge_lifetime
                m2_ribbon.gravity = bl_data.gravity
                m2_ribbon.texture_rows = bl_data.texture_rows
                m2_ribbon.texture_cols = bl_data.texture_cols

                # --- Textures ---
                if hasattr(bl_data, "textures") and len(bl_data.textures) > 0:
                    for tex_slot in bl_data.textures:
                        bl_texture = getattr(tex_slot, "pointer", None)
                        if not bl_texture:
                            log.warn(f"Ribbon '{bl_ribbon.name}' has an empty texture slot.")
                            continue

                        if bl_texture in ribbon_textures:
                            tex_id = ribbon_textures[bl_texture]
                        else:
                            try:
                                tex_id = self.m2.add_texture(
                                    bl_texture.wow_m2_texture.path,
                                    construct_bitfield(bl_texture.wow_m2_texture.flags),
                                    int(bl_texture.wow_m2_texture.texture_type)
                                )
                                ribbon_textures[bl_texture] = tex_id
                            except Exception as e:
                                log.error(f"Failed adding texture for ribbon '{bl_ribbon.name}': {e}")
                                tex_id = 0

                        m2_ribbon.texture_indices.append(tex_id)

                        try:
                            wow_path = bl_texture.wow_m2_texture.path
                            self.final_textures[wow_path] = tex_id
                        except Exception:
                            pass
                else:
                    log.warn(f"Ribbon '{bl_ribbon.name}' has no textures assigned.")

                # --- Materials ---
                if hasattr(bl_data, "materials") and len(bl_data.materials) > 0:
                    for mat_slot in bl_data.materials:
                        bl_mat = getattr(mat_slot, "pointer", None)
                        if not bl_mat:
                            log.warn(f"Ribbon '{bl_ribbon.name}' has an empty material slot.")
                            continue

                        if bl_mat in ribbon_materials:
                            mat_id = ribbon_materials[bl_mat]
                        else:
                            try:
                                m2_mat = M2Material()
                                mat_id = self.m2.root.materials.add(m2_mat)
                                m2_mat.flags = construct_bitfield(bl_mat.wow_m2_material.texture_1_render_flags)
                                m2_mat.blending_mode = int(bl_mat.wow_m2_material.texture_1_blending_mode)
                                ribbon_materials[bl_mat] = mat_id
                            except Exception as e:
                                tb = traceback.format_exc()
                                log.error(f"Failed adding material for ribbon '{bl_ribbon.name}': {e}\n{tb}")
                                mat_id = 0

                        m2_ribbon.material_indices.append(mat_id)
                else:
                    log.warn(f"Ribbon '{bl_ribbon.name}' has no materials assigned.")

                log.debug(f"Exported Ribbon '{bl_ribbon.name}' successfully with {len(m2_ribbon.texture_indices)} textures and {len(m2_ribbon.material_indices)} materials.")
                success_count += 1

            except Exception as e:
                tb = traceback.format_exc()
                log.error(f"Failed exporting ribbon '{bl_ribbon.name}': {e}\n{tb}")
                continue
                
        # --- Final summary ---
        log.info(f"Exported {success_count}/{len(ribbons)} ribbons successfully.")

    def save_particles(self, timestamp_convert):
        """
        Saves particle emitters from Blender empties with wow_m2_particle enabled.
        """
        # Collect particle empties
        particles = [obj for obj in bpy.data.objects if obj.type == 'EMPTY' and getattr(obj, "wow_m2_particle", None) and obj.wow_m2_particle.enabled]

        if not particles:
            log.info("No particle emitters found in the scene.")
            return

        particle_textures = {}

        def _to_millis(frame_time: float) -> int:
            """Convert Blender time value to milliseconds when requested."""
            if timestamp_convert == "Convert":
                fps = self.fps or 24.0  # fallback if somehow fps is 0
                denom = fps / 1000.0
                return int(round(frame_time / denom))
            return int(frame_time)

        success_count = 0

        for i, bl_obj in tqdm(enumerate(particles), total=len(particles), desc='Exporting Particles', ascii=True):
            try:
                self.particle_ids[bl_obj.name] = i
                m2_particle = M2Particle()
                self.m2.root.particle_emitters.append(m2_particle)
                bl_particle = bl_obj.wow_m2_particle

                # Basic identifiers
                m2_particle.particle_id = 4294967295

                # Position (convert to M2 coord system if needed)
                try:
                    m2_particle.position = self._convert_vec(tuple(bl_obj.location))
                except Exception:
                    # fallback to raw location if converter isn't available
                    m2_particle.position = tuple(bl_obj.location)

                # Bone binding via first constraint (if present and valid)
                if len(bl_obj.constraints) > 0:
                    subtarget = getattr(bl_obj.constraints[0], "subtarget", "") or ""
                    if not subtarget:
                        log.warn(f"Particle '{bl_obj.name}' has a constraint without subtarget; bone binding skipped.")
                    elif subtarget not in self.bone_ids:
                        log.warn(f"Particle '{bl_obj.name}' references unknown bone '{subtarget}'; bone binding skipped.")
                    else:
                        m2_particle.bone = self.bone_ids[subtarget]

                # Texture
                bl_texture = bl_particle.texture
                if bl_texture:
                    if bl_texture in particle_textures:
                        m2_particle.texture = particle_textures[bl_texture]
                    else:
                        try:
                            tex_id = self.m2.add_texture(
                                bl_texture.wow_m2_texture.path,
                                construct_bitfield(bl_texture.wow_m2_texture.flags),
                                int(bl_texture.wow_m2_texture.texture_type)
                            )
                            particle_textures[bl_texture] = tex_id  # cache so we actually reuse it later
                            m2_particle.texture = tex_id
                        except Exception as e:
                            log.warn(f"Failed to add texture for particle '{bl_obj.name}': {e}. Using texture 0.")
                            m2_particle.texture = 0
                    # track final textures mapping (safe even if empty path)
                    try:
                        wow_path = bl_texture.wow_m2_texture.path
                        if wow_path not in self.final_textures:
                            self.final_textures[wow_path] = m2_particle.texture
                    except Exception:
                        pass
                else:
                    m2_particle.texture = 0

                m2_particle.flags = construct_bitfield(bl_particle.flags)
                m2_particle.geometry_model_filename.value = bl_particle.geometry_model_filename
                m2_particle.recursion_model_filename.value = bl_particle.recursion_model_filename
                m2_particle.blending_type = int(bl_particle.blending_type)
                m2_particle.emitter_type = int(bl_particle.emitter_type)
                m2_particle.particle_color_index = bl_particle.particle_color_index
                m2_particle.particle_type = int(bl_particle.particle_type)
                m2_particle.head_or_tail = int(bl_particle.side)
                m2_particle.texture_tile_rotation = bl_particle.texture_tile_rotation
                m2_particle.texture_dimensions_rows = bl_particle.texture_dimensions_rows
                m2_particle.texture_dimension_columns = bl_particle.texture_dimensions_cols
                m2_particle.life_span_vary = bl_particle.lifespan_vary
                m2_particle.emission_rate_vary = bl_particle.emission_rate_vary
                m2_particle.scale_vary = tuple(bl_particle.scale_vary)
                m2_particle.tail_length = bl_particle.tail_length
                m2_particle.twinkle_speed = bl_particle.twinkle_speed
                m2_particle.twinkle_percent = bl_particle.twinkle_percent
                m2_particle.twinkle_scale.min = bl_particle.twinkle_scale[0]
                m2_particle.twinkle_scale.max = bl_particle.twinkle_scale[1]
                m2_particle.burst_multiplier = bl_particle.burst_multiplier
                m2_particle.drag = bl_particle.drag
                m2_particle.basespin = bl_particle.basespin
                m2_particle.base_spin_vary = bl_particle.basespin_vary
                m2_particle.spin = bl_particle.spin
                m2_particle.spin_vary = bl_particle.spin_vary
                m2_particle.tumble.model_rotation_speed_min = tuple(bl_particle.tumble_min)
                m2_particle.tumble.model_rotation_speed_max = tuple(bl_particle.tumble_max)
                m2_particle.wind_vector = tuple(bl_particle.wind)
                m2_particle.wind_time = bl_particle.wind_time
                m2_particle.follow_speed1 = bl_particle.follow_speed_1
                m2_particle.follow_scale1 = bl_particle.follow_scale_1
                m2_particle.follow_speed2 = bl_particle.follow_speed_2
                m2_particle.follow_scale2 = bl_particle.follow_scale_2

                # --------
                # Animated tracks exporter
                # --------
                def export_fcurve(m2_track, action, data_path, has_time, conv=lambda x: x):
                    fcurves = [fc for fc in action.fcurves if fc.data_path == 'wow_m2_particle.' + data_path]
                    if len(fcurves) == 0:
                        # no keys for this property in this action
                        # silently skip, but log as info for visibility
                        log.info(f"Particle '{bl_obj.name}' has no fcurves for '{data_path}' in action '{action.name}'.")
                        return

                    keyframe_count = len(fcurves[0].keyframe_points)
                    for idx, fcurve in enumerate(fcurves):
                        cur_count = len(fcurve.keyframe_points)
                        if cur_count != keyframe_count:
                            raise ValueError(
                                f"Track index {idx} keyframe count ({cur_count}) is different from index 0 ({keyframe_count}) "
                                f"in action '{action.name}', path '{data_path}'"
                            )

                    for k in range(keyframe_count):
                        values = []
                        for fcurve in fcurves:
                            values.append(fcurve.keyframe_points[k].co[1])
                        values = conv(tuple(values) if len(values) > 1 else values[0])

                        if has_time:
                            time = _to_millis(fcurves[0].keyframe_points[k].co[0])
                            m2_track.timestamps.append(time)
                            m2_track.keys.append(values)
                        else:
                            m2_track.append(values)

                # Export action curves
                if bl_particle.action:
                    try:
                        export_fcurve(m2_particle.color_track, bl_particle.action, 'color', True, lambda x: (x[0] * 255, x[1] * 255, x[2] * 255))
                        export_fcurve(m2_particle.alpha_track, bl_particle.action, 'alpha', True, lambda x: int(x * 0x7fff))
                        export_fcurve(m2_particle.scale_track, bl_particle.action, 'scale', True)
                        export_fcurve(m2_particle.head_cell_track, bl_particle.action, 'head_cell', True, lambda x: int(x))
                        export_fcurve(m2_particle.tail_cell_track, bl_particle.action, 'tail_cell', True, lambda x: int(x))
                    except Exception as e:
                        log.error(f"Failed exporting particle action curves for '{bl_obj.name}': {e}")

                # Export spline action curves
                if bl_particle.spline_action:
                    try:
                        export_fcurve(m2_particle.spline_points, bl_particle.spline_action, 'spline_point', False)
                    except Exception as e:
                        log.error(f"Failed exporting particle spline curves for '{bl_obj.name}': {e}")
            
                log.debug(f"Exported particle '{bl_obj.name}' successfully")
                success_count += 1

            except Exception as e:
                tb = traceback.format_exc()
                log.error(f"Failed exporting particle '{bl_obj.name}': {e}\n{tb}")
                continue
                
        # --- Final summary ---
        log.info(f"Exported {success_count}/{len(particles)} particles successfully.")

    def save_animations(self, timestamp_convert):
        """Export M2 animation data with safe checks and structured logging."""

        # --------
        # Helpers
        # --------
        def bl_to_m2_time(bl):
            """Convert a Blender time value to M2 time (milliseconds)."""
            if timestamp_convert == "Convert":
                fps = self.fps if self.fps > 0 else 24.0
                return int(round(bl / (fps / 1000.0)))
            return int(bl)

        def bl_to_m2_quat(n, threshold=1e-7):
            n = max(min(n, 1.0), -1.0) * 32767.0
            if abs(n) < threshold:
                n = 0.0
            # Match original sign mapping
            return int(n + 32767 if n <= 0 else n - 32768)

        def bl_to_m2_interpolation(interpolation):
            # Allow None and default to LINEAR
            if interpolation is None:
                return 1
            if interpolation == 'CONSTANT': return 0
            if interpolation == 'LINEAR':   return 1
            if interpolation == 'BEZIER':   return 2
            if interpolation == 'CUBIC':    return 3
            log.warn(f"Unknown interpolation '{interpolation}', defaulting to LINEAR.")
            return 1

        def bl_find_interpolation(fcurve):
            last_interp = None
            for point in fcurve.keyframe_points:
                if last_interp is None:
                    last_interp = point.interpolation
                else:
                    # wow does not support changing interpolation type
                    assert last_interp == point.interpolation
            return last_interp

        def func_animations_count():
            global_seq_count = 0
            for wow_seq in bpy.context.scene.wow_m2_animations:
                if wow_seq.is_global_sequence:
                    global_seq_count += 1
            return len(bpy.context.scene.wow_m2_animations) - global_seq_count

        # Used to measure the highest duration for any keyframe of a given sequence index
        global_seq_durations = {}
        seq_durations = {}

        # Used to ensure consistent data between tracks
        track_global_sequences = {}
        track_interpolations = {}

        class ObjectTracks:
            def __init__(self,seq_id,global_seq_id,pair,callback):
                self.seq_id = seq_id
                self.global_seq_id = global_seq_id
                self.compounds = make_fcurve_compound(pair.action.fcurves)
                self.pair = pair
                self.n_animations = func_animations_count()
                callback(self,pair)

            def get_paths(self):
                return self.compounds.keys()

            def get_curves(self, path):
                return self.compounds[path]

            def ensure_track_length(self, track, seq_id, anim_count, value_type=None, fill_tracks=False):

                while len(track.timestamps) <= seq_id:
                    track.timestamps.add(M2Array(uint32))

                if seq_id > 0 or fill_tracks:
                    while len(track.timestamps) < anim_count:
                        track.timestamps.add(M2Array(uint32))

                if value_type is not None:
                    while len(track.values) <= seq_id:
                        track.values.add(M2Array(value_type))

                    if seq_id > 0 or fill_tracks:
                        while len(track.values) < anim_count:
                            track.values.add(M2Array(value_type))

            def write_track(self, path, track_count, m2_track, value_type, converter = None, fill_tracks = False):
                if converter is None:
                    converter = (lambda x: x)
            
                # Exit on empty tracks
                if not path in self.compounds and not fill_tracks:
                        #log.info(f"M2 track path not found : {path}")
                        return

                anim_count = self.n_animations

                if fill_tracks and path not in self.compounds:
                    self.ensure_track_length(m2_track, self.seq_id, anim_count, value_type, fill_tracks)                 
                    return
                
                fcurves = self.get_curves(path)
                if not fcurves:
                    return

                mismatch_detected = False
                
                # Find interpolation in current action
                for i, fcurve in enumerate(fcurves.values()):
                    interpolation = None
                    
                    for point in fcurve.keyframe_points:
                        if interpolation is None:
                            interpolation = point.interpolation
                        else:
                            if interpolation != point.interpolation and not mismatch_detected:
                                log.warn(f"There's an interpolation discrepancy in {path}, found {point.interpolation}, "
                                           f"but last type for this object was {interpolation}, WoW only supports one interpolation setting. "
                                           f"Exportation will continue using the original interpolation, but make sure to check the action: {self.pair.action.name}")
                                mismatch_detected = True
                                break
                
                # Compare interpolation from (let's say a bone.translation) with other animations, to see discrepancies
                if m2_track in track_interpolations:
                    if track_interpolations[m2_track] != interpolation:
                        log.warn(
                            f"Path {path} in action {self.pair.action.name} has {interpolation} interpolation while in other sequences uses {track_interpolations[m2_track]}, WoW only supports one. "
                            f"Exportation will continue using the original interpolation, but make sure to check the action: {self.pair.action.name}"
                        )
                else:
                    m2_track.interpolation_type = bl_to_m2_interpolation(interpolation)
                    track_interpolations[m2_track] = interpolation

                # Find global sequence id discrepancies
                if not m2_track in track_global_sequences:
                    track_global_sequences[m2_track] = self.global_seq_id
                    m2_track.global_sequence = self.global_seq_id
                else:
                    if track_global_sequences[m2_track] != self.global_seq_id:
                        if self.global_seq_id != -1:
                            raise ValueError(f"\n\nPath {path} in action {self.pair.action.name} was assigned to Global Sequence: {track_global_sequences[m2_track]} and has been found using Global Sequence:  {self.global_seq_id}, WoW only supports one\nExample: If a bone.translation is animated in a Global Sequence it cannot be animated in a different Global Sequence")
                        else:
                            raise ValueError(f"\n\nPath {path} in action {self.pair.action.name} was assigned to Global Sequence: {track_global_sequences[m2_track]} and has been found in a regular animation\nExample: If a bone.translation is animated in a Global Sequence it cannot be animated in a regular animation")
                
                # Find missing tracks (For example, missing Green from RGB Color)
                for i in range(track_count):
                    if not i in fcurves:
                        raise ValueError(f"\n\nTrack index {i} from {path} missing in {self.pair.action.name} fcurves")

                # Find keyframe count discrepancies
                keyframe_count = len(fcurves[0].keyframe_points)
                for i,fcurve in fcurves.items():
                    cur_count = len(fcurve.keyframe_points)
                    if cur_count != keyframe_count:
                        raise ValueError(f"\n\nTrack index {i} keyframe count ({cur_count}) is different from index 0: {keyframe_count} in bone: {path} from action: {self.pair.action.name}")
                
                # Find timestamp discrepancies
                for i in range(keyframe_count):
                    time = fcurves[0].keyframe_points[i].co[0]
                    for j in range(track_count):
                        cur_time = fcurves[j].keyframe_points[i].co[0]
                        if cur_time != time:
                            raise ValueError(f"\n\nTrack index {j} frame {j} has a different time value ({cur_time}) from index 0 ({time}) in bone: {path} from action: {self.pair.action.name}")
                
                self.ensure_track_length(m2_track, self.seq_id, anim_count, value_type, fill_tracks)

                m2_times = m2_track.timestamps[self.seq_id]
                m2_values = m2_track.values[self.seq_id] if value_type is not None else None

                for i in range(keyframe_count):
                    time = bl_to_m2_time(fcurves[0].keyframe_points[i].co[0])
                    if m2_values is not None:
                        values = [fcurves[j].keyframe_points[i].co[1] for j in range(track_count)]
                        m2_values.add(converter(tuple(values) if len(values) > 1 else values[0]))
                    m2_times.append(time)

                # Increase the highest duration
                if self.global_seq_id >= 0:
                    if not self.global_seq_id in global_seq_durations or time > global_seq_durations[self.global_seq_id]:
                        global_seq_durations[self.global_seq_id] = time
                else:
                    if not self.seq_id in seq_durations or time > seq_durations[self.seq_id]:
                        seq_durations[self.seq_id] = max(33, time)

        # --------
        # Writers 
        # --------
        def write_light(cpd, pair):
            m2_light = self.m2.root.lights.values[self.light_ids[pair.object.name]]

            tracks = [
                ("ambient_color",        3, "ambient_color",        vec3D,   None),
                ("diffuse_color",        3, "diffuse_color",        vec3D,   None),
                ("ambient_intensity",    1, "ambient_intensity",    float32, None),
                ("diffuse_intensity",    1, "diffuse_intensity",    float32, None),
                ("attenuation_start",    1, "attenuation_start",    float32, None),
                ("attenuation_end",      1, "attenuation_end",      float32, None),
                ("visibility",           1, "visibility",           uint8,   (lambda x: int(x))),
            ]

            for name, dim, attr, dtype, conv in tracks:
                value = getattr(m2_light, attr)
                cpd.write_track(f"data.wow_m2_light.{name}", dim, value, dtype, conv)

        def write_attachment(cpd, pair):
            m2_attachment = self.m2.root.attachments.values[self.attachment_ids[pair.object.name]]
            cpd.write_track('wow_m2_attachment.animate', 1, m2_attachment.animate_attached,boolean,lambda x: bool(x), fill_tracks=True)

        def write_bone(cpd, pair):
            for path in cpd.get_paths():
                bone_str = re.search('"(.+?)"',path)
                if not bone_str:
                    log.warn(f"FCurve {path} doesn't reference a bone")
                    continue
                bone = bone_str.group(1)

                curve_type_str = re.search('([a-zA-Z_]+)$',path)
                if not curve_type_str:
                    log.warn(f"FCurve {path} doesn't have a proper type")
                    continue
                curve_type = curve_type_str.group(0)

                m2_bone = self.m2.root.bones.values[self.bone_ids[bone]]
                m2_bone.flags = m2_bone.flags | 512

                if curve_type == 'rotation_quaternion':
                    cpd.write_track(path,4,m2_bone.rotation,M2CompQuaternion,
                        lambda x: M2CompQuaternion((
                            bl_to_m2_quat(x[0]),
                            bl_to_m2_quat(x[self.axis_order[0] + 1] * self.axis_polarity[0]),
                            bl_to_m2_quat(x[self.axis_order[1] + 1] * self.axis_polarity[1]),
                            bl_to_m2_quat(x[3])
                        )), fill_tracks = False
                    )

                elif curve_type == 'scale':
                    def convert_scale(scale):                  
                        if self.forward_axis == 'X+' or self.forward_axis == 'X-':
                            scale = (scale[1],scale[0],scale[2])
                        elif self.forward_axis == 'Y+' or self.forward_axis == 'Y-':
                            scale = (scale[0],scale[1],scale[2])
                        return scale
                    cpd.write_track(path,3,m2_bone.scale,vec3D,convert_scale, fill_tracks = False)

                # TODO: this probably doesn't work if bone is not at 0,0,0
                elif curve_type == 'location':
                    cpd.write_track(path,3,m2_bone.translation,vec3D,
                        lambda x: self._convert_vec((x[1],-x[0],x[2])), fill_tracks = False)

        def write_color_transparency_controller(cpd, pair):
            """Exports animation tracks from the unified color/transparency controller."""

            def extract_scene_data(path):
                index = re.search(r"\[(.+?)\]", path).group(1)
                data_path = re.search(r"\]\.(.+)", path).group(1)
                return int(index), data_path

            obj = pair.object
            ct = getattr(obj, "wow_m2_color_transparency", None)
            if not ct or not ct.enabled:
                log.warn(f"Object {obj.name} has no active wow_m2_color_transparency.")
                return

            # --- Handle color animation tracks ---
            for path in cpd.get_paths():
                # --------------------------------------------------
                # COLORS
                # --------------------------------------------------
                if path.startswith("wow_m2_color_transparency.colors"):
                    index, data_path = extract_scene_data(path)

                    # Ensure color slot exists
                    while len(self.m2.root.colors) <= index:
                        self.m2.root.colors.append(M2Color())

                    m2_color = self.m2.root.colors[index]

                    if index < len(ct.colors):
                        color_entry = ct.colors[index]
                        color_name = color_entry.name
                    else:
                        log.error(
                            f"Color: wow_m2_color_transparency.colors[{index}] "
                            f"is animated but missing from the controller. Create or remove it."
                        )
                        color_name = None

                    # Maintain export ID map
                    if color_name:
                        if color_name in self.color_ids:
                            old_index = self.color_ids[color_name]
                            assert old_index == index, (
                                f"Color {color_name} has conflicting IDs {index} vs {old_index}"
                            )
                        else:
                            self.color_ids[color_name] = index

                        # RGB
                        if data_path == "color":
                            cpd.write_track(path, 3, m2_color.color, vec3D)

                        # Alpha (do separate object? placeholder code)
                        elif data_path == "alpha":
                            cpd.write_track(path, 1, m2_color.alpha, fixed16, lambda x: int(x * 0x7FFF))

                # --------------------------------------------------
                # TRANSPARENCY
                # --------------------------------------------------
                elif path.startswith("wow_m2_color_transparency.transparencies"):
                    index, data_path = extract_scene_data(path)

                    # Ensure transparency slot exists in the M2 root
                    while len(self.m2.root.texture_weights) <= index:
                        self.m2.root.texture_weights.append(M2Track(fixed16, M2Header))

                    weight = self.m2.root.texture_weights.values[index]

                    # Maintain transparency lookup table (always 0..n)
                    lt = self.m2.root.transparency_lookup_table
                    while len(lt) <= index:
                        lt.append(len(lt))

                    # Ensure corresponding entry exists in the controller
                    props = ct  # shorthand
                    while len(props.transparencies) <= index:
                        t = props.transparencies.add()
                        t.name = f"Transparency_{len(props.transparencies)-1}"

                    trans_entry = props.transparencies[index]
                    trans_name = trans_entry.name

                    # Maintain export ID map
                    if trans_name in self.transparency_ids:
                        old_index = self.transparency_ids[trans_name]
                        assert old_index == index, (
                            f"Transparency {trans_name} has conflicting IDs {index} vs {old_index}"
                        )
                    else:
                        self.transparency_ids[trans_name] = index

                    # Write value
                    if data_path == "value":
                        cpd.write_track(path, 1, weight, fixed16, lambda x: int(x * 0x7FFF))

        def write_event(cpd, pair):
            m2_event = self.m2.root.events[self.event_ids[pair.object.name]]

            cpd.write_track("wow_m2_event.fire",1,m2_event.enabled,None, fill_tracks = True)

            events_to_remove = []
            for event in self.final_events:
                if pair.object.name == event:
                    events_to_remove.append(event)
            for event in events_to_remove:
                del self.final_events[event]

        def write_empty_events():
            global_seq_count = 0
            for wow_seq in bpy.context.scene.wow_m2_animations:
                if wow_seq.is_global_sequence:
                    global_seq_count += 1
            animations_count = len(bpy.context.scene.wow_m2_animations) - global_seq_count

            for key, identifier in self.final_events.items():
                m2_track = identifier.enabled
                while len(m2_track.timestamps) < animations_count:
                    m2_track.timestamps.add(M2Array(0))
                    
        def write_texture_transform(cpd, pair):
            if pair.object.name in self.texture_transform_ids:
                return
            
            self.texture_transform_ids[pair.object.name] = len(self.m2.root.texture_transforms)
            trans = M2TextureTransform()
            self.m2.root.texture_transforms.append(trans)

            cpd.write_track("location",3,trans.translation,vec3D, lambda x: ( -x[0], x[1], x[2] ))

            cpd.write_track("scale",3,trans.scaling,vec3D)

            # TODO: fix this with axis order!
            cpd.write_track("rotation_quaternion",4,trans.rotation,quat, lambda x: ( x[2], -x[1], x[3], x[0] ))

        def write_ribbon(cpd, pair):
            m2_ribbon = self.m2.root.ribbon_emitters[self.ribbon_ids[pair.object.name]]

            tracks = [
                ("color",         3, "color_track",        vec3D,  None),
                ("alpha",         1, "alpha_track",        float32, lambda x: int(x * 0x7fff)),
                ("height_above",  1, "height_above_track", float32, None),
                ("height_below",  1, "height_below_track", float32, None),
                ("texture_slot",  1, "tex_slot_track",     uint16, lambda x: int(x)),
                ("visibility",    1, "visibility_track",   uint8,  lambda x: int(x)),
            ]

            for name, dim, attr, dtype, conv in tracks:
                cpd.write_track(
                    f"wow_m2_ribbon.{name}",
                    dim,
                    getattr(m2_ribbon, attr),
                    dtype,
                    conv
                )

        def write_particle(cpd, pair):
            m2_particle = self.m2.root.particle_emitters[self.particle_ids[pair.object.name]]

            tracks = [
                ("emission_speed",        1, "emission_speed",        float32, None),
                ("speed_variation",       1, "speed_variation",       float32, None),
                ("vertical_range",        1, "vertical_range",        float32, None),
                ("horizontal_range",      1, "horizontal_range",      float32, None),
                ("gravity",               1, "gravity",               float32, None),
                ("lifespan",              1, "lifespan",              float32, None),
                ("emission_rate",         1, "emission_rate",         float32, None),
                ("emission_area_length",  1, "emission_area_length",  float32, None),
                ("emission_area_width",   1, "emission_area_width",   float32, None),
                ("z_source",              1, "z_source",              float32, None),
                ("color_track",           3, "color_track",           vec3D,   None),
                ("alpha",                 1, "alpha_track",           float32, None),
                ("scale",                 2, "scale_track",           vec2D,   None),
                ("active",                1, "enabled_in",            uint8,   lambda x: int(x)),
            ]

            for name, dim, attr, dtype, conv in tracks:
                kwargs = {"fill_tracks": True} if name == "active" else {}
                cpd.write_track(
                    f"wow_m2_particle.{name}",
                    dim,
                    getattr(m2_particle, attr),
                    dtype,
                    conv,
                    **kwargs
                )

        def write_camera(cpd, pair):
            m2_camera = self.m2.root.cameras[self.camera_ids[pair.object.name]]
            def convert_spline(x):
                key = M2SplineKey(vec3D)
                key.value = x
                return key
            cpd.write_track("rotation_axis_angle",m2_camera.positions,vec3D,convert_spline)                                                         

        def write_camera_target(cpd, pair):
            m2_camera = self.m2.root.cameras[self.camera_target_ids[pair.object.name]]
            def convert_spline(x):
                key = M2SplineKey(float32)
                key.value = x
                return key
            # TODO: can't write this because the track thinks the m2array type is generic for some reason
            #cpd.write_track("rotation_axis_angle",m2_camera.roll,float32,convert_spline)

        # -------------------------
        # Main body
        # -------------------------
        self.m2.root.transparency_lookup_table.add(len(self.m2.root.texture_weights))

        global_seq_count = 0
        for wow_seq in self.scene.wow_m2_animations:
            if wow_seq.is_global_sequence:
                global_seq_count += 1

        success_count = 0

        for wow_seq in tqdm(self.scene.wow_m2_animations, total=len(self.scene.wow_m2_animations), desc='Exporting Animations', ascii=True):
            seq_id = 0
            global_seq_id = -1
            if wow_seq.is_global_sequence:
                global_seq_id = len(self.m2.root.global_sequences)
                self.m2.root.global_sequences.append(0)
            else:
                is_alias = "64" in wow_seq.flags

                # TODO using root boundings when not using preset, better than nothing
                if wow_seq.use_preset_bounds:
                    box_min = self._convert_vec((wow_seq.preset_bounds_min_x, wow_seq.preset_bounds_min_y, wow_seq.preset_bounds_min_z))
                    box_max = self._convert_vec((wow_seq.preset_bounds_max_x, wow_seq.preset_bounds_max_y, wow_seq.preset_bounds_max_z))
                    
                    bounding = ((box_min, box_max), wow_seq.preset_bounds_radius)     
                else: 
                    bounding = ((self.m2.root.bounding_box.min,self.m2.root.bounding_box.max),
                        self.m2.root.bounding_sphere_radius)
                    
                seq_id = self.m2.add_anim(
                    int(wow_seq.animation_id),
                    wow_seq.chain_index, # titi, to test
                    (0,0), # set it later
                    wow_seq.move_speed * self.scale,
                    construct_bitfield(wow_seq.flags),
                    convert_frequency_percentage(wow_seq.frequency),
                    (wow_seq.replay_min, wow_seq.replay_max),
                    wow_seq.blend_time,  # TODO: multiversioning
                    bounding,
                    wow_seq.VariationNext,
                    wow_seq.alias_next
                )
            
            for pair in wow_seq.anim_pairs:
                if pair.object is None or pair.action is None:
                    continue

                if pair.object.type == 'ARMATURE':
                    ObjectTracks(seq_id, global_seq_id, pair, write_bone)
                elif pair.object.type == 'LIGHT':
                    ObjectTracks(seq_id, global_seq_id, pair, write_light)
                elif pair.object.type == 'CAMERA':
                    ObjectTracks(seq_id, global_seq_id, pair, write_camera)
                elif pair.object.type == 'CAMERA_TARGET':
                    ObjectTracks(seq_id, global_seq_id, pair, write_camera_target)
                elif pair.object.type == 'EMPTY':
                    if pair.object.wow_m2_attachment.enabled:
                        ObjectTracks(seq_id, global_seq_id, pair, write_attachment)
                    elif pair.object.wow_m2_event.enabled:
                        ObjectTracks(seq_id, global_seq_id, pair, write_event)
                    elif pair.object.wow_m2_camera.enabled:
                        ObjectTracks(seq_id, global_seq_id, pair, write_camera_target)
                    elif pair.object.wow_m2_uv_transform.enabled:
                        ObjectTracks(seq_id, global_seq_id, pair, write_texture_transform)
                    elif pair.object.wow_m2_ribbon.enabled:
                        ObjectTracks(seq_id, global_seq_id, pair, write_ribbon)
                    elif pair.object.wow_m2_particle.enabled:
                        ObjectTracks(seq_id, global_seq_id, pair, write_particle)
                    elif pair.object.wow_m2_color_transparency.enabled:
                        ObjectTracks(seq_id, global_seq_id, pair, write_color_transparency_controller)

            for global_seq_id,duration in global_seq_durations.items():
                assert global_seq_id < len(self.m2.root.global_sequences)
                self.m2.root.global_sequences.set_index(global_seq_id,duration)

            if wow_seq.use_preset_duration == True:
                self.m2.root.sequences[seq_id].duration = wow_seq.duration
            else:
                for seq_id,duration in seq_durations.items():
                    assert seq_id < len(self.m2.root.sequences)
                    self.m2.root.sequences[seq_id].duration = duration

        # Add dummy texture weight/transparency
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
        
        write_empty_events()

    def save_globalflags(self, need_combiner_flag):
        """Save global flags back into the M2 file using the M2 root collection."""
        try:
            # Locate existing M2 root collection
            m2_collection = util.find_m2_root_collection()

            if not m2_collection:
                log.warn("No M2 root collection found, skipping global flag save.")
                return

            if not hasattr(m2_collection, "wow_m2_globalflags"):
                log.warn(f"Collection '{m2_collection.name}' has no wow_m2_globalflags property.")
                return
                    
            if not m2_collection.wow_m2_globalflags.enabled:
                log.warn(f"Global flags disabled on collection '{m2_collection.name}', skipping flag save.")
                return

            globalflags = m2_collection.wow_m2_globalflags

            # Read flags defensively
            try:
                flags_lk = list(getattr(globalflags, "flagsLK", []))
                flags_legion = list(getattr(globalflags, "flagsLegion", []))
                log.debug(f"Read flags from collection '{m2_collection.name}': LK={flags_lk}, Legion={flags_legion}")
            except Exception as e:
                log.error(f"Failed reading global flags from collection '{m2_collection.name}': {e}")
                return

            # Texture combiner flag (bit 8)
            combiner_flag = "8"
            flag_changed = False

            if need_combiner_flag and combiner_flag not in flags_lk:
                flags_lk.append(combiner_flag)
                flag_changed = True
                log.debug("Added texture combiner flag (8), required by model export.")
            elif not need_combiner_flag and combiner_flag in flags_lk:
                flags_lk.remove(combiner_flag)
                flag_changed = True
                log.debug("Removed texture combiner flag (8), model export indicates not needed.")

            # Write updated flags back into property
            try:
                globalflags.flagsLK = set(flags_lk)
                globalflags.flagsLegion = set(flags_legion)
                log.debug(f"Updated collection flags: LK={flags_lk}, Legion={flags_legion}")
            except Exception as e:
                log.warn(f"Could not update flags on collection '{m2_collection.name}': {e}")

            # Apply combined bitfield to M2 file memory
            try:
                combined_flags = construct_bitfield(flags_lk + flags_legion)
                self.m2.root.global_flags = combined_flags
            except Exception as e:
                log.error(f"Failed to construct or assign combined bitfield: {e}")
                return

            if flag_changed:
                log.info(f"Updated global flags on '{m2_collection.name}' to {combined_flags}")
            else:
                log.info("No global flag change required.")

        except Exception as e:
            tb = traceback.format_exc()
            log.error(f"Unexpected failure in save_globalflags: {e}\n{tb}")

    def save_geosets(self, selected_only, fill_textures, merge_vertices):
        import io, sys

        objects = bpy.context.selected_objects if selected_only else bpy.context.scene.objects
        if not objects:
            log.error("No mesh found on the scene or selected.")
            return

        bpy.ops.object.select_all(action="DESELECT")

        proxy_objects = []
        tex_anim_lookup_table = []
        tex_combiner_materials = []
        tt_controller_combinations = []
        rearranged_transforms = []
        anim_lookup_executed = False
        need_combiner_flag = False

        def mapping(mapping_method):
            if mapping_method == "UVMap":
                return 0
            elif mapping_method == "UVMap.001":
                return 1
            elif mapping_method == "Env":
                return -1
            return 0

        # Build transform controllers map
        for wow_seq in self.scene.wow_m2_animations:
            for pair in wow_seq.anim_pairs:
                if pair.object and pair.object.type == "EMPTY" and pair.object.wow_m2_uv_transform.enabled:
                    if pair.object.name not in rearranged_transforms:
                        rearranged_transforms.append(pair.object.name)
        tt_controller_id_map = {name: idx for idx, name in enumerate(rearranged_transforms)}

        # Export each mesh
        geoset_objects = [
            ob for ob in objects
            if ob.type == "MESH" and not ob.hide_get() and not ob.wow_m2_geoset.collision_mesh
        ]

        success_count = 0

        for obj in tqdm(geoset_objects, total=len(geoset_objects), desc="Exporting Geosets", ascii=True):
            try:
                if not obj.data or not obj.data.polygons:
                    log.warn(f"Skipping mesh '{obj.name}' — no geometry data.")
                    continue

                # Duplicate mesh
                new_obj = obj.copy()
                new_obj.data = obj.data.copy()
                proxy_objects.append(new_obj)
                bpy.context.collection.objects.link(new_obj)
                bpy.context.view_layer.objects.active = new_obj
                mesh = new_obj.data

                if not mesh.uv_layers or not mesh.uv_layers.active:
                    log.error(f"Mesh '{obj.name}' has no UV Map — skipping.")
                    bpy.data.objects.remove(new_obj, do_unlink=True)
                    continue

                # Apply modifiers safely
                if obj.modifiers:
                    for mod in obj.modifiers:
                        if "M2TexTransform" not in mod.name:
                            try:
                                bpy.ops.object.modifier_apply(modifier=mod.name)
                            except Exception as e:
                                log.warn(f"Could not apply modifier '{mod.name}' on '{obj.name}': {e}")

                # Silence Blender console temporarily
                temporal_console_output = io.StringIO()
                sys.stdout = temporal_console_output

                # Triangulate and clean mesh
                try:
                    bpy.ops.object.mode_set(mode="EDIT")
                    bpy.ops.mesh.select_all(action="SELECT")
                    bpy.ops.mesh.reveal()
                    bpy.ops.mesh.quads_convert_to_tris()
                    bpy.ops.mesh.delete_loose()
                    bpy.ops.mesh.select_all(action="DESELECT")
                    bpy.ops.object.mode_set(mode="OBJECT")
                except Exception as e:
                    log.warn(f"Failed to triangulate '{obj.name}': {e}")
                    bpy.ops.object.mode_set(mode="OBJECT")

                # Re-enable stdout
                sys.stdout = sys.__stdout__
                temporal_console_output.close()

                # Compute vertex data
                mesh.calc_loop_triangles()
                mesh.calc_normals_split()

                vertices = [self._convert_vec(new_obj.matrix_world @ v.co) for v in mesh.vertices]
                normals = [(0.0, 0.0, 1.0)] * len(vertices)
                tex_coords = [(0.0, 0.0)] * len(vertices)
                tex_coords2 = [(0.0, 0.0)] * len(vertices)

                for loop in mesh.loops:
                    v_idx = loop.vertex_index
                    normals[v_idx] = tuple(getattr(loop, "normal", (0.0, 0.0, 1.0)))
                    if mesh.uv_layers:
                        uv1 = mesh.uv_layers[0].data[loop.index].uv
                        tex_coords[v_idx] = (uv1[0], 1 - uv1[1])
                        if len(mesh.uv_layers) > 1:
                            uv2 = mesh.uv_layers[1].data[loop.index].uv
                            tex_coords2[v_idx] = (uv2[0], 1 - uv2[1])
                        else:
                            tex_coords2[v_idx] = tex_coords[v_idx]

                tris = [poly.vertices for poly in mesh.polygons]

                # Compute geometric origin
                vertcount = len(vertices)
                origin = tuple(sum(v[i] for v in vertices) / vertcount for i in range(3))
                sort_pos = get_obj_boundbox_center(new_obj)
                sort_radius = get_obj_radius(new_obj, sort_pos)

                # Bones
                if self.rig:
                    bone_indices, bone_weights = [], []
                    bone_names = [b.name for b in self.rig.data.bones]
                    unique_bones = set()

                    for vertex in mesh.vertices:
                        v_bone_indices = [0, 0, 0, 0]
                        v_bone_weights = [0, 0, 0, 0]
                        
                        groups = get_bone_groups(new_obj, vertex, bone_names)[:4]
                        
                        for i, g in enumerate(groups):
                            group_name = (
                                new_obj.vertex_groups[g.group].name
                                if g.group < len(new_obj.vertex_groups)
                                else None
                            )
                            bone_id = self.bone_ids.get(group_name)
                            weight = max(0, min(1, g.weight))
                            
                            if bone_id is None:
                                bone_id = 0
                                weight = 0
                                log.warn(f"Mesh '{obj.name}' vertex group '{group_name}' not linked to any known bone, defaulting bone and weight to 0.")
                                
                            v_bone_indices[i] = bone_id
                            v_bone_weights[i] = int(weight * 255)
                            unique_bones.add(bone_id)

                        total = sum(v_bone_weights)
                        if total != 255 and total > 0:
                            scale = 255 / total
                            v_bone_weights = [int(w * scale) for w in v_bone_weights]
                            diff = 255 - sum(v_bone_weights)
                            if diff != 0:
                                v_bone_weights[v_bone_weights.index(max(v_bone_weights))] += diff

                        bone_indices.append(v_bone_indices)
                        bone_weights.append(v_bone_weights)

                    if len(unique_bones) > 64:
                        log.error(f"Mesh '{obj.name}' uses {len(unique_bones)} bones — exceeds 64 bone limit. Split it and retry.")
                        bpy.data.objects.remove(new_obj, do_unlink=True)
                        continue
                else:
                    bone_indices = [[0, 0, 0, 0] for _ in mesh.vertices]
                    bone_weights = [[255, 0, 0, 0] for _ in mesh.vertices]

                # Create geoset
                g_index = self.m2.add_geoset(
                    vertices, normals, tex_coords, tex_coords2, tris,
                    bone_indices, bone_weights, origin, sort_pos, sort_radius,
                    int(new_obj.wow_m2_geoset.mesh_part_id)
                )

                # Export materials
                for i, material in enumerate(mesh.materials):
                    if not material or not hasattr(material, "wow_m2_material"):
                        log.warn(f"Mesh '{obj.name}' has invalid material at slot {i}. Skipping.")
                        continue

                    try:
                        mat_name = material.name
                        mat_data = material.wow_m2_material
                        textures = [mat_data.texture_1, mat_data.texture_2]

                        valid_textures = [t for t in textures if t and hasattr(t, "wow_m2_texture")]
                        if not valid_textures:
                            log.warn(
                                f"Material '{mat_name}' on '{obj.name}' has no valid textures "
                                f"(missing texture or texture missing wow_m2_texture attribute)."
                            )
                            continue

                        first_path = None
                        texture_count = 0

                        for texture in valid_textures:
                            texture_count += 1
                            tex_data = texture.wow_m2_texture
                            wow_path = tex_data.path
                            tex_type = tex_data.texture_type

                            # Determine first_path on first valid texture
                            if texture_count == 1:
                                first_path = wow_path if tex_type == '0' else tex_type

                            # Resolve empty type-0 texture path only when needed
                            if tex_type == 0 and fill_textures and not wow_path:
                                wow_path = resolve_texture_path(texture.filepath)

                            # Add texture to self.m2
                            self.m2.add_texture(
                                wow_path if tex_type == '0' else "",
                                construct_bitfield(tex_data.flags),
                                int(tex_type),
                            )

                            # Key is either the wow_path (if type 0) or the tex_type literal
                            key = wow_path if tex_type == '0' else tex_type

                            if key not in self.final_textures:
                                self.final_textures[key] = len(self.final_textures)

                            tex2_id = self.final_textures[key]

                            # tex1_id defaults to tex2_id, unless first_path overrides
                            tex1_id = tex2_id
                            if first_path in self.final_textures:
                                tex1_id = self.final_textures[first_path]

                        # Add pair lookup (combiners expect pairs)
                        tex_lookup_id = self.m2.add_tex_lookup(tex1_id, tex2_id)

                        # --- Material and render setup ---
                        render_flags = construct_bitfield(mat_data.texture_1_render_flags)
                        flags = construct_bitfield(mat_data.flags)
                        priority_plane = int(mat_data.priority_plane)
                        bl_mode = int(mat_data.texture_1_blending_mode)
                        shader_id = 0
                        mat_layer = i

                        # Color / transparency validation
                        color_name = mat_data.color
                        transparency_name = mat_data.transparency

                        if color_name and color_name not in self.color_ids:
                            log.warn(f"Material '{mat_name}' on '{obj.name}' references missing color '{color_name}'.")
                            color_id = -1
                        else:
                            color_id = self.color_ids.get(color_name, -1)

                        if transparency_name and transparency_name not in self.transparency_ids:
                            log.warn(f"Material '{mat_name}' on '{obj.name}' references missing transparency '{transparency_name}'.")
                            transparency_id = 0
                        else:
                            transparency_id = self.transparency_ids.get(transparency_name, 0)

                        tex_1_mapping = mapping(mat_data.texture_1_mapping)
                        tex_2_mapping = 1

                        # Two-texture combiner setup
                        if texture_count == 2:
                            need_combiner_flag = True
                            tex_2_mapping = mapping(mat_data.texture_2_mapping)
                            tex_combiner_data = (
                                construct_bitfield(mat_data.texture_2_render_flags),
                                int(mat_data.texture_2_blending_mode)
                            )
                            
                            if tex_combiner_data not in tex_combiner_materials:
                                tex_combiner_materials.append(tex_combiner_data)
                                self.m2.root.texture_combiner_combos.append(tex_combiner_data[0])
                                self.m2.root.texture_combiner_combos.append(tex_combiner_data[1])

                            if tex_combiner_data in tex_combiner_materials:
                                shader_id = next(i for i, value in enumerate(tex_combiner_materials) if value == tex_combiner_data) * 2

                        # UV transform controllers
                        ntexanim, tt_controller_id_uv1, tt_controller_id_uv2 = 0, -1, -1
                        tex1_anim = mat_data.texture_1_animation
                        tex2_anim = mat_data.texture_2_animation
                        if tex1_anim:
                            tt_controller_id_uv1 = tt_controller_id_map.get(tex1_anim.name, -1)
                            if tt_controller_id_uv1 == -1:
                                log.warn(f"Material '{mat_name}' references missing UV animation '{tex1_anim.name}'.")
                            ntexanim += 1
                        if tex2_anim:
                            tt_controller_id_uv2 = tt_controller_id_map.get(tex2_anim.name, -1)
                            if tt_controller_id_uv2 == -1:
                                log.warn(f"Material '{mat_name}' references missing UV animation '{tex2_anim.name}'.")
                            ntexanim += 1

                        combo = (tt_controller_id_uv1, tt_controller_id_uv2)
                        if combo not in tt_controller_combinations:
                            tt_controller_combinations.append(combo)
                        if combo not in tex_anim_lookup_table:
                            tex_anim_lookup_table.append(combo)
                            self.m2.root.texture_transforms_lookup_table.extend(combo)

                        transform_id = tex_anim_lookup_table.index(combo) * 2

                        self.m2.add_material_to_geoset(
                            g_index, render_flags, bl_mode, flags, shader_id,
                            tex_lookup_id, tex_1_mapping, tex_2_mapping,
                            priority_plane, mat_layer, texture_count,
                            color_id, transparency_id, transform_id
                        )

                        log.debug(f"Exported material '{mat_name}'")

                    except Exception as mat_e:
                        tb = traceback.format_exc()
                        log.error(f"Failed to export material {i} ('{material.name}') of '{obj.name}': {mat_e}\n{tb}")
                        continue

                bpy.data.objects.remove(new_obj, do_unlink=True)
                log.debug(f"Exported geoset '{obj.name}'")
                success_count += 1

            except Exception as e:
                tb = traceback.format_exc()
                log.error(f"Failed to export geoset '{obj.name}': {e}\n{tb}")
                try:
                    bpy.data.objects.remove(new_obj, do_unlink=True)
                except:
                    pass
                continue

        # Update global flags
        self.save_globalflags(need_combiner_flag)
        
        # --- Final summary ---
        log.info(f"Exported {success_count}/{len(geoset_objects)} geosets successfully.")

    def save_collision(self, selected_only):
        """Exports collision meshes, triangulates and collects bounds safely."""
        import io, sys

        # Get collision meshes
        objects = bpy.context.selected_objects if selected_only else bpy.context.scene.objects
        objects = list(filter(lambda ob: ob.wow_m2_geoset.collision_mesh and ob.type == "MESH", objects))

        if not objects:
            log.info("No collision meshes found in scene or selection.")
            return

        proxy_objects = []

        for obj in tqdm(objects, total=len(objects), desc="Exporting Collision", ascii=True):
            try:
                if not obj.data or not obj.data.polygons:
                    log.warn(f"Skipping collision mesh '{obj.name}' — no geometry data.")
                    continue

                # Duplicate the mesh for editing
                new_obj = obj.copy()
                new_obj.data = obj.data.copy()
                proxy_objects.append(new_obj)
                bpy.context.collection.objects.link(new_obj)
                bpy.context.view_layer.objects.active = new_obj
                mesh = new_obj.data

                # Apply modifiers (ignore M2TexTransform-like)
                for mod in obj.modifiers:
                    try:
                        bpy.ops.object.modifier_apply(modifier=mod.name)
                    except Exception as e:
                        log.warn(f"Could not apply modifier '{mod.name}' on collision mesh '{obj.name}': {e}")

                # Silence Blender console to suppress noisy operator output
                temporal_console_output = io.StringIO()
                sys.stdout = temporal_console_output

                # Triangulate and clean geometry
                try:
                    bpy.ops.object.mode_set(mode="EDIT")
                    bpy.ops.mesh.select_all(action="SELECT")
                    bpy.ops.mesh.reveal()
                    bpy.ops.mesh.quads_convert_to_tris()
                    bpy.ops.mesh.delete_loose()
                    bpy.ops.mesh.select_all(action="DESELECT")
                    bpy.ops.object.mode_set(mode="OBJECT")
                except Exception as e:
                    log.warn(f"Triangulation failed for collision mesh '{obj.name}': {e}")
                    bpy.ops.object.mode_set(mode="OBJECT")

                # Restore stdout
                sys.stdout = sys.__stdout__
                temporal_console_output.close()

                # Verify valid mesh data
                if not mesh.vertices or not mesh.polygons:
                    log.warn(f"Collision mesh '{obj.name}' has no valid vertices or faces after processing.")
                    bpy.data.objects.remove(new_obj, do_unlink=True)
                    continue

                # Collect geometry data
                vertices = [self._convert_vec(tuple(new_obj.matrix_world @ v.co)) for v in mesh.vertices]
                faces = [tuple(poly.vertices) for poly in mesh.polygons]
                normals = [self._convert_vec(tuple(poly.normal)) for poly in mesh.polygons]

                # Sanity check
                if not vertices or not faces:
                    log.warn(f"Skipping collision mesh '{obj.name}' — empty geometry.")
                    bpy.data.objects.remove(new_obj, do_unlink=True)
                    continue

                # Add to M2
                self.m2.add_collision_mesh(vertices, faces, normals)
                bpy.data.objects.remove(new_obj, do_unlink=True)

            except Exception as e:
                tb = traceback.format_exc()
                log.error(f"Failed to export collision mesh '{obj.name}': {e}\n{tb}")
                try:
                    bpy.data.objects.remove(new_obj, do_unlink=True)
                except:
                    pass
                continue

        # Compute collision bounding box safely
        try:
            if not objects:
                log.warn("No valid collision objects found to compute bounding box.")
                return

            b_min, b_max = get_objs_boundbox_world(objects)
            if b_min is None or b_max is None:
                log.warn("Failed to compute collision bounding box — no valid geometry.")
                return

            b_min = self._convert_vec(b_min)
            b_max = self._convert_vec(b_max)

            self.m2.root.collision_box.min = b_min
            self.m2.root.collision_box.max = b_max
            self.m2.root.collision_sphere_radius = (
                sqrt(
                    ((b_max[self.axis_order[0]] - b_min[self.axis_order[0]]) * self.axis_polarity[0] * self.scale) ** 2
                    + ((b_max[self.axis_order[1]] - b_min[self.axis_order[1]]) * self.axis_polarity[1] * self.scale) ** 2
                    + ((b_max[2] - b_min[2])) ** 2
                )
                / 2
            )
        except Exception as e:
            tb = traceback.format_exc()
            log.error(f"Failed to compute collision bounding box: {e}\n{tb}")

        # Clean up proxies (redundant, but safe)
        for p in proxy_objects:
            try:
                if p.name in bpy.data.objects:
                    bpy.data.objects.remove(p, do_unlink=True)
            except:
                pass