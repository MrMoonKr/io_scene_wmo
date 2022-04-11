#include "batch_geometry.hpp"
#include <bl_utils/mesh/custom_data.hpp>
#include <bl_utils/mesh/wmo/bsp_tree.hpp>

#include <cassert>
#include <algorithm>
#include <limits>

extern "C"
{
  #include <DNA_mesh_types.h>
  #include <DNA_meshdata_types.h>
  #include <DNA_material_types.h>
  #include <DNA_ID.h>
  #include <BKE_customdata.h>
}

using namespace wbs_kernel::bl_utils::math_utils;
using namespace wbs_kernel::bl_utils::mesh::wmo;
using namespace wbs_kernel::bl_utils::mesh;


WMOGeometryBatcher::WMOGeometryBatcher(std::uintptr_t mesh_ptr
  , bool use_large_material_id
  , bool use_vertex_color
  , int vg_collision_index
  , unsigned node_size
  , std::vector<int> const& material_mapping

)
: _mesh(reinterpret_cast<Mesh*>(mesh_ptr))
, _bsp_tree(nullptr)
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
, _bl_loops(reinterpret_cast<const MLoop*>(_mesh->mloop))
, _bl_verts(reinterpret_cast<const MVert*>(_mesh->mvert))
, _bl_polygons(reinterpret_cast<const MPoly*>(_mesh->mpoly))
, _bl_vertex_normals(reinterpret_cast<const float(*)[3]>(_mesh->runtime.vert_normals))
, _has_collision_vg(_vg_collision_index >= 0)
, _bl_batch_map_trans(get_custom_data_layer_named<MLoopCol>(&_mesh->ldata, "BatchmapTrans"))
, _bl_batch_map_int(get_custom_data_layer_named<MLoopCol>(&_mesh->ldata, "BatchmapInt"))
, _bl_lightmap(get_custom_data_layer_named<MLoopCol>(&_mesh->ldata, "Lightmap"))
, _bl_blendmap(get_custom_data_layer_named<MLoopCol>(&_mesh->ldata, "Blendmap"))
, _bl_vertex_color(get_custom_data_layer_named<MLoopCol>(&_mesh->ldata, "Col"))
, _bl_uv(get_custom_data_layer_named<MLoopUV>(&_mesh->ldata, "UVMap"))
, _bl_uv2(get_custom_data_layer_named<MLoopUV>(&_mesh->ldata, "UVMap.001"))
, _last_error(WMOGeometryBatcherError::NO_ERROR)
, _material_ids(material_mapping)
{
  assert(!_mesh->runtime.vert_normals_dirty && "Vertex normals were not calculated.");
  assert(!_mesh->runtime.poly_normals_dirty && "Poly normals were not calculated.");

  if (_has_collision_vg)
  {
    _bl_vg_data = static_cast<MDeformVert*>(WBS_CustomData_get_layer(&_mesh->vdata,
                                                                     CustomDataType::CD_MDEFORMVERT));

    if (!_bl_vg_data)
    {
      _has_collision_vg = false;
    }
  }

  std::vector<std::pair<const MPoly*, BatchType>> polys_per_mat;
  polys_per_mat.resize(_mesh->totpoly);

  for (int i = 0; i < _mesh->totpoly; ++i)
  {
    polys_per_mat[i] = std::make_pair(&_bl_polygons[i], WMOGeometryBatcher::get_batch_type(&_bl_polygons[i]
                                                                                           , _bl_batch_map_trans
                                                                                           , _bl_batch_map_int));
  }


  // presort faces by their batch type and material_id forming the batches
  std::sort(polys_per_mat.begin(), polys_per_mat.end(),
      [](std::pair<const MPoly*, BatchType> const& lhs, std::pair<const MPoly*, BatchType> const& rhs) -> bool
      {
        return std::tie(lhs.second, lhs.first->mat_nr) < std::tie(rhs.second, rhs.first->mat_nr);
      });

  MOBABatch* cur_batch = nullptr;
  std::uint16_t cur_batch_mat_id = 0;
  BatchType cur_batch_type = BatchType::TRANS;

  for (auto [poly, batch_type] : polys_per_mat)
  {
    // handle collision-only geometry later, collisions non-batched geometry comes last.
    // stop iterating the list when collision is encountered, not more real batches should follow.
    if (poly->mat_nr == COLLISION_MAT_NR)
      continue;

    if (WMOGeometryBatcher::_needs_new_batch(cur_batch, poly, cur_batch_type,
                                             batch_type, cur_batch_mat_id))
    {
      _create_new_batch(_material_ids[poly->mat_nr], batch_type, cur_batch, cur_batch_mat_id, cur_batch_type);
    }

    _create_new_render_triangle(poly, cur_batch);
  }

  // handle collision only faces
  for (auto [poly, batch_type] : polys_per_mat)
  {
    if (poly->mat_nr != COLLISION_MAT_NR)
      continue;

    _create_new_collision_triangle(poly);
  }

  // calculate BSP tree
  BoundingBox bb_box{_bounding_box_min, _bounding_box_max};
  _bsp_tree = new BSPTree{_vertices, _triangle_indices, bb_box, node_size};
}

void WMOGeometryBatcher::_create_new_collision_triangle(const MPoly* poly)
{
  assert(poly->mat_nr == COLLISION_MAT_NR);

  MOPYTriangleMaterial& tri_mat = _triangle_materials.emplace_back();
  tri_mat.flags_int = 0;
  tri_mat.flags.F_COLLISION = true;
  tri_mat.material_id = 0xFF;

  for (int j = 0; j < poly->totloop; ++j)
  {
    const MLoop* loop = &_bl_loops[poly->loopstart + j];
    const MVert* vert = &_bl_verts[loop->v];

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
  if (_use_vertex_color && _bl_vertex_color)
  {
    const MLoopCol* color = &_bl_vertex_color[loop_index];
    v_info.col.r = color->b;
    v_info.col.g = color->g;
    v_info.col.b = color->r;

    if (_bl_lightmap)
    {
      unsigned char attenuation = _get_grayscale_factor(&_bl_lightmap[loop_index]);

      // TODO: verify what this actually does and if needed
      if (attenuation > 0)
      {
        tri_mat.flags.F_UNK_0x01 = true;
      }

      v_info.col.a = attenuation;
    }

  }

  if (_bl_blendmap)
  {
    const MLoopCol* color = &_bl_blendmap[loop_index];
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
}

void WMOGeometryBatcher::_create_new_collision_vert(const MVert* vertex
                                                   , const MLoop* loop)
{
  unsigned v_local_index = _vertices.size();
  _vertices.emplace_back(Vector3D{vertex->co[0], vertex->co[1], vertex->co[2]});
  _normals.emplace_back(Vector3D{_bl_vertex_normals[loop->v][0], _bl_vertex_normals[loop->v][1],
                                 _bl_vertex_normals[loop->v][2]});
  _tex_coords.emplace_back(Vector2D{0.f, 0.f});

  if (_bl_uv2)
  {
    _tex_coords2.emplace_back(Vector2D{0.f, 0.f});
  }

  if (_use_vertex_color)
  {
    _vertex_colors.emplace_back(RGBA{0x7F, 0x7F, 0x7F, 0x0});
  }

  if (_bl_blendmap)
  {
    _vertex_colors2.emplace_back(RGBA{0x0, 0x0, 0x0, 0x0});
  }

  _triangle_indices.emplace_back(v_local_index);
  _collision_vertex_map[loop->v] = v_local_index;

  _calculate_bounding_for_vertex(vertex);
}

void WMOGeometryBatcher::_create_new_vert(BatchVertexInfo& v_info
                                         , MOBABatch* cur_batch
                                         , const MVert* vertex
                                         , const MLoop* loop)
{
  v_info.local_index = _vertices.size();
  _vertices.emplace_back(Vector3D{vertex->co[0], vertex->co[1], vertex->co[2]});
  _normals.emplace_back(Vector3D{_bl_vertex_normals[loop->v][0], _bl_vertex_normals[loop->v][1],
                                 _bl_vertex_normals[loop->v][2]});
  _tex_coords.emplace_back(v_info.uv);

  if (_bl_uv2)
    _tex_coords2.emplace_back(v_info.uv2);

  if (_use_vertex_color)
  {
    _vertex_colors.emplace_back(v_info.col);
  }

  if (_bl_blendmap)
  {
    _vertex_colors2.emplace_back(v_info.col2);
  }

  _cur_batch_vertex_map[loop->v].emplace_back(v_info);

  _calculate_bounding_for_vertex(vertex);
  _calculate_batch_bounding_for_vertex(cur_batch, vertex);
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
      || !_compare_colors(v_info.col, cur_v_info.col)
      || !_compare_colors(v_info.col2, cur_v_info.col2))
    {
      continue;
    }

    cur_v_info.local_index = v_info.local_index;
    return false;
  }

  return true;
}

bool WMOGeometryBatcher::_compare_colors(RGBA const& v1, RGBA const& v2)
{
  return v1.r == v2.r && v1.g == v2.g && v1.b == v2.b && v1.a == v2.a;
}

bool WMOGeometryBatcher::_needs_new_batch(MOBABatch* cur_batch
    , const MPoly* cur_poly
    , BatchType cur_batch_type
    , BatchType cur_poly_batch_type
    , std::uint16_t cur_batch_mat_id)
{
  return !cur_batch || cur_batch_type != cur_poly_batch_type || _material_ids[cur_poly->mat_nr] != cur_batch_mat_id;
}

bool WMOGeometryBatcher::comp_color_key(RGBA const& color)
{
  return color.r || color.b || color.g || color.a;
}

unsigned char WMOGeometryBatcher::_get_grayscale_factor(const MLoopCol* color)
{
  return (color->r + color->g + color->b) / 3;
}

BatchType WMOGeometryBatcher::get_batch_type(const MPoly* poly
    , const MLoopCol* batch_map_trans
    , const MLoopCol* batch_map_int)
{
  if (!batch_map_trans && !batch_map_int)
    return BatchType::EXT;

  unsigned trans_count = 0;
  unsigned int_count = 0;

  unsigned n_loops = poly->totloop;
  assert(n_loops == 3 && "Mesh was not triangulated.");

  for (int i = 0; i < n_loops; ++i)
  {

    if (batch_map_trans)
    {
      const MLoopCol* loop_col = &batch_map_trans[poly->loopstart + i];
      RGBA color = {loop_col->r, loop_col->g, loop_col->b, loop_col->a};

      if (WMOGeometryBatcher::comp_color_key(color))
      {
        trans_count++;
      }

    }

    if (batch_map_int)
    {
      const MLoopCol* loop_col = &batch_map_int[poly->loopstart + i];
      RGBA color = {loop_col->r, loop_col->g, loop_col->b, loop_col->a};

      if (WMOGeometryBatcher::comp_color_key(color))
      {
        int_count++;
      }
    }
  }

  if (trans_count == n_loops)
  {
    return BatchType::TRANS;
  }
  else if (int_count == n_loops)
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

void WMOGeometryBatcher::_create_new_render_triangle(const MPoly* poly, MOBABatch* cur_batch)
{
  MOPYTriangleMaterial& tri_mat = _triangle_materials.emplace_back();
  tri_mat.flags_int = 0;
  tri_mat.flags.F_RENDER = true;

  // overflow may occur here, and is intended. uint8_t overflow for values > 255 corresponds to the data
  // found in Blizzard files.
  tri_mat.material_id = cur_batch->material_id;


  assert(poly->totloop == 3 && "Mesh was not triangulated");

  unsigned collision_counter = 0;
  for (int i = 0; i < poly->totloop; ++i)
  {
    int loop_index = poly->loopstart + i;
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

void WMOGeometryBatcher::_calculate_bounding_for_vertex(const MVert* vertex)
{
  _bounding_box_min.x = std::min(_bounding_box_min.x, vertex->co[0]);
  _bounding_box_min.y = std::min(_bounding_box_min.y, vertex->co[1]);
  _bounding_box_min.z = std::min(_bounding_box_min.z, vertex->co[2]);

  _bounding_box_max.x = std::max(_bounding_box_max.x, vertex->co[0]);
  _bounding_box_max.y = std::max(_bounding_box_max.y, vertex->co[1]);
  _bounding_box_max.z = std::max(_bounding_box_max.z, vertex->co[2]);
}

void WMOGeometryBatcher::_calculate_batch_bounding_for_vertex(MOBABatch* cur_batch, const MVert* vertex) const
{
  // batch bounding box is not needed for newer clients supporting large material ids
  if (_use_large_material_id)
    return;

  cur_batch->bb_box.min[0] = std::min(cur_batch->bb_box.min[0], static_cast<std::int16_t>(vertex->co[0]));
  cur_batch->bb_box.min[1] = std::min(cur_batch->bb_box.min[1], static_cast<std::int16_t>(vertex->co[1]));
  cur_batch->bb_box.min[2] = std::min(cur_batch->bb_box.min[2], static_cast<std::int16_t>(vertex->co[2]));

  cur_batch->bb_box.max[0] = std::max(cur_batch->bb_box.max[0], static_cast<std::int16_t>(vertex->co[0]));
  cur_batch->bb_box.max[1] = std::max(cur_batch->bb_box.max[1], static_cast<std::int16_t>(vertex->co[1]));
  cur_batch->bb_box.max[2] = std::max(cur_batch->bb_box.max[2], static_cast<std::int16_t>(vertex->co[2]));
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
}

