#include "math_utils.hpp"

int wbs_kernel::bl_utils::math_utils::compare_ff(float a, float b, const float max_diff)
{
  return std::fabs(a - b) <= max_diff;
}

bool wbs_kernel::bl_utils::math_utils::compare_v2v2(Vector2D const& v1, Vector2D const& v2, const float limit)
{
  return (wbs_kernel::bl_utils::math_utils::compare_ff(v1.x, v2.x, limit)
    && wbs_kernel::bl_utils::math_utils::compare_ff(v1.y, v2.y, limit));
}

bool wbs_kernel::bl_utils::math_utils::compare_v3v3(Vector3D const& v1, Vector3D const& v2, const float limit)
{
  return (wbs_kernel::bl_utils::math_utils::compare_ff(v1.x, v2.x, limit)
    && wbs_kernel::bl_utils::math_utils::compare_ff(v1.y, v2.y, limit)
    && wbs_kernel::bl_utils::math_utils::compare_ff(v1.z, v2.z, limit));
}