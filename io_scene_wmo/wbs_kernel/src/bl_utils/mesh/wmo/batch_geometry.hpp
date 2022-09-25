#ifndef WBS_KERNEL_BATCH_GEOMETRY_HPP
#define WBS_KERNEL_BATCH_GEOMETRY_HPP

#include <bl_utils/math_utils.hpp>
#include <bl_utils/color_utils.hpp>

#include <cstdint>
#include <vector>
#include <string>
#include <unordered_map>
#include <variant>


struct Mesh;
struct MPoly;
struct MLoop;
struct MLoopCol;
struct MPropCol;
struct MDeformVert;


namespace wbs_kernel::bl_utils::mesh::wmo
{
  class BSPTree;
  class LiquidExporter;

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
    color_utils::RGBA col;
    color_utils::RGBA col2;
    math_utils::Vector2D uv;
    math_utils::Vector2D uv2;
    math_utils::Vector3D loop_normal;

  };

  struct LiquidParams
  {
    std::uintptr_t liquid_mesh;
    const float* liquid_mesh_matrix_world;
    unsigned x_tiles;
    unsigned y_tiles;
    unsigned mat_id;
    bool is_water;
  };

  struct VertexColorLayer
  {
    VertexColorLayer(const Mesh* mesh, std::string const& name);

    [[nodiscard]]
    bool exists() const { return _exists; };

    [[nodiscard]]
    bool is_per_loop() const { return _is_per_loop; };

    color_utils::RGBA operator[] (std::size_t index) const;

  private:
    bool _exists;
    bool _is_per_loop;
    const Mesh* _mesh;
    std::variant<std::monostate, MLoopCol*, MPropCol*> _color_layer;
  };

  class WMOGeometryBatcher
  {
  public:
    WMOGeometryBatcher(std::uintptr_t mesh_ptr
                       , const float* mesh_matrix_world
                       , std::uintptr_t collision_mesh_ptr
                       , const float* collision_mesh_matrix_world
                       , bool use_large_material_id
                       , bool use_vertex_color
                       , bool use_custom_normals
                       , int vg_collision_index
                       , unsigned node_size
                       , std::vector<int> const& material_mapping
                       , const LiquidParams* liquid_params
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
    BufferKey liquid_vertices();

    [[nodiscard]]
    BufferKey liquid_tiles();

    [[nodiscard]]
    BufferKey liquid_header();

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

    void _create_new_collision_triangle(const MLoopTri* tri);

    void _create_new_render_triangle(const MLoopTri* tri, MOBABatch* cur_batch);

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

    void _calculate_bounding_for_vertex(glm::vec3 const& vertex);

    void _calculate_batch_bounding_for_vertex(MOBABatch* cur_batch,  glm::vec3 const& vertex) const;

    void _set_last_error(WMOGeometryBatcherError error) { _last_error = error; };

    [[nodiscard]]
    bool _needs_new_batch(MOBABatch* cur_batch
        , const MLoopTri* cur_tri
        , BatchType cur_batch_type
        , BatchType cur_poly_batch_type
        , std::uint16_t cur_batch_mat_id);

    [[nodiscard]]
    static unsigned char _get_grayscale_factor(color_utils::RGBA const& color);

    [[nodiscard]]
    BatchType get_batch_type(const MLoopTri* poly);


    Mesh* _mesh;
    Mesh* _collision_mesh;

    glm::mat4 _mesh_mtx_world;
    glm::mat4 _collision_mtx_world;

    std::vector<MOBABatch> _batches;

    std::vector<math_utils::Vector3D> _vertices;
    std::vector<std::uint16_t> _triangle_indices;
    std::vector<MOPYTriangleMaterial> _triangle_materials;
    std::vector<math_utils::Vector3D> _normals;
    std::vector<math_utils::Vector2D> _tex_coords;
    std::vector<math_utils::Vector2D> _tex_coords2;
    std::vector<color_utils::RGBA> _vertex_colors;
    std::vector<color_utils::RGBA> _vertex_colors2;

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
    bool _use_custom_normals;
    bool _has_collision_vg;

    const MLoop* _bl_loops;
    const MVert* _bl_verts;
    const MPoly* _bl_polygons;
    const MLoopTri* _bl_looptris;
    const float(*_bl_vertex_normals)[3];
    const float(*_bl_loop_normals)[3];

    VertexColorLayer _bl_batch_map_trans;
    VertexColorLayer _bl_batch_map_int;
    VertexColorLayer _bl_lightmap;
    VertexColorLayer _bl_blendmap;
    VertexColorLayer _bl_vertex_color;
    MLoopUV* _bl_uv;
    MLoopUV* _bl_uv2;
    MDeformVert* _bl_vg_data;

    // collision mesh data
    const MLoop* _bl_col_loops;
    const MVert* _bl_col_verts;
    const MLoopTri* _bl_col_looptris;
    const float(*_bl_col_vertex_normals)[3];

    BSPTree* _bsp_tree;
    LiquidExporter* _liquid_exporter;


  };
}

#endif //WBS_KERNEL_BATCH_GEOMETRY_HPP
