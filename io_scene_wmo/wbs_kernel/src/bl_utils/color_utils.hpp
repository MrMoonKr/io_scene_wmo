#ifndef WBS_KERNEL_COLOR_UTILS_HPP
#define WBS_KERNEL_COLOR_UTILS_HPP

#include <cassert>

namespace wbs_kernel::bl_utils::color_utils
{
  struct RGBA
  {
    unsigned char r;
    unsigned char g;
    unsigned char b;
    unsigned char a;

    unsigned char& operator[](unsigned index)
    {
      assert(index <= 3);

      switch(index)
      {
        case 0:
          return r;
        case 1:
          return g;
        case 2:
          return b;
        case 3:
          return a;
        default:
          assert(false);
      }
    }

    unsigned char operator[](unsigned index) const
    {
      assert(index <= 3);

      switch(index)
      {
        case 0:
          return r;
        case 1:
          return g;
        case 2:
          return b;
        case 3:
          return a;
        default:
          assert(false);
      }
    }
  };

  RGBA SRGB_to_linear(RGBA const& color);
}

#endif //WBS_KERNEL_COLOR_UTILS_HPP
