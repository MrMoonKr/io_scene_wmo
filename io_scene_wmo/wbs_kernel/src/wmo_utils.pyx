cimport wmo_utils
from cpython.memoryview cimport PyMemoryView_FromMemory
from cpython.buffer cimport PyBUF_READ
from cython.parallel cimport prange, parallel
from cython.operator cimport dereference as deref, preincrement as inc
from libc.stdlib cimport malloc, free

from typing import Tuple, Optional, List

from enum import Enum

import mathutils


class CBatchCountInfo:
    n_batches_trans: int
    n_batches_int: int
    n_batches_ext: int

    def __init__(self, n_batches_trans: int, n_batches_int: int, n_batches_ext: int):
        self.n_batches_trans = n_batches_trans
        self.n_batches_int = n_batches_int
        self.n_batches_ext = n_batches_ext

class CBoundingBox:
    min: Tuple[float, float, float]
    max: Tuple[float, float, float]

    def __init__(self, min: Tuple[float, float, float], max: Tuple[float, float, float]):
        self.min = min
        self.max = max

class CWMOGeometryBatcherError(Enum):
    NO_ERROR = 0
    LOOSE_MATERIAL_ID = 1


class LiquidExportParams:
    liquid_mesh_pointer: int
    liquid_mesh_matrix_world: mathutils.Matrix
    x_tiles: int
    y_tiles: int
    mat_id: int
    is_water: bool

class WMOGeometryBatcherMeshParams:
    mesh_pointer: int
    mesh_matrix_world: mathutils.Matrix
    collision_mesh_pointer: int
    collision_mesh_matrix_world: mathutils.Matrix
    use_large_material_id: bool
    use_vertex_color: bool
    use_custom_normals: bool
    vg_collision_index: int
    node_size: int
    material_mapping: List[int]
    liquid_params: Optional[LiquidExportParams]

    def __init__(self
                , mesh_pointer: int
                , mesh_matrix_world: mathutils.Matrix
                , collision_mesh_pointer: int
                , collision_mesh_matrix_world: Optional[mathutils.Matrix]
                , use_large_material_id: bool
                , use_vertex_color: bool
                , use_custom_normals: bool
                , vg_collision_index: int
                , node_size: int
                , material_mapping: List[int]
                , liquid_params: LiquidExportParams):
        self.mesh_pointer = mesh_pointer
        self.mesh_matrix_world = mesh_matrix_world
        self.collision_mesh_pointer = collision_mesh_pointer
        self.collision_mesh_matrix_world = collision_mesh_matrix_world
        self.use_large_material_id = use_large_material_id
        self.use_vertex_color = use_vertex_color
        self.use_custom_normals = use_custom_normals
        self.vg_collision_index = vg_collision_index
        self.node_size = node_size
        self.material_mapping = material_mapping
        self.liquid_params = liquid_params

cdef struct CWMOGeometryBatcherMeshParams:
    uintptr_t mesh_pointer
    const float* mesh_matrix_world
    uintptr_t collision_mesh_pointer
    const float* collision_mesh_matrix_world
    bool use_large_material_id
    bool use_vertex_color
    bool use_custom_normals
    int vg_collision_index
    int node_size
    vector[int] material_mapping

    bool has_liquid
    LiquidParams liquid_params

cdef class CWMOGeometryBatcher:
    cdef vector[WMOGeometryBatcher*] _c_batchers
    cdef vector[CWMOGeometryBatcherMeshParams] _c_params

    def __cinit__(self, param_entries: List[WMOGeometryBatcherMeshParams]):
        cdef int n_groups = len(param_entries)
        cdef int i, j, k
        cdef float* group_matrix_world
        cdef float* collision_matrix_world
        cdef float* liquid_matrix_world

        self._c_params.resize(n_groups)
        self._c_batchers.resize(n_groups)

        cdef vector[float*] matrices_temp

        for x, py_param in enumerate(param_entries):
            group_matrix_world = <float*>malloc(16 * sizeof(float))
            matrices_temp.push_back(group_matrix_world)

            for j in range(4):
                for k in range(4):
                    group_matrix_world[k * 4 + j] = py_param.mesh_matrix_world[j][k]

            self._c_params[x].mesh_matrix_world = group_matrix_world

            if py_param.collision_mesh_pointer:
                self._c_params[x].collision_mesh_pointer = py_param.collision_mesh_pointer

                collision_matrix_world = <float*>malloc(16 * sizeof(float))
                matrices_temp.push_back(collision_matrix_world)

                for j in range(4):
                    for k in range(4):
                        collision_matrix_world[k * 4 + j] = py_param.collision_mesh_matrix_world[j][k]

                self._c_params[x].collision_mesh_matrix_world = collision_matrix_world
            else:
                self._c_params[x].collision_mesh_pointer = 0
                self._c_params[x].collision_mesh_matrix_world = NULL

            self._c_params[x].mesh_pointer = py_param.mesh_pointer
            self._c_params[x].use_large_material_id = py_param.use_large_material_id
            self._c_params[x].use_vertex_color = py_param.use_vertex_color
            self._c_params[x].use_custom_normals = py_param.use_custom_normals
            self._c_params[x].vg_collision_index = py_param.vg_collision_index
            self._c_params[x].node_size = py_param.node_size
            self._c_params[x].material_mapping = py_param.material_mapping

            if py_param.liquid_params:
                self._c_params[x].has_liquid = True
                self._c_params[x].liquid_params.liquid_mesh = py_param.liquid_params.liquid_mesh_pointer
                self._c_params[x].liquid_params.x_tiles = py_param.liquid_params.x_tiles
                self._c_params[x].liquid_params.y_tiles = py_param.liquid_params.y_tiles
                self._c_params[x].liquid_params.mat_id = py_param.liquid_params.mat_id
                self._c_params[x].liquid_params.is_water = py_param.liquid_params.is_water

                liquid_matrix_world = <float*>malloc(16 * sizeof(float))
                matrices_temp.push_back(liquid_matrix_world)

                for j in range(4):
                    for k in range(4):
                        liquid_matrix_world[k * 4 + j] = py_param.liquid_params.liquid_mesh_matrix_world[j][k]

                self._c_params[x].liquid_params.liquid_mesh_matrix_world = liquid_matrix_world
            else:
                self._c_params[x].has_liquid = False

        cdef CWMOGeometryBatcherMeshParams* param
        for i in prange(n_groups, nogil=True):
            param = &self._c_params[i]
            self._c_batchers[i] = new WMOGeometryBatcher(param.mesh_pointer
                                                         , param.mesh_matrix_world
                                                         , param.collision_mesh_pointer
                                                         , param.collision_mesh_matrix_world
                                                         , param.use_large_material_id
                                                         , param.use_vertex_color
                                                         , param.use_custom_normals
                                                         , param.vg_collision_index
                                                         , param.node_size
                                                         , param.material_mapping
                                                         , (&param.liquid_params) if param.has_liquid else NULL)

        cdef vector[float*].iterator it = matrices_temp.begin()
        cdef WMOGeometryBatcher * ptr

        # free temporary matrices
        while it != matrices_temp.end():
            free(deref(it))
            inc(it)


    def batches(self, group_index: int) -> Optional[bytes]:
        cdef BufferKey c_key = self._c_batchers[group_index].batches()

        if c_key.data == NULL or not c_key.size:
            return None

        return PyMemoryView_FromMemory(c_key.data, c_key.size, PyBUF_READ).tobytes()

    def normals(self, group_index: int) -> Optional[bytes]:
        cdef BufferKey c_key = self._c_batchers[group_index].normals()

        if c_key.data == NULL or not c_key.size:
            return None

        return PyMemoryView_FromMemory(c_key.data, c_key.size, PyBUF_READ).tobytes()

    def vertices(self, group_index: int) -> Optional[bytes]:
        cdef BufferKey c_key = self._c_batchers[group_index].vertices()

        if c_key.data == NULL or not c_key.size:
            return None

        return PyMemoryView_FromMemory(c_key.data, c_key.size, PyBUF_READ).tobytes()

    def triangle_indices(self, group_index: int) -> Optional[bytes]:
        cdef BufferKey c_key = self._c_batchers[group_index].triangle_indices()

        if c_key.data == NULL or not c_key.size:
            return None

        return PyMemoryView_FromMemory(c_key.data, c_key.size, PyBUF_READ).tobytes()

    def triangle_materials(self, group_index: int) -> Optional[bytes]:
        cdef BufferKey c_key = self._c_batchers[group_index].triangle_materials()

        if c_key.data == NULL or not c_key.size:
            return None

        return PyMemoryView_FromMemory(c_key.data, c_key.size, PyBUF_READ).tobytes()

    def tex_coords(self, group_index: int) -> Optional[bytes]:
        cdef BufferKey c_key = self._c_batchers[group_index].tex_coords()

        if c_key.data == NULL or not c_key.size:
            return None

        return PyMemoryView_FromMemory(c_key.data, c_key.size, PyBUF_READ).tobytes()

    def tex_coords2(self, group_index: int) -> Optional[bytes]:
        cdef BufferKey c_key = self._c_batchers[group_index].tex_coords2()

        if c_key.data == NULL or not c_key.size:
            return None

        return PyMemoryView_FromMemory(c_key.data, c_key.size, PyBUF_READ).tobytes()

    def vertex_colors(self, group_index: int) -> Optional[bytes]:
        cdef BufferKey c_key = self._c_batchers[group_index].vertex_colors()

        if c_key.data == NULL or not c_key.size:
            return None

        return PyMemoryView_FromMemory(c_key.data, c_key.size, PyBUF_READ).tobytes()

    def vertex_colors2(self, group_index: int) -> Optional[bytes]:
        cdef BufferKey c_key = self._c_batchers[group_index].vertex_colors2()

        if c_key.data == NULL or not c_key.size:
            return None

        return PyMemoryView_FromMemory(c_key.data, c_key.size, PyBUF_READ).tobytes()

    def bsp_nodes(self, group_index: int) -> Optional[bytes]:
        cdef BufferKey c_key = self._c_batchers[group_index].bsp_nodes()

        if c_key.data == NULL or not c_key.size:
            return None

        return PyMemoryView_FromMemory(c_key.data, c_key.size, PyBUF_READ).tobytes()

    def bsp_faces(self, group_index: int) -> Optional[bytes]:
        cdef BufferKey c_key = self._c_batchers[group_index].bsp_faces()

        if c_key.data == NULL or not c_key.size:
            return None

        return PyMemoryView_FromMemory(c_key.data, c_key.size, PyBUF_READ).tobytes()

    def liquid(self, group_index: int) -> bytes:
        cdef BufferKey c_key_header = self._c_batchers[group_index].liquid_header()
        header = PyMemoryView_FromMemory(c_key_header.data, c_key_header.size, PyBUF_READ).tobytes()

        cdef BufferKey c_key_vertices = self._c_batchers[group_index].liquid_vertices()
        vertices = PyMemoryView_FromMemory(c_key_vertices.data, c_key_vertices.size, PyBUF_READ).tobytes()

        cdef BufferKey c_key_tiles = self._c_batchers[group_index].liquid_tiles()
        tiles = PyMemoryView_FromMemory(c_key_tiles.data, c_key_tiles.size, PyBUF_READ).tobytes()

        return header + vertices + tiles

    def batch_count_info(self, group_index: int) -> CBatchCountInfo:
        return CBatchCountInfo(self._c_batchers[group_index].trans_batch_count()
                              , self._c_batchers[group_index].int_batch_count()
                              , self._c_batchers[group_index].ext_batch_count())


    def bounding_box(self, group_index: int) -> CBoundingBox:
        cdef const Vector3D* bb_min = self._c_batchers[group_index].bb_min()
        cdef const Vector3D* bb_max = self._c_batchers[group_index].bb_max()
        return CBoundingBox((bb_min.x, bb_min.y, bb_min.z), (bb_max.x, bb_max.y, bb_max.z))

    def get_last_error(self, group_index: int) -> CWMOGeometryBatcherError:
        return self._c_batchers[group_index].get_last_error()

    def __dealloc__(self):
       cdef vector[WMOGeometryBatcher*].iterator it = self._c_batchers.begin()
       cdef WMOGeometryBatcher * ptr

       while it != self._c_batchers.end():
           ptr = deref(it)
           del ptr
           inc(it)
