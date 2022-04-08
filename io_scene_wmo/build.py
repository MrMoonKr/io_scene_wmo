#!/usr/bin/env python
import subprocess
import os
import sys
import time
import shutil
import argparse

from typing import Optional, Iterable

PYTHON_PATH = sys.executable


def print_error(*s: str):
    print("\033[91m {}\033[00m".format(' '.join(s)))


def print_succes(*s: str):
    print("\033[92m {}\033[00m".format(' '.join(s)))


def print_info(*s: str):
    print("\033[93m {}\033[00m".format(' '.join(s)))


def build_type_mismatch(debug: bool) -> bool:

    has_mismatch = False
    if os.path.exists("build/build.cache"):
        with open("build/build.cache", 'rb') as f:
            f.seek(0, 2)
            pos = f.tell()
            if pos:
                f.seek(0)
                cur_mode = b'\x00' if debug else b'\x01'
                old_mode = f.read(1)
                if old_mode != cur_mode:
                    print(old_mode)
                    has_mismatch = True
            else:
                has_mismatch = True
    else:
        has_mismatch = True

    with open("build/build.cache", 'wb') as f:
        f.write(b'\x00' if debug else b'\x01')

    return has_mismatch


def clean_build_data(ext_dirs: Iterable[str]):
    for ext_dir in ext_dirs:
        shutil.rmtree(os.path.join(ext_dir, "build"), ignore_errors=False, onerror=None)


def create_distribution(addon_root_path: str, dist_path: str):

    print_info(f'\nCreating WBS distribution in \"{dist_path}\" ...')
    os.makedirs(dist_path, exist_ok=True)

    final_dist_path = os.path.join(dist_path, 'io_scene_wmo')
    os.makedirs(final_dist_path, exist_ok=True)
    shutil.copytree(addon_root_path, final_dist_path, dirs_exist_ok=True)

    paths_to_remove = (
        "__pycache__",
        "build",
        "venv",
        "build.py",
        ".idea",
        ".vs",
        ".vscode",
        ".gitignore",
        "requirements.txt",
        "wbs_kernel/build",
        "wbs_kernel/cmake-build-debug",
        "wbs_kernel/cmake-build-release",
        "wbs_kernel/.idea",
        "wbs_kernel/.vs",
        "wbs_kernel/.vscode",
        "wbs_kernel/CmakeLists.txt",
        "wbs_kernel/setup.py",
        "wbs_kernel/src",
        "pywowlib/.git",
        "pywowlib/.gitignore",
        "pywowlib/.gitmodules",
        "pywowlib/.travis.yml",
        "pywowlib/build.py",
        "pywowlib/cmake.py",
        "pywowlib/requirements.txt",
        "pywowlib/__pycache__",
        "pywowlib/archives/casc/build",
        "pywowlib/archives/casc/CASCLib",
        "pywowlib/archives/casc/lib",
        "pywowlib/archives/casc/casc.cpp",
        "pywowlib/archives/casc/setup.py",
        "pywowlib/archives/casc/.git",
        "pywowlib/archives/casc/.gitignore",
        "pywowlib/archives/casc/.gitmodules",
        "pywowlib/archives/mpq/native/build",
        "pywowlib/archives/mpq/native/StormLib",
        "pywowlib/archives/mpq/native/python_wrapper.hpp",
        "pywowlib/archives/mpq/native/stormmodule.cc",
        "pywowlib/archives/mpq/native/stormmodule.h",
        "pywowlib/archives/mpq/native/setup.py",
        "pywowlib/blp/include",
        "pywowlib/blp/BLP2PNG/build",
        "pywowlib/blp/BLP2PNG/native",
        "pywowlib/blp/BLP2PNG/blp.cpp",
        "pywowlib/blp/BLP2PNG/setup.py",
        "pywowlib/blp/PNG2BLP/build",
        "pywowlib/blp/PNG2BLP/native",
        "pywowlib/blp/PNG2BLP/png2blp.cpp",
        "pywowlib/blp/PNG2BLP/setup.py",

    )

    for path in paths_to_remove:
        new_path = os.path.join(final_dist_path, path)
        if not os.path.exists(new_path):
            continue

        if os.path.isdir(new_path):
            shutil.rmtree(new_path, ignore_errors=True)
        else:
            os.remove(new_path)

    print_succes("\nSuccessfully created WBS distribution.")


def build_project(debug: bool, clean: bool, no_req: bool, dist_path: Optional[str]):

    start_time = time.time()

    print_info('\nBuilding WoW Blender Studio...')
    print('Detected build parameters:')
    print(f'Build type: {"Debug" if debug else "Release"}')
    print(f'Build mode: {"Clean" if clean else "Incremental"}')
    print(f'Python third-party modules: {"OFF" if no_req else "ON"}')

    do_distribute = bool(dist_path)

    try:
        import Cython
    except ImportError:
        print_error("\nCython is required to build this project")
        sys.exit(1)

    try:
        from pip import main as pipmain
    except ImportError:
        try:
            from pip._internal import main as pipmain
        except ImportError:
            print_error("\npip is required to build this project.")
            sys.exit(1)

    addon_root_path = os.path.realpath(os.path.dirname(os.path.abspath(__file__)).replace('\\', '/'))

    extension_dirs = (
        "wbs_kernel/",
    )

    os.chdir(addon_root_path)
    os.makedirs("build", exist_ok=True)

    # clean up build data if previous build type does not match with current, or if set manually with an option
    if build_type_mismatch(debug) or clean:
        clean = True
        clean_build_data(extension_dirs)

    print_info('\nBuilding C++ extensions...')

    for module_relpath in extension_dirs:
        try:
            os.chdir(os.path.join(addon_root_path, module_relpath))
            launch_args = [PYTHON_PATH, "setup.py", 'build_clib', 'build_ext', '--inplace']

            if debug:
                launch_args.append('--wbs_debug')

            status = subprocess.call(launch_args)

            if status:
                print_error(f"\nProcess returned error code {status} while building module \"{module_relpath}\"")
                sys.exit(1)

        except PermissionError:
            print_error("\nThis build script may need to be called with admin (root) rights.")
            sys.exit(1)

        except RuntimeError:
            print_error("\nUnknown error occurred.")
            sys.exit(1)

    # build pywowlib
    os.chdir(addon_root_path)
    launch_args = [PYTHON_PATH, "pywowlib/build.py"]

    if debug:
        launch_args.append('--debug')

    if clean:
        launch_args.append('--clean')

    status = subprocess.call(launch_args)
    if status:
        print_error("\nError building pywowlib.")
        sys.exit(1)

    # install required Python modules
    if not no_req:
        print_info('\nInstalling third-party Python modules...')

        def install_requirements(f):
            for line in f.readlines():
                status = subprocess.call([PYTHON_PATH, '-m', 'pip', 'install', line, '-t', 'third_party', '--upgrade'])
                if status:
                    print('\nError: failed installing module \"{}\". See pip error above.'.format(line))
                    sys.exit(1)

        with open('requirements.txt') as f:
            install_requirements(f)

        with open('pywowlib/requirements.txt') as f:
            install_requirements(f)

    else:
        print_info("\nWarning: Third-party Python modules will not be installed. (--noreq option)")

    print_succes('\nWBS building finished successfully.',
       "\nTotal build time: ", time.strftime("%M minutes %S seconds\a", time.gmtime(time.time() - start_time)))

    if do_distribute:
        create_distribution(addon_root_path, dist_path)


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Build WoW Blender Studio."
                                                 "\nMake sure your Python version matches the version of Python"
                                                 " inside the target Blender distribution."
                                                 "\n"
                                                 "\nRequired dependencies are:"
                                                 "\n    All:"
                                                 "\n    * pip (https://pip.pypa.io/en/stable/installation/)"
                                                 "\n    * Cython (pip install Cython)"
                                                 "\n    * CMake (commandline CMake is required, see: https://cmake.org"
                                                 "\n    * C++ compiler (MSVC for Windows, GCC/Clang for Linux/Mac)"
                                                 "\n"
                                                 "\n    Linux:"
                                                 "\n    * OpenGL (sudo apt install libglu1-mesa-dev freeglut3-dev)"
                                                 "\n    * Python headers (sudo apt install python3-dev)"
                                     , formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument('--dist', type=str, help='create a distribution of WBS in specified directory')
    parser.add_argument('--debug', action='store_true', help='compile WBS in debug mode')
    parser.add_argument('--clean', action='store_true', help='erase previous build files and recompile from scratch')
    parser.add_argument('--noreq', action='store_true', help='do not pull python modules from PyPi')
    args = parser.parse_args()

    build_project(args.debug, args.clean, args.noreq, args.dist)
