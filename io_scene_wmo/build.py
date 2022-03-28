#!/usr/bin/env python
import subprocess
import sys

PYTHON_PATH = sys.executable


def build_project():

    try:
        import Cython
    except ImportError:
        raise Exception("\nCython is required to build this project")

    try:
        from pip import main as pipmain
    except ImportError:
        try:
            from pip._internal import main as pipmain
        except ImportError:
            raise Exception("\npip is required to build this project")

    import os

    addon_root_path = os.path.realpath(os.path.dirname(os.path.abspath(__file__)).replace('\\', '/'))

    extension_dirs = (
        "wbs_kernel/",
    )

    print('\nBuilding C++ extensions.')

    for module_relpath in extension_dirs:
        try:
            os.chdir(os.path.join(addon_root_path, module_relpath))
            status = subprocess.call([PYTHON_PATH, "setup.py", 'build_clib', 'build_ext', '--inplace'])

            if status:
                print (f"\nProcess returned error code {status} while building module \"{module_relpath}\"")
                sys.exit(1)

        except PermissionError:
            raise PermissionError("\nThis build script may need to be called with admin (root) rights.")
            sys.exit(1)

        except RuntimeError:
            print ("\nUnknown error occured.")
            sys.exit(1)

    os.chdir(addon_root_path)

    status = subprocess.call([PYTHON_PATH, "pywowlib/build.py"])
    if status:
        print("\nError building pywowlib.")
        sys.exit(1)

    os.chdir(addon_root_path)

    print('\nInstalling third-party modules.')

    def install_requirements(f):
        for line in f.readlines():
            status = subprocess.call(['pip3', 'install', line, '-t', 'third_party', '--upgrade'])
            if status:
                print('\nError: failed installing module \"{}\". See pip error above.'.format(line))

    with open('requirements.txt') as f:
        install_requirements(f)

    with open('pywowlib/requirements.txt') as f:
        install_requirements(f)

    print('\nWBS building finished successfully.')


if __name__ == "__main__":
    build_project()
