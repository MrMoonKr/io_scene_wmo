cimport wmo_utils
from cpython.memoryview cimport PyMemoryView_FromMemory
from cpython.buffer cimport PyBUF_READ

from typing import Tuple, Optional, List
from enum import Enum


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
                  , unsigned node_size
                  , material_mapping: List[int]):

        cdef vector[int] c_material_mapping = material_mapping
        self._c_batcher = new WMOGeometryBatcher(mesh_pointer, use_large_material_id, use_vertex_color
                                                 , vg_collision_index, node_size, c_material_mapping)

    def batches(self) -> Optional[bytes]:
        cdef BufferKey c_key = self._c_batcher.batches()

        if c_key.data == NULL or not c_key.size:
            return None

        return PyMemoryView_FromMemory(c_key.data, c_key.size, PyBUF_READ).tobytes()

    def normals(self) -> Optional[bytes]:
        cdef BufferKey c_key = self._c_batcher.normals()

        if c_key.data == NULL or not c_key.size:
            return None

        return PyMemoryView_FromMemory(c_key.data, c_key.size, PyBUF_READ).tobytes()

    def vertices(self) -> Optional[bytes]:
        cdef BufferKey c_key = self._c_batcher.vertices()

        if c_key.data == NULL or not c_key.size:
            return None

        return PyMemoryView_FromMemory(c_key.data, c_key.size, PyBUF_READ).tobytes()

    def triangle_indices(self) -> Optional[bytes]:
        cdef BufferKey c_key = self._c_batcher.triangle_indices()

        if c_key.data == NULL or not c_key.size:
            return None

        return PyMemoryView_FromMemory(c_key.data, c_key.size, PyBUF_READ).tobytes()

    def triangle_materials(self) -> Optional[bytes]:
        cdef BufferKey c_key = self._c_batcher.triangle_materials()

        if c_key.data == NULL or not c_key.size:
            return None

        return PyMemoryView_FromMemory(c_key.data, c_key.size, PyBUF_READ).tobytes()

    def tex_coords(self) -> Optional[bytes]:
        cdef BufferKey c_key = self._c_batcher.tex_coords()

        if c_key.data == NULL or not c_key.size:
            return None

        return PyMemoryView_FromMemory(c_key.data, c_key.size, PyBUF_READ).tobytes()

    def tex_coords2(self) -> Optional[bytes]:
        cdef BufferKey c_key = self._c_batcher.tex_coords2()

        if c_key.data == NULL or not c_key.size:
            return None

        return PyMemoryView_FromMemory(c_key.data, c_key.size, PyBUF_READ).tobytes()

    def vertex_colors(self) -> Optional[bytes]:
        cdef BufferKey c_key = self._c_batcher.vertex_colors()

        if c_key.data == NULL or not c_key.size:
            return None

        return PyMemoryView_FromMemory(c_key.data, c_key.size, PyBUF_READ).tobytes()

    def vertex_colors2(self) -> Optional[bytes]:
        cdef BufferKey c_key = self._c_batcher.vertex_colors2()

        if c_key.data == NULL or not c_key.size:
            return None

        return PyMemoryView_FromMemory(c_key.data, c_key.size, PyBUF_READ).tobytes()

    def bsp_nodes(self) -> Optional[bytes]:
        cdef BufferKey c_key = self._c_batcher.bsp_nodes()

        if c_key.data == NULL or not c_key.size:
            return None

        return PyMemoryView_FromMemory(c_key.data, c_key.size, PyBUF_READ).tobytes()

    def bsp_faces(self) -> Optional[bytes]:
        cdef BufferKey c_key = self._c_batcher.bsp_faces()

        if c_key.data == NULL or not c_key.size:
            return None

        return PyMemoryView_FromMemory(c_key.data, c_key.size, PyBUF_READ).tobytes()

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
