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

    cdef struct LiquidParams:
        uintptr_t liquid_mesh;
        const float* liquid_mesh_matrix_world
        unsigned x_tiles
        unsigned y_tiles
        unsigned mat_id
        bool is_water

    cdef cppclass WMOGeometryBatcher:
        WMOGeometryBatcher(uintptr_t mesh_ptr
                           , const float* mesh_matrix_world
                           , uintptr_t collision_mesh_ptr
                           , const float* collision_mesh_matrix_world
                           , bool use_large_material_id
                           , bool use_vertex_color
                           , bool use_custom_normals
                           , int vg_collision_index
                           , unsigned node_size
                           , const vector[int]& material_mapping
                           , const LiquidParams* liquid_params) nogil

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
        BufferKey liquid_header()
        BufferKey liquid_vertices()
        BufferKey liquid_tiles()
        uint16_t trans_batch_count() const
        uint16_t int_batch_count() const
        uint16_t ext_batch_count() const
        const Vector3D* bb_min() const
        const Vector3D* bb_max() const
        WMOGeometryBatcherError get_last_error() const