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
}




