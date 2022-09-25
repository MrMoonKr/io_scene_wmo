#include "color_utils.hpp"
#include <cmath>

namespace wbs_kernel::bl_utils::color_utils
{
  RGBA SRGB_to_linear(RGBA const& color)
  {
    RGBA new_color{};

    for (int i = 0; i < 4; ++i)
    {
      float c = color[i] / 255.0f;

      if (c < 0.04045f)
        new_color[i] = static_cast<unsigned char>(((c < 0.0f)? 0.0f: c * (1.0f / 12.92f)) * 255.f);
      else
        new_color[i] = static_cast<unsigned char>(std::pow((c + 0.055f)*(1.0f/1.055f), 2.4f) * 255.f);
    }

    return new_color;
  }

  RGBA linear_to_SRGB(const RGBA& color)
  {
    RGBA new_color{};

    for (int i = 0; i < 4; ++i)
    {
      float c = color[i] / 255.0f;

      if (c <= 0.0031308f)
        new_color[i] = static_cast<unsigned char>(12.92f * c * 255.f);
      else
        new_color[i] = static_cast<unsigned char>((((1.f + 0.055f) * std::pow(c, 1.f / 2.4f)) - 0.055f) * 255.f);
    }

    return new_color;
  }

  bool compare_colors(RGBA const& v1, RGBA const& v2)
  {
    return v1.r == v2.r && v1.g == v2.g && v1.b == v2.b && v1.a == v2.a;
  }

  bool comp_color_key(RGBA const& color)
  {
    return color.r || color.b || color.g || color.a;
  }
}
