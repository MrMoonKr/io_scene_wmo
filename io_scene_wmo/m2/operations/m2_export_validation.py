import bpy
from ..util import get_bone_groups

# ---------------------------
# Scene validation functions
# ---------------------------

def wrong_scene_type():
    name = "Wrong Scene Type"
    description = [
        "Issue: The scene type is set to WMO instead of M2",
        "Fix: Change the scene type to 'M2' in the top-right corner of Blender"
    ]
    items = []

    if not bpy.context.scene:
        items.append("Wrong scene: There is no scene object, please report this (unexpected).")
    elif bpy.context.scene.wow_scene.type != 'M2':
        items.append(f"Wrong scene: Type is {bpy.context.scene.wow_scene.type} but should be M2")

    return (name, description, items)

def transformed_objects():
    name = "Transformed Objects"
    description = [
        "Issue: Objects in the scene are transformed (moved, rotated, or scaled).",
        "Fix: Run the 'Convert Bones To WoW' command and fix any issues it causes."
    ]
    items = []

    def vec_eq(n, q1, q2):
        for i in range(n):
            if q1[i] != q2[i]:
                return False
        return True

    def vec_str(value, names):
        return " ".join([f"{names[i]}={value[i]}" for i in range(len(names))])

    for obj in bpy.data.objects:
        if obj.type not in ('ARMATURE', 'MESH'):
            continue

        def compare(name, names, val1, val2):
            if not vec_eq(len(names), val1, val2):
                items.append(f"Object {obj.name}'s {name} is {vec_str(val1, names)}, but should be {vec_str(val2, names)}")

        vec_names = ['x', 'y', 'z']
        quat_names = ['w', 'x', 'y', 'z']

        compare("location", vec_names, obj.location, (0, 0, 0))
        compare("scale", vec_names, obj.scale, (1, 1, 1))
        if obj.rotation_mode == 'QUATERNION':
            compare("quaternion rotation", quat_names, obj.rotation_quaternion, (1, 0, 0, 0))
        elif obj.rotation_mode == 'AXIS_ANGLE':
            compare("axis angle rotation", quat_names, obj.rotation_quaternion, (1, 0, 0, 0))
        else:
            compare("euler rotation", vec_names, obj.rotation_euler, (0, 0, 0))

    return (name, description, items)

def empty_textures():
    name = "Empty Textures"
    description = [
        "Issue: An M2 material has no texture set in any of its texture slots.",
        "Effect: Will usually cause the model to become invisible ingame.",
        "Note: This is not *always* an error, not all materials have textures."
    ]
    items = []

    for obj in bpy.data.objects:
        if not hasattr(obj, "wow_m2_geoset") or obj.wow_m2_geoset.collision_mesh or not obj.material_slots:
            continue

        for slot in obj.material_slots:
            mat = slot.material
            if mat is None:
                items.append(f"Object '{obj.name}' has an empty material slot.")
                continue

            if not hasattr(mat, "wow_m2_material"):
                items.append(f"Material '{mat.name}' on object '{obj.name}' has no wow_m2_material attribute.")
                continue

            wow_mat = mat.wow_m2_material
            if not hasattr(wow_mat, "texture_1"):
                items.append(f"wow_m2_material on '{mat.name}' has no 'texture_1' attribute.")
                continue

            if wow_mat.texture_1 is None:
                items.append(f"Object '{obj.name}', material '{mat.name}' has no M2 textures, may be invisible ingame.")

    return (name, description, items)

def empty_texture_paths():
    name = "Empty Texture Path"
    description = [
        "Issue: A model has an M2 material with a texture set that has no .blp path.",
        "Effect: Will usually cause the model to become invisible ingame.",
        "Fix: Find the material with the texture and fill the Texture Path.",
    ]
    items = []

    texture_maps = {}
    for obj in bpy.data.objects:
        if obj.type == 'MESH' and not obj.wow_m2_geoset.collision_mesh and obj.material_slots:
            for slot in obj.material_slots:
                if slot.material is None or not hasattr(slot.material, 'wow_m2_material'):
                    continue
                mat = slot.material.wow_m2_material
                for texture in [mat.texture_1, mat.texture_2]:
                    if texture and hasattr(texture, 'wow_m2_texture') and not texture.wow_m2_texture.path:
                        if texture.wow_m2_texture.texture_type == '0':
                            texture_maps.setdefault(texture.name, []).append(obj.name)

    for texture, obj_names in texture_maps.items():
        obj_str = ", ".join(obj_names)
        items.append(f"Texture '{texture}' used by ({obj_str}) has no .blp path set.")

    return (name, description, items)

def no_materials():
    name = "No Materials"
    description = [
        "Issue: A model has no materials set.",
        "Effect: The model will usually be invisible ingame.",
        "Fix: Add at least one material to your model.",
        "Note: Not always an error, some models don't require materials."
    ]
    items = [
        f"Object {obj.name} has no M2 materials (invisible ingame)."
        for obj in bpy.data.objects
        if obj.type == 'MESH' and not obj.wow_m2_geoset.collision_mesh and len(obj.material_slots) == 0
    ]
    return (name, description, items)

def bone_constraints():
    name = "Bone Constraints"
    description = [
        "Issue: A bone has constraints applied.",
        "Effect: Will almost always break animations (WoW doesn't support bone constraints).",
        "Fix: Remove bone constraints or bake animations into keyframes."
    ]
    items = []
    for obj in bpy.data.objects:
        if obj.type != 'ARMATURE':
            continue
        for bone in obj.pose.bones:
            for constraint in bone.constraints:
                items.append(f"Bone {obj.name}.{bone.name} has constraint '{constraint.name}', usually a mistake.")
    return (name, description, items)

def no_animation_pairs():
    name = "No Animation Pairs"
    description = [
        "Issue: Animations in the Animation Editor have no object pairs.",
        "Effect: No animation data will be exported for this sequence.",
        "Fix: Add at least one object/action pair."
    ]
    items = [
        f"Sequence '{seq.name}' has no pairs."
        for seq in bpy.context.scene.wow_m2_animations
        if len(seq.anim_pairs) == 0 and "64" not in seq.flags
    ]
    return (name, description, items)

def missing_animation_items():
    name = "Missing Animation Items"
    description = [
        "Issue: Animation pairs lack an object or action.",
        "Effect: No animation data will be written.",
        "Fix: Assign both an object and an action."
    ]
    items = []
    for seq in bpy.context.scene.wow_m2_animations:
        for pair in seq.anim_pairs:
            if pair.object is None:
                items.append(f"Sequence '{seq.name}' pair missing object.")
            elif pair.action is None:
                if pair.object.name not in ['CharInfoCam', 'CharInfoCam_Target', 'PortraitCam', 'PortraitCam_Target']:
                    items.append(f"Sequence '{seq.name}' pair '{pair.object.name}' missing action.")
    return (name, description, items)

def non_primary_sequences():
    name = "Non-primary Sequences"
    description = [
        "Issue: Non-primary sequences are unsupported.",
        "Effect: Animation will break or crash the game.",
        "Fix: Add the 'primary sequence' flag."
    ]
    items = [
        f"Sequence '{seq.name}' is missing the primary flag."
        for seq in bpy.context.scene.wow_m2_animations
        if not seq.is_global_sequence and "32" not in seq.flags
    ]
    return (name, description, items)

def too_many_bone_groups():
    name = "Too Many Bone Groups"
    description = [
        "Issue: Vertices are influenced by more than 4 bones.",
        "Effect: Excess bones will be dropped, mesh will deform incorrectly.",
        "Fix: Use 'Limit Bone Groups' or test the effect in-game."
    ]
    items = []
    for obj in bpy.data.objects:
        if obj.type != 'MESH' or not obj.parent or obj.parent.type != 'ARMATURE':
            continue
        bone_names = [b.name for b in obj.parent.data.bones]
        broken = sum(1 for v in obj.data.vertices if len(get_bone_groups(obj, v, bone_names)) > 4)
        if broken > 0:
            items.append(f"Object '{obj.name}' has {broken} vertices with too many bone groups.")
    return (name, description, items)

def fcurves_transforming_objects():
    name = "FCurves Transforming Objects"
    description = [
        "Issue: FCurves animate Blender objects directly, unsupported in M2.",
        "Effect: Object transforms incorrectly in-game.",
        "Fix: Run 'Convert Bones To WoW' and verify results."
    ]
    items = []
    for animation in bpy.context.scene.wow_m2_animations:
        for pair in animation.anim_pairs:
            if not pair.action:
                continue
            for curve in pair.action.fcurves:
                if curve.data_path in ["location", "rotation_euler", "scale"]:
                    if pair.object and not pair.object.wow_m2_uv_transform.enabled:
                        items.append(f"FCurve '{curve.data_path}[{curve.array_index}]' in '{pair.action.name}' transforms object '{pair.object.name}'.")
    return (name, description, items)

def run_validations():
    """Run all static validation checks and return structured results."""
    validation_callbacks = [
        wrong_scene_type,
        transformed_objects,
        empty_textures,
        empty_texture_paths,
        no_materials,
        bone_constraints,
        no_animation_pairs,
        missing_animation_items,
        non_primary_sequences,
        too_many_bone_groups,
        fcurves_transforming_objects,
    ]

    results = []
    for callback in validation_callbacks:
        name, descriptions, items = callback()
        if items:
            results.append((name, descriptions, items))

    return results