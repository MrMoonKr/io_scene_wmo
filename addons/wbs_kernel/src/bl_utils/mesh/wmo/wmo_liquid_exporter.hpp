#ifndef WBS_KERNEL_WMO_LIQUID_EXPORTER_HPP
#define WBS_KERNEL_WMO_LIQUID_EXPORTER_HPP

#include <bl_utils/math_utils.hpp>

#include <cstdint>
#include <vector>

struct Mesh;
struct MVert;
struct MPoly;
struct MLoop;

namespace wbs_kernel::bl_utils::mesh::wmo
{
  #pragma pack(push, 1)
  struct MLIQHeader
  {
    math_utils::Vector2Di liquid_verts;
    math_utils::Vector2Di liquid_tiles;
    math_utils::Vector3D liquid_corner;
    std::uint16_t liquid_mat_id;
  };
  #pragma pack(pop)

  struct SMOWVert
  {
    std::uint8_t flow1;
    std::uint8_t flow2;
    std::uint8_t flow1Pct;
    std::uint8_t filler;
    float height;
  };

  struct SMOMVert
  {
    std::int16_t s;
    std::int16_t t;
    float height;
  };

  union SMOLVert
  {
    SMOWVert water_vert;
    SMOMVert magma_vert;
  };

  struct SMOLTileFlags
  {
    uint8_t legacy_liquid_type : 4; // For older WMOs, used to set liquid type.
    uint8_t unknown_1 : 1;
    uint8_t unknown_2 : 1;
    uint8_t fishable : 1;
    uint8_t shared : 1;
  };

  struct SMOLTile
  {
    union
    {
      SMOLTileFlags flags;
      uint8_t flags_raw;
    };

  };

  class LiquidExporter
  {
  public:
    LiquidExporter(std::uintptr_t liquid_mesh
                   , const float* liquid_mesh_matrix_world
                   , unsigned x_tiles
                   , unsigned y_tiles
                   , unsigned mat_id
                   , bool is_water);

    [[nodiscard]]
    std::vector<SMOLVert>& vertices() { return _mliq_vertices; };

    [[nodiscard]]
    std::vector<SMOLTile>& tiles() { return _mliq_tiles; };

    [[nodiscard]]
    MLIQHeader& header() { return _mliq_header; };


  private:
    void _process_mesh_data();

    Mesh* _liquid_mesh;
    MVert* _bl_verts;
    MPoly* _bl_polygons;
    MLoop *_bl_loops;
    glm::mat4 _liquid_mesh_matrix_world;

    MLIQHeader _mliq_header;
    std::vector<SMOLVert> _mliq_vertices;
    std::vector<SMOLTile> _mliq_tiles;

    bool _is_water;



  };

}

#endif //WBS_KERNEL_WMO_LIQUID_EXPORTER_HPP
