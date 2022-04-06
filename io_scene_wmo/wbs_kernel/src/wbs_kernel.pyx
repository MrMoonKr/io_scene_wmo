cimport wbs_kernel
from typing import Dict
from cython.operator cimport dereference
from libcpp.cast cimport reinterpret_cast

from typing import List, Optional, Tuple
from enum import Enum

import bpy

cdef class CM2DrawingMesh:
    cdef M2DrawingMesh* draw_mesh
    cdef vector[M2DrawingBatch*]* batches

    def __cinit__(self, uintptr_t mesh_pointer):
       self.draw_mesh = new M2DrawingMesh(mesh_pointer)
       self.batches = NULL

    def update_geometry(self, bool is_indexed=True):
        return self.draw_mesh.update_geometry(is_indexed)

    def update_mesh_pointer(self, uintptr_t mesh_pointer):
        self.draw_mesh.update_mesh_pointer(mesh_pointer) 

    def get_drawing_batches(self) -> List[CM2DrawingBatch]:
        self.batches = self.draw_mesh.get_drawing_batches()

        batches = [CM2DrawingBatch(<uintptr_t>batch_ptr) for batch_ptr in dereference(self.batches)]

        return batches

    def update_buffers(self):
        self.draw_mesh.run_buffer_updates()

    def __dealloc__(self):
       del self.draw_mesh


cdef class CM2DrawingBatch:
    cdef M2DrawingBatch* draw_batch

    def __cinit__(self, uintptr_t draw_batch_ptr):
       self.draw_batch = <M2DrawingBatch*>draw_batch_ptr

    def set_program(self, int shader_program):
        self.draw_batch.set_program(shader_program)

    def create_vao(self):
        self.draw_batch.create_vao()

    def get_mat_id(self):
        return self.draw_batch.get_mat_id()

    def draw(self):
        self.draw_batch.draw()

    @property
    def bb_center(self):
        cdef float* bb_center = self.draw_batch.get_bb_center()
        return bb_center[0], bb_center[1], bb_center[2]

    @property
    def sort_radius(self):
        return self.draw_batch.get_sort_radius()

cdef class OpenGLUtils:

    @staticmethod
    def init_glew():
        COpenGLUtils.glew_init()

    @staticmethod
    def glBlendFuncSeparate(int srcRGB, int dstRGB, int srcAlpha, int dstAlpha):
         COpenGLUtils.set_blend_func(srcRGB, dstRGB, srcAlpha, dstAlpha)


class CBufferKey:
    buffer: int
    size: int

    def __init__(self, buffer: int, size: int):
        self.buffer = buffer
        self.size = size

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

cdef class CWMOGeometryBatcher:
    cdef WMOGeometryBatcher* _c_batcher

    def __cinit__(self
                  , uintptr_t mesh_pointer
                  , bool use_large_material_id
                  , bool use_vertex_color
                  , int vg_collision_index
                  , material_mapping: Dict[str, int]):

        cdef unordered_map[string, int] c_material_mapping

        for name, index in material_mapping.items():
            c_material_mapping[name] = index

        self._c_batcher = new WMOGeometryBatcher(mesh_pointer, use_large_material_id, use_vertex_color, vg_collision_index, c_material_mapping)

    def batches(self) -> Optional[CBufferKey]:
        cdef BufferKey c_key = self._c_batcher.batches()

        if c_key.data == NULL or not c_key.size:
            return None

        return CBufferKey(reinterpret_cast[uintptr_t](c_key.data), c_key.size)

    def normals(self) -> Optional[CBufferKey]:
        cdef BufferKey c_key = self._c_batcher.normals()

        if c_key.data == NULL or not c_key.size:
            return None

        return CBufferKey(reinterpret_cast[uintptr_t](c_key.data), c_key.size)

    def vertices(self) -> Optional[CBufferKey]:
        cdef BufferKey c_key = self._c_batcher.vertices()

        if c_key.data == NULL or not c_key.size:
            return None

        return CBufferKey(reinterpret_cast[uintptr_t](c_key.data), c_key.size)

    def triangle_indices(self) -> Optional[CBufferKey]:
        cdef BufferKey c_key = self._c_batcher.triangle_indices()

        if c_key.data == NULL or not c_key.size:
            return None

        return CBufferKey(reinterpret_cast[uintptr_t](c_key.data), c_key.size)

    def triangle_materials(self) -> Optional[CBufferKey]:
        cdef BufferKey c_key = self._c_batcher.triangle_materials()

        if c_key.data == NULL or not c_key.size:
            return None

        return CBufferKey(reinterpret_cast[uintptr_t](c_key.data), c_key.size)

    def tex_coords(self) -> Optional[CBufferKey]:
        cdef BufferKey c_key = self._c_batcher.tex_coords()

        if c_key.data == NULL or not c_key.size:
            return None

        return CBufferKey(reinterpret_cast[uintptr_t](c_key.data), c_key.size)

    def tex_coords2(self) -> Optional[CBufferKey]:
        cdef BufferKey c_key = self._c_batcher.tex_coords2()

        if c_key.data == NULL or not c_key.size:
            return None

        return CBufferKey(reinterpret_cast[uintptr_t](c_key.data), c_key.size)

    def vertex_colors(self) -> Optional[CBufferKey]:
        cdef BufferKey c_key = self._c_batcher.vertex_colors()

        if c_key.data == NULL or not c_key.size:
            return None

        return CBufferKey(reinterpret_cast[uintptr_t](c_key.data), c_key.size)

    def vertex_colors2(self) -> Optional[CBufferKey]:
        cdef BufferKey c_key = self._c_batcher.vertex_colors2()

        if c_key.data == NULL or not c_key.size:
            return None

        return CBufferKey(reinterpret_cast[uintptr_t](c_key.data), c_key.size)

    def batch_count_info(self) -> CBatchCountInfo:
        return CBatchCountInfo(self._c_batcher.trans_batch_count()
                              , self._c_batcher.int_batch_count()
                              , self._c_batcher.ext_batch_count())


    def bounding_box(self) -> CBoundingBox:
        cdef const Vector3D* bb_min = self._c_batcher.bb_min()
        cdef const Vector3D* bb_max = self._c_batcher.bb_max()
        return CBoundingBox((bb_min.x, bb_min.y, bb_min.z), (bb_max.x, bb_max.y, bb_max.z))

    def get_last_error(self) -> CWMOGeometryBatcherError:
        return self._c_batcher.get_last_error()

    def __dealloc__(self):
       del self._c_batcher
