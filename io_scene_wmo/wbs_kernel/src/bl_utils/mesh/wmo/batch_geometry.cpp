#include "batch_geometry.hpp"
#include <bl_utils/mesh/custom_data.hpp>
#include <bl_utils/mesh/wmo/bsp_tree.hpp>
#include <bl_utils/mesh/wmo/wmo_liquid_exporter.hpp>
#include <extern/glm/gtc/type_ptr.hpp>

#include <cassert>
#include <algorithm>
#include <limits>

#include <BKE_mesh_types.h>
#include <DNA_mesh_types.h>
#include <DNA_meshdata_types.h>
#include <DNA_material_types.h>
#include <DNA_ID.h>
#include <BKE_customdata.h>

using namespace wbs_kernel::bl_utils::math_utils;
using namespace wbs_kernel::bl_utils::color_utils;
using namespace wbs_kernel::bl_utils::mesh::wmo;
using namespace wbs_kernel::bl_utils::mesh;


WMOGeometryBatcher::WMOGeometryBatcher(std::uintptr_t mesh_ptr
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

)
: _mesh(reinterpret_cast<Mesh*>(mesh_ptr))
, _mesh_mtx_world(glm::make_mat4(mesh_matrix_world))
, _bsp_tree(nullptr)
, _liquid_exporter(nullptr)
, _trans_batch_count(0)
, _int_batch_count(0)
, _ext_batch_count(0)
, _use_vertex_color(use_vertex_color)
, _use_large_material_id(use_large_material_id)
, _vg_collision_index(vg_collision_index)
, _bounding_box_min(Vector3D{std::numeric_limits<float>::max()
                             , std::numeric_limits<float>::max()
                             , std::numeric_limits<float>::max()})
, _bounding_box_max(Vector3D{std::numeric_limits<float>::lowest()
                              , std::numeric_limits<float>::lowest()
                              , std::numeric_limits<float>::lowest()})
, _bl_loops(_mesh->mloop)
, _bl_verts(_mesh->mvert)
, _bl_polygons(_mesh->mpoly)
, _bl_looptris(_mesh->runtime->looptris.array)
, _bl_vertex_normals(reinterpret_cast<const float(*)[3]>(_mesh->runtime->vert_normals))
, _has_collision_vg(_vg_collision_index >= 0)
, _bl_batch_map_trans(_mesh, "BatchmapTrans")
, _bl_batch_map_int(_mesh, "BatchmapInt")
, _bl_lightmap(_mesh, "Lightmap")
, _bl_blendmap(_mesh, "Blendmap")
, _bl_vertex_color(_mesh, "Col")
, _bl_uv(get_custom_data_layer_named<MLoopUV>(&_mesh->ldata, "UVMap"))
, _bl_uv2(get_custom_data_layer_named<MLoopUV>(&_mesh->ldata, "UVMap.001"))
, _last_error(WMOGeometryBatcherError::NO_ERROR)
, _collision_mesh(nullptr)
, _material_ids(material_mapping)
, _mesh_materials_per_poly(static_cast<std::int32_t*>(WBS_CustomData_get_layer_named(&_mesh->pdata, eCustomDataType::CD_PROP_INT32, "material_index")))
{
  assert(!_mesh->runtime->vert_normals_dirty && "Vertex normals were not calculated for group mesh.");
  assert(!_mesh->runtime->poly_normals_dirty && "Poly normals were not calculated for group mesh.");

  if (collision_mesh_ptr)
  {
    _collision_mesh = reinterpret_cast<Mesh*>(collision_mesh_ptr);

    assert(!_collision_mesh->runtime->vert_normals_dirty && "Vertex normals were not calculated for collision mesh.");
    assert(!_collision_mesh->runtime->poly_normals_dirty && "Poly normals were not calculated for collision mesh.");

    _bl_col_loops = _collision_mesh->mloop;
    _bl_col_verts = _collision_mesh->mvert;
    _bl_col_vertex_normals = reinterpret_cast<const float(*)[3]>(_collision_mesh->runtime->vert_normals);
    _bl_col_looptris = _collision_mesh->runtime->looptris.array;

    assert(collision_mesh_matrix_world && "Collision is present but its world matrix is nullptr.");
    _collision_mtx_world = glm::make_mat4(collision_mesh_matrix_world);
  }

  if (_has_collision_vg)
  {
    _bl_vg_data = static_cast<MDeformVert*>(WBS_CustomData_get_layer(&_mesh->vdata,
                                                                     eCustomDataType::CD_MDEFORMVERT));

    if (!_bl_vg_data)
    {
      _has_collision_vg = false;
    }
  }

  // custom normals
  _use_custom_normals = use_custom_normals && WBS_CustomData_has_layer(&_mesh->ldata,
                                                                       eCustomDataType::CD_CUSTOMLOOPNORMAL);

  if (_use_custom_normals)
  {
    _bl_loop_normals = reinterpret_cast<const float(*)[3]>(WBS_CustomData_get_layer(&_mesh->ldata,
                                                                                    eCustomDataType::CD_NORMAL));
  }


  unsigned n_loop_tris = _mesh->totloop - (_mesh->totpoly * 2);
  std::vector<std::pair<const MLoopTri*, BatchType>> polys_per_mat;
  polys_per_mat.resize(n_loop_tris);

  for (int i = 0; i < n_loop_tris; ++i)
  {
    polys_per_mat[i] = std::make_pair(&_bl_looptris[i], WMOGeometryBatcher::get_batch_type(&_bl_looptris[i]));
  }
  
  // presort faces by their batch type and material_id forming the batches
  std::sort(polys_per_mat.begin(), polys_per_mat.end(),
      [this](std::pair<const MLoopTri*, BatchType> const& lhs, std::pair<const MLoopTri*, BatchType> const& rhs) -> bool
      {
        return std::tie(lhs.second, _mesh_materials_per_poly[lhs.first->poly])
          < std::tie(rhs.second, _mesh_materials_per_poly[rhs.first->poly]);
      });

  MOBABatch* cur_batch = nullptr;
  std::uint16_t cur_batch_mat_id = 0;
  BatchType cur_batch_type = BatchType::TRANS;

  for (auto [looptri, batch_type] : polys_per_mat)
  {
    if (WMOGeometryBatcher::_needs_new_batch(cur_batch, looptri, cur_batch_type,
                                             batch_type, cur_batch_mat_id))
    {
      _create_new_batch(_material_ids[_mesh_materials_per_poly[looptri->poly]],
                        batch_type, cur_batch, cur_batch_mat_id, cur_batch_type);
    }

    _create_new_render_triangle(looptri, cur_batch);
  }

  // fill last batch max index
  if (cur_batch)
  {
    cur_batch->max_index = _vertices.size() - 1;
  }

  // handle collision only faces
  if (_collision_mesh)
  {
    for (std::size_t i = 0; i < _collision_mesh->totloop - (_collision_mesh->totpoly * 2); ++i)
    {
      _create_new_collision_triangle(&_bl_col_looptris[i]);
    }
  }

  // calculate BSP tree
  BoundingBox bb_box{_bounding_box_min, _bounding_box_max};
  _bsp_tree = new BSPTree{_vertices, _triangle_indices, bb_box, node_size};

  // handle liquid
  if (liquid_params)
  {
    _liquid_exporter = new LiquidExporter(liquid_params->liquid_mesh
        , liquid_params->liquid_mesh_matrix_world
        , liquid_params->x_tiles
        , liquid_params->y_tiles
        , liquid_params->mat_id
        , liquid_params->is_water);
  }
}

void WMOGeometryBatcher::_create_new_collision_triangle(const MLoopTri* tri)
{

  MOPYTriangleMaterial& tri_mat = _triangle_materials.emplace_back();
  tri_mat.flags_int = 0;
  tri_mat.flags.F_COLLISION = true;
  tri_mat.material_id = 0xFF;

  for (unsigned loop_index : tri->tri)
  {
    const MLoop* loop = &_bl_col_loops[loop_index];
    const MVert* vert = &_bl_col_verts[loop->v];

    auto it = _collision_vertex_map.find(loop->v);

    // add new vertex if required
    if (it == _collision_vertex_map.end())
    {
      _create_new_collision_vert(vert, loop);
    }
    else
    {
      _triangle_indices.emplace_back(it->second);
    }
  }

}

void WMOGeometryBatcher::_unpack_vertex(BatchVertexInfo& v_info
    , MOPYTriangleMaterial& tri_mat
    , unsigned loop_index)
{
  if (_use_vertex_color && _bl_vertex_color.exists())
  {
    RGBA color = _bl_vertex_color[loop_index];
    v_info.col.r = color.b;
    v_info.col.g = color.g;
    v_info.col.b = color.r;

    if (_bl_lightmap.exists())
    {
      unsigned char attenuation = _get_grayscale_factor(_bl_lightmap[loop_index]);

      // TODO: verify what this actually does and if needed
      if (attenuation > 0)
      {
        tri_mat.flags.F_UNK_0x01 = true;
      }

      v_info.col.a = attenuation;
    }
  }

  if (_bl_blendmap.exists())
  {
    RGBA color = _bl_blendmap[loop_index];
    v_info.col2.a = _get_grayscale_factor(color);
  }

  if (_bl_uv)
  {
    const MLoopUV* uv_coord = &_bl_uv[loop_index];
    v_info.uv = {uv_coord->uv[0], 1.0f - uv_coord->uv[1]};
  }

  if (_bl_uv2)
  {
    const MLoopUV* uv_coord = &_bl_uv2[loop_index];
    v_info.uv2 = {uv_coord->uv[0], 1.0f - uv_coord->uv[1]};
  }

  if (_use_custom_normals)
  {
    v_info.loop_normal = Vector3D({_bl_loop_normals[loop_index][0],
                                   _bl_loop_normals[loop_index][1],
                                   _bl_loop_normals[loop_index][2]});
  }
}

void WMOGeometryBatcher::_create_new_collision_vert(const MVert* vertex
                                                   , const MLoop* loop)
{
  unsigned v_local_index = _vertices.size();

  glm::vec4 vertex_co_4 = glm::vec4(vertex->co[0], vertex->co[1], vertex->co[2], 1.f);
  glm::vec3 vertex_co = glm::vec3(_collision_mtx_world * vertex_co_4);

  _vertices.emplace_back(Vector3D{vertex_co.x, vertex_co.y, vertex_co.z});

  glm::mat3 normal_mtx = glm::inverse(glm::transpose( glm::mat3(_collision_mtx_world)));

  glm::vec3 normal = glm::vec3{_bl_col_vertex_normals[loop->v][0], _bl_col_vertex_normals[loop->v][1],
                                 _bl_col_vertex_normals[loop->v][2]};
  normal = glm::normalize(glm::vec3(normal_mtx * normal));

  _normals.emplace_back(Vector3D{normal.x, normal.y, normal.z});

  _tex_coords.emplace_back(Vector2D{0.f, 0.f});

  if (_bl_uv2)
  {
    _tex_coords2.emplace_back(Vector2D{0.f, 0.f});
  }

  if (_use_vertex_color)
  {
    _vertex_colors.emplace_back(RGBA{0x7F, 0x7F, 0x7F, 0x0});
  }

  if (_bl_blendmap.exists())
  {
    _vertex_colors2.emplace_back(RGBA{0x0, 0x0, 0x0, 0x0});
  }

  _triangle_indices.emplace_back(v_local_index);
  _collision_vertex_map[loop->v] = v_local_index;

  _calculate_bounding_for_vertex(vertex_co);
}

void WMOGeometryBatcher::_create_new_vert(BatchVertexInfo& v_info
                                         , MOBABatch* cur_batch
                                         , const MVert* vertex
                                         , const MLoop* loop)
{
  v_info.local_index = _vertices.size();

  glm::vec4 vertex_co_4 = glm::vec4(vertex->co[0], vertex->co[1], vertex->co[2], 1.f);
  glm::vec3 vertex_co = glm::vec3(_mesh_mtx_world * vertex_co_4);

  _vertices.emplace_back(Vector3D{vertex_co.x, vertex_co.y, vertex_co.z});

  glm::mat3 normal_mtx = glm::inverse(glm::transpose( glm::mat3(_mesh_mtx_world)));

  glm::vec3 normal;
  if (_use_custom_normals)
  {
    normal = glm::vec4{v_info.loop_normal.x, v_info.loop_normal.y, v_info.loop_normal.z, 0.f};
  }
  else
  {
    normal = glm::vec4{_bl_vertex_normals[loop->v][0], _bl_vertex_normals[loop->v][1],
                         _bl_vertex_normals[loop->v][2], 0.f};
  }

  normal = glm::normalize(normal_mtx * normal);
  _normals.emplace_back(Vector3D{normal.x, normal.y, normal.z});


  _tex_coords.emplace_back(v_info.uv);

  if (_bl_uv2)
    _tex_coords2.emplace_back(v_info.uv2);

  if (_use_vertex_color)
  {
    _vertex_colors.emplace_back(v_info.col);
  }

  if (_bl_blendmap.exists())
  {
    _vertex_colors2.emplace_back(v_info.col2);
  }

  _cur_batch_vertex_map[loop->v].emplace_back(v_info);

  _calculate_bounding_for_vertex(vertex_co);
  _calculate_batch_bounding_for_vertex(cur_batch, vertex_co);
}


bool WMOGeometryBatcher::_needs_new_vert(unsigned vert_index, BatchVertexInfo& cur_v_info)
{
  // Checks if new vertex needs to be created for processed vertex.
  // If already found, assigns a correct local index to cur_v_info.

  auto it = _cur_batch_vertex_map.find((vert_index));

  if (it == _cur_batch_vertex_map.end())
  {
    return true;
  }

  for (auto& v_info : it->second)
  {
    if (!compare_v2v2(v_info.uv, cur_v_info.uv, STD_UV_CONNECT_LIMIT)
      || !compare_v2v2(v_info.uv2, cur_v_info.uv2, STD_UV_CONNECT_LIMIT)
      || !compare_colors(v_info.col, cur_v_info.col)
      || !compare_colors(v_info.col2, cur_v_info.col2))
    {
      continue;
    }

    if (_use_custom_normals && !compare_v3v3(v_info.loop_normal, cur_v_info.loop_normal, STD_UV_CONNECT_LIMIT))
    {
      continue;
    }

    cur_v_info.local_index = v_info.local_index;
    return false;
  }

  return true;
}

bool WMOGeometryBatcher::_needs_new_batch(MOBABatch* cur_batch
    , const MLoopTri* cur_tri
    , BatchType cur_batch_type
    , BatchType cur_poly_batch_type
    , std::uint16_t cur_batch_mat_id)
{
  return !cur_batch || cur_batch_type != cur_poly_batch_type
    || _material_ids[_mesh_materials_per_poly[cur_tri->poly]] != cur_batch_mat_id;
}

unsigned char WMOGeometryBatcher::_get_grayscale_factor(RGBA const& color)
{
  return (color.r + color.g + color.b) / 3;
}

BatchType WMOGeometryBatcher::get_batch_type(const MLoopTri* poly)
{
  if (!_bl_batch_map_trans.exists() && !_bl_batch_map_int.exists())
    return BatchType::EXT;

  unsigned trans_count = 0;
  unsigned int_count = 0;

  for (int i = 0; i < 3; ++i)
  {

    if (_bl_batch_map_trans.exists())
    {
      RGBA color = _bl_batch_map_trans[poly->tri[i]];

      if (comp_color_key(color))
      {
        trans_count++;
      }

    }

    if (_bl_batch_map_int.exists())
    {
      RGBA color = _bl_batch_map_int[poly->tri[i]];

      if (comp_color_key(color))
      {
        int_count++;
      }
    }
  }

  if (trans_count == 3)
  {
    return BatchType::TRANS;
  }
  else if (int_count == 3)
  {
    return BatchType::INT;
  }
  else
  {
    return BatchType::EXT;
  }
}

void WMOGeometryBatcher::_create_new_batch(std::uint16_t mat_id
                                          , BatchType batch_type
                                          , MOBABatch*& cur_batch
                                          , uint16_t& cur_batch_mat_id
                                          , BatchType& cur_batch_type)
{
  if (cur_batch)
  {
    cur_batch->max_index = _vertices.size() - 1;
  }

  // create new batch
  cur_batch = &_batches.emplace_back();
  cur_batch->start_index = _triangle_indices.size();
  cur_batch->indices_count = 0;
  cur_batch->min_index = _vertices.size();
  cur_batch->bb_box.min[0] = std::numeric_limits<std::int16_t>::max();
  cur_batch->bb_box.min[1] = std::numeric_limits<std::int16_t>::max();
  cur_batch->bb_box.min[2] = std::numeric_limits<std::int16_t>::max();
  cur_batch->bb_box.max[0] = std::numeric_limits<std::int16_t>::lowest();
  cur_batch->bb_box.max[1] = std::numeric_limits<std::int16_t>::lowest();
  cur_batch->bb_box.max[2] = std::numeric_limits<std::int16_t>::lowest();

  if (_use_large_material_id && mat_id > 255)
  {
    cur_batch->flags |= MOBAFlags::FLAG_USE_MATERIAL_ID_LARGE;
    cur_batch->material_id_large.id = mat_id;
    cur_batch->material_id = 0;
  }
  else
  {
    cur_batch->material_id = mat_id;
  }

  cur_batch_mat_id = mat_id;
  cur_batch_type = batch_type;
  _cur_batch_vertex_map.clear();

  switch (batch_type)
  {
    case BatchType::TRANS:
      _trans_batch_count++;
      break;
    case BatchType::INT:
      _int_batch_count++;
      break;
    case BatchType::EXT:
      _ext_batch_count++;
      break;
  }
}

bool WMOGeometryBatcher::_is_vertex_collidable(unsigned int vert_index)
{
  if (!_has_collision_vg)
    return false;

  return WBS_BKE_defvert_find_index(&_bl_vg_data[vert_index], _vg_collision_index);
}

void WMOGeometryBatcher::_create_new_render_triangle(const MLoopTri* tri, MOBABatch* cur_batch)
{
  MOPYTriangleMaterial& tri_mat = _triangle_materials.emplace_back();
  tri_mat.flags_int = 0;
  tri_mat.flags.F_RENDER = true;

  // overflow may occur here, and is intended. uint8_t overflow for values > 255 corresponds to the data
  // found in Blizzard files.
  tri_mat.material_id = cur_batch->material_id;


  unsigned collision_counter = 0;
  for (unsigned loop_index : tri->tri)
  {
    const MLoop* loop = &_bl_loops[loop_index];
    const MVert* vertex = &_bl_verts[loop->v];

    BatchVertexInfo v_info{};
    v_info.col = {0x7F, 0x7F, 0x7F, 0x00};
    v_info.col2 = {0, 0, 0, 0};
    v_info.uv = {0.0f, 0.0f};
    v_info.uv2 = {0.0f, 0.0f};

    _unpack_vertex(v_info, tri_mat, loop_index);

    // create new vertex if necessary
    if (WMOGeometryBatcher::_needs_new_vert(loop->v, v_info))
    {
      _create_new_vert(v_info, cur_batch, vertex, loop);
    }

    if (_is_vertex_collidable(loop->v))
    {
      collision_counter++;
    }

    _triangle_indices.emplace_back(v_info.local_index);
    cur_batch->indices_count++;
  }

  if (collision_counter != 3)
  {
    tri_mat.flags.F_DETAIL = true;
  }
}

void WMOGeometryBatcher::_calculate_bounding_for_vertex(glm::vec3 const& vertex)
{
  _bounding_box_min.x = std::min(_bounding_box_min.x, vertex[0]);
  _bounding_box_min.y = std::min(_bounding_box_min.y, vertex[1]);
  _bounding_box_min.z = std::min(_bounding_box_min.z, vertex[2]);

  _bounding_box_max.x = std::max(_bounding_box_max.x, vertex[0]);
  _bounding_box_max.y = std::max(_bounding_box_max.y, vertex[1]);
  _bounding_box_max.z = std::max(_bounding_box_max.z, vertex[2]);
}

namespace
{
  std::int16_t round_bb_float(float x)
  {
    std::int16_t sign = x < 0 ? -1 : 1;

    auto base = static_cast<std::int16_t>(std::ceil(std::fabs(x)));

    return sign * base;
  }
}

void WMOGeometryBatcher::_calculate_batch_bounding_for_vertex(MOBABatch* cur_batch, glm::vec3 const& vertex) const
{
  // batch bounding box is not needed for newer clients supporting large material ids
  if (_use_large_material_id)
    return;

  cur_batch->bb_box.min[0] = std::min(cur_batch->bb_box.min[0], round_bb_float(vertex[0]));
  cur_batch->bb_box.min[1] = std::min(cur_batch->bb_box.min[1], round_bb_float(vertex[1]));
  cur_batch->bb_box.min[2] = std::min(cur_batch->bb_box.min[2], round_bb_float(vertex[2]));

  cur_batch->bb_box.max[0] = std::max(cur_batch->bb_box.max[0], round_bb_float(vertex[0]));
  cur_batch->bb_box.max[1] = std::max(cur_batch->bb_box.max[1], round_bb_float(vertex[1]));
  cur_batch->bb_box.max[2] = std::max(cur_batch->bb_box.max[2], round_bb_float(vertex[2]));
}


BufferKey WMOGeometryBatcher::batches()
{
  return {reinterpret_cast<char*>(_batches.data()), _batches.size() * sizeof(MOBABatch)};
}

BufferKey WMOGeometryBatcher::normals()
{
  return {reinterpret_cast<char*>(_normals.data()), _normals.size() * sizeof(Vector3D)};
}

BufferKey WMOGeometryBatcher::vertices()
{
  return {reinterpret_cast<char*>(_vertices.data()), _vertices.size() * sizeof(Vector3D)};
}

BufferKey WMOGeometryBatcher::triangle_indices()
{
  return {reinterpret_cast<char*>(_triangle_indices.data()),
          _triangle_indices.size() * sizeof(std::uint16_t)};
}

BufferKey WMOGeometryBatcher::triangle_materials()
{
  return {reinterpret_cast<char*>(_triangle_materials.data()),
          _triangle_materials.size() * sizeof(MOPYTriangleMaterial)};
}

BufferKey WMOGeometryBatcher::tex_coords()
{
  return {reinterpret_cast<char*>(_tex_coords.data()), _tex_coords.size()  * sizeof(Vector2D)};
}

BufferKey WMOGeometryBatcher::tex_coords2()
{
  return {reinterpret_cast<char*>(_tex_coords2.data()), _tex_coords2.size() * sizeof(Vector2D)};
}

BufferKey WMOGeometryBatcher::vertex_colors()
{
  return {reinterpret_cast<char*>(_vertex_colors.data()), _vertex_colors.size() * sizeof(RGBA)};
}

BufferKey WMOGeometryBatcher::vertex_colors2()
{
  return {reinterpret_cast<char*>(_vertex_colors2.data()), _vertex_colors2.size() * sizeof(RGBA)};
}

BufferKey WMOGeometryBatcher::bsp_nodes()
{
  return {reinterpret_cast<char*>(_bsp_tree->nodes().data()), _bsp_tree->nodes().size() * sizeof(BSPNode)};
}

BufferKey WMOGeometryBatcher::bsp_faces()
{
  return {reinterpret_cast<char*>(_bsp_tree->faces().data()), _bsp_tree->faces().size() * sizeof(std::uint16_t)};
}

WMOGeometryBatcher::~WMOGeometryBatcher()
{
  delete _bsp_tree;
  delete _liquid_exporter;
}

BufferKey WMOGeometryBatcher::liquid_vertices()
{
  assert(_liquid_exporter && "Attempted accessing liquid data, but not liquid params were provided.");
  return {reinterpret_cast<char*>(_liquid_exporter->vertices().data()),
          _liquid_exporter->vertices().size() * sizeof(SMOLVert)};
}

BufferKey WMOGeometryBatcher::liquid_tiles()
{
  assert(_liquid_exporter && "Attempted accessing liquid data, but not liquid params were provided.");
  return {reinterpret_cast<char*>(_liquid_exporter->tiles().data()),
          _liquid_exporter->tiles().size() * sizeof(SMOLTile)};

}

BufferKey WMOGeometryBatcher::liquid_header()
{
  assert(_liquid_exporter && "Attempted accessing liquid data, but not liquid params were provided.");
  return {reinterpret_cast<char*>(&_liquid_exporter->header()), sizeof(MLIQHeader)};
}

VertexColorLayer::VertexColorLayer(const Mesh* mesh, std::string const& name)
: _mesh(mesh)
, _is_per_loop(false)
, _exists(false)
{
  int per_loop_index = WBS_CustomData_get_named_layer_index(&mesh->ldata, name.c_str());

  if (per_loop_index >= 0)
  {
    int type = WBS_CustomData_get_layer_type(&mesh->ldata, per_loop_index);

    if (type == CD_PROP_BYTE_COLOR)
    {
      _exists = true;
      _is_per_loop = true;
      _color_layer = static_cast<MLoopCol*>(mesh->ldata.layers[per_loop_index].data);
    }
    else if (type == CD_PROP_COLOR)
    {
      _is_per_loop = true;
      _exists = true;
      _color_layer = static_cast<MPropCol*>(mesh->ldata.layers[per_loop_index].data);
    }

    return;
  }

  int per_vert_index = WBS_CustomData_get_named_layer_index(&mesh->vdata, name.c_str());

  if (per_vert_index >= 0)
  {
    int type = WBS_CustomData_get_layer_type(&mesh->vdata, per_vert_index);

    if (type == CD_PROP_BYTE_COLOR)
    {
      _exists = true;
      _is_per_loop = false;
      _color_layer = static_cast<MLoopCol*>(mesh->vdata.layers[per_vert_index].data);
    }
    else if (type == CD_PROP_COLOR)
    {
      _is_per_loop = false;
      _exists = true;
      _color_layer = static_cast<MPropCol*>(mesh->vdata.layers[per_vert_index].data);
    }
  }

}

RGBA VertexColorLayer::operator[](std::size_t index) const
{
  assert(_exists && "Attempt accessing non existing non-existing layer.");

  if (!_is_per_loop)
  {
    index = _mesh->mloop[index].v;
  }

  if (std::holds_alternative<MLoopCol*>(_color_layer))
  {
    MLoopCol* col = &std::get<MLoopCol*>(_color_layer)[index];
    return RGBA{col->r, col->g, col->b, 0xFF};
  }
  else
  {
    MPropCol* col = &std::get<MPropCol*>(_color_layer)[index];
    return linear_to_SRGB({static_cast<unsigned char>(col->color[0] * 255.f)
                          , static_cast<unsigned char>(col->color[1] * 255.f)
                          , static_cast<unsigned char>(col->color[2] * 255.f)
                          , 0xFF});
  }
}
