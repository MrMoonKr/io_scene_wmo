#ifndef WBS_KERNEL_CUSTOM_DATA_HPP
#define WBS_KERNEL_CUSTOM_DATA_HPP

#include <string>

struct CustomData;
struct MDeformWeight;
struct MDeformVert;


namespace wbs_kernel::bl_utils::mesh
{
  // Functions with WBS_ prefix are direct copies or adjusted copies of Blender's internal functions.
  // If no longer works with recent Blender, look it up in Blender's code without the prefix.
  // Last updated to Blender 3.10. Please keep this note in sync with your changes.

  int WBS_CustomData_get_named_layer_index(const CustomData* data, int type, const char* name);

  void* WBS_CustomData_get_layer_named(const struct CustomData* data, int type, const char* name);

  int WBS_CustomData_get_active_layer_index(const CustomData* data, int type);

  int WBS_CustomData_get_layer_index(const CustomData* data, int type);

  bool WBS_CustomData_has_layer(const CustomData* data, int type);

  // Returns deform weight if vertex group is asigned to that vertex, nullptr if not
  MDeformWeight* WBS_BKE_defvert_find_index(const MDeformVert* dvert, const int defgroup);

  void* WBS_CustomData_get_layer(const CustomData* data, int type);

  template<typename T>
  T* get_custom_data_layer_named(const CustomData* data, std::string const& name);




}

#endif //WBS_KERNEL_CUSTOM_DATA_HPP
