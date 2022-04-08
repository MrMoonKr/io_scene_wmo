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

  _add_node(_bb_box, faces);
}

std::int16_t BSPTree::_add_node(const BoundingBox& box, const std::vector<std::uint32_t>& faces_in_box)
{
  std::int16_t i_node = _nodes.size();

  BSPNode& node = _nodes.emplace_back();

  // part contain less than 30 polygons, lets end this, add final node
  if (faces_in_box.size() <= _node_size)
  {
    node.plane_type = BSPPlaneType::Leaf;
    node.children[0] = -1;
    node.children[1] = -1;
    node.num_faces = faces_in_box.size();
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

  auto [split_dist, child1_box, child2_box] = BSPTree::_split_box(box, plane_type);


  // caculate faces in child1 box
  std::vector<std::uint32_t> child1_faces;
  for (auto f : faces_in_box)
  {
    std::array<Vector3D, 3> tri = {_vertices[_triangle_indices[f * 3]]
                                  , _vertices[_triangle_indices[f * 3 + 1]]
                                  , _vertices[_triangle_indices[f * 3 + 2]]};

    if (BSPTree::_collide_box_tri(child1_box, tri))
      child1_faces.emplace_back(f);
  }

  // calculate faces in child2 box
  std::vector<std::uint32_t> child2_faces;
  for (auto f : faces_in_box)
  {
    std::array<Vector3D, 3> tri = {_vertices[_triangle_indices[f * 3]]
        , _vertices[_triangle_indices[f * 3 + 1]]
        , _vertices[_triangle_indices[f * 3 + 2]]};

    if (BSPTree::_collide_box_tri(child2_box, tri))
      child2_faces.emplace_back(f);
  }

  std::int16_t i_child1;
  std::int16_t i_child2;
  // don't add child if there is no faces inside

  if (child1_faces.empty())
    i_child1 = -1;
  else
    i_child1 = _add_node(child1_box, child1_faces);

  if (child2_faces.empty())
    i_child2 = -1;
  else
    i_child2 = _add_node(child2_box, child2_faces);

  auto& this_node = _nodes[i_node]; // needed here because of reference invalidation
  this_node.plane_type = plane_type;
  this_node.children[0] = i_child1;
  this_node.children[1] = i_child2;
  this_node.num_faces = 0;
  this_node.first_face = 0;
  this_node.dist = split_dist;

  return i_node;
}

std::tuple<float, BoundingBox, BoundingBox> BSPTree::_split_box(BoundingBox const& box, BSPPlaneType axis)
{
  /*
        # compute average of vertice positions
        """count = 0
        sum = 0
        for iFace in range(len(facesInBox)):
            sum += vertices[indices[facesInBox[iFace] * 3]][axis]
            sum += vertices[indices[facesInBox[iFace] * 3 + 1]][axis]
            sum += vertices[indices[facesInBox[iFace] * 3 + 2]][axis]
            count += 1
        splitDist = sum / count

        # if split is out of box, just split in half
        if(splitDist <= box[0][axis] or splitDist >= box[1][axis]):"""
   */

  assert(axis != BSPPlaneType::Leaf);
  float split_dist = (box.min[axis] + box.max[axis]) / 2;

  BoundingBox new_box1 = box;
  new_box1.max[axis] = split_dist;

  BoundingBox new_box2 = box;
  new_box2.min[axis] = split_dist;

  //split dist absolute coordinate on split axis
  //ret_splitDist = splitDist - ((box[0][axis] + box[1][axis]) / 2)

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
  Vector3D min = {std::numeric_limits<float>::max(),
                  std::numeric_limits<float>::max(),
                  std::numeric_limits<float>::max()};

  Vector3D max = {std::numeric_limits<float>::lowest(),
                  std::numeric_limits<float>::lowest(),
                  std::numeric_limits<float>::lowest()};


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
  if (v.y == 0)
    l = 0;
  else
  {
    l = - pt.y / v.y;
    proj.z = pt.x + l * v.x;
  }

  //project on Y
  if (v.z == 0)
    l = 0;
  else
  {
    l = - pt.z / v.z;
    proj.y = pt.x + l * v.x;
  }

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
