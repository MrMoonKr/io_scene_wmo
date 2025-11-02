import bpy

# ---------------------------
# Animation utilities
# ---------------------------

def can_apply_scale(fcurves, keyframe_count):
    for i in range(keyframe_count):
        x = fcurves[0].keyframe_points[i].co[1] if 0 in fcurves else 1
        y = fcurves[1].keyframe_points[i].co[1] if 1 in fcurves else 1
        z = fcurves[2].keyframe_points[i].co[1] if 2 in fcurves else 1
        if abs(x - y) > 0.0001 or abs(x - z) > 0.0001:
            return False
    return True

def make_fcurve_compound(fcurves, accept=lambda path: True):
    compound = {}
    for fcurve in fcurves:
        if not accept(fcurve.data_path):
            continue
        if fcurve.data_path not in compound:
            compound[fcurve.data_path] = {}
        compound[fcurve.data_path][fcurve.array_index] = fcurve
    return compound

def get_bone_groups(obj, vertex, bone_names):
    groups = [el for el in vertex.groups if obj.vertex_groups[el.group].name in bone_names]
    groups.sort(key=lambda x: -x.weight)
    return groups

def _find_final_alias(self, n_global_sequences, alias_next):
    for anim_index in self.animations:
        anim = bpy.context.scene.wow_m2_animations[alias_next + n_global_sequences]
        if '64' in anim.flags:
            alias_next = anim.alias_next
        else:
            return alias_next + n_global_sequences

# ---------------------------
# Collection Management
# ---------------------------

def get_or_create_collection(name, parent=None, color_tag="NONE"):
    """Get or create a collection by name, optionally under a parent."""
    if name in bpy.data.collections:
        col = bpy.data.collections[name]
    else:
        col = bpy.data.collections.new(name)
        if parent:
            parent.children.link(col)
        else:
            bpy.context.scene.collection.children.link(col)
            
    col.color_tag = color_tag
    return col

def find_m2_root_collection():
    """Locate the top-level M2 collection in the scene."""
    return next(
        (c for c in bpy.context.scene.collection.children if c.get("wow_m2_collection")),
        None
    )

def _link_to_single_collection(obj, collection):
    """Ensure obj is linked only to the given collection."""
    for col in obj.users_collection:
        col.objects.unlink(obj)
    if obj.name in bpy.context.scene.collection.objects:
        bpy.context.scene.collection.objects.unlink(obj)
    collection.objects.link(obj)

def get_or_create_m2_collection(target):
    """
    Ensure a top-level M2 collection exists and required sub-collections are present.
    target = name (str) or Collection
    Returns: (main_collection, dict{sub collections})
    """
    M2_SUBS = {
        "Armature": "COLOR_02",
        "Geosets": "COLOR_02",
        "Color_Transparency": "COLOR_02",
        "Texture_Transforms": "COLOR_02",
        "Events": "COLOR_02",
        "Attachments": "COLOR_02",
        "Cameras": "COLOR_02",
        "Collision": "COLOR_02",
        "Particles": "COLOR_02",
        "Ribbons": "COLOR_02",
        "Lights": "COLOR_02",
    }

    # Resolve target
    if isinstance(target, str):
        name = target
        main_col = bpy.data.collections.get(name) or get_or_create_collection(name)
    elif isinstance(target, bpy.types.Collection):
        main_col = target
        name = main_col.name
    else:
        raise TypeError("target must be a string or bpy.types.Collection")

    # Must be top-level
    if main_col.name not in bpy.context.scene.collection.children:
        raise ValueError(f"Collection '{name}' exists but is not top-level")

    # Mark collection as M2 root
    if "wow_m2_collection" not in main_col:
        main_col["wow_m2_collection"] = True

    # Ensure global flags pointer exists
    if hasattr(main_col, "wow_m2_globalflags"):
        main_col.wow_m2_globalflags.enabled = True

    # Create sub-collections
    subs = {}
    for sub, col_tag in M2_SUBS.items():
        subs[sub.lower()] = get_or_create_collection(sub, main_col, col_tag)

    # Build ColorTransparencyController
    ensure_color_transparency_controller(subs["color_transparency"])

    return main_col, subs

# ---------------------------
# Color/Transparency Controller
# ---------------------------

def find_color_transparency_controller():
    """Return the M2 ColorTransparencyController object, or None."""
    m2_root = find_m2_root_collection()
    if not m2_root:
        return None

    def walk(col):
        for o in col.objects:
            yield o
        for sub in col.children:
            yield from walk(sub)

    for obj in walk(m2_root):
        if obj.get("is_color_transparency_controller") or obj.name == "ColorTransparencyController":
            return obj
    return None

def ensure_color_transparency_controller(color_trans_collection):
    """Ensure the ColorTransparencyController exists in this M2 set."""
    from .operations import m2_action_logger as log
    
    m2_root = None
    for coll in bpy.context.scene.collection.children:
        if any(child is color_trans_collection for child in coll.children):
            m2_root = coll
            break

    if not m2_root:
        raise RuntimeError("Could not locate parent M2 root collection")

    controller = find_color_transparency_controller()

    if not controller:
        bpy.ops.object.empty_add(type="CUBE", location=(0, 0, 0))
        controller = bpy.context.view_layer.objects.active
        controller.name = "ColorTransparencyController"
        controller.scale = (0.03, 0.03, 0.03)
        controller["is_color_transparency_controller"] = True

        if hasattr(controller, "wow_m2_color_transparency"):
            controller.wow_m2_color_transparency.enabled = True

        _link_to_single_collection(controller, color_trans_collection)
        log.debug(f"Created ColorTransparencyController in '{m2_root.name}'")
    else:
        log.debug(f"Reusing ColorTransparencyController in '{m2_root.name}'")
        if color_trans_collection not in controller.users_collection:
            _link_to_single_collection(controller, color_trans_collection)

    controller.animation_data_create()
    controller.animation_data.action_blend_type = "ADD"

    props = getattr(controller, "wow_m2_color_transparency", None)
    return controller, props