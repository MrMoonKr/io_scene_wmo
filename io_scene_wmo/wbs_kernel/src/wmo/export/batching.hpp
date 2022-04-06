#ifndef WBS_KERNEL_BATCHING_HPP
#define WBS_KERNEL_BATCHING_HPP

#include <cstdint>

extern "C"
{
#include <DNA_mesh_types.h>
#include <BKE_customdata.h>
};

namespace wbs_kernel
{
    class BatchCreator
    {
    public:
        BatchCreator(std::uintptr_t mesh_pointer);

    private:
        Mesh* _bl_mesh;
    };
}

#endif //WBS_KERNEL_BATCHING_HPP


