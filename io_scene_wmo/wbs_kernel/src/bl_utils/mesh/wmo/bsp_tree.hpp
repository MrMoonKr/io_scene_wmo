#ifndef WBS_KERNEL_BSP_TREE_HPP
#define WBS_KERNEL_BSP_TREE_HPP

#include <bl_utils/math_utils.hpp>

#include <cstdint>
#include <vector>
#include <tuple>
#include <array>

namespace wbs_kernel::bl_utils::mesh::wmo
{
  enum BSPPlaneType
  {
    YZ_plane = 0,
    XZ_plane = 1,
    XY_plane = 2,
    Leaf = 4  // end node, contains polygons
  };

  struct BSPNode
  {
    std::int16_t plane_type;
    std::int16_t children[2];
    std::uint16_t num_faces;
    std::uint32_t first_face;
    float dist;
  };

  struct BoundingBox
  {
    math_utils::Vector3D min;
    math_utils::Vector3D max;
  };

  class BSPTree
  {
  public:
    BSPTree(std::vector<math_utils::Vector3D> const& vertices
            , std::vector<std::uint16_t> const& triangle_indices
            , BoundingBox const& bb_box
            , unsigned node_size);

    [[nodiscard]]
    std::vector<BSPNode>& nodes() { return _nodes; };

    [[nodiscard]]
    std::vector<std::uint16_t>& faces() { return _faces; };

  private:

    void _generate_bsp();
    std::int16_t _add_node(BoundingBox  const& box, std::vector<std::uint32_t> const& faces_in_box, int depth);

    // Return true if AABB and triangle overlap
    [[nodiscard]]
    static bool _collide_box_tri(BoundingBox const& box, std::array<math_utils::Vector3D, 3> const& tri);

    template<typename T>
    [[nodiscard]]
    static std::pair<math_utils::Vector3D, math_utils::Vector3D> _get_min_max(T const& vert_array);

    [[nodiscard]]
    static bool _proj_overlap(float poly1_min, float poly1_max, float poly2_min, float poly2_max);

    [[nodiscard]]
    static bool _check_overlaps(math_utils::Vector3D const& projected_box_min
                                , math_utils::Vector3D const& projected_box_max
                                , math_utils::Vector3D const& projected_triangle_min
                                , math_utils::Vector3D const& projected_triangle_max);

    [[nodiscard]]
    static math_utils::Vector3D _project_point(math_utils::Vector3D const& pt, math_utils::Vector3D const& v);

    [[nodiscard]]
    static bool _plane_box_overlap(math_utils::Vector3D const& normal
                                   , math_utils::Vector3D const& vert
                                   , BoundingBox const& box);

    // split box in two smaller ones, at dist calculated internally
    [[nodiscard]]
    std::tuple<float, BoundingBox, BoundingBox> _split_box(BoundingBox const& box, BSPPlaneType axis, const std::vector<std::uint32_t>& faces_in_box);

    std::vector<math_utils::Vector3D> const& _vertices;
    std::vector<std::uint16_t> const& _triangle_indices;
    BoundingBox const& _bb_box;
    unsigned _node_size;

    std::vector<BSPNode> _nodes;
    std::vector<std::uint16_t> _faces;
  };
}

#endif //WBS_KERNEL_BSP_TREE_HPP
