#include "wmo_liquid_exporter.hpp"
#include <bl_utils/mesh/custom_data.hpp>
#include <bl_utils/color_utils.hpp>
#include <extern/glm/gtc/type_ptr.hpp>

#include <unordered_map>
#include <cmath>

#include <DNA_mesh_types.h>
#include <DNA_meshdata_types.h>
#include <DNA_material_types.h>
#include <DNA_ID.h>
#include <BKE_customdata.h>

using namespace wbs_kernel::bl_utils::mesh::wmo;
using namespace wbs_kernel::bl_utils::math_utils;
using namespace wbs_kernel::bl_utils::color_utils;

LiquidExporter::LiquidExporter(std::uintptr_t liquid_mesh
    , const float* liquid_mesh_matrix_world
    , unsigned x_tiles
    , unsigned y_tiles
    , unsigned mat_id
    , bool is_water)
: _liquid_mesh(reinterpret_cast<Mesh*>(liquid_mesh))
, _liquid_mesh_matrix_world(glm::make_mat4(liquid_mesh_matrix_world))
, _mliq_header()
, _mliq_vertices()
, _mliq_tiles()
, _is_water(is_water)
{
  _mliq_header.liquid_tiles.x = x_tiles;
  _mliq_header.liquid_tiles.y = y_tiles;
  _mliq_header.liquid_verts.x = x_tiles + 1;
  _mliq_header.liquid_verts.y = y_tiles + 1;
  _mliq_header.liquid_mat_id = mat_id;

  const MVert* vertex = &_liquid_mesh->mvert[0];
  glm::vec4 vertex_co4 = {vertex->co[0], vertex->co[1], vertex->co[2], 1.f};
  glm::vec3 vertex_co = _liquid_mesh_matrix_world * vertex_co4;
  _mliq_header.liquid_corner = Vector3D{vertex_co.x, vertex_co.y, vertex_co.z};

  _process_mesh_data();
}

void LiquidExporter::_process_mesh_data()
{
  float vert_sum = 0;

  // find liquid corner
  for (int i = 0; i < _liquid_mesh->totvert; ++i)
  {
    const MVert* vertex = &_liquid_mesh->mvert[i];
    glm::vec4 vertex_co4 = {vertex->co[0], vertex->co[1], vertex->co[2], 1.f};
    glm::vec3 vertex_co = _liquid_mesh_matrix_world * vertex_co4;

    float cur_sum = vertex_co[0] + vertex_co[1];

    if (cur_sum < vert_sum)
    {
      _mliq_header.liquid_corner = Vector3D{vertex_co.x, vertex_co.y, vertex_co.z};
      vert_sum = cur_sum;
    }
  }

  if (_is_water)
  {
    // handle water vertices
    for (std::size_t i = 0; i < _mliq_header.liquid_verts.x * _mliq_header.liquid_verts.y; ++i)
    {
      auto& water_vertex = _mliq_vertices.emplace_back();
      const MVert* vertex = &_liquid_mesh->mvert[i];
      glm::vec4 vertex_co4 = {vertex->co[0], vertex->co[1], vertex->co[2], 1.f};
      glm::vec3 vertex_co = _liquid_mesh_matrix_world * vertex_co4;

      water_vertex.water_vert.height = vertex_co.z;

      // TODO: implement these?
      water_vertex.water_vert.flow1 = 0;
      water_vertex.water_vert.flow2 = 0;
      water_vertex.water_vert.flow1Pct = 0;
      water_vertex.water_vert.filler = 0;
    }
  }
  else
  {
    // handle magma vertices
    const MLoopUV* uv_map = get_custom_data_layer_named<MLoopUV>(&_liquid_mesh->ldata, "UVMap");
    assert(uv_map && "Magma type liquid mush have a UV map.");

    std::unordered_map<unsigned, Vector2D> vertex_to_uv;

    for (std::size_t i = 0; i < _liquid_mesh->totpoly; ++i)
    {
      const MPoly* poly = &_liquid_mesh->mpoly[i];

      for (int j = 0; j < poly->totloop; ++j)
      {
        const MLoop* loop = &_liquid_mesh->mloop[poly->loopstart + j];

        const MLoopUV* uv = &uv_map[poly->loopstart + j];

        vertex_to_uv[loop->v] = Vector2D{uv->uv[0], uv->uv[1]};
      }
    }

    for (std::size_t i = 0; i < _mliq_header.liquid_verts.x * _mliq_header.liquid_verts.y; ++i)
    {
      auto& magma_vertex = _mliq_vertices.emplace_back();
      Vector2D const& uv = vertex_to_uv[i];
      magma_vertex.magma_vert.s = static_cast<std::int16_t>(std::round(uv.x * 255));
      magma_vertex.magma_vert.t = static_cast<std::int16_t>(std::round(uv.y * 255));

      const MVert* vertex = &_liquid_mesh->mvert[i];
      glm::vec4 vertex_co4 = {vertex->co[0], vertex->co[1], vertex->co[2], 1.f};
      glm::vec3 vertex_co = _liquid_mesh_matrix_world * vertex_co4;

      magma_vertex.magma_vert.height = vertex_co.z;

    }
  }

  const RGBA blue {0, 0, 255, 255};

  for (std::size_t i = 0; i < _liquid_mesh->totpoly; ++i)
  {
    const MPoly* poly = &_liquid_mesh->mpoly[i];

    SMOLTile& tile_flags = _mliq_tiles.emplace_back();
    tile_flags.flags_raw = 0;

    unsigned counter = 0;
    unsigned bit = 1;
    bool not_rendered = false;

    while (bit <= 0x80)
    {
      const MLoopCol* vc_layer = get_custom_data_layer_named<MLoopCol>(&_liquid_mesh->ldata,
                                                                       "flag_" + std::to_string(counter));

      if (!vc_layer)
      {
        bit <<= 1;
        counter++;
        continue;
      }
      const RGBA cur_color {vc_layer[poly->loopstart].r,
                            vc_layer[poly->loopstart].g,
                            vc_layer[poly->loopstart].b, 255};


      bool is_checked = compare_colors(cur_color, blue);
      if (bit == 0x1 && is_checked)
      {
        not_rendered = true;
      }

      if (bit <= 0x8) // legacy/no render tile flags : set not rendered from layer 0
      {
        if (not_rendered)
        {
          tile_flags.flags_raw |= bit;
        }

        // TODO : For vanilla/BC, set liquid type flags here
      }
      else if (is_checked)
      {
        tile_flags.flags_raw |= bit;
      }

      bit <<= 1;
      counter++;
    }

  }
}
