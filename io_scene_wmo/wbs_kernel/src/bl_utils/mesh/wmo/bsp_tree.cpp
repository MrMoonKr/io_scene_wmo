#include "bsp_tree.hpp"

#include <cassert>

using namespace wbs_kernel::bl_utils::mesh::wmo;
using namespace wbs_kernel::bl_utils::math_utils;

BSPTree::BSPTree(std::vector<math_utils::Vector3D> const& vertices
                 , std::vector<std::uint16_t> const& triangle_indices
                 , BoundingBox const& bb_box
                 , unsigned int node_size)
: _vertices(vertices)
, _triangle_indices(triangle_indices)
, _bb_box(bb_box)
, _node_size(node_size)
{
  _generate_bsp();
}

void BSPTree::_generate_bsp()
{
  std::vector<std::uint32_t> faces;
  assert(!(_triangle_indices.size() % 3) && "Bad mesh format for BSP.");
  faces.resize(_triangle_indices.size() / 3);

  for (std::size_t i = 0; i < _triangle_indices.size() / 3; ++i)
  {
    faces[i] = i;
  }

  _add_node(_bb_box, faces, 0);
}

std::int16_t BSPTree::_add_node(const BoundingBox& box, const std::vector<std::uint32_t>& faces_in_box, int depth)
{
  // Max depth for safety, blizz WMOs rarely seem to go beyond depth 9. We're doing something really wrong if we reach that
  const int MAX_DEPTH = 16;
  const int MIN_FACES = _node_size / 2;
  constexpr float MIN_SPLIT_RATIO = 0.2f;
  constexpr float MAX_DUPLICATION_RATIO = 1.3f;

  std::int16_t i_node = _nodes.size();

  BSPNode& node = _nodes.emplace_back();

  uint32_t total_size  = faces_in_box.size();

  // part contain less than 30 polygons, lets end this, add final node
  if (depth > MAX_DEPTH || total_size <= _node_size)
  {
    node.plane_type = BSPPlaneType::Leaf;
    node.children[0] = -1;
    node.children[1] = -1;
    node.num_faces = total_size;
    node.first_face = _faces.size();
    node.dist = 0.f;

    _faces.reserve(_faces.size() + distance(faces_in_box.begin(), faces_in_box.end()));
    _faces.insert(_faces.end(), faces_in_box.begin(), faces_in_box.end());
    return i_node;
  }

  // split bigger side
  float box_size_x =  box.max.x - box.min.x;
  float box_size_y =  box.max.y - box.min.y;
  float box_size_z =  box.max.z - box.min.z;

  BSPPlaneType plane_type;

  if (box_size_x > box_size_y && box_size_x > box_size_z)
  {
    // split on axis X (YZ plane)
    plane_type = BSPPlaneType::YZ_plane;
  }
  else if ( box_size_y > box_size_x && box_size_y > box_size_z)
  {
    // split on axis Y (XZ plane)
    plane_type = BSPPlaneType::XZ_plane;
  }
  else
  {
    // split on axis Z (XY plane)
    plane_type = BSPPlaneType::XY_plane;
  }

  auto [split_dist, child1_box, child2_box] = BSPTree::_split_box(box, plane_type, faces_in_box);


  // caculate faces in child1 box
  std::vector<std::uint32_t> child1_faces, child2_faces;
  for (auto f : faces_in_box)
  {
      std::array<Vector3D, 3> tri = {
          _vertices[_triangle_indices[f * 3]],
          _vertices[_triangle_indices[f * 3 + 1]],
          _vertices[_triangle_indices[f * 3 + 2]]
      };
      if (_collide_box_tri(child1_box, tri))
        child1_faces.push_back(f);
      if (_collide_box_tri(child2_box, tri))
        child2_faces.push_back(f);
  }

  uint32_t child1_size = child1_faces.size();
  uint32_t child2_size = child2_faces.size();

  float duplication_ratio = (float)(child1_size + child2_size) / total_size;
  float ratio = float(std::min(child1_size, child2_size)) / float(total_size); // distribution ratio between the two children
  // allow up to 20% duplicated faces
  if ( (duplication_ratio > MAX_DUPLICATION_RATIO /*&& total_size <= (_node_size * 2)*/) // detect ineffective splits, if size didn't reduce, it will recurse endlessly. Mostly caused by duplicate faces
      || child1_size < MIN_FACES || child2_size < MIN_FACES // hard minimum requirement to avoid tiny leaves.
      || (ratio < MIN_SPLIT_RATIO && total_size <= (_node_size * 1.5f)) // soft balance requirement to avoid very lopsided splits
     ) // the 1.5 and 2.0 _node_size checks are too make sure we don't return too early on too large nodes
  {
      // fallback to leaf
      node.plane_type = BSPPlaneType::Leaf;
      node.children[0] = -1;
      node.children[1] = -1;
      node.num_faces = total_size;
      node.first_face = _faces.size();
      node.dist = 0.f;
  
      _faces.reserve(_faces.size() + total_size);
      _faces.insert(_faces.end(), faces_in_box.begin(), faces_in_box.end());
      return i_node;
  }

  // don't add child if there is no faces inside
  std::int16_t i_child1 = child1_faces.empty() ? -1 : _add_node(child1_box, std::move(child1_faces), depth + 1);
  std::int16_t i_child2 = child2_faces.empty() ? -1 : _add_node(child2_box, std::move(child2_faces), depth + 1);

  auto& this_node = _nodes[i_node]; // needed here because of reference invalidation
  this_node.plane_type = plane_type;
  this_node.children[0] = i_child1;
  this_node.children[1] = i_child2;
  this_node.num_faces = 0;
  this_node.first_face = 0;
  this_node.dist = split_dist;

  return i_node;
}

std::tuple<float, BoundingBox, BoundingBox> BSPTree::_split_box(BoundingBox const& box, BSPPlaneType axis, const std::vector<std::uint32_t>& faces_in_box)
{
  assert(axis != BSPPlaneType::Leaf);

  float split_dist = 0.0f;

  // get average pos
  /*
  int count = 0;
  float sum = 0.0f;
  for (uint32_t f : faces_in_box)
  {
    sum += _vertices[_triangle_indices[f * 3]][axis];
    sum += _vertices[_triangle_indices[f * 3 + 1]][axis];
    sum += _vertices[_triangle_indices[f * 3 + 2]][axis];
    count ++;
  }
  float split_dist = sum / count;

*/

  // get median position
  std::vector<float> positions;
  for (uint32_t f : faces_in_box)
  {
      const auto& v0 = _vertices[_triangle_indices[f * 3]];
      const auto& v1 = _vertices[_triangle_indices[f * 3 + 1]];
      const auto& v2 = _vertices[_triangle_indices[f * 3 + 2]];

      positions.push_back(v0[axis]);
      positions.push_back(v1[axis]);
      positions.push_back(v2[axis]);
  }
  // Sort the positions along the axis to find the median
  std::sort(positions.begin(), positions.end());
  // Calculate the median
  split_dist = positions[positions.size() / 2];
  /////

  // if split is out of box, just use center
  if (split_dist <= box.min[axis] || split_dist >= box.max[axis] || split_dist == 0.0f)
  {
    // center of Bounding box
    split_dist = (box.min[axis] + box.max[axis]) / 2;
  }

  BoundingBox new_box1 = box;
  new_box1.max[axis] = split_dist;

  BoundingBox new_box2 = box;
  new_box2.min[axis] = split_dist;

  //split dist absolute coordinate on split axis
  // auto ret_splitDist = split_dist - ((box.min[axis] + box.max[axis]) / 2);

  return {split_dist, new_box1, new_box2};
}

bool BSPTree::_collide_box_tri(const BoundingBox& box, const std::array<math_utils::Vector3D, 3>& tri)
{
  auto [triangle_min, triangle_max] = BSPTree::_get_min_max(tri);

  // check if overlap on box axis
  if (!BSPTree::_proj_overlap(box.min.x, box.max.x, triangle_min.x, triangle_max.x)
    || !BSPTree::_proj_overlap(box.min.y, box.max.y, triangle_min.y, triangle_max.y)
    || !BSPTree::_proj_overlap(box.min.z, box.max.z, triangle_min.z, triangle_max.z))
  {
    return false;
  }

  std::vector<Vector3D> pt_box = {
      box.min,
      Vector3D{box.min.x, box.max.y, box.min.z},
      Vector3D{box.max.x, box.max.y, box.min.z},
      Vector3D{box.max.x, box.min.y, box.min.z},
      box.max,
      Vector3D{box.min.x, box.max.y, box.max.z},
      Vector3D{box.max.x, box.max.y, box.max.z},
      Vector3D{box.max.x, box.min.y, box.max.z}
  };

  // project on edge 1 axis
  Vector3D E0 = tri[1] - tri[0];

  std::vector<Vector3D> pt_box_projected;
  std::vector<Vector3D> pt_triangle_projected;

  for (auto& pt : pt_box)
  {
    pt_box_projected.emplace_back(BSPTree::_project_point(pt, E0));
  }

  for (auto& pt : tri)
  {
    pt_triangle_projected.emplace_back(BSPTree::_project_point(pt, E0));
  }

  auto [E0_pt_box_min, E0_pt_box_max] = BSPTree::_get_min_max(pt_box_projected);
  auto [E0_pt_tri_min, E0_pt_tri_max] = BSPTree::_get_min_max(pt_triangle_projected);
  if (BSPTree::_check_overlaps(E0_pt_box_min, E0_pt_box_max
                               , E0_pt_tri_min, E0_pt_tri_max))
    return false;

  // project on edge 2 axis
  Vector3D E1 = tri[2] - tri[1];
  pt_box_projected.clear();
  pt_triangle_projected.clear();

  for (auto& pt : pt_box)
  {
    pt_box_projected.emplace_back(BSPTree::_project_point(pt, E1));
  }

  for (auto& pt : tri)
  {
    pt_triangle_projected.emplace_back(BSPTree::_project_point(pt, E1));
  }

  auto [E1_pt_box_min, E1_pt_box_max] = BSPTree::_get_min_max(pt_box_projected);
  auto [E1_pt_tri_min, E1_pt_tri_max] = BSPTree::_get_min_max(pt_triangle_projected);
  if (BSPTree::_check_overlaps(E1_pt_box_min, E1_pt_box_max
      , E1_pt_tri_min, E1_pt_tri_max))
    return false;

  // project on edge 3 axis
  Vector3D E2 = tri[0] - tri[2];
  pt_box_projected.clear();
  pt_triangle_projected.clear();

  for (auto& pt : pt_box)
  {
    pt_box_projected.emplace_back(BSPTree::_project_point(pt, E2));
  }

  for (auto& pt : tri)
  {
    pt_triangle_projected.emplace_back(BSPTree::_project_point(pt, E2));
  }

  auto [E2_pt_box_min, E2_pt_box_max] = BSPTree::_get_min_max(pt_box_projected);
  auto [E2_pt_tri_min, E2_pt_tri_max] = BSPTree::_get_min_max(pt_triangle_projected);
  if (BSPTree::_check_overlaps(E2_pt_box_min, E2_pt_box_max
      , E2_pt_tri_min, E2_pt_tri_max)
      || !BSPTree::_plane_box_overlap(E0.cross(E1), tri[0], box))
    return false;

  return true;
}

template<typename T>
std::pair<Vector3D, Vector3D> BSPTree::_get_min_max(T const& vert_array)
{
  Vector3D min = vert_array[0];
  Vector3D max = vert_array[0];


  for (auto& v : vert_array)
  {
    if (v.x < min.x)
      min.x = v.x;
    else if (v.x > max.x)
      max.x = v.x;

    if (v.y < min.y)
      min.y = v.y;
    else if (v.y > max.y)
      max.y = v.y;

    if (v.z < min.z)
      min.z = v.z;
    else if (v.z > max.z)
      max.z = v.z;
  }

  return {min, max};
}

bool BSPTree::_proj_overlap(float poly1_min, float poly1_max, float poly2_min, float poly2_max)
{
  return !(poly1_max < poly2_min || poly2_max < poly1_min);
}

bool BSPTree::_check_overlaps(Vector3D const& projected_box_min, Vector3D const& projected_box_max,
                               Vector3D const& projected_triangle_min, Vector3D const& projected_triangle_max)
{
  return (!BSPTree::_proj_overlap(projected_box_min.x,
                              projected_box_max.x,
                              projected_triangle_min.x,
                              projected_triangle_max.x)
    || !BSPTree::_proj_overlap(projected_box_min.y,
                               projected_box_max.y,
                               projected_triangle_min.y,
                               projected_triangle_max.y)
    || !BSPTree::_proj_overlap(projected_box_min.z,
                               projected_box_max.z,
                               projected_triangle_min.z,
                               projected_triangle_max.z));
}

Vector3D BSPTree::_project_point(Vector3D const& pt, Vector3D const & v)
{
  Vector3D proj{};
  float l;

  // project on X
  if (math_utils::compare_ff(v.y, 0.f, STD_UV_CONNECT_LIMIT))
    l = 0;
  else
  {
    l = -pt.y / v.y;
  }
  proj.z = pt.x + l * v.x;

  //project on Y
  if (math_utils::compare_ff(v.z, 0.f, STD_UV_CONNECT_LIMIT))
    l = 0;
  else
  {
    l = -pt.z / v.z;
  }

  proj.y = pt.x + l * v.x;
  // project on Z
  proj.x = pt.y + l * v.y;

  return proj;
}

bool BSPTree::_plane_box_overlap(Vector3D const& normal, Vector3D const& vert, BoundingBox const& box)
{
  //Vector3D v_min;
  Vector3D v_max{};

  for (int i = 0; i < 3; ++i)
  {
    float v = vert[i];

    if (normal[i] > 0.f)
    {
      //v_min[i] = box.min[i] - v;
      v_max[i] = box.max[i] - v;
    }
    else
    {
      //v_min[i] = box.max[i] - v;
      v_max[i]= box.min[i] - v;
    }
  }

  return normal.dot(v_max) >= 0.f;
}
