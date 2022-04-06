#ifndef WBS_KERNEL_MATH_UTILS_HPP
#define WBS_KERNEL_MATH_UTILS_HPP

#include <cmath>

extern "C"
{
  #include <BKE_mesh_mapping.h>
};

namespace wbs_kernel::bl_utils::math_utils
{
  struct Vector3D
  {
    float x;
    float y;
    float z;
  };

  struct Vector2D
  {
    float x;
    float y;
  };


  int compare_ff(float a, float b, float max_diff);

  bool compare_v2v2(Vector2D const& v1, Vector2D const& v2, float limit);

  bool compare_v3v3(Vector3D const& v1, Vector3D const& v2, float limit);
}

#endif //WBS_KERNEL_MATH_UTILS_HPP
