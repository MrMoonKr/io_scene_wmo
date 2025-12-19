# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

# <pep8-80 compliant>


bl_info = {
    "name": "WoW Blender Studio",
    "author": "Skarn",
    "version": (1, 1, 2),
    "blender": (3, 4, 0),
    "description": "Import-Export WoW M2-WMO",
    "category": "Import-Export"
}

import os
import sys
import traceback
import bpy.utils.previews
from bpy.props import StringProperty
from . import icons
from . import auto_load

PACKAGE_NAME = __package__

# include custom lib vendoring dir
parent_dir = os.path.abspath(os.path.dirname(__file__))
vendor_dir = os.path.join(parent_dir, 'third_party')

sys.path.append(vendor_dir)

def register():
    auto_load.init()

    try:
        icons.init()
        auto_load.register()
        print("Registered WoW Blender Studio")

    except:
        traceback.print_exc()

def unregister():
    try:
        icons.unregister()
        auto_load.unregister()
        print("Unregistered WoW Blender Studio")

    except:
        traceback.print_exc()

if __name__ == "__main__":
    register()
