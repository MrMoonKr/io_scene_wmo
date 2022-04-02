import os
import platform
from typing import List
from distutils.core import setup, Extension
from Cython.Build import cythonize


def main():
    if platform.system() != 'Darwin':
        extra_compile_args = ['-O3']
        extra_link_args = []

    else:
        extra_compile_args = ['-g3', '-O0', '-stdlib=libc++']
        extra_link_args = ['-stdlib=libc++']

    extra_compile_args.extend(['-std=c++17'])

    glew = ('glew', {'sources': ["src/extern/glew/src/glew.c"], 'include_dirs': ["src/extern/glew/include/"]})

    setup(
        name='WoW Blender Studio Kernel',
        ext_modules=cythonize([Extension(
            "wbs_kernel",
            sources=[
                "src/wbs_kernel.pyx",
                "src/render/m2_drawing_batch.cpp",
                "src/render/m2_drawing_mesh.cpp",
                "src/render/wmo_drawing_mesh.cpp",
                "src/render/wmo_drawing_batch.cpp",
                "src/render/opengl_utils.cpp"
            ],

            include_dirs=[
                "src/",
                "src/render/",
                "src/extern/glew/include/GL/",
                "src/extern/glm/",
                "src/extern/",
                "src/bl_src/source/blender/blenkernel/",
                "src/bl_src/source/blender/blenlib/",
                "src/bl_src/source/blender/makesdna/",
                "src/bl_src/source/blender/makesrna/",
                ],
            language="c++",
            extra_compile_args=extra_compile_args,
            extra_link_args=extra_link_args,
            libraries=['opengl32'] if platform.system() == 'Windows' else []
        )]
        ),
        libraries=[glew],
        requires=['Cython'])


if __name__ == '__main__':
    main()
