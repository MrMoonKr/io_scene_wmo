#include "custom_data.hpp"
#include <cstring>
#include <cassert>

#include <BKE_mesh.h>
#include <DNA_mesh_types.h>
#include <DNA_meshdata_types.h>
#include <BKE_mesh_mapping.h>
#include <BKE_mesh_runtime.h>
#include <BLI_utildefines.h>

int wbs_kernel::bl_utils::mesh::WBS_CustomData_get_named_layer_index(const CustomData* data, int type, const char* name)
{
  for (int i = 0; i < data->totlayer; i++)
  {
    if (data->layers[i].type == type)
    {
      if (STREQ(data->layers[i].name, name))
      {
        return i;
      }
    }
  }

  return -1;
}

int wbs_kernel::bl_utils::mesh::WBS_CustomData_get_named_layer_index(const CustomData* data, const char* name)
{
    for (int i = 0; i < data->totlayer; i++)
    {
        if (STREQ(data->layers[i].name, name))
        {
            return i;
        }
    }
    return -1;
}

int wbs_kernel::bl_utils::mesh::WBS_CustomData_get_active_layer_index(const CustomData* data, int type)
{
  const int layer_index = data->typemap[type];
  return (layer_index != -1) ? layer_index + data->layers[layer_index].active : -1;
}


void* wbs_kernel::bl_utils::mesh::WBS_CustomData_get_layer_named(const struct CustomData* data, int type, const char* name)
{
  int layer_index = wbs_kernel::bl_utils::mesh::WBS_CustomData_get_named_layer_index(data, type, name);
  if (layer_index == -1)
  {
    return nullptr;
  }

  return data->layers[layer_index].data;
}

void* wbs_kernel::bl_utils::mesh::WBS_CustomData_get_layer(const CustomData* data, int type)
{
  /* get the layer index of the active layer of type */
  int layer_index = wbs_kernel::bl_utils::mesh::WBS_CustomData_get_active_layer_index(data, type);

  if (layer_index == -1)
  {
    return nullptr;
  }

  return data->layers[layer_index].data;
}

int wbs_kernel::bl_utils::mesh::WBS_CustomData_get_layer_index(const CustomData* data, int type)
{
  return data->typemap[type];
}

bool wbs_kernel::bl_utils::mesh::WBS_CustomData_has_layer(const CustomData* data, int type)
{
  return (wbs_kernel::bl_utils::mesh::WBS_CustomData_get_layer_index(data, type) != -1);
}

MDeformWeight* wbs_kernel::bl_utils::mesh::WBS_BKE_defvert_find_index(const MDeformVert* dvert, const int defgroup)
{
  if (dvert && defgroup >= 0)
  {
    MDeformWeight *dw = dvert->dw;
    unsigned int i;

    for (i = dvert->totweight; i != 0; i--, dw++)
    {
      if (dw->def_nr == defgroup)
      {
        return dw;
      }
    }
  }
  else
  {
    assert(false);
  }

  return nullptr;
}

template<>
MLoopCol* wbs_kernel::bl_utils::mesh::get_custom_data_layer_named<MLoopCol>(const CustomData* data, const std::string& name)
{
  return static_cast<MLoopCol*>(WBS_CustomData_get_layer_named(data, eCustomDataType::CD_PROP_BYTE_COLOR, name.c_str()));
}

template<>
MLoopUV* wbs_kernel::bl_utils::mesh::get_custom_data_layer_named<MLoopUV>(const CustomData* data, const std::string& name)
{
  return static_cast<MLoopUV*>(WBS_CustomData_get_layer_named(data,eCustomDataType::CD_MLOOPUV, name.c_str()));
}

template<>
MDeformVert* wbs_kernel::bl_utils::mesh::get_custom_data_layer_named<MDeformVert>(const CustomData* data, const std::string& name)
{
  return static_cast<MDeformVert*>(WBS_CustomData_get_layer_named(data,eCustomDataType::CD_MDEFORMVERT, name.c_str()));
}

int wbs_kernel::bl_utils::mesh::WBS_CustomData_get_layer_type(const CustomData* data, int index)
{
  assert(index >= 0 && "Requested type of non existing layer.");
  return data->layers[index].type;
}


