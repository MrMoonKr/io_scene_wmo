import bpy
import os

# load custom icons
ui_icons = {}
pcoll = None

def init():
    global pcoll
    global ui_icons

    pcoll = bpy.utils.previews.new()
    icons_dir = os.path.join(os.path.dirname(__file__), "icons")

    for file in os.listdir(icons_dir):
        pcoll.load(os.path.splitext(file)[0].upper(), os.path.join(icons_dir, file), 'IMAGE', True)

    for name, icon_file in pcoll.items():
        ui_icons[name] = icon_file.icon_id


def unregister():
    global pcoll
    bpy.utils.previews.remove(pcoll)

    global ui_icons
    ui_icons = {}