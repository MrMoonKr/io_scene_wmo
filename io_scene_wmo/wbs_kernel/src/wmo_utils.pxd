from libc.stdint cimport uintptr_t, uint16_t
from libcpp.vector cimport vector
from libcpp cimport bool

cdef extern from "bl_utils/mesh/wmo/batch_geometry.hpp" namespace "wbs_kernel::bl_utils::math_utils":
    cdef struct Vector3D:
        float x
        float y
        float z

cdef extern from "bl_utils/math_utils.hpp" namespace "wbs_kernel::bl_utils::mesh::wmo":

    cdef struct BufferKey:
        char* data
        size_t size

    cdef enum WMOGeometryBatcherError:
        NO_ERROR = 0,
        LOOSE_MATERIAL_ID = 1

    cdef cppclass WMOGeometryBatcher:
        WMOGeometryBatcher(uintptr_t mesh_ptr
                           , bool use_large_material_id
                           , bool use_vertex_color
                           , int vg_collision_index
                           , unsigned node_size
                           , const vector[int]& material_mapping) nogil

        BufferKey batches()
        BufferKey normals()
        BufferKey vertices()
        BufferKey triangle_indices()
        BufferKey triangle_materials()
        BufferKey tex_coords()
        BufferKey tex_coords2()
        BufferKey vertex_colors()
        BufferKey vertex_colors2()
        BufferKey bsp_nodes()
        BufferKey bsp_faces()
        uint16_t trans_batch_count() const
        uint16_t int_batch_count() const
        uint16_t ext_batch_count() const
        const Vector3D* bb_min() const
        const Vector3D* bb_max() const
        WMOGeometryBatcherError get_last_error() const