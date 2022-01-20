import bpy
import bmesh
import os

from math import cos, sin, tan, radians
from time import time

from mathutils import Vector
from mathutils.bvhtree import BVHTree
from bpy_extras import view3d_utils

from ....addon_common.cookiecutter.cookiecutter import CookieCutter
from ....addon_common.common import ui
from ....addon_common.common.utils import delay_exec
from ....addon_common.common.drawing import Drawing
from ....addon_common.common.boundvar import BoundInt, BoundFloat, BoundBool
from ....addon_common.common.ui_styling import load_defaultstylings
from ....addon_common.common.globals import Globals

from ..handlers import DepsgraphLock
from .. import handlers



def angled_vertex(origin: Vector, pos: Vector, angle: float, orientation: float) -> float:
    return origin.z + ((pos.x - origin.x) * cos(orientation) + (pos.y - origin.y) * sin(orientation)) * tan(angle)


def get_median_point(bm: bmesh.types.BMesh) -> Vector:

    selected_vertices = [v for v in bm.verts if v.select]

    f = 1 / len(selected_vertices)

    median = Vector((0, 0, 0))

    for vert in selected_vertices:
        median += vert.co * f

    return median


def align_vertices(bm : bmesh.types.BMesh, mesh : bpy.types.Mesh, median : Vector, angle : float, orientation : float):
    for vert in bm.verts:
        if vert.select:
            vert.co[2] = angled_vertex(median, vert.co, radians(angle), radians(orientation))

    bmesh.update_edit_mesh(mesh, loop_triangles=True, destructive=True)


def reload_stylings():
    load_defaultstylings()
    path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'ui', 'ui.css')
    try:
        Globals.ui_draw.load_stylesheet(path)
    except AssertionError as e:
        # TODO: show proper dialog to user here!!
        print('could not load stylesheet "%s"' % path)
        print(e)
    Globals.ui_document.body.dirty('Reloaded stylings', children=True)
    Globals.ui_document.body.dirty_styling()
    Globals.ui_document.body.dirty_flow()


event_keymap = {
    'ONE' : 0,
    'TWO' : 1,
    'THREE': 2,
    'FOUR': 3,
    'FIVE': 4,
    'SIX': 5,
    'SEVEN': 6,
    'EIGHT': 7,
    'NUMPAD_1': 0,
    'NUMPAD_2': 1,
    'NUMPAD_3': 2,
    'NUMPAD_4': 3,
    'NUMPAD_5': 4,
    'NUMPAD_6': 5,
    'NUMPAD_7': 6,
    'NUMPAD_8': 7,
}

# some settings container
options = {}
options["variable_1"] = 10.0
options["variable_3"] = True


class WMO_OT_add_liquid(bpy.types.Operator):
    bl_idname = 'scene.wow_add_liquid'
    bl_label = 'Add liquid'
    bl_description = 'Add a WoW liquid plane'
    bl_options = {'REGISTER', 'UNDO'}

    x_planes:  bpy.props.IntProperty(
        name="X subdivisions:",
        description="Amount of WoW liquid planes in a row. One plane is 4.1666625 in its radius.",
        default=10,
        min=1
    )

    y_planes:  bpy.props.IntProperty(
        name="Y subdivisions:",
        description="Amount of WoW liquid planes in a column. One plane is 4.1666625 in its radius.",
        default=10,
        min=1
    )

    def execute(self, context):
        with DepsgraphLock():
            bpy.ops.mesh.primitive_grid_add(x_subdivisions=self.x_planes,
                                            y_subdivisions=self.y_planes,
                                            size=4.1666625
                                            )
            water = bpy.context.view_layer.objects.active
            bpy.ops.transform.resize(value=(self.x_planes, self.y_planes, 1.0))
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

            water.name += "_Liquid"

            mesh = water.data

            bit = 1
            counter = 0
            while bit <= 0x80:
                mesh.vertex_colors.new(name="flag_{}".format(counter))

                counter += 1
                bit <<= 1

            water.wow_wmo_liquid.enabled = True

            water.hide_set(False if "4" in bpy.context.scene.wow_visibility else True)

        self.report({'INFO'}, "Successfully сreated WoW liquid: {}".format(water.name))
        return {'FINISHED'}
