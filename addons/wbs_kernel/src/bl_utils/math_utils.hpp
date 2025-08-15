#ifndef WBS_KERNEL_MATH_UTILS_HPP
#define WBS_KERNEL_MATH_UTILS_HPP

#include <cmath>
#include <cassert>
#include <extern/glm/mat4x4.hpp>
#include <extern/glm/vec3.hpp>
#include <extern/glm/vec4.hpp>

#include <DNA_meshdata_types.h>
#include <BLI_vector.hh>
#include <BKE_mesh_mapping.h>

namespace wbs_kernel::bl_utils::math_utils
{
  struct Vector2Di
  {
    std::int32_t x;
    std::int32_t y;
  };

  struct Vector3D
  {
    float x;
    float y;
    float z;

    float& operator[](unsigned index)
    {
      assert(index <= 2);

      switch(index)
      {
        case 0:
          return x;
        case 1:
          return y;
        case 2:
          return z;
        default:
          assert(false);
      }
    }

    float operator[](unsigned index) const
    {
      assert(index <= 2);

      switch(index)
      {
        case 0:
          return x;
        case 1:
          return y;
        case 2:
          return z;
        default:
          assert(false);
      }
    }

    Vector3D operator-(Vector3D const& v) const
    {
      return Vector3D{
          x - v.x,
          y - v.y,
          z - v.z};
    }

    Vector3D operator*(Vector3D const& v) const
    {
      return Vector3D{
          x * v.x,
          y * v.y,
          z * v.z};
    }

    [[nodiscard]]
    Vector3D cross(Vector3D const& v) const
    {
      return Vector3D{y * v.z - z * v.y,
                      z * v.x - x * v.z,
                      x * v.y - y * v.x};
    }

    [[nodiscard]]
    float dot(Vector3D const& v) const
    {
      return x * v.x + y * v.y + z * v.z;
    }
  };

  struct Vector2D
  {
    float x;
    float y;

    float& operator[](unsigned index)
    {
      assert(index <= 1);

      switch(index)
      {
        case 0:
          return x;
        case 1:
          return y;
        default:
          assert(false);
      }
    }

    float operator[](unsigned index) const
    {
      assert(index <= 1);

      switch(index)
      {
        case 0:
          return x;
        case 1:
          return y;
        default:
          assert(false);
      }
    }
  };


  int compare_ff(float a, float b, float max_diff);

  bool compare_v2v2(Vector2D const& v1, Vector2D const& v2, float limit);

  bool compare_v3v3(Vector3D const& v1, Vector3D const& v2, float limit);
}

#endif //WBS_KERNEL_MATH_UTILS_HPP
