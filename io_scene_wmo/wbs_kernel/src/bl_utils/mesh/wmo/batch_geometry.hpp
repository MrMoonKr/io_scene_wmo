#ifndef WBS_KERNEL_BATCH_GEOMETRY_HPP
#define WBS_KERNEL_BATCH_GEOMETRY_HPP

#include <bl_utils/math_utils.hpp>

#include <cstdint>
#include <vector>
#include <string>
#include <unordered_map>


struct Mesh;
struct MPoly;
struct MLoop;
struct MLoopCol;
struct MDeformVert;


namespace wbs_kernel::bl_utils::mesh::wmo
{
  class BSPTree;

  inline constexpr short COLLISION_MAT_NR = 32767;

  struct RGBA
  {
    unsigned char r;
    unsigned char g;
    unsigned char b;
    unsigned char a;
  };

  enum MOBAFlags
  {
    FLAG_UNK = 0x1,
    FLAG_USE_MATERIAL_ID_LARGE = 0x2
  };

  enum BatchType
  {
    TRANS = 0,
    INT = 1,
    EXT = 2
  };

  enum WMOGeometryBatcherError
  {
    NO_ERROR = 0,
    LOOSE_MATERIAL_ID = 1
  };

  struct MOBABoundingBox
  {
    std::int16_t min[3];
    std::int16_t max[3];
  };

  struct MOBAMaterialIDLarge
  {
    std::uint8_t pad[0xA];
    std::uint16_t id;
  };

  struct MOBABatch
  {
    union
    {
      MOBABoundingBox bb_box;
      MOBAMaterialIDLarge material_id_large;
    };

    std::uint32_t start_index;
    std::uint16_t indices_count;
    std::uint16_t min_index;
    std::uint16_t max_index;
    std::uint8_t flags;
    std::uint8_t material_id;
  };

  struct MOPYFlags
  {
    /*0x01*/ std::uint8_t F_UNK_0x01: 1;
    /*0x02*/ std::uint8_t F_NOCAMCOLLIDE : 1;
    /*0x04*/ std::uint8_t F_DETAIL : 1;
    /*0x08*/ std::uint8_t F_COLLISION : 1; // Turns off rendering of water ripple effects. May also do more. Should be used for ghost material triangles.
    /*0x10*/ std::uint8_t F_HINT : 1;
    /*0x20*/ std::uint8_t F_RENDER : 1;
    /*0x40*/ std::uint8_t F_UNK_0x40 : 1;
    /*0x80*/ std::uint8_t F_COLLIDE_HIT : 1;
  };

  struct MOPYTriangleMaterial
  {
    union
    {
      std::uint8_t flags_int;
      MOPYFlags flags;
    };

    std::uint8_t material_id;
  };

  struct BufferKey
  {
    char* data;
    std::size_t size;
  };

  struct BatchVertexInfo
  {
    unsigned local_index;
    RGBA col;
    RGBA col2;
    math_utils::Vector2D uv;
    math_utils::Vector2D uv2;
  };

  class WMOGeometryBatcher
  {
  public:
    WMOGeometryBatcher(std::uintptr_t mesh_ptr
                       , bool use_large_material_id
                       , bool use_vertex_color
                       , int vg_collision_index
                       , unsigned node_size
                       , std::vector<int> const& material_mapping
    );

    ~WMOGeometryBatcher();

    [[nodiscard]]
    BufferKey batches();

    [[nodiscard]]
    BufferKey normals();

    [[nodiscard]]
    BufferKey vertices();

    [[nodiscard]]
    BufferKey triangle_indices();

    [[nodiscard]]
    BufferKey triangle_materials();

    [[nodiscard]]
    BufferKey tex_coords();

    [[nodiscard]]
    BufferKey tex_coords2();

    [[nodiscard]]
    BufferKey vertex_colors();

    [[nodiscard]]
    BufferKey vertex_colors2();

    [[nodiscard]]
    BufferKey bsp_nodes();

    [[nodiscard]]
    BufferKey bsp_faces();

    [[nodiscard]]
    std::uint16_t trans_batch_count() const { return _trans_batch_count; };

    [[nodiscard]]
    std::uint16_t int_batch_count() const { return _int_batch_count; };

    [[nodiscard]]
    std::uint16_t ext_batch_count() const { return _ext_batch_count; };

    [[nodiscard]]
    const math_utils::Vector3D* bb_min() const { return &_bounding_box_min; };

    [[nodiscard]]
    const math_utils::Vector3D* bb_max() const { return &_bounding_box_max; };

    [[nodiscard]]
    WMOGeometryBatcherError get_last_error() const { return _last_error; };

  private:

    void _create_new_vert(BatchVertexInfo& v_info
                         , MOBABatch* cur_batch
                         , const MVert* vertex
                         , const MLoop* loop);

    void _create_new_collision_vert(const MVert* vertex
                                   , const MLoop* loop);

    void _create_new_collision_triangle(const MPoly* poly);

    void _create_new_render_triangle(const MPoly* poly, MOBABatch* cur_batch);

    // Initalize
    void _unpack_vertex(BatchVertexInfo& v_info
                       , MOPYTriangleMaterial& tri_mat
                       , unsigned loop_index);

    void _create_new_batch(std::uint16_t mat_id
                          , BatchType batch_type
                          , MOBABatch*& cur_batch
                          , std::uint16_t& cur_batch_mat_id
                          , BatchType& cur_batch_type);

    [[nodiscard]]
    bool _needs_new_vert(unsigned vert_index, BatchVertexInfo& cur_v_info);

    [[nodiscard]]
    bool _is_vertex_collidable(unsigned vert_index);

    void _calculate_bounding_for_vertex(const MVert* vertex);

    void _calculate_batch_bounding_for_vertex(MOBABatch* cur_batch, const MVert* vertex) const;

    void _set_last_error(WMOGeometryBatcherError error) { _last_error = error; };

    [[nodiscard]]
    bool _needs_new_batch(MOBABatch* cur_batch
        , const MPoly* cur_poly
        , BatchType cur_batch_type
        , BatchType cur_poly_batch_type
        , std::uint16_t cur_batch_mat_id);

    [[nodiscard]]
    static unsigned char _get_grayscale_factor(const MLoopCol* color);

    [[nodiscard]]
    static bool _compare_colors(RGBA const& v1, RGBA const& v2);

    [[nodiscard]]
    static bool comp_color_key(RGBA const& color);

    [[nodiscard]]
    static BatchType get_batch_type(const MPoly* poly
        , const MLoopCol* batch_map_trans
        , const MLoopCol* batch_map_int);


    Mesh* _mesh;
    std::vector<MOBABatch> _batches;

    std::vector<math_utils::Vector3D> _vertices;
    std::vector<std::uint16_t> _triangle_indices;
    std::vector<MOPYTriangleMaterial> _triangle_materials;
    std::vector<math_utils::Vector3D> _normals;
    std::vector<math_utils::Vector2D> _tex_coords;
    std::vector<math_utils::Vector2D> _tex_coords2;
    std::vector<RGBA> _vertex_colors;
    std::vector<RGBA> _vertex_colors2;

    std::uint16_t _trans_batch_count;
    std::uint16_t _int_batch_count;
    std::uint16_t _ext_batch_count;

    math_utils::Vector3D _bounding_box_min;
    math_utils::Vector3D _bounding_box_max;

    std::unordered_map<unsigned, std::vector<BatchVertexInfo>> _cur_batch_vertex_map;
    std::unordered_map<unsigned, unsigned> _collision_vertex_map;
    std::vector<int> const& _material_ids;

    WMOGeometryBatcherError _last_error;

    int _vg_collision_index;

    bool _use_vertex_color;
    bool _use_large_material_id;
    bool _has_collision_vg;

    const MLoop* _bl_loops;
    const MVert* _bl_verts;
    const MPoly* _bl_polygons;
    const float(*_bl_vertex_normals)[3];

    MLoopCol* _bl_batch_map_trans;
    MLoopCol* _bl_batch_map_int;
    MLoopCol* _bl_lightmap;
    MLoopCol* _bl_blendmap;
    MLoopCol* _bl_vertex_color;
    MLoopUV* _bl_uv;
    MLoopUV* _bl_uv2;
    MDeformVert* _bl_vg_data;

    BSPTree* _bsp_tree;


  };
}

#endif //WBS_KERNEL_BATCH_GEOMETRY_HPP
